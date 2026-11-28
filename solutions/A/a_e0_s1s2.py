#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1-E0-S1/S2 合成闭环求解器（作者实现，纯合成，零真实 ``.dat`` 读取）。

范围
----
只实现 `experiments/A/A-Q1-E0/PLAN.md` 的 **阶段 1（E0-S）**：

* ``E0-S1``：2 路无噪解析闭环，复用已批复 M0 §8 参数；
* ``E0-S2``：63 路全阵列、固定种子 ``20261128``、植入公共参考色散
  ``H_ref``、62 路相对幅相/时延与 25 dB 时域实白高斯噪声的合成闭环。

求解链路严格为已批复的经典基线 ``M0-Cal-Base -> M0-DW-Base ->
M0-Rng-Base``：固定 ``alpha_g = 1.0``，不启用自适应 alpha、子空间抑制、
WLS、逐通道非等权或任何 N0 改进。实现不读取真实 ``.dat``，也不读取
``d_true`` 参与估计；``d_true`` 只在生成阶段植入、在评价阶段计算误差。

运行
----
    python solutions/A/a_e0_s1s2.py --out experiments/A/A-Q1-E0/s1s2/results

结果 JSON 的接口与预登记 ``checks/A/e0_s1s2_prereg.md``（E0-PREREG-1）及
统筹裁定 ``coordination/A_Q1_E0_S_DECISION.md`` 的字段映射见
``solutions/A/e0_s1s2_contract.md``。
"""

from __future__ import annotations

import os

# 资源预算要求：单进程、BLAS/OpenMP 等单线程。必须在导入 numpy 前设置。
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
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CONFIG_PATH = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "config.json"
DEFAULT_OUT = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "s1s2" / "results"

# 预登记锚点（checks/A/e0_s1s2_prereg.md §1）
EXPECTED_CONFIG_SHA256_LF = "8fb6821fa3335ef748e16ad2f5b5b8fc818c13cbe9d3315377faf48d5e40e06a"
EXPECTED_PLAN_SHA256 = "073511c0b6ae44dbc90d228b7d79c2de9d0687d4e65949494803b19f24595a88"
EXPECTED_S2_PARAM_TABLE_SHA256 = (
    "aa86bf56fb138789cd0ad4375691293e7d0e5d65a2daf678d151d44720576e96"
)

S2_SEED = 20261128
S2_TX_IDX = 27
S2_REF_IDX = 28
S2_TARGETS = (
    {"case_id": "E0-S2@0.42", "d_true_m": 0.42, "gamma": 0.25, "peak_rule": "wall"},
    {"case_id": "E0-S2@0.69", "d_true_m": 0.69, "gamma": -0.35, "peak_rule": "metal"},
)
S1_D_TRUE_M = 0.6
S1_GAMMA = -0.35
S1_RX = (28, 12)  # RX1(ref, 4 行 5 列) 与 RX2(4 行 3 列) 对应 M0 §8 几何
S1_DTAU2_S = 0.5e-9
S1_G2 = 1.25
S1_PSI2_RAD = 0.30
S1_TAU_HW_S = 0.2e-9
S1_T0_AIR_S = 120.25  # * Ts
S1_T0_TGT_S = 250.40  # * Ts

DW_OFFSETS_NS = np.linspace(-1.0, 1.0, 41)  # W_dw 41 点、0.05 ns 步长


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def lf_sha256_bytes(blob: bytes) -> str:
    """按 LF 归一化后计算 SHA256（与数据/配置锚点口径一致）。"""
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


def file_sha256(path: Path, normalize_lf: bool = False) -> str:
    blob = path.read_bytes()
    if normalize_lf:
        blob = blob.replace(b"\r\n", b"\n")
    return hashlib.sha256(blob).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def canonical_json_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def array_sha256(arr: np.ndarray) -> str:
    a = np.ascontiguousarray(arr)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode("ascii"))
    h.update(repr(a.shape).encode("ascii"))
    h.update(a.tobytes())
    return h.hexdigest()


def arrays_sha256(arrays: Dict[str, np.ndarray]) -> str:
    """对一组命名数组做确定性摘要（键排序后逐个吸收）。"""
    h = hashlib.sha256()
    for key in sorted(arrays):
        h.update(key.encode("utf-8"))
        h.update(array_sha256(arrays[key]).encode("ascii"))
    return h.hexdigest()


def json_safe(obj: Any) -> Any:
    """递归转换为可 JSON 序列化的值；非有限浮点显式记 None（不允许裸 NaN）。"""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        obj = float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())
    return obj


def peak_rss_mib() -> Optional[float]:
    """Windows 下读取当前进程峰值工作集；不可用时返回 None。"""
    if platform.system() != "Windows":
        return None
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

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        if not ok:
            return None
        return float(counters.PeakWorkingSetSize) / (1024.0 * 1024.0)
    except Exception:  # pragma: no cover - 平台相关兜底
        return None


def git_info(repo: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "head_sha": None,
        "parent_sha": None,
        "branch": None,
        "origin_main_sha": None,
        "working_tree_clean": None,
    }

    def _run(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    info["head_sha"] = _run("rev-parse", "HEAD")
    info["parent_sha"] = _run("rev-parse", "HEAD^")
    info["branch"] = _run("rev-parse", "--abbrev-ref", "HEAD")
    info["origin_main_sha"] = _run("rev-parse", "origin/main")
    status = _run("status", "--porcelain")
    if status is not None:
        info["working_tree_clean"] = status == ""
    return info


# --------------------------------------------------------------------------
# 配置与固定参数
# --------------------------------------------------------------------------
def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path is not None else CONFIG_PATH
    raw = p.read_bytes()
    cfg = json.loads(raw.replace(b"\r\n", b"\n").decode("utf-8"))
    cfg["_config_path"] = str(p)
    cfg["_config_sha256_lf"] = lf_sha256_bytes(raw)
    return cfg


class Setup:
    """由已批复配置派生的物理常数、频带与阵列几何。"""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        pc = cfg["physical_constants"]
        self.cfg = cfg
        self.c0 = float(pc["c0_m_s"])
        self.fs = float(pc["fs_hz"])
        self.np_n = int(pc["np_samples"])
        self.ts = 1.0 / self.fs
        self.tp = self.np_n * self.ts
        self.f_start = float(pc["f_start_hz"])
        self.f_stop = float(pc["f_stop_hz"])
        self.k_slope = (self.f_stop - self.f_start) / self.tp
        self.tx_amp = float(pc["tx_amplitude"])

        # 方案 §3/§5.1：f_D = k/(Np*Ts) = k*1 MHz，k in {300,...,1700}（1401 点）。
        # 显式用整数索引，避免 np.fft.rfftfreq 的浮点端点比较丢掉 k=300。
        self.k_lo = int(round(self.f_start * self.tp))
        self.k_hi = int(round(self.f_stop * self.tp))
        assert (self.k_lo, self.k_hi) == (300, 1700), (self.k_lo, self.k_hi)
        self.band_idx = np.arange(self.k_lo, self.k_hi + 1, dtype=np.int64)
        self.n_band = int(self.band_idx.size)
        self.f_d = self.band_idx.astype(np.float64) / self.tp
        self.f_r = self.fs - self.f_d

        n = np.arange(self.np_n, dtype=np.float64)
        t = n * self.ts
        win = 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (self.np_n - 1))
        phase = 2.0 * np.pi * (
            self.f_start * t + 0.5 * self.k_slope * t * t
        )
        self.s_t = self.tx_amp * win * np.cos(phase)
        self.s_f = np.fft.rfft(self.s_t)
        self.s_band = self.s_f[self.band_idx].copy()

        coords: List[Tuple[float, float]] = []
        for r in range(1, 9):
            z = (75.5 - 7.0 * (r - 1)) * 1e-2
            for c in range(1, 9):
                c_grid = (2 * c - 1) if (r % 2 == 1) else (2 * c)
                x = (8 - c_grid) * 0.035
                coords.append((x, z))
        self.coords = np.asarray(coords, dtype=np.float64)
        assert np.allclose(self.coords[self.tx_idx()], (0.0, 0.545)), self.coords[
            self.tx_idx()
        ]
        self.r_dir_all = np.linalg.norm(
            self.coords - self.coords[self.tx_idx()], axis=1
        )
        self.tau_dir_all = self.r_dir_all / self.c0

        self.rx63 = np.array(
            [i for i in range(64) if i != self.tx_idx()], dtype=np.int64
        )
        assert self.rx63.size == 63
        assert int(np.where(self.rx63 == self.ref_idx())[0][0]) == 27

        self.wm = cfg["windows_and_metrics"]
        self.d_min = float(self.wm["ranging_search_interval_m"][0])
        self.d_max = float(self.wm["ranging_search_interval_m"][1])
        self.ml_half_m = float(self.wm["pslr_mainlobe_half_width_m"])
        self.d_grid = np.arange(
            self.d_min, self.d_max + 0.5e-12, 0.001, dtype=np.float64
        )
        self.dw_offsets_s = DW_OFFSETS_NS * 1e-9

    @staticmethod
    def tx_idx() -> int:
        return S2_TX_IDX

    @staticmethod
    def ref_idx() -> int:
        return S2_REF_IDX


def make_s1_setup(cfg: Dict[str, Any], base: Setup) -> Dict[str, Any]:
    rx = np.asarray(S1_RX, dtype=np.int64)
    r_dir = base.r_dir_all[rx]
    return {
        "rx": rx,
        "r_dir": r_dir,
        "tau_dir": r_dir / base.c0,
        "ref_pos": 0,
        "f_d": base.f_d,
        "f_r": base.f_r,
        "s_band": base.s_band,
    }


# --------------------------------------------------------------------------
# 合成信号生成（不读取任何真实数据；d_true 只用于植入）
# --------------------------------------------------------------------------
def synth_group_spectrum(
    h_rel: np.ndarray,
    s_eff: np.ndarray,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    c0: float,
    d_true: Optional[float] = None,
    gamma: float = 0.0,
    include_direct: bool = True,
) -> np.ndarray:
    """带内观测频谱：直达波 + 可选平面目标镜面回波（均匀 1/R 幅相）。

    ``include_direct=False`` 只返回目标回波分量，用于按预登记/裁定计算
    *纯目标回波* 的 25 dB 噪声基准（不得把强直达波算入噪声基准）。
    """
    if include_direct:
        phase_dir = np.exp(1j * 2.0 * np.pi * np.outer(tau_dir, f_r))
        x = h_rel * ((1.0 / r_dir)[:, None] * s_eff[None, :] * phase_dir)
    else:
        x = np.zeros(
            (h_rel.shape[0], s_eff.shape[0]), dtype=np.complex128
        )
    if d_true is not None:
        r_tgt = np.sqrt(r_dir ** 2 + 4.0 * d_true ** 2)
        tau_tgt = r_tgt / c0
        phase_tgt = np.exp(1j * 2.0 * np.pi * np.outer(tau_tgt, f_r))
        x = x + h_rel * ((gamma / r_tgt)[:, None] * s_eff[None, :] * phase_tgt)
    return x


def to_time(x_band: np.ndarray, band_idx: np.ndarray, np_n: int) -> np.ndarray:
    full = np.zeros((x_band.shape[0], np_n), dtype=np.complex128)
    full[:, band_idx] = x_band
    return np.fft.irfft(full, n=np_n, axis=1)


def from_time(x_time: np.ndarray, band_idx: np.ndarray) -> np.ndarray:
    return np.fft.rfft(x_time, axis=1)[:, band_idx]


def draw_s2_param_table() -> Tuple[Dict[str, Any], np.ndarray, np.random.Generator]:
    """按 E0-PREREG-1 §3.2 的固定顺序抽取 62 路参数。

    每路依次抽 delta_tau、gain、psi0、psi2；行按 rx 升序（去掉 tx=27、ref=28）。
    返回 (规范表, 行数组, 继续使用的 rng)。
    """
    rng = np.random.default_rng(S2_SEED)
    rows: List[List[float]] = []
    for i in (j for j in range(64) if j not in (S2_TX_IDX, S2_REF_IDX)):
        rows.append(
            [
                int(i),
                float(rng.uniform(-0.75e-9, 0.75e-9)),
                float(rng.uniform(0.5, 1.5)),
                float(rng.uniform(-0.5, 0.5)),
                float(rng.uniform(-0.3, 0.3)),
            ]
        )
    table = {
        "experiment": "A-Q1-E0-S2",
        "seed": S2_SEED,
        "rng": "numpy.random.default_rng(20261128)",
        "draw_order": (
            "for rx in sorted(0..63 excluding 27,28): "
            "Uniform(-0.75e-9,0.75e-9), Uniform(0.5,1.5), "
            "Uniform(-0.5,0.5), Uniform(-0.3,0.3)"
        ),
        "columns": [
            "rx_idx",
            "delta_tau_s",
            "gain_mag",
            "psi0_rad",
            "psi2_u2_rad",
        ],
        "rows": rows,
    }
    return table, np.asarray(rows, dtype=np.float64), rng


def planted_h_ref(f_d: np.ndarray, f_r: np.ndarray) -> np.ndarray:
    u = (f_d - 1.0e9) / 0.7e9
    return (1.0 + 0.20 * u) * np.exp(
        1j * (2.0 * np.pi * f_r * S1_TAU_HW_S + 0.5 * u ** 2)
    )


def h_rel_from_rows(
    rows: np.ndarray, rx63: np.ndarray, f_d: np.ndarray
) -> np.ndarray:
    """把 62 路参数展开为 63 路相对频响（参考通道恒为 1）。"""
    h_rel = np.ones((rx63.size, f_d.size), dtype=np.complex128)
    pos_of = {int(rx): p for p, rx in enumerate(rx63)}
    u = (f_d - 1.0e9) / 0.7e9
    for row in rows:
        idx = int(row[0])
        p = pos_of[idx]
        h_rel[p] = float(row[2]) * np.exp(
            -1j * 2.0 * np.pi * f_d * float(row[1])
            + 1j * (float(row[3]) + float(row[4]) * u ** 2)
        )
    return h_rel


def generate_s1(base: Setup) -> Dict[str, Any]:
    s1 = make_s1_setup(base.cfg, base)
    r_dir = s1["r_dir"]
    tau_dir = s1["tau_dir"]
    f_d = s1["f_d"]
    f_r = s1["f_r"]
    s_band = s1["s_band"]

    h_ref = np.exp(1j * 2.0 * np.pi * f_r * S1_TAU_HW_S)
    h_rel = np.vstack(
        [
            np.ones_like(f_d),
            S1_G2
            * np.exp(-1j * 2.0 * np.pi * f_d * S1_DTAU2_S + 1j * S1_PSI2_RAD),
        ]
    )

    t0_air = S1_T0_AIR_S * base.ts
    t0_tgt = S1_T0_TGT_S * base.ts
    s_eff_air = h_ref * s_band * np.exp(1j * 2.0 * np.pi * f_r * t0_air)
    s_eff_tgt = h_ref * s_band * np.exp(1j * 2.0 * np.pi * f_r * t0_tgt)

    x_air = synth_group_spectrum(h_rel, s_eff_air, r_dir, tau_dir, f_r, base.c0)
    x_tgt = synth_group_spectrum(
        h_rel,
        s_eff_tgt,
        r_dir,
        tau_dir,
        f_r,
        base.c0,
        d_true=S1_D_TRUE_M,
        gamma=S1_GAMMA,
    )
    return {
        "case_id": "E0-S1",
        "rx": s1["rx"],
        "r_dir": r_dir,
        "tau_dir": tau_dir,
        "f_d": f_d,
        "f_r": f_r,
        "s_band": s_band,
        "h_rel": h_rel,
        "h_ref": h_ref,
        "air": [x_air],
        "air_offsets_s": [t0_air],
        "target": x_tgt,
        "target_offset_s": t0_tgt,
        "truth": {
            "d_true_m": S1_D_TRUE_M,
            "gamma": S1_GAMMA,
            "dtau2_s": S1_DTAU2_S,
            "g2": S1_G2,
            "psi2_rad": S1_PSI2_RAD,
            "tau_ref_hw_s": S1_TAU_HW_S,
            "t0_air_s": t0_air,
            "t0_tgt_s": t0_tgt,
            "dt0_s": t0_tgt - t0_air,
            "t0_eff_tgt_s": t0_tgt + S1_TAU_HW_S,
        },
    }


def generate_s2(base: Setup) -> Dict[str, Any]:
    cfg = base.cfg
    table, rows, rng = draw_s2_param_table()
    rx63 = base.rx63
    r_dir = base.r_dir_all[rx63]
    tau_dir = base.tau_dir_all[rx63]
    f_d = base.f_d
    f_r = base.f_r
    s_band = base.s_band

    air_offsets = [120.25 * base.ts]
    for _ in range(9):
        air_offsets.append(float(rng.uniform(0.0, base.tp)))
    target_offsets = [float(rng.uniform(0.0, base.tp)) for _ in S2_TARGETS]

    h_ref = planted_h_ref(f_d, f_r)
    h_rel = h_rel_from_rows(rows, rx63, f_d)

    # 25 dB SNR 的噪声基准：0.42 m **纯目标回波**（不含直达波）的 63 路
    # 平均时域功率；裁定 §2 明确“目标组的标准差按该目标的 63 路纯回波
    # 平均时域功率及 25 dB SNR 计算”。直达波幅度约为回波的 20 倍，若误
    # 把直达波计入基准，σ 会放大约 22 倍，等效 SNR 不再是 25 dB。
    d0 = S2_TARGETS[0]["d_true_m"]
    g0 = float(S2_TARGETS[0]["gamma"])
    s_eff0 = h_ref * s_band * np.exp(
        1j * 2.0 * np.pi * f_r * target_offsets[0]
    )
    tgt_only = synth_group_spectrum(
        h_rel,
        s_eff0,
        r_dir,
        tau_dir,
        f_r,
        base.c0,
        d_true=d0,
        gamma=g0,
        include_direct=False,
    )
    tgt_only_t = to_time(tgt_only, base.band_idx, base.np_n)
    echo_power = float(np.mean(tgt_only_t ** 2))
    sigma2 = (10.0 ** (-cfg["pilot_datasets"]["phase_s_synthetic"][1]["noise"]["snr_db"] / 10.0)) * echo_power
    sigma = math.sqrt(sigma2)

    # 噪声抽取顺序（裁定 §2）：air_0..air_9、目标 0.42、目标 0.69，各一次 (63,4000)。
    noise_raw: List[np.ndarray] = []
    for _ in range(12):
        noise_raw.append(rng.standard_normal((rx63.size, base.np_n)))

    air: List[np.ndarray] = []
    air_time: List[np.ndarray] = []
    noise_sha_raw: List[str] = []
    noise_sha_scaled: List[str] = []
    for j, t0 in enumerate(air_offsets):
        s_eff = h_ref * s_band * np.exp(1j * 2.0 * np.pi * f_r * t0)
        x_clean_t = to_time(
            synth_group_spectrum(h_rel, s_eff, r_dir, tau_dir, f_r, base.c0),
            base.band_idx,
            base.np_n,
        )
        noise = sigma * noise_raw[j]
        noise_sha_raw.append(array_sha256(noise_raw[j]))
        noise_sha_scaled.append(array_sha256(noise))
        x_meas = from_time(x_clean_t + noise, base.band_idx)
        air.append(x_meas)
        air_time.append(x_clean_t)

    targets: List[Dict[str, Any]] = []
    for k, spec in enumerate(S2_TARGETS):
        t0 = target_offsets[k]
        s_eff = h_ref * s_band * np.exp(1j * 2.0 * np.pi * f_r * t0)
        x_clean_t = to_time(
            synth_group_spectrum(
                h_rel,
                s_eff,
                r_dir,
                tau_dir,
                f_r,
                base.c0,
                d_true=float(spec["d_true_m"]),
                gamma=float(spec["gamma"]),
            ),
            base.band_idx,
            base.np_n,
        )
        noise = sigma * noise_raw[10 + k]
        noise_sha_raw.append(array_sha256(noise_raw[10 + k]))
        noise_sha_scaled.append(array_sha256(noise))
        x_meas = from_time(x_clean_t + noise, base.band_idx)
        targets.append(
            {
                "case_id": spec["case_id"],
                "d_true_m": float(spec["d_true_m"]),
                "gamma": float(spec["gamma"]),
                "peak_rule": spec["peak_rule"],
                "t0_s": t0,
                "x": x_meas,
                "x_clean_time": x_clean_t,
                "noise": noise,
                "noise_sha_raw": array_sha256(noise_raw[10 + k]),
                "noise_sha_scaled": array_sha256(noise),
            }
        )

    return {
        "case_id": "E0-S2",
        "table": table,
        "table_sha256": canonical_json_sha256(table),
        "param_rows": rows,
        "rng_tail_sha256": None,
        "rx": rx63,
        "r_dir": r_dir,
        "tau_dir": tau_dir,
        "f_d": f_d,
        "f_r": f_r,
        "s_band": s_band,
        "h_ref": h_ref,
        "h_rel": h_rel,
        "air": air,
        "air_offsets_s": air_offsets,
        "targets": targets,
        "sigma": sigma,
        "sigma2": sigma2,
        "echo_power_042": echo_power,
        "noise_sha_raw": noise_sha_raw,
        "noise_sha_scaled": noise_sha_scaled,
    }


# --------------------------------------------------------------------------
# 估计原语：对齐、校准、有效模板、压缩响应、剖面
# --------------------------------------------------------------------------
def _oversampled_q(
    c_corr: np.ndarray,
    band_idx: np.ndarray,
    np_n: int,
    ts: float,
    factor: int = 8,
) -> Tuple[np.ndarray, float]:
    """在 ``factor`` 倍过采样 lag 网格上计算 Q(s)=sum C e^{+j2*pi*f_R*s}。

    返回 (Q, s_step)。Q[n] 对应 s = n*Ts/factor（模 Tp）。使用频域补零
    ifft 实现，避免在 4 GHz 载波下整数样点实部振荡导致粗峰错位。
    """
    n_big = np_n * factor
    full = np.zeros(n_big, dtype=np.complex128)
    full[band_idx] = np.conj(c_corr)
    q = np.conj(np.fft.ifft(full)) * n_big
    q *= np.exp(1j * 2.0 * np.pi * np.arange(n_big) / factor)
    return q, ts / factor


def align_lag(
    x: np.ndarray,
    ref: np.ndarray,
    f_r: np.ndarray,
    band_idx: np.ndarray,
    np_n: int,
    ts: float,
    tp: float,
) -> float:
    """求把 ``x`` 乘上 ``exp(+j2*pi*f_R*s)`` 后最接近 ``ref`` 的循环 lag s。

    粗搜先在 8 倍过采样 lag 网格上用包络 |Q(s)| 定位（覆盖全部 Tp），再在
    粗峰 +-1 Ts 内以 1e-3 Ts 细搜 Re Q(s)。返回 s in [0, Tp)。
    """
    c_corr = np.sum(x * np.conj(ref), axis=0)
    q_big, s_step = _oversampled_q(c_corr, band_idx, np_n, ts, factor=8)
    s0 = float(np.argmax(np.abs(q_big)) * s_step) % tp
    u = np.linspace(-1.0, 1.0, 2001)
    s = (s0 + u * ts) % tp
    scores = np.real(np.exp(1j * 2.0 * np.pi * np.outer(s, f_r)) @ c_corr)
    return float(s[int(np.argmax(scores))])


def estimate_scalar_anchor(
    s_eff: np.ndarray,
    s_band: np.ndarray,
    f_r: np.ndarray,
    band_idx: np.ndarray,
    np_n: int,
    ts: float,
    tp: float,
) -> float:
    """由 S_eff_hat 与理想 S 的标量时延匹配估计有效零点 t0_eff（诊断/对照用）。"""
    g = s_eff * np.conj(s_band)
    q_big, s_step = _oversampled_q(g, band_idx, np_n, ts, factor=8)
    # |Q(s)| 的峰在 s = -t0_eff，故取反得到 t0_eff 初值。
    s0 = (-float(np.argmax(np.abs(q_big))) * s_step) % tp
    u = np.linspace(-1.0, 1.0, 2001)
    s = (s0 + u * ts) % tp
    scores = np.abs(np.exp(-1j * 2.0 * np.pi * np.outer(s, f_r)) @ g)
    return float(s[int(np.argmax(scores))])


def estimate_h_rel(
    xbar: np.ndarray,
    ref_pos: int,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    lam_cal: float,
) -> np.ndarray:
    """M0-Cal-Base 正则化比值校准（参考通道规范固定 H_ref^rel = 1）。"""
    x_ref = xbar[ref_pos]
    p_ref = float(np.mean(np.abs(x_ref) ** 2))
    denom = np.abs(x_ref) ** 2 + lam_cal * p_ref
    h = np.empty_like(xbar)
    h[ref_pos] = 1.0
    for i in range(xbar.shape[0]):
        if i == ref_pos:
            continue
        h[i] = (
            xbar[i]
            * np.conj(x_ref)
            / denom
            * (r_dir[i] / r_dir[ref_pos])
            * np.exp(
                -1j
                * 2.0
                * np.pi
                * f_r
                * (tau_dir[i] - tau_dir[ref_pos])
            )
        )
    return h


def inverse_op(h: np.ndarray, lam_inv: float) -> np.ndarray:
    """X_cal = conj(H)/(|H|^2 + lam_inv) * X 的乘子。"""
    return np.conj(h) / (np.abs(h) ** 2 + lam_inv)


def calibrate_air(
    air: Sequence[np.ndarray],
    ref_pos: int,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    band_idx: np.ndarray,
    np_n: int,
    ts: float,
    tp: float,
    lam_cal: float,
    lam_inv: float,
) -> Dict[str, Any]:
    shifts = [0.0]
    for x in air[1:]:
        shifts.append(
            align_lag(x, air[0], f_r, band_idx, np_n, ts, tp)
        )
    aligned = [
        x
        * np.exp(1j * 2.0 * np.pi * f_r * s)[None, :]
        for x, s in zip(air, shifts)
    ]
    xbar = np.mean(np.asarray(aligned), axis=0)
    h = estimate_h_rel(xbar, ref_pos, r_dir, tau_dir, f_r, lam_cal)
    inv = inverse_op(h, lam_inv)
    return {
        "shifts_s": shifts,
        "aligned": aligned,
        "xbar": xbar,
        "h": h,
        "inv": inv,
        "xbar_cal": xbar * inv,
        "lam_cal": lam_cal,
        "lam_inv": lam_inv,
    }


def select_lambdas_air_loo(
    aligned_air: Sequence[np.ndarray],
    ref_pos: int,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    cal_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """纯空场 LOO 确定性选参（PLAN §3.1，9 组固定预算）。"""
    grid_cal = [float(v) for v in cal_cfg["lambda_cal_grid_air_loo"]]
    grid_inv = [float(v) for v in cal_cfg["lambda_inv_grid_air_loo"]]
    default_cal = float(cal_cfg["lambda_cal_default"])
    default_inv = float(cal_cfg["lambda_inv_default"])
    n_air = len(aligned_air)
    rows: List[Dict[str, Any]] = []

    for lc in grid_cal:
        for li in grid_inv:
            supps = []
            for g in range(n_air):
                tmpl = np.mean(
                    [aligned_air[j] for j in range(n_air) if j != g], axis=0
                )
                h = estimate_h_rel(tmpl, ref_pos, r_dir, tau_dir, f_r, lc)
                inv = inverse_op(h, li)
                xcal = aligned_air[g] * inv
                residual = xcal - tmpl * inv
                num = float(np.sum(np.abs(xcal) ** 2))
                den = float(np.sum(np.abs(residual) ** 2))
                supps.append(10.0 * math.log10(num / den))
            supps_arr = np.asarray(supps)
            j_air = float(np.median(supps_arr) + 0.5 * float(np.min(supps_arr)))
            rows.append(
                {
                    "lambda_cal": lc,
                    "lambda_inv": li,
                    "J_air_db": j_air,
                    "min_supp_db": float(np.min(supps_arr)),
                    "median_supp_db": float(np.median(supps_arr)),
                    "supp_db": [float(v) for v in supps_arr],
                }
            )

    def _sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
        return (
            -row["J_air_db"],
            row["lambda_cal"] + row["lambda_inv"],
            abs(
                math.log10(row["lambda_cal"] / default_cal)
                + math.log10(row["lambda_inv"] / default_inv)
            ),
            row["lambda_cal"],
            row["lambda_inv"],
        )

    ordered = sorted(rows, key=_sort_key)
    best = ordered[0]
    default_row = min(
        rows,
        key=lambda r: abs(r["lambda_cal"] - default_cal)
        + abs(r["lambda_inv"] - default_inv),
    )
    trigger = False
    reason = "keep_default"
    if best["J_air_db"] - default_row["J_air_db"] >= 0.5:
        trigger = True
        reason = "J_gain_ge_0.5dB"
    elif (
        default_row["min_supp_db"] < 10.0
        and best["min_supp_db"] >= 10.0
    ):
        trigger = True
        reason = "default_min_below_10dB_and_best_meets"
    chosen = best if trigger else default_row
    return {
        "grid_rows": rows,
        "best": best,
        "default": default_row,
        "selected": {
            "lambda_cal": chosen["lambda_cal"],
            "lambda_inv": chosen["lambda_inv"],
        },
        "triggered": trigger,
        "trigger_reason": reason,
        "n_air": n_air,
        "folds": n_air,
        "budget_pairs": len(rows),
    }


def build_s_eff(
    xair_cal_aligned: np.ndarray,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
) -> np.ndarray:
    """由对齐校准空场重构显式色散模板 S_eff_hat（PLAN §5.1）。"""
    weights = 1.0 / r_dir
    num = np.sum(
        weights[:, None]
        * xair_cal_aligned
        * np.exp(-1j * 2.0 * np.pi * np.outer(tau_dir, f_r)),
        axis=0,
    )
    den = float(np.sum(1.0 / r_dir ** 2))
    return num / den


def z_at_delays(
    x: np.ndarray, tpl: np.ndarray, f_r: np.ndarray, delays: np.ndarray
) -> np.ndarray:
    """在任意循环延迟 delays[i, m] 上计算 z_i(tau)（单位模板能量归一化）。"""
    norm = float(np.linalg.norm(tpl))
    xc = x * np.conj(tpl)[None, :]
    out = np.empty(delays.shape, dtype=np.complex128)
    for i in range(x.shape[0]):
        out[i] = (
            xc[i] @ np.exp(-1j * 2.0 * np.pi * np.outer(f_r, delays[i]))
        ) / norm
    return out


def z_grid(
    x: np.ndarray, tpl: np.ndarray, f_r: np.ndarray, np_n: int, band_idx: np.ndarray
) -> np.ndarray:
    """在 tau_m = m*Ts (m=0..Np-1) 上计算 z_i(tau)（Np 点 ifft）。"""
    norm = float(np.linalg.norm(tpl))
    full = np.zeros((x.shape[0], np_n), dtype=np.complex128)
    full[:, band_idx] = x * np.conj(tpl)[None, :]
    return np_n * np.fft.ifft(full, axis=1) / norm


def r_tgt_of_d(r_dir: np.ndarray, d: float) -> np.ndarray:
    return np.sqrt(r_dir ** 2 + 4.0 * d ** 2)


def profile_p_norm_eff(
    x_after: np.ndarray,
    s_eff: np.ndarray,
    r_dir: np.ndarray,
    f_r: np.ndarray,
    c0: float,
    d_grid: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """主统计量 P_norm,eff 与逐通道 z_i(tau_tgt_i(d))。"""
    r_t = np.sqrt(r_dir[:, None] ** 2 + 4.0 * d_grid[None, :] ** 2)
    tau = r_t / c0
    z = z_at_delays(x_after, s_eff, f_r, tau)
    num = np.abs(np.sum(z / r_t, axis=0)) ** 2
    den = np.sum(1.0 / r_t ** 2, axis=0)
    return num / den, z, tau


def profile_p_norm(
    x_after: np.ndarray,
    s_band: np.ndarray,
    r_dir: np.ndarray,
    f_r: np.ndarray,
    c0: float,
    d_grid: np.ndarray,
    t_anchor_s: float,
) -> np.ndarray:
    """对照统计量 P_norm（纯时延标量模板 + t0_eff 锚点）。"""
    r_t = np.sqrt(r_dir[:, None] ** 2 + 4.0 * d_grid[None, :] ** 2)
    tau = r_t / c0 + t_anchor_s
    z = z_at_delays(x_after, s_band, f_r, tau)
    num = np.abs(np.sum(z / r_t, axis=0)) ** 2
    den = np.sum(1.0 / r_t ** 2, axis=0)
    return num / den


def profile_p_env(
    z: np.ndarray, r_dir: np.ndarray, d_grid: np.ndarray
) -> np.ndarray:
    """对照统计量 P_env（非相干包络叠加），复用 P_norm,eff 的 z。"""
    r_t = np.sqrt(r_dir[:, None] ** 2 + 4.0 * d_grid[None, :] ** 2)
    num = (
        np.sum(np.abs(z) / r_t, axis=0)
    ) ** 2
    den = np.sum(1.0 / r_t ** 2, axis=0)
    return num / den


def peak_index(
    p: np.ndarray, d_grid: np.ndarray, rule: str, bg_proxy: float, eta_wall: float
) -> int:
    if rule == "metal":
        return int(np.argmax(p))
    if rule != "wall":
        raise ValueError("unknown peak rule: %r" % (rule,))
    p_max = float(np.max(p))
    local = np.zeros_like(p, dtype=bool)
    local[1:-1] = (p[1:-1] > p[:-2]) & (p[1:-1] >= p[2:])
    cand = np.where(
        local & (p >= eta_wall * p_max) & (p >= (10.0 ** 0.6) * bg_proxy)
    )[0]
    if cand.size == 0:
        return int(np.argmax(p))
    return int(cand[0])


def refine_peak(
    d_coarse: float,
    profile_fn: Any,
    d_min: float,
    d_max: float,
    step: float = 1e-4,
) -> Tuple[float, float]:
    """在粗峰 +-1 mm 内以 0.1 mm 细搜，返回 (d_hat, P_hat)。"""
    d_fine = np.clip(
        d_coarse + np.arange(-10, 11, dtype=np.float64) * step, d_min, d_max
    )
    p_fine = profile_fn(d_fine)
    k = int(np.argmax(p_fine))
    return float(d_fine[k]), float(p_fine[k])


# --------------------------------------------------------------------------
# 指标与门控
# --------------------------------------------------------------------------
def compute_suppression(
    x_before: np.ndarray,
    x_after: np.ndarray,
    s_eff: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    tp: float,
    dw_offsets_s: np.ndarray,
) -> Tuple[float, np.ndarray, np.ndarray]:
    delays = (tau_dir[:, None] + dw_offsets_s[None, :]) % tp
    z_b = z_at_delays(x_before, s_eff, f_r, delays)
    z_a = z_at_delays(x_after, s_eff, f_r, delays)
    num = float(np.sum(np.abs(z_b) ** 2))
    den = float(np.sum(np.abs(z_a) ** 2))
    return 10.0 * math.log10(num / den), z_b, z_a


def compute_bg_proxy(
    x_after: np.ndarray,
    s_eff: np.ndarray,
    f_r: np.ndarray,
    np_n: int,
    band_idx: np.ndarray,
) -> Tuple[float, np.ndarray]:
    z = z_grid(x_after, s_eff, f_r, np_n, band_idx)
    # W_bg: tau_m = m*Ts, m in [200, 3800]（50..950 ns）
    bg = float(np.mean(np.abs(z[:, 200:3801]) ** 2))
    return bg, z


def compute_pnr(
    x_after: np.ndarray,
    s_eff: np.ndarray,
    r_dir: np.ndarray,
    f_r: np.ndarray,
    c0: float,
    d_hat: float,
    bg_proxy: float,
) -> Tuple[float, np.ndarray]:
    r_t = r_tgt_of_d(r_dir, d_hat)
    tau = r_t / c0
    z = z_at_delays(x_after, s_eff, f_r, tau[:, None])[:, 0]
    pnr = 10.0 * math.log10(float(np.mean(np.abs(z) ** 2)) / bg_proxy)
    return pnr, z


def compute_pslr(
    p: np.ndarray, d_grid: np.ndarray, d_hat: float, p_peak: float, ml_half: float
) -> float:
    sl = np.abs(d_grid - d_hat) > ml_half
    p_sl = float(np.max(p[sl]))
    return 10.0 * math.log10(float(p_peak) / p_sl)


# --------------------------------------------------------------------------
# 单例求解
# --------------------------------------------------------------------------
def solve_case(
    measured: np.ndarray,
    cal: Dict[str, Any],
    s_band: np.ndarray,
    r_dir: np.ndarray,
    tau_dir: np.ndarray,
    f_r: np.ndarray,
    c0: float,
    setup: Setup,
    peak_rule: str,
    eta_wall: float,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """对单组校准后测量执行 DW 对齐减除、S_eff、三统计量与指标。"""
    x_cal = measured * cal["inv"]
    dt0_s = align_lag(
        cal["xbar_cal"],
        x_cal,
        f_r,
        setup.band_idx,
        setup.np_n,
        setup.ts,
        setup.tp,
    )
    xair_aligned = cal["xbar_cal"] * np.exp(
        1j * 2.0 * np.pi * f_r * dt0_s
    )[None, :]
    alpha = float(
        cfg["methods_classic_baseline_only"]["direct_wave_suppression"][
            "alpha_fixed_value"
        ]
    )
    assert alpha == 1.0
    x_after = x_cal - alpha * xair_aligned
    s_eff = build_s_eff(xair_aligned, r_dir, tau_dir, f_r)

    valid_rx = int(np.sum(np.all(np.isfinite(measured), axis=1)))

    bg_proxy, z_full = compute_bg_proxy(
        x_after, s_eff, f_r, setup.np_n, setup.band_idx
    )
    supp, z_dw_b, z_dw_a = compute_suppression(
        x_cal,
        x_after,
        s_eff,
        tau_dir,
        f_r,
        setup.tp,
        setup.dw_offsets_s,
    )

    p_eff, z_eff_coarse, _ = profile_p_norm_eff(
        x_after, s_eff, r_dir, f_r, c0, setup.d_grid
    )

    def _peff(d: Any) -> np.ndarray:
        return profile_p_norm_eff(
            x_after, s_eff, r_dir, f_r, c0, np.asarray(d, dtype=np.float64)
        )[0]

    idx = peak_index(p_eff, setup.d_grid, peak_rule, bg_proxy, eta_wall)
    d0 = float(setup.d_grid[idx])
    d_hat, p_hat = refine_peak(d0, _peff, setup.d_min, setup.d_max)

    pslr = compute_pslr(p_eff, setup.d_grid, d_hat, p_hat, setup.ml_half_m)
    pnr, z_tgt = compute_pnr(
        x_after, s_eff, r_dir, f_r, c0, d_hat, bg_proxy
    )

    t_anchor = estimate_scalar_anchor(
        s_eff,
        s_band,
        f_r,
        setup.band_idx,
        setup.np_n,
        setup.ts,
        setup.tp,
    )

    def _pnorm(d: Any) -> np.ndarray:
        return profile_p_norm(
            x_after,
            s_band,
            r_dir,
            f_r,
            c0,
            np.asarray(d, dtype=np.float64),
            t_anchor,
        )

    p_norm_coarse = _pnorm(setup.d_grid)
    d_norm_coarse = float(setup.d_grid[int(np.argmax(p_norm_coarse))])
    d_hat_norm, _ = refine_peak(
        d_norm_coarse, _pnorm, setup.d_min, setup.d_max
    )

    p_env_coarse = profile_p_env(z_eff_coarse, r_dir, setup.d_grid)
    d_env_coarse = float(setup.d_grid[int(np.argmax(p_env_coarse))])

    def _penv(d: Any) -> np.ndarray:
        zz = profile_p_norm_eff(
            x_after, s_eff, r_dir, f_r, c0, np.asarray(d, dtype=np.float64)
        )[1]
        return profile_p_env(zz, r_dir, np.asarray(d, dtype=np.float64))

    d_hat_env, _ = refine_peak(
        d_env_coarse, _penv, setup.d_min, setup.d_max
    )

    # EchoRet（仅诊断）：固定 alpha=1 的峰保留度
    p_before = profile_p_norm_eff(
        x_cal, s_eff, r_dir, f_r, c0, np.asarray([d_hat])
    )[0][0]
    p_after_hat = float(
        profile_p_norm_eff(
            x_after, s_eff, r_dir, f_r, c0, np.asarray([d_hat])
        )[0][0]
    )
    echo_ret_db = 10.0 * math.log10(p_after_hat / p_before)

    return {
        "dt0_s": dt0_s,
        "dt0_samples": dt0_s / setup.ts,
        "t_anchor_s": t_anchor,
        "t_anchor_samples": t_anchor / setup.ts,
        "x_cal": x_cal,
        "x_after": x_after,
        "xair_aligned_cal": xair_aligned,
        "s_eff": s_eff,
        "bg_proxy": bg_proxy,
        "supp_dw_win_db": supp,
        "z_dw_before": z_dw_b,
        "z_dw_after": z_dw_a,
        "d_hat_m": d_hat,
        "p_hat": p_hat,
        "d_hat_p_norm_m": d_hat_norm,
        "d_hat_p_env_m": d_hat_env,
        "pslr_db": pslr,
        "pnr_db": pnr,
        "z_after_tgt": z_tgt,
        "echo_ret_db": echo_ret_db,
        "profile_d_grid_m": setup.d_grid,
        "profile_p_norm_eff": p_eff,
        "profile_p_norm": p_norm_coarse,
        "profile_p_env": p_env_coarse,
        "z_full": z_full,
        "valid_rx": valid_rx,
        "finite": bool(
            np.all(np.isfinite(x_after))
            and np.all(np.isfinite(s_eff))
            and np.all(np.isfinite(z_full))
            and math.isfinite(supp)
            and math.isfinite(pslr)
            and math.isfinite(pnr)
            and math.isfinite(d_hat)
        ),
    }


def run_s1(
    base: Setup, cfg: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, np.ndarray], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    gen = generate_s1(base)
    r_dir = gen["r_dir"]
    tau_dir = gen["tau_dir"]
    f_d = gen["f_d"]
    f_r = gen["f_r"]
    s_band = gen["s_band"]
    cal_cfg = cfg["methods_classic_baseline_only"]["calibration"]
    cal = calibrate_air(
        gen["air"],
        0,
        r_dir,
        tau_dir,
        f_r,
        base.band_idx,
        base.np_n,
        base.ts,
        base.tp,
        lam_cal=0.0,
        lam_inv=0.0,
    )
    h_hat = cal["h"]
    ratio = h_hat[1]
    core = (f_d >= cfg["physical_constants"]["core_band_hz"][0]) & (
        f_d <= cfg["physical_constants"]["core_band_hz"][1]
    )
    weights = np.abs(s_band) ** 2
    phi = np.unwrap(np.angle(ratio[core]))
    fc = f_d[core]
    wc = weights[core]
    wsum = float(np.sum(wc))
    fbar = float(np.sum(wc * fc) / wsum)
    phibar = float(np.sum(wc * phi) / wsum)
    df = fc - fbar
    slope = float(np.sum(wc * df * (phi - phibar)) / np.sum(wc * df ** 2))
    dtau2_hat = -slope / (2.0 * np.pi)
    g2_hat = float(np.mean(np.abs(ratio[core])))
    psi2_hat = float(
        np.mean(np.angle(ratio[core] * np.exp(1j * 2.0 * np.pi * fc * dtau2_hat)))
    )

    solved = solve_case(
        gen["target"],
        cal,
        s_band,
        r_dir,
        tau_dir,
        f_r,
        base.c0,
        base,
        "metal",
        float(cfg["methods_classic_baseline_only"]["ranging"]["eta_wall_default"]),
        cfg,
    )
    d_hat = solved["d_hat_m"]
    abs_err_cm = abs(d_hat - gen["truth"]["d_true_m"]) * 100.0
    dtau_err_ns = abs(dtau2_hat - S1_DTAU2_S) * 1e9
    t0_eff_err_samples = abs(
        solved["t_anchor_s"] - gen["truth"]["t0_eff_tgt_s"]
    ) / base.ts
    gates = cfg["gates_and_thresholds"]
    gate_results = {
        "abs_err_cm": {
            "value": abs_err_cm,
            "threshold": float(gates["synthetic_noiseless_max_range_err_cm"]),
            "passed": abs_err_cm <= float(gates["synthetic_noiseless_max_range_err_cm"]),
        },
        "dtau2_err_ns": {
            "value": dtau_err_ns,
            "threshold": float(gates["synthetic_noiseless_max_dtau_err_ns"]),
            "passed": dtau_err_ns <= float(gates["synthetic_noiseless_max_dtau_err_ns"]),
        },
        "t0_eff_tgt_samples": {
            "value": solved["t_anchor_samples"],
            "expected": gen["truth"]["t0_eff_tgt_s"] / base.ts,
            "abs_err_samples": t0_eff_err_samples,
            "threshold": 1e-3,
            "passed": t0_eff_err_samples <= 1e-3,
            "role": "diagnostic",
        },
        "dt0_samples": {
            "value": solved["dt0_samples"],
            "expected": gen["truth"]["dt0_s"] / base.ts,
            "abs_err_samples": abs(solved["dt0_s"] - gen["truth"]["dt0_s"]) / base.ts,
            "threshold": 1e-3,
            "passed": abs(solved["dt0_s"] - gen["truth"]["dt0_s"]) / base.ts <= 1e-3,
            "role": "diagnostic",
        },
        "finite": {"value": bool(solved["finite"]), "passed": bool(solved["finite"])},
    }
    failed_gates = [
        name for name, g in gate_results.items() if "passed" in g and not g["passed"]
    ]

    case = {
        "case_id": "E0-S1",
        "d_true_m": gen["truth"]["d_true_m"],
        "d_hat_m": d_hat,
        "abs_err_cm": abs_err_cm,
        "dtau2_hat_s": dtau2_hat,
        "dtau_err_ns": dtau_err_ns,
        "g2_hat": g2_hat,
        "psi2_hat_rad": psi2_hat,
        "t0_eff_tgt_samples": solved["t_anchor_samples"],
        "dt0_samples": solved["dt0_samples"],
        "supp_dw_win_db": None,
        "pslr_db": None,
        "pnr_db": None,
        "valid_rx": int(solved["valid_rx"]),
        "finite": bool(solved["finite"]),
        "seed": None,
        "gates_applied": ["abs_err_cm", "dtau2_err_ns", "finite"],
        "diagnostics": [
            "t0_eff_tgt_samples",
            "dt0_samples",
            "g2_hat",
            "psi2_hat_rad",
            "p_norm_eff",
            "p_norm",
            "p_env",
        ],
        "gate_results": gate_results,
        "stop_reason": None if not failed_gates else "gate_failed: " + ", ".join(failed_gates),
        "not_applicable": {
            "supp_dw_win_db": "E0-S1 为 2 路无噪解析例外，63 路 DW 窗门控不适用",
            "pslr_db": "E0-S1 无噪解析例，近距回波质量门控不适用",
            "pnr_db": "E0-S1 无噪解析例，近距回波质量门控不适用",
        },
        "d_hat_p_norm_m": solved["d_hat_p_norm_m"],
        "d_hat_p_env_m": solved["d_hat_p_env_m"],
        "echo_ret_db": solved["echo_ret_db"],
        "arrays_sha256": {},
    }
    arrays = {
        "s1_rx_idx": gen["rx"].astype(np.int64),
        "s1_r_dir_m": r_dir,
        "s1_tau_dir_s": tau_dir,
        "s1_x_air": gen["air"][0],
        "s1_x_target": gen["target"],
        "s1_h_rel_hat": h_hat,
        "s1_x_cal": solved["x_cal"],
        "s1_x_after": solved["x_after"],
        "s1_s_eff_hat": solved["s_eff"],
        "s1_z_dw_before": solved["z_dw_before"],
        "s1_z_dw_after": solved["z_dw_after"],
        "s1_profile_d_grid_m": solved["profile_d_grid_m"],
        "s1_profile_p_norm_eff": solved["profile_p_norm_eff"],
        "s1_profile_p_norm": solved["profile_p_norm"],
        "s1_profile_p_env": solved["profile_p_env"],
        "s1_p_at_d_hat": np.asarray([solved["p_hat"]]),
        "s1_bg_proxy": np.asarray([solved["bg_proxy"]]),
        "s1_d_hat_m": np.asarray([solved["d_hat_m"]]),
        "s1_t_anchor_s": np.asarray([solved["t_anchor_s"]]),
    }
    case["arrays_sha256"] = {
        "case_arrays": arrays_sha256(arrays),
        "x_after": array_sha256(solved["x_after"]),
        "s_eff": array_sha256(solved["s_eff"]),
    }
    return case, arrays, gen, solved, cal


def run_s2(
    base: Setup, cfg: Dict[str, Any]
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, np.ndarray],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    List[float],
]:
    gen = generate_s2(base)
    if gen["table_sha256"] != EXPECTED_S2_PARAM_TABLE_SHA256:
        raise RuntimeError(
            "S2 参数表规范 SHA256 与预登记不一致: %s" % gen["table_sha256"]
        )
    r_dir = gen["r_dir"]
    tau_dir = gen["tau_dir"]
    f_r = gen["f_r"]
    s_band = gen["s_band"]
    cal_cfg = cfg["methods_classic_baseline_only"]["calibration"]

    # 先对齐全部空场，供 LOO 与最终模板共用
    shifts = [0.0]
    for x in gen["air"][1:]:
        shifts.append(
            align_lag(
                x, gen["air"][0], f_r, base.band_idx, base.np_n, base.ts, base.tp
            )
        )
    aligned_air = [
        x * np.exp(1j * 2.0 * np.pi * f_r * s)[None, :]
        for x, s in zip(gen["air"], shifts)
    ]
    loo = select_lambdas_air_loo(
        aligned_air, 27, r_dir, tau_dir, f_r, cal_cfg
    )
    lam = loo["selected"]
    cal = calibrate_air(
        gen["air"],
        27,
        r_dir,
        tau_dir,
        f_r,
        base.band_idx,
        base.np_n,
        base.ts,
        base.tp,
        lam_cal=float(lam["lambda_cal"]),
        lam_inv=float(lam["lambda_inv"]),
    )

    eta_wall = float(
        cfg["methods_classic_baseline_only"]["ranging"]["eta_wall_default"]
    )
    gates = cfg["gates_and_thresholds"]
    cases: List[Dict[str, Any]] = []
    arrays: Dict[str, np.ndarray] = {
        "s2_rx_idx": gen["rx"].astype(np.int64),
        "s2_r_dir_m": r_dir,
        "s2_tau_dir_s": tau_dir,
        "s2_param_rows": gen["param_rows"],
        "s2_air_offsets_s": np.asarray(gen["air_offsets_s"], dtype=np.float64),
        "s2_target_offsets_s": np.asarray(
            [t["t0_s"] for t in gen["targets"]], dtype=np.float64
        ),
        "s2_noise_sigma": np.asarray([gen["sigma"]], dtype=np.float64),
        "s2_h_hat": cal["h"],
    }

    for tgt, key in zip(gen["targets"], ("s2_042", "s2_069")):
        solved = solve_case(
            tgt["x"],
            cal,
            s_band,
            r_dir,
            tau_dir,
            f_r,
            base.c0,
            base,
            tgt["peak_rule"],
            eta_wall,
            cfg,
        )
        d_hat = solved["d_hat_m"]
        abs_err_cm = abs(d_hat - tgt["d_true_m"]) * 100.0
        finite = bool(solved["finite"])
        gates_case = {
            "abs_err_cm": {
                "value": abs_err_cm,
                "threshold": float(gates["synthetic_noisy_max_range_err_cm"]),
                "passed": abs_err_cm <= float(gates["synthetic_noisy_max_range_err_cm"]),
            },
            "supp_dw_win_db": {
                "value": solved["supp_dw_win_db"],
                "threshold": float(gates["synthetic_noisy_min_dw_suppression_db"]),
                "passed": solved["supp_dw_win_db"]
                >= float(gates["synthetic_noisy_min_dw_suppression_db"]),
            },
            "pslr_db": {
                "value": solved["pslr_db"],
                "threshold": float(gates["target_echo_min_pslr_db"]),
                "passed": solved["pslr_db"] >= float(gates["target_echo_min_pslr_db"]),
            },
            "pnr_db": {
                "value": solved["pnr_db"],
                "threshold": float(gates["target_echo_min_pnr_db"]),
                "passed": solved["pnr_db"] >= float(gates["target_echo_min_pnr_db"]),
            },
            "valid_rx": {
                "value": int(solved["valid_rx"]),
                "threshold": int(gates["required_valid_rx_channels"]),
                "passed": int(solved["valid_rx"])
                == int(gates["required_valid_rx_channels"]),
            },
            "finite": {"value": finite, "passed": finite},
        }
        failed_gates_case = [
            name
            for name, g in gates_case.items()
            if "passed" in g and not g["passed"]
        ]
        case = {
            "case_id": tgt["case_id"],
            "d_true_m": tgt["d_true_m"],
            "d_hat_m": d_hat,
            "abs_err_cm": abs_err_cm,
            "dtau_err_ns": None,
            "supp_dw_win_db": solved["supp_dw_win_db"],
            "pslr_db": solved["pslr_db"],
            "pnr_db": solved["pnr_db"],
            "bg_proxy": solved["bg_proxy"],
            "echo_ret_db": solved["echo_ret_db"],
            "valid_rx": int(solved["valid_rx"]),
            "finite": finite,
            "seed": S2_SEED,
            "peak_rule": tgt["peak_rule"],
            "t_anchor_samples": solved["t_anchor_samples"],
            "dt0_samples": solved["dt0_samples"],
            "gates_applied": [
                "abs_err_cm",
                "supp_dw_win_db",
                "pslr_db",
                "pnr_db",
                "valid_rx",
                "finite",
            ],
            "gate_results": gates_case,
            "stop_reason": None
            if not failed_gates_case
            else "gate_failed: " + ", ".join(failed_gates_case),
            "d_hat_p_norm_m": solved["d_hat_p_norm_m"],
            "d_hat_p_env_m": solved["d_hat_p_env_m"],
            "not_applicable": {"dtau_err_ns": "S2 无相对校准参数门控"},
            "arrays_sha256": {},
        }
        case_arrays = {
            "freq_hz": base.f_d,
            "freq_rf_hz": f_r,
            "tau_dir_s": tau_dir,
            "x_cal": solved["x_cal"],
            "x_after": solved["x_after"],
            "s_eff": solved["s_eff"],
            "z_dw_before": solved["z_dw_before"],
            "z_dw_after": solved["z_dw_after"],
            "z_after_tgt": solved["z_after_tgt"],
            "profile_d_grid_m": solved["profile_d_grid_m"],
            "profile_p_norm_eff": solved["profile_p_norm_eff"],
            "profile_p_norm": solved["profile_p_norm"],
            "profile_p_env": solved["profile_p_env"],
        }
        case["arrays_sha256"] = {
            "case_arrays": arrays_sha256(case_arrays),
            "x_after": array_sha256(solved["x_after"]),
            "s_eff": array_sha256(solved["s_eff"]),
        }
        for k, v in case_arrays.items():
            arrays["%s_%s" % (key, k)] = v
        arrays["%s_d_hat_m" % key] = np.asarray([d_hat])
        arrays["%s_t_anchor_s" % key] = np.asarray([solved["t_anchor_s"]])
        arrays["%s_p_at_d_hat" % key] = np.asarray([solved["p_hat"]])
        arrays["%s_bg_proxy" % key] = np.asarray([solved["bg_proxy"]])
        cases.append(case)

    return cases, arrays, gen, cal, loo, shifts


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def run_all(
    cfg: Dict[str, Any],
    base: Setup,
    log: List[str],
) -> Dict[str, Any]:
    t_start = time.perf_counter()
    log.append(
        "[setup] Np=%d Ts=%.6g tp=%.6g band_k=%d..%d (%d bins)"
        % (
            base.np_n,
            base.ts,
            base.tp,
            base.k_lo,
            base.k_hi,
            base.n_band,
        )
    )
    log.append(
        "[setup] config_sha256_lf=%s" % cfg["_config_sha256_lf"]
    )

    s1_case, s1_arrays, s1_gen, s1_solved, s1_cal = run_s1(base, cfg)
    log.append(
        "[E0-S1] d_hat=%.9f m err=%.6f cm dtau_err=%.9f ns "
        "t0_eff=%.6f Ts dt0=%.6f Ts"
        % (
            s1_case["d_hat_m"],
            s1_case["abs_err_cm"],
            s1_case["dtau_err_ns"],
            s1_case["t0_eff_tgt_samples"],
            s1_case["dt0_samples"],
        )
    )

    s2_cases, s2_arrays, s2_gen, s2_cal, loo, shifts = run_s2(base, cfg)
    log.append(
        "[E0-S2] sigma=%.6g echo_power_042=%.6g param_sha=%s"
        % (s2_gen["sigma"], s2_gen["echo_power_042"], s2_gen["table_sha256"])
    )
    log.append(
        "[E0-S2] air shifts (Ts)=%s"
        % ", ".join("%.6f" % (s / base.ts) for s in shifts)
    )
    log.append(
        "[E0-S2] lambda_LOO selected=(%.6g, %.6g) triggered=%s reason=%s"
        % (
            loo["selected"]["lambda_cal"],
            loo["selected"]["lambda_inv"],
            loo["triggered"],
            loo["trigger_reason"],
        )
    )
    for row in loo["grid_rows"]:
        log.append(
            "[E0-S2][LOO] lc=%.6g li=%.6g J=%.6f dB min=%.6f median=%.6f"
            % (
                row["lambda_cal"],
                row["lambda_inv"],
                row["J_air_db"],
                row["min_supp_db"],
                row["median_supp_db"],
            )
        )
    for c in s2_cases:
        log.append(
            "[%s] d_hat=%.9f m err=%.6f cm supp=%.6f dB pslr=%.6f dB "
            "pnr=%.6f dB bg=%.6g EchoRet=%.6f dB"
            % (
                c["case_id"],
                c["d_hat_m"],
                c["abs_err_cm"],
                c["supp_dw_win_db"],
                c["pslr_db"],
                c["pnr_db"],
                c["bg_proxy"],
                c["echo_ret_db"],
            )
        )

    all_cases = [s1_case, *s2_cases]
    plan_sha256 = file_sha256(
        REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "PLAN.md"
    )
    config_match = cfg["_config_sha256_lf"] == EXPECTED_CONFIG_SHA256_LF
    table_match = s2_gen["table_sha256"] == EXPECTED_S2_PARAM_TABLE_SHA256
    plan_match = plan_sha256 == EXPECTED_PLAN_SHA256
    failed: List[str] = []
    if not config_match:
        failed.append("config_sha256_mismatch")
    if not plan_match:
        failed.append("plan_sha256_mismatch")
    if not table_match:
        failed.append("s2_param_table_sha256_mismatch")
    for c in all_cases:
        for gate_name, g in c["gate_results"].items():
            if "passed" in g and not g["passed"]:
                failed.append("%s:%s" % (c["case_id"], gate_name))
    overall_pass = not failed
    stop_reason = None if overall_pass else "gate_failed: " + ", ".join(failed)
    wall = time.perf_counter() - t_start

    arrays = {}
    arrays.update(s1_arrays)
    arrays.update(s2_arrays)
    arrays["freq_hz"] = base.f_d
    arrays["freq_rf_hz"] = base.f_r
    arrays["band_k"] = base.band_idx

    result = {
        "experiment_id": cfg["experiment_id"],
        "phase": "E0-S",
        "scope": "synthetic_only_no_real_dat",
        "config_sha256": cfg["_config_sha256_lf"],
        "config_sha256_expected": EXPECTED_CONFIG_SHA256_LF,
        "config_sha256_match": bool(config_match),
        "plan_sha256": plan_sha256,
        "plan_sha256_expected": EXPECTED_PLAN_SHA256,
        "plan_sha256_match": bool(plan_match),
        "rng": {
            "s2_seed": S2_SEED,
            "generator": "numpy.random.default_rng",
            "numpy_version": np.__version__,
        },
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "cases": all_cases,
        "s2_param_table_sha256": s2_gen["table_sha256"],
        "s2_param_table_expected_sha256": EXPECTED_S2_PARAM_TABLE_SHA256,
        "s2_param_table_match": s2_gen["table_sha256"]
        == EXPECTED_S2_PARAM_TABLE_SHA256,
        "s2_noise_sigma": s2_gen["sigma"],
        "s2_noise_sigma2": s2_gen["sigma2"],
        "s2_echo_power_042": s2_gen["echo_power_042"],
        "s2_noise_sha256_raw": s2_gen["noise_sha_raw"],
        "s2_noise_sha256_scaled": s2_gen["noise_sha_scaled"],
        "s2_air_offsets_s": s2_gen["air_offsets_s"],
        "s2_target_offsets_s": [t["t0_s"] for t in s2_gen["targets"]],
        "s2_offsets_sha256": canonical_json_sha256(
            {
                "air_offsets_s": s2_gen["air_offsets_s"],
                "target_offsets_s": [t["t0_s"] for t in s2_gen["targets"]],
                "order": "air_0..air_9,target_0.42,target_0.69",
            }
        ),
        "s2_param_rows": s2_gen["param_rows"].tolist(),
        "lambda_loo": {
            "grid_rows": loo["grid_rows"],
            "selected": loo["selected"],
            "triggered": loo["triggered"],
            "trigger_reason": loo["trigger_reason"],
            "default": loo["default"],
            "best": loo["best"],
            "budget_pairs": loo["budget_pairs"],
        },
        "air_alignment_shifts_s": shifts,
        "overall_pass": bool(overall_pass),
        "stop_reason": stop_reason,
        "resource": {"wall_time_s": wall, "peak_rss_mib": peak_rss_mib()},
        "arrays_sha256": arrays_sha256(arrays),
        "semantics": {
            "alpha_g": 1.0,
            "n0_improvements_enabled": False,
            "primary_statistic": "P_norm_eff",
            "peak_rules": {
                "E0-S1": "global_argmax",
                "E0-S2@0.42": "wall_first_peak",
                "E0-S2@0.69": "metal_global_argmax",
            },
            "band": "f_D = k/(Np*Ts) = k*1MHz, k=300..1700 (1401 bins)",
        },
        "log": list(log),
    }
    return result, arrays, s1_gen, s2_gen, s1_solved, s2_cases


def write_outputs(
    out_dir: Path,
    result: Dict[str, Any],
    arrays: Dict[str, np.ndarray],
    s2_table: Dict[str, Any],
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / "e0_s1s2_arrays.npz"
    np.savez_compressed(npz_path, **arrays)
    result["arrays_file"] = npz_path.name
    result["arrays_file_sha256"] = file_sha256(npz_path)

    table_path = out_dir / "e0_s2_param_table.json"
    table_path.write_text(
        json.dumps(s2_table, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    result["s2_param_table_file"] = table_path.name
    result["s2_param_table_file_sha256"] = file_sha256(table_path)

    json_path = out_dir / "e0_s1s2_results.json"
    json_path.write_text(
        json.dumps(json_safe(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log_path = out_dir / "run.log"
    log_path.write_text("\n".join(result.get("log", [])) + "\n", encoding="utf-8")

    sums = {
        npz_path.name: file_sha256(npz_path),
        table_path.name: file_sha256(table_path),
        json_path.name: file_sha256(json_path),
        log_path.name: file_sha256(log_path),
    }
    (out_dir / "SHA256SUMS.txt").write_text(
        "\n".join("%s  %s" % (v, k) for k, v in sorted(sums.items())) + "\n",
        encoding="utf-8",
    )
    return sums


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="A-Q1-E0-S1/S2 合成闭环求解器（零真实 .dat 读取）"
    )
    ap.add_argument("--config", type=str, default=str(CONFIG_PATH))
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    ap.add_argument("--implementation-sha", type=str, default=None)
    ap.add_argument("--parent-commit", type=str, default=None)
    ap.add_argument("--main-commit", type=str, default=None)
    args = ap.parse_args(argv)

    log: List[str] = []
    cfg = load_config(Path(args.config))
    expected = EXPECTED_CONFIG_SHA256_LF
    if cfg["_config_sha256_lf"] != expected:
        log.append(
            "[warn] config SHA256(lf)=%s != 预登记 %s"
            % (cfg["_config_sha256_lf"], expected)
        )
    base = Setup(cfg)
    try:
        result, arrays, s1_gen, s2_gen, s1_solved, s2_cases = run_all(
            cfg, base, log
        )
    except Exception:
        # 失败/异常也留下日志与输出目录，避免只给非零退出码。
        err_dir = Path(args.out)
        err_dir.mkdir(parents=True, exist_ok=True)
        (err_dir / "run_error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise

    prov = git_info(REPO_ROOT)
    result["implementation_sha"] = (
        args.implementation_sha
        or prov.get("head_sha")
        or "UNKNOWN"
    )
    result["parent_commit"] = (
        args.parent_commit or prov.get("parent_sha") or "UNKNOWN"
    )
    result["main_commit"] = (
        args.main_commit
        or prov.get("origin_main_sha")
        or "UNKNOWN"
    )
    result["branch"] = prov.get("branch")
    result["git"] = prov
    command = "python solutions/A/a_e0_s1s2.py --config %s --out %s" % (
        args.config,
        args.out,
    )
    for flag, value in (
        ("--implementation-sha", args.implementation_sha),
        ("--parent-commit", args.parent_commit),
        ("--main-commit", args.main_commit),
    ):
        if value:
            command += " %s %s" % (flag, value)
    result["command"] = command

    out_dir = Path(args.out)
    sums = write_outputs(out_dir, result, arrays, s2_gen["table"])
    print(json.dumps(json_safe({
        "overall_pass": result["overall_pass"],
        "cases": [
            {
                "case_id": c["case_id"],
                "d_hat_m": c["d_hat_m"],
                "abs_err_cm": c["abs_err_cm"],
                "supp_dw_win_db": c["supp_dw_win_db"],
                "pslr_db": c["pslr_db"],
                "pnr_db": c["pnr_db"],
                "passed": all(
                    g["passed"] for g in c["gate_results"].values() if "passed" in g
                ),
            }
            for c in result["cases"]
        ],
        "resource": result["resource"],
        "out": str(out_dir),
        "files": sums,
    }), ensure_ascii=False, indent=2))
    for line in log:
        print(line)
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
