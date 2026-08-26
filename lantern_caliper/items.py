# -*- coding: utf-8 -*-
"""知识条目 CRUD、阴阳闭环校准、导入导出与草稿。"""

import os
import re
import sqlite3
import time
import hashlib
from . import summarize as _summod

def _global_typical(con):
    """全库常规严密度 = 当前所有条目游标读数的中位数。

    单一成员领域没有\"同伴\"可对比，偏移就改用全库常规作参照，
    这样哪怕每个领域只有 1 篇，偏差地图也能看出这篇相对整个知识库的论证风格是偏严还是偏松。
    只统计现存条目（JOIN items），避免已删除条目的残留读数污染中位数。
    """
    vals = [r["value"] for r in con.execute(
        "SELECT r.value FROM readings r JOIN items i ON i.id=r.item_id "
        "WHERE r.scale='vernier'")]
    if not vals:
        return 45.0
    vals.sort()
    return round(vals[len(vals) // 2], 1)

def _registered_typical(name, gtyp=None):
    """偏差基准（最新思想）：优先学科域级注册 typical_vernier（带内视角差异），
    其次主干带注册 typical，再次全局常规。

    这样偏移基准稳定、且与地图基线同源，不再依赖「同领域同伴中位数」
    （样本少时退化、且无法体现带内视角差异）。name 为显示领域（细领域或主干带）。"""
    tv = domain_typical_vernier(name)
    if tv is not None:
        return tv
    for b in BACKBONE_BANDS:
        if b["name"] == name:
            return b["typical_vernier"]
    return gtyp if gtyp is not None else 45.0

def _row_to_item(con, row, threshold, doms=None, global_typical=None):
    r = {x["scale"]: x for x in con.execute(
        "SELECT * FROM readings WHERE item_id=?", (row["id"],))}
    main, vern = r.get("main"), r.get("vernier")
    # 容错：个别条目可能因守卫拉闸 / 迁移中途 / 手动裸录入而缺读数。
    # 缺则安全兜底，避免 list_items / refresh_soft_links 因一条不完整数据
    # 全盘崩溃（崩溃会被服务端 sweeper 的 except 静默吞掉，自动核对形同虚设）。
    if main is None:
        main = {"label": "未分类", "value": 50.0, "confidence": 0.5,
                "provider": "none", "signal_family": "none", "revised": 0}
    if vern is None:
        vern = {"value": 45.0, "confidence": 0.0,
                "provider": "none", "signal_family": "none", "revised": 0}
    band_name = (main["label"] or "").strip() or "未分类"
    if doms is None:
        doms = {d["name"]: d for d in list_domains()}
    d = doms.get(band_name) or {"center": main["value"], "typical_vernier": 45.0, "count": 1}
    band_center = d["center"]
    dcount = d.get("count", 1)
    # 领域只有 1 篇时，没有同伴可对比 → 偏移改为相对全库常规严密度
    use_global = dcount < 2 and global_typical is not None
    # 偏移基准优先下沉到学科域级（带内视角差异），回退带级，再回退全局
    axis_dom = (row["axis_domain"] if "axis_domain" in row.keys() else "") or ""
    axis_dom = axis_dom.strip()
    dom_typ = domain_typical_vernier(axis_dom)
    if dom_typ is not None:
        typical = dom_typ
    else:
        typical = global_typical if use_global else d["typical_vernier"]
    offset = round(vern["value"] - typical, 1)
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "main_pos": round(main["value"], 1),
        "band": band_name,
        "band_center": band_center,
        "typical": typical,
        "global_typical": global_typical,
        "ref_kind": "global" if use_global else "domain",
        "main_conf": main["confidence"],
        "main_provider": main["provider"],
        "main_family": main["signal_family"],
        "revised": bool(main["revised"]),
        "vernier": round(vern["value"], 1),
        "vernier_conf": vern["confidence"],
        "vernier_provider": vern["provider"],
        "vernier_family": vern["signal_family"],
        "offset": offset,
        "collision": abs(offset) > threshold,
        "direction": "positive" if offset > 0 else ("negative" if offset < 0 else "zero"),
        "axis_domain": row["axis_domain"] if "axis_domain" in row.keys() else "",
        "source_url": row["source_url"] if "source_url" in row.keys() else "",
        "summary": row["summary"] if "summary" in row.keys() else "",
        "tags": row["tags"] if "tags" in row.keys() else "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"] if "updated_at" in row.keys() else None,
    }

def _assign_disp_and_typics(items, threshold, global_typical=None):
    """统一计算每条的「显示领域 / 领域典型游标 / 偏移 / 离域典型较远标记」。

    第一性原理：偏差（偏移）必须是「相对所属领域」的，而不是相对全库一条
    水平线。不同主尺领域本就有不同的典型论证形态，所以基准必须按显示领域分别取
    —— 优先取该学科域注册的典型游标（带内视角差异），回退主干带注册值，再回退全局。
    这样地图的基准线就是"每个领域一条、高度各不相同"，而不是一条全库水平线。

    「离域典型较远」(far) 是中性注意力标记，不是缺陷判定：偏移大既可能是有意义的
    跨域洞见，也可能是分类偏差。阈值仅为注意力过滤器（可调，schema 默认 18ld）；
    当某域样本足够（≥4）时可升级为相对该域分布的 MAD，但小库下退化回全局阈值。
    """
    backbone_names = {b["name"] for b in BACKBONE_BANDS}
    raw_counts = {}
    for it in items:
        raw_counts[it["band"]] = raw_counts.get(it["band"], 0) + 1
    disp_counts = {}
    for it in items:
        bn = it["band"]
        if bn in backbone_names or raw_counts.get(bn, 0) >= 2:
            it["disp_band"] = bn
        else:
            it["disp_band"] = backbone_of(it["main_pos"])["name"]
        disp_counts[it["disp_band"]] = disp_counts.get(it["disp_band"], 0) + 1
    for it in items:
        # 偏移基准键 = 学科域（axis_domain）优先，使其真正下沉到学科域级；
        # 无学科域时退回显示领域（主干带）的典型值。
        ad = (it.get("axis_domain") or "").strip()
        typ = _registered_typical(ad or it["disp_band"], global_typical)
        it["typical"] = round(typ, 1)
        it["offset"] = round(it["vernier"] - typ, 1)
        it["collision"] = abs(it["offset"]) > threshold
        it["ref_kind"] = "domain"
        it["band_count"] = disp_counts.get(it["disp_band"], 0)
        it["direction"] = ("positive" if it["offset"] > 0
                           else "negative" if it["offset"] < 0 else "zero")
    return disp_counts

def _baseline_curve():
    """固定基准曲线：全部受控学科域按 (主干带范围, 带内 intra_band_order) 均匀铺开 center，
    连成一条平滑上升的『领域典型形式化』参考线，与库内数据无关。前端偏差地图用它画背景
    基准，使「从领域基准线偏移」成为全谱参照；中心重排消除带内倒挂后曲线单调上升。"""
    curve = []
    for b in BACKBONE_BANDS:
        bn = b["name"]; lo, hi = b["range"]
        regs = [(d.get("intra_band_order", 99), name)
                for name, d in _DOMAIN_REGISTRY.items()
                if isinstance(d, dict) and d.get("band") == bn]
        regs.sort(key=lambda x: x[0])
        n = len(regs)
        for i, (order, name) in enumerate(regs):
            c = (lo + hi) / 2 if n == 1 else lo + (hi - lo) * (i + 1) / (n + 1)
            tv = domain_typical_vernier(name)
            curve.append({"name": name, "band": bn, "center": round(c, 1),
                          "typical_vernier": tv,
                          "hidden": bool(_DOMAIN_REGISTRY[name].get("hidden", False))})
    curve.sort(key=lambda x: x["center"])
    return curve

def list_items():
    con = connect()
    th = get_threshold(con)
    rows = con.execute("SELECT * FROM items ORDER BY id").fetchall()
    doms = {d["name"]: d for d in list_domains()}
    gtyp = _global_typical(con)
    items = [_row_to_item(con, r, th, doms, gtyp) for r in rows]
    con.close()

    # —— 领域节点的"显示层"约束 + 按领域取偏差基准（第一性原理）——
    # 1) 主干学科带永远在；内容衍生细领域只有"够宽且同伴≥2"才立为独立节点，
    #    否则退回主干带（具体技术/实体降为标签，不切碎图谱）。
    # 2) 偏差基准（典型游标）按"显示领域"分别取注册值（学科域级优先、回退主干带、
    #    再回退全局）—— 不同领域基准高度不同，不画一条全库水平线。
    disp_counts = _assign_disp_and_typics(items, th, gtyp)

    bands = []
    bb_names = {b["name"] for b in BACKBONE_BANDS}
    for b in BACKBONE_BANDS:
        lo, hi = b["range"]
        bands.append({"name": b["name"], "center": b["center"],
                      "count": disp_counts.get(b["name"], 0), "backbone": True,
                      "order": b.get("order"),
                      "range": b["range"], "x0": lo, "x1": hi,
                      "typical_vernier": round(_registered_typical(b["name"], gtyp), 1)})
    # 细领域：X 范围取其成员主尺位置跨度（两侧各留 8，至少 16 宽），
    # 典型游标取该学科域注册值（与地图基线、单条读数同源）。
    fine_spread = {}
    for it in items:
        if it["disp_band"] not in bb_names:
            fine_spread.setdefault(it["disp_band"], []).append(it["main_pos"])
    for d in doms.values():
        if d["name"] not in bb_names and d.get("count", 0) >= 2:
            sp = fine_spread.get(d["name"], [d["center"]])
            lo = max(0, min(sp) - 8); hi = min(100, max(sp) + 8)
            bands.append({**d, "backbone": False, "x0": lo, "x1": hi,
                          "typical_vernier":
                              round(_registered_typical(d["name"], gtyp), 1)})
    # 主干带严格按 schema 的 order 排序（天然谱系顺序：人文→社科→自科→形式），
    # 永不被条数打乱；细领域排在主带之后，再按条数/中心排序。
    bands.sort(key=lambda x: (0 if x.get("backbone") else 1,
                              x.get("order", 99) if x.get("backbone") else 0,
                              -x["count"], x["center"]))
    # 学科域列（偏差地图用）：按 axis_domain 聚合，展现带内视角差异。
    # 每条基线高度 = 该学科域注册典型游标（与单条/列表偏移同源），
    # 同一主干带内按 intra_band_order 递增排，直接呈现「带内视角差异递增线」。
    dom_groups = {}
    for it in items:
        ad = (it.get("axis_domain") or "").strip()
        if ad:
            dom_groups.setdefault(ad, []).append(it)
    domain_bands = []
    for name, gs in dom_groups.items():
        reg = _DOMAIN_REGISTRY.get(name, {})
        bb = reg.get("band")
        intra = reg.get("intra_band_order")
        poss = [g["main_pos"] for g in gs]
        center = round(sum(poss) / len(poss), 1)
        domain_bands.append({
            "name": name,
            "backbone": bb,
            "intra_order": intra if intra is not None else 99,
            "center": center,
            "count": len(gs),
            "typical_vernier": round(_registered_typical(name, gtyp), 1),
        })
    bb_order = {b["name"]: b.get("order", i + 1) for i, b in enumerate(BACKBONE_BANDS)}
    domain_bands.sort(key=lambda d: (bb_order.get(d["backbone"], 99),
                                     d["intra_order"], d["center"]))
    # —— 智能开放：隐藏学科域一旦被真实内容映射（有条目以其为 axis_domain），
    # 即在偏差地图中开放显示（趋势线 / 锚点 / 标签），与已有数据的域一致；
    # 「根据存进来的真实内容映射智能开放」在地图入口落地。
    baseline_curve = _baseline_curve()
    _opened = {d["name"] for d in domain_bands}
    for c in baseline_curve:
        if c.get("hidden") and c["name"] in _opened:
            c["hidden"] = False
    return {"threshold": th, "items": items, "bands": bands,
            "domain_bands": domain_bands, "global_typical": gtyp,
            "baseline_curve": baseline_curve}

def get_item(item_id):
    """按 id 取单条（含双尺读数 / 显示领域 / 领域相对偏移 / 离域典型较远标记）。"""
    con = connect()
    th = get_threshold(con)
    row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        con.close()
        return None
    it = _row_to_item(con, row, th, None, None)
    # 与 list_items 一致的显示领域 + 领域相对基准，避免单条读取与列表读取结果不一致
    allc = con.execute("""
        SELECT m.label AS band, m.value AS pos, v.value AS vern
        FROM items i
        JOIN readings m ON m.item_id=i.id AND m.scale='main'
        JOIN readings v ON v.item_id=i.id AND v.scale='vernier'
        WHERE m.label IS NOT NULL AND m.label!='' AND m.label!='未分类'
    """).fetchall()
    bb_names = {b["name"] for b in BACKBONE_BANDS}
    raw_counts = {}
    for r in allc:
        raw_counts[r["band"]] = raw_counts.get(r["band"], 0) + 1
    def _disp(band, pos):
        if band in bb_names or raw_counts.get(band, 0) >= 2:
            return band
        return backbone_of(pos)["name"]
    disp = _disp(it["band"], it["main_pos"])
    vs = [r["vern"] for r in allc if _disp(r["band"], r["pos"]) == disp]
    # 注意：必须在 con 关闭前算完（_global_typical 要查询 con），故 close 放到函数末尾
    typ = _registered_typical(disp, _global_typical(con))
    it["disp_band"] = disp
    it["band_count"] = len(vs)
    it["typical"] = round(typ, 1)
    it["offset"] = round(it["vernier"] - typ, 1)
    it["collision"] = abs(it["offset"]) > th
    it["ref_kind"] = "domain"
    it["direction"] = ("positive" if it["offset"] > 0
                       else "negative" if it["offset"] < 0 else "zero")
    con.close()
    return it

def _content_rev(content):
    """正文内容版本指纹（短哈希），供乐观并发守卫比对，避免双窗口/后台互踩静默覆盖。"""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]


def append_to_item(item_id, text, label="孵化合并"):
    """向条目正文【追加】一段证据，**保留原双尺定位（不重投影）**。

    用于灵感碎片孵化「命中合并」场景：碎片观点并入既有条目，但既有条目的
    主尺/游标是已经校准过的，不应被重新测量覆盖。只拼接带日期/标签的块 +
    写日志 + 同步文章镜像。返回 {ok,item_id}。"""
    if not text or not text.strip():
        return {"ok": False, "msg": "追加内容为空"}
    con = connect()
    row = con.execute("SELECT id,content,title FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "条目不存在"}
    today = time.strftime("%Y-%m-%d")
    old = row["content"] or ""
    block = f"[{today} {label}] {text}"
    new = (old.rstrip() + "\n\n" + block) if old.strip() else block
    con.execute("UPDATE items SET content=? WHERE id=?", (new, item_id))
    log(con, item_id, "system",
        f"孵化合并：追加碎片证据「{text[:30]}…」（保留原双尺定位）")
    con.commit(); con.close()
    try:
        write_article_file(item_id)
    except Exception:                              # noqa: BLE001
        pass
    return {"ok": True, "item_id": item_id}

def update_item(item_id, title, content, axis_domain=None, rev=None, source_url=None):
    """更新条目内容：同步只做「本地启发式定位 + 落库 + 本地向量/摘要 + 写文件」，
    响应秒回；llm 模式下的真实模型读数与向量/摘要升级交给后台 _refine 线程补算。

    与 add_item 同策略（先落库返回，后台默默整理，前端靠轮询自动刷新到位）：
    编辑保存不再因「慢模型调用」卡在前台，做到点一下立即返回。

    rev：客户端打开时正文的内容版本指纹（_content_rev）；若与当前库内正文不一致，
    说明自打开后被其它窗口/后台/reload 改过，返回 conflict 拒绝静默覆盖。
    """
    content = _clean_text(content)
    con = connect()
    old_it = get_item(item_id)            # 先取旧分类/标题，供换目录时清理旧文件
    old_title = old_it["title"] if old_it else ""
    # 乐观并发守卫：版本不一致则拒绝覆盖，把抉择权交回用户。
    if rev is not None and old_it is not None:
        cur_rev = _content_rev(old_it.get("content", ""))
        if cur_rev != rev:
            con.close()
            return {"ok": False, "conflict": True,
                    "msg": "正文版本冲突：自你打开后，内容已被其它改动更新。请核对最新内容后再保存。",
                    "current_rev": cur_rev,
                    "current_title": old_it.get("title", "")}
    row = con.execute("SELECT id,title FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": "条目不存在"}
    con.execute("UPDATE items SET title=?, content=?, updated_at=? WHERE id=?",
                (title, content, time.time(), item_id))
    # 同步快路径：本地启发式立即定位（永不依赖网络），与 add_item 一致。
    # llm 模式下启发式只允许「归入已有领域」，自创新名先写「未分类」，交给后台 LLM 归纳。
    _write_readings(con, item_id, content, "heuristic",
                    allow_invent=(_current_mode() != "llm"))
    _write_chunks(con, item_id, content)   # 片段索引随内容更新
    if axis_domain:
        con.execute("UPDATE items SET axis_domain=? WHERE id=?",
                    (axis_domain, item_id))
        _enforce_band_invariant(con, item_id)   # 编辑保存后横轴立即对齐学科域
    if source_url is not None:
        con.execute("UPDATE items SET source_url=? WHERE id=?",
                    (source_url, item_id))
    th = get_threshold(con)
    r2 = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    item = _row_to_item(con, r2, th)
    if axis_domain:
        item["axis_domain"] = axis_domain
    if source_url is not None:
        item["source_url"] = source_url
    log(con, item_id, "system",
        f"条目更新「{title}」：主尺 {item['band']}@{item['main_pos']}，"
        f"游标 {item['vernier']}，偏移 {item['offset']}"
        f"（{'离域典型较远' if item['collision'] else '贴近域典型'}）。后台将按当前模式补全模型读数。")
    con.commit(); con.close()

    # 互链 + 本地向量 + 离线摘要（同步、本地、快，与 add_item 一致）
    try:
        c2 = connect()
        try:
            set_links_for_item(c2, item_id, content)
            _set_embedding(c2, item_id, local_embed(content))
            try:
                s, tg = local_summarize(content)
                s = _summod.sanitize_summary(s)             # A2 · L0 收口
                if s:
                    c2.execute("UPDATE items SET summary=?, tags=? WHERE id=?",
                               (s, tg, item_id))
            except Exception:                              # noqa: BLE001
                pass
        finally:
            c2.commit(); c2.close()
    except Exception:                                  # noqa: BLE001
        pass
    # 同步镜像到本地文章文件（DB -> 文件 协同）
    p = write_article_file(item_id)
    # 标题或分类变化都可能换目录：用旧分类定位旧文件并清理
    if old_it:
        oldp = os.path.join(_article_dir(old_it), _article_name(item_id, old_title))
        if oldp != p and os.path.exists(oldp):
            try:
                os.remove(oldp)
            except Exception:                      # noqa: BLE001
                pass

    # 后台补算：llm 模式用真实模型重算两尺 + 候选边/闭环 + 向量/摘要；
    # 模型不通则中途自动退回本地，前台完全无感。
    if _current_mode() == "llm" and LLM_OK:
        try:
            _refine_pool.submit(_refine, item_id, content, axis_domain)
        except Exception:                              # noqa: BLE001
            pass
    return {"ok": True, "item": item, "file": p}

def reload_from_file(item_id):
    """从本地 .md 重新载入正文回灌 DB 并重测双尺（文件 -> KB 协同）。"""
    p = article_path(item_id)
    if not os.path.exists(p):
        return {"ok": False, "msg": f"本地文件不存在：{p}"}
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    meta, body = deserialize_article(text)
    cur = get_item(item_id) or {}
    title = meta.get("title") or cur.get("title") or f"#{item_id}"
    content = body or meta.get("title", "")
    if not content:
        return {"ok": False, "msg": "文件正文为空"}
    return update_item(item_id, title, content)

def export_all_articles():
    items = list_items()["items"]
    paths = [write_article_file(i["id"]) for i in items]
    return {"ok": True, "count": len(paths), "paths": paths}

def delete_item(item_id, backup=False):
    """删除一条知识：级联清掉它在所有表里的痕迹 + 本地 .md 文件。

    默认不做整库快照；如确需留底，调用方显式传 backup=True。
    删除依赖前端二次确认弹窗把关。本地 .md 文档移入系统回收站（可找回），
    但 SQLite 数据库记录为永久删除、无法进回收站。
    """
    item_id = int(item_id)
    con = connect()
    row = con.execute("SELECT id,title FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        con.close()
        return {"ok": False, "msg": f"没有 id={item_id} 的条目"}
    title = row["title"]
    con.close()
    fp = article_path(item_id)              # 先取分类路径（此时条目尚在 DB，路径才准确）
    legacy = legacy_article_path(item_id)

    snap = snapshot("delete") if backup else None

    con = connect()
    removed = {}
    # 各表对「条目」的引用列名不统一，这里集中声明一次，避免漏删
    plan = [
        ("readings",   "item_id=?",                    (item_id,)),
        ("embeddings", "item_id=?",                    (item_id,)),
        ("chunks",     "item_id=?",                    (item_id,)),
        ("links",      "src_item_id=? OR dst_item_id=?", (item_id, item_id)),
        ("edges",      "src_item=?",                   (item_id,)),
        ("logs",       "item_id=?",                    (item_id,)),
    ]
    for table, where, args in plan:
        try:
            removed[table] = con.execute(
                f"DELETE FROM {table} WHERE {where}", args).rowcount
        except sqlite3.Error:
            removed[table] = 0                     # 表不存在或无该列，跳过
    # 级联：把 feedback_inbox 中挂在该条目上的反馈软标为「已忽略」。
    # 条目已删，这类反馈再也无法「应用更新」（否则会报「关联文章不存在」）；
    # 软标而非物理删，保留决策痕迹。near_duplicate 等条目对类反馈 item_id=0，不受影响。
    try:
        removed["feedback_inbox"] = con.execute(
            "UPDATE feedback_inbox SET status='dismissed' "
            "WHERE item_id=? AND status NOT IN ('applied','dismissed')",
            (item_id,)).rowcount
    except sqlite3.Error:
        removed["feedback_inbox"] = 0
    removed["items"] = con.execute("DELETE FROM items WHERE id=?",
                                   (item_id,)).rowcount
    con.commit()
    con.close()

    file_removed = False
    if os.path.exists(fp):
        trash_file(fp)                          # 移入回收站（而非永久删）
        file_removed = not os.path.exists(fp)
    if legacy != fp and os.path.exists(legacy):
        trash_file(legacy)                       # 旧式命名残留一并进回收站
    # 清理删除后可能遗留的空目录（含被清空的分类子目录）
    for root, dirs, files in os.walk(ARTICLES_DIR, topdown=False):
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except OSError:                        # noqa: BLE001
                pass
    return {"ok": True, "id": item_id, "title": title,
            "removed": removed, "file_removed": file_removed,
            "backup": (snap or {}).get("path")}

def _clean_text(text):
    """入库前预处理（对应 RAG 流程的「清洗」阶段）：把控数据质量，只做无损规范化。

    - 统一换行符（\\r\\n / \\r → \\n）
    - 去掉每行行尾空白
    - 连续空行合并为单个空行（避免扫描/OCR 残留下的大量空白把切块/摘要带偏）
    - 去掉首尾空行
    不改写任何语义内容，标题、Markdown 结构、原文措辞一律保留。
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out, blank = [], 0
    for ln in text.split("\n"):
        ln = ln.rstrip()
        if ln.strip() == "":
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    while out and out[0].strip() == "":
        out.pop(0)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)

def add_item(title, content, axis_domain=None, source_url=None):
    """入库：同步只做「本地启发式定位 + 落库 + 本地向量/摘要」，响应秒回；
    llm 模式下的真实模型读数与向量/摘要升级交给后台 _refine 线程补算。

    这样即便模型很慢或不可达，保存也立即返回——这是「先落库返回，后台补算」
    的落地：分类→向量→摘要这条最慢的链路不再阻塞 HTTP 响应。
    """
    content = _clean_text(content)
    con = connect()
    now = time.time()
    cur = con.execute(
        "INSERT INTO items(title,content,created_at,alias,updated_at) VALUES(?,?,?,?,?)",
        (title, content, now, title, now))
    iid = cur.lastrowid
    # 同步快路径：本地启发式立即定位（永不依赖网络）。
    # llm 模式下启发式只归入已有领域，自创新名交给后台 LLM 归纳。
    _write_readings(con, iid, content, "heuristic",
                    allow_invent=(_current_mode() != "llm"))
    _write_chunks(con, iid, content)          # 片段索引（检索定位层，零网络）
    th = get_threshold(con)
    row = con.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    item = _row_to_item(con, row, th)
    # 契约修正：axis_domain 在下方 c2 连接里同步落库（1141 行），但 item 字典是
    # 在落库前 SELECT 出来的，导致返回 dict 里 axis_domain 恒为 null，误导调用方以为
    # 没写进去。这里把入参原样回填进返回 dict，让响应与库内状态一致（llm 模式的
    # 摘要/向量才是真正异步补算的部分，与 axis_domain 无关）。
    if axis_domain:
        item["axis_domain"] = axis_domain
    if source_url:
        item["source_url"] = source_url
    log(con, iid, "system",
        f"新条目入库「{title}」：主尺 {item['band']}@{item['main_pos']}，"
        f"游标 {item['vernier']}，偏移 {item['offset']}"
        f"（{'离域典型较远' if item['collision'] else '贴近域典型'}）。后台将按当前模式补全模型读数。")
    con.commit()
    con.close()

    # 互链 + 本地向量 + 离线摘要（同步、本地、快）
    try:
        c2 = connect()
        try:
            set_links_for_item(c2, iid, content)
            try:
                # 仅在启发式/无 LLM 模式离线抽概念兜底；llm 模式交给 _refine 用模型抽真概念
                if _current_mode() != "llm" or not LLM_OK:
                    link_concepts_for_item(c2, iid, content, item)
            except Exception:                              # noqa: BLE001
                pass
            if axis_domain:
                c2.execute("UPDATE items SET axis_domain=? WHERE id=?",
                           (axis_domain, iid))
                _enforce_band_invariant(c2, iid)   # 入库后横轴立即对齐学科域
            if source_url:
                c2.execute("UPDATE items SET source_url=? WHERE id=?",
                           (source_url, iid))
            _set_embedding(c2, iid, local_embed(content))
            try:
                s, tg = local_summarize(content)
                s = _summod.sanitize_summary(s)             # A2 · L0 收口
                if s:
                    c2.execute("UPDATE items SET summary=?, tags=? WHERE id=?",
                               (s, tg, iid))
            except Exception:                              # noqa: BLE001
                pass
        finally:
            # 异常也必须提交并关闭：否则连接带着未提交的写事务泄漏，
            # 会永久持有数据库写锁（其他进程全部 database is locked）。
            c2.commit(); c2.close()
    except Exception:                                  # noqa: BLE001
        pass
    # 同步镜像到本地文章文件（DB -> 文件 协同）
    try:
        write_article_file(iid)
    except Exception:                                  # noqa: BLE001
        pass
    # 后台补算：llm 模式用真实模型重算两尺 + 候选边/闭环 + 向量/摘要；
    # 模型不通则中途自动退回本地，前台完全无感。
    if _current_mode() == "llm" and LLM_OK:
        try:
            _refine_pool.submit(_refine, iid, content, axis_domain)
        except Exception:                              # noqa: BLE001
            pass
    return item

def _refine(item_id, content, axis_domain=None):
    """后台补算线程。

    模式无关部分：引擎自主共现发现（refresh_soft_links，纯本地统计、不依赖 LLM），
    使内容图谱在「启发式模式」下也能自动长出「引擎建议」软边——这正是 KB 独立性的
    体现：发现关联不等人点按钮、不靠 agent 触发，写完即默默跑。

    LLM 相关富集（双尺重测 / 向量升级 / 摘要）仅在 llm 模式跑。"""
    try:
        # —— 模式无关：写时已同步落 local_embed，故 suggest_links 在启发式下也能跑 ——
        try:
            refresh_soft_links()
        except Exception:                              # noqa: BLE001
            pass
        # 概念衍生层：llm 模式用模型抽真概念（离线噪声已在同步路径跳过）
        try:
            if LLM_OK and not _llm.breaker_state()["open"]:
                enrich_concepts_with_llm(item_id)
        except Exception:                              # noqa: BLE001
            pass
        mode = _current_mode()
        if mode != "llm" or not LLM_OK:
            write_article_file(item_id)
            return
        # 1) 重算双尺（measure_pair 在模型不可用时自动退回启发式，不抛错）
        #    独立性守卫：坍缩时拒绝写入新读数（拉闸、隔离偏移），避免继续污染。
        ok, ind = _guard_allows_write(force=False)
        if not ok:
            c = connect()
            try:
                log(c, item_id, "system",
                    f"⛔ 独立性守卫已拉闸（r={ind['r']}，n={ind['n']}）："
                    f"后台补算的双尺读数不予写入，偏移保持隔离。")
            finally:
                c.commit(); c.close()
            return
        (band_name, pos, mconf, mprov, mwhy), (depth, vconf, vprov, vwhy) = \
            measure_pair(content, "llm", item_id=item_id)
        c = connect()
        try:
            now = time.time()
            c.execute(
                "INSERT OR REPLACE INTO readings"
                "(item_id,scale,value,label,confidence,provider,signal_family,revised,computed_at)"
                " VALUES(?,?,?,?,?,?,?,0,?)",
                (item_id, "main", pos, band_name, mconf, mprov["id"], mprov["signal_family"], now))
            c.execute(
                "INSERT OR REPLACE INTO readings"
                "(item_id,scale,value,label,confidence,provider,signal_family,revised,computed_at)"
                " VALUES(?,?,?,?,?,?,?,0,?)",
                (item_id, "vernier", depth, None, vconf, vprov["id"], vprov["signal_family"], now))
            _enforce_band_invariant(c, item_id, now)   # 写入路径收口：LLM 测量后横轴以学科域为锚
            th = get_threshold(c)
            row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                return                                # 条目已删除：静默结束，finally 会关连接
            it = _row_to_item(c, row, th)
        finally:
            # 异常也必须提交并关闭：否则写事务泄漏会永久持锁
            c.commit(); c.close()
        # 2) 候选边 + 闭环（基于真实模型坐标）；各自独立连接、内部异常安全
        try:
            gen_edge(item_id)
        except Exception:                              # noqa: BLE001
            pass
        try:
            # 带域一致不变量已保证横轴=学科域带；有受控学科域锚的条目，
            # 偏移视为「深度相对所属领域」的真实信号（非错位缺陷），不再跨带重投影；
            # 仅对无受控学科域锚的条目保留旧闭环校准。
            if it["collision"] and not domain_band_name(it.get("axis_domain") or ""):
                calibrate(item_id)
        except Exception:                              # noqa: BLE001
            pass
        # 3) 向量 + 摘要升级（embed_text/summarize 自带本地兜底）
        # 注意：embed_text/summarize 可能调用慢模型（数秒），
        # 期间绝不能持有未提交的写事务 —— 否则其他线程 busy_timeout 超时即
        # "database is locked"。所以向量写完立刻 commit 关连接，摘要用独立连接。
        c2 = connect()
        try:
            _set_embedding(c2, item_id, embed_text(content))
        finally:
            c2.commit(); c2.close()
        try:
            s, tg = summarize(content)
            s = _summod.sanitize_summary(s)             # A2 · L0 收口（LLM 结果也过一遍）
            if s:
                c3 = connect()
                try:
                    c3.execute("UPDATE items SET summary=?, tags=? WHERE id=?",
                               (s, tg, item_id))
                finally:
                    c3.commit(); c3.close()
        except Exception:                              # noqa: BLE001
            pass
        write_article_file(item_id)
    except Exception as e:                             # noqa: BLE001
        try:
            c = connect()
            log(c, item_id, "system", f"后台补算中断：{e}")
            c.commit(); c.close()
        except Exception:                              # noqa: BLE001
            pass

def calibrate(item_id):
    """
    阴阳闭环校准。修复原型 v2 的缺陷：
    主尺位置移动后，必须重新判定所属领域带，typical 随之改变，偏移才会真正收敛。
    锚：每轮都回扣条目原文重算游标，禁止两模型互喂。
    """
    con = connect()
    try:
        th = get_threshold(con)
        row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return {"ok": False, "msg": "条目不存在"}
        it = _row_to_item(con, row, th)
        if not it["collision"]:
            log(con, item_id, "system", f"「{it['title']}」已对齐（偏移 {it['offset']}），无需校准。")
            return {"ok": False, "msg": "已对齐，无需校准"}

        # 锚：游标每轮回扣原文重算，不接受任何来自主尺的输入
        depth = vernier_of(row["content"], get_mode(con))
        target = best_band_for(depth)
        pos = it["main_pos"]
        step, n, offset = 0.5, 0, it["offset"]
        trace = []
        while n < MAX_ITER:
            pos = max(0.0, min(100.0, pos + step * (target["center"] - pos)))
            band = band_of(pos)                       # ← 关键修复：重新判定领域带
            dt = domain_typical_vernier(it.get("axis_domain") or "")
            base = dt if dt is not None else band["typical_vernier"]
            offset = round(depth - base, 1)
            n += 1
            trace.append({"iter": n, "pos": round(pos, 1),
                          "band": band["name"], "offset": offset})
            if abs(offset) <= th:
                break

        converged = abs(offset) <= th
        con.execute(
            "UPDATE readings SET value=?,label=?,revised=1,computed_at=? "
            "WHERE item_id=? AND scale='main'",
            (round(pos, 1), band_of(pos)["name"], time.time(), item_id),
        )
        # 终极收口：即便手动校准跨带移动主尺，仍以学科域所属主干带为权威横轴坐标。
        _enforce_band_invariant(con, item_id)
        log(con, item_id, "yin->yang",
            f"阴修订 ×{n}：主尺自 {it['main_pos']}({it['band']}) 迁移至 "
            f"{round(pos,1)}({band_of(pos)['name']})，偏移 {it['offset']} → {offset}，"
            f"{'已收敛' if converged else '未收敛 → 标记 unresolved，转人工复核'}。")
        if not converged:
            log(con, item_id, "system", f"「{it['title']}」达到最大迭代 {MAX_ITER} 仍未收敛。")
        con.commit()
        row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        result = _row_to_item(con, row, th)
        return {"ok": True, "converged": converged, "iterations": n,
                "trace": trace, "item": result}
    finally:
        con.commit(); con.close()

def reconcile_band_with_domain(item_id, force_domain=None):
    """
    以学科域(axis_domain)为语义锚，把主尺位置(main_pos)收敛回该域所属主干带的中心，
    消除「条目主尺落在与学科域相冲突的主干带」这类一眼错错位。

    设计边界（第一性原理）：
    - 只动主尺(main readings 的 value/label)，vernier 原样保留。
    - 残留偏移 = 游标相对学科域典型，是「深度相对所属领域」的真实信号，不是错位缺陷，
      故不强制压平（压平会抹掉有意义的论证风格差异）。
    - force_domain: 当 axis_domain 为空时，指定要归入的受控学科域（如 id68 域缺失需补）。

    返回 {ok, item?, old_band?, new_band?, new_pos?, msg?}。
    """
    from . import schema
    con = connect()
    try:
        row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return {"ok": False, "msg": "条目不存在"}
        domain = (force_domain or row["axis_domain"] or "").strip()
        if not domain:
            return {"ok": False, "msg": "axis_domain 为空且未指定 force_domain，无法锚定主干带"}
        target_band = schema.domain_band_name(domain)
        if target_band is None:
            return {"ok": False, "msg": f"学科域「{domain}」不在受控注册表，无法映射主干带"}
        center = None
        for b in BACKBONE_BANDS:
            if b["name"] == target_band:
                center = b["center"]
                break
        if center is None:
            return {"ok": False, "msg": f"主干带「{target_band}」无中心值，无法收敛"}
        old = con.execute(
            "SELECT * FROM readings WHERE item_id=? AND scale='main'", (item_id,)
        ).fetchone()
        old_val = old["value"] if old else None
        old_label = old["label"] if old else None
        conf = (old["confidence"] if old and old["confidence"] is not None else 0.0)
        prov = old["provider"] if old else "reconcile"
        fam = old["signal_family"] if old else "axis-domain-anchor"
        now = time.time()
        con.execute(
            "INSERT OR REPLACE INTO readings(item_id,scale,value,label,confidence,"
            "provider,signal_family,revised,computed_at) VALUES(?,?,?,?,?,?,?,1,?)",
            (item_id, "main", center, target_band, conf, prov, fam, now),
        )
        if force_domain:
            con.execute("UPDATE items SET axis_domain=? WHERE id=?", (domain, item_id))
        log(con, item_id, "reconcile",
            f"以学科域「{domain}」为锚：主尺自 {old_val}({old_label}) 收敛至 "
            f"{center}({target_band})，主干带与学科域对齐；vernier 保留，"
            f"残留偏移视为深度相对学科域典型的信号。")
        con.commit()
        th = get_threshold(con)
        new_row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return {"ok": True, "item": _row_to_item(con, new_row, th),
                "old_band": old_label, "new_band": target_band, "new_pos": center}
    finally:
        con.close()


def parse_import_text(text):
    """把粘贴文本拆成多篇：独占一行的 --- 分隔；每篇可以 # 标题 开头（标题行会被剥掉当标题）。"""
    entries = []
    for block in re.split(r"^\s*---\s*$", text or "", flags=re.M):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        m = re.match(r"^#{1,6}\s+(.+)$", lines[0].strip()) if lines else None
        if m:
            title = m.group(1).strip()
            body = "\n".join(lines[1:]).strip()
        else:
            title, body = None, block
        entries.append({"title": title, "content": body})
    return entries

def scan_md_dir(directory):
    """扫描目录下 *.md/*.txt：带 frontmatter 的按 deserialize_article 解析，
    否则整文件为正文、文件名（去扩展名）作标题。"""
    entries = []
    if not directory or not os.path.isdir(directory):
        return entries
    for fn in sorted(os.listdir(directory)):
        if not fn.lower().endswith((".md", ".markdown", ".txt")):
            continue
        p = os.path.join(directory, fn)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:                              # noqa: BLE001
            continue
        if text.lstrip().startswith("---"):
            meta, body = deserialize_article(text)
            entries.append({"title": meta.get("title") or os.path.splitext(fn)[0],
                            "content": body or ""})
        else:
            entries.append({"title": os.path.splitext(fn)[0], "content": text.strip()})
    return entries

def create_draft(title):
    """E1 · 自生长：为虚节点（正文 [[目标]] 但库里没有）创建一篇空壳草稿，
    源条目的 wikilink 随即解析成硬链 —— KB 自己长大，不必等人工补写。"""
    title = (title or "").strip()
    if not title:
        return {"ok": False, "msg": "标题不能为空"}
    it = add_item(title, "（待补充）")      # add_item 已同步落 embedding，发现管线会自动接上
    return {"ok": True, "id": it["id"], "title": title}


def item_l0(item_id):
    """L0 抽象层聚合视图（A3 · 为第 2 层检索/调用留形，不改加载机制）。

    只返回「一眼定位这条知识所需的最小字段」——标题、一句话摘要、学科域、
    主尺带、标签——**不含正文 content**。未来第 2 层（面向 agent 调用的检索）
    取 L0 时直接走这个函数，无需回刷历史数据（summary/band/tags 已落库）。

    第 1 层（当前）只负责「存好、把关好」，L0 字段现在就固化成型；
    第 2 层的 L0/L1/L2 按需下钻机制届时直接消费本视图，不必现在实现。
    """
    con = connect()
    try:
        row = con.execute(
            "SELECT id, title, summary, axis_domain, tags "
            "FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        band = con.execute(
            "SELECT label FROM readings WHERE item_id=? AND scale='main'",
            (item_id,)).fetchone()
        band_name = band["label"] if band else None
    finally:
        con.close()
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"] or "",
        "axis_domain": row["axis_domain"] or None,
        "band": band_name,
        "tags": [t for t in (row["tags"] or "").split(",") if t],
    }


