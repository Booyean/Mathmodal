#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 题 D1 预处理：16000 点按 Np=4000 折迭 + 包内/包间一致性门控。

职责边界（D1，A-Q1-M0 §1.2.3 / §7.2）
  * 只做：把一个 D0 ``GroupData`` 的 ``(P, 64, 16000)`` 原始包按 ``Np = 4000``
    折迭成 4 段；在 ``[0.3, 1.7] GHz`` 带内计算包内 4 段相干增益 ``gamma``；
    对参考通道（idx=28）计算包间复相干 ``rho``、群时延漂移 ``delta``、
    去时延常相位 ``phi`` 与增益变化 ``gain_db``；只对通过门控的包做**等权、
    无相位补偿**的相干平均，输出 ``signals_folded (64, 4000) float64``；
    每个包输出完整拒绝日志。
  * **不做**：漂移补偿/时偏对齐（门控只拒绝不修正）、校准、直射波抑制、
    测距、成像、任何标签划分；不改写 D0 的 ``packets``/``sync``/``rx_mask``。
  * 真实数据诊断只读原件，不写入、不复制。

依据
  ``solutions/A/model_q1.md`` §1.2（周期边界）、§1.2.3（多包与跨行一致性门控）、
  §7.2（已批复预处理输出：``signals_folded (64,4000) float64`` + 逐包相位漂移日志）；
  ``solutions/A/data_contract.md`` D0-4（输入契约）。
  公式、阈值与依据见 ``solutions/A/fold_gate_contract.md``（D1-1）。

公开接口
  * ``GateParams``       门控阈值（带默认值与依据链接）
  * ``band_bins``        Np/fs/频带 -> rfft 整数 bin 区间
  * ``fold_group``       GroupData -> FoldedGroup（或抛 FoldGateError）
  * ``FoldGateError``    全部包被拒时抛出，携带 packet_log 与 meta

命令行
  python solutions/A/a_fold_gate.py --diagnose "附件2-测距数据/空场数据/data1"
  可选：--root <A 题目录> --json <输出文件> --npz <数组文件>
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

import a_dat_reader as d0
from a_dat_reader import (
    FS_HZ,
    N_CHANNELS,
    N_PERIOD_SAMPLES,
    REF_IDX,
    GroupData,
    IncompleteGroupError,
)

CONTRACT_VERSION = "D1-1"

# 工作频带（题面补充说明 2；对应 rfft 整数 bin 300..1700，共 1401 bin）
BAND_HZ = (0.3e9, 1.7e9)


# ---------------------------------------------------------------- 阈值
@dataclass(frozen=True)
class GateParams:
    """D1 门控阈值；依据见 ``fold_gate_contract.md`` §3。"""

    gamma_ref_min: float = 0.99
    gamma_median_min: float = 0.95
    rho_min: float = 0.99
    delta_max_ps: float = 50.0
    phase_max_rad: float = 0.1
    gain_max_db: float = 3.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gamma_ref_min": self.gamma_ref_min,
            "gamma_median_min": self.gamma_median_min,
            "rho_min": self.rho_min,
            "delta_max_ps": self.delta_max_ps,
            "phase_max_rad": self.phase_max_rad,
            "gain_max_db": self.gain_max_db,
            "rationale": "fold_gate_contract.md D1-1 §3（相干增益/相位界/sinc 时延界）",
        }


DEFAULT_GATE = GateParams()


class FoldGateError(RuntimeError):
    """没有任何包通过门控（或输入不可折叠）时抛出；不返回伪造信号。"""

    def __init__(
        self,
        group_key: str,
        message: str,
        *,
        packet_log: Optional[List[Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        self.group_key = group_key
        self.packet_log = packet_log or []
        self.meta = meta or {}
        super().__init__("group %r: %s" % (group_key, message))


# ---------------------------------------------------------------- 基础工具
def band_bins(
    n_period_samples: int = N_PERIOD_SAMPLES,
    fs_hz: float = FS_HZ,
    band_hz: Tuple[float, float] = BAND_HZ,
) -> Tuple[int, int]:
    """工作频带 -> ``rfft`` 整数 bin 闭区间 ``[k_lo, k_hi]``。

    用 ``round(f*Np/fs)`` 而不是浮点比较：``0.3e9`` 的浮点表示略小于 0.3 GHz，
    直接比较会漏掉边界 bin。Np=4000、fs=4 GHz 时为 ``(300, 1700)``，共 1401 bin。
    """
    n_period_samples = int(n_period_samples)
    k_lo = int(round(float(band_hz[0]) * n_period_samples / float(fs_hz)))
    k_hi = int(round(float(band_hz[1]) * n_period_samples / float(fs_hz)))
    nyq = n_period_samples // 2
    if not (0 < k_lo <= k_hi <= nyq):
        raise ValueError(
            "频带 %r 在 Np=%d/fs=%g 下不是有效正频率区间：k_lo=%d k_hi=%d (Nyquist bin=%d)"
            % (band_hz, n_period_samples, fs_hz, k_lo, k_hi, nyq)
        )
    return k_lo, k_hi


def _spectra(seg: np.ndarray, k_lo: int, k_hi: int) -> np.ndarray:
    """(C, Q, Np) 实段 -> (C, Q, nb) 带限正频谱（单边谱 ×2）。"""
    fr = np.fft.rfft(seg, axis=-1)
    return 2.0 * fr[..., k_lo : k_hi + 1]


def _rho(ap: np.ndarray, aa: np.ndarray) -> float:
    """归一化零延迟复相干 ``|sum ap conj(aa)| / sqrt(sum|ap|^2 sum|aa|^2)``。"""
    num = np.sum(ap * np.conj(aa))
    den = math.sqrt(float(np.sum(np.abs(ap) ** 2)) * float(np.sum(np.abs(aa) ** 2)))
    if den <= 0.0:
        return 0.0
    return float(abs(num) / den)


def _delay_and_phase(
    c: np.ndarray, freqs_hz: np.ndarray
) -> Tuple[Optional[float], Optional[float], int]:
    """对互谱 ``c`` 做加权线性相位拟合，返回 ``(delta_s, phi_rad, n_bins_used)``。

    ``delta`` 为正表示 ``ap`` 相对 ``aa`` 滞后；``phi`` 是扣掉线性时延后的
    相干常相位（``angle(sum c·exp(+j2πf·delta))``），纯时延给 0、极性翻转给 ±π。
    """
    w = np.abs(c)
    if w.size < 3 or not np.isfinite(w).all() or float(w.max()) <= 0.0:
        return None, None, 0
    mask = w >= 1e-9 * float(w.max())
    n_used = int(np.count_nonzero(mask))
    if n_used < 3:
        return None, None, n_used
    f = np.asarray(freqs_hz[mask], dtype=np.float64)
    ww = w[mask]
    ph = np.unwrap(np.angle(c[mask]))
    wsum = float(ww.sum())
    fbar = float(np.sum(ww * f) / wsum)
    phbar = float(np.sum(ww * ph) / wsum)
    sxx = float(np.sum(ww * (f - fbar) ** 2))
    if sxx <= 0.0:
        return None, None, n_used
    slope = float(np.sum(ww * (f - fbar) * (ph - phbar)) / sxx)
    delta = -slope / (2.0 * math.pi)
    # 常相位：先按估计时延把线性项扣掉，再取相干和的角度（避免 unwrap 起点 2π 歧义）
    resid = c * np.exp(1j * 2.0 * math.pi * freqs_hz * delta)
    phi = float(np.angle(np.sum(resid)))
    return delta, phi, n_used


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


# ---------------------------------------------------------------- 结果容器
@dataclass
class FoldedGroup:
    signals_folded: np.ndarray      # (64, Np) float64
    sync: np.ndarray                # (P,) int64
    accepted: np.ndarray            # (P,) bool
    segment_coherence: np.ndarray   # (P, 64) float64
    packet_log: List[Dict[str, Any]]
    meta: Dict[str, Any]
    rx_mask: np.ndarray             # (64,) bool
    channel_valid: np.ndarray       # (64,) bool
    positions_m: np.ndarray         # (64, 3) float64
    channel_summary: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def group_key(self) -> str:
        return str(self.meta.get("group_key", ""))

    @property
    def n_accepted(self) -> int:
        return int(np.count_nonzero(self.accepted))


# ---------------------------------------------------------------- 核心
def fold_group(
    group: GroupData,
    *,
    params: Optional[GateParams] = None,
    n_period_samples: Optional[int] = None,
    band_hz: Tuple[float, float] = BAND_HZ,
) -> FoldedGroup:
    """按 D1-1 契约折迭一个组并做一致性门控。

    参数
      params            门控阈值（默认 ``DEFAULT_GATE``）
      n_period_samples  单周期点数 Np；默认取 ``group.meta["n_period_samples"]``，
                        再退到 4000。要求每包点数可被 Np 整除且 Q>=2。
      band_hz           工作频带，默认 ``[0.3, 1.7] GHz``。

    返回
      ``FoldedGroup``；若没有任何包通过门控，抛 ``FoldGateError``（带日志）。
    """
    p = params or DEFAULT_GATE
    _validate_params(p)
    packets = group.packets
    if packets.ndim != 3:
        raise ValueError("packets 必须是 (P, 64, S)，实际 shape=%r" % (packets.shape,))
    n_packets, n_ch, n_samp = packets.shape
    if n_ch != N_CHANNELS:
        raise ValueError("packets 通道数应为 %d，实际 %d" % (N_CHANNELS, n_ch))
    if n_period_samples is None:
        n_period_samples = int(group.meta.get("n_period_samples", N_PERIOD_SAMPLES))
    n_period_samples = int(n_period_samples)
    if n_period_samples <= 1 or n_samp % n_period_samples != 0:
        raise ValueError("每包点数 %d 不能被 Np=%d 整除" % (n_samp, n_period_samples))
    n_seg = n_samp // n_period_samples
    if n_seg < 2:
        raise ValueError("折迭段数 Q=%d < 2，无法做包内相干门控" % n_seg)
    fs_hz = float(group.meta.get("fs_hz", FS_HZ))
    ts_s = 1.0 / fs_hz
    k_lo, k_hi = band_bins(n_period_samples, fs_hz, band_hz)
    freqs = np.fft.rfftfreq(n_period_samples, d=1.0 / fs_hz)[k_lo : k_hi + 1]

    if n_packets == 0:
        raise FoldGateError(str(group.group_key), "组内没有共同 sync 包（P=0），无法折迭")

    rx_mask = np.asarray(group.rx_mask, dtype=bool)
    channel_valid = np.asarray(group.channel_valid, dtype=bool)
    valid_rx = rx_mask & channel_valid

    # ---- Pass 1：逐包带限频谱、gamma、参考通道折迭谱
    seg_gamma = np.zeros((n_packets, N_CHANNELS), dtype=np.float64)
    gamma_active = np.zeros((n_packets, N_CHANNELS), dtype=bool)
    a_ref = np.zeros((n_packets, k_hi - k_lo + 1), dtype=np.complex128)
    ref_rms = np.zeros(n_packets, dtype=np.float64)
    ref_finite = np.zeros(n_packets, dtype=bool)
    seg_delta_ps: List[Optional[List[float]]] = [None] * n_packets
    logs: List[Dict[str, Any]] = []

    for pi in range(n_packets):
        xp = packets[pi].astype(np.float64)
        seg = xp.reshape(N_CHANNELS, n_seg, n_period_samples)
        ref_seg = seg[REF_IDX]
        ref_rms[pi] = _rms(ref_seg)
        ref_finite[pi] = bool(np.isfinite(ref_seg).all())

        if ref_finite[pi]:
            z = _spectra(seg, k_lo, k_hi)                  # (64, Q, nb)
            a = np.sum(z, axis=1)                          # (64, nb) 包内相干折迭谱
            num = np.sum(np.abs(a) ** 2, axis=1)
            den = float(n_seg) * np.sum(np.abs(z) ** 2, axis=(1, 2))
            ok = den > 0.0
            gamma_active[pi] = ok
            seg_gamma[pi][ok] = num[ok] / den[ok]
            a_ref[pi] = a[REF_IDX]
            if ok[REF_IDX]:
                ds: List[float] = []
                for q in range(1, n_seg):
                    c = z[REF_IDX, q] * np.conj(z[REF_IDX, 0])
                    delta_s, _, _ = _delay_and_phase(c, freqs)
                    if delta_s is not None:
                        ds.append(delta_s * 1e12)
                seg_delta_ps[pi] = ds

        logs.append(
            {
                "index": int(pi),
                "sync": int(group.sync[pi]),
                "ref_rms": float(ref_rms[pi]),
                "gamma_ref": None,
                "gamma_median_rx": None,
                "gamma_min_rx": None,
                "n_rx_below_gamma": None,
                "seg_delta_ps": seg_delta_ps[pi],
                "intra_pass": False,
                "inter_evaluated": False,
                "rho": None,
                "delta_ps": None,
                "phi_rad": None,
                "gain_db": None,
                "anchor": False,
                "inter_pass": False,
                "accepted": False,
                "reject_reasons": [],
            }
        )

    def _add_reason(pi: int, code: str) -> None:
        if code not in logs[pi]["reject_reasons"]:
            logs[pi]["reject_reasons"].append(code)

    # ---- 包内门控
    intra_pass = np.zeros(n_packets, dtype=bool)
    ref_ok = bool(valid_rx[REF_IDX])
    for pi in range(n_packets):
        lg = logs[pi]
        if ref_finite[pi]:
            lg["gamma_ref"] = float(seg_gamma[pi, REF_IDX])
        pool = np.flatnonzero(valid_rx & gamma_active[pi])
        if pool.size:
            g = seg_gamma[pi, pool]
            lg["gamma_median_rx"] = float(np.median(g))
            lg["gamma_min_rx"] = float(np.min(g))
            lg["n_rx_below_gamma"] = int(np.count_nonzero(g < p.gamma_ref_min))
        if not ref_ok:
            _add_reason(pi, "reference_channel_invalid")
            continue
        if not ref_finite[pi]:
            _add_reason(pi, "reference_channel_nonfinite")
            continue
        if ref_rms[pi] <= 0.0 or not gamma_active[pi, REF_IDX]:
            _add_reason(pi, "reference_channel_zero_energy")
            continue
        # 两条包内判据都检查并记录（AND 门控，但日志要给出全部违反项）
        if seg_gamma[pi, REF_IDX] < p.gamma_ref_min:
            _add_reason(pi, "intra_segment_low_gamma_ref")
        if lg["gamma_median_rx"] is None or lg["gamma_median_rx"] < p.gamma_median_min:
            _add_reason(pi, "intra_segment_low_gamma_median")
        if not logs[pi]["reject_reasons"]:
            intra_pass[pi] = True
            lg["intra_pass"] = True

    # ---- 包间门控：锚包 + rho/delta/phi/gain
    en = np.sum(np.abs(a_ref) ** 2, axis=1)
    intra_idx = np.flatnonzero(intra_pass)
    anchor: Optional[int] = None
    if intra_idx.size:
        if intra_idx.size >= 2:
            med = np.zeros(intra_idx.size, dtype=np.float64)
            for ai, pa in enumerate(intra_idx):
                vals = [
                    _rho(a_ref[pa], a_ref[pb])
                    for bi, pb in enumerate(intra_idx)
                    if bi != ai
                ]
                med[ai] = float(np.median(vals)) if vals else 0.0
            anchor = int(intra_idx[int(np.argmax(med))])
        else:
            anchor = int(intra_idx[0])

    if anchor is not None:
        a_en = float(en[anchor])
        for pi in intra_idx:
            lg = logs[int(pi)]
            lg["inter_evaluated"] = True
            lg["anchor"] = int(pi) == anchor
            if int(pi) == anchor:
                lg["rho"] = 1.0
                lg["delta_ps"] = 0.0
                lg["phi_rad"] = 0.0
                lg["gain_db"] = 0.0
            else:
                c = a_ref[int(pi)] * np.conj(a_ref[anchor])
                den = math.sqrt(float(en[int(pi)]) * a_en)
                lg["rho"] = float(abs(np.sum(c)) / den) if den > 0.0 else 0.0
                delta_s, phi, _ = _delay_and_phase(c, freqs)
                lg["delta_ps"] = None if delta_s is None else float(delta_s * 1e12)
                lg["phi_rad"] = phi
                lg["gain_db"] = (
                    float(20.0 * math.log10(float(ref_rms[int(pi)]) / float(ref_rms[anchor])))
                    if ref_rms[anchor] > 0.0 and ref_rms[int(pi)] > 0.0
                    else None
                )
                if lg["rho"] is not None and lg["rho"] < p.rho_min:
                    _add_reason(int(pi), "inter_packet_low_coherence")
                if lg["delta_ps"] is None or abs(lg["delta_ps"]) > p.delta_max_ps:
                    _add_reason(int(pi), "inter_packet_delay_drift")
                if lg["phi_rad"] is None or abs(lg["phi_rad"]) > p.phase_max_rad:
                    _add_reason(int(pi), "inter_packet_phase_offset")
                if lg["gain_db"] is None or abs(lg["gain_db"]) > p.gain_max_db:
                    _add_reason(int(pi), "inter_packet_gain_jump")
            lg["inter_pass"] = len(lg["reject_reasons"]) == 0
            lg["accepted"] = bool(lg["inter_pass"])

    accepted = np.asarray([bool(lg["accepted"]) for lg in logs], dtype=bool)
    if not accepted.any():
        meta = _build_meta(
            group, p, n_period_samples, n_seg, k_lo, k_hi, band_hz, fs_hz, ts_s,
            intra_pass, accepted, anchor, None,
        )
        raise FoldGateError(
            str(group.group_key),
            "没有任何包通过 D1 一致性门控（%d 个包全部被拒）" % n_packets,
            packet_log=logs,
            meta=meta,
        )

    # ---- 折叠：等权、无相位补偿
    acc_idx = np.flatnonzero(accepted)
    signals = np.zeros((N_CHANNELS, n_period_samples), dtype=np.float64)
    for pi in acc_idx:
        seg = packets[int(pi)].astype(np.float64).reshape(N_CHANNELS, n_seg, n_period_samples)
        signals += seg.mean(axis=1)
    signals /= float(acc_idx.size)

    meta = _build_meta(
        group, p, n_period_samples, n_seg, k_lo, k_hi, band_hz, fs_hz, ts_s,
        intra_pass, accepted, anchor, int(acc_idx.size),
    )
    channel_summary = _channel_summary(seg_gamma, gamma_active, signals, rx_mask, channel_valid)

    return FoldedGroup(
        signals_folded=signals,
        sync=np.asarray(group.sync, dtype=np.int64),
        accepted=accepted,
        segment_coherence=seg_gamma,
        packet_log=logs,
        meta=meta,
        rx_mask=rx_mask,
        channel_valid=channel_valid,
        positions_m=np.asarray(group.positions_m, dtype=np.float64),
        channel_summary=channel_summary,
    )


def _build_meta(
    group: GroupData,
    p: GateParams,
    n_period_samples: int,
    n_seg: int,
    k_lo: int,
    k_hi: int,
    band_hz: Tuple[float, float],
    fs_hz: float,
    ts_s: float,
    intra_pass: np.ndarray,
    accepted: np.ndarray,
    anchor: Optional[int],
    n_folded: Optional[int],
) -> Dict[str, Any]:
    sync = np.asarray(group.sync, dtype=np.int64)
    return {
        "contract_version": CONTRACT_VERSION,
        "group_key": str(group.group_key),
        "dataset": str(getattr(group.ref, "dataset", "")),
        "name": str(getattr(group.ref, "name", "")),
        "n_packets": int(sync.size),
        "n_intra_pass": int(np.count_nonzero(intra_pass)),
        "n_accepted": int(np.count_nonzero(accepted)),
        "accepted_sync": [int(s) for s in sync[accepted]],
        "rejected_sync": [int(s) for s in sync[~accepted]],
        "anchor_index": None if anchor is None else int(anchor),
        "anchor_sync": None if anchor is None else int(sync[anchor]),
        "n_period_samples": int(n_period_samples),
        "n_segments": int(n_seg),
        "samples_per_packet": int(group.packets.shape[2]),
        "fs_hz": float(fs_hz),
        "ts_s": float(ts_s),
        "band_hz": [float(band_hz[0]), float(band_hz[1])],
        "band_bins": [int(k_lo), int(k_hi)],
        "n_band_bins": int(k_hi - k_lo + 1),
        "gate": p.as_dict(),
        "fold": {
            "mode": "coherent_equal_weight",
            "phase_compensation": "none",
            "n_packets_folded": None if n_folded is None else int(n_folded),
            "note": "只对通过门控的包做等权平均；未做逐包旋转/时移/重采样",
        },
        "rx_mask_true_count": int(np.count_nonzero(group.rx_mask)),
        "channel_valid_true_count": int(np.count_nonzero(group.channel_valid)),
        "positions_source": "D0 positions_m 透传（M0 §2.1，A-Q1-M0 已批复 098e17d）",
    }


def _channel_summary(
    seg_gamma: np.ndarray,
    gamma_active: np.ndarray,
    signals: np.ndarray,
    rx_mask: np.ndarray,
    channel_valid: np.ndarray,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(N_CHANNELS):
        g = seg_gamma[gamma_active[:, i], i]
        out.append(
            {
                "channel": int(i),
                "rx": bool(rx_mask[i]),
                "valid": bool(channel_valid[i]),
                "gamma_median": float(np.median(g)) if g.size else None,
                "gamma_min": float(np.min(g)) if g.size else None,
                "folded_rms": _rms(signals[i]),
            }
        )
    return out


def _validate_params(p: GateParams) -> None:
    for name in ("gamma_ref_min", "gamma_median_min", "rho_min"):
        v = float(getattr(p, name))
        if not (0.0 < v <= 1.0):
            raise ValueError("%s 必须在 (0,1]，实际 %r" % (name, v))
    if p.delta_max_ps <= 0.0:
        raise ValueError("delta_max_ps 必须为正，实际 %r" % (p.delta_max_ps,))
    if not (0.0 < p.phase_max_rad <= math.pi):
        raise ValueError("phase_max_rad 必须在 (0, pi]，实际 %r" % (p.phase_max_rad,))
    if p.gain_max_db <= 0.0:
        raise ValueError("gain_max_db 必须为正，实际 %r" % (p.gain_max_db,))


# ---------------------------------------------------------------- 命令行
def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_ready(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def diagnose(
    root: Path,
    group_key: str,
    *,
    save_npz: Optional[Path] = None,
) -> Dict[str, Any]:
    """装载一个组并输出 D1 诊断 JSON（不含原始数组）。"""
    ref = d0.find_group(root, group_key)
    try:
        gd = d0.load_group(ref)
    except IncompleteGroupError as exc:
        return {
            "status": "incomplete_group",
            "error": "IncompleteGroupError",
            "message": str(exc),
            "missing_rows": list(exc.missing_rows),
            "empty_rows": list(exc.empty_rows),
        }
    try:
        res = fold_group(gd)
    except FoldGateError as exc:
        return {
            "status": "all_rejected",
            "error": "FoldGateError",
            "message": str(exc),
            "meta": exc.meta,
            "packet_log": exc.packet_log,
        }
    if save_npz is not None:
        np.savez_compressed(
            save_npz,
            signals_folded=res.signals_folded,
            sync=res.sync,
            accepted=res.accepted,
            segment_coherence=res.segment_coherence,
        )
    return {
        "status": "ok",
        "meta": res.meta,
        "packet_log": res.packet_log,
        "segment_coherence": res.segment_coherence,
        "channel_summary": res.channel_summary,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    d0._utf8_stdout()
    ap = argparse.ArgumentParser(
        description="A 题 D1：16000->4x4000 折迭与包内/包间一致性门控（只读，不做补偿/测距）"
    )
    ap.add_argument("--diagnose", metavar="GROUP_KEY", required=True, help="要诊断的 group_key")
    ap.add_argument("--root", default=str(d0._default_root()), help="A 题目录（含 附件/）")
    ap.add_argument("--json", metavar="PATH", help="把诊断结果写入 JSON（默认打印到 stdout）")
    ap.add_argument("--npz", metavar="PATH", help="把 signals_folded 等数组写入 npz")
    args = ap.parse_args(argv)

    result = diagnose(Path(args.root), args.diagnose, save_npz=Path(args.npz) if args.npz else None)
    payload = json.dumps(_json_ready(result), ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(payload + "\n", encoding="utf-8")
        print("已写入 %s（%d 字节，status=%s）" % (args.json, len(payload), result["status"]))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
