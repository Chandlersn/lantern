# -*- coding: utf-8 -*-
"""全文（FTS）、切片、向量嵌入与语义检索。"""

import json
import math
import os
import re
import sqlite3
import time
import hashlib
import collections
import binascii
import concurrent.futures
import threading
import sys
import subprocess
import ctypes
from ctypes import wintypes
from .core import *

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

def rebuild_chunks():
    """为全部条目重建片段索引（重切分 + 本地向量）。换切块策略或存量迁移时调用。"""
    items = list_items()["items"]
    con = connect()
    done = 0
    for it in items:
        _write_chunks(con, it["id"], it.get("content") or "")
        con.commit()
        done += 1
    con.close()
    return {"ok": True, "done": done}

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

def rebuild_embeddings():
    """用 embed_text（模型 embedding 优先、本地哈希兜底）为全部条目重建向量。
    内容哈希缓存由 llm.embed 负责，重复重建不重复计费。
    注意：embed_text 可能调慢模型，每篇写后立即提交，避免跨模型调用持有写锁。"""
    items = list_items()["items"]
    con = connect()
    done = failed = 0
    dim = None
    for it in items:
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
    con.close()
    return {"ok": True, "done": done, "failed": failed, "dim": dim}

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

def embed_text(text):
    """优先用真实 embedding 接口；熔断中或不可用时退回本地哈希向量。"""
    if LLM_OK and not _llm.breaker_state()["open"]:
        try:
            v = _llm.embed(text, timeout=20)
            if v:
                return v
        except Exception:                              # noqa: BLE001
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

