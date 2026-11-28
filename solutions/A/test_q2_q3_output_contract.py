#!/usr/bin/env python3
"""Unit verification for Q2/Q3 output-field and paper figure/table slot contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_JSON = REPO_ROOT / "solutions" / "A" / "q2_q3_output_contract.json"
CONTRACT_MD = REPO_ROOT / "paper" / "A" / "Q2_Q3_OUTPUT_FIGURE_CONTRACT.md"
CHECKLIST_MD = REPO_ROOT / "paper" / "A" / "RESULTS_AND_FIGURES_CHECKLIST.md"
CH57_MD = REPO_ROOT / "paper" / "A" / "draft_ch5_7.md"


class TestQ2Q3OutputContract(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
        self.md = CONTRACT_MD.read_text(encoding="utf-8")
        self.checklist = CHECKLIST_MD.read_text(encoding="utf-8")
        self.ch57 = CH57_MD.read_text(encoding="utf-8")

    def test_all_q2_q3_paper_slots_present_and_tbd(self) -> None:
        expected_slots = ["Fig 2-1", "Fig 2-2", "Table 2-1", "Fig 3-1", "Table 3-1", "Fig 3-2", "Table 3-2"]
        self.assertEqual(sorted(self.data["paper_slots"].keys()), sorted(expected_slots))
        for slot in expected_slots:
            spec = self.data["paper_slots"][slot]
            self.assertEqual(spec["status"], "[待补]")
            self.assertIn(slot, self.md)
            self.assertIn(slot, self.checklist)
            self.assertIn(slot, self.ch57)
            src = self.data[spec["source_contract"]]
            available = set(src["json_fields"].keys()) | set(src["npz_arrays"].keys())
            for req in spec["required_fields"]:
                self.assertIn(req, available, f"{slot} required field {req} missing in {spec['source_contract']}")

    def test_units_and_defaults_consistent_with_model_specs(self) -> None:
        q2 = self.data["q2_contract"]["json_fields"]
        self.assertEqual(q2["row_id"]["default"], 4)
        self.assertEqual(q2["rx_indices"]["default"], [24, 25, 26, 28, 29, 30, 31])
        self.assertAlmostEqual(q2["z_slice_m"]["default"], 0.545)
        self.assertAlmostEqual(q2["gain_params.g_cap"]["default"], 20.0)
        self.assertEqual(q2["gain_params.alpha_gain_per_ns"]["unit"], "ns^-1")
        self.assertIn("delta_ba_db", q2["metrics_after_gain_coh"]["keys"])
        self.assertIn("eps_r_diag", q2["wall_b_apparent"]["keys"])

        q2_npz = self.data["q2_contract"]["npz_arrays"]
        for row_key in ("image_after_gain_coh", "image_row3_coh", "image_row5_coh"):
            self.assertIn(row_key, self.data["paper_slots"]["Fig 2-2"]["required_fields"])
            self.assertFalse(q2_npz[row_key].get("optional", False), f"{row_key} must be mandatory for Fig 2-2")
        self.assertIn("row_4_wall_b_y_m", q2["row_consistency"]["keys"])

        q3w = self.data["q3_wall_contract"]["json_fields"]
        self.assertIn("passed_le_2cm", q3w["q2_q3_reconciliation"]["keys"])

        q3m = self.data["q3_metal_contract"]["json_fields"]
        q3m_npz = self.data["q3_metal_contract"]["npz_arrays"]
        self.assertIn("shadow_ratio_db", q3m["shadow_diagnostics"]["item_keys"])
        self.assertIn("centroid_10db_xyz_m", q3m["metal_objects"]["item_keys"])

        # Fig 3-2 vertical axis mapping + linear-to-dB reference contract
        self.assertEqual(q3m_npz["y_wall_band_m"]["shape"], ["N_y_wall"])
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["shape"], ["N_y_wall", "N_x"])
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["y_axis_key"], "y_wall_band_m")
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["x_axis_key"], "x_grid_m")
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["db_ref_key"], "i_unocc_med")
        self.assertIn("y_wall_band_m", self.data["paper_slots"]["Fig 3-2"]["required_fields"])
        self.assertIn("shadow_profile_axis_spec", self.data["paper_slots"]["Fig 3-2"]["required_fields"])
        self.assertEqual(q3m["shadow_profile_axis_spec"]["defaults"]["ref_energy_key"], "i_unocc_med")

        # All NPZ energy arrays store linear normalized energy with locked dB plotting reference
        db_norm = self.data["unit_conventions"]["plot_db_normalization"]
        self.assertIn("10 * log10", db_norm["formula"])
        self.assertIn("i_unocc_med", db_norm["fig_3_2_shadow_profile_i_ref"])
        for c_name in ("q2_contract", "q3_wall_contract", "q3_metal_contract"):
            for arr_key, meta in self.data[c_name]["npz_arrays"].items():
                if arr_key.startswith(("image_", "slice_", "proj_", "shadow_profile_")):
                    self.assertEqual(meta["unit"], "normalized_energy", f"{c_name}.{arr_key} must store linear normalized_energy")

    def test_no_unverified_real_dat_results_claimed(self) -> None:
        self.assertEqual(self.data["status"], "contract_only_empirical_slots_tbd")
        self.assertGreaterEqual(self.md.count("[待补]"), 7)
        self.assertIn("ShadowRatio", self.md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
