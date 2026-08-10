#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灯笼 · 多维轴知识库 —— 命令行入口（供 agent / 脚本 / 人类直接调用）

用法：
    python kb_cli.py <tool> '<json-args>'
示例：
    python kb_cli.py kb_state
    python kb_cli.py kb_query '{"text":"不完备 形式系统"}'
    python kb_cli.py kb_context '{"query":"哥德尔 不完备","top_k":3}'

所有 kb.py 的 TOOLS（13 个）均可通过此入口调用，输出 JSON（ensure_ascii=False）。
调用前会切换到脚本所在目录，以保证 lantern.db / .env 等相对路径被正确解析。
"""
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

import kb  # noqa: E402


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "list"):
        names = [t["name"] for t in kb.TOOLS]
        print(json.dumps(
            {"usage": "python kb_cli.py <tool> '<json-args>'",
             "tools": names},
            ensure_ascii=False, indent=2))
        return
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    try:
        res = kb.dispatch(name, args)
    except Exception as e:  # noqa: BLE001
        res = {"error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
