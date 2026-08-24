---
name: memory-function-org
description: This skill should be used when organizing, writing, or refactoring long-term/project memory files (.workbuddy/memory or ~/.workbuddy/MEMORY.md). It enforces a "function-area aggregation" memory structure where each feature's iterative history lives in its own file under functions/, indexed by MEMORY.md, instead of date-chronological stream-of-consciousness logs. On top of that it enforces a NATURE DICHOTOMY: concrete operational experience goes to functions/ (经验沉淀), while generalizable thought iterations distilled from that work go to insights/ (创新优化思想) — two complementary zones, never mixed. Use it whenever the user asks to "summarize experience", "organize memory", "consolidate notes", or when about to write substantive work notes that should be retrievable later.
agent_created: true
---

# Memory Function-Area Organization

## Purpose

Replace date-chronological memory logs (stream-of-consciousness "流水账") with a
**function-area aggregation** structure. Every feature/module gets ONE file that
accumulates its full iterative history; the date timeline degrades to a small
`[YYYY-MM-DD]` tag per iteration. This makes memory far easier for an agent to
retrieve and reuse: a feature's two-sided iteration — why it changed and the
lessons from any reverts — sits together instead of being scattered across daily files.

## When to Use

- User asks to summarize, organize, consolidate, or "沉淀" past experience/memory.
- About to write substantive work notes (built/fixed/refactored something) and
  they should be retrievable later — route them into the correct function file.
- Migrating existing date-based logs into the new structure.
- Starting memory from scratch in a new project (run the init script).

## Structure (canonical)

```
<memory-root>/
├── MEMORY.md              # INDEX + 跨功能铁律/共识 + 环境常量 + 功能详档指针（详档下沉 functions/，本文件只留指针，控体积防注入截断）
├── functions/             # one file per feature/module — 经验沉淀（具体环节精髓）
│   └── <feature-name>.md  # full iterative history, date as small tag
├── insights/             # 创新优化思想 — 可通用升华，蒸馏自 functions/
│   └── <insight-theme>.md
└── YYYY-MM-DD.md          # TRANSIENT scratch: decision-thread only; deleted after distillation (Rule 9)
```

- `<memory-root>` = project memory dir (e.g. `D:/测试/.workbuddy/memory/`) or
  user-level `~/.workbuddy/MEMORY.md` for cross-project facts.
- To bootstrap a new project's memory, run `scripts/init_memory.py <memory-root>`.

## Nature Dichotomy (性质二分)

On top of function-area aggregation, every memory root is split into TWO
complementary zones by the *nature* of the content. This keeps retrieval/calling
from ever mixing "how-to detail" with "general principle":

- **分区一 · 经验沉淀 (`functions/`)** — concrete, operational essence.
  - **What goes here**: 某功能「怎么做」/ 某 bug 根因与修法 / 某配置如何配 / 某接口契约。
  - **Call scenario**: 复现某功能、排障、回想某条配置或命令。
  - **File shape**: `# 功能迭代记录：<名>` + 分区标签 + 当前稳定状态 + 迭代块。

- **分区二 · 创新优化思想 (`insights/`)** — generalizable thought iterations,
  distilled UP from concrete work.
  - **What goes here**: 可复用的设计哲学、优化方向、跨功能的原则
    （如 中立化原则、引擎自主 vs 被动镜像、边界清晰解耦、硬链软链区分）。
  - **Call scenario**: 做新设计决策、选优化方向、权衡取舍时查阅。NOT 用于回想操作步骤。
  - **File shape**: `# 创新优化思想：<主题>` + 分区标签 + 「源于（蒸馏自）」回链到
    对应 `functions/` 文件 + 核心原则 / 思想迭代 / 可迁移场景 / 待观察。

**Why it lowers, not raises, retrieval cost**: MEMORY.md's dual table pre-filters
"should I go to `functions/` or `insights/`" at a glance, and calling routes by
task type (reproduce/troubleshoot → `functions/`, new-design/optimize →
`insights/`). The two zones are complementary, not duplicative — `insights/`
never restates how-to steps; `functions/` never speculates on general principles.

**Each index row carries a one-line summary** (like a Skill's `description`
field): a single sentence stating what the doc is about or the problem it
solves, so you can judge relevance *without opening the file*. This is what
makes the index fast and accurate to call — you scan summaries, not filenames.

## Rules (the constraints that make it work)

1. **Functions over dates as the spine.** Never write a feature's iteration
   history as a date-keyed section. Ask: "which `functions/<name>.md` does this
   belong to?" then append an iteration block there.

2. **Daily log = decision thread only.** `YYYY-MM-DD.md` holds at most:
   - A one-line principle note (first time only).
   - A "当日决策脉络" list: each item is `<short phrase> → [functions/x.md](...)`.
   - A "跨日待观察" section: open risks/observations (detail lives in function files).
   No detailed how/why in the daily log — that goes in the function file.

   The daily log is TRANSIENT scratch for capturing-as-you-work, NOT a permanent
   archive. Once its content is distilled into `functions/` (+ `insights/` if a
   principle emerged), DELETE the daily-log file (Rule 9). Never keep both the
   stream and the distilled version — that duplication is exactly what this skill
   exists to prevent.

3. **Function file shape.** Each `functions/<name>.md`:
   - Starts with a one-line scope line naming related code paths.
   - Has a `## 当前稳定状态（截至 YYYY-MM-DD）` summary block (current stable
     behavior, so a reader gets the present state without reading history).
   - Then iteration blocks, each headed `## [YYYY-MM-DD 时段] 动因`, containing
     **动因 / 根因 / 改动 / 判据 / 待观察** as applicable. Timeline is a tag, not
     the skeleton.
   - Ends with `## 待观察 / 未决` for open items.

4. **Single source of truth per feature.** If the same fact appears in two
   places, the function file owns it; the daily log and MEMORY.md only link.
   After migrating, compress the old daily-log detail into a link reference to
   avoid dual maintenance.

5. **MEMORY.md is an index, not a notebook — and every index row carries a
   one-line summary.** It contains:
   - The organization principle (first time).
   - A function-module table with a summary column:
     `| 功能模块 | 一句话摘要 / 关键问题 | 迭代记录 | 状态 |`.
   - An insights table with a summary column:
     `| 思想主题 | 一句话摘要 / 解决什么取舍 | 思想文件 | 源于（蒸馏自） |`.
   - Cross-cutting consensus (design principles shared across features).
   - Env constants that are easy to forget (ports, DB paths, startup commands).
   The one-line summary is the KEY discipline: treat it like a Skill's
   `description` field — it must let you decide *whether to open the file*
   without reading it. For `functions/` rows, state what the feature does or
   the bug/config pitfall it records; for `insights/` rows, state the principle
   and the trade-off it resolves. Keep it to one sentence. It must NOT contain
   feature iteration detail (that lives in the linked file).

   **Three-layer duty + detail-sink discipline.** MEMORY.md's job is exactly
   three things: (1) the dual-table index with one-line summaries; (2)
   cross-cutting 铁律/共识 — decision-level rules shared across features, which
   is the *legitimate* "通病记录" zone; (3) env constants. It must NOT host a
   feature's *detailed argumentation* (derivations, API lists, domain-taxonomy
   deep-dives) — those belong in the corresponding `functions/<name>.md`, and
   MEMORY.md reaches them via a single 「功能详档索引」 pointer section. **Keep
   it light**: an overgrown MEMORY.md gets truncated by the host's context
   injection (observed in practice — the second half was silently dropped,
   hurting retrieval). Sink detail, trim long passages; if it grows past ~80
   lines / ~10KB, refactor.

6. **Discipline for future writes.** When adding new work notes, append an
   iteration block to the relevant `functions/<name>.md` and add one line to the
   daily decision thread. Do NOT fall back to date-chained narrative.

7. **Nature dichotomy by content, not just by feature.** A feature's operational
   iteration always lives in `functions/<name>.md`. When a piece of work yields a
   *generalizable* principle (not tied to one feature's mechanics), distill it
   into a separate `insights/<theme>.md` and link back to its source function
   file(s) via 「源于（蒸馏自）」. Keep the two zones complementary:
   `functions/` = how-to detail, `insights/` = generalizable thought. Do NOT
   duplicate how-to steps into `insights/`, and do NOT bury general principles
   inside a function file's iteration block. When in doubt, ask: "is this an
   operation I'd re-run, or a principle I'd re-apply?" — the former → functions/,
   the latter → insights/.

8. **Dependency direction: functions own the detail, never reverse-link to
   MEMORY.md's detail.** A `functions/<name>.md` MUST be self-contained: its
   "当前稳定状态" and any 「设计论证 / 详档」 section live *in the file*, never
   as "详见 MEMORY.md「xxx 详档」". MEMORY.md points DOWN to functions (index →
   detail); functions may point UP to MEMORY.md's *cross-cutting 铁律/共识*
   (that is a healthy index link), but never to a detail block that should have
   stayed in functions. If you find a function file saying "详见 MEMORY.md" for
   detail, the detail was mis-placed — move it back into the function file and
   leave MEMORY.md a pointer.

9. **Delete distilled originals — no backup/archive step.** After a stream log's
   content is fully captured in `functions/` (+ `insights/` where a principle
   emerged) — including its date-tagged iteration blocks — DELETE the original
   stream file. The distilled files are the durable record; keeping the raw
   stream alongside them is the exact duplication this skill exists to prevent.
   Do NOT add a backup or move-to-archive step: a copy of data you've judged
   redundant just relocates the waste, it does not eliminate it. The only guard
   is **verifying distillation is complete** — every decision/fact in the stream
   must already live in `functions/` or `insights/`. If you are unsure it is all
   captured, finish distilling first; never "back up then delete anyway."

## Naming conventions

- Feature file name = short Chinese/English slug of the module, e.g.
  `领域把关.md`, `阅读页预览.md`, `反馈邮箱.md`, `多维同步检索.md`.
- Match the name used in MEMORY.md's index table exactly (so links resolve).
- Iteration heading date tag uses `早` / `午` / `晚` suffix when multiple
  iterations land on the same day.

## Migration workflow (existing date-based logs)

1. Read the target daily logs; identify feature boundaries (group by module,
   not by date).
2. For each feature, create `functions/<name>.md` with stable-state + iteration
   blocks (timeline as tags), preserving 动因/根因/改动/判据.
3. Rewrite each touched daily log to the slim decision-thread format with links.
4. Build/update the MEMORY.md index table; move any cross-cutting rules into the
   consensus section.
5. **Refactor/收口 if MEMORY.md grew a "功能详档" belly or functions reverse-link
   to it.** Symptoms: MEMORY.md holds derivation/API deep-dives, or a function
   file says "详见 MEMORY.md「xxx 详档」". Fix: move the detail into the
   function file's 「设计论证」 section, replace MEMORY.md's copy with a
   「功能详档索引」 pointer line. This keeps the
   index light and the dependency one-directional (MEMORY → functions).
6. **After distilling a stream log, DELETE it — no archive, no backup.** Once a
   daily/stream log's decisions and facts all have a home in `functions/`
   (± `insights/`), delete the original file. The distilled files ARE the durable
   record; retaining the raw stream too is duplication. Do NOT move it to an
   `archive/` folder either — that only relocates the redundancy. (Guard: verify
   distillation is complete before deleting; see Rule 9.)

## Skeleton templates

Function file (分区一 · 经验沉淀):
```
# 功能迭代记录：<功能名>

> **分区**：经验沉淀（具体环节精髓） | **调用场景**：回顾某功能「怎么做 / 某 bug 根因与修法 / 某配置如何配」时查阅。
> 聚合 <功能名> 功能区迭代。相关代码：<path1>、<path2>。

## 当前稳定状态（截至 YYYY-MM-DD）
- <present behavior bullet; 可一句话指向本文件「设计论证」段>

## 设计论证 / 详档（自含于本文件，严禁"详见 MEMORY.md"回指）
- <该功能的完整推导 / API 列表 / 领域谱系 / 配置契约等；MEMORY.md 仅以「功能详档索引」指针指向本文件>

## [YYYY-MM-DD 时段] 动因
**动因**：<why>
**根因**：<if bug>
**改动**：<what changed>
**判据**：<verification>
**待观察**：<open>

## 待观察 / 未决
- <item>

## 相关思想升华（可通用原则）
- <主题> → [insights/<主题>.md](../insights/<主题>.md)
```

Daily log:
```
# YYYY-MM-DD 工作日志

> 记忆组织原则：短期日志只记决策脉络，细节下沉 functions/，由 MEMORY.md 索引。

## 当日决策脉络
- <短短语> → [functions/x.md](functions/x.md)

## 跨日待观察
- <risk>
```

Insight file (分区二 · 创新优化思想):
```
# 创新优化思想：<主题>

> **分区**：创新优化思想（可通用·思想迭代升华） | **调用场景**：做新设计决策 / 选优化方向 / 权衡取舍时查阅。 | **源于（蒸馏自）**：[functions/xxx.md](../functions/xxx.md)

## 核心原则
- <principle, stated concretely>

## 思想迭代
- <how this thought evolved / what it replaced>

## 可迁移场景
- <where else it applies beyond the source feature>

## 待观察
- <open / what to validate next>
```
