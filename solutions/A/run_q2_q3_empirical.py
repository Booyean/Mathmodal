#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Q2 / Q3 empirical execution shell (preflight, strict guards, D1 audit, dual-process framework).

Modes:
- ``check`` (default): metadata & path-guard preflight only (zero ``.dat`` packet parsing).
- ``d1-audit``: requires ``--approval-ref``; runs Attachment-3 D0-4 + D1-2 audit WITHOUT
  requiring any Q1 frozen artifact. Supports ``--repeat-runs 1|2`` (default 2).
- ``execute``: requires ``--approval-ref``, ``--repeat-runs 2``, and ``--q1-dir`` with
  ``e0c_frozen.json`` (unless ``--allow-unfrozen-q1-diagnostic`` is set). Runs two
  sequential independent worker subprocesses (run-1 -> ``<out>``, run-2 -> ``repeat_runs/run-2/``).

Security & data boundaries:
- Never calls ``a_dat_reader.discover_groups()`` (which rglobs the whole A tree).
- Refuses missing ``--approval-ref`` (exit code 2), refuses overwriting existing outputs
  without ``--overwrite`` (exit code 2), and enforces lexical + anti-reparse + realpath
  path guards via ``a_q2q3_preflight`` before touching any ``.dat`` file.
"""

from __future__ import annotations

import os

for _env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_env] = "1"

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a_dat_reader as D0  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402
import a_fold_gate as D1  # noqa: E402
import a_q2_solver as Q2S  # noqa: E402
import a_q2q3_common as Q23C  # noqa: E402
import a_q2q3_preflight as PF2  # noqa: E402
import a_q3_solver as Q3S  # noqa: E402
import e0c_preflight as PF  # noqa: E402


CONTRACT_VERSION = "Q2Q3-EMP-1"
REPEAT_CONTRACT = "Q2Q3-EMP-REPEAT-1"
REPEAT_DIR_NAME = "repeat_runs"

DEFAULT_CHECK_OUT = REPO_ROOT / "experiments" / "A" / "A-Q2Q3-EMP" / "check"
DEFAULT_D1_OUT = REPO_ROOT / "experiments" / "A" / "A-Q2Q3-EMP" / "d1_audit"
DEFAULT_EXEC_OUT = REPO_ROOT / "experiments" / "A" / "A-Q2Q3-EMP" / "results"

PROTECTED_FILENAMES: Tuple[str, ...] = (
    "q2q3_d1_audit.json",
    "q2_results.json",
    "q2_arrays.npz",
    "q3_wall_results.json",
    "q3_wall_arrays.npz",
    "q3_metal_results.json",
    "q3_metal_arrays.npz",
    "q2q3_repeat.json",
    "SHA256SUMS.txt",
)

REPEAT_REQUIRED_FIELDS: Tuple[str, ...] = (
    "run_index",
    "run_id",
    "pid",
    "started_at",
    "finished_at",
    "wall_time_s",
    "results_file",
    "results_sha256",
    "digest_sha256",
)
REPEAT_PROVENANCE_FIELDS: Tuple[str, ...] = (
    "run_id",
    "pid",
    "started_at",
    "finished_at",
    "results_file",
)


class Q2Q3Stop(RuntimeError):
    """Hard-stop or contract violation raised before or during empirical execution."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_lf(path: Path, obj: Any) -> str:
    payload = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_sha256sums_lf(out_dir: Path, sums: Dict[str, str]) -> None:
    lines = [f"{digest}  {name}" for name, digest in sorted(sums.items())]
    (out_dir / "SHA256SUMS.txt").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _file_sha256(path: Path) -> str:
    return PF.sha256_file(path)


def _peak_rss_mib() -> Optional[float]:
    try:
        import resource  # POSIX only

        val = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return round(val / 1024.0, 3)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return round(float(pmc.PeakWorkingSetSize) / (1024.0 * 1024.0), 3)
        except Exception:
            pass
    return None


def _rel_inside(base: Path, rel: str) -> Path:
    base_res = base.resolve()
    target = (base_res / rel).resolve()
    try:
        target.relative_to(base_res)
    except ValueError as exc:
        raise Q2Q3Stop(f"相对路径越出输出目录：{rel!r}") from exc
    return target


def existing_protected_artifacts(out_dir: Path) -> List[str]:
    hits: List[str] = []
    if not out_dir.exists():
        return hits
    for name in PROTECTED_FILENAMES:
        if (out_dir / name).exists():
            hits.append(name)
    run2_dir = out_dir / REPEAT_DIR_NAME / "run-2"
    if run2_dir.exists() and any(run2_dir.iterdir()):
        hits.append(f"{REPEAT_DIR_NAME}/run-2")
    return hits


def _allowed_run1_rel_dir_for_worker(repo: Path, worker_mode: str, out_dir: Path) -> Optional[str]:
    """Allow only run-1 deliverable outputs in run-2 worker when out_dir is repo/experiments/A/A-Q2Q3-EMP/<run>/repeat_runs/run-2."""
    if worker_mode not in ("d1-audit-worker", "execute-worker"):
        return None
    out_res = out_dir.resolve()
    if out_res.name != "run-2" or out_res.parent.name != REPEAT_DIR_NAME:
        return None
    run1_dir = out_res.parent.parent
    emp_base = (repo.resolve() / "experiments/A/A-Q2Q3-EMP").resolve()
    try:
        rel_posix = run1_dir.relative_to(repo.resolve()).as_posix()
        run1_dir.relative_to(emp_base)
    except ValueError:
        return None
    if not (run1_dir / "worker_meta.json").is_file():
        return None
    return rel_posix


def validate_cli_guards(
    repo: Path,
    mode: str,
    approval_ref: Optional[str],
    approval_record_path: Optional[Path],
    repeat_runs: int,
    out_dir: Path,
    overwrite: bool,
    q1_dir: Optional[Path],
    allow_unfrozen_q1_diagnostic: bool,
) -> Optional[str]:
    """Return error message (exit code 2) if any execution guard fails, else None."""
    q1_info: Dict[str, Any] = {}
    if mode in ("execute", "execute-worker"):
        q1_ok, q1_info = PF2.verify_q1_calibration_bundle(
            q1_dir,
            allow_unfrozen_q1_diagnostic=allow_unfrozen_q1_diagnostic,
        )
        if not q1_ok:
            return str(q1_info.get("reason") or q1_info.get("status") or "Q1 校准校验未通过")

    if mode in ("d1-audit", "d1-audit-worker", "execute", "execute-worker"):
        app_ok, app_info = PF2.verify_approval_authorization(
            repo=repo,
            mode=mode,
            approval_ref=approval_ref,
            approval_record_path=approval_record_path,
            allow_unfrozen_q1_diagnostic=allow_unfrozen_q1_diagnostic,
            q1_frozen_sha256=q1_info.get("frozen_sha256"),
            q1_arrays_sha256=q1_info.get("arrays_sha256"),
            q1_results_sha256=q1_info.get("results_sha256"),
            allowed_run1_rel_dir=_allowed_run1_rel_dir_for_worker(repo, mode, out_dir),
        )
        if not app_ok:
            return str(app_info.get("reason") or "审批状态或范围校验未通过")

    if mode == "execute":
        if int(repeat_runs) != 2:
            return f"--mode execute 强制要求 --repeat-runs 2，收到 {repeat_runs}"
    elif mode == "d1-audit":
        if int(repeat_runs) not in (1, 2):
            return f"--mode d1-audit 的 --repeat-runs 仅支持 1 或 2，收到 {repeat_runs}"

    if mode in ("d1-audit", "d1-audit-worker", "execute", "execute-worker"):
        if not overwrite:
            existing = existing_protected_artifacts(out_dir)
            if existing:
                return f"目标目录 {out_dir} 已存在交付产物 {existing}；未传入 --overwrite，拒绝覆盖"

    return None


def _build_guarded_group_ref(data_root: Path, grp_meta: Dict[str, Any]) -> D0.GroupRef:
    """Build ``D0.GroupRef`` strictly from preflight-guarded file paths (never calls discover_groups)."""
    files: Dict[int, Path] = {}
    for f in grp_meta["files"]:
        r = int(f["row"])
        gp = Path(f["guarded_path"])
        files[r] = gp
    return D0.GroupRef(
        root=data_root,
        dir_rel=str(grp_meta["dir_rel"]),
        prefix=str(grp_meta["prefix"]),
        dataset=str(grp_meta["dataset"]),
        name=str(grp_meta["prefix"]),
        files=files,
        duplicate_rows=[],
    )


def _fold_guarded_dataset(
    data_root: Path,
    groups_meta: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, D1.FoldedGroup]]:
    """Load and D1-2 fold every guarded group; returns (inputs, group_records, folded_by_key)."""
    inputs: List[Dict[str, Any]] = []
    group_records: List[Dict[str, Any]] = []
    folded_by_key: Dict[str, D1.FoldedGroup] = {}

    for grp_meta in groups_meta:
        ref = _build_guarded_group_ref(data_root, grp_meta)
        gd = D0.load_group(ref, require_all_rows=True, compute_sha256=True)
        fg = D1.fold_group(gd)

        valid_rx = int(np.count_nonzero(fg.rx_mask & fg.channel_valid))
        all_finite = bool(np.all(np.isfinite(fg.signals_folded)))
        if valid_rx != 63:
            raise Q2Q3Stop(f"组 {gd.group_key} 有效通道 valid_rx={valid_rx} != 63")
        if not all_finite:
            raise Q2Q3Stop(f"组 {gd.group_key} 折叠输出含非有限值")

        row_files = gd.meta.get("row_files", {})
        neg_32768_total = 0
        pos_32767_total = 0
        row_neg_detail: Dict[str, int] = {}
        for r_key, rf in sorted(row_files.items()):
            ep = rf.get("endpoint_counts_all_packets") or {}
            neg = int(ep.get("neg_32768", 0))
            pos = int(ep.get("pos_32767", 0))
            neg_32768_total += neg
            pos_32767_total += pos
            if neg > 0:
                row_neg_detail[str(r_key)] = neg

        for f in grp_meta["files"]:
            inputs.append(
                {
                    "rel_path": str(f["rel_path"]),
                    "size_bytes": int(f["size_bytes"]),
                    "sha256": str(f["sha256"]),
                }
            )

        rejected_logs = [
            {"sync": int(p["sync"]), "reasons": list(p.get("reject_reasons") or [])}
            for p in fg.packet_log
            if not bool(p.get("accepted"))
        ]
        anchor_syncs = [int(p["sync"]) for p in fg.packet_log if bool(p.get("anchor"))]
        p_common = int(gd.meta.get("n_packets", len(gd.sync)))

        group_records.append(
            {
                "dataset": str(grp_meta["dataset"]),
                "group_key": str(gd.group_key),
                "prefix": str(grp_meta["prefix"]),
                "p_common": p_common,
                "sync_common": [int(s) for s in gd.sync.tolist()],
                "valid_rx": valid_rx,
                "finite": all_finite,
                "d1_accepted": int(fg.n_accepted),
                "d1_rejected": int(len(rejected_logs)),
                "d1_reject_details": rejected_logs,
                "anchor_sync": anchor_syncs[0] if anchor_syncs else None,
                "neg_32768_count": neg_32768_total,
                "pos_32767_count": pos_32767_total,
                "row_neg_32768": row_neg_detail,
            }
        )
        folded_by_key[str(gd.group_key)] = fg

    return inputs, group_records, folded_by_key


def _build_empirical_anomaly_isolation(
    *,
    phase: str,
    records: Sequence[Dict[str, Any]],
    orphan_files: Sequence[Dict[str, Any]],
    total_dat_read: int,
) -> Dict[str, Any]:
    mismatch = [
        {
            "group_index": idx + 1,
            "group_id": rec["group_key"],
            "p_common": int(rec["p_common"]),
        }
        for idx, rec in enumerate(records)
        if int(rec["p_common"]) < max(int(r["p_common"]) for r in records)
    ] if records else []

    orphan_summary = {
        "count": len(orphan_files),
        "files": [
            {
                "rel_path": o["rel_path"],
                "size_bytes": int(o["size_bytes"]),
                "reason": o["reason"],
            }
            for o in orphan_files
        ],
    }

    provenance: Dict[str, Any] = {
        "real_dat_files_read": {
            "source_path": "d0_load_group+preflight.orphan_files",
            "field": "len(inputs) + len(orphan_files)",
            "derivation": "count of guarded .dat files actually verified/loaded in this phase",
        },
        "packet_mismatch_groups": {
            "source_path": "d0_load_group#meta.n_packets",
            "field": "records[*].p_common",
            "derivation": "groups whose D0共同sync交集包数 p_common < max(p_common)",
        },
        "orphan_skipped": {
            "source_path": "a_q2q3_preflight#data.orphan_files",
            "field": "orphan_files[*]",
            "derivation": "manifest entries excluded from 8-row group parsing (e.g., 0-byte orphan)",
        },
    }

    out: Dict[str, Any] = {
        "real_dat_files_read": int(total_dat_read),
        "packet_mismatch_groups": mismatch,
        "orphan_skipped": orphan_summary,
        "provenance": provenance,
    }
    if phase in ("Q3-Metal", "D1-Audit") and len(records) >= 8:
        metal_recs = [r for r in records if r["dataset"] == PF2.METAL_DATASET]
        if len(metal_recs) >= 8:
            g8 = metal_recs[7]
            out["group8_sync_common"] = int(g8["p_common"])
            out["group8_int16_min_count"] = int(g8["neg_32768_count"])
            out["group8_d1_gate_action"] = {
                "d1_accepted": int(g8["d1_accepted"]),
                "d1_rejected": int(g8["d1_rejected"]),
                "d1_reject_details": g8["d1_reject_details"],
            }
            provenance["group8_sync_common"] = {
                "source_path": f"d0_load_group({g8['group_key']})",
                "field": "meta.n_packets",
                "derivation": "D0 common sync packet intersection count of 8th metal group",
            }
            provenance["group8_int16_min_count"] = {
                "source_path": f"d0_load_group({g8['group_key']})",
                "field": "meta.row_files[*].endpoint_counts_all_packets.neg_32768",
                "derivation": "sum of int32-promoted == -32768 counts across all packets of 8th metal group",
            }
            provenance["group8_d1_gate_action"] = {
                "source_path": f"d1_fold_group({g8['group_key']})",
                "field": "packet_log[*].{accepted,reject_reasons}",
                "derivation": "actual D1-2 packet gate outcome for 8th metal group",
            }
    return out


def _compute_d1_audit_digest(
    *,
    records: Sequence[Dict[str, Any]],
    orphan_files: Sequence[Dict[str, Any]],
    manifest_entries_count: int,
    max_protocol_parseable_files: int,
) -> str:
    return Q23C.canonical_json_sha256(
        {
            "records": list(records),
            "orphan_files": list(orphan_files),
            "manifest_entries_count": int(manifest_entries_count),
            "max_protocol_parseable_files": int(max_protocol_parseable_files),
        }
    )


def _compute_execute_digest(
    q2_res: Dict[str, Any],
    q3w_res: Dict[str, Any],
    q3m_res: Dict[str, Any],
) -> str:
    return Q23C.canonical_json_sha256(
        {
            "q2_alpha": q2_res["gain_selection"]["selected_alpha_per_ns"],
            "q2_max_row_diff_cm": q2_res["row_consistency"]["max_row_diff_cm"],
            "q3_wall_reconcile_max_cm": q3w_res["q2_q3_reconciliation"]["air_segment_max_diff_cm"],
            "q3_metal_objects_count": len(q3m_res["metal_objects"]),
            "q3_metal_shadow_unocc_global_med": float(q3m_res["shadow_unocc_global_med"]),
        }
    )


def run_check(
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    q1_dir: Optional[Path],
    allow_unfrozen_q1_diagnostic: bool,
    out_dir: Path,
    *,
    approval_ref: Optional[str] = None,
    approval_record_path: Optional[Path] = None,
    expected_manifest_overall_sha256: Optional[str] = None,
    expected_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    mode = "execute" if q1_dir is not None else "d1-audit"
    pre = PF2.run_preflight(
        repo=repo,
        data_root=data_root,
        manifest_path=manifest_path,
        mode=mode,
        q1_dir=q1_dir,
        allow_unfrozen_q1_diagnostic=allow_unfrozen_q1_diagnostic,
        approval_ref=approval_ref,
        approval_record_path=approval_record_path,
        check_hashes=True,
        expected_manifest_overall_sha256=expected_manifest_overall_sha256,
        expected_counts=expected_counts,
    )
    compact = dict(pre)
    compact_data = dict(pre["data"])
    compact_data["protocol_parseable_groups"] = [
        {
            "dataset": g["dataset"],
            "group_key": g["group_key"],
            "prefix": g["prefix"],
            "file_count": len(g["files"]),
        }
        for g in compact_data.get("protocol_parseable_groups", [])
    ]
    compact["data"] = compact_data
    payload = {
        "contract_version": CONTRACT_VERSION,
        "mode": "check",
        "generated_at": _now_iso(),
        "packets_parsed": 0,
        "preflight": compact,
    }
    _write_json_lf(out_dir / "q2q3_check.json", payload)
    return payload


def run_d1_audit_worker(
    *,
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    out_dir: Path,
    approval_ref: str,
    approval_record_path: Optional[Path] = None,
    implementation_sha: Optional[str],
    parent_commit: Optional[str],
    main_commit: Optional[str],
    command: str,
    expected_manifest_overall_sha256: Optional[str] = None,
    expected_counts: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    started_at = _now_iso()
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex

    pre = PF2.run_preflight(
        repo=repo,
        data_root=data_root,
        manifest_path=manifest_path,
        mode="d1-audit",
        q1_dir=None,
        approval_ref=approval_ref,
        approval_record_path=approval_record_path,
        check_hashes=True,
        expected_manifest_overall_sha256=expected_manifest_overall_sha256,
        expected_counts=expected_counts,
        allowed_run1_rel_dir=_allowed_run1_rel_dir_for_worker(repo, "d1-audit-worker", out_dir),
    )
    if not pre["preconditions_pass"]:
        raise Q2Q3Stop("D1 审计预检失败，拒绝解析 .dat：" + ", ".join(pre["summary"]["blocking_ids"]))

    groups_meta = pre["data"]["protocol_parseable_groups"]
    orphan_files = pre["data"]["orphan_files"]
    inputs, records, _ = _fold_guarded_dataset(data_root, groups_meta)

    wall_recs = [r for r in records if r["dataset"] == PF2.WALL_DATASET]
    metal_recs = [r for r in records if r["dataset"] == PF2.METAL_DATASET]
    total_dat_read = len(inputs) + len(orphan_files)

    anomaly = _build_empirical_anomaly_isolation(
        phase="D1-Audit",
        records=records,
        orphan_files=orphan_files,
        total_dat_read=total_dat_read,
    )

    digest_sha256 = _compute_d1_audit_digest(
        records=records,
        orphan_files=orphan_files,
        manifest_entries_count=pre["data"]["manifest_entries_count"],
        max_protocol_parseable_files=pre["data"]["max_protocol_parseable_files"],
    )

    elapsed = round(time.perf_counter() - t0, 4)
    finished_at = _now_iso()

    result = {
        "contract_version": CONTRACT_VERSION,
        "phase": "D1-Audit",
        "generated_at": finished_at,
        "approval_ref": approval_ref,
        "implementation_sha": implementation_sha or Q23C.git_head_full(),
        "parent_commit": parent_commit,
        "main_commit": main_commit,
        "command": command,
        "q1_frozen_required": False,
        "d0_contract_version": D0.CONTRACT_VERSION,
        "d1_contract_version": D1.CONTRACT_VERSION,
        "accounting": {
            "manifest_entries_count": pre["data"]["manifest_entries_count"],
            "max_protocol_parseable_files": pre["data"]["max_protocol_parseable_files"],
            "orphan_files_count": pre["data"]["orphan_files_count"],
            "wall_groups_audited": len(wall_recs),
            "metal_groups_audited": len(metal_recs),
            "real_dat_files_loaded": len(inputs),
        },
        "anomaly_isolation": anomaly,
        "groups": records,
        "inputs": inputs,
        "orphan_files": orphan_files,
        "digest_sha256": digest_sha256,
        "finite": all(r["finite"] for r in records),
        "all_valid_rx_63": all(r["valid_rx"] == 63 for r in records),
        "status": "empirical_pending_acceptance",
        "resource": {
            "wall_time_s": elapsed,
            "peak_rss_mib": _peak_rss_mib(),
            "single_process": True,
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    log_lines = [
        f"phase=D1-Audit run_id={run_id} pid={os.getpid()}",
        f"manifest_entries={pre['data']['manifest_entries_count']} parseable={pre['data']['max_protocol_parseable_files']} orphan={pre['data']['orphan_files_count']}",
        f"wall_groups={len(wall_recs)} metal_groups={len(metal_recs)} digest={digest_sha256}",
    ]
    (out_dir / "run.log").write_bytes(("\n".join(log_lines) + "\n").encode("utf-8"))
    res_sha = _write_json_lf(out_dir / "q2q3_d1_audit.json", result)
    sums = {
        "q2q3_d1_audit.json": res_sha,
        "run.log": _file_sha256(out_dir / "run.log"),
    }
    _write_sha256sums_lf(out_dir, sums)

    worker_meta = {
        "run_id": run_id,
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_time_s": elapsed,
        "peak_rss_mib": result["resource"]["peak_rss_mib"],
        "results_file": "q2q3_d1_audit.json",
        "results_sha256": res_sha,
        "digest_sha256": digest_sha256,
    }
    _write_json_lf(out_dir / "worker_meta.json", worker_meta)
    return result, worker_meta


def _folded_groups_to_scene(
    *,
    records: Sequence[Dict[str, Any]],
    folded_by_key: Dict[str, D1.FoldedGroup],
    x_scan: np.ndarray,
    inv_op: np.ndarray,
    xbar_air_cal: np.ndarray,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    band_idx: np.ndarray,
    orphan_files: Sequence[Dict[str, Any]],
    real_dat_count: int,
) -> Dict[str, Any]:
    """Calibrate, subtract direct wave (M0-DW-Base alpha=1.0), and evaluate 4x baseband z_base_over."""
    osr = Q23C.OSR
    n_over = Q23C.NP * osr
    np_n = Q23C.NP
    ts = Q23C.TS
    tp = Q23C.TP
    causal_over = Q23C.CAUSAL_SAMPLES_OVER

    coords, row_rx, all_rx = Q23C.build_array_coords()
    n_rx = len(all_rx)

    z_base_over = np.zeros((len(records), n_rx, causal_over), dtype=np.complex128)
    gids: List[str] = []
    p_counts: List[int] = []

    for j_idx, rec in enumerate(records):
        gkey = rec["group_key"]
        fg = folded_by_key[gkey]
        sig_rx = fg.signals_folded[all_rx]  # (63, Np)
        x_raw_band = np.fft.rfft(sig_rx, axis=1)[:, band_idx]  # (63, nb)
        x_cal = x_raw_band * inv_op
        dt0_s = E0S.align_lag(xbar_air_cal, x_cal, f_r, band_idx, np_n, ts, tp)
        xair_aligned = xbar_air_cal * np.exp(1j * 2.0 * np.pi * f_r * dt0_s)[None, :]
        x_after = x_cal - 1.0 * xair_aligned
        s_eff = E0S.build_s_eff(xair_aligned, r_dir, tau_dir, f_r)
        s_eff_norm = max(float(np.linalg.norm(s_eff)), 1e-30)

        full_spec = np.zeros((n_rx, n_over), dtype=np.complex128)
        full_spec[:, band_idx] = x_after * np.conj(s_eff)[None, :]
        z_over = n_over * np.fft.ifft(full_spec, axis=1) / s_eff_norm
        z_base_over[j_idx] = z_over[:, :causal_over]
        gids.append(gkey)
        p_counts.append(int(rec["p_common"]))

    return {
        "coords": coords,
        "row_rx": row_rx,
        "all_rx": all_rx,
        "x_scan_m": x_scan,
        "j_group_ids": np.array(gids),
        "j_p_common": np.array(p_counts, dtype=np.int64),
        "z_base_over": z_base_over,
        "input_mode": "empirical",
        "anomaly_inputs": {
            "real_dat_files_read": int(real_dat_count),
            "packet_mismatch_exercised": True,
            "orphan_files": {
                "count": len(orphan_files),
                "files": [o["rel_path"] for o in orphan_files],
            },
        },
    }


def _empirical_metadata(
    *,
    phase: str,
    arrays: Dict[str, np.ndarray],
    groups_used: List[str],
    anomaly: Dict[str, Any],
    energy_prefixes: Tuple[str, ...],
    approval_ref: str,
    implementation_sha: str,
    parent_commit: Optional[str],
    main_commit: Optional[str],
    q1_dir: Path,
    q1_info: Dict[str, Any],
    q1_frozen: bool,
    diagnostic_mode: bool,
    command: str,
    real_dat_count: int,
) -> Dict[str, Any]:
    prov = Q23C.build_generation_provenance(
        preset="empirical",
        generated_at=_now_iso(),
        command=command,
    )
    prov["implementation_sha"] = implementation_sha
    prov["generator_script"] = "solutions/A/run_q2_q3_empirical.py"
    prov["applies_to_phase"] = phase
    prov["input_fixture"] = {
        "mode": "empirical",
        "real_dat_files_read": int(real_dat_count),
        "q1_dir": str(q1_dir),
        "q1_frozen": bool(q1_frozen),
        "q1_frozen_sha256": q1_info.get("frozen_sha256"),
        "q1_results_sha256": q1_info.get("results_sha256"),
        "q1_arrays_sha256": q1_info.get("arrays_sha256"),
        "q1_implementation_sha": q1_info.get("implementation_sha"),
    }

    q1_cfg_path = str(q1_dir / ("e0c_frozen.json" if q1_frozen else "e0c_results.json"))
    q1_cfg_sha = (
        q1_info.get("frozen_sha256_lf")
        if q1_frozen
        else q1_info.get("results_sha256_lf")
    ) or (PF.sha256_file_lf(Path(q1_cfg_path)) if Path(q1_cfg_path).is_file() else "missing")
    status = "hard_stop" if diagnostic_mode else "empirical_pending_acceptance"

    return {
        "phase": phase,
        "input_mode": "empirical_diagnostic" if diagnostic_mode else "empirical",
        "real_dat_files_read": int(real_dat_count),
        "citable": False,
        "approval_ref": approval_ref,
        "implementation_sha": implementation_sha,
        "parent_commit": parent_commit,
        "main_commit": main_commit or "c7b841e",
        "q1_frozen_config_path": q1_cfg_path,
        "q1_frozen_config_sha256": q1_cfg_sha,
        "q1_arrays_sha256": q1_info.get("arrays_sha256"),
        "q1_implementation_sha": q1_info.get("implementation_sha"),
        "d0_contract_version": D0.CONTRACT_VERSION,
        "d1_contract_version": D1.CONTRACT_VERSION,
        "groups_used": groups_used,
        "anomaly_isolation": anomaly,
        "arrays_sha256": Q23C.arrays_dict_sha256(arrays),
        "arrays_sha256_scope": Q23C.arrays_sha256_scope(arrays),
        "provenance": prov,
        "finite": Q23C.all_arrays_finite_and_valid(arrays, energy_prefixes),
        "status": status,
    }


def run_execute_worker(
    *,
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    q1_dir: Path,
    allow_unfrozen_q1_diagnostic: bool,
    out_dir: Path,
    approval_ref: str,
    approval_record_path: Optional[Path] = None,
    implementation_sha: Optional[str],
    parent_commit: Optional[str],
    main_commit: Optional[str],
    command: str,
    grid_step_m: float = 0.01,
    q3_step_m: Tuple[float, float, float] = (0.02, 0.02, 0.02),
    expected_manifest_overall_sha256: Optional[str] = None,
    expected_counts: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    started_at = _now_iso()
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex

    pre = PF2.run_preflight(
        repo=repo,
        data_root=data_root,
        manifest_path=manifest_path,
        mode="execute",
        q1_dir=q1_dir,
        allow_unfrozen_q1_diagnostic=allow_unfrozen_q1_diagnostic,
        approval_ref=approval_ref,
        approval_record_path=approval_record_path,
        check_hashes=True,
        expected_manifest_overall_sha256=expected_manifest_overall_sha256,
        expected_counts=expected_counts,
        allowed_run1_rel_dir=_allowed_run1_rel_dir_for_worker(repo, "execute-worker", out_dir),
    )
    if not pre["preconditions_pass"]:
        raise Q2Q3Stop("execute 预检失败，拒绝解析 .dat：" + ", ".join(pre["summary"]["blocking_ids"]))

    q1_info = dict(pre["q1"])
    q1_frozen = bool(q1_info.get("frozen"))
    diagnostic_mode = bool(not q1_frozen and allow_unfrozen_q1_diagnostic)
    impl_sha = implementation_sha or Q23C.git_head_full()

    # Re-verify loaded arrays file SHA matches verified Q1 bundle immediately before reading
    actual_q1_arr_sha = PF.sha256_file(q1_dir / "e0c_arrays.npz")
    if actual_q1_arr_sha != q1_info.get("arrays_sha256"):
        raise Q2Q3Stop("加载前检测到 e0c_arrays.npz 摘要漂移，拒绝执行")

    with np.load(q1_dir / "e0c_arrays.npz", allow_pickle=False) as q1_npz:
        inv_op = np.asarray(q1_npz["inv_op"], dtype=np.complex128)
        xbar_air_cal = np.asarray(q1_npz["xbar_air_cal"], dtype=np.complex128)
        f_r = np.asarray(q1_npz["freq_rf_hz"], dtype=np.float64)
        tau_dir = np.asarray(q1_npz["tau_dir_s"], dtype=np.float64)
        r_dir = np.asarray(q1_npz["r_dir_m"], dtype=np.float64)

    band_mask, _, _, _ = Q23C.make_reference_band()
    band_idx = np.flatnonzero(band_mask)
    groups_meta = pre["data"]["protocol_parseable_groups"]
    orphan_files = pre["data"]["orphan_files"]
    inputs, records, folded_by_key = _fold_guarded_dataset(data_root, groups_meta)

    wall_recs = [r for r in records if r["dataset"] == PF2.WALL_DATASET]
    metal_recs = [r for r in records if r["dataset"] == PF2.METAL_DATASET]
    x_scan_wall = -0.20 + 0.05 * np.arange(len(wall_recs), dtype=np.float64)
    x_scan_metal = 0.05 * np.arange(len(metal_recs), dtype=np.float64)

    wall_dat_count = len(wall_recs) * 8
    metal_dat_count = len(metal_recs) * 8 + len(orphan_files)
    total_dat_count = wall_dat_count + metal_dat_count

    scene_wall = _folded_groups_to_scene(
        records=wall_recs,
        folded_by_key=folded_by_key,
        x_scan=x_scan_wall,
        inv_op=inv_op,
        xbar_air_cal=xbar_air_cal,
        r_dir=r_dir,
        tau_dir=tau_dir,
        f_r=f_r,
        band_idx=band_idx,
        orphan_files=[],
        real_dat_count=wall_dat_count,
    )
    scene_metal = _folded_groups_to_scene(
        records=metal_recs,
        folded_by_key=folded_by_key,
        x_scan=x_scan_metal,
        inv_op=inv_op,
        xbar_air_cal=xbar_air_cal,
        r_dir=r_dir,
        tau_dir=tau_dir,
        f_r=f_r,
        band_idx=band_idx,
        orphan_files=orphan_files,
        real_dat_count=metal_dat_count,
    )

    q2_res, q2_arr = Q2S.solve_q2_synthetic(scene_wall, dx_m=grid_step_m, dy_m=grid_step_m)
    q3w_res, q3w_arr = Q3S.solve_q3_wall_synthetic(scene_wall, q2_res, q2_arr, step_m=q3_step_m)
    q3m_res, q3m_arr = Q3S.solve_q3_metal_synthetic(scene_metal, q2_res, step_m=q3_step_m)

    # Replace synthetic metadata shells with empirical provenance & D0/D1 anomaly isolation
    wall_anom = _build_empirical_anomaly_isolation(
        phase="Q2", records=wall_recs, orphan_files=[], total_dat_read=wall_dat_count
    )
    metal_anom = _build_empirical_anomaly_isolation(
        phase="Q3-Metal", records=metal_recs, orphan_files=orphan_files, total_dat_read=metal_dat_count
    )

    for res_obj, arr_obj, phase_name, prefixes, anom_obj, rec_list, dat_cnt in (
        (q2_res, q2_arr, "Q2", ("image_",), wall_anom, wall_recs, wall_dat_count),
        (q3w_res, q3w_arr, "Q3-Wall", ("image_", "slice_", "proj_"), wall_anom, wall_recs, wall_dat_count),
        (q3m_res, q3m_arr, "Q3-Metal", ("image_", "shadow_profile_"), metal_anom, metal_recs, metal_dat_count),
    ):
        meta = _empirical_metadata(
            phase=phase_name,
            arrays=arr_obj,
            groups_used=[r["group_key"] for r in rec_list],
            anomaly=anom_obj,
            energy_prefixes=prefixes,
            approval_ref=approval_ref,
            implementation_sha=impl_sha,
            parent_commit=parent_commit,
            main_commit=main_commit,
            q1_dir=q1_dir,
            q1_info=q1_info,
            q1_frozen=q1_frozen,
            diagnostic_mode=diagnostic_mode,
            command=command,
            real_dat_count=dat_cnt,
        )
        res_obj.update(meta)

    out_dir.mkdir(parents=True, exist_ok=True)
    sums: Dict[str, str] = {}
    for prefix, res_obj, arr_obj in (
        ("q2", q2_res, q2_arr),
        ("q3_wall", q3w_res, q3w_arr),
        ("q3_metal", q3m_res, q3m_arr),
    ):
        npz_path = out_dir / f"{prefix}_arrays.npz"
        Q23C.save_npz_deterministic(npz_path, arr_obj)
        sums[npz_path.name] = _file_sha256(npz_path)
        sums[f"{prefix}_results.json"] = _write_json_lf(out_dir / f"{prefix}_results.json", res_obj)

    elapsed = round(time.perf_counter() - t0, 4)
    finished_at = _now_iso()
    digest_sha256 = _compute_execute_digest(q2_res, q3w_res, q3m_res)
    summary_payload = {
        "contract_version": CONTRACT_VERSION,
        "phase": "Q2Q3-Execute",
        "generated_at": finished_at,
        "approval_ref": approval_ref,
        "real_dat_files_read": total_dat_count,
        "q1_frozen": q1_frozen,
        "q1_frozen_sha256": q1_info.get("frozen_sha256"),
        "q1_arrays_sha256": q1_info.get("arrays_sha256"),
        "diagnostic_mode": diagnostic_mode,
        "status": q2_res["status"],
        "q2_selected_alpha_per_ns": q2_res["gain_selection"]["selected_alpha_per_ns"],
        "q2_max_row_diff_cm": q2_res["row_consistency"]["max_row_diff_cm"],
        "q3_wall_reconcile_max_cm": q3w_res["q2_q3_reconciliation"]["air_segment_max_diff_cm"],
        "q3_metal_objects_count": len(q3m_res["metal_objects"]),
        "q3_metal_shadow_unocc_global_med": float(q3m_res["shadow_unocc_global_med"]),
        "arrays_sha256_map": {
            "q2": q2_res["arrays_sha256"],
            "q3_wall": q3w_res["arrays_sha256"],
            "q3_metal": q3m_res["arrays_sha256"],
        },
        "inputs_count": len(inputs),
        "orphan_files_count": len(orphan_files),
        "digest_sha256": digest_sha256,
    }

    (out_dir / "run.log").write_bytes(
        (
            f"phase=Q2Q3-Execute run_id={run_id} pid={os.getpid()} "
            f"real_dat={total_dat_count} digest={digest_sha256}\n"
        ).encode("utf-8")
    )
    sums["run.log"] = _file_sha256(out_dir / "run.log")
    sums["q2q3_summary.json"] = _write_json_lf(out_dir / "q2q3_summary.json", summary_payload)
    _write_sha256sums_lf(out_dir, sums)

    worker_meta = {
        "run_id": run_id,
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_time_s": elapsed,
        "peak_rss_mib": _peak_rss_mib(),
        "results_file": "q2q3_summary.json",
        "results_sha256": sums["q2q3_summary.json"],
        "digest_sha256": digest_sha256,
        "arrays_sha256_map": summary_payload["arrays_sha256_map"],
    }
    _write_json_lf(out_dir / "worker_meta.json", worker_meta)
    return summary_payload, worker_meta


def _verify_execute_run_dir(run_dir: Path, summary_obj: Dict[str, Any]) -> Tuple[str, Dict[str, Dict[str, np.ndarray]]]:
    """Recompute arrays_sha256 and execute digest from actual on-disk Q2/Q3 JSON+NPZ artifacts."""
    loaded_res: Dict[str, Dict[str, Any]] = {}
    loaded_arr: Dict[str, Dict[str, np.ndarray]] = {}
    for prefix in ("q2", "q3_wall", "q3_metal"):
        rpath = run_dir / f"{prefix}_results.json"
        npath = run_dir / f"{prefix}_arrays.npz"
        if not rpath.is_file() or not npath.is_file():
            raise Q2Q3Stop(f"{run_dir} 缺少 {prefix}_results.json 或 {prefix}_arrays.npz")
        robj = json.loads(rpath.read_text(encoding="utf-8"))
        with np.load(npath, allow_pickle=False) as npz:
            arrs = {k: npz[k] for k in npz.files}
        re_arr_sha = Q23C.arrays_dict_sha256(arrs)
        if str(robj.get("arrays_sha256")) != re_arr_sha:
            raise Q2Q3Stop(f"{run_dir}/{prefix}_results.json 的 arrays_sha256 与实际 NPZ 不符")
        loaded_res[prefix] = robj
        loaded_arr[prefix] = arrs

    re_digest = _compute_execute_digest(loaded_res["q2"], loaded_res["q3_wall"], loaded_res["q3_metal"])
    if str(summary_obj.get("digest_sha256")) != re_digest:
        raise Q2Q3Stop(f"{run_dir}/q2q3_summary.json 的 digest_sha256 与实际 Q2/Q3 产物重算不符")
    return re_digest, loaded_arr


def verify_repeat_manifest(out_dir: Path) -> Dict[str, Any]:
    """Verify dual-process ``q2q3_repeat.json`` by recomputing digests and comparing actual artifacts."""
    out_dir = Path(out_dir)
    manifest_path = out_dir / "q2q3_repeat.json"
    if not manifest_path.is_file():
        raise Q2Q3Stop("缺少 q2q3_repeat.json：两次独立运行证据未登记")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Q2Q3Stop(f"q2q3_repeat.json 不可读：{exc}") from exc

    problems: List[str] = []
    runs = list(manifest.get("runs") or [])
    if int(manifest.get("n_runs") or 0) != 2 or len(runs) != 2:
        problems.append("n_runs 必须为 2 且 runs 长度为 2")
        raise Q2Q3Stop("两次独立运行证据不完整：" + "; ".join(problems))

    windows: List[Tuple[datetime, datetime]] = []
    loaded_targets: List[Path] = []
    loaded_payloads: List[Dict[str, Any]] = []
    for idx, rec in enumerate(runs):
        missing = [f for f in REPEAT_REQUIRED_FIELDS if f not in rec]
        if missing:
            problems.append(f"runs[{idx}] 缺少字段 {missing}")
            continue
        rel = str(rec["results_file"])
        target = _rel_inside(out_dir, rel)
        if not target.is_file():
            problems.append(f"runs[{idx}].results_file 不存在：{rel}")
        elif _file_sha256(target) != str(rec["results_sha256"]):
            problems.append(f"runs[{idx}].results_sha256 与文件不符")
        else:
            loaded_targets.append(target)
            loaded_payloads.append(json.loads(target.read_text(encoding="utf-8")))

        if not isinstance(rec.get("pid"), int) or int(rec["pid"]) <= 0:
            problems.append(f"runs[{idx}].pid 非法")
        try:
            st = datetime.fromisoformat(str(rec["started_at"]).replace("Z", "+00:00"))
            fn = datetime.fromisoformat(str(rec["finished_at"]).replace("Z", "+00:00"))
            if st.tzinfo is None or fn.tzinfo is None or not (st <= fn):
                raise ValueError("invalid timestamps")
            windows.append((st, fn))
        except Exception as exc:
            problems.append(f"runs[{idx}] 时间戳异常：{exc}")

    if len(windows) == 2 and windows[0][1] > windows[1][0]:
        problems.append("两次运行时间窗重叠或顺序颠倒")

    for field in REPEAT_PROVENANCE_FIELDS:
        vals = [str(r.get(field)) for r in runs]
        if len(set(vals)) != len(vals):
            problems.append(f"两次运行的 {field} 相同 → 非独立进程")

    if str(runs[0].get("digest_sha256")) != str(runs[1].get("digest_sha256")):
        problems.append("两次独立运行记录的 digest_sha256 不一致")

    if problems:
        raise Q2Q3Stop("两次独立运行证据校验失败：" + "; ".join(problems))

    # Recompute digests from actual on-disk artifacts of BOTH runs (never trust declared digest alone)
    worker_mode = str(manifest.get("worker_mode", ""))
    if len(loaded_payloads) == 2:
        p0, p1 = loaded_payloads
        if worker_mode == "d1-audit-worker" or p0.get("phase") == "D1-Audit":
            re0 = _compute_d1_audit_digest(
                records=p0.get("groups", []),
                orphan_files=p0.get("orphan_files", []),
                manifest_entries_count=int((p0.get("accounting") or {}).get("manifest_entries_count", -1)),
                max_protocol_parseable_files=int((p0.get("accounting") or {}).get("max_protocol_parseable_files", -1)),
            )
            re1 = _compute_d1_audit_digest(
                records=p1.get("groups", []),
                orphan_files=p1.get("orphan_files", []),
                manifest_entries_count=int((p1.get("accounting") or {}).get("manifest_entries_count", -1)),
                max_protocol_parseable_files=int((p1.get("accounting") or {}).get("max_protocol_parseable_files", -1)),
            )
            if re0 != str(p0.get("digest_sha256")) or re0 != str(runs[0]["digest_sha256"]):
                raise Q2Q3Stop("run-1 实际 D1 审计产物重算 digest_sha256 不一致")
            if re1 != str(p1.get("digest_sha256")) or re1 != str(runs[1]["digest_sha256"]):
                raise Q2Q3Stop("run-2 实际 D1 审计产物重算 digest_sha256 不一致")
            if re0 != re1 or p0.get("groups") != p1.get("groups") or p0.get("accounting") != p1.get("accounting"):
                raise Q2Q3Stop("两次独立 D1 审计实际产物内容不一致")
        elif worker_mode == "execute-worker" or p0.get("phase") == "Q2Q3-Execute":
            re0, arrs0 = _verify_execute_run_dir(loaded_targets[0].parent, p0)
            re1, arrs1 = _verify_execute_run_dir(loaded_targets[1].parent, p1)
            if re0 != str(runs[0]["digest_sha256"]) or re1 != str(runs[1]["digest_sha256"]):
                raise Q2Q3Stop("实际 Q2/Q3 产物重算 digest_sha256 与 repeat 清单不符")
            if re0 != re1:
                raise Q2Q3Stop("两次独立执行实际重算 digest_sha256 不一致")
            for prefix in ("q2", "q3_wall", "q3_metal"):
                for k in arrs0[prefix]:
                    v0, v1 = arrs0[prefix][k], arrs1[prefix][k]
                    if v0.dtype.kind in ("f", "c") and not np.allclose(v0, v1, rtol=1e-9, atol=1e-12):
                        raise Q2Q3Stop(f"两次独立执行 {prefix}_arrays.npz::{k} 数值超差 (rtol=1e-9)")

    return manifest


def run_two_independent_runs(
    *,
    worker_mode: str,
    out_dir: Path,
    base_argv: Sequence[str],
    python_executable: str = sys.executable,
    worker_cmd_override: Optional[Callable[[Path, int], List[str]]] = None,
) -> Dict[str, Any]:
    """Execute ``worker_mode`` sequentially in two separate OS subprocesses and build ``q2q3_repeat.json``."""
    out_dir = out_dir.resolve()
    run2_dir = out_dir / REPEAT_DIR_NAME / "run-2"
    out_dir.mkdir(parents=True, exist_ok=True)
    run2_dir.mkdir(parents=True, exist_ok=True)

    metas: List[Dict[str, Any]] = []
    t_total0 = time.perf_counter()

    for idx, target_dir in enumerate((out_dir, run2_dir), start=1):
        if worker_cmd_override is not None:
            cmd = worker_cmd_override(target_dir, idx)
        else:
            cmd = [
                python_executable,
                str(Path(__file__).resolve()),
                "--mode",
                worker_mode,
                "--out",
                str(target_dir),
                *list(base_argv),
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise Q2Q3Stop(
                f"第 {idx} 次独立进程失败（exit={proc.returncode}）：{proc.stderr.strip() or proc.stdout.strip()}"
            )
        meta_path = target_dir / "worker_meta.json"
        if not meta_path.is_file():
            raise Q2Q3Stop(f"第 {idx} 次独立进程未写出 worker_meta.json：{meta_path}")
        metas.append(json.loads(meta_path.read_text(encoding="utf-8")))

    total_wall = round(time.perf_counter() - t_total0, 4)

    rel_prefix = f"{REPEAT_DIR_NAME}/run-2/"
    runs = [
        {
            "run_index": 1,
            "run_id": str(metas[0]["run_id"]),
            "pid": int(metas[0]["pid"]),
            "started_at": str(metas[0]["started_at"]),
            "finished_at": str(metas[0]["finished_at"]),
            "wall_time_s": float(metas[0]["wall_time_s"]),
            "peak_rss_mib": metas[0].get("peak_rss_mib"),
            "results_file": str(metas[0]["results_file"]),
            "results_sha256": str(metas[0]["results_sha256"]),
            "digest_sha256": str(metas[0]["digest_sha256"]),
        },
        {
            "run_index": 2,
            "run_id": str(metas[1]["run_id"]),
            "pid": int(metas[1]["pid"]),
            "started_at": str(metas[1]["started_at"]),
            "finished_at": str(metas[1]["finished_at"]),
            "wall_time_s": float(metas[1]["wall_time_s"]),
            "peak_rss_mib": metas[1].get("peak_rss_mib"),
            "results_file": rel_prefix + str(metas[1]["results_file"]),
            "results_sha256": str(metas[1]["results_sha256"]),
            "digest_sha256": str(metas[1]["digest_sha256"]),
        },
    ]
    manifest = {
        "contract": REPEAT_CONTRACT,
        "worker_mode": worker_mode,
        "n_runs": 2,
        "delivery_run_index": 1,
        "selection_rule": "not best-of: run 1 is the delivery; run 2 must agree",
        "total_wall_time_s": total_wall,
        "digests_identical": runs[0]["digest_sha256"] == runs[1]["digest_sha256"],
        "runs": runs,
    }
    rep_sha = _write_json_lf(out_dir / "q2q3_repeat.json", manifest)

    sums_path = out_dir / "SHA256SUMS.txt"
    sums: Dict[str, str] = {}
    if sums_path.is_file():
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                dig, fn = line.split(None, 1)
                sums[fn.strip()] = dig
    sums["q2q3_repeat.json"] = rep_sha
    sums[runs[1]["results_file"]] = runs[1]["results_sha256"]
    _write_sha256sums_lf(out_dir, sums)

    verify_repeat_manifest(out_dir)
    return manifest


def _build_worker_base_argv(args: argparse.Namespace, repo: Path, data_root: Path, manifest_path: Path) -> List[str]:
    argv = [
        "--repo",
        str(repo),
        "--data-root",
        str(data_root),
        "--manifest",
        str(manifest_path),
        "--approval-ref",
        str(args.approval_ref),
    ]
    if args.q1_dir:
        argv += ["--q1-dir", str(Path(args.q1_dir).resolve())]
    if args.allow_unfrozen_q1_diagnostic:
        argv.append("--allow-unfrozen-q1-diagnostic")
    if args.implementation_sha:
        argv += ["--implementation-sha", str(args.implementation_sha)]
    if args.parent_commit:
        argv += ["--parent-commit", str(args.parent_commit)]
    if args.main_commit:
        argv += ["--main-commit", str(args.main_commit)]
    if args.overwrite:
        argv.append("--overwrite")
    return argv


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Q2 / Q3 实测准入与双进程执行入口（默认 --mode check，不读取采样）"
    )
    parser.add_argument("--repo", default=str(REPO_ROOT), help="仓库根目录")
    parser.add_argument("--data-root", default=None, help="A 题数据根目录")
    parser.add_argument("--manifest", default=None, help="R0 a_dat_manifest.csv 路径")
    parser.add_argument("--q1-dir", default=None, help="上游 Q1 校准产物目录")
    parser.add_argument("--out", default=None, help="输出目录")
    parser.add_argument(
        "--mode",
        choices=("check", "d1-audit", "d1-audit-worker", "execute", "execute-worker"),
        default="check",
        help="执行模式（默认 check）",
    )
    parser.add_argument("--approval-ref", default=None, help="统筹放行编号（d1-audit/execute 必填，强制核验仓库 origin/main 受信任审批表）")
    parser.add_argument("--repeat-runs", type=int, default=2, help="独立重跑进程数（execute 必须为 2）")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有结果目录")
    parser.add_argument(
        "--allow-unfrozen-q1-diagnostic",
        action="store_true",
        help="execute 允许挂载未冻结 Q1 基线仅作诊断（citable=false，需单独诊断审批）",
    )
    parser.add_argument("--implementation-sha", default=None, help="40 位实现提交 SHA")
    parser.add_argument("--parent-commit", default=None, help="父提交 SHA")
    parser.add_argument("--main-commit", default=None, help="主线基线 SHA")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    repo = Path(args.repo).resolve()
    data_root = Path(args.data_root).resolve() if args.data_root else (repo / PF2.A_ROOT_DEFAULT)
    manifest_path = Path(args.manifest).resolve() if args.manifest else (repo / "recon/manifests/a_dat_manifest.csv")
    q1_dir = Path(args.q1_dir).resolve() if args.q1_dir else None
    approval_record_path = None

    if args.out:
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = repo / out_dir
    elif args.mode == "check":
        out_dir = DEFAULT_CHECK_OUT
    elif args.mode in ("d1-audit", "d1-audit-worker"):
        out_dir = DEFAULT_D1_OUT
    else:
        out_dir = DEFAULT_EXEC_OUT

    guard_err = validate_cli_guards(
        repo=repo,
        mode=args.mode,
        approval_ref=args.approval_ref,
        approval_record_path=approval_record_path,
        repeat_runs=args.repeat_runs,
        out_dir=out_dir,
        overwrite=bool(args.overwrite),
        q1_dir=q1_dir,
        allow_unfrozen_q1_diagnostic=bool(args.allow_unfrozen_q1_diagnostic),
    )
    if guard_err is not None:
        print(json.dumps({"error": guard_err, "exit_code": 2}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.mode == "check":
        payload = run_check(
            repo=repo,
            data_root=data_root,
            manifest_path=manifest_path,
            q1_dir=q1_dir,
            allow_unfrozen_q1_diagnostic=bool(args.allow_unfrozen_q1_diagnostic),
            approval_ref=args.approval_ref,
            approval_record_path=approval_record_path,
            out_dir=out_dir,
        )
        print(
            json.dumps(
                {
                    "mode": "check",
                    "preconditions_pass": payload["preflight"]["preconditions_pass"],
                    "execution_ready": payload["preflight"]["execution_ready"],
                    "packets_parsed": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0 if payload["preflight"]["execution_ready"] else 1

    cmd_str = " ".join(sys.argv)
    try:
        if args.mode == "d1-audit-worker":
            res, _ = run_d1_audit_worker(
                repo=repo,
                data_root=data_root,
                manifest_path=manifest_path,
                out_dir=out_dir,
                approval_ref=str(args.approval_ref),
                approval_record_path=approval_record_path,
                implementation_sha=args.implementation_sha,
                parent_commit=args.parent_commit,
                main_commit=args.main_commit,
                command=cmd_str,
            )
            print(json.dumps({"mode": "d1-audit-worker", "digest_sha256": res["digest_sha256"]}, ensure_ascii=False))
            return 0

        if args.mode == "d1-audit":
            if args.repeat_runs == 1:
                res, _ = run_d1_audit_worker(
                    repo=repo,
                    data_root=data_root,
                    manifest_path=manifest_path,
                    out_dir=out_dir,
                    approval_ref=str(args.approval_ref),
                    approval_record_path=approval_record_path,
                    implementation_sha=args.implementation_sha,
                    parent_commit=args.parent_commit,
                    main_commit=args.main_commit,
                    command=cmd_str,
                )
                print(json.dumps({"mode": "d1-audit", "repeat_runs": 1, "digest_sha256": res["digest_sha256"]}, ensure_ascii=False))
                return 0

            manifest = run_two_independent_runs(
                worker_mode="d1-audit-worker",
                out_dir=out_dir,
                base_argv=_build_worker_base_argv(args, repo, data_root, manifest_path),
            )
            print(json.dumps({"mode": "d1-audit", "repeat_runs": 2, "digests_identical": manifest["digests_identical"]}, ensure_ascii=False))
            return 0

        if args.mode == "execute-worker":
            assert q1_dir is not None
            summary, _ = run_execute_worker(
                repo=repo,
                data_root=data_root,
                manifest_path=manifest_path,
                q1_dir=q1_dir,
                allow_unfrozen_q1_diagnostic=bool(args.allow_unfrozen_q1_diagnostic),
                out_dir=out_dir,
                approval_ref=str(args.approval_ref),
                approval_record_path=approval_record_path,
                implementation_sha=args.implementation_sha,
                parent_commit=args.parent_commit,
                main_commit=args.main_commit,
                command=cmd_str,
            )
            print(json.dumps({"mode": "execute-worker", "digest_sha256": summary["digest_sha256"]}, ensure_ascii=False))
            return 0

        # mode == "execute"
        manifest = run_two_independent_runs(
            worker_mode="execute-worker",
            out_dir=out_dir,
            base_argv=_build_worker_base_argv(args, repo, data_root, manifest_path),
        )
        print(json.dumps({"mode": "execute", "repeat_runs": 2, "digests_identical": manifest["digests_identical"]}, ensure_ascii=False))
        return 0
    except Q2Q3Stop as exc:
        print(json.dumps({"error": str(exc), "exit_code": 3}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
