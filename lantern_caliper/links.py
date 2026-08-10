# -*- coding: utf-8 -*-
"""知识图谱候选边、硬链/软链、跨域桥接与高可信关联发现。"""

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

def gen_edge(item_id):
    """偏移 → 知识图谱候选边。卡尺管发现，图谱管确定。"""
    con = connect()
    try:
        th = get_threshold(con)
        row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return {"ok": False, "msg": "条目不存在"}
        it = _row_to_item(con, row, th)
        if not it["collision"]:
            log(con, item_id, "system",
                f"「{it['title']}」偏移 {it['offset']} 未超阈值 {th}，无需生成候选边。")
            return {"ok": False, "msg": f"未碰撞（偏移 {it['offset']} ≤ 阈值 {th}）"}

        target = best_band_for(it["vernier"])
        if target["name"] == it["band"]:
            log(con, item_id, "system",
                f"「{it['title']}」偏移大但最匹配领域仍是 {target['name']}，"
                f"疑为主尺置信不足（conf={it['main_conf']}），建议复查分类而非连边。")
            return {"ok": False, "msg": "最匹配领域未变，建议复查主尺分类"}

        kind = "logic-isomorphism" if it["offset"] > 0 else "under-formalized"
        try:
            con.execute(
                "INSERT INTO edges(src_item,src_band,dst_band,kind,offset_ld,status,created_at)"
                " VALUES(?,?,?,?,?,'candidate',?)",
                (item_id, it["band"], target["name"], kind, it["offset"], time.time()),
            )
            msg = (f"阳生阴：「{it['title']}」实测演绎深度 {it['vernier']} vs "
                   f"{it['band']}典型 {it['typical']} → 偏移 {it['offset']} → "
                   f"候选边 [{kind}] → {target['name']}")
        except sqlite3.IntegrityError:
            msg = f"「{it['title']}」→ {target['name']} 的候选边已存在，未重复生成。"
        log(con, item_id, "yang->yin", msg)
        return {"ok": True, "msg": msg}
    finally:
        con.commit(); con.close()

def list_edges():
    """候选边 + 失效判定。

    edges 里存的是「入库那一刻」的快照。条目后来被重新定位（后台补算把
    启发式换成模型读数、或人工改了正文）之后，当年那条"它其实更像 X 学科"
    的推断可能早就不成立了 —— 再画出来就是完全不可能的关联。
    这里逐条回算一遍，不成立的打上 stale 和原因，由前端默认隐藏。
    """
    con = connect()
    th = get_threshold(con)
    rows = con.execute(
        "SELECT e.*, i.title FROM edges e JOIN items i ON i.id=e.src_item "
        "ORDER BY e.id DESC").fetchall()
    items = {r["id"]: _row_to_item(con, r, th)
             for r in con.execute("SELECT * FROM items")}
    con.close()

    out = []
    for r in rows:
        e = dict(r)
        e["stale"] = False
        e["stale_why"] = ""
        it = items.get(e["src_item"])
        if e.get("status") == "candidate":
            if it is None:
                e["stale"], e["stale_why"] = True, "源条目已不存在"
            elif not it["collision"]:
                e["stale"] = True
                e["stale_why"] = (f"「{it['title']}」现在偏移只有 {it['offset']}"
                                  f"（阈值 {th}），已不算异常")
            else:
                target = best_band_for(it["vernier"])["name"]
                if target == it["band"]:
                    e["stale"] = True
                    e["stale_why"] = f"重算后最匹配的仍是本学科 {it['band']}"
                elif target != e["dst_band"]:
                    e["stale"] = True
                    e["stale_why"] = (f"重算后更像「{target}」，"
                                      f"不再是「{e['dst_band']}」")
        if it is not None:
            e["cur_offset"] = it["offset"]
            e["cur_band"] = it["band"]
        out.append(e)
    return out

def set_edge_status(edge_id, status):
    con = connect()
    con.execute("UPDATE edges SET status=? WHERE id=?", (status, edge_id))
    row = con.execute("SELECT e.*, i.title FROM edges e JOIN items i ON i.id=e.src_item "
                      "WHERE e.id=?", (edge_id,)).fetchone()
    if row:
        verb = "采纳并写入知识图谱" if status == "accepted" else "驳回"
        log(con, row["src_item"], "system",
            f"候选边「{row['title']}」→{row['dst_band']} 已{verb}。")
    con.commit(); con.close()
    return {"ok": True}

def parse_links(content):
    """解析正文里的 [[标题]] 互链标记，返回标题列表。"""
    return re.findall(r"\[\[([^\]]+)\]\]", content or "")

def resolve_title_conn(con, target):
    """解析 [[目标]]：优先稳定 id，其次别名（防改标题断链），最后标题精确/模糊。"""
    target = (target or "").strip()
    if not target:
        return None
    if target.isdigit():                      # [[12]] 直接按 id
        row = con.execute("SELECT id FROM items WHERE id=?",
                          (int(target),)).fetchone()
        if row:
            return row["id"]
    # 别名（创建时固化，重命名标题不影响）> 当前标题
    row = con.execute(
        "SELECT id FROM items WHERE alias=? OR title=?", (target, target)).fetchone()
    if row:
        return row["id"]
    rows = con.execute("SELECT id FROM items WHERE title LIKE ? OR alias LIKE ?",
                       (f"%{target}%", f"%{target}%")).fetchall()
    return rows[0]["id"] if rows else None

def set_links_for_item(con, item_id, content):
    """按正文 [[标题]] 重建该条目的「硬链」（显式互链）。

    只重写 kind='hard' 的源链，保留 kind='soft' 的共现软链（由 suggest_links 写入），
    避免每次保存把自动共现边一并抹掉。"""
    titles = parse_links(content)
    dst = set()
    for t in titles:
        d = resolve_title_conn(con, t)
        if d and d != item_id:
            dst.add(d)
    con.execute("DELETE FROM links WHERE src_item_id=? AND kind='hard'", (item_id,))
    for d in dst:
        con.execute(
            "INSERT OR IGNORE INTO links(src_item_id,dst_item_id,created_at,kind)"
            " VALUES(?,?,?,?)", (item_id, d, time.time(), "hard"))

def add_link(src, dst, kind="hard"):
    con = connect()
    con.execute("INSERT OR IGNORE INTO links(src_item_id,dst_item_id,created_at,kind)"
                " VALUES(?,?,?,?)", (int(src), int(dst), time.time(), kind))
    con.commit(); con.close()
    return {"ok": True, "src": src, "dst": dst}

def remove_link(src, dst):
    con = connect()
    con.execute("DELETE FROM links WHERE src_item_id=? AND dst_item_id=?",
                (int(src), int(dst)))
    con.commit(); con.close()
    return {"ok": True, "src": src, "dst": dst}

def list_links():
    con = connect()
    rows = con.execute(
        "SELECT src_item_id, dst_item_id, kind, evidence, confirmed, provenance FROM links").fetchall()
    con.close()
    return [{"src": r["src_item_id"], "dst": r["dst_item_id"],
             "kind": r["kind"], "evidence": r["evidence"],
             "confirmed": r["confirmed"],
             "provenance": r["provenance"] or ("author" if r["kind"] == "hard" else "cooccur")}
            for r in rows]

def unresolved_links():
    """返回正文中 [[目标]] 但库里解析不到的「虚节点」候选（供图谱显示未写文章）。"""
    con = connect()
    rows = con.execute("SELECT id, title, content FROM items").fetchall()
    con.close()
    out = []
    for r in rows:
        for t in parse_links(r["content"]):
            t = t.strip()
            if not t:
                continue
            tmp = connect()
            did = resolve_title_conn(tmp, t)
            tmp.close()
            if not did:
                out.append({"src_id": r["id"], "src_title": r["title"], "target": t})
    return out

def backlinks(item_id):
    """谁引用了这条（入链）。仅含作者手写的 [[...]] 硬链，不含引擎软链——
    软链是对称相似关系、没有引用方向语义，绝不能算作「被引用」，否则就是无中生有。"""
    con = connect()
    rows = con.execute(
        "SELECT i.id, i.title FROM links l JOIN items i ON i.id=l.src_item_id "
        "WHERE l.dst_item_id=? AND l.kind='hard'", (item_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

def outlinks(item_id):
    """这条引用了谁（出链）。仅含作者手写的 [[...]] 硬链。"""
    con = connect()
    rows = con.execute(
        "SELECT i.id, i.title FROM links l JOIN items i ON i.id=l.dst_item_id "
        "WHERE l.src_item_id=? AND l.kind='hard'", (item_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

def linked_neighbors(item_id, k=8):
    """返回与 item_id 经 links 直接相连的条目（硬链 + 软链，双向），附关系元数据。
    这是图谱「相邻知识」与阅读页「相关条目」的推荐数据源——引擎自主发现的关系，
    默认已接入图谱、无需用户确认；用户只在发现明显错误时被动移除。
    排序：作者互链(hard) 优先，其次 语义(semantic)，再次 共现(cooccur)。"""
    con = connect()
    rows = con.execute(
        "SELECT src_item_id,dst_item_id,kind,evidence,provenance,confirmed FROM links "
        "WHERE src_item_id=? OR dst_item_id=?", (int(item_id), int(item_id))).fetchall()
    con.close()
    rank = {"author": 0, "hard": 0, "semantic": 1, "cooccur": 2, "bridge": 3}
    out = []
    for r in rows:
        other = r["dst_item_id"] if r["src_item_id"] == int(item_id) else r["src_item_id"]
        it = get_item(other)
        if not it:
            continue
        prov = r["provenance"] or ("author" if r["kind"] == "hard" else "cooccur")
        out.append({
            "id": it["id"], "title": it["title"], "band": it.get("band"),
            "main_pos": it.get("main_pos"), "vernier": it.get("vernier"),
            "summary": (it.get("summary") or ""),
            "kind": r["kind"], "provenance": prov,
            "confirmed": r["confirmed"],
            "evidence": json.loads(r["evidence"]) if r["evidence"] else [],
        })
    out.sort(key=lambda x: (rank.get(x["provenance"], 3), 0 if x["kind"] == "hard" else 1))
    return out[:k]

def upsert_soft_link(src, dst, score=0.0, evidence=None, provenance="cooccur", confirmed=1):
    """写入一条软边（kind='soft'）。已存在硬链则不覆盖；
    已存在软链则仅刷新证据词、保留确认态（刷新发现不再把 confirmed 打回 0）；
    不存在则新写入 confirmed=1——引擎自主判定，无需用户逐一点击确认（主体性在引擎，不在确认弹窗）。
    provenance 标识来源：cooccur=关键词共现 / semantic=语义相似。
    语义信号优先：若已存在 cooccur 且本次为 semantic，升级 provenance（更强、更罕见的发现）。
    返回是否发生写库。"""
    con = connect()
    ex = con.execute(
        "SELECT kind,confirmed,provenance FROM links WHERE src_item_id=? AND dst_item_id=?",
        (int(src), int(dst))).fetchone()
    if ex and ex["kind"] == "hard":
        con.close(); return False              # 硬链优先，软链不抢
    ev = json.dumps(evidence, ensure_ascii=False) if evidence else None
    if ex:
        # 仅更新证据词；确认态(confirmed)保留，不回退
        new_prov = ex["provenance"]
        if provenance == "semantic" and new_prov != "semantic":
            new_prov = "semantic"
        con.execute(
            "UPDATE links SET evidence=?, provenance=? WHERE src_item_id=? AND dst_item_id=? AND kind='soft'",
            (ev, new_prov, int(src), int(dst)))
    else:
        con.execute(
            "INSERT OR IGNORE INTO links(src_item_id,dst_item_id,created_at,kind,evidence,confirmed,provenance)"
            " VALUES(?,?,?,?,?,?,?)",
            (int(src), int(dst), time.time(), "soft", ev, int(confirmed), provenance))
    con.commit(); con.close()
    return True

def discover_semantic_links(threshold=None, persist=False):
    """D · 语义发现：用 embeddings 余弦相似度找出「没共享关键词、却语义相近」的条目对——
    这是 person_dashboard 那种被动镜子做不到的、独立 KB 引擎独有的智能。

    只比较向量维度一致的条目对（真实 embedding 与本地哈希向量不混比）；
    已存在任何链接（硬/软）的对跳过；通过门槛的作为 provenance='semantic' 软边写入。

    门槛自适应：真实 embedding 在线（LLM_OK）时用 0.62——此时语义信号可靠，
    能捞出"无共享关键词却相关"的条目对；本地哈希兜底时余弦≈关键词重叠（与共现重复且更噪），
    于是抬到 0.92，只抓近重复，避免灌入一堆弱关联污染图谱。"""
    if threshold is None:
        threshold = 0.62
    # 暂停开关：语义相似度依赖可信嵌入；当前嵌入退化（语义分数与真实词重叠矛盾，
    # 会制造跨主题 0.9+ 假链），故默认关闭语义链自动生成，避免污染图谱。
    # 重新开启前须先修复嵌入（换可信模型并重建向量），再置 semantic_links_enabled=1。
    if get_meta("semantic_links_enabled", "0") != "1":
        return {"suggestions": [], "threshold": threshold,
                "note": "语义链接已暂停（嵌入暂不可信，semantic_links_enabled=0）。"}
    items = list_items()["items"]
    by_id = {it["id"]: it for it in items}
    con = connect()
    vecs = {r["item_id"]: json.loads(r["vec"])
            for r in con.execute("SELECT item_id,vec FROM embeddings")}
    linked = {tuple(sorted((r["src_item_id"], r["dst_item_id"])))
              for r in con.execute("SELECT src_item_id,dst_item_id FROM links")}
    con.close()
    ids = [i for i in by_id if i in vecs]
    # 语义发现的唯一价值是「无共享关键词也能连」——这只有在真实 embedding 在线时才成立。
    # 库里可能混有本地哈希向量（256 维）；只跳过那一组、不让它污染真实向量组：
    # 仅当「全部」向量都是本地哈希（即库里没有任何真实 embedding）时才整体跳过，
    # 否则按维度分组，循环内的 len(va)!=len(vb) 已自动跳过跨维 pair。
    # 仅当真实 embedding 接口在线（配置可用且未熔断）才做语义发现；
    # 否则向量来自本地哈希/对话兜底，判别力差（实测产生跨主题 0.9+ 假相似），
    # 必须跳过，否则会向图谱灌入误连（即用户看到的「乱」）。
    if not (LLM_OK and not _llm.breaker_state()["open"]):
        return {"suggestions": [], "threshold": threshold,
                "note": "真实 embedding 接口不可用（未配置/已熔断），语义发现跳过（避免误连）。"}
    # 库内若全为本地哈希向量（256 维），语义信号等价于关键词重叠，亦跳过。
    if vecs and all(len(v) == 256 for v in vecs.values()):
        return {"suggestions": [], "threshold": threshold,
                "note": "全部为本地哈希向量（无真实 embedding），语义发现跳过。"}
    out = []
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if tuple(sorted((a, b))) in linked:
                continue
            va, vb = vecs[a], vecs[b]
            if len(va) != len(vb):            # 维度不一致（本地向量 vs 真实 embedding）不混比
                continue
            dot = sum(x * y for x, y in zip(va, vb))
            na = math.sqrt(sum(x * x for x in va)) or 1.0
            nb = math.sqrt(sum(y * y for y in vb)) or 1.0
            sim = dot / (na * nb)
            if sim < threshold:
                continue
            out.append({"src_id": a, "src_title": by_id[a]["title"],
                        "dst_id": b, "dst_title": by_id[b]["title"],
                        "score": round(sim, 3), "cross_band":
                        by_id[a].get("band") != by_id[b].get("band")})
            if persist:
                upsert_soft_link(a, b, sim, [f"语义相似 {sim:.2f}"], provenance="semantic")
    out.sort(key=lambda x: -x["score"])
    return {"suggestions": out, "threshold": threshold}

def confirm_soft_link(src, dst):
    """用户确认一条软边 → 标记 confirmed=1（仍保留 kind='soft' 以示来源）。"""
    con = connect()
    con.execute(
        "UPDATE links SET confirmed=1 WHERE src_item_id=? AND dst_item_id=? AND kind='soft'",
        (int(src), int(dst)))
    con.commit(); con.close()
    return {"ok": True}

def dismiss_soft_link(src, dst):
    """用户忽略一条软边 → 删除（下次 refresh 可能再次提出，属预期）。"""
    con = connect()
    con.execute(
        "DELETE FROM links WHERE src_item_id=? AND dst_item_id=? AND kind='soft'",
        (int(src), int(dst)))
    con.commit(); con.close()
    return {"ok": True}

def refresh_soft_links():
    """重算全库关联软边（可在后台默默跑，不卡前台）：同时跑
    ① 关键词共现（suggest_links, provenance='cooccur'）
    ② 语义相似（discover_semantic_links, provenance='semantic'）
    ③ 跨簇桥接（discover_bridge_links, provenance='bridge'）——异主题但共核心概念
    经 _discovery_lock 串行化，避免与写后自动发现或周期扫描并发重算互相踩。
    返回细分计数；**不在此处写 auto_log**（由调用方 sweeper / 按钮统一记审计）。"""
    sig = enforce_signal_guard()        # 重算前先据信号质量自动挂起/恢复语义链
    with _discovery_lock:
        co = suggest_links(persist=True)
        se = discover_semantic_links(persist=True)
        br = discover_bridge_links(persist=True)
    return {"ok": True,
            "written": len(co.get("suggestions", [])) + len(se.get("suggestions", [])) + br.get("written", 0),
            "cooccur_written": len(co.get("suggestions", [])),
            "semantic_written": len(se.get("suggestions", [])),
            "bridge_written": br.get("written", 0),
            "dropped_noise": co.get("dropped_noise", 0),
            "dropped_generic": co.get("dropped_generic", 0),
            "signal": sig}

def summarize_links():
    """统计当前关联全貌，供自动核对心跳文案与前端概览用。"""
    links = list_links()
    cnt = {"hard": 0, "cooccur": 0, "semantic": 0, "unconfirmed": 0, "confirmed": 0}
    for l in links:
        if l["kind"] == "hard":
            cnt["hard"] += 1
        else:
            cnt[l["provenance"]] = cnt.get(l["provenance"], 0) + 1
            if l["confirmed"]:
                cnt["confirmed"] += 1
            else:
                cnt["unconfirmed"] += 1
    return cnt

def _topic_terms(text):
    """抽出可用于判断「两条到底有没有共同话题」的词。

    直接切二元组会造出「然成」「上必」这种跨词边界的碎片，
    再配上人人都写的「因为/所以」，两条毫不相干的东西也能"很像"。
    所以这里反过来做：先把虚字和标点全部当分隔符，
    剩下的连续实字块（≥2 字）才算话题词，并附带其内部二元组用于近似匹配。
    """
    terms = set()
    for seg in re.split(r"[^\u4e00-\u9fffA-Za-z0-9]+", text or ""):
        if not seg:
            continue
        if not _CJK.match(seg[0]):                 # 英文/数字整体保留
            if len(seg) >= 3 and not seg.isdigit():
                terms.add(seg.lower())
            continue
        buf = ""
        for ch in seg + "\u0000":
            if "\u4e00" <= ch <= "\u9fff" and ch not in _FUNC_CH:
                buf += ch
            else:
                if len(buf) >= 2:
                    if buf not in _STOP_TERM:
                        terms.add(buf)
                    for i in range(len(buf) - 1):  # 块内二元组，容忍"动量守恒"vs"动量守恒定律"
                        g = buf[i:i + 2]
                        if g not in _STOP_TERM:
                            terms.add(g)
                buf = ""
    return terms

def _grow_common(term, sa, sb, cap=8):
    """把「验观」这类跨词碎片还原成「实验观测」—— 只为让理由读得懂。

    向两侧各扩一个字，条件是扩完后两条原文里都还在、且新字不是虚字。
    """
    cur = term
    while len(cur) < cap:
        i = sa.find(cur)
        if i < 0:
            break
        grown = None
        if i + len(cur) < len(sa):
            ch = sa[i + len(cur)]
            if "\u4e00" <= ch <= "\u9fff" and ch not in _FUNC_CH and (cur + ch) in sb:
                grown = cur + ch
        if grown is None and i > 0:
            ch = sa[i - 1]
            if "\u4e00" <= ch <= "\u9fff" and ch not in _FUNC_CH and (ch + cur) in sb:
                grown = ch + cur
        if grown is None:
            break
        cur = grown
    return cur

def _tag_set(v):
    """tags 在库里是逗号分隔的字符串，不是列表 —— 直接 set() 会拆成单字。"""
    if not v:
        return set()
    if isinstance(v, (list, tuple, set)):
        return {str(x).strip() for x in v if str(x).strip()}
    return {t.strip() for t in re.split(r"[,，;；\s]+", str(v)) if t.strip()}

def _topic_segments(text):
    """抽「真词」：连续的 ≥2 字实义块 + ≥3 字英文词，块内**不再**拆二元组。

    和 _topic_terms 的关键区别：不再把「动量守恒」切成「动量」「量守」。
    旧逻辑下，两条毫不相干的文章只要都写过「动量」二字就能"共享"，
    于是 0.8 的假相似满天飞。这里只认整词 —— 两条必须出现同一串
    ≥2 字实义词，才算真的沾边。内部二元组只在 _grow_common 里用于
    把"验观"还原成"实验观测"做展示，不参与判定。
    """
    segs = set()
    for seg in re.split(r"[^\u4e00-\u9fffA-Za-z0-9]+", text or ""):
        if not seg:
            continue
        if not _CJK.match(seg[0]):                  # 英文 / 数字整词保留
            if len(seg) >= 3 and not seg.isdigit():
                segs.add(seg.lower())
            continue
        buf = ""
        for ch in seg + "\u0000":
            if "\u4e00" <= ch <= "\u9fff" and ch not in _FUNC_CH:
                buf += ch
            else:
                if len(buf) >= 2 and buf not in _STOP_TERM:
                    segs.add(buf)
                buf = ""
    return segs

def _about(term, body, body_title):
    """这个词是不是"真的在讲"，而不只是顺嘴提一次。

    出现在标题里 → 可信；正文出现 ≥2 次 → 可信（是条主线）；
    只出现 1 次时：≥3 字的具体词（如"重叠窗口""embedding"）仍可信，
    2 字碎片单次出现偏巧合，不予采信。靠"多重性 + Dice"再兜底。
    英文词统一转小写比较，避免 RAG/rag 这类大小写漏配。
    """
    term = (term or "").lower()
    body_l = (body or "").lower()
    title_l = (body_title or "").lower()
    if term and term in title_l:
        return True
    n = body_l.count(term)
    if n >= 2:
        return True
    return n >= 1 and len(term) >= 3

def _idf_cos(A, B, df, N):
    """IDF 加权余弦：只在"有区分度的词"上比相似，虚词 / 通用词不掺和。"""
    if not A or not B:
        return 0.0
    def w(t):
        return math.log(N / max(1, df[t]))
    va = {t: w(t) for t in A}
    vb = {t: w(t) for t in B}
    num = sum(va[t] * vb[t] for t in (A & B))
    na = math.sqrt(sum(x * x for x in va.values())) or 1.0
    nb = math.sqrt(sum(x * x for x in vb.values())) or 1.0
    return num / (na * nb)

def suggest_links(k=8, min_score=0.0, min_shared=2, persist=False, anchor=None):
    """「该连未连」：意思上**真有共同话题**、却还没互链的条目对。

    anchor：传入某条目 id 时，只返回与该条目相关的候选对（用于「以新孵化节点
    为中心」重织图谱，而不扫描全库）。其余 R0–R3 门槛与全量扫描完全一致。

    persist=True 时，把通过的候选写入 links(kind='soft',confirmed=0,evidence=共享词)，
    作为知识图谱的「软边」——用户可在图谱里一键确认/忽略，而不是被悄悄连上。

    第一性原理 —— 一条"该连未连"的候选，必须同时过四道关：

      R0 预处理：两条都还在、都还没连过、都有向量。
      R1 实质共同话题（specificity + 多重性）：
          共享词必须是「真词」（≥2 字实义块 / ≥3 字英文），且
            · 有区分度：全库文档频 df ≤ 2（只在这两条里出现，不算人人都写）；
            · 非空洞：不在通用词黑名单（系统/模型/理解/解决…"因为所以"的近亲）；
            · 真在讲：至少一条的标题或正文 ≥2 次出现它。
          而且共享的"证据词"至少要有 2 个（1 个太容易是巧合）；
          或者 1 个证据词 + 1 个共同标签（两条独立线索凑够 2）。
      R2 重叠相干（coherence）：两条"有区分度词"集合的 Dice 系数 ≥ 0.08，
          即共同话题至少占较窄那条笔记特色词的 8%——防止两篇长文各提一次就"很像"。
      R3 跨领域加严：分属不同学科带的，假阳性最凶（不同领域都写"模型"），
          于是要求证据词 ≥ 3 或 Dice ≥ 0.12 才放。

    全部用词的统计门槛（df、Dice）而非写死的余弦，所以库越大越准；
    没有真关系的条目对，宁可返回空，也绝不拿"措辞像"糊弄。
    """
    items = list_items()["items"]
    by_id = {it["id"]: it for it in items}
    con = connect()
    vecs = {r["item_id"]: json.loads(r["vec"])
            for r in con.execute("SELECT item_id,vec FROM embeddings")}
    linked = {tuple(sorted((r["src_item_id"], r["dst_item_id"])))
              for r in con.execute("SELECT src_item_id,dst_item_id FROM links")}
    bodies = {r["id"]: (r["title"] or "") + "。" + (r["content"] or "")
              for r in con.execute("SELECT id,title,content FROM items")}
    con.close()

    # 全库"真词"文档频 → 区分度
    seg = {i: _topic_segments(bodies.get(i, "")) for i in by_id}
    df = collections.Counter()
    for t in seg.values():
        df.update(t)
    N = max(1, len(by_id))
    DF_CAP = 2                                   # 出现在 >2 篇里 = 太常见，证明不了关联
    DICE_FLOOR = 0.08
    CROSS_DICE = 0.12
    CROSS_MIN_SHARED = 3

    tags = {i: _tag_set(by_id[i].get("tags")) for i in by_id}

    def admissible(i):
        """该条里能当"证据"的词：有区分度 + 非空洞 + 真在讲。"""
        body = bodies.get(i, "")
        title = by_id[i].get("title") or ""
        return {t for t in seg[i]
                if df[t] <= DF_CAP and t not in _GENERIC_BAN and _about(t, body, title)}

    adm = {i: admissible(i) for i in by_id}
    adm_tags = {i: {t for t in tags[i] if t not in _GENERIC_BAN} for i in by_id}

    ids = [i for i in by_id if i in vecs]
    pairs, dropped_noise, dropped_generic = [], 0, 0
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if tuple(sorted((a, b))) in linked:    # 已连过不重复提
                continue
            if anchor is not None and anchor not in (a, b):  # 仅围绕新节点
                continue
            cross = by_id[a].get("band") != by_id[b].get("band")
            shared_spec = adm[a] & adm[b]
            shared_tags = adm_tags[a] & adm_tags[b]
            raw_shared = seg[a] & seg[b]           # 没过门槛前的原始重合（用于判"一眼错"）
            # R1 多重性
            evidence = len(shared_spec) + len(shared_tags)
            if evidence < int(min_shared):
                dropped_noise += 1
                if raw_shared and not shared_spec and not shared_tags:
                    dropped_generic += 1           # 只靠通用词硬凑的（跨领域一眼错）
                continue
            # R2 重叠相干
            dice = 2 * len(shared_spec) / ((len(adm[a]) + len(adm[b])) or 1)
            if dice < DICE_FLOOR:
                dropped_noise += 1
                continue
            # R3 跨领域加严
            if cross and (len(shared_spec) < CROSS_MIN_SHARED and dice < CROSS_DICE):
                dropped_noise += 1
                continue
            sem = _idf_cos(adm[a], adm[b], df, N)
            if sem < float(min_score):
                dropped_noise += 1
                continue
            # 排名：证据词数 > 标签数 > 重叠相干 > 语义；跨领域且稳过 R3 的给点奖励
            rank = (10 * len(shared_spec) + 5 * len(shared_tags)
                    + 50 * dice + 5 * sem
                    + (3 if (cross and len(shared_spec) >= CROSS_MIN_SHARED) else 0))
            pairs.append((rank, sem, a, b, shared_spec, shared_tags, dice, cross))
    pairs.sort(key=lambda x: -x[0])

    out = []
    for rank, sem, a, b, shared_spec, shared_tags, dice, cross in pairs[:int(k)]:
        ia, ib = by_id[a], by_id[b]
        grown = sorted(shared_spec, key=lambda t: (-df[t], len(t)))[:4]
        words = list(shared_tags)[:3] + [w for w in grown if w not in shared_tags][:4]
        common = "、".join(words[:4])
        # 为什么该连：优先说"都围绕 X 讲"，否则说"共享标签 X"
        if shared_spec:
            why = f"都围绕「{common}」展开"
        else:
            why = f"共享标签「{common}」"
        why += (f"，且分属{ia.get('band')}与{ib.get('band')}"
                if cross else f"，同属{ia.get('band')}")
        out.append({
            "src_id": a, "src_title": ia["title"], "src_band": ia.get("band"),
            "dst_id": b, "dst_title": ib["title"], "dst_band": ib.get("band"),
            "score": round(rank, 2),              # 现在是"证据强度"，不是假余弦
            "semantic": round(sem, 3),
            "dice": round(dice, 3),
            "shared": words[:4],
            "cross_band": cross,
            "why": why,
        })
        if persist:
            upsert_soft_link(a, b, rank, words[:4])
    # 孤岛统计：帮用户判断这个库到底连没连起来
    connected = set()
    for pair in linked:
        connected |= set(pair)
    isolated = [{"id": i["id"], "title": i["title"]}
                for i in items if i["id"] not in connected]
    return {"suggestions": out, "total_candidates": len(pairs),
            "dropped_noise": dropped_noise,      # 被判定为「完全不可能 / 只是措辞像」的对数
            "dropped_generic": dropped_generic,  # 其中：只靠通用词硬凑的（跨领域一眼错）
            "isolated": isolated, "item_count": len(items),
            "linked_pairs": len(linked)}

def discover_bridge_links(persist=False, min_shared=2):
    """跨簇桥接：连接「分属不同学科带、却共享核心概念词」的条目对。

    这是灯笼相对工作台的差异能力——工作台纯靠作者 [[...]] 互链，
    我们让引擎自动发现「跨主题的桥」，默认接入图谱（confirmed=1，透明标注 provenance='bridge'），
    不必用户逐一确认（契合「主体性在引擎、不增加用户操作」）。

    与第一性原理一致：桥必须有真关系，绝不拿「措辞像」糊弄。
      · 只取跨 band 的条目对（同带归 semantic / cooccur 负责，避免和它们重复连线）；
      · 共享词须为「有区分度 + 非空洞 + 真在讲」的真词（复用 suggest_links 的 admissible）；
      · 共享真词 ≥ min_shared（默认 2，桥要至少两个共同概念，一个太像巧合）——
        这是主门控；IDF 越高的共有词越可信，按 IDF 和排序。
    注：本库 _topic_segments 切分偏细，单篇 admissible 词可达数百，使 Dice 分母过大、
    重叠相干度恒偏低而失效；故桥接不依赖 Dice，改用「有区分度共享词数 + IDF 权重」
    作为可靠门控（这俩在过度切分下仍成立）。
    语义相似只会把「同主题」的聚到一起；桥专补它漏掉的「异主题但共核心概念」，
    于是图谱才长出跨簇交叉，而非一团同色块。
    """
    items = list_items()["items"]
    by_id = {it["id"]: it for it in items}
    con = connect()
    bodies = {r["id"]: (r["title"] or "") + "。" + (r["content"] or "")
              for r in con.execute("SELECT id,title,content FROM items")}
    linked = {tuple(sorted((r["src_item_id"], r["dst_item_id"])))
              for r in con.execute("SELECT src_item_id,dst_item_id FROM links")}
    con.close()

    seg = {i: _topic_segments(bodies.get(i, "")) for i in by_id}
    df = collections.Counter()
    for t in seg.values():
        df.update(t)
    N = max(1, len(by_id))

    def admissible(i):
        body = bodies.get(i, ""); title = by_id[i].get("title") or ""
        return {t for t in seg[i]
                if df[t] <= 2 and t not in _GENERIC_BAN and _about(t, body, title)}

    adm = {i: admissible(i) for i in by_id}
    ids = list(by_id)
    bridges = []
    written = 0
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if by_id[a].get("band") == by_id[b].get("band"):
                continue                      # 同带不算桥
            if tuple(sorted((a, b))) in linked:
                continue
            shared = adm[a] & adm[b]
            if len(shared) < int(min_shared):
                continue
            idf_sum = sum((math.log(N / (df[t] + 1)) + 1) for t in shared)
            if idf_sum < 2.0:                  # 至少约两个稀有共有概念，挡掉偶然共现
                continue
            dice = 2 * len(shared) / ((len(adm[a]) + len(adm[b])) or 1)
            rank = 10 * len(shared) + idf_sum
            grown = sorted(shared, key=lambda t: (-df[t], len(t)))[:4]
            why = (f"都围绕「{'、'.join(grown)}」展开，"
                   f"却分属 {by_id[a].get('band') or '—'} 与 {by_id[b].get('band') or '—'}——跨主题的桥")
            bridges.append({"src_id": a, "dst_id": b,
                            "src_band": by_id[a].get("band"), "dst_band": by_id[b].get("band"),
                            "shared": grown, "dice": round(dice, 3),
                            "score": round(rank, 2), "why": why})
            if persist:
                if upsert_soft_link(a, b, rank, grown, provenance="bridge", confirmed=1):
                    written += 1
    bridges.sort(key=lambda x: -x["score"])
    return {"written": written, "bridges": bridges,
            "dropped_same_band": sum(1 for ai in range(len(ids)) for bi in range(ai + 1, len(ids))
                                     if by_id[ids[ai]].get("band") == by_id[ids[bi]].get("band"))}

