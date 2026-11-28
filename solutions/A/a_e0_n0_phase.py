#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-Q1-N0 相位证据：`phase__coherence` 与 `d1_min_abs_inner` 的冻结定义与计算。

契约
----
`E0-N0-PHASE-EVIDENCE-1`（配合 `E0-N0-PHASE-1`）。本模块只做**相位证据的度量**：

* ``phase__coherence[g]``：第 g 组空场与**同预登记簇内的另一组**在参考通道上的
  宽带复相干模（complex coherence magnitude），范围 ``[0, 1]``；
* ``d1_min_abs_inner``：全池秩 2 基 ``B(f) = [T(f), D_1(f)]`` 中，两基向量在
  **未退化频点**上归一化复内积模的最小值，范围 ``[0, 1]``。它是 Gram-Schmidt
  正交化的**数值恒等式证书**：正确实现下应 ``≤ 1e-6``（实测 ``0.0``–``1e-16``），
  漏做正交化时会变成 ``O(1)``。``0.0`` 是**正确实现的期望值**，不是占位符——
  该值由交付的基向量重算，不是调用方填写的常数。它不是“越大越好”的质量指标；
  第二模态的质量另由 ``d1_rank`` / ``sigma2_over_sigma1`` 诊断。

边界
----
* 只接受**已校准且已按登记偏移对齐**的复谱 ``(10, 63, n_f)``；
* 合成夹具入口只调用 `a_e0_n0.generate_synthetic_pool`（seed 固定），不读 `.dat`；
* 产物带 ``synthetic`` / ``citable=false``，不得进入论文或冻结材料；
* 不改任何数值门槛、不改数值内核。

用法
----
```sh
python solutions/A/a_e0_n0_phase.py --synthetic-fixture \
    --out tmp/phase_evidence_synthetic.json
```
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import a_e0_n0 as N0  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402

PHASE_EVIDENCE_CONTRACT = "E0-N0-PHASE-EVIDENCE-1"
RHO_MIN = 0.001
RHO_RANGE = (0.0, 1.0)
D1_INNER_RANGE = (0.0, 1.0)
#: 正确 Gram-Schmidt 后归一化 |<T, D1>| 的数值上界；> 此值即视为未正交化。
D1_ORTHO_TOL = 1e-6
#: 参考通道（与 `a_e0_n0.REF_POS` 同一锚点，即 `rx63[27]`）。
REF_POS = int(N0.REF_POS)


def complex_coherence(z_a: Sequence[complex], z_b: Sequence[complex]) -> float:
    """两复序列的宽带复相干模：``|<a,b>| / (||a||·||b||)``。

    `<a,b> = Σ_f conj(a_f)·b_f`（与 ``np.vdot`` 同口径）。由 Cauchy-Schwarz，
    返回值必在 ``[0, 1]``；任一侧全零时按 0 处理（不抛异常，便于退化诊断）。
    """
    a = np.asarray(z_a, dtype=np.complex128).ravel()
    b = np.asarray(z_b, dtype=np.complex128).ravel()
    if a.shape != b.shape:
        raise ValueError("coherence 输入形状不一致：%r vs %r" % (a.shape, b.shape))
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    value = float(abs(np.vdot(a, b)) / (na * nb))
    # 浮点舍入可能给 1+1e-16；夹回 [0,1] 但保留可审计性。
    return float(min(1.0, max(0.0, value)))


def coherence_table(
    spectra_aligned: np.ndarray,
    *,
    air_groups: Sequence[str] = N0.AIR_GROUPS,
    clusters: Sequence[Sequence[str]] = N0.CLUSTERS,
    ref_pos: int = REF_POS,
) -> List[Dict[str, Any]]:
    """逐组复相干模。

    ``spectra_aligned``：``(10, n_ch, n_f)``，已校准并已按预登记偏移对齐。
    簇内两组共享同一 ``rho``（互为锚点），顺序严格按 ``air_groups`` 预登记序。
    """
    spectra = np.asarray(spectra_aligned, dtype=np.complex128)
    if spectra.ndim != 3:
        raise ValueError("spectra_aligned 应为 (10, n_ch, n_f)，实为 %r" % (spectra.shape,))
    if spectra.shape[0] != len(air_groups):
        raise ValueError("spectra_aligned 组数 %d ≠ %d" %
                         (spectra.shape[0], len(air_groups)))
    if not (0 <= int(ref_pos) < spectra.shape[1]):
        raise ValueError("ref_pos=%r 超出通道数 %d" % (ref_pos, spectra.shape[1]))
    rows: List[Dict[str, Any]] = []
    for k, held in enumerate(clusters):
        if len(held) != 2:
            raise ValueError("簇 %d 不是两组：%r" % (k, held))
        i0 = list(air_groups).index(held[0])
        i1 = list(air_groups).index(held[1])
        rho = complex_coherence(spectra[i0, ref_pos, :], spectra[i1, ref_pos, :])
        for j, (idx, other) in enumerate(((i0, held[1]), (i1, held[0]))):
            rows.append({
                "group": held[j],
                "cluster": "C%d" % k,
                "anchor_group": other,
                "rho": rho,
                "ref_pos": int(ref_pos),
                "n_freq": int(spectra.shape[2]),
            })
    order = [list(air_groups).index(r["group"]) for r in rows]
    if order != list(range(len(air_groups))):
        raise ValueError("coherence_table 组序与预登记不符：%r" % (order,))
    return rows


def d1_inner_stats(
    T: np.ndarray,
    D1: np.ndarray,
    *,
    eps_rel: float = 1e-12,
) -> Dict[str, Any]:
    """``D_1`` 与 ``T`` 的归一化复内积统计（逐频点）。

    对每个频点 f：``e_f = |<T_f, D1_f>| / (||T_f||·||D1_f||)``；
    ``D1_f`` 近零（退化频点）时不计入，并单独计数。
    ``d1_min_abs_inner = min_f e_f``；若全部退化则为 ``0.0``。
    """
    t = np.asarray(T, dtype=np.complex128)
    d = np.asarray(D1, dtype=np.complex128)
    if t.shape != d.shape:
        raise ValueError("T/D1 形状不一致：%r vs %r" % (t.shape, d.shape))
    if t.ndim != 2:
        raise ValueError("T/D1 应为 (n_ch, n_f)，实为 %r" % (t.shape,))
    values: List[float] = []
    n_degenerate = 0
    for f in range(t.shape[1]):
        nt = float(np.linalg.norm(t[:, f]))
        nd = float(np.linalg.norm(d[:, f]))
        if nt <= 0.0 or nd <= eps_rel * max(nt, 1e-300):
            n_degenerate += 1
            continue
        values.append(float(abs(np.vdot(t[:, f], d[:, f])) / (nt * nd)))
    values_sorted = sorted(values)
    n = len(values_sorted)
    median = (values_sorted[n // 2] if n % 2
              else 0.5 * (values_sorted[n // 2 - 1] + values_sorted[n // 2])) if n else 0.0
    return {
        "d1_min_abs_inner": float(values_sorted[0]) if n else 0.0,
        "d1_max_abs_inner": float(values_sorted[-1]) if n else 0.0,
        "d1_median_abs_inner": float(median),
        "n_freq_non_degenerate": int(n),
        "n_freq_degenerate": int(n_degenerate),
        "ortho_tol": D1_ORTHO_TOL,
    }


def _basis_summary(name: str, basis: Dict[str, Any]) -> Dict[str, Any]:
    stats = d1_inner_stats(basis["T"], basis["D1"])
    out = {"basis": name,
           "d1_rank": int(basis.get("rank_effective", 2)),
           "sigma2_over_sigma1_median": float(
               basis.get("sigma2_over_sigma1_median", 0.0)),
           "near_parallel": bool(basis.get("near_parallel", False))}
    out.update(stats)
    return out


def build_phase_evidence(
    spectra_aligned: np.ndarray,
    basis_full: Dict[str, Any],
    shifts_s: Sequence[float],
    *,
    air_groups: Sequence[str] = N0.AIR_GROUPS,
    clusters: Sequence[Sequence[str]] = N0.CLUSTERS,
    ref_pos: int = REF_POS,
) -> Dict[str, Any]:
    """真实执行路径的薄包装：由 ``stack`` + 全池基 + 偏移生成相位证据块。

    `--mode execute` 已持有 ``air_cal / air_aligned / stack``；调用本函数即可得到
    与合成夹具同 schema 的核心字段，再由调用方补 ``seed``/``band_hz`` 等元数据。
    """
    shifts = [float(v) for v in shifts_s]
    rows = coherence_table(spectra_aligned, air_groups=air_groups,
                           clusters=clusters, ref_pos=ref_pos)
    return {
        "contract": PHASE_EVIDENCE_CONTRACT,
        "phase_contract": "E0-N0-PHASE-1",
        "synthetic": False,
        "citable": False,
        "air_groups": list(air_groups),
        "clusters": [{"name": "C%d" % i, "held_out": list(h)}
                     for i, h in enumerate(clusters)],
        "ref_pos": int(ref_pos),
        "rho_min": RHO_MIN,
        "rho_range": list(RHO_RANGE),
        "shifts_ns": [v * 1e9 for v in shifts],
        "coherence": rows,
        "coherence_values": [float(r["rho"]) for r in rows],
        "d1": dict(_basis_summary("full_pool", basis_full), scope="full_pool"),
        "definition": {
            "coherence": "rho_g = |sum_f conj(z_g(f))*z_h(f)| / (||z_g||*||z_h||), "
                         "z_g = x_g(ref_pos, f) after calibration+shift; "
                         "h = other group of the same prereg cluster",
            "d1_min_abs_inner": "min_f |<T(f),D1(f)>| / (||T(f)||*||D1(f)||), "
                                "full-pool rank-2 basis, degenerate bins excluded",
        },
    }


def build_synthetic_evidence(seed: int = N0.SYNTH_SEED) -> Dict[str, Any]:
    """从 `N0-SYN-1` 合成池重建相位证据（固定 seed，可逐位复跑）。

    复用 `run_synthetic` 的同一条前处理链：
    `generate_synthetic_pool → calibrate_pool → align_spectra → build_rank2_basis`。
    不运行 P1/P2 臂拟合，也不读任何真实数据。
    """
    cfg = E0S.load_config(N0.CONFIG_PATH)
    setup = E0S.Setup(cfg)
    synth = N0.generate_synthetic_pool(setup, seed=int(seed))
    shifts_s = [float(v) for v in synth["shifts_s"][: len(N0.AIR_GROUPS)]]
    fold_lock = N0.assert_fold_lock(shifts_s)
    cal = N0.calibrate_pool(synth["air"], setup)
    inv = cal["inv"]
    air_cal = [x * inv for x in synth["air"]]
    air_aligned = [N0.align_spectra(x, s, setup.f_r)
                   for x, s in zip(air_cal, shifts_s)]
    stack = np.stack(air_aligned, axis=0)

    basis_full = N0.build_rank2_basis(stack)
    evidence = build_phase_evidence(stack, basis_full, shifts_s)

    fold_d1: List[Dict[str, Any]] = []
    for fold_idx, held in enumerate(N0.CLUSTERS):
        pool = [i for i in range(len(N0.AIR_GROUPS))
                if N0.AIR_GROUPS[i] not in held]
        b = N0.build_rank2_basis(stack[pool])
        fold_d1.append(_basis_summary("p1_fold_%d" % fold_idx, b))

    evidence.update({
        "synthetic": True,
        "may_enter_paper_numbers": False,
        "seed": int(seed),
        "cluster_shift_tol_ns": float(N0.SHIFT_TOL_NS),
        "shift_max_dev_ns": float(fold_lock["max_dev_ns"]),
        "within_cluster_dev_ns": [float(v) for v in fold_lock["within_cluster_dev_ns"]],
        "n_freq": int(setup.f_r.size),
        "band_hz": {
            "first": float(setup.f_r[0]),
            "last": float(setup.f_r[-1]),
            "step": float(setup.f_r[1] - setup.f_r[0]) if setup.f_r.size > 1 else 0.0,
        },
    })
    evidence["d1"] = dict(evidence["d1"], folds=fold_d1)
    return evidence


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    raise TypeError("not JSON serializable: %r" % (type(obj),))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A-Q1-N0 phase evidence builder")
    ap.add_argument("--synthetic-fixture", action="store_true",
                    help="从 N0-SYN-1 合成池重建证据（唯一入口；不读 .dat）")
    ap.add_argument("--seed", type=int, default=N0.SYNTH_SEED)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.synthetic_fixture:
        ap.error("当前只登记了 --synthetic-fixture；真实数据证据由 --mode execute 调用函数生成")
    doc = build_synthetic_evidence(seed=args.seed)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=_json_default)
        f.write("\n")
    print(json.dumps({
        "contract": doc["contract"],
        "coherence_values": [round(v, 9) for v in doc["coherence_values"]],
        "d1_min_abs_inner": doc["d1"]["d1_min_abs_inner"],
        "d1_rank": doc["d1"]["d1_rank"],
        "out": os.path.abspath(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
