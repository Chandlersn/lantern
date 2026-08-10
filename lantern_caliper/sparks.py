# -*- coding: utf-8 -*-
"""灵感碎片（原料层）：随手记捕获、离线聚类萌发、孵化成知识条目。

设计原则（与灯笼整体哲学一致）：
  · 碎片刻意【无坐标】——捕获时不做双尺度投影；投影发生在「孵化」环节，
    由 add_knowledge 完成。这保证「先有原料，后有坐标」，碎片的本质是出发点。
  · 聚类萌发（spark_clusters）是「摊开结构、不下结论」的软洞察：仅呈现
    「这些碎片似乎在讲同一件事」，绝不替用户判定；是否孵化由人决定。
  · 孵化（hatch_spark）把碎片交给 kb.add_knowledge 走正常双尺投影 + 阴阳闭环，
    并回填 hatched_item_id + status=hatched，打通「原料 → 成品」溯源。
  · embedding 仅 LLM 可用时存，否则 NULL；聚类用离线关键词共现，不依赖向量。
"""

import json
import time
from collections import Counter

from .core import *


# ----------------------------------------------------------------- 行格式化
def _row_spark(r):
    d = dict(r)
    try:
        d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    except (json.JSONDecodeError, TypeError):
        d["tags"] = []
    d.pop("embedding", None)          # 不向前端泄露向量
    return d


def _norm_tags(tags):
    """把 list / 逗号串归一化为 JSON 字符串；空 → None。"""
    if tags is None:
        return None
    if isinstance(tags, (list, tuple)):
        arr = [str(t).strip() for t in tags if str(t).strip()]
    else:
        arr = [t.strip() for t in str(tags).split(",") if t.strip()]
    return json.dumps(arr, ensure_ascii=False) if arr else None


# 功能/语法字符集：用于判断一个中文 2 字 bigram 是否为「纯虚词组合」而被剔除。
# 规则：bigram 的【两个字都属于功能字】才视为虚词组合——这样能精准去掉
# 「的是 / 可以 / 但是 / 因为 / 所以 / 我们 / 这个 / 什么」等连接性碎片，
# 同时【保留】「领域 / 坐标 / 主尺 / 科学 / 人文 / 机制 / 价值」等实义内容词
# （这些词至少有一个字是实义字，不会被误杀）。这是概念层 _GENERIC_BAN 激进表
# 做不到的——那张表会把 领域/机制/价值 也 ban 掉，对碎片聚类是灾难性误杀。
_FUNCTION_CHARS = set(
    "的 了 在 和 与 或 但 因 为 就 也 都 很 更 可 能 要 会 把 被 让 给 对 从 向 到 于 以 "
    "这 那 哪 什 怎 么 们 我 你 他 它 她 个 些 种 样 里 中 上 下 前 后 内 外 没 有 无 不 "
    "而 且 并 若 如 虽 然 则 即 亦 其 之 者 也 已 经 过 来 去 起 出 将 应 需 进 成 作 方 "
    "时 候 地 东 西 事 现 目 间 此 实 当 毕 似 许 定 得 吗 呢 吧 啊 呀 哦 嗯 啦 咯 嘛 各 该 等"
)


def _is_generic_bigram(bg):
    """bigram 两字皆属功能字 → 视为纯虚词组合，剔除。"""
    return len(bg) == 2 and bg[0] in _FUNCTION_CHARS and bg[1] in _FUNCTION_CHARS


def _spark_terms(text):
    """抽碎片的实义关键词（离线）：去纯虚词，中文按「相邻单字合词」补 bigram。

    过滤策略（与概念层刻意不同）：
      · 中文 bigram 仅当【两字皆功能字】才剔除（_is_generic_bigram），从而保留
        领域/坐标/主尺 等实义主题词，只去 的是/可以/但是 这类连接性碎片；
      · 拉丁词统一小写，仅按 _STOP 去极少虚词；
      · 不用概念层的 _GENERIC_BAN（会误杀主题词）。"""
    toks = tokenize(text or "")
    out = set()
    for t in toks:
        if t.isascii():
            t = t.lower()
            if len(t) >= 2 and t not in _STOP:
                out.add(t)
        # 中文相邻单字合词（仅当两端都不是拉丁时才拼）
    for i in range(len(toks) - 1):
        a, b = toks[i], toks[i + 1]
        if a.isascii() or b.isascii():
            continue
        bg = a + b
        if len(bg) == 2 and not _is_generic_bigram(bg):
            out.add(bg)
    return out


# ----------------------------------------------------------------- 捕获 / 列表
def add_spark(content, title=None, tags=None, source="manual"):
    """捕获一条灵感碎片。content 非空，title 缺省取首 24 字；自带建表守卫
    （Skill 引擎 CLI 独立运行也能建表）。返回 {ok,id,title,status}。"""
    content = (content or "").strip()
    if not content:
        return {"ok": False, "msg": "内容不能为空"}
    title = (title or "").strip() or content[:24]
    now = time.time()
    con = connect()
    # 自带建表守卫（兼容早期库 / CLI 独立运行）
    con.execute("""
    CREATE TABLE IF NOT EXISTS sparks (
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT NOT NULL,
      tags TEXT, source TEXT NOT NULL DEFAULT 'manual', status TEXT NOT NULL DEFAULT 'raw',
      created_at REAL NOT NULL, updated_at REAL NOT NULL, hatched_item_id INTEGER, embedding TEXT)""")
    cur = con.execute(
        "INSERT INTO sparks(title,content,tags,source,status,created_at,updated_at) "
        "VALUES(?,?,?,?,'raw',?,?)",
        (title, content, _norm_tags(tags), source, now, now))
    sid = cur.lastrowid
    con.commit(); con.close()
    return {"ok": True, "id": sid, "title": title, "status": "raw"}


def list_sparks(status=None, limit=500):
    con = connect()
    if status:
        rows = con.execute(
            "SELECT * FROM sparks WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit)).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM sparks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [_row_spark(r) for r in rows]


def get_spark(sid):
    con = connect()
    r = con.execute("SELECT * FROM sparks WHERE id=?", (sid,)).fetchone()
    con.close()
    return _row_spark(r) if r else None


def update_spark_status(sid, status, tags=None):
    con = connect()
    now = time.time()
    if tags is not None:
        con.execute(
            "UPDATE sparks SET status=?, tags=?, updated_at=? WHERE id=?",
            (status, _norm_tags(tags), now, sid))
    else:
        con.execute(
            "UPDATE sparks SET status=?, updated_at=? WHERE id=?", (status, now, sid))
    ok = con.total_changes > 0
    con.commit(); con.close()
    return ok


def delete_spark(sid):
    con = connect()
    cur = con.execute("DELETE FROM sparks WHERE id=?", (sid,))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


# ----------------------------------------------------------------- 聚类萌发（软洞察）
def spark_clusters(top_k=8, min_shared=2, min_jac=0.0):
    """离线聚类萌发：关键词共现（并查集）把相近碎片贪心聚成主题簇。
    只呈现「这些碎片似乎在讲同一件事」的结构，不下结论、不替用户判定。

    主门槛是【共享词数 ≥ min_shared】（中文按 bigram 还原后，2 个实义词已是很强的
    相关性信号）；Jaccard 仅作可选的额外收紧（min_jac>0 时才生效，默认 0 即不卡
    Jaccard）。原因：bigram 会把短中文碎片的并集膨胀得很大，Jaccard 天然偏低，若
    用作硬门槛会把本该聚拢的相关碎片误杀——与「以共享词数为主要判据」的设计相悖。"""
    sparks = list_sparks(limit=500)
    if len(sparks) < 2:
        return []
    vec = {s["id"]: _spark_terms(s["content"]) for s in sparks}
    ids = [s["id"] for s in sparks]

    # 并查集
    parent = {i: i for i in ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # 两两评估：共享词足够多才合并（按共享词降序，优先合并确凿相近的）；
    # 仅当 min_jac>0 时才额外要求 Jaccard 达标（可选收紧，非默认）。
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = vec[ids[i]], vec[ids[j]]
            if not a or not b:
                continue
            inter = len(a & b)
            if inter < min_shared:
                continue
            jac = inter / (len(a | b) or 1)
            if min_jac > 0 and jac < min_jac:
                continue
            pairs.append((inter, jac, ids[i], ids[j]))
    pairs.sort(key=lambda x: (-x[0], -x[1]))
    for inter, jac, a, b, in pairs:
        union(a, b)

    # 归集簇
    clusters = {}
    for s in sparks:
        clusters.setdefault(find(s["id"]), []).append(s)

    out = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        cnt = Counter()
        for m in members:
            for t in vec[m["id"]]:
                cnt[t] += 1
        rep = [w for w, c in cnt.most_common(5) if c >= 2]
        title = " / ".join(rep[:3]) if rep else (members[0]["title"] or "未命名簇")
        out.append({
            "title": title,
            "shared_terms": rep,
            "size": len(members),
            "members": [{"id": m["id"], "title": m["title"] or "",
                         "content": (m["content"] or "")[:90]} for m in members],
        })
    out.sort(key=lambda x: (-x["size"], x["title"]))
    return out[:top_k]


# ----------------------------------------------------------------- 孵化成知识条目
def hatch_spark(sid, title=None, axis_domain=None, run_closure=True):
    """孵化：把一条灵感碎片投影成正式知识条目（走 kb.add_knowledge 双尺投影 + 闭环），
    并回填 hatched_item_id + status=hatched，打通原料 → 成品溯源。
    延迟导入 kb（避免包加载期循环），调用时包已就绪。"""
    sp = get_spark(sid)
    if not sp:
        return {"ok": False, "msg": "碎片不存在"}
    if sp.get("hatched_item_id"):
        return {"ok": False, "msg": "该碎片已孵化", "item_id": sp["hatched_item_id"]}
    content = sp["content"]
    title = (title or sp.get("title") or "").strip() or content[:20]
    import kb as _kb
    res = _kb.add_knowledge(
        title, content, bool(run_closure),
        _kb.normalize_axis_domain(axis_domain) if axis_domain else None)
    if not res.get("ok"):
        return res
    item_id = (res.get("item") or {}).get("id")
    con = connect()
    con.execute(
        "UPDATE sparks SET status='hatched', hatched_item_id=?, updated_at=? WHERE id=?",
        (item_id, time.time(), sid))
    con.commit(); con.close()
    return {"ok": True, "spark_id": sid, "item_id": item_id, "item": res.get("item")}
