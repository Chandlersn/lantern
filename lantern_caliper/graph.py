# -*- coding: utf-8 -*-
"""知识图谱构建与库健康自检。"""

import json
import math

def detect_health(sim_threshold=0.90):
    """E2 · 健康自检：用高余弦找近重复 / 高耦合条目对（疑似冗余），
    未上报过的推入反馈收件箱（自我审查建议）并写 auto_log；返回新发现的条目对。
    已上报的靠 meta 里的 health_reported 集合去重，避免反复打扰。"""
    items = list_items()["items"]
    by_id = {it["id"]: it for it in items}
    con = connect()
    vecs = {r["item_id"]: json.loads(r["vec"])
            for r in con.execute("SELECT item_id,vec FROM embeddings")}
    # 信号守卫：嵌入是否可信。退化时语义相似类反馈不可信——直接跳过整轮推送，
    # 既不入库也不弹窗，避免假阳性误报占用收件箱。
    sig = signal_integrity()
    signal_ok = sig.get("status") == "healthy"
    if not signal_ok:
        con.close()
        return {"ok": True, "found": [], "skipped": "signal_degraded"}
    reported = set()
    row = con.execute("SELECT v FROM meta WHERE k='health_reported'").fetchone()
    if row and row["v"]:
        try:
            reported = set(json.loads(row["v"]))
        except (json.JSONDecodeError, TypeError):
            reported = set()
    # 用户已「标记为非重复」的条目对：健康自检永久跳过，不再打扰
    ignored = set()
    irow = con.execute("SELECT v FROM meta WHERE k='ignore_dupe_pairs'").fetchone()
    if irow and irow["v"]:
        try:
            ignored = set(tuple(p) for p in json.loads(irow["v"]))
        except (json.JSONDecodeError, TypeError):
            ignored = set()
    con.close()
    ids = [i for i in by_id if i in vecs]
    found = []
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            va, vb = vecs[a], vecs[b]
            if len(va) != len(vb):
                continue
            dot = sum(x * y for x, y in zip(va, vb))
            na = math.sqrt(sum(x * x for x in va)) or 1.0
            nb = math.sqrt(sum(y * y for y in vb)) or 1.0
            sim = dot / (na * nb)
            if sim < sim_threshold:
                continue
            key = tuple(sorted((a, b)))
            if key in reported or key in ignored:
                continue
            reported.add(key)
            found.append({"a": a, "a_title": by_id[a]["title"],
                          "b": b, "b_title": by_id[b]["title"], "sim": round(sim, 3)})
            note = "两篇语义高度相似，疑似重复或过度耦合；可在条目中合并，或在此标记为非重复。"
            push_feedback(
                0, f"{by_id[a]['title']} ↔ {by_id[b]['title']}",
                by_id[a].get("axis_domain"),
                {"type": "near_duplicate", "partner": by_id[b]["title"],
                 "partner_id": b, "self_id": a, "sim": round(sim, 3),
                 "note": note},
                severity="warn", must_revise=0, pushable=True)
    # 持久化已上报集合
    con = connect()
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('health_reported',?)",
                (json.dumps(sorted(reported)),))
    con.commit(); con.close()
    if found:
        auto_log("health",
                 f"健康自检：发现 {len(found)} 组高度相似条目"
                 + "，已推入「自我审查反馈」收件箱（待你确认是否合并）。")
    return {"ok": True, "found": found}

def build_graph():
    """构建 wiki 知识图谱数据：边来自 [[...]] 硬链 + 关键词共现软链，与 band/domain 解耦。

    返回 nodes / edges / unresolved（虚节点）/ stats。位置由前端力导布局决定，
    此处只给「关联」与「元数据」，不掺入双尺定位坐标（定位交给偏差地图）。"""
    items = list_items()["items"]          # 含 band/axis_domain/tags 等推导字段
    con = connect()
    links = con.execute(
        "SELECT src_item_id,dst_item_id,kind,evidence,confirmed,provenance FROM links").fetchall()
    con.close()
    node_map = {}
    for it in items:
        tags = [t for t in (it.get("tags") or "").split(",") if t]
        node_map[it["id"]] = {
            "id": it["id"], "title": it.get("title", ""),
            "band": it.get("band"), "axis_domain": it.get("axis_domain"),
            "tags": tags, "degree": 0, "inDegree": 0, "outDegree": 0,
        }
    # 概念不再作为图谱节点：concepts / concept_links 是后端被动存储的「概念↔文档」列表，
    # 只通过 concept_neighbors() 给文档做桥接推荐（在节点详情页展示），不混入图谱布局。
    edges = []
    for l in links:
        s, d = l["src_item_id"], l["dst_item_id"]
        if s not in node_map or d not in node_map:
            continue
        edges.append({
            "source": s, "target": d, "kind": l["kind"],
            "confirmed": l["confirmed"],
            "provenance": l["provenance"] or ("author" if l["kind"] == "hard" else "cooccur"),
            "evidence": json.loads(l["evidence"]) if l["evidence"] else [],
        })
        # 仅硬链（作者意图的 [[...]] 双向链）才有真正的引用方向；
        # 软链（语义/共现/桥接）是对称关系，source/target 顺序任意，不能计入出/入方向，
        # 否则会把引擎的对称关联强加一个不存在的「谁引用谁」。
        if l["kind"] == "hard":
            node_map[s]["outDegree"] += 1
            node_map[d]["inDegree"] += 1
        node_map[s]["degree"] += 1
        node_map[d]["degree"] += 1
    connected = {s for e in edges for s in (e["source"], e["target"])}
    isolated = [n["id"] for n in node_map.values() if n["id"] not in connected]
    return {
        "nodes": list(node_map.values()),
        "edges": edges,
        "unresolved": unresolved_links(),
        "stats": {
            "nodeCount": len(node_map),
            "edgeCount": len(edges),
            "isolatedCount": len(isolated),
        },
    }

