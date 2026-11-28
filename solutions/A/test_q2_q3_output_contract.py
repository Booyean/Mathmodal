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

        q3w = self.data["q3_wall_contract"]["json_fields"]
        self.assertIn("passed_le_2cm", q3w["q2_q3_reconciliation"]["keys"])

        q3m = self.data["q3_metal_contract"]["json_fields"]
        self.assertIn("shadow_ratio_db", q3m["shadow_diagnostics"]["item_keys"])
        self.assertIn("centroid_10db_xyz_m", q3m["metal_objects"]["item_keys"])

    def test_no_unverified_real_dat_results_claimed(self) -> None:
        self.assertEqual(self.data["status"], "contract_only_empirical_slots_tbd")
        self.assertGreaterEqual(self.md.count("[待补]"), 7)
        self.assertIn("ShadowRatio", self.md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
