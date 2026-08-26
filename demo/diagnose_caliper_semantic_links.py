# -*- coding: utf-8 -*-
"""
lantern-caliper 语义相似链接诊断驱动（读库·零写入）

把每条 provenance='semantic' 的软链当成诊断 Unit，用「当前 embeddings 重算余弦」
作外部锚点跑闭环：
  observe  : 取两端当前向量，重算余弦 sim_now（跨维则无外部锚）
  evaluate : 对比存储分 sim_stored（取自 evidence），给出 verdict
  verdict  :
    ok               同维 + sim_now >= 0.62             —— 仍成立
    stale_valid      同维 + sim_now >= 0.62 但 |drift| > 0.10 —— 成立但显示值陈旧
    false_positive   同维 + sim_now <  0.62             —— 现已不成立（误导图谱）
    cross_dim        两端维度不一致 → 无外部锚，基准失效 —— 应移除
    orphan           任一端点已不存在

阈值取 discover_semantic_links 的 0.62（真实 embedding 在线时）。
"""
import sqlite3, json, math, re, sys
from collections import Counter

DB = r"D:/测试/lantern-caliper/lantern.db"
THRESHOLD = 0.62

def parse_vec(v):
    if v is None: return None
    if isinstance(v, str):
        try: return [float(x) for x in json.loads(v)]
        except: return None
    if isinstance(v, bytes):
        try: return [float(x) for x in json.loads(v.decode('utf-8', 'ignore'))]
        except: return None
    return None

def cos(a, b):
    if a is None or b is None or len(a) != len(b) or not a:
        return None
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)) or 1.0
    nb = math.sqrt(sum(y*y for y in b)) or 1.0
    return dot/(na*nb)

def parse_score(ev):
    if not ev: return None
    m = re.search(r"(\d+\.\d+)", str(ev))
    return float(m.group(1)) if m else None

def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    emb = {}
    for item_id, vec in con.execute("SELECT item_id, vec FROM embeddings"):
        v = parse_vec(vec)
        if v: emb[item_id] = v
    item_ids = {r["id"] for r in con.execute("SELECT id FROM items")}
    dim_dist = Counter(len(v) for v in emb.values())
    links = con.execute(
        "SELECT src_item_id, dst_item_id, evidence, confirmed, provenance "
        "FROM links WHERE provenance='semantic' ORDER BY src_item_id, dst_item_id"
    ).fetchall()
    con.close()

    units = []
    for f, t, ev, conf, prov in links:
        ef, et = emb.get(f), emb.get(t)
        sim_stored = parse_score(ev)
        if f not in item_ids or t not in item_ids:
            verdict = "orphan"
            sim_now, dimf, dimt = None, "-", "-"
        elif ef is None or et is None:
            verdict = "no_vector"
            sim_now, dimf, dimt = None, len(ef) if ef else "-", len(et) if et else "-"
        elif len(ef) != len(et):
            verdict = "cross_dim"
            sim_now, dimf, dimt = None, len(ef), len(et)
        else:
            sim_now = cos(ef, et)
            dimf, dimt = len(ef), len(et)
            if sim_now is None:
                verdict = "cross_dim"
            elif sim_now < THRESHOLD:
                verdict = "false_positive"
            elif abs((sim_now or 0) - (sim_stored or 0)) > 0.10:
                verdict = "stale_valid"
            else:
                verdict = "ok"
        units.append({
            "src": f, "dst": t, "stored": sim_stored, "now": sim_now,
            "dim_f": dimf, "dim_t": dimt, "verdict": verdict,
            "confirmed": conf, "evidence": ev,
        })

    vc = Counter(u["verdict"] for u in units)
    print("=== embeddings 维度分布 ===")
    print(dict(dim_dist), "  item向量覆盖:", len(emb), "/ 18")
    print("\n=== 语义链接 verdict 分布 (n=%d, threshold=%.2f) ===" % (len(units), THRESHOLD))
    for k in ["ok", "stale_valid", "false_positive", "cross_dim", "orphan", "no_vector"]:
        if vc.get(k): print(f"  {k:14s}: {vc[k]}")
    print("\n=== 逐条 ===")
    for u in units:
        now_s = f"{u['now']:.4f}" if isinstance(u['now'], float) else str(u['now'])
        print(f"  {u['src']:>3}->{u['dst']:<3} | stored={u['stored']} now={now_s:>9} "
              f"| dim {u['dim_f']}/{u['dim_t']} | {u['verdict']} | {u['evidence']}")

    # 机器可读摘要，供报告引用
    summary = {"threshold": THRESHOLD, "dim_dist": dict(dim_dist),
               "total": len(units), "verdicts": dict(vc), "units": units}
    with open(r"D:/测试/lantern-caliper/demo/_diag_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n[DONE] summary -> demo/_diag_summary.json")

if __name__ == "__main__":
    main()
