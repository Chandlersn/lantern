# lantern-caliper 语义相似链接诊断报告

> 诊断对象：`D:/测试/lantern-caliper/lantern.db`（18 条目 / 62 条 links / 29 条 `provenance='semantic'` 软链）
> 方法：把每条语义链接当作诊断 Unit，用「当前 embeddings 重算余弦」作外部锚点跑闭环（读库·零写入）
> 驱动：`demo/diagnose_caliper_semantic_links.py`（已实跑，非推演）
> 阈值：取 `discover_semantic_links` 的真实 embedding 门槛 `0.62`

---

## 0. 一句话结论

**根因成立**：`embeddings` 表是三代向量混存（512 / 256 / 64 维），而 `rebuild_embeddings` 重建向量时**从不变语义链接**，`discover_semantic_links` 又跳过已连对 + 跨维对 → 链接写完即冻结，向量换了也不重算。你的"框架当诊断镜"假设被验证是对的。

**但先验叙事有 4 处与真实 DB 对不上**，修正如下。

---

## 1. 真实 verdict（实跑，n=29）

| verdict | 数量 | 含义 | 处置 |
|---|---|---|---|
| `ok` | 4 | 同维 · 当前重算 ≥ 0.62 | 保留 |
| `stale_valid` | 2 | 同维 · 当前仍 ≥ 0.62，但存储显示分偏差 > 0.10 | 重建后刷新显示即可 |
| `false_positive` | 2 | 同维 · 当前 < 0.62（链接现已误导图谱） | 删除 |
| `cross_dim` | 21 | 两端维度不一致 · 无共同比较基准 | 删除后随重建重算 |

- **仍成立（6）**：`1->86`、`69->85`、`72->85`、`78->85`（ok）；`69->72`（0.81）、`72->78`（0.75）（stale_valid，仅显示值陈旧）
- **确为假阳性（2）**：`87->88` 存储 0.76 → 当前 **−0.058（负相关）**；`87->89` 存储 0.79 → 当前 **0.097（近正交）**。这两条建立在已变向量上，图谱正在显示反向/无关的边。
- **跨维不可比（21）**：如 `46->69`(512/256)、`69->87`(256/64)、`85->90`(256/512) 等。两端落在不同向量空间，存储分来自已不存在的统一空间，**既不能证实也不能证伪，应视为失效**。
- **孤儿 / 重复 / 反向**：0 条。

---

## 2. 对先验叙事的 4 处修正（重要）

| # | 先验叙事判断 | 真实 DB 事实 |
|---|---|---|
| 1 | embeddings 维度混存 `{512,256,64}` | ✅ **正确**。实际分布：512×12、256×4、64×3（共 19 行覆盖 18 条目，1 条目有 2 行）。 |
| 2 | `semantic_links_enabled=0`，"系统自判嵌入不可信已停维护、链接是冻结产物" | ❌ **错误**。meta 表该键当前 = `'1'`（开启），`discover_semantic_links` 会真跑。链接是"**没被失效**"的陈旧产物，而非"被冻结"。`enforce_signal_guard` 只会在 `degraded` 时把开关置 0，且**不自动恢复**——所以现在开关为 1 是人工/历史置位结果。 |
| 3 | verdict 计数：ok=1 / redefine=5 / no_external_anchor=23 | ❌ **错误**。真实：ok=4 / stale_valid=2 / false_positive=2 / cross_dim=21。"仅 1 条成立"夸大了——256 维簇内（69/72/78/85）彼此仍高度相似。 |
| 4 | "rebuild_embeddings 把部分 item 重建为 512 维，却没让旧链接失效" | ✅ **方向正确，但机制更具体**：`rebuild_embeddings(force=False)` 会**跳过已有向量的条目**（断点续传），这正是 7 个旧条目（256/64）永远卡在旧维度的原因；`force=True` 才全量重算，但全函数**没有任何 `DELETE FROM links WHERE provenance='semantic'`**，故重算后链接仍冻结。 |

> 注：先验叙事还提到 `links` 表"没有 `status` 列"——✅ 正确，`links` 只有 `confirmed`(0/1)，候选闸门的 `status`(candidate/accepted/rejected) 实际落在 `edges` 表（7 行，当前全 `candidate`）。

---

## 3. 根因（机制 bug，已坐实）

1. **向量维度三代混存**：`embed_text`(search.py:297) 优先级 = 本地 bge 高维 → 远程 embed API → 本地哈希兜底。512=bge/远程好向量，256=哈希兜底，64=旧远程退化 API。7 个条目在历史兜底期被嵌入，之后 `rebuild_embeddings(force=False)` 因"已有向量"被跳过，永远没被升级到 512。
2. **重建不失效链接**：`rebuild_embeddings` 全函数无失效语义链接逻辑（见 search.py:222–255，只做 `_set_embedding`）。
3. **发现算法不重算已连对**：`discover_semantic_links`(links.py:268) 第 313 行 `if pair in linked: continue` 跳过已存在对、第 316 行 `if len(va)!=len(vb): continue` 跳过跨维对 → `refresh_soft_links` 跑一万次也不会修复/清理旧链接。链接是**写一次定终身**。

---

## 4. 顺带照出的两个设计缺陷

1. **软链绕过候选闸门**：`upsert_soft_link`(links.py:238) 默认 `confirmed=1`，`discover_semantic_links`/`discover_bridge_links` 直接写入 confirmed 软边。`schema.json` 的 `graph_edge.status=candidate|accepted|rejected` 契约在 `links` 表根本没落地（无 `status` 列）。即"候选→人工确认→入图"闸门对图谱软链是空的。
2. **links 无实时 staleness 回算**：`edges`（卡尺偏移候选边）有 `list_edges()` 逐条回算 `stale`；`links`（图谱边）**没有**。所以陈旧/跨维边不会被前端识别隐藏，照样渲染成 confirmed 连线。

---

## 5. 修复方案

### A. 数据修复（高侵入写回 · 须先备份 + 用户确认）
1. **备份**：`copy lantern.db lantern.db.bak-<时间戳>`（沙箱外）。
2. `rebuild_embeddings(force=True)` → 18 条目统一到 canonical 维度（前提是 bge 本地模型可加载；不可加载则回落 256/64，维度仍不统一，须先修模型）。
3. `DELETE FROM links WHERE provenance='semantic'` → 清掉全部陈旧软链。
4. `refresh_soft_links()` → 在统一维度下重算，得到自洽链接。
5. 复跑本驱动，确认：0 条 cross_dim、0 条 false_positive，且存储分与重算分一致。

> 风险：动真库。按纪律，**备份后再动，且须你明确说"做 A"才执行**。

### B. 代码治理（根因，让问题不再复发）
- `rebuild_embeddings` 末尾：若 `force=True` 或维度发生变化，自动 `DELETE FROM links WHERE provenance='semantic'`（让下次 `refresh_soft_links` 重建）。
- `links` 表加 `status` 列，语义/桥接软链走 `candidate`→人工确认→`accepted` 闸门（对齐 `schema.json` 契约）。
- `discover_semantic_links` 入参支持"强制重算已连对"，或新增 `prune_stale_semantic_links()` 定期清跨维/低分边。

### C. 前端兜底
- 渲染图谱边时，若两端 embedding 维度不一致（或某端无向量），**直接不渲染**该边，避免显示无效连线。
- 复用 `edges.list_edges()` 的 staleness 思路，为 `links` 加实时回算，陈旧边默认隐藏。

---

## 6. 交付物与下一步

- `demo/diagnose_caliper_semantic_links.py` —— 读库零写诊断驱动（已实跑，产出上方 verdict）。
- `demo/caliper_semantic_links_diagnosis.md` —— 本报告。

**下一步**：等你拍板是否执行方案 A（我会先备份再动）。B/C 为代码改动，可另开任务推进，不影响当前运行库。

---

## 7. 修复执行记录（已实跑 · 2026-08-26）

用户确认"继续完善"，遂按"先备份 → 验证嵌入环境 → 动真库 → 代码治理防复发"推进。

### 7.1 前置（可逆）
- 备份：`lantern.db.bak-20260826-202337`（纯复制，零写入）。
- 嵌入环境探针：本地 bge 模型可加载，`embed_text` 实跑产出 **512 维**（确认 force-rebuild 不会降级）。当前维度分布 512×12 / 256×4 / 64×3。

### 7.2 代码治理（B，根因防复发）
- `links.py` 新增 `prune_stale_semantic_links(threshold=0.62)`：把每条语义链当 Unit，用当前 embeddings 重算余弦作外部锚；孤儿(缺向量)/跨维/低分(<阈值，且只在信号 healthy 时)三类一律删除。
- `rebuild_embeddings(force 或本次有新增)` 与 `refresh_soft_links()` 均挂钩调用 prune → 语义链获得**持续 staleness 回算**，治愈"写一次定终身 + links 无实时回算"缺陷。
- `graph.py.build_graph()`：渲染前对语义边做兜底过滤（缺向量 / 跨维 / 余弦<0.62 一律不 emit），前端永不画出无效连线（C 兜底，落在后端）。
- 决策：未引入 `links.status` 候选闸门（原报告 B 项②）。理由：项目哲学是"主体性在引擎、不增加用户操作"，软链本就该引擎自主维护而非挂起待确认；正确解法是「引擎持续回算清理」而非「人工闸门」。

### 7.3 数据修复（A，写回真库）
1. `rebuild_embeddings(force=True)` → 18 条目统一 **512 维**；内置 prune 当场清掉 23 条陈旧语义链。
2. `DELETE FROM links WHERE provenance='semantic'` → 清剩余 6 条，干净出发点。
3. `refresh_soft_links()` → 统一维度下重发现，写入 **4** 条新语义链。
4. 复验：`signal_integrity=healthy`；语义链 verdict = ok:4 / false_positive:0 / cross_dim:0 / orphan:0 → **PASS**。

### 7.4 验收（可复现）
- `EMBED_DIMS = {512: 19}`（含 1 条历史重复 item_id 行，见遗留）。
- `LINKS_BY_PROV = bridge:10 / author:22 / cooccur:1 / semantic:4`。
- `build_graph()` 输出 37 条边，语义边 4 条，**0 条不可渲染** → GRAPH_CHECK PASS。
- 交付脚本：`demo/apply_semantic_links_fix.py`（写回步骤，可复跑）。

### 7.5 遗留（非阻塞，待用户拍板）
- `embeddings` 表存在 1 条重复 `item_id` 行（历史数据，非本次引入）；所有向量现为 512 维，不影响正确性，建议后续加 `UNIQUE(item_id)` 约束并去重。
- 后端 PID 24860 监听 8731，按请求读库，刷新浏览器即见新图谱；信号缓存 TTL 后自动刷新。
- 改动未提交未推送（按纪律等用户说"推"）。
