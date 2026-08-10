#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 · 游标卡尺 —— HTTP 服务（仅标准库）
静态页面 + REST API，数据落 SQLite（见 lantern_caliper 包）。
"""

import json
import os
import re
import subprocess
import sys
import http.server
import socketserver
import threading
import time
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lantern_caliper as store
import kb

PORT = 8731
ROOT = os.path.dirname(os.path.abspath(__file__))   # 仓库根：用于导入 lantern_caliper / kb / llm
WEB_DIR = os.path.join(ROOT, "web")                  # 前端静态根：index.html / theory.html / css / js


def _free_port(port):
    """
    启动前清理：仅杀掉【正在监听】本端口的进程，避免两个活服务抢同一端口。
    TIME_WAIT 残留由 allow_reuse_address=True 处理，不在此处强杀。
    """
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             timeout=10).stdout
    except Exception:                              # noqa: BLE001
        return
    if not out:
        return
    try:
        text = out.decode("utf-8", "ignore")
    except Exception:                             # noqa: BLE001
        text = ""
    for line in text.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", m.group(1)],
                                   capture_output=True, timeout=10)
                except Exception:                  # noqa: BLE001
                    pass


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass

    # 对所有响应（含静态 JS/CSS/HTML）都禁止缓存，避免浏览器用旧文件、改了前端却不生效。
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ---------------------------------------------------------- helpers
    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ------------------------------------------------------------- GET
    def do_GET(self):
        p = urlparse(self.path)
        if not p.path.startswith("/api/"):
            return super().do_GET()
        try:
            if p.path == "/api/schema":
                return self._json(store.SCHEMA)
            if p.path == "/api/state":
                data = store.list_items()
                # 列表不需要全文：整站轮询的这份响应里，正文占了绝大部分体积。
                # 保留一段摘录供预览，真要看全文时前端走 /api/kb/article。
                for it in data.get("items", []):
                    body = it.get("content") or ""
                    it["excerpt"] = body[:120] + ("…" if len(body) > 120 else "")
                    it["content_len"] = len(body)
                    it.pop("content", None)
                data["edges"] = store.list_edges()
                data["links"] = store.list_links()
                data["axes"] = store.list_axes()
                data["axis_domains"] = store.domains_of_axes()
                data["logs"] = store.list_logs()
                data["independence"] = store.independence()
                data["signal"] = store.signal_integrity()
                data["concept_count"] = len(store.list_concepts())
                data["concepts"] = store.list_concepts()
                data["schema_version"] = store.SCHEMA["version"]
                con = store.connect()
                data["mode"] = store.get_mode(con)
                con.close()
                data["llm"] = store._llm.info() if store._llm.AVAILABLE else {"available": False}
                data["metrics"] = kb.health()
                data["summary_backend"] = store.summary_backend()
                return self._json(data)
            if p.path == "/api/llm":
                return self._json(store._llm.info() if store._llm.AVAILABLE
                                  else {"available": False})
            if p.path == "/api/isolation":
                # 演示两尺输入的互补切分：这是独立性的工程根基
                text = (parse_qs(p.query).get("text") or [""])[0]
                if not text or not store.LLM_OK:
                    return self._json({"ok": False})
                return self._json({
                    "ok": True, "raw": text,
                    "main_sees": store._llm.strip_logic(text),
                    "vernier_sees": store._llm.mask_domain(text)})
            if p.path == "/api/edges":
                return self._json(store.list_edges())
            if p.path == "/api/logs":
                return self._json(store.list_logs())
            if p.path == "/api/independence":
                return self._json(store.independence())
            # -------------------------------------------- 反馈收件箱接口（GET 列表 + 未读数）
            if p.path == "/api/feedback":
                status = (parse_qs(p.query).get("status") or [None])[0]
                return self._json({"unread": store.count_unread_feedback(),
                                   "items": store.list_feedback(status),
                                   "signal": store.signal_integrity()})
            # -------------------------------------------- 灵感碎片（原料层）接口
            if p.path == "/api/sparks":
                status = (parse_qs(p.query).get("status") or [None])[0]
                items = store.list_sparks(status)
                return self._json({"items": items, "count": len(items)})
            if p.path == "/api/sparks/clusters":
                return self._json({"clusters": store.spark_clusters()})
            # -------------------------------------------- 知识库 REST 接口
            if p.path == "/api/kb/state":
                return self._json(kb.state())
            if p.path == "/api/kb/schema":
                return self._json(kb.schema())
            if p.path == "/api/kb/config":
                return self._json(store._llm.get_config())
            if p.path == "/api/kb/edges":
                status = (parse_qs(p.query).get("status") or [None])[0]
                return self._json({"edges": kb.list_edges(status)})
            if p.path == "/api/kb/article":
                iid = (parse_qs(p.query).get("id") or [None])[0]
                if not iid:
                    return self._json({"error": "缺少 id"}, 400)
                return self._json(kb.get_article(int(iid)))
            if p.path == "/api/kb/backlinks":
                iid = (parse_qs(p.query).get("id") or [None])[0]
                if not iid:
                    return self._json({"error": "缺少 id"}, 400)
                return self._json(kb.backlinks(int(iid)))
            if p.path == "/api/kb/axes":
                return self._json(kb.axes())
            if p.path == "/api/kb/similar":
                qs = parse_qs(p.query)
                q = (qs.get("text") or qs.get("q") or [""])[0]
                k = int((qs.get("k") or [5])[0])
                return self._json(kb.semantic(q, k))
            if p.path == "/api/kb/suggest_links":
                qs = parse_qs(p.query)
                return self._json(kb.suggest_links(
                    int((qs.get("k") or [8])[0]),
                    float((qs.get("min_score") or [0.0])[0]),
                    int((qs.get("min_shared") or [2])[0])))
            if p.path == "/api/kb/backups":
                return self._json({"backups": store.list_backups()})
            if p.path == "/api/graph":
                return self._json(kb.graph())
            if p.path == "/api/concepts":
                return self._json({"concepts": store.list_concepts()})
            # 概念桥接推荐（后端中间件）：给定文档，返回共享概念的其他文档，仅作桥接依据，不画成图边
            if p.path == "/api/kb/concept_neighbors":
                iid = (parse_qs(p.query).get("id") or [None])[0]
                if not iid:
                    return self._json({"error": "缺少 id"}, 400)
                return self._json({"item_id": int(iid),
                                   "neighbors": store.concept_neighbors(int(iid))})
            if p.path == "/api/audit-log":
                return self._json({"items": kb.audit_log(), "stats": kb.audit_stats()})
            return self._json({"error": "not found"}, 404)
        except Exception as e:                                  # noqa: BLE001
            return self._json({"error": str(e)}, 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        p = urlparse(self.path)
        body = self._body()
        try:
            if p.path == "/api/items":
                title = (body.get("title") or "").strip()
                content = (body.get("content") or "").strip()
                if not title or not content:
                    return self._json({"error": "标题与内容不能为空"}, 400)
                return self._json(store.add_item(title, content))
            if p.path == "/api/threshold":
                store.set_threshold(float(body.get("value", 18)))
                return self._json({"ok": True})
            if p.path == "/api/edge":
                return self._json(store.gen_edge(int(body["item_id"])))
            if p.path == "/api/edge/status":
                return self._json(store.set_edge_status(
                    int(body["edge_id"]), body.get("status", "accepted")))
            if p.path == "/api/calibrate":
                return self._json(store.calibrate(int(body["item_id"])))
            if p.path == "/api/mode":
                return self._json(store.remeasure_all(body.get("mode", "heuristic")))
            if p.path == "/api/reset":
                store.init(force=True)
                return self._json({"ok": True})
            if p.path == "/api/kb/consolidate":
                return self._json(store.consolidate_domains(
                    float(body.get("merge_jaccard", 0.5))))
            # -------------------------------------------- 知识库 REST 接口
            if p.path == "/api/kb/add":
                title = (body.get("title") or "").strip()
                content = (body.get("content") or "").strip()
                if not content:
                    return self._json({"error": "content 不能为空"}, 400)
                return self._json(kb.add_knowledge(title, content,
                                                  bool(body.get("run_closure", True)),
                                                  (body.get("axis_domain") or None)))
            if p.path == "/api/kb/query":
                return self._json(kb.query(body.get("text", ""), int(body.get("top_k", 5))))
            if p.path == "/api/kb/retrieve":
                return self._json(kb.retrieve(
                    body.get("query", body.get("text", "")),
                    body.get("filters") or {},
                    int(body.get("top_k", 10))))
            if p.path == "/api/kb/fragments":
                return self._json(kb.fragments(
                    body.get("query", body.get("text", "")),
                    body.get("filters") or {},
                    int(body.get("top_k", 8))))
            if p.path == "/api/kb/neighbors":
                iid = body.get("item_id")
                return self._json(kb.neighbors(iid, body.get("text"), int(body.get("k", 5))))
            if p.path == "/api/kb/linked_neighbors":
                iid = body.get("item_id")
                return self._json(kb.linked_neighbors(iid, int(body.get("k", 8))))
            if p.path == "/api/kb/search":
                dm = body.get("depth_min")
                dx = body.get("depth_max")
                return self._json(kb.search_dual(
                    body.get("band"),
                    float(dm) if dm is not None else None,
                    float(dx) if dx is not None else None,
                    int(body.get("top_k", 20))))
            if p.path == "/api/kb/position":
                return self._json(kb.position(body.get("text", "")))
            if p.path == "/api/kb/calibrate":
                return self._json(kb.calibrate(int(body.get("item_id"))))
            if p.path == "/api/kb/mode":
                return self._json(kb.set_mode(body.get("mode", "heuristic")))
            if p.path == "/api/kb/config_set":
                return self._json(store._llm.apply_config(body))
            if p.path == "/api/kb/config_test":
                return self._json(store._llm.test_connection(body))
            if p.path == "/api/kb/relate":
                return self._json(kb.relate(body.get("item_id"), body.get("text")))
            if p.path == "/api/kb/context":
                return self._json(kb.context(body.get("query", ""),
                                             int(body.get("top_k", 5)),
                                             bool(body.get("include_edges", True)),
                                             int(body.get("max_chars", 2200))))
            if p.path == "/api/kb/traverse":
                return self._json(kb.traverse(body.get("start_id"),
                                              int(body.get("hops", 2)),
                                              body.get("kind")))
            if p.path == "/api/kb/update":
                return self._json(kb.update_article(
                    int(body.get("item_id")),
                    (body.get("title") or "").strip(),
                    (body.get("content") or "").strip(),
                    (body.get("axis_domain") or None),
                    body.get("rev")))
            if p.path == "/api/kb/reload":
                return self._json(kb.reload_article(int(body.get("item_id"))))
            if p.path == "/api/kb/open_folder":
                return self._json(store.open_article_folder(body.get("item_id")))
            if p.path == "/api/kb/link":
                return self._json(kb.link(body.get("src_id"), body.get("dst_id")))
            if p.path == "/api/kb/unlink":
                return self._json(kb.unlink(body.get("src_id"), body.get("dst_id")))
            if p.path == "/api/kb/import_axes":
                return self._json(kb.import_axes(body.get("path")))
            if p.path == "/api/kb/similar":
                return self._json(kb.semantic(body.get("text") or body.get("q") or "",
                                              int(body.get("k") or 5)))
            if p.path == "/api/kb/backlinks":
                return self._json(kb.backlinks(int(body.get("item_id") or body.get("id"))))
            if p.path == "/api/kb/axes":
                return self._json(kb.axes())
            if p.path == "/api/kb/suggest_links":
                return self._json(kb.suggest_links(
                    int(body.get("k") or 8),
                    float(body.get("min_score") or 0.0),
                    int(body.get("min_shared") or 2)))
            if p.path == "/api/kb/import":
                return self._json(kb.import_kb(body.get("text"), body.get("entries"),
                                               body.get("directory")))
            if p.path == "/api/kb/embed_rebuild":
                return self._json(kb.rebuild_embeddings())
            if p.path == "/api/kb/delete":
                iid = body.get("item_id") or body.get("id")
                if iid is None:
                    return self._json({"error": "缺少 item_id"}, 400)
                return self._json(kb.delete(int(iid),
                                            bool(body.get("backup", False))))
            if p.path == "/api/kb/backup":
                return self._json(kb.backup(body.get("reason") or "manual"))
            # -------------------------------------------- 灵感碎片（原料层）接口
            if p.path == "/api/sparks":
                content = (body.get("content") or "").strip()
                if not content:
                    return self._json({"error": "content 不能为空"}, 400)
                return self._json(store.add_spark(
                    content, body.get("title"), body.get("tags"), body.get("source", "manual")))
            if p.path.startswith("/api/sparks/"):
                rest = p.path[len("/api/sparks/"):].strip("/")
                parts = [x for x in rest.split("/") if x]
                if not parts or not parts[0].isdigit():
                    return self._json({"error": "bad path"}, 400)
                sid = int(parts[0])
                if len(parts) >= 2 and parts[1] == "hatch":
                    return self._json(kb.hatch_spark(
                        sid, body.get("title"), body.get("axis_domain"),
                        bool(body.get("run_closure", True))))
                if len(parts) >= 2 and parts[1] == "delete":
                    return self._json({"ok": store.delete_spark(sid)})
                # 默认：改状态 / 标签
                return self._json({"ok": store.update_spark_status(
                    sid, body.get("status", "raw"), body.get("tags"))})
            # -------------------------------------------- 反馈收件箱接口（POST 状态变更）
            if p.path == "/api/feedback/read":
                return self._json({"ok": store.mark_feedback_read(int(body.get("id")))})
            if p.path == "/api/feedback/applied":
                return self._json({"ok": store.mark_feedback_applied(int(body.get("id")))})
            if p.path == "/api/feedback/dismiss":
                return self._json({"ok": store.dismiss_feedback(int(body.get("id")))})
            if p.path == "/api/feedback/delete":
                return self._json({"ok": store.delete_feedback(int(body.get("id")))})
            if p.path == "/api/feedback/apply":
                # 应用更新闭环第 1 步：仅生成修订稿，不落库；前端 diff 预览 + 用户确认后才回写
                try:
                    return self._json({"ok": True, **kb.revise_with_feedback(int(body.get("id")))})
                except Exception as e:                              # noqa: BLE001
                    return self._json({"ok": False, "msg": str(e)}, 400)
            if p.path == "/api/soft-link/confirm":
                return self._json(kb.confirm_soft_link(
                    body.get("src_id") or body.get("src"), body.get("dst_id") or body.get("dst")))
            if p.path == "/api/soft-link/dismiss":
                return self._json(kb.dismiss_soft_link(
                    body.get("src_id") or body.get("src"), body.get("dst_id") or body.get("dst")))
            if p.path == "/api/soft-links/refresh":
                res = kb.refresh_soft_links()
                # 写入引擎自主核对审计：用户手动触发也算一次「核对」
                if res.get("written"):
                    kb.auto_log("discover",
                                f"主动核对：发现 {res['written']} 组新关联"
                                f"（共现 {res.get('cooccur_written',0)} · 语义 {res.get('semantic_written',0)}），"
                                f"已自动接入图谱。")
                return self._json(res)
            if p.path == "/api/kb/create_draft":
                return self._json(kb.create_draft((body.get("title") or "").strip()))
            if p.path == "/api/audit-log/purge":
                return self._json(kb.purge_audit_log(int(body.get("keep_days", 30))))
            return self._json({"error": "not found"}, 404)
        except Exception as e:                                  # noqa: BLE001
            return self._json({"error": str(e)}, 500)


class Server(socketserver.ThreadingTCPServer):
    # Windows 下需开启地址复用：旧监听进程被 taskkill 后会留 TIME_WAIT，
    # 不复用则新进程无法立刻重绑同一端口。重复活服务的防护改由 _free_port 在
    # 启动前杀掉「正在监听」本端口的进程来承担，而非依赖不复用。
    allow_reuse_address = True
    daemon_threads = True


# 自动核对心跳节拍：每天早 / 中 / 晚三个固定时刻（本地时间，可改）
SWEEP_SLOTS = [(8, 0, "早"), (13, 0, "中"), (19, 0, "晚")]


def _next_sweep(slots):
    """返回 (距离下一个定时槽的秒数, 该槽标签)。本地时间，不足 1s 取 1s。"""
    now = time.localtime()
    now_sec = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
    best = None
    for h, m, label in slots:
        s = h * 3600 + m * 60
        diff = s - now_sec
        if diff <= 0:
            diff += 86400                       # 已过今天 -> 推到明天同一时刻
        if best is None or diff < best[0]:
            best = (diff, label)
    return max(1, best[0]), best[1]


def _start_link_sweeper(slots=SWEEP_SLOTS):
    """服务端定时扫描：独立于任何 agent / 人工操作，在每天早 / 中 / 晚三个固定时刻
    默默重算全库关联、跑健康自检，并把「引擎自主核对」审计写进 auto_log ——
    让内容图谱持续自生长、且每次核对都有迹可循。
    与写后自动发现(_refine) / 「立即核对」按钮共用 _discovery_lock 串行化，二者仍按需即时触发。"""
    def _loop():
        while True:
            delay, label = _next_sweep(slots)
            time.sleep(delay)
            try:
                res = kb.refresh_soft_links()
                if res.get("written"):
                    kb.auto_log("discover",
                                f"自动核对：发现 {res['written']} 组新关联"
                                f"（共现 {res.get('cooccur_written',0)} · 语义 {res.get('semantic_written',0)}），"
                                f"剔除 {res.get('dropped_noise',0)} 组只是措辞像的。")
                # E2 健康自检：近重复 / 高耦合条目对推入反馈收件箱
                try:
                    kb.detect_health()
                except Exception:                          # noqa: BLE001
                    pass
                # 心跳：库当前关联全貌（让「自动核对记录」始终有最新状态）
                try:
                    c = kb.summarize_links()
                    kb.auto_log("sweep",
                                f"自动核对心跳（{label}）：库共 {c['hard']} 条互链 · "
                                f"{c['cooccur']} 共现 · {c['semantic']} 语义；"
                                f"待确认 {c['unconfirmed']} · 已确认 {c['confirmed']}。")
                except Exception:                          # noqa: BLE001
                    pass
            except Exception:                              # noqa: BLE001
                pass
    t = threading.Thread(target=_loop, daemon=True, name="link-sweeper")
    t.start()


if __name__ == "__main__":
    store.init()
    _free_port(PORT)
    try:
        httpd = Server(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print(f"端口 {PORT} 已被占用，请先停掉旧进程再启动。({e})")
        sys.exit(1)
    _start_link_sweeper()                    # 每天早/中/晚三刻独立重算共现，无需 agent/人触发
    with httpd:
        print(f"灯笼游标卡尺 v3 已启动 -> http://127.0.0.1:{PORT}/")
        print(f"数据库：{store.DB_PATH}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
