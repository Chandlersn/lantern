#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灯笼 · 多维轴知识库 —— Skill 薄壳转发器

本脚本是 `lantern-kb` Skill 的入口：定位仓库根下的 `kb_cli.py` 并原样转发参数。
`kb_cli.py` 会自行切换到仓库根，直接读取 `lantern.db`，**无需 server.py 在线**。

用法：
    python lantern_kb.py <tool> '<json-args>'
    python lantern_kb.py list          # 列出全部 29 个 kb_* 工具

可用环境变量 LANTERN_KB_DIR 显式指定仓库根（含 kb_cli.py 的目录）。
"""
import os
import sys
import subprocess


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    # 仓库根 = skills/lantern-kb/scripts → ../../..
    repo = os.environ.get("LANTERN_KB_DIR") or os.path.normpath(
        os.path.join(here, "..", "..", ".."))
    kb_cli = os.path.join(repo, "kb_cli.py")
    if not os.path.isfile(kb_cli):
        alt = os.path.join(repo, "lantern-caliper", "kb_cli.py")
        if os.path.isfile(alt):
            kb_cli = alt
    if not os.path.isfile(kb_cli):
        sys.stderr.write(
            f"找不到 kb_cli.py：已尝试 {kb_cli}\n"
            f"请设置环境变量 LANTERN_KB_DIR 指向含 kb_cli.py 的仓库根。\n")
        return 2
    return subprocess.run([sys.executable, kb_cli, *sys.argv[1:]]).returncode


if __name__ == "__main__":
    sys.exit(main())
