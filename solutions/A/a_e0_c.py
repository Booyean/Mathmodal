#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1-E0-C 真实校准先导的**正式执行入口**（`Phase E0-C`，不含 `E0-T`）。

范围
----
严格按 `experiments/A/A-Q1-E0/PLAN.md` 阶段 2 与
`solutions/A/e0c_execution_checklist.md` 的口径实现：

* 输入只允许 12 组 / 96 个 `.dat`：10 组空场 `空场数据/data1..data10` 与 2 组已披露
  校准目标 `墙体数据/data1-42cm`、`金属板数据/data1-69cm`；不读任何 `*_test`、
  `附件3`、B 题数据，**不触碰 `E0-T`**。
* 链路固定 `M0-Cal-Base -> M0-DW-Base(alpha ≡ 1.0) -> M0-Rng-Base(P_norm,eff)`，
  数学原语直接复用已验收的 `a_e0_s1s2.py`（E0-S 全量合成闭环），不另写一套。
* 折迭统一走 `a_fold_gate.py`（`CONTRACT_VERSION == "D1-2"`），读取走
  `a_dat_reader.py`（`D0-4`）。
* `lambda` 选参只用空场 LOO（9 组固定预算），目标组标签只用于**事后评价**。

安全边界
--------
本模块不调用 `a_dat_reader.discover_groups()`（它会 `rglob` 整棵 A 题目录，等于
glob 到禁止组）。组清单由白名单显式给出，且每个组目录、每个待读文件在
`stat`/`open` 之前都要过 `e0c_preflight.guard_group_dir` / `guard_dat_path`
（词法归属 → 反符号链接/重解析点 → `realpath` 包含性）。

两种模式
--------
``--mode check``（默认）
    只跑放行前自检与白名单路径扫描（仅 `lstat`/`iterdir`，**不打开任何 `.dat`**），
    用来证明入口可用、边界正确。当前 `E0-C` 未获放行，本模式可随时运行。

``--mode execute``
    真正读取 96 个 `.dat` 并求解。**必须**同时给出 ``--approval-ref``（统筹放行
    消息的编号/链接），否则拒绝启动；该编号会写进结果 JSON 供追溯。

用法::

    # 1) 现在可跑：入口 + 边界自检（不读采样）
    python solutions/A/a_e0_c.py --mode check

    # 2) 放行后：正式执行（示例）
    python solutions/A/a_e0_c.py --mode execute --approval-ref <release-ref> `
        --implementation-sha <impl-sha> --parent-commit <parent-sha> `
        --main-commit <main-sha>

退出码
------
``0`` 通过（check 模式=自检通过；execute 模式=全部门槛可冻结）
``1`` 门槛失败 / 灰区不可冻结
``2`` 用法错误（缺 ``--approval-ref``、输出目录已有结果等）
``3`` 硬停止（前置未过、越界、`valid_rx<63`、NaN/Inf、资源超预算等）
"""

from __future__ import annotations

import os

# 资源预算要求单进程单线程；必须在导入 numpy 之前设置（与 E0-S 一致）。
for _thread_env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_env] = "1"

import argparse
import json
import platform
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a_dat_reader as D0  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402
import a_fold_gate as D1  # noqa: E402
import e0c_preflight as PF  # noqa: E402

CONTRACT_VERSION = "E0-C-1"

REPO_ROOT = HERE.parents[1]
CONFIG_PATH = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "config.json"
SPLIT_PATH = REPO_ROOT / "coordination" / "A_Q1_SPLIT.json"
PLAN_PATH = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "PLAN.md"
MANIFEST_PATH = REPO_ROOT / "recon" / "manifests" / "a_dat_manifest.csv"
DEFAULT_OUT = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "e0c" / "results"

AIR_GROUPS: Tuple[str, ...] = tuple("空场数据/data%d" % i for i in range(1, 11))
TARGET_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "case_id": "E0-C/Wall-42cm",
        "array_prefix": "wall",
        "group": "墙体数据/data1-42cm",
        "target_type": "wall",
        "d_true_cm": 42.0,
        "in_split": "wall_cal",
        "peak_rule": "wall",
    },
    {
        "case_id": "E0-C/Metal-69cm",
        "array_prefix": "metal",
        "group": "金属板数据/data1-69cm",
        "target_type": "metal",
        "d_true_cm": 69.0,
        "in_split": "metal_cal",
        "peak_rule": "metal",
    },
)

_ROW_FILE_RE = re.compile(r"^(?P<prefix>.+)_(?P<row>[0-7])\.dat$", re.IGNORECASE)
_REF_POS = 27  # rx63 中的参考通道位置：rx63[27] == ref_idx == 28


class E0CStop(RuntimeError):
    """硬停止：触发后禁止自动重跑，保留证据交统筹。"""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self.reason = reason
        self.detail = detail or {}
        super().__init__(reason)


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def file_sha256(path: Path) -> str:
    return E0S.file_sha256(Path(path))


def lf_sha256(path: Path) -> str:
    return E0S.file_sha256(Path(path), normalize_lf=True)


def json_safe(obj: Any) -> Any:
    return E0S.json_safe(obj)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(json_safe(obj), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_config(path: Path) -> Dict[str, Any]:
    return E0S.load_config(Path(path))


def environment_info() -> Dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "threads": {
            k: os.environ.get(k)
            for k in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 白名单 I/O（D0 读取 + D1-2 折迭），读前路径校验
# --------------------------------------------------------------------------
def guarded_group_ref(data_root: Path, group_key: str) -> Tuple[D0.GroupRef, Dict[str, Any]]:
    """按白名单显式构造 ``GroupRef``；不调用 ``discover_groups``（其 rglob 会越界）。

    组目录与每个 ``.dat`` 都必须先过 ``e0c_preflight`` 的读前路径校验；通过的
    条目只保留**真实路径**，后续 ``stat``/``open`` 只用真实路径。
    """
    data_root = Path(data_root)
    data_root_real = Path(os.path.realpath(str(data_root)))
    gdir_lex = PF.group_dir(data_root, group_key)
    real_gdir = PF.guard_group_dir(gdir_lex, data_root)

    if "/" not in group_key:
        raise E0CStop("group_key 缺数据集前缀：%s" % group_key)
    dataset, name = group_key.split("/", 1)

    files: Dict[int, Path] = {}
    prefixes = set()
    for entry in sorted(real_gdir.iterdir()):
        if entry.suffix.lower() != ".dat":
            continue
        match = _ROW_FILE_RE.match(entry.name)
        if not match:
            raise E0CStop(
                "白名单组内出现不合协议的文件名：%s/%s" % (group_key, entry.name)
            )
        real = PF.guard_dat_path(entry, real_gdir, data_root_real)
        row = int(match.group("row"))
        if row in files:
            raise E0CStop("白名单组内行号重复：%s row=%d" % (group_key, row))
        files[row] = real
        prefixes.add(match.group("prefix"))

    if sorted(files) != list(range(8)):
        raise E0CStop(
            "白名单组行号不是 0..7：%s -> %s" % (group_key, sorted(files))
        )
    if len(prefixes) != 1:
        raise E0CStop("白名单组出现多个时间戳前缀：%s -> %s" % (group_key, sorted(prefixes)))

    ref = D0.GroupRef(
        root=data_root,
        dir_rel=(PF.DATA_SUBDIR / Path(group_key)).as_posix(),
        prefix=prefixes.pop(),
        dataset=dataset,
        name=name,
        files=files,
    )
    info = {
        "group_key": group_key,
        "real_dir": str(real_gdir),
        "files": {
            str(r): {"name": p.name, "size_bytes": p.stat().st_size}
            for r, p in sorted(files.items())
        },
    }
    return ref, info


def load_group_spectrum(
    ref: D0.GroupRef,
    setup: "E0S.Setup",
    role: str,
) -> Dict[str, Any]:
    """读 8 个行文件 → D1-2 折迭 → 带内 63 路频谱。

    只返回数据；任何 `valid_rx < 63`、非有限值或折迭失败都转成 ``E0CStop``。
    """
    try:
        group = D0.load_group(ref, require_all_rows=True, compute_sha256=True)
    except (D0.IncompleteGroupError, D0.DatFormatError) as exc:
        raise E0CStop("读取失败：%s（%s）" % (ref.group_key, exc)) from exc
    except OSError as exc:
        raise E0CStop("读取 I/O 失败：%s（%s）" % (ref.group_key, exc)) from exc

    if int(group.packets.shape[0]) == 0:
        raise E0CStop("组内无共同 sync 包：%s" % ref.group_key)

    try:
        fold = D1.fold_group(group, n_period_samples=setup.np_n)
    except D1.FoldGateError as exc:
        raise E0CStop("D1-2 折迭门控失败：%s（%s）" % (ref.group_key, exc)) from exc

    signals = np.asarray(fold.signals_folded, dtype=np.float64)
    if signals.shape != (D0.N_CHANNELS, setup.np_n):
        raise E0CStop(
            "折迭输出形状异常：%s -> %r" % (ref.group_key, signals.shape)
        )
    spectra_all = np.fft.rfft(signals, axis=1)[:, setup.band_idx]

    rx = setup.rx63
    channel_ok = (np.asarray(fold.rx_mask, dtype=bool) & np.asarray(fold.channel_valid, dtype=bool))[rx]
    finite = np.all(np.isfinite(spectra_all), axis=1)[rx]
    valid_rx = int(np.count_nonzero(channel_ok & finite))
    ref_valid = bool(channel_ok[_REF_POS] and finite[_REF_POS])

    if valid_rx != int(setup.cfg["gates_and_thresholds"]["required_valid_rx_channels"]):
        raise E0CStop(
            "valid_rx=%d≠63（%s），按 PLAN §5.2 硬停止，禁止静默丢通道"
            % (valid_rx, ref.group_key),
            {"valid_rx": valid_rx, "group": ref.group_key},
        )
    if not ref_valid:
        raise E0CStop("参考通道 ref_idx=28 无效：%s" % ref.group_key)

    x = spectra_all[rx].copy()
    if not bool(np.all(np.isfinite(x))):
        raise E0CStop("带内频谱含 NaN/Inf：%s" % ref.group_key)

    rows = group.meta.get("row_files", {})
    return {
        "group_key": ref.group_key,
        "role": role,
        "x": x,
        "valid_rx": valid_rx,
        "ref_channel_valid": ref_valid,
        "n_packets": int(group.packets.shape[0]),
        "n_accepted": int(fold.n_accepted),
        "sync_common": [int(v) for v in group.sync],
        "sync_accepted": [int(group.sync[i]) for i in np.flatnonzero(fold.accepted)],
        "anchor": fold.meta.get("anchor_sync"),
        "files": [
            {
                "row": int(r),
                "file": rows[str(r)]["file"],
                "size_bytes": rows[str(r)]["size_bytes"],
                "sha256": rows[str(r)]["sha256"],
            }
            for r in range(8)
            if str(r) in rows
        ],
        "extremes": {
            "neg_32768": int(group.meta["extremes"]["neg_32768"]),
            "pos_32767": int(group.meta["extremes"]["pos_32767"]),
        },
        "packet_problems": int(len(group.meta.get("excluded_packets", []))),
    }


# --------------------------------------------------------------------------
# 求解（纯数组，无文件访问）：与 E0-S 共用同一套数学原语
# --------------------------------------------------------------------------
def solve_bundle(
    air: Sequence[np.ndarray],
    targets: Sequence[Dict[str, Any]],
    cfg: Dict[str, Any],
    setup: "E0S.Setup",
    log: List[str],
    *,
    eta_wall: Optional[float] = None,
) -> Dict[str, Any]:
    """对"已就绪的带内频谱"执行 E0-C 全流程。

    ``air`` 为 10 个空场组的 (63, nb) 频谱；``targets`` 每项含 ``x`` / ``d_true_cm``
    / ``peak_rule`` / ``target_type`` / ``case_id`` / ``array_prefix``。
    目标标签只在本函数末尾计算误差时使用，不参与任何选参。
    """
    cal_cfg = cfg["methods_classic_baseline_only"]["calibration"]
    gates = cfg["gates_and_thresholds"]
    r_dir = setup.r_dir_all[setup.rx63]
    tau_dir = setup.tau_dir_all[setup.rx63]
    f_r = setup.f_r
    s_band = setup.s_band

    # ---- 空场对齐（相对 air[0]）→ 纯空场 LOO 选参
    shifts = [0.0]
    for x in air[1:]:
        shifts.append(
            E0S.align_lag(x, air[0], f_r, setup.band_idx, setup.np_n, setup.ts, setup.tp)
        )
    aligned_air = [
        x * np.exp(1j * 2.0 * np.pi * f_r * s)[None, :]
        for x, s in zip(air, shifts)
    ]
    loo = E0S.select_lambdas_air_loo(
        aligned_air, _REF_POS, r_dir, tau_dir, f_r, cal_cfg
    )
    lam = loo["selected"]
    cal = E0S.calibrate_air(
        list(air),
        _REF_POS,
        r_dir,
        tau_dir,
        f_r,
        setup.band_idx,
        setup.np_n,
        setup.ts,
        setup.tp,
        lam_cal=float(lam["lambda_cal"]),
        lam_inv=float(lam["lambda_inv"]),
    )

    # 选中对在 10 折上的抑制（LOO 目标值口径）
    selected_row = None
    for row in loo["grid_rows"]:
        if (
            row["lambda_cal"] == float(lam["lambda_cal"])
            and row["lambda_inv"] == float(lam["lambda_inv"])
        ):
            selected_row = row
            break
    if selected_row is None:  # pragma: no cover - 选参实现变化时兜底
        raise E0CStop("选中的 lambda 对不在 LOO 网格内")
    air_min_db = float(selected_row["min_supp_db"])
    air_median_db = float(selected_row["median_supp_db"])
    log.append(
        "air LOO: selected (%.0e, %.0e) triggered=%s reason=%s min=%.4f dB median=%.4f dB"
        % (
            float(lam["lambda_cal"]),
            float(lam["lambda_inv"]),
            bool(loo["triggered"]),
            loo["trigger_reason"],
            air_min_db,
            air_median_db,
        )
    )

    arrays: Dict[str, np.ndarray] = {
        "freq_hz": setup.f_d,
        "freq_rf_hz": f_r,
        "tau_dir_s": tau_dir,
        "r_dir_m": r_dir,
        "rx_idx": setup.rx63.astype(np.int64),
        "h_rel_hat": cal["h"],
        "inv_op": cal["inv"],
        "xbar_air_cal": cal["xbar_cal"],
        "air_shifts_s": np.asarray(shifts, dtype=np.float64),
        "air_aligned_cal": np.stack([a * cal["inv"] for a in aligned_air]),
        "lambda_grid_cal": np.asarray([r["lambda_cal"] for r in loo["grid_rows"]]),
        "lambda_grid_inv": np.asarray([r["lambda_inv"] for r in loo["grid_rows"]]),
        "lambda_grid_J_air_db": np.asarray([r["J_air_db"] for r in loo["grid_rows"]]),
        "lambda_grid_min_supp_db": np.asarray([r["min_supp_db"] for r in loo["grid_rows"]]),
        "lambda_grid_median_supp_db": np.asarray(
            [r["median_supp_db"] for r in loo["grid_rows"]]
        ),
    }

    eta_default = float(
        cfg["methods_classic_baseline_only"]["ranging"]["eta_wall_default"]
    )
    eta_candidates = [
        float(v)
        for v in cfg["methods_classic_baseline_only"]["ranging"]["eta_wall_candidates_cal_only"]
    ]
    if eta_wall is not None:
        eta_default = float(eta_wall)
        eta_candidates = [float(eta_wall)]
    # 按“最接近默认值，其次更小值”定序（PLAN §3.3 的确定性裁决）。
    eta_order = sorted(eta_candidates, key=lambda v: (round(abs(v - eta_default), 12), v))

    cases: List[Dict[str, Any]] = []
    for tgt in targets:
        prefix = str(tgt["array_prefix"])
        peak_rule = str(tgt["peak_rule"])
        d_true_cm = float(tgt["d_true_cm"])
        solved = E0S.solve_case(
            tgt["x"],
            cal,
            s_band,
            r_dir,
            tau_dir,
            f_r,
            setup.c0,
            setup,
            peak_rule,
            float(eta_default),
            cfg,
        )

        eta_records: List[Dict[str, Any]] = []
        selected_eta = float(eta_default)
        if peak_rule == "wall":
            # PLAN §3.3：仅在本校准组上核对 {0.15,0.25,0.35}，取满足条件且最接近
            # 默认 0.25 者；逐个用同一条已验收求解链重算，结果全部入档。
            chosen: Optional[Dict[str, Any]] = None
            for eta in eta_order:
                cand = E0S.solve_case(
                    tgt["x"],
                    cal,
                    s_band,
                    r_dir,
                    tau_dir,
                    f_r,
                    setup.c0,
                    setup,
                    peak_rule,
                    float(eta),
                    cfg,
                )
                err = abs(float(cand["d_hat_m"]) - d_true_cm / 100.0) * 100.0
                record = {
                    "eta_wall": float(eta),
                    "d_hat_m": float(cand["d_hat_m"]),
                    "abs_err_cm": err,
                    "pslr_db": float(cand["pslr_db"]),
                    "pnr_db": float(cand["pnr_db"]),
                    "eligible": bool(
                        err <= float(gates["cal_pilot_eligible_max_range_err_cm"])
                        and float(cand["pslr_db"]) >= float(gates["target_echo_min_pslr_db"])
                        and float(cand["pnr_db"]) >= float(gates["target_echo_min_pnr_db"])
                        and int(cand["valid_rx"]) == int(gates["required_valid_rx_channels"])
                        and bool(cand["finite"])
                    ),
                    "solved": cand,
                }
                eta_records.append({k: v for k, v in record.items() if k != "solved"})
                if record["eligible"] and chosen is None:
                    chosen = record
            if chosen is not None:
                solved = chosen["solved"]
                selected_eta = float(chosen["eta_wall"])
            log.append(
                "wall eta candidates: %s -> selected %.2f"
                % (
                    ", ".join(
                        "%.2f(err=%.3fcm)" % (r["eta_wall"], r["abs_err_cm"])
                        for r in eta_records
                    ),
                    selected_eta,
                )
            )

        d_hat = float(solved["d_hat_m"])
        abs_err_cm = abs(d_hat - d_true_cm / 100.0) * 100.0
        case = {
            "case_id": str(tgt["case_id"]),
            "group_key": str(tgt.get("group_key", "")),
            "target_type": str(tgt["target_type"]),
            "in_split": tgt.get("in_split"),
            "peak_rule": peak_rule,
            "eta_wall": selected_eta if peak_rule == "wall" else None,
            "eta_wall_candidates": eta_records if peak_rule == "wall" else [],
            "d_true_cm_nominal": d_true_cm,
            "d_hat_m": d_hat,
            "d_hat_cm": d_hat * 100.0,
            "abs_err_cm": abs_err_cm,
            "supp_dw_win_db": float(solved["supp_dw_win_db"]),
            "pslr_db": float(solved["pslr_db"]),
            "pnr_db": float(solved["pnr_db"]),
            "echo_ret_db": float(solved["echo_ret_db"]),
            "bg_proxy": float(solved["bg_proxy"]),
            "valid_rx": int(solved["valid_rx"]),
            "finite": bool(solved["finite"]),
            "dt0_samples": float(solved["dt0_samples"]),
            "t_anchor_samples": float(solved["t_anchor_samples"]),
            "d_hat_p_norm_m": float(solved["d_hat_p_norm_m"]),
            "d_hat_p_env_m": float(solved["d_hat_p_env_m"]),
            "arrays_sha256": {
                "x_cal": E0S.array_sha256(solved["x_cal"]),
                "x_after": E0S.array_sha256(solved["x_after"]),
                "s_eff": E0S.array_sha256(solved["s_eff"]),
                "profile_p_norm_eff": E0S.array_sha256(solved["profile_p_norm_eff"]),
            },
        }
        case["gate_results"] = evaluate_case_gates(case, gates)
        case["freeze_status"] = case_freeze_status(case["gate_results"])
        cases.append(case)

        arrays.update(
            {
                "%s_x_cal" % prefix: solved["x_cal"],
                "%s_x_after" % prefix: solved["x_after"],
                "%s_s_eff" % prefix: solved["s_eff"],
                "%s_z_dw_before" % prefix: solved["z_dw_before"],
                "%s_z_dw_after" % prefix: solved["z_dw_after"],
                "%s_z_after_tgt" % prefix: solved["z_after_tgt"],
                "%s_profile_d_grid_m" % prefix: solved["profile_d_grid_m"],
                "%s_profile_p_norm_eff" % prefix: solved["profile_p_norm_eff"],
                "%s_profile_p_norm" % prefix: solved["profile_p_norm"],
                "%s_profile_p_env" % prefix: solved["profile_p_env"],
                "%s_d_hat_m" % prefix: np.asarray([d_hat]),
                "%s_bg_proxy" % prefix: np.asarray([float(solved["bg_proxy"])]),
                "%s_t_anchor_s" % prefix: np.asarray([float(solved["t_anchor_s"])]),
            }
        )

    air_gate = evaluate_air_gate(air_min_db, air_median_db, gates)
    return {
        "lambda_loo": {
            "grid": [
                [float(v) for v in cal_cfg["lambda_cal_grid_air_loo"]],
                [float(v) for v in cal_cfg["lambda_inv_grid_air_loo"]],
            ],
            "budget_pairs": int(loo["budget_pairs"]),
            "folds": int(loo["folds"]),
            "rows": loo["grid_rows"],
            "best": loo["best"],
            "default": loo["default"],
            "selected": loo["selected"],
            "triggered": bool(loo["triggered"]),
            "trigger_reason": loo["trigger_reason"],
            "selected_min_supp_db": air_min_db,
            "selected_median_supp_db": air_median_db,
            "air_gate": air_gate,
        },
        "cal": {
            "shifts_s": [float(s) for s in shifts],
            "lambda_cal": float(lam["lambda_cal"]),
            "lambda_inv": float(lam["lambda_inv"]),
            "eta_wall": float(eta_default),
            "eta_candidates": [float(v) for v in eta_order],
        },
        "cases": cases,
        "arrays": arrays,
        "selected_eta_wall": float(
            next((c["eta_wall"] for c in cases if c["peak_rule"] == "wall"), eta_default)
        ),
    }


# --------------------------------------------------------------------------
# 门槛判定
# --------------------------------------------------------------------------
def evaluate_case_gates(case: Dict[str, Any], gates: Dict[str, Any]) -> Dict[str, Any]:
    """逐门给出 value/threshold/status；status ∈ passed / gray / failed。"""
    eligible_err = float(gates["cal_pilot_eligible_max_range_err_cm"])
    hard_err = float(gates["cal_pilot_hard_stop_range_err_cm"])
    err = float(case["abs_err_cm"])
    if err <= eligible_err:
        err_status, err_passed = "passed", True
    elif err <= hard_err:
        err_status, err_passed = "gray", False
    else:
        err_status, err_passed = "failed", False

    pslr_ok = float(case["pslr_db"]) >= float(gates["target_echo_min_pslr_db"])
    pnr_ok = float(case["pnr_db"]) >= float(gates["target_echo_min_pnr_db"])
    rx_ok = int(case["valid_rx"]) == int(gates["required_valid_rx_channels"])
    finite_ok = bool(case["finite"])

    return {
        "abs_err_cm": {
            "value": err,
            "eligible_max": eligible_err,
            "hard_stop_gt": hard_err,
            "status": err_status,
            "passed": err_passed,
        },
        "pslr_db": {
            "value": float(case["pslr_db"]),
            "threshold": float(gates["target_echo_min_pslr_db"]),
            "status": "passed" if pslr_ok else "failed",
            "passed": pslr_ok,
        },
        "pnr_db": {
            "value": float(case["pnr_db"]),
            "threshold": float(gates["target_echo_min_pnr_db"]),
            "status": "passed" if pnr_ok else "failed",
            "passed": pnr_ok,
        },
        "valid_rx": {
            "value": int(case["valid_rx"]),
            "threshold": int(gates["required_valid_rx_channels"]),
            "status": "passed" if rx_ok else "failed",
            "passed": rx_ok,
        },
        "finite": {
            "value": finite_ok,
            "status": "passed" if finite_ok else "failed",
            "passed": finite_ok,
        },
    }


def evaluate_air_gate(min_supp_db: float, median_supp_db: float, gates: Dict[str, Any]) -> Dict[str, Any]:
    eligible = float(gates["air_loo_eligible_min_suppression_db"])
    hard = float(gates["air_loo_hard_stop_suppression_db"])
    if min_supp_db >= eligible:
        status, passed = "passed", True
    elif min_supp_db >= hard:
        status, passed = "gray", False
    else:
        status, passed = "failed", False
    return {
        "metric": "min(Supp_air-LOO)_db",
        "min_supp_db": float(min_supp_db),
        "median_supp_db": float(median_supp_db),
        "eligible_min": eligible,
        "hard_stop_below": hard,
        "status": status,
        "passed": passed,
        "gray_action": "6.0 <= min < 10.0 dB：仅允许在 9 组空场网格复核，仍 <10 即停、禁入 E0-T",
    }


def case_freeze_status(gate_results: Dict[str, Any]) -> str:
    if any(
        g.get("status") == "failed" for g in gate_results.values()
    ):
        return "hard_stop"
    if all(g.get("passed") for g in gate_results.values()):
        return "eligible"
    return "not_eligible_for_freeze"


# --------------------------------------------------------------------------
# check 模式：只做放行前自检 + 白名单路径扫描（不打开 .dat）
# --------------------------------------------------------------------------
def run_check(
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    cfg: Dict[str, Any],
    log: List[str],
) -> Dict[str, Any]:
    pf = PF.run_preflight(repo, data_root, manifest_path)
    log.append(
        "preflight: %d/%d passed, preconditions_pass=%s"
        % (pf["summary"]["passed"], pf["summary"]["total"], pf["preconditions_pass"])
    )

    groups: List[Dict[str, Any]] = []
    problems: List[str] = []
    plan = [(g, "air") for g in AIR_GROUPS] + [
        (str(t["group"]), str(t["target_type"])) for t in TARGET_SPECS
    ]
    for key, role in plan:
        try:
            _ref, info = guarded_group_ref(data_root, key)
        except (PF.PathGuardError, E0CStop, OSError) as exc:
            problems.append("%s：%s" % (key, exc))
            groups.append({"group_key": key, "role": role, "ok": False, "error": str(exc)})
            continue
        groups.append(
            {
                "group_key": key,
                "role": role,
                "ok": True,
                "real_dir": info["real_dir"],
                "files": len(info["files"]),
                "bytes": sum(f["size_bytes"] for f in info["files"].values()),
            }
        )

    return {
        "mode": "check",
        "preflight": {
            "preconditions_pass": pf["preconditions_pass"],
            "execution_ready": pf["execution_ready"],
            "summary": pf["summary"],
            "open_items": pf["open_items"],
            "data_path_guard": pf["data"].get("path_guard", {}),
        },
        "boundary_scan": {
            "allowed_groups": len(plan),
            "groups": groups,
            "problems": problems,
            "dat_files_open_for_sha256": int(pf["data"].get("signal_files_hashed", 0)),
            "packets_parsed": 0,
            "note": "本模式不解析任何 .dat 包头/采样；只对白名单 96 个 .dat 计算 size+SHA256（与 e0c_preflight 同口径）并对 12 个组目录做 iterdir/lstat 边界扫描",
        },
        "ready_for_execute": bool(pf["preconditions_pass"] and not problems),
    }


# --------------------------------------------------------------------------
# execute 模式
# --------------------------------------------------------------------------
def run_execute(
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    cfg: Dict[str, Any],
    setup: "E0S.Setup",
    approval_ref: str,
    eta_wall: Optional[float],
    log: List[str],
) -> Dict[str, Any]:
    started = time.perf_counter()
    ctx: Dict[str, Any] = {
        "experiment_id": "A-Q1-E0",
        "phase": "E0-C",
        "contract_version": CONTRACT_VERSION,
        "approval_ref": approval_ref,
        "hard_stops": [],
        "gray_reasons": [],
        "stop_reasons": [],
        "data": {"groups": [], "opened_files": 0},
    }

    # ---- 0) 前置：放行前自检必须通过
    pf = PF.run_preflight(repo, data_root, manifest_path)
    ctx["preflight"] = {
        "contract_version": pf.get("contract_version"),
        "preconditions_pass": pf["preconditions_pass"],
        "summary": pf["summary"],
        "failed_ids": pf["summary"]["failed_ids"],
    }
    log.append("preflight preconditions_pass=%s" % pf["preconditions_pass"])
    if not pf["preconditions_pass"]:
        ctx["hard_stops"].append(
            "preflight_failed: " + ", ".join(pf["summary"]["blocking_ids"])
        )
        return ctx

    # ---- 1) 读取白名单 12 组（读前路径校验由 guarded_group_ref 完成）
    spectra: Dict[str, Dict[str, Any]] = {}
    for key, role in [(g, "air") for g in AIR_GROUPS] + [
        (str(t["group"]), str(t["target_type"])) for t in TARGET_SPECS
    ]:
        if time.perf_counter() - started > float(cfg["resource_budget"]["max_wall_time_sec"]):
            ctx["hard_stops"].append("resource: wall time budget exceeded during load")
            return ctx
        ref, _info = guarded_group_ref(data_root, key)
        try:
            item = load_group_spectrum(ref, setup, role)
        except E0CStop as exc:
            # 保留“已读了哪些组”的证据，避免失败时只剩一条原因。
            exc.detail = dict(exc.detail)
            exc.detail["loaded_groups"] = [g["group_key"] for g in ctx["data"]["groups"]]
            exc.detail["failing_group"] = key
            raise
        spectra[key] = item
        log.append(
            "loaded %s: packets=%d accepted=%d valid_rx=%d"
            % (key, item["n_packets"], item["n_accepted"], item["valid_rx"])
        )
        ctx["data"]["groups"].append(
            {
                "group_key": key,
                "role": role,
                "n_packets": item["n_packets"],
                "n_accepted": item["n_accepted"],
                "valid_rx": item["valid_rx"],
                "ref_channel_valid": item["ref_channel_valid"],
                "sync_common": item["sync_common"],
                "sync_accepted": item["sync_accepted"],
                "anchor_sync": item["anchor"],
                "files": item["files"],
                "extremes": item["extremes"],
            }
        )
        ctx["data"]["opened_files"] += len(item["files"])
        ctx["data"]["path_guard"] = pf["data"].get("path_guard", {})

    if ctx["data"]["opened_files"] != 96:
        ctx["hard_stops"].append(
            "boundary: opened_files=%d≠96" % ctx["data"]["opened_files"]
        )
        return ctx

    # ---- 2) 求解（空场 LOO → 校准 → DW 抑制 → 测距 → 门槛）
    air = [spectra[g]["x"] for g in AIR_GROUPS]
    targets = [
        dict(
            spec,
            x=spectra[str(spec["group"])]["x"],
            group_key=str(spec["group"]),
        )
        for spec in TARGET_SPECS
    ]

    solved = solve_bundle(air, targets, cfg, setup, log, eta_wall=eta_wall)
    ctx["lambda_loo"] = solved["lambda_loo"]
    ctx["cal"] = solved["cal"]
    ctx["cases"] = solved["cases"]
    ctx["arrays"] = solved["arrays"]

    # ---- 3) 硬停止 / 灰区判定
    air_gate = solved["lambda_loo"]["air_gate"]
    ctx["air_gate"] = air_gate
    hard_stops: List[str] = []
    gray_reasons: List[str] = []
    if air_gate["status"] == "failed":
        hard_stops.append(
            "air_loo_hard_stop: min=%.4f dB < %.1f dB"
            % (air_gate["min_supp_db"], air_gate["hard_stop_below"])
        )
    elif air_gate["status"] == "gray":
        grid_min = float(
            min(row["min_supp_db"] for row in solved["lambda_loo"]["rows"])
        )
        gray_reasons.append(
            "air_loo_gray: selected min=%.4f dB in [6,10); 9-pair grid min=%.4f dB -> 不冻结、禁入 E0-T"
            % (air_gate["min_supp_db"], grid_min)
        )

    for case in ctx["cases"]:
        status = case["freeze_status"]
        if status == "hard_stop":
            hard_stops.append(
                "%s: %s"
                % (
                    case["case_id"],
                    ", ".join(
                        "%s(%s)" % (k, g.get("status"))
                        for k, g in case["gate_results"].items()
                        if g.get("status") == "failed"
                    ),
                )
            )
        elif status == "not_eligible_for_freeze":
            gray_reasons.append(
                "%s: %s"
                % (
                    case["case_id"],
                    ", ".join(
                        "%s(%s)" % (k, g.get("status"))
                        for k, g in case["gate_results"].items()
                        if g.get("status") == "gray"
                    ),
                )
            )

    # ---- 4) 冻结判定
    ctx["hard_stops"] = hard_stops
    ctx["gray_reasons"] = gray_reasons
    ctx["stop_reasons"] = hard_stops + gray_reasons
    if hard_stops:
        freeze_status = "hard_stop"
    elif gray_reasons:
        freeze_status = "not_eligible_for_freeze"
    else:
        freeze_status = "eligible"
    ctx["freeze"] = {
        "status": freeze_status,
        "eligible": freeze_status == "eligible",
        "lambda_cal": solved["cal"]["lambda_cal"],
        "lambda_inv": solved["cal"]["lambda_inv"],
        "eta_wall": solved["selected_eta_wall"],
        "eta_selection_rule": "仅在校准组 data1-42cm 上按“满足条件且最接近默认 0.25”选取",
        "reasons": list(ctx["stop_reasons"]),
        "frozen_file": "e0c_frozen.json" if freeze_status == "eligible" else None,
    }
    return ctx


# --------------------------------------------------------------------------
# 产物
# --------------------------------------------------------------------------
def write_outputs(
    out_dir: Path,
    result: Dict[str, Any],
    arrays: Optional[Dict[str, np.ndarray]],
    log: List[str],
) -> Dict[str, str]:
    """落盘全部产物；返回 SHA256SUMS 的映射。

    顺序：二进制/子表 → run.log → 把已算出的摘要写进 ``result["files_sha256"]``
    → 写 ``e0c_results.json``（自身摘要只能进 ``SHA256SUMS.txt``，不能自引用）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sums: Dict[str, str] = {}

    if arrays:
        npz_path = out_dir / "e0c_arrays.npz"
        np.savez_compressed(npz_path, **arrays)
        result["arrays_file"] = npz_path.name
        result["arrays_file_sha256"] = file_sha256(npz_path)
        sums[npz_path.name] = result["arrays_file_sha256"]

    loo = result.get("lambda_loo")
    if loo:
        loo_path = out_dir / "e0c_air_loo.json"
        write_json(loo_path, loo)
        result["air_loo_file"] = loo_path.name
        result["air_loo_file_sha256"] = file_sha256(loo_path)
        sums[loo_path.name] = result["air_loo_file_sha256"]

    if result.get("freeze", {}).get("eligible"):
        frozen = {
            "contract_version": CONTRACT_VERSION,
            "experiment_id": "A-Q1-E0",
            "phase": "E0-Freeze",
            "frozen_at": now_iso(),
            "lambda_cal": result["freeze"]["lambda_cal"],
            "lambda_inv": result["freeze"]["lambda_inv"],
            "eta_wall": result["freeze"]["eta_wall"],
            "eta_selection_rule": result["freeze"]["eta_selection_rule"],
            "implementation_sha": result.get("implementation_sha"),
            "parent_commit": result.get("parent_commit"),
            "main_commit": result.get("main_commit"),
            "approval_ref": result.get("approval_ref"),
            "config_sha256": result.get("config_sha256"),
            "config_sha256_match": result.get("config_sha256_match"),
            "plan_sha256": result.get("plan_sha256"),
            "plan_sha256_match": result.get("plan_sha256_match"),
            "split_sha256": result.get("split_sha256"),
            "split_sha256_match": result.get("split_sha256_match"),
            "results_file": "e0c_results.json",
        }
        frozen_path = out_dir / "e0c_frozen.json"
        write_json(frozen_path, frozen)
        result["frozen_file_sha256"] = file_sha256(frozen_path)
        sums[frozen_path.name] = result["frozen_file_sha256"]

    log_path = out_dir / "run.log"
    log_path.write_text("\n".join(log) + "\n", encoding="utf-8")
    sums[log_path.name] = file_sha256(log_path)

    result["files_sha256"] = dict(sums)
    result["files_sha256_note"] = (
        "本表不含 e0c_results.json 自身；其摘要见 SHA256SUMS.txt"
    )

    json_path = out_dir / "e0c_results.json"
    write_json(json_path, result)
    sums[json_path.name] = file_sha256(json_path)

    sums_path = out_dir / "SHA256SUMS.txt"
    sums_path.write_text(
        "\n".join("%s  %s" % (v, k) for k, v in sorted(sums.items())) + "\n",
        encoding="utf-8",
    )
    return sums


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="A-Q1-E0-C 真实校准先导正式入口（默认只做 check，不读采样）"
    )
    parser.add_argument("--repo", default=str(REPO_ROOT), help="仓库根目录")
    parser.add_argument("--config", default=None, help="config.json 路径")
    parser.add_argument("--split", default=None, help="A_Q1_SPLIT.json 路径")
    parser.add_argument("--data-root", default=None, help="A 题根目录")
    parser.add_argument("--manifest", default=None, help="R0 a_dat_manifest.csv")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="结果输出目录")
    parser.add_argument(
        "--mode",
        choices=("check", "execute"),
        default="check",
        help="check=放行前自检+边界扫描（不打开 .dat）；execute=真实执行（需 --approval-ref）",
    )
    parser.add_argument("--approval-ref", default=None, help="统筹放行消息编号/链接（execute 必填）")
    parser.add_argument("--runtime-sha", default=None, help="实现提交 SHA（写入结果）")
    parser.add_argument("--implementation-sha", default=None, help="同 --runtime-sha，保留兼容")
    parser.add_argument("--parent-commit", default=None, help="实现提交的父提交")
    parser.add_argument("--main-commit", default=None, help="运行时 origin/main")
    parser.add_argument("--eta-wall", type=float, default=None, help="覆盖墙体首峰门限（默认取 config）")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有 e0c_results.json")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

    repo = Path(args.repo).resolve()
    config_path = Path(args.config).resolve() if args.config else repo / "experiments/A/A-Q1-E0/config.json"
    data_root = (
        Path(args.data_root).resolve() if args.data_root else repo / PF.A_ROOT_DEFAULT
    )
    manifest_path = (
        Path(args.manifest).resolve() if args.manifest else repo / "recon/manifests/a_dat_manifest.csv"
    )
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    if args.mode == "check" and args.out == str(DEFAULT_OUT):
        # check 产物不落进正式结果目录，避免与 E0-C 证据混放。
        out_dir = repo / "experiments" / "A" / "A-Q1-E0" / "e0c" / "check"

    log: List[str] = ["contract_version=%s" % CONTRACT_VERSION]
    cfg = load_config(config_path)
    setup = E0S.Setup(cfg)

    if args.mode == "execute":
        if not args.approval_ref or not str(args.approval_ref).strip():
            print(
                "拒绝执行：--mode execute 必须带 --approval-ref（统筹放行编号/链接）。"
                "E0-C 未放行时请用默认 --mode check。",
                file=sys.stderr,
            )
            return 2
        if (out_dir / "e0c_results.json").is_file() and not args.overwrite:
            print(
                "拒绝执行：%s 已有 e0c_results.json；失败证据不得覆盖，换目录或显式 --overwrite。"
                % out_dir,
                file=sys.stderr,
            )
            return 2

    if args.mode == "check":
        check = run_check(repo, data_root, manifest_path, cfg, log)
        payload = {
            "contract_version": CONTRACT_VERSION,
            "generated_at": now_iso(),
            "mode": "check",
            "repo": str(repo),
            "environment": environment_info(),
            "config_sha256": lf_sha256(config_path),
            "config_sha256_match": lf_sha256(config_path)
            == PF.APPROVED_ANCHORS["config_sha256_lf"],
            **check,
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "e0c_check.json"
        write_json(path, payload)
        print(
            json.dumps(
                {
                    "mode": "check",
                    "preconditions_pass": check["preflight"]["preconditions_pass"],
                    "ready_for_execute": check["ready_for_execute"],
                    "boundary_problems": check["boundary_scan"]["problems"],
                    "dat_files_open_for_sha256": check["boundary_scan"]["dat_files_open_for_sha256"],
                    "packets_parsed": check["boundary_scan"]["packets_parsed"],
                    "json": str(path),
                },
                ensure_ascii=False,
            )
        )
        return 0 if check["ready_for_execute"] else 1

    started = time.perf_counter()
    try:
        ctx = run_execute(
            repo,
            data_root,
            manifest_path,
            cfg,
            setup,
            str(args.approval_ref).strip(),
            args.eta_wall,
            log,
        )
    except E0CStop as exc:
        ctx = {
            "experiment_id": "A-Q1-E0",
            "phase": "E0-C",
            "contract_version": CONTRACT_VERSION,
            "approval_ref": args.approval_ref,
            "hard_stops": [exc.reason],
            "gray_reasons": [],
            "stop_reasons": [exc.reason],
            "stop_detail": exc.detail,
            "partial": {
                "loaded_groups": exc.detail.get("loaded_groups", []),
                "failing_group": exc.detail.get("failing_group"),
            },
            "cases": [],
        }
        log.append("E0CStop: %s" % exc.reason)
    except Exception:
        err_text = traceback.format_exc()
        log.append("EXCEPTION:\n" + err_text)
        ctx = {
            "experiment_id": "A-Q1-E0",
            "phase": "E0-C",
            "contract_version": CONTRACT_VERSION,
            "approval_ref": args.approval_ref,
            "hard_stops": ["exception: see run_error.log"],
            "gray_reasons": [],
            "stop_reasons": ["exception: see run_error.log"],
            "cases": [],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "run_error.log").write_text(err_text, encoding="utf-8")

    elapsed = time.perf_counter() - started
    peak = E0S.peak_rss_mib()
    prov = E0S.git_info(repo)
    result = {
        "contract_version": CONTRACT_VERSION,
        "experiment_id": "A-Q1-E0",
        "phase": "E0-C",
        "scope": "真实校准组（10 空场 + 2 已披露校准目标），非盲测，不含 E0-T；标签只用于事后评价",
        "generated_at": now_iso(),
        "approval_ref": args.approval_ref,
        "implementation_sha": args.implementation_sha or args.runtime_sha or prov.get("head_sha"),
        "parent_commit": args.parent_commit or prov.get("parent_sha"),
        "main_commit": args.main_commit or prov.get("origin_main_sha"),
        "branch": prov.get("branch"),
        "git": prov,
        "config_sha256": lf_sha256(config_path),
        "config_sha256_match": lf_sha256(config_path) == PF.APPROVED_ANCHORS["config_sha256_lf"],
        "plan_sha256": file_sha256(repo / "experiments/A/A-Q1-E0/PLAN.md"),
        "plan_sha256_match": file_sha256(repo / "experiments/A/A-Q1-E0/PLAN.md")
        == PF.APPROVED_ANCHORS["plan_sha256"],
        "split_sha256": lf_sha256(repo / "coordination/A_Q1_SPLIT.json"),
        "split_sha256_match": lf_sha256(repo / "coordination/A_Q1_SPLIT.json")
        == PF.APPROVED_ANCHORS["split_sha256_lf"],
        "environment": environment_info(),
        "command": "python solutions/A/a_e0_c.py --mode execute --approval-ref %s --out %s"
        % (args.approval_ref, args.out),
        "resource": {
            "wall_time_s": round(elapsed, 3),
            "peak_rss_mib": peak,
            "budget": {
                "max_wall_time_sec": cfg["resource_budget"]["max_wall_time_sec"],
                "max_peak_rss_mib": cfg["resource_budget"]["max_peak_rss_mib"],
            },
        },
    }
    result.update({k: v for k, v in ctx.items() if k not in result})

    over_budget = elapsed > float(cfg["resource_budget"]["max_wall_time_sec"]) or (
        peak is not None and peak > float(cfg["resource_budget"]["max_peak_rss_mib"])
    )
    hard_stops = list(result.get("hard_stops") or [])
    gray_reasons = list(result.get("gray_reasons") or [])
    if over_budget:
        hard_stops.append(
            "resource_budget_exceeded: wall=%.1fs peak=%sMiB" % (elapsed, peak)
        )
    if hard_stops:
        freeze_status = "hard_stop"
    elif gray_reasons:
        freeze_status = "not_eligible_for_freeze"
    elif result.get("freeze"):
        freeze_status = str(result["freeze"].get("status"))
    else:
        freeze_status = "not_eligible_for_freeze"
    result["hard_stops"] = hard_stops
    result["gray_reasons"] = gray_reasons
    result["stop_reasons"] = hard_stops + gray_reasons
    result["freeze"] = {
        **(result.get("freeze") or {}),
        "status": freeze_status,
        "eligible": freeze_status == "eligible",
    }

    arrays = result.pop("arrays", None)
    write_outputs(out_dir, result, arrays, log)

    freeze = result["freeze"]
    print(
        json.dumps(
            json_safe(
                {
                    "phase": "E0-C",
                    "freeze_status": freeze.get("status"),
                    "freeze_eligible": bool(freeze.get("eligible")),
                    "air_gate": (result.get("air_gate") or {}).get("status"),
                    "cases": [
                        {
                            "case_id": c["case_id"],
                            "d_hat_cm": c["d_hat_cm"],
                            "abs_err_cm": c["abs_err_cm"],
                            "pslr_db": c["pslr_db"],
                            "pnr_db": c["pnr_db"],
                            "supp_dw_win_db": c["supp_dw_win_db"],
                            "freeze_status": c["freeze_status"],
                        }
                        for c in result.get("cases", [])
                    ],
                    "hard_stops": result["hard_stops"],
                    "gray_reasons": result["gray_reasons"],
                    "out_dir": str(out_dir),
                }
            ),
            ensure_ascii=False,
        )
    )
    if freeze_status == "eligible":
        return 0
    if freeze_status == "hard_stop":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
