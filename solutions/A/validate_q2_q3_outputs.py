#!/usr/bin/env python3
"""Contract validator for Q2/Q3 synthetic output JSON and NPZ artifacts against PR #38 schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from a_q2q3_common import all_arrays_finite_and_valid, arrays_dict_sha256


CONTRACT_JSON_PATH = Path(__file__).resolve().parent / "q2_q3_output_contract.json"

REQUIRED_UPSTREAM_KEYS = (
    "phase",
    "implementation_sha",
    "main_commit",
    "q1_frozen_config_path",
    "q1_frozen_config_sha256",
    "d0_contract_version",
    "d1_contract_version",
    "groups_used",
    "anomaly_isolation",
    "arrays_sha256",
    "arrays_sha256_scope",
    "provenance",
    "finite",
    "status",
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _validate_generation_provenance(results: dict[str, Any], contract_sha256: str) -> None:
    phase = results["phase"]
    sha = str(results["implementation_sha"])
    if not _HEX40.fullmatch(sha):
        raise AssertionError(f"{phase}: implementation_sha must be a full 40-char lowercase hex SHA, got {sha!r}")
    prov = results["provenance"]
    if not isinstance(prov, dict):
        raise AssertionError(f"{phase}.provenance must be a dict")
    if prov.get("implementation_sha") != sha:
        raise AssertionError(f"{phase}.provenance.implementation_sha != implementation_sha")
    if prov.get("implementation_sha_kind") != "generation_code_commit":
        raise AssertionError(f"{phase}.provenance.implementation_sha_kind must be generation_code_commit")
    if not isinstance(prov.get("git_dirty"), bool):
        raise AssertionError(f"{phase}.provenance.git_dirty must be a bool")
    if prov.get("applies_to_phase") != phase:
        raise AssertionError(f"{phase}.provenance.applies_to_phase mismatch")
    generated_at = str(prov.get("generated_at", ""))
    try:
        stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssertionError(f"{phase}.provenance.generated_at is not ISO-8601: {generated_at!r}") from exc
    if stamp.tzinfo is None:
        raise AssertionError(f"{phase}.provenance.generated_at must carry a UTC/offset timezone")
    if stamp.astimezone(timezone.utc).isoformat() == "":
        raise AssertionError(f"{phase}.provenance.generated_at invalid")
    if "run_q2_q3_synthetic.py" not in str(prov.get("command", "")):
        raise AssertionError(f"{phase}.provenance.command must name run_q2_q3_synthetic.py")
    if prov.get("generator_script") != "solutions/A/run_q2_q3_synthetic.py":
        raise AssertionError(f"{phase}.provenance.generator_script mismatch")
    if not str(prov.get("preset", "")):
        raise AssertionError(f"{phase}.provenance.preset must be non-empty")
    if prov.get("contract_sha256") != contract_sha256:
        raise AssertionError(f"{phase}.provenance.contract_sha256 does not match the delivered contract")
    env = prov.get("environment")
    if not isinstance(env, dict):
        raise AssertionError(f"{phase}.provenance.environment must be a dict")
    for env_key in ("python", "numpy", "platform", "byte_order"):
        if not str(env.get(env_key, "")):
            raise AssertionError(f"{phase}.provenance.environment missing {env_key!r}")
    fixture = prov.get("input_fixture")
    if not isinstance(fixture, dict) or fixture.get("real_dat_files_read") != 0:
        raise AssertionError(f"{phase}.provenance.input_fixture must declare real_dat_files_read=0")


def _validate_arrays_scope(results: dict[str, Any], arrays: dict[str, np.ndarray]) -> None:
    phase = results["phase"]
    scope = results["arrays_sha256_scope"]
    if not isinstance(scope, dict):
        raise AssertionError(f"{phase}.arrays_sha256_scope must be a dict")
    if scope.get("algorithm") != "sha256":
        raise AssertionError(f"{phase}.arrays_sha256_scope.algorithm must be sha256")
    covered = list(scope.get("covered_arrays", []))
    if covered != sorted(arrays.keys()):
        raise AssertionError(
            f"{phase}.arrays_sha256_scope.covered_arrays {covered} != actual NPZ arrays {sorted(arrays.keys())}"
        )
    if int(scope.get("array_count", -1)) != len(covered):
        raise AssertionError(f"{phase}.arrays_sha256_scope.array_count mismatch")
    for key in ("aggregate_definition", "per_array_definition", "covers", "cross_run_policy", "file_level_ledger"):
        if not str(scope.get(key, "")):
            raise AssertionError(f"{phase}.arrays_sha256_scope missing {key!r}")
    if not isinstance(scope.get("excludes"), list) or not scope["excludes"]:
        raise AssertionError(f"{phase}.arrays_sha256_scope.excludes must be a non-empty list")


def _validate_anomaly_provenance(results: dict[str, Any]) -> None:
    phase = results["phase"]
    anomaly = results["anomaly_isolation"]
    if not isinstance(anomaly, dict):
        raise AssertionError(f"{phase}.anomaly_isolation must be a dict")
    provenance = anomaly.get("provenance")
    if not isinstance(provenance, dict):
        raise AssertionError(f"{phase}.anomaly_isolation.provenance must be a dict")
    for stat in anomaly:
        if stat == "provenance":
            continue
        entry = provenance.get(stat)
        if not isinstance(entry, dict):
            raise AssertionError(f"{phase}.anomaly_isolation.provenance missing entry for {stat!r}")
        for field in ("source_path", "field", "derivation"):
            if not str(entry.get(field, "")).strip():
                raise AssertionError(
                    f"{phase}.anomaly_isolation.provenance[{stat!r}] missing non-empty {field!r}"
                )
    if phase == "Q3-Metal" and isinstance(anomaly.get("group8_sync_common"), bool):
        raise AssertionError(f"{phase}.anomaly_isolation.group8_sync_common must be a numeric count or status dict")


def _lookup_dotted(obj: dict[str, Any], key: str) -> Any:
    cur: Any = obj
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"Missing required field path {key!r} (failed at {part!r})")
        cur = cur[part]
    return cur


def _assert_monotonic_grid(arr: np.ndarray, name: str) -> None:
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError(f"Grid {name} must be 1D with >=2 points, got {arr.shape}")
    if arr.dtype != np.float64:
        raise ValueError(f"Grid {name} dtype must be float64, got {arr.dtype}")
    if not np.all(np.diff(arr) > 0.0):
        raise ValueError(f"Grid {name} is not strictly ascending")


def _validate_single_contract(
    contract_section: dict[str, Any],
    results: dict[str, Any],
    arrays: dict[str, np.ndarray],
    expected_phase: str,
    energy_prefixes: tuple[str, ...],
    allowed_statuses: set[str],
    contract_sha256: str,
) -> None:
    for up_key in REQUIRED_UPSTREAM_KEYS:
        if up_key not in results:
            raise AssertionError(f"{expected_phase}: missing upstream key {up_key!r}")
    if results["phase"] != expected_phase:
        raise AssertionError(f"Expected phase={expected_phase!r}, got {results['phase']!r}")
    if results["status"] not in allowed_statuses:
        raise AssertionError(f"{expected_phase}: invalid status {results['status']!r}; allowed={sorted(allowed_statuses)}")
    if results.get("real_dat_files_read") != 0:
        raise AssertionError(f"{expected_phase}: real_dat_files_read must be 0")
    if not bool(results["finite"]):
        raise AssertionError(f"{expected_phase}: finite flag is False")

    _validate_generation_provenance(results, contract_sha256)
    _validate_arrays_scope(results, arrays)
    _validate_anomaly_provenance(results)

    if not all_arrays_finite_and_valid(arrays, energy_prefixes):
        raise AssertionError(f"{expected_phase}: non-finite array or negative energy detected")

    recomputed_sha = arrays_dict_sha256(arrays)
    if results["arrays_sha256"] != recomputed_sha:
        raise AssertionError(f"{expected_phase}: arrays_sha256 mismatch ({results['arrays_sha256']} != {recomputed_sha})")

    # Verify grid_spec axis counts and uniform spacing match actual NPZ coordinate grids
    gs = results["grid_spec"]
    for axis_char, arr_key in (("x", "x_grid_m"), ("y", "y_grid_m"), ("z", "z_grid_m")):
        if arr_key in arrays:
            arr = arrays[arr_key]
            if int(gs[f"n{axis_char}"]) != int(arr.size):
                raise AssertionError(f"{expected_phase}.grid_spec.n{axis_char} != {arr_key}.size")
            if not math.isclose(float(arr[0]), float(gs[f"{axis_char}_range_m"][0]), abs_tol=1e-9):
                raise AssertionError(f"{expected_phase}.{arr_key}[0] mismatch with {axis_char}_range_m[0]")
            if not math.isclose(float(arr[-1]), float(gs[f"{axis_char}_range_m"][1]), abs_tol=1e-9):
                raise AssertionError(f"{expected_phase}.{arr_key}[-1] mismatch with {axis_char}_range_m[1]")
            diffs = np.diff(arr)
            if not np.allclose(diffs, float(gs[f"d{axis_char}_m"]), atol=1e-9):
                raise AssertionError(f"{expected_phase}.{arr_key} spacing != d{axis_char}_m")

    # Check JSON fields and nested keys against schema
    for field_path, meta in contract_section["json_fields"].items():
        val = _lookup_dotted(results, field_path)
        if "keys" in meta:
            if not isinstance(val, dict):
                raise AssertionError(f"{expected_phase}.{field_path} must be a dict")
            for sub_key in meta["keys"]:
                if sub_key not in val:
                    raise AssertionError(f"{expected_phase}.{field_path} missing key {sub_key!r}")
        if "item_keys" in meta:
            if not isinstance(val, list) or not val:
                raise AssertionError(f"{expected_phase}.{field_path} must be a non-empty list")
            for idx, item in enumerate(val):
                for sub_key in meta["item_keys"]:
                    if sub_key not in item:
                        raise AssertionError(f"{expected_phase}.{field_path}[{idx}] missing key {sub_key!r}")

    # Check NPZ arrays and shapes
    dim_sizes: dict[str, int] = {}
    if "x_grid_m" in arrays:
        _assert_monotonic_grid(arrays["x_grid_m"], f"{expected_phase}.x_grid_m")
        dim_sizes["N_x"] = int(arrays["x_grid_m"].size)
    if "y_grid_m" in arrays:
        _assert_monotonic_grid(arrays["y_grid_m"], f"{expected_phase}.y_grid_m")
        dim_sizes["N_y"] = int(arrays["y_grid_m"].size)
    if "z_grid_m" in arrays:
        _assert_monotonic_grid(arrays["z_grid_m"], f"{expected_phase}.z_grid_m")
        dim_sizes["N_z"] = int(arrays["z_grid_m"].size)
    if "y_wall_band_m" in arrays:
        _assert_monotonic_grid(arrays["y_wall_band_m"], f"{expected_phase}.y_wall_band_m")
        dim_sizes["N_y_wall"] = int(arrays["y_wall_band_m"].size)
    if "tau_curve_s" in arrays:
        _assert_monotonic_grid(arrays["tau_curve_s"], f"{expected_phase}.tau_curve_s")
        dim_sizes["K_tau"] = int(arrays["tau_curve_s"].size)

    for arr_key, meta in contract_section["npz_arrays"].items():
        if arr_key not in arrays:
            raise AssertionError(f"{expected_phase}: missing NPZ array {arr_key!r}")
        arr = arrays[arr_key]
        if meta["dtype"] == "float64" and arr.dtype != np.float64:
            raise AssertionError(f"{expected_phase}.{arr_key} dtype must be float64, got {arr.dtype}")
        expected_shape = tuple(
            dim_sizes[d] if isinstance(d, str) else int(d) for d in meta["shape"]
        )
        if arr.shape != expected_shape:
            raise AssertionError(f"{expected_phase}.{arr_key} shape {arr.shape} != expected {expected_shape}")
        if arr_key.startswith(energy_prefixes) and float(np.min(arr)) < 0.0:
            raise AssertionError(f"{expected_phase}.{arr_key} contains negative energy values")


def validate_output_dir(out_dir: Path, contract_path: Path = CONTRACT_JSON_PATH) -> dict[str, Any]:
    """Validate all Q2/Q3 JSON + NPZ outputs in `out_dir` against `q2_q3_output_contract.json`."""
    schema = json.loads(contract_path.read_text(encoding="utf-8"))

    # Verify contract paper slots remain untouched as [待补]
    for slot, slot_meta in schema["paper_slots"].items():
        if slot_meta["status"] != "[待补]":
            raise AssertionError(f"Paper slot {slot} status changed from [待补]: {slot_meta['status']!r}")

    bundles = {
        "q2_contract": ("Q2", "q2_results.json", "q2_arrays.npz", ("image_",)),
        "q3_wall_contract": ("Q3-Wall", "q3_wall_results.json", "q3_wall_arrays.npz", ("image_", "slice_", "proj_")),
        "q3_metal_contract": ("Q3-Metal", "q3_metal_results.json", "q3_metal_arrays.npz", ("image_", "shadow_profile_")),
    }

    loaded_results: dict[str, dict[str, Any]] = {}
    loaded_arrays: dict[str, dict[str, np.ndarray]] = {}
    status_enum = schema.get("status_enum")
    if not isinstance(status_enum, list) or not status_enum:
        raise AssertionError("contract must declare a non-empty top-level status_enum")
    runtime_enum = schema["unit_conventions"]["runtime_status_enum"]
    if set(status_enum) != set(runtime_enum):
        raise AssertionError("contract status_enum and unit_conventions.runtime_status_enum disagree")
    allowed_statuses = set(status_enum)
    contract_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()

    for contract_key, (phase, json_name, npz_name, prefixes) in bundles.items():
        json_path = out_dir / json_name
        npz_path = out_dir / npz_name
        if not json_path.exists() or not npz_path.exists():
            raise FileNotFoundError(f"Missing {json_path} or {npz_path}")
        res = json.loads(json_path.read_text(encoding="utf-8"))
        with np.load(npz_path, allow_pickle=False) as npz:
            arrs = {k: npz[k] for k in npz.files}
        _validate_single_contract(
            schema[contract_key], res, arrs, phase, prefixes, allowed_statuses, contract_sha256
        )
        loaded_results[contract_key] = res
        loaded_arrays[contract_key] = arrs

    # Verify per-file SHA256SUMS.txt ledger when present
    sha_file = out_dir / "SHA256SUMS.txt"
    if sha_file.exists():
        for line in sha_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            digest, fname = line.split(None, 1)
            target = out_dir / fname.strip()
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != digest:
                raise AssertionError(f"SHA256SUMS mismatch for {fname}: {actual} != {digest}")

    # Cross-check Q2 gain bounds and Q3 reconciliation + deterministic slice_xy_z4 + 3D projections
    q2_res = loaded_results["q2_contract"]
    q2_arr = loaded_arrays["q2_contract"]
    if float(np.max(q2_arr["w_comp_curve"])) > float(q2_res["gain_params"]["g_cap"]) + 1e-12:
        raise AssertionError("Q2 w_comp_curve exceeds g_cap")
    if float(np.min(q2_arr["w_comp_curve"])) < 1.0 - 1e-12:
        raise AssertionError("Q2 w_comp_curve drops below 1.0")

    q3w_res = loaded_results["q3_wall_contract"]
    q3w_arr = loaded_arrays["q3_wall_contract"]
    if not bool(q3w_res["q2_q3_reconciliation"]["passed_le_2cm"]):
        raise AssertionError("Q2/Q3 air-segment reconciliation failed <= 2.0 cm check")

    # Verify slice_xy_z4 strictly from image_3d_coh and z_grid_m using slice_z4_spec
    sz = q3w_res["slice_z4_spec"]
    lo, hi = int(sz["z_low_idx"]), int(sz["z_high_idx"])
    w_hi = float(sz["weight_high"])
    expected_slice = (1.0 - w_hi) * q3w_arr["image_3d_coh"][lo] + w_hi * q3w_arr["image_3d_coh"][hi]
    if not np.allclose(q3w_arr["slice_xy_z4"], expected_slice, atol=1e-12, rtol=1e-12):
        raise AssertionError("Q3-Wall slice_xy_z4 does not match slice_z4_spec linear interpolation of image_3d_coh")
    if not np.allclose(q3w_arr["proj_xy_max"], np.max(q3w_arr["image_3d_coh"], axis=0), atol=1e-12):
        raise AssertionError("Q3-Wall proj_xy_max != max(image_3d_coh, axis=0)")
    if not np.allclose(q3w_arr["proj_xz_max"], np.max(q3w_arr["image_3d_coh"], axis=1), atol=1e-12):
        raise AssertionError("Q3-Wall proj_xz_max != max(image_3d_coh, axis=1)")
    if not np.allclose(q3w_arr["proj_yz_max"], np.max(q3w_arr["image_3d_coh"], axis=2), atol=1e-12):
        raise AssertionError("Q3-Wall proj_yz_max != max(image_3d_coh, axis=2)")

    # Strict PR #38 multi-target Fig 3-2 check on Q3-Metal
    q3m_res = loaded_results["q3_metal_contract"]
    q3m_arr = loaded_arrays["q3_metal_contract"]
    axis_spec = q3m_res["shadow_profile_axis_spec"]
    idx0 = int(axis_spec["y_wall_band_idx_start"])
    idx1 = int(axis_spec["y_wall_band_idx_end"])
    if not np.array_equal(q3m_arr["y_wall_band_m"], q3m_arr["y_grid_m"][idx0:idx1]):
        raise AssertionError("Q3-Metal y_wall_band_m != y_grid_m[idx_start:idx_end]")

    if axis_spec["ref_energy_key"] != "shadow_unocc_global_med":
        raise AssertionError("Unexpected ref_energy_key in shadow_profile_axis_spec")
    if axis_spec["multi_target_rule"] != "exclude_union_of_all_metal_x_boxes":
        raise AssertionError("Unexpected multi_target_rule in shadow_profile_axis_spec")

    xg_m = q3m_arr["x_grid_m"]
    prof = q3m_arr["shadow_profile_x_y"]
    objs = q3m_res["metal_objects"]
    diags = q3m_res["shadow_diagnostics"]
    if {o["object_id"] for o in objs} != {d["object_id"] for d in diags}:
        raise AssertionError("Q3-Metal object_id set mismatch between metal_objects and shadow_diagnostics")

    unocc_col_mask = np.array(
        [
            not any(o["bbox_10db_m"][0] - 1e-9 <= float(xi) <= o["bbox_10db_m"][1] + 1e-9 for o in objs)
            for xi in xg_m
        ],
        dtype=bool,
    )
    if not np.any(unocc_col_mask):
        raise AssertionError("No unoccluded columns remaining after excluding union of metal x-boxes")
    recomputed_global_med = float(np.median(prof[:, unocc_col_mask]))
    if not math.isclose(recomputed_global_med, float(q3m_res["shadow_unocc_global_med"]), rel_tol=1e-9, abs_tol=1e-12):
        raise AssertionError(
            f"shadow_unocc_global_med mismatch: recomputed {recomputed_global_med} != reported {q3m_res['shadow_unocc_global_med']}"
        )

    # Verify per-object sideband reference and ShadowRatio formulas
    half_w = float(axis_spec["per_object_unocc_window_half_width_m"])
    obj_by_id = {o["object_id"]: o for o in objs}
    for diag in diags:
        obj = obj_by_id[diag["object_id"]]
        px = float(obj["peak_xyz_m"][0])
        bx0, bx1 = float(obj["bbox_10db_m"][0]), float(obj["bbox_10db_m"][1])
        obj_cols = (xg_m >= bx0 - 1e-9) & (xg_m <= bx1 + 1e-9)
        if not np.any(obj_cols):
            obj_cols = np.zeros_like(xg_m, dtype=bool)
            obj_cols[int(np.argmin(np.abs(xg_m - px)))] = True
        re_i_shadow = float(np.mean(prof[:, obj_cols]))
        local_cols = unocc_col_mask & (np.abs(xg_m - px) <= half_w + 1e-9)
        ref_cols = local_cols if np.any(local_cols) else unocc_col_mask
        re_i_unocc = float(np.median(prof[:, ref_cols]))
        re_ratio = 10.0 * math.log10(max(re_i_shadow, 1e-30) / max(re_i_unocc, 1e-30))
        if not math.isclose(re_i_unocc, float(diag["i_unocc_med"]), rel_tol=1e-9, abs_tol=1e-12):
            raise AssertionError(f"i_unocc_med mismatch for {diag['object_id']}")
        if not math.isclose(re_ratio, float(diag["shadow_ratio_db"]), rel_tol=1e-9, abs_tol=1e-12):
            raise AssertionError(f"shadow_ratio_db mismatch for {diag['object_id']}")

    # Verify every paper slot's required fields exist in actual JSON/NPZ outputs
    for slot, slot_meta in schema["paper_slots"].items():
        ck = slot_meta["source_contract"]
        available = set(loaded_results[ck].keys()) | set(loaded_arrays[ck].keys())
        for req in slot_meta["required_fields"]:
            if req not in available:
                raise AssertionError(f"Paper slot {slot} missing runtime output field {req!r} in {ck}")

    return {
        "validated_dir": str(out_dir),
        "q2_selected_alpha_per_ns": q2_res["gain_selection"]["selected_alpha_per_ns"],
        "q2_max_row_diff_cm": q2_res["row_consistency"]["max_row_diff_cm"],
        "q3_wall_reconcile_max_cm": q3w_res["q2_q3_reconciliation"]["air_segment_max_diff_cm"],
        "q3_metal_objects_count": len(objs),
        "q3_metal_shadow_unocc_global_med": float(q3m_res["shadow_unocc_global_med"]),
        "status": "ALL_Q2_Q3_CONTRACT_CHECKS_PASSED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Q2/Q3 synthetic outputs against schema.")
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate_output_dir(args.dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
