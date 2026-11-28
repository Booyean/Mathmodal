#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synthetic unit & subprocess tests for Q2/Q3 S1 empirical admission toolchain.

Zero real ``.dat`` files in ``竞赛题目/`` are touched or parsed. Verifies:
1. Full 481 manifest entries vs <=480 protocol-parseable files + 1 zero-byte orphan accounting;
2. D1-audit preflight & dual-process execution WITHOUT any Q1 frozen artifact;
3. Path-guard rejection of symlinks, Windows directory junctions, reparse points, and realpath escapes;
4. CLI guards: missing ``--approval-ref`` (exit 2), ``--overwrite`` protection (exit 2),
   ``--repeat-runs != 2`` on execute (exit 2), missing ``e0c_frozen.json`` on execute (exit 2);
5. Dual-process ``q2q3_repeat.json`` invariants + tamper rejections + end-to-end synthetic execute.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a_e0_s1s2 as E0S  # noqa: E402
import a_q2q3_common as Q23C  # noqa: E402
import a_q2q3_preflight as PF2  # noqa: E402
import e0c_preflight as PF  # noqa: E402
import run_q2_q3_empirical as RUN  # noqa: E402


DAT_MAGIC = 963072


def _make_tmp_dir(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"q2q3_s1_{tag}_"))


def _rmtree_force(path: Path) -> None:
    def _on_err(func: Any, p: str, _exc_info: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_on_err)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(path: Path, rows: List[Dict[str, Any]]) -> str:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["rel_path", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    return PF.manifest_overall_sha256(PF.manifest_rows(path))


def _write_dummy_dat_corpus(
    data_root: Path,
    *,
    n_wall_groups: int,
    n_metal_groups: int,
    include_orphan: bool = True,
) -> Tuple[Path, str, Dict[str, int]]:
    """Create tiny non-empty dummy .dat files + optional 0-byte orphan for preflight accounting tests."""
    wall_dir = data_root / "附件" / "附件3-成像数据" / "墙体"
    metal_dir = data_root / "附件" / "附件3-成像数据" / "金属柱和金属铲"
    wall_dir.mkdir(parents=True, exist_ok=True)
    metal_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for j in range(n_wall_groups):
        prefix = f"2026-11-12-21-{j:02d}-00_16000"
        for r in range(8):
            fp = wall_dir / f"{prefix}_{r}.dat"
            payload = bytes([65 + (r % 16)]) * 64
            fp.write_bytes(payload)
            rows.append(
                {
                    "rel_path": f"附件/附件3-成像数据/墙体/{fp.name}",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )

    for j in range(n_metal_groups):
        prefix = f"2026-11-12-22-{j:02d}-00_16000"
        for r in range(8):
            fp = metal_dir / f"{prefix}_{r}.dat"
            payload = bytes([80 + (r % 16)]) * 64
            fp.write_bytes(payload)
            rows.append(
                {
                    "rel_path": f"附件/附件3-成像数据/金属柱和金属铲/{fp.name}",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )

    if include_orphan:
        orp = metal_dir / "2026-11-12-22-50-31_16000_7.dat"
        orp.write_bytes(b"")
        rows.append(
            {
                "rel_path": f"附件/附件3-成像数据/金属柱和金属铲/{orp.name}",
                "size_bytes": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
            }
        )

    manifest_path = data_root.parent / "a_dat_manifest.csv"
    overall_sha = _write_manifest(manifest_path, rows)
    counts = {
        "manifest_entries_count": len(rows),
        "max_protocol_parseable_files": (n_wall_groups + n_metal_groups) * 8,
        "orphan_files_count": 1 if include_orphan else 0,
        "wall_valid_groups_count": n_wall_groups,
        "wall_files_count": n_wall_groups * 8,
        "metal_valid_groups_count": n_metal_groups,
        "metal_group_files_count": n_metal_groups * 8,
    }
    return manifest_path, overall_sha, counts


def _write_valid_d0_dat(
    path: Path,
    per_pkt_rows8: List[np.ndarray],
    syncs: List[int],
    *,
    inject_46_min_last_pkt: bool = False,
) -> None:
    """Write valid D0-4 .dat file where each packet contains 4 periods (optionally 46 -32768 samples in last pkt)."""
    chunks: List[bytes] = []
    for idx, (rows8, sync) in enumerate(zip(per_pkt_rows8, syncs)):
        block = np.tile(rows8, (1, 4))  # (8, 16000)
        if inject_46_min_last_pkt and idx == len(syncs) - 1:
            for pt_i in range(46):
                block[pt_i % 8, 10 + 300 * pt_i] = np.int16(-32768)
        payload = block.T.astype("<i2").tobytes()
        header = struct.pack("<IIIfIII", DAT_MAGIC, 20 + len(payload), 102, 0.0, sync, 16000, 16)
        chunks.append(header + payload)
    path.write_bytes(b"".join(chunks))


def _build_valid_d0_synthetic_corpus(
    data_root: Path,
    *,
    n_wall: int,
    n_metal: int,
    inject_group8_neg32768: bool = True,
    plant_echoes: bool = False,
) -> Tuple[Path, str, Dict[str, int]]:
    """Build valid D0-4 synthetic Attachment-3 .dat files exercising packet mismatch & -32768."""
    wall_dir = data_root / "附件" / "附件3-成像数据" / "墙体"
    metal_dir = data_root / "附件" / "附件3-成像数据" / "金属柱和金属铲"
    wall_dir.mkdir(parents=True, exist_ok=True)
    metal_dir.mkdir(parents=True, exist_ok=True)

    np_n = 4000
    t_idx = np.arange(np_n, dtype=np.float64)
    ref_wave = np.round(9000.0 * np.cos(2.0 * np.pi * 12.0 * t_idx / np_n)).astype(np.int16)
    base_mat = np.zeros((64, np_n), dtype=np.int16)
    for ch in range(64):
        if ch == 27:
            base_mat[ch] = np.round(15.0 * np.sin(2.0 * np.pi * (ch + 1) * t_idx / np_n)).astype(np.int16)
        else:
            phase = 0.05 * (ch % 8)
            base_mat[ch] = np.round(6000.0 * np.cos(2.0 * np.pi * 12.0 * t_idx / np_n + phase)).astype(np.int16)
    base_mat[28] = ref_wave

    if plant_echoes:
        # Inject coherent synthetic echoes for wall/metal execute tests
        f_d = np.fft.rfftfreq(np_n, d=Q23C.TS)
        band_mask = (f_d >= Q23C.F_START) & (f_d <= Q23C.F_STOP)
        f_r = Q23C.FS - f_d[band_mask]
        s_ref = np.fft.rfft(ref_wave.astype(np.float64))[band_mask]
        tau_wall = 2.0 * 1.10 / Q23C.C0
        echo_spec = np.zeros_like(np.fft.rfft(ref_wave.astype(np.float64)))
        echo_spec[band_mask] = 0.25 * s_ref * np.exp(1j * 2.0 * np.pi * f_r * tau_wall)
        echo_time = np.round(np.fft.irfft(echo_spec, n=np_n)).astype(np.int16)
        for ch in range(64):
            if ch != 27:
                base_mat[ch] = np.clip(base_mat[ch].astype(np.int32) + echo_time.astype(np.int32), -32000, 32000).astype(np.int16)

    rows: List[Dict[str, Any]] = []

    def _emit_group(ds_name: str, ds_dir: Path, prefix: str, n_pkts_per_row: List[int], inject_46_min: bool) -> None:
        for r in range(8):
            npkts = n_pkts_per_row[r]
            syncs = [100 + k for k in range(npkts)]
            pkts = [base_mat[8 * r : 8 * (r + 1)].copy() for _ in range(npkts)]
            fp = ds_dir / f"{prefix}_{r}.dat"
            _write_valid_d0_dat(fp, pkts, syncs, inject_46_min_last_pkt=bool(inject_46_min and r == 1))
            rows.append(
                {
                    "rel_path": f"附件/{ds_name}/{fp.name}",
                    "size_bytes": fp.stat().st_size,
                    "sha256": _sha256_file(fp),
                }
            )

    for j in range(n_wall):
        prefix = f"2026-11-12-21-{j:02d}-00_16000"
        counts_r = [3 if (j == 2 and r == 0) else 4 for r in range(8)]
        _emit_group(PF2.WALL_DATASET, wall_dir, prefix, counts_r, inject_46_min=False)

    for j in range(n_metal):
        prefix = f"2026-11-12-22-{j:02d}-00_16000"
        counts_r = [3 if (j == 7 and r == 0) else 4 for r in range(8)]
        _emit_group(PF2.METAL_DATASET, metal_dir, prefix, counts_r, inject_46_min=(inject_group8_neg32768 and j == 7))

    orp = metal_dir / "2026-11-12-22-50-31_16000_7.dat"
    orp.write_bytes(b"")
    rows.append(
        {
            "rel_path": f"附件/{PF2.METAL_DATASET}/{orp.name}",
            "size_bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
    )

    manifest_path = data_root.parent / "a_dat_manifest.csv"
    overall_sha = _write_manifest(manifest_path, rows)
    counts = {
        "manifest_entries_count": len(rows),
        "max_protocol_parseable_files": (n_wall + n_metal) * 8,
        "orphan_files_count": 1,
        "wall_valid_groups_count": n_wall,
        "wall_files_count": n_wall * 8,
        "metal_valid_groups_count": n_metal,
        "metal_group_files_count": n_metal * 8,
    }
    return manifest_path, overall_sha, counts


def _make_synthetic_q1_dir(q1_dir: Path, *, frozen: bool, eligible: bool = True) -> None:
    q1_dir.mkdir(parents=True, exist_ok=True)
    band_mask, _, f_r, _ = Q23C.make_reference_band()
    band_idx = np.flatnonzero(band_mask)
    coords, _, all_rx = Q23C.build_array_coords()
    p_tx = coords[27]
    r_dir = np.linalg.norm(coords[all_rx] - p_tx[None, :], axis=1)
    tau_dir = r_dir / Q23C.C0

    np_n = Q23C.NP
    t_idx = np.arange(np_n, dtype=np.float64)
    ref_wave = np.round(9000.0 * np.cos(2.0 * np.pi * 12.0 * t_idx / np_n))
    ref_spec = np.fft.rfft(ref_wave)[band_idx]

    inv_op = np.ones((len(all_rx), len(band_idx)), dtype=np.complex128)
    xbar_air_cal = np.broadcast_to(ref_spec[None, :], (len(all_rx), len(band_idx))).copy()

    arrays_path = q1_dir / "e0c_arrays.npz"
    Q23C.save_npz_deterministic(
        arrays_path,
        {
            "inv_op": inv_op,
            "xbar_air_cal": xbar_air_cal,
            "freq_rf_hz": f_r,
            "tau_dir_s": tau_dir,
            "r_dir_m": r_dir,
            "lambda_grid_cal": np.array([1e-4, 1e-3, 1e-2], dtype=np.float64),
            "lambda_grid_inv": np.array([1e-4, 1e-3, 1e-2], dtype=np.float64),
        },
    )
    arr_sha = _sha256_file(arrays_path)
    impl_sha = "a" * 40
    res_obj = {
        "status": "eligible" if eligible else "hard_stop",
        "implementation_sha": impl_sha,
        "arrays_file": "e0c_arrays.npz",
        "arrays_sha256": arr_sha,
        "arrays_file_sha256": arr_sha,
        "config_sha256": "c" * 64,
        "plan_sha256": "p" * 64,
        "split_sha256": "s" * 64,
        "freeze": {
            "eligible": bool(eligible),
            "status": "eligible" if eligible else "hard_stop",
            "lambda_cal": 1e-3,
            "lambda_inv": 1e-3,
            "eta_wall": 0.25,
        },
    }
    res_path = q1_dir / "e0c_results.json"
    res_path.write_bytes((json.dumps(res_obj, indent=2) + "\n").encode("utf-8"))
    res_sha = _sha256_file(res_path)
    sums = {"e0c_arrays.npz": arr_sha, "e0c_results.json": res_sha}
    if frozen:
        frozen_obj = {
            "implementation_sha": impl_sha,
            "lambdas": [1e-3, 1e-3],
            "lambda_cal": 1e-3,
            "lambda_inv": 1e-3,
            "eta_wall": 0.25,
            "config_sha256": "c" * 64,
            "config_sha256_match": True,
            "plan_sha256": "p" * 64,
            "plan_sha256_match": True,
            "split_sha256": "s" * 64,
            "split_sha256_match": True,
            "results_file": "e0c_results.json",
            "results_sha256": res_sha,
            "arrays_sha256": arr_sha,
        }
        frz_path = q1_dir / "e0c_frozen.json"
        frz_path.write_bytes((json.dumps(frozen_obj, indent=2) + "\n").encode("utf-8"))
        sums["e0c_frozen.json"] = _sha256_file(frz_path)
    (q1_dir / "SHA256SUMS.txt").write_bytes(
        ("\n".join(f"{v}  {k}" for k, v in sorted(sums.items())) + "\n").encode("utf-8")
    )


def _build_approval_registry_payload(
    *,
    q1_frozen_dir: Optional[Path] = None,
    q1_diag_dir: Optional[Path] = None,
    include_bad_variants: bool = True,
) -> Dict[str, Any]:
    if q1_frozen_dir is not None and (q1_frozen_dir / "e0c_frozen.json").is_file():
        exec_frz_sha = _sha256_file(q1_frozen_dir / "e0c_frozen.json")
        exec_arr_sha = _sha256_file(q1_frozen_dir / "e0c_arrays.npz")
    else:
        exec_frz_sha = "1" * 64
        exec_arr_sha = "2" * 64

    if q1_diag_dir is not None and (q1_diag_dir / "e0c_results.json").is_file():
        diag_arr_sha = _sha256_file(q1_diag_dir / "e0c_arrays.npz")
        diag_res_sha = _sha256_file(q1_diag_dir / "e0c_results.json")
    else:
        diag_arr_sha = "3" * 64
        diag_res_sha = "4" * 64

    approvals: Dict[str, Any] = {
        "CODEX-S1-D1-TEST": {
            "approval_ref": "CODEX-S1-D1-TEST",
            "status": "approved",
            "approved_by": "codex",
            "scope": "S2-d1-audit",
            "allowed_modes": ["d1-audit"],
            "diagnostic_only": False,
        },
        "CODEX-S1-EXEC-TEST": {
            "approval_ref": "CODEX-S1-EXEC-TEST",
            "status": "approved",
            "approved_by": "codex",
            "scope": "S3-A-execute",
            "allowed_modes": ["execute"],
            "diagnostic_only": False,
            "allow_unfrozen_q1_diagnostic": False,
            "q1_frozen_sha256": exec_frz_sha,
            "q1_arrays_sha256": exec_arr_sha,
        },
        "CODEX-S1-DIAG-TEST": {
            "approval_ref": "CODEX-S1-DIAG-TEST",
            "status": "approved",
            "approved_by": "codex",
            "scope": "S3-B-diagnostic",
            "allowed_modes": ["execute-diagnostic"],
            "diagnostic_only": True,
            "allow_unfrozen_q1_diagnostic": True,
            "q1_arrays_sha256": diag_arr_sha,
            "q1_results_sha256": diag_res_sha,
        },
        "CODEX-PENDING": {
            "approval_ref": "CODEX-PENDING",
            "status": "pending",
            "approved_by": "codex",
            "scope": "S2-d1-audit",
            "allowed_modes": ["d1-audit"],
            "diagnostic_only": False,
        },
    }
    if include_bad_variants:
        approvals.update(
            {
                "UNTRUSTED-ISSUER": {
                    "approval_ref": "UNTRUSTED-ISSUER",
                    "status": "approved",
                    "approved_by": "antigravity02",
                    "scope": "S2-d1-audit",
                    "allowed_modes": ["d1-audit"],
                    "diagnostic_only": False,
                },
                "EXEC-MISSING-FROZEN-SHA": {
                    "approval_ref": "EXEC-MISSING-FROZEN-SHA",
                    "status": "approved",
                    "approved_by": "codex",
                    "scope": "S3-A-execute",
                    "allowed_modes": ["execute"],
                    "diagnostic_only": False,
                    "allow_unfrozen_q1_diagnostic": False,
                    "q1_arrays_sha256": exec_arr_sha,
                },
                "EXEC-MISSING-ARRAYS-SHA": {
                    "approval_ref": "EXEC-MISSING-ARRAYS-SHA",
                    "status": "approved",
                    "approved_by": "codex",
                    "scope": "S3-A-execute",
                    "allowed_modes": ["execute"],
                    "diagnostic_only": False,
                    "allow_unfrozen_q1_diagnostic": False,
                    "q1_frozen_sha256": exec_frz_sha,
                },
                "EXEC-WRONG-FROZEN-SHA": {
                    "approval_ref": "EXEC-WRONG-FROZEN-SHA",
                    "status": "approved",
                    "approved_by": "codex",
                    "scope": "S3-A-execute",
                    "allowed_modes": ["execute"],
                    "diagnostic_only": False,
                    "allow_unfrozen_q1_diagnostic": False,
                    "q1_frozen_sha256": "f" * 64,
                    "q1_arrays_sha256": exec_arr_sha,
                },
                "DIAG-MISSING-RESULTS-SHA": {
                    "approval_ref": "DIAG-MISSING-RESULTS-SHA",
                    "status": "approved",
                    "approved_by": "codex",
                    "scope": "S3-B-diagnostic",
                    "allowed_modes": ["execute-diagnostic"],
                    "diagnostic_only": True,
                    "allow_unfrozen_q1_diagnostic": True,
                    "q1_arrays_sha256": diag_arr_sha,
                },
                "DIAG-WITH-FROZEN-SHA": {
                    "approval_ref": "DIAG-WITH-FROZEN-SHA",
                    "status": "approved",
                    "approved_by": "codex",
                    "scope": "S3-B-diagnostic",
                    "allowed_modes": ["execute-diagnostic"],
                    "diagnostic_only": True,
                    "allow_unfrozen_q1_diagnostic": True,
                    "q1_frozen_sha256": exec_frz_sha,
                    "q1_arrays_sha256": diag_arr_sha,
                    "q1_results_sha256": diag_res_sha,
                },
            }
        )

    return {
        "schema_version": 1,
        "registry_id": "A-Q2Q3-EMPIRICAL-APPROVALS",
        "trusted_approvers": ["codex"],
        "approvals": approvals,
    }


def _init_trusted_test_repo(repo_dir: Path, payload: Dict[str, Any]) -> Tuple[Path, Path]:
    bare_origin = repo_dir.parent / f"{repo_dir.name}_origin.git"
    subprocess.run(["git", "init", "--bare", str(bare_origin)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(bare_origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True, capture_output=True)

    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "symbolic-ref", "HEAD", "refs/heads/main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "core.autocrlf", "false"], check=True, capture_output=True)

    shutil.copy2(REPO / ".gitattributes", repo_dir / ".gitattributes")
    coord_dir = repo_dir / "coordination"
    coord_dir.mkdir(parents=True, exist_ok=True)
    reg_path = coord_dir / "A_Q2Q3_APPROVALS.json"
    reg_path.write_bytes((json.dumps(payload, indent=2) + "\n").encode("utf-8"))

    sol_dir = repo_dir / "solutions/A"
    sol_dir.mkdir(parents=True, exist_ok=True)
    for rel_name in (
        "a_dat_reader.py",
        "a_fold_gate.py",
        "a_q2q3_common.py",
        "a_q2_solver.py",
        "a_q3_solver.py",
        "validate_q2_q3_outputs.py",
        "q2_q3_output_contract.json",
        "run_q2_q3_empirical.py",
    ):
        shutil.copy2(HERE / rel_name, sol_dir / rel_name)

    cfg_dir = repo_dir / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "a_e0_c.json").write_bytes(b'{"schema_version": 1}\n')

    subprocess.run(
        ["git", "-C", str(repo_dir), "add", ".gitattributes", "coordination/A_Q2Q3_APPROVALS.json", "solutions/A", "configs"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "Add trusted approval registry"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "remote", "add", "origin", str(bare_origin)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "push", "-u", "origin", "main"], check=True, capture_output=True)
    return repo_dir, reg_path


def _worker_cmd_with_synthetic_anchor(
    *,
    worker_mode: str,
    target_dir: Path,
    syn_manifest_sha: str,
    expected_counts: Dict[str, int],
    base_argv: List[str],
    extra_py: str = "",
) -> List[str]:
    counts_json = json.dumps(expected_counts)
    code = (
        "import json, sys; "
        f"sys.path.insert(0, {str(HERE)!r}); "
        "import e0c_preflight as PF, a_q2q3_preflight as PF2, run_q2_q3_empirical as R; "
        f"PF.APPROVED_ANCHORS['dat_manifest_overall_sha256'] = {syn_manifest_sha!r}; "
        f"cnt = json.loads({counts_json!r}); "
        "PF2.EXPECTED_MANIFEST_ENTRIES = cnt['manifest_entries_count']; "
        "PF2.EXPECTED_MAX_PROTOCOL_FILES = cnt['max_protocol_parseable_files']; "
        "PF2.EXPECTED_ORPHAN_FILES = cnt['orphan_files_count']; "
        "PF2.EXPECTED_WALL_GROUPS = cnt['wall_valid_groups_count']; "
        "PF2.EXPECTED_WALL_FILES = cnt['wall_files_count']; "
        "PF2.EXPECTED_METAL_VALID_GROUPS = cnt['metal_valid_groups_count']; "
        "PF2.EXPECTED_METAL_GROUP_FILES = cnt['metal_group_files_count']; "
        f"{extra_py}"
        "raise SystemExit(R.main())"
    )
    return [
        sys.executable,
        "-c",
        code,
        "--mode",
        worker_mode,
        "--out",
        str(target_dir),
        *base_argv,
    ]


class TestQ2Q3S1Toolchain(unittest.TestCase):
    def test_no_discover_groups_called_in_toolchain(self) -> None:
        for rel in ("solutions/A/a_q2q3_preflight.py", "solutions/A/run_q2_q3_empirical.py"):
            txt = (REPO / rel).read_text(encoding="utf-8")
            for line in txt.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "Never calls" in stripped:
                    continue
                self.assertNotIn("discover_groups(", stripped, f"{rel} must never call discover_groups()")

    def test_preflight_481_vs_480_accounting_and_no_q1_frozen_needed_for_d1_audit(self) -> None:
        tmp = _make_tmp_dir("acct481")
        try:
            data_root = tmp / "A_ROOT"
            manifest_path, overall_sha, counts = _write_dummy_dat_corpus(
                data_root, n_wall_groups=33, n_metal_groups=27, include_orphan=True
            )
            self.assertEqual(counts["manifest_entries_count"], 481)
            self.assertEqual(counts["max_protocol_parseable_files"], 480)
            self.assertEqual(counts["orphan_files_count"], 1)

            # 1) D1 audit preflight runs cleanly WITHOUT any Q1 frozen artifact
            res_d1 = PF2.run_preflight(
                repo=REPO,
                data_root=data_root,
                manifest_path=manifest_path,
                mode="d1-audit",
                q1_dir=None,
                expected_manifest_overall_sha256=overall_sha,
            )
            self.assertTrue(res_d1["preconditions_pass"])
            self.assertTrue(res_d1["execution_ready"])
            self.assertEqual(res_d1["packets_parsed"], 0)
            self.assertEqual(res_d1["q1"]["status"], "not_required_for_d1_audit")
            self.assertEqual(res_d1["data"]["manifest_entries_count"], 481)
            self.assertEqual(res_d1["data"]["max_protocol_parseable_files"], 480)
            self.assertEqual(res_d1["data"]["orphan_files_count"], 1)
            self.assertEqual(res_d1["data"]["verified_protocol_parseable_files"], 480)
            self.assertEqual(res_d1["data"]["verified_orphan_files"], 1)
            self.assertEqual(res_d1["data"]["signal_files_hashed"], 481)
            self.assertEqual(len(res_d1["data"]["orphan_files"]), 1)
            self.assertEqual(res_d1["data"]["orphan_files"][0]["size_bytes"], 0)

            # 2) Execute preflight fails when Q1 has no e0c_frozen.json, unless diagnostic flag set
            unfrozen_q1 = tmp / "q1_unfrozen"
            _make_synthetic_q1_dir(unfrozen_q1, frozen=False)
            res_exec_blocked = PF2.run_preflight(
                repo=REPO,
                data_root=data_root,
                manifest_path=manifest_path,
                mode="execute",
                q1_dir=unfrozen_q1,
                expected_manifest_overall_sha256=overall_sha,
            )
            self.assertFalse(res_exec_blocked["preconditions_pass"])
            self.assertIn("q1.dependency", res_exec_blocked["summary"]["blocking_ids"])

            res_exec_diag = PF2.run_preflight(
                repo=REPO,
                data_root=data_root,
                manifest_path=manifest_path,
                mode="execute",
                q1_dir=unfrozen_q1,
                allow_unfrozen_q1_diagnostic=True,
                expected_manifest_overall_sha256=overall_sha,
            )
            self.assertTrue(res_exec_diag["preconditions_pass"])
            self.assertEqual(res_exec_diag["q1"]["status"], "unfrozen_q1_diagnostic_only")
        finally:
            _rmtree_force(tmp)

    def test_path_guard_rejects_escape_reparse_and_out_of_scope(self) -> None:
        tmp = _make_tmp_dir("pathguard")
        try:
            data_root = tmp / "A_ROOT"
            outside = tmp / "OUTSIDE_ATT2" / "墙体数据" / "data20-73cm"
            outside.mkdir(parents=True, exist_ok=True)
            secret_dat = outside / "2026-11-12-21-00-00_16000_0.dat"
            secret_dat.write_bytes(b"FORBIDDEN_HOLDOUT")

            manifest_path, overall_sha, counts = _write_dummy_dat_corpus(
                data_root, n_wall_groups=1, n_metal_groups=1, include_orphan=True
            )

            # 1) Direct guard_dat_path rejects lstat reparse-point flag (0x400) and realpath escape
            wall_dir = PF2.dataset_dir(data_root, PF2.WALL_DATASET)
            real_wall_dir = PF.guard_group_dir(wall_dir, data_root)
            real_root = Path(os.path.realpath(str(data_root)))
            sample_entry = next(real_wall_dir.glob("*.dat"))

            class _FakeStat:
                st_mode = 0o100644
                st_file_attributes = PF.FILE_ATTRIBUTE_REPARSE_POINT

            with self.assertRaises(PF.PathGuardError):
                PF.guard_dat_path(sample_entry, real_wall_dir, real_root, lstat=lambda _p: _FakeStat())

            with self.assertRaises(PF.PathGuardError):
                PF.guard_dat_path(sample_entry, real_wall_dir, real_root, realpath=lambda _p: str(secret_dat))

            # 2) Windows directory junction (or symlink) replacing 墙体 -> OUTSIDE_ATT2 must be rejected
            wall_dir_backup = tmp / "wall_backup"
            shutil.move(str(wall_dir), str(wall_dir_backup))
            created_link = False
            if sys.platform == "win32":
                proc = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(wall_dir), str(outside)],
                    capture_output=True,
                    text=True,
                )
                created_link = proc.returncode == 0
            else:
                os.symlink(outside, wall_dir)
                created_link = True

            if created_link:
                res_junc = PF2.run_preflight(
                    repo=REPO,
                    data_root=data_root,
                    manifest_path=manifest_path,
                    mode="d1-audit",
                    expected_manifest_overall_sha256=overall_sha,
                    expected_counts=counts,
                )
                self.assertFalse(res_junc["preconditions_pass"])
                self.assertIn("data.path_guard", res_junc["summary"]["blocking_ids"])
                self.assertTrue(len(res_junc["data"]["path_guard"]["rejections"]) >= 1)
                self.assertFalse(any("FORBIDDEN" in p or "OUTSIDE_ATT2" in p for p in res_junc["data"]["opened_dat_files"]))
                if sys.platform == "win32":
                    subprocess.run(["cmd", "/c", "rmdir", str(wall_dir)], capture_output=True)
                else:
                    wall_dir.unlink()
        finally:
            _rmtree_force(tmp)

    def test_cli_guards_approval_overwrite_repeat_and_q1_frozen(self) -> None:
        tmp = _make_tmp_dir("cliguards")
        try:
            runner = str(HERE / "run_q2_q3_empirical.py")
            preflight_cli = str(HERE / "a_q2q3_preflight.py")
            data_root = tmp / "A_ROOT"
            manifest_path, _, _ = _write_dummy_dat_corpus(data_root, n_wall_groups=1, n_metal_groups=1, include_orphan=True)
            out_dir = tmp / "out_guard"
            out_dir.mkdir(parents=True, exist_ok=True)
            unfrozen_q1 = tmp / "q1_unfrozen"
            frozen_q1 = tmp / "q1_frozen"
            _make_synthetic_q1_dir(unfrozen_q1, frozen=False, eligible=False)
            _make_synthetic_q1_dir(frozen_q1, frozen=True, eligible=True)

            payload = _build_approval_registry_payload(q1_frozen_dir=frozen_q1, q1_diag_dir=unfrozen_q1)
            trusted_repo, app_reg = _init_trusted_test_repo(tmp / "trusted_repo", payload)

            # 0) Removed --approval-record CLI flag must be rejected (exit 2) on both CLIs
            for cli_path in (runner, preflight_cli):
                p_removed = subprocess.run(
                    [sys.executable, cli_path, "--repo", str(trusted_repo), "--approval-ref", "CODEX-S1-D1-TEST", "--approval-record", str(app_reg)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p_removed.returncode, 2, f"{cli_path} must reject removed --approval-record")

            # 1) Missing --approval-ref -> exit 2 for both d1-audit and execute
            for mode, extra in (("d1-audit", []), ("execute", ["--q1-dir", str(frozen_q1)])):
                p = subprocess.run(
                    [sys.executable, runner, "--repo", str(trusted_repo), "--mode", mode, "--data-root", str(data_root), "--manifest", str(manifest_path), "--out", str(out_dir), *extra],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p.returncode, 2, f"{mode} without approval-ref must exit 2: {p.stderr}")

            # 2) Blank / unknown ref / pending / untrusted issuer / wrong scope / missing required calibration SHA -> exit 2
            bad_cases = [
                ["--mode", "d1-audit", "--approval-ref", "   "],
                ["--mode", "d1-audit", "--approval-ref", "NO-SUCH-REF"],
                ["--mode", "d1-audit", "--approval-ref", "CODEX-PENDING"],
                ["--mode", "d1-audit", "--approval-ref", "UNTRUSTED-ISSUER"],
                ["--mode", "execute", "--approval-ref", "CODEX-S1-D1-TEST", "--q1-dir", str(frozen_q1)],
                ["--mode", "execute", "--approval-ref", "CODEX-S1-EXEC-TEST", "--q1-dir", str(unfrozen_q1), "--allow-unfrozen-q1-diagnostic"],
                ["--mode", "execute", "--approval-ref", "CODEX-S1-DIAG-TEST", "--q1-dir", str(frozen_q1)],
                ["--mode", "execute", "--approval-ref", "EXEC-MISSING-FROZEN-SHA", "--q1-dir", str(frozen_q1)],
                ["--mode", "execute", "--approval-ref", "EXEC-MISSING-ARRAYS-SHA", "--q1-dir", str(frozen_q1)],
                ["--mode", "execute", "--approval-ref", "EXEC-WRONG-FROZEN-SHA", "--q1-dir", str(frozen_q1)],
                ["--mode", "execute", "--approval-ref", "DIAG-MISSING-RESULTS-SHA", "--q1-dir", str(unfrozen_q1), "--allow-unfrozen-q1-diagnostic"],
                ["--mode", "execute", "--approval-ref", "DIAG-WITH-FROZEN-SHA", "--q1-dir", str(unfrozen_q1), "--allow-unfrozen-q1-diagnostic"],
            ]
            for extra_args in bad_cases:
                p_bad = subprocess.run(
                    [sys.executable, runner, "--repo", str(trusted_repo), *extra_args, "--out", str(out_dir)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p_bad.returncode, 2, f"Expected exit 2 for {extra_args}: {p_bad.stderr}")

            # 3) --repeat-runs != 2 on execute -> exit 2
            p_rep = subprocess.run(
                [sys.executable, runner, "--repo", str(trusted_repo), "--mode", "execute", "--approval-ref", "CODEX-S1-EXEC-TEST", "--repeat-runs", "1", "--q1-dir", str(frozen_q1), "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_rep.returncode, 2)

            # 4) execute without e0c_frozen.json -> exit 2
            p_unfrozen = subprocess.run(
                [sys.executable, runner, "--repo", str(trusted_repo), "--mode", "execute", "--approval-ref", "CODEX-S1-EXEC-TEST", "--repeat-runs", "2", "--q1-dir", str(unfrozen_q1), "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_unfrozen.returncode, 2)

            # 5) Overwrite protection: sentinel files remain untouched when --overwrite is omitted
            sentinel_d1 = out_dir / "q2q3_d1_audit.json"
            sentinel_q2 = out_dir / "q2_results.json"
            sentinel_d1.write_bytes(b'{"sentinel": "d1_keep"}\n')
            sentinel_q2.write_bytes(b'{"sentinel": "q2_keep"}\n')
            sha_d1_before = _sha256_file(sentinel_d1)
            sha_q2_before = _sha256_file(sentinel_q2)

            p_ov1 = subprocess.run(
                [sys.executable, runner, "--repo", str(trusted_repo), "--mode", "d1-audit", "--approval-ref", "CODEX-S1-D1-TEST", "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_ov1.returncode, 2)
            p_ov2 = subprocess.run(
                [sys.executable, runner, "--repo", str(trusted_repo), "--mode", "execute", "--approval-ref", "CODEX-S1-EXEC-TEST", "--repeat-runs", "2", "--q1-dir", str(frozen_q1), "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_ov2.returncode, 2)
            self.assertEqual(_sha256_file(sentinel_d1), sha_d1_before)
            self.assertEqual(_sha256_file(sentinel_q2), sha_q2_before)
        finally:
            _rmtree_force(tmp)

    def test_q1_frozen_binding_and_diagnostic_approval_isolation(self) -> None:
        tmp = _make_tmp_dir("q1bind")
        try:
            data_root = tmp / "A_ROOT"
            manifest_path, overall_sha, counts = _write_dummy_dat_corpus(
                data_root, n_wall_groups=1, n_metal_groups=1, include_orphan=True
            )
            q1_ok = tmp / "q1_ok"
            q1_diag = tmp / "q1_diag"
            _make_synthetic_q1_dir(q1_ok, frozen=True, eligible=True)
            _make_synthetic_q1_dir(q1_diag, frozen=False, eligible=False)

            payload = _build_approval_registry_payload(q1_frozen_dir=q1_ok, q1_diag_dir=q1_diag)
            trusted_repo, app_reg = _init_trusted_test_repo(tmp / "trusted_repo", payload)

            # Valid frozen bundle passes
            ok, info = PF2.verify_q1_calibration_bundle(q1_ok, allow_unfrozen_q1_diagnostic=False)
            self.assertTrue(ok, info)

            # Separate formal & diagnostic approvals pass ONLY with matching mandatory calibration SHAs
            ok_exec, info_exec = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="execute",
                approval_ref="CODEX-S1-EXEC-TEST",
                allow_unfrozen_q1_diagnostic=False,
                q1_frozen_sha256=info["frozen_sha256"],
                q1_arrays_sha256=info["arrays_sha256"],
                q1_results_sha256=info["results_sha256"],
            )
            self.assertTrue(ok_exec, info_exec)

            ok_d, info_d = PF2.verify_q1_calibration_bundle(q1_diag, allow_unfrozen_q1_diagnostic=True)
            self.assertTrue(ok_d, info_d)
            ok_diag, info_diag = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="execute",
                approval_ref="CODEX-S1-DIAG-TEST",
                allow_unfrozen_q1_diagnostic=True,
                q1_arrays_sha256=info_d["arrays_sha256"],
                q1_results_sha256=info_d["results_sha256"],
            )
            self.assertTrue(ok_diag, info_diag)

            # Custom external approval_record_path override is rejected even internally
            external_copy = tmp / "forged_approvals.json"
            external_copy.write_bytes(app_reg.read_bytes())
            ok_ext, _ = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="CODEX-S1-D1-TEST",
                approval_record_path=external_copy,
            )
            self.assertFalse(ok_ext)

            # Mandatory calibration digest checks reject missing/empty digests
            for bad_ref in ("EXEC-MISSING-FROZEN-SHA", "EXEC-MISSING-ARRAYS-SHA", "EXEC-WRONG-FROZEN-SHA"):
                ok_bad_exec, _ = PF2.verify_approval_authorization(
                    repo=trusted_repo,
                    mode="execute",
                    approval_ref=bad_ref,
                    allow_unfrozen_q1_diagnostic=False,
                    q1_frozen_sha256=info["frozen_sha256"],
                    q1_arrays_sha256=info["arrays_sha256"],
                    q1_results_sha256=info["results_sha256"],
                )
                self.assertFalse(ok_bad_exec, f"Expected reject for {bad_ref}")

            for bad_diag_ref in ("DIAG-MISSING-RESULTS-SHA", "DIAG-WITH-FROZEN-SHA"):
                ok_bad_diag, _ = PF2.verify_approval_authorization(
                    repo=trusted_repo,
                    mode="execute",
                    approval_ref=bad_diag_ref,
                    allow_unfrozen_q1_diagnostic=True,
                    q1_arrays_sha256=info_d["arrays_sha256"],
                    q1_results_sha256=info_d["results_sha256"],
                )
                self.assertFalse(ok_bad_diag, f"Expected reject for {bad_diag_ref}")

            # Tamper cases on Q1 frozen <-> results <-> NPZ calibration binding
            # Case A: e0c_results.json has freeze.eligible=False even though e0c_frozen.json exists
            q1_inelig = tmp / "q1_inelig"
            _make_synthetic_q1_dir(q1_inelig, frozen=True, eligible=False)
            ok_a, _ = PF2.verify_q1_calibration_bundle(q1_inelig, allow_unfrozen_q1_diagnostic=False)
            self.assertFalse(ok_a)

            # Case B: lambda_cal mismatch between e0c_frozen.json and e0c_results.json
            q1_lam = tmp / "q1_lam"
            _make_synthetic_q1_dir(q1_lam, frozen=True, eligible=True)
            frz = json.loads((q1_lam / "e0c_frozen.json").read_text(encoding="utf-8"))
            frz["lambdas"] = [1e-2, 1e-3]
            frz["lambda_cal"] = 1e-2
            (q1_lam / "e0c_frozen.json").write_bytes((json.dumps(frz) + "\n").encode("utf-8"))
            ok_b, _ = PF2.verify_q1_calibration_bundle(q1_lam, allow_unfrozen_q1_diagnostic=False)
            self.assertFalse(ok_b)

            # Case C: e0c_arrays.npz replaced/tampered after freeze -> arrays_sha256 mismatch
            q1_arr = tmp / "q1_arr"
            _make_synthetic_q1_dir(q1_arr, frozen=True, eligible=True)
            with np.load(q1_arr / "e0c_arrays.npz", allow_pickle=False) as src:
                arrs = {k: src[k].copy() for k in src.files}
            arrs["inv_op"] = arrs["inv_op"] * 2.0
            Q23C.save_npz_deterministic(q1_arr / "e0c_arrays.npz", arrs)
            ok_c, _ = PF2.verify_q1_calibration_bundle(q1_arr, allow_unfrozen_q1_diagnostic=False)
            self.assertFalse(ok_c)

            # Case D: preflight rejects when q1_frozen_sha256 doesn't match approval record binding
            res_pre = PF2.run_preflight(
                repo=trusted_repo,
                data_root=data_root,
                manifest_path=manifest_path,
                mode="execute",
                q1_dir=q1_arr,
                approval_ref="CODEX-S1-EXEC-TEST",
                expected_manifest_overall_sha256=overall_sha,
                expected_counts=counts,
            )
            self.assertFalse(res_pre["preconditions_pass"])
            self.assertIn("q1.dependency", res_pre["summary"]["blocking_ids"])
        finally:
            _rmtree_force(tmp)

    def test_approval_registry_untrusted_git_origin_and_reparse_rejections(self) -> None:
        tmp = _make_tmp_dir("origin_trust")
        try:
            payload = _build_approval_registry_payload()
            trusted_repo, app_reg = _init_trusted_test_repo(tmp / "trusted_repo", payload)

            # Baseline valid against origin/main
            ok0, info0 = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="CODEX-S1-D1-TEST",
            )
            self.assertTrue(ok0, info0)

            # 1) Dirty local modification to coordination/A_Q2Q3_APPROVALS.json -> rejected
            orig_bytes = app_reg.read_bytes()
            mod_payload = copy.deepcopy(payload)
            mod_payload["approvals"]["LOCAL-FORGED"] = {
                "approval_ref": "LOCAL-FORGED",
                "status": "approved",
                "approved_by": "codex",
                "scope": "S2-d1-audit",
                "allowed_modes": ["d1-audit"],
                "diagnostic_only": False,
            }
            app_reg.write_bytes((json.dumps(mod_payload, indent=2) + "\n").encode("utf-8"))
            ok_dirty, info_dirty = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="LOCAL-FORGED",
            )
            self.assertFalse(ok_dirty)
            self.assertIn("工作区存在未提交改动或未追踪文件", info_dirty["reason"])
            app_reg.write_bytes(orig_bytes)

            # 1b) Full-workspace dirty-tree rejections outside coordination/ (source, config, staged edit, untracked file)
            solver_path = trusted_repo / "solutions/A/a_q2_solver.py"
            orig_solver = solver_path.read_bytes()
            solver_path.write_bytes(orig_solver + b"# dirty edit\n")
            ok_src, info_src = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="CODEX-S1-D1-TEST",
            )
            self.assertFalse(ok_src)
            self.assertIn("solutions/A/a_q2_solver.py", info_src["reason"])

            # CLI must also exit 2 when repo has uncommitted source edit
            p_dirty_cli = subprocess.run(
                [sys.executable, str(HERE / "run_q2_q3_empirical.py"), "--repo", str(trusted_repo), "--mode", "d1-audit", "--approval-ref", "CODEX-S1-D1-TEST", "--out", str(tmp / "out_dirty")],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_dirty_cli.returncode, 2)

            # Staged edit (even if clean in diff? no, staged relative to HEAD) must also fail
            subprocess.run(["git", "-C", str(trusted_repo), "add", "solutions/A/a_q2_solver.py"], check=True, capture_output=True)
            ok_staged, _ = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="CODEX-S1-D1-TEST",
            )
            self.assertFalse(ok_staged)
            subprocess.run(["git", "-C", str(trusted_repo), "reset", "HEAD", "--", "solutions/A/a_q2_solver.py"], check=True, capture_output=True)
            solver_path.write_bytes(orig_solver)

            # Modified config file must fail
            cfg_path = trusted_repo / "configs/a_e0_c.json"
            orig_cfg = cfg_path.read_bytes()
            cfg_path.write_bytes(b'{"schema_version": 2}\n')
            ok_cfg, info_cfg = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="CODEX-S1-D1-TEST",
            )
            self.assertFalse(ok_cfg)
            self.assertIn("configs/a_e0_c.json", info_cfg["reason"])
            cfg_path.write_bytes(orig_cfg)

            # Untracked source/override file anywhere in workspace must fail
            untracked_override = trusted_repo / "solutions/A/local_override.py"
            untracked_override.write_bytes(b"OVERRIDE = True\n")
            ok_untracked, info_untracked = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="CODEX-S1-D1-TEST",
            )
            self.assertFalse(ok_untracked)
            self.assertIn("solutions/A/local_override.py", info_untracked["reason"])
            untracked_override.unlink()

            # 1c) Worker-2 dual-run tolerance: only deliverable run-1 files under experiments/A/A-Q2Q3-EMP/... are tolerated in worker-2, never arbitrary/rogue files
            emp_d1_dir = trusted_repo / "experiments/A/A-Q2Q3-EMP/d1_audit"
            emp_run2_dir = emp_d1_dir / "repeat_runs/run-2"
            emp_run2_dir.mkdir(parents=True, exist_ok=True)
            (emp_d1_dir / "worker_meta.json").write_bytes(b'{"run_id": "1"}\n')
            (emp_d1_dir / "q2q3_d1_audit.json").write_bytes(b'{"ok": true}\n')
            self.assertIsNone(
                RUN.validate_cli_guards(
                    repo=trusted_repo,
                    mode="d1-audit-worker",
                    approval_ref="CODEX-S1-D1-TEST",
                    approval_record_path=None,
                    repeat_runs=2,
                    out_dir=emp_run2_dir,
                    overwrite=True,
                    q1_dir=None,
                    allow_unfrozen_q1_diagnostic=False,
                )
            )
            (emp_d1_dir / "rogue_override.py").write_bytes(b"EVIL = 1\n")
            err_rogue = RUN.validate_cli_guards(
                repo=trusted_repo,
                mode="d1-audit-worker",
                approval_ref="CODEX-S1-D1-TEST",
                approval_record_path=None,
                repeat_runs=2,
                out_dir=emp_run2_dir,
                overwrite=True,
                q1_dir=None,
                allow_unfrozen_q1_diagnostic=False,
            )
            self.assertIsNotNone(err_rogue)
            self.assertIn("rogue_override.py", str(err_rogue))
            shutil.rmtree(trusted_repo / "experiments", ignore_errors=True)

            # 2) Unmerged branch commit not in origin/main -> rejected even when working copy is clean
            subprocess.run(["git", "-C", str(trusted_repo), "checkout", "-b", "feature/self-approve"], check=True, capture_output=True)
            branch_payload = copy.deepcopy(payload)
            branch_payload["approvals"]["BRANCH-ONLY-SELF"] = {
                "approval_ref": "BRANCH-ONLY-SELF",
                "status": "approved",
                "approved_by": "codex",
                "scope": "S2-d1-audit",
                "allowed_modes": ["d1-audit"],
                "diagnostic_only": False,
            }
            app_reg.write_bytes((json.dumps(branch_payload, indent=2) + "\n").encode("utf-8"))
            subprocess.run(["git", "-C", str(trusted_repo), "add", "coordination/A_Q2Q3_APPROVALS.json"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(trusted_repo), "commit", "-m", "Self-approved on feature branch"], check=True, capture_output=True)
            ok_branch, info_branch = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="BRANCH-ONLY-SELF",
            )
            self.assertFalse(ok_branch)
            self.assertIn("尚未合入 origin/main", info_branch["reason"])

            # Return cleanly to main for junction test
            subprocess.run(["git", "-C", str(trusted_repo), "checkout", "main"], check=True, capture_output=True)

            # 3) Untrusted approved_by even when merged into origin/main -> rejected
            ok_untrusted, info_untrusted = PF2.verify_approval_authorization(
                repo=trusted_repo,
                mode="d1-audit",
                approval_ref="UNTRUSTED-ISSUER",
            )
            self.assertFalse(ok_untrusted)
            self.assertIn("受信任统筹签发名单", info_untrusted["reason"])

            # 4) Reparse point / junction replacing coordination/ pointing outside repo -> rejected
            outside_coord = tmp / "outside_coord"
            outside_coord.mkdir(parents=True, exist_ok=True)
            (outside_coord / "A_Q2Q3_APPROVALS.json").write_bytes(orig_bytes)
            coord_dir = trusted_repo / "coordination"
            coord_backup = tmp / "coord_backup"
            shutil.move(str(coord_dir), str(coord_backup))
            created_junc = False
            if sys.platform == "win32":
                p_mk = subprocess.run(["cmd", "/c", "mklink", "/J", str(coord_dir), str(outside_coord)], capture_output=True, text=True)
                created_junc = p_mk.returncode == 0
            else:
                os.symlink(outside_coord, coord_dir)
                created_junc = True
            if created_junc:
                ok_junc, info_junc = PF2.verify_approval_authorization(
                    repo=trusted_repo,
                    mode="d1-audit",
                    approval_ref="CODEX-S1-D1-TEST",
                )
                self.assertFalse(ok_junc, info_junc)
                self.assertIn("反重解析", info_junc["reason"])
                if sys.platform == "win32":
                    subprocess.run(["cmd", "/c", "rmdir", str(coord_dir)], capture_output=True)
                else:
                    coord_dir.unlink()
                shutil.move(str(coord_backup), str(coord_dir))
        finally:
            _rmtree_force(tmp)

    def test_dual_process_d1_audit_without_q1_and_repeat_tamper_cases(self) -> None:
        tmp = _make_tmp_dir("dual_d1")
        try:
            data_root = tmp / "A_ROOT"
            manifest_path, overall_sha, counts = _build_valid_d0_synthetic_corpus(
                data_root, n_wall=3, n_metal=8, inject_group8_neg32768=True, plant_echoes=False
            )
            payload = _build_approval_registry_payload(include_bad_variants=False)
            trusted_repo, _ = _init_trusted_test_repo(tmp / "trusted_repo", payload)
            out_dir = tmp / "d1_audit_out"
            base_argv = [
                "--repo",
                str(trusted_repo),
                "--data-root",
                str(data_root),
                "--manifest",
                str(manifest_path),
                "--approval-ref",
                "CODEX-S1-D1-TEST",
            ]
            manifest = RUN.run_two_independent_runs(
                worker_mode="d1-audit-worker",
                out_dir=out_dir,
                base_argv=base_argv,
                worker_cmd_override=lambda tdir, _idx: _worker_cmd_with_synthetic_anchor(
                    worker_mode="d1-audit-worker",
                    target_dir=tdir,
                    syn_manifest_sha=overall_sha,
                    expected_counts=counts,
                    base_argv=base_argv,
                ),
            )

            self.assertTrue(manifest["digests_identical"])
            self.assertEqual(manifest["n_runs"], 2)
            runs = manifest["runs"]
            self.assertNotEqual(runs[0]["pid"], runs[1]["pid"])
            self.assertLessEqual(runs[0]["finished_at"], runs[1]["started_at"])

            audit_path = out_dir / "q2q3_d1_audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertFalse(audit["q1_frozen_required"])
            self.assertTrue(audit["all_valid_rx_63"])
            self.assertTrue(audit["finite"])
            self.assertEqual(audit["accounting"]["manifest_entries_count"], counts["manifest_entries_count"])
            self.assertEqual(audit["accounting"]["max_protocol_parseable_files"], counts["max_protocol_parseable_files"])
            self.assertEqual(audit["accounting"]["orphan_files_count"], 1)
            self.assertEqual(audit["anomaly_isolation"]["group8_sync_common"], 3)
            self.assertEqual(audit["anomaly_isolation"]["group8_int16_min_count"], 46)
            self.assertEqual(audit["anomaly_isolation"]["orphan_skipped"]["count"], 1)
            self.assertIn("provenance", audit["anomaly_isolation"])
            self.assertNotIn(b"\r\n", audit_path.read_bytes())
            self.assertNotIn(b"\r\n", (out_dir / "SHA256SUMS.txt").read_bytes())

            # Verify SHA256SUMS ledger matches all files
            for line in (out_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
                dig, fn = line.split(None, 1)
                self.assertEqual(_sha256_file(out_dir / fn.strip()), dig)

            # Negative tamper tests on repeat manifest
            rep_path = out_dir / "q2q3_repeat.json"
            orig_rep = rep_path.read_text(encoding="utf-8")

            def _assert_rejected(mutator) -> None:
                fake = copy.deepcopy(manifest)
                mutator(fake)
                rep_path.write_text(json.dumps(fake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                try:
                    with self.assertRaises(RUN.Q2Q3Stop):
                        RUN.verify_repeat_manifest(out_dir)
                finally:
                    rep_path.write_text(orig_rep, encoding="utf-8")

            _assert_rejected(lambda m: m["runs"][1].update({"pid": m["runs"][0]["pid"]}))
            _assert_rejected(lambda m: m["runs"][1].update({"started_at": m["runs"][0]["started_at"]}))
            _assert_rejected(lambda m: m["runs"][1].update({"results_file": m["runs"][0]["results_file"]}))
            _assert_rejected(lambda m: m["runs"][1].update({"digest_sha256": "0" * 64}))
            _assert_rejected(lambda m: m["runs"][1].update({"results_sha256": "f" * 64}))

            # Negative test proving digest_sha256 is recomputed from actual on-disk artifact (fake digest rejected)
            run2_path = out_dir / runs[1]["results_file"]
            orig_run2_bytes = run2_path.read_bytes()
            tampered_run2 = json.loads(orig_run2_bytes.decode("utf-8"))
            tampered_run2["groups"][0]["p_common"] = 99
            run2_path.write_bytes((json.dumps(tampered_run2, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            fake_rep = copy.deepcopy(manifest)
            fake_rep["runs"][1]["results_sha256"] = _sha256_file(run2_path)
            rep_path.write_bytes((json.dumps(fake_rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            try:
                with self.assertRaises(RUN.Q2Q3Stop):
                    RUN.verify_repeat_manifest(out_dir)
            finally:
                run2_path.write_bytes(orig_run2_bytes)
                rep_path.write_text(orig_rep, encoding="utf-8")
        finally:
            _rmtree_force(tmp)

    def test_dual_process_execute_end_to_end_synthetic_q1_frozen(self) -> None:
        tmp = _make_tmp_dir("dual_exec")
        try:
            data_root = tmp / "A_ROOT"
            manifest_path, overall_sha, counts = _build_valid_d0_synthetic_corpus(
                data_root, n_wall=3, n_metal=3, inject_group8_neg32768=False, plant_echoes=True
            )
            q1_dir = tmp / "q1_frozen"
            _make_synthetic_q1_dir(q1_dir, frozen=True, eligible=True)
            payload = _build_approval_registry_payload(q1_frozen_dir=q1_dir, include_bad_variants=False)
            trusted_repo, _ = _init_trusted_test_repo(tmp / "trusted_repo", payload)
            out_dir = tmp / "exec_out"
            base_argv = [
                "--repo",
                str(trusted_repo),
                "--data-root",
                str(data_root),
                "--manifest",
                str(manifest_path),
                "--q1-dir",
                str(q1_dir),
                "--approval-ref",
                "CODEX-S1-EXEC-TEST",
            ]
            # Use coarse solver grid inside synthetic test so dual subprocess run finishes in a few seconds
            coarse_override = (
                "_orig_exec = R.run_execute_worker; "
                "R.run_execute_worker = lambda **kw: _orig_exec(**{**kw, 'grid_step_m': 0.08, 'q3_step_m': (0.10, 0.10, 0.10)}); "
            )
            manifest = RUN.run_two_independent_runs(
                worker_mode="execute-worker",
                out_dir=out_dir,
                base_argv=base_argv,
                worker_cmd_override=lambda tdir, _idx: _worker_cmd_with_synthetic_anchor(
                    worker_mode="execute-worker",
                    target_dir=tdir,
                    syn_manifest_sha=overall_sha,
                    expected_counts=counts,
                    base_argv=base_argv,
                    extra_py=coarse_override,
                ),
            )
            self.assertTrue(manifest["digests_identical"])
            self.assertNotEqual(manifest["runs"][0]["pid"], manifest["runs"][1]["pid"])
            for fname in ("q2_results.json", "q3_wall_results.json", "q3_metal_results.json", "q2q3_repeat.json", "SHA256SUMS.txt"):
                p = out_dir / fname
                self.assertTrue(p.is_file(), f"Missing {fname}")
                self.assertNotIn(b"\r\n", p.read_bytes(), f"{fname} must be LF")
            q2_res = json.loads((out_dir / "q2_results.json").read_text(encoding="utf-8"))
            q3m_res = json.loads((out_dir / "q3_metal_results.json").read_text(encoding="utf-8"))
            self.assertEqual(q2_res["status"], "empirical_pending_acceptance")
            self.assertEqual(q2_res["real_dat_files_read"], 24)
            self.assertEqual(q3m_res["real_dat_files_read"], 25)
            self.assertEqual(q3m_res["anomaly_isolation"]["orphan_skipped"]["count"], 1)
            self.assertEqual(q2_res["q1_arrays_sha256"], _sha256_file(q1_dir / "e0c_arrays.npz"))
            self.assertEqual(q2_res["q1_implementation_sha"], "a" * 40)
            for line in (out_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
                dig, fn = line.split(None, 1)
                self.assertEqual(_sha256_file(out_dir / fn.strip()), dig)

            # Negative recomputation check: tamper run-2 q2_results.json without changing q2q3_summary digest
            r2_q2_path = out_dir / "repeat_runs" / "run-2" / "q2_results.json"
            orig_r2_q2 = r2_q2_path.read_bytes()
            bad_q2 = json.loads(orig_r2_q2.decode("utf-8"))
            bad_q2["row_consistency"]["max_row_diff_cm"] += 1.0
            r2_q2_path.write_bytes((json.dumps(bad_q2, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            try:
                with self.assertRaises(RUN.Q2Q3Stop):
                    RUN.verify_repeat_manifest(out_dir)
            finally:
                r2_q2_path.write_bytes(orig_r2_q2)
        finally:
            _rmtree_force(tmp)

    def test_gitattributes_lf_checkout_on_windows_autocrlf_true(self) -> None:
        tmp = _make_tmp_dir("git_lf")
        try:
            subprocess.run(["git", "init", str(tmp)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(tmp), "config", "core.autocrlf", "true"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(tmp), "config", "user.email", "test@example.com"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(tmp), "config", "user.name", "Test"], check=True, capture_output=True)
            shutil.copy2(REPO / ".gitattributes", tmp / ".gitattributes")

            targets = [
                tmp / "experiments/A/A-Q2Q3-EMP/results/q2_results.json",
                tmp / "experiments/A/A-Q2Q3-EMP/results/run.log",
                tmp / "experiments/A/A-Q2Q3-EMP/d1_audit/q2q3_d1_audit.json",
                tmp / "experiments/A/A-Q2Q3-EMP/results/repeat_runs/run-2/q2_results.json",
                tmp / "coordination/A_Q2Q3_APPROVALS.json",
            ]
            for p in targets:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'{\n  "line": "lf_locked"\n}\n')

            sums_res = tmp / "experiments/A/A-Q2Q3-EMP/results/SHA256SUMS.txt"
            sums_res.write_bytes(
                f"{_sha256_file(targets[0])}  q2_results.json\n{_sha256_file(targets[1])}  run.log\n".encode("utf-8")
            )
            sums_d1 = tmp / "experiments/A/A-Q2Q3-EMP/d1_audit/SHA256SUMS.txt"
            sums_d1.write_bytes(f"{_sha256_file(targets[2])}  q2q3_d1_audit.json\n".encode("utf-8"))

            subprocess.run(["git", "-C", str(tmp), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(tmp), "commit", "-m", "test lf"], check=True, capture_output=True)

            # Force a clean checkout from index under core.autocrlf=true
            for p in [*targets, sums_res, sums_d1]:
                p.unlink()
            subprocess.run(["git", "-C", str(tmp), "checkout", "--", "."], check=True, capture_output=True)

            for p in [*targets, sums_res, sums_d1]:
                raw = p.read_bytes()
                self.assertNotIn(b"\r\n", raw, f"CRLF leaked on clean checkout: {p}")

            for sums_file in (sums_res, sums_d1):
                for line in sums_file.read_text(encoding="utf-8").splitlines():
                    dig, fn = line.split(None, 1)
                    self.assertEqual(_sha256_file(sums_file.parent / fn.strip()), dig)
        finally:
            _rmtree_force(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
