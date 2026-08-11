#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 —— 知识库核心（检索 + 入库 + 闭环）
====================================================================
在 lantern_caliper 双尺引擎之上，提供「可被任何 agent 调用」的知识库能力：

  · 入库即定位：主尺=学科领域，游标=逻辑演绎深度，并自动跑阴阳闭环
  · 文本检索：离线评分（标题 +2 / 正文 +1 / 多词 +0.5）+ <mark> 高亮
  · 坐标检索：按双尺度位置找最近邻；或按「领域带 + 演绎深度区间」过滤
  · 候选跨学科边：知识图谱的发现结果（logic-isomorphism / under-formalized）
  · 单文本定位：只分类不入库，供 agent 判断「这段知识属于哪」

设计原则：本文件只定义【纯函数式 API】与【工具元数据 TOOLS】。
REST（server.py）与 MCP（mcp_server.py）两套接口共用同一实现，
保证「任何 agent 无论走 HTTP 还是 MCP，拿到的能力完全一致」。

全部仅依赖 Python 标准库 + 兄弟模块（store / llm）。
"""

import json
import math
import os
import re
import time

import lantern_caliper as store

_SPLIT = re.compile(r"[\s，。；、,.;!?！？：:（）()\[\]【】\n\t]+")


# ============================================================== 入库
# ============================================================== 分类链对齐（KB 本职：数据一致性）
# 系统有三条分类链，必须在其重叠处保持一致，否则「数据驱动定轴」会失真：
#   1) axis_domain —— 条目级学科标签（自由文本，本应受控）
#   2) bands       —— 4 主干领域带（人文/社科/自科/形式科学），由内容在主尺上的位置派生
#   3) axes 表     —— 14 域 × 维度的静态分类法，是 Skill 提议透镜的词表
# 对齐策略：axis_domain 受控为 axes 表的 domain 词表（单点真相）；并提供
# domain → band 的规范映射，让任何受控学科域都能一致地落到 4 大带。
_AXIS_DOMAINS_CACHE = None


def axis_domains():
    """受控学科域词表，动态取自 axes 表（与 axes.domains 列一致）。"""
    global _AXIS_DOMAINS_CACHE
    if _AXIS_DOMAINS_CACHE is None:
        _AXIS_DOMAINS_CACHE = list(axes().get("domains") or [])
    return _AXIS_DOMAINS_CACHE


# 学科域 → 4 主干领域带。单点真相是 schema.json 的 domain_registry（经
# store._DOMAIN_REGISTRY 加载），此处仅做派生，杜绝与 store 双份硬编码。
# 注：「时间」在 axes 表里实为维度而非学科域，domain_registry 不含它，故不在此。
DOMAIN_TO_BAND = {d: reg["band"] for d, reg in store._DOMAIN_REGISTRY.items()}

# 受控学科域词表（静态、永远来自 schema domain_registry）。作为 axis_domain 归一化
# 的真相源——axes 表的 domains 是 Skill 提议的透镜词表（动态、可能为空），不应作为
# 学科域判定的依据，否则空库 / seed 演示库会把所有合法学科域都归一化为 None。
CONTROLLED_DOMAINS = set(store._DOMAIN_REGISTRY.keys())




def domain_typical_vernier(domain):
    """受控学科域的带内典型游标；非受控域返回 None（调用方回退带级）。"""
    return store.domain_typical_vernier(domain)


def domain_intra_order(domain):
    """受控学科域在所属带内的递增序（仅视角差异呈现，不代表优劣）。"""
    return store.domain_intra_order(domain)


def normalize_axis_domain(value):
    """把自由文本学科标签收敛到受控学科域词表（schema domain_registry，静态 13 域）；
    不在词表内则返回 None（不污染存储）。

    注意：受控集取自静态 domain_registry，而非 axis_domains()（后者来自 axes 表，
    是 Skill 提议的透镜词表，动态且可能为空）。以 axes 表为真相源会导致空库 / seed
    演示库的 axis_domain 全部归一化为 None。"""
    if not value:
        return None
    v = str(value).strip()
    return v if v in CONTROLLED_DOMAINS else None


def add_knowledge(title, content, run_closure=True, axis_domain=None):
    """摄入一条知识：自动双尺定位 + 生成候选边（+ 碰撞时自动闭环一次）。
    axis_domain：可选更细的学科方向标签，必须是受控学科域（见 axis_domains()），
    否则被归一化为 None，避免自由文本污染存储。"""
    if not content or not content.strip():
        return {"ok": False, "msg": "内容不能为空"}
    axis_domain = normalize_axis_domain(axis_domain)
    title = (title or "").strip() or content[:20]
    item = store.add_item(title, content, axis_domain)
    edges = []
    # llm 模式下候选边/闭环交给后台补算（store._refine），避免阻塞保存响应；
    # 启发式模式则是本地同步、极快，直接在此连边。
    con = store.connect()
    mode = store.get_mode(con)
    con.close()
    if mode != "llm":
        gen = store.gen_edge(item["id"])
        if gen.get("ok"):
            edges.append(gen)
        # 碰撞即自动校准一次（阴修订主尺），闭环收敛后重取条目
        if run_closure and item.get("collision"):
            store.calibrate(item["id"])
            item = store.get_item(item["id"]) or item
    return {"ok": True, "item": item, "edges": edges}


# ============================================================== 文本检索
def _tokens(q):
    q = (q or "").strip()
    toks = [t for t in _SPLIT.split(q) if t]
    return q, toks


def _snippet(content, toks, phrase, width=90):
    pos = len(content)
    for t in toks + [phrase]:
        if t and t in content:
            pos = min(pos, content.find(t))
    start = max(0, pos - 24)
    end = min(len(content), start + width)
    seg = content[start:end]
    seg = _highlight(seg, phrase or " ".join(toks))
    if start > 0:
        seg = "…" + seg
    if end < len(content):
        seg = seg + "…"
    return seg


def query(text, top_k=5):
    """
    按自由文本检索知识库（离线评分，无需 embedding）。
    评分：短语命中标题 +2、正文 +1/次(封顶5)；分词命中标题 +2、正文 +1；多词再 +0.5。
    返回按相关性降序，并附 <mark> 高亮片段。
    """
    q, toks = _tokens(text)
    if not q:
        return {"query": text, "results": []}
    items = store.list_items()["items"]
    fts_rank = {iid: i + 1 for i, iid in enumerate(store.fts_search(text, top_k * 4))}
    scored = []
    for it in items:
        title = it.get("title") or ""
        content = it.get("content") or ""
        score = 0.0
        if q in title:
            score += 2
        if q in content:
            score += min(content.count(q), 5)
        hit_tok = 0
        for t in toks:
            if not t:
                continue
            if t in title:
                score += 2
            if t in content:
                score += 1
                hit_tok += 1
        if hit_tok > 1:
            score += 0.5  # 多词加成
        fbi = fts_rank.get(it["id"])
        if fbi:
            score += 3.0 if fbi == 1 else 2.0   # FTS5(bm25) 头部命中加权
        if score > 0:
            snippet = _snippet(content, toks, q)
            scored.append({**it, "score": round(score, 2), "snippet": snippet})
    scored.sort(key=lambda x: (-x["score"], x["id"]))
    return {"query": text, "results": scored[:top_k]}


# ============================================================== 混合检索管线（RAG 对齐）
def retrieve(query, filters=None, top_k=10):
    """统一检索管线：把「关键词召回 + 语义召回 + 排名融合 + 元数据过滤」串成一条流水线。

    对应 RAG 文章的检索阶段：
    · Stage1 关键词召回：FTS5(bm25) 取候选（中文子串友好）。
    · Stage2 语义召回：store.semantic_search（哈希向量余弦；真实 embedding 接入后
      这里零改动自动升级为语义距离——存的是 embed_text 输出，查的也是）。
    · Stage3 倒数排名融合(RRF)：两套排名融合，避免单信号偏科，比简单加权更稳。
    · Stage4 元数据过滤：领域/标签/是否异常——企业级检索的刚需。
    返回带「命中信号」的结果，前端/agent 能知道这条是靠关键词还是靠语义命中的。
    """
    filters = filters or {}
    items = store.list_items()["items"]
    fts_ids = store.fts_search(query, top_k * 4)
    fts_rank = {iid: i + 1 for i, iid in enumerate(fts_ids)}
    sem = store.semantic_search(query, top_k * 4)
    sem_rank = {d["id"]: i + 1 for i, d in enumerate(sem)}
    K = 60  # RRF 常数
    merged = {}
    for it in items:
        iid = it["id"]
        sig = []
        rrf = 0.0
        if iid in fts_rank:
            rrf += 1.0 / (K + fts_rank[iid]); sig.append("fts")
        if iid in sem_rank:
            rrf += 1.0 / (K + sem_rank[iid]); sig.append("sem")
        if not sig:
            continue
        # Stage4 元数据过滤
        if filters.get("band") and it["band"] != filters["band"]:
            continue
        if filters.get("tag") and filters["tag"] not in (it.get("tags") or ""):
            continue
        if filters.get("collision") is not None and it["collision"] != filters["collision"]:
            continue
        merged[iid] = {"item": it, "rrf": round(rrf, 4), "signals": sig}
    ranked = sorted(merged.values(), key=lambda x: -x["rrf"])
    return {"query": query, "count": len(ranked),
            "results": [{"id": m["item"]["id"], "title": m["item"]["title"],
                         "band": m["item"]["band"], "signals": m["signals"],
                         "rrf": m["rrf"], "summary": m["item"].get("summary", "")}
                        for m in ranked[:top_k]]}


def _highlight(text, query):
    """把查询词在片段原文里标红（<mark>）。中文按词/短串命中即可。"""
    q = (query or "").strip()
    safe = store.esc if hasattr(store, "esc") else (lambda s: s)
    if not q:
        return safe(text)
    terms = [t for t in re.split(r'[\s，。、；：！？,.!?;:]+', q) if t]
    if not terms:
        terms = [q]
    out = store.esc(text)
    for t in sorted(set(terms), key=len, reverse=True):
        lt = store.esc(t)
        if lt:
            out = out.replace(lt, f'<mark>{lt}</mark>')
    return out


def fragments(query, filters=None, top_k=8):
    """片段级检索（对应 RAG 文章的「语义切分 + 重叠窗口」检索定位层）。

    条目层仍保持整篇（保住「游标=论证严密度」语义），这里额外在片段层做：
    · Stage1 关键词召回：chunks_fts(trigram) 取候选片段；
    · Stage2 语义召回：store.semantic_chunk_search（哈希向量；真实 embedding 接入后
      由 rebuild_chunk_vecs 升级为语义距离，零改动）；
    · Stage3 RRF 融合两套排名；
    · Stage4 元数据过滤（领域/是否异常）+ 片段高亮，直接定位到具体句子。
    返回带「命中信号」的片段，每条都带所属条目标题，前端可一键跳去阅读整篇。
    """
    filters = filters or {}
    items = store.list_items()["items"]
    id2item = {it["id"]: it for it in items}
    # Stage1 关键词召回（片段级）
    fts_ids = store.chunk_fts_search(query, top_k * 6)
    fts_rank = {cid: i + 1 for i, cid in enumerate(fts_ids)}
    # Stage2 语义召回（片段级）
    sem = store.semantic_chunk_search(query, top_k * 6)
    sem_rank = {d["chunk_id"]: i + 1 for i, d in enumerate(sem)}
    sem_text = {d["chunk_id"]: d["text"] for d in sem}
    K = 60
    merged = {}
    all_ids = set(fts_rank) | set(sem_rank)
    if not all_ids:
        return {"query": query, "count": 0, "results": []}
    # 取片段文本：优先语义返回的，否则查库
    con = store.connect()
    try:
        rows = {r["id"]: r for r in con.execute(
            "SELECT id,item_id,seq,text FROM chunks WHERE id IN (%s)"
            % ",".join("?" * len(all_ids)), list(all_ids)).fetchall()}
    finally:
        con.close()
    for cid in all_ids:
        r = rows.get(cid)
        if not r:
            continue
        iid = r["item_id"]
        it = id2item.get(iid)
        if not it:
            continue
        # Stage4 元数据过滤
        if filters.get("band") and it["band"] != filters["band"]:
            continue
        if filters.get("collision") is not None and it["collision"] != filters["collision"]:
            continue
        sig, rrf = [], 0.0
        if cid in fts_rank:
            rrf += 1.0 / (K + fts_rank[cid]); sig.append("fts")
        if cid in sem_rank:
            rrf += 1.0 / (K + sem_rank[cid]); sig.append("sem")
        text = r["text"] or sem_text.get(cid, "")
        merged[cid] = {
            "item_id": iid, "title": it["title"], "band": it["band"],
            "chunk_seq": r["seq"], "text": text,
            "snippet": _highlight(text, query), "signals": sig,
            "rrf": round(rrf, 4),
        }
    ranked = sorted(merged.values(), key=lambda x: -x["rrf"])
    return {"query": query, "count": len(ranked),
            "results": ranked[:top_k]}


def health():
    """知识库健康快照（对应 RAG 文章的「运维迭代 / 效果监控」）。

    当前无需定时任务即可随时观测：条目量、领域分布、向量覆盖、候选边状态、
    异常(碰撞)数、最近一次模型补算时间、当前模式。后续接真实 embedding 或换模型时，
    rebuild_embeddings 就是「一键重索引」入口，覆盖度会随之刷新。
    """
    data = store.list_items()
    items = data["items"]
    n = len(items)
    con = store.connect()
    try:
        emb_n = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        chunk_n = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        chunk_vec_n = con.execute(
            "SELECT COUNT(*) FROM chunks WHERE vec IS NOT NULL AND vec <> 'null'").fetchone()[0]
        edges = {r["status"]: r["c"] for r in con.execute(
            "SELECT status, COUNT(*) c FROM edges GROUP BY status").fetchall()}
        last = con.execute("SELECT MAX(computed_at) FROM readings").fetchone()[0]
        mode = store.get_mode(con)
    finally:
        con.close()
    return {
        "items": n,
        "domains": len(data["bands"]),
        "embeddings": emb_n,
        "embedding_coverage": round(emb_n / max(1, n), 3),
        "chunks": chunk_n,
        "chunk_index_coverage": round(chunk_vec_n / max(1, chunk_n), 3),
        "edges": edges,
        "collisions": sum(1 for it in items if it["collision"]),
        "global_typical": data.get("global_typical"),
        "last_computed_at": last,
        "mode": mode,
        "domain_distribution": [{"name": b["name"], "count": b["count"]}
                                for b in data["bands"]],
    }


# ============================================================== 坐标检索
def _threshold():
    return store.get_threshold_value()


def position(text, mode=None):
    """只定位不入库：返回主尺/游标读数与偏移（供 agent 判断归属，不走存储）。"""
    con = store.connect()
    m = mode or store.get_mode(con)
    con.close()
    (band_name, pos, mconf, _mprov, _mw), (depth, vconf, _vprov, _vw) = \
        store.measure_pair(text, m)
    band = store.band_of(pos)
    offset = round(depth - band["typical_vernier"], 1)
    return {
        "band": band["name"], "main_pos": round(pos, 1),
        "vernier": round(depth, 1), "offset": offset,
        "collision": abs(offset) > _threshold(),
        "main_conf": round(mconf, 3), "vernier_conf": round(vconf, 3),
    }


def linked_neighbors(item_id, k=8):
    """经 links 直接相连的「相邻知识」（硬链 + 软链），供阅读页 / 图谱推荐用。"""
    return {"neighbors": store.linked_neighbors(int(item_id), int(k))}


def neighbors(item_id=None, text=None, k=5):
    """按双尺度位置找最近邻（欧氏距离）。"""
    items = store.list_items()["items"]
    if text is not None:
        p = position(text)
        target = (p["main_pos"], p["vernier"])
    else:
        if item_id is None:
            return {"ok": False, "msg": "需提供 item_id 或 text"}
        it = store.get_item(item_id)
        if not it:
            return {"ok": False, "msg": "条目不存在"}
        target = (it["main_pos"], it["vernier"])

    def dist(o):
        return math.hypot(o["main_pos"] - target[0], o["vernier"] - target[1])

    ranked = sorted(items, key=dist)
    if text is None:
        ranked = [o for o in ranked if o["id"] != item_id]
    return {
        "target": {"main_pos": target[0], "vernier": target[1]},
        "neighbors": ranked[:k],
    }


def search_dual(band=None, depth_min=None, depth_max=None, top_k=20):
    """按双尺度坐标过滤：领域带 + 演绎深度区间。"""
    items = store.list_items()["items"]
    out = []
    for it in items:
        if band and it["band"] != band:
            continue
        if depth_min is not None and it["vernier"] < depth_min:
            continue
        if depth_max is not None and it["vernier"] > depth_max:
            continue
        out.append(it)
    out.sort(key=lambda x: x["id"])
    return {"matches": out[:top_k], "count": len(out)}


# ============================================================== 图谱 / 闭环 / 状态
def list_edges(status=None):
    edges = store.list_edges()
    if status:
        edges = [e for e in edges if e.get("status") == status]
    return edges


def calibrate(item_id):
    return store.calibrate(int(item_id))


def reconcile(item_id, force_domain=None):
    """以学科域为语义锚，把主尺收敛回所属主干带中心（见 items.reconcile_band_with_domain）。"""
    return store.reconcile_band_with_domain(int(item_id), force_domain)


def state():
    con = store.connect()
    mode = store.get_mode(con)
    con.close()
    items = store.list_items()
    ind = store.independence()
    llm = store._llm.info() if store.LLM_OK else {"available": False}
    return {
        "item_count": len(items["items"]),
        "edges": store.list_edges(),
        "independence": ind,
        "mode": mode,
        "llm": llm,
        "threshold": items["threshold"],
        "bands": items["bands"],
    }


def set_mode(mode):
    return store.remeasure_all(mode)


# ============================================================== 关系处理引擎（agent 专用）
# 设计立场：知识库的主要消费方是 agent。下面这组能力把「如何使用和处理数据的关联性」
# 交还给 agent —— 人类只负责定义构成逻辑（领域带、阈值、provider），agent 负责检索增强、
# 关系图构建与多跳推理。REST 与 MCP 共用同一实现。
def schema():
    """返回「构成逻辑」快照：动态领域（内容归纳）、阈值、模式、独立性、模型。
    agent 在调用关系工具前可先读它，以理解坐标空间与当前策略。"""
    con = store.connect()
    mode = store.get_mode(con)
    con.close()
    return {
        "bands": store.list_domains(),
        "threshold": store.get_threshold_value(),
        "mode": mode,
        "independence": store.independence(),
        "llm": store._llm.info() if store.LLM_OK else {"available": False},
    }


def _title_of(item_id):
    it = store.get_item(int(item_id))
    return it["title"] if it else f"#{item_id}"


def _snip(content, n=170):
    c = (content or "").replace("\n", " ").strip()
    return c[:n] + ("…" if len(c) > n else "")


def _edges_for_item(item_id, band):
    edges = store.list_edges()
    hit = [e for e in edges if e.get("src_item") == item_id
           or e.get("dst_band") == band]
    seen, out = set(), []
    for e in hit:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    return out


def _relate_summary(target, nbrs, edges):
    lines = []
    band = target.get("band") or "?"
    mp = target.get("main_pos")
    vn = target.get("vernier")
    off = target.get("offset")
    lines.append(f"坐标：领域带={band}，主尺={mp}，演绎深度={vn}，偏移={off}"
                 + ("（碰撞/越界）" if target.get("collision") else "（已对齐）"))
    if nbrs:
        near = nbrs[0]
        d = round(math.hypot(near["main_pos"] - (mp or 0),
                             near["vernier"] - (vn or 0)), 1)
        lines.append(f"最近邻：『{near.get('title')}』（距离 {d}，{near.get('band')}）")
        deeper = [n for n in nbrs if n["vernier"] > (vn or 0)]
        if deeper:
            lines.append("邻域中演绎更深：" + "、".join(n["title"] for n in deeper[:3]))
    if edges:
        for e in edges[:4]:
            lines.append(f"候选关联边：『{e.get('title')}』→{e.get('dst_band')}"
                         f"（{e.get('kind')}，偏移 {e.get('offset_ld')}）")
    if not nbrs and not edges:
        lines.append("暂无强关联：该知识在现有库中较孤立，建议补充相关条目或交由 agent 建立连接。")
    return lines


def context(qtext, top_k=5, include_edges=True, max_chars=2200):
    """组装检索增强上下文包：供 agent 把『相关知识』一次性取走喂给自己。
    这是『如何使用数据』由 agent 决定的体现——KB 只负责把相关材料聚合好。"""
    q_res = query(qtext, top_k=top_k)
    picked = q_res["results"]
    items_map = {i["id"]: i for i in store.list_items()["items"]}
    seen = set()
    blocks = []
    for it in picked:
        seen.add(it["id"])
        blocks.append(_ctx_block(it, qtext))
    if picked and len(picked) < top_k:
        nbrs = neighbors(picked[0]["id"], None, k=top_k)["neighbors"]
        for n in nbrs:
            if n["id"] not in seen and len(seen) < top_k:
                seen.add(n["id"])
                blocks.append(_ctx_block(n, qtext))
    edge_note = ""
    if include_edges and seen:
        seen_bands = {items_map[i]["band"] for i in seen if i in items_map}
        es = [e for e in store.list_edges()
              if (e.get("src_item") in seen or e.get("dst_band") in seen_bands)
              and e.get("status") != "rejected"]
        if es:
            edge_note = "\n# 已选知识间的候选关联边\n" + "\n".join(
                f"- 『{_title_of(e['src_item'])}』⇄{e['dst_band']}：{e['kind']}（{e.get('status')}）"
                for e in es)
    packet = "# 检索上下文（由知识库自动聚合）\n" + "\n\n".join(blocks) + edge_note
    if max_chars and len(packet) > max_chars:
        packet = packet[:max_chars] + "\n…(截断)"
    return {"query": qtext, "count": len(seen), "packet": packet}


def _ctx_block(it, query):
    title = it.get("title", "")
    snip = it.get("snippet") or _snip(it.get("content", ""), 160)
    return (f"## {title}\n"
            f"- 领域带：{it.get('band')}｜主尺 {it.get('main_pos')}｜"
            f"演绎深度 {it.get('vernier')}｜偏移 {it.get('offset')}"
            f"{'（碰撞）' if it.get('collision') else ''}\n"
            f"- 内容：{snip}")


def traverse(start_id, hops=2, kind=None):
    """多跳关系遍历：从起点沿候选边（item→band→同带成员）向外扩展 hops 跳。
    agent 用来『顺藤摸瓜』发现跨领域知识链。"""
    items_map = {i["id"]: i for i in store.list_items()["items"]}
    sid = int(start_id)
    if sid not in items_map:
        return {"ok": False, "msg": "起点不存在"}
    edges = store.list_edges()
    if kind:
        edges = [e for e in edges if e.get("kind") == kind]
    visited = {sid}
    frontier = {sid}
    path = []
    for _ in range(hops):
        nxt = set()
        for e in edges:
            s, db = e.get("src_item"), e.get("dst_band")
            if s in frontier:
                for oid, o in items_map.items():
                    if o.get("band") == db and oid not in visited:
                        nxt.add(oid)
                        path.append((s, oid, db, e.get("kind"), e.get("status")))
            for fid in frontier:
                if db == items_map[fid].get("band") and s not in visited and s is not None:
                    nxt.add(s)
                    path.append((fid, s, db, e.get("kind"), e.get("status")))
        if not nxt:
            break
        visited |= nxt
        frontier = nxt
    nodes = [items_map[i] for i in visited if i in items_map]
    return {"start_id": sid, "hops": hops, "visited_ids": sorted(visited),
            "nodes": nodes,
            "edges_traversed": [{"from": a, "to": b, "via_band": vb,
                                 "kind": k, "status": s} for (a, b, vb, k, s) in path]}


# ============================================================== 本地文章文件 + 点击查看协同
# 知识文章以 SQLite（items/readings）为唯一真相源；每条同步镜像到 articles/<id>.md，
# 供人直接阅读 / 用外部编辑器改写。下面这组能力把「存」与「看」打通：
#   get_article     —— 取全文 + 本地文件路径（界面点开阅读 / 打开文件用）
#   update_article  —— 在 KB 内改写并保存，同步回写文件（KB -> 文件）
#   reload_article  —— 从本地 .md 重新载入正文回灌 DB（文件 -> KB）
def get_article(item_id):
    it = store.get_item(item_id)
    if not it:
        return {"ok": False, "msg": "条目不存在"}
    p = store.article_path(item_id)
    exists = os.path.exists(p)
    md = None
    if exists:
        with open(p, "r", encoding="utf-8") as f:
            md = f.read()
    return {**it, "file": p, "file_exists": exists, "markdown": md,
            "rev": store._content_rev(it.get("content", "")),
            "outlinks": store.outlinks(item_id), "backlinks": store.backlinks(item_id)}


def update_article(item_id, title, content, axis_domain=None, rev=None):
    axis_domain = normalize_axis_domain(axis_domain)
    return store.update_item(item_id, title, content, axis_domain, rev=rev)


def reload_article(item_id):
    return store.reload_from_file(item_id)


# ============================================================== 双向引用 / 多维轴 / 语义相似
def backlinks(item_id):
    """谁引用了这条（入链）。"""
    return {"item_id": int(item_id), "backlinks": store.backlinks(int(item_id))}


def link(src_id, dst_id):
    """手动建立一条条目间互链。"""
    return store.add_link(int(src_id), int(dst_id))


def unlink(src_id, dst_id):
    return store.remove_link(int(src_id), int(dst_id))


def confirm_soft_link(src_id, dst_id):
    return store.confirm_soft_link(int(src_id), int(dst_id))


def dismiss_soft_link(src_id, dst_id):
    return store.dismiss_soft_link(int(src_id), int(dst_id))


def refresh_soft_links():
    return store.refresh_soft_links()


def discover_semantic_links(threshold=0.62, persist=False):
    """D · 语义发现：无共享关键词、却语义相近的条目对（provenance='semantic' 软边）。"""
    return store.discover_semantic_links(float(threshold), persist)


def create_draft(title):
    """E1 · 自生长：为虚节点创建空壳草稿，源 [[目标]] 随即解析成硬链。"""
    return store.create_draft(title)


def detect_health(sim_threshold=0.90):
    """E2 · 健康自检：近重复/高耦合条目对推入反馈收件箱。"""
    return store.detect_health(float(sim_threshold))


def summarize_links():
    return store.summarize_links()


def auto_log(kind, message):
    return store.auto_log(kind, message)


def list_auto_log(limit=40):
    return store.list_auto_log(int(limit))


def audit_log(limit=80):
    """合并审计流：引擎自主核对(auto_log) + 阴阳互纠与系统消息(calib_log)，
    供「自动核对记录」面板统一按时间倒序带时间戳呈现。"""
    return store.list_audit_log(int(limit))


def audit_stats():
    """日志/缓存型数据的占用与计数（前端清理入口展示）。"""
    return store.audit_stats()


def purge_audit_log(keep_days=30):
    """清理不需要长期保存的日志/缓存型数据（按时间窗口保留近期，过期删除并回收磁盘）。"""
    return store.purge_audit_log(int(keep_days))


def graph():
    """wiki 知识图谱数据（边来自 [[...]] 硬链 + 共现/语义软链，与 band/domain 解耦）。"""
    return store.build_graph()


def axes():
    """已并入的多维轴分类（领域|维度）。"""
    return {"domains": store.domains_of_axes(), "axes": store.list_axes()}


def import_axes(path=None):
    return store.import_axes(path)


def semantic(text, k=5):
    """按语义向量相似度检索（本地哈希向量，离线可用；有 embedding 接口则优先用）。"""
    return {"query": text, "results": store.semantic_search(text, int(k))}


def delete(item_id, backup=False):
    """删除一条知识（级联清理关联、向量、日志与本地 .md），默认不做快照。"""
    return store.delete_item(item_id, backup=backup)


def backup(reason="manual"):
    """立刻生成一份整库快照，并返回现有快照列表。"""
    r = store.snapshot(reason)
    r["backups"] = store.list_backups()
    return r


def suggest_links(k=8, min_score=0.0, min_shared=2):
    """「该连未连」：意思上**真有共同话题**、却还没互链的条目对。

    知识库真正的价值在关系，但关系一向要人手动去建 —— 这里用已有的
    向量把候选摆出来，人只需判断"是/否"，把发现关系的成本压到一次点击。

    规则（store.suggest_links 内）：共享词必须是"有区分度 + 非空洞 + 真在讲"
    的真词，且至少 2 条独立证据（≥2 个证据词，或 1 词 + 1 共同标签）；
    两条特色词的 Dice 重叠 ≥ 0.08；跨领域再额外加严。宁可返回空，也不拿
    "措辞像"糊弄。
    """
    return store.suggest_links(int(k), float(min_score), int(min_shared))


def relate(item_id=None, text=None):
    """关系图：在原有邻域/候选边基础上，补上条目间互链（双向引用）。"""
    base = _relate_base(item_id, text)
    if base.get("target_id") is not None:
        tid = base["target_id"]
        base["outlinks"] = store.outlinks(tid)
        base["backlinks"] = store.backlinks(tid)
        base["summary"].append(
            f"双向引用：出链 {len(base['outlinks'])} 条、入链（被引用）{len(base['backlinks'])} 条。"
            if (base["outlinks"] or base["backlinks"])
            else "暂无条目间互链：可在正文用 [[标题]] 关联其他知识，或让 agent 建立连接。")
    return base


def _relate_base(item_id=None, text=None):
    """relate 的内核（与旧逻辑一致，仅抽出以便扩展）。"""
    items = store.list_items()["items"]
    if text is not None:
        p = position(text)
        target = {"main_pos": p["main_pos"], "vernier": p["vernier"],
                  "band": p["band"], "offset": p["offset"],
                  "collision": p["collision"]}
        target_id = None
    else:
        if item_id is None:
            return {"ok": False, "msg": "需提供 item_id 或 text"}
        it = store.get_item(item_id)
        if not it:
            return {"ok": False, "msg": "条目不存在"}
        target = it
        target_id = item_id
    nbrs = neighbors(item_id, text, k=5)["neighbors"]
    if target_id is not None:
        edges = _edges_for_item(target_id, target.get("band"))
    else:
        edges = [e for e in store.list_edges()
                 if e.get("dst_band") == target.get("band")]
    summary = _relate_summary(target, nbrs, edges)
    return {
        "target": {k: target.get(k) for k in
                   ("id", "title", "band", "main_pos", "vernier", "offset", "collision")},
        "target_id": target_id,
        "neighbors": nbrs,
        "edges_touching": edges,
        "summary": summary,
    }


# ============================================================== 工具元数据
# REST 与 MCP 共用同一份定义，保证「任何 agent 拿到的能力一致」。


def import_kb(text=None, entries=None, directory=None):
    """批量导入：粘贴多篇（--- 分隔、支持 # 标题）或读本地 md 目录；标题已存在则跳过。"""
    if entries is None and text:
        entries = store.parse_import_text(text)
    if not entries and directory:
        entries = store.scan_md_dir(directory)
    if not entries:
        return {"ok": False, "msg": "没有可导入的内容"}
    existing = {i.get("title") for i in store.list_items()["items"]}
    out = {"ok": True, "imported": [], "skipped": [], "failed": []}
    for e in entries:
        title = (e.get("title") or "").strip()
        content = (e.get("content") or "").strip()
        if not content:
            out["failed"].append({"title": title or "(无标题)", "msg": "正文为空"})
            continue
        if title and title in existing:
            out["skipped"].append({"title": title, "msg": "标题已存在"})
            continue
        try:
            r = add_knowledge(title or None, content)
            if r.get("ok") is False:
                out["failed"].append({"title": title or content[:12], "msg": r.get("msg", "导入失败")})
                continue
            out["imported"].append({
                "title": title or content[:12],
                "id": (r.get("item") or {}).get("id"),
            })
            if title:
                existing.add(title)
        except Exception as ex:                    # noqa: BLE001
            out["failed"].append({"title": title or content[:12], "msg": str(ex)})
    return out


def rebuild_embeddings():
    """用真实模型 embedding 重建全部条目向量（模型不可用自动退回本地）。"""
    return store.rebuild_embeddings()


TOOLS = [
    {
        "name": "kb_import",
        "description": "批量导入知识：可传 text（多篇用独占一行的 --- 分隔，每篇可用 # 标题 开头），"
                       "或传 directory（扫描本地 md/txt 目录，带 frontmatter 自动解析）。标题已存在则跳过。"
                       "返回 成功/跳过/失败 明细。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "粘贴的多篇文本（与 directory 二选一）"},
                "directory": {"type": "string", "description": "本地目录路径（与 text 二选一）"}
            }
        },
    },
    {
        "name": "kb_embed_rebuild",
        "description": "用真实模型 embedding 为全部条目重建语义向量（内容哈希缓存，重复重建不重复计费）。"
                       "模型不可用时自动退回本地向量。返回 完成数/失败数/维度。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_add",
        "description": "摄入一条知识：自动双尺度定位（主尺=学科领域，游标=逻辑演绎深度）"
                       "并生成候选跨学科边；碰撞时自动跑一次阴阳闭环校准。返回定位结果与候选边。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "知识标题（可选，缺省取内容前20字）"},
                "content": {"type": "string", "description": "知识正文（必填）"},
                "run_closure": {"type": "boolean", "description": "碰撞时是否自动闭环，默认 true"}
            },
            "required": ["content"]
        },
    },
    {
        "name": "kb_query",
        "description": "按自由文本检索知识库（离线评分，无需 embedding）。"
                       "标题命中+2、正文命中+1/次、多词+0.5，返回相关性排序 + <mark> 高亮片段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "检索词/句子（必填）"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5"}
            },
            "required": ["text"]
        },
    },
    {
        "name": "kb_neighbors",
        "description": "按双尺度坐标位置找最近邻知识（欧氏距离）。可传 item_id 定位已有条目，"
                       "或传 text 先定位再找邻域——用于「相似知识发现」。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "已有条目 id（与 text 二选一）"},
                "text": {"type": "string", "description": "待定位文本（与 item_id 二选一）"},
                "k": {"type": "integer", "description": "返回邻域条数，默认 5"}
            }
        },
    },
    {
        "name": "kb_search",
        "description": "按双尺度坐标过滤知识：可限定领域带（人文/社会科学/自然科学/形式科学）"
                       "与演绎深度区间，用于「某领域内高形式化程度的材料」这类结构化检索。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "band": {"type": "string", "description": "领域带名（可选）"},
                "depth_min": {"type": "number", "description": "演绎深度下限 0-100（可选）"},
                "depth_max": {"type": "number", "description": "演绎深度上限 0-100（可选）"},
                "top_k": {"type": "integer", "description": "返回条数，默认 20"}
            }
        },
    },
    {
        "name": "kb_retrieve",
        "description": "混合检索管线：关键词(FTS5) + 语义(向量余弦) 倒数排名融合(RRF)，"
                       "再按元数据过滤（领域/标签/是否异常）。返回带命中信号的排序结果。"
                       "对应 RAG 的检索阶段；真实 embedding 接入后语义段自动升级，无需改调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词/句子（必填）"},
                "filters": {"type": "object",
                            "description": "元数据过滤：{band, tag, collision(true/false)}（可选）"},
                "top_k": {"type": "integer", "description": "返回条数，默认 10"}
            },
            "required": ["query"]
        },
    },
    {
        "name": "kb_health",
        "description": "知识库健康快照：条目量、领域分布、向量覆盖度、候选边状态、异常(碰撞)数、"
                       "最近模型补算时间、当前模式。对应 RAG 的运维监控；"
                       "换 embedding 模型后调 kb_embed_rebuild 即「一键重索引」。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_edges",
        "description": "列出知识图谱的候选跨学科边（logic-isomorphism 逻辑同构 / "
                       "under-formalized 未形式化）。可选按状态过滤 candidate/accepted/rejected。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "边状态过滤（可选）"}
            }
        },
    },
    {
        "name": "kb_position",
        "description": "仅定位不入库：判断一段文本在双尺度上的坐标（学科领域 + 演绎深度 + 偏移）。"
                       "供 agent 在不写入知识库的前提下评估「这段知识属于哪」。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待定位文本（必填）"}
            },
            "required": ["text"]
        },
    },
    {
        "name": "kb_calibrate",
        "description": "对指定条目运行阴阳闭环校准（阴修订主尺直至偏移收敛或达上限）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "条目 id（必填）"}
            },
            "required": ["item_id"]
        },
    },
    {
        "name": "kb_state",
        "description": "知识库总览：条目数、候选边、两尺独立性检验、当前 provider 模式、LLM 状态。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_mode",
        "description": "切换双尺 provider：heuristic（本地零依赖）/ llm（真实大模型，输入互补切分保独立）。"
                       "切换会重测全部条目。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "description": "heuristic 或 llm", "enum": ["heuristic", "llm"]}
            },
            "required": ["mode"]
        },
    },
    {
        "name": "kb_schema",
        "description": "返回人类定义的「构成逻辑」快照：领域带划分、碰撞阈值、当前 provider 模式、"
                       "两尺独立性、模型信息。agent 在调用关系工具前先读它，以理解坐标空间与策略边界。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_relate",
        "description": "关系图（agent 理解『X 与已知知识如何关联』的核心入口）：给定条目 id 或文本，"
                       "返回其双尺邻域、指向它的候选跨学科边、以及一段结构化关系摘要。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "已有条目 id（与 text 二选一）"},
                "text": {"type": "string", "description": "待定位文本（与 item_id 二选一）"}
            }
        },
    },
    {
        "name": "kb_context",
        "description": "组装检索增强上下文包：给定查询，把『相关知识』一次性聚合并格式化为可直接喂给 agent 自身 prompt 的文本。"
                       "体现『如何使用数据由 agent 决定，KB 只负责聚合』。可选 include_edges 与 max_chars 控制范围。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索查询（必填）"},
                "top_k": {"type": "integer", "description": "聚合条数，默认 5"},
                "include_edges": {"type": "boolean", "description": "是否附上已选知识间的候选关联边，默认 true"},
                "max_chars": {"type": "integer", "description": "上下文包最大字符数，默认 2200"}
            },
            "required": ["query"]
        },
    },
    {
        "name": "kb_traverse",
        "description": "多跳关系遍历：从起点沿候选边（item→band→同带成员）向外扩展 N 跳，"
                       "发现跨领域知识链。agent『顺藤摸瓜』的能力。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_id": {"type": "integer", "description": "起点条目 id（必填）"},
                "hops": {"type": "integer", "description": "遍历跳数，默认 2"},
                "kind": {"type": "string", "description": "仅遍历指定类型边：logic-isomorphism / under-formalized（可选）"}
            },
            "required": ["start_id"]
        },
    },
    {
        "name": "kb_article",
        "description": "取某条知识的全文 + 本地文件路径（articles/<id>.md）。界面点开阅读、或『打开本地文件』时使用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "条目 id（必填）"}
            },
            "required": ["item_id"]
        },
    },
    {
        "name": "kb_update",
        "description": "在知识库内改写某条知识并保存：更新正文、重测双尺坐标，并同步回写本地 articles/<id>.md（KB -> 文件 协同）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "条目 id（必填）"},
                "title": {"type": "string", "description": "新标题（必填）"},
                "content": {"type": "string", "description": "新正文（必填）"}
            },
            "required": ["item_id", "title", "content"]
        },
    },
    {
        "name": "kb_reload",
        "description": "从本地 articles/<id>.md 重新载入正文回灌知识库并重测双尺（文件 -> KB 协同）。"
                       "用于你在外部编辑器改了 .md 后，让知识库同步更新。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "条目 id（必填）"}
            },
            "required": ["item_id"]
        },
    },
    {
        "name": "kb_backlinks",
        "description": "查看某条知识的双向引用：谁引用了它（入链）。配合 kb_link 与正文 [[标题]] 标记，"
                       "让条目间织成知识网，而非只挂在学科分类下。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "条目 id（必填）"}
            },
            "required": ["item_id"]
        },
    },
    {
        "name": "kb_link",
        "description": "手动建立条目间的互链（双向引用网络的一条边）。src_id 引用 dst_id。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src_id": {"type": "integer", "description": "源条目 id（必填）"},
                "dst_id": {"type": "integer", "description": "目标条目 id（必填）"}
            },
            "required": ["src_id", "dst_id"]
        },
    },
    {
        "name": "kb_axes",
        "description": "列出本库的领域|维度 多维轴分类法（已并入 DB），"
                       "作为比学科带更细的学科方向参考。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_import_axes",
        "description": "把 领域|维度 分类法并入本知识库。分类文件通过 path 显式提供，"
                       "不传则默认在知识库目录内查找 axis_meta.json。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "axis_meta.json 路径（可选，默认自动定位）"}
            }
        },
    },
    {
        "name": "kb_similar",
        "description": "语义检索：按向量相似度（余弦）找最相关的内容，捕捉『意思相近』而非仅关键词命中。"
                       "默认本地哈希向量离线可用；若配置了 embedding 接口则优先使用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "查询文本（必填）"},
                "k": {"type": "integer", "description": "返回条数，默认 5"}
            },
            "required": ["text"]
        },
    },
    {
        "name": "kb_suggest_links",
        "description": "「该连未连」：找出意思上真的沾边、却还没建立互链的条目对，"
                       "并给出共同词、跨学科标记与理由。只靠虚词相似的会被判为"
                       "完全不可能并剔除。用于把孤立的条目连成知识网；"
                       "确认后用 kb_link 采纳。同时返回孤岛条目清单。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "k": {"type": "integer", "description": "返回候选对数，默认 8"},
                "min_score": {"type": "number", "description": "相似度下限，默认 0.28"},
                "min_shared": {"type": "integer",
                               "description": "至少要有几个有区分度的共同词，默认 1"}
            }
        },
    },
    {
        "name": "kb_delete",
        "description": "删除一条知识：级联清理它的分类读数、向量、互链、关联边、日志与本地 .md 文件。"
                       "不可撤销，依赖前端二次确认；默认不做整库快照。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "要删除的条目 id（必填）"},
                "backup": {"type": "boolean", "description": "是否先备份整库，默认 false（仅显式传 true 才留快照）"}
            },
            "required": ["item_id"]
        },
    },
    {
        "name": "kb_backup",
        "description": "立刻生成一份整库快照（分类坐标、向量、互链、摘要都只存在数据库里，"
                       "articles/*.md 只镜像正文），并返回现有快照列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "备注，会写进文件名"}
            }
        },
    },
    {
        "name": "kb_fragments",
        "description": "片段级检索：把每篇正文切成带重叠的语义片段单独建索引，"
                       "返回命中具体句子的片段（带高亮 + 所属条目标题），让查找能定位到段落。"
                       "可传 filters={band, collision} 按领域/是否异常过滤。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词（必填）"},
                "filters": {"type": "object", "description": "可选：{band:领域名, collision:布尔}"},
                "top_k": {"type": "integer", "description": "返回片段数，默认 8"}
            },
            "required": ["query"]
        },
    },
    {
        "name": "kb_sparks",
        "description": "列出灵感碎片（最上游原料层，无坐标随手记）。可传 status 过滤（raw/incubating/hatched），用于查看待孵化原料或已孵化溯源。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "可选：raw（原料）/incubating（孵化中）/hatched（已孵化）"},
                "limit": {"type": "integer", "description": "返回条数，默认 500"}
            }
        }
    },
    {
        "name": "kb_add_spark",
        "description": "捕获一条灵感碎片（真正的知识出发点）。content 为随手记想法，title/tags 可选；刻意不做双尺度投影，投影在孵化时由 kb_hatch_spark 完成。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "灵感内容（必填）"},
                "title": {"type": "string", "description": "可选标题，不填取首 24 字"},
                "tags": {"type": "array", "description": "可选自由标签"},
                "source": {"type": "string", "description": "来源：manual/import/clip，默认 manual"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "kb_update_spark",
        "description": "编辑一条灵感碎片（content/title/tags 任一可改，不给则不改）。碎片与知识条目互相独立，已孵化的碎片也允许在此改原始记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spark_id": {"type": "integer", "description": "碎片 id（必填）"},
                "content": {"type": "string", "description": "新的正文（可选；不给则不改）"},
                "title": {"type": "string", "description": "新的标题（可选）"},
                "tags": {"type": "string", "description": "新的标签，逗号分隔（可选）"}
            },
            "required": ["spark_id"]
        }
    },
    {
        "name": "kb_reconcile",
        "description": "以学科域(axis_domain)为语义锚，把某条目的主尺位置收敛回该域所属主干带中心，消除『主尺带与学科域相冲突』的错位。保留游标(vernier)不动，残留偏移视为深度相对学科域典型的信号。axis_domain 为空时可用 force_domain 指定受控学科域。返回对齐前后带与位置。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "条目 id（必填）"},
                "force_domain": {"type": "string", "description": "可选受控学科域；当条目 axis_domain 为空时指定，用于补全并锚定"}
            },
            "required": ["item_id"]
        }
    },
    {
        "name": "kb_hatch_spark",
        "description": "智能孵化灵感碎片：冗余闸门(命中则增量合并保留双尺)→投影富化(注入簇信号)→全库关联发现(以新节点为中心写软边)→反馈轴自检(推送收件箱)→簇血缘(兄弟联动)→事件日志。返回决策/关联数/反馈/兄弟等报告。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spark_id": {"type": "integer", "description": "碎片 id（必填）"},
                "title": {"type": "string", "description": "可选覆写标题"},
                "axis_domain": {"type": "string", "description": "可选受控学科域；缺省则从簇主题/标签推断"},
                "run_closure": {"type": "boolean", "description": "是否自动跑阴阳闭环，默认 true"},
                "hit_threshold": {"type": "number", "description": "冗余闸门命中阈值(kb.query top 分)，默认 4.0；≥此分视为同一概念→合并"}
            },
            "required": ["spark_id"]
        }
    },
    {
        "name": "kb_draft_hatch",
        "description": "智能孵化·阶段一：对灵感碎片生成「碰撞创作草稿」（结合知识库相关内容合成，不落库）。返回 decision(merged/new)/merge_target/相关素材/可编辑 draft 正文。落库请再调 kb_commit_hatch。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spark_id": {"type": "integer", "description": "碎片 id（必填）"},
                "title": {"type": "string", "description": "可选覆写标题"},
                "axis_domain": {"type": "string", "description": "可选受控学科域；缺省则从簇主题/标签推断"},
                "run_closure": {"type": "boolean", "description": "确认阶段是否自动跑阴阳闭环，默认 true"},
                "hit_threshold": {"type": "number", "description": "冗余闸门命中阈值，默认 4.0"}
            },
            "required": ["spark_id"]
        }
    },
    {
        "name": "kb_commit_hatch",
        "description": "智能孵化·阶段二：用户微调草稿后确认入库。content 为用户编辑后的正文（必填）；按冗余闸门自动决定并入既有条目或新建。返回六阶段完整报告。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spark_id": {"type": "integer", "description": "碎片 id（必填）"},
                "content": {"type": "string", "description": "用户微调后的草稿正文（必填）"},
                "title": {"type": "string", "description": "可选覆写标题"},
                "axis_domain": {"type": "string", "description": "可选受控学科域"},
                "hit_threshold": {"type": "number", "description": "冗余闸门命中阈值，默认 4.0"}
            },
            "required": ["spark_id", "content"]
        }
    },
    {
        "name": "kb_spark_clusters",
        "description": "灵感碎片的离线聚类萌发：关键词共现把相近碎片聚成主题簇，只呈现「这些碎片似乎在讲同一件事」的结构，不下结论；供决定哪些该孵化。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "top_k": {"type": "integer", "description": "返回簇数，默认 8"},
                "min_shared": {"type": "integer", "description": "成簇最少共享词数，默认 2"},
                "min_jac": {"type": "number", "description": "成簇最小 Jaccard 重叠比，默认 0（不卡 Jaccard，仅以共享词数为门槛；>0 时作额外收紧）"}
            }
        }
    },
    {
        "name": "kb_hatch_stats",
        "description": "智能孵化事件聚合：总孵化数、按决策(new/merged)分布、按学科域分布、近 7 天趋势、累计关联发现/反馈/簇血缘数。供 Skill 据以校准轴绩点（库自我反思生长）。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
]


# ---------------------------------------------------------------- 反馈收件箱 API
# 自我对抗审查（反馈轴）不进文章正文，单独走这里——作消息通知储存 + 自我更新指导。
def push_feedback(item_id, title, axis_domain, review, severity="info", must_revise=0):
    return store.push_feedback(item_id, title, axis_domain, review, severity, must_revise)

def list_feedback(status=None, limit=100):
    return store.list_feedback(status, limit)

def get_feedback(fid):
    return store.get_feedback(fid)

def count_unread_feedback():
    return store.count_unread_feedback()

def mark_feedback_read(fid):
    return store.mark_feedback_read(fid)

def mark_feedback_applied(fid):
    return store.mark_feedback_applied(fid)

def dismiss_feedback(fid):
    return store.dismiss_feedback(fid)

def revise_with_feedback(fid):
    """生成反馈对应的修订稿（不落库）。前端拿到后做 diff 预览，用户确认才回写。"""
    return store.revise_with_feedback(fid)


# ---------------------------------------------------------------- 灵感碎片（原料层）API
# 最上游的随手记捕获，刻意无坐标；投影发生在孵化（kb.add_knowledge）。
def sparks(status=None, limit=500):
    return store.list_sparks(status, limit)

def add_spark(content, title=None, tags=None, source="manual"):
    return store.add_spark(content, title, tags, source)


def update_spark(sid, content=None, title=None, tags=None):
    return store.update_spark(int(sid), content, title, tags)

def spark_clusters(top_k=8, min_shared=2, min_jac=0.0):
    return store.spark_clusters(top_k, min_shared, min_jac)

def hatch_spark(spark_id, title=None, axis_domain=None, run_closure=True, hit_threshold=4.0):
    return store.hatch_spark(int(spark_id), title, axis_domain, run_closure, hit_threshold)


def draft_hatch(spark_id, title=None, axis_domain=None, run_closure=True, hit_threshold=4.0):
    """阶段一：生成碰撞创作草稿（不落库）。供前端展示/用户微调。"""
    return store.draft_hatch(int(spark_id), title, axis_domain, run_closure, hit_threshold)


def commit_hatch(spark_id, content, title=None, axis_domain=None, hit_threshold=4.0):
    """阶段二：用户微调草稿后确认入库。content 为用户编辑后的正文（必填）。"""
    return store.commit_hatch(int(spark_id), content, title, axis_domain, hit_threshold)


def hatch_stats():
    """孵化事件聚合：让知识库能「反思」自己的生长（智能孵化的第 ⑥ 阶段数据侧）。

    返回：总孵化数、按决策(new/merged)分布、按学科带分布、近 7 天趋势、
    累计关联发现数 / 反馈数 / 簇血缘数。Skill 可据以校准「轴绩点」（哪些透镜最近热）。

    注：本函数只产出数据，不写回 Skill 状态——KB 守数据本职、Skill 驾驭迭代的
    边界已锁定，故由 Skill 主动读取本函数，而非 KB 反向侵入 Skill 状态目录。"""
    con = store.connect()
    try:
        rows = con.execute(
            "SELECT decision, axis_domain, links_found, feedback_ids, "
            "sibling_spark_ids, item_id, created_at FROM hatch_events").fetchall()
    finally:
        con.close()
    total = len(rows)
    by_decision = {"new": 0, "merged": 0}
    by_band = {}
    recent = 0
    cutoff = time.time() - 7 * 86400
    sum_links = sum_links_total = 0
    sum_fb = sum_fb_total = 0
    sum_sib = 0
    for r in rows:
        by_decision[r["decision"]] = by_decision.get(r["decision"], 0) + 1
        if r["created_at"] >= cutoff:
            recent += 1
        sum_links_total += (r["links_found"] or 0)
        try:
            sum_fb_total += len(json.loads(r["feedback_ids"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            sum_sib += len(json.loads(r["sibling_spark_ids"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        if r["axis_domain"]:
            by_band[r["axis_domain"]] = by_band.get(r["axis_domain"], 0) + 1
    return {
        "total": total, "by_decision": by_decision, "by_domain": by_band,
        "recent_7d": recent, "links_discovered": sum_links_total,
        "feedback_raised": sum_fb_total, "siblings_linked": sum_sib,
    }


def dispatch(name, args):
    """统一入口：REST 与 MCP 都通过它调用，确保行为一致。"""
    args = args or {}
    if name == "kb_add":
        return add_knowledge(args.get("title"), args.get("content"),
                            bool(args.get("run_closure", True)))
    if name == "kb_import":
        return import_kb(args.get("text"), args.get("entries"), args.get("directory"))
    if name == "kb_embed_rebuild":
        return rebuild_embeddings()
    if name == "kb_query":
        return query(args.get("text", ""), int(args.get("top_k", 5)))
    if name == "kb_neighbors":
        return neighbors(args.get("item_id"), args.get("text"), int(args.get("k", 5)))
    if name == "kb_search":
        dm = args.get("depth_min")
        dx = args.get("depth_max")
        return search_dual(args.get("band"),
                          float(dm) if dm is not None else None,
                          float(dx) if dx is not None else None,
                          int(args.get("top_k", 20)))
    if name == "kb_retrieve":
        return retrieve(args.get("query", args.get("text", "")),
                       args.get("filters") or {},
                       int(args.get("top_k", 10)))
    if name == "kb_fragments":
        return fragments(args.get("query", args.get("text", "")),
                        args.get("filters") or {},
                        int(args.get("top_k", 8)))
    if name == "kb_sparks":
        return sparks(args.get("status"), int(args.get("limit", 500)))
    if name == "kb_add_spark":
        return add_spark(args.get("content"), args.get("title"),
                        args.get("tags"), args.get("source", "manual"))
    if name == "kb_update_spark":
        return update_spark(args.get("spark_id"), args.get("content"),
                           args.get("title"), args.get("tags"))
    if name == "kb_hatch_spark":
        return hatch_spark(args.get("spark_id"), args.get("title"),
                          args.get("axis_domain"),
                          bool(args.get("run_closure", True)),
                          float(args.get("hit_threshold", 4.0)))
    if name == "kb_draft_hatch":
        return draft_hatch(args.get("spark_id"), args.get("title"),
                           args.get("axis_domain"),
                           bool(args.get("run_closure", True)),
                           float(args.get("hit_threshold", 4.0)))
    if name == "kb_commit_hatch":
        return commit_hatch(args.get("spark_id"), args.get("content"),
                            args.get("title"), args.get("axis_domain"),
                            float(args.get("hit_threshold", 4.0)))
    if name == "kb_spark_clusters":
        return {"clusters": spark_clusters(int(args.get("top_k", 8)),
                                          int(args.get("min_shared", 2)),
                                          float(args.get("min_jac", 0.0)))}
    if name == "kb_hatch_stats":
        return hatch_stats()
    if name == "kb_health":
        return health()
    if name == "kb_edges":
        return {"edges": list_edges(args.get("status"))}
    if name == "kb_position":
        return position(args.get("text", ""))
    if name == "kb_calibrate":
        return calibrate(args.get("item_id"))
    if name == "kb_reconcile":
        return reconcile(int(args.get("item_id")), args.get("force_domain"))
    if name == "kb_state":
        return state()
    if name == "kb_mode":
        return set_mode(args.get("mode", "heuristic"))
    if name == "kb_schema":
        return schema()
    if name == "kb_relate":
        return relate(args.get("item_id"), args.get("text"))
    if name == "kb_context":
        return context(args.get("query", ""),
                       int(args.get("top_k", 5)),
                       bool(args.get("include_edges", True)),
                       int(args.get("max_chars", 2200)))
    if name == "kb_traverse":
        return traverse(args.get("start_id"),
                       int(args.get("hops", 2)), args.get("kind"))
    if name == "kb_article":
        return get_article(args.get("item_id"))
    if name == "kb_update":
        return update_article(args.get("item_id"),
                             args.get("title", ""), args.get("content", ""))
    if name == "kb_reload":
        return reload_article(args.get("item_id"))
    if name == "kb_backlinks":
        return backlinks(args.get("item_id"))
    if name == "kb_link":
        return link(args.get("src_id"), args.get("dst_id"))
    if name == "kb_axes":
        return axes()
    if name == "kb_import_axes":
        return import_axes(args.get("path"))
    if name == "kb_similar":
        return semantic(args.get("text", ""), int(args.get("k", 5)))
    if name == "kb_suggest_links":
        return suggest_links(int(args.get("k", 8)),
                             float(args.get("min_score", 0.28)),
                             int(args.get("min_shared", 1)))
    if name == "kb_delete":
        return delete(args.get("item_id"), bool(args.get("backup", True)))
    if name == "kb_backup":
        return backup(args.get("reason", "manual"))
    return {"error": f"unknown tool: {name}"}


def axis_domain_distribution():
    """按学科标签(axis_domain)聚合条目数，供 Skill『数据驱动定轴』判冷暖使用。

    这是 KB 拥有的查询——Skill 只调用本函数，不再直接对 items 表跑裸 SQL，
    从而保证 KB 存储层的独立与纯洁（查询封装在 KB 内部）。
    """
    con = store.connect()
    try:
        rows = con.execute(
            "SELECT axis_domain, COUNT(*) c FROM items "
            "WHERE axis_domain IS NOT NULL AND axis_domain <> '' "
            "GROUP BY axis_domain ORDER BY c DESC"
        ).fetchall()
    finally:
        con.close()
    return [{"domain": r[0], "count": r[1]} for r in rows]
