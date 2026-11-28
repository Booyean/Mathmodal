#!/usr/bin/env python3
"""Reproducible pure-synthetic CLI runner for Problem A Q2 (2D) & Q3 (3D) baseline solvers."""

from __future__ import annotations

import os

for _env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_env] = "1"

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from a_q2_solver import solve_q2_synthetic
from a_q2q3_common import (
    build_synthetic_metal_scene_63rx,
    build_synthetic_wall_scene_63rx,
    canonical_json_bytes,
    save_npz_deterministic,
)
from a_q3_solver import solve_q3_metal_synthetic, solve_q3_wall_synthetic
from validate_q2_q3_outputs import validate_output_dir


PRESETS: dict[str, dict[str, Any]] = {
    "minimal": {
        "q2_dx_m": 0.04,
        "q2_dy_m": 0.02,
        "q3_wall_step_m": (0.04, 0.025, 0.05),
        "q3_metal_step_m": (0.05, 0.05, 0.04),
    },
    "standard": {
        "q2_dx_m": 0.01,
        "q2_dy_m": 0.01,
        "q3_wall_step_m": (0.02, 0.02, 0.02),
        "q3_metal_step_m": (0.02, 0.02, 0.02),
    },
}


def _save_bundle(out_dir: Path, prefix: str, results: dict[str, Any], arrays: dict[str, np.ndarray]) -> list[Path]:
    json_path = out_dir / f"{prefix}_results.json"
    npz_path = out_dir / f"{prefix}_arrays.npz"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_npz_deterministic(npz_path, arrays)
    return [json_path, npz_path]


def run_synthetic_suite(out_dir: Path, preset: str = "standard") -> dict[str, Any]:
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset {preset!r}; choose from {sorted(PRESETS)}")
    cfg = PRESETS[preset]
    out_dir.mkdir(parents=True, exist_ok=True)

    scene_wall = build_synthetic_wall_scene_63rx()
    q2_res, q2_arr = solve_q2_synthetic(scene_wall, dx_m=cfg["q2_dx_m"], dy_m=cfg["q2_dy_m"])
    q3w_res, q3w_arr = solve_q3_wall_synthetic(scene_wall, q2_res, q2_arr, step_m=cfg["q3_wall_step_m"])

    scene_metal = build_synthetic_metal_scene_63rx()
    q3m_res, q3m_arr = solve_q3_metal_synthetic(scene_metal, q2_res, step_m=cfg["q3_metal_step_m"])

    written: list[Path] = []
    written.extend(_save_bundle(out_dir, "q2", q2_res, q2_arr))
    written.extend(_save_bundle(out_dir, "q3_wall", q3w_res, q3w_arr))
    written.extend(_save_bundle(out_dir, "q3_metal", q3m_res, q3m_arr))

    # Deterministic SHA256 ledger over LF-normalized JSON + NPZ artifacts
    sha_lines = []
    for p in sorted(written, key=lambda x: x.name):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        sha_lines.append(f"{digest}  {p.name}")
    (out_dir / "SHA256SUMS.txt").write_bytes(("\n".join(sha_lines) + "\n").encode("utf-8"))

    validation = validate_output_dir(out_dir)
    return {
        "preset": preset,
        "out_dir": str(out_dir),
        "real_dat_files_read": 0,
        "validation": validation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible synthetic Q2/Q3 baseline solvers.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "experiments" / "A" / "A-Q2Q3-SYN" / "results",
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    args = parser.parse_args()
    summary = run_synthetic_suite(args.out, preset=args.preset)
    print(canonical_json_bytes(summary).decode("utf-8"))


if __name__ == "__main__":
    main()
