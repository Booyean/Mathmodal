#!/usr/bin/env python3
"""Unit verification for Q2/Q3 output-field and paper figure/table slot contract."""

from __future__ import annotations

import json
import math
import statistics
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

        # Fig 3-2 vertical axis mapping + unique global multi-target dB reference contract
        self.assertEqual(q3m_npz["y_wall_band_m"]["shape"], ["N_y_wall"])
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["shape"], ["N_y_wall", "N_x"])
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["y_axis_key"], "y_wall_band_m")
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["x_axis_key"], "x_grid_m")
        self.assertEqual(q3m_npz["shadow_profile_x_y"]["db_ref_key"], "shadow_unocc_global_med")
        self.assertEqual(q3m["shadow_unocc_global_med"]["type"], "float")
        self.assertEqual(q3m["shadow_unocc_global_med"]["unit"], "normalized_energy")
        self.assertIn("y_wall_band_m", self.data["paper_slots"]["Fig 3-2"]["required_fields"])
        self.assertIn("shadow_unocc_global_med", self.data["paper_slots"]["Fig 3-2"]["required_fields"])
        self.assertIn("shadow_profile_axis_spec", self.data["paper_slots"]["Fig 3-2"]["required_fields"])
        axis_defaults = q3m["shadow_profile_axis_spec"]["defaults"]
        self.assertEqual(axis_defaults["ref_energy_key"], "shadow_unocc_global_med")
        self.assertEqual(axis_defaults["multi_target_rule"], "exclude_union_of_all_metal_x_boxes")
        self.assertIn("object_id", axis_defaults["per_object_ratio_source"])

        # All NPZ energy arrays store linear normalized energy with locked dB plotting reference
        db_norm = self.data["unit_conventions"]["plot_db_normalization"]
        self.assertIn("10 * log10", db_norm["formula"])
        self.assertIn("shadow_unocc_global_med", db_norm["fig_3_2_shadow_profile_i_ref"])
        self.assertIn("object_id", db_norm["fig_3_2_shadow_profile_i_ref"])
        for c_name in ("q2_contract", "q3_wall_contract", "q3_metal_contract"):
            for arr_key, meta in self.data[c_name]["npz_arrays"].items():
                if arr_key.startswith(("image_", "slice_", "proj_", "shadow_profile_")):
                    self.assertEqual(meta["unit"], "normalized_energy", f"{c_name}.{arr_key} must store linear normalized_energy")

    def test_status_enum_and_generation_provenance_contract(self) -> None:
        status_enum = self.data["status_enum"]
        self.assertIn("synthetic_baseline_only", status_enum)
        self.assertEqual(set(status_enum), set(self.data["unit_conventions"]["runtime_status_enum"]))
        for c_name in ("q2_contract", "q3_wall_contract", "q3_metal_contract"):
            fields = self.data[c_name]["json_fields"]
            prov_keys = fields["provenance"]["keys"]
            for key in ("implementation_sha", "git_dirty", "generated_at", "command", "environment", "contract_sha256"):
                self.assertIn(key, prov_keys)
            scope_keys = fields["arrays_sha256_scope"]["keys"]
            for key in ("algorithm", "covered_arrays", "array_count", "cross_run_policy", "excludes"):
                self.assertIn(key, scope_keys)
        self.assertIn("provenance", self.data["q3_metal_contract"]["json_fields"]["anomaly_isolation"]["keys"])

    def test_no_unverified_real_dat_results_claimed(self) -> None:
        self.assertEqual(self.data["status"], "contract_only_empirical_slots_tbd")
        self.assertGreaterEqual(self.md.count("[待补]"), 7)
        self.assertIn("ShadowRatio", self.md)

    def test_fig3_2_multi_target_distinct_references(self) -> None:
        """Verify whole-map dB uses shadow_unocc_global_med while per-target annotations bind by object_id."""
        axis_defaults = self.data["q3_metal_contract"]["json_fields"]["shadow_profile_axis_spec"]["defaults"]
        ref_key = axis_defaults["ref_energy_key"]
        floor_ratio = axis_defaults["db_floor_ratio"]

        x_grid_m = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.1, 1.2]
        # Energy over wall band: occluded under [0.2,0.4] (0.15) & [0.8,1.0] (0.50);
        # unoccluded x in {0.0, 0.6, 1.1, 1.2} has values [1.0, 2.0, 2.0, 4.0] -> median = 2.0
        shadow_profile_x_y = [
            [1.0, 0.15, 0.15, 2.0, 0.50, 0.50, 2.0, 4.0],
            [1.0, 0.15, 0.15, 2.0, 0.50, 0.50, 2.0, 4.0],
        ]
        metal_objects = [
            {"object_id": "metal_col", "bbox_10db_m": [0.2, 0.4, 1.0, 1.2, 0.25, 0.75]},
            {"object_id": "metal_shv", "bbox_10db_m": [0.8, 1.0, 0.65, 0.85, 0.28, 0.42]},
        ]
        # Distinct per-target i_unocc_med values (1.0 vs 4.0), both != global union-excluded median (2.0)
        shadow_diagnostics = [
            {
                "object_id": "metal_col",
                "i_shadow_bar": 0.15,
                "i_unocc_med": 1.0,
                "shadow_ratio_db": 10.0 * math.log10(0.15 / 1.0),
                "shadow_confirmed": True,
            },
            {
                "object_id": "metal_shv",
                "i_shadow_bar": 0.50,
                "i_unocc_med": 4.0,
                "shadow_ratio_db": 10.0 * math.log10(0.50 / 4.0),
                "shadow_confirmed": True,
            },
        ]

        # Recompute global unoccluded median per rule: exclude union of all detected [x_min, x_max]
        unocc_vals = []
        for row in shadow_profile_x_y:
            for xi, val in zip(x_grid_m, row):
                inside_any = any(obj["bbox_10db_m"][0] <= xi <= obj["bbox_10db_m"][1] for obj in metal_objects)
                if not inside_any:
                    unocc_vals.append(val)
        recomputed_global_med = statistics.median(unocc_vals)
        self.assertAlmostEqual(recomputed_global_med, 2.0)

        def render_fig3_2_db_and_bind(results_json: dict, profile: list[list[float]]) -> tuple[list[list[float]], dict[str, dict]]:
            i_ref = results_json[ref_key]
            floor = floor_ratio * i_ref
            db_map = [[10.0 * math.log10(max(v, floor) / i_ref) for v in row] for row in profile]
            by_id = {item["object_id"]: item for item in results_json["shadow_diagnostics"]}
            return db_map, by_id

        res_order_a = {
            ref_key: recomputed_global_med,
            "shadow_diagnostics": shadow_diagnostics,
        }
        res_order_b = {
            ref_key: recomputed_global_med,
            "shadow_diagnostics": list(reversed(shadow_diagnostics)),
        }
        db_a, bind_a = render_fig3_2_db_and_bind(res_order_a, shadow_profile_x_y)
        db_b, bind_b = render_fig3_2_db_and_bind(res_order_b, shadow_profile_x_y)

        # Whole-map dB grid is invariant to target ordering and anchored to global_med=2.0 (0 dB at val=2.0)
        self.assertEqual(db_a, db_b)
        self.assertAlmostEqual(db_a[0][3], 0.0)
        self.assertAlmostEqual(db_a[0][0], 10.0 * math.log10(1.0 / 2.0))
        self.assertAlmostEqual(db_a[0][7], 10.0 * math.log10(4.0 / 2.0))

        # Per-object annotations bind deterministically by object_id despite distinct i_unocc_med
        self.assertNotAlmostEqual(bind_a["metal_col"]["i_unocc_med"], bind_a["metal_shv"]["i_unocc_med"])
        self.assertAlmostEqual(bind_a["metal_col"]["i_unocc_med"], 1.0)
        self.assertAlmostEqual(bind_b["metal_col"]["i_unocc_med"], 1.0)
        self.assertAlmostEqual(bind_a["metal_shv"]["i_unocc_med"], 4.0)
        self.assertAlmostEqual(bind_b["metal_shv"]["i_unocc_med"], 4.0)
        self.assertAlmostEqual(bind_b["metal_col"]["shadow_ratio_db"], 10.0 * math.log10(0.15 / 1.0))
        self.assertAlmostEqual(bind_b["metal_shv"]["shadow_ratio_db"], 10.0 * math.log10(0.50 / 4.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
