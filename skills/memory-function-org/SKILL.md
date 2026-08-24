---
name: memory-function-org
description: This skill should be used when organizing, writing, or refactoring long-term/project memory files (.workbuddy/memory or ~/.workbuddy/MEMORY.md). It enforces a "function-area aggregation" memory structure where each feature's iterative history lives in its own file under functions/, indexed by MEMORY.md, instead of date-chronological stream-of-consciousness logs. Use it whenever the user asks to "summarize experience", "organize memory", "consolidate notes", or when about to write substantive work notes that should be retrievable later.
agent_created: true
---

# Memory Function-Area Organization

## Purpose

Replace date-chronological memory logs (stream-of-consciousness "流水账") with a
**function-area aggregation** structure. Every feature/module gets ONE file that
accumulates its full iterative history; the date timeline degrades to a small
`[YYYY-MM-DD]` tag per iteration. This makes memory far easier for an agent to
retrieve and reuse: a feature's正反迭代 (why-changed / reverted lessons) sits
together instead of being scattered across daily files.

## When to Use

- User asks to summarize, organize, consolidate, or "沉淀" past experience/memory.
- About to write substantive work notes (built/fixed/refactored something) and
  they should be retrievable later — route them into the correct function file.
- Migrating existing date-based logs into the new structure.
- Starting memory from scratch in a new project (run the init script).

## Structure (canonical)

```
<memory-root>/
├── MEMORY.md              # INDEX only: function table + cross-cutting consensus + env constants
├── functions/             # one file per feature/module
│   └── <feature-name>.md  # full iterative history, date as small tag
└── YYYY-MM-DD.md          # daily log: DECISION THREAD only (links to functions/)
```

- `<memory-root>` = project memory dir (e.g. `D:/测试/.workbuddy/memory/`) or
  user-level `~/.workbuddy/MEMORY.md` for cross-project facts.
- To bootstrap a new project's memory, run `scripts/init_memory.py <memory-root>`.

## Rules (the constraints that make it work)

1. **Functions over dates as the spine.** Never write a feature's iteration
   history as a date-keyed section. Ask: "which `functions/<name>.md` does this
   belong to?" then append an iteration block there.

2. **Daily log = decision thread only.** `YYYY-MM-DD.md` holds at most:
   - A one-line principle note (first time only).
   - A "当日决策脉络" list: each item is `<short phrase> → [functions/x.md](...)`.
   - A "跨日待观察" section: open risks/observations (detail lives in function files).
   No detailed how/why in the daily log — that goes in the function file.

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

5. **MEMORY.md is an index, not a notebook.** It contains:
   - The organization principle (first time).
   - A function-module table: `| 功能模块 | 迭代记录 | 状态 |`.
   - Cross-cutting consensus (design principles shared across features).
   - Env constants that are easy to forget (ports, DB paths, startup commands).
   It must NOT contain feature iteration detail.

6. **Discipline for future writes.** When adding new work notes, append an
   iteration block to the relevant `functions/<name>.md` and add one line to the
   daily decision thread. Do NOT fall back to date-chained narrative.

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
5. Leave OLD prototype-era logs untouched unless the user asks — they may be
   obsolete and merging them can confuse the current architecture. Offer to
   extract only still-valid parts on request.

## Skeleton templates

Function file:
```
# 功能迭代记录：<功能名>

> 聚合 <功能名> 功能区迭代。相关代码：<path1>、<path2>。

## 当前稳定状态（截至 YYYY-MM-DD）
- <present behavior bullet>

## [YYYY-MM-DD 时段] 动因
**动因**：<why>
**根因**：<if bug>
**改动**：<what changed>
**判据**：<verification>
**待观察**：<open>

## 待观察 / 未决
- <item>
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
