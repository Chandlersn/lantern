# -*- coding: utf-8 -*-
"""概念衍生层（后端桥接中间件）：概念抽取、聚合与「概念↔文档」被动列表。"""

import time

def _concept_name_ok(name):
    """概念名须是足够实义的字符串：长度 2-8，不含纯虚字。"""
    if not name or not (2 <= len(name) <= 8):
        return False
    if any(ch in _FUNC for ch in name):
        return False
    return True

def _extract_concept_names(content, top_n=5):
    """离线抽取核心概念名：词频（相邻二元组 + 实义单元）过滤虚词/虚字，取高频实义单元。"""
    toks = tokenize(content or "")
    from collections import Counter
    c = Counter()
    for t in toks:
        if len(t) >= 2 and t not in _STOP and _concept_name_ok(t):
            c[t] += 1
    for i in range(len(toks) - 1):
        bg = toks[i] + toks[i + 1]
        if len(bg) == 2 and bg not in _STOP and _concept_name_ok(bg):
            c[bg] += 1
    return [w for w, _ in c.most_common(top_n * 2)][:top_n]

def _upsert_concept_raw(name, definition, main_pos, vernier, axis_domain, source, con=None):
    """概念落库（同名聚合），返回 concept id。坐标取首次出现文章（首篇主导其领域归属）。

    con 为 None 时自行开闭连接；传入时复用（避免写事务嵌套死锁）。"""
    own = con is None
    if own:
        con = connect()
    now = time.time()
    row = con.execute("SELECT id, definition FROM concepts WHERE name=?", (name,)).fetchone()
    band = canonical_band(main_pos)
    if row:
        cid = row["id"]
        # 仅当现有定义为空时补（避免后到的低质定义覆盖首个），坐标保持首篇主导。
        if not (row["definition"] or "").strip():
            con.execute("UPDATE concepts SET definition=?, source=?, updated_at=? WHERE id=?",
                        (definition, source, now, cid))
        else:
            con.execute("UPDATE concepts SET updated_at=? WHERE id=?", (now, cid))
    else:
        cur = con.execute(
            "INSERT INTO concepts(name,definition,main_pos,vernier,axis_domain,band,source,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (name, definition, main_pos, vernier, axis_domain, band, source, now, now))
        cid = cur.lastrowid
    if own:
        con.commit(); con.close()
    return cid

def link_concepts_for_item(con, item_id, content, item, top_n=5):
    """写后自动长概念（离线、本地、快）：抽核心概念→落库→与文章双向链。复用传入 con。"""
    main_pos = float(item.get("main_pos") or 50.0)
    vernier = float(item.get("vernier") or 45.0)
    axis_domain = item.get("axis_domain")
    now = time.time()
    for name in _extract_concept_names(content, top_n):
        cid = _upsert_concept_raw(name, "", main_pos, vernier, axis_domain, "heuristic", con=con)
        con.execute(
            "INSERT OR IGNORE INTO concept_links(concept_id,item_id,weight,created_at) VALUES(?,?,?,?)",
            (cid, item_id, 1.0, now))

def enrich_concepts_with_llm(item_id):
    """LLM 增强：抽精炼概念定义。失败/熔断静默跳过，不影响主流程。"""
    if not (LLM_OK and not _llm.breaker_state()["open"]):
        return
    it = get_item(item_id)
    if not it:
        return
    content = it.get("content", "")
    if not content:
        return
    try:
        sys_p = ("你是知识库的概念抽取器。从文章中抽取 3-5 个最核心的概念。"
                 "每个概念给一句中文定义（≤30字），须来自文章正文、非空泛。"
                 "只输出 JSON：{\"concepts\":[{\"name\":\"概念名\",\"definition\":\"一句定义\"}]}。")
        usr = content[:3500]
        raw, _ = _llm.chat(sys_p, usr, temperature=0.2, max_tokens=900)
        data = _llm.parse_json(raw)
        concepts = data.get("concepts", []) if isinstance(data, dict) else []
        main_pos = float(it.get("main_pos") or 50.0)
        vernier = float(it.get("vernier") or 45.0)
        axis_domain = it.get("axis_domain")
        now = time.time()
        for cc in concepts[:5]:
            name = (cc.get("name") or "").strip()
            definition = (cc.get("definition") or "").strip()
            if not name or not _concept_name_ok(name):
                continue
            cid = _upsert_concept_raw(name, definition, main_pos, vernier, axis_domain, "llm")
            con = connect()
            con.execute(
                "INSERT OR IGNORE INTO concept_links(concept_id,item_id,weight,created_at) VALUES(?,?,?,?)",
                (cid, item_id, 1.0, now))
            con.commit(); con.close()
    except Exception:                              # noqa: BLE001
        pass


def list_concepts():
    """返回所有概念（含坐标、定义、来源文章标题）。"""
    con = connect()
    rows = con.execute(
        "SELECT c.id,c.name,c.definition,c.main_pos,c.vernier,c.axis_domain,c.band,c.source "
        "FROM concepts c ORDER BY c.main_pos, c.name").fetchall()
    out = []
    for r in rows:
        links = con.execute(
            "SELECT cl.item_id, i.title FROM concept_links cl JOIN items i ON i.id=cl.item_id "
            "WHERE cl.concept_id=?", (r["id"],)).fetchall()
        out.append({
            "id": r["id"], "name": r["name"], "definition": r["definition"] or "",
            "main_pos": r["main_pos"], "vernier": r["vernier"],
            "axis_domain": r["axis_domain"], "band": r["band"], "source": r["source"],
            "items": [{"id": l["item_id"], "title": l["title"]} for l in links],
        })
    con.close()
    return out

def concept_neighbors(item_id, limit=10):
    """概念桥接推荐（后端中间件）：通过 concept_links 找与该文档共享概念的其他文档。

    返回按共享概念数降序的 [{item_id,title,shared_concepts,score}]。
    这是被动存储的「概念↔文档」列表（wiki 层），只作为桥接/推荐的依据，
    不自动画成图谱边——由节点详情页展示，人工决定是否互链。"""
    con = connect()
    my = con.execute(
        "SELECT cl.concept_id, c.name FROM concept_links cl "
        "JOIN concepts c ON c.id=cl.concept_id WHERE cl.item_id=?", (item_id,)).fetchall()
    if not my:
        con.close()
        return []
    my_ids = [m["concept_id"] for m in my]
    my_names = {m["concept_id"]: m["name"] for m in my}
    placeholders = ",".join("?" * len(my_ids))
    rows = con.execute(
        "SELECT cl.item_id AS iid, i.title AS title, cl.concept_id AS cid "
        "FROM concept_links cl JOIN items i ON i.id=cl.item_id "
        f"WHERE cl.concept_id IN ({placeholders}) AND cl.item_id != ?",
        my_ids + [item_id]).fetchall()
    con.close()
    agg = {}
    for r in rows:
        a = agg.setdefault(r["iid"], {"title": r["title"], "concepts": []})
        a["concepts"].append(my_names[r["cid"]])
    out = [{
        "item_id": iid, "title": v["title"],
        "shared_concepts": v["concepts"], "score": len(v["concepts"]),
    } for iid, v in agg.items()]
    out.sort(key=lambda x: (-x["score"], x["title"]))
    return out[:limit]

