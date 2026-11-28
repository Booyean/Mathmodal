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

三种模式
--------
``--mode check``（默认）
    只跑放行前自检与白名单路径扫描（仅 `lstat`/`iterdir`，**不打开任何 `.dat`**），
    用来证明入口可用、边界正确。当前 `E0-C` 未获放行，本模式可随时运行。

``--mode execute``
    真正读取 96 个 `.dat` 并求解。**必须**同时给出 ``--approval-ref``（统筹放行
    消息的编号/链接），否则拒绝启动；该编号会写进结果 JSON 供追溯。
    按 ``E0-C-C12-REPEAT-1`` 冻结契约，**顺序启动两个独立进程**各跑一遍完整链路
    （每次都重新 preflight、重新读 96 个 `.dat`、互不共享数组），第 1 次写交付
    顶层文件，第 2 次写 ``repeat_runs/run-2/``；最终 ``e0c_repeat.json`` 登记
    两次运行的 PID、时间窗、结果/数组文件与 SHA256，两次组指标必须一致。
    不再接受“同一批数组两次序列化”。

``--mode execute-worker``
    内部单次运行入口（由 ``execute`` 派生，两次进程各调用一次）；也可用于只跑
    一次的诊断，但不构成 C12 证据。

用法::

    # 1) 现在可跑：入口 + 边界自检（不读采样）
    python solutions/A/a_e0_c.py --mode check

    # 2) 放行后：正式执行（两次独立进程，示例）
    python solutions/A/a_e0_c.py --mode execute --approval-ref <release-ref> `
        --repeat-runs 2 --implementation-sha <impl-sha> --parent-commit <parent-sha> `
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
import math
import platform
import re
import subprocess
import sys
import time
import traceback
import uuid
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

#: E0-PREREG-3 §2.3 冻结的交付数组契约。
AIR_LOO_PREFIX = "air_loo"
#: τ 轴非均匀：DW 窗与目标峰附近 0.05 ns（与 PLAN §5.1 的 41 点窗同分辨率），
#: 背景代理窗 [50,950] ns 取 0.25 ns（PLAN §5.1 的 m=200..3800 原生网格），
#: 跨 0/Tp 循环边界处保留 0.05 ns 以防止左半主瓣被截断。
DELIVERY_DENSE_STEP_NS = 0.05
DELIVERY_COARSE_STEP_NS = 0.25
DELIVERY_DENSE_SPAN_NS = 20.0
DELIVERY_BG_STOP_NS = 950.0
DELIVERY_D_STEP_M = 1e-4  # 0.1 mm 细网格（E0-PREREG-3 §2.3）
PSLR_HALF_WIDTH_M = 0.1606031
DATA_REL_PREFIX = PF.DATA_SUBDIR.as_posix()  # "附件/附件2-测距数据"

#: E0-PREREG-3 C12（两次独立运行证据，E0C-CL-5）：execute 必须顺序跑两次完整重算，
#: 每次从原始 .dat 重新读取、互不共享数组，分别落盘证据后再比对。
REPEAT_RUNS_DEFAULT = 2
REPEAT_DIR_NAME = "repeat_runs"
REPEAT_CONTRACT = "E0-C-C12-REPEAT-1"


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
def delivery_tau_axis(setup: "E0S.Setup") -> Tuple[np.ndarray, float]:
    """E0-PREREG-3 §2.3 的压缩延迟轴（单调、非均匀、覆盖一个 Tp）。

    * ``[0, 20)`` ns：0.05 ns 密集采样，覆盖全部直射波窗与目标峰（τ_dir ≤ 1.33 ns）；
    * ``[20, 950]`` ns：0.25 ns 采样，``[50,950]`` 与 PLAN §5.1 的 ``m=200..3800`` 对齐；
    * ``[999, 1000)`` ns：0.05 ns 密集采样，保留跨 0/Tp 边界的左半主瓣。

    返回 ``(tau_ns, dense_step_ns)``。窗口中心按 ``dense_step_ns`` 量化（≤0.025 ns），
    使每个通道的直射波窗恰为 PLAN 的 41 个采样点。
    """
    dense = np.arange(0.0, DELIVERY_DENSE_SPAN_NS, DELIVERY_DENSE_STEP_NS)
    n_coarse = int(round((DELIVERY_BG_STOP_NS - DELIVERY_DENSE_SPAN_NS) / DELIVERY_COARSE_STEP_NS))
    coarse = DELIVERY_DENSE_SPAN_NS + DELIVERY_COARSE_STEP_NS * np.arange(n_coarse + 1)
    tp_ns = float(np.round(float(setup.tp) * 1e9, 6))
    tail_start = tp_ns - 1.0
    tail = tail_start + DELIVERY_DENSE_STEP_NS * np.arange(
        int(round(1.0 / DELIVERY_DENSE_STEP_NS))
    )
    tau = np.concatenate([dense, coarse, tail])
    if not np.all(np.diff(tau) > 0):
        raise E0CStop("交付 tau 轴非严格单调")
    if tau[-1] >= setup.tp * 1e9:
        raise E0CStop("交付 tau 轴越出一个 Tp")
    return tau, DELIVERY_DENSE_STEP_NS


def z_at_tau_axis(
    x: np.ndarray,
    tpl: np.ndarray,
    f_r: np.ndarray,
    tau_ns: np.ndarray,
) -> np.ndarray:
    """在任意（非均匀）τ 轴上逐通道评估 ``z_i(tau)``（复用 E0S.z_at_delays）。"""
    delays = np.tile(np.asarray(tau_ns, dtype=np.float64) * 1e-9, (x.shape[0], 1))
    return E0S.z_at_delays(x, tpl, f_r, delays)


def profile_fine(
    x_after: np.ndarray,
    s_eff: np.ndarray,
    r_dir: np.ndarray,
    f_r: np.ndarray,
    c0: float,
    d_grid: np.ndarray,
    chunk: int = 1024,
) -> np.ndarray:
    """0.1 mm 网格上的 ``P_norm,eff``；分块求值以避免 (63, M, 1401) 峰值内存。"""
    out = np.empty(d_grid.size, dtype=np.float64)
    for start in range(0, d_grid.size, chunk):
        stop = min(start + chunk, d_grid.size)
        out[start:stop] = E0S.profile_p_norm_eff(
            x_after, s_eff, r_dir, f_r, c0, d_grid[start:stop]
        )[0]
    return out


def bg_from_z(z_after: np.ndarray, tau_ns: np.ndarray) -> float:
    """``BG_proxy = mean_{i, tau in [50,950] ns} |z_after|^2``（E0-PREREG-3 §5）。"""
    idx = np.flatnonzero((tau_ns >= 50.0) & (tau_ns <= 950.0))
    if idx.size == 0:
        raise E0CStop("交付 tau 轴不含背景代理窗 [50,950] ns")
    return float(np.mean(np.abs(z_after[:, idx]) ** 2))


def supp_from_z(
    z_before: np.ndarray,
    z_after: np.ndarray,
    tau_ns: np.ndarray,
    tau_dir_ns: np.ndarray,
    tp_ns: float = 1000.0,
) -> Tuple[float, int]:
    """按交付网格重算 ``Supp_dw-win``：逐通道取 ``|wrap(tau-tau_dir)|<=1 ns`` 的样本。"""
    before = 0.0
    after = 0.0
    samples = 0
    for i in range(z_before.shape[0]):
        delta = (tau_ns - float(tau_dir_ns[i]) + 0.5 * tp_ns) % tp_ns - 0.5 * tp_ns
        idx = np.flatnonzero(np.abs(delta) <= 1.0)
        if idx.size == 0:
            raise E0CStop("通道 %d 的直射波窗为空（tau_dir=%.3f ns）" % (i, tau_dir_ns[i]))
        samples += int(idx.size)
        before += float(np.sum(np.abs(z_before[i, idx]) ** 2))
        after += float(np.sum(np.abs(z_after[i, idx]) ** 2))
    if after <= 0.0:
        raise E0CStop("直射波窗内 after 功率非正")
    return 10.0 * math.log10(before / after), samples


def select_d_hat(
    p: np.ndarray,
    d_m: np.ndarray,
    target_type: str,
    eta_wall: float,
    bg_proxy: float,
) -> Tuple[float, str]:
    """在交付的 0.1 mm 剖面上按 E0-PREREG-3 §5 重选 ``d_hat``。"""
    if target_type == "metal":
        return float(d_m[int(np.argmax(p))]), "global_argmax"
    if target_type != "wall":
        raise E0CStop("未登记的 target_type=%r" % target_type)
    p_max = float(np.max(p))
    thr = max(float(eta_wall) * p_max, (10.0 ** 0.6) * float(bg_proxy))
    for k in range(1, len(p) - 1):
        if p[k] >= p[k - 1] and p[k] >= p[k + 1] and p[k] >= thr:
            return float(d_m[k]), "wall_first_peak"
    raise E0CStop(
        "墙体首峰规则在 0.1 mm 网格上无候选（thr=%.6g, P_max=%.6g）" % (thr, p_max)
    )


def pslr_from_p(p: np.ndarray, d_m: np.ndarray, d_hat: float) -> float:
    pk = int(np.argmin(np.abs(d_m - d_hat)))
    sidelobe = p[np.abs(d_m - d_hat) > PSLR_HALF_WIDTH_M]
    if sidelobe.size == 0:
        raise E0CStop("PSLR 旁瓣区为空")
    return 10.0 * math.log10(float(p[pk]) / float(np.max(sidelobe)))


def pnr_from_z(
    z_after: np.ndarray,
    tau_ns: np.ndarray,
    d_hat: float,
    c0: float,
    bg_proxy: float,
) -> float:
    tau_tgt_ns = 2.0 * float(d_hat) / float(c0) * 1e9
    k = int(np.argmin(np.abs(tau_ns - tau_tgt_ns)))
    p_tgt = float(np.mean(np.abs(z_after[:, k]) ** 2))
    if p_tgt <= 0.0:
        raise E0CStop("目标时延采样点功率非正")
    return 10.0 * math.log10(p_tgt / float(bg_proxy))


def build_air_loo_document(
    loo: Dict[str, Any],
    gates: Dict[str, Any],
    air_min_db: float,
    air_median_db: float,
) -> Dict[str, Any]:
    """按 E0-PREREG-3 §2.4 生成 ``e0c_air_loo.json`` 的字段结构。"""
    rows = loo["grid_rows"]
    grid: List[Dict[str, Any]] = []
    for row in rows:
        grid.append(
            {
                "lambdas": [float(row["lambda_cal"]), float(row["lambda_inv"])],
                "folds": [
                    {"held_out": str(g), "supp_db": float(v)}
                    for g, v in zip(AIR_GROUPS, row["supp_db"])
                ],
                "j_air_db": float(row["J_air_db"]),
                "min_db": float(row["min_supp_db"]),
                "median_db": float(row["median_supp_db"]),
            }
        )
    elig_min = float(gates["air_loo_eligible_min_suppression_db"])
    hard = float(gates["air_loo_hard_stop_suppression_db"])
    if float(air_min_db) >= elig_min:
        eligibility = "eligible"
    elif float(air_min_db) >= hard:
        eligibility = "gray"
    else:
        eligibility = "hard_stop"
    return {
        "prereg": "E0-PREREG-3",
        "folds": [
            {"index": i, "held_out": str(g)} for i, g in enumerate(AIR_GROUPS)
        ],
        "grid": grid,
        "selected": [
            float(loo["selected"]["lambda_cal"]),
            float(loo["selected"]["lambda_inv"]),
        ],
        "switched": bool(loo["triggered"]),
        "min_supp_db": float(air_min_db),
        "median_supp_db": float(air_median_db),
        "j_air_default_db": float(loo["default"]["J_air_db"]),
        "j_air_best_db": float(loo["best"]["J_air_db"]),
        "eligibility": eligibility,
        "switch_reason": str(loo["trigger_reason"]),
        "tie_tolerance_db": float(loo["tie_tolerance_db"]),
        "near_tie": bool(loo.get("near_tie", False)),
        "tied_candidates": loo.get("tied_candidates", []),
        "budget_pairs": int(loo["budget_pairs"]),
    }


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

    # ---- 交付网格（E0-PREREG-3 §2.3）：0.05 ns 压缩延迟轴 + 0.1 mm 距离网格
    tau_ns, tau_step_ns = delivery_tau_axis(setup)
    # 窗口中心对齐到交付网格：保证每通道恰为 PLAN §5.1 的 41 点窗（量化 ≤0.025 ns）。
    tau_dir_ns = np.round(tau_dir * 1e9 / tau_step_ns) * tau_step_ns
    d_fine = np.arange(
        setup.d_min, setup.d_max + 0.5 * DELIVERY_D_STEP_M, DELIVERY_D_STEP_M
    )

    cases: List[Dict[str, Any]] = []
    for tgt in targets:
        prefix = str(tgt["array_prefix"])
        peak_rule = str(tgt["peak_rule"])
        d_true_cm = float(tgt["d_true_cm"])

        # ---- M0-DW-Base(alpha=1.0) 与 S_eff（复用 E0-S 已验收原语）
        x_cal = tgt["x"] * cal["inv"]
        dt0_s = E0S.align_lag(
            cal["xbar_cal"], x_cal, f_r, setup.band_idx, setup.np_n, setup.ts, setup.tp
        )
        xair_aligned = cal["xbar_cal"] * np.exp(1j * 2.0 * np.pi * f_r * dt0_s)[None, :]
        alpha = float(
            cfg["methods_classic_baseline_only"]["direct_wave_suppression"][
                "alpha_fixed_value"
            ]
        )
        if alpha != 1.0:
            raise E0CStop("alpha_fixed_value=%r ≠ 1.0（违反方法范围）" % alpha)
        x_after = x_cal - alpha * xair_aligned
        s_eff = E0S.build_s_eff(xair_aligned, r_dir, tau_dir, f_r)

        z_before = z_at_tau_axis(x_cal, s_eff, f_r, tau_ns)
        z_after = z_at_tau_axis(x_after, s_eff, f_r, tau_ns)
        if not (
            np.all(np.isfinite(z_before))
            and np.all(np.isfinite(z_after))
            and np.all(np.isfinite(x_after))
        ):
            raise E0CStop("交付数组含 NaN/Inf：%s" % tgt["group_key"])

        bg_proxy = bg_from_z(z_after, tau_ns)
        supp_db, win_samples = supp_from_z(z_before, z_after, tau_ns, tau_dir_ns)
        p_fine = profile_fine(x_after, s_eff, r_dir, f_r, setup.c0, d_fine)
        if not np.all(np.isfinite(p_fine)):
            raise E0CStop("0.1 mm 剖面含 NaN/Inf：%s" % tgt["group_key"])

        valid_rx = int(np.sum(np.all(np.isfinite(x_cal), axis=1)))
        finite = bool(
            np.all(np.isfinite(z_before))
            and np.all(np.isfinite(z_after))
            and np.all(np.isfinite(p_fine))
            and math.isfinite(supp_db)
            and math.isfinite(bg_proxy)
        )

        def _metrics_for_eta(eta_value: float) -> Tuple[float, str, float, float]:
            d_hat_v, rule_v = select_d_hat(
                p_fine, d_fine, peak_rule, eta_value, bg_proxy
            )
            return (
                d_hat_v,
                rule_v,
                pslr_from_p(p_fine, d_fine, d_hat_v),
                pnr_from_z(z_after, tau_ns, d_hat_v, setup.c0, bg_proxy),
            )

        d_hat, d_rule, pslr_db, pnr_db = _metrics_for_eta(float(eta_default))
        eta_records: List[Dict[str, Any]] = []
        selected_eta = float(eta_default)
        if peak_rule == "wall":
            # PLAN §3.3：仅在本校准组上核对 {0.15,0.25,0.35}，取满足条件且最接近
            # 默认 0.25 者；所有候选结果全部入档。
            chosen: Optional[Dict[str, Any]] = None
            for eta in eta_order:
                d_v, rule_v, pslr_v, pnr_v = _metrics_for_eta(float(eta))
                err_v = abs(d_v - d_true_cm / 100.0) * 100.0
                record = {
                    "eta_wall": float(eta),
                    "d_hat_m": float(d_v),
                    "abs_err_cm": float(err_v),
                    "pslr_db": float(pslr_v),
                    "pnr_db": float(pnr_v),
                    "eligible": bool(
                        err_v <= float(gates["cal_pilot_eligible_max_range_err_cm"])
                        and pslr_v >= float(gates["target_echo_min_pslr_db"])
                        and pnr_v >= float(gates["target_echo_min_pnr_db"])
                        and valid_rx == int(gates["required_valid_rx_channels"])
                        and finite
                    ),
                }
                eta_records.append(record)
                if record["eligible"] and chosen is None:
                    chosen = dict(record, rule=rule_v)
            if chosen is not None:
                d_hat = float(chosen["d_hat_m"])
                d_rule = str(chosen["rule"])
                pslr_db = float(chosen["pslr_db"])
                pnr_db = float(chosen["pnr_db"])
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

        abs_err_cm = abs(float(d_hat) - d_true_cm / 100.0) * 100.0
        p_before_hat = float(
            E0S.profile_p_norm_eff(
                x_cal, s_eff, r_dir, f_r, setup.c0, np.asarray([d_hat])
            )[0][0]
        )
        p_after_hat = float(
            E0S.profile_p_norm_eff(
                x_after, s_eff, r_dir, f_r, setup.c0, np.asarray([d_hat])
            )[0][0]
        )
        echo_ret_db = 10.0 * math.log10(p_after_hat / p_before_hat)

        case = {
            "case_id": str(tgt["case_id"]),
            "group_key": str(tgt.get("group_key", "")),
            "target_type": str(tgt["target_type"]),
            "in_split": tgt.get("in_split"),
            "peak_rule": peak_rule,
            "d_hat_rule": d_rule,
            "eta_wall": selected_eta if peak_rule == "wall" else None,
            "eta_wall_candidates": eta_records if peak_rule == "wall" else [],
            "d_true_cm_nominal": d_true_cm,
            "d_hat_m": float(d_hat),
            "d_hat_cm": float(d_hat) * 100.0,
            "abs_err_cm": float(abs_err_cm),
            "supp_dw_win_db": float(supp_db),
            "pslr_db": float(pslr_db),
            "pnr_db": float(pnr_db),
            "echo_ret_db": float(echo_ret_db),
            "bg_proxy": float(bg_proxy),
            "valid_rx": int(valid_rx),
            "finite": bool(finite),
            "dt0_samples": float(dt0_s / setup.ts),
            "dw_window_samples": int(win_samples),
            "metric_grid": {
                "tau_step_ns": float(tau_step_ns),
                "d_step_m": float(DELIVERY_D_STEP_M),
                "supp_window": "|wrap(tau-tau_dir)|<=1.0 ns on delivered tau grid",
                "pnr_sample": "nearest delivered tau sample to 2*d_hat/c0",
                "bg_window_ns": [50.0, 950.0],
            },
        }
        case["gate_results"] = evaluate_case_gates(case, gates)
        case["freeze_status"] = case_freeze_status(case["gate_results"])
        cases.append(case)

        arrays.update(
            {
                "%s__tau_ns" % prefix: tau_ns,
                "%s__tau_dir_ns" % prefix: tau_dir_ns,
                "%s__z_before" % prefix: z_before,
                "%s__z_after" % prefix: z_after,
                "%s__d_m" % prefix: d_fine,
                "%s__P_after" % prefix: p_fine,
            }
        )

    arrays["%s__p_cal" % AIR_LOO_PREFIX] = np.asarray(loo["p_cal"], dtype=np.float64)
    arrays["%s__p_sup" % AIR_LOO_PREFIX] = np.asarray(loo["p_sup"], dtype=np.float64)

    return {
        "lambda_loo": build_air_loo_document(loo, gates, air_min_db, air_median_db),
        "air_loo_raw": {
            "budget_pairs": int(loo["budget_pairs"]),
            "folds": int(loo["folds"]),
            "best": loo["best"],
            "default": loo["default"],
            "trigger_reason": loo["trigger_reason"],
            "tie_tolerance_db": float(loo["tie_tolerance_db"]),
            "near_tie": bool(loo.get("near_tie", False)),
            "tied_candidates": loo.get("tied_candidates", []),
        },
        "cal": {
            "shifts_s": [float(s) for s in shifts],
            "lambda_cal": float(lam["lambda_cal"]),
            "lambda_inv": float(lam["lambda_inv"]),
            "eta_wall_default": float(eta_default),
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
    ctx["air_loo_raw"] = solved.get("air_loo_raw")
    ctx["cal"] = solved["cal"]
    ctx["cases"] = solved["cases"]
    ctx["arrays"] = solved["arrays"]

    # ---- 3) 硬停止 / 灰区判定
    loo_doc = solved["lambda_loo"]
    ctx["air_loo_eligibility"] = loo_doc["eligibility"]
    hard_stops: List[str] = []
    gray_reasons: List[str] = []
    if loo_doc["eligibility"] == "hard_stop":
        hard_stops.append(
            "air_loo_hard_stop: min=%.4f dB < %.1f dB"
            % (loo_doc["min_supp_db"], float(cfg["gates_and_thresholds"]["air_loo_hard_stop_suppression_db"]))
        )
    elif loo_doc["eligibility"] == "gray":
        grid_min = min(float(g["min_db"]) for g in loo_doc["grid"])
        gray_reasons.append(
            "air_loo_gray: selected min=%.4f dB in [6,10); 9-pair grid min=%.4f dB -> 不冻结、禁入 E0-T"
            % (loo_doc["min_supp_db"], grid_min)
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
METRIC_KEYS = (
    "group_key",
    "d_hat_m",
    "abs_err_cm",
    "supp_dw_win_db",
    "pslr_db",
    "pnr_db",
    "valid_rx",
    "finite",
)

E0S_RESULTS_REL = "experiments/A/A-Q1-E0/s1s2/results/e0_s1s2_results.json"


def metrics_digest(groups: Sequence[Dict[str, Any]]) -> str:
    """E0-PREREG-3 §2.2 的 ``metrics_sha256``：按 groups 顺序取 8 个键规范化。"""
    rows = [{k: g.get(k) for k in METRIC_KEYS} for g in groups]
    return E0S.canonical_json_sha256(rows)


def save_npz_deterministic(path: Path, arrays: Dict[str, np.ndarray]) -> None:
    """确定性 npz（固定 zip 时间戳），使同一组数组两次序列化逐字节可比。"""
    import io
    import zipfile

    with zipfile.ZipFile(
        path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        for key in sorted(arrays):
            arr = np.ascontiguousarray(np.asarray(arrays[key]))
            info = zipfile.ZipInfo(
                filename=key + ".npy", date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            buf = io.BytesIO()
            np.lib.format.write_array(buf, arr, allow_pickle=False)
            zf.writestr(info, buf.getvalue())


def _iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


#: C12 冻结契约 `E0-C-C12-REPEAT-1`（checks/A/e0_c_repeat_contract.json）。
REPEAT_REQUIRED_FIELDS: Tuple[str, ...] = (
    "run_id",
    "pid",
    "started_at",
    "finished_at",
    "results_file",
    "results_sha256",
    "arrays_file",
    "arrays_sha256",
    "wall_time_s",
)
REPEAT_PROVENANCE_FIELDS: Tuple[str, ...] = (
    "run_id",
    "pid",
    "started_at",
    "finished_at",
    "results_file",
    "arrays_file",
)
REPEAT_CASE_FIELDS: Tuple[str, ...] = (
    "d_hat_m",
    "abs_err_cm",
    "supp_dw_win_db",
    "pslr_db",
    "pnr_db",
    "echo_ret_db",
)


def _case_metrics(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for case in ctx.get("cases") or []:
        cid = str(case.get("case_id") or case.get("group_key"))
        row: Dict[str, Any] = {}
        for k in REPEAT_CASE_FIELDS:
            value = case.get(k)
            row[k] = None if value is None else float(value)
        row["freeze_status"] = str(case.get("freeze_status"))
        row["valid_rx"] = int(case.get("valid_rx") or 0)
        out[cid] = row
    return out


def _rel_inside(out_dir: Path, rel: Any) -> Path:
    """把交付目录内的相对路径解析为绝对路径；拒绝绝对路径与 ``..`` 逃逸。"""
    text = str(rel or "").replace("\\", "/").strip()
    if not text:
        raise E0CStop("证据路径为空")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise E0CStop("证据路径必须是相对路径：%r" % rel)
    norm = os.path.normpath(text).replace("\\", "/")
    if norm == ".." or norm.startswith("../"):
        raise E0CStop("证据路径逃出交付目录：%r" % rel)
    path = (Path(out_dir) / norm).resolve()
    root = Path(out_dir).resolve()
    if path != root and root not in path.parents:
        raise E0CStop("证据路径逃出交付目录：%r" % rel)
    return path


def _apply_stop_status(
    result: Dict[str, Any], cfg: Dict[str, Any], elapsed: float, peak: Optional[float]
) -> str:
    """把硬停止/灰区/资源预算折算成冻结状态（worker 与最终交付共用）。"""
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
    result["stop_reason"] = "; ".join(hard_stops + gray_reasons) or None
    result["freeze"] = {
        **(result.get("freeze") or {}),
        "status": freeze_status,
        "eligible": freeze_status == "eligible",
        "reasons": list(hard_stops + gray_reasons),
    }
    return freeze_status


def execute_single_delivery(
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    config_path: Path,
    cfg: Dict[str, Any],
    setup: "E0S.Setup",
    approval_ref: str,
    eta_wall: Optional[float],
    out_dir: Path,
    implementation_sha: Optional[str],
    parent_commit: Optional[str],
    main_commit: Optional[str],
    command: str,
    log: List[str],
) -> Dict[str, Any]:
    """**一次**完整 E0-C 运行，并写出一套自洽的交付文件（不含 C12 汇总）。

    这是 ``--mode execute-worker`` 的唯一实现：把整条链路跑一遍、按
    ``E0-PREREG-3`` 落盘并写 ``worker_meta.json``。两次独立运行由
    ``run_two_independent_runs`` 分别启动**两个进程**调用本函数完成。
    """
    out_dir = Path(out_dir)
    started_at = _iso_ms()
    started = time.perf_counter()
    try:
        ctx = run_execute(
            repo,
            data_root,
            manifest_path,
            cfg,
            setup,
            approval_ref,
            eta_wall,
            log,
        )
    except E0CStop as exc:
        ctx = {
            "experiment_id": "A-Q1-E0",
            "phase": "E0-C",
            "contract_version": CONTRACT_VERSION,
            "approval_ref": approval_ref,
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
            "approval_ref": approval_ref,
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
    result = assemble_results(
        ctx,
        cfg,
        config_path,
        repo,
        approval_ref,
        implementation_sha or prov.get("head_sha"),
        parent_commit or prov.get("parent_sha"),
        main_commit or prov.get("origin_main_sha"),
        prov.get("branch"),
        command,
        elapsed,
        peak,
        out_dir,
    )
    result["git"] = prov
    result["stop_detail"] = ctx.get("stop_detail")
    result["partial"] = ctx.get("partial")
    result["resource"]["wall_time_s"] = round(elapsed, 3)
    result["resource"]["peak_rss_mib"] = peak

    freeze_status = _apply_stop_status(result, cfg, elapsed, peak)

    arrays = ctx.get("arrays")
    write_outputs(out_dir, result, arrays, log, c0=float(setup.c0))
    finished_at = _iso_ms()
    meta = {
        "run_id": uuid.uuid4().hex,
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_time_s": round(elapsed, 3),
        "peak_rss_mib": peak,
        "results_file": "e0c_results.json",
        "results_sha256": file_sha256(out_dir / "e0c_results.json"),
        "arrays_file": "e0c_arrays.npz" if arrays is not None else None,
        "arrays_sha256": result.get("arrays_sha256"),
        "metrics_sha256": result.get("metrics_sha256"),
        "freeze_status": freeze_status,
        "stop_reason": result.get("stop_reason"),
        "groups_complete": bool(result.get("groups")),
    }
    write_json(out_dir / "worker_meta.json", meta)
    return {
        "meta": meta,
        "result": result,
        "arrays": arrays,
        "freeze_status": freeze_status,
    }


def _compare_two_runs(
    res1: Dict[str, Any],
    res2: Dict[str, Any],
    meta1: Dict[str, Any],
    meta2: Dict[str, Any],
    npz_sha: Optional[str],
) -> List[str]:
    """两次独立运行必须逐项一致；返回问题清单（空=可登记）。"""
    problems: List[str] = []
    if not meta1.get("arrays_sha256") or not meta2.get("arrays_sha256"):
        problems.append("至少一次运行没有交付数组")
        return problems
    if not (
        meta1["arrays_sha256"]
        == meta2["arrays_sha256"]
        == res1.get("arrays_sha256")
        == res2.get("arrays_sha256")
        == npz_sha
    ):
        problems.append("两次运行的交付数组摘要不一致或与 e0c_arrays.npz 不符")
    if res1.get("metrics_sha256") != res2.get("metrics_sha256"):
        problems.append("两次运行的指标摘要不一致")
    if meta1.get("freeze_status") != meta2.get("freeze_status"):
        problems.append("两次运行的冻结状态不一致")
    if (meta1.get("stop_reason") or None) != (meta2.get("stop_reason") or None):
        problems.append("两次运行的停止原因不一致")
    g1 = {g.get("group_key"): g for g in (res1.get("groups") or [])}
    g2 = {g.get("group_key"): g for g in (res2.get("groups") or [])}
    if set(g1) != set(g2):
        problems.append("两次运行的组集合不同")
    for key in sorted(set(g1) & set(g2)):
        for field, tol in (
            ("d_hat_m", 1e-12),
            ("abs_err_cm", 1e-9),
            ("supp_dw_win_db", 1e-9),
            ("pslr_db", 1e-9),
            ("pnr_db", 1e-9),
        ):
            a, b = g1[key].get(field), g2[key].get(field)
            if a is None and b is None:
                continue
            if a is None or b is None or abs(float(a) - float(b)) > tol:
                problems.append("%s.%s 两次运行不一致：%r vs %r" % (key, field, a, b))
        for field in ("valid_rx", "finite"):
            if g1[key].get(field) != g2[key].get(field):
                problems.append("%s.%s 两次运行不一致" % (key, field))
    return problems


def run_two_independent_runs(
    worker_argv: Sequence[str],
    out_dir: Path,
    log: List[str],
    command: str,
    result_transform: Optional[Any] = None,
) -> Dict[str, Any]:
    """顺序启动**两个独立进程**跑完整 E0-C，并汇总成 C12 的两次运行证据。

    第 1 次运行写交付目录顶层（``e0c_results.json`` / ``e0c_arrays.npz``），
    第 2 次写到 ``repeat_runs/run-2/``；两次的 PID、时间窗、结果文件与数组文件
    互不相同（``E0-C-C12-REPEAT-1`` 的 ``provenance_must_differ``），两次运行的
    组指标必须一致。最终交付写 ``e0c_repeat.json``（runs 清单）与顶层
    ``repeat_run`` 摘要（不内嵌 runs，避免 “results_sha256 自引用” 不可能闭环）。
    """
    out_dir = Path(out_dir)
    second_dir = out_dir / REPEAT_DIR_NAME / "run-2"
    if second_dir.exists() and any(second_dir.iterdir()):
        raise E0CStop(
            "%s 已存在旧证据；请换新输出目录（不覆盖已登记证据）" % second_dir
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    overall_started = time.perf_counter()
    metas: List[Dict[str, Any]] = []
    for idx, target in ((1, out_dir), (2, second_dir)):
        argv = [str(x) for x in worker_argv] + ["--out", str(target)]
        proc = subprocess.run(
            argv,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log.append("[orchestrator] run %d exit=%d" % (idx, proc.returncode))
        for stream, text in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            for line in (text or "").strip().splitlines()[-6:]:
                log.append("[run%d %s] %s" % (idx, stream, line))
        meta_path = target / "worker_meta.json"
        if proc.returncode not in (0, 1, 3) or not meta_path.is_file():
            raise E0CStop(
                "第 %d 次运行未产出可登记结果（exit=%d，meta=%s）"
                % (idx, proc.returncode, meta_path)
            )
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise E0CStop("第 %d 次运行的 worker_meta.json 不可读：%s" % (idx, exc))
        meta["_dir"] = str(target)
        metas.append(meta)
    total_wall = time.perf_counter() - overall_started

    res1 = json.loads((out_dir / "e0c_results.json").read_text(encoding="utf-8"))
    res2 = json.loads((second_dir / "e0c_results.json").read_text(encoding="utf-8"))
    npz_sha = file_sha256(out_dir / "e0c_arrays.npz") if (
        out_dir / "e0c_arrays.npz"
    ).is_file() else None
    problems = _compare_two_runs(res1, res2, metas[0], metas[1], npz_sha)
    if problems:
        raise E0CStop("两次独立运行不一致：" + "; ".join(problems[:6]))

    if result_transform is not None:
        result_transform(res1)

    res1["resource"]["wall_time_s"] = round(total_wall, 3)
    res1["resource"]["repeat_runs"] = 2
    res1["resource"]["per_run_wall_time_s"] = [
        float(metas[0]["wall_time_s"]),
        float(metas[1]["wall_time_s"]),
    ]
    res1["resource"]["peak_rss_mib"] = max(
        [float(metas[0].get("peak_rss_mib") or 0.0), float(metas[1].get("peak_rss_mib") or 0.0)]
    )
    res1["resource"]["process_model"] = (
        "两次顺序独立运行；任一时刻单进程单线程，两次进程号不同"
    )
    res1["command"] = command
    res1["arrays_sha256"] = npz_sha
    res1["arrays_file_sha256"] = npz_sha
    res1["repeat_run"] = {
        "contract": REPEAT_CONTRACT,
        "n_runs": 2,
        "runs_file": "e0c_repeat.json",
        "arrays_sha256": npz_sha,
        "metrics_sha256": res1.get("metrics_sha256"),
        "arrays_identical": True,
        "metrics_identical": True,
        "metrics_max_abs_delta": 0.0,
        "metrics_recomputed_from_delivered_arrays": True,
        "selection_rule": "第一次运行即交付运行；第二次运行只作独立复跑，两次必须逐项一致",
        "note": "两次独立进程各自的 results/arrays 证据见 e0c_repeat.json；"
        "本字段不内嵌 runs，避免 results_sha256 自引用",
    }

    # 最终日志：第 1 次运行的 run.log + 汇总行。
    log_path = out_dir / "run.log"
    base_log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    log_path.write_text(
        base_log.rstrip("\n")
        + "\n"
        + "\n".join(log)
        + "\n",
        encoding="utf-8",
    )

    evidence_files = [
        "e0c_arrays.npz",
        "e0c_air_loo.json",
        "run.log",
    ]
    if (out_dir / "e0c_frozen.json").is_file():
        evidence_files.append("e0c_frozen.json")
    for name in ("e0c_results.json", "e0c_arrays.npz", "e0c_air_loo.json", "run.log", "e0c_frozen.json"):
        rel = "%s/run-2/%s" % (REPEAT_DIR_NAME, name)
        if (second_dir / name).is_file():
            evidence_files.append(rel)
    res1["files_sha256"] = {
        rel: file_sha256(out_dir / rel) for rel in evidence_files
    }
    res1["files_sha256_note"] = (
        "本表不含 e0c_results.json / e0c_repeat.json 自身；其摘要见 SHA256SUMS.txt"
    )
    write_json(out_dir / "e0c_results.json", res1)
    res1_sha = file_sha256(out_dir / "e0c_results.json")

    runs = []
    for idx, (meta, result_path, arrays_path) in enumerate(
        (
            (metas[0], "e0c_results.json", "e0c_arrays.npz"),
            (metas[1], "%s/run-2/e0c_results.json" % REPEAT_DIR_NAME,
             "%s/run-2/e0c_arrays.npz" % REPEAT_DIR_NAME),
        ),
        start=1,
    ):
        runs.append(
            {
                "run_index": idx,
                "run_id": str(meta["run_id"]),
                "pid": int(meta["pid"]),
                "started_at": str(meta["started_at"]),
                "finished_at": str(meta["finished_at"]),
                "wall_time_s": float(meta["wall_time_s"]),
                "peak_rss_mib": meta.get("peak_rss_mib"),
                "results_file": result_path,
                "results_sha256": res1_sha if idx == 1 else file_sha256(out_dir / result_path),
                "arrays_file": arrays_path,
                "arrays_sha256": file_sha256(out_dir / arrays_path),
                "metrics_sha256": res1.get("metrics_sha256") if idx == 1 else res2.get("metrics_sha256"),
                "freeze_status": res1.get("freeze", {}).get("status") if idx == 1 else res2.get("freeze", {}).get("status"),
                "stop_reason": res1.get("stop_reason") if idx == 1 else res2.get("stop_reason"),
            }
        )
    manifest = {
        "contract": REPEAT_CONTRACT,
        "n_runs": 2,
        "delivery_run_index": 1,
        "selection_rule": "not best-of: run 1 is the delivery; run 2 must agree",
        "total_wall_time_s": round(total_wall, 3),
        "arrays_identical": True,
        "metrics_identical": True,
        "metrics_max_abs_delta": 0.0,
        "runs": runs,
        "problems": [],
    }
    write_json(out_dir / "e0c_repeat.json", manifest)

    # SHA256SUMS：交付必需文件 + 两次运行证据（含 e0c_repeat.json）。
    sums: Dict[str, str] = {}
    for rel in (
        "e0c_results.json",
        "e0c_arrays.npz",
        "e0c_air_loo.json",
        "e0c_repeat.json",
        "run.log",
    ):
        if (out_dir / rel).is_file():
            sums[rel] = file_sha256(out_dir / rel)
    if (out_dir / "e0c_frozen.json").is_file():
        sums["e0c_frozen.json"] = file_sha256(out_dir / "e0c_frozen.json")
    for rec in runs:
        for rel in (rec["results_file"], rec["arrays_file"]):
            if rel not in sums and (out_dir / rel).is_file():
                sums[rel] = file_sha256(out_dir / rel)
    (out_dir / "SHA256SUMS.txt").write_text(
        "\n".join("%s  %s" % (v, k) for k, v in sorted(sums.items())) + "\n",
        encoding="utf-8",
    )
    # 把最终 results 摘要回填到 worker_meta（只作诊断，权威清单是 e0c_repeat.json）。
    metas[0]["results_sha256"] = res1_sha
    write_json(out_dir / "worker_meta.json", metas[0])

    verify_repeat_manifest(out_dir)
    return {
        "result": res1,
        "manifest": manifest,
        "elapsed": total_wall,
        "runs": runs,
        "freeze_status": str(res1.get("freeze", {}).get("status")),
    }


def verify_repeat_manifest(out_dir: Path) -> Dict[str, Any]:
    """机械核验 ``e0c_repeat.json`` 与顶层交付的 C12 一致性（写盘后自检）。"""
    out_dir = Path(out_dir)
    path = out_dir / "e0c_repeat.json"
    if not path.is_file():
        raise E0CStop("缺少 e0c_repeat.json：两次独立运行证据未登记")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise E0CStop("e0c_repeat.json 不可读：%s" % exc)
    problems: List[str] = []
    runs = list(manifest.get("runs") or [])
    if int(manifest.get("n_runs") or 0) != 2 or len(runs) != 2:
        problems.append("n_runs 必须为 2 且 runs 长度为 2")
    if len(runs) != 2:
        raise E0CStop("两次独立运行证据不完整：" + "; ".join(problems))
    windows = []
    for idx, rec in enumerate(runs):
        miss = [f for f in REPEAT_REQUIRED_FIELDS if f not in rec]
        if miss:
            problems.append("runs[%d] 缺少字段 %s" % (idx, miss))
            continue
        for kind in ("results", "arrays"):
            rel = rec.get("%s_file" % kind)
            try:
                target = _rel_inside(out_dir, rel)
            except E0CStop as exc:
                problems.append("runs[%d].%s_file 非法：%s" % (idx, kind, exc))
                continue
            if not target.is_file():
                problems.append("runs[%d].%s_file 不存在：%s" % (idx, kind, rel))
                continue
            if file_sha256(target) != str(rec.get("%s_sha256" % kind)):
                problems.append("runs[%d].%s_sha256 与文件不符" % (idx, kind))
        if not isinstance(rec.get("pid"), int) or int(rec.get("pid")) <= 0:
            problems.append("runs[%d].pid 非法" % idx)
        try:
            started = datetime.fromisoformat(
                str(rec["started_at"]).replace("Z", "+00:00")
            )
            finished = datetime.fromisoformat(
                str(rec["finished_at"]).replace("Z", "+00:00")
            )
            if started.tzinfo is None or finished.tzinfo is None:
                raise ValueError("缺少时区")
            if not started < finished:
                problems.append("runs[%d].started_at 不早于 finished_at" % idx)
            windows.append((started, finished))
        except (KeyError, ValueError) as exc:
            problems.append("runs[%d] 时间戳不可解析：%s" % (idx, exc))
        try:
            if float(rec.get("wall_time_s")) <= 0:
                problems.append("runs[%d].wall_time_s 非正" % idx)
        except (TypeError, ValueError):
            problems.append("runs[%d].wall_time_s 非数值" % idx)
    if len(windows) == 2 and windows[0][1] > windows[1][0]:
        problems.append("两次运行的时间窗重叠或顺序颠倒")
    for field in REPEAT_PROVENANCE_FIELDS:
        vals = [str(r.get(field)) for r in runs]
        if len(set(vals)) != len(vals):
            problems.append("两次运行的 %s 相同 → 不是独立运行" % field)
    # runs[0] 必须绑定本次交付的顶层文件。
    if str(runs[0].get("arrays_file")) != "e0c_arrays.npz":
        problems.append("runs[0].arrays_file 必须是 e0c_arrays.npz")
    if str(runs[0].get("results_file")) != "e0c_results.json":
        problems.append("runs[0].results_file 必须是 e0c_results.json")
    # 顶层结果摘要与证据绑定。
    try:
        result = json.loads((out_dir / "e0c_results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise E0CStop("e0c_results.json 不可读：%s" % exc)
    rr = result.get("repeat_run") or {}
    if rr.get("runs_file") != "e0c_repeat.json":
        problems.append("repeat_run.runs_file 未指向 e0c_repeat.json")
    if "runs" in rr:
        problems.append("repeat_run 不应内嵌 runs（会造成 results_sha256 自引用）")
    if rr.get("arrays_sha256") != result.get("arrays_sha256"):
        problems.append("repeat_run.arrays_sha256 与顶层 arrays_sha256 不同")
    if rr.get("arrays_sha256") != runs[0].get("arrays_sha256"):
        problems.append("repeat_run.arrays_sha256 与第一次运行数组不同")
    if rr.get("metrics_sha256") != result.get("metrics_sha256"):
        problems.append("repeat_run.metrics_sha256 与顶层 metrics_sha256 不同")
    # 第二次运行的 groups 必须与交付一致。
    try:
        second = json.loads(
            (out_dir / str(runs[1]["results_file"])).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise E0CStop("第二次运行结果不可读：%s" % exc)
    problems.extend(_compare_two_runs(result, second, runs[0], runs[1], result.get("arrays_sha256")))
    if problems:
        raise E0CStop("两次独立运行证据不可核验：" + "; ".join(problems[:6]))
    return manifest


def verify_delivery_metrics(
    result: Dict[str, Any],
    arrays: Dict[str, np.ndarray],
    c0: float = 299792458.0,
) -> Dict[str, float]:
    """按 E0-PREREG-3 §5 从交付数组重算目标指标，核对 JSON 值（C10 前置自检）。

    任何不一致都会抛 ``E0CStop``，绝不写出“实现自洽、数组不符”的结果。
    """
    problems: List[str] = []
    deltas: Dict[str, float] = {}
    by_group = {c["group_key"]: c for c in result.get("cases", [])}
    for grp in result.get("groups", []):
        key = str(grp.get("group_key"))
        if key not in by_group:
            continue
        case = by_group[key]
        prefix = None
        for spec in TARGET_SPECS:
            if str(spec["group"]) == key:
                prefix = str(spec["array_prefix"])
        if prefix is None:
            continue
        tau = np.asarray(arrays["%s__tau_ns" % prefix], dtype=np.float64)
        tau_dir = np.asarray(arrays["%s__tau_dir_ns" % prefix], dtype=np.float64)
        zb = np.asarray(arrays["%s__z_before" % prefix])
        za = np.asarray(arrays["%s__z_after" % prefix])
        d_m = np.asarray(arrays["%s__d_m" % prefix], dtype=np.float64)
        p = np.asarray(arrays["%s__P_after" % prefix], dtype=np.float64)
        bg = bg_from_z(za, tau)
        supp, _ = supp_from_z(zb, za, tau, tau_dir)
        d_hat, _ = select_d_hat(
            p, d_m, str(case["target_type"]), float(result["eta_wall"]), bg
        )
        pslr = pslr_from_p(p, d_m, d_hat)
        pnr = pnr_from_z(za, tau, d_hat, c0, bg)
        checks = {
            "supp_dw_win_db": (supp, 1e-6),
            "pslr_db": (pslr, 1e-6),
            "pnr_db": (pnr, 1e-6),
            "d_hat_m": (d_hat, 1e-9),
        }
        for field, (want, tol) in checks.items():
            got = float(grp.get(field))
            delta = abs(got - want)
            deltas["%s.%s" % (key, field)] = delta
            if delta > tol:
                problems.append(
                    "%s.%s: JSON=%.12g 重算=%.12g (Δ=%.3g)"
                    % (key, field, got, want, delta)
                )
    if problems:
        raise E0CStop("交付指标与数组重算不一致：" + "; ".join(problems[:5]))
    return deltas


def collect_inputs(data_groups: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把 12 组 × 8 行文件展开成 E0-PREREG-3 §2.2 的 ``inputs[96]``。"""
    rows: List[Dict[str, Any]] = []
    order = list(AIR_GROUPS) + [str(t["group"]) for t in TARGET_SPECS]
    by_key = {g["group_key"]: g for g in data_groups}
    for key in order:
        grp = by_key.get(key)
        if grp is None:
            raise E0CStop("缺少已读组元数据：%s" % key)
        files = grp.get("files") or []
        if len(files) != 8:
            raise E0CStop("组 %s 的文件数 %d≠8" % (key, len(files)))
        for f in files:
            rows.append(
                {
                    "rel_path": "%s/%s/%s" % (DATA_REL_PREFIX, key, f["file"]),
                    "size_bytes": int(f["size_bytes"]),
                    "sha256": str(f["sha256"]),
                }
            )
    if len(rows) != 96:
        raise E0CStop("inputs 数量 %d≠96" % len(rows))
    return rows


def build_groups(
    cases: Sequence[Dict[str, Any]],
    data_groups: Sequence[Dict[str, Any]],
    gates_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """E0-PREREG-3 §2.2 的 ``groups[12]``。空场组只填通道/有限性，指标为 null。"""
    by_case = {c["group_key"]: c for c in cases}
    meta = {g["group_key"]: g for g in data_groups}
    groups: List[Dict[str, Any]] = []
    for key in AIR_GROUPS:
        m = meta.get(key) or {}
        groups.append(
            {
                "group_key": key,
                "target_type": "air",
                "split": "air",
                "d_true_cm": None,
                "d_hat_m": None,
                "abs_err_cm": None,
                "supp_dw_win_db": None,
                "pslr_db": None,
                "pnr_db": None,
                "echo_ret_db": None,
                "valid_rx": int(m.get("valid_rx", 0)),
                "finite": True,
                "status": "eligible",
                "gate_results": {},
                "stop_reason": None,
            }
        )
    for spec in TARGET_SPECS:
        key = str(spec["group"])
        case = by_case.get(key)
        if case is None:
            raise E0CStop("缺少目标组结果：%s" % key)
        gate_detail = case["gate_results"]
        named = {
            "pslr_ge_3db": bool(gate_detail["pslr_db"]["passed"]),
            "pnr_ge_6db": bool(gate_detail["pnr_db"]["passed"]),
            "abs_err_eligible": bool(gate_detail["abs_err_cm"]["passed"]),
            "abs_err_not_hard": bool(
                float(case["abs_err_cm"])
                <= float(gates_cfg["cal_pilot_hard_stop_range_err_cm"])
            ),
            "detail": gate_detail,
        }
        failed = [
            name for name, gate in gate_detail.items() if gate.get("status") == "failed"
        ]
        groups.append(
            {
                "group_key": key,
                "target_type": str(case["target_type"]),
                "split": case.get("in_split"),
                "d_true_cm": float(case["d_true_cm_nominal"]),
                "d_hat_m": float(case["d_hat_m"]),
                "abs_err_cm": float(case["abs_err_cm"]),
                "supp_dw_win_db": float(case["supp_dw_win_db"]),
                "pslr_db": float(case["pslr_db"]),
                "pnr_db": float(case["pnr_db"]),
                "echo_ret_db": float(case["echo_ret_db"]),
                "valid_rx": int(case["valid_rx"]),
                "finite": bool(case["finite"]),
                "status": str(case["freeze_status"]),
                "gate_results": named,
                "stop_reason": (", ".join(failed) or None)
                if case["freeze_status"] != "eligible"
                else None,
            }
        )
    return groups


def assemble_results(
    ctx: Dict[str, Any],
    cfg: Dict[str, Any],
    config_path: Path,
    repo: Path,
    approval_ref: str,
    implementation_sha: Optional[str],
    parent_commit: Optional[str],
    main_commit: Optional[str],
    branch: Optional[str],
    command: str,
    elapsed: float,
    peak: Optional[float],
    out_dir: Path,
) -> Dict[str, Any]:
    """组装 E0-PREREG-3 §2.2 的 ``e0c_results.json``（数组与文件摘要稍后补）。"""
    e0s_path = repo / E0S_RESULTS_REL
    freeze = dict(ctx.get("freeze") or {})
    stop_reasons = [str(s) for s in (ctx.get("stop_reasons") or [])]
    data_groups = list((ctx.get("data") or {}).get("groups") or [])
    cases = list(ctx.get("cases") or [])

    partial = len(data_groups) != 12 or len(cases) != 2
    if partial:
        # 硬停止/异常路径也保留可追溯的结果骨架；此时不由 C3/C7-C11 判通过。
        groups: List[Dict[str, Any]] = []
        inputs: List[Dict[str, Any]] = []
    else:
        groups = build_groups(cases, data_groups, cfg["gates_and_thresholds"])
        inputs = collect_inputs(data_groups)

    config_sha = lf_sha256(config_path)
    plan_sha = lf_sha256(repo / "experiments/A/A-Q1-E0/PLAN.md")
    split_sha = lf_sha256(repo / "coordination/A_Q1_SPLIT.json")
    e0s_sha = lf_sha256(e0s_path) if e0s_path.is_file() else None

    env = environment_info()
    result: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "experiment_id": "A-Q1-E0",
        "phase": "E0-C",
        "scope": (
            "真实校准组（10 空场 + 2 已披露校准目标），非盲测，不含 E0-T；"
            "标称距离仅用于事后评价与 PLAN §3.3 的 eta_wall 校准组筛选"
        ),
        "generated_at": now_iso(),
        "approval_ref": approval_ref,
        "implementation_sha": implementation_sha,
        "parent_commit": parent_commit,
        "main_commit": main_commit,
        "branch": branch,
        "output_dir": str(out_dir),
        "config_sha256": config_sha,
        "config_sha256_match": config_sha == PF.APPROVED_ANCHORS["config_sha256_lf"],
        "plan_sha256": plan_sha,
        "plan_sha256_match": plan_sha == PF.APPROVED_ANCHORS["plan_sha256"],
        "split_sha256": split_sha,
        "split_sha256_match": split_sha == PF.APPROVED_ANCHORS["split_sha256_lf"],
        "e0_s_results_sha256": e0s_sha,
        "e0_s_results_sha256_match": e0s_sha
        == "171f55f75e464d289815af7352fb6fcb6635b8d73db97b3af2dcbb687eab3fdf",
        "fold_gate_contract_version": getattr(D1, "CONTRACT_VERSION", None),
        "environment": env,
        "command": command,
        "resource": {
            "wall_time_s": round(float(elapsed), 3),
            "peak_rss_mib": peak,
            "single_process": True,
            "budget": {
                "max_wall_time_sec": cfg["resource_budget"]["max_wall_time_sec"],
                "max_peak_rss_mib": cfg["resource_budget"]["max_peak_rss_mib"],
            },
        },
        "methods": {
            "alpha_mode": "fixed_1.0",
            "n0_improvements_enabled": False,
            "adaptive_alpha": False,
            "subspace_suppression": False,
            "wls_ranging": False,
            "nonuniform_channel_weights": False,
        },
        "inputs": inputs,
        "air_loo_folds": list(AIR_GROUPS),
        "array_map": {
            "air_loo_prefix": AIR_LOO_PREFIX,
            "group_prefix": {
                str(spec["group"]): str(spec["array_prefix"]) for spec in TARGET_SPECS
            },
        },
        "lambda_selected": [
            float(freeze.get("lambda_cal")),
            float(freeze.get("lambda_inv")),
        ]
        if freeze.get("lambda_cal") is not None
        else None,
        "eta_wall": freeze.get("eta_wall"),
        "freeze": {
            "status": freeze.get("status"),
            "eligible": bool(freeze.get("status") == "eligible"),
            "written": False,
            "lambda_cal": freeze.get("lambda_cal"),
            "lambda_inv": freeze.get("lambda_inv"),
            "eta_wall": freeze.get("eta_wall"),
            "eta_selection_rule": freeze.get("eta_selection_rule"),
            "reasons": list(stop_reasons),
        },
        "groups": groups,
        "metrics_sha256": metrics_digest(groups),
        "d_true_usage": "evaluation_only",
        "d_true_usage_note": (
            "标称距离只进入 abs_err 与 PLAN §3.3 的 eta_wall 校准组筛选；"
            "不参与 lambda 选参、DW 减除或统计量计算"
        ),
        "stop_reason": ("; ".join(stop_reasons) if stop_reasons else None),
        "hard_stops": [str(s) for s in (ctx.get("hard_stops") or [])],
        "gray_reasons": [str(s) for s in (ctx.get("gray_reasons") or [])],
        "stop_reasons": stop_reasons,
        "air_loo_eligibility": ctx.get("air_loo_eligibility"),
        "lambda_loo": ctx.get("lambda_loo"),
        "air_loo_raw": ctx.get("air_loo_raw"),
        "cal": ctx.get("cal"),
        "cases": cases,
        "preflight": ctx.get("preflight"),
        "data": ctx.get("data"),
        "partial": bool(partial),
    }
    return result


def write_outputs(
    out_dir: Path,
    result: Dict[str, Any],
    arrays: Optional[Dict[str, np.ndarray]],
    log: List[str],
    c0: float = 299792458.0,
) -> Dict[str, str]:
    """落盘**单次运行**的产物；返回 SHA256SUMS 的映射。

    顺序：数组（确定性 npz）→ ``e0c_air_loo.json`` → 冻结文件 → ``run.log``
    → ``files_sha256`` → ``e0c_results.json`` → ``SHA256SUMS.txt``。
    C12 的两次独立运行汇总**不在这里**：由 ``run_two_independent_runs`` 在两次
    worker 结束后写 ``e0c_repeat.json`` 并回填顶层 ``repeat_run`` 摘要。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sums: Dict[str, str] = {}

    if arrays:
        verify_delivery_metrics(result, arrays, c0=c0)
        npz_path = out_dir / "e0c_arrays.npz"
        save_npz_deterministic(npz_path, arrays)
        sha = file_sha256(npz_path)
        result["arrays_file"] = npz_path.name
        result["arrays_sha256"] = sha
        result["arrays_file_sha256"] = sha
        sums[npz_path.name] = sha

    loo = result.get("lambda_loo")
    if loo:
        loo_path = out_dir / "e0c_air_loo.json"
        write_json(loo_path, loo)
        result["air_loo_file"] = loo_path.name
        result["air_loo_file_sha256"] = file_sha256(loo_path)
        sums[loo_path.name] = result["air_loo_file_sha256"]

    freeze = result.get("freeze") or {}
    if freeze.get("eligible"):
        frozen = {
            "contract_version": CONTRACT_VERSION,
            "experiment_id": "A-Q1-E0",
            "phase": "E0-Freeze",
            "frozen_at_utc": now_iso(),
            "lambdas": [
                result["freeze"]["lambda_cal"],
                result["freeze"]["lambda_inv"],
            ],
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
        result["freeze"]["written"] = True

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
def _print_exec_summary(result: Dict[str, Any]) -> None:
    freeze = result.get("freeze") or {}
    print(
        json.dumps(
            json_safe(
                {
                    "phase": "E0-C",
                    "freeze_status": freeze.get("status"),
                    "freeze_eligible": bool(freeze.get("eligible")),
                    "air_loo_eligibility": result.get("air_loo_eligibility"),
                    "repeat_runs": (result.get("repeat_run") or {}).get("n_runs"),
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
                }
            ),
            ensure_ascii=False,
        )
    )


def _worker_argv(
    repo: Path,
    config_path: Path,
    data_root: Path,
    manifest_path: Path,
    approval_ref: str,
    implementation_sha: Optional[str],
    parent_commit: Optional[str],
    main_commit: Optional[str],
    eta_wall: Optional[float],
    overwrite: bool,
) -> List[str]:
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--mode",
        "execute-worker",
        "--repo",
        str(repo),
        "--config",
        str(config_path),
        "--data-root",
        str(data_root),
        "--manifest",
        str(manifest_path),
        "--approval-ref",
        approval_ref,
    ]
    if implementation_sha:
        argv += ["--implementation-sha", str(implementation_sha)]
    if parent_commit:
        argv += ["--parent-commit", str(parent_commit)]
    if main_commit:
        argv += ["--main-commit", str(main_commit)]
    if eta_wall is not None:
        argv += ["--eta-wall", str(eta_wall)]
    if overwrite:
        argv.append("--overwrite")
    return argv


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
        choices=("check", "execute", "execute-worker"),
        default="check",
        help=(
            "check=放行前自检（不打开 .dat）；execute=两次独立进程正式执行"
            "（需 --approval-ref）；execute-worker=内部单次运行（由 execute 派生）"
        ),
    )
    parser.add_argument("--approval-ref", default=None, help="统筹放行消息编号/链接（execute 必填）")
    parser.add_argument("--runtime-sha", default=None, help="实现提交 SHA（写入结果）")
    parser.add_argument("--implementation-sha", default=None, help="同 --runtime-sha，保留兼容")
    parser.add_argument("--parent-commit", default=None, help="实现提交的父提交")
    parser.add_argument("--main-commit", default=None, help="运行时 origin/main")
    parser.add_argument("--eta-wall", type=float, default=None, help="覆盖墙体首峰门限（默认取 config）")
    parser.add_argument(
        "--repeat-runs",
        type=int,
        default=REPEAT_RUNS_DEFAULT,
        help="execute 的独立进程重跑次数（C12 冻结契约为 2）",
    )
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

    if not args.approval_ref or not str(args.approval_ref).strip():
        print(
            "拒绝执行：--mode %s 必须带 --approval-ref（统筹放行编号/链接）。"
            "E0-C 未放行时请用默认 --mode check。" % args.mode,
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

    approval = str(args.approval_ref).strip()
    if args.mode == "execute-worker":
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            out = execute_single_delivery(
                repo,
                data_root,
                manifest_path,
                config_path,
                cfg,
                setup,
                approval,
                args.eta_wall,
                out_dir,
                args.implementation_sha or args.runtime_sha,
                args.parent_commit,
                args.main_commit,
                " ".join(sys.argv),
                log,
            )
        except E0CStop as exc:
            (out_dir / "run_error.log").write_text(
                "E0CStop during execute-worker: %s\n" % exc, encoding="utf-8"
            )
            print("单次运行失败：%s" % exc, file=sys.stderr)
            return 3
        _print_exec_summary(out["result"])
        status = out["freeze_status"]
        return 0 if status == "eligible" else (3 if status == "hard_stop" else 1)

    # -- mode execute：两个独立进程顺序运行，汇总 C12 证据 ----------------- #
    if int(args.repeat_runs) != REPEAT_RUNS_DEFAULT:
        print(
            "拒绝执行：E0-C-C12-REPEAT-1 冻结契约为两次独立进程运行；"
            "--repeat-runs 必须等于 %d，当前 %d。"
            % (REPEAT_RUNS_DEFAULT, int(args.repeat_runs)),
            file=sys.stderr,
        )
        return 2
    second_dir = out_dir / REPEAT_DIR_NAME / "run-2"
    if second_dir.exists() and any(second_dir.iterdir()):
        print(
            "拒绝执行：%s 已存在旧证据；请换新输出目录（不覆盖已登记证据）。"
            % second_dir,
            file=sys.stderr,
        )
        return 2

    prov = E0S.git_info(repo)
    implementation_sha = args.implementation_sha or args.runtime_sha or prov.get("head_sha")
    parent_commit = args.parent_commit or prov.get("parent_sha")
    main_commit = args.main_commit or prov.get("origin_main_sha")
    worker = _worker_argv(
        repo,
        config_path,
        data_root,
        manifest_path,
        approval,
        implementation_sha,
        parent_commit,
        main_commit,
        args.eta_wall,
        bool(args.overwrite),
    )
    command = (
        "python solutions/A/a_e0_c.py --mode execute --approval-ref %s "
        "--repeat-runs %d --out %s"
        % (approval, int(args.repeat_runs), args.out)
    )
    try:
        out = run_two_independent_runs(worker, out_dir, log, command)
    except E0CStop as exc:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "run_error.log").write_text(
            "E0CStop during execute: %s\n" % exc, encoding="utf-8"
        )
        (out_dir / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        print("E0-C 两次独立运行失败：%s" % exc, file=sys.stderr)
        return 3

    result = out["result"]
    _print_exec_summary(result)
    status = out["freeze_status"]
    return 0 if status == "eligible" else (3 if status == "hard_stop" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
