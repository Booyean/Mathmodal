#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`a_e0_n0_phase.py` 的自检（纯合成；不读 `.dat`、不跑 execute）。

覆盖：
* 相干模在 [0,1]，正比谱 = 1，纯延迟残差会把它拉低（0.1 ns 量级可分辨）；
* `d1_min_abs_inner` 是正交化证书：正交残差 → 0，平行 → 1，退化频点被跳过；
* 合成证据文件的契约/顺序/范围自洽。

用法：
    python solutions/A/test_a_e0_n0_phase.py -v
"""

from __future__ import annotations

import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import a_e0_n0_phase as ph  # noqa: E402

BAND_HZ = np.arange(3.7e9, 2.3e9 - 1.0, -1.0e6)  # 与 E0 配置同带宽（1.4 GHz）


class CoherenceTest(unittest.TestCase):
    def test_proportional_is_one(self):
        rng = np.random.default_rng(0)
        z = rng.standard_normal(BAND_HZ.size) + 1j * rng.standard_normal(BAND_HZ.size)
        self.assertAlmostEqual(ph.complex_coherence(z, 2.5 * z), 1.0, places=12)

    def test_uncorrelated_is_near_zero(self):
        rng = np.random.default_rng(1)
        a = rng.standard_normal(4096) + 1j * rng.standard_normal(4096)
        b = rng.standard_normal(4096) + 1j * rng.standard_normal(4096)
        self.assertLess(ph.complex_coherence(a, b), 0.1)

    def test_pure_delay_reduces_coherence(self):
        # 0.1 ns 纯延迟在 1.4 GHz 带宽上的相干模约 0.71；1.5 ns 已接近 0。
        z = np.exp(1j * 2.0 * np.pi * BAND_HZ * 3.0e-7)
        for delay_ns, upper in ((0.1, 0.99), (1.5, 0.1)):
            z2 = z * np.exp(-1j * 2.0 * np.pi * BAND_HZ * delay_ns * 1e-9)
            rho = ph.complex_coherence(z, z2)
            self.assertGreaterEqual(rho, 0.0)
            self.assertLessEqual(rho, 1.0)
            self.assertLess(rho, upper, "delay=%r rho=%.6f" % (delay_ns, rho))

    def test_zero_vector_is_zero(self):
        z = np.ones(16, dtype=np.complex128)
        self.assertEqual(ph.complex_coherence(z, np.zeros(16)), 0.0)


class D1InnerTest(unittest.TestCase):
    def test_orthogonal_residual_is_zero(self):
        rng = np.random.default_rng(2)
        T = rng.standard_normal((63, 8)) + 1j * rng.standard_normal((63, 8))
        D1 = rng.standard_normal((63, 8)) + 1j * rng.standard_normal((63, 8))
        # 逐频点对 T 做 Gram-Schmidt
        for f in range(8):
            proj = np.vdot(T[:, f], D1[:, f]) / np.vdot(T[:, f], T[:, f])
            D1[:, f] = D1[:, f] - proj * T[:, f]
        stats = ph.d1_inner_stats(T, D1)
        self.assertLessEqual(stats["d1_min_abs_inner"], 1e-12)
        self.assertLessEqual(stats["d1_max_abs_inner"], 1e-12)
        self.assertEqual(stats["n_freq_degenerate"], 0)

    def test_parallel_mode_is_one(self):
        T = np.ones((63, 4), dtype=np.complex128)
        D1 = 2.0 * T
        stats = ph.d1_inner_stats(T, D1)
        self.assertAlmostEqual(stats["d1_min_abs_inner"], 1.0, places=12)
        self.assertAlmostEqual(stats["d1_max_abs_inner"], 1.0, places=12)

    def test_degenerate_columns_skipped(self):
        T = np.ones((63, 3), dtype=np.complex128)
        D1 = np.zeros((63, 3), dtype=np.complex128)
        stats = ph.d1_inner_stats(T, D1)
        self.assertEqual(stats["n_freq_degenerate"], 3)
        self.assertEqual(stats["d1_min_abs_inner"], 0.0)


class SyntheticEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = ph.build_synthetic_evidence()

    def test_contract_and_order(self):
        self.assertEqual(self.doc["contract"], "E0-N0-PHASE-EVIDENCE-1")
        self.assertTrue(self.doc["synthetic"])
        self.assertFalse(self.doc["citable"])
        self.assertEqual([r["group"] for r in self.doc["coherence"]],
                         list(self.doc["air_groups"]))
        self.assertEqual([r["cluster"] for r in self.doc["coherence"]],
                         ["C%d" % (i // 2) for i in range(10)])

    def test_rho_range_and_aligned(self):
        for r in self.doc["coherence"]:
            self.assertGreaterEqual(r["rho"], 0.0)
            self.assertLessEqual(r["rho"], 1.0)
        for i, v in enumerate(self.doc["coherence_values"]):
            self.assertEqual(v, self.doc["coherence"][i]["rho"])
            self.assertTrue(v >= self.doc["rho_min"])

    def test_d1_inner_within_tolerance(self):
        d1 = self.doc["d1"]
        self.assertEqual(d1["d1_rank"], 2)
        self.assertGreaterEqual(d1["d1_min_abs_inner"], 0.0)
        self.assertLessEqual(d1["d1_min_abs_inner"], 1e-6)
        self.assertLessEqual(d1["d1_max_abs_inner"], 1e-6)
        for fold in d1["folds"]:
            self.assertLessEqual(fold["d1_min_abs_inner"], 1e-6)
            self.assertLessEqual(fold["d1_max_abs_inner"], 1e-6)

    def test_shifts_are_ns_and_cluster_locked(self):
        shifts = self.doc["shifts_ns"]
        self.assertEqual(len(shifts), 10)
        self.assertAlmostEqual(shifts[1], 0.01475, places=12)
        for i in range(0, 10, 2):
            self.assertLessEqual(abs(shifts[i] - shifts[i + 1]), 0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
