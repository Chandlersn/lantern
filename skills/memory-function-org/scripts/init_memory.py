#!/usr/bin/env python3
"""Bootstrap the function-area memory structure in a project's memory root.

Usage:
    python init_memory.py <memory-root> [--date YYYY-MM-DD]

Creates (idempotently):
    <memory-root>/MEMORY.md          index + principle + env-constant stub
    <memory-root>/functions/         feature-iteration directory
    <memory-root>/YYYY-MM-DD.md      slim daily-log template with principle note

Existing files are never overwritten; the script only writes what is missing
and reports what it created.
"""
import os
import sys
from datetime import date

PRINCIPLE = (
    "记忆组织原则：① 短期日志只记「当日决策脉络」，功能区的完整迭代历史下沉到 "
    "functions/<功能名>.md，由 MEMORY.md 做索引；② 性质二分——经验沉淀(具体环节精髓)归 "
    "functions/，创新优化思想(可通用升华)归 insights/，两区互补不重复。不要再在同一功能上用"
    "日期串联记流水账——同一功能区的迭代就该聚合在一起，时间线退为每段的小标注。"
)

MEMORY_MD = """# 长期记忆（功能索引）

> 组织原则：① 按功能区聚合迭代，不按日期记流水账；② 性质二分——经验沉淀(具体环节精髓)
> 归 functions/，创新优化思想(可通用升华)归 insights/，两区互补不重复。MEMORY.md 做双表索引。

## 分区一 · 经验沉淀（具体环节精髓 → functions/）

| 功能模块 | 迭代记录 | 状态 |
|---|---|---|
| （示例）某功能 | [functions/某功能.md](functions/某功能.md) | 待补充 |

## 分区二 · 创新优化思想（可通用·思想迭代升华 → insights/）

| 思想主题 | 思想文件 | 源于（蒸馏自） |
|---|---|---|
| （示例）某思想 | [insights/某思想.md](insights/某思想.md) | [functions/某功能.md](functions/某功能.md) |

## 跨功能共识 / 设计原则

- （在此填写跨功能共享的设计原则，如主题变量、布局原则、领域约束等）

## 环境常量（易忘，集中记）

- （端口 / 真实库路径 / 启动命令 / 项目路径 / 前端刷新方式等）
"""

DAILY_MD = """# {date} 工作日志

> {principle}

## 当日决策脉络
- （短短语）→ [functions/x.md](functions/x.md)

## 跨日待观察
- （开放风险 / 待观察项，细节在各功能文件）
"""


def ensure_dir(path: str) -> bool:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        return True
    return False


def write_if_missing(path: str, content: str, label: str) -> None:
    if os.path.exists(path):
        print(f"  跳过已存在 {label}: {path}")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  已创建 {label}: {path}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python init_memory.py <memory-root> [--date YYYY-MM-DD]")
        return 2
    root = sys.argv[1]
    date_str = date.today().isoformat()
    if "--date" in sys.argv:
        idx = sys.argv.index("--date") + 1
        if idx < len(sys.argv):
            date_str = sys.argv[idx]

    print(f"初始化记忆结构于: {root}")
    ensure_dir(root)
    ensure_dir(os.path.join(root, "functions"))
    ensure_dir(os.path.join(root, "insights"))

    write_if_missing(
        os.path.join(root, "MEMORY.md"),
        MEMORY_MD,
        "索引 MEMORY.md",
    )
    write_if_missing(
        os.path.join(root, f"{date_str}.md"),
        DAILY_MD.format(date=date_str, principle=PRINCIPLE),
        f"当日日志 {date_str}.md",
    )
    print("完成。后续：把功能迭代写入 functions/<功能名>.md，当日日志只留决策脉络。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
