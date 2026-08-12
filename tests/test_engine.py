# -*- coding: utf-8 -*-
"""灯笼引擎核心路径单元测试（纯标准库，零依赖）。

覆盖报告 P0 建议的三处核心路径：
  - lantern_caliper/measure.py  双尺度量（纯函数，不触 DB）
  - lantern_caliper/guard.py    两尺独立性守卫 / 信号可信度监测（临时 DB）
  - lantern_caliper/links.py    硬链解析 / 话题词 / IDF 余弦 / 候选边（纯函数 + 冒烟）

运行：
    python -m unittest tests.test_engine -v
    python tests/test_engine.py          # 直接跑也行
"""
import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import lantern_caliper as store  # noqa: E402


# ======================================================================
# measure.py —— 纯函数（不触 DB），只依赖注入进包的常量与 SCHEMA
# ======================================================================
class TestMeasurePure(unittest.TestCase):

    def test_measure_vernier_bounds(self):
        """游标读数恒在 [0, 100]，置信度在 [0, 1]。"""
        for txt in ("", "一段纯叙事文字。", "因为所以然而并且如果那么", "a" * 500):
            depth, conf = store.measure_vernier(txt)
            self.assertGreaterEqual(depth, 0.0)
            self.assertLessEqual(depth, 100.0)
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 1.0)

    def test_measure_vernier_empty_floor(self):
        """空文本没有任何逻辑信号，落到读数下限 6.0、置信 0。"""
        depth, conf = store.measure_vernier("")
        self.assertEqual(depth, 6.0)
        self.assertEqual(conf, 0.0)

    def test_measure_vernier_monotonic(self):
        """强论证文本应比纯叙事文本游标更深（连续谱成立）。"""
        narrative = "从前有座山，山里有座庙，庙里有个老和尚在讲从前的故事。" * 6
        argument = ("因此该假设成立。因为前提是充分必要条件，所以如果条件满足，"
                    "那么结论必然导出；然而反例表明此推论并不普遍，于是我们进一步"
                    "量化并证明上述关系。") * 4
        d_narr, _ = store.measure_vernier(narrative)
        d_arg, _ = store.measure_vernier(argument)
        self.assertGreater(d_arg, d_narr)

    def test_clean_terms_english(self):
        """英文 / 数字整词保留并转小写；标点被丢弃。"""
        out = store._clean_terms("RAG embedding 模型 123")
        self.assertIsInstance(out, list)
        self.assertIn("rag", out)
        self.assertIn("embedding", out)
        self.assertIn("模型", out)
        # 纯标点应返回空
        self.assertEqual(store._clean_terms("，。；！？"), [])

    def test_is_broad_field(self):
        """够宽领域 vs 技术碎片的判定边界。"""
        self.assertFalse(store._is_broad_field(""))        # 空
        self.assertFalse(store._is_broad_field("a"))        # 单字
        self.assertFalse(store._is_broad_field("rag"))      # 窄词黑名单
        self.assertFalse(store._is_broad_field("rag方案"))   # 含窄词
        self.assertTrue(store._is_broad_field("XYZ长名词组合abc"))  # 默认放行分支

    def test_coarse_main_pos(self):
        """离线极性粗判：技术重→高位，人文重→低位，中性→50。"""
        self.assertGreater(store._coarse_main_pos("算法 模型 公式 证明 函数 数据"), 50)
        self.assertLess(store._coarse_main_pos("心理 社会 文化 历史 哲学"), 50)
        self.assertEqual(store._coarse_main_pos("hello world"), 50.0)

    def test_domain_label_fallback(self):
        """提炼不出够宽领域时退回主干带，置信保底 0.5。"""
        name, center, conf = store._domain_label("算法模型证明", [])
        self.assertIn(name, {b["name"] for b in store.BACKBONE_BANDS})
        self.assertAlmostEqual(center, {b["name"]: b["center"] for b in store.BACKBONE_BANDS}[name])
        self.assertEqual(conf, 0.5)

    def test_canonical_band(self):
        """固定 4 带映射：低→人文，高→形式科学，None→未分类。"""
        self.assertEqual(store.canonical_band(5), "人文")
        self.assertEqual(store.canonical_band(99), "形式科学")
        self.assertEqual(store.canonical_band(None), "未分类")

    def test_backbone_of_clamps(self):
        """越界位置收口到最近主干带（返回字典而非抛错）。"""
        b = store.backbone_of(200)
        self.assertIn("name", b)
        self.assertIn("center", b)
        self.assertIn("range", b)

    def test_clauses(self):
        """分句按中英文标点切分。"""
        self.assertEqual(store._clauses("甲。乙，丙！丁？戊"), ["甲", "乙", "丙", "丁", "戊"])


# ======================================================================
# guard.py —— 守卫逻辑（临时 DB，确定性）
# ======================================================================
class TestGuard(unittest.TestCase):
    TMP = None

    @classmethod
    def setUpClass(cls):
        fd, cls.TMP = tempfile.mkstemp(prefix="lantern_test_", suffix=".db")
        os.close(fd)
        os.remove(cls.TMP)  # 让 init 走 first_run 分支建库
        store.core.DB_PATH = cls.TMP
        store.init(force=True)

    @classmethod
    def tearDownClass(cls):
        for ext in ("", "-wal", "-shm"):
            p = cls.TMP + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _seed(self, rows):
        """rows: list of dict(main, vernier, vec?, band?). 清空后按给定读数重建。"""
        mp, vp = store.MAIN_PROVIDER, store.VERNIER_PROVIDER
        con = store.connect()
        con.executescript(
            "DELETE FROM links; DELETE FROM embeddings; "
            "DELETE FROM readings; DELETE FROM items; DELETE FROM meta;")
        for i, r in enumerate(rows, 1):
            con.execute(
                "INSERT INTO items(id,title,content,created_at) VALUES(?,?,?,?)",
                (i, "T%d" % i, "C%d" % i, 0.0))
            con.execute(
                "INSERT INTO readings(item_id,scale,value,label,confidence,"
                "provider,signal_family,revised,computed_at) VALUES(?,?,?,?,?,?,?,0,?)",
                (i, "main", r["main"], r.get("band"), 1.0,
                 mp["id"], mp["signal_family"], 0.0))
            con.execute(
                "INSERT INTO readings(item_id,scale,value,label,confidence,"
                "provider,signal_family,revised,computed_at) VALUES(?,?,?,?,?,?,?,0,?)",
                (i, "vernier", r["vernier"], None, 1.0,
                 vp["id"], vp["signal_family"], 0.0))
            if "vec" in r:
                con.execute("INSERT INTO embeddings(item_id,vec) VALUES(?,?)",
                            (i, json.dumps(r["vec"])))
        con.commit()
        con.close()

    def test_indep_cfg(self):
        """守卫阈值来自 SCHEMA：block_at=0.6, min_samples=12。"""
        block_at, min_samples = store._indep_cfg()
        self.assertEqual(block_at, 0.6)
        self.assertEqual(min_samples, 12)

    def test_independence_insufficient(self):
        """样本 < 3 时返回 insufficient 且不拦截。"""
        self._seed([{"main": 10, "vernier": 20}, {"main": 30, "vernier": 60}])
        ind = store.independence(use_cache=False)
        self.assertEqual(ind["status"], "insufficient")
        self.assertFalse(ind["blocked"])
        self.assertEqual(ind["n"], 2)

    def test_independence_collapsed_blocks(self):
        """两尺完全线性相关（n≥12）→ 坍缩、真拉闸拦截写入。"""
        rows = [{"main": 10 + i * 5, "vernier": (10 + i * 5) * 2}
                for i in range(14)]
        self._seed(rows)
        ind = store.independence(use_cache=False)
        self.assertEqual(ind["n"], 14)
        self.assertAlmostEqual(abs(ind["r"]), 1.0, places=2)
        self.assertTrue(ind["blocked"])
        self.assertEqual(ind["status"], "fail")

    def test_independence_uncorrelated_ok(self):
        """两尺正交（n≥12）→ 健康、不拦截。"""
        rows = [{"main": i * 7, "vernier": (i % 2) * 100} for i in range(14)]
        self._seed(rows)
        ind = store.independence(use_cache=False)
        self.assertFalse(ind["blocked"])
        self.assertIn(ind["status"], ("healthy", "warn"))

    def test_signal_integrity_insufficient(self):
        """向量 < 3 时返回 insufficient。"""
        self._seed([{"main": 12.5, "vernier": 40, "vec": [1, 0, 0, 0]},
                    {"main": 37.5, "vernier": 50, "vec": [0, 1, 0, 0]}])
        sig = store.signal_integrity(use_cache=False)
        self.assertEqual(sig["status"], "insufficient")
        self.assertFalse(sig["blocked"])

    def test_signal_integrity_healthy(self):
        """正交向量、跨带分布 → 健康、语义链不挂起。"""
        self._seed([
            {"main": 12.5, "vernier": 40, "vec": [1, 0, 0, 0]},   # 人文
            {"main": 37.5, "vernier": 50, "vec": [0, 1, 0, 0]},   # 社科
            {"main": 62.5, "vernier": 60, "vec": [0, 0, 1, 0]},   # 自科
        ])
        sig = store.signal_integrity(use_cache=False)
        self.assertEqual(sig["status"], "healthy")
        self.assertFalse(sig["blocked"])

    def test_signal_integrity_degraded(self):
        """≥3 对跨带却极高相似（退化指纹）→ 自动挂起语义链。"""
        self._seed([
            {"main": 12.5, "vernier": 40, "vec": [1, 1, 1, 1]},   # 人文
            {"main": 37.5, "vernier": 50, "vec": [1, 1, 1, 1]},   # 社科
            {"main": 62.5, "vernier": 60, "vec": [1, 1, 1, 1]},   # 自科
            {"main": 87.5, "vernier": 70, "vec": [1, 1, 1, 1]},   # 形式科学
        ])
        sig = store.signal_integrity(use_cache=False)
        self.assertGreaterEqual(sig["cross_band_highsim"], 3)
        self.assertEqual(sig["status"], "degraded")
        self.assertTrue(sig["blocked"])


# ======================================================================
# links.py —— 纯函数 + 候选边冒烟
# ======================================================================
class TestLinksPure(unittest.TestCase):

    def test_parse_links(self):
        """解析 [[标题]] 硬链标记。"""
        self.assertEqual(store.parse_links("见 [[A]] 与 [[B]] 结尾"), ["A", "B"])
        self.assertEqual(store.parse_links("没有任何互链"), [])
        self.assertEqual(store.parse_links(""), [])

    def test_tag_set(self):
        """tags 是逗号串，不能裸 set() 拆成单字。"""
        self.assertEqual(store._tag_set(None), set())
        self.assertEqual(store._tag_set(""), set())
        self.assertEqual(store._tag_set("a,b,c"), {"a", "b", "c"})
        self.assertEqual(store._tag_set(["x", "y"]), {"x", "y"})

    def test_topic_segments(self):
        """整词抽取：连续的 ≥2 字实义块被保留。"""
        out = store._topic_segments("机器学习 与 深度学习 关系")
        self.assertIn("机器学习", out)
        self.assertIn("深度学习", out)

    def test_about(self):
        """是否『真的在讲』该词：标题命中 / 正文≥2 次 / 长词单次。"""
        self.assertTrue(store._about("模型", "讲模型讲模型", "浅谈模型"))   # 标题命中
        self.assertTrue(store._about("动量", "动量出现两次动量", "主题"))     # 正文≥2
        self.assertFalse(store._about("动量", "只提一次动量", "主题"))        # 短词单次

    def test_idf_cos(self):
        """IDF 加权余弦：相同→1，正交→0，空集→0。"""
        df = {"a": 1, "b": 1}
        self.assertAlmostEqual(store._idf_cos({"a", "b"}, {"a", "b"}, df, 2), 1.0)
        self.assertEqual(store._idf_cos({"a"}, {"b"}, df, 2), 0.0)
        self.assertEqual(store._idf_cos(set(), {"a"}, df, 2), 0.0)

    def test_suggest_links_smoke(self):
        """候选边在种子库上结构正确、不崩溃。"""
        # 复用 TestGuard 已建好的临时库（同进程）；若单独跑则自建
        if not os.path.exists(store.core.DB_PATH):
            store.init(force=True)
        res = store.suggest_links(persist=False)
        self.assertIsInstance(res, dict)
        self.assertIn("suggestions", res)
        self.assertIn("item_count", res)
        self.assertIsInstance(res["suggestions"], list)


# ======================================================================
# 并发写入串行化复核（报告 P0 第 2 条）
# 验证：多线程各自 connect() 并发写 items 不出现 "database is locked"；
#       多个 refresh_soft_links（共用 _discovery_lock）并发也串行化不卡死。
# 全部跑在临时库上，绝不触碰仓库真实的 lantern.db。
# ======================================================================
class TestConcurrency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lantern_conc_")
        self.old_db = store.core.DB_PATH
        store.core.DB_PATH = os.path.join(self.tmp, "lantern.db")
        store.init(force=True)
        # 清空 init 可能种入的种子（first_run 时），让基准严格可控；
        # 同时清掉孤立 readings，避免残留读数干扰计数。
        con = store.connect()
        con.execute("DELETE FROM items")
        con.execute("DELETE FROM readings")
        con.commit()
        # 预置 20 条基础数据，给共现发现提供素材（裸录入，刻意不写 readings，
        # 顺带覆盖 _row_to_item 对缺失读数的容错路径）
        for i in range(20):
            con.execute(
                "INSERT INTO items(title,content,created_at,alias) VALUES(?,?,?,?)",
                (f"base{i}", f"关于 算法 与 模型 的第 {i} 段讨论", time.time(), f"base{i}"))
        con.commit(); con.close()

    def tearDown(self):
        store.core.DB_PATH = self.old_db

    def _insert_batch(self, tid, n, errors):
        """一个线程：独立 connect() 后插入 n 条不冲突的新条目。"""
        try:
            con = store.connect()
            for i in range(n):
                con.execute(
                    "INSERT INTO items(title,content,created_at,alias) VALUES(?,?,?,?)",
                    (f"t{tid}_{i}", f"线程 {tid} 第 {i} 条 关于 逻辑 与 推理 的 内容",
                     time.time(), f"t{tid}_{i}"))
            con.commit(); con.close()
        except Exception as e:
            errors.append((tid, repr(e)))

    def test_concurrent_item_writes(self):
        """8 个线程并发各插入 5 条 -> 共 40 条，无锁死、总数精确。"""
        errors = []
        threads = [threading.Thread(target=self._insert_batch, args=(t, 5, errors))
                   for t in range(8)]
        for th in threads: th.start()
        for th in threads: th.join()
        self.assertEqual(errors, [], f"并发写 items 异常: {errors}")
        con = store.connect()
        n = con.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        con.close()
        self.assertEqual(n, 20 + 8 * 5)

    def test_concurrent_refresh_serialized(self):
        """4 个线程同时 refresh_soft_links（共用 _discovery_lock）不卡死、均成功。"""
        errors = []
        def runner(idx):
            try:
                res = store.refresh_soft_links()
                if not (isinstance(res, dict) and "ok" in res):
                    errors.append((idx, f"bad result: {res!r}"))
            except Exception as e:
                errors.append((idx, repr(e)))
        threads = [threading.Thread(target=runner, args=(i,)) for i in range(4)]
        for th in threads: th.start()
        for th in threads: th.join()
        self.assertEqual(errors, [], f"并发 refresh 异常: {errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
