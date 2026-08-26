#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号 / 网页图文 -> lantern-caliper 知识库 录入流水线。

纯标准库。须联网运行（沙箱外 / dangerouslyDisableSandbox=true）：
    python skills/weixin-ingest/scripts/ingest.py "<URL>" --axis-domain 心理

流程：抓取 HTML -> 抽正文(#js_content)+data-src 配图 -> 下载本地化到 attachments/
      -> 改写为 markdown(本地图引用) -> 带 source_url + axis_domain POST /api/kb/add。
"""
import argparse
import datetime as _dt
import gzip
import hashlib
import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]          # .../lantern-caliper
ATTACH_DIR = REPO_ROOT / "attachments"
SCHEMA = REPO_ROOT / "schema.json"
KB_ADD = "http://127.0.0.1:8731/api/kb/add"
KB_UPDATE = "http://127.0.0.1:8731/api/kb/update"
KB_DELETE = "http://127.0.0.1:8731/api/kb/delete"
KB_QUERY = "http://127.0.0.1:8731/api/kb/query"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
WX_REFERER = "https://mp.weixin.qq.com/"
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote"}


def controlled_domains():
    d = json.loads(SCHEMA.read_text(encoding="utf-8"))
    reg = d.get("scales", {}).get("main", {}).get("domain_registry", {})
    return set(reg.keys())


def _read(url, referer):
    """返回原始字节（图片用）；HTML 调用方自行 decode。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def fetch_html(url):
    referer = WX_REFERER if "mp.weixin.qq.com" in url else url
    return _read(url, referer).decode("utf-8", "replace")


def download_image(url, idx, referer):
    data = _read(url, referer)
    if data[:4] == b"\x89PNG":
        ext = "png"
    elif data[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif data[:4] == b"GIF8":
        ext = "gif"
    elif data[:4] == b"RIFF":
        ext = "webp"
    else:
        ext = "jpg"
    h = hashlib.md5(data).hexdigest()[:8]
    name = f"{idx}_{h}.{ext}"
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    (ATTACH_DIR / name).write_bytes(data)
    return name, len(data)


def extract_title(html_text):
    m = re.search(r'var\s+msg_title\s*=\s*"([^"]+)"', html_text)
    if m:
        return html.unescape(m.group(1)).strip()
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_text, re.I)
    if m:
        return html.unescape(m.group(1)).strip()
    m = re.search(r"<title>([^<]*)</title>", html_text, re.I)
    if m:
        return html.unescape(m.group(1)).strip()
    return ""


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_js = False
        self.js_depth = 0
        self.blocks = []          # (kind, payload)
        self._inline = []
        self._cur_kind = "p"
        self._skip = 0

    def _flush(self):
        text = "".join(self._inline).strip()
        self._inline = []
        if text:
            self.blocks.append((self._cur_kind, text))
        self._cur_kind = "p"

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        if not self.in_js:
            if tag == "div" and d.get("id") == "js_content":
                self.in_js = True
                self.js_depth = 1
            return
        self.js_depth += 1
        if tag == "img":
            src = d.get("data-src") or d.get("src") or ""
            if src:
                self._flush()
                self.blocks.append(("img", src))
        elif tag in BLOCK_TAGS:
            self._flush()
            self._cur_kind = tag
        elif tag == "br":
            self._inline.append("\n")
        elif tag in ("strong", "b"):
            self._inline.append("**")
        elif tag in ("em", "i"):
            self._inline.append("*")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if not self.in_js:
            return
        if tag == "div":
            self.js_depth -= 1
            if self.js_depth <= 0:
                self._flush()
                self.in_js = False
            return
        self.js_depth -= 1
        if tag in BLOCK_TAGS:
            self._flush()
        elif tag in ("strong", "b"):
            self._inline.append("**")
        elif tag in ("em", "i"):
            self._inline.append("*")

    def handle_data(self, data):
        if self._skip or not self.in_js:
            return
        self._inline.append(data)


def parse_article(html_text):
    p = ArticleParser()
    p.feed(html_text)
    if not p.blocks:
        # 兜底：无 js_content 时，从全文档抽图 + 去标签文本
        imgs = re.findall(r'data-src="([^"]+)"', html_text) or \
               re.findall(r'<img[^>]+src="([^"]+)"', html_text)
        text = re.sub(r"<script.*?</script>", "", html_text, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = html.unescape(text)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        p.blocks = [("p", l) for l in lines[:200]]
        for src in imgs:
            p.blocks.append(("img", src))
    return p.blocks


def build_markdown(blocks, title, source_url, source_label):
    today = _dt.date.today().isoformat()
    out = []
    out.append(f"> 来源：{source_label}")
    out.append(f"> 标题：《{title}》")
    out.append(f"> 原文链接：{source_url}")
    out.append(f"> 收录时间：{today}")
    out.append("")
    idx = 0
    referer = WX_REFERER if "mp.weixin.qq.com" in source_url else source_url
    for kind, payload in blocks:
        if kind == "img":
            idx += 1
            name, _ = download_image(payload, idx, referer)
            out.append(f"![](/attachments/{name})")
            out.append("")
        elif kind == "h1":
            out.append(f"# {payload}")
            out.append("")
        elif kind == "h2":
            out.append(f"## {payload}")
            out.append("")
        elif kind == "h3":
            out.append(f"### {payload}")
            out.append("")
        elif kind == "h4":
            out.append(f"#### {payload}")
            out.append("")
        elif kind == "blockquote":
            out.append(f"> {payload}")
            out.append("")
        elif kind == "li":
            out.append(f"- {payload}")
            out.append("")
        else:
            out.append(payload)
            out.append("")
    return "\n".join(out).strip() + "\n"


def http_post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def check_duplicate(source_url, title):
    try:
        resp = http_post(KB_QUERY, {"text": title[:20], "top_k": 5})
    except Exception:
        return None
    items = resp.get("items") or resp.get("results") or []
    for it in items:
        if it.get("source_url") == source_url:
            return it.get("id")
    return None


def main():
    ap = argparse.ArgumentParser(description="公众号/网页图文 -> 灯笼 KB 录入")
    ap.add_argument("url", help="文章 URL")
    ap.add_argument("--axis-domain", required=True, help="受控学科域（见 schema domain_registry）")
    ap.add_argument("--source-url", default=None, help="原文链接，默认=url")
    ap.add_argument("--title", default=None, help="覆盖标题")
    ap.add_argument("--update-id", type=int, default=None, help="更新既有条目而非新建")
    ap.add_argument("--dry-run", action="store_true", help="只抓取解析下载+打印 payload，不写入 KB")
    ap.add_argument("--force", action="store_true", help="跳过重复检查")
    args = ap.parse_args()

    source_url = args.source_url or args.url
    source_label = "微信公众号文章" if "mp.weixin.qq.com" in args.url else "网页文章"

    ctrl = controlled_domains()
    axis = args.axis_domain if args.axis_domain in ctrl else None
    if args.axis_domain not in ctrl:
        print(f"[WARN] axis_domain「{args.axis_domain}」不在受控词表，归一化为 None（入库但无学科域）。",
              file=sys.stderr)
        print(f"[WARN] 受控域示例：{', '.join(sorted(ctrl)[:12])} …", file=sys.stderr)

    print(f"[*] 抓取 {args.url} …")
    html_text = fetch_html(args.url)
    title = args.title or extract_title(html_text)
    if not title:
        title = next((p for k, p in parse_article(html_text) if k != "img"), "未命名")
    blocks = parse_article(html_text)
    n_imgs = sum(1 for k, _ in blocks if k == "img")
    print(f"[*] 解析到 {len(blocks)} 个块，其中图片 {n_imgs} 张")

    content = build_markdown(blocks, title, source_url, source_label)
    local = content.count("/attachments/")
    ext = content.count("mmbiz.qpic.cn") + content.count("qpic.cn")
    print(f"[*] 本地图引用 {local} 处，外链残留 {ext} 处")

    payload = {
        "title": title,
        "content": content,
        "axis_domain": axis,
        "source_url": source_url,
    }

    if args.dry_run:
        print("[DRY-RUN] 不写入 KB。payload 预览（前 1500 字）：")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:1500])
        return

    if not args.force and args.update_id is None:
        dup = check_duplicate(source_url, title)
        if dup is not None:
            print(f"[ABORT] 已存在同 source_url 条目 id={dup}，请改用 --update-id {dup} 更新。",
                  file=sys.stderr)
            sys.exit(2)

    if args.update_id is not None:
        resp = http_post(KB_UPDATE, {"item_id": args.update_id, **payload})
    else:
        resp = http_post(KB_ADD, payload)
    print("[OK] 写入结果：", json.dumps(resp, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
