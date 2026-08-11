# -*- coding: utf-8 -*-
"""两尺独立性守卫与信号可信度监测；退化解自动拉闸挂起语义链。"""

import json
import math
import time


def _indep_cfg():
    rg = (SCHEMA.get("independence_constraint", {})
          .get("runtime_guard", {}))
    return (float(rg.get("block_at", 0.6)),
            int(rg.get("block_min_samples", 12)))

def independence(use_cache=True):
    """运行时守卫：两尺读数若高度相关，偏移即退化为噪声，闭环破产。

    返回字典含 blocked / same_underlying_source / note，供写库入口与健康报告共用。
    """
    global _indep_cache
    now = time.time()
    if use_cache and _indep_cache["v"] is not None and now - _indep_cache["t"] < _INDEP_TTL:
        return _indep_cache["v"]

    con = connect()
    rows = con.execute(
        "SELECT m.value AS a, v.value AS b, m.signal_family AS fa, "
        "v.signal_family AS fb, m.provider AS pa, v.provider AS pb FROM readings m "
        "JOIN readings v ON m.item_id=v.item_id "
        "WHERE m.scale='main' AND v.scale='vernier'").fetchall()
    mode = get_mode(con)
    con.close()
    n = len(rows)
    fams = ([rows[0]["fa"], rows[0]["fb"]] if n else
            [MAIN_PROVIDER["signal_family"], VERNIER_PROVIDER["signal_family"]])
    provs = [rows[0]["pa"], rows[0]["pb"]] if n else \
            [MAIN_PROVIDER["id"], VERNIER_PROVIDER["id"]]
    block_at, min_samples = _indep_cfg()

    if n < 3:
        out = {"n": n, "r": None, "status": "insufficient",
               "msg": "样本不足，无法检验", "families": fams,
               "providers": provs, "mode": mode, "blocked": False,
               "block_at": block_at, "block_min_samples": min_samples,
               "same_underlying_source": None,
               "note": "两尺当前共用同一底层信号源（llm 同一模型 / 启发式同一本地函数），"
                       "signal_family 仅为语义标签；独立性只能靠实证 r 监测。"}
        _indep_cache = {"t": now, "v": out}
        return out

    xs = [r["a"] for r in rows]
    ys = [r["b"] for r in rows]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    r = 0.0 if vx == 0 or vy == 0 else cov / (vx * vy)
    a = abs(r)

    # —— 同源脆弱性：两尺是否真的来自不同底层信号源？——
    pa, pb = provs
    same = None
    if pa and pb:
        if pa.startswith("llm:") and pb.startswith("llm:"):
            same = (pa.split("/", 1)[0] == pb.split("/", 1)[0])   # 同一模型
        elif pa == MAIN_PROVIDER["id"] and pb == VERNIER_PROVIDER["id"]:
            same = True                                           # 都是本地启发式函数
    if same is None:
        same = (pa == pb)

    if a < 0.6:
        status, msg = "healthy", "两尺独立性良好，偏移携带真实信息。"
    elif a < 0.85:
        status, msg = "warn", "两尺出现相关，偏移信息量下降，建议检查 provider 是否共享信号。"
    else:
        status, msg = "fail", "两尺坍缩！偏移已退化为噪声，必须更换其中一路 provider。"

    blocked = (a >= block_at) and (n >= min_samples)
    out = {"n": n, "r": round(r, 3), "status": status, "msg": msg,
           "families": fams, "providers": provs, "mode": mode,
           "blocked": blocked, "block_at": block_at,
           "block_min_samples": min_samples,
           "same_underlying_source": bool(same),
           "note": ("⚠ 两尺当前共用同一底层信号源（same_underlying_source=true），"
                    "signal_family 仅为语义标签；独立性是实证量而非结构保证，"
                    "r 升高即意味着偏移正在失去意义。") if same else
                   "两尺来自不同底层信号源，独立性有结构保障。"}
    _indep_cache = {"t": now, "v": out}
    return out

def _guard_allows_write(force=False):
    """写库守卫闸门。force=True 绕过（供 remeasure_all / init 复位用）。"""
    if force:
        return True, None
    ind = independence()
    if ind.get("blocked"):
        return False, ind
    return True, ind

def _invalidate_indep_cache():
    global _indep_cache
    _indep_cache = {"t": 0.0, "v": None}

def signal_integrity(use_cache=True):
    """信号可信度守卫：用 Lantern 实证统计检测 embedding 是否退化。

    融合 Karpathy Lint 的"信号可信度"检查。退化向量（哈希/对话兜底）的特征是
    "把不相关的东西也判成很像"——典型指纹：跨领域（不同主尺带）的条目对却出现
    极高余弦相似度（>0.85），而真实语义嵌入下跨主题相似度应明显更低。
    全局均值会被这种"局部假簇"稀释（本库 mean 仅 0.145，但 73↔70/71/72 达 0.94），
    所以判据不只看均值，更看"跨带高相似对"这一退化指纹。
    判据（任一成立即 degraded，语义链自动挂起）：
      ① 全局均值偏高（mean>0.75）——所有文档彼此都"像"；
      ② 近重复率偏高（near>0.3）——大量 sim>0.9；
      ③ 跨带高相似对 ≥3 —— 跨领域却被判极相似（本库 64 维兜底向量的真实指纹）。
    """
    global _signal_cache
    now = time.time()
    if use_cache and _signal_cache["v"] is not None and now - _signal_cache["t"] < _SIGNAL_TTL:
        return _signal_cache["v"]

    con = connect()
    rows = con.execute("SELECT item_id,vec FROM embeddings").fetchall()
    mp = {r["item_id"]: r["value"] for r in con.execute(
        "SELECT item_id,value FROM readings WHERE scale='main'")}
    band_map = {i: (canonical_band(v) if v is not None else "") for i, v in mp.items()}
    con.close()
    n = len(rows)
    if n < 3:
        out = {"n": n, "pairs": 0, "mean_sim": None, "std_sim": None,
               "near_dup_rate": None, "cross_band_highsim": 0,
               "status": "insufficient", "msg": "样本不足，无法检验信号质量", "blocked": False}
        _signal_cache = {"t": now, "v": out}
        return out

    # 按维度分组，只比同维向量（本地哈希 vs 真实 embedding 不混比）
    groups = {}
    for r in rows:
        try:
            v = json.loads(r["vec"]) if isinstance(r["vec"], str) else r["vec"]
        except Exception:
            continue
        groups.setdefault(len(v), []).append((r["item_id"], v))
    sims, cross_high, cross_total = [], 0, 0
    for vs in groups.values():
        m = len(vs)
        for ai in range(m):
            for bi in range(ai + 1, m):
                ida, va = vs[ai]
                idb, vb = vs[bi]
                dot = sum(x * y for x, y in zip(va, vb))
                na = math.sqrt(sum(x * x for x in va)) or 1.0
                nb = math.sqrt(sum(y * y for y in vb)) or 1.0
                s = dot / (na * nb)
                sims.append(s)
                ba, bb = band_map.get(ida, ""), band_map.get(idb, "")
                if ba != bb:                      # 跨主尺带（含缺失视为不同）
                    cross_total += 1
                    if s > 0.85:
                        cross_high += 1
    if not sims:
        out = {"n": n, "pairs": 0, "mean_sim": None, "std_sim": None,
               "near_dup_rate": None, "cross_band_highsim": 0,
               "status": "insufficient", "msg": "无可比向量", "blocked": False}
        _signal_cache = {"t": now, "v": out}
        return out

    mean = sum(sims) / len(sims)
    std = math.sqrt(sum((s - mean) ** 2 for s in sims) / len(sims))
    near = sum(1 for s in sims if s > 0.9) / len(sims)
    cross_rate = (cross_high / cross_total) if cross_total else 0.0
    # 退化判据：① 全局偏高 ② 大量近重复 ③ 跨带高相似指纹（局部假簇）
    if mean > 0.75 or near > 0.3 or cross_high >= 3:
        status, msg = "degraded", ("嵌入退化：检测到 %d 对跨领域条目却呈极高相似"
                                   "（sim>0.85），语义信号失去区分度，语义链已自动挂起。" % cross_high)
        blocked = True
    elif mean > 0.6 or cross_high >= 1:
        status, msg = "warn", "嵌入信号偏弱，存在跨领域高相似，建议核查嵌入来源。"
        blocked = False
    else:
        status, msg = "healthy", "嵌入信号健康，语义区分度良好。"
        blocked = False
    out = {"n": n, "pairs": len(sims), "mean_sim": round(mean, 3),
           "std_sim": round(std, 3), "near_dup_rate": round(near, 3),
           "cross_band_highsim": cross_high,
           "cross_band_highsim_rate": round(cross_rate, 3),
           "status": status, "msg": msg, "blocked": blocked}
    _signal_cache = {"t": now, "v": out}
    return out

def enforce_signal_guard():
    """联动执行：据 signal_integrity 自动挂起语义链生成。

    仅做"挂起"（degraded→set 0），不做"自动恢复"——恢复语义链需先修复嵌入
    （换可信模型并重建向量）再由人工/显式流程置 enabled=1，避免在"接口时好时坏"
    时反复横跳，也尊重用户关于"暂停生成"的拍板。把 Karpathy Lint 的"信号可信度"
    从人眼检查变成 Lantern 引擎自主拉闸（合闸交人工）。
    """
    sig = signal_integrity(use_cache=False)
    if sig["status"] == "degraded" and get_meta("semantic_links_enabled", "0") == "1":
        set_meta("semantic_links_enabled", "0")
        auto_log("signal", "信号可信度守卫：嵌入退化，已自动挂起语义链生成。")
    return sig


