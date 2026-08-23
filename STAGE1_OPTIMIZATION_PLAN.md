# lantern-caliper 当前阶段细化优化方案（储存优化 + 领域把关）

> 阶段定位（用户确认的三层架构）：
> - **第 1 层 · 储存优化与管理知识**（当前所在）：双尺度坐标、领域把关、图谱组织、内容入库。面向人管理。
> - **第 2 层 · 检索与调用**：分层加载（L0/L1/L2）、语义召回、按需下钻。面向 agent 调用，在乎 token 预算。
> - **第 3 层 · agent 间协议沟通**：哪个 agent 调用、用什么协议（MCP/消息）、上下文如何流转。
>
> OpenViking 的 L0/L1/L2 落在第 2 层，不属当前阶段，不提前实现机制。
> 本方案只动第 1 层内能做、且不为 2/3 层过度设计的细节。

---

## 方案边界原则

1. **不实现分层加载机制本身**——那是第 2 层，当前无调用方（agent），做了是过度工程。
2. **只"为将来留形"**——把已有的 summary / axis_domain / band / tags 当作 L0 雏形显式固化，不写 L0/L1/L2 加载逻辑。
3. **领域把关是护城河，优先做扎实**——这是 OpenViking 缺、我们有差异化的地方。
4. **入库收口防污染**——根除之前"item_doms 自我强化导致脏域（重叠窗口）"的根因，属于第 1 层核心。

---

## 细化项 A：L0 摘要字段固化（为第 2 层留形，不改机制）

### 现状事实
- `items` 表已有 `summary` 列，5 篇均已有 LLM 摘要（如 #1："技能管理3.0通过调用频率与纠正频率双向印证…"）。
- 但 `summary` 目前只是"展示用字段"，未被显式定义为"L0 抽象层"的契约字段；没有长度/格式约束，没有"一句话 ≤ 100 token"的规矩。
- `axis_domain`（学科域）、`tags`、`readings.label`（band）分散存储，`items.axis_domain` 全为 None（演示态设计），领域权威在 `readings.label`。

### 改动点
- **A1. 定义 L0 契约**：在 `DOMAIN_CLASSIFICATION_CONTRACT.md` 之外新增一节"条目 L0 结构化字段"，明确：
  - `summary` = L0 抽象层，约束为"一句话 ≤ 80 汉字 / 100 token"，纯陈述、不含 markdown。
  - `axis_domain` + `band`（来自 readings） = L1 学科坐标（已存在，只补文档）。
  - `tags` = L1 关键词索引（已存在）。
- **A2. 入库校验**：在 `core.py` 的 `_write_readings` / 写入路径收口处，确保 `summary` 非空且长度受控；若 LLM 未给摘要，回退到 `summarize.py` 的启发式摘要，不允许空 summary 落库。
- **A3. 字段聚合视图**：新增 `store.item_l0(item_id)` 返回 `{title, summary, axis_domain, band, tags}` 的纯字典（不返回 content），供将来第 2 层检索直接取 L0，无需回刷历史数据。

### 验收
- 任一新文章入库后 `summary` 非空且 ≤ 80 汉字。
- `item_l0()` 对全库 5 篇返回结构化字典，字段齐全。
- 不改任何第 2 层加载逻辑。

---

## 细化项 B：领域把关闭环增强（护城河做实）

### 现状事实（已核验）
- `DOMAIN_CLASSIFICATION_CONTRACT.md` 已落地（单一事实来源）。
- `llm.py:_main_system` 已注入 §3 守门阈值（代表词≥2）+ §4 防过粗。
- `measure.py:240` 已有 `_is_broad_field` 拒回时 `push_feedback` 的调用意图，但：
  - `feedback_inbox` 表**当前 0 行**（之前验证的 id=1 是测试脚本临时连接，未落库）。
  - `push_feedback(item_id, title, axis_domain, review, severity, must_revise, pushable)` 无 `payload` 参数，`review` 是自由文本。
  - 当前 LLM 路径在 `_main_system` 自滤后很少走到拒回分支，导致闭环"名义上有、实际空转"。
- 前端无 `domain_rejected` 展示，模型也无"历史退回"可读。

### 改动点
- **B1. 闭环真正落库**：确认 `measure.py` 的 `push_feedback` 调用指向正确的 `lantern.db` 连接并 commit（修复"空转"）。每次 `_is_broad_field` 拒回，写一条 `severity='info', review='领域被守门驳回：候选={band}，已退回主干带'`，`pushable=0`（不推给用户，仅供系统收敛）。
- **B2. 即便 LLM 自滤通过，也记录"边界样本"**：当模型输出的 band 与 `_is_broad_field` 判定不一致（模型想立窄域、被系统纠正）时记一条；模型自滤正确则不计。让 `feedback_inbox` 真实积累"模型学错/被纠正"的样本。
- **B3. 前端可见（轻量）**：在"知识库健康自检"页加一个 `domain_rejected` 计数卡（读 feedback_inbox 该类条数），让用户能看到"模型累计被守门拦截 N 次、已收敛到正确域"。不展示明细，避免噪音。
- **B4. 契约自检命令**：`kb_cli.py` 新增 `selfcheck-domain` 子命令，打印全库 band 分布 + 窄域残留（命中技术词黑名单的 label）+ feedback 驳回数，作为"把关健康度"快照。

### 验收
- 跑一次 `remeasure_all(mode="llm")` 后，`feedback_inbox` 出现 domain 相关条目（非空转）。
- 前端健康页显示 domain_rejected 计数。
- `kb_cli selfcheck-domain` 输出 band 分布与窄域残留报告。

---

## 细化项 C：入库收口防污染（根除脏域根因）

### 现状事实（根因）
- 之前"重叠窗口"误分类的根因之一：`domains_of_axes()` 把 `items.axis_domain` 已有值开放为下拉选项，导致脏域（重叠窗口/RAG）自我强化污染 UI 与后续分类。
- `core.py:_enforce_band_invariant` 已在写入路径收口（主尺带 == 学科域所属主干带），但**受控域校验**（`normalize_axis_domain` 只放行 `CONTROLLED_DOMAINS`）在哪些入口真正生效需确认。

### 改动点
- **C1. 受控域白名单收紧**：所有写入 `readings.label`（band）的入口（LLM 测量、启发式、人工编辑 API）统一过 `normalize_axis_domain`——非受控域一律退回其主干带，不允许脏域落库。
- **C2. 下拉选项去自我强化**：UI / API 的领域候选列表只取 `CONTROLLED_DOMAINS`（schema.json 的 domain_registry），**不**把 `items.axis_domain` 已有值混入候选，杜绝"脏域越用越多"。
- **C3. 入库不变量测试**：新增 `tests/test_band_invariant.py`，断言：
  - 任意 item 的 `readings.label`（main）必在 `CONTROLLED_DOMAINS` 或为空。
  - `canonical_band(main_pos) == domain_band_name(axis_domain)`（当 axis_domain 受控且非空）。
  - 跑 `remeasure_all` 后全库通过。

### 验收
- 人工通过 API 传一个脏域（如 "重叠窗口"）写入，落库后 band 自动归回主干带（如 "信息检索"）。
- `tests/test_band_invariant.py` 全绿。

---

## 执行顺序建议（不跨阶段）

1. **先做 C**（防污染是地基，脏域不根除，A/B 都是沙上楼）—— C1/C2/C3。
2. **再做 B**（把守门闭环从"名义"做实）—— B1/B2/B3/B4。
3. **最后 A**（L0 留形，纯增益、风险最低）—— A1/A2/A3。

每项做完即重启服务 + 硬刷新验证，不堆叠到末尾一次性验证。

---

## 明确不做（第 2/3 层，本次不碰）

- 不实现 L0/L1/L2 按需加载 / 下钻机制。
- 不实现 agent 调用接口 / MCP 上下文注入 / token 预算逻辑。
- 不实现跨 agent 协议沟通。
- 不引入 OpenViking 的 `viking://` 文件系统隐喻（隐喻冲突，且超出第 1 层）。

---

## 当前阶段完成判据

- 全库 5 篇 band 均为受控学科域，无技术碎片域残留。
- 领域把关 feedback 闭环非空转，前端可观测收敛度。
- `item_l0()` 就绪，为第 2 层留好 L0 形。
- 不变量测试覆盖入库收口，防回归。

---

## 实施记录（2026-08-23 已全部落地 C→B→A）

### 已完成的改动
- **C1** `lantern_caliper/measure.py`：`normalize_band(value, content, known_domains)` 落库前收口。注意初版误用 63 受控词表硬卡，实测会误杀"信息检索/缓存管理"等合理涌现域——改为「已知域(list_domains 聚合)放行 + 新名过 `_is_broad_field` 够宽守门」双层，兼容"领域涌现"设计。
- **C2** `lantern_caliper/schema.py:domains_of_axes()`：移除对 `items.axis_domain` 的依赖（不再因 axis_domain 命中开放隐藏域），候选只来自受控可见域。
- **C3** `tests/test_band_invariant.py`：7 tests OK（全库无技术碎片、known/够宽、候选只含受控可见域、remeasure 后仍满足）。
- **B1** `measure.py:measure_pair` 反馈逻辑重写：比较"模型原判 band"与"最终落库 band"，不一致才记 `domain_corrected`（真实纠正信号），修掉旧逻辑语义错误（技术碎片被拦没记录、够宽域误记）。
- **B4** `backend/kb.py`：`selfcheck_domain()` + `health()` 加 `domain_corrected_total`。调用：`python backend/kb_cli.py selfcheck_domain '{}'`。
- **B3** 前端：`index.html` 加"领域把关健康度"卡（#mDomainGuard/#mDomainFam），`render.js:renderDomainGuard()` 读 `state.metrics.domain_corrected_total`。宣纸墨韵主题，无 emoji。
- **A1** `DOMAIN_CLASSIFICATION_CONTRACT.md` §7：定义 summary=L0 抽象层（≤80汉字、纯陈述无 markdown）。
- **A3** `lantern_caliper/items.py:item_l0(item_id)`：返回 {title,summary,axis_domain,band,tags} 不含 content。

### 验证
- `py_compile` 全过（measure/schema/items/kb.py + 前端 render.js/model.js `--check`）。
- C3 测试 7 OK；重启服务后 `/api/state` 返回 `domain_corrected_total=1`；`/api/graph` band 正确（#46=信息检索）。
- 前端改动需**硬刷新**浏览器生效。

### 发现的新待办（已全部解决，记此备查）
> 以下两项在 2026-08-23 晚的收尾轮已解决，原判断①为误判，特此更正。

1. ~~`list_domains()` 漏域~~ **误判已推翻**：`list_domains` 返回 4 域是正确的（真实有效 items=5 条、4 个领域）。真正病灶是 `readings` 表有 20 行孤儿读数（item_id 指向已删除 items，来自早前删 49 篇测试文章漏清子表），污染了 `selfcheck_domain().band_distribution`（误报 11 域）。已备份后 `DELETE FROM readings WHERE item_id NOT IN (SELECT id FROM items)` 清理，selfcheck 现返回 4 域、known_domains=4、healthy=True。
2. ~~`summary` 存 markdown 标题~~ **已修复**：根因是 `_SENT` 把句末标点（含！）吞掉做分隔，文章以 `# 标题`/标题式问句开头时首句即标题。`local_summarize` 已重写（剥 `#` 号、跳过标题行、优先选非连词开头的独立陈述句、清 markdown 残留），并回填全部 5 条 items。

---

## 补做项（第 1 层收口，2026-08-23 晚）

### A2 · 入库摘要收口（L0 契约强制，原计划漏做）
- **问题**：三处落库点（add_item 同步 / update_item / `_refine` 后台）直接用 LLM 或 local 摘要写 `items.summary`，**未过 L0 契约收口**——LLM 抽风返回 markdown 标题/超长/带符号时直接污染落库，且无"非空兜底"约束。
- **改动**：
  - `lantern_caliper/summarize.py` 新增 `sanitize_summary(text, max_len=80)`：去 markdown 残留符号（`*_`>#~-`）、折叠空白、去首尾标点、按句末标点优先截断到 ≤80 汉字（加 `…`）、清洗后为空返回 None。
  - `lantern_caliper/items.py` 顶部加 `from . import summarize as _summod`；三处落库点统一 `s = _summod.sanitize_summary(s)` 收口后再写（含 LLM 路径），保证无论模型怎么抽风，写进 summary 的必是合规一句人话。
- **验收**：sanitize 对 markdown 标题 / 加粗代码引用 / 超长 / 空 / 纯空白 五类不良输入均正确归一（空→None 由调用方兜底）；现有 5 条 summary 过 sanitize 全部合规（≤80字、无 `#`）；服务重启 `/api/state` 200。

### 第 1 层完工判据（对照文档"当前阶段完成判据"）
- ✅ 全库 5 篇 band 均为受控/合理涌现域，无技术碎片域残留（C1）。
- ✅ 领域把关 feedback 闭环非空转（`domain_corrected_total=1`），前端健康页可观测（B1/B3/B4）。
- ✅ `item_l0()` 就绪，为第 2 层留好 L0 形（A3）。
- ✅ 不变量测试覆盖入库收口（C3）。
- ✅ L0 摘要契约强制收口，无 markdown/超长/空落库（A2，补做）。
- ✅ readings 孤儿读数清理，领域分布统计干净（收尾 bug）。

> **第 1 层（储存优化 + 领域把关）已全部完工。** 下一步是否进入第 2 层（检索与调用：L0/L1/L2 分层加载、语义召回、按需下钻，属 agent 调用范畴）待用户确认——按既定三阶段论，不擅自跨层。

