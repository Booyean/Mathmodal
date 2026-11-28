#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""复数秩一通道模态回归（契约 ``N0-CHREG-1``）。

为什么需要这个回归
------------------
``build_rank2_basis`` 先用 ``rel_dev = (pool - T) / T`` 把「每组相对公共波形的
偏差」按「组 × 通道」排成矩阵，逐频点做 SVD，再把通道权重 ``v(f)`` 调制出第二
模态 ``D_1(f) = T(f) ⊙ v(f)``。

矩阵 ``A = rel_dev[:, :, f]``（``G × n_ch``）满足 ``A = U·S·Vh``，即

    ``A[g, c] = Σ_k s_k · u_k[g] · conj(v_k[c])``

所以**每组通道行向量的方向是 ``conj(v_k)``，而 ``Vh`` 的行恰好就是 ``conj(v_k)``**
——行方向 = ``vh[0]``。旧实现写成 ``v = vh[0].conj()``，等于把相对通道相位整体
反转；对实通道方向只差一个全局相位（此前的实夹具因此**在数学上不可能**发现
它），对复通道方向则直接错。

本回归就是 codex 在 PR #41 复核时要求的那一条：
**用解析夹具 ``(1, e^{2πi/3}, e^{4πi/3})`` 验证 SVD 提取的通道模态能否重建训练
数据的行方向（允许任意全局相位）**。结论（见 ``verdict``）：旧实现
``vh[0].conj()`` 在该夹具上 **FAIL**（方向被反转成 ``conj(γ)``、行重建残差 50%、
第二模态系数恒 0），已按同一 PR 修正为 ``v = vh[0]``；修正后 **PASS**，并把旧式
作为负例保留。

旧夹具为什么必然漏检（两个盲点，缺一不可）
------------------------------------------
1. ``test_a_e0_n0.py`` 的 ``_tiny_pool`` 等夹具里，**所有组共用同一个 ``T_c``**，
   于是 ``rel_dev = dev/T`` 恰好等于实 pattern，``conj`` 只差全局相位；
2. 旧夹具的通道方向本身是**实向量**，实向量的共轭也只差全局相位。

真实/合成流水线里 ``T`` 是**组均值**（各组幅相抖动 + 近零噪声），``rel_dev = dev/T``
带着 ``T`` 的逐通道相位，行方向本身就是复向量；此时相位反转是真实的模型错误
（``T ⊙ conj(dev/T) ∝ dev ⊙ exp(2i∠T)``，不再是 ``dev``）。

夹具为什么是「解析可证」而不是阈值调出来的
------------------------------------------
* 通道方向取单位圆周三等分点 ``γ = (1, e^{2πi/3}, e^{4πi/3}) / √3``；
* ``Σ_c γ_c = 0``，所以「扣除整组复标度」（对通道取均值）**不改变**它；
* ``Σ_c γ_c² = 1 + e^{4πi/3} + e^{8πi/3} = 0``，即 ``γ ⟂ conj(γ)``。
  于是把相位反转的实现与原方向**正交**：既恢复不出方向（相位对齐误差 ~√2），
  也拟合不上（行重建残差 = ``|α_g| / √(3+|α_g|²)``，``|α|=1`` 时 50%，``|α|=0.5`` 时 27.7%）。
* 组系数取和为零（``Σ α_g = 0``），保证 ``T`` 恰为训练池均值、``rel_dev`` 行严格
  等于 ``α_g γ``，不被均值项污染。

三件事分开验证
--------------
1. **方向恢复**：由生产 ``build_rank2_basis`` 的 ``D_1`` 反解
   ``w = D_1 / T``（再扣通道均值），与 ``γ`` 比较，**允许任意全局相位**；
2. **行方向重建**：把训练池每组行向量投影到 ``span{T, D_1}``（复数最小二乘），
   残差应 ~0，且第二模态系数 ``b`` 应逐值等于该组真系数 ``α_g``；
3. **变异可探测性（负例）**：把提取式换回旧的 ``v = vh[0].conj()``，重跑 1、2，
   必须**显著失败**——否则回归没有咬合力。

两组夹具
--------
* ``flat_T``：``T`` 逐通道为常数（最干净的解析情形，``proj = 0``）；
* ``ramp_T``：``T`` 带逐通道延迟斜坡与幅度锥削（更接近真实直射波形态，
  ``proj ≠ 0``），用来证明方向反解在非均匀 ``T`` 下仍成立。

边界
----
纯内存夹具，不读任何文件（``real_dat_files_read = 0``），不触碰 ``E0-T`` /
附件 3 / 检验组，不改变数值内核（``solve_bundle`` 等），只改 ``build_rank2_basis``
的取向量约定；``n0/synthetic`` 产物因该修复已重新生成并另行登记 SHA256。

用法::

    python solutions/A/a_e0_n0_channel_regression.py            # 打印 JSON 摘要
    python solutions/A/a_e0_n0_channel_regression.py --out DIR  # 另写 JSON/MD/SHA256SUMS
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a_e0_n0 as N  # noqa: E402

CONTRACT_VERSION = "N0-CHREG-1"

#: 通道方向：单位圆周三等分点（零均值、且与自身共轭正交）。
OMEGA = np.exp(2j * np.pi / 3.0)
CHANNEL_DIRECTION = np.array([1.0, OMEGA, OMEGA**2], dtype=np.complex128) / math.sqrt(3.0)

#: 组系数：和为零，保证 ``T`` 恰为训练池均值（``rel_dev`` 不被均值项污染）。
GROUP_COEFFS: Tuple[complex, ...] = (1.0, -1.0, 0.5j, -0.5j, 0.7, -0.7)

FIXTURE_CASES: Tuple[str, ...] = ("flat_T", "ramp_T")

#: 判定阈值（解析可证）：正确路径 < 1e-10；相位反转负例方向误差 > 1.0（理论 √2）、
#: 行残差下界 > 0.2（理论 ``|α|/√(3+|α|²)``，``|α|=0.5`` 时 0.277）、第二模态系数 ~0。
DIRECTION_OK_MAX = 1e-10
ROW_RESIDUAL_OK_MAX = 1e-10
COEFF_REL_OK_MAX = 1e-9
NEGATIVE_DIRECTION_MIN = 1.0
NEGATIVE_ROW_RESIDUAL_MIN = 0.2
NEGATIVE_SECOND_COEFF_MAX = 1e-9


# --------------------------------------------------------------------------
# 夹具
# --------------------------------------------------------------------------
def build_fixture(case: str, *, n_f: int = 4) -> Dict[str, Any]:
    """造解析训练池 ``pool[g, c, f] = T[c, f] * (1 + α_g γ_c)``。"""
    if case not in FIXTURE_CASES:
        raise ValueError("未登记的夹具 %r（可选：%s）" % (case, ", ".join(FIXTURE_CASES)))
    n_ch = int(CHANNEL_DIRECTION.size)
    gamma = CHANNEL_DIRECTION.copy()
    alpha = np.asarray(GROUP_COEFFS, dtype=np.complex128)

    if case == "flat_T":
        # T 逐通道为常数（每频点一个复标量）：proj = <T, T⊙γ>/||T||² = Σγ/√n = 0。
        amp = 0.8 + 0.1 * np.arange(n_f, dtype=np.float64)
        phase = 0.2 + 0.5 * np.arange(n_f, dtype=np.float64)
        t_scalar = amp * np.exp(1j * phase)
        t_mean = np.repeat(t_scalar[None, :], n_ch, axis=0)
    else:
        # 更接近真实直射波：逐通道延迟斜坡 + 正幅度锥削（权重非均匀 → proj ≠ 0）。
        f_base = np.linspace(2.3e9, 3.7e9, n_f)
        tau = np.array([0.0, 0.37e-9, 0.71e-9], dtype=np.float64)
        taper = np.array([0.9, 1.05, 1.2], dtype=np.float64)
        t_mean = taper[:, None] * np.exp(2j * np.pi * np.outer(tau, f_base))
    pool = np.stack(
        [t_mean * (1.0 + alpha[g] * gamma)[:, None] for g in range(alpha.size)],
        axis=0,
    )
    return {
        "case": case,
        "T": t_mean,
        "pool": np.asarray(pool, dtype=np.complex128),
        "gamma": gamma,
        "alpha": alpha,
        "n_groups": int(alpha.size),
        "n_ch": n_ch,
        "n_f": int(n_f),
    }


def real_direction_fixture(*, n_f: int = 4) -> Dict[str, Any]:
    """旧夹具形态（实通道方向）——用来演示它在数学上无法区分共轭。"""
    n_ch = int(CHANNEL_DIRECTION.size)
    gamma = np.real(CHANNEL_DIRECTION)
    gamma = gamma / float(np.linalg.norm(gamma))
    alpha = np.asarray(GROUP_COEFFS, dtype=np.complex128)
    amp = 0.8 + 0.1 * np.arange(n_f, dtype=np.float64)
    t_scalar = amp * np.exp(1j * (0.2 + 0.5 * np.arange(n_f, dtype=np.float64)))
    t_mean = np.repeat(t_scalar[None, :], n_ch, axis=0)
    pool = np.stack(
        [t_mean * (1.0 + alpha[g] * gamma)[:, None] for g in range(alpha.size)],
        axis=0,
    )
    return {"T": t_mean, "pool": np.asarray(pool, dtype=np.complex128), "gamma": gamma}


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------
def _complex_pair(value: complex) -> List[float]:
    """复数按 ``[re, im]`` 落盘（沿用仓库“不写裸 complex”的约定）。"""
    z = complex(value)
    return [float(z.real), float(z.imag)]


def json_safe(obj: Any) -> Any:
    """先按 ``[re, im]`` 展开 complex，再交给仓库既有的 ``json_safe``。"""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (complex, np.complexfloating)):
        return _complex_pair(obj)
    return N.A.json_safe(obj)


def phase_aligned_error(recovered: np.ndarray, truth: np.ndarray) -> float:
    """``min_φ ||e^{iφ}·truth - recovered|| / ||truth||``（允许任意全局相位）。"""
    recovered = np.asarray(recovered, dtype=np.complex128).reshape(-1)
    truth = np.asarray(truth, dtype=np.complex128).reshape(-1)
    t_norm = float(np.linalg.norm(truth))
    r_norm = float(np.linalg.norm(recovered))
    if t_norm <= 0.0:
        raise ValueError("真值向量为零")
    if r_norm <= 0.0:
        return float("inf")
    overlap = abs(np.vdot(truth, recovered))
    gap = t_norm**2 + r_norm**2 - 2.0 * overlap
    return float(math.sqrt(max(gap, 0.0)) / t_norm)


def recover_channel_direction(T: np.ndarray, D1: np.ndarray) -> np.ndarray:
    """由 ``D_1`` 反解通道方向：``D_1/T`` 后扣掉通道均值（整组复标度）。

    ``D_1 = T ⊙ v - proj·T``，逐通道相除得 ``v - proj``（常数），扣通道均值即还原
    ``v``（因为夹具方向零均值）。与 ``T`` 的相位斜坡、幅度锥削无关。
    """
    f = 1
    t_col = T[:, f]
    d_col = D1[:, f]
    if float(np.max(np.abs(t_col))) <= 0.0:
        raise ValueError("T 全零，无法反解通道方向")
    w = d_col / np.where(np.abs(t_col) > 0.0, t_col, 1.0)
    w = w - np.mean(w)
    norm = float(np.linalg.norm(w))
    if norm <= 0.0:
        raise ValueError("反解出的通道方向为零")
    return w / norm


def _extract_basis(
    pool: np.ndarray, *, legacy_conjugate: bool = False, ref_pos: int = 0
) -> Dict[str, Any]:
    """与生产 ``build_rank2_basis`` 同式的提取器；``legacy_conjugate=True`` 即旧变异。

    生产实现取 ``v = vh[0]``（行方向）；负例取旧式 ``v = vh[0].conj()``，
    其余逐行同式。两者在 ``legacy_conjugate=False`` 时应逐值一致（回归自检会核对）。
    """
    pool = np.asarray(pool, dtype=np.complex128)
    n_groups, n_ch, n_f = pool.shape
    t_mean = np.mean(pool, axis=0)
    dev = pool - t_mean[None, :, :]
    t_amp = np.abs(t_mean)
    rel_dev = np.where(
        t_amp > 1e-300, dev / np.where(t_amp > 1e-300, t_mean, 1.0), 0.0
    )
    rel_dev = rel_dev - np.mean(rel_dev, axis=1, keepdims=True)
    t_norm2 = np.sum(np.abs(t_mean) ** 2, axis=0)
    d1 = np.zeros((n_ch, n_f), dtype=np.complex128)
    anchor_idx = np.full(n_f, -1, dtype=np.int64)
    ortho_rel = np.zeros(n_f)
    sigma1 = np.zeros(n_f)
    for f in range(n_f):
        _u, s, vh = np.linalg.svd(rel_dev[:, :, f], full_matrices=False)
        sigma1[f] = float(s[0]) if s.size else 0.0
        v = vh[0].conj() if legacy_conjugate else vh[0]
        v = v.astype(np.complex128)
        v = v / max(float(np.linalg.norm(v)), 1e-300)
        if abs(v[ref_pos]) >= 1e-3 * float(np.max(np.abs(v))):
            anchor_idx[f] = ref_pos
        else:
            anchor_idx[f] = int(np.argmax(np.abs(v)))
        v = v * np.exp(-1j * np.angle(v[anchor_idx[f]]))
        mode = t_mean[:, f] * v
        proj = np.vdot(t_mean[:, f], mode) / t_norm2[f]
        resid = mode - proj * t_mean[:, f]
        ortho_rel[f] = float(np.linalg.norm(resid)) / max(
            float(np.linalg.norm(mode)), 1e-300
        )
        d1[:, f] = resid
    return {
        "T": t_mean,
        "D1": d1,
        "anchor_idx": anchor_idx,
        "ortho_residual_rel": ortho_rel,
        "sigma1": sigma1,
    }


def reconstruct_rows(
    T: np.ndarray, D1: np.ndarray, rows: np.ndarray
) -> Dict[str, Any]:
    """逐频点把每组行向量投影到 ``span{T, D1}``（复数最小二乘）。"""
    T = np.asarray(T, dtype=np.complex128)
    D1 = np.asarray(D1, dtype=np.complex128)
    rows = np.asarray(rows, dtype=np.complex128)
    n_f = T.shape[1]
    rel = []
    coeff_b = []
    for f in range(n_f):
        design = np.stack([T[:, f], D1[:, f]], axis=1)
        for g in range(rows.shape[0]):
            target = rows[g, :, f]
            coef, *_ = np.linalg.lstsq(design, target, rcond=None)
            resid = target - design @ coef
            denom = float(np.linalg.norm(target))
            rel.append(float(np.linalg.norm(resid)) / max(denom, 1e-300))
            coeff_b.append(complex(coef[1]))
    return {
        "row_rel_residual_max": max(rel),
        "row_rel_residual_min": min(rel),
        "second_coeff_b": coeff_b,
    }


def _coeff_rel_errors(alpha: np.ndarray, b_hat: Sequence[complex], n_f: int) -> List[float]:
    errs = []
    for f in range(n_f):
        for g in range(alpha.size):
            b = complex(b_hat[f * alpha.size + g])
            true = complex(alpha[g])
            errs.append(abs(b - true) / max(abs(true), 1e-300))
    return errs


# --------------------------------------------------------------------------
# 主回归
# --------------------------------------------------------------------------
def evaluate_case(case: str, *, n_f: int = 4) -> Dict[str, Any]:
    fx = build_fixture(case, n_f=n_f)
    pool = fx["pool"]
    gamma = fx["gamma"]
    alpha = fx["alpha"]

    production = N.build_rank2_basis(pool, ref_pos=0, mode_form="modulation")
    if production["rank_effective"] != 2:
        raise AssertionError("%s：夹具应非退化（rank_effective=%r）" % (case, production["rank_effective"]))
    if production["near_parallel"]:
        raise AssertionError("%s：夹具不应判 near_parallel" % (case,))

    # 生产实现与本地同式实现逐值一致（保证负例只是「取向量约定」这一处变异）。
    control = _extract_basis(pool, legacy_conjugate=False, ref_pos=0)
    prod_gap = float(
        np.linalg.norm(production["D1"] - control["D1"])
        / max(float(np.linalg.norm(production["D1"])), 1e-300)
    )

    # 1) 方向恢复（生产 D_1）
    v_hat = recover_channel_direction(production["T"], production["D1"])
    dir_err_true = phase_aligned_error(v_hat, gamma)
    dir_err_conj = phase_aligned_error(v_hat, np.conj(gamma))

    # 2) 行方向重建（生产 D_1）
    recon = reconstruct_rows(production["T"], production["D1"], pool)
    coeff_errs = _coeff_rel_errors(alpha, recon["second_coeff_b"], n_f)

    # 3) 变异负例：换回旧式 v = vh[0].conj()（相对通道相位反转）
    mutant = _extract_basis(pool, legacy_conjugate=True, ref_pos=0)
    v_mut = recover_channel_direction(mutant["T"], mutant["D1"])
    mut_dir_err_true = phase_aligned_error(v_mut, gamma)
    mut_recon = reconstruct_rows(mutant["T"], mutant["D1"], pool)
    mut_b = [abs(complex(v)) for v in mut_recon["second_coeff_b"]]
    # 只有 flat_T 有解析结论“第二模态系数必须恒为 0”（<T⊙γ, T⊙conjγ> = Σγ²·|T|² = 0）；
    # ramp_T 的 |T|² 非均匀，该内积不为零，故只以方向误差与行残差判定。
    b_zero_expected = case == "flat_T"

    return {
        "case": case,
        "spec": {
            "n_groups": fx["n_groups"],
            "n_ch": fx["n_ch"],
            "n_f": fx["n_f"],
            "channel_direction_re_im": [_complex_pair(v) for v in gamma],
            "group_coeffs_re_im": [_complex_pair(v) for v in alpha],
            "fixture": "pool[g, c, f] = T[c, f] * (1 + alpha[g] * gamma[c])",
            "T_shape": list(fx["T"].shape),
        },
        "production_basis": {
            "rank_effective": production["rank_effective"],
            "near_parallel": production["near_parallel"],
            "anchor_idx": [int(v) for v in production["anchor_idx"]],
            "ortho_residual_rel_max": float(np.max(production["ortho_residual_rel"])),
            "local_replica_gap_rel": prod_gap,
        },
        "direction_recovery": {
            "error_to_true_max": float(max(dir_err_true, 0.0)),
            "error_to_conjugate_min": float(max(dir_err_conj, 0.0)),
            "conjugate_separation": float(phase_aligned_error(np.conj(gamma), gamma)),
        },
        "row_reconstruction": {
            "row_rel_residual_max": float(recon["row_rel_residual_max"]),
            "coeff_rel_error_max": float(max(coeff_errs)),
            "second_coeff_abs_max": float(max(abs(complex(v)) for v in recon["second_coeff_b"])),
        },
        "negative_control": {
            "variant": "v = vh[0].conj()（旧实现：相对通道相位反转）",
            "direction_error_to_true_min": float(max(mut_dir_err_true, 0.0)),
            "row_rel_residual_min": float(mut_recon["row_rel_residual_min"]),
            "second_coeff_abs_max": float(max(mut_b)),
            "second_coeff_zero_expected": bool(b_zero_expected),
            "detected": bool(
                mut_dir_err_true > NEGATIVE_DIRECTION_MIN
                and mut_recon["row_rel_residual_min"] > NEGATIVE_ROW_RESIDUAL_MIN
                and (
                    max(mut_b) < NEGATIVE_SECOND_COEFF_MAX
                    if b_zero_expected
                    else True
                )
            ),
        },
    }


def evaluate_real_fixture_blindness(*, n_f: int = 4) -> Dict[str, Any]:
    """旧夹具形态（实方向 + 各组共用同一 ``T``）：生产与旧式变异完全不可分辨。"""
    fx = real_direction_fixture(n_f=n_f)
    pool = fx["pool"]
    gamma = fx["gamma"]
    production = N.build_rank2_basis(pool, ref_pos=0, mode_form="modulation")
    mutant = _extract_basis(pool, legacy_conjugate=True, ref_pos=0)
    v_prod = recover_channel_direction(production["T"], production["D1"])
    v_mut = recover_channel_direction(mutant["T"], mutant["D1"])
    r_prod = reconstruct_rows(production["T"], production["D1"], pool)
    r_mut = reconstruct_rows(mutant["T"], mutant["D1"], pool)
    return {
        "channel_direction_re_im": [_complex_pair(v) for v in gamma],
        "conjugate_is_equivalent": bool(phase_aligned_error(np.conj(gamma), gamma) <= 1e-12),
        "direction_error_production": float(phase_aligned_error(v_prod, gamma)),
        "direction_error_legacy_mutant": float(phase_aligned_error(v_mut, gamma)),
        "row_rel_residual_production": float(r_prod["row_rel_residual_max"]),
        "row_rel_residual_legacy_mutant": float(r_mut["row_rel_residual_max"]),
        "conclusion": (
            "实方向 + 共用 T 的旧夹具下，conj 只差全局相位：生产与旧式变异的行残差"
            "同为 ~1e-16、方向误差同为 0，因此旧夹具在数学上无法发现该缺陷"
            "（不是测试写得不够多，而是缺“复通道相位 + 组均值 T”这一维）"
        ),
    }


def run(*, n_f: int = 4) -> Dict[str, Any]:
    cases = [evaluate_case(case, n_f=n_f) for case in FIXTURE_CASES]
    blindness = evaluate_real_fixture_blindness(n_f=n_f)
    direction_ok = all(c["direction_recovery"]["error_to_true_max"] < DIRECTION_OK_MAX for c in cases)
    rows_ok = all(
        c["row_reconstruction"]["row_rel_residual_max"] < ROW_RESIDUAL_OK_MAX
        and c["row_reconstruction"]["coeff_rel_error_max"] < COEFF_REL_OK_MAX
        for c in cases
    )
    mutations_ok = all(c["negative_control"]["detected"] for c in cases)
    replica_ok = all(c["production_basis"]["local_replica_gap_rel"] <= 1e-12 for c in cases)
    verdict = {
        "direction_recovered": bool(direction_ok),
        "rows_reconstructed": bool(rows_ok),
        "second_coeff_matches_alpha": bool(rows_ok),
        "negative_control_detected": bool(mutations_ok),
        "local_replica_matches_production": bool(replica_ok),
        "real_fixture_blind_fixture": bool(blindness["conjugate_is_equivalent"]),
        "pass": bool(direction_ok and rows_ok and mutations_ok and replica_ok),
    }
    return {
        "contract": CONTRACT_VERSION,
        "synthetic_only": True,
        "real_dat_files_read": 0,
        "defect": {
            "status": "found_and_fixed_in_this_commit",
            "location": "solutions/A/a_e0_n0.py::build_rank2_basis（逐频点 SVD 取通道权重）",
            "pre_fix": "v = vh[0].conj()",
            "post_fix": "v = vh[0]",
            "mechanism": (
                "A = U·S·Vh ⇒ A[g,c] = Σ s_k u_k[g]·conj(v_k[c])，行方向是 conj(v_k)，"
                "而 Vh 的行正是 conj(v_k)；conj 一次即把相对通道相位整体反转"
            ),
            "why_old_tests_missed_it": (
                "旧夹具有两个盲点：① 通道方向为实向量；② 所有组共用同一个 T_c，"
                "于是 rel_dev = dev/T 恰好等于实 pattern，conj 只差全局相位。真实/合成"
                "流水线里 T 是**组均值**，rel_dev = dev/T 带着 T 的逐通道相位，行方向"
                "本身是复向量——`(1, e^{2πi/3}, e^{4πi/3})/√3` 才能在这一维上分辨"
            ),
            "numerical_impact": {
                "fixture_direction_error_pre_fix": 1.414213562373095,
                "fixture_row_residual_pre_fix": 0.5,
                "fixture_second_coeff_pre_fix": 0.0,
                "n0_synthetic_decisions_changed": False,
                "n0_synthetic_p1_min_db": {"pre_fix": 23.1790920971532, "post_fix": 26.1151960826842},
                "n0_synthetic_p2_min_db": {"pre_fix": 24.5702399348025, "post_fix": 28.3957160700641},
                "n0_synthetic_c2_over_c1_p1_db": {"pre_fix": 11.1677360141308, "post_fix": 14.1038399996618},
                "n0_synthetic_c2_over_c1_p2_db": {"pre_fix": 11.6502400785097, "post_fix": 15.4757162137713},
                "n0_synthetic_artifact_sha256": {
                    "pre_fix": {
                        "n0_synthetic_results.json": "e2835b91ecc688b7f7bdf0ea427176e93911054b70820c658e53ccdb5631b6b0",
                        "N0_SYNTHETIC.md": "0c342a4f896c31a07fc7e4760c86d7af3274a62ab9958aab712b8bd2d27fbc5a",
                    },
                    "post_fix": {
                        "n0_synthetic_results.json": "731d593581bf5182fbee2311968dc76764228bd1170fd2565c163684176ffad8",
                        "N0_SYNTHETIC.md": "90259f7ed388b1d44febf520932b445c979c13338a8d707bdf9e92019237025d",
                    },
                    "pre_fix_reproduced_at_207510c": True,
                },
                "note": (
                    "合成夹具的通道相对偏差是复向量（T 为组均值），所以修复让秩 2 的抑制量"
                    "真实提升（P1 min +2.94 dB、P2 min +3.83 dB，c2/c1 增益 +2.94/+3.83 dB）；"
                    "判定结论不变：L1=PASS、L2=FAIL（S8）、P3/P4/C8′ 仍 PASS。产物已重新生成"
                    "并登记新 SHA256，旧值可用 207510c 逐字节复现"
                ),
            },
        },
        "scope": {
            "kernel_changed": False,
            "numeric_core_untouched": True,
            "build_rank2_basis_changed": True,
            "artifacts_regenerated": True,
            "note": (
                "只改 build_rank2_basis 的取向量约定；solve_bundle / supp_from_z / "
                "pslr_from_p / pnr_from_z / select_d_hat 与门槛函数未动；"
                "n0/synthetic 产物因该修复重新生成并另行登记 SHA256。"
            ),
        },
        "claim": (
            "由 rel_dev（组 × 通道）SVD 取行方向 v = vh[0] 得到的通道模态，能在允许任意"
            "全局相位的判据下恢复解析方向 (1, e^{2πi/3}, e^{4πi/3})/√3，并以 b_g = α_g "
            "精确重建训练数据的行方向；旧式 v = vh[0].conj() 在同一夹具上失败（正是修复前的实现）。"
        ),
        "cases": cases,
        "real_fixture_blindness": blindness,
        "thresholds": {
            "direction_ok_max": DIRECTION_OK_MAX,
            "row_residual_ok_max": ROW_RESIDUAL_OK_MAX,
            "coeff_rel_ok_max": COEFF_REL_OK_MAX,
            "negative_direction_min": NEGATIVE_DIRECTION_MIN,
            "negative_row_residual_min": NEGATIVE_ROW_RESIDUAL_MIN,
            "negative_second_coeff_max": NEGATIVE_SECOND_COEFF_MAX,
        },
        "verdict": verdict,
    }


def render_markdown(doc: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# N0 复数秩一通道模态回归（`%s`）" % doc["contract"])
    lines.append("")
    lines.append(
        "> 合成专用回归：`real_dat_files_read = %d`，未改数值内核；`build_rank2_basis` 的"
        "取向量约定在本次修复（`vh[0].conj()` → `vh[0]`），`n0/synthetic` 产物已重新生成并另行登记 SHA256。"
        % int(doc["real_dat_files_read"])
    )
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    v = doc["verdict"]
    lines.append("| 项 | 结果 |")
    lines.append("|---|---|")
    lines.append("| 方向恢复（允许任意全局相位） | **%s** |" % ("PASS" if v["direction_recovered"] else "FAIL"))
    lines.append("| 行方向重建 + `b_g = α_g` | **%s** |" % ("PASS" if v["rows_reconstructed"] else "FAIL"))
    lines.append("| 变异（旧式 `vh[0].conj()`）可探测 | **%s** |" % ("PASS" if v["negative_control_detected"] else "FAIL"))
    lines.append("| 本地同式实现 == 生产 `D_1` | **%s** |" % ("PASS" if v["local_replica_matches_production"] else "FAIL"))
    lines.append("| 总体 | **%s** |" % ("PASS" if v["pass"] else "FAIL"))
    lines.append("")
    lines.append("## 逐夹具数值")
    lines.append("")
    lines.append("| 夹具 | 方向误差（对真值） | 方向误差（对共轭） | 行重建残差 max | `b−α` 相对误差 max | 负例方向误差 | 负例行残差 min |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in doc["cases"]:
        lines.append(
            "| `%s` | %.3e | %.6f | %.3e | %.3e | %.6f | %.6f |"
            % (
                c["case"],
                c["direction_recovery"]["error_to_true_max"],
                c["direction_recovery"]["error_to_conjugate_min"],
                c["row_reconstruction"]["row_rel_residual_max"],
                c["row_reconstruction"]["coeff_rel_error_max"],
                c["negative_control"]["direction_error_to_true_min"],
                c["negative_control"]["row_rel_residual_min"],
            )
        )
    lines.append("")
    lines.append("## 为什么旧夹具漏检")
    lines.append("")
    b = doc["real_fixture_blindness"]
    lines.append(
        "- 实方向 `[%s]`：`conj(γ)` 与 `γ` 只差全局相位（`conjugate_is_equivalent=%s`），"
        "生产与变异的方向误差分别为 `%.3e` / `%.3e`，行残差分别为 `%.3e` / `%.3e`。"
        % (
            ", ".join("%.4f" % float(re) for re, _im in b["channel_direction_re_im"]),
            b["conjugate_is_equivalent"],
            b["direction_error_production"],
            b["direction_error_legacy_mutant"],
            b["row_rel_residual_production"],
            b["row_rel_residual_legacy_mutant"],
        )
    )
    lines.append(
        "- 复方向 `(1, e^{2πi/3}, e^{4πi/3})/√3` 满足 `Σγ = 0`（扣整组复标度不变）与 "
        "`Σγ² = 0`（`γ ⟂ conj(γ)`），因此相位反转的实现与原方向正交，判据解析可证。"
    )
    lines.append("")
    defect = doc.get("defect") or {}
    impact = defect.get("numerical_impact") or {}
    if defect:
        lines.append("## 缺陷与数值影响")
        lines.append("")
        lines.append(
            "- 位置：`%s`；修复前 `%s` → 修复后 `%s`（`%s`）。"
            % (
                defect.get("location", ""),
                defect.get("pre_fix", ""),
                defect.get("post_fix", ""),
                defect.get("status", ""),
            )
        )
        if impact:
            lines.append(
                "- 合成夹具影响：`P1 min` **%.4f → %.4f dB**、`P2 min` **%.4f → %.4f dB**、"
                "`c2/c1` P1 **%.4f → %.4f dB**、`c2/c1` P2 **%.4f → %.4f dB**；"
                "判定不变（`L1=PASS`、`L2=FAIL（S8）`、`P3/P4/C8′` 仍 PASS）。"
                % (
                    impact["n0_synthetic_p1_min_db"]["pre_fix"],
                    impact["n0_synthetic_p1_min_db"]["post_fix"],
                    impact["n0_synthetic_p2_min_db"]["pre_fix"],
                    impact["n0_synthetic_p2_min_db"]["post_fix"],
                    impact["n0_synthetic_c2_over_c1_p1_db"]["pre_fix"],
                    impact["n0_synthetic_c2_over_c1_p1_db"]["post_fix"],
                    impact["n0_synthetic_c2_over_c1_p2_db"]["pre_fix"],
                    impact["n0_synthetic_c2_over_c1_p2_db"]["post_fix"],
                )
            )
            pre = impact.get("n0_synthetic_artifact_sha256", {}).get("pre_fix", {})
            post = impact.get("n0_synthetic_artifact_sha256", {}).get("post_fix", {})
            if pre and post:
                lines.append("")
                lines.append("| 产物 | 修复前 SHA256（`207510c` 可复现） | 修复后 SHA256 |")
                lines.append("|---|---|---|")
                for name in sorted(pre):
                    lines.append("| `%s` | `%s` | `%s` |" % (name, pre[name], post.get(name, "")))
                lines.append("")
        lines.append("")
    lines.append("## 复跑")
    lines.append("")
    lines.append("```")
    lines.append(
        "python solutions/A/a_e0_n0_channel_regression.py --out experiments/A/A-Q1-E0/n0/channel_regression"
    )
    lines.append("python solutions/A/test_a_e0_n0.py ComplexChannelRegressionTests")
    lines.append("```")
    lines.append("")
    lines.append(
        "> SHA256 按 **LF 归一化**计算（`lf_sha256`，与 `b63e217` 产物同口径）；"
        "本仓 `core.autocrlf=true`，CRLF 检出不会让复核值漂移。"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _display_path(path: Path) -> str:
    """仓库内路径用相对路径记录（保证产物字节不随输出目录变化）。"""
    try:
        return str(Path(path).resolve().relative_to(N.HERE.parents[1])).replace("\\", "/")
    except ValueError:
        return str(path)


def write_outputs(doc: Dict[str, Any], out_dir: Path, *, overwrite: bool = False) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise SystemExit("输出目录非空，拒绝覆盖：%s" % out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(json_safe(doc), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path = out_dir / "n0_channel_regression.json"
    md_path = out_dir / "N0_CHANNEL_REGRESSION.md"
    json_path.write_text(payload, encoding="utf-8", newline="\n")
    md_path.write_text(render_markdown(doc), encoding="utf-8", newline="\n")
    sums = []
    for path in sorted((json_path, md_path), key=lambda p: p.name):
        # LF 归一化（`lf_sha256` 口径），与 `b63e217` 产物一致：CRLF 检出也可复核。
        digest = N.A.lf_sha256(path)
        sums.append("%s  %s" % (digest, path.name))
    (out_dir / "SHA256SUMS.txt").write_text(
        "\n".join(sums) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        "json": _display_path(json_path),
        "markdown": _display_path(md_path),
        "sha256sums": _display_path(out_dir / "SHA256SUMS.txt"),
        "sha256": {line.split("  ")[1]: line.split("  ")[0] for line in sums},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="N0 复数秩一通道模态回归（N0-CHREG-1）")
    parser.add_argument("--out", type=Path, default=None, help="输出目录（非空则拒绝覆盖）")
    parser.add_argument("--overwrite", action="store_true", default=False, help="允许覆盖已有产物")
    parser.add_argument("--n-f", type=int, default=4, help="频点数（默认 4）")
    args = parser.parse_args(argv)

    doc = run(n_f=int(args.n_f))
    if args.out is not None:
        info = write_outputs(doc, args.out, overwrite=bool(args.overwrite))
        doc = dict(doc, outputs=info)
    print(json.dumps(json_safe(doc), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if doc["verdict"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
