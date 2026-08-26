---
name: lantern-kb
title: 灯笼·多维轴知识库（KB 接入指引）
description: 灯笼多维轴知识库的概念指引与路由 Skill。KB 的全部 kb_* 工具已由「lantern-kb」MCP 连接器原生暴露给 Agent（检索/定位/关系/图谱/校准/摄入/灵感孵化等），本 Skill 不重复声明工具，只负责讲清「何时用、坐标模型是什么、如何与 lantern-method 配合」。当 Agent 需要「查知识库 / 找相关知识 / 沿图谱推理 / 评估文本双尺度坐标」时，优先调用 lantern-kb 连接器的 kb_* 工具；本 Skill 提供概念与路由。
agent_created: true
---

# 灯笼·多维轴知识库（KB 接入指引）

**角色**：KB 的「概念指引 + 路由」薄壳。KB 工具本身由 **lantern-kb MCP 连接器**原生提供（与 REST / CLI 同源、行为一致），本 Skill **不再重复声明 38 个工具**，只讲清概念、触发场景与组合方式，避免与连接器双路重复。

**工具从哪来**：`backend/mcp_server.py`（纯标准库 stdio MCP 服务器，server 名 `lantern-kb`）把 `kb.py` 的全部工具暴露给支持 MCP 的 Agent。连接器已登记在 `~/.workbuddy/.mcp.json`，在连接器管理中点 **Trust** 即启用；之后 Agent 像调 GitHub 工具一样直接调 `kb_*` 工具。

**边界**：本 Skill 只做 KB 消费侧的概念与路由（检索 / 定位 / 关系 / 图谱），不接管认知编排；构成逻辑（领域带 / 阈值 / provider）由 KB 自身维护。

## 何时用 / 怎么用

接到知识相关任务时，直接调用 lantern-kb 连接器的工具：

1. `kb_schema` —— 先看坐标空间（领域带 / 阈值 / provider / 独立性）。
2. `kb_query` / `kb_context` —— 取相关知识，聚合成可直接粘贴进自身 prompt 的上下文。
3. `kb_relate` / `kb_traverse` —— 顺藤摸瓜，发现跨域知识链。
4. 新知识产出后 `kb_add` 入库定位（碰撞自动闭环一次）。

完整参数与返回体见仓库 [`AGENTS.md`](../../AGENTS.md)；连接器工具列表即 AGENTS.md 所列 38 个（以 `kb list` / MCP `tools/list` 实时为准）。

## 双尺度坐标速记

- **主尺（main）**：0–100 横梁，四带 —— 人文[0,25) / 社会科学[25,50) / 自然科学[50,75) / 形式科学[75,100)。
- **游标（vernier）**：0–100 逻辑演绎深度（描述→归纳→条件推断→结构化论证→形式证明）。
- **offset** = 游标值 − 所属领域带典型游标值；`|offset| > 阈值(默认18)` 即「离域典型远」，触发闭环与候选边（只摊开差异、不下优劣结论）。
- **独立性守卫**：`kb_state` 返回 Pearson r；`≥0.6` 且样本充足时两尺坍缩、真拉闸隔离偏移。

## 与 lantern-method 的配合

`lantern-method` 负责认知编排（定透镜 / 投影 / 冗余检查 / 反馈轴 / 绩点生命周期 / 编排写回）；写回 KB 时调用本连接器的 `kb_*` 工具即可，两层只走干净 API，Skill 不直接对 KB 跑裸 SQL。

## 依赖与隔离

- 纯 Python 标准库；无需 `pip install`，无需服务在线。
- 真实模型凭据由仓库自身 `.env` / `llm_config.json` 提供；不填则走本地启发式，全功能可用。
- `lantern.db` / `articles/*.md` / `.env` 已被 `.gitignore` 排除，演示数据由 `seed_demo.py` 合成生成。

> 手动/调试备用：仓库 `backend/kb_cli.py` 与 `skills/lantern-kb/scripts/lantern_kb.py` 仍可用 CLI 直连，但**仅供人工排障**，不是 Agent 的并行调用路径。
