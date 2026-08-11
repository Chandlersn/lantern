# -*- coding: utf-8 -*-
"""双尺度量引擎：主尺（学科领域）× 游标（演绎深度）的读数、带判定与典型值。"""

import math
import re

def backbone_of(pos):
    """按主尺位置落回主干学科带；带是范围，不是点。"""
    p = float(pos)
    for b in BACKBONE_BANDS:
        lo, hi = b["range"]
        if lo <= p < hi or (hi == 100 and p == 100):
            return b
    # 边界外兜底到最近
    return min(BACKBONE_BANDS, key=lambda b: abs(b["center"] - p))

def _is_broad_field(name, content=""):
    """这个名字算不算一个"够宽、够稳"的学科 / 主题领域，而非技术 / 实体碎片。

    规则（保守，宁可折回主干带也不乱立领域）：
      1) 空 / 单字 → 否；
      2) 在公认宽领域白名单 → 是；
      3) 整词就是某项技术/实体（rag/向量…）→ 否；
      4) 含技术/构造词（重叠窗口技术、语义分块、梯度下降…）→ 否；
      5) 又短又只出现一两次 → 偏术语/实体 → 否。
    """
    if not name or len(name) < 2:
        return False
    if name in _DOMAIN_ALLOW:                             # 公认宽领域优先放行
        return True
    low = name.lower()
    if low in _DOMAIN_NARROW:
        return False
    if any(tok in name or tok in low for tok in _DOMAIN_NARROW):
        return False                                      # 含技术词的具体短语
    # 又短又只出现一两次的词，偏术语 / 实体，不是能容纳多内容的领域
    if len(name) <= 3 and (content or "").count(name) <= 1:
        return False
    return True

def _coarse_main_pos(content):
    """离线兜底的主尺位置：用主题词极性粗判落在人文/社科(低)还是自科/形式(高)。
    只用于「连够宽的领域名都提炼不出、退回主干带」时的落位，不追求精确。"""
    c = content or ""
    human = sum(c.count(k) for k in
                ("人", "心理", "社会", "情绪", "关系", "文化", "历史", "哲学",
                 "组织", "管理", "沟通", "伦理", "艺术", "文学", "叙事", "审美"))
    tech = sum(c.count(k) for k in
               ("数据", "算法", "模型", "函数", "证明", "公式", "代码", "向量",
                "梯度", "系统", "实验", "物理", "化学", "生物", "数学", "计算",
                "神经", "量子", "能量", "细胞", "概率", "矩阵"))
    if human == 0 and tech == 0:
        return 50.0
    return round(20.0 + 60.0 * (tech / (tech + human + 1)), 1)

def _clauses(text):
    parts = [p for p in re.split(r"[，。；、,.;!?！？\n]", text) if p.strip()]
    return parts or [text]

def _clean_terms(text, top_n=None):
    """干净的代表词提取：纯中文实字块 + 纯英文/数字词。

    - 中文连续实字块 ≤8 字整体保留（如「技能管理」「自组织框架」），
      超长块（句子级碎片）退化为块内二元组，避免代表词变成一长串难看句子；
    - 中英混合段（如「agent的调用信号…」）只保留纯英文词部分；
    - 丢弃标点、虚字、纯数字。
    """
    cnt = {}
    for seg in re.split(r"[^\u4e00-\u9fffA-Za-z0-9]+", text or ""):
        if not seg:
            continue
        if _CJK.match(seg[0]):
            buf = ""
            for ch in seg + "\u0000":
                if "\u4e00" <= ch <= "\u9fff" and ch not in _FUNC_CH:
                    buf += ch
                else:
                    if len(buf) >= 2 and buf not in _STOP_TERM:
                        if len(buf) <= 8:
                            cnt[buf] = cnt.get(buf, 0) + 1
                        for i in range(len(buf) - 1):
                            g = buf[i:i + 2]
                            if g not in _STOP_TERM:
                                cnt[g] = cnt.get(g, 0) + 1
                    buf = ""
        elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]*", seg) and len(seg) >= 2:
            cnt[seg.lower()] = cnt.get(seg.lower(), 0) + 1
    ranked = sorted(cnt.items(), key=lambda kv: (-len(kv[0]), -kv[1], kv[0]))
    words = [w for w, _ in ranked]
    return words[:top_n] if top_n else words

def _domain_reps(text, top_n=8):
    """从该领域全部内容里挑高频实义代表词（供动态打分与 LLM 提示用）。"""
    return _clean_terms(text, top_n)


def _domain_label(content, doms):
    """综合判定一条内容的领域标签：优先归入够宽的已有领域，否则退主干带。

    本地模式（无大模型）下基本只会退到主干带 —— 这是保守且正确的：
    没有可靠分类器时，宁可归到宽泛学科，也不乱立技术碎片当领域节点。
    """
    if doms:
        best, best_hit, best_kinds = None, 0, 0
        for d in doms:
            hit = sum(content.count(k) for k in d["reps"])
            kinds = sum(1 for k in d["reps"] if k in content)
            if (hit + kinds * 0.5) > (best_hit + best_kinds * 0.5):
                best, best_hit, best_kinds = d, hit, kinds
        if best and best_hit > 0 and _is_broad_field(best["name"], content):
            conf = round(min(1.0, 0.5 + best_kinds * 0.12), 3)
            return best["name"], best["center"], conf
    # 提炼不出够宽的领域 → 退回主干学科带（按内容极性落位）
    bb = backbone_of(_coarse_main_pos(content))
    return bb["name"], bb["center"], 0.5

def list_domains():
    """内容驱动的领域聚合：从条目+读数实时算出「当前库实际存在的领域」。

    领域不是预设的 —— 内容进来它出现，内容删光它消失；
    center（成员主尺位置均值）、典型严密度（成员游标中位数）、代表词全部由内容决定。
    """
    con = connect()
    rows = con.execute("""
        SELECT i.id, i.content,
               m.label AS band, m.value AS pos, v.value AS vern
        FROM items i
        JOIN readings m ON m.item_id = i.id AND m.scale = 'main'
        JOIN readings v ON v.item_id = i.id AND v.scale = 'vernier'
        WHERE m.label IS NOT NULL AND m.label != '' AND m.label != '未分类'
        ORDER BY i.id
    """).fetchall()
    con.close()
    groups = {}
    for r in rows:
        groups.setdefault(r["band"] or "未分类", []).append(r)
    out = []
    for name, gs in groups.items():
        poss = [g["pos"] for g in gs]
        vern = sorted(g["vern"] for g in gs)
        out.append({
            "name": name,
            "count": len(gs),
            "center": round(sum(poss) / len(poss), 1),
            "typical_vernier": round(vern[len(vern) // 2], 1),
            "reps": _domain_reps("\n".join(g["content"] for g in gs)),
        })
    # 主干带优先、并按 schema 的 order 排在天然谱系顺序（人文→社科→自科→形式）；
    # 内容衍生细领域排在其后，按条数降序。保证「先天顺序」在 schema 接口也成立。
    bb_order = {b["name"]: b.get("order", i + 1)
                for i, b in enumerate(BACKBONE_BANDS)}
    out.sort(key=lambda d: (0 if d["name"] in bb_order else 1,
                            bb_order.get(d["name"], 99), -d["count"], d["name"]))
    return out

def measure_main(content):
    """主尺读数：内容驱动的领域归纳，但**只接受够宽的领域名**。

    已有领域按动态代表词打分归入；都不沾边则自创一个领域名 —— 因文而变。
    若提炼不出够宽的领域（内容只聊某项具体技术 / 实体），则退回到主干学科带，
    把具体技术留给标签，不让它切碎图谱。
    """
    doms = list_domains()
    return _domain_label(content, doms)

def consolidate_domains(merge_jaccard=0.5):
    """知识库自我完善：把"长歪了的"细领域并回正确的上位领域。

    内容变多后，两条本应同属一个领域的笔记，可能各自被归成了两个名字不同、
    但代表词高度重叠的细领域。这里把它们合并成较大的那个，较小的名字并入
    其标签（保留信息，不丢），避免图谱被近义碎片切碎。主干学科带不参与合并。
    """
    backbone_names = {b["name"] for b in BACKBONE_BANDS}
    doms = [d for d in list_domains() if d["name"] not in backbone_names]
    changed = {}                                   # old_name -> new_name
    for i in range(len(doms)):
        for j in range(i + 1, len(doms)):
            a, b = doms[i], doms[j]
            if a["name"] in changed or b["name"] in changed:
                continue
            ra, rb = set(a["reps"]), set(b["reps"])
            if not ra or not rb:
                continue
            jac = len(ra & rb) / len(ra | rb)
            if jac >= merge_jaccard:
                keep, drop = (a, b) if a["count"] >= b["count"] else (b, a)
                changed[drop["name"]] = keep["name"]
    if changed:
        con = connect()
        for old, new in changed.items():
            con.execute("UPDATE readings SET label=? WHERE scale='main' AND label=?",
                        (new, old))
            rows = con.execute(
                "SELECT id, tags FROM items WHERE id IN "
                "(SELECT item_id FROM readings WHERE scale='main' AND label=?)",
                (new,)).fetchall()
            for r in rows:
                tg = _tag_set(r["tags"])
                if old not in tg:
                    tg.add(old)
                    con.execute("UPDATE items SET tags=? WHERE id=?",
                                (",".join(sorted(tg)), r["id"]))
        con.commit()
        con.close()
    return {"merged": [{"kept": v, "dropped": k} for k, v in changed.items()],
            "count": len(changed)}

def measure_vernier(content):
    """
    游标读数：抽象逻辑演绎深度（纯论证句法，无领域词）。
    用指数饱和而非硬截断，避免读数堆在 0/100 两极 —— 连续谱是卡尺的前提。
    """
    cl = _clauses(content)
    hits = sum(content.count(m) for m in LOGIC_MARKERS)
    kinds = sum(1 for m in LOGIC_MARKERS if m in content)
    quant = sum(1 for q in QUANTIFIERS if q in content)
    density = hits / max(1, len(cl))                 # 论证连接密度（无上限）
    variety = kinds / 8.0                            # 论证链条丰富度
    formality = quant / 5.0                          # 量化/模态骨架
    signal = 0.55 * density + 0.30 * variety + 0.15 * formality
    depth = 6.0 + 94.0 * (1.0 - math.exp(-1.3 * signal))   # 平滑饱和
    conf = round(min(1.0, (kinds + quant) / 5.0), 3)
    return round(max(0.0, min(100.0, depth)), 1), conf

def measure_pair(content, mode):
    """按模式取两尺读数。llm 模式下两路输入互补切分，彼此看不到对方的信息。

    熔断中或模型调用失败一律退回本地启发式，绝不抛错阻塞主流程——这是
    「保存不被慢接口拖住」的兜底：分类路径永远有本地结果可用。
    """
    if mode == "llm" and LLM_OK:
        if _llm.breaker_state()["open"]:
            pass                                       # 熔断中：直接走启发式
        else:
            try:
                m, v = _llm.measure_pair(content, list_domains())
                band = (m.get("band") or "").strip()
                # 模型若仍吐出「重叠窗口 / rag」这类窄义词，拒绝并退回到
                # 本地把关的归类（要么归入够宽的已有领域，要么回主干带）。
                if band and _is_broad_field(band, content):
                    return (
                        (band, m["pos"], m["conf"], LLM_MAIN_PROVIDER, m.get("reason", "")),
                        (v["depth"], v["conf"], LLM_VERNIER_PROVIDER, v.get("reason", "")),
                    )
                # 否则按本地规则重算（覆盖 measure_main 里的 LLM 分支已跳过）
            except Exception:                          # noqa: BLE001
                pass                                   # 模型不可用：退回启发式
    band_name, pos, mconf = measure_main(content)
    depth, vconf = measure_vernier(content)
    return ((band_name, pos, mconf, MAIN_PROVIDER, ""),
            (depth, vconf, VERNIER_PROVIDER, ""))

def vernier_of(content, mode):
    """闭环的锚：每轮回扣原文重算游标。llm 模式走确定性缓存，不重复计费。"""
    if mode == "llm" and LLM_OK:
        return _llm.measure_vernier_llm(content)["depth"]
    return measure_vernier(content)[0]

def band_of(pos):
    """按主尺位置找最接近的领域（动态：领域的中心=成员位置均值，随内容漂移）。"""
    doms = list_domains()
    if not doms:
        return {"name": "未分类", "center": 50.0, "typical_vernier": 45.0,
                "count": 0, "reps": []}
    return min(doms, key=lambda d: abs(d["center"] - pos))


def canonical_band(pos):
    """按 SCHEMA 主尺固定中心把位置映射到 4 个规范领域带之一（人文/社会科学/自然科学/形式科学）。
    独立于 list_domains() 的动态聚类——后者会被旧数据里被污染的域名（如『技能管理』）带偏，
    而这里只认卡尺实测位置，保证文章归档与 KB 主尺定位一一对应。"""
    if pos is None:
        return "未分类"
    bands = SCHEMA["scales"]["main"]["bands"]
    best = min(bands, key=lambda b: abs(b["center"] - pos))
    return best["name"]

def best_band_for(depth):
    """按游标读数找最匹配的领域（动态：典型严密度=成员中位数，随内容变化）。"""
    doms = list_domains()
    if not doms:
        return {"name": "未分类", "center": 50.0, "typical_vernier": 45.0}
    return min(doms, key=lambda d: abs(d["typical_vernier"] - depth))

