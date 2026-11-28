#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``a_e0_n0.py``（``N0-SYN-1`` 秩 2 合成原型）的自检。

覆盖
----
1. **守卫**：合成专用（拒绝 `附件` / `.dat` / `E0-T` 组）、秩固定 2、臂固定三档；
2. **分簇与训练范围锁定**：5 个两元素簇、五折留出同簇 2 组、模板池恰为其余 8 组；
   偏移与 `b63e217#cal.shifts_s` 不符（>0.1 ns）必须按 `S5` 拒绝，且不提供重新分簇入口；
3. **跨频相位对齐**：参考通道锚定后 `D_1` 与 `T` 逐频点正交、量级与 `T` 可比；
   负例（逐频点随机相位）会让第二模态在直射波窗内的能量显著塌陷；
4. **近零内积处理**：偏差只剩“整组复标度”时判 `near_parallel`、`rank_effective=1`、
   `c2` 退化为 `c1`（不做近零除法、不产生 NaN）；Gram 近奇异时加相对岭并标记；
5. **复数秩一通道模态回归**（`N0-CHREG-1`，codex 2026-11-28 复核要求）：解析方向
   `(1, e^{2πi/3}, e^{4πi/3})/√3` 下由 `rel_dev` 行方向恢复通道模态、以 `b_g = α_g`
   精确重建训练数据行向量；旧式 `vh[0].conj()` 作为负例必须被抓住；实方向夹具
   在同一变异下不可分辨（记录“旧夹具为何漏检”）；
6. **拟合可复算**：已知 (a,b) 的合成窗数据可被 2×2 LS 回收；充分统计量与数组两条
   独立路径的 `Supp` 一致（C8' 口径，≤1e-6 dB）；
7. **判定链**：P1 三档（`<6` / `6–<10` / `≥10`）、P1/P2 取较低档、P3 单侧非退化、
   L1 三值互斥、L2 的 C9b/灰区/frozen 条件、`L1 PASS / L2 FAIL → S8`；
8. **夹具全流程**：`P1` 秩 2 比秩 1 至少高 5 dB、P4 保留、`citable=false`、
   `real_dat_reads=0`、`L1=PASS` 而 `L2=FAIL（S8）`；
9. **CLI**：`check` 只读；`synthetic` 写出三件产物且拒绝覆盖非空目录（退出码 3）；
10. **证据链**：产物带 `implementation_sha/generated_at/command/environment` 溯源，
    `SHA256SUMS` 与 LF 归一化摘要一致，`--generated-at` 固定时逐字节可复现；
    `.gitattributes` 把纳入摘要的 JSON 钉成 `eol=lf`；C8' 覆盖 P2 十折；P3 锚点与归档一致。

用法::

    python solutions/A/test_a_e0_n0.py
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import a_e0_n0 as N  # noqa: E402
import a_e0_n0_channel_regression as R  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402

CONFIG = N.CONFIG_PATH
ARCHIVED = REPO / "experiments/A/A-Q1-E0/e0c/results/e0c_results.json"
WORK = REPO / "tmp"
WORK.mkdir(parents=True, exist_ok=True)


def _work_tmp() -> Path:
    path = WORK / ("n0_test_" + uuid.uuid4().hex[:10])
    path.mkdir(parents=True, exist_ok=False)
    return path


def _tiny_pool(n_groups: int = 6, n_ch: int = 8, n_f: int = 5, seed: int = 3):
    rng = np.random.default_rng(seed)
    t = rng.standard_normal((n_ch, n_f)) + 1j * rng.standard_normal((n_ch, n_f))
    t = t / np.max(np.abs(t))
    pattern = np.cos(2.0 * np.pi * 1.5 * np.arange(n_ch) / n_ch + 0.4)
    pool = []
    for g in range(n_groups):
        coeff = float(rng.uniform(0.6, 1.4)) * np.exp(1j * rng.uniform(-np.pi, np.pi))
        pool.append(t * (1.0 + 0.4 * coeff * pattern[:, None]))
    return np.stack(pool, axis=0), t, pattern


class GuardTests(unittest.TestCase):
    def test_rejects_real_attachment_path(self):
        for bad in ("D:/data/附件/附件2-测距数据", "../附件3/成像数据", "x/e0-t/y"):
            with self.assertRaises(N.N0Stop) as ctx:
                N.assert_synthetic_only(bad)
            self.assertEqual(ctx.exception.code, "S5")

    def test_rejects_dat_file(self):
        with self.assertRaises(N.N0Stop):
            N.assert_synthetic_only("空场数据/data1_0.dat")

    def test_rejects_e0t_group(self):
        with self.assertRaises(N.N0Stop):
            N.assert_synthetic_only("墙体数据/data20-73cm")

    def test_rejects_rank_search(self):
        self.assertEqual(N.assert_rank(2), 2)
        for bad in (1, 3, 0):
            with self.assertRaises(N.N0Stop) as ctx:
                N.assert_rank(bad)
            self.assertEqual(ctx.exception.code, "S7")

    def test_rejects_unknown_arm(self):
        self.assertEqual(N.assert_arm("c2"), "c2")
        with self.assertRaises(N.N0Stop):
            N.assert_arm("c3")

    def test_accepts_plain_path(self):
        N.assert_synthetic_only("experiments/A/A-Q1-E0/n0/synthetic")


class FoldLockTests(unittest.TestCase):
    def test_clusters_match_proposal_pairs(self):
        self.assertEqual(len(N.CLUSTERS), 5)
        for k, pair in enumerate(N.CLUSTERS):
            self.assertEqual(pair, ("空场数据/data%d" % (2 * k + 1),
                                    "空场数据/data%d" % (2 * k + 2)))

    def test_roster_matches_archived_b63e217(self):
        self.assertTrue(ARCHIVED.is_file(), ARCHIVED)
        with open(ARCHIVED, "r", encoding="utf-8") as f:
            res = json.load(f)
        shifts = [float(v) for v in res["cal"]["shifts_s"]]
        self.assertEqual(len(shifts), 10)
        for got, want in zip(shifts, N.BASELINE_SHIFTS_S):
            self.assertAlmostEqual(got * 1e9, want * 1e9, places=9)

    def test_fold_lock_accepts_roster_and_excludes_holdout(self):
        out = N.assert_fold_lock(N.BASELINE_SHIFTS_S)
        self.assertLessEqual(out["max_dev_ns"], N.SHIFT_TOL_NS)
        self.assertEqual(out["cluster_index"],
                         [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]])
        for fold, cluster in enumerate(N.CLUSTERS):
            pool = [g for g in N.AIR_GROUPS if g not in cluster]
            self.assertEqual(len(pool), 8)
            self.assertTrue(all(g not in pool for g in cluster))
            self.assertEqual(len(set(pool) - set(N.AIR_GROUPS)), 0)

    def test_fold_lock_rejects_shift_change(self):
        bad = list(N.BASELINE_SHIFTS_S)
        bad[4] += 0.2e-9  # 0.2 ns > 0.1 ns 容差
        with self.assertRaises(N.N0Stop) as ctx:
            N.assert_fold_lock(bad)
        self.assertEqual(ctx.exception.code, "S5")

    def test_fold_lock_rejects_wrong_roster_size(self):
        with self.assertRaises(N.N0Stop):
            N.assert_fold_lock(list(N.BASELINE_SHIFTS_S)[:9])

    def test_fold_lock_rejects_imbalanced_clusters(self):
        bad = (("空场数据/data1", "空场数据/data2", "空场数据/data3"),) + N.CLUSTERS[1:]
        with self.assertRaises(N.N0Stop):
            N.assert_fold_lock(N.BASELINE_SHIFTS_S, clusters=bad)


class BasisTests(unittest.TestCase):
    def test_modulation_mode_is_orthogonal_and_comparable_scale(self):
        pool, t, _ = _tiny_pool()
        basis = N.build_rank2_basis(pool, ref_pos=0, mode_form="modulation")
        self.assertEqual(basis["rank_effective"], 2)
        self.assertFalse(basis["near_parallel"])
        d1 = basis["D1"]
        t_mean = basis["T"]
        for f in range(pool.shape[2]):
            inner = abs(np.vdot(t_mean[:, f], d1[:, f]))
            denom = np.linalg.norm(t_mean[:, f]) * np.linalg.norm(d1[:, f])
            self.assertLess(inner / denom, 1e-9, "f=%d" % f)
            ratio = np.linalg.norm(d1[:, f]) / np.linalg.norm(t_mean[:, f])
            self.assertGreater(ratio, 0.05, "f=%d" % f)
            self.assertTrue(np.all(np.isfinite(d1[:, f])))

    def test_global_scale_only_pool_is_degenerate(self):
        pool, t, _ = _tiny_pool()
        scaled = np.stack(
            [t * c for c in (1.2, 0.8, 1.1 + 0.2j, 0.9 - 0.1j, 1.05, 0.95)], axis=0
        )
        basis = N.build_rank2_basis(scaled, ref_pos=0, mode_form="modulation")
        self.assertTrue(basis["near_parallel"])
        self.assertEqual(basis["rank_effective"], 1)
        self.assertEqual(basis["degenerate_freqs"], scaled.shape[2])
        self.assertTrue(np.all(basis["D1"] == 0.0))
        self.assertFalse(np.any(np.isnan(basis["D1"])))

    def test_empty_pool_rejected(self):
        with self.assertRaises(N.N0Stop):
            N.build_rank2_basis(np.zeros((1, 4, 2), dtype=complex))

    def test_random_phase_negative_control_collapses_direct_delay_energy(self):
        # 专用夹具：T 的通道相位是纯延迟斜坡（真实数据的直射波形态），
        # 第二模态的延迟域能量应集中在各通道 τ_dir 上；逐频点随机相位会塌陷。
        n_ch, n_f = 16, 64
        f_r = np.linspace(2.3e9, 3.7e9, n_f)
        tau_dir = np.arange(n_ch) * 0.05e-9
        pattern = np.cos(2.0 * np.pi * 1.5 * np.arange(n_ch) / n_ch + 0.3)
        base = np.exp(1j * 2.0 * np.pi * np.outer(tau_dir, f_r))
        pool = np.stack(
            [
                base * (1.0 + 0.4 * np.exp(1j * (0.3 + 0.9 * g)) * pattern)[:, None]
                for g in range(6)
            ],
            axis=0,
        )
        anchored = N.build_rank2_basis(pool, ref_pos=0, mode_form="modulation")
        randomized = N.build_rank2_basis(
            pool, ref_pos=0, mode_form="modulation", randomize_phase=True
        )
        tpl = np.ones(n_f, dtype=complex)
        delays = np.tile(tau_dir[:, None], (1, 1))
        z_a = E0S.z_at_delays(anchored["D1"], tpl, f_r, delays)
        z_r = E0S.z_at_delays(randomized["D1"], tpl, f_r, delays)
        e_a = float(np.mean(np.abs(z_a) ** 2))
        e_r = float(np.mean(np.abs(z_r) ** 2))
        self.assertGreater(e_a, 0.0)
        self.assertLess(e_r / e_a, 0.1, "随机相位负例应显著塌陷：%.3g" % (e_r / e_a))


class ComplexChannelRegressionTests(unittest.TestCase):
    """`N0-CHREG-1`：复数秩一通道模态回归（codex 2026-11-28 复核要求）。

    解析夹具 `γ = (1, e^{2πi/3}, e^{4πi/3})/√3` 同时满足 `Σγ = 0`（扣整组复标度
    不变）与 `Σγ² = 0`（`γ ⟂ conj(γ)`），因此“取向量相位反转”这一缺陷既可解析
    预测、又只能在这一维上被抓住。
    """

    def test_fixture_direction_is_zero_mean_and_isotropic(self):
        g = R.CHANNEL_DIRECTION
        self.assertLess(abs(complex(np.sum(g))), 1e-15)
        self.assertLess(abs(complex(np.sum(g**2))), 1e-15)
        self.assertAlmostEqual(float(np.linalg.norm(g)), 1.0, places=15)

    def test_complex_channel_direction_is_recovered(self):
        for case in R.FIXTURE_CASES:
            res = R.evaluate_case(case)
            self.assertLess(
                res["direction_recovery"]["error_to_true_max"],
                R.DIRECTION_OK_MAX,
                msg=case,
            )
            self.assertGreater(
                res["direction_recovery"]["error_to_conjugate_min"],
                R.NEGATIVE_DIRECTION_MIN,
                msg=case,
            )
            self.assertEqual(res["production_basis"]["rank_effective"], 2, msg=case)

    def test_training_rows_reconstructed_with_b_equals_alpha(self):
        for case in R.FIXTURE_CASES:
            res = R.evaluate_case(case)
            self.assertLess(
                res["row_reconstruction"]["row_rel_residual_max"],
                R.ROW_RESIDUAL_OK_MAX,
                msg=case,
            )
            self.assertLess(
                res["row_reconstruction"]["coeff_rel_error_max"],
                R.COEFF_REL_OK_MAX,
                msg=case,
            )
            # 第二模态系数必须非零（否则秩 2 退化成秩 1）。
            self.assertGreater(
                res["row_reconstruction"]["second_coeff_abs_max"], 0.4, msg=case
            )

    def test_legacy_conjugate_mutation_is_detected(self):
        for case in R.FIXTURE_CASES:
            neg = R.evaluate_case(case)["negative_control"]
            self.assertTrue(neg["detected"], msg=case)
            self.assertGreater(neg["direction_error_to_true_min"], R.NEGATIVE_DIRECTION_MIN)
            self.assertGreater(neg["row_rel_residual_min"], R.NEGATIVE_ROW_RESIDUAL_MIN)
            if case == "flat_T":
                # 解析结论：<T⊙γ, T⊙conjγ> = Σγ²·|T|² = 0 → 第二模态系数必须恒为 0。
                self.assertLess(neg["second_coeff_abs_max"], R.NEGATIVE_SECOND_COEFF_MAX)

    def test_real_fixture_cannot_distinguish_conjugation(self):
        blind = R.evaluate_real_fixture_blindness()
        self.assertTrue(blind["conjugate_is_equivalent"])
        self.assertLess(blind["row_rel_residual_production"], 1e-12)
        self.assertLess(blind["row_rel_residual_legacy_mutant"], 1e-12)
        self.assertLess(blind["direction_error_legacy_mutant"], 1e-12)

    def test_local_replica_matches_production_basis(self):
        for case in R.FIXTURE_CASES:
            res = R.evaluate_case(case)
            self.assertLessEqual(
                res["production_basis"]["local_replica_gap_rel"], 1e-12, msg=case
            )

    def test_regression_verdict_and_scope(self):
        doc = R.run()
        self.assertEqual(doc["contract"], "N0-CHREG-1")
        self.assertEqual(int(doc["real_dat_files_read"]), 0)
        self.assertTrue(doc["verdict"]["pass"])
        self.assertTrue(doc["verdict"]["negative_control_detected"])
        self.assertTrue(doc["scope"]["numeric_core_untouched"])
        self.assertEqual(doc["defect"]["pre_fix"], "v = vh[0].conj()")
        self.assertEqual(doc["defect"]["post_fix"], "v = vh[0]")
        json.dumps(R.json_safe(doc), ensure_ascii=False)

    def test_evidence_outputs_are_self_consistent(self):
        tmp = _work_tmp()
        try:
            doc = R.run()
            info = R.write_outputs(doc, tmp / "out")
            out = tmp / "out"
            for name in ("n0_channel_regression.json", "N0_CHANNEL_REGRESSION.md", "SHA256SUMS.txt"):
                self.assertTrue((out / name).is_file(), name)
            sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
            for name, digest in info["sha256"].items():
                self.assertIn("%s  %s" % (digest, name), sums)
            reloaded = json.loads((out / "n0_channel_regression.json").read_text(encoding="utf-8"))
            self.assertEqual(reloaded["contract"], "N0-CHREG-1")
            self.assertTrue(reloaded["verdict"]["pass"])
            prov = reloaded["provenance"]
            self.assertRegex(prov["implementation_sha"], r"^(?:[0-9a-f]{40}|unknown)$")
            self.assertTrue(prov["generated_at"].endswith("Z"))
            self.assertIn("a_e0_n0_channel_regression.py", prov["command"])
            # 输出目录非空且未给 overwrite → 拒绝（与 `n0/synthetic` 同约定）。
            with self.assertRaises(SystemExit):
                R.write_outputs(doc, out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CoefficientTests(unittest.TestCase):
    def _known_stats(self, a_true: complex, b_true: complex, seed: int = 11):
        rng = np.random.default_rng(seed)
        n_ch, n_s = 5, 9
        z_t = rng.standard_normal((n_ch, n_s)) + 1j * rng.standard_normal((n_ch, n_s))
        z_d = 0.5 * (
            rng.standard_normal((n_ch, n_s)) + 1j * rng.standard_normal((n_ch, n_s))
        )
        noise = 1e-3 * (
            rng.standard_normal((n_ch, n_s)) + 1j * rng.standard_normal((n_ch, n_s))
        )
        z_x = a_true * z_t + b_true * z_d + noise
        mask = np.ones(n_s, dtype=bool)
        stats = N._window_stats(z_x, z_t, z_d, mask)
        return stats, z_x, z_t, z_d, mask

    def test_recovers_known_coefficients(self):
        a_true, b_true = 0.93 - 0.11j, 0.21 + 0.07j
        stats, *_ = self._known_stats(a_true, b_true)
        coeffs = N.solve_coefficients(stats, "c2")
        self.assertLess(abs(coeffs["a"] - a_true), 5e-3)
        self.assertLess(abs(coeffs["b"] - b_true), 5e-3)
        self.assertTrue(coeffs["second_mode_used"])

    def test_rank1_and_c0_are_fixed_forms(self):
        stats, *_ = self._known_stats(1.0 + 0j, 0.3 + 0j)
        c0 = N.solve_coefficients(stats, "c0")
        self.assertEqual(c0["a"], 1.0 + 0j)
        self.assertEqual(c0["b"], 0.0 + 0j)
        c1 = N.solve_coefficients(stats, "c1")
        self.assertEqual(c1["b"], 0.0 + 0j)
        self.assertFalse(c1["second_mode_used"])

    def test_stats_and_array_paths_agree_per_arm(self):
        # 两条路径必须解同一个臂模型：c0 a≡1/b=0、c1 只解 a、c2 解 (a,b)。
        stats, z_x, z_t, z_d, mask = self._known_stats(0.9 + 0.2j, -0.4 + 0.15j, seed=17)
        for arm in ("c0", "c1", "c2"):
            coeffs = N.solve_coefficients(stats, arm)
            arr = N.suppression_from_arrays(z_x, z_t, z_d, mask, arm=arm)
            self.assertLessEqual(
                abs(N.suppression_from_stats(stats, coeffs) - arr["supp_db"]), 1e-9, arm
            )
            self.assertLessEqual(abs(complex(coeffs["a"]) - arr["a"]), 1e-9, arm)
            self.assertLessEqual(abs(complex(coeffs["b"]) - arr["b"]), 1e-9, arm)

    def test_rank2_beats_rank1_when_second_mode_present(self):
        stats, *_ = self._known_stats(1.0 + 0j, 0.5 + 0j)
        s1 = N.suppression_from_stats(stats, N.solve_coefficients(stats, "c1"))
        s2 = N.suppression_from_stats(stats, N.solve_coefficients(stats, "c2"))
        self.assertGreater(s2, s1 + 3.0)

    def test_near_singular_gram_is_regularized(self):
        # A22 = 0 → Gram 近奇异：必须加相对岭并标记，不抛异常、不出 NaN。
        rng = np.random.default_rng(5)
        z_t = rng.standard_normal((4, 8)) + 1j * rng.standard_normal((4, 8))
        z_d = np.zeros_like(z_t)
        z_x = 1.2 * z_t
        stats = N._window_stats(z_x, z_t, z_d, np.ones(8, dtype=bool))
        coeffs = N.solve_coefficients(stats, "c2")
        self.assertTrue(coeffs["regularized"])
        self.assertGreater(coeffs["gram_ridge"], 0.0)
        self.assertTrue(math.isfinite(coeffs["gram_cond"]))
        self.assertTrue(math.isfinite(N.suppression_from_stats(stats, coeffs)))


class DecisionTests(unittest.TestCase):
    def test_p1_three_tiers(self):
        self.assertEqual(N.classify_p1(5.999), "hard_stop")
        self.assertEqual(N.classify_p1(6.0), "not_met")
        self.assertEqual(N.classify_p1(9.999), "not_met")
        self.assertEqual(N.classify_p1(10.0), "met")

    def test_l1_hard_stop(self):
        l1 = N.decide_l1(
            p1_min_db=5.0, p2_min_db=8.0, p2_median_db=12.0,
            p3_pass=True, p3_items=[], p4_pass=True, p5a_pass=True,
        )
        self.assertEqual(l1["l1"], "hard_stop")
        self.assertEqual(l1["s_code"], "S1")

    def test_l1_not_met_between_6_and_10(self):
        l1 = N.decide_l1(
            p1_min_db=7.5, p2_min_db=8.0, p2_median_db=12.0,
            p3_pass=True, p3_items=[], p4_pass=True, p5a_pass=True,
        )
        self.assertEqual(l1["l1"], "not_met")
        self.assertEqual(l1["s_code"], "S2")

    def test_l1_pass_and_lower_tier_rule(self):
        ok = N.decide_l1(
            p1_min_db=11.0, p2_min_db=12.0, p2_median_db=15.0,
            p3_pass=True, p3_items=[], p4_pass=True, p5a_pass=True,
        )
        self.assertEqual(ok["l1"], "pass")
        # P1 达标但 P2 min 只有 7 dB → 取较低档
        low = N.decide_l1(
            p1_min_db=11.0, p2_min_db=7.0, p2_median_db=15.0,
            p3_pass=True, p3_items=[], p4_pass=True, p5a_pass=True,
        )
        self.assertEqual(low["l1"], "not_met")
        self.assertEqual(low["lower_tier"], "not_met")

    def test_l1_requires_p4_and_p3(self):
        bad = N.decide_l1(
            p1_min_db=12.0, p2_min_db=12.0, p2_median_db=12.0,
            p3_pass=False, p3_items=[], p4_pass=True, p5a_pass=True,
        )
        self.assertEqual(bad["l1"], "not_met")

    def _l1_pass(self):
        return N.decide_l1(
            p1_min_db=12.0, p2_min_db=12.0, p2_median_db=14.0,
            p3_pass=True, p3_items=[], p4_pass=True, p5a_pass=True,
        )

    def test_l2_s8_when_freeze_not_eligible(self):
        l2 = N.decide_l2(
            l1=self._l1_pass(), p5a_pass=True,
            c9b={"pass": True, "failed": []}, gray_targets=[],
            freeze_status="not_eligible_for_freeze", frozen_present=False,
        )
        self.assertEqual(l2["l2"], "fail")
        self.assertEqual(l2["s_code"], "S8")
        self.assertIn("S8", l2["matrix_position"])

    def test_l2_fails_on_gray_zone_and_c9b(self):
        l2 = N.decide_l2(
            l1=self._l1_pass(), p5a_pass=True,
            c9b={"pass": False, "failed": ["g:pslr_ok"]},
            gray_targets=["墙体数据/data1-42cm"],
            freeze_status="eligible", frozen_present=True,
        )
        self.assertEqual(l2["l2"], "fail")
        joined = " ".join(l2["reasons"])
        self.assertIn("灰区", joined)
        self.assertIn("C9b", joined)

    def test_l2_pass_requires_all(self):
        l2 = N.decide_l2(
            l1=self._l1_pass(), p5a_pass=True,
            c9b={"pass": True, "failed": []}, gray_targets=[],
            freeze_status="eligible", frozen_present=True,
        )
        self.assertEqual(l2["l2"], "pass")
        self.assertIn("L1 PASS / L2 PASS", l2["matrix_position"])


class FixtureTests(unittest.TestCase):
    """一次全流程（4 mm 剖面网格，缩短耗时），然后做多项断言。"""

    @classmethod
    def setUpClass(cls):
        cfg = E0S.load_config(CONFIG)
        cls.setup = E0S.Setup(cfg)
        cls.doc = N.run_synthetic(seed=N.SYNTH_SEED, d_step_m=0.004, p4_step_m=5e-4, setup=cls.setup)
        cls.md = N.render_markdown(cls.doc)

    def test_scope_and_policy(self):
        self.assertEqual(self.doc["scope"]["real_dat_reads"], 0)
        self.assertEqual(self.doc["scope"]["opened_files"], 0)
        self.assertIn("只统计实验数据文件", self.doc["scope"]["note"])
        self.assertFalse(self.doc["scope"]["e0t_touched"])
        for key in (
            "citable",
            "may_enter_results_table",
            "may_enter_paper_numbers",
            "may_be_used_for_freeze",
            "may_be_used_for_e0t",
        ):
            self.assertFalse(self.doc["policy"][key], key)
        self.assertTrue(self.doc["synthetic"])

    def test_fold_plan_excludes_holdout(self):
        self.assertEqual(len(self.doc["fold_plan"]["p1_folds"]), 5)
        for fold in self.doc["fold_plan"]["p1_folds"]:
            self.assertEqual(len(fold["held_out"]), 2)
            self.assertEqual(len(fold["template_pool"]), 8)
            self.assertFalse(set(fold["held_out"]) & set(fold["template_pool"]))
        self.assertTrue(all(v == 8 for v in self.doc["fold_plan"]["p1_pool_sizes"]))

    def test_rank2_gain_over_rank1(self):
        p1 = self.doc["p1"]
        p2 = self.doc["p2"]
        self.assertGreater(p1["c2"]["min_db"], p1["c1"]["min_db"] + 5.0)
        self.assertGreater(p1["c1"]["min_db"], p1["c0"]["min_db"] + 1.0)
        self.assertGreater(p2["c2"]["min_db"], p2["c1"]["min_db"] + 5.0)
        self.assertGreater(self.doc["contrasts"]["c2_over_c1_p1_db"], 5.0)

    def test_second_mode_used_in_targets(self):
        for group, res in self.doc["targets"].items():
            self.assertTrue(res["arms"]["c2"]["second_mode_used"], group)
            self.assertGreater(res["arms"]["c2"]["second_mode_energy_fraction"], 0.1)

    def test_p5a_gates_its_own_constants(self):
        items = self.doc["p5a"]["items"]["p5a_1_interfaces"]
        # 列出的常量必须是参与判定的布尔项，而不是只打印数值（F5）。
        self.assertIs(items["lambda_fixed"], True)
        self.assertIs(items["fit_window_ns"], True)
        self.assertEqual(items["fit_window_ns_value"], 1.0)
        self.assertEqual(items["lambda_fixed_value"], [1e-3, 1e-3])
        self.assertEqual(self.doc["p5a"]["items"]["p5a_2_self_consistency"]["p2_values"], 30)
        self.assertIs(self.doc["p5a"]["pass"], True)

    def test_p4_retention_and_p3(self):
        self.assertTrue(self.doc["p3"]["pass"])
        self.assertTrue(self.doc["p4"]["pass"])
        item = self.doc["p4"]["items"][0]
        self.assertGreaterEqual(item["peak_retention_db"], -0.1)
        self.assertLessEqual(abs(item["range_shift_mm"]), 2.0)

    def test_c8_prime_consistency(self):
        self.assertTrue(self.doc["c8_prime"]["pass"])
        self.assertLessEqual(self.doc["c8_prime"]["max_delta_db"], 1e-6)
        self.assertEqual(self.doc["c8_prime"]["lambda_fixed"], [1e-3, 1e-3])

    def test_c8_prime_covers_p2_ten_folds(self):
        cov = self.doc["c8_prime"]["coverage"]
        self.assertEqual(cov["p1_values"], 5 * 2 * 3)
        self.assertEqual(cov["p2_values"], 10 * 3)
        self.assertEqual(cov["target_values"], 2 * 3)
        self.assertEqual(cov["total_values"], 66)
        self.assertEqual(cov["p2_folds_per_arm"], 10)
        for arm in self.doc["p2"]:
            self.assertEqual(len(self.doc["p2"][arm]["values"]), 10)
            for value in self.doc["p2"][arm]["values"]:
                # P2 每个折也必须带双路径复算差值（F3 声明=实现）。
                self.assertLessEqual(value["c8_delta_supp_db"], 1e-6)
                self.assertIn("c8_delta_coeff", value)

    def test_wall_pnr_anchor_matches_archive(self):
        archive = json.loads(ARCHIVED.read_text(encoding="utf-8"))
        rows = {g["group_key"]: g for g in archive["groups"]}
        for key, anchor in N.BASELINE_P3_ANCHOR.items():
            row = rows[key]
            # 锚点是从归档四舍五入来的，必须逐项在 4 位小数内一致（F4）。
            self.assertAlmostEqual(anchor["pnr_db"], float(row["pnr_db"]), places=4)
            self.assertAlmostEqual(anchor["pslr_db"], float(row["pslr_db"]), places=4)
            self.assertAlmostEqual(anchor["abs_err_cm"], float(row["abs_err_cm"]), places=2)
            self.assertAlmostEqual(anchor["d_hat_m"], float(row["d_hat_m"]), places=6)

    def test_check_mode_anchor_matches_declared(self):
        doc = N.run_check()
        for key, anchor in N.BASELINE_P3_ANCHOR.items():
            got = doc["archived_anchor"][key]
            self.assertAlmostEqual(got["pnr_db"], anchor["pnr_db"], places=4)

    def test_write_outputs_provenance_and_byte_reproducibility(self):
        tmp = _work_tmp()
        try:
            command = "python solutions/A/a_e0_n0.py --mode synthetic"
            N.write_outputs(self.doc, tmp / "a", command=command,
                            generated_at="2026-11-28T00:00:00Z")
            N.write_outputs(self.doc, tmp / "b", command=command,
                            generated_at="2026-11-28T00:00:00Z")
            for name in ("n0_synthetic_results.json", "N0_SYNTHETIC.md"):
                self.assertEqual(
                    (tmp / "a" / name).read_bytes(), (tmp / "b" / name).read_bytes(), name
                )
            artifact = json.loads(
                (tmp / "a" / "n0_synthetic_results.json").read_text(encoding="utf-8")
            )
            prov = artifact["provenance"]
            self.assertRegex(prov["implementation_sha"], r"^(?:[0-9a-f]{40}|unknown)$")
            self.assertEqual(prov["generated_at"], "2026-11-28T00:00:00Z")
            self.assertEqual(prov["generated_at_source"], "explicit")
            self.assertEqual(prov["command"], command)
            self.assertIn("numpy", prov["environment"])
            lines = (tmp / "a" / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                want, name = line.split("  ", 1)
                self.assertEqual(want, N._sha256(tmp / "a" / name))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_l1_pass_l2_fail_s8(self):
        self.assertEqual(self.doc["l1"]["l1"], "pass")
        self.assertEqual(self.doc["l2"]["l2"], "fail")
        self.assertEqual(self.doc["l2"]["s_code"], "S8")
        self.assertIn("not_eligible_for_freeze", " ".join(self.doc["l2"]["reasons"]))

    def test_markdown_has_non_citable_notice(self):
        self.assertIn("不可引用声明", self.md)
        self.assertIn("citable=false", self.md)
        self.assertIn("real_dat_reads=0", self.md)

    def test_deterministic_for_same_seed(self):
        a = N.generate_synthetic_pool(self.setup, seed=123)
        b = N.generate_synthetic_pool(self.setup, seed=123)
        c = N.generate_synthetic_pool(self.setup, seed=124)
        self.assertTrue(np.array_equal(a["air"][0], b["air"][0]))
        self.assertFalse(np.array_equal(a["air"][0], c["air"][0]))


class CliTests(unittest.TestCase):
    def test_check_mode(self):
        code = N.main(["--mode", "check"])
        self.assertEqual(code, 0)

    def test_synthetic_writes_artifacts(self):
        tmp = _work_tmp()
        try:
            code = N.main([
                "--mode", "synthetic",
                "--out", str(tmp / "out"),
                "--profile-step-m", "0.004", "--p4-step-m", "5e-4",
                "--generated-at", "2026-11-28T00:00:00Z",
            ])
            self.assertEqual(code, 0)
            out = tmp / "out"
            for name in ("n0_synthetic_results.json", "N0_SYNTHETIC.md", "SHA256SUMS.txt"):
                self.assertTrue((out / name).is_file(), name)
            doc = json.loads((out / "n0_synthetic_results.json").read_text(encoding="utf-8"))
            self.assertFalse(doc["citable"])
            self.assertEqual(doc["contract"], "N0-SYN-1")
            prov = doc["provenance"]
            self.assertEqual(prov["generated_at"], "2026-11-28T00:00:00Z")
            self.assertIn("--generated-at 2026-11-28T00:00:00Z", prov["command"])
            sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(sums), 2)
            for line in sums:
                want, name = line.split("  ", 1)
                self.assertEqual(want, N._sha256(out / name))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_json_artifacts_are_lf_locked(self):
        # F1：纳入 SHA256SUMS 的 JSON 必须在 CRLF 检出下仍以 LF 落地。
        paths = [
            "experiments/A/A-Q1-E0/n0/synthetic/n0_synthetic_results.json",
            "experiments/A/A-Q1-E0/n0/channel_regression/n0_channel_regression.json",
            "experiments/A/A-Q1-E0/e0c/poststop/poststop_targets.json",
        ]
        try:
            for rel in paths:
                proc = subprocess.run(
                    ["git", "-C", str(REPO), "check-attr", "eol", "--", rel],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn("eol: lf", proc.stdout, rel)
        except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
            self.skipTest("git 不可用，跳过 .gitattributes 检查：%s" % exc)

    def test_refuses_non_empty_output(self):
        tmp = _work_tmp()
        try:
            out = tmp / "out"
            out.mkdir()
            (out / "keep.txt").write_text("x", encoding="utf-8")
            code = N.main(["--mode", "synthetic", "--out", str(out)])
            self.assertEqual(code, 3)
            self.assertTrue((out / "keep.txt").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
