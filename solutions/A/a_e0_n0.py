#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1-N0 秩 2 空场子空间（``M0-DW-Subspace``）**合成原型**，契约 ``N0-SYN-1``。

本模块只做一件事：把 `coordination/A_Q1_N0_PROPOSAL.md`（`A-Q1-N0-DEC-2`，head
`4904bc8`）里已经写死的判定口径**变成可执行、可复跑、可自检的代码**，并在**纯合成夹具**
上跑通 P1/P2/P3/P4/P5a 与 L1/L2 判定逻辑，用于在统筹放行 ``N0`` 实测（B-02）之前
把三处最容易做错的口径固定下来：

1. **分簇与训练范围**（§1）：五折跨簇的折分配是**常量**（`b63e217#cal.shifts_s`
   已识别的 5 个两元素采集簇），模板池只能取其余 4 簇 8 组；**不**按 N0 自己的
   `shifts_s` 重新分簇，**不**做秩/窗/λ 搜索。
2. **跨频相位对齐**（§2）：逐频点 SVD 得到的第二模态 `D_1(f)` 有任意相位；必须以
   参考通道为相位锚（``phase_anchor = ref_channel``）把它接成一条**跨频相干波形**，
   否则延迟域投影 `z_D1(τ)` 会散开、拟合拿不到增益。
3. **近零内积处理**（§3）：`D_1` 与 `T` 在通道域做 Gram-Schmidt 正交化；正交化后
   残差相对范数 `< 1e-9`（即 `D_1` 几乎与 `T` 平行）时判 ``near_parallel`` 退化，
   退回秩 1 并显式标记，**不**对近零范数做除法；拟合的 2×2 Gram 矩阵在近奇异时
   加相对岭并标记 ``regularized``；第二模态能量占比 `< 1e-6` 时判 ``second_mode_unused``。

硬边界
------
* **合成专用**：不打开任何 ``.dat``、不读 ``附件``、不读 ``E0-T`` 两组、不读 18 组留出样；
  入口只有 ``--mode synthetic`` 与只读的 ``--mode check``，没有 ``execute``。
* **不可引用**：产物一律带 ``synthetic=true`` / ``citable=false`` /
  ``may_enter_paper_numbers=false`` / ``may_be_used_for_e0t=false``。
* **不改数值内核**：只 import 已验收原语（``a_e0_s1s2`` 的合成/校准/压缩，
  ``a_e0_c`` 的 ``bg_from_z`` / ``supp_from_z`` 风格窗口、``select_d_hat`` /
  ``pslr_from_p`` / ``pnr_from_z``），不修改它们。
* ``L1 PASS`` 不等于可冻结：``L2`` 还要求 C9b 绝对目标门、无灰区、``freeze.status``
  与 frozen 文件；本原型因无真实冻结证据，``L2`` 必然 FAIL（即提案 §6 的 ``S8``）。

用法::

    python solutions/A/a_e0_n0.py --mode check
    python solutions/A/a_e0_n0.py --mode synthetic --out experiments/A/A-Q1-E0/n0/synthetic

退出码
------
``0`` 判定链条跑通（合成夹具；不等于任何真实结论）
``2`` 用法错误
``3`` 守卫拒绝（非合成输入 / 折分配被改 / 秩≠2 / 近零内积退化 / 证据不一致）
"""

from __future__ import annotations

import os

for _thread_env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_env] = "1"

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a_e0_c as A  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402

CONTRACT_VERSION = "N0-SYN-1"
DECISION_VERSION = "A-Q1-N0-DEC-2"
PROPOSAL_HEAD = "4904bc8"

#: 秩固定为 2（提案 §3）；不做秩网格搜索。
N0_RANK = 2
#: 三个对照臂：c0=单秩、a≡1；c1=单秩窗内拟合；c2=秩 2 窗内拟合。
N0_ARMS: Tuple[str, ...] = ("c0", "c1", "c2")
N0_GRID_SEARCH = False
LAMBDA_FIXED: Tuple[float, float] = (1e-3, 1e-3)
ETA_WALL = 0.25
FIT_WINDOW_NS = 1.0
REF_POS = A._REF_POS

#: `b63e217#cal.shifts_s`（只读归档；这里只登记，不重新估计）。
BASELINE_SHIFTS_S: Tuple[float, ...] = (
    0.0,
    1.475e-11,
    2.119730e-07,
    2.1197275e-07,
    7.2326425e-07,
    7.2326350e-07,
    3.4013875e-07,
    3.4013750e-07,
    6.2538425e-07,
    6.2538375e-07,
)
#: 偏移容差 0.1 ns：超出即按 S5「边界变化」停，不改折。
SHIFT_TOL_NS = 0.1

AIR_GROUPS: Tuple[str, ...] = tuple("空场数据/data%d" % i for i in range(1, 11))
#: 五折跨簇：固定配对（提案 §5.1），不按数据重新分簇。
CLUSTERS: Tuple[Tuple[str, str], ...] = (
    ("空场数据/data1", "空场数据/data2"),
    ("空场数据/data3", "空场数据/data4"),
    ("空场数据/data5", "空场数据/data6"),
    ("空场数据/data7", "空场数据/data8"),
    ("空场数据/data9", "空场数据/data10"),
)
#: N0 明确禁止触碰的 E0-T 留出组（只用于守卫拒绝）。
E0T_GROUPS: Tuple[str, ...] = (
    "墙体数据/data20-73cm",
    "金属板数据/data5-60cm",
)
TARGET_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "case_id": "N0-SYN/Wall-42cm",
        "group": "墙体数据/data1-42cm",
        "target_type": "wall",
        "peak_rule": "wall",
        "d_true_cm": 42.0,
        "cluster": 0,
    },
    {
        "case_id": "N0-SYN/Metal-69cm",
        "group": "金属板数据/data1-69cm",
        "target_type": "metal",
        "peak_rule": "metal",
        "d_true_cm": 69.0,
        "cluster": 1,
    },
)

#: 提案 §5.1 的 P1/P2 三档阈值（dB）。
P1_HARD_STOP_DB = 6.0
P1_MAIN_TARGET_DB = 10.0
#: 提案 §5.2 的 C9b 绝对门。
C9B_PSLR_DB = 3.0
C9B_PNR_DB = 6.0
C9B_ABS_ERR_CM = 5.0
GRAY_ABS_ERR_CM = 10.71
#: P3 单侧非退化容差（提案 §5.1）。
P3_SLACK_DB = 0.05
P3_SLACK_CM = 0.05
#: 近零内积 / Gram 守卫。
NEAR_ZERO_MODE_REL = 1e-9
MIN_SECOND_MODE_ENERGY = 1e-6
GRAM_COND_MAX = 1e12

#: `b63e217` 目标侧标称锚点（只读；P3 的「不退化」参照，不是独立真值认证）。
BASELINE_P3_ANCHOR: Dict[str, Dict[str, float]] = {
    "墙体数据/data1-42cm": {
        "pslr_db": 2.6643,
        "pnr_db": 34.293809,
        "abs_err_cm": 6.18,
        "d_hat_m": 0.4818,
    },
    "金属板数据/data1-69cm": {
        "pslr_db": 4.1726,
        "pnr_db": 35.4293,
        "abs_err_cm": 4.37,
        "d_hat_m": 0.7337,
    },
}

CONFIG_PATH = A.CONFIG_PATH
DEFAULT_OUT = HERE.parents[1] / "experiments" / "A" / "A-Q1-E0" / "n0" / "synthetic"
TMP_ROOT = HERE.parents[1] / "tmp"


class N0Stop(RuntimeError):
    """守卫拒绝 / 硬停：触发后不自动重跑，保留证据。"""

    def __init__(self, code: str, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__("%s: %s" % (code, reason))
        self.code = code
        self.reason = reason
        self.detail = detail or {}


# --------------------------------------------------------------------------
# 守卫：合成专用 / 折分配锁定 / 秩锁定
# --------------------------------------------------------------------------
def assert_synthetic_only(path: Any) -> None:
    """拒绝任何真实数据路径（``附件`` / ``.dat`` / E0-T 组名）进入原型。"""
    text = str(path)
    lowered = text.lower()
    if "附件" in text or "e0-t" in lowered or "e0_t" in lowered:
        raise N0Stop("S5", "原型禁止读真实数据路径：%s" % text)
    if lowered.endswith(".dat") or ".dat" in lowered:
        raise N0Stop("S5", "原型禁止打开 .dat：%s" % text)
    p = Path(text)
    if p.is_dir():
        for child in p.rglob("*.dat"):
            raise N0Stop("S5", "目录内出现 .dat：%s" % child)
    for group in E0T_GROUPS:
        if group in text:
            raise N0Stop("S5", "原型禁止触碰 E0-T 组：%s" % group)


def assert_rank(rank: int) -> int:
    rank = int(rank)
    if rank != N0_RANK:
        raise N0Stop("S7", "N0 秩固定为 %d，不做秩搜索（收到 %r）" % (N0_RANK, rank))
    return rank


def assert_arm(arm: str) -> str:
    if arm not in N0_ARMS:
        raise N0Stop("S7", "未登记的臂 %r（只允许 %r）" % (arm, N0_ARMS))
    return arm


def assert_fold_lock(
    shifts_s: Sequence[float],
    clusters: Sequence[Sequence[str]] = CLUSTERS,
    tol_ns: float = SHIFT_TOL_NS,
) -> Dict[str, Any]:
    """锁定分簇：校验 10 组偏移落在 `b63e217` 登记的 5 簇内（容差 0.1 ns）。

    只做**校验**，不提供「用数据重新分簇」的入口——分簇是常量，看到结果后改折即 S5。
    """
    shifts = np.asarray(shifts_s, dtype=np.float64)
    if shifts.shape != (len(AIR_GROUPS),):
        raise N0Stop("S5", "偏移数量 %r ≠ 10" % (shifts.shape,))
    if len(clusters) != 5 or any(len(c) != 2 for c in clusters):
        raise N0Stop("S5", "折分配必须是 5 个两元素簇")
    flat = [g for c in clusters for g in c]
    if sorted(flat) != sorted(AIR_GROUPS):
        raise N0Stop("S5", "折分配未覆盖 10 组空场或不互斥")
    base = np.asarray(BASELINE_SHIFTS_S, dtype=np.float64)
    dev_ns = np.abs(shifts - base) * 1e9
    worst = float(np.max(dev_ns))
    if worst > float(tol_ns):
        raise N0Stop(
            "S5",
            "偏移与 b63e217 登记不符：max|Δ|=%.3f ns > %.3f ns（改折须交统筹）"
            % (worst, tol_ns),
            {"max_dev_ns": worst, "tol_ns": float(tol_ns)},
        )
    # 簇内偏移必须同簇、簇间必须分开，否则说明分簇与偏移不再自洽。
    spread = []
    for c in clusters:
        idx = [AIR_GROUPS.index(g) for g in c]
        spread.append(float(np.max(np.abs(shifts[idx] - base[idx]))) * 1e9)
    return {
        "shifts_s": [float(v) for v in shifts],
        "baseline_shifts_s": list(BASELINE_SHIFTS_S),
        "max_dev_ns": worst,
        "tol_ns": float(tol_ns),
        "cluster_index": [[AIR_GROUPS.index(g) for g in c] for c in clusters],
        "within_cluster_dev_ns": spread,
    }


# --------------------------------------------------------------------------
# 合成夹具（纯内存；seed 固定；不读任何文件）
# --------------------------------------------------------------------------
SYNTH_SEED = 20261128


def _smooth_channel_pattern(n_ch: int, order: float, phase: float) -> np.ndarray:
    idx = np.arange(n_ch, dtype=np.float64)
    return np.cos(2.0 * np.pi * order * idx / n_ch + phase)


def _shift_for(index: int) -> float:
    """组序号 → 采集偏移：0..9 直接用 `b63e217` 登记值；目标组借用所属簇值。"""
    if index < len(BASELINE_SHIFTS_S):
        return float(BASELINE_SHIFTS_S[index])
    return float(BASELINE_SHIFTS_S[2 * (index - len(BASELINE_SHIFTS_S))])


def generate_synthetic_pool(
    setup: "E0S.Setup",
    seed: int = SYNTH_SEED,
    *,
    cluster_scale: float = 0.30,
    second_scale: float = 0.05,
    amp_jitter: float = 0.05,
    phase_jitter_rad: float = 0.15,
    noise_rel_db: float = -60.0,
) -> Dict[str, Any]:
    """生成 10 组空场 + 2 组目标的合成观测（accepted forward model）。

    直接复用 ``E0S.synth_group_spectrum``（直射波 + 1/R 目标回波）与
    ``E0S.calibrate_air``（固定 λ=(1e-3,1e-3)）。批量差异按提案 §2 的“五簇、簇内
    形状相关高”构造：**第一模态在通道形状上跨簇相同、只在簇复系数上不同**
    （所以秩 2 能精确表示），第二模态逐簇不同（所以秩 2 也不会完美，能区分 c1/c2）。
    """
    setup_checked = setup
    r_dir = setup_checked.r_dir_all[setup_checked.rx63]
    tau_dir = setup_checked.tau_dir_all[setup_checked.rx63]
    f_r = setup_checked.f_r
    f_d = setup_checked.f_d
    rng = np.random.default_rng(int(seed))

    h_rel = np.ones((r_dir.size, f_d.size), dtype=np.complex128)
    h_rel *= E0S.planted_h_ref(f_d, f_r)[None, :]
    h_rel[5] *= 1.20 * np.exp(1j * 0.70)
    h_rel[40] *= 0.80 * np.exp(-1j * 1.10)

    n_ch = int(r_dir.size)
    mode1 = _smooth_channel_pattern(n_ch, 1.5, 0.7) + 0.5 * _smooth_channel_pattern(
        n_ch, 4.0, -0.3
    )
    mode1 = mode1 / float(np.max(np.abs(mode1)))
    cluster_coeff = []
    for k in range(5):
        # 五个采集簇的差异必须是“真的差异”：幅相都跨 ~1（诊断 §3 的簇间偏差）。
        mag = float(rng.uniform(0.6, 1.4))
        phase = float(rng.uniform(-np.pi, np.pi))
        cluster_coeff.append(mag * np.exp(1j * phase))

    n_draw = len(AIR_GROUPS) + len(TARGET_SPECS)
    amps = 1.0 + amp_jitter * rng.standard_normal(n_draw)
    phases = phase_jitter_rad * rng.standard_normal(n_draw)
    noise_sigma = float(np.sqrt(np.mean(np.abs(h_rel) ** 2))) * float(
        10.0 ** (noise_rel_db / 20.0)
    )

    def _apply(received: np.ndarray, g: int, k: int) -> np.ndarray:
        x = received * (amps[g] * np.exp(1j * phases[g]))
        x = x * np.exp(-1j * 2.0 * np.pi * f_r * _shift_for(g))[None, :]
        mode2 = _smooth_channel_pattern(n_ch, 2.5 + 0.4 * k, 1.1 * k)
        u2 = np.exp(1j * (0.3 + 0.9 * k))
        x = x * (
            1.0
            + cluster_scale * cluster_coeff[k] * mode1[:, None]
            + second_scale * u2 * mode2[:, None]
        )
        x = x + noise_sigma * (
            rng.standard_normal(x.shape) + 1j * rng.standard_normal(x.shape)
        ) / np.sqrt(2.0)
        return x

    air: List[np.ndarray] = []
    for g in range(10):
        k = g // 2
        base = E0S.synth_group_spectrum(
            h_rel, setup_checked.s_band, r_dir, tau_dir, f_r, setup_checked.c0
        )
        air.append(_apply(base, g, k))

    targets: Dict[str, Dict[str, Any]] = {}
    for spec in TARGET_SPECS:
        k = int(spec["cluster"])
        g_index = 10 + k
        base = E0S.synth_group_spectrum(
            h_rel,
            setup_checked.s_band,
            r_dir,
            tau_dir,
            f_r,
            setup_checked.c0,
            d_true=float(spec["d_true_cm"]) * 1e-2,
            gamma=1.0,
        )
        x = _apply(base, g_index, k)
        targets[str(spec["group"])] = {
            "spec": dict(spec),
            "x": x,
            "cluster": k,
        }

    return {
        "seed": int(seed),
        "air": air,
        "targets": targets,
        "h_rel": h_rel,
        "shifts_s": [
            float(_shift_for(i))
            for i in range(len(AIR_GROUPS) + len(TARGET_SPECS))
        ],
        "cluster_coeff": [complex(v) for v in cluster_coeff],
        "params": {
            "cluster_scale": float(cluster_scale),
            "second_scale": float(second_scale),
            "amp_jitter": float(amp_jitter),
            "phase_jitter_rad": float(phase_jitter_rad),
            "noise_rel_db": float(noise_rel_db),
            "noise_sigma": noise_sigma,
            "forward_model": "E0S.synth_group_spectrum",
            "calibration": "E0S.calibrate_air(lambda_cal=1e-3, lambda_inv=1e-3)",
        },
    }


def calibrate_pool(
    air: Sequence[np.ndarray], setup: "E0S.Setup"
) -> Dict[str, Any]:
    """固定 λ 的空场校准（不选参、不做 λ 网格）。"""
    lam_cal, lam_inv = LAMBDA_FIXED
    cal = E0S.calibrate_air(
        list(air),
        REF_POS,
        setup.r_dir_all[setup.rx63],
        setup.tau_dir_all[setup.rx63],
        setup.f_r,
        setup.band_idx,
        setup.np_n,
        setup.ts,
        setup.tp,
        lam_cal=float(lam_cal),
        lam_inv=float(lam_inv),
    )
    return cal


def align_spectra(x: np.ndarray, shift_s: float, f_r: np.ndarray) -> np.ndarray:
    """按 `b63e217` 登记的组偏移做跨组相位对齐（线性相位 = 纯延迟）。"""
    return x * np.exp(1j * 2.0 * np.pi * f_r * float(shift_s))[None, :]


# --------------------------------------------------------------------------
# 秩 2 基：T + D1（跨频相位锚 + 与 T 正交化 + 近零内积守卫）
# --------------------------------------------------------------------------
def build_rank2_basis(
    pool: np.ndarray,
    *,
    ref_pos: int = REF_POS,
    phase_anchor: str = "ref_channel",
    randomize_phase: bool = False,
    mode_form: str = "modulation",
    rng: Optional[np.random.Generator] = None,
) -> Dict[str, Any]:
    """由模板池 (G, n_ch, n_f) 造 ``T`` 与 ``D_1``，并给出退化诊断。

    * ``mode_form="modulation"``（默认）：``D_1(f) = T(f) ⊙ v(f)``，即把通道权重
      方向 ``v`` 调制到**公共波形**上，使第二模态与直射波同处一个延迟窗。合成对照
      实测：若只用单位范数的通道向量 ``D_1(f)=v(f)``（``mode_form="unit"``，字面读法），
      它在直射波窗内几乎没有能量，秩 2 退化成秩 1（c2≡c1）——见自检
      ``test_unit_mode_collapses_to_rank1``。
    * ``phase_anchor="ref_channel"``：逐频点把 ``v(f)`` 的相位旋到参考通道为实正
      （跨频相干波形）；``randomize_phase=True`` 只用于**负例测试**，模拟“逐频点相位不接”。
    * 与 ``T`` 正交化后残差相对范数 < ``NEAR_ZERO_MODE_REL`` → ``near_parallel``，
      ``rank_effective=1``，``D_1`` 记为未使用（不做近零除法）。
    """
    if mode_form not in ("modulation", "unit"):
        raise N0Stop("S7", "未登记的模态形式 %r" % (mode_form,))
    pool = np.asarray(pool, dtype=np.complex128)
    if pool.ndim != 3:
        raise N0Stop("S5", "模板池维度错误：%r" % (pool.shape,))
    n_groups, n_ch, n_f = pool.shape
    if n_groups < 2:
        raise N0Stop("S5", "模板池少于 2 组，无法估计第二模态")
    if not (0 <= int(ref_pos) < n_ch):
        raise N0Stop(
            "S5", "参考通道 %r 超出通道数 %d（相位锚非法）" % (ref_pos, n_ch)
        )
    t_mean = np.mean(pool, axis=0)
    dev = pool - t_mean[None, :, :]
    t_amp = np.abs(t_mean)
    # 相对偏差：用 **T 的复数**归一，才能把 T 自带的通道相位（含 τ_dir 斜坡）约掉；
    # 只除 |T| 会把 T 的相位二次留在模态里，z_D1 散到窗外。
    rel_dev = np.where(t_amp > 1e-300, dev / np.where(t_amp > 1e-300, t_mean, 1.0), 0.0)
    # 可识别性：把“整组复标度”方向（通道常数）从相对偏差里扣掉。它是 `a·T`
    # 已经能精确吸收的成分，若留给第二模态，SVD 会把它当第一模态，导致
    # `D_1` 只表示一个复标度、在直射波窗内没有可拟合的新方向（秩 2 退化）。
    rel_dev = rel_dev - np.mean(rel_dev, axis=1, keepdims=True)
    d1 = np.zeros((n_ch, n_f), dtype=np.complex128)
    sigma1 = np.zeros(n_f)
    sigma2 = np.zeros(n_f)
    anchor_idx = np.full(n_f, -1, dtype=np.int64)
    ortho_rel = np.zeros(n_f)
    degenerate = np.zeros(n_f, dtype=bool)
    t_norm2 = np.sum(np.abs(t_mean) ** 2, axis=0)

    for f in range(n_f):
        col_norm = float(np.linalg.norm(rel_dev[:, :, f]))
        u, s, vh = np.linalg.svd(rel_dev[:, :, f], full_matrices=False)
        sigma1[f] = float(s[0]) if s.size else 0.0
        sigma2[f] = float(s[1]) if s.size > 1 else 0.0
        if col_norm <= 1e-9 or sigma1[f] <= 1e-12 * col_norm:
            # 相对偏差矩阵整体近零（各组只差一个“整组复标度”或完全相同）：
            # 第二模态没有定义，直接判退化，不去对近零矩阵取奇异向量。
            degenerate[f] = True
            d1[:, f] = 0.0
            ortho_rel[f] = 0.0
            continue
        # rel_dev 是 (组, 通道)：右奇异向量落在通道域，才是模态权重 v(f)。
        # 约定警告（codex 2026-11-28 复核 / 回归 `N0-CHREG-1`）：numpy 的 SVD 满足
        #   A = U·S·Vh  ⇒  A[g, c] = Σ_k s_k u_k[g] · conj(v_k[c])，
        # 所以**"每组通道行向量"是 conj(v_k)，而 `Vh` 的行正好就是 conj(v_k)**，
        # 即行方向 = `vh[0]`。此前的 `vh[0].conj()` 把相对通道相位整体反转：
        # 对实通道方向只差全局相位（旧夹具看不出），对复方向则与真方向正交
        # （`(1, e^{2πi/3}, e^{4πi/3})/√3` 上 Σγ² = 0），行方向无法重建。
        v = vh[0].astype(np.complex128)
        v = v / max(float(np.linalg.norm(v)), 1e-300)
        if randomize_phase:
            local = np.random.default_rng(1000 + f) if rng is None else rng
            v = v * np.exp(1j * local.uniform(-np.pi, np.pi))
        else:
            if abs(v[ref_pos]) >= 1e-3 * float(np.max(np.abs(v))):
                anchor_idx[f] = ref_pos
            else:
                anchor_idx[f] = int(np.argmax(np.abs(v)))
            v = v * np.exp(-1j * np.angle(v[anchor_idx[f]]))
        # 第二模态必须与 T **同量级**：`D_1` 是“扣除公共波形后的差异模态”，
        # 若把它归一成单位范数，z_D1 会比 z_T 小十几个数量级、拟合系数不可识别。
        mode = (
            t_mean[:, f] * v
            if mode_form == "modulation"
            else v * float(np.sqrt(t_norm2[f]))
        )
        # 近零内积处理：与 T 做 Gram-Schmidt，残差近零即判退化。
        if t_norm2[f] <= 0.0:
            degenerate[f] = True
            d1[:, f] = 0.0
            ortho_rel[f] = 0.0
            continue
        mode_norm = float(np.linalg.norm(mode))
        if mode_norm <= 1e-12 * float(np.sqrt(t_norm2[f])):
            # 全组几乎相同 / 偏差只剩“整组复标度”：第二模态没有可用方向。
            degenerate[f] = True
            d1[:, f] = 0.0
            ortho_rel[f] = 0.0
            continue
        proj = np.vdot(t_mean[:, f], mode) / t_norm2[f]
        resid = mode - proj * t_mean[:, f]
        rel = float(np.linalg.norm(resid)) / max(float(np.linalg.norm(mode)), 1e-300)
        ortho_rel[f] = rel
        if rel < NEAR_ZERO_MODE_REL:
            degenerate[f] = True
            d1[:, f] = 0.0
        else:
            d1[:, f] = resid

    n_deg = int(np.count_nonzero(degenerate))
    rank_effective = 1 if n_deg == n_f else 2
    return {
        "T": t_mean,
        "D1": d1,
        "rank_requested": N0_RANK,
        "rank_effective": rank_effective,
        "phase_anchor": phase_anchor if not randomize_phase else "randomized_negative_control",
        "mode_form": mode_form,
        "ref_pos": int(ref_pos),
        "anchor_idx": anchor_idx,
        "sigma1": sigma1,
        "sigma2": sigma2,
        "ortho_residual_rel": ortho_rel,
        "degenerate_freqs": n_deg,
        "near_parallel": bool(n_deg > 0),
        "sigma1_median": float(np.median(sigma1)) if n_f else 0.0,
        "sigma2_over_sigma1_median": float(
            np.median(sigma2 / np.maximum(sigma1, 1e-300))
        )
        if n_f
        else 0.0,
    }


def _local_window_axis(
    tau_dir_s: np.ndarray, half_ns: float = 2.0, step_ns: float = 0.05
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """每通道直射波窗附近的局部 τ 轴（相对偏移，单位 s）与窗掩码。"""
    offsets = np.arange(-float(half_ns), float(half_ns) + 0.5 * step_ns, step_ns) * 1e-9
    delays = tau_dir_s[:, None] + offsets[None, :]
    mask = np.abs(offsets) <= FIT_WINDOW_NS + 1e-15
    return delays, offsets, mask


def _window_stats(
    z_x: np.ndarray,
    z_t: np.ndarray,
    z_d: np.ndarray,
    mask: np.ndarray,
) -> Dict[str, complex]:
    """窗内 LS 的充分统计量（复杂内积）。"""
    w = mask[None, :]
    xw = np.where(w, z_x, 0)
    tw = np.where(w, z_t, 0)
    dw = np.where(w, z_d, 0)
    return {
        "Exx": complex(np.sum(np.abs(xw) ** 2)),
        "A11": complex(np.sum(np.abs(tw) ** 2)),
        "A22": complex(np.sum(np.abs(dw) ** 2)),
        "A12": complex(np.vdot(tw, dw)),
        "Stx": complex(np.vdot(tw, xw)),
        "Sdx": complex(np.vdot(dw, xw)),
        "n_samples": int(np.count_nonzero(mask) * z_x.shape[0]),
    }


def solve_coefficients(
    stats: Dict[str, complex], arm: str, rank_effective: int = 2
) -> Dict[str, Any]:
    """由充分统计量解 (a, b)；近奇异 Gram 加相对岭并标记。"""
    arm = assert_arm(arm)
    if arm == "c0":
        return {
            "a": 1.0 + 0.0j,
            "b": 0.0 + 0.0j,
            "regularized": False,
            "gram_cond": 1.0,
            "second_mode_energy_fraction": 0.0,
            "second_mode_used": False,
        }
    A11 = float(stats["A11"].real)
    A22 = float(stats["A22"].real)
    A12 = complex(stats["A12"])
    Stx = complex(stats["Stx"])
    Sdx = complex(stats["Sdx"])
    if arm == "c1" or rank_effective < 2:
        a = Stx / A11 if A11 > 0.0 else 0.0 + 0.0j
        out = {
            "a": complex(a),
            "b": 0.0 + 0.0j,
            "regularized": False,
            "gram_cond": 1.0,
            "second_mode_used": False,
        }
        out["second_mode_energy_fraction"] = 0.0
        return out
    trace = A11 + A22
    reg = 0.0
    if A11 <= 0.0:
        raise N0Stop("S4", "窗内模板能量非正（A11=%.3g）" % A11)
    disc = ((A11 - A22) / 2.0) ** 2 + abs(A12) ** 2
    lam_max = trace / 2.0 + math.sqrt(max(disc, 0.0))
    lam_min = trace / 2.0 - math.sqrt(max(disc, 0.0))
    cond = lam_max / lam_min if lam_min > 0.0 else float("inf")
    regularized = False
    if not math.isfinite(cond) or cond > GRAM_COND_MAX:
        reg = trace * 1e-12
        regularized = True
        A11 += reg
        A22 += reg
        disc = ((A11 - A22) / 2.0) ** 2 + abs(A12) ** 2
        lam_max = (A11 + A22) / 2.0 + math.sqrt(max(disc, 0.0))
        lam_min = (A11 + A22) / 2.0 - math.sqrt(max(disc, 0.0))
        cond = lam_max / lam_min if lam_min > 0.0 else float("inf")
    det = A11 * A22 - abs(A12) ** 2
    if det <= 0.0:
        raise N0Stop("S4", "窗内 Gram 非正定（det=%.3g）" % det)
    a = (A22 * Stx - A12 * Sdx) / det
    b = (A11 * Sdx - np.conj(A12) * Stx) / det
    e_d = float(abs(b) ** 2) * float(stats["A22"].real)
    # 相对“秩 1 拟合后残余”的能量占比：直接回答“第二模态是否真的多扣了东西”。
    e1_resid = float(stats["Exx"].real) - float(abs(Stx) ** 2) / max(A11, 1e-300)
    frac = e_d / max(e1_resid, 1e-300) if e1_resid > 0.0 else 0.0
    return {
        "a": complex(a),
        "b": complex(b),
        "regularized": bool(regularized),
        "gram_cond": float(cond),
        "gram_ridge": float(reg),
        "second_mode_energy_fraction": float(frac),
        "second_mode_used": bool(frac >= MIN_SECOND_MODE_ENERGY),
    }


def suppression_from_stats(
    stats: Dict[str, complex], coeffs: Dict[str, Any]
) -> float:
    """由充分统计量直接算窗内 ``Supp``（与数组路径独立）。"""
    a = complex(coeffs["a"])
    b = complex(coeffs["b"])
    exx = float(stats["Exx"].real)
    a11 = float(stats["A11"].real)
    a22 = float(stats["A22"].real)
    a12 = complex(stats["A12"])
    stx = complex(stats["Stx"])
    sdx = complex(stats["Sdx"])
    e_after = (
        exx
        - 2.0 * (np.conj(a) * stx + np.conj(b) * sdx).real
        + float(abs(a) ** 2) * a11
        + float(abs(b) ** 2) * a22
        + 2.0 * (np.conj(a) * b * a12).real
    )
    if e_after <= 0.0:
        # 精确合成（无噪声）可能把残余压到浮点误差量级；只要 |残余| 远小于
        # 扣除前功率就按“可忽略”处理，而不是判证据缺陷。
        if e_after > -1e-9 * exx:
            e_after = max(exx * 1e-15, 1e-300)
        else:
            raise N0Stop("S4", "窗内残余功率非正：%.6g" % e_after)
    return 10.0 * math.log10(exx / e_after)


def suppression_from_arrays(
    z_x: np.ndarray, z_t: np.ndarray, z_d: np.ndarray, mask: np.ndarray
) -> Dict[str, Any]:
    """数组路径（``lstsq``）独立重算 (a, b) 与 Supp，用于 C8' 交叉核对。"""
    w = mask[None, :]
    x = np.where(w, z_x, 0.0).reshape(-1)
    t = np.where(w, z_t, 0.0).reshape(-1)
    d = np.where(w, z_d, 0.0).reshape(-1)
    design = np.stack([t, d], axis=1)
    coef, *_ = np.linalg.lstsq(design, x, rcond=None)
    resid = x - design @ coef
    e_before = float(np.sum(np.abs(x) ** 2))
    e_after = float(np.sum(np.abs(resid) ** 2))
    if e_after <= 0.0:
        raise N0Stop("S4", "数组路径残余功率非正")
    return {
        "a": complex(coef[0]),
        "b": complex(coef[1]),
        "supp_db": 10.0 * math.log10(e_before / e_after),
    }


def prepare_window(
    setup: "E0S.Setup", t_mean: np.ndarray, d1: np.ndarray
) -> Dict[str, Any]:
    """与“被处理的那一组”无关的窗内预计算：tpl、τ 轴、z_T、z_D1 与 Gram 对角量。"""
    r_dir = setup.r_dir_all[setup.rx63]
    tau_dir = setup.tau_dir_all[setup.rx63]
    f_r = setup.f_r
    tpl = E0S.build_s_eff(t_mean, r_dir, tau_dir, f_r)
    delays, _offsets, mask = _local_window_axis(tau_dir)
    z_t = E0S.z_at_delays(t_mean, tpl, f_r, delays)
    z_d = E0S.z_at_delays(d1, tpl, f_r, delays)
    a11 = float(np.sum(np.abs(np.where(mask[None, :], z_t, 0.0)) ** 2))
    a22 = float(np.sum(np.abs(np.where(mask[None, :], z_d, 0.0)) ** 2))
    a12 = complex(np.vdot(np.where(mask[None, :], z_t, 0.0), np.where(mask[None, :], z_d, 0.0)))
    return {
        "tpl": tpl,
        "delays": delays,
        "mask": mask,
        "z_t": z_t,
        "z_d": z_d,
        "a11": a11,
        "a22": a22,
        "a12": a12,
    }


def apply_arm(
    x_cal: np.ndarray,
    prepared: Dict[str, Any],
    t_mean: np.ndarray,
    d1: np.ndarray,
    f_r: np.ndarray,
    arm: str,
    rank_effective: int = 2,
    z_x: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """对一组（已校准）谱执行 c0/c1/c2：窗内拟合 → 扣除 → 窗内 Supp。

    ``z_x`` 可由调用方提供（同一组的三个臂共用同一次内积）。
    """
    arm = assert_arm(arm)
    mask = prepared["mask"]
    if z_x is None:
        z_x = E0S.z_at_delays(x_cal, prepared["tpl"], f_r, prepared["delays"])
    z_t, z_d = prepared["z_t"], prepared["z_d"]
    stats = _window_stats(z_x, z_t, z_d, mask)
    coeffs = solve_coefficients(stats, arm, rank_effective=rank_effective)
    supp_stats = suppression_from_stats(stats, coeffs)
    arr = suppression_from_arrays(z_x, z_t, z_d, mask)
    x_after = x_cal - complex(coeffs["a"]) * t_mean - complex(coeffs["b"]) * d1
    z_after = E0S.z_at_delays(x_after, prepared["tpl"], f_r, prepared["delays"])
    e_before = float(np.sum(np.abs(np.where(mask[None, :], z_x, 0.0)) ** 2))
    e_after = float(np.sum(np.abs(np.where(mask[None, :], z_after, 0.0)) ** 2))
    if e_after <= 0.0:
        raise N0Stop("S4", "帧内残余功率非正（数组）")
    supp_array = 10.0 * math.log10(e_before / e_after)
    return {
        "arm": arm,
        "coefficients": {
            "a": [float(coeffs["a"].real), float(coeffs["a"].imag)],
            "b": [float(coeffs["b"].real), float(coeffs["b"].imag)],
        },
        "regularized": bool(coeffs["regularized"]),
        "gram_cond": float(coeffs["gram_cond"]),
        "gram_ridge": float(coeffs.get("gram_ridge", 0.0)),
        "second_mode_energy_fraction": float(coeffs["second_mode_energy_fraction"]),
        "second_mode_used": bool(coeffs["second_mode_used"]),
        "supp_db": float(supp_stats),
        "x_after": x_after,
        "c8": {
            "stats_path_supp_db": float(supp_stats),
            "array_path_supp_db": float(supp_array),
            "array_path_coeff": [complex(arr["a"]), complex(arr["b"])],
            "delta_coeff": float(
                max(abs(complex(coeffs["a"]) - arr["a"]), abs(complex(coeffs["b"]) - arr["b"]))
            ),
            "delta_supp_db": float(abs(supp_stats - supp_array)),
        },
        "window": {
            "n_samples_per_channel": int(np.count_nonzero(mask)),
            "window_ns": float(FIT_WINDOW_NS),
            "e_before": e_before,
            "e_after_stats": float(
                stats["Exx"].real
                - 2.0
                * (
                    np.conj(coeffs["a"]) * stats["Stx"]
                    + np.conj(coeffs["b"]) * stats["Sdx"]
                ).real
                + abs(coeffs["a"]) ** 2 * stats["A11"].real
                + abs(coeffs["b"]) ** 2 * stats["A22"].real
                + 2.0 * (np.conj(coeffs["a"]) * coeffs["b"] * stats["A12"]).real
            ),
        },
    }


# --------------------------------------------------------------------------
# 目标侧：P3 / P4（复用 a_e0_c 的测距与 PSLR/PNR 原语）
# --------------------------------------------------------------------------
def evaluate_target(
    setup: "E0S.Setup",
    x_cal: np.ndarray,
    x_after: np.ndarray,
    t_mean: np.ndarray,
    d_true_cm: float,
    peak_rule: str,
    *,
    d_step_m: float = 0.001,
    p4_step_m: float = 1e-4,
    p4_half_m: float = 0.03,
    d_grid: Optional[np.ndarray] = None,
    p_before: Optional[np.ndarray] = None,
    fine_grid: Optional[np.ndarray] = None,
    p_before_fine: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """目标侧测距/PSLR/PNR/峰值保留；``d`` 单位为米、搜索区间沿用配置 ``[0.15,2.0]``。

    ``p_before``/``p_before_fine`` 与对应网格可由调用方复用（扣除前剖面与臂无关），
    避免对同一内积重复求值。
    """
    r_dir = setup.r_dir_all[setup.rx63]
    tau_dir = setup.tau_dir_all[setup.rx63]
    f_r = setup.f_r
    tpl = E0S.build_s_eff(t_mean, r_dir, tau_dir, f_r)
    if d_grid is None:
        d_grid = np.arange(setup.d_min, setup.d_max + 0.5 * d_step_m, d_step_m)
    if p_before is None:
        p_before = A.profile_fine(x_cal, tpl, r_dir, f_r, setup.c0, d_grid)
    p_after = A.profile_fine(x_after, tpl, r_dir, f_r, setup.c0, d_grid)

    tau_bg = np.arange(50.0, 950.0 + 1e-9, 2.0) * 1e-9
    z_bg = E0S.z_at_delays(x_after, tpl, f_r, np.tile(tau_bg, (x_after.shape[0], 1)))
    bg = float(np.mean(np.abs(z_bg) ** 2))
    d_hat_b, rule_b = A.select_d_hat(p_before, d_grid, peak_rule, ETA_WALL, bg)
    d_hat_a, rule_a = A.select_d_hat(p_after, d_grid, peak_rule, ETA_WALL, bg)

    pslr = A.pslr_from_p(p_after, d_grid, d_hat_a)
    tau_tgt = 2.0 * d_hat_a / setup.c0
    z_tgt = E0S.z_at_delays(
        x_after, tpl, f_r, np.full((x_after.shape[0], 1), tau_tgt, dtype=np.float64)
    )
    pnr = A.pnr_from_z(z_tgt, np.array([tau_tgt * 1e9]), d_hat_a, setup.c0, bg)

    d_true_m = float(d_true_cm) * 1e-2
    # P4 用**注入真值邻域的 0.1 mm 细网格**单独评：粗搜索网格（1 mm）不足以判
    # “测距偏移 ≤2 mm”，且未扣除前的主峰可能落在近场直射残余上。
    fine = fine_grid
    if fine is None:
        fine = np.arange(
            d_true_m - p4_half_m, d_true_m + p4_half_m + 0.5 * p4_step_m, p4_step_m
        )
    if p_before_fine is None:
        p_before_fine = A.profile_fine(x_cal, tpl, r_dir, f_r, setup.c0, fine)
    p_after_fine = A.profile_fine(x_after, tpl, r_dir, f_r, setup.c0, fine)
    k_fine = int(np.argmax(p_after_fine))
    peak_loss_db = 10.0 * math.log10(
        float(p_after_fine[k_fine]) / float(p_before_fine[k_fine])
    )
    range_shift_mm = float((fine[k_fine] - d_true_m) * 1000.0)
    return {
        "d_hat_m": float(d_hat_a),
        "d_hat_before_m": float(d_hat_b),
        "abs_err_cm": float(abs(d_hat_a - d_true_m) * 100.0),
        "abs_err_before_cm": float(abs(d_hat_b - d_true_m) * 100.0),
        "range_shift_mm": range_shift_mm,
        "range_shift_vs_before_mm": float((d_hat_a - d_hat_b) * 1000.0),
        "pslr_db": float(pslr),
        "peak_rule": str(rule_a),
        "pslr_before_db": float(A.pslr_from_p(p_before, d_grid, d_hat_b)),
        "pnr_db": float(pnr),
        "bg_proxy": float(bg),
        "peak_retention_db": float(peak_loss_db),
        "profile": {
            "d_step_m": float(d_step_m),
            "d_min_m": float(setup.d_min),
            "d_max_m": float(setup.d_max),
            "n": int(d_grid.size),
            "p4_step_m": float(p4_step_m),
            "p4_half_m": float(p4_half_m),
        },
    }


# --------------------------------------------------------------------------
# 判定：P1/P2 三档、P3 单侧非退化、P4、P5a、L1/L2
# --------------------------------------------------------------------------
def classify_p1(value_db: float) -> str:
    if value_db < P1_HARD_STOP_DB:
        return "hard_stop"
    if value_db < P1_MAIN_TARGET_DB:
        return "not_met"
    return "met"


def decide_l1(
    *,
    p1_min_db: float,
    p2_min_db: float,
    p2_median_db: float,
    p3_pass: bool,
    p3_items: Sequence[Dict[str, Any]],
    p4_pass: bool,
    p5a_pass: bool,
) -> Dict[str, Any]:
    """提案 §5.1 的 L1 三值判定（互斥、穷尽），P1/P2 取较低档。"""
    p1_tier = classify_p1(p1_min_db)
    p2_tier = classify_p1(p2_min_db)
    order = {"hard_stop": 0, "not_met": 1, "met": 2}
    lower = p1_tier if order[p1_tier] <= order[p2_tier] else p2_tier
    if lower == "hard_stop":
        l1 = "hard_stop"
        s = "S1"
    elif lower == "not_met":
        l1 = "not_met"
        s = "S2"
    else:
        ok = (
            p2_median_db >= P1_MAIN_TARGET_DB and p3_pass and p4_pass and p5a_pass
        )
        l1 = "pass" if ok else "not_met"
        s = "PASS" if ok else "S3/S4/S9"
    return {
        "decision_version": DECISION_VERSION,
        "p1_min_db": float(p1_min_db),
        "p1_tier": p1_tier,
        "p2_min_db": float(p2_min_db),
        "p2_tier": p2_tier,
        "p2_median_db": float(p2_median_db),
        "lower_tier": lower,
        "p3_pass": bool(p3_pass),
        "p3_items": list(p3_items),
        "p4_pass": bool(p4_pass),
        "p5a_pass": bool(p5a_pass),
        "l1": l1,
        "s_code": s,
    }


def decide_l2(
    *,
    l1: Dict[str, Any],
    p5a_pass: bool,
    c9b: Dict[str, Any],
    gray_targets: Sequence[str],
    freeze_status: str,
    frozen_present: bool,
) -> Dict[str, Any]:
    """提案 §5.2 的 L2：L1 + P5a + C9b 绝对门 + 无灰区 + frozen 证据。"""
    reasons: List[str] = []
    if l1["l1"] != "pass":
        reasons.append("L1=%s（非 PASS）" % l1["l1"])
    if not p5a_pass:
        reasons.append("P5a 未全 PASS")
    if not c9b.get("pass", False):
        reasons.append("C9b 绝对目标门未全 PASS：%s" % c9b.get("failed", []))
    if gray_targets:
        reasons.append("灰区目标：%s（5.0 < abs_err ≤ 10.71 cm）" % list(gray_targets))
    if freeze_status != "eligible":
        reasons.append("freeze.status=%r ≠ eligible" % freeze_status)
    if not frozen_present:
        reasons.append("e0c_frozen.json 不存在")
    l2 = "pass" if not reasons else "fail"
    s_code = "PASS" if l2 == "pass" else ("S8" if l1["l1"] == "pass" else l1["s_code"])
    return {
        "l1": l1["l1"],
        "l2": l2,
        "c9b_pass": bool(c9b.get("pass", False)),
        "c9b": c9b,
        "gray_targets": list(gray_targets),
        "freeze_status": freeze_status,
        "frozen_present": bool(frozen_present),
        "reasons": reasons,
        "s_code": s_code,
        "matrix_position": (
            "L1 PASS / L2 FAIL（S8：抑制方法达标、整轮不可冻结）"
            if l1["l1"] == "pass" and l2 == "fail"
            else ("L1 PASS / L2 PASS（可写 frozen，E0-T 仍由统筹签发）"
                  if l2 == "pass"
                  else "L1 %s（不可冻结）" % l1["l1"].upper())
        ),
    }


def _p3_items(
    arm_results: Dict[str, Dict[str, Any]],
    baseline_arm: str = "c0",
) -> List[Dict[str, Any]]:
    """P3 单侧非退化：PSLR/PNR ≥ 基线−0.05 dB，abs_err ≤ 基线+0.05 cm。"""
    items: List[Dict[str, Any]] = []
    for group, res in arm_results.items():
        base = res["arms"][baseline_arm]
        for arm in ("c1", "c2"):
            cur = res["arms"][arm]
            items.append(
                {
                    "group": group,
                    "arm": arm,
                    "pslr_delta_db": float(cur["pslr_db"] - base["pslr_db"]),
                    "pnr_delta_db": float(cur["pnr_db"] - base["pnr_db"]),
                    "abs_err_delta_cm": float(cur["abs_err_cm"] - base["abs_err_cm"]),
                    "pslr_ok": bool(cur["pslr_db"] >= base["pslr_db"] - P3_SLACK_DB),
                    "pnr_ok": bool(cur["pnr_db"] >= base["pnr_db"] - P3_SLACK_DB),
                    "abs_err_ok": bool(
                        cur["abs_err_cm"] <= base["abs_err_cm"] + P3_SLACK_CM
                    ),
                }
            )
    return items


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run_synthetic(
    *,
    seed: int = SYNTH_SEED,
    d_step_m: float = 0.001,
    p4_step_m: float = 1e-4,
    p4_half_m: float = 0.03,
    setup: Optional["E0S.Setup"] = None,
) -> Dict[str, Any]:
    """跑完整合成夹具：P1 五折跨簇 / P2 十折 LOO / P3 / P4 / P5a → L1/L2。"""
    if setup is None:
        cfg = E0S.load_config(CONFIG_PATH)
        setup = E0S.Setup(cfg)
    assert_rank(N0_RANK)

    synth = generate_synthetic_pool(setup, seed=seed)
    fold_lock = assert_fold_lock(synth["shifts_s"][: len(AIR_GROUPS)])
    cal = calibrate_pool(synth["air"], setup)
    inv = cal["inv"]
    air_cal = [x * inv for x in synth["air"]]
    air_aligned = [
        align_spectra(x, s, setup.f_r)
        for x, s in zip(air_cal, synth["shifts_s"])
    ]
    stack = np.stack(air_aligned, axis=0)

    # ---- 基（全 10 组池，用于目标侧）
    basis_full = build_rank2_basis(stack)
    prepared_full = prepare_window(setup, basis_full["T"], basis_full["D1"])
    near_zero_events: List[Dict[str, Any]] = []
    if basis_full["near_parallel"]:
        near_zero_events.append(
            {"where": "full_pool", "degenerate_freqs": basis_full["degenerate_freqs"]}
        )

    # ---- P1：五折跨采集簇（留出同簇 2 组，模板 = 其余 8 组）
    p1_per_arm: Dict[str, List[Dict[str, Any]]] = {arm: [] for arm in N0_ARMS}
    p1_basis: List[Dict[str, Any]] = []
    for fold_idx, cluster in enumerate(CLUSTERS):
        held = [AIR_GROUPS.index(g) for g in cluster]
        pool = [i for i in range(10) if i not in held]
        basis = build_rank2_basis(stack[pool])
        prepared = prepare_window(setup, basis["T"], basis["D1"])
        p1_basis.append(
            {
                "fold": fold_idx,
                "held_out": list(cluster),
                "template_pool": [AIR_GROUPS[i] for i in pool],
                "rank_effective": basis["rank_effective"],
                "near_parallel": basis["near_parallel"],
                "sigma2_over_sigma1_median": basis["sigma2_over_sigma1_median"],
            }
        )
        if basis["near_parallel"]:
            near_zero_events.append(
                {"where": "p1_fold_%d" % fold_idx,
                 "degenerate_freqs": basis["degenerate_freqs"]}
            )
        for i in held:
            z_x = E0S.z_at_delays(
                stack[i], prepared["tpl"], setup.f_r, prepared["delays"]
            )
            for arm in N0_ARMS:
                res = apply_arm(
                    stack[i], prepared, basis["T"], basis["D1"], setup.f_r, arm,
                    rank_effective=basis["rank_effective"], z_x=z_x,
                )
                p1_per_arm[arm].append(
                    {
                        "group": AIR_GROUPS[i],
                        "fold": fold_idx,
                        "supp_db": res["supp_db"],
                        "second_mode_used": res["second_mode_used"],
                        "regularized": res["regularized"],
                        "c8_delta_supp_db": res["c8"]["delta_supp_db"],
                    }
                )

    # ---- P2：十折 LOO（模板 = 其余 9 组）
    p2_per_arm: Dict[str, List[Dict[str, Any]]] = {arm: [] for arm in N0_ARMS}
    for i in range(10):
        pool = [j for j in range(10) if j != i]
        basis = build_rank2_basis(stack[pool])
        prepared = prepare_window(setup, basis["T"], basis["D1"])
        if basis["near_parallel"]:
            near_zero_events.append(
                {"where": "p2_loo_%d" % i, "degenerate_freqs": basis["degenerate_freqs"]}
            )
        z_x = E0S.z_at_delays(stack[i], prepared["tpl"], setup.f_r, prepared["delays"])
        for arm in N0_ARMS:
            res = apply_arm(
                stack[i], prepared, basis["T"], basis["D1"], setup.f_r, arm,
                rank_effective=basis["rank_effective"], z_x=z_x,
            )
            p2_per_arm[arm].append(
                {
                    "group": AIR_GROUPS[i],
                    "supp_db": res["supp_db"],
                    # C8' 的双路径复算覆盖 P2 十折（不只 P1/目标侧）。
                    "c8_delta_supp_db": res["c8"]["delta_supp_db"],
                    "c8_delta_coeff": res["c8"]["delta_coeff"],
                }
            )

    p1_summary = {}
    for arm in N0_ARMS:
        vals = [v["supp_db"] for v in p1_per_arm[arm]]
        p1_summary[arm] = {
            "min_db": float(np.min(vals)),
            "median_db": float(np.median(vals)),
            "tier": classify_p1(float(np.min(vals))),
            "values": p1_per_arm[arm],
        }
    p2_summary = {}
    for arm in N0_ARMS:
        vals = [v["supp_db"] for v in p2_per_arm[arm]]
        p2_summary[arm] = {
            "min_db": float(np.min(vals)),
            "median_db": float(np.median(vals)),
            "tier": classify_p1(float(np.min(vals))),
            "values": p2_per_arm[arm],
        }

    # ---- 目标侧：c0/c1/c2（模板 = 全 10 组）
    target_results: Dict[str, Dict[str, Any]] = {}
    for group, payload in synth["targets"].items():
        spec = payload["spec"]
        x_cal = payload["x"] * inv
        x_cal = align_spectra(x_cal, synth["shifts_s"][10 + int(spec["cluster"])], setup.f_r)
        # 扣除前剖面与臂无关：算一次复用（否则 3 个臂会把同一内积重算 3 遍）。
        d_grid = np.arange(setup.d_min, setup.d_max + 0.5 * d_step_m, d_step_m)
        tpl_full = E0S.build_s_eff(
            basis_full["T"],
            setup.r_dir_all[setup.rx63],
            setup.tau_dir_all[setup.rx63],
            setup.f_r,
        )
        p_before = A.profile_fine(
            x_cal,
            tpl_full,
            setup.r_dir_all[setup.rx63],
            setup.f_r,
            setup.c0,
            d_grid,
        )
        d_true_m = float(spec["d_true_cm"]) * 1e-2
        fine_grid = np.arange(
            d_true_m - p4_half_m, d_true_m + p4_half_m + 0.5 * p4_step_m, p4_step_m
        )
        p_before_fine = A.profile_fine(
            x_cal,
            tpl_full,
            setup.r_dir_all[setup.rx63],
            setup.f_r,
            setup.c0,
            fine_grid,
        )
        arms_out: Dict[str, Any] = {}
        z_x_tgt = E0S.z_at_delays(
            x_cal, prepared_full["tpl"], setup.f_r, prepared_full["delays"]
        )
        for arm in N0_ARMS:
            res = apply_arm(
                x_cal, prepared_full, basis_full["T"], basis_full["D1"],
                setup.f_r, arm,
                rank_effective=basis_full["rank_effective"], z_x=z_x_tgt,
            )
            metrics = evaluate_target(
                setup,
                x_cal,
                res["x_after"],
                basis_full["T"],
                float(spec["d_true_cm"]),
                str(spec["peak_rule"]),
                d_step_m=d_step_m,
                p4_step_m=p4_step_m,
                p4_half_m=p4_half_m,
                d_grid=d_grid,
                p_before=p_before,
                fine_grid=fine_grid,
                p_before_fine=p_before_fine,
            )
            metrics.update(
                {
                    "supp_dw_win_db": float(res["supp_db"]),
                    "coefficients": res["coefficients"],
                    "second_mode_used": res["second_mode_used"],
                    "second_mode_energy_fraction": float(
                        res["second_mode_energy_fraction"]
                    ),
                    "regularized": res["regularized"],
                    "c8": {
                        "delta_supp_db": res["c8"]["delta_supp_db"],
                        "delta_coeff": res["c8"]["delta_coeff"],
                    },
                }
            )
            arms_out[arm] = metrics
        target_results[group] = {
            "case_id": spec["case_id"],
            "target_type": spec["target_type"],
            "d_true_cm": float(spec["d_true_cm"]),
            "arms": arms_out,
        }

    # ---- C8'：固定 λ 的 Supp 逐值复算一致性（P1 五折 + P2 十折 + 目标侧，逐值覆盖）
    c8_deltas = [v["c8_delta_supp_db"] for arm in N0_ARMS for v in p1_per_arm[arm]]
    c8_p2_deltas = [v["c8_delta_supp_db"] for arm in N0_ARMS for v in p2_per_arm[arm]]
    c8_target_deltas = [
        t["arms"][arm]["c8"]["delta_supp_db"]
        for t in target_results.values()
        for arm in N0_ARMS
    ]
    c8_deltas += c8_p2_deltas
    c8_deltas += c8_target_deltas
    c8_coeff_deltas = [
        v["c8_delta_coeff"] for arm in N0_ARMS for v in p2_per_arm[arm]
    ] + [
        t["arms"][arm]["c8"]["delta_coeff"]
        for t in target_results.values()
        for arm in N0_ARMS
    ]
    c8_max_delta = float(max(c8_deltas)) if c8_deltas else 0.0
    c8_pass = c8_max_delta <= 1e-6
    c8_coverage = {
        "p1_values": len(p1_per_arm[N0_ARMS[0]]) * len(N0_ARMS),
        "p2_values": len(c8_p2_deltas),
        "target_values": len(c8_target_deltas),
        "total_values": len(c8_deltas),
        "p2_folds_per_arm": len(p2_per_arm[N0_ARMS[0]]),
        "arms": list(N0_ARMS),
        "max_delta_coeff": float(max(c8_coeff_deltas)) if c8_coeff_deltas else 0.0,
        "coeff_note": "系数差仅作诊断（stats 路径含 λ 正则，数组路径不含），不参与 C8' 判定",
    }

    # ---- P3 单侧非退化
    p3_items = _p3_items(target_results)
    p3_pass = all(i["pslr_ok"] and i["pnr_ok"] and i["abs_err_ok"] for i in p3_items)

    # ---- P4 合成回波保留（42 cm 注入）
    wall = target_results["墙体数据/data1-42cm"]["arms"]["c2"]
    p4_items = [
        {
            "peak_retention_db": float(wall["peak_retention_db"]),
            "range_shift_mm": float(wall["range_shift_mm"]),
            "peak_ok": bool(wall["peak_retention_db"] >= -0.1),
            "shift_ok": bool(abs(wall["range_shift_mm"]) <= 2.0),
        }
    ]
    p4_pass = all(i["peak_ok"] and i["shift_ok"] for i in p4_items)

    # ---- C9b 绝对门（只进 L2）
    c9b_items = {}
    for group, res in target_results.items():
        m = res["arms"]["c2"]
        c9b_items[group] = {
            "pslr_db": float(m["pslr_db"]),
            "pnr_db": float(m["pnr_db"]),
            "abs_err_cm": float(m["abs_err_cm"]),
            "pslr_ok": bool(m["pslr_db"] >= C9B_PSLR_DB),
            "pnr_ok": bool(m["pnr_db"] >= C9B_PNR_DB),
            "abs_err_ok": bool(m["abs_err_cm"] <= C9B_ABS_ERR_CM),
        }
    c9b_failed = [
        "%s:%s" % (g, k)
        for g, item in c9b_items.items()
        for k in ("pslr_ok", "pnr_ok", "abs_err_ok")
        if not item[k]
    ]
    c9b = {"pass": not c9b_failed, "failed": c9b_failed, "items": c9b_items}
    gray_targets = [
        g
        for g, item in c9b_items.items()
        if C9B_ABS_ERR_CM < item["abs_err_cm"] <= GRAY_ABS_ERR_CM
    ]

    # ---- P5a：接口与证据链
    p5a_items = {
        "p5a_1_interfaces": {
            "rank_fixed": N0_RANK == 2,
            "arms_fixed": tuple(N0_ARMS) == ("c0", "c1", "c2"),
            "no_grid_search": not N0_GRID_SEARCH,
            "lambda_fixed": tuple(LAMBDA_FIXED) == (1e-3, 1e-3),
            "fit_window_ns": FIT_WINDOW_NS,
        },
        "p5a_2_self_consistency": {
            "c8_max_delta_db": c8_max_delta,
            "c8_pass": c8_pass,
            "fold_count": len(CLUSTERS),
            "p1_values": sum(len(v) for v in p1_per_arm.values()),
        },
        "p5a_3_freeze_integrity": {
            "frozen_written": False,
            "freeze_status": "not_eligible_for_freeze",
            "note": "合成夹具不产生任何冻结证据；L2 必 FAIL（S8）",
        },
    }
    p5a_pass = bool(
        p5a_items["p5a_1_interfaces"]["rank_fixed"]
        and p5a_items["p5a_1_interfaces"]["arms_fixed"]
        and p5a_items["p5a_1_interfaces"]["no_grid_search"]
        and c8_pass
        and p5a_items["p5a_2_self_consistency"]["fold_count"] == 5
    )

    # ---- L1 / L2
    c2_p1 = p1_summary["c2"]["min_db"]
    c2_p2 = p2_summary["c2"]
    l1 = decide_l1(
        p1_min_db=c2_p1,
        p2_min_db=c2_p2["min_db"],
        p2_median_db=c2_p2["median_db"],
        p3_pass=p3_pass,
        p3_items=p3_items,
        p4_pass=p4_pass,
        p5a_pass=p5a_pass,
    )
    l2 = decide_l2(
        l1=l1,
        p5a_pass=p5a_pass,
        c9b=c9b,
        gray_targets=gray_targets,
        freeze_status="not_eligible_for_freeze",
        frozen_present=False,
    )

    cp_blocks = {
        "c1_over_c0_p1_db": float(p1_summary["c1"]["min_db"] - p1_summary["c0"]["min_db"]),
        "c2_over_c1_p1_db": float(p1_summary["c2"]["min_db"] - p1_summary["c1"]["min_db"]),
        "c2_over_c0_p1_db": float(p1_summary["c2"]["min_db"] - p1_summary["c0"]["min_db"]),
        "c2_over_c1_p2_db": float(p2_summary["c2"]["min_db"] - p2_summary["c1"]["min_db"]),
    }

    doc = {
        "contract": CONTRACT_VERSION,
        "decision_version": DECISION_VERSION,
        "proposal_head": PROPOSAL_HEAD,
        "synthetic": True,
        "citable": False,
        "policy": {
            "synthetic": True,
            "citable": False,
            "may_enter_results_table": False,
            "may_enter_paper_numbers": False,
            "may_be_used_for_freeze": False,
            "may_be_used_for_e0t": False,
            "usage": "synthetic_prototype_only_no_real_conclusion",
            "note": (
                "合成夹具只验证代码路径与判定链条，不构成 N0 方法结论；"
                "真实 N0 需 B-02 放行后按同一契约跑 96 个 .dat。"
            ),
        },
        "n0": {
            "rank_requested": N0_RANK,
            "rank_effective_full_pool": basis_full["rank_effective"],
            "arms": list(N0_ARMS),
            "grid_search": N0_GRID_SEARCH,
            "lambda_fixed": list(LAMBDA_FIXED),
            "eta_wall": ETA_WALL,
            "fit_window_ns": FIT_WINDOW_NS,
            "phase_anchor": basis_full["phase_anchor"],
            "ref_pos": REF_POS,
            "near_zero": {
                "ortho_rel_threshold": NEAR_ZERO_MODE_REL,
                "min_second_mode_energy": MIN_SECOND_MODE_ENERGY,
                "gram_cond_max": GRAM_COND_MAX,
                "events": near_zero_events,
                "full_pool_ortho_residual_median": float(
                    np.median(basis_full["ortho_residual_rel"])
                ),
                "full_pool_ortho_residual_max": float(
                    np.max(basis_full["ortho_residual_rel"])
                ),
            },
        },
        "fold_lock": fold_lock,
        "fold_plan": {
            "clusters": [list(c) for c in CLUSTERS],
            "p1_folds": [
                {"fold": f["fold"], "held_out": f["held_out"],
                 "template_pool": f["template_pool"]}
                for f in p1_basis
            ],
            "p1_pool_sizes": [len(f["template_pool"]) for f in p1_basis],
            "p2_loo_pool_size": 9,
        },
        "basis": {
            "sigma1_median": basis_full["sigma1_median"],
            "sigma2_over_sigma1_median": basis_full["sigma2_over_sigma1_median"],
            "p1_folds": p1_basis,
        },
        "synthetic_params": synth["params"],
        "p1": p1_summary,
        "p2": p2_summary,
        "targets": target_results,
        "p3": {"pass": p3_pass, "items": p3_items},
        "p4": {"pass": p4_pass, "items": p4_items},
        "p5a": {"pass": p5a_pass, "items": p5a_items},
        "c8_prime": {"pass": c8_pass, "max_delta_db": c8_max_delta,
                     "lambda_fixed": list(LAMBDA_FIXED),
                     "coverage": c8_coverage,
                     "note": "固定 λ 的逐值复算；P1 五折 + P2 十折 + 目标侧全覆盖；不做 9 对 λ 选择/并列裁决"},
        "c9b": c9b,
        "contrasts": cp_blocks,
        "l1": l1,
        "l2": l2,
        "baseline_p3_anchor": BASELINE_P3_ANCHOR,
        "scope": {
            "opened_files": 0,
            "real_dat_reads": 0,
            "e0t_touched": False,
            "holdout_touched": False,
            "attachment3_touched": False,
            "mode": "synthetic",
        },
    }
    return doc


# --------------------------------------------------------------------------
# check 模式：只读核对（不生成合成数据、不读 .dat）
# --------------------------------------------------------------------------
def run_check(config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    assert_rank(N0_RANK)
    cfg = E0S.load_config(Path(config_path))
    setup = E0S.Setup(cfg)
    fold_lock = assert_fold_lock(BASELINE_SHIFTS_S)
    archived = A.REPO_ROOT / "experiments/A/A-Q1-E0/e0c/results/e0c_results.json"
    anchor = {}
    if archived.is_file():
        with open(archived, "r", encoding="utf-8") as f:
            res = json.load(f)
        for g in res.get("groups", []):
            key = g.get("group_key")
            if key in BASELINE_P3_ANCHOR:
                anchor[key] = {
                    "d_hat_m": g.get("d_hat_m"),
                    "abs_err_cm": g.get("abs_err_cm"),
                    "pslr_db": g.get("pslr_db"),
                    "pnr_db": g.get("pnr_db"),
                }
    return {
        "contract": CONTRACT_VERSION,
        "mode": "check",
        "citable": False,
        "synthetic": True,
        "config_path": str(config_path),
        "n_channels": int(setup.rx63.size),
        "n_freq_bins": int(setup.band_idx.size),
        "rank": N0_RANK,
        "arms": list(N0_ARMS),
        "lambda_fixed": list(LAMBDA_FIXED),
        "fit_window_ns": FIT_WINDOW_NS,
        "fold_lock": fold_lock,
        "cluster_count": len(CLUSTERS),
        "p1_holdout_sizes": [len(c) for c in CLUSTERS],
        "archived_anchor": anchor,
        "real_dat_reads": 0,
    }


# --------------------------------------------------------------------------
# 落盘
# --------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    # 与 `b63e217` 的 `lf_sha256` 同口径：按 LF 归一化后取 SHA256。
    # 本仓 `core.autocrlf=true`，CRLF 检出不会让复核值漂移。
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk.replace(b"\r\n", b"\n"))
    return h.hexdigest()


# --------------------------------------------------------------------------
# 生成溯源（F2）：实现提交、生成时间、实际命令、运行环境
# --------------------------------------------------------------------------
def _git_state(repo_root: Path) -> Tuple[str, bool]:
    """返回 (HEAD 完整 SHA, 工作区是否有未提交改动)；取不到时返回 ("unknown", True)。"""

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    try:
        sha = _git("rev-parse", "HEAD")
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
        return sha, dirty
    except Exception:
        return "unknown", True


def _display_path(path: Path) -> str:
    """仓库内路径用相对路径记录（保证命令字段不依赖本机 worktree 位置）。"""
    try:
        return str(Path(path).resolve().relative_to(A.REPO_ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def _resolve_generated_at(value: Optional[str]) -> Tuple[str, str]:
    """生成时间：显式参数 > SOURCE_DATE_EPOCH > 系统时钟。"""
    if value:
        return value, "explicit"
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            stamp = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            return stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "SOURCE_DATE_EPOCH"
        except (TypeError, ValueError, OSError):
            pass
    return (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "system_clock",
    )


def build_provenance(
    *, command: str, generated_at: Optional[str] = None
) -> Dict[str, Any]:
    sha, dirty = _git_state(A.REPO_ROOT)
    stamp, stamp_source = _resolve_generated_at(generated_at)
    return {
        "implementation_sha": sha,
        "implementation_dirty": bool(dirty),
        "generated_at": stamp,
        "generated_at_source": stamp_source,
        "command": command,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "reproduction": (
            "数值字段由 seed/参数决定，可按容差复算；逐字节复现需用 --generated-at "
            "或 SOURCE_DATE_EPOCH 指定同一 generated_at、保持 implementation_dirty=false，"
            "并使用相同运行环境（本块已记录）。"
        ),
    }


def _json_bytes(obj: Any) -> bytes:
    return (
        json.dumps(A.json_safe(obj), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    ).encode("utf-8")


def render_markdown(doc: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# A-Q1-N0 秩 2 合成原型结果（%s）" % doc["contract"])
    lines.append("")
    lines.append(
        "> **不可引用声明**：本文件是**纯合成夹具**结果（`synthetic=true` / "
        "`citable=false`），只验证 N0 代码路径与 L1/L2 判定链条；**不得**进入论文数字、"
        "结果表、冻结证据或 E0-T 放行材料。真实 N0 需统筹放行 B-02 后按同一契约重跑。"
    )
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append("| 判定口径 | `%s`（提案 head `%s`） |" % (doc["decision_version"], doc["proposal_head"]))
    lines.append("| 秩 | 请求 `2` / 全池实际 `%d` |" % doc["n0"]["rank_effective_full_pool"])
    lines.append("| 臂 | `%s`（无搜索） |" % "`, `".join(doc["n0"]["arms"]))
    lines.append("| λ / η | 固定 `(1e-3,1e-3)` / `%.2f` |" % doc["n0"]["eta_wall"])
    lines.append("| 拟合窗 | 直射波 `±%.1f ns` |" % doc["n0"]["fit_window_ns"])
    lines.append("| 跨频相位锚 | `%s`（ref_pos=%d） |" % (doc["n0"]["phase_anchor"], doc["n0"]["ref_pos"]))
    lines.append("| 真实 `.dat` 读取 | `%d` |" % doc["scope"]["real_dat_reads"])
    lines.append("| 打开文件数 | `%d` |" % doc["scope"]["opened_files"])
    prov = doc.get("provenance") or {}
    if prov:
        sha = prov.get("implementation_sha", "unknown")
        dirty = " (dirty)" if prov.get("implementation_dirty") else ""
        lines.append("| 生成代码 | `%s%s` |" % (sha, dirty))
        lines.append("| 生成时间（UTC） | `%s`（%s） |"
                     % (prov.get("generated_at", "unknown"),
                        prov.get("generated_at_source", "unknown")))
        lines.append("| 生成命令 | `%s` |" % prov.get("command", "unknown"))
        env = prov.get("environment") or {}
        lines.append("| 运行环境 | `python %s` / `numpy %s` / `%s` |"
                     % (env.get("python", "?"), env.get("numpy", "?"),
                        env.get("platform", "?")))
    lines.append("")
    lines.append("## 1. 分簇与训练范围（锁定）")
    lines.append("")
    lines.append("| 折 | 留出（同簇） | 模板池（其余 4 簇） | 实际秩 | `σ2/σ1` 中位 |")
    lines.append("|---|---|---|---:|---:|")
    for f in doc["fold_plan"]["p1_folds"]:
        basis = doc["basis"]["p1_folds"][f["fold"]]
        lines.append(
            "| %d | `%s` | %d 组 | %d | %.3f |"
            % (
                f["fold"],
                "`, `".join(f["held_out"]),
                len(f["template_pool"]),
                basis["rank_effective"],
                basis["sigma2_over_sigma1_median"],
            )
        )
    lines.append("")
    lines.append(
        "偏移锁定：`max|Δ| = %.3f ns`（容差 `%.2f ns`，来源 `b63e217#cal.shifts_s`）。"
        % (doc["fold_lock"]["max_dev_ns"], doc["fold_lock"]["tol_ns"])
    )
    lines.append("")
    lines.append("## 2. P1 五折跨簇 / P2 十折 LOO（`min` / `median`，dB）")
    lines.append("")
    lines.append("| 臂 | P1 min | P1 median | P1 档位 | P2 min | P2 median | P2 档位 |")
    lines.append("|---|---:|---:|---|---:|---:|---|")
    for arm in doc["n0"]["arms"]:
        p1 = doc["p1"][arm]
        p2 = doc["p2"][arm]
        lines.append(
            "| `%s` | %.3f | %.3f | `%s` | %.3f | %.3f | `%s` |"
            % (arm, p1["min_db"], p1["median_db"], p1["tier"],
               p2["min_db"], p2["median_db"], p2["tier"])
        )
    lines.append("")
    lines.append("对照（合成）：")
    for key, val in doc["contrasts"].items():
        lines.append("- `%s` = `%+.3f dB`" % (key, val))
    lines.append("")
    lines.append("## 3. 目标侧（c0/c1/c2）与 P3/P4")
    lines.append("")
    lines.append("| 目标 | 臂 | Supp (dB) | PSLR (dB) | PNR (dB) | `d_hat` (m) | abs_err (cm) | 峰值保留 (dB) | 测距偏移 (mm) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for group, res in doc["targets"].items():
        for arm in doc["n0"]["arms"]:
            m = res["arms"][arm]
            lines.append(
                "| `%s` | `%s` | %.3f | %.3f | %.3f | %.6f | %.3f | %+.3f | %+.3f |"
                % (group, arm, m["supp_dw_win_db"], m["pslr_db"], m["pnr_db"],
                   m["d_hat_m"], m["abs_err_cm"], m["peak_retention_db"],
                   m["range_shift_mm"])
            )
    lines.append("")
    lines.append("| 守卫 | 结果 |")
    lines.append("|---|---|")
    lines.append("| P3 单侧非退化 | `%s` |" % doc["p3"]["pass"])
    lines.append("| P4 回波保留（≥ −0.1 dB，≤ 2 mm） | `%s` |" % doc["p4"]["pass"])
    lines.append("| C8′ 固定 λ 逐值复算（≤ 1e-6 dB） | `%s`（max `%.3g dB`，覆盖 P1/P2/目标侧 `%d` 值） |"
                 % (doc["c8_prime"]["pass"], doc["c8_prime"]["max_delta_db"],
                    doc["c8_prime"].get("coverage", {}).get("total_values", 0)))
    lines.append("| P5a 接口与证据链 | `%s` |" % doc["p5a"]["pass"])
    lines.append("| 近零内积事件 | `%s` |"
                 % ("none" if not doc["n0"]["near_zero"]["events"]
                    else str(len(doc["n0"]["near_zero"]["events"]))))
    lines.append("| 相位锚正交化残差中位 | `%.3g` |"
                 % doc["n0"]["near_zero"]["full_pool_ortho_residual_median"])
    lines.append("")
    lines.append("## 4. L1 / L2 判定（合成）")
    lines.append("")
    l1 = doc["l1"]
    l2 = doc["l2"]
    lines.append(
        "**L1 = `%s`**（P1 `%.3f dB` → `%s`；P2 min `%.3f dB` → `%s`；较低档 `%s`）"
        % (l1["l1"], l1["p1_min_db"], l1["p1_tier"], l1["p2_min_db"],
           l1["p2_tier"], l1["lower_tier"])
    )
    lines.append("")
    lines.append("**L2 = `%s`**（`%s`）" % (l2["l2"], l2["matrix_position"]))
    lines.append("")
    for reason in l2["reasons"]:
        lines.append("- %s" % reason)
    lines.append("")
    lines.append("## 5. 边界（必须随结果一起引用）")
    lines.append("")
    lines.append("- 只跑合成夹具：`real_dat_reads=0`，未读 `附件2/附件3`、未读 `E0-T` 两组、未读 18 组留出样。")
    lines.append("- `P1`/`P2` 的合成数值**不是** N0 的真实抑制结论；真实 `P1` 仍需 B-02 放行后实测。")
    lines.append("- 合成 `L1` 只用来验证判定逻辑分支；`L2` 因无冻结证据必然 FAIL（即提案 `S8`），不是方法失败。")
    lines.append("- 数值内核（`solve_bundle` 等）未改动；分簇、窗宽、λ、η 全部固定。")
    lines.append("")
    lines.append("复跑：`%s`" % (
        prov.get("command")
        or "python solutions/A/a_e0_n0.py --mode synthetic --out experiments/A/A-Q1-E0/n0/synthetic --overwrite"
    ))
    lines.append("")
    if prov.get("generated_at"):
        lines.append(
            "逐字节复现：在同上命令后追加 `--generated-at %s`（或设 `SOURCE_DATE_EPOCH=...`），"
            "并要求 `implementation_dirty=false` 且运行环境一致。" % prov["generated_at"]
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def write_outputs(
    doc: Dict[str, Any],
    out_dir: Path,
    *,
    overwrite: bool = False,
    command: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise N0Stop("S6", "输出目录非空，未给 --overwrite：%s" % out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "n0_synthetic_results.json"
    md_path = out_dir / "N0_SYNTHETIC.md"
    if command is None:
        command = "python solutions/A/a_e0_n0.py --mode synthetic --out %s" % _display_path(out_dir)
    doc = dict(doc)
    doc["provenance"] = build_provenance(command=command, generated_at=generated_at)
    json_path.write_bytes(_json_bytes(doc))
    md_path.write_text(render_markdown(doc), encoding="utf-8", newline="\n")
    sums = []
    for p in (json_path, md_path):
        sums.append("%s  %s" % (_sha256(p), p.name))
    (out_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    return {"json": json_path, "markdown": md_path, "sha256": {p.name: _sha256(p) for p in (json_path, md_path)}}


def _iso_utc(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise argparse.ArgumentTypeError("要求 UTC 时间格式 YYYY-MM-DDTHH:MM:SSZ")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A-Q1-N0 秩 2 合成原型（%s）" % CONTRACT_VERSION)
    ap.add_argument("--mode", choices=("check", "synthetic"), default="check")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=SYNTH_SEED)
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--profile-step-m", type=float, default=0.001)
    ap.add_argument("--p4-step-m", type=float, default=1e-4)
    ap.add_argument("--p4-half-m", type=float, default=0.03)
    ap.add_argument("--generated-at", type=_iso_utc, default=None,
                    help="固定生成时间（UTC），用于逐字节复现；默认取系统时钟")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.mode == "check":
            doc = run_check(Path(args.config))
            print(json.dumps(doc, ensure_ascii=False, indent=1))
            return 0
        cfg = E0S.load_config(Path(args.config))
        setup = E0S.Setup(cfg)
        doc = run_synthetic(
            seed=int(args.seed),
            d_step_m=float(args.profile_step_m),
            p4_step_m=float(args.p4_step_m),
            p4_half_m=float(args.p4_half_m),
            setup=setup,
        )
        command_parts = [
            "python", "solutions/A/a_e0_n0.py",
            "--mode", "synthetic",
            "--seed", str(args.seed),
            "--out", _display_path(Path(args.out)),
            "--profile-step-m", "%g" % args.profile_step_m,
            "--p4-step-m", "%g" % args.p4_step_m,
            "--p4-half-m", "%g" % args.p4_half_m,
        ]
        if args.generated_at:
            command_parts += ["--generated-at", args.generated_at]
        if args.overwrite:
            command_parts.append("--overwrite")
        paths = write_outputs(
            doc,
            Path(args.out),
            overwrite=bool(args.overwrite),
            command=" ".join(command_parts),
            generated_at=args.generated_at,
        )
    except N0Stop as exc:
        print("N0 STOP %s: %s" % (exc.code, exc.reason), file=sys.stderr)
        if exc.detail:
            print(json.dumps(A.json_safe(exc.detail), ensure_ascii=False), file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "contract": doc["contract"],
                "p1": {k: round(v["min_db"], 3) for k, v in doc["p1"].items()},
                "p2": {k: round(v["min_db"], 3) for k, v in doc["p2"].items()},
                "l1": doc["l1"]["l1"],
                "l2": doc["l2"]["l2"],
                "s_code": doc["l2"]["s_code"],
                "out": {k: str(v) for k, v in paths.items() if k != "sha256"},
                "sha256": paths["sha256"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
