#!/usr/bin/env python3
"""Unit and end-to-end synthetic regression suite for Q2 (2D) & Q3 (3D) baseline solvers."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from a_q2q3_common import interval_union_mask, save_npz_deterministic
from run_q2_q3_synthetic import run_synthetic_suite
from validate_q2_q3_outputs import validate_output_dir


REPO_ROOT = Path(__file__).resolve().parents[2]
STD_RESULTS_DIR = REPO_ROOT / "experiments" / "A" / "A-Q2Q3-SYN" / "results"


class TestQ2Q3SyntheticSolvers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_root = tempfile.TemporaryDirectory()
        cls.out_dir = Path(cls._tmp_root.name) / "results"
        cls.summary = run_synthetic_suite(cls.out_dir, preset="minimal")
        cls.q2_res = json.loads((cls.out_dir / "q2_results.json").read_text(encoding="utf-8"))
        cls.q3w_res = json.loads((cls.out_dir / "q3_wall_results.json").read_text(encoding="utf-8"))
        cls.q3m_res = json.loads((cls.out_dir / "q3_metal_results.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_root.cleanup()

    def test_committed_standard_contract_grids_and_hashes(self) -> None:
        if not (STD_RESULTS_DIR / "q2_results.json").exists():
            self.skipTest("Standard results directory not yet generated")
        summary = validate_output_dir(STD_RESULTS_DIR)
        self.assertEqual(summary["status"], "ALL_Q2_Q3_CONTRACT_CHECKS_PASSED")

        q2 = json.loads((STD_RESULTS_DIR / "q2_results.json").read_text(encoding="utf-8"))
        q3w = json.loads((STD_RESULTS_DIR / "q3_wall_results.json").read_text(encoding="utf-8"))
        q3m = json.loads((STD_RESULTS_DIR / "q3_metal_results.json").read_text(encoding="utf-8"))

        self.assertEqual((q2["grid_spec"]["ny"], q2["grid_spec"]["nx"]), (251, 161))
        self.assertEqual((q3w["grid_spec"]["nz"], q3w["grid_spec"]["ny"], q3w["grid_spec"]["nx"]), (31, 126, 81))
        self.assertEqual((q3m["grid_spec"]["nz"], q3m["grid_spec"]["ny"], q3m["grid_spec"]["nx"]), (31, 126, 66))
        self.assertEqual([obj["object_id"] for obj in q3m["metal_objects"]], ["metal_col", "metal_shv"])

        with np.load(STD_RESULTS_DIR / "q2_arrays.npz", allow_pickle=False) as d2:
            self.assertEqual(d2["image_after_gain_coh"].shape, (251, 161))
            self.assertAlmostEqual(float(d2["y_grid_m"][0]), 0.0)
            self.assertAlmostEqual(float(d2["y_grid_m"][-1]), 2.50)

        with np.load(STD_RESULTS_DIR / "q3_wall_arrays.npz", allow_pickle=False) as d3w:
            self.assertEqual(d3w["image_3d_coh"].shape, (31, 126, 81))
            self.assertEqual(d3w["slice_xy_z4"].shape, (126, 81))

        with np.load(STD_RESULTS_DIR / "q3_metal_arrays.npz", allow_pickle=False) as d3m:
            self.assertEqual(d3m["image_3d_coh"].shape, (31, 126, 66))

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

    def test_q3_wall_reconciliation_dual_metal_and_dynamic_anomaly(self) -> None:
        rec = self.q3w_res["q2_q3_reconciliation"]
        self.assertTrue(rec["passed_le_2cm"], f"Reconciliation diff too large: {rec}")
        self.assertGreater(self.q3w_res["wall_b_3d"]["pbr_b_coh_db"], self.q3w_res["wall_b_3d"]["pbr_b_env_db"])

        anom = self.q3m_res["anomaly_isolation"]
        self.assertEqual(anom["orphan_skipped"]["status"], "not_covered_by_synthetic_fixture")
        self.assertEqual(anom["group8_int16_min_count"]["status"], "not_covered_by_synthetic_fixture")
        self.assertEqual(anom["group8_sync_common"], 3)

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

    def test_air_segment_boundary_tolerance_and_deterministic_npz(self) -> None:
        xg = np.round(np.linspace(-0.20, 1.40, 41), 6)
        noisy_ranges = [[-0.16, 0.12000000000000001], [1.2000000000000002, 1.3599999999999999]]
        mask = interval_union_mask(xg, noisy_ranges)
        # Ensure boundary points 1.20 and 1.36 are NOT dropped by IEEE-754 rounding noise
        for exact_val in (-0.16, 0.12, 1.20, 1.36):
            idx = int(np.argmin(np.abs(xg - exact_val)))
            self.assertAlmostEqual(float(xg[idx]), exact_val)
            self.assertTrue(bool(mask[idx]), f"Boundary column x={exact_val} dropped by mask")

        with tempfile.TemporaryDirectory() as td:
            p1 = Path(td) / "a.npz"
            p2 = Path(td) / "b.npz"
            arr = {"x": np.linspace(0.0, 1.0, 11)}
            save_npz_deterministic(p1, arr)
            save_npz_deterministic(p2, arr)
            self.assertEqual(hashlib.sha256(p1.read_bytes()).hexdigest(), hashlib.sha256(p2.read_bytes()).hexdigest())

    def test_g6_g7_g11_provenance_status_and_digest_scope(self) -> None:
        """Lock G6 anomaly provenance, G7 status/generation version, and G11 digest scope."""
        contract = json.loads(
            (REPO_ROOT / "solutions" / "A" / "q2_q3_output_contract.json").read_text(encoding="utf-8")
        )
        bundles = (
            (self.q2_res, "q2_arrays.npz", "Q2"),
            (self.q3w_res, "q3_wall_arrays.npz", "Q3-Wall"),
            (self.q3m_res, "q3_metal_arrays.npz", "Q3-Metal"),
        )
        for res, npz_name, phase in bundles:
            self.assertEqual(res["phase"], phase)
            self.assertRegex(res["implementation_sha"], r"^[0-9a-f]{40}$")
            self.assertIn(res["status"], contract["status_enum"])

            prov = res["provenance"]
            self.assertEqual(prov["implementation_sha"], res["implementation_sha"])
            self.assertEqual(prov["implementation_sha_kind"], "generation_code_commit")
            self.assertEqual(prov["applies_to_phase"], phase)
            self.assertIsInstance(prov["git_dirty"], bool)
            self.assertIn("run_q2_q3_synthetic.py", prov["command"])
            self.assertIn("T", prov["generated_at"])
            self.assertIn("Z", prov["generated_at"])
            self.assertEqual(prov["environment"]["numpy"], np.__version__)
            self.assertEqual(prov["input_fixture"]["real_dat_files_read"], 0)

            scope = res["arrays_sha256_scope"]
            with np.load(self.out_dir / npz_name, allow_pickle=False) as npz:
                self.assertEqual(scope["covered_arrays"], sorted(npz.files))
                self.assertEqual(scope["array_count"], len(npz.files))
            self.assertEqual(scope["algorithm"], "sha256")
            self.assertTrue(scope["excludes"])
            self.assertIn("rtol=1e-9", scope["cross_run_policy"])

        anomaly = self.q3m_res["anomaly_isolation"]
        self.assertEqual(anomaly["group8_sync_common"], 3)
        expected_stats = {
            "real_dat_files_read",
            "packet_mismatch_groups",
            "orphan_skipped",
            "group8_sync_common",
            "group8_int16_min_count",
            "group8_d1_gate_action",
        }
        self.assertEqual(set(anomaly["provenance"]), expected_stats)
        for stat, entry in anomaly["provenance"].items():
            self.assertTrue(entry["source_path"].strip(), stat)
            self.assertTrue(entry["field"].strip(), stat)
            self.assertTrue(entry["derivation"].strip(), stat)
        self.assertEqual(
            anomaly["provenance"]["group8_sync_common"]["source_path"],
            "synthetic_scene#j_p_common[7]",
        )
        self.assertEqual(anomaly["provenance"]["group8_sync_common"]["field"], "j_p_common[7]")

    def test_validator_rejects_provenance_and_scope_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            copy_dir = Path(td) / "case"
            shutil.copytree(self.out_dir, copy_dir)
            q2_path = copy_dir / "q2_results.json"
            sums_path = copy_dir / "SHA256SUMS.txt"
            original_q2 = q2_path.read_bytes()
            original_sums = sums_path.read_bytes()

            def restore() -> None:
                q2_path.write_bytes(original_q2)
                sums_path.write_bytes(original_sums)

            def tamper(mutator) -> None:
                bad = json.loads(original_q2.decode("utf-8"))
                mutator(bad)
                payload = (json.dumps(bad, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                q2_path.write_bytes(payload)
                # Keep the byte ledger consistent with the tampered JSON so the validator reaches
                # the specific provenance/scope check instead of failing early on SHA256SUMS.
                digest = hashlib.sha256(payload).hexdigest()
                lines = original_sums.decode("utf-8").splitlines()
                rewritten = [
                    f"{digest}  q2_results.json" if line.split(None, 1)[1].strip() == "q2_results.json" else line
                    for line in lines
                ]
                sums_path.write_bytes(("\n".join(rewritten) + "\n").encode("utf-8"))

            # Drop G7 generation provenance
            tamper(lambda bad: bad.pop("provenance"))
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)
            restore()

            # G11 scope must cover exactly the NPZ arrays
            def drop_scope_entry(bad) -> None:
                scope = bad["arrays_sha256_scope"]
                scope["covered_arrays"] = scope["covered_arrays"][:-1]

            tamper(drop_scope_entry)
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)
            restore()

            # G6 anomaly statistics must carry source_path/field provenance
            def drop_anomaly_provenance(bad) -> None:
                del bad["anomaly_isolation"]["provenance"]["packet_mismatch_groups"]

            tamper(drop_anomaly_provenance)
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)
            restore()

            self.assertEqual(validate_output_dir(copy_dir)["status"], "ALL_Q2_Q3_CONTRACT_CHECKS_PASSED")

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
            save_npz_deterministic(q2_npz, reduced)
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)
            shutil.copy2(self.out_dir / "q2_arrays.npz", q2_npz)

            # Negative case 3: tamper slice_xy_z4 so it violates slice_z4_spec linear interpolation
            q3w_npz = copy_dir / "q3_wall_arrays.npz"
            with np.load(q3w_npz, allow_pickle=False) as src:
                tampered = {k: src[k].copy() for k in src.files}
            tampered["slice_xy_z4"] += 100.0
            save_npz_deterministic(q3w_npz, tampered)
            with self.assertRaises(AssertionError):
                validate_output_dir(copy_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
