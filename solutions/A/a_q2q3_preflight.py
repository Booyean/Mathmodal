#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Q2 / Q3 empirical admission preflight (metadata & SHA256 only, zero packet/signal parsing).

Distinguishes:
- ``manifest_entries_count`` (expected 481 Attachment-3 entries in R0 manifest: 264 wall + 217 metal),
- ``max_protocol_parseable_files`` (expected 480 valid 8-row group files: 33*8 wall + 27*8 metal),
- ``orphan_files_count`` (expected 1 zero-byte orphan file excluded from protocol parsing).

Supports ``--mode d1-audit`` (runs without any Q1 frozen artifact) and ``--mode execute``
(verifies Q1 calibration / freeze status unless ``--allow-unfrozen-q1-diagnostic`` is set).
Never calls ``a_dat_reader.discover_groups()``; enforces lexical + anti-reparse + realpath
guards via ``e0c_preflight.guard_group_dir`` and ``guard_dat_path`` before any ``stat``/``open``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import e0c_preflight as PF  # noqa: E402


CONTRACT_VERSION = "Q2Q3-PREFLIGHT-1"
SCOPE = "metadata_only_no_signal_parse"

A_ROOT_DEFAULT = PF.A_ROOT_DEFAULT
ATTACHMENT3_PREFIX = "附件/附件3-成像数据/"
WALL_DATASET = "附件3-成像数据/墙体"
METAL_DATASET = "附件3-成像数据/金属柱和金属铲"
DATASET_SPECS: Tuple[Tuple[str, str], ...] = (
    (WALL_DATASET, "wall"),
    (METAL_DATASET, "metal"),
)

EXPECTED_WALL_GROUPS = 33
EXPECTED_WALL_FILES = 264
EXPECTED_METAL_VALID_GROUPS = 27
EXPECTED_METAL_GROUP_FILES = 216
EXPECTED_ORPHAN_FILES = 1
EXPECTED_MANIFEST_ENTRIES = 481
EXPECTED_MAX_PROTOCOL_FILES = 480

_ROW_RE = re.compile(r"^(?P<prefix>.+)_(?P<row>[0-7])\.dat$", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dataset_dir(data_root: Path, dataset: str) -> Path:
    return data_root / "附件" / Path(dataset.replace("\\", "/"))


def _classify_attachment3_manifest(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """Group Attachment-3 manifest rows into valid 8-row groups (<=480) vs orphans (1)."""
    att3_rows = [r for r in rows if str(r["rel_path"]).startswith(ATTACHMENT3_PREFIX)]
    buckets: Dict[Tuple[str, str], Dict[int, Dict[str, Any]]] = {}
    unmatched: List[Dict[str, Any]] = []

    for row in att3_rows:
        rel = str(row["rel_path"]).replace("\\", "/")
        parts = rel.split("/")
        if len(parts) < 4:
            unmatched.append({"rel_path": rel, "size_bytes": int(row["size_bytes"]), "reason": "unexpected_path_depth"})
            continue
        ds = "/".join(parts[1:3])
        fname = parts[-1]
        m = _ROW_RE.match(fname)
        if ds not in (WALL_DATASET, METAL_DATASET) or not m:
            unmatched.append({"rel_path": rel, "size_bytes": int(row["size_bytes"]), "reason": "unexpected_dataset_or_name"})
            continue
        prefix = m.group("prefix")
        r_idx = int(m.group("row"))
        key = (ds, prefix)
        buckets.setdefault(key, {})
        if r_idx in buckets[key]:
            unmatched.append({"rel_path": rel, "size_bytes": int(row["size_bytes"]), "reason": "duplicate_row_in_manifest"})
            continue
        buckets[key][r_idx] = {
            "row": r_idx,
            "file": fname,
            "rel_path": rel,
            "size_bytes": int(row["size_bytes"]),
            "sha256": str(row["sha256"]).lower(),
        }

    parseable_groups: List[Dict[str, Any]] = []
    orphan_files: List[Dict[str, Any]] = list(unmatched)

    for (ds, prefix) in sorted(buckets):
        row_map = buckets[(ds, prefix)]
        has_all_rows = sorted(row_map.keys()) == list(range(8))
        all_nonzero = all(int(item["size_bytes"]) > 0 for item in row_map.values())
        if has_all_rows and all_nonzero:
            files = [row_map[r] for r in range(8)]
            parseable_groups.append(
                {
                    "dataset": ds,
                    "group_key": f"{ds}/{prefix}",
                    "prefix": prefix,
                    "dir_rel": f"附件/{ds}",
                    "files": files,
                }
            )
        else:
            for r_idx, item in sorted(row_map.items()):
                reason = "zero_byte_orphan_file" if int(item["size_bytes"]) == 0 else "incomplete_group_orphan"
                orphan_files.append(
                    {
                        "rel_path": item["rel_path"],
                        "dataset": ds,
                        "prefix": prefix,
                        "row": r_idx,
                        "size_bytes": int(item["size_bytes"]),
                        "sha256": item["sha256"],
                        "reason": reason,
                    }
                )

    wall_groups = [g for g in parseable_groups if g["dataset"] == WALL_DATASET]
    metal_groups = [g for g in parseable_groups if g["dataset"] == METAL_DATASET]
    counts = {
        "manifest_entries_count": len(att3_rows),
        "max_protocol_parseable_files": sum(len(g["files"]) for g in parseable_groups),
        "orphan_files_count": len(orphan_files),
        "wall_valid_groups_count": len(wall_groups),
        "wall_files_count": sum(len(g["files"]) for g in wall_groups),
        "metal_valid_groups_count": len(metal_groups),
        "metal_group_files_count": sum(len(g["files"]) for g in metal_groups),
        "metal_manifest_entries_count": sum(1 for r in att3_rows if r["rel_path"].startswith(f"附件/{METAL_DATASET}/")),
    }
    return parseable_groups, orphan_files, counts


def check_code_and_contracts(repo: Path, ck: PF.Checker) -> bool:
    d0_ok = (repo / "solutions/A/a_dat_reader.py").is_file()
    ck.add(
        "code.d0_reader",
        "code",
        d0_ok,
        "D0 读取器在库（solutions/A/a_dat_reader.py）" if d0_ok else "缺少 solutions/A/a_dat_reader.py",
    )

    fg_path = repo / "solutions/A/a_fold_gate.py"
    fg_ok = fg_path.is_file() and bool(
        re.search(r'CONTRACT_VERSION\s*=\s*"D1-2"', fg_path.read_text(encoding="utf-8", errors="replace"))
    )
    ck.add(
        "code.fold_gate_d1_2",
        "code",
        fg_ok,
        "折迭门控契约版本 CONTRACT_VERSION=D1-2" if fg_ok else "折迭门控缺失或版本非 D1-2",
    )

    solvers_ok = all(
        (repo / rel).is_file()
        for rel in (
            "solutions/A/a_q2q3_common.py",
            "solutions/A/a_q2_solver.py",
            "solutions/A/a_q3_solver.py",
            "solutions/A/validate_q2_q3_outputs.py",
        )
    )
    ck.add(
        "code.q2q3_solvers",
        "code",
        solvers_ok,
        "Q2/Q3 核心求解与契约校验模块齐全" if solvers_ok else "缺少 Q2/Q3 求解或校验模块",
    )

    schema_path = repo / "solutions/A/q2_q3_output_contract.json"
    schema_ok = schema_path.is_file()
    if schema_ok:
        try:
            schema = PF.load_json(schema_path)
            schema_ok = isinstance(schema, dict) and "status_enum" in schema and "q3_metal_contract" in schema
        except Exception:
            schema_ok = False
    ck.add(
        "contract.q2q3_schema",
        "contract",
        schema_ok,
        "q2_q3_output_contract.json 有效且含 status_enum" if schema_ok else "q2_q3_output_contract.json 缺失或无效",
    )

    runner_path = repo / "solutions/A/run_q2_q3_empirical.py"
    runner_present = runner_path.is_file() and runner_path.stat().st_size > 0
    ck.add(
        "code.q2q3_empirical_runner_present",
        "readiness",
        runner_present,
        "Q2/Q3 实测主入口已交付" if runner_present else "缺少 solutions/A/run_q2_q3_empirical.py",
    )
    return runner_present


def check_q1_dependency(
    mode: str,
    q1_dir: Optional[Path],
    allow_unfrozen_q1_diagnostic: bool,
    ck: PF.Checker,
) -> Dict[str, Any]:
    if mode == "d1-audit":
        info = {
            "required": False,
            "q1_dir": str(q1_dir) if q1_dir else None,
            "frozen": bool(q1_dir and (q1_dir / "e0c_frozen.json").is_file()),
            "status": "not_required_for_d1_audit",
        }
        ck.add(
            "q1.dependency",
            "q1",
            True,
            "D1 审计模式无需 Q1 冻结产物（可独立于 Q1 校准先行自检）",
            **info,
        )
        return info

    if q1_dir is None:
        info = {"required": True, "q1_dir": None, "frozen": False, "status": "missing_q1_dir"}
        ck.add("q1.dependency", "q1", False, "execute 模式必须提供 --q1-dir", **info)
        return info

    arrays_path = q1_dir / "e0c_arrays.npz"
    results_path = q1_dir / "e0c_results.json"
    frozen_path = q1_dir / "e0c_frozen.json"
    has_arrays = arrays_path.is_file()
    has_frozen = frozen_path.is_file()

    if not has_arrays:
        info = {"required": True, "q1_dir": str(q1_dir), "frozen": has_frozen, "status": "missing_q1_arrays"}
        ck.add("q1.dependency", "q1", False, f"Q1 目录缺少 e0c_arrays.npz: {q1_dir}", **info)
        return info

    if has_frozen:
        try:
            frozen_obj = PF.load_json(frozen_path)
            frozen_valid = bool(frozen_obj.get("implementation_sha")) and "lambdas" in frozen_obj
        except Exception:
            frozen_valid = False
        info = {
            "required": True,
            "q1_dir": str(q1_dir),
            "frozen": frozen_valid,
            "arrays_sha256": PF.sha256_file(arrays_path),
            "frozen_sha256": PF.sha256_file_lf(frozen_path) if frozen_valid else None,
            "status": "frozen_ready" if frozen_valid else "invalid_frozen_json",
        }
        ck.add(
            "q1.dependency",
            "q1",
            frozen_valid,
            "已检测到有效 Q1 冻结校准产物 e0c_frozen.json" if frozen_valid else "e0c_frozen.json 格式无效",
            **info,
        )
        return info

    if allow_unfrozen_q1_diagnostic and results_path.is_file():
        info = {
            "required": True,
            "q1_dir": str(q1_dir),
            "frozen": False,
            "diagnostic_mode": True,
            "arrays_sha256": PF.sha256_file(arrays_path),
            "results_sha256": PF.sha256_file_lf(results_path),
            "status": "unfrozen_q1_diagnostic_only",
        }
        ck.add(
            "q1.dependency",
            "q1",
            True,
            "已显式声明 --allow-unfrozen-q1-diagnostic：挂载未冻结 Q1 基线仅作诊断（citable=false）",
            **info,
        )
        return info

    info = {"required": True, "q1_dir": str(q1_dir), "frozen": False, "status": "q1_not_frozen"}
    ck.add(
        "q1.dependency",
        "q1",
        False,
        "Q1 尚未冻结（缺少 e0c_frozen.json），正式 Q2/Q3 execute 被阻塞",
        **info,
    )
    return info


def check_attachment3_data(
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    ck: PF.Checker,
    *,
    check_hashes: bool = True,
    expected_manifest_overall_sha256: Optional[str] = None,
    expected_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Verify Attachment-3 whitelist inventory (481 manifest vs <=480 parseable + 1 orphan) with path guard."""
    expected_overall = expected_manifest_overall_sha256 or PF.APPROVED_ANCHORS["dat_manifest_overall_sha256"]
    exp = expected_counts or {
        "manifest_entries_count": EXPECTED_MANIFEST_ENTRIES,
        "max_protocol_parseable_files": EXPECTED_MAX_PROTOCOL_FILES,
        "orphan_files_count": EXPECTED_ORPHAN_FILES,
        "wall_valid_groups_count": EXPECTED_WALL_GROUPS,
        "wall_files_count": EXPECTED_WALL_FILES,
        "metal_valid_groups_count": EXPECTED_METAL_VALID_GROUPS,
        "metal_group_files_count": EXPECTED_METAL_GROUP_FILES,
    }

    info: Dict[str, Any] = {
        "packets_parsed": 0,
        "signal_files_hashed": 0,
        "opened_dat_files": [],
        "protocol_parseable_groups": [],
        "orphan_files": [],
        "manifest_entries_count": 0,
        "max_protocol_parseable_files": 0,
        "orphan_files_count": 0,
    }

    if not manifest_path.is_file():
        ck.add("data.manifest_present", "data", False, f"缺少 R0 清单 {PF.rel_to(manifest_path, repo)}")
        return info

    try:
        rows = PF.manifest_rows(manifest_path)
    except Exception as exc:
        ck.add("data.manifest_parse", "data", False, f"R0 清单无法解析：{exc}")
        return info

    overall = PF.manifest_overall_sha256(rows)
    info["manifest_overall_sha256"] = overall
    ck.add(
        "data.manifest_overall_sha256",
        "data",
        overall == expected_overall,
        "R0 清单总体 SHA256 匹配" if overall == expected_overall else "R0 清单总体 SHA256 不匹配",
        actual=overall,
        expected=expected_overall,
        total_manifest_rows=len(rows),
    )

    parseable_groups, orphan_files, counts = _classify_attachment3_manifest(rows)
    info.update(counts)
    info["orphan_files"] = orphan_files

    counts_ok = (
        counts["manifest_entries_count"] == exp["manifest_entries_count"]
        and counts["max_protocol_parseable_files"] == exp["max_protocol_parseable_files"]
        and counts["orphan_files_count"] == exp["orphan_files_count"]
        and counts["wall_valid_groups_count"] == exp["wall_valid_groups_count"]
        and counts["metal_valid_groups_count"] == exp["metal_valid_groups_count"]
    )
    ck.add(
        "data.attachment3_accounting",
        "data",
        counts_ok,
        (
            f"清单条目 {counts['manifest_entries_count']} = 可进入协议解析 {counts['max_protocol_parseable_files']} "
            f"({counts['wall_valid_groups_count']}墙体+{counts['metal_valid_groups_count']}金属) + "
            f"单独登记 0B/孤儿 {counts['orphan_files_count']}"
        ),
        **counts,
        expected=exp,
    )

    if not data_root.is_dir():
        ck.add("data.root", "data", False, f"数据根目录不存在：{data_root}")
        return info
    ck.add("data.root", "data", True, "数据根目录存在", root=str(data_root))

    if not check_hashes:
        ck.add("data.hash_skipped", "data", False, "--no-hash：未核对 .dat 摘要，不能作为放行证据")
        return info

    data_root_real = Path(os.path.realpath(str(data_root)))
    guarded: List[str] = []
    opened: List[str] = []
    rejections: List[Dict[str, str]] = []
    problems: List[str] = []
    verified_parseable_files = 0
    verified_orphan_files = 0
    total_bytes = 0

    expected_by_rel: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for grp in parseable_groups:
        for f in grp["files"]:
            expected_by_rel[f["rel_path"]] = ("parseable", f)
    for orp in orphan_files:
        expected_by_rel[orp["rel_path"]] = ("orphan", orp)

    real_dataset_dirs: Dict[str, Path] = {}
    guarded_by_rel: Dict[str, Path] = {}
    for ds, _ in DATASET_SPECS:
        ds_dir = dataset_dir(data_root, ds)
        try:
            real_ds = PF.guard_group_dir(ds_dir, data_root)
        except PF.PathGuardError as exc:
            problems.append(f"{ds}：数据集目录未通过路径校验 - {exc}")
            rejections.append({"dataset": ds, "path": str(ds_dir), "kind": "dataset_dir", "reason": str(exc)})
            continue
        real_dataset_dirs[ds] = real_ds

        # Inspect directory entries strictly with guard_dat_path before stat/open
        seen_in_dir: Dict[str, Path] = {}
        for entry in sorted(real_ds.iterdir()):
            if entry.suffix.lower() != ".dat":
                continue
            try:
                real_entry = PF.guard_dat_path(entry, real_ds, data_root_real)
            except PF.PathGuardError as exc:
                problems.append(f"{ds}：{entry.name} 未通过读前路径校验 - {exc}")
                rejections.append({"dataset": ds, "path": str(entry), "kind": "dat_entry", "reason": str(exc)})
                continue
            guarded.append(str(real_entry))
            rel_key = f"附件/{ds}/{entry.name}"
            seen_in_dir[rel_key] = real_entry
            guarded_by_rel[rel_key] = real_entry
            if rel_key not in expected_by_rel:
                problems.append(f"{ds}：出现清单外文件 {entry.name}")

        # Verify expected manifest entries for this dataset
        ds_prefix = f"附件/{ds}/"
        for rel_key, (kind, rec) in sorted(expected_by_rel.items()):
            if not rel_key.startswith(ds_prefix):
                continue
            if rel_key not in seen_in_dir:
                problems.append(f"{ds}：缺少清单条目 {rel_key}")
                continue
            real_path = seen_in_dir[rel_key]
            try:
                size = real_path.stat().st_size
            except OSError as exc:
                problems.append(f"{rel_key} 无法 stat：{exc}")
                continue
            total_bytes += size
            if size != int(rec["size_bytes"]):
                problems.append(f"{rel_key} 大小 {size} != 清单 {rec['size_bytes']}")
                continue
            if kind == "orphan":
                if size != 0:
                    problems.append(f"{rel_key} 孤儿文件大小 {size} != 0")
                    continue
                # Zero-byte orphan file: verify empty SHA256 if recorded, never treated as parseable group
                digest = PF.sha256_file(real_path, opened)
                if rec.get("sha256") and digest != rec["sha256"]:
                    problems.append(f"{rel_key} 孤儿 SHA256 不符")
                    continue
                verified_orphan_files += 1
            else:
                if size <= 0:
                    problems.append(f"{rel_key} 非孤儿文件为 0 字节")
                    continue
                digest = PF.sha256_file(real_path, opened)
                if digest != rec["sha256"]:
                    problems.append(f"{rel_key} SHA256 不符")
                    continue
                verified_parseable_files += 1

    # Populate guarded paths inside protocol_parseable_groups for downstream workers
    guarded_groups: List[Dict[str, Any]] = []
    for grp in parseable_groups:
        ds = grp["dataset"]
        if ds not in real_dataset_dirs:
            continue
        files_with_paths = []
        for f in grp["files"]:
            rp = guarded_by_rel.get(f["rel_path"])
            if rp is None:
                break
            f_copy = dict(f)
            f_copy["guarded_path"] = str(rp)
            files_with_paths.append(f_copy)
        if len(files_with_paths) == 8:
            g_copy = dict(grp)
            g_copy["dir_real"] = str(real_dataset_dirs[ds])
            g_copy["files"] = files_with_paths
            guarded_groups.append(g_copy)

    info["protocol_parseable_groups"] = guarded_groups
    info["verified_protocol_parseable_files"] = verified_parseable_files
    info["verified_orphan_files"] = verified_orphan_files
    info["signal_files_hashed"] = len(opened)
    info["total_bytes"] = total_bytes
    info["opened_dat_files"] = [PF.rel_to(Path(p), repo) for p in opened]
    info["path_guard"] = {
        "rule": "lexical_parent -> lstat_no_reparse -> realpath_within_dataset_and_root",
        "applied_before": ["stat", "open"],
        "guarded_files": len(guarded),
        "rejections": rejections,
        "data_root_real": str(data_root_real),
    }

    inv_ok = (
        not problems
        and verified_parseable_files == exp["max_protocol_parseable_files"]
        and verified_orphan_files == exp["orphan_files_count"]
    )
    ck.add(
        "data.inventory",
        "data",
        inv_ok,
        (
            f"附件3 清单 {exp['manifest_entries_count']} 条目核验通过："
            f"{verified_parseable_files} 份进入协议解析 + {verified_orphan_files} 份 0B 孤儿单列"
            if inv_ok
            else "附件3 数据清单核验存在异常或缺失"
        ),
        verified_protocol_parseable_files=verified_parseable_files,
        verified_orphan_files=verified_orphan_files,
        total_bytes=total_bytes,
        problems=problems[:20],
        problem_count=len(problems),
    )

    guard_ok = not rejections and len(guarded) == exp["manifest_entries_count"]
    ck.add(
        "data.path_guard",
        "data",
        guard_ok,
        (
            f"{len(guarded)} 个条目在 stat/open 之前均通过读前路径校验"
            if guard_ok
            else "存在未通过读前路径校验的条目或受保护计数不足"
        ),
        guarded_files=len(guarded),
        rejected=len(rejections),
        rejections=rejections[:10],
    )

    allowed_dirs = list(real_dataset_dirs.values())
    outside = PF.find_out_of_scope(opened, allowed_dirs) if allowed_dirs else list(opened)
    # Also explicitly ensure no Attachment-2 / test path was opened
    leaked_att2 = [p for p in opened if ("附件2" in p or "_test" in Path(p).name)]
    no_leak = not outside and not leaked_att2 and len(opened) == exp["manifest_entries_count"]
    ck.add(
        "data.no_out_of_scope_open",
        "data",
        no_leak,
        "实际校验文件全部落在附件3白名单两目录内（零附件2/留出组接触）" if no_leak else "存在越界打开或文件数不符",
        outside=outside,
        leaked_att2=leaked_att2,
    )
    return info


def run_preflight(
    repo: Path,
    data_root: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    *,
    mode: str = "d1-audit",
    q1_dir: Optional[Path] = None,
    allow_unfrozen_q1_diagnostic: bool = False,
    check_hashes: bool = True,
    expected_manifest_overall_sha256: Optional[str] = None,
    expected_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Run Q2/Q3 preflight checks without parsing any ``.dat`` signal packet."""
    if mode not in ("d1-audit", "execute"):
        raise ValueError(f"Unsupported preflight mode: {mode!r}")

    started = time.perf_counter()
    repo = repo.resolve()
    data_root = (data_root or (repo / A_ROOT_DEFAULT)).resolve()
    manifest_path = (manifest_path or (repo / "recon/manifests/a_dat_manifest.csv")).resolve()
    q1_resolved = q1_dir.resolve() if q1_dir is not None else None

    ck = PF.Checker()
    runner_present = check_code_and_contracts(repo, ck)
    q1_info = check_q1_dependency(mode, q1_resolved, allow_unfrozen_q1_diagnostic, ck)
    data_info = check_attachment3_data(
        repo,
        data_root,
        manifest_path,
        ck,
        check_hashes=check_hashes,
        expected_manifest_overall_sha256=expected_manifest_overall_sha256,
        expected_counts=expected_counts,
    )

    failed_ids = ck.failed_ids
    blocking_ids = [c["id"] for c in ck.checks if not c["passed"] and c["group"] != "readiness"]
    preconditions_pass = not blocking_ids

    return {
        "contract_version": CONTRACT_VERSION,
        "scope": SCOPE,
        "mode": mode,
        "generated_at": _now_iso(),
        "elapsed_s": round(time.perf_counter() - started, 4),
        "repo": str(repo),
        "data_root": str(data_root),
        "manifest_path": str(manifest_path),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "preconditions_pass": preconditions_pass,
        "execution_ready": bool(preconditions_pass and runner_present),
        "overall_pass": preconditions_pass,
        "packets_parsed": 0,
        "real_dat_packets_parsed": 0,
        "q1": q1_info,
        "data": data_info,
        "checks": ck.checks,
        "summary": {
            "total": len(ck.checks),
            "passed": sum(1 for c in ck.checks if c["passed"]),
            "failed": len(failed_ids),
            "failed_ids": failed_ids,
            "blocking_ids": blocking_ids,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Q2/Q3 实测准入预检（仅元数据与读前路径校验，零采样解析）"
    )
    parser.add_argument("--repo", default=str(REPO_ROOT), help="仓库根目录")
    parser.add_argument("--data-root", default=None, help="A 题数据根目录")
    parser.add_argument("--manifest", default=None, help="R0 a_dat_manifest.csv 路径")
    parser.add_argument(
        "--mode",
        choices=("d1-audit", "execute"),
        default="d1-audit",
        help="d1-audit（无需 Q1 冻结）或 execute（需 Q1 冻结或显式诊断标记）",
    )
    parser.add_argument("--q1-dir", default=None, help="上游 Q1 校准产物目录")
    parser.add_argument(
        "--allow-unfrozen-q1-diagnostic",
        action="store_true",
        help="execute 模式下允许挂载未冻结 Q1 基线仅作诊断",
    )
    parser.add_argument("--no-hash", action="store_true", help="跳过 SHA256 校验（不作为放行证据）")
    parser.add_argument("--out", default=None, help="输出预检 JSON 路径")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    try:
        result = run_preflight(
            repo=Path(args.repo),
            data_root=Path(args.data_root) if args.data_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            mode=args.mode,
            q1_dir=Path(args.q1_dir) if args.q1_dir else None,
            allow_unfrozen_q1_diagnostic=bool(args.allow_unfrozen_q1_diagnostic),
            check_hashes=not bool(args.no_hash),
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    # Strip large per-file guarded paths from serialized summary while preserving counts/orphans
    compact = dict(result)
    compact_data = dict(result["data"])
    groups_summary = [
        {
            "dataset": g["dataset"],
            "group_key": g["group_key"],
            "prefix": g["prefix"],
            "file_count": len(g["files"]),
        }
        for g in compact_data.get("protocol_parseable_groups", [])
    ]
    compact_data["protocol_parseable_groups"] = groups_summary
    compact["data"] = compact_data

    payload = (json.dumps(compact, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = Path(args.repo).resolve() / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
    else:
        sys.stdout.write(payload.decode("utf-8"))

    return 0 if result["preconditions_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
