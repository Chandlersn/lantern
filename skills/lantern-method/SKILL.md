---
name: lantern-method
title: 灯笼·多维轴 KB 策展方法
description: 本 Skill 将用户对某个概念或判断的理解，通过多维轴投影与冗余检查拆解成一条结构化知识条目并写回 lantern-caliper 知识库。当用户要求「分析一个概念」「多视角拆解一个问题」「把这次理解沉淀进知识库」「更新 KB 里的某条知识」「给 KB 做正交体检（合并高耦合轴、休眠长期不用的轴）」时调用。
agent_created: true
---

# 灯笼·多维轴 KB 策展方法

**角色**：lantern-caliper 知识库的策展员（KB curator）。

**任务**：接收用户给出的一个概念，通过多视角拆解产出一条结构化知识条目，写入 KB。

**硬约束**：
- 不做学术分析，不穷尽概念的所有维度。
- 产出最终要入库；可检索、无冗余，比深度更重要。
- 每次分析只跑一轮，不做多轮迭代。

> 引擎脚本 `scripts/lantern_method.py` 与本文件同级，会自动从仓库根（或 `backend/`）定位知识库（`kb.py` 所在目录）；也可用环境变量 `LANTERN_KB_DIR` 显式指定。

---

## 流程总览（严格执行这 6 步）

1. **定透镜（A）**：跑 `kb-stats`，按决策树选 3–5 个分析透镜。
2. **投影（B）**：对每个透镜填模板，产出 `projection`。
3. **冗余检查 + 计分（C）**：逐对检查耦合标记 `high_coupling`，把 B+C 交给引擎 `update-scores`。
4. **反馈轴（D）**：对综合结论做自我对抗审查，揪薄弱点 / 盲区 / 过度推断，修订回分析。
5. **写回 KB（E）**：统一走 `upsert-kb`（命中增量更新 / 未命中新增；反馈轴不进正文，落独立收件箱）。

> 语义信号健康由 KB 引擎在写入时守护：写回前可用 `kb_state`（见仓库 AGENTS.md）查看独立性 r 与信号状态；embedding 退化时引擎自动挂起语义链，无需 Skill 侧额外命令。

---

## 概念约定（两个易混词）

- **存储坐标**：知识"存在哪"——主尺=学科领域带 × 游标=演绎深度，外加 `axes` 分类法（`domain|dimension`）。由 KB 自身维护。
- **分析透镜**：本次分析时从 KB 域分布派生的正交视角，格式同为 `domain|dimension`（如 `经济|本质`）。由本次分析提议。
- 关系：分析透镜是存储坐标的**下游产物**，不反向改写领域带。两者格式相同但含义不同。

---

## 步骤 A — 选透镜（决策树）

1. 运行：
   ```
   python scripts/lantern_method.py kb-stats
   ```
2. 看返回的 `axis_domain_distribution`（**按学科聚合的条目数**，判冷暖用）：
   - **核心学科的条目数 ≥ 3（暖启动）**：从该学科 + `axes_list` 绩点最高的 2 个学科选透镜，共 **3–5 个**。
   - **条目数 < 3（冷启动）**：自主提议 3–5 个透镜，全部标 `"tentative": true`。
   - **判冷暖只用 `axis_domain_distribution`**；不要用 `domain_distribution`（那是游标卡尺的 4 领域带，与学科标签不是同一套）。
3. 检查选定列表：
   - 同一 `dimension` 出现 ≥ 2 次 → 删掉多余的。
   - 所有透镜都来自同一 `domain` → 至少补 1 个其他 domain 的。
4. 输出格式：
   ```json
   {"axes":[{"domain":"经济","dimension":"本质","tentative":false},{"domain":"哲学","dimension":"矛盾","tentative":false}]}
   ```

---

## 步骤 B — 沿轴投影（填空模板）

对每个透镜，**复制以下模板填入**（不增删字段）：

```json
{
  "name": "通货膨胀的购买力侵蚀效应",
  "rationale": "从经济学本质切入，揭示通胀的核心伤害机制",
  "projection": "通货膨胀本质上是对持有现金者的隐性征税——物价持续上涨使同等金额购买力缩水，固定收入群体承受不成比例损失，而资产持有者反而可能因资产价格同步上涨而受益。",
  "stance": "support",
  "orthogonal": true
}
```

规则：
- `name` 必须是"概念 + 具体切入点"，**禁止**只写"经济视角"这种空泛名称。
- `projection` 必须含至少一个**因果判断或对比关系**，**禁止**纯描述（如"通货膨胀是指物价上涨"）。
- 若某透镜 `projection` 与另一个说的是同一件事，把该透镜 `orthogonal` 填 `false`。

---

## 步骤 C — 冗余检查 + 计分

逐对检查步骤 B 的所有 `projection`：
- 轴 A 与轴 B 是否换了个说法却核心判断相同（耦合）？
- 判断标准：删掉轴 A 的 `projection` 后，轴 B 是否已覆盖同样信息？是 → `score ≥ 7`。

输出格式：
```json
{
  "pairwise": [
    {"a":"经济|本质","b":"社会|矛盾","score":3,"confidence":0.8,"reason":"一个讲购买力机制，一个讲分配冲突，角度不同"},
    {"a":"经济|本质","b":"金融|本质","score":8,"confidence":0.9,"reason":"都在说'通胀是隐性征税'，只是换了领域标签"}
  ],
  "high_coupling": [["经济|本质","金融|本质"]]
}
```

若存在 `high_coupling`：**保留**信息量更大的轴，**删除**另一个，最终输出注明"已合并：X 与 Y 耦合，保留 X"。

计分（B、C 交引擎确定性计算，无需手算）：把步骤 B 的投影整理为 `{"axes":[{"domain","dimension","projection","orthogonal"}]}` 结构传入 `--gen`。
```
python scripts/lantern_method.py update-scores --gen '<步骤B的JSON>' --review '<步骤C的JSON>' --concept '概念名'
```
引擎自动：良好轴加绩点；高耦合（`score≥7` 且 `confidence≥0.6`）加权扣分；长期未用活跃轴缓慢衰减。

---

## 步骤 D — 反馈轴（自我对抗审查）

对步骤 B 全部 `projection` + 步骤 C 合并后的核心判断，做红队审查：以最不利角度审核心判断与全部投影，找出会被真实反驳之处，把修订反馈回分析。这一步是元认知，不是再加一个分析透镜。

**逐个回答以下 6 问**（每问必须落到具体投影或判断，禁止空话）：

1. **核心判断最弱的支撑点**：哪个投影没撑住核心判断？差在哪？
2. **最强反论据**：陈述一个即使你不同意也最有力的反面论证（不要稻草人）。
3. **隐藏假设**：本次分析成立依赖哪些未言明前提？
4. **透镜盲区**：哪些重要 `dimension` 没被纳入？为何可能漏掉关键视角？
5. **内部张力**：投影之间有无未察觉的矛盾？
6. **过度推断**：核心判断是否在投影实际产出范围之外跳跃？

输出格式：
```json
{
  "core_verdict_weakest_support": "经济|激励 轴只论证了偏差'被利用'，未证明它'必然发生'",
  "strongest_counter": "偏差也是 profitable heuristic——多数日常情境成本低收益高，'失灵'只在特定复杂环境",
  "hidden_assumptions": ["人脑算力约束恒为瓶颈", "现代环境普遍更复杂"],
  "blind_spots": ["未纳入神经可塑性维度", "未考察文化差异维度"],
  "internal_tension": "无（各投影互补）",
  "over_reach": "把'默认启发式'直接等同'失灵'跨越了证据",
  "verdict_revised": "认知偏差是有限算力下的节能默认设置，在现代复杂/激励错配环境误触发频率更高",
  "must_revise_before_write": true
}
```

闭环规则：
- 反馈经 `upsert-kb` / `push-feedback` 落独立的 `feedback_inbox` 表（**不进文章正文**），作为消息推送与集中收件箱的数据源，由前端呈现为两条通道（实时逐条推送 + 侧边持久收件箱）。
- 若 `must_revise_before_write` 为 `true`：**先用 `verdict_revised` 替换核心判断**并软化相关 `projection`，再进步骤 E。
- 即使不必修订，也**必须至少指出 1 个真实弱点**（强反论据 / 盲区 / 隐藏假设之一）。禁止只夸不批。

---

## 步骤 E — 写回 KB

1. **（可选）先看命中**：
   ```
   python scripts/lantern_method.py kb-query --text '概念名'
   ```
   命中 = top 结果 `score ≥ 4`。

2. **写回前置 · 信号守卫**：
   ```
   python scripts/lantern_method.py enforce-signal-guard
   ```
   返回 `degraded` 时**暂停写回与语义链发现**，先修好嵌入（换可信模型并 `rebuild_embeddings`）再继续。

3. **条目内容严格按此结构**（不自由发挥版式）：
   ```
   ## 核心判断
   {core_verdict，一句话}

   ## 多视角摘要
   - 【{轴1 name}】{projection 压缩到 1–2 句}
   - 【{轴2 name}】{projection 压缩到 1–2 句}

   ## 仍存张力
   {tension，无则写"无"}

   ## 元信息
   - 分析日期：{today}
   - 使用透镜：{domain|dimension 列表}
   - 冗余处理：{如有合并，注明}
   ```
   （`## 对抗审查（反馈轴）` **绝不手写进 content**——反馈经收件箱表承载，保持文章正文独立与纯洁。）

4. **写入（统一走 `upsert-kb`，内部已做检索判定）**：
   ```
   python scripts/lantern_method.py upsert-kb --title '概念·核心判断关键词' --content '...上述结构...' --axis-domain '概念的核心学科归属' --review '{"core_verdict_weakest_support":"...","strongest_counter":"...","hidden_assumptions":[...],"blind_spots":[...],"internal_tension":"...","over_reach":"...","verdict_revised":"...","must_revise_before_write":false}'
   ```
   - 命中判定用**概念名**：`--concept` 显式给定，否则引擎自动取 `--title` 中 `·` 之前部分去匹配；**不要拿完整新标题当检索词**，否则反复建重。
   - 命中（`score ≥ 4`）→ `action:"updated"`，本次 content + 日期**追加**到已有条目末尾，保留双尺定位与 id。
   - 未命中 → `action:"created"`，新建条目。
   - 引擎写回时自动抽取概念进衍生层，供「概念桥接」推荐（不污染正文）。

（`kb-context --qtext '概念'` 可一次性取回相关知识包，写投影前用来避免与已有条目重复。）

---

## 引擎命令速查

| 命令 | 作用 | 返回关键字段 |
|---|---|---|
| `kb-stats` | 拉 KB 域分布 + 轴分类法（定轴用） | `item_count`, `axis_domain_distribution`, `domain_distribution`, `axes_list` |
| `kb-query --text '<概念>'` | 自由文本检索（看命中） | `results:[{title,score,snippet}]` |
| `kb-context --qtext '<概念>'` | 聚合检索上下文包 | `packet` |
| `update-scores --gen '<B>' --review '<C>' --concept '<名>'` | 确定性更新全场轴绩点 | 按绩点排序的轴库 |
| `enforce-signal-guard` | 检测 embedding 是否退化，degraded 时挂起语义链 | `status`(healthy/degraded) |
| `feedback --domain <域> --dimension <维> --vote up\|down` | 用户对轴的投票/复活 | `score`, `state` |
| `library` | 打印当前轴库（看哪些该休眠/优选） | 按绩点排序的轴 |
| `upsert-kb --title '<t>' --content '<c>' [--axis-domain '<域>'] [--review '<反馈轴JSON>'] [--concept '<概念>'] [--hit-threshold 4.0]` | **唯一写入入口**：命中增量更新 / 未命中新增；反馈轴不进正文、落收件箱 | `action`(`updated`/`created`), `id`, `matched_score` |
| `push-feedback --title '<t>' --axis-domain '<域>' --review '<反馈轴JSON>' [--item-id <id>] [--severity info\|warn\|critical] [--must-revise 0\|1]` | 单独推一条反馈进收件箱（不依赖写回） | `feedback_id` |
| `write-kb --title '<t>' --content '<c>' [--axis-domain '<域>'] [--review '<反馈轴JSON>']` | 强制新建（**不经命中判定**，仅明确要建重复条目时用） | 入库结果 |

---

## 禁止清单

- 禁止多轮迭代（一轮分析完毕即写回）。
- 禁止 `projection` 出现纯描述（必须有因果 / 对比 / 判断）。
- 禁止在 `high_coupling` 存在时直接写回（必须先合并）。
- 禁止 `name` 使用"XX视角""XX维度"这类空泛名称。
- 禁止直接 `write-kb` 跳过命中判定（真实写入统一走 `upsert-kb`）。
- 禁止把分析透镜写回 KB 的 `axes` 分类法（透镜是下游，不改存储坐标）。
- 禁止跳过反馈轴（步骤 D）直接写回。
- 禁止反馈轴写成总结 / 复述（必须找茬 / 对抗，至少指出 1 个真实弱点）。
- 禁止在 `must_revise_before_write: true` 时，不改核心判断就直接写回。
- 禁止在信号守卫返回 `degraded` 时写回或发现语义链。
