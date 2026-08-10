#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灯笼·多维轴认知方法 —— Skill 引擎（纯标准库）
====================================================================
把「头脑风暴」Node 版里已通过确定性测试的精密机制，**逐条移植**为纯标准库
Python，并接入 lantern-caliper 知识库（kb.py）。

移植来源（已逐行核对）：
  - 头脑风暴/lantern/axis.js      → 绩点生命周期 update_scores / feedback_axis / 快照去重
  - 头脑风暴/lantern/config.js    → THRESHOLDS 阈值常量
  - 头脑风暴/lantern/thresholds.js → 阈值自适应校准（报告式，保守）
  - 头脑风暴/lantern/analysis.js  → 方法论编排（见 SKILL.md，本项目仅保留确定性内核）

设计立场（与第一性原理一致）：
  · 本文件只承担「确定性、可复现」的评分机械——正交评审的耦合扣分、绩点生命
    周期、收敛/补维停止阈值。这些是精密机械，不能用自然语言描述退化成模糊指令。
  · 真正的「投影 / 评审判断」由调用方（WorkBuddy 模型 / agent）完成——它沿轴
    产出视角化投影，并独立给出轴间耦合度，再把结构化结果喂给本引擎。
  · 「分析透镜」（框架轴）是「存储坐标」（KB 领域带 × 游标）的**下游产物**：
    先用 kb.health() 拉 KB 域分布，再由 AI 提议候选轴，本引擎只负责计分与记忆。

全部仅依赖 Python 标准库 + 兄弟模块 kb（lantern-caliper 的纯标准库 KB 核心）。
"""

import argparse
import json
import math
import os
import sys
import datetime

# ---------------------------------------------------------------- 阈值（与 Node config.js 完全一致）
THRESHOLDS = {
    "SCORE_INIT": 0.6,        # 新轴进入=中性分，须经验证才能升入优先区
    "SCORE_MIN": 0.4,         # 低于此=休眠（淘汰，仍可功绩复活）
    "SCORE_PREF": 0.7,        # 高于此=优选轴（优先推荐）
    "SCORE_ARCHIVE": 0.2,     # 低于此=归档（几乎不再复活）
    "REVIVE_MERITS": 3,       # 休眠轴良好选用累计达此次数 → 自动复活
    "DECAY": 0.015,           # 活跃但未选用轴的缓慢衰减
    "GAIN_GOOD": 0.12,        # 表现良好轴的回升
    "GAIN_BASE": 0.05,        # 普通选用基础回升
    "SCORE_CEIL": 0.9,        # 选用回升上限（消除原 0.7 天花板 bug）
    "DECAY_FLOOR_OFFSET": 2,  # 衰减下界 = SCORE_MIN - OFFSET*DECAY，留缓冲
}
SCORE_INIT = THRESHOLDS["SCORE_INIT"]
SCORE_MIN = THRESHOLDS["SCORE_MIN"]
SCORE_PREF = THRESHOLDS["SCORE_PREF"]
SCORE_ARCHIVE = THRESHOLDS["SCORE_ARCHIVE"]
REVIVE_MERITS = THRESHOLDS["REVIVE_MERITS"]
DECAY = THRESHOLDS["DECAY"]
GAIN_GOOD = THRESHOLDS["GAIN_GOOD"]
GAIN_BASE = THRESHOLDS["GAIN_BASE"]
SCORE_CEIL = THRESHOLDS["SCORE_CEIL"]
DECAY_FLOOR_OFFSET = THRESHOLDS["DECAY_FLOOR_OFFSET"]

SNAPSHOT_DEDUP_MS = 30 * 60 * 1000
HISTORY_KEEP = 200

# ---------------------------------------------------------------- 路径解析
def _default_kb_dir():
    # KB 真相源：lantern-caliper 仓库根（含 kb.py 与 lantern.db；store.py 按自身目录解析 DB 路径）。
    # 优先用环境变量 LANTERN_KB_DIR（可指向仓库根，或内含 lantern-caliper 副本的父目录），
    # 否则从本脚本位置相对回溯到仓库根——这样无论 Skill 放在仓库内
    # （skills/lantern-method/）还是用户的 ~/.workbuddy/skills/，都能自动定位。
    env = os.environ.get("LANTERN_KB_DIR")
    if env:
        # env 可能直接指向含 kb.py 的目录，也可能指向一个内含 lantern-caliper 副本的父目录。
        # 两种都接受，避免「env 指向副本却因缺 kb.py 而静默回退真实库」的 footgun。
        for cand in (os.path.normpath(env),
                     os.path.normpath(os.path.join(env, "lantern-caliper"))):
            if os.path.isfile(os.path.join(cand, "kb.py")):
                return cand
        return os.path.normpath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    # here = <repo>/skills/lantern-method/scripts → 仓库根 = here/../../..
    candidates = [
        os.path.normpath(os.path.join(here, "..", "..", "..")),            # <repo>/（含 kb.py）
        os.path.normpath(os.path.join(here, "..", "..", "..", "lantern-caliper")),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "kb.py")):
            return c
    return candidates[0]

KB_DIR = _default_kb_dir()
# Skill 自身的元数据（轴绩点库 / 元信息 / 历史 / 校准）一律存在 Skill 自己的
# 目录下，不污染知识库目录——保证 KB 目录只含 KB 职能文件（独立与纯洁）。
_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(_SKILL_DIR, "state")
os.makedirs(STATE_DIR, exist_ok=True)
SCORES_FILE = os.path.join(STATE_DIR, "lantern_axis_scores.json")
META_FILE = os.path.join(STATE_DIR, "lantern_axis_meta.json")
HISTORY_FILE = os.path.join(STATE_DIR, "lantern_axis_history.json")
CALIB_FILE = os.path.join(STATE_DIR, "lantern_axis_calibration.json")

# 懒加载 kb 模块（仅当真正需要写 KB 时才 import）
_KB = None

def _load_kb():
    global _KB
    if _KB is None:
        sys.path.insert(0, KB_DIR)
        import kb as _mod
        _KB = _mod
    return _KB


# ---------------------------------------------------------------- 持久化
def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 轴库引擎
def axis_key(domain, dimension):
    return f"{domain}|{dimension}"


class AxisLibrary:
    def __init__(self):
        self.scores = _read_json(SCORES_FILE, {})
        self.meta = _read_json(META_FILE, {})
        self.history = _read_json(HISTORY_FILE, [])

    # ---- 元信息 ----
    def touch_meta(self, k, patch):
        base = {"used": 0, "dormant": False, "merits": 0, "lastUsed": None, "vital": 0}
        self.meta[k] = {**base, **self.meta.get(k, {}), **patch}

    def get_axis_state(self, domain, dimension):
        k = axis_key(domain, dimension)
        base = {"used": 0, "dormant": False, "merits": 0, "lastUsed": None, "vital": 0}
        return {**base, **self.meta.get(k, {})}

    # ---- 快照（去重：同概念 30 分钟内只留最新） ----
    def record_snapshot(self, scores, concept):
        now = datetime.datetime.now()
        key = concept or "__empty__"
        dup = None
        for snap in self.history:
            if (snap.get("concept") or "__empty__") != key:
                continue
            snap_ts = datetime.datetime.fromisoformat(snap["ts"])
            if abs((now - snap_ts).total_seconds() * 1000) < SNAPSHOT_DEDUP_MS:
                dup = snap
                break
        if dup:
            dup["ts"] = now.isoformat()
            dup["scores"] = {**scores}
        else:
            self.history.append({"ts": now.isoformat(), "concept": concept or "", "scores": {**scores}})
        if len(self.history) > HISTORY_KEEP:
            self.history = self.history[-HISTORY_KEEP:]

    def get_trend(self, domain, dimension):
        k = axis_key(domain, dimension)
        out = []
        for snap in self.history:
            sc = snap.get("scores", {}).get(k)
            if sc is not None:
                out.append({"ts": snap["ts"], "concept": snap.get("concept"), "score": sc})
        return out

    def get_library(self):
        rows = []
        for k, v in self.scores.items():
            d, dim = k.split("|") if "|" in k else (k, "")
            st = self.meta.get(k, {})
            rows.append({
                "domain": d, "dimension": dim, "score": v,
                "active": v >= SCORE_MIN, "dormant": bool(st.get("dormant")),
                "merits": st.get("merits", 0), "used": st.get("used", 0),
                "vital": st.get("vital", 0),
            })
        return sorted(rows, key=lambda r: (r["score"] if r["score"] is not None else -1), reverse=True)

    # ---- 用户反馈 ----
    def feedback_axis(self, domain, dimension, vote):
        k = axis_key(domain, dimension)
        s = self.scores
        if k not in s:
            s[k] = SCORE_INIT
        delta = 0.1 if vote == "up" else -0.2
        s[k] = max(0.0, min(1.2, s[k] + delta))
        st = self.get_axis_state(domain, dimension)
        new_merits = st["merits"] + (1 if vote == "up" else 0)
        self.touch_meta(k, {"merits": new_merits, "lastUsed": datetime.datetime.now().isoformat()})
        if vote == "up":
            cur = self.meta.get(k, {})
            if cur.get("dormant") and new_merits >= REVIVE_MERITS:
                cur["dormant"] = False
                cur["vital"] = 1
                self.meta[k] = cur
        self.record_snapshot(s, "feedback")
        self.save()
        return s[k]

    # ---- 核心：根据一次分析结果更新全场绩点（与 axis.js updateScores 逐行对齐） ----
    def update_scores(self, gen, review, opts=None):
        opts = opts or {}
        s = self.scores
        m = self.meta
        chosen = {axis_key(a.get("domain"), a.get("dimension")) for a in (gen.get("axes") or [])}
        now = datetime.datetime.now().isoformat()

        # —— 本轮被选用的轴：新生/回升、计数、处理功绩复活 ——
        for a in (gen.get("axes") or []):
            k = axis_key(a.get("domain"), a.get("dimension"))
            if k not in s:
                s[k] = SCORE_INIT
            before = m.get(k, {})
            was_dormant = bool(before.get("dormant"))
            reviving_candidate = was_dormant or (before.get("merits", 0) > 0)
            proj = (a.get("projection") or "").strip()
            good = len(proj) >= 20 and a.get("orthogonal", True) is not False
            if len(proj) < 20:
                s[k] = max(0.0, s[k] - 0.1)          # 差投影惩罚减半（v4.3）
            if a.get("orthogonal") is False:
                s[k] = max(0.0, s[k] - 0.1)
            gain = GAIN_GOOD if good else GAIN_BASE
            if s[k] < SCORE_CEIL:
                s[k] = min(SCORE_CEIL, s[k] + gain)
            self.touch_meta(k, {
                "used": before.get("used", 0) + 1,
                "lastUsed": now,
                "vital": 1,
                "dormant": False,
                "merits": before.get("merits", 0) + (1 if (good and reviving_candidate) else 0),
            })
            cur = self.meta.get(k, {})
            if reviving_candidate and cur.get("merits", 0) >= REVIVE_MERITS:
                cur["dormant"] = False
                cur["vital"] = 1
                self.meta[k] = cur

        # —— 评审高耦合：按 pairwise.score 加权扣分；低置信(<0.6)只警告不扣分 ——
        pairwise_map = {}
        for p in (review or {}).get("pairwise", []) or []:
            if not p or not p.get("a") or not p.get("b"):
                continue
            pairwise_map["|".join(sorted([p["a"], p["b"]]))] = p
        coupl_penalty = lambda sc: (0.3 if sc >= 10 else 0.25 if sc >= 9 else 0.2 if sc >= 8 else 0.12 if sc >= 7 else 0.05)
        for pair in (review or {}).get("high_coupling", []) or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            p = pairwise_map.get("|".join(sorted([pair[0], pair[1]])))
            sc = (p.get("score") if p and p.get("score") is not None else 8)
            conf = (p.get("confidence") if p and p.get("confidence") is not None else 0.8)
            if conf < 0.6:
                sys.stderr.write(f"  (评审低置信) 高耦合对 {pair[0]}|{pair[1]} 置信度 {conf}，仅警告不扣分\n")
                continue
            for k in pair:
                if k and k in s:
                    s[k] = max(0.0, s[k] - coupl_penalty(sc))

        # —— 休眠 / 归档 / 衰减（针对已存在库的轴） ——
        decay_floor = SCORE_MIN - DECAY_FLOOR_OFFSET * DECAY  # 约 0.37
        for k in list(s.keys()):
            st = m.get(k, {})
            if k in chosen:
                continue
            if s[k] < SCORE_ARCHIVE:
                self.touch_meta(k, {"dormant": True, "vital": 3})     # 归档
            elif s[k] < SCORE_MIN:
                self.touch_meta(k, {"dormant": True, "vital": 2})     # 休眠（淘汰）
            else:
                if (st.get("used") or 0) > 0:
                    s[k] = max(decay_floor, s[k] - DECAY)             # 缓慢衰减

        self.save()
        if opts.get("snapshot") is not False:
            self.record_snapshot(s, opts.get("concept") or "")
            self.save()
        return s

    # ---- 阈值自适应校准（报告式，保守；永不自动改坏） ----
    def calibrate_thresholds(self):
        s = self.scores
        vals = list(s.values())
        n = len(vals)
        in_pref = sum(1 for v in vals if v >= SCORE_PREF)
        near_min = sum(1 for v in vals if SCORE_MIN <= v < SCORE_MIN + 0.05)
        archived = sum(1 for x in self.meta.values() if x.get("vital") == 3)
        suggestion = []
        if in_pref == 0 and n >= 5:
            suggestion.append("优选区长期空置(0/%d)：建议 SCORE_CEIL 提到 0.95 或 GAIN_GOOD 提到 0.15" % n)
        if near_min > 0 and near_min / n > 0.3:
            suggestion.append("约 %d/%d 轴贴着休眠线(0.4~0.45)：衰减/惩罚仍偏重，建议 DECAY 降到 0.01" % (near_min, n))
        if archived > 0 and archived / n > 0.2:
            suggestion.append("归档占比过高(%d/%d)：SCORE_ARCHIVE=0.2 可能过严，建议提到 0.15" % (archived, n))
        return {
            "observed": {"total": n, "inPref": in_pref, "nearMin": near_min, "archived": archived},
            "thresholds": THRESHOLDS,
            "suggestion": suggestion or ["当前参数与运行数据大致匹配，无需调整"],
        }

    def save(self):
        _write_json(SCORES_FILE, self.scores)
        _write_json(META_FILE, self.meta)
        _write_json(HISTORY_FILE, self.history)


# ---------------------------------------------------------------- KB 集成
def kb_stats():
    """拉 KB 域分布与轴分类法，供『数据驱动定轴』使用。"""
    kb = _load_kb()
    health = kb.health()
    ax = kb.axes()
    # axis_domain_distribution 现在由 KB 自身提供（kb.axis_domain_distribution()），
    # Skill 不再直接对 items 表跑裸 SQL——查询封装在 KB 内部，保证 KB 存储层的独立与纯洁。
    axis_dist = kb.axis_domain_distribution()
    return {
        "item_count": health.get("items"),
        "domain_distribution": health.get("domain_distribution"),
        "axis_domain_distribution": axis_dist,
        "axes_domains": ax.get("domains"),
        "axes_list": ax.get("axes"),
        "mode": health.get("mode"),
    }


def _format_review_section(rv):
    """把反馈轴对抗审查 JSON 渲染为可读的 KB 段落。"""
    field_map = [
        ("core_verdict_weakest_support", "核心判断最弱支撑点"),
        ("strongest_counter", "最强反论据"),
        ("hidden_assumptions", "隐藏假设"),
        ("blind_spots", "透镜盲区"),
        ("internal_tension", "内部张力"),
        ("over_reach", "过度推断"),
        ("verdict_revised", "修订后核心判断"),
    ]
    lines = ["## 对抗审查（反馈轴）", ""]
    for key, label in field_map:
        v = rv.get(key)
        if v is None:
            continue
        if isinstance(v, list):
            if not v:
                continue
            lines.append(f"- **{label}**：")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"- **{label}**：{v}")
    if rv.get("must_revise_before_write"):
        lines.append("")
        lines.append("> 反馈轴判定：分析在写回前已按上述修订软化核心判断 / 投影。")
    return "\n".join(lines)


def write_kb(title, content, axis_domain=None, review=None):
    """把一次分析落成结构化洞察，写回 KB（入库即双尺定位 + 闭环）。

    重要：反馈轴对抗审查（review）**不再写进文章正文**——那样会破坏知识文章的
    独立与纯洁性。改为推入独立的反馈收件箱（数据表），既作消息通知，也作
    知识库自我更新的指导。文章正文保持纯净。

    写回校验：仅当 add_knowledge 成功（拿到条目 id）才推送反馈，避免写回被拒
    （如 content 为空）时留下 item_id 为空的孤儿反馈。"""
    kb = _load_kb()
    res = kb.add_knowledge(title, content, True, axis_domain)
    if res.get("ok"):
        new_id = (res.get("item") or {}).get("id")
        if new_id and review:
            push_review_inbox(kb, new_id, title, axis_domain, review)
    return res


def _severity_of(rv):
    """由反馈轴内容推断严重度：需先修订=critical，有任何真实找茬=warn，空=info。"""
    if rv.get("must_revise_before_write"):
        return "critical"
    for k in ("strongest_counter", "blind_spots", "internal_tension",
              "over_reach", "hidden_assumptions", "core_verdict_weakest_support"):
        v = rv.get(k)
        if isinstance(v, list):
            if v:
                return "warn"
        elif isinstance(v, str) and v.strip():
            return "warn"
    return "info"


def push_review_inbox(kb, item_id, title, axis_domain, review):
    """把一条自我对抗审查反馈推入独立收件箱（不污染文章正文）。"""
    try:
        rv = review if isinstance(review, dict) else json.loads(review)
    except (json.JSONDecodeError, TypeError):
        rv = {"raw": str(review)}
    sev = _severity_of(rv)
    mr = bool(rv.get("must_revise_before_write"))
    return kb.push_feedback(item_id, title, axis_domain, rv, sev, mr)


def _derive_concept(title):
    """从条目标题派生检索用的『概念名』：取中文间隔号 `·` 之前的部分
    （如『认知偏差·补充视角』→『认知偏差』）。upsert 的命中判定应以『概念』
    而非『完整新标题』去匹配既有条目——否则新标题与旧标题逐字不匹配会永远走新建。"""
    t = (title or "").strip()
    for sep in ("·", "•", "丨", "|", " - ", "："):
        if sep in t:
            return t.split(sep, 1)[0].strip()
    return t


def upsert_kb(title, content, axis_domain=None, review=None, concept=None, hit_threshold=4.0):
    """写回 KB 的智能入口（封装 kb.query + add_knowledge + update_article）：
    先检索判定命中，命中则增量更新已有条目（保留 id 与双尺定位），未命中则新建。
    对应 SKILL.md 步骤 E『先检索 → 命中则增量更新，未命中则新增』。

    命中判定：kb.query 的 top 结果 score ≥ hit_threshold（token 重叠分）。
      · 检索词用『概念名』（--concept 显式给定，否则取标题 `·` 之前的部分），
        而非完整新标题——这样才能匹配到既有同概念条目。
      · 同一概念的既有条目（概念名在标题/正文）→ score 通常 8–10；
        无关条目 → 0–3；阈值 4.0 可干净分开，对应文档中的『重叠 > 50%』。
    命中时把本次 content（含反馈轴段）+ 标注日期，追加到已有条目 content 末尾，保留历史。
    """
    kb = _load_kb()
    # 1) 复用 kb.query 检索（写回前先查重用）——用概念名，不用完整新标题
    qtext = (concept or _derive_concept(title) or "").strip()
    qres = kb.query(qtext, top_k=1)
    results = qres.get("results") or []
    hit = None
    if results and float(results[0].get("score", 0) or 0) >= hit_threshold:
        hit = results[0]

    # 2) 命中 → 增量更新（保留 id / 双尺定位）；未命中 → 新建
    #    注意：反馈轴（review）**不写进 content**——保持文章正文纯洁，
    #    改由第 3 步推入独立反馈收件箱。
    if hit:
        item_id = hit["id"]
        existing = kb.get_article(item_id) or {}
        old = existing.get("content") or ""
        today = datetime.date.today().isoformat()
        merged = old.rstrip("\n") + f"\n\n---\n## 增量更新（{today}）\n" + content
        res = kb.update_article(item_id, existing.get("title") or title, merged, axis_domain)
        action, res_id = "updated", item_id
    else:
        res = kb.add_knowledge(title, content, True, axis_domain)
        res_id = (res.get("item") or {}).get("id")
        action = "created"

    # 3) 把反馈轴推入独立收件箱（消息通知 + 自我更新指导），与文章正文解耦。
    #    关键：仅当写回确实成功（拿到有效条目 id）才推送——写回被拒（如 content
    #    为空）时 res_id 为 None，若仍推送会产生 item_id 为空的孤儿反馈记录。
    write_ok = bool(res_id)
    if review and write_ok:
        push_review_inbox(kb, res_id, title, axis_domain, review)
    return {"ok": write_ok, "action": action, "id": res_id,
            "title": (hit or {}).get("title") or title,
            "matched_score": (hit or {}).get("score"), "result": res}


def kb_query(text, top_k=5):
    """自由文本检索 KB，写回前先查重用 / 增量更新。"""
    kb = _load_kb()
    return kb.query(text, top_k=top_k)


def kb_context(qtext, top_k=5):
    """聚合检索上下文包，可直接喂给模型作为相关知识。"""
    kb = _load_kb()
    return kb.context(qtext, top_k=top_k)


# ---------------------------------------------------------------- CLI
def _cmd_kb_stats(_):
    print(json.dumps(kb_stats(), ensure_ascii=False, indent=2))


def _cmd_update_scores(args):
    gen = json.loads(args.gen)
    review = json.loads(args.review) if args.review else {}
    lib = AxisLibrary()
    lib.update_scores(gen, review, {"snapshot": True, "concept": args.concept})
    print(json.dumps(lib.get_library(), ensure_ascii=False, indent=2))


def _cmd_feedback(args):
    lib = AxisLibrary()
    v = lib.feedback_axis(args.domain, args.dimension, args.vote)
    print(json.dumps({"score": v, "state": lib.get_axis_state(args.domain, args.dimension)}, ensure_ascii=False))


def _cmd_push_feedback(args):
    """把一条自我对抗审查反馈推入独立收件箱（不污染文章正文）。"""
    kb = _load_kb()
    rv = json.loads(args.review) if args.review else {}
    fid = kb.push_feedback(args.item_id, args.title, args.axis_domain, rv,
                           args.severity, args.must_revise)
    print(json.dumps({"ok": True, "feedback_id": fid}, ensure_ascii=False))


def _cmd_library(_):
    lib = AxisLibrary()
    print(json.dumps(lib.get_library(), ensure_ascii=False, indent=2))


def _cmd_state(args):
    lib = AxisLibrary()
    print(json.dumps(lib.get_axis_state(args.domain, args.dimension), ensure_ascii=False))


def _cmd_calibrate(_):
    lib = AxisLibrary()
    print(json.dumps(lib.calibrate_thresholds(), ensure_ascii=False, indent=2))


def _cmd_write_kb(args):
    res = write_kb(args.title, args.content, args.axis_domain, args.review)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        sys.exit(1)


def _cmd_upsert_kb(args):
    res = upsert_kb(args.title, args.content, args.axis_domain, args.review,
                    args.concept, args.hit_threshold)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        sys.exit(1)


def _cmd_kb_query(args):
    print(json.dumps(kb_query(args.text, args.top_k), ensure_ascii=False, indent=2))


def _cmd_kb_context(args):
    print(json.dumps(kb_context(args.qtext, args.top_k), ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(description="灯笼·多维轴认知方法引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("kb-stats", help="拉 KB 域分布（数据驱动定轴用）")
    sp.set_defaults(func=_cmd_kb_stats)

    sp = sub.add_parser("update-scores", help="根据一次分析结果更新全场轴绩点")
    sp.add_argument("--gen", required=True, help='生成结果 JSON {"axes":[...]}')
    sp.add_argument("--review", help='评审结果 JSON {"pairwise":[...],"high_coupling":[[...]]}')
    sp.add_argument("--concept", default="", help="本次分析的概念（用于快照去重）")
    sp.set_defaults(func=_cmd_update_scores)

    sp = sub.add_parser("feedback", help="用户对某轴 👍/👎")
    sp.add_argument("--domain", required=True)
    sp.add_argument("--dimension", required=True)
    sp.add_argument("--vote", choices=["up", "down"], required=True)
    sp.set_defaults(func=_cmd_feedback)

    sp = sub.add_parser("library", help="打印当前轴库（按绩点排序）")
    sp.set_defaults(func=_cmd_library)

    sp = sub.add_parser("state", help="查单轴状态")
    sp.add_argument("--domain", required=True)
    sp.add_argument("--dimension", required=True)
    sp.set_defaults(func=_cmd_state)

    sp = sub.add_parser("calibrate", help="阈值自适应校准（报告式）")
    sp.set_defaults(func=_cmd_calibrate)

    sp = sub.add_parser("write-kb", help="强制新建条目写回 KB（不经命中判定）")
    sp.add_argument("--title", required=True)
    sp.add_argument("--content", required=True)
    sp.add_argument("--axis-domain", default=None)
    sp.add_argument("--review", default=None, help='反馈轴对抗审查 JSON（推入独立收件箱，不写进文章正文）')
    sp.set_defaults(func=_cmd_write_kb)

    sp = sub.add_parser("upsert-kb", help="智能写回：先检索判定命中，命中则增量更新、未命中则新增")
    sp.add_argument("--title", required=True, help="条目标题（也是检索用的概念名；可用 --concept 覆盖）")
    sp.add_argument("--content", required=True, help="条目正文（结构化模板内容）")
    sp.add_argument("--axis-domain", default=None, help="核心学科归属")
    sp.add_argument("--review", default=None, help='反馈轴对抗审查 JSON（推入独立收件箱，不写进文章正文）')
    sp.add_argument("--concept", default=None, help="检索概念（默认用 --title）")
    sp.add_argument("--hit-threshold", type=float, default=4.0, help="命中阈值：top 结果 score ≥ 此值视为同一概念（默认 4.0）")
    sp.set_defaults(func=_cmd_upsert_kb)

    sp = sub.add_parser("push-feedback", help="把一条自我对抗审查反馈推入独立收件箱（不写进文章正文）")
    sp.add_argument("--item-id", type=int, default=None, help="目标知识条目 id（新建前可省略）")
    sp.add_argument("--title", required=True, help="反馈标题（概念名 / 条目标题）")
    sp.add_argument("--axis-domain", default=None, help="核心学科归属")
    sp.add_argument("--review", default=None, help='反馈轴对抗审查 JSON')
    sp.add_argument("--severity", default="info", choices=["info", "warn", "critical"])
    sp.add_argument("--must-revise", type=int, default=0, help="写回前是否需先修订核心判断（0/1）")
    sp.set_defaults(func=_cmd_push_feedback)

    sp = sub.add_parser("kb-query", help="自由文本检索 KB（写回前先查重用）")
    sp.add_argument("--text", required=True, help="检索文本（通常用概念名）")
    sp.add_argument("--top-k", type=int, default=5)
    sp.set_defaults(func=_cmd_kb_query)

    sp = sub.add_parser("kb-context", help="聚合检索上下文包（可直喂模型）")
    sp.add_argument("--qtext", required=True)
    sp.add_argument("--top-k", type=int, default=5)
    sp.set_defaults(func=_cmd_kb_context)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
