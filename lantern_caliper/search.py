# -*- coding: utf-8 -*-
"""全文（FTS）、切片、向量嵌入与语义检索。"""

import json
import math
import os
import re
import sqlite3
import time
import binascii

def _ensure_fts(con):
    """建 FTS5 虚表（trigram 分词，支持中文子串）并挂同步触发器；存量条目一次灌入。
    注意：trigram 分词器不支持 FTS5 的 'delete' 特殊命令（内容稍长即 SQL logic error），
    触发器里一律用「按 rowid 普通 DELETE」代替，实测可用。"""
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS items_fts "
                "USING fts5(title, content, tokenize='trigram')")
    # 先清掉旧触发器（若有），再按 rowid 删除方式重建
    con.execute("DROP TRIGGER IF EXISTS items_fts_ai")
    con.execute("DROP TRIGGER IF EXISTS items_fts_ad")
    con.execute("DROP TRIGGER IF EXISTS items_fts_au")
    con.execute("""
    CREATE TRIGGER items_fts_ai AFTER INSERT ON items BEGIN
      INSERT INTO items_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
    END""")
    con.execute("""
    CREATE TRIGGER items_fts_ad AFTER DELETE ON items BEGIN
      DELETE FROM items_fts WHERE rowid = old.id;
    END""")
    con.execute("""
    CREATE TRIGGER items_fts_au AFTER UPDATE OF title, content ON items BEGIN
      DELETE FROM items_fts WHERE rowid = old.id;
      INSERT INTO items_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
    END""")
    n_it = con.execute("SELECT count(*) FROM items").fetchone()[0]
    n_fts = con.execute("SELECT count(*) FROM items_fts").fetchone()[0]
    if n_fts != n_it:
        con.execute("DELETE FROM items_fts")
        con.execute("INSERT INTO items_fts(rowid,title,content) SELECT id,title,content FROM items")

def _ensure_chunks(con):
    """片段索引表 + FTS5（trigram 中文子串）+ 同步触发器。

    对应 RAG 文章的「文档切分 + 重叠窗口」：把每篇正文切成带重叠的语义片段，
    单独建全文/向量索引，让「查找」能定位到具体句子，而不只是整篇命中。
    条目层仍保持整篇（保住「游标=论证严密度」整篇语义——这是我们有意不做
    整篇切块的原因），切块只发生在检索定位层。
    """
    con.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        text TEXT NOT NULL,
        vec TEXT,
        created_at REAL NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_item ON chunks(item_id)")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
                "USING fts5(text, content='chunks', content_rowid='id', tokenize='trigram')")
    con.execute("DROP TRIGGER IF EXISTS chunks_fts_ai")
    con.execute("DROP TRIGGER IF EXISTS chunks_fts_ad")
    con.execute("DROP TRIGGER IF EXISTS chunks_fts_au")
    con.execute("""
    CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN
      INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
    END""")
    con.execute("""
    CREATE TRIGGER chunks_fts_ad AFTER DELETE ON chunks BEGIN
      DELETE FROM chunks_fts WHERE rowid = old.id;
    END""")
    con.execute("""
    CREATE TRIGGER chunks_fts_au AFTER UPDATE OF text ON chunks BEGIN
      DELETE FROM chunks_fts WHERE rowid = old.id;
      INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
    END""")
    n_ch = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    n_fts = con.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    if n_fts != n_ch:
        con.execute("DELETE FROM chunks_fts")
        con.execute("INSERT INTO chunks_fts(rowid,text) SELECT id,text FROM chunks")

def _tail_sentences(text, budget):
    """从一段文本尾部取「完整句子」作为重叠区，字符预算内尽量多带整句。

    不按字符硬切，避免把句子拦腰截断导致语义断层。
    """
    parts = [s.strip() for s in re.split(r'(?<=[。！？；!?;\n])', text) if s.strip()]
    taken, total = [], 0
    for p in reversed(parts):
        if total + len(p) <= budget:
            taken.insert(0, p)
            total += len(p)
        else:
            break
    return taken

def _chunk_text(content, target=320, overlap=120):
    """语义切分 + 整句重叠窗口（RAG 文章核心推荐方案，按你的要求改为整句重叠）。

    · 按句末标点切句，绝不固定长度「拦腰截断完整句子」——每块都是完整句子；
    · 累积到 ~target 字符切一块，下一块以本块末尾的整句（预算 overlap 内）起头，
      相邻两块共享 1~2 个完整句子，可互相参照对照，大模型对单块语义理解偏差更小；
      关键信息即便压在边界，也会在两块里各留一份完整句子，不会卡在中间被截断。

    返回片段文本列表（已去除纯空白片段）。
    """
    content = (content or "").strip()
    if not content:
        return []
    # 按句末标点（含换行）切句
    sents = [s.strip() for s in re.split(r'(?<=[。！？；!?;\n])', content) if s.strip()]
    if not sents:
        return [content]
    chunks, i, n = [], 0, len(sents)
    while i < n:
        buf = sents[i]
        j = i + 1
        while j < n and len(buf) + len(sents[j]) <= target:
            buf += sents[j]
            j += 1
        chunks.append(buf)
        # 下一块以本块末尾的整句起头（重叠），既不截断句子又能相互对照
        ov = _tail_sentences(buf, overlap)
        i = max(i + 1, j - len(ov))
    return [c for c in chunks if c.strip()]

def _write_chunks(con, item_id, content):
    """重算并写入某条目的片段索引（同步、本地哈希向量，零网络）。
    真实 embedding 接入后会由 rebuild_chunk_vecs / _refine 升级为语义向量。"""
    texts = _chunk_text(content)
    con.execute("DELETE FROM chunks WHERE item_id=?", (item_id,))
    now = time.time()
    for seq, t in enumerate(texts):
        vec = json.dumps(local_embed(t))
        con.execute(
            "INSERT INTO chunks(item_id,seq,text,vec,created_at) VALUES(?,?,?,?,?)",
            (item_id, seq, t, vec, now))

def semantic_chunk_search(query, k=8):
    """按向量余弦在片段级找最相关片段，返回 [{item_id,chunk_id,text,score}]。"""
    q = embed_text(query)
    con = connect()
    rows = con.execute("SELECT id,item_id,text,vec FROM chunks").fetchall()
    con.close()
    scored = []
    for r in rows:
        v = r["vec"]
        if not v:
            continue
        try:
            vec = json.loads(v)
        except Exception:                              # noqa: BLE001
            continue
        if len(vec) != len(q):
            continue
        dot = sum(a * b for a, b in zip(q, vec))
        scored.append((dot, r["item_id"], r["id"], r["text"]))
    scored.sort(key=lambda x: -x[0])
    return [{"item_id": i, "chunk_id": c, "text": t, "score": round(s, 3)}
            for s, i, c, t in scored[:k]]

def rebuild_chunk_vecs():
    """用 embed_text 为全部片段重建向量（内容哈希缓存，真实 embedding 接入自动升级）。
    对应 RAG 文章的「一键重索引」——换模型后碎片向量随之刷新。"""
    con = connect()
    rows = con.execute("SELECT id,text FROM chunks").fetchall()
    done = failed = 0
    for r in rows:
        try:
            v = embed_text(r["text"])
            if not v:
                failed += 1
                continue
            con.execute("UPDATE chunks SET vec=? WHERE id=?",
                        (json.dumps(v), r["id"]))
            con.commit()                              # 每片即提交：不跨模型调用持锁
            done += 1
        except Exception:                              # noqa: BLE001
            failed += 1
    con.close()
    return {"ok": True, "done": done, "failed": failed}


def esc(s):
    """HTML 转义：防止正文/片段里的 < > & 破坏前端渲染或被注入。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def chunk_fts_search(text, k=12):
    """片段级 FTS5 全文检索：trigram 子串匹配 + bm25 排序，返回命中片段 id 列表。"""
    q = (text or "").strip()
    if len(q) < 3:
        return []
    query = '"' + q.replace('"', '""') + '"'
    con = connect()
    try:
        rows = con.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?", (query, k)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    return [r["rowid"] for r in rows]

def fts_search(text, k=8):
    """FTS5 全文检索：trigram 子串匹配 + bm25 排序，返回命中的条目 id 列表。
    trigram 对不足 3 字符的查询不产生命中（中文两字词走 token 评分兜底）。"""
    q = (text or "").strip()
    if len(q) < 3:
        return []
    query = '"' + q.replace('"', '""') + '"'
    con = connect()
    try:
        rows = con.execute(
            "SELECT rowid FROM items_fts WHERE items_fts MATCH ? ORDER BY bm25(items_fts) LIMIT ?",
            (query, k)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    return [r["rowid"] for r in rows]

def rebuild_embeddings(force=False):
    """用 embed_text（模型 embedding 优先、本地哈希兜底）为全部条目重建向量。
    内容哈希缓存由 llm.embed 负责，重复重建不重复计费。
    注意：embed_text 可能调慢模型，每篇写后立即提交，避免跨模型调用持有写锁。
    force=False 时跳过已有向量的条目（断点续传：只补缺失项，不重复计算已有项）；
    force=True 时全量重算（例如切换了底层 embedding 模型后需要整体重建）。"""
    items = list_items()["items"]
    con = connect()
    existing = set()
    if not force:
        try:
            existing = {r["item_id"] for r in con.execute("SELECT item_id FROM embeddings")}
        except Exception:                              # noqa: BLE001
            existing = set()
    done = skipped = failed = 0
    dim = None
    for it in items:
        if it["id"] in existing:
            skipped += 1
            continue
        text = ((it.get("title") or "") + "\n" + (it.get("content") or ""))[:2000]
        try:
            v = embed_text(text)
            if not v:
                failed += 1
                continue
            dim = len(v)
            _set_embedding(con, it["id"], v)
            con.commit()                            # 每篇即提交：不跨模型调用持锁
            done += 1
        except Exception:                              # noqa: BLE001
            failed += 1
    # 重建向量后，旧语义链（尤其换模型 / 维度变化时）可能早已失效 → 持续回算清理，
    # 避免"链接写一次定终身"。仅当真动了向量（force 或本次有新增）时才扫，省去无谓开销。
    pruned = 0
    if force or done > 0:
        try:
            p = prune_stale_semantic_links()
            pruned = (p or {}).get("pruned", 0)
        except Exception:                              # noqa: BLE001
            pruned = 0
    con.close()
    return {"ok": True, "done": done, "skipped": skipped, "failed": failed,
            "dim": dim, "forced": force, "pruned_semantic": pruned}

def tokenize(text):
    """切成可比较的最小语义单元：英文词 / 数字 / 单个汉字。中文按字切，靠二元组补语序。"""
    return _TOKEN.findall((text or "").lower())

def local_embed(text, dim=256):
    """哈希型向量：词与二元组映射到定长空间，L2 归一化；离线、无词汇漂移、跨条目可比。"""
    vec = [0.0] * dim
    toks = tokenize(text)
    for t in toks:
        h = binascii.crc32(t.encode("utf-8")) & 0xFFFFFFFF
        vec[h % dim] += 1.0
    for i in range(len(toks) - 1):
        h = binascii.crc32((toks[i] + toks[i + 1]).encode("utf-8")) & 0xFFFFFFFF
        vec[h % dim] += 0.6
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]

_LOCAL_ST = None  # 本地高维语义模型缓存（sentence-transformers）
# 模型已离线下载至项目根 .models/ 目录；本沙箱无法访问 huggingface.co，故强制离线，
# 任何 hub 访问都直接失败而非卡网络。search.py 在包内，项目根为 __file__ 上溯两级。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".models", "bge-small-zh-v1.5")

def _local_st_model():
    """懒加载本地高维 embedding 模型（BAAI/bge-small-zh-v1.5，384 维，离线、区分度高）。
    从项目内 .models 目录加载（已离线下载，零网络依赖）；加载失败则缓存 False，
    回退远程/哈希。"""
    global _LOCAL_ST
    if _LOCAL_ST is None:
        try:
            from sentence_transformers import SentenceTransformer
            _LOCAL_ST = SentenceTransformer(_LOCAL_MODEL_DIR)
        except Exception as e:                        # noqa: BLE001
            _LOCAL_ST = False
            print(f"[embed] 本地高维模型不可用，将回退远程/哈希：{e}")
    return _LOCAL_ST


def embed_text(text):
    """嵌入优先级：① 本地高维语义模型（区分度有保证、离线）；② 远程 embed API；③ 本地哈希兜底。
    旧逻辑只用远程 64 维 API（区分度过低，导致跨领域误判极高相似、信号守卫降级）；
    本地高维模型上线后，语义链（近似重复提醒 / 语义软链 / 语义检索）恢复可靠。"""
    m = _local_st_model()
    if m:
        try:
            vec = m.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception:                             # noqa: BLE001
            pass
    if LLM_OK and not _llm.breaker_state()["open"]:
        try:
            v = _llm.embed(text, timeout=20)
            if v:
                return v
        except Exception:                             # noqa: BLE001
            pass
    return local_embed(text)

def _set_embedding(con, item_id, vec):
    con.execute("INSERT OR REPLACE INTO embeddings(item_id,vec) VALUES(?,?)",
                (item_id, json.dumps(vec)))

def semantic_search(text, k=5):
    """按向量余弦相似度找最相关内容。"""
    q = embed_text(text)
    items = list_items()["items"]
    con = connect()
    vecs = {r["item_id"]: json.loads(r["vec"])
            for r in con.execute("SELECT item_id,vec FROM embeddings")}
    con.close()
    scored = []
    for it in items:
        v = vecs.get(it["id"])
        if not v or len(v) != len(q):          # 维度不一致（本地向量 vs 真实 embedding）则跳过
            continue
        dot = sum(a * b for a, b in zip(q, v))
        scored.append((dot, it))
    scored.sort(key=lambda x: -x[0])
    return [dict(it, score=round(s, 3)) for s, it in scored[:k]]


def multidim_search(text="", k=10, band=None, main_min=None, main_max=None,
                    vernier_min=None, vernier_max=None, tags=None, offset_max=None,
                    grouped=False):
    """多维联合检索：把"语义相似度 + 主尺接近度 + 游标接近度 + 领域带匹配 + 标签命中"
    合成一个综合分，一次返回跨轴结果，而非逐轴拼装。

    维度参数（均可选，留空表示不约束该轴）：
      text       语义查询（走 embed_text，真模型优先）；为空则纯按维度过滤
      band       领域带名（如 '自然科学'），只返回该领域
      main_min/max  主尺位置区间 [main_min, main_max]
      vernier_min/max 游标深度区间 [vernier_min, vernier_max]
      tags       标签子集（逗号分隔），命中任一即加分
      offset_max 逻辑偏差上限，只返回 |offset| <= offset_max 的条目

    综合分 = 0.5*语义(归一) + 0.2*主尺接近 + 0.15*游标接近 + 0.1*领域匹配 + 0.05*标签命中
    （无 text 时语义权重 redistributes 到维度接近度）。"""
    items = list_items()["items"]
    # 语义分：拿全量余弦，归一化到 0-1
    sem = {}
    if text:
        for r in semantic_search(text, k=len(items) or 1):
            sem[r["id"]] = r.get("score", 0.0)
        if sem:
            lo, hi = min(sem.values()), max(sem.values())
            span = (hi - lo) or 1.0
            sem = {i: (s - lo) / span for i, s in sem.items()}
    tag_set = set(t.strip() for t in (tags or "").split(",") if t.strip())

    out = []
    for it in items:
        # 维度硬过滤
        if band and it.get("disp_band") != band:
            continue
        mp = it.get("main_pos")
        if main_min is not None and (mp is None or mp < main_min):
            continue
        if main_max is not None and (mp is None or mp > main_max):
            continue
        vn = it.get("vernier")
        if vernier_min is not None and (vn is None or vn < vernier_min):
            continue
        if vernier_max is not None and (vn is None or vn > vernier_max):
            continue
        if offset_max is not None:
            off = it.get("offset") or 0
            if abs(off) > offset_max:
                continue
        # 接近度（相对区间中点的归一得分）
        main_close = 1.0 - min(abs((mp or 50) - ((main_min or 0) + (main_max or 100)) / 2), 50) / 50 if (main_min is not None or main_max is not None) else 0.0
        vern_close = 1.0 - min(abs((vn or 50) - ((vernier_min or 0) + (vernier_max or 100)) / 2), 50) / 50 if (vernier_min is not None or vernier_max is not None) else 0.0
        band_hit = 1.0 if (band and it.get("disp_band") == band) else 0.0
        tag_hit = 0.0
        if tag_set:
            it_tags = set(t.strip() for t in (it.get("tags") or "").split(",") if t.strip())
            tag_hit = 1.0 if (it_tags & tag_set) else 0.0
        s_sem = sem.get(it["id"], 0.0)
        if text:
            score = 0.5 * s_sem + 0.2 * main_close + 0.15 * vern_close + 0.1 * band_hit + 0.05 * tag_hit
        else:
            # 无语义查询：权重重分配到维度接近度
            w_sum = (0.2 + 0.15 + 0.1 + 0.05)
            score = (0.2 * main_close + 0.15 * vern_close + 0.1 * band_hit + 0.05 * tag_hit) / w_sum if w_sum else 0.0
        out.append(dict(it, multidim_score=round(score, 4),
                        semantic_score=round(s_sem, 4),
                        main_close=round(main_close, 3),
                        vernier_close=round(vern_close, 3),
                        band_hit=band_hit, tag_hit=tag_hit))
    out.sort(key=lambda x: -x["multidim_score"])
    out = out[:k]
    # 非线性索引终态：按主题轴（disp_band）聚合，组间按组内最高分降序，
    # 组内保持综合分序。时间线（条目顺序）降级为组内细节，主题轴升为主键。
    if grouped:
        buckets = {}
        for it in out:
            b = it.get("disp_band") or "未分类"
            buckets.setdefault(b, []).append(it)
        groups = []
        for b, items in buckets.items():
            top = max(x["multidim_score"] for x in items)
            groups.append({
                "band": b,
                "count": len(items),
                "top_score": round(top, 4),
                "items": items,
            })
        groups.sort(key=lambda g: -g["top_score"])
        return {"groups": groups, "total": len(out)}
    return out

