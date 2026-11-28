#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 独立复测（对 `data/a-q1-fold-gate` @ a292ace）。

验证方视角：期望值**不取自** `solutions/A/a_fold_gate.py`。
- 真实数据：用本文件独立实现的 `gamma/rho/delta/phi`（按 D1-1 契约 §2 公式）
  重算，再与 `fold_group` 的 `packet_log` 逐项对照；折叠结果另用"对接受包做
  双重平均"独立重算。
- 合成例：解析式（单音相位、带限几何和）+ 本文件自建信号，覆盖恒等折叠、
  段间失相、已知分数时延、极性翻转、增益跳变、P=0、Q=2、int16 边界。
- 对抗例：锚包极性/顺序依赖、非参考通道 NaN 传播、账本闭合、schema、确定性。

预登记口径见 `checks/A/d1_prereg.md`（D1-PREREG-1）。

用法::

    python checks/A/test_d1_independent.py            # 需要 numpy 与原始 data1
    python checks/A/test_d1_independent.py --no-real  # 只跑合成/对抗（无原始数据）
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "solutions" / "A"))

import a_dat_reader as D0  # noqa: E402
import a_fold_gate as FG  # noqa: E402

NP = 4000
FS = D0.FS_HZ
K_LO, K_HI = 300, 1700
BINS = np.arange(K_LO, K_HI + 1, dtype=np.float64)
REF = D0.REF_IDX
TX = D0.TX_IDX
RESULTS: list[dict] = []
FINDINGS: list[dict] = []


# ---------------------------------------------------------------- 框架
def check(name: str, expected: Any, actual: Any, tol: Optional[float] = None,
          note: str = "") -> bool:
    if tol is not None:
        try:
            ok = bool(np.all(np.abs(np.asarray(expected, dtype=float)
                                    - np.asarray(actual, dtype=float)) <= tol))
        except (TypeError, ValueError):
            ok = False
    elif isinstance(expected, np.ndarray) or isinstance(actual, np.ndarray):
        ok = bool(np.array_equal(np.asarray(expected), np.asarray(actual)))
    elif isinstance(expected, float) or isinstance(actual, float):
        ok = bool(float(expected) == float(actual))
    else:
        ok = bool(expected == actual)
    RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL",
                    "expected": expected, "actual": actual})
    print("[%s] %-56s expected=%r actual=%r%s" % (
        "PASS" if ok else "FAIL", name, expected, actual, ("  " + note) if note else ""))
    return ok


def check_raises(name: str, exc_type: type, fn, contains: Optional[str] = None) -> bool:
    try:
        fn()
    except exc_type as exc:
        ok = contains is None or contains in str(exc)
        RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL",
                        "expected": exc_type.__name__, "actual": str(exc)})
        print("[%s] %-56s %s%s" % ("PASS" if ok else "FAIL", name,
                                   exc_type.__name__, "" if ok else "  msg=%r" % str(exc)))
        return ok
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"name": name, "status": "FAIL", "expected": exc_type.__name__,
                        "actual": repr(exc)})
        print("[FAIL] %-56s 期望 %s，实际 %r" % (name, exc_type.__name__, exc))
        return False
    RESULTS.append({"name": name, "status": "FAIL", "expected": exc_type.__name__,
                    "actual": "没有抛异常"})
    print("[FAIL] %-56s 期望 %s，实际没有抛异常" % (name, exc_type.__name__))
    return False


def finding(fid: str, severity: str, text: str) -> None:
    FINDINGS.append({"id": fid, "severity": severity, "text": text})
    print("[NOTE] %-6s %s" % (fid, text))


# ---------------------------------------------------------------- 独立统计量（按契约 §2）
def my_spectra(x: np.ndarray) -> np.ndarray:
    """(C, Q, Np) -> (C, Q, 1401) 带限正频谱（单边 ×2，契约 §2.2）。"""
    return 2.0 * np.fft.rfft(x, axis=-1)[..., K_LO:K_HI + 1]


def my_gamma(z: np.ndarray) -> np.ndarray:
    """契约 §2.3：gamma[c] = |sum_q S|^2 / (Q * sum_q |S|^2)，按通道。"""
    a = np.sum(z, axis=1)
    num = np.sum(np.abs(a) ** 2, axis=1)
    den = z.shape[1] * np.sum(np.abs(z) ** 2, axis=(1, 2))
    out = np.full(z.shape[0], np.nan)
    ok = den > 0
    out[ok] = num[ok] / den[ok]
    return out


def my_rho(ap: np.ndarray, aa: np.ndarray) -> float:
    num = abs(np.sum(ap * np.conj(aa)))
    den = math.sqrt(float(np.sum(np.abs(ap) ** 2)) * float(np.sum(np.abs(aa) ** 2)))
    return float(num / den) if den > 0 else 0.0


def my_delta_phi(c: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """契约 §2.4 的加权直线拟合；返回 (delta_s, phi_rad)。"""
    freqs = np.fft.rfftfreq(NP, d=1.0 / FS)[K_LO:K_HI + 1]
    w = np.abs(c)
    mask = w >= 1e-9 * float(w.max())
    if int(mask.sum()) < 3:
        return None, None
    f, ww, ph = freqs[mask], w[mask], np.unwrap(np.angle(c[mask]))
    sw = float(ww.sum())
    fbar = float((ww * f).sum() / sw)
    pbar = float((ww * ph).sum() / sw)
    sxx = float((ww * (f - fbar) ** 2).sum())
    slope = float((ww * (f - fbar) * (ph - pbar)).sum() / sxx)
    delta = -slope / (2.0 * math.pi)
    phi = float(np.angle(np.sum(c * np.exp(1j * 2.0 * math.pi * freqs * delta))))
    return delta, phi


def frac_delay_real(s: np.ndarray, frac: float) -> np.ndarray:
    """带限实信号的循环分数时延（frac>0 = 滞后），独立于被测实现。"""
    n = len(s)
    k = np.arange(n // 2 + 1, dtype=np.float64)
    spec = np.fft.rfft(np.asarray(s, dtype=np.float64))
    return np.fft.irfft(spec * np.exp(-2j * np.pi * k * frac / n), n=n)


def phase_shift_real(s: np.ndarray, phi: float) -> np.ndarray:
    """带限实信号的整体相位旋转（正频谱乘 e^{jφ}，负频共轭），保持实值。"""
    n = len(s)
    spec = np.fft.rfft(np.asarray(s, dtype=np.float64))
    return np.fft.irfft(spec * np.exp(1j * phi), n=n)


def expected_rho(frac: float, n: int = NP) -> float:
    """等幅带限谱、时延 frac 样点时的归一化复相干几何和闭式。"""
    bins = np.arange(K_LO, K_HI + 1, dtype=np.float64)
    return float(abs(np.sum(np.exp(-2j * np.pi * bins * frac / n))) / bins.size)


# ---------------------------------------------------------------- 构造 GroupData
def make_group(packets: np.ndarray, *, key: str = "synthetic/d1",
               n_period: int = NP, channel_valid: Optional[np.ndarray] = None,
               sync: Optional[np.ndarray] = None) -> D0.GroupData:
    packets = np.asarray(packets)
    p = packets.shape[0]
    chv = np.ones(D0.N_CHANNELS, dtype=bool) if channel_valid is None else np.asarray(channel_valid, bool)
    rx = np.ones(D0.N_CHANNELS, dtype=bool)
    rx[TX] = False
    return D0.GroupData(
        ref=SimpleNamespace(group_key=key, dataset="synthetic", name=key.split("/")[-1]),
        packets=packets,
        sync=np.arange(p, dtype=np.int64) + 100 if sync is None else np.asarray(sync, np.int64),
        rx_mask=rx,
        channel_valid=chv,
        positions_m=D0.channel_positions(),
        meta={"group_key": key, "n_period_samples": int(n_period)},
    )


def bandlimited_signal(n: int = NP, amp: float = 12000.0, seed: int = 7) -> np.ndarray:
    """带限实信号：能量只在 bin 300..1700（对时延闭式成立）。"""
    rng = np.random.default_rng(seed)
    half = n // 2
    bins = np.arange(K_LO, K_HI + 1)
    full = np.zeros(n, dtype=np.complex128)
    ph = rng.uniform(0.0, 2.0 * np.pi, bins.size)
    full[bins] = np.exp(1j * ph)
    full[n - bins] = np.conj(full[bins])
    s = np.fft.ifft(full).real
    return np.round(s / np.max(np.abs(s)) * amp).astype(np.int16)


def repeat_packet(seg: np.ndarray) -> np.ndarray:
    """(Q,Np) 段序列 -> 64 通道相同的 (64, Q*Np) int16 包。"""
    flat = np.asarray(seg, dtype=np.int16).reshape(-1)
    return np.tile(flat, (D0.N_CHANNELS, 1))


def tone(freq: float = 1.0e9, amp: float = 12000.0, n: int = NP) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / FS
    return np.round(amp * np.cos(2.0 * np.pi * freq * t)).astype(np.int16)


# ---------------------------------------------------------------- A. 真实 data1
def run_real() -> None:
    print("\n== A. 空场 data1：独立重算 vs 被测实现 ==")
    root = D0._default_root()
    ref = D0.find_group(root, "附件2-测距数据/空场数据/data1")
    gd = D0.load_group(ref)
    res = FG.fold_group(gd)
    pk = gd.packets
    print("P=%d sync=%r accepted=%r anchor=%r" % (
        pk.shape[0], gd.sync.tolist(), res.accepted.tolist(), res.meta.get("anchor_sync")))

    # 独立 gamma 矩阵与逐段谱
    z = np.stack([my_spectra(pk[pi].astype(np.float64).reshape(D0.N_CHANNELS, 4, NP))
                  for pi in range(pk.shape[0])])
    gam = np.stack([my_gamma(z[pi]) for pi in range(pk.shape[0])])

    check("A1 segment_coherence 形状", (pk.shape[0], D0.N_CHANNELS), res.segment_coherence.shape)
    check("A2 gamma 矩阵与独立重算一致", 0.0,
          float(np.max(np.abs(res.segment_coherence - gam))), tol=1e-12)
    for pi, lg in enumerate(res.packet_log):
        check("A3.%d gamma_ref 独立一致" % pi, float(gam[pi, REF]), lg["gamma_ref"], tol=1e-12)
        pool = np.flatnonzero(res.rx_mask & res.channel_valid)
        med = float(np.median(gam[pi, pool]))
        check("A4.%d gamma_median_rx 独立一致" % pi, med, lg["gamma_median_rx"], tol=1e-12)

    # 独立 rho/delta/phi（锚包取实现给出的 anchor，仅用于同尺子对比）
    anchor = int(res.meta["anchor_index"])
    a_ref = np.sum(z, axis=2)  # (P, 64, nb)
    for pi, lg in enumerate(res.packet_log):
        if pi == anchor:
            continue
        c = a_ref[pi, REF] * np.conj(a_ref[anchor, REF])
        rho = my_rho(a_ref[pi, REF], a_ref[anchor, REF])
        delta, phi = my_delta_phi(c)
        check("A5.%d rho 独立一致" % pi, rho, lg["rho"], tol=1e-10)
        check("A6.%d delta_ps 独立一致" % pi, delta * 1e12, lg["delta_ps"], tol=1e-3)
        check("A7.%d phi_rad 独立一致" % pi, phi, lg["phi_rad"], tol=1e-9)

    # 锚包选择规则独立重算（契约 §3.2）
    intra = [i for i, lg in enumerate(res.packet_log) if lg["intra_pass"]]
    med = {}
    for i in intra:
        med[i] = float(np.median([my_rho(a_ref[i, REF], a_ref[j, REF]) for j in intra if j != i])) if len(intra) > 1 else 0.0
    my_anchor = max(intra, key=lambda i: (med[i], -i)) if intra else None
    check("A8 锚包独立重算", my_anchor, anchor)

    # 折叠 = 对接受包的双重平均（独立重算，逐点）
    acc = np.flatnonzero(res.accepted)
    direct = pk[acc].astype(np.float64).reshape(len(acc), D0.N_CHANNELS, 4, NP).mean(axis=(0, 2))
    check("A9 折叠==接受包双重平均", 0.0,
          float(np.max(np.abs(res.signals_folded - direct))), tol=0.0)
    check("A10 形状/dtype", ((D0.N_CHANNELS, NP), "float64"),
          (res.signals_folded.shape, str(res.signals_folded.dtype)))
    check("A11 全有限", True, bool(np.isfinite(res.signals_folded).all()))
    check("A12 未接受包不进入折叠", set(res.meta["accepted_sync"]),
          {int(s) for s in gd.sync[res.accepted]})

    # 账本闭合与 schema
    keys = {"index", "sync", "ref_rms", "gamma_ref", "gamma_median_rx", "gamma_min_rx",
            "n_rx_below_gamma", "seg_delta_ps", "intra_pass", "inter_evaluated", "rho",
            "delta_ps", "phi_rad", "gain_db", "anchor", "inter_pass", "accepted",
            "reject_reasons"}
    check("A13 逐包日志字段齐全", True,
          all(keys <= set(lg) for lg in res.packet_log))
    check("A14 接受/拒绝账本闭合", pk.shape[0],
          int(res.accepted.sum()) + int((~res.accepted).sum()))
    check("A15 接受包无拒绝原因", True,
          all(not lg["reject_reasons"] for lg in res.packet_log if lg["accepted"]))

    # 通道标记
    check("A16 发射通道不参与接收", False, bool(res.rx_mask[TX]))
    check("A17 有效接收通道数", 63, int(res.rx_mask.sum()))
    summ = {c["channel"]: c for c in res.channel_summary}
    check("A18 ch28 折叠 RMS 与契约一致", 9700.9, round(summ[REF]["folded_rms"], 1), tol=0.05)
    check("A19 ch27 标记 rx=False", False, summ[TX]["rx"])

    # 确定性 / 输入未改
    before = pk.copy()
    res2 = FG.fold_group(gd)
    check("A20 重复运行逐位一致", True,
          bool(np.array_equal(res.signals_folded, res2.signals_folded)))
    check("A21 输入 packets 未被修改", True, bool(np.array_equal(before, gd.packets)))

    # 与预登记事实对账（同一批段的不同度量，给量级）
    finding("N1", "info",
            "data1: 预登记段相关最小 0.9438（ch63）、1 GHz 相位漂移中位 0.61°；"
            "被测实现 gamma_ref≥0.99988、seg_delta≤2.84 ps，两者不矛盾（度量不同）。")


# ---------------------------------------------------------------- B. 合成解析例
def run_synthetic() -> None:
    print("\n== B. 合成解析例 ==")
    s = bandlimited_signal()
    pkt = repeat_packet(np.tile(s, (4, 1)))

    # B1 恒等折叠
    res = FG.fold_group(make_group(np.stack([pkt, pkt])))
    check("B1a 恒等 gamma=1", 1.0, float(res.segment_coherence.min()), tol=1e-12)
    check("B1b 折叠==原段", 0.0,
          float(np.max(np.abs(res.signals_folded - s.astype(np.float64)))), tol=0.0)
    check("B1c 两包都接受", [True, True], res.accepted.tolist())

    # B2 段间 1 样点进度时移 @1 GHz：解析 gamma=0
    t = tone()
    segs = np.stack([np.roll(t, q) for q in range(4)])
    check_raises("B2a 段间失相 -> 全拒", FG.FoldGateError,
                 lambda: FG.fold_group(make_group(repeat_packet(segs)[None, :, :])))
    try:
        FG.fold_group(make_group(repeat_packet(segs)[None, :, :]))
    except FG.FoldGateError as exc:
        check("B2b gamma_ref 解析 0", 0.0, exc.packet_log[0]["gamma_ref"], tol=1e-9)
        check("B2c 拒绝原因", {"intra_segment_low_gamma_ref",
                              "intra_segment_low_gamma_median"},
              set(exc.packet_log[0]["reject_reasons"]))

    # B3 包间已知分数时延 0.16 样点 = 40 ps（闭式 rho、delta）
    p0 = pkt
    sd = np.round(frac_delay_real(s.astype(np.float64), 0.16)).astype(np.int16)
    p1 = repeat_packet(np.tile(sd, (4, 1)))
    res3 = FG.fold_group(make_group(np.stack([p0, p1])))
    lg = res3.packet_log[1]
    check("B3a rho 闭式", expected_rho(0.16), lg["rho"], tol=3e-3)
    check("B3b delta=40 ps", 40.0, lg["delta_ps"], tol=0.6)
    check("B3c phi~0", 0.0, lg["phi_rad"], tol=0.02)
    check("B3d 两包接受", [True, True], res3.accepted.tolist())
    direct = (p0.astype(np.float64) + p1.astype(np.float64)) / 2.0
    direct = direct.reshape(D0.N_CHANNELS, 4, NP).mean(axis=1)
    check("B3e 折叠==双重平均", 0.0,
          float(np.max(np.abs(res3.signals_folded - direct))), tol=0.0)

    # B4 极性翻转（好包在前）：rho=1、|phi|=pi，仅相位拒绝
    flip = (-pkt).astype(np.int16)
    res4 = FG.fold_group(make_group(np.stack([pkt, flip])))
    lg = res4.packet_log[1]
    check("B4a rho=1", 1.0, lg["rho"], tol=1e-9)
    check("B4b |phi|=pi", math.pi, abs(lg["phi_rad"]), tol=1e-6)
    check("B4c 仅相位原因", ["inter_packet_phase_offset"], lg["reject_reasons"])
    check("B4d 折叠未被抵消", 0.0,
          float(np.max(np.abs(res4.signals_folded - s.astype(np.float64)))), tol=0.0)

    # B5 增益 -12 dB
    quiet = np.round(pkt.astype(np.float64) / 4.0).astype(np.int16)
    res5 = FG.fold_group(make_group(np.stack([pkt, quiet])))
    check("B5a gain=-12.04 dB", -12.0412, res5.packet_log[1]["gain_db"], tol=2e-3)
    check("B5b 增益跳变被拒", ["inter_packet_gain_jump"],
          res5.packet_log[1]["reject_reasons"])

    # B6 P=0
    check_raises("B6 P=0 -> FoldGateError", FG.FoldGateError,
                 lambda: FG.fold_group(make_group(np.zeros((0, D0.N_CHANNELS, 16000),
                                                           dtype=np.int16))))

    # B7 全零参考通道
    zero = np.zeros((1, D0.N_CHANNELS, 16000), dtype=np.int16)
    check_raises("B7 参考零能量 -> 全拒", FG.FoldGateError,
                 lambda: FG.fold_group(make_group(zero)))

    # B8 channel_valid=False 的通道折叠为 0 且透传
    chv = np.ones(D0.N_CHANNELS, bool)
    chv[5] = False
    pkts = np.stack([pkt, pkt]).copy()
    pkts[:, 5, :] = 0
    res8 = FG.fold_group(make_group(pkts, channel_valid=chv))
    check("B8a 无效通道折叠为 0", 0.0, float(np.max(np.abs(res8.signals_folded[5]))), tol=0.0)
    check("B8b channel_valid 透传", False, bool(res8.channel_valid[5]))
    check("B8c 有效通道不受影响", 0.0,
          float(np.max(np.abs(res8.signals_folded[6] - s.astype(np.float64)))), tol=0.0)

    # B9 Q=2（Np=8000，两段完全相同）
    half = np.tile(s[:2000], 2)                      # 4000 点
    two = np.concatenate([half, half])               # 8000 点（每段）
    pk2 = repeat_packet(np.tile(two, 2).reshape(2, 8000))
    res9 = FG.fold_group(make_group(pk2[None, :, :], n_period=8000))
    check("B9a Q=2 折叠==双重平均", 0.0,
          float(np.max(np.abs(res9.signals_folded - two.astype(np.float64)))), tol=0.0)
    check("B9b Q=2 meta", 2, res9.meta["n_segments"])

    # B10 int16 大幅值：均值折叠不回绕
    big = tone(amp=32700.0)
    res10 = FG.fold_group(make_group(np.stack([repeat_packet(np.tile(big, (4, 1)))] * 4)))
    check("B10 int16 大幅值不回绕", float(np.max(big)), float(np.max(res10.signals_folded)),
          tol=1e-6)

    # B11 参数校验
    check_raises("B11a gamma_ref_min=0 拒绝", ValueError,
                 lambda: FG.fold_group(make_group(np.stack([pkt])),
                                       params=FG.GateParams(gamma_ref_min=0.0)))
    check_raises("B11b rho_min>1 拒绝", ValueError,
                 lambda: FG.fold_group(make_group(np.stack([pkt])),
                                       params=FG.GateParams(rho_min=1.5)))
    check_raises("B11c phase_max_rad>pi 拒绝", ValueError,
                 lambda: FG.fold_group(make_group(np.stack([pkt])),
                                       params=FG.GateParams(phase_max_rad=4.0)))

    # B12 阈值依据核验：gamma ≈ 1 - sigma_phi^2
    s2 = bandlimited_signal(amp=20000.0, seed=11)
    phis = np.array([-0.15, -0.05, 0.05, 0.15])
    segs = [np.round(phase_shift_real(s2.astype(np.float64), ph)).astype(np.int16)
            for ph in phis]
    g12 = FG.fold_group(make_group(repeat_packet(np.stack(segs))[None, :, :]),
                        params=FG.GateParams(gamma_ref_min=0.9, gamma_median_min=0.9))
    gamma_pred = float(abs(np.sum(np.exp(1j * phis))) ** 2 / 16.0)
    sigma2 = float(np.mean(phis ** 2))
    check("B12a gamma 与 |sum e^{jphi}|^2/Q^2 一致", gamma_pred,
          float(g12.segment_coherence[0, REF]), tol=1e-3)
    check("B12b gamma ≈ 1 - sigma_phi^2（阈值依据）", 1.0 - sigma2,
          float(g12.segment_coherence[0, REF]), tol=5e-3)

    # B13 阈值依据核验：rho=0.99 对应约 55 ps
    check("B13 rho(55 ps)=0.9902", 0.9902, expected_rho(55e-12 / 0.25e-9), tol=1e-3)


# ---------------------------------------------------------------- C. 对抗/鲁棒性
def run_adversarial() -> None:
    print("\n== C. 对抗与鲁棒性 ==")
    s = bandlimited_signal()
    pkt = repeat_packet(np.tile(s, (4, 1)))
    flip = (-pkt).astype(np.int16)

    # C1 系列是 **D1-1 已知缺陷的刻画**：仅在 CONTRACT_VERSION=="D1-1" 成立。
    # D1-2 修复 F1 后这些旧期望必然失败，不能作为回归标准；改由
    # checks/A/test_d1_2_independent.py 的 P-F1-1..6 覆盖（D1-PREREG-2 §5）。
    if FG.CONTRACT_VERSION == "D1-1":
        # C1 极性翻转包排第一：rho 并列 -> 锚包取小序号，可能选中翻转包
        res = FG.fold_group(make_group(np.stack([flip, pkt, pkt, pkt])))
        anchor = int(res.meta["anchor_index"])
        check("C1a 锚包=0（翻转包，rho 并列取小）", 0, anchor)
        check("C1b 仅接受翻转包", [True, False, False, False], res.accepted.tolist())
        check("C1c 其余包按相位拒绝", ["inter_packet_phase_offset"], res.packet_log[1]["reject_reasons"])
        finding("F1", "medium",
                "锚包选择只用 rho 中位数，极性翻转使 rho=1 并列，翻转包排第一时被选为锚包，"
                "3 个正常包被相位门控拒绝（n_accepted=1，输出=翻转包）。折叠本身仍自洽，"
                "但结果依赖包顺序且丢弃多数正常包；建议锚包评分加入 phi 一致性（如通过相位门控的"
                "同伴数），或先按 |phi| 聚类再取最大簇。非阻断：默认数据无极性翻转。")

        # C1x 顺序敏感性：同一批包换个顺序，接受集不同
        res2 = FG.fold_group(make_group(np.stack([pkt, flip, pkt, pkt])))
        check("C1x 顺序改变接受集", [True, False, True, True], res2.accepted.tolist())
        check("C1y 恒等包折叠一致", 0.0,
              float(np.max(np.abs(res2.signals_folded - s.astype(np.float64)))), tol=0.0)
    else:
        print("[SKIP] C1a/C1b/C1c/C1x 为 D1-1 缺陷刻画（当前 %s，由 D1-2 套件替代）"
              % FG.CONTRACT_VERSION)

    # C2 非参考通道 NaN 传播（D0 int16 输入下不可达，只作为鲁棒性观察记录）
    bad = np.stack([pkt, pkt]).astype(np.float64)
    bad[0, 5, :] = np.nan
    try:
        res3 = FG.fold_group(make_group(bad))
        finite = bool(np.isfinite(res3.signals_folded).all())
        if finite:
            finding("F2", "info", "非参考通道 NaN 输入下输出仍全有限（实现已拦截或 NaN 未进入折叠）。")
        else:
            finding("F2", "low",
                    "非参考通道出现 NaN 时，gamma 把该通道排除出中位数，但折叠仍把它纳入均值，"
                    "signals_folded 出现 NaN 且无报错（契约 §4.1/§7 要求全有限）。"
                    "D0 输入为 int16，实际数据不可达；建议返回前加 np.isfinite 断言或剔除该通道。")
    except Exception as exc:  # noqa: BLE001
        finding("F2", "info", "NaN 输入被拒绝（%r），属更安全行为，仅记录。" % (exc,))

    # C3 拒绝原因码必须来自契约 §3.3 白名单
    allowed = {"reference_channel_invalid", "reference_channel_nonfinite",
               "reference_channel_zero_energy", "intra_segment_low_gamma_ref",
               "intra_segment_low_gamma_median", "inter_packet_low_coherence",
               "inter_packet_delay_drift", "inter_packet_phase_offset",
               "inter_packet_gain_jump"}
    codes = set()
    bad_segs = np.stack([np.roll(tone(), q) for q in range(4)])
    try:
        FG.fold_group(make_group(repeat_packet(bad_segs)[None, :, :]))
    except FG.FoldGateError as exc:
        codes |= {r for lg in exc.packet_log for r in lg["reject_reasons"]}
    check("C3 原因码在契约白名单内", True, codes <= allowed, note=str(sorted(codes)))

    # C4 meta 阈值与默认一致
    res4 = FG.fold_group(make_group(np.stack([pkt])))
    g = res4.meta["gate"]
    check("C4 meta gate 默认值", (0.99, 0.95, 0.99, 50.0, 0.1, 3.0),
          (g["gamma_ref_min"], g["gamma_median_min"], g["rho_min"],
           g["delta_max_ps"], g["phase_max_rad"], g["gain_max_db"]))

    # C5 单包 / 无共同包
    res5 = FG.fold_group(make_group(np.stack([pkt])))
    check("C5a 单包接受", [True], res5.accepted.tolist())
    check("C5b 单包折叠==原段", 0.0,
          float(np.max(np.abs(res5.signals_folded - s.astype(np.float64)))), tol=0.0)

    # C6 全拒时抛异常且日志完整（不返回全零）
    try:
        FG.fold_group(make_group(repeat_packet(bad_segs)[None, :, :]))
        check("C6 全拒必须抛异常", True, False)
    except FG.FoldGateError as exc:
        check("C6 全拒抛异常且带日志", True, len(exc.packet_log) == 1)
        check("C6b meta n_accepted=0", 0, exc.meta["n_accepted"])


# ---------------------------------------------------------------- 主流程
def main() -> int:
    print("env: python=%s numpy=%s" % (sys.version.split()[0], np.__version__))
    real = "--no-real" not in sys.argv
    run_synthetic()
    run_adversarial()
    if real:
        run_real()
    else:
        print("\n[SKIP] 真实 data1（--no-real）")
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    print("\n== 汇总: %d passed, %d failed, %d findings ==" % (n_pass, n_fail, len(FINDINGS)))
    out = HERE / "d1_independent_results.json"
    out.write_text(json.dumps({"env": {"python": sys.version.split()[0],
                                       "numpy": np.__version__},
                               "results": RESULTS, "findings": FINDINGS},
                              ensure_ascii=False, indent=2, allow_nan=False,
                              default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print("JSON -> %s" % out)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
