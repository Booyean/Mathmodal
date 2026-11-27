#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D1 折叠/门控测试：合成例（预期先写死/解析式给出）+ 空场 ``data1`` 单组真实诊断。

覆盖：
  * 恒等折迭（4 段全同、多包全同）
  * 包内 4 段进度时移 -> ``gamma = 0``（1 GHz 单音每段移 1 样点，解析可证）
  * 包间整样点时延（``rho = |geometric sum|``、``delta = k·Ts``）
  * 包间分数样点时延（``delta = frac·Ts``、门控通过、折叠等于双重平均）
  * 极性翻转（``rho = 1``、``|phi| = pi``，必须由相位门控拒绝，否则折叠自消）
  * 增益跳变、无效参考通道、``P = 0``、单包、无效行通道、阈值覆盖

预期值来源：
  * 纯时延/单音的解析式（本文件内独立计算，不复用 ``a_fold_gate`` 的统计量）
  * ``solutions/A/fold_gate_contract.md`` D1-1 §2–§3 的定义
  * 空场 ``data1`` 的 D0 事实：P=4、sync=[114..117]、8 行齐全

用法：
  python solutions/A/test_a_fold_gate.py            # 合成 + 真实 data1
  python solutions/A/test_a_fold_gate.py --no-real  # 只跑合成（无原始数据时）
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import a_dat_reader as D0  # noqa: E402
import a_fold_gate as FG  # noqa: E402

RESULTS: List[Dict[str, Any]] = []
NP = 4000
K_LO, K_HI = 300, 1700
BINS = np.arange(K_LO, K_HI + 1, dtype=np.float64)


# ---------------------------------------------------------------- 测试框架
def check(name: str, expected: Any, actual: Any, tol: Optional[float] = None, note: str = "") -> bool:
    if tol is not None:
        try:
            ok = bool(np.all(np.abs(np.asarray(expected, dtype=float) - np.asarray(actual, dtype=float)) <= tol))
        except (TypeError, ValueError):
            ok = False
    elif isinstance(expected, np.ndarray) or isinstance(actual, np.ndarray):
        ok = bool(np.array_equal(np.asarray(expected), np.asarray(actual)))
    else:
        ok = bool(expected == actual)
    RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL", "expected": expected, "actual": actual})
    print("[%s] %-58s expected=%r actual=%r%s" % ("PASS" if ok else "FAIL", name, expected, actual, ("  " + note) if note else ""))
    return ok


def skip(name: str, why: str) -> None:
    RESULTS.append({"name": name, "status": "SKIP", "expected": "-", "actual": why})
    print("[SKIP] %-58s %s" % (name, why))


def check_raises(name: str, exc_type: type, fn, contains: Optional[str] = None) -> bool:
    try:
        fn()
    except exc_type as exc:  # noqa: PERF203
        msg = str(exc)
        ok = contains is None or contains in msg
        RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL", "expected": exc_type.__name__, "actual": msg})
        print("[%s] %-58s %s%s" % ("PASS" if ok else "FAIL", name, exc_type.__name__, "" if ok else "  msg=%r" % msg))
        return ok
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"name": name, "status": "FAIL", "expected": exc_type.__name__, "actual": repr(exc)})
        print("[FAIL] %-58s 期望 %s，实际 %r" % (name, exc_type.__name__, exc))
        return False
    RESULTS.append({"name": name, "status": "FAIL", "expected": exc_type.__name__, "actual": "没有抛异常"})
    print("[FAIL] %-58s 期望 %s，实际没有抛异常" % (name, exc_type.__name__))
    return False


# ---------------------------------------------------------------- 合成信号
def tone_signal(f_hz: float = 1.0e9, amp: float = 12000.0, n: int = NP) -> np.ndarray:
    """单音实信号，取整为 int16（1 GHz 在 Np=4000 上恰好 1000 周，循环移样点精确）。"""
    t = np.arange(n, dtype=np.float64) / D0.FS_HZ
    return np.round(amp * np.cos(2.0 * np.pi * f_hz * t)).astype(np.int16)


def flat_signal(amp: float = 12000.0, seed: int = 20261128, n: int = NP) -> np.ndarray:
    """正频谱在 bin 300..1700 上等幅、随机相位的实信号（取整 int16）。

    等幅谱使包间时延的 ``rho`` 有闭式几何和，可独立于实现算期望。
    """
    rng = np.random.default_rng(seed)
    half = n // 2
    full = np.zeros(n, dtype=np.complex128)
    ph = rng.uniform(0.0, 2.0 * np.pi, BINS.size)
    full[BINS.astype(int)] = np.exp(1j * ph)
    full[n - BINS.astype(int)] = np.conj(full[BINS.astype(int)])
    s = np.fft.ifft(full).real
    s = s / np.max(np.abs(s)) * amp
    return np.round(s).astype(np.int16)


def frac_delay(s: np.ndarray, frac: float) -> np.ndarray:
    """循环分数样点时延（frac>0 = 滞后），保持实数输出。"""
    n = len(s)
    k = np.arange(n // 2 + 1, dtype=np.float64)
    spec = np.fft.rfft(np.asarray(s, dtype=np.float64))
    spec = spec * np.exp(-2j * np.pi * k * frac / n)
    return np.fft.irfft(spec, n=n)


def expected_rho(frac: float, n: int = NP) -> float:
    """等幅带限谱在时延 ``frac`` 样点下的归一化复相干（几何和闭式）。"""
    return float(abs(np.sum(np.exp(-2j * np.pi * BINS * frac / n))) / BINS.size)


def all_channels(seg: np.ndarray) -> np.ndarray:
    """(Q,Np) 段序列 -> 全 64 通道相同的 (64, Q*Np) int16 包。"""
    flat = np.asarray(seg, dtype=np.int16).reshape(-1)
    return np.tile(flat, (D0.N_CHANNELS, 1))


def make_group(
    packets: np.ndarray,
    *,
    key: str = "synthetic/d1",
    channel_valid: Optional[np.ndarray] = None,
) -> D0.GroupData:
    packets = np.asarray(packets)
    p = packets.shape[0]
    if channel_valid is None:
        channel_valid = np.ones(D0.N_CHANNELS, dtype=bool)
    rx = np.ones(D0.N_CHANNELS, dtype=bool)
    rx[D0.TX_IDX] = False
    return D0.GroupData(
        ref=SimpleNamespace(group_key=key, dataset="synthetic", name=key.split("/")[-1]),
        packets=packets,
        sync=np.arange(p, dtype=np.int64) + 100,
        rx_mask=rx,
        channel_valid=np.asarray(channel_valid, dtype=bool),
        positions_m=D0.channel_positions(),
        meta={"group_key": key, "n_period_samples": NP},
    )


def fold(packets: np.ndarray, params: Optional[FG.GateParams] = None, **kw: Any) -> FG.FoldedGroup:
    return FG.fold_group(make_group(packets, **{k: v for k, v in kw.items() if k == "channel_valid"}),
                         params=params)


# ---------------------------------------------------------------- 合成例
def synthetic_tests() -> None:
    # T1 频带 bin
    check("T1a band_bins", (300, 1700), FG.band_bins())
    check("T1b band bin 数", 1401, FG.band_bins()[1] - FG.band_bins()[0] + 1)

    s = flat_signal()
    one = all_channels(np.tile(s, (4, 1)).reshape(4, NP))

    # T2 恒等折迭：4 段全同、2 包全同
    g = make_group(np.stack([one, one]))
    res = FG.fold_group(g)
    check("T2a gamma 全为 1", 1.0, float(res.segment_coherence.min()), tol=1e-12)
    check("T2b 接受包数", 2, res.n_accepted)
    check("T2c 折叠 == 原段", 0.0, float(np.max(np.abs(res.signals_folded - s.astype(np.float64)))), tol=0.0)
    check("T2d 锚包=0（并列取小）", 0, res.meta["anchor_index"])
    check("T2e 折叠形状/dtype", ((64, NP), "float64"), (res.signals_folded.shape, str(res.signals_folded.dtype)))

    # T3 包内 4 段进度 1 样点时移（1 GHz 单音）：gamma = 0 解析可证
    t = tone_signal()
    segs = np.stack([np.roll(t, q) for q in range(4)])
    g3 = make_group(all_channels(segs)[None, :, :])
    check_raises("T3a 全段不同相 -> 全拒", FG.FoldGateError, lambda: FG.fold_group(g3))
    try:
        FG.fold_group(g3)
    except FG.FoldGateError as exc:
        check("T3b gamma_ref == 0", 0.0, exc.packet_log[0]["gamma_ref"], tol=1e-12)
        check(
            "T3c 拒绝原因",
            {"intra_segment_low_gamma_ref", "intra_segment_low_gamma_median"},
            set(exc.packet_log[0]["reject_reasons"]),
        )
        check("T3d 全拒 meta", 0, exc.meta["n_accepted"])

    # T4 包间整 2 样点时延 = 500 ps
    s = flat_signal()
    p0 = all_channels(np.tile(s, (4, 1)))
    p1 = all_channels(np.tile(np.roll(s, 2), (4, 1)))
    res4 = FG.fold_group(make_group(np.stack([p0, p1])))
    lg1 = res4.packet_log[1]
    check("T4a rho 闭式", expected_rho(2.0), lg1["rho"], tol=2e-4)
    check("T4b delta = +500 ps", 500.0, lg1["delta_ps"], tol=1e-3)
    check("T4c 锚包=0", 0, res4.meta["anchor_index"])
    check("T4d 只接受锚包", [True, False], res4.accepted.tolist())
    check(
        "T4e 拒绝原因",
        {"inter_packet_low_coherence", "inter_packet_delay_drift"},
        set(lg1["reject_reasons"]),
    )
    check("T4f 折叠 == 锚包段", 0.0, float(np.max(np.abs(res4.signals_folded - s.astype(np.float64)))), tol=0.0)

    # T5 包间 0.16 样点 = 40 ps 分数时延：通过门控，折叠 = 双重平均
    s = flat_signal()
    p0 = all_channels(np.tile(s, (4, 1)))
    sd = np.round(frac_delay(s.astype(np.float64), 0.16)).astype(np.int16)
    p1 = all_channels(np.tile(sd, (4, 1)))
    res5 = FG.fold_group(make_group(np.stack([p0, p1])))
    lg1 = res5.packet_log[1]
    check("T5a rho 闭式", expected_rho(0.16), lg1["rho"], tol=2e-3)
    check("T5b delta = +40 ps", 40.0, lg1["delta_ps"], tol=0.5)
    check("T5c phi ~ 0", 0.0, lg1["phi_rad"], tol=0.02)
    check("T5d 两包都接受", [True, True], res5.accepted.tolist())
    direct = (p0.astype(np.float64) + p1.astype(np.float64)) / 2.0
    direct = direct.reshape(64, 4, NP).mean(axis=1)
    check("T5e 折叠 == 双重平均", 0.0, float(np.max(np.abs(res5.signals_folded - direct))), tol=0.0)

    # T5x 阈值覆盖：delta_max=30 ps 时同一对只收锚包
    res5x = FG.fold_group(make_group(np.stack([p0, p1])), params=FG.GateParams(delta_max_ps=30.0))
    check("T5x 时延阈值覆盖", [True, False], res5x.accepted.tolist())
    check("T5y 原因", ["inter_packet_delay_drift"], res5x.packet_log[1]["reject_reasons"])

    # T6 极性翻转：rho=1、|phi|=pi，必须拒绝（否则折叠自消）
    s = flat_signal()
    p0 = all_channels(np.tile(s, (4, 1)))
    p1 = (-p0).astype(np.int16)
    res6 = FG.fold_group(make_group(np.stack([p0, p1])))
    lg1 = res6.packet_log[1]
    check("T6a rho = 1", 1.0, lg1["rho"], tol=1e-9)
    check("T6b |phi| = pi", np.pi, abs(lg1["phi_rad"]), tol=1e-6)
    check("T6c delta ~ 0", 0.0, lg1["delta_ps"], tol=1e-6)
    check("T6d 极性翻转被拒", [True, False], res6.accepted.tolist())
    check("T6e 原因仅相位", ["inter_packet_phase_offset"], lg1["reject_reasons"])
    check("T6f 折叠未被抵消", 0.0, float(np.max(np.abs(res6.signals_folded - s.astype(np.float64)))), tol=0.0)

    # T7 增益跳变 -12 dB：rho=1 但等权平均被大包主导 -> 拒绝
    s = flat_signal()
    p0 = all_channels(np.tile(s, (4, 1)))
    p1 = np.round(0.25 * p0.astype(np.float64)).astype(np.int16)
    res7 = FG.fold_group(make_group(np.stack([p0, p1])))
    lg1 = res7.packet_log[1]
    check("T7a gain = -12.04 dB", 20.0 * np.log10(0.25), lg1["gain_db"], tol=0.05)
    check("T7b 增益跳变被拒", ["inter_packet_gain_jump"], lg1["reject_reasons"])
    check("T7c 折叠 == 锚包", 0.0, float(np.max(np.abs(res7.signals_folded - s.astype(np.float64)))), tol=0.0)

    # T8 参考通道无效
    s = flat_signal()
    p0 = all_channels(np.tile(s, (4, 1)))
    cv = np.ones(64, dtype=bool)
    cv[D0.REF_IDX] = False
    g8 = make_group(np.stack([p0, p0]), channel_valid=cv)
    check_raises("T8a 无效参考通道 -> 全拒", FG.FoldGateError, lambda: FG.fold_group(g8))
    try:
        FG.fold_group(g8)
    except FG.FoldGateError as exc:
        check("T8b 原因", {"reference_channel_invalid"}, set(exc.packet_log[0]["reject_reasons"]))

    # T9 P=0
    check_raises(
        "T9 P=0 明确报错",
        FG.FoldGateError,
        lambda: FG.fold_group(make_group(np.zeros((0, 64, 16000), dtype=np.int16))),
        contains="P=0",
    )

    # T10 单包
    s = flat_signal()
    res10 = FG.fold_group(make_group(all_channels(np.tile(s, (4, 1)))[None, :, :]))
    check("T10a 单包接受", [True], res10.accepted.tolist())
    check("T10b rho=1 delta=0", (1.0, 0.0), (res10.packet_log[0]["rho"], res10.packet_log[0]["delta_ps"]))

    # T11 无效行通道（56..63）不参与中位数，折叠保持 0
    s = flat_signal()
    p = all_channels(np.tile(s, (4, 1)))
    cv = np.ones(64, dtype=bool)
    cv[56:] = False
    p[56:, :] = 0
    res11 = FG.fold_group(make_group(np.stack([p, p]), channel_valid=cv))
    check("T11a 有效通道仍通过", 2, res11.n_accepted)
    check("T11b 无效通道折叠为 0", 0.0, float(np.max(np.abs(res11.signals_folded[56:]))), tol=0.0)
    check("T11c 有效通道等于原段", 0.0, float(np.max(np.abs(res11.signals_folded[:56] - s.astype(np.float64)))), tol=0.0)

    # T12 自定义工作频带同样可跑
    res12 = FG.fold_group(make_group(np.stack([p0, p0])), band_hz=(0.4e9, 1.6e9))
    check("T12 自定义频带 bin", [400, 1600], res12.meta["band_bins"])


# ---------------------------------------------------------------- 真实 data1
def real_tests(root: Path) -> None:
    ref = D0.find_group(root, "附件2-测距数据/空场数据/data1")
    gd = D0.load_group(ref)
    check("R1a D0 共同包", [114, 115, 116, 117], gd.sync.tolist())
    res = FG.fold_group(gd)
    check("R1b P=4 全接受", (4, 4, []), (res.meta["n_packets"], res.n_accepted, res.meta["rejected_sync"]))
    check("R1c 参考通道 gamma >= 0.999", True, float(res.segment_coherence[:, D0.REF_IDX].min()) >= 0.999)
    anchor = res.meta["anchor_index"]
    others = [lg for lg in res.packet_log if not lg["anchor"]]
    check("R1d rho >= 0.9999", True, all(lg["rho"] >= 0.9999 for lg in others))
    check("R1e |delta| <= 5 ps", True, all(abs(lg["delta_ps"]) <= 5.0 for lg in others))
    check("R1f |phi| <= 0.05 rad", True, all(abs(lg["phi_rad"]) <= 0.05 for lg in others))
    check("R1g 锚包在 0..3", True, anchor in (0, 1, 2, 3))

    s = res.signals_folded
    check("R1h 形状/dtype", ((64, NP), "float64"), (s.shape, str(s.dtype)))
    check("R1i 全有限", True, bool(np.isfinite(s).all()))
    acc = res.accepted
    direct = gd.packets[acc].astype(np.float64).reshape(int(acc.sum()), 64, 4, NP).mean(axis=(0, 2))
    check("R1j 折叠 == 双重平均", 0.0, float(np.max(np.abs(s - direct))), tol=1e-9)
    check("R1k 发射通道掩码", False, bool(res.rx_mask[27]))
    check("R1l 段相干矩阵形状", (4, 64), res.segment_coherence.shape)
    check("R1m 发射通道 gamma 低（诊断）", True, float(res.segment_coherence[:, 27].max()) < 0.9)


# ---------------------------------------------------------------- 入口
def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    want_real = "--no-real" not in argv
    root = D0._default_root()
    print("== D1 折叠/门控测试 ==")
    print("实现: %s" % (HERE / "a_fold_gate.py"))
    print("真实数据根: %s" % root)
    try:
        synthetic_tests()
        if want_real:
            if (root / "附件" / "附件2-测距数据" / "空场数据" / "data1").is_dir():
                try:
                    real_tests(root)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    RESULTS.append({"name": "real_tests", "status": "FAIL", "expected": "无异常", "actual": traceback.format_exc(limit=2)})
            else:
                skip("真实 data1 测试", "数据目录不存在: %s" % root)
        else:
            skip("真实 data1 测试", "--no-real")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        RESULTS.append({"name": "synthetic_tests", "status": "FAIL", "expected": "无异常", "actual": traceback.format_exc(limit=2)})

    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    n_skip = sum(1 for r in RESULTS if r["status"] == "SKIP")
    print("\n== 汇总: %d passed, %d failed, %d skipped ==" % (n_pass, n_fail, n_skip))
    if n_fail:
        for r in RESULTS:
            if r["status"] == "FAIL":
                print("FAIL: %s expected=%r actual=%r" % (r["name"], r["expected"], r["actual"]))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
