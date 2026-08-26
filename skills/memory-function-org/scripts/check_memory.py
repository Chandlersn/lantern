#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_memory.py — linter for memory-function-org memory roots.

Usage:
    python check_memory.py <memory-root> [--json]

Checks (per memory-function-org SKILL.md):
  R5   MEMORY.md index <= ~10KB (warn >10KB, fail >15KB)
  R5   every index row carries a one-line summary (non-empty summary column)
  R10  every markdown link target resolves (relative to the file it lives in);
       a target that exists but escapes the memory root is WARN (R10e)
  R8   no function file reverse-links to a DETAIL block in MEMORY.md
       (upward links to 铁律/共识/环境常量 are allowed)
  R9   functions/<name>.md <= ~30KB (warn; suggest compress)
  R3   iteration-block date tags non-decreasing top->bottom (append-only)
  R13  files inside a `legacy/` subdir must carry the "原型期遗留" header

Notes:
  - Links starting with `/`, `http`, or containing `attachments` are skipped
    (they point outside the memory root, e.g. KB attachments).
  - Every relative link in MEMORY.md, functions/, insights/, AND top-level
    daily logs is checked: it must resolve AND stay inside the memory root
    (a `../` that escapes the root is flagged as dangling).
  - prototype-era detection for top-level daily logs is a MANUAL judgment;
    only files already placed in `legacy/` are auto-checked.

Exit code: 0 = only PASS/WARN, 1 = any FAIL.
"""
import os
import re
import sys

KB = 1024
WARN_MEM = 10 * KB
FAIL_MEM = 15 * KB
WARN_FUNC = 30 * KB
PROTO_HEADER = "原型期遗留"
REVERSE_DETAIL = re.compile(
    r"详见 MEMORY\.md[「（][^」）]*(详档|推导|API|谱系|分类|归档|契约|配置契约)")
UPWARD_OK = ("铁律", "共识", "环境常量", "边界", "哲学", "职责", "定位", "推送",
             "反馈轴", "独立性", "启动", "端口", "数据库", "真相源", "设计",
             "git", "GitHub", "系统", "跨功能")
DATE_TAG = re.compile(r"^##\s*\[(\d{4})-(\d{2})-(\d{2})")


def strip_code(text):
    """Remove fenced code blocks and inline `code` spans so the link scanner
    does not mistake syntax examples (e.g. `@[provider](url)`) for real links."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    return text


def link_targets(text, fp, root):
    """Return list of (rel, exists, under_root) for in-tree relative links.

    - exists=False   -> the link is DANGLING (FAIL, R10).
    - under_root=False -> the link resolves to a real file OUTSIDE the memory
      root (WARN, R10e): it works now but breaks if the memory dir is moved.
    Code spans are stripped first so syntax examples are never flagged.
    """
    text = strip_code(text)
    base = os.path.dirname(fp)
    root_abs = os.path.abspath(root)
    out = []
    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        rel = m.group(1).split("#")[0].strip()
        if not rel or rel.startswith(("/", "http")) or "attachments" in rel:
            continue
        resolved = os.path.normpath(os.path.join(base, rel))
        out.append((rel, os.path.exists(resolved),
                    os.path.abspath(resolved).startswith(root_abs + os.sep)))
    return out


def check(root):
    root = os.path.abspath(root)
    results = []

    def add(level, rule, msg):
        results.append((level, rule, msg))

    mem = os.path.join(root, "MEMORY.md")
    if not os.path.isfile(mem):
        add("FAIL", "R?", f"MEMORY.md not found at {mem}")
        return results

    size = os.path.getsize(mem)
    if size > FAIL_MEM:
        add("FAIL", "R5", f"MEMORY.md {size/KB:.1f}KB > 15KB hard cap")
    elif size > WARN_MEM:
        add("WARN", "R5", f"MEMORY.md {size/KB:.1f}KB > 10KB comfort ceiling")

    text = open(mem, encoding="utf-8").read()
    empty_summary = 0
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) >= 4:
            summary = cells[1]
            if summary.startswith("一句话摘要"):
                continue  # table header row, not a data row
            if not summary:
                empty_summary += 1
    if empty_summary:
        add("WARN", "R5", f"{empty_summary} index row(s) missing one-line summary")
    for rel, exists, under_root in link_targets(text, mem, root):
        if not exists:
            add("FAIL", "R10", f"dangling index link -> {rel}")
        elif not under_root:
            add("WARN", "R10", f"index link escapes memory root -> {rel}")

    for zone in ("functions", "insights"):
        zdir = os.path.join(root, zone)
        if not os.path.isdir(zdir):
            continue
        for fn in sorted(os.listdir(zdir)):
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(zdir, fn)
            fsize = os.path.getsize(fp)
            ftext = open(fp, encoding="utf-8").read()
            if zone == "functions":
                if fsize > WARN_FUNC:
                    add("WARN", "R9", f"{zone}/{fn} {fsize/KB:.1f}KB > 30KB — compress oldest blocks")
                if REVERSE_DETAIL.search(ftext):
                    add("FAIL", "R8", f"{zone}/{fn} reverse-links to a DETAIL block in MEMORY.md")
                elif re.search(r"详见 MEMORY\.md[「（]", ftext):
                    after = ftext.split("详见 MEMORY.md", 1)[1][:20]
                    if not any(k in after for k in UPWARD_OK):
                        add("WARN", "R8", f"{zone}/{fn} '详见 MEMORY.md' target unclear (manual check)")
                dates = [tuple(map(int, m.groups())) for m in DATE_TAG.finditer(ftext)]
                if dates and dates != sorted(dates):
                    add("WARN", "R3", f"{zone}/{fn} iteration date tags not non-decreasing (not append-only)")
            for rel, exists, under_root in link_targets(ftext, fp, root):
                if not exists:
                    add("FAIL", "R10", f"dangling link in {zone}/{fn} -> {rel}")
                elif not under_root:
                    add("WARN", "R10", f"link in {zone}/{fn} escapes memory root -> {rel}")

    # top-level daily logs (YYYY-MM-DD.md) are also link-checked (R10) — the
    # previous scope only covered MEMORY.md + functions/ + insights/, leaving
    # root-level daily logs' links unverified.
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".md") or fn == "MEMORY.md":
            continue
        fp = os.path.join(root, fn)
        if not os.path.isfile(fp):
            continue
        dtext = open(fp, encoding="utf-8").read()
        for rel, exists, under_root in link_targets(dtext, fp, root):
            if not exists:
                add("FAIL", "R10", f"dangling link in {fn} -> {rel}")
            elif not under_root:
                add("WARN", "R10", f"link in {fn} escapes memory root -> {rel}")

    legacy = os.path.join(root, "legacy")
    if os.path.isdir(legacy):
        for fn in sorted(os.listdir(legacy)):
            if fn.endswith(".md"):
                if PROTO_HEADER not in open(os.path.join(legacy, fn), encoding="utf-8").read():
                    add("WARN", "R13", f"legacy/{fn} lacks '⚠️ 原型期遗留' header")

    return results


def main():
    if len(sys.argv) < 2:
        print("usage: check_memory.py <memory-root> [--json]")
        sys.exit(2)
    root = sys.argv[1]
    as_json = "--json" in sys.argv
    results = check(root)
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    if as_json:
        import json
        print(json.dumps([{"level": l, "rule": r, "msg": m} for l, r, m in results],
                          ensure_ascii=False, indent=2))
    else:
        print(f"check_memory.py — {root}")
        print(f"  {len(warns)} WARN, {len(fails)} FAIL\n")
        for l, r, m in results:
            print(f"  [{l}] {r}: {m}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
