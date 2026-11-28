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
import struct
import subprocess
import sys
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


WORK_TMP = REPO / "tmp"
WORK_TMP.mkdir(parents=True, exist_ok=True)
DAT_MAGIC = 963072


def _make_tmp_dir(tag: str) -> Path:
    path = WORK_TMP / f"q2q3_s1_{tag}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


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


def _make_synthetic_q1_dir(q1_dir: Path, *, frozen: bool) -> None:
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

    Q23C.save_npz_deterministic(
        q1_dir / "e0c_arrays.npz",
        {
            "inv_op": inv_op,
            "xbar_air_cal": xbar_air_cal,
            "freq_rf_hz": f_r,
            "tau_dir_s": tau_dir,
            "r_dir_m": r_dir,
        },
    )
    (q1_dir / "e0c_results.json").write_bytes((json.dumps({"status": "synthetic_q1"}) + "\n").encode("utf-8"))
    if frozen:
        (q1_dir / "e0c_frozen.json").write_bytes(
            (
                json.dumps(
                    {
                        "implementation_sha": "a" * 40,
                        "lambdas": [1e-3, 1e-3],
                        "eta_wall": 0.25,
                    }
                )
                + "\n"
            ).encode("utf-8")
        )


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
            shutil.rmtree(tmp, ignore_errors=True)

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
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_guards_approval_overwrite_repeat_and_q1_frozen(self) -> None:
        tmp = _make_tmp_dir("cliguards")
        try:
            runner = str(HERE / "run_q2_q3_empirical.py")
            data_root = tmp / "A_ROOT"
            manifest_path, _, _ = _write_dummy_dat_corpus(data_root, n_wall_groups=1, n_metal_groups=1, include_orphan=True)
            out_dir = tmp / "out_guard"
            out_dir.mkdir(parents=True, exist_ok=True)
            unfrozen_q1 = tmp / "q1_unfrozen"
            frozen_q1 = tmp / "q1_frozen"
            _make_synthetic_q1_dir(unfrozen_q1, frozen=False)
            _make_synthetic_q1_dir(frozen_q1, frozen=True)

            # 1) Missing --approval-ref -> exit 2 for both d1-audit and execute
            for mode, extra in (("d1-audit", []), ("execute", ["--q1-dir", str(frozen_q1)])):
                p = subprocess.run(
                    [sys.executable, runner, "--mode", mode, "--data-root", str(data_root), "--manifest", str(manifest_path), "--out", str(out_dir), *extra],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p.returncode, 2, f"{mode} without approval-ref must exit 2: {p.stderr}")

            # 2) Blank --approval-ref -> exit 2
            p_blank = subprocess.run(
                [sys.executable, runner, "--mode", "d1-audit", "--approval-ref", "   ", "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_blank.returncode, 2)

            # 3) --repeat-runs != 2 on execute -> exit 2
            p_rep = subprocess.run(
                [sys.executable, runner, "--mode", "execute", "--approval-ref", "CODEX-TEST", "--repeat-runs", "1", "--q1-dir", str(frozen_q1), "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_rep.returncode, 2)

            # 4) execute without e0c_frozen.json -> exit 2
            p_unfrozen = subprocess.run(
                [sys.executable, runner, "--mode", "execute", "--approval-ref", "CODEX-TEST", "--repeat-runs", "2", "--q1-dir", str(unfrozen_q1), "--out", str(out_dir)],
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
                [sys.executable, runner, "--mode", "d1-audit", "--approval-ref", "CODEX-TEST", "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_ov1.returncode, 2)
            p_ov2 = subprocess.run(
                [sys.executable, runner, "--mode", "execute", "--approval-ref", "CODEX-TEST", "--repeat-runs", "2", "--q1-dir", str(frozen_q1), "--out", str(out_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_ov2.returncode, 2)
            self.assertEqual(_sha256_file(sentinel_d1), sha_d1_before)
            self.assertEqual(_sha256_file(sentinel_q2), sha_q2_before)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dual_process_d1_audit_without_q1_and_repeat_tamper_cases(self) -> None:
        tmp = _make_tmp_dir("dual_d1")
        try:
            data_root = tmp / "A_ROOT"
            manifest_path, overall_sha, counts = _build_valid_d0_synthetic_corpus(
                data_root, n_wall=3, n_metal=8, inject_group8_neg32768=True, plant_echoes=False
            )
            out_dir = tmp / "d1_audit_out"
            base_argv = [
                "--repo",
                str(REPO),
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
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dual_process_execute_end_to_end_synthetic_q1_frozen(self) -> None:
        tmp = _make_tmp_dir("dual_exec")
        try:
            data_root = tmp / "A_ROOT"
            manifest_path, overall_sha, counts = _build_valid_d0_synthetic_corpus(
                data_root, n_wall=3, n_metal=3, inject_group8_neg32768=False, plant_echoes=True
            )
            q1_dir = tmp / "q1_frozen"
            _make_synthetic_q1_dir(q1_dir, frozen=True)
            out_dir = tmp / "exec_out"
            base_argv = [
                "--repo",
                str(REPO),
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
            for line in (out_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
                dig, fn = line.split(None, 1)
                self.assertEqual(_sha256_file(out_dir / fn.strip()), dig)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
