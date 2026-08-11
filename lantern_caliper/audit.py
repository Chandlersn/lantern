# -*- coding: utf-8 -*-
"""自动日志与审计追踪（写操作/自检留痕，可清理）。"""

import os
import time

def list_logs(limit=60):
    con = connect()
    # 只回「仍存在条目」的校准记录：避免已删除（测试/种子）条目的孤儿日志
    # 占满最近-60 窗口、把真文档的阴阳闭环记录挤出视野。
    rows = con.execute(
        "SELECT l.* FROM calib_log l JOIN items i ON i.id = l.item_id "
        "ORDER BY l.id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

def auto_log(kind, message):
    """写入一条引擎自主核对的审计记录（自动核对记录面板的来源）。"""
    con = connect()
    con.execute(
        "INSERT INTO auto_log(created_at,kind,message) VALUES(?,?,?)",
        (time.time(), kind, message))
    con.commit(); con.close()

def list_auto_log(limit=40):
    con = connect()
    rows = con.execute(
        "SELECT id,created_at,kind,message FROM auto_log ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

def list_audit_log(limit=80):
    """合并「自动核对记录」面板所需的全部审计消息，统一按时间倒序、带时间戳：
    - auto_log：引擎自主核对（心跳 sweep / 发现 discover / 自检 health）
    - calib_log：阴阳互纠与系统消息（yang->yin / yin->yang / system）
    归一化为 {created_at, tag, cls, message}，cls 直接对接前端 .dir 配色。"""
    TAG = {
        # auto_log.kind
        "sweep":    ("d-sys", "心跳"),
        "discover": ("d-yang", "发现"),
        "health":   ("d-yin", "自检"),
        # calib_log.direction
        "yang->yin": ("d-yang", "阳→阴"),
        "yin->yang": ("d-yin", "阴→阳"),
        "system":    ("d-sys", "系统"),
    }
    con = connect()
    merged = []
    for r in con.execute(
        "SELECT created_at,kind,message FROM auto_log ORDER BY id DESC"):
        cls, tag = TAG.get(r["kind"], ("d-sys", "核对"))
        merged.append({"created_at": r["created_at"], "tag": tag, "cls": cls,
                       "message": r["message"]})
    # 阴阳互纠 + 系统消息（剔除孤儿：仅保留仍存在条目的记录，避免测试/种子残留）
    for r in con.execute(
        "SELECT l.created_at,l.direction,l.message FROM calib_log l "
        "JOIN items i ON i.id = l.item_id ORDER BY l.id DESC"):
        cls, tag = TAG.get(r["direction"], ("d-sys", "系统"))
        merged.append({"created_at": r["created_at"], "tag": tag, "cls": cls,
                       "message": r["message"]})
    con.close()
    merged.sort(key=lambda x: x["created_at"], reverse=True)
    return merged[:limit]

def audit_stats():
    """日志 / 缓存型数据（自动核对记录的来源）的占用与计数，供前端清理入口展示。
    log_bytes 为估算值：消息 UTF-8 字节 + 每条约 60 字节固定开销（id/时间/方向/索引页）。"""
    con = connect()
    row = con.execute(
        "SELECT (SELECT COUNT(*) FROM auto_log) AS a,"
        "       (SELECT COUNT(*) FROM calib_log) AS c,"
        "       (SELECT COALESCE(SUM(LENGTH(message)),0) FROM auto_log) AS am,"
        "       (SELECT COALESCE(SUM(LENGTH(message)),0) FROM calib_log) AS cm"
    ).fetchone()
    con.close()
    a, c = int(row["a"]), int(row["c"])
    log_bytes = int(row["am"]) + int(row["cm"]) + (a + c) * 60
    db_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    return {"auto_count": a, "calib_count": c,
            "log_bytes": log_bytes, "db_bytes": db_bytes}

def purge_audit_log(keep_days=30):
    """清理不需要长期保存的日志 / 缓存型数据：
    - auto_log（引擎自主核对，纯瞬时审计，每天早/中/晚三刻各一条心跳）保留最近 keep_days 天，更早删除；
    - calib_log（阴阳互纠 / 系统消息）保留最近 keep_days×3 天（校准历史更值得留）；
    - 一并清除指向已删除条目的孤儿记录，避免无限增长。
    删除后 VACUUM 真正回收磁盘空间。"""
    cutoff_auto = time.time() - keep_days * 86400
    cutoff_calib = time.time() - keep_days * 3 * 86400
    con = connect()
    n_auto = con.execute(
        "DELETE FROM auto_log WHERE created_at < ?", (cutoff_auto,)).rowcount
    n_calib = con.execute(
        "DELETE FROM calib_log WHERE created_at < ? "
        "OR (item_id IS NOT NULL AND item_id NOT IN (SELECT id FROM items))",
        (cutoff_calib,)).rowcount
    con.commit(); con.close()
    try:
        c2 = connect(); c2.execute("VACUUM"); c2.close()
    except Exception:                              # noqa: BLE001
        pass
    return {"ok": True, "deleted_auto": n_auto, "deleted_calib": n_calib,
            "stats": audit_stats()}

