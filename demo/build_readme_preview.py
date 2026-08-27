#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 README.md 生成一个自包含 HTML 预览（docs/README-preview.html）。

- 用 markdown 库把 README 转成 HTML（支持表格 / 代码块）。
- 把 README 里所有 ./docs/... 图片内联为 base64 data URI，
  这样双击用任意浏览器离线打开都能看到截图，不依赖网络、不依赖插件。
- 源 README.md 保持标准相对路径（GitHub 网页 + VS Code/Typora 等编辑器正常显示）。

用法：
    python demo/build_readme_preview.py
"""
import base64
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OUT = ROOT / "docs" / "README-preview.html"

MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def inline_image(src: str) -> str:
    """把 ./docs/... 相对路径换成 base64 data URI；其它原样返回。"""
    if not src.startswith("./docs/") and not src.startswith("docs/"):
        return src
    rel = src.lstrip("./")
    p = ROOT / rel
    if not p.exists():
        return src
    mime = MIME.get(p.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def main():
    text = README.read_text(encoding="utf-8")
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc"])
    body = md.convert(text)

    # 内联 <img src="./docs/...">
    body = re.sub(
        r'src="(\./docs/[^"]+)"',
        lambda m: f'src="{inline_image(m.group(1))}"',
        body,
    )
    # 兜底：markdown 原生 ![alt](./docs/...) 残留
    body = re.sub(
        r'\]\((\./docs/[^)]+)\)',
        lambda m: f']({inline_image(m.group(1))})',
        body,
    )

    # 统计内联数量
    n = body.count("data:image")

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>灯笼 · 多维轴知识库 — 离线预览</title>
<style>
  :root {{
    --paper:#f7f3ea; --line:#d8cdb8; --ink:#2b2620; --cinnabar:#b23a2e; --stone:#6b6256;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin:0; background:var(--paper); color:var(--ink);
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    line-height:1.7;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 40px 28px 80px; }}
  h1,h2,h3 {{ color:var(--ink); line-height:1.3; }}
  h1 {{ border-bottom: 2px solid var(--line); padding-bottom:.3em; }}
  h2 {{ border-bottom: 1px solid var(--line); padding-bottom:.2em; margin-top:2em; }}
  a {{ color:var(--cinnabar); }}
  code {{ background:#efe7d6; padding:.15em .4em; border-radius:4px; font-size:.9em; }}
  pre {{ background:#2b2620; color:#f3ead7; padding:16px; border-radius:8px; overflow:auto; }}
  pre code {{ background:none; padding:0; color:inherit; }}
  table {{ border-collapse: collapse; width:100%; margin:1em 0; font-size:.95em; }}
  th,td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }}
  th {{ background:#ece2cd; }}
  img {{ max-width:100%; height:auto; border:1px solid var(--line); border-radius:8px; }}
  blockquote {{ border-left:4px solid var(--cinnabar); margin:1em 0; padding:.2em 1em; color:var(--stone); background:#f0e8d8; }}
  .note {{ font-size:.85em; color:var(--stone); background:#f0e8d8; border:1px dashed var(--line); padding:10px 14px; border-radius:8px; margin-bottom:24px; }}
</style>
</head>
<body>
<div class="wrap">
  <p class="note">这是 README.md 的<strong>离线自包含预览</strong>：所有截图已内联为 base64，双击即可在任意浏览器查看，无需联网、无需 Markdown 插件。源文件见 <code>README.md</code>（标准相对路径，GitHub 网页与 VS Code/Typora 等编辑器可直接渲染）。</p>
{body}
</div>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"OK -> {OUT}  (内联图片 {n} 张, {len(html)//1024} KB)")


if __name__ == "__main__":
    main()
