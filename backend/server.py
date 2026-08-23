#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 · 游标卡尺 —— HTTP 服务（仅标准库）
================================================================
职责分两层：
  · backend/routes.py  —— REST 路由表与业务 handler（与传输解耦）
  · 本文件            —— 纯传输层：HTTP 连接、JSON 响应、请求体解析、
                        静态前端托管、自动核对定时扫描。

静态前端位于仓库根的 frontend/（原 web/）目录；所有 /api/* 请求经
routes.match_route 派发到对应 handler。数据落 SQLite（见 lantern_caliper 包）。
"""

import json
import os
import re
import socketserver
import subprocess
import sys
import http.server
import threading
import time
from urllib.parse import urlparse, parse_qs

# server.py 位于 backend/ 子目录：把 backend/ 与仓库根注入 sys.path，
# 使 lantern_caliper / kb / routes 可被导入。
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(ROOT)                          # 切到仓库根，确保 lantern.db / .env 相对路径正确解析

import routes                          # noqa: E402  REST 路由表
import lantern_caliper as store        # noqa: E402  引擎包（供 __main__ 调 store.init）
import kb                              # noqa: E402  Agent 工具门面

PORT = 8731
WEB_DIR = os.path.join(ROOT, "frontend")   # 前端静态根：index.html / theory.html / css / js


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

    def _binary(self, data, code, headers=None):
        self.send_response(code)
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _respond(self, res):
        if isinstance(res, tuple):
            if len(res) == 3 and isinstance(res[0], (bytes, bytearray)):
                data, code, headers = res
                return self._binary(bytes(data), code, headers)
            payload, code = res
            return self._json(payload, code)
        return self._json(res)

    # ------------------------------------------------------------- GET
    def do_GET(self):
        p = urlparse(self.path)
        if not p.path.startswith("/api/"):
            return super().do_GET()               # 静态前端资源
        try:
            handler, captures = routes.match_route("GET", p.path)
            if handler is None:
                return self._json({"error": "not found"}, 404)
            return self._respond(handler(parse_qs(p.query), {}, captures))
        except Exception as e:                    # noqa: BLE001
            return self._json({"error": str(e)}, 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        p = urlparse(self.path)
        try:
            handler, captures = routes.match_route("POST", p.path)
            if handler is None:
                return self._json({"error": "not found"}, 404)
            return self._respond(handler({}, self._body(), captures))
        except Exception as e:                    # noqa: BLE001
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
