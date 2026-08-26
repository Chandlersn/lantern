# 灯笼 · 多维轴知识库 —— Agent 接口规范

> 本知识库基于「游标卡尺」双尺度定位：主尺 = 学科领域（阳·感知归类），游标 = 逻辑演绎深度（阴·深层推理）。
> 两尺输入在**输入层互补切分**后分别交给真实大模型，互不可见，从而在同一个模型上保住两尺独立性。
> 偏移（游标 − 领域带典型游标值）触发阴阳闭环，并产出知识图谱候选边（跨域逻辑同构 / 未形式化）。

## 核心定位：人是定义者，Agent 是使用者

- **人类层（定义台 / 展示窗）**：人只负责定义「构成逻辑」与「展示形式」——
  领域带如何划分（`schema.json` 中的 `bands`）、碰撞阈值、双尺 provider、Agent 的授权边界。
  这些通过前端「设置」配置与校验，也可经 `kb_mode` / `kb_schema` 读取。
- **Agent 层（运行时 / 消费方）**：知识库真正的使用方是 Agent。检索、找关联、跨边推理、
  把相关知识组装成上下文喂给自己——「怎么使用、怎么处理数据的关联性」全是 Agent 的职责。
  本规范列出的全部工具，Agent 均可自主调用。

> 前端界面（`frontend/index.html`）只是**展示窗**，不是交互窗口。人不在界面里"用"知识库，
> 而是定义它、校验它；Agent 在运行时通过 REST / MCP 真正消费它。

任何 Agent 都可通过**三条等价通道**调用同一套能力：

| 通道 | 适用对象 | 接入方式 |
|------|----------|----------|
| **REST** | HTTP 型 Agent / 脚本 / 浏览器 | `http://127.0.0.1:8731/api/kb/*`（先 `python backend/server.py`） |
| **MCP** | 支持 Model Context Protocol 的 Agent（Claude Desktop / Cursor / 框架） | `backend/mcp_server.py`，server 名 `lantern-kb` |
| **Skill + CLI** | WorkBuddy 等自带工具链的 Agent | 安装 `lantern-kb` Skill，经 `backend/kb_cli.py` 直连，无需服务在线 |

三条通道共享 `kb.py` 的同一份 `TOOLS` 与 `dispatch`，行为完全一致。

---

## 知识文章：本地储存与点击查看协同

知识文章**双重落地**，二者始终保持同步：

1. **数据库（唯一真相源）** —— `lantern.db` 的 `items`（title/content/created_at）+ `readings`（双尺坐标）。
   这是检索、定位、关系计算的依据，永不依赖外部文件。
2. **本地文件镜像** —— 每条知识在 `articles/<id>.md` 同步落一份人类可读、可用外部编辑器改写的 Markdown。
   文件带 frontmatter 元信息（id/title/band/坐标/碰撞/created_at），正文即原文。

**协同闭环**（任一处改动都能回流到另一处）：

| 动作 | 触发 | 结果 |
|------|------|------|
| 保存新知识 | `kb_add` / 界面「保存这条知识」 | 写 DB + 自动生成 `articles/<id>.md` |
| 在知识库内改写并保存 | `kb_update` / 阅读页「保存修改」 | 更新 DB 并重测坐标 + 回写 `.md` |
| 在外部编辑器改了 `.md` | `kb_reload`（API；阅读页该按钮已替换为「删除」） | 读回正文 → 灌入 DB 并重测坐标 |
| 点开查看全文 | `kb_article` / 界面「阅读」 | 返回全文 + 本地文件路径（可复制去文件夹打开） |

> 设计要点：**DB 永远是坐标与检索的真相源**，`.md` 是可读镜像与编辑入口。
> 因此即便 `.md` 被人误删，知识不会丢；外部改完用 `kb_reload` 一键同步即可。

---

## 工具清单（38 个）

### 人类定义 / 配置（构成逻辑）
| 工具 | 说明 |
|------|------|
| `kb_schema` | 读取「构成逻辑」快照：领域带、阈值、模式、独立性、模型、概念层 |
| `kb_mode` | 切换双尺 provider：`heuristic`（本地）/`llm`（真实大模型） |
| `kb_axes` | 领域轴定义与领域分布（各 axis 的 domain 与计数） |

### 摄入与本地协同（存与看）
| 工具 | 说明 |
|------|------|
| `kb_add` | 摄入知识：自动双尺定位 + 生成候选边（碰撞时自动闭环一次） |
| `kb_import` | 从文本 / 目录批量摄入知识 |
| `kb_import_axes` | 导入领域轴定义（外部分类体系接入） |
| `kb_update` | 在知识库内改写并保存：更新正文、重测双尺坐标、回写 `articles/<id>.md` |
| `kb_reload` | 从本地 `articles/<id>.md` 重新载入正文回灌 DB 并重测双尺 |
| `kb_article` | 取某条知识全文 + 本地文件路径（界面阅读 / 「打开本地文件」用） |
| `kb_delete` | 删除条目（连同文章镜像与关联记录） |
| `kb_link` | 手动建立硬链（作者意图 `[[...]]`） |
| `kb_backup` | 快照备份当前库（含 articles 镜像），返回快照列表 |

### Agent 运行时 · 检索与定位
| 工具 | 说明 |
|------|------|
| `kb_query` | 按自由文本检索（离线评分 + `<mark>` 高亮），无需 embedding |
| `kb_neighbors` | 按双尺坐标找最近邻（相似知识发现） |
| `kb_search` | 按领域带 + 演绎深度区间过滤（结构化检索） |
| `kb_retrieve` | 取结构化知识条目（按 id / 标题） |
| `kb_position` | 仅定位不入库：判断一段文本的坐标（供 Agent 评估归属） |
| `kb_fragments` | 片段级检索定位（长文内部锚点） |
| `kb_similar` | 语义相似（embedding）检索 top-k |
| `kb_suggest_links` | 引擎建议的关联边（共现 / 语义 / 跨域桥接） |

### Agent 运行时 · 关系与图谱
| 工具 | 说明 |
|------|------|
| `kb_edges` | 列出知识图谱候选跨学科边（可按状态过滤） |
| `kb_relate` | **关系图**：给定知识，返回邻域 + 指向它的候选边 + 关系摘要 |
| `kb_context` | **检索增强包**：把相关知识聚合成可直接喂给 Agent 自身 prompt 的文本 |
| `kb_traverse` | **多跳遍历**：沿候选边扩展 N 跳，发现跨领域知识链 |
| `kb_backlinks` | 反向链接（哪些知识指向它） |

### Agent 运行时 · 状态与校准
| 工具 | 说明 |
|------|------|
| `kb_state` | 知识库总览（条目数 / 候选边 / 独立性检验 / provider 模式 / LLM 状态） |
| `kb_health` | 健康自检（领域分布 / 耦合 / 漂移预警） |
| `kb_calibrate` | 对指定条目运行阴阳闭环校准（碰撞 unresolved 时 Agent 可调用） |
| `kb_reconcile` | 以学科域(axis_domain)为语义锚，把条目主尺位置收敛回该域所属主干带中心，消除「主尺带与学科域相冲突」的错位；保留游标(vernier)不动，残留偏移视为深度相对学科域典型的信号。 |

### 向量与维护
| 工具 | 说明 |
|------|------|
| `kb_embed_rebuild` | 重建 embedding 索引（换模型或索引损坏后） |

### 灵感孵化闭环（sparks）
| 工具 | 说明 |
|------|------|
| `kb_sparks` | 列出灵感碎片（最上游原料层，无坐标随手记）。可传 status 过滤（raw/incubating/hatched），用于查看待孵化原料或已孵化溯源。 |
| `kb_add_spark` | 捕获一条灵感碎片（真正的知识出发点）。content 为随手记想法，title/tags 可选；刻意不做双尺度投影，投影在孵化时由 kb_hatch_spark 完成。 |
| `kb_update_spark` | 编辑一条灵感碎片（content/title/tags 任一可改，不给则不改）。碎片与知识条目互相独立，已孵化的碎片也允许在此改原始记录。 |
| `kb_hatch_spark` | 智能孵化灵感碎片：冗余闸门→投影富化→全库关联发现(以新节点为中心写软边)→反馈轴自检→簇血缘→事件日志。返回决策/关联数/反馈/兄弟等报告。 |
| `kb_draft_hatch` | 智能孵化·阶段一：对灵感碎片生成「碰撞创作草稿」（结合知识库相关内容合成，不落库）。落库请再调 kb_commit_hatch。 |
| `kb_commit_hatch` | 智能孵化·阶段二：用户微调草稿后确认入库。content 为用户编辑后的正文（必填）；按冗余闸门自动决定并入既有条目或新建。返回六阶段完整报告。 |
| `kb_spark_clusters` | 灵感碎片的离线聚类萌发：关键词共现把相近碎片聚成主题簇，只呈现结构、不下结论；供决定哪些该孵化。 |
| `kb_hatch_stats` | 智能孵化事件聚合：总孵化数、按决策(new/merged)分布、按学科域分布、近 7 天趋势、累计关联发现/反馈/簇血缘数。供 Skill 据以校准轴绩点。 |

---

## 一、REST 通道

服务启动（在仓库根目录）：

```bash
python backend/server.py        # 监听 127.0.0.1:8731
```

所有 `kb_*` 工具均以 `POST /api/kb/<tool>` 暴露，请求体 JSON 与下方 MCP `arguments` 同构；
另有若干只读端点（`GET /api/state`、`/api/graph`、`/api/schema`、`/api/feedback` 等）供前端轮询。
返回体为 JSON。

若干典型调用：

### `POST /api/kb/add`
```json
{ "title": "可选标题", "content": "知识正文（必填）", "run_closure": true }
```
返回：定位结果 `item` + 候选边 `edges`。

### `POST /api/kb/query`
```json
{ "text": "动量守恒", "top_k": 5 }
```
返回：`results` 按相关性降序，含 `score` 与 `<mark>` 高亮 `snippet`。

### `POST /api/kb/neighbors`
```json
{ "item_id": 6 }            // 或 { "text": "三段论推理" }
```
返回：`target` 坐标 + 最近邻 `neighbors`。

### `POST /api/kb/search`
```json
{ "band": "形式科学", "depth_min": 60, "depth_max": 100, "top_k": 20 }
```
返回：`matches`（任一过滤条件可省略）。

### `POST /api/kb/position`
```json
{ "text": "因为所有人都会死，所以苏格拉底会死" }
```
返回坐标，不写入库。

### `POST /api/kb/relate`
```json
{ "item_id": 10 }          // 或 { "text": "一段待定位文本" }
```
返回：`target` 坐标 + 最近邻 `neighbors` + 指向它的候选边 `edges_touching` + `summary`（关系摘要）。

### `POST /api/kb/context`
```json
{ "query": "不完备 形式系统", "top_k": 3, "include_edges": true, "max_chars": 2200 }
```
返回：`packet` 为可直接粘贴进 Agent 自身 prompt 的检索增强上下文文本。

### `POST /api/kb/traverse`
```json
{ "start_id": 9, "hops": 2, "kind": "under-formalized" }
```
返回：从起点沿候选边扩展 N 跳的 `visited_ids` / `nodes` / `edges_traversed`。

### `GET /api/kb/article?id=3`
返回单条知识全文 + 本地文件路径（`file` / `file_exists` / `markdown`）。

---

## 二、MCP 通道（stdio JSON-RPC 2.0）

在 MCP 客户端配置中注册（路径请替换为你的仓库根与 Python 解释器）：

```json
{
  "mcpServers": {
    "lantern-kb": {
      "command": "<你的 python 解释器绝对路径>",
      "args": ["<仓库根>/backend/mcp_server.py"],
      "cwd": "<仓库根>"
    }
  }
}
```

任何 MCP 客户端执行 `initialize` → `tools/list` 即可发现上述 38 个工具，
用 `tools/call` 调用，参数为 `arguments`（与 REST 请求体同构）。
返回 `content[0].text` 为 JSON 字符串（与 REST 返回体同构）。

---

## 坐标语义

- **主尺（main）**：0–100 横梁，分四带 —— 人文[0,25) / 社会科学[25,50) / 自然科学[50,75) / 形式科学[75,100)。
- **游标（vernier）**：0–100 逻辑演绎深度（描述 → 归纳 → 条件推断 → 结构化论证 → 形式证明）。
- **offset** = 游标值 − 所属领域带的典型游标值；`|offset| > 阈值(默认18)` 即「离域典型远」，触发闭环与候选边。
  > 设计原则：偏移只描述坐标差异、不下优劣结论；阈值仅作注意力过滤，不把偏离当缺陷。

## 独立性守卫

`kb_state` 返回 Pearson `r`（主尺 vs 游标读数）：`<0.6` 健康，`≥0.6` 且样本充足时判定两尺坍缩并**真拉闸**，
隔离偏移、保留条目，避免把相关噪声继续喂进 readings。当前用同一模型 + 输入互补切分实测 `r≈0.35`，独立性良好；
若 r 攀升，建议游标换异构模型。

## 依赖与隔离

- 纯 Python 标准库（`sqlite3` / `urllib` / `json` / `re` / `math`），`pip install` 非必需。
- 真实模型凭据由仓库自身目录的 `.env`（默认值）与 `llm_config.json`（用户自定义，优先）提供，
  不依赖任何外部目录。
- 数据库 `lantern.db`、缓存 `llm_cache.db`、密钥 `.env` 已被 `.gitignore` 排除；演示数据由 `backend/seed_demo.py` 合成生成。

---

## 三、Skill + CLI 通道（WorkBuddy 自带工具）

让 WorkBuddy（或同类 Agent）把知识库当成**自带可调用的工具**，在任意对话里联合使用：

1. 安装 `lantern-kb` Skill（封装 `kb.py` 的全部工具）。
2. 调用入口 `backend/kb_cli.py`，由 Python 运行：

```bash
python backend/kb_cli.py <tool> '<json-args>'
```

脚本自切换 cwd 到仓库根，直接读 `lantern.db`，**不依赖 `backend/server.py` 在线**。
`python kb_cli.py list` 列出全部 38 个工具名；其余用法与 MCP 工具一一对应。

典型"联合使用"：接到知识相关任务 → `kb_schema` 看坐标空间 → `kb_query`/`kb_context` 取知识喂推理
→ `kb_relate`/`kb_traverse` 顺藤摸瓜 → 新知识产出用 `kb_add` 入库定位。
