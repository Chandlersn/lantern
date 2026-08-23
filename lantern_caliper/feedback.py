# -*- coding: utf-8 -*-
"""自我对抗审查的反馈收件箱：推送可筛、状态机（未读/已读/已采纳/忽略）。"""

import json
import time

def push_feedback(item_id, title, axis_domain, review, severity="info", must_revise=0, pushable=None):
    """把一条自我对抗审查反馈写入独立收件箱。返回新行 id。
    自带建表守卫：即便 Skill 引擎 CLI 独立运行（未经服务 init/migrate），
    也能确保 feedback_inbox 表存在。
    pushable：是否值得打扰用户（推送资格）。None 时按 severity 默认（warn/critical=推）。"""
    con = connect()
    con.execute(
        "CREATE TABLE IF NOT EXISTS feedback_inbox ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, title TEXT NOT NULL, "
        "axis_domain TEXT, severity TEXT NOT NULL DEFAULT 'info', review TEXT NOT NULL, "
        "must_revise INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'unread', "
        "created_at REAL NOT NULL, read_at REAL, applied_at REAL)")
    # 兼容旧库：确保 pushable 列存在（仅首次，失败即已存在）
    try:
        con.execute("ALTER TABLE feedback_inbox ADD COLUMN pushable INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass
    if pushable is None:
        pushable = 1 if severity in ("critical", "warn") else 0
    cur = con.execute(
        "INSERT INTO feedback_inbox"
        "(item_id,title,axis_domain,review,severity,must_revise,status,created_at,pushable)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (item_id, title, axis_domain, json.dumps(review, ensure_ascii=False),
         severity, 1 if must_revise else 0, "unread", time.time(), 1 if pushable else 0),
    )
    fid = cur.lastrowid
    con.commit(); con.close()
    return fid


def _row_feedback(r):
    d = dict(r)
    try:
        d["review"] = json.loads(d["review"]) if d["review"] else {}
    except (json.JSONDecodeError, TypeError):
        d["review"] = {"raw": d["review"]}
    d["pushable"] = d.get("pushable", 1)
    hc = d.get("human_correction")
    if hc and isinstance(hc, str):
        try:
            d["human_correction"] = json.loads(hc)
        except (json.JSONDecodeError, TypeError):
            d["human_correction"] = None
    return d

def list_feedback(status=None, limit=100):
    con = connect()
    if status:
        rows = con.execute(
            "SELECT * FROM feedback_inbox WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit)).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM feedback_inbox ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
    con.close()
    return [_row_feedback(r) for r in rows]

def get_feedback(fid):
    con = connect()
    r = con.execute("SELECT * FROM feedback_inbox WHERE id=?", (fid,)).fetchone()
    con.close()
    return _row_feedback(r) if r else None

def revise_with_feedback(fid):
    """依据一条反馈（feedback_inbox）生成修订后的文章正文——不落库，只生成。

    这是「应用更新」真闭环的第 1 步（生成）：用 llm 把原文与审查要点综合成修订稿，
    返回 {item_id, title, old_content, new_content}。第 2 步由前端 diff 预览 +
    用户显式确认后，再走 /api/kb/update 真正回写——绝不静默污染文章纯洁性。
    LLM 不可用时抛 RuntimeError，由上层提示用户手动编辑。"""
    fb = get_feedback(fid)
    if not fb:
        raise ValueError("反馈不存在")
    item_id = fb.get("item_id")
    if not item_id:
        raise ValueError("该反馈未关联文章，无法应用")
    it = get_item(item_id)
    if not it:
        raise ValueError("关联文章不存在")
    content = it.get("content", "")
    review = fb.get("review") or {}
    labels = {
        "core_verdict_weakest_support": "核心判断最弱支撑点",
        "strongest_counter": "最强反论据",
        "hidden_assumptions": "隐藏假设",
        "blind_spots": "透镜盲区",
        "internal_tension": "内部张力",
        "over_reach": "过度推断",
        "verdict_revised": "修订后核心判断",
    }
    pts = []
    for k, lab in labels.items():
        v = review.get(k)
        if not v:
            continue
        if isinstance(v, list):
            v = "；".join(str(x) for x in v)
        pts.append(f"- {lab}：{v}")
    fb_text = "\n".join(pts) if pts else "（无具体要点）"
    system = (
        "你是一位严谨的编辑。用户会给你一篇原文，以及一份「自我对抗审查」反馈。"
        "请基于反馈对原文进行修订：补足最弱支撑、回应最强反论据、显式标注隐藏假设、"
        "补足透镜盲区、化解内部张力、收敛过度推断，并落实「修订后核心判断」。\n"
        "硬性要求：保持原文核心主题、结构与文风；只在必要时增删改；绝不改变作者原意；"
        "不要把审查意见作为「自我审查／修订说明」等元注释塞进正文；"
        "直接输出修订后的完整正文（Markdown），不要任何前后缀、标题或解释性文字。"
    )
    user = (f"【原文】\n{content}\n\n"
            f"【自我对抗审查反馈】\n{fb_text}\n\n"
            f"请输出修订后的完整正文：")
    if not LLM_OK:
        raise RuntimeError("未配置模型，无法自动生成修订稿；请在关联文章里手动修订后再应用。")
    out, _ = _llm.chat(system, user, temperature=0.3, max_tokens=4000,
                       use_cache=False, timeout=90, retries=1)
    return {"item_id": item_id, "title": it.get("title", ""),
            "old_content": content, "new_content": out}

def count_unread_feedback():
    con = connect()
    n = con.execute("SELECT COUNT(*) c FROM feedback_inbox WHERE status='unread' AND pushable=1").fetchone()["c"]
    con.close()
    return n

def mark_feedback_read(fid):
    # 仅未读→已读；已应用/已忽略不回退，保留决策痕迹
    con = connect()
    cur = con.execute(
        "UPDATE feedback_inbox SET status='read', read_at=? "
        "WHERE id=? AND status='unread'", (time.time(), fid))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok

def mark_feedback_applied(fid):
    # 标记为指导的自我更新已采纳（无论此前是否已读）
    con = connect()
    cur = con.execute(
        "UPDATE feedback_inbox SET status='applied', applied_at=?, read_at=COALESCE(read_at,?) "
        "WHERE id=?", (time.time(), time.time(), fid))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok

def dismiss_feedback(fid):
    con = connect()
    cur = con.execute(
        "UPDATE feedback_inbox SET status='dismissed' WHERE id=?", (fid,))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


def delete_feedback(fid):
    """彻底删除一条反馈（物理删除，区别于 dismiss 软忽略）。"""
    con = connect()
    cur = con.execute("DELETE FROM feedback_inbox WHERE id=?", (fid,))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


def clear_feedback():
    """一键清空收件箱：物理删除全部反馈行（区别于逐条 dismiss 软忽略）。
    用于用户想一次性甩掉累积的低价值/误报提醒时。返回被删除的行数。"""
    con = connect()
    n = con.execute("SELECT COUNT(*) c FROM feedback_inbox").fetchone()["c"]
    con.execute("DELETE FROM feedback_inbox")
    con.commit(); con.close()
    return n


def apply_human_correction(fid, correction):
    """对话式闭环：人在同一条反馈下给出修正，系统立即落回文章。

    correction: dict，可含
      - corrected_domain: 人认定的正确学科域（落回 items.axis_domain + readings 主尺，保持双尺度一致）
      - corrected_summary: 人认定的正确一句话摘要（过 L0 收口后落回 summary）
      - note: 人写的其它修正意见（仅记录，不落库正文）
    落库后把 correction（附时间戳）写入 feedback_inbox.human_correction，状态置 applied。
    返回 {ok, applied:[...], item_id}。"""
    fb = get_feedback(fid)
    if not fb:
        raise ValueError("反馈不存在")
    item_id = fb.get("item_id")
    if not item_id:
        raise ValueError("该反馈未关联文章，无法落回修正")
    from . import items as _items          # 局部导入，避免顶层循环依赖
    from . import summarize as _sum
    from . import schema as _schema
    applied = []
    # 1) 领域修正：人的判断是最终权威，直接落回 items.axis_domain，
    #    并把 readings 主尺 label 同步为该域（value 归到其主干带中心，缺失则保留原值）。
    dom = (correction.get("corrected_domain") or "").strip()
    if dom:
        con = connect()
        con.execute("UPDATE items SET axis_domain=? WHERE id=?", (dom, item_id))
        center = None
        try:
            tb = _schema.domain_band_name(dom)
            if tb:
                for b in _items.BACKBONE_BANDS:
                    if b["name"] == tb:
                        center = b["center"]; break
        except Exception:                   # noqa: BLE001
            pass
        old = con.execute(
            "SELECT * FROM readings WHERE item_id=? AND scale='main'", (item_id,)
        ).fetchone()
        if old:
            new_val = center if center is not None else old["value"]
            con.execute(
                "INSERT OR REPLACE INTO readings(item_id,scale,value,label,confidence,"
                "provider,signal_family,revised,computed_at) VALUES(?,?,?,?,?,?,?,1,?)",
                (item_id, "main", new_val, dom,
                 old["confidence"] if old["confidence"] is not None else 0.0,
                 old["provider"] or "human-correction",
                 old["signal_family"] or "human-correction", time.time()))
        con.commit(); con.close()
        applied.append("domain")
    # 2) 摘要修正：过 L0 收口后落回
    summ = (correction.get("corrected_summary") or "").strip()
    if summ:
        clean = _sum.sanitize_summary(summ)
        if clean:
            con = connect()
            con.execute("UPDATE items SET summary=? WHERE id=?", (clean, item_id))
            con.commit(); con.close()
            applied.append("summary")
    # 3) 记录人的修正意见（含时间戳），状态置 applied
    rec = dict(correction)
    rec["at"] = time.time()
    con = connect()
    con.execute(
        "UPDATE feedback_inbox SET human_correction=?, status='applied', "
        "applied_at=?, read_at=COALESCE(read_at,?) WHERE id=?",
        (json.dumps(rec, ensure_ascii=False), time.time(), time.time(), fid))
    con.commit(); con.close()
    return {"ok": True, "applied": applied, "item_id": item_id}


def get_human_correction(fid):
    """读取某条反馈的人修正意见（dict 或 None）。"""
    fb = get_feedback(fid)
    if not fb:
        return None
    hc = fb.get("human_correction")
    if not hc:
        return None
    try:
        return json.loads(hc) if isinstance(hc, str) else hc
    except (ValueError, TypeError):
        return None


def ignore_dupe_pair(a, b):
    """用户确认某对条目「并非重复」：永久加入忽略集（meta.ignore_dupe_pairs），
    健康自检检测近似重复时永久跳过这一对，不再弹窗/入库打扰。返回是否成功。"""
    con = connect()
    row = con.execute("SELECT v FROM meta WHERE k='ignore_dupe_pairs'").fetchone()
    pairs = []
    if row and row["v"]:
        try:
            pairs = json.loads(row["v"])
        except (json.JSONDecodeError, TypeError):
            pairs = []
    key = sorted((int(a), int(b)))
    if key not in pairs:
        pairs.append(key)
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('ignore_dupe_pairs',?)",
                (json.dumps(pairs),))
    con.commit(); con.close()
    return True

