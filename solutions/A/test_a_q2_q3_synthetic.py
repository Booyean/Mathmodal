#!/usr/bin/env python3
"""Unit and end-to-end synthetic regression suite for Q2 (2D) & Q3 (3D) baseline solvers."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from run_q2_q3_synthetic import run_synthetic_suite
from validate_q2_q3_outputs import validate_output_dir


class TestQ2Q3SyntheticSolvers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_root = tempfile.TemporaryDirectory()
        cls.out_dir = Path(cls._tmp_root.name) / "results"
        cls.summary = run_synthetic_suite(cls.out_dir, preset="minimal")
        cls.q2_res = json.loads((cls.out_dir / "q2_results.json").read_text(encoding="utf-8"))
        cls.q3w_res = json.loads((cls.out_dir / "q3_wall_results.json").read_text(encoding="utf-8"))
        cls.q3m_res = json.loads((cls.out_dir / "q3_metal_results.json").read_text(encoding="utf-8"))
        with np.load(cls.out_dir / "q3_metal_arrays.npz", allow_pickle=False) as npz:
            cls.q3m_arr = {k: npz[k] for k in npz.files}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_root.cleanup()

    def test_q2_physics_gain_and_cross_row_consistency(self) -> None:
        self.assertEqual(self.q2_res["row_id"], 4)
        self.assertEqual(self.q2_res["rx_indices"], [24, 25, 26, 28, 29, 30, 31])
        self.assertAlmostEqual(self.q2_res["z_slice_m"], 0.545)
        self.assertGreater(self.q2_res["gain_selection"]["selected_alpha_per_ns"], 0.0)

        m_before = self.q2_res["metrics_before_gain"]
        m_coh = self.q2_res["metrics_after_gain_coh"]
        m_env = self.q2_res["metrics_after_gain_env"]
        self.assertGreaterEqual(m_coh["delta_ba_db"] - m_before["delta_ba_db"], 10.0)
        self.assertGreater(m_coh["pbr_b_db"], m_env["pbr_b_db"])
        self.assertGreater(m_coh["b_coverage_pct"], 80.0)

        planted_tilt = math.degrees(math.atan((0.56 - 0.37) / (1.06 - 0.25)))
        self.assertLessEqual(abs(self.q2_res["wall_a_apparent"]["tilt_deg"] - planted_tilt), 2.5)
        self.assertGreater(self.q2_res["wall_b_apparent"]["delta_y_app_m"], 0.02)
        self.assertGreater(self.q2_res["wall_b_apparent"]["eps_r_diag"], 1.4)
        self.assertLessEqual(self.q2_res["row_consistency"]["max_row_diff_cm"], 2.0)

    def test_q3_wall_reconciliation_and_dual_metal_shadow(self) -> None:
        rec = self.q3w_res["q2_q3_reconciliation"]
        self.assertTrue(rec["passed_le_2cm"], f"Reconciliation diff too large: {rec}")
        self.assertGreater(self.q3w_res["wall_b_3d"]["pbr_b_coh_db"], self.q3w_res["wall_b_3d"]["pbr_b_env_db"])

        by_id = {obj["object_id"]: obj for obj in self.q3m_res["metal_objects"]}
        self.assertIn("metal_col", by_id)
        self.assertIn("metal_shv", by_id)
        col = by_id["metal_col"]
        shv = by_id["metal_shv"]

        err_col_xy = math.hypot(col["centroid_10db_xyz_m"][0] - 0.35, col["centroid_10db_xyz_m"][1] - 1.15)
        err_shv_3d = math.sqrt(
            (shv["centroid_10db_xyz_m"][0] - 0.90) ** 2
            + (shv["centroid_10db_xyz_m"][1] - 0.75) ** 2
            + (shv["centroid_10db_xyz_m"][2] - 0.35) ** 2
        )
        self.assertLessEqual(err_col_xy, 0.055)
        self.assertLessEqual(err_shv_3d, 0.060)
        self.assertGreaterEqual(col["delta_z_10db_m"] - shv["delta_z_10db_m"], 0.08)

        diag_by_id = {d["object_id"]: d for d in self.q3m_res["shadow_diagnostics"]}
        self.assertTrue(diag_by_id["metal_col"]["shadow_confirmed"])
        self.assertLessEqual(diag_by_id["metal_col"]["shadow_ratio_db"], -6.0)
        self.assertLess(diag_by_id["metal_shv"]["shadow_ratio_db"], -2.0)

    def test_validator_rejects_contract_violations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            copy_dir = Path(td) / "case"
            shutil.copytree(self.out_dir, copy_dir)
            self.assertEqual(validate_output_dir(copy_dir)["status"], "ALL_Q2_Q3_CONTRACT_CHECKS_PASSED")

            # Negative case 1: tamper shadow_unocc_global_med
            m_path = copy_dir / "q3_metal_results.json"
            bad_m = json.loads(m_path.read_text(encoding="utf-8"))
            bad_m["shadow_unocc_global_med"] *= 1.5
            m_path.write_text(json.dumps(bad_m), encoding="utf-8")
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)
            m_path.write_text((self.out_dir / "q3_metal_results.json").read_text(encoding="utf-8"), encoding="utf-8")

            # Negative case 2: drop mandatory image_row3_coh from q2_arrays.npz
            q2_npz = copy_dir / "q2_arrays.npz"
            with np.load(q2_npz, allow_pickle=False) as src:
                reduced = {k: src[k] for k in src.files if k != "image_row3_coh"}
            np.savez_compressed(q2_npz, **reduced)
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
