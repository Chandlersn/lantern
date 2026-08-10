#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
确定性回归：验证 lantern_method.py 的绩点生命周期与 Node 版 test_lifecycle_v2.cjs
逐条对齐。所有状态写入临时目录，不污染真实 KB 轴库。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lantern_method as M

# —— 重定向状态文件到临时目录 ——
TMP = tempfile.mkdtemp(prefix="lantern_verify_")
M.SCORES_FILE = os.path.join(TMP, "scores.json")
M.META_FILE = os.path.join(TMP, "meta.json")
M.HISTORY_FILE = os.path.join(TMP, "history.json")
M.CALIB_FILE = os.path.join(TMP, "calib.json")

TK = "测试|回归"


def set_axis(score, meta):
    lib = M.AxisLibrary()
    lib.scores[TK] = score
    lib.meta[TK] = dict(meta)
    lib.save()


pass_n = 0
fail_n = 0

def ok(name, cond, extra=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ✓", name)
    else:
        fail_n += 1
        print("  ✗ FAIL", name, extra)


# 路径1：活跃轴长期未选用 → 衰减跌破 0.4 进入休眠
print("--- 路径1：活跃轴长期未选用 → 衰减跌破 0.4 休眠 ---")
set_axis(0.8, {"used": 1, "dormant": False, "merits": 0, "lastUsed": None, "vital": 1})
lib = M.AxisLibrary()
for _ in range(30):
    lib.update_scores(
        {"axes": [{"domain": "社会", "dimension": "矛盾", "name": "x",
                   "projection": "足够长足够长足够长足够长", "orthogonal": True}]},
        {"high_coupling": []}, {"snapshot": False})
s = M.AxisLibrary().scores
st = M.AxisLibrary().get_axis_state("测试", "回归")
ok("TK 分数已跌破 0.4 (实测 %s)" % s[TK], s[TK] < M.SCORE_MIN)
ok("TK 已休眠(dormant=true)", st["dormant"] is True)
ok("TK vital=2(休眠态)", st["vital"] == 2)

# 路径2：休眠轴被重新选用 → 功绩累计达 REVIVE_MERITS 自动复活
print("--- 路径2：休眠轴被重新选用 → 功绩累计自动复活 ---")
set_axis(0.35, {"used": 2, "dormant": True, "merits": 0, "lastUsed": None, "vital": 2})
proj = "足够长足够长足够长足够长很长很长很长很长很长很长很长"
lib = M.AxisLibrary()
lib.update_scores({"axes": [{"domain": "测试", "dimension": "回归", "name": "重生轴",
                             "projection": proj, "orthogonal": True}]},
                  {"high_coupling": []}, {"snapshot": False})
st = M.AxisLibrary().get_axis_state("测试", "回归")
ok("重选后 dormant 已清=false", st["dormant"] is False)
ok("一次重选功绩=1", st["merits"] == 1 and st["vital"] == 1)
for _ in range(2):
    l2 = M.AxisLibrary()
    l2.update_scores({"axes": [{"domain": "测试", "dimension": "回归", "name": "重生轴",
                                "projection": proj, "orthogonal": True}]},
                     {"high_coupling": []}, {"snapshot": False})
st = M.AxisLibrary().get_axis_state("测试", "回归")
ok("功绩达 %d 自动复活" % M.REVIVE_MERITS, st["dormant"] is False and st["vital"] == 1 and st["merits"] >= M.REVIVE_MERITS)

# 路径3：手动 👍 复活（feedback up）
print("--- 路径3：手动 👍 复活 ---")
set_axis(0.3, {"used": 2, "dormant": True, "merits": 0, "lastUsed": None, "vital": 2})
lib = M.AxisLibrary()
for _ in range(3):
    lib.feedback_axis("测试", "回归", "up")
st = M.AxisLibrary().get_axis_state("测试", "回归")
ok("手动👍×3 复活(dormant=false)", st["dormant"] is False)

# 路径4：归档线（低于 SCORE_ARCHIVE 且未选用 → vital=3 归档）
print("--- 路径4：归档线 ---")
set_axis(M.SCORE_ARCHIVE - 0.05, {"used": 1, "dormant": False, "merits": 0, "lastUsed": None, "vital": 1})
lib = M.AxisLibrary()
lib.update_scores(
    {"axes": [{"domain": "社会", "dimension": "矛盾", "name": "x",
               "projection": "足够长足够长足够长足够长", "orthogonal": True}]},
    {"high_coupling": []}, {"snapshot": False})
st = M.AxisLibrary().get_axis_state("测试", "回归")
ok("低于归档线 → vital=3 归档", st["vital"] == 3 and st["dormant"] is True)

# 路径5：高耦合加权扣分命中（score=8）
print("--- 路径5：高耦合加权扣分 ---")
set_axis(0.8, {"used": 1, "dormant": False, "merits": 0, "lastUsed": None, "vital": 1})
lib = M.AxisLibrary()
lib.update_scores(
    {"axes": []},
    {"high_coupling": [["测试|回归", "社会|矛盾"]],
     "pairwise": [{"a": "测试|回归", "b": "社会|矛盾", "score": 8, "confidence": 0.9}]},
    {"snapshot": False})
s = M.AxisLibrary().scores
ok("高耦合 score=8 加权扣分命中(TK≈0.585，实测 %s)" % s[TK], abs(s[TK] - 0.585) < 1e-9)

# 路径6：低置信(<0.6)高耦合只警告不扣分
print("--- 路径6：低置信只警告不扣分 ---")
set_axis(0.8, {"used": 1, "dormant": False, "merits": 0, "lastUsed": None, "vital": 1})
lib = M.AxisLibrary()
lib.update_scores(
    {"axes": []},
    {"high_coupling": [["测试|回归", "社会|矛盾"]],
     "pairwise": [{"a": "测试|回归", "b": "社会|矛盾", "score": 9, "confidence": 0.4}]},
    {"snapshot": False})
s = M.AxisLibrary().scores
ok("低置信不扣分(仅衰减，TK≈0.785，实测 %s)" % s[TK], abs(s[TK] - 0.785) < 1e-9)

# 路径7：表现良好轴可升入优选区(≥0.7)
print("--- 路径7：良好轴升入优选区 ---")
set_axis(0.6, {"used": 0, "dormant": False, "merits": 0, "lastUsed": None, "vital": 0})
lib = M.AxisLibrary()
lib.update_scores(
    {"axes": [{"domain": "测试", "dimension": "回归", "name": "优质轴",
               "projection": "足够长足够长足够长足够长很长很长很长很长很长很长很长", "orthogonal": True}]},
    {"high_coupling": [], "pairwise": []}, {"snapshot": False})
s = M.AxisLibrary().scores
ok("一次良好选用 0.6→0.72 升入优选区(实测 %s)" % s[TK], s[TK] >= 0.7)

# 路径8：快照去重（同概念 30 分钟内合并为一点）
print("--- 路径8：快照去重 ---")
lib = M.AxisLibrary()
gen_good = {"axes": [{"domain": "测试", "dimension": "回归", "name": "优质轴",
                      "projection": "足够长足够长足够长足够长很长很长很长很长很长很长很长", "orthogonal": True}]}
lib.update_scores(gen_good, {"high_coupling": [], "pairwise": []}, {"snapshot": True, "concept": "去重测试概念"})
lib.update_scores(gen_good, {"high_coupling": [], "pairwise": []}, {"snapshot": True, "concept": "去重测试概念"})
hist = M.AxisLibrary().history
same = [p for p in hist if p.get("concept") == "去重测试概念"]
ok("同概念 30 分钟内只留 1 个快照(实测 %d)" % len(same), len(same) == 1)

print("\n结果： %d 通过 / %d 失败" % (pass_n, fail_n))
sys.exit(1 if fail_n else 0)
