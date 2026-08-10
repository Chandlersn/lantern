# -*- coding: utf-8 -*-
"""自我对抗审查的反馈收件箱：推送可筛、状态机（未读/已读/已采纳/忽略）。"""

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

def _feedback_pushable(review, severity, signal_ok):
    """判定一条反馈是否值得打扰用户（推送资格）。
    设计原则：只有'明显有问题'才推，低质量/疑似误报绝不打扰——否则系统显得蠢。
      - 语义相似类：依赖嵌入质量。守卫退化（embedding 不可信）时一概不推；
        守卫正常时也仅高相似(sim>=0.90)且 warn/critical 才推。
      - 非语义类（事实矛盾/硬规则违反）：不依赖嵌入，warn/critical 即推。"""
    rtype = (review or {}).get("type", "")
    sim = (review or {}).get("sim") or 0
    if rtype in _SEMANTIC_FB_TYPES:
        if not signal_ok:
            return False
        return severity in ("critical", "warn") and sim >= 0.90
    return severity in ("critical", "warn")

def _row_feedback(r):
    d = dict(r)
    try:
        d["review"] = json.loads(d["review"]) if d["review"] else {}
    except (json.JSONDecodeError, TypeError):
        d["review"] = {"raw": d["review"]}
    d["pushable"] = d.get("pushable", 1)
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

