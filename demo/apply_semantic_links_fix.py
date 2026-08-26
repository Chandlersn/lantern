# -*- coding: utf-8 -*-
"""数据修复 A（写库）：在已备份前提下，统一 embedding 维度并重建自洽的语义软链。
步骤：① rebuild_embeddings(force=True) 统一 512 维（内置 prune 清陈旧链）
      ② DELETE 全部 provenance='semantic'（彻底清旧，保证干净出发点）
      ③ refresh_soft_links() 在统一维度下重算
      ④ 复跑 verdict 闭环，确认 0 cross_dim / 0 false_positive / 0 orphan。
只读诊断部分复用诊断驱动思路；本脚本是写回步骤，运行前须已备份 lantern.db。"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lantern_caliper import search, links, connect

TH = 0.62

print("=== 1) rebuild_embeddings(force=True) ===")
rb = search.rebuild_embeddings(force=True)
print("  ->", rb)

print("=== 2) DELETE 全部 semantic 软链（干净出发点）===")
con = connect()
n_before = con.execute("SELECT count(*) FROM links WHERE provenance='semantic'").fetchone()[0]
con.execute("DELETE FROM links WHERE provenance='semantic'")
con.commit()
n_after = con.execute("SELECT count(*) FROM links WHERE provenance='semantic'").fetchone()[0]
con.close()
print(f"  -> 删除前 {n_before} 条，删除后 {n_after} 条")

print("=== 3) refresh_soft_links() 统一维度下重算 ===")
rf = links.refresh_soft_links()
print("  ->", {k: rf[k] for k in ("ok", "pruned_semantic", "written",
                                  "cooccur_written", "semantic_written", "bridge_written")})

def verdicts():
    con = connect()
    rows = con.execute("SELECT src_item_id,dst_item_id FROM links WHERE provenance='semantic'").fetchall()
    vecs = {r["item_id"]: json.loads(r["vec"])
            for r in con.execute("SELECT item_id,vec FROM embeddings")}
    con.close()
    dist = {"ok": 0, "false_positive": 0, "cross_dim": 0, "orphan": 0}
    for l in rows:
        s, d = l["src_item_id"], l["dst_item_id"]
        vs, vd = vecs.get(s), vecs.get(d)
        if vs is None or vd is None:
            dist["orphan"] += 1; continue
        if len(vs) != len(vd):
            dist["cross_dim"] += 1; continue
        dot = sum(a * b for a, b in zip(vs, vd))
        na = math.sqrt(sum(x * x for x in vs)) or 1.0
        nb = math.sqrt(sum(y * y for y in vd)) or 1.0
        dist["ok" if dot / (na * nb) >= TH else "false_positive"] += 1
    return dist, len(rows)

print("=== 4) 复验 verdict 闭环 ===")
from lantern_caliper import signal_integrity
print("  signal_integrity:", signal_integrity(use_cache=False).get("status"))
dist, total = verdicts()
print(f"  语义链接总数 = {total}")
print(f"  verdict 分布 = {dist}")
bad = dist["cross_dim"] + dist["false_positive"] + dist["orphan"]
print("  RESULT:", "PASS ✅ (0 无效边)" if bad == 0 else f"FAIL ❌ (仍有 {bad} 条无效)")
print("APPLY_DONE")
