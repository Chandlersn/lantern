---
name: lantern-kb
title: 灯笼·多维轴知识库（KB 工具）
description: 灯笼多维轴知识库的薄壳调用入口，封装 kb.py 的全部 29 个 kb_* 工具（检索/定位/关系/图谱/校准/配置），经 kb_cli.py 直接读 lantern.db，无需服务在线。当 Agent 需要「查知识库」「找相关知识」「沿知识图谱推理」「把结果喂给自己 prompt」「评估一段文本的双尺度坐标」时调用。REST/MCP 等价通道见仓库 AGENTS.md。
agent_created: true
---

# 灯笼·多维轴知识库（KB 工具）

**角色**：灯笼知识库的「运行时消费」薄壳——把知识库的能力直接交给 Agent 调用，不接管认知，只负责稳定地取数与算关系。

**任务**：让 Agent 在任意对话里把灯笼知识库当成自带工具：检索、定位、找关联、跨边推理、聚合成上下文。

> 人类定义「构成逻辑」（领域带 / 阈值 / provider）与 Agent 消费知识是两层职责。
> 本 Skill 只做消费侧——怎么检索、怎么处理关联性，全是 Agent 的职责。

## 调用方式

本 Skill 通过 `scripts/lantern_kb.py` 原样转发到仓库根的 `kb_cli.py`（后者自行切换目录、直读 `lantern.db`，**不依赖 server.py 在线**）：

```bash
python scripts/lantern_kb.py <tool> '<json-args>'
python scripts/lantern_kb.py list          # 列出全部 29 个工具
```

可用环境变量 `LANTERN_KB_DIR` 显式指定仓库根（含 `kb_cli.py` 的目录）；否则脚本从本 Skill 位置相对回溯到仓库根自动定位。

## 工具总览（29 个，与 REST / MCP 同源）

完整参数与返回体见仓库 [`AGENTS.md`](../../AGENTS.md)。按用途分六组：

1. **人类定义 / 配置**：`kb_schema`（构成逻辑快照）、`kb_mode`（heuristic/llm 切换）、`kb_axes`（领域轴与分布）。
2. **摄入与本地协同**：`kb_add`、`kb_import`、`kb_import_axes`、`kb_update`、`kb_reload`、`kb_article`、`kb_delete`、`kb_link`、`kb_backup`。
3. **检索与定位**：`kb_query`（离线评分+`<mark>`高亮）、`kb_neighbors`（最近邻）、`kb_search`（领域带+深度区间过滤）、`kb_retrieve`、`kb_position`（仅定位不入库）、`kb_fragments`、`kb_similar`（语义）、`kb_suggest_links`。
4. **关系与图谱**：`kb_edges`（候选跨学科边）、`kb_relate`（关系图+摘要）、`kb_context`（检索增强包，直接喂 prompt）、`kb_traverse`（多跳遍历）、`kb_backlinks`。
5. **状态与校准**：`kb_state`（总览+独立性 r）、`kb_health`（健康自检）、`kb_calibrate`（阴阳闭环校准）。
6. **向量与维护**：`kb_embed_rebuild`。

## 典型联合使用

接到知识相关任务时：

1. `kb_schema` —— 先看坐标空间（领域带 / 阈值 / provider / 独立性）。
2. `kb_query` / `kb_context` —— 取相关知识，聚合成可直接粘贴进自身 prompt 的上下文。
3. `kb_relate` / `kb_traverse` —— 顺藤摸瓜，发现跨域知识链。
4. 新知识产出后 `kb_add` 入库定位（碰撞自动闭环一次）。

## 双尺度坐标速记

- **主尺（main）**：0–100 横梁，四带 —— 人文[0,25) / 社会科学[25,50) / 自然科学[50,75) / 形式科学[75,100)。
- **游标（vernier）**：0–100 逻辑演绎深度（描述→归纳→条件推断→结构化论证→形式证明）。
- **offset** = 游标值 − 所属领域带典型游标值；`|offset| > 阈值(默认18)` 即「离域典型远」，触发闭环与候选边（只摊开差异、不下优劣结论）。
- **独立性守卫**：`kb_state` 返回 Pearson r；`≥0.6` 且样本充足时两尺坍缩、真拉闸隔离偏移。

## 依赖与隔离

- 纯 Python 标准库；无需 `pip install`，无需服务在线。
- 真实模型凭据由仓库自身 `.env` / `llm_config.json` 提供；不填则走本地启发式，全功能可用。
- `lantern.db` / `articles/*.md` / `.env` 已被 `.gitignore` 排除，演示数据由 `seed_demo.py` 合成生成。
