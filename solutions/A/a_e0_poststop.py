#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E0-C 硬停后的目标结果再生入口（契约 ``E0-C-POSTSTOP-1``）。

背景
----
``a_e0_c.py`` 是"先全量求解、后统一判定"：``run_execute`` 在读完 12 组白名单后
先跑 ``solve_bundle``（空场 LOO → 校准 → 直射波抑制 → 两目标测距/PSLR/PNR），
之后才评估门槛。因此即使空场或目标门控**硬停**，``e0c_results.json`` 里仍有
两组目标的观测指标；这是 ``b63e217`` 失败包中目标结果存在的原因，不是漏判
（见 ``experiments/A/A-Q1-E0/e0c/DIAGNOSIS_AIR_LOO.md`` §8）。

本入口把这个"硬停后仍生成目标结果"的代码路径**单独交付**为一个可复跑、可审计的
只读步骤：从**已归档**的硬停交付包（``e0c_results.json`` + ``e0c_arrays.npz``）
按与生产实现逐字相同的度量口径重算两组目标的 ``Supp/PSLR/PNR/d_hat/abs_err``，
与报告值逐项核对，并写出一份**显式不可引用**的独立产物。

硬性边界
--------
* 只适用于 ``freeze.status == "hard_stop"`` 的包；``eligible`` / 灰区包一律拒绝。
* 不打开任何 ``.dat``、不重跑求解链、不改任何阈值、不选参、不写
  ``e0c_frozen.json``。
* 只允许 12 组白名单组；出现 ``E0-T`` 两组（``data20-73cm`` / ``data5-60cm``）、
  其他留出样、``附件3``、``B题`` 一律拒绝。
* 输出 ``citable=false``：硬停运行的 ``d_hat`` **不得**进入结果表、论文数字、
  冻结或 ``E0-T``；只能进失败登记/诊断/局限性。

用法::

    python solutions/A/a_e0_poststop.py \
        --results-dir experiments/A/A-Q1-E0/e0c/results \
        --out experiments/A/A-Q1-E0/e0c/poststop

退出码：``0`` 全部核对在容差内并写出产物；``3`` 守卫/一致性失败（诊断不通过）；
``2`` 用法错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a_e0_c as A  # noqa: E402

CONTRACT_VERSION = "E0-C-POSTSTOP-1"
DEFAULT_RESULTS_DIR = "experiments/A/A-Q1-E0/e0c/results"
DEFAULT_OUT_DIR = "experiments/A/A-Q1-E0/e0c/poststop"
DEFAULT_CONFIG = "experiments/A/A-Q1-E0/config.json"
DEFAULT_C0_M_S = 299792458.0

#: 本入口只接受这些组名；出现其他任何组都视为越界。
WHITELIST_GROUPS: Tuple[str, ...] = (
    "空场数据/data1",
    "空场数据/data2",
    "空场数据/data3",
    "空场数据/data4",
    "空场数据/data5",
    "空场数据/data6",
    "空场数据/data7",
    "空场数据/data8",
    "空场数据/data9",
    "空场数据/data10",
    "墙体数据/data1-42cm",
    "金属板数据/data1-69cm",
)

#: 任何命中都直接拒绝（E0-T / 留出样 / 附件3 / B 题）。
FORBIDDEN_MARKERS: Tuple[str, ...] = (
    "data20-73cm",
    "data5-60cm",
    "_test",
    "test_",
    "附件3",
    "b题",
)

TOL_DB = 1e-6
TOL_M = 1e-9


class PostStopError(RuntimeError):
    """守卫或一致性失败；``detail`` 携带机器可读证据。"""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def file_sha256(path: Path | str) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO.resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def _write_text_lf(path: Path, text: str) -> None:
    """总是写 LF；避免 Windows 下 CRLF 让 SHA256SUMS 与 Git blob 不一致。"""
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PostStopError("无法读取 JSON：%s（%s）" % (path, exc))


def load_arrays(path: Path) -> Dict[str, np.ndarray]:
    if not Path(path).is_file():
        raise PostStopError("缺少交付数组：%s" % path)
    try:
        with np.load(path) as npz:
            return {key: npz[key] for key in npz.files}
    except (OSError, ValueError) as exc:
        raise PostStopError("交付数组不可读：%s（%s）" % (path, exc))


def load_c0(config_path: Optional[Path]) -> float:
    if config_path is None or not Path(config_path).is_file():
        return DEFAULT_C0_M_S
    cfg = load_json(config_path)
    try:
        return float(cfg["physical_constants"]["c0_m_s"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_C0_M_S


# --------------------------------------------------------------------------
# 守卫
# --------------------------------------------------------------------------
def _all_group_like_strings(result: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for grp in result.get("groups") or []:
        values.append(str(grp.get("group_key") or ""))
    prefix = (result.get("array_map") or {}).get("group_prefix") or {}
    if isinstance(prefix, dict):
        values.extend(str(k) for k in prefix)
    for row in result.get("inputs") or []:
        values.append(str(row.get("rel_path") or ""))
    cases = result.get("cases") or []
    for case in cases:
        values.append(str(case.get("group_key") or ""))
    return values


def assert_whitelist_only(result: Dict[str, Any]) -> None:
    bad: List[str] = []
    for text in _all_group_like_strings(result):
        low = text.lower()
        if any(marker in low for marker in FORBIDDEN_MARKERS):
            bad.append(text)
    keys = {str(g.get("group_key") or "") for g in result.get("groups") or []}
    outside = sorted(k for k in keys if k not in WHITELIST_GROUPS)
    if bad or outside:
        raise PostStopError(
            "出现白名单外/留出组，拒绝处理",
            {"forbidden_hits": sorted(set(bad)), "unknown_groups": outside},
        )


def assert_hard_stopped(result: Dict[str, Any], results_dir: Path) -> Dict[str, Any]:
    """只接受硬停包；冻结包、灰区包、缺证据包一律拒绝。"""
    freeze = dict(result.get("freeze") or {})
    status = str(freeze.get("status") or "")
    problems: List[str] = []
    if status != "hard_stop":
        problems.append("freeze.status=%r（本入口只处理 hard_stop）" % status)
    if freeze.get("eligible") is not False:
        problems.append("freeze.eligible 不是 False")
    if freeze.get("written") is True or (Path(results_dir) / "e0c_frozen.json").is_file():
        problems.append("存在 frozen 证据（硬停包不得有）")
    if not (result.get("hard_stops") or []):
        problems.append("hard_stops 为空，无法证明这是硬停包")
    if problems:
        raise PostStopError("不是可处理的硬停包：" + "; ".join(problems))
    return freeze


def assert_arrays_identity(result: Dict[str, Any], results_dir: Path) -> Tuple[Path, str]:
    arrays_path = Path(results_dir) / str(result.get("arrays_file") or "e0c_arrays.npz")
    actual = file_sha256(arrays_path)
    claimed = str(result.get("arrays_sha256") or "")
    if claimed and claimed != actual:
        raise PostStopError(
            "交付数组 SHA256 与结果登记不一致",
            {"arrays_file": str(arrays_path), "claimed": claimed, "actual": actual},
        )
    return arrays_path, actual


# --------------------------------------------------------------------------
# 重新生成目标结果
# --------------------------------------------------------------------------
def _target_of(result: Dict[str, Any], group_key: str) -> Optional[Dict[str, Any]]:
    for case in result.get("cases") or []:
        if str(case.get("group_key") or "") == group_key:
            return case
    return None


def _capture_targets(result: Dict[str, Any], arrays: Dict[str, np.ndarray], c0: float) -> List[Dict[str, Any]]:
    prefix_map = dict((result.get("array_map") or {}).get("group_prefix") or {})
    if not prefix_map:
        raise PostStopError("array_map.group_prefix 缺失，无法定位目标数组")
    targets: List[Dict[str, Any]] = []
    for grp in result.get("groups") or []:
        if grp.get("d_hat_m") is None:
            continue
        key = str(grp.get("group_key") or "")
        if key not in prefix_map:
            raise PostStopError("目标组 %r 不在 array_map.group_prefix 中" % key)
        prefix = str(prefix_map[key])
        required = [
            "%s__tau_ns" % prefix,
            "%s__tau_dir_ns" % prefix,
            "%s__z_before" % prefix,
            "%s__z_after" % prefix,
            "%s__d_m" % prefix,
            "%s__P_after" % prefix,
        ]
        missing = [name for name in required if name not in arrays]
        if missing:
            raise PostStopError("交付数组缺少目标 %r 的字段：%s" % (key, missing))
        tau = np.asarray(arrays[required[0]], dtype=np.float64)
        tau_dir = np.asarray(arrays[required[1]], dtype=np.float64)
        zb = np.asarray(arrays[required[2]])
        za = np.asarray(arrays[required[3]])
        d_m = np.asarray(arrays[required[4]], dtype=np.float64)
        p = np.asarray(arrays[required[5]], dtype=np.float64)
        for name, arr in (("z_before", zb), ("z_after", za), ("d_m", d_m), ("P_after", p)):
            if not np.all(np.isfinite(arr)):
                raise PostStopError("目标 %r 的 %s 含 NaN/Inf" % (key, name))

        bg = A.bg_from_z(za, tau)
        supp, win_samples = A.supp_from_z(zb, za, tau, tau_dir)
        eta_wall = result.get("eta_wall")
        if str(grp.get("target_type") or "") == "wall" and eta_wall is None:
            raise PostStopError("墙体目标 %r 缺少 eta_wall，无法按预登记规则重选 d_hat" % key)
        d_hat, rule = A.select_d_hat(
            p,
            d_m,
            str(grp.get("target_type") or ""),
            float(eta_wall if eta_wall is not None else 0.0),
            bg,
        )
        pslr = A.pslr_from_p(p, d_m, d_hat)
        pnr = A.pnr_from_z(za, tau, d_hat, c0, bg)
        d_true_cm = grp.get("d_true_cm")
        abs_err = (
            abs(float(d_hat) - float(d_true_cm) / 100.0) * 100.0
            if d_true_cm is not None
            else None
        )
        recomputed = {
            "d_hat_m": float(d_hat),
            "d_hat_rule": str(rule),
            "abs_err_cm": (float(abs_err) if abs_err is not None else None),
            "supp_dw_win_db": float(supp),
            "pslr_db": float(pslr),
            "pnr_db": float(pnr),
            "bg_proxy": float(bg),
            "dw_window_samples": int(win_samples),
        }
        reported = {
            "d_hat_m": float(grp["d_hat_m"]),
            "abs_err_cm": (float(grp["abs_err_cm"]) if grp.get("abs_err_cm") is not None else None),
            "supp_dw_win_db": (float(grp["supp_dw_win_db"]) if grp.get("supp_dw_win_db") is not None else None),
            "pslr_db": (float(grp["pslr_db"]) if grp.get("pslr_db") is not None else None),
            "pnr_db": (float(grp["pnr_db"]) if grp.get("pnr_db") is not None else None),
        }
        deltas: Dict[str, Optional[float]] = {}
        for field in ("d_hat_m", "abs_err_cm", "supp_dw_win_db", "pslr_db", "pnr_db"):
            if reported[field] is None:
                deltas[field] = None
            else:
                deltas[field] = abs(float(reported[field]) - float(recomputed[field]))
        case = _target_of(result, key) or {}
        targets.append(            {
                "group_key": key,
                "target_type": str(grp.get("target_type") or ""),
                "split": str(grp.get("split") or ""),
                "d_true_cm_nominal": (float(d_true_cm) if d_true_cm is not None else None),
                "reported": reported,
                "recomputed": recomputed,
                "delta": deltas,
                "valid_rx": int(grp.get("valid_rx") or 0),
                "finite": bool(grp.get("finite")),
                "group_status": str(grp.get("status") or ""),
                "group_stop_reason": grp.get("stop_reason") or case.get("stop_reason"),
                "citable": False,
            }
        )
    return targets


def _tolerance_problems(targets: Sequence[Dict[str, Any]]) -> List[str]:
    problems: List[str] = []
    for tgt in targets:
        for field, delta in (tgt.get("delta") or {}).items():
            if delta is None:
                continue
            tol = TOL_M if field == "d_hat_m" else TOL_DB
            if float(delta) > tol:
                problems.append(
                    "%s.%s 重算与报告不一致：Δ=%.3g（容差 %.0e）"
                    % (tgt["group_key"], field, float(delta), tol)
                )
        if not tgt.get("finite"):
            problems.append("%s finite=false" % tgt["group_key"])
        if int(tgt.get("valid_rx") or 0) != 63:
            problems.append("%s valid_rx=%s" % (tgt["group_key"], tgt.get("valid_rx")))
    return problems


# --------------------------------------------------------------------------
# 组装与落盘
# --------------------------------------------------------------------------
def build_poststop_document(
    result: Dict[str, Any],
    arrays: Dict[str, np.ndarray],
    results_dir: Path,
    *,
    c0: float = DEFAULT_C0_M_S,
    arrays_sha256: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """核心入口：守卫 → 重算 → 组装。返回 (文档, 一致性问题清单)。"""
    assert_whitelist_only(result)
    freeze = assert_hard_stopped(result, results_dir)
    results_path = Path(results_dir) / "e0c_results.json"
    arrays_path = Path(results_dir) / str(result.get("arrays_file") or "e0c_arrays.npz")
    actual_arrays_sha = arrays_sha256 or file_sha256(arrays_path)
    claimed = str(result.get("arrays_sha256") or "")
    if claimed and claimed != actual_arrays_sha:
        raise PostStopError(
            "交付数组 SHA256 与结果登记不一致",
            {"claimed": claimed, "actual": actual_arrays_sha},
        )

    targets = _capture_targets(result, arrays, float(c0))
    if not targets:
        raise PostStopError("硬停包中没有可再生的目标组指标")
    problems = _tolerance_problems(targets)

    loo = result.get("lambda_loo") or {}
    document = {
        "contract": CONTRACT_VERSION,
        "generated_at_utc": _utc_now(),
        "phase": "E0-C-poststop",
        "source": {
            "results_dir": _rel(results_dir),
            "results_file": "e0c_results.json",
            "results_sha256": file_sha256(results_path),
            "arrays_file": str(result.get("arrays_file") or "e0c_arrays.npz"),
            "arrays_sha256": actual_arrays_sha,
            "arrays_sha256_match": bool(claimed == actual_arrays_sha),
            "implementation_sha": result.get("implementation_sha"),
            "parent_commit": result.get("parent_commit"),
            "main_commit": result.get("main_commit"),
            "approval_ref": result.get("approval_ref"),
            "config_sha256": result.get("config_sha256"),
        },
        "hard_stop": {
            "freeze_status": str(freeze.get("status")),
            "eligible": bool(freeze.get("eligible")),
            "frozen_file_present": (Path(results_dir) / "e0c_frozen.json").is_file(),
            "stop_reasons": list(result.get("stop_reasons") or result.get("hard_stops") or []),
            "air_loo_eligibility": result.get("air_loo_eligibility"),
            "air_loo_min_supp_db": loo.get("min_supp_db"),
            "air_loo_median_supp_db": loo.get("median_supp_db"),
        },
        "policy": {
            "citable": False,
            "usage": "diagnostic_only_after_hard_stop",
            "may_enter_results_table": False,
            "may_enter_paper_numbers": False,
            "may_be_used_for_freeze": False,
            "may_be_used_for_e0t": False,
            "note": (
                "本文件的目标指标来自一次未通过门控的硬停运行；按 E0-C 预登记与 "
                "DIAGNOSIS_AIR_LOO.md §8，硬停运行的 d_hat 一律不得作为结果引用。"
            ),
        },
        "targets": targets,
        "checks": {
            "whitelist_only": True,
            "no_frozen_file": not (Path(results_dir) / "e0c_frozen.json").is_file(),
            "arrays_sha256_match": bool(claimed == actual_arrays_sha),
            "targets_recomputed": len(targets),
            "max_delta_db": max(
                [
                    float(d)
                    for tgt in targets
                    for field, d in (tgt.get("delta") or {}).items()
                    if d is not None and field != "abs_err_cm" and field != "d_hat_m"
                ]
                or [0.0]
            ),
            "max_delta_m": max(
                [float(tgt["delta"]["d_hat_m"]) for tgt in targets if tgt["delta"].get("d_hat_m") is not None]
                or [0.0]
            ),
            "all_within_tolerance": not problems,
            "problems": problems,
        },
        "limits": [
            "0.1 mm 剖面与 0.05 ns 压缩延迟轴均来自原交付数组，未重采样。",
            "重算复用生产实现 a_e0_c.py 的度量原语，不是独立实现；独立复核归验证方。",
            "未打开任何 .dat、未重跑求解链、未选参、未改阈值、未写 e0c_frozen.json。",
            "未读取 E0-T 两组、18 组留出样、附件3 与 B 题。",
        ],
        "reproduce": (
            "python solutions/A/a_e0_poststop.py --results-dir %s --out %s"
            % (_rel(results_dir), DEFAULT_OUT_DIR)
        ),
    }
    return document, problems


def render_markdown(document: Dict[str, Any]) -> str:
    hs = document.get("hard_stop") or {}
    pol = document.get("policy") or {}
    chk = document.get("checks") or {}
    lines: List[str] = [
        "# E0-C 硬停后的目标结果再生（`%s`）" % document.get("contract"),
        "",
        "> **不可引用声明**：本文件的目标数值来自一次**未通过门控**的硬停运行；按 E0-C 预登记与",
        "> `DIAGNOSIS_AIR_LOO.md` §8，硬停运行的 `d_hat` **不得**进入结果表、论文数字、冻结或 `E0-T`，",
        "> 只能用于失败登记、诊断与局限性说明。",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 生成时间（UTC） | `%s` |" % document.get("generated_at_utc"),
        "| 源结果包 | `%s` |" % (document.get("source") or {}).get("results_dir"),
        "| 源 results SHA256 | `%s` |" % (document.get("source") or {}).get("results_sha256"),
        "| 源 arrays SHA256 | `%s` |" % (document.get("source") or {}).get("arrays_sha256"),
        "| 实现提交 | `%s` |" % (document.get("source") or {}).get("implementation_sha"),
        "| 放行引用 | `%s` |" % (document.get("source") or {}).get("approval_ref"),
        "| `freeze.status` | **`%s`**（eligible=`%s`，frozen 文件存在=`%s`）|"
        % (hs.get("freeze_status"), hs.get("eligible"), hs.get("frozen_file_present")),
        "| `stop_reasons` | %s |" % "；".join("`%s`" % s for s in (hs.get("stop_reasons") or [])),
        "| 空场 LOO | `eligibility=%s`，`min=%.4f dB`，`median=%.4f dB` |"
        % (
            hs.get("air_loo_eligibility"),
            float(hs.get("air_loo_min_supp_db") or 0.0),
            float(hs.get("air_loo_median_supp_db") or 0.0),
        ),
        "| 一致性 | `all_within_tolerance=%s`，`max|Δ|_dB=%.3g`，`max|Δ|_m=%.3g` |"
        % (chk.get("all_within_tolerance"), float(chk.get("max_delta_db") or 0.0), float(chk.get("max_delta_m") or 0.0)),
        "",
        "## 1. 两目标组（重算值 / 报告值）",
        "",
        "| 目标组 | 类型 | `d_hat` (m) | `abs_err` (cm) | `Supp` (dB) | `PSLR` (dB) | `PNR` (dB) | 组状态 | 可引用 |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for tgt in document.get("targets") or []:
        rec = tgt.get("recomputed") or {}
        rep = tgt.get("reported") or {}
        lines.append(
            "| `%s` | %s | %.6f / %.6f | %.3f / %.3f | %.3f / %.3f | %.3f / %.3f | %.2f / %.2f | `%s` | **否** |"
            % (
                tgt.get("group_key"),
                tgt.get("target_type"),
                float(rec.get("d_hat_m") or 0.0),
                float(rep.get("d_hat_m") or 0.0),
                float(rec.get("abs_err_cm") or 0.0),
                float(rep.get("abs_err_cm") or 0.0),
                float(rec.get("supp_dw_win_db") or 0.0),
                float(rep.get("supp_dw_win_db") or 0.0),
                float(rec.get("pslr_db") or 0.0),
                float(rep.get("pslr_db") or 0.0),
                float(rec.get("pnr_db") or 0.0),
                float(rep.get("pnr_db") or 0.0),
                tgt.get("group_status"),
            )
        )
    lines += [
        "",
        "> 每格为「本次从交付数组重算值 / `e0c_results.json` 报告值」。全部差值须 ≤ `1e-6 dB`",
        "> （长度 ≤ `1e-9 m`）；不满足时本入口以退出码 `3` 拒绝出具。",
        "",
        "## 2. 引用隔离字段",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        "| `citable` | `%s` |" % pol.get("citable"),
        "| `usage` | `%s` |" % pol.get("usage"),
        "| 可进结果表 / 论文数字 | `%s` / `%s` |" % (pol.get("may_enter_results_table"), pol.get("may_enter_paper_numbers")),
        "| 可用于冻结 / `E0-T` | `%s` / `%s` |" % (pol.get("may_be_used_for_freeze"), pol.get("may_be_used_for_e0t")),
        "",
        "## 3. 守卫与边界",
        "",
        "- 只接受 `freeze.status == \"hard_stop\"` 且无 `e0c_frozen.json` 的包；`eligible`/灰区包直接拒绝。",
        "- 只允许 12 组白名单；出现 `data20-73cm`、`data5-60cm`、`_test`、`附件3`、`B题` 直接拒绝。",
        "- 不打开任何 `.dat`、不重跑、不选参、不改阈值、不写冻结文件。",
        "- 重算复用 `a_e0_c.py` 的度量原语，用于核对报告值；独立复核仍由验证方完成。",
        "",
        "## 4. 复跑",
        "",
        "```sh",
        document.get("reproduce"),
        "```",
        "",
        "## 5. 机器可读产物",
        "",
        "- `poststop_targets.json`：同名字段 + `checks.problems`；`citable=false`。",
        "- 每个目标含 `reported` / `recomputed` / `delta` 三组值，便于逐项复核。",
        "",
    ]
    if chk.get("problems"):
        lines += ["## 6. 一致性问题", ""] + ["- %s" % p for p in chk.get("problems") or []] + [""]
    return "\n".join(lines)


def write_outputs(
    out_dir: Path,
    document: Dict[str, Any],
    *,
    overwrite: bool = False,
) -> Dict[str, str]:
    out_dir = Path(out_dir)
    if out_dir.exists():
        existing = [p.name for p in out_dir.iterdir()]
        if existing and not overwrite:
            raise PostStopError(
                "输出目录已存在非空内容；如需重写请显式 --overwrite（不覆盖原始交付包）",
                {"out_dir": str(out_dir), "existing": sorted(existing)},
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "poststop_targets.json"
    md_path = out_dir / "POSTSTOP_TARGETS.md"
    _write_text_lf(
        json_path,
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    )
    _write_text_lf(md_path, render_markdown(document))
    sums = {
        json_path.name: file_sha256(json_path),
        md_path.name: file_sha256(md_path),
    }
    _write_text_lf(
        out_dir / "SHA256SUMS.txt",
        "\n".join("%s  %s" % (v, k) for k, v in sorted(sums.items())) + "\n",
    )
    return sums


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def run(
    results_dir: Path,
    out_dir: Path,
    *,
    config_path: Optional[Path] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    result = load_json(Path(results_dir) / "e0c_results.json")
    arrays_path = Path(results_dir) / str(result.get("arrays_file") or "e0c_arrays.npz")
    arrays = load_arrays(arrays_path)
    c0 = load_c0(config_path)
    document, problems = build_poststop_document(
        result, arrays, Path(results_dir), c0=c0
    )
    sums = write_outputs(Path(out_dir), document, overwrite=overwrite)
    return {"document": document, "problems": problems, "files": sums}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E0-C 硬停后的目标结果再生（E0-C-POSTSTOP-1）"
    )
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--out", default=DEFAULT_OUT_DIR)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    results_dir = Path(args.results_dir)
    if not results_dir.is_absolute():
        results_dir = REPO / results_dir
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO / config_path
    try:
        out = run(results_dir, out_dir, config_path=config_path, overwrite=bool(args.overwrite))
    except PostStopError as exc:
        print("POSTSTOP STOP: %s" % exc.reason)
        if exc.detail:
            print(json.dumps(exc.detail, ensure_ascii=False, indent=1))
        return 3
    doc = out["document"]
    chk = doc["checks"]
    print(
        "POSTSTOP OK: targets=%d citable=false max|delta|_dB=%.3g max|delta|_m=%.3g"
        % (chk["targets_recomputed"], chk["max_delta_db"], chk["max_delta_m"])
    )
    for tgt in doc["targets"]:
        print(
            "  %s: d_hat=%.6f m abs_err=%.3f cm pslr=%.3f dB pnr=%.2f dB status=%s"
            % (
                tgt["group_key"],
                tgt["recomputed"]["d_hat_m"],
                tgt["recomputed"]["abs_err_cm"],
                tgt["recomputed"]["pslr_db"],
                tgt["recomputed"]["pnr_db"],
                tgt["group_status"],
            )
        )
    print("  written: %s" % ", ".join(sorted(out["files"])))
    if out["problems"]:
        print("POSTSTOP FAIL: 一致性检查未通过（退出码 3）")
        for problem in out["problems"]:
            print("  - %s" % problem)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
