#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 —— MCP stdio 服务器（仅标准库）
====================================================================
把 kb.py 的全部工具以 Model Context Protocol 暴露给「任何支持 MCP 的 agent」：
Claude Desktop / Cursor / 各类智能体框架均可一键接入。

传输：stdio，按行分隔的 JSON-RPC 2.0。
支持方法：initialize / notifications/initialized / tools/list / tools/call / ping

实现要点：
  · stdout 只走协议 JSON，绝不 print —— 任何杂输出都会让客户端解析失败。
  · 日志一律写 stderr。
  · 同一份 kb.TOOLS / kb.dispatch，与 REST 接口行为完全一致。
"""

import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import lantern_caliper as store
import kb

SERVER_INFO = {"name": "lantern-kb", "version": "1.0.0"}
PROTOCOL_VERSION = "2024-11-05"


def _log(*a):
    print("[mcp-server]", *a, file=sys.stderr, flush=True)


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _tools_list():
    return [{"name": t["name"],
             "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in kb.TOOLS]


def _tools_call(name, arguments):
    try:
        result = kb.dispatch(name, arguments or {})
    except Exception as e:  # noqa: BLE001
        _log("tool error:", name, e)
        text = json.dumps({"error": str(e)}, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "isError": True}
    is_error = isinstance(result, dict) and "error" in result
    text = json.dumps(result, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _handle(msg):
    if not isinstance(msg, dict):
        return None
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params", {}) or {}

    # 通知（无 id）无需回复
    if msg_id is None:
        if method == "notifications/initialized":
            _log("client initialized")
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _tools_list()}}
    if method == "tools/call":
        name = params.get("name", "")
        res = _tools_call(name, params.get("arguments"))
        return {"jsonrpc": "2.0", "id": msg_id, "result": res}
    # 未知方法
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    _log("启动 lantern-kb MCP server，pid =", os.getpid())
    # 确保数据库与种子存在（与 HTTP 服务共享同一 SQLite 文件）
    try:
        store.init()
    except Exception as e:  # noqa: BLE001
        _log("init warning:", e)

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            _log("skip non-json line:", raw[:80])
            continue
        try:
            resp = _handle(msg)
        except Exception as e:  # noqa: BLE001
            _log("handler crash:", e)
            resp = None
        if resp is not None:
            _send(resp)
    _log("stdin 关闭，退出。")


if __name__ == "__main__":
    main()
