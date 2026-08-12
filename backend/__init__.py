#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼 · 多维轴知识库 —— 后端服务层（backend）
================================================================
本目录承载「服务端 Python」，与前端（frontend/ 静态 SPA）、引擎
（lantern_caliper/ 核心业务逻辑）、provider（llm.py）三层解耦：

  · server.py        HTTP 服务：REST API 路由表 + 静态前端托管
  · routes.py        REST 路由表与 handler（与 HTTP 传输层解耦）
  · kb.py            Agent 工具门面（29 个 kb_* 工具，REST / MCP / CLI 同源）
  · kb_cli.py        命令行直连入口（无需服务在线，直接读 lantern.db）
  · mcp_server.py    MCP stdio 入口（server 名 lantern-kb）
  · seed_demo.py     合成演示数据生成器

所有文件统一把「仓库根」注入 sys.path，使 lantern_caliper / llm 可被导入；
kb_cli.py 额外把工作目录切到仓库根，保证 lantern.db / .env 相对路径正确解析。
"""
