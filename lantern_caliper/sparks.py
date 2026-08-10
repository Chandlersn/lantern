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


# ----------------------------------------------------------------- 簇归属
def cluster_of_spark(sid):
    """返回该碎片所属簇的 (shared_terms, sibling_ids)；不在任何簇则返回 (None, [])。

    用于孵化时把「簇信号」带进投影、并把同簇兄弟标为 incubating 形成联动——
    碎片间的邻近关系在孵化时不应被丢弃。"""
    clusters = spark_clusters(top_k=50, min_shared=2, min_jac=0.0)
    for c in clusters:
        ids = [m["id"] for m in c["members"]]
        if sid in ids:
            sibs = [i for i in ids if i != sid]
            return (c.get("shared_terms") or []), sibs
    return None, []


def _infer_domain(sp, cluster_terms, kbm):
    """从碎片标签/簇主题中，尝试匹配一个【受控学科域】作为 axis_domain 建议。

    仅当标签字面命中受控域时才给（诚实、不下结论）；命中不到则返回 None，
    交由 add_knowledge 启发式自由归类。不臆造域。"""
    try:
        controlled = set(kbm.axis_domains() or [])
    except Exception:                       # noqa: BLE001
        controlled = set()
    if not controlled:
        return None
    tags = []
    try:
        tags = json.loads(sp.get("tags") or "[]") if sp.get("tags") else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    for t in list(tags) + list(cluster_terms or []):
        if t in controlled:
            return t
    return None


# ----------------------------------------------------------------- 孵化成知识条目（智能孵化）
def hatch_spark(sid, title=None, axis_domain=None, run_closure=True, hit_threshold=4.0):
    """智能孵化：把一条灵感碎片接入知识网，并触发一次小型方法执行 + 系统事件。

    管线（对照「文件移动」式旧孵化）：
      ① 冗余闸门：先 kb.query 判命中，命中则【增量合并】原条目（保留 id/双尺定位，
         追加带日期的证据），不新建；未命中则新建。
      ② 投影富化：查碎片所属簇，提取 shared_terms + 兄弟，预填 axis_domain 建议，
         并在正文留「孵化自灵感碎片（簇主题：…）」元痕（不下结论仅留痕）。
      ③ 全库关联发现：新建后以新节点为中心跑 suggest_links，把潜在关联写成
         links(confirmed=0) 软边，回报 links_found。
      ④ 反馈轴自检：collision / 新域候选 / 近似未合并 → 各推一条 feedback_inbox，
         让库自我更新、用户看到 🔔。
      ⑤ 簇血缘：同簇未孵化兄弟标 incubating（联动），血缘写入 hatch_events。
      ⑥ 事件日志：把本次孵化的决策/簇/关联数/反馈数/兄弟数落 hatch_events，
         供 kb.hatch_stats() 聚合（库可「反思」生长；Skill 可据以校准轴绩点）。

    延迟导入 kb/links/feedback（避免包加载期循环）。"""
    sp = get_spark(sid)
    if not sp:
        return {"ok": False, "msg": "碎片不存在"}
    if sp.get("hatched_item_id"):
        return {"ok": False, "msg": "该碎片已孵化", "item_id": sp["hatched_item_id"]}
    content = sp["content"]
    title = (title or sp.get("title") or "").strip() or content[:20]
    import kb as _kb
    from . import links as _links
    from . import feedback as _feedback

    con = connect()

    # ② 投影富化：簇信号 + 域建议
    cluster_terms, siblings = cluster_of_spark(sid)
    if not axis_domain:
        axis_domain = _infer_domain(sp, cluster_terms, _kb)

    # ① 冗余闸门：先检索判命中（复用 upsert-kb 的命中逻辑）
    qres = _kb.query(title, top_k=1)
    results = qres.get("results") or []
    hit, near = None, None
    if results:
        top = results[0]
        sc = float(top.get("score", 0) or 0)
        if sc >= hit_threshold:
            hit = top
        elif sc > 0:
            near = top

    feedback_ids, links_found, decision, item_id, new_item = [], 0, "new", None, None

    if hit:
        # 合并：保留原条目 id / 双尺定位，追加带日期的证据
        decision = "merged"
        item_id = hit["id"]
        append_to_item(item_id, content, label="灵感碎片孵化合并")
        fid = _feedback.push_feedback(
            item_id, hit.get("title", title), axis_domain,
            {"type": "hatch_merged",
             "note": f"灵感碎片「{title}」已并入此条目（保留原双尺定位）",
             "spark_id": sid}, severity="info")
        feedback_ids.append(fid)
    else:
        # 新建 + 投影富化元痕 + 关联发现 + 反馈自检
        res = _kb.add_knowledge(
            title, content, bool(run_closure),
            _kb.normalize_axis_domain(axis_domain) if axis_domain else None)
        if not res.get("ok"):
            con.close()
            return res
        new_item = res.get("item") or {}
        item_id = new_item.get("id")
        if cluster_terms:
            note = "、".join(cluster_terms[:4])
            append_to_item(
                item_id, f"本条目孵化自灵感碎片，簇主题：{note}", label="碎片来源")
        # ③ 全库关联发现：以新节点为中心，写软边
        try:
            sug = _links.suggest_links(k=8, min_shared=2, persist=True, anchor=item_id)
            links_found = len(sug.get("suggestions") or [])
        except Exception:                      # noqa: BLE001
            links_found = 0
        # ④ 反馈轴自检
        if new_item.get("collision"):
            feedback_ids.append(_feedback.push_feedback(
                item_id, title, axis_domain,
                {"type": "hatch_collision",
                 "note": "孵化条目坐标偏离所在域典型读数，建议人工核对标签/关联",
                 "offset": new_item.get("offset")}, severity="warn"))
        if axis_domain and axis_domain not in (_kb.axis_domains() or []):
            feedback_ids.append(_feedback.push_feedback(
                item_id, title, axis_domain,
                {"type": "hatch_new_domain",
                 "note": f"孵化使用了库内尚未登记的学科域「{axis_domain}」，建议登记入 axes 受控词表",
                 "domain": axis_domain}, severity="info"))
        if near:
            feedback_ids.append(_feedback.push_feedback(
                item_id, title, axis_domain,
                {"type": "hatch_near",
                 "note": f"与条目「{near.get('title')}」(# {near.get('id')}) 内容相近但未达合并阈值，已建立软边待确认",
                 "near_id": near.get("id")}, severity="info"))

    # ⑤ 簇血缘：同簇未孵化兄弟标 incubating（联动）
    sib_incubating = []
    for sibid in siblings:
        s = get_spark(sibid)
        if s and not s.get("hatched_item_id"):
            update_spark_status(sibid, "incubating")
            sib_incubating.append(sibid)

    # 回填 spark → item 溯源
    now = time.time()
    con.execute(
        "UPDATE sparks SET status='hatched', hatched_item_id=?, updated_at=? WHERE id=?",
        (item_id, now, sid))
    # ⑥ 事件日志
    con.execute(
        "INSERT INTO hatch_events(spark_id,item_id,decision,near_match_item_id,"
        "cluster_terms,sibling_spark_ids,links_found,feedback_ids,axis_domain,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (sid, item_id, decision, (near or {}).get("id"),
         json.dumps(cluster_terms, ensure_ascii=False),
         json.dumps(sib_incubating, ensure_ascii=False),
         links_found, json.dumps(feedback_ids, ensure_ascii=False),
         axis_domain, now))
    con.commit(); con.close()
    return {
        "ok": True, "spark_id": sid, "item_id": item_id, "decision": decision,
        "near_match_item_id": (near or {}).get("id"),
        "cluster_terms": cluster_terms, "siblings_incubating": sib_incubating,
        "siblings_total": siblings, "links_found": links_found,
        "feedback_ids": feedback_ids, "axis_domain": axis_domain,
        "item": (new_item or hit),
    }
