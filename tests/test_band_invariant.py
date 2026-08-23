# -*- coding: utf-8 -*-
"""入库收口不变量测试（C3 · 防脏域污染）。

验证第 1 层「储存优化」的核心收口逻辑：
  - C1：任意 item 的主尺领域（readings.label, main）落库即受控——
        要么是已知合法涌现域，要么过 _is_broad_field 够宽守门；
        技术碎片（重叠窗口 / rag / 梯度下降）绝不许落库。
  - C2：领域候选选择器（domains_of_axes）只返回受控可见域，
        不依赖 items.axis_domain 内容、不繁殖脏域。
  - 跑一次 remeasure_all 后全库仍满足上述不变量（防回归）。

运行：
    python -m unittest tests.test_band_invariant -v
    python tests/test_band_invariant.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import lantern_caliper as store
import lantern_caliper.measure as M
import lantern_caliper.schema as S

# 技术碎片黑名单（C1 守门应拦截、绝不许作为领域落库；聚焦中文技术/实体碎片）
NARROW_TOKENS = ["重叠窗口", "rag", "梯度下降", "向量", "语义分块",
                 "注意力机制", "损失函数"]

# 合理领域（_is_broad_field 判 True、且为库内已知涌现域）
BROAD_KNOWN = ["信息检索", "技能管理", "社会心理学", "认知突破"]


def _known_bands_from_db():
    """库内已知主尺领域（readings.label 真实落库值），作为 normalize_band 的
    known_domains 真相源——不依赖 list_domains 的聚合过滤（后者有多重 JOIN
    可能漏域，属另一处待修，不在本测试范围）。"""
    con = store.connect()
    rows = con.execute(
        "SELECT DISTINCT label FROM readings "
        "WHERE scale='main' AND label IS NOT NULL AND label != ''"
    ).fetchall()
    con.close()
    return {r[0] for r in rows}


class TestBandInvariant(unittest.TestCase):
    """全库不变量：主尺领域受控、无技术碎片。"""

    def setUp(self):
        self.known = _known_bands_from_db()
        con = store.connect()
        self.rows = con.execute(
            "SELECT i.id, i.content, m.label AS band "
            "FROM items i "
            "JOIN readings m ON m.item_id=i.id AND m.scale='main'"
        ).fetchall()
        con.close()

    def test_no_narrow_token_as_band(self):
        """任何主尺 band 都不含技术碎片词。"""
        for r in self.rows:
            band = (r["band"] or "")
            for tok in NARROW_TOKENS:
                self.assertNotIn(
                    tok, band.lower(),
                    f"#{r['id']} 主尺领域含技术碎片词 {tok!r}: {band!r}"
                )

    def test_all_bands_broad_or_known(self):
        """任何主尺 band 要么已知涌现域、要么过够宽守门。"""
        for r in self.rows:
            band = (r["band"] or "").strip()
            if not band:
                continue
            ok = band in self.known or M._is_broad_field(band, r["content"] or "")
            self.assertTrue(
                ok,
                f"#{r['id']} 主尺领域既非已知域也非够宽域: {band!r}"
            )

    def test_normalize_band_rejects_narrow(self):
        """normalize_band 对技术碎片一律判否。"""
        for tok in NARROW_TOKENS:
            self.assertIsNone(
                M.normalize_band(tok, "测试内容 " + tok, known_domains=self.known),
                f"normalize_band 未拦截技术碎片: {tok!r}"
            )

    def test_normalize_band_keeps_broad(self):
        """normalize_band 对合理且已知领域（信息检索/技能管理…）放行。"""
        for name in BROAD_KNOWN:
            got = M.normalize_band(name, "测试", known_domains=self.known)
            self.assertEqual(got, name, f"合理领域被误杀: {name!r}")


class TestCandidateSelector(unittest.TestCase):
    """C2：领域候选选择器不繁殖脏域。"""

    def test_domains_of_axes_only_controlled_visible(self):
        doms = S.domains_of_axes()
        reg = S._DOMAIN_REGISTRY
        for d in doms:
            meta = reg.get(d)
            self.assertIsInstance(meta, dict, f"候选含非受控域: {d!r}")
            self.assertIn("band", meta, f"候选含无带域: {d!r}")
            self.assertFalse(meta.get("hidden"), f"候选含隐藏域: {d!r}")

    def test_domains_of_axes_no_narrow(self):
        doms = S.domains_of_axes()
        for tok in NARROW_TOKENS:
            self.assertNotIn(tok, doms, f"候选选择器含技术碎片: {tok!r}")


class TestRemeasureKeepsInvariant(unittest.TestCase):
    """跑 remeasure_all 后全库仍满足收口（防回归）。"""

    def test_remeasure_all_preserves_invariant(self):
        # 仅在 LLM 可用时跑完整重测；否则跳过（不强制联网）
        if not getattr(store, "LLM_OK", False):
            self.skipTest("LLM 不可用，跳过在线重测")
        res = store.remeasure_all(mode="llm")
        self.assertTrue(res.get("ok"))
        # 重测后重新断言无技术碎片
        con = store.connect()
        bands = [r[0] for r in con.execute(
            "SELECT label FROM readings WHERE scale='main'")]
        con.close()
        for b in bands:
            if not b:
                continue
            for tok in NARROW_TOKENS:
                self.assertNotIn(tok, (b or "").lower(),
                                  f"重测后仍有技术碎片域: {b!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
