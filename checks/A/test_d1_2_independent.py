#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-2 独立验收套件（F1 锚包极性/顺序依赖、F2 非有限值防护）。

预登记口径见 ``checks/A/d1_2_prereg.md``（D1-PREREG-2，提交于任何 D1-2
实现出现之前）。本文件不导入生产统计量来生成预期：
  * 合成例的预期来自解析式与独立实现的 ``gamma/rho/delta/phi``；
  * 真实数据只读空场 ``data1``，独立重算后再与实现日志对照。

在 D1-1（``CONTRACT_VERSION="D1-1"``）上运行，F1/F2 项会按预登记预期失败，
这是套件非空转的证明；D1-2 上应全部 PASS。

用法::

    python checks/A/test_d1_2_independent.py
    python checks/A/test_d1_2_independent.py --no-real   # 只跑合成
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
FREQS = np.fft.rfftfreq(NP, d=1.0 / FS)[K_LO:K_HI + 1]
REF = D0.REF_IDX
TX = D0.TX_IDX
RESULTS: list[dict] = []
FINDINGS: list[dict] = []
VERSION = str(getattr(FG, "CONTRACT_VERSION", "?"))


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
    print("[%s] %-60s expected=%r actual=%r%s" % (
        "PASS" if ok else "FAIL", name, expected, actual,
        ("  " + note) if note else ""))
    return ok


def check_true(name: str, cond: bool, detail: str = "") -> bool:
    return check(name, True, bool(cond), note=detail)


def finding(fid: str, severity: str, text: str) -> None:
    FINDINGS.append({"id": fid, "severity": severity, "text": text})
    print("[NOTE] %-8s %s" % (fid, text))


def mentions_nonfinite(text: str) -> bool:
    s = str(text).lower()
    return any(k in s for k in ("nonfinite", "non-finite", "非有限"))


# ---------------------------------------------------------------- 独立统计量
def my_spectra(x: np.ndarray) -> np.ndarray:
    """(C, Q, Np) -> (C, Q, 1401) 带限正频谱（单边 ×2）。"""
    return 2.0 * np.fft.rfft(x, axis=-1)[..., K_LO:K_HI + 1]


def my_gamma(z: np.ndarray) -> np.ndarray:
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
    w = np.abs(c)
    mask = w >= 1e-9 * float(w.max())
    if int(mask.sum()) < 3:
        return None, None
    f, ww, ph = FREQS[mask], w[mask], np.unwrap(np.angle(c[mask]))
    sw = float(ww.sum())
    fbar = float((ww * f).sum() / sw)
    pbar = float((ww * ph).sum() / sw)
    sxx = float((ww * (f - fbar) ** 2).sum())
    if sxx <= 0:
        return None, None
    slope = float((ww * (f - fbar) * (ph - pbar)).sum() / sxx)
    delta = -slope / (2.0 * math.pi)
    phi = float(np.angle(np.sum(c * np.exp(1j * 2.0 * math.pi * FREQS * delta))))
    return delta, phi


# ---------------------------------------------------------------- 合成数据
def bandlimited_signal(n: int = NP, amp: float = 12000.0, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    bins = np.arange(K_LO, K_HI + 1)
    full = np.zeros(n, dtype=np.complex128)
    ph = rng.uniform(0.0, 2.0 * np.pi, bins.size)
    full[bins] = np.exp(1j * ph)
    full[n - bins] = np.conj(full[bins])
    s = np.fft.ifft(full).real
    return np.round(s / np.max(np.abs(s)) * amp).astype(np.int16)


def frac_delay_real(s: np.ndarray, frac: float) -> np.ndarray:
    n = len(s)
    k = np.arange(n // 2 + 1, dtype=np.float64)
    spec = np.fft.rfft(np.asarray(s, dtype=np.float64))
    return np.fft.irfft(spec * np.exp(-2j * np.pi * k * frac / n), n=n)


def repeat_packet(seg: np.ndarray) -> np.ndarray:
    flat = np.asarray(seg, dtype=np.int16).reshape(-1)
    return np.tile(flat, (D0.N_CHANNELS, 1))


def make_group(packets: np.ndarray, *, key: str = "synthetic/d1-2",
               channel_valid: Optional[np.ndarray] = None) -> D0.GroupData:
    packets = np.asarray(packets)
    p = packets.shape[0]
    chv = np.ones(D0.N_CHANNELS, dtype=bool) if channel_valid is None else np.asarray(channel_valid, bool)
    rx = np.ones(D0.N_CHANNELS, dtype=bool)
    rx[TX] = False
    return D0.GroupData(
        ref=SimpleNamespace(group_key=key, dataset="synthetic", name=key.split("/")[-1]),
        packets=packets,
        sync=np.arange(p, dtype=np.int64) + 100,
        rx_mask=rx,
        channel_valid=chv,
        positions_m=D0.channel_positions(),
        meta={"group_key": key, "n_period_samples": NP},
    )


def accepted_labels(res, labels: list[str]) -> set[str]:
    acc = np.asarray(res.accepted, dtype=bool)
    return {labels[i] for i in range(len(labels)) if acc[i]}


def anchor_label(res, labels: list[str]) -> Optional[str]:
    a = res.meta.get("anchor_index")
    if a is None:
        return None
    return labels[int(a)]


# ---------------------------------------------------------------- F1
def run_f1() -> None:
    print("\n== F1 锚包极性 / 包顺序依赖 ==")
    s = bandlimited_signal()
    pkt = repeat_packet(np.tile(s, (4, 1)))
    flip = (-pkt).astype(np.int16)
    mean_s = s.astype(np.float64)

    # ---- F1-1 翻转包位于位置 0..3
    for pos in range(4):
        labels = ["s1", "s2", "s3"]
        labels.insert(pos, "flip")
        pmap = {"flip": flip, "s1": pkt, "s2": pkt, "s3": pkt}
        stack = np.stack([pmap[l] for l in labels])
        res = FG.fold_group(make_group(stack, key="f1-rot%d" % pos))
        acc = accepted_labels(res, labels)
        check("F1-1.%d 接受集（翻转@%d）" % (pos, pos), {"s1", "s2", "s3"}, acc)
        check("F1-1.%d 锚包属于一致簇（翻转@%d）" % (pos, pos), True,
              anchor_label(res, labels) in {"s1", "s2", "s3"})
        check("F1-1.%d 翻转包按相位拒绝（翻转@%d）" % (pos, pos), True,
              "inter_packet_phase_offset" in res.packet_log[pos]["reject_reasons"],
              note=str(res.packet_log[pos]["reject_reasons"]))
        check("F1-1.%d 折叠值逐点等于 s（翻转@%d）" % (pos, pos), 0.0,
              float(np.max(np.abs(res.signals_folded - mean_s))), tol=0.0)

    # ---- F1-2 多数在翻转侧：3 翻转 + 1 正常
    labels = ["flip1", "flip2", "flip3", "s1"]
    stack = np.stack([flip, flip, flip, pkt])
    res = FG.fold_group(make_group(stack, key="f1-majority"))
    check("F1-2a 接受多数簇（3/4）", 3, int(np.count_nonzero(res.accepted)))
    check("F1-2b 拒绝少数包", {"s1"},
          {labels[i] for i in range(4) if not res.accepted[i]})
    check("F1-2c 输出为 ±s 之一", 0.0,
          float(np.max(np.abs(np.abs(res.signals_folded) - np.abs(mean_s)))), tol=0.0)

    # ---- F1-3 2 vs 2 并列：确定 + 只接受同簇 2 包
    labels = ["s1", "flip1", "s2", "flip2"]
    stack = np.stack([pkt, flip, pkt, flip])
    res = FG.fold_group(make_group(stack, key="f1-tie"))
    check("F1-3a 并列时接受 2 包", 2, int(np.count_nonzero(res.accepted)))
    check("F1-3b 并列时输出为 ±s", 0.0,
          float(np.max(np.abs(np.abs(res.signals_folded) - np.abs(mean_s)))), tol=0.0)
    res2 = FG.fold_group(make_group(stack, key="f1-tie"))
    check("F1-3c 并列结果确定", True,
          bool(np.array_equal(res.signals_folded, res2.signals_folded)
               and np.array_equal(res.accepted, res2.accepted)))

    # ---- F1-4 5 包（3 s + 翻转 + 20 ps 延迟）循环换序
    d = np.round(frac_delay_real(s, 0.08)).astype(np.int16)
    mean4 = (3.0 * s.astype(np.float64) + d.astype(np.float64)) / 4.0
    base = ["s1", "s2", "s3", "flip", "d"]
    pmap = {"s1": pkt, "s2": pkt, "s3": pkt, "flip": flip, "d": repeat_packet(np.tile(d, (4, 1)))}
    for k in range(5):
        labels = base[k:] + base[:k]
        stack = np.stack([pmap[l] for l in labels])
        res = FG.fold_group(make_group(stack, key="f1-cycle%d" % k))
        check("F1-4.%d 接受集按标签不变（循环%d）" % (k, k),
              {"s1", "s2", "s3", "d"}, accepted_labels(res, labels))
        check("F1-4.%d 折叠值=(3s+d)/4（循环%d）" % (k, k), 0.0,
              float(np.max(np.abs(res.signals_folded - mean4))), tol=0.0,
              note="无时移补偿")

    # ---- F1-5 2 包 [s, d] 均接受，折叠=直接平均（不得对齐）
    labels = ["s1", "d"]
    res = FG.fold_group(make_group(np.stack([pkt, pmap["d"]]), key="f1-nodelay"))
    check("F1-5a 延迟 20 ps 包接受", True, bool(res.accepted[1]))
    check("F1-5b 折叠=(s+d)/2（未做时移补偿）", 0.0,
          float(np.max(np.abs(res.signals_folded - (mean_s + d.astype(np.float64)) / 2.0))),
          tol=0.0)


# ---------------------------------------------------------------- F2
def _f2_case(name: str, packets: np.ndarray, bad_pos: int,
             channel: int = 5, channel_valid: Optional[np.ndarray] = None,
             expect_good_pos: Optional[int] = None,
             expected_rows: Optional[np.ndarray] = None) -> None:
    packets = np.asarray(packets)
    orig = packets.copy()
    grp = make_group(packets, key=name, channel_valid=channel_valid)
    try:
        res = FG.fold_group(grp)
    except FG.FoldGateError as exc:
        msg_ok = mentions_nonfinite(str(exc)) or any(
            mentions_nonfinite(r) for lg in exc.packet_log for r in lg["reject_reasons"])
        check("%s 异常含非有限说明" % name, True, msg_ok, note=str(exc)[:120])
        finding("%s.group-refused" % name, "info",
                "整组被拒（安全但会丢弃同组好包）；D1-2 若采用包级隔离可保留好包。")
        check("%s 输入未被修改" % name, True, bool(np.array_equal(orig, packets, equal_nan=True)))
        return

    finite = bool(np.isfinite(res.signals_folded).all())
    check("%s 输出全有限" % name, True, finite)

    reasons = list(res.packet_log[bad_pos]["reject_reasons"])
    ch_excluded = (channel < len(res.channel_valid)) and (not bool(res.channel_valid[channel]))
    explicit = any(mentions_nonfinite(r) for r in reasons)
    if ch_excluded and np.all(res.signals_folded[channel] == 0.0):
        explicit = True
    check("%s 异常显式登记" % name, True, explicit,
          note="reasons=%r channel_valid[%d]=%r" % (reasons, channel, bool(res.channel_valid[channel])))

    if bool(res.accepted[bad_pos]) and not ch_excluded:
        check("%s 坏包被接受时不得含该通道污染" % name, True,
              bool(np.all(np.isfinite(res.signals_folded[channel]))))
    if expect_good_pos is not None and expect_good_pos < len(res.accepted):
        if not bool(res.accepted[expect_good_pos]):
            finding("%s.good-dropped" % name, "medium",
                    "坏包与好包同组时好包未进入折叠（P-F2-3 质量项）。")
        elif expected_rows is not None and not ch_excluded:
            rows = np.ones(D0.N_CHANNELS, dtype=bool)
            rows[channel] = False
            check("%s 好包仍参与折叠" % name, 0.0,
                  float(np.max(np.abs(res.signals_folded[rows] - expected_rows[rows]))),
                  tol=0.0)
    check("%s 输入未被修改" % name, True, bool(np.array_equal(orig, packets, equal_nan=True)))

    try:
        payload = {"meta": res.meta, "packet_log": res.packet_log,
                   "segment_coherence": res.segment_coherence}
        json.dumps(FG._json_ready(payload), allow_nan=False)
        check("%s 诊断 JSON 无裸 NaN" % name, True, True)
    except Exception as exc:  # noqa: BLE001
        check("%s 诊断 JSON 无裸 NaN" % name, True, False, note=repr(exc))


def run_f2() -> None:
    print("\n== F2 非有限值输入 / 输出防护 ==")
    s = bandlimited_signal()
    pkt = repeat_packet(np.tile(s, (4, 1))).astype(np.float64)
    good = pkt.copy()
    mean_s = s.astype(np.float64)
    rows_s = np.tile(mean_s, (D0.N_CHANNELS, 1))

    # F2-1 非参考通道 NaN（坏包 + 好包）
    bad = pkt.copy()
    bad[5, :] = np.nan
    _f2_case("F2-1 NaN@ch5", np.stack([bad, good]), 0, channel=5,
             expect_good_pos=1, expected_rows=rows_s)

    # F2-2 只有坏包
    _f2_case("F2-2 单车坏包", np.stack([bad]), 0, channel=5)

    # F2-3 非参考通道 Inf
    ibad = pkt.copy()
    ibad[5, :] = np.inf
    _f2_case("F2-3 Inf@ch5", np.stack([ibad, good]), 0, channel=5,
             expect_good_pos=1, expected_rows=rows_s)

    # F2-4 参考通道 NaN：必须按 reference_channel_nonfinite 拒绝
    rbad = pkt.copy()
    rbad[REF, :] = np.nan
    grp = make_group(np.stack([rbad, good]), key="f2-ref")
    res = FG.fold_group(grp)
    check("F2-4a 参考通道 NaN 拒绝", True,
          "reference_channel_nonfinite" in res.packet_log[0]["reject_reasons"])
    check("F2-4b 好包仍接受", True, bool(res.accepted[1]))
    check("F2-4c 输出=好包段", 0.0,
          float(np.max(np.abs(res.signals_folded - mean_s))), tol=0.0)

    # F2-5 channel_valid=False 的 NaN 通道不得污染输出
    inv = np.ones(D0.N_CHANNELS, dtype=bool)
    inv[5] = False
    bad2 = pkt.copy()
    bad2[5, :] = np.nan
    _f2_case("F2-5 无效通道 NaN", np.stack([bad2, bad2]), 0, channel=5,
             channel_valid=inv, expect_good_pos=1)

    # F2-6 正常输入不得被误伤
    res = FG.fold_group(make_group(np.stack([pkt, pkt]), key="f2-normal"))
    check("F2-6 正常输入全有限且接受", True,
          bool(np.isfinite(res.signals_folded).all() and res.accepted.all()))


# ---------------------------------------------------------------- 回归
def run_regression() -> None:
    print("\n== R 回归（空场 data1 与 D1-1 语义） ==")
    check("R-4 默认阈值不变", (0.99, 0.95, 0.99, 50.0, 0.1, 3.0),
          tuple(float(FG.DEFAULT_GATE.as_dict()[k]) for k in
                ("gamma_ref_min", "gamma_median_min", "rho_min",
                 "delta_max_ps", "phase_max_rad", "gain_max_db")))
    check("R-5 契约版本 D1-2", "D1-2", VERSION)

    if "--no-real" in sys.argv:
        print("[SKIP] 空场 data1（--no-real）")
        return

    root = D0._default_root()
    gd = D0.load_group(D0.find_group(root, "附件2-测距数据/空场数据/data1"))
    pk = gd.packets
    res = FG.fold_group(gd)
    pkf = pk.astype(np.float64)

    check("R-1 data1 接受集 4/4", [True, True, True, True], res.accepted.tolist())
    check("R-1b data1 sync", [114, 115, 116, 117], res.sync.tolist())
    check("R-2a 形状/dtype", ((D0.N_CHANNELS, NP), "float64"),
          (res.signals_folded.shape, str(res.signals_folded.dtype)))
    check("R-2b 全有限", True, bool(np.isfinite(res.signals_folded).all()))

    # 独立双重平均
    manual = np.mean([pkf[i].reshape(D0.N_CHANNELS, 4, NP).mean(axis=1)
                      for i in range(pkf.shape[0]) if res.accepted[i]], axis=0)
    check("R-2c 折叠=接受包双重平均", 0.0,
          float(np.max(np.abs(res.signals_folded - manual))), tol=0.0)

    # 独立统计量（以报告锚包为基准）
    z = np.stack([my_spectra(pkf[i].reshape(D0.N_CHANNELS, 4, NP)) for i in range(pkf.shape[0])])
    gam = np.stack([my_gamma(z[i]) for i in range(z.shape[0])])
    check("R-2d0 段相干矩阵全有限", True, bool(np.isfinite(res.segment_coherence).all()))
    check("R-2d 段相干矩阵一致", 0.0,
          float(np.max(np.abs(res.segment_coherence - gam))), tol=1e-12)
    check("R-2e gamma_ref 一致", 0.0,
          float(max(abs(res.packet_log[i]["gamma_ref"] - gam[i, REF]) for i in range(z.shape[0]))),
          tol=1e-12)

    anchor = int(res.meta["anchor_index"])
    a_ref = np.stack([z[i, REF].sum(axis=0) for i in range(z.shape[0])])
    rms = np.sqrt(np.mean(pkf[:, REF, :] ** 2, axis=1))
    max_rho = max_delta = max_phi = max_gain = 0.0
    for i in range(z.shape[0]):
        if i == anchor:
            exp_rho, exp_delta, exp_phi, exp_gain = 1.0, 0.0, 0.0, 0.0
        else:
            exp_rho = my_rho(a_ref[i], a_ref[anchor])
            delta, phi = my_delta_phi(a_ref[i] * np.conj(a_ref[anchor]))
            exp_delta = float(delta * 1e12) if delta is not None else float("nan")
            exp_phi = float(phi) if phi is not None else float("nan")
            exp_gain = float(20.0 * math.log10(rms[i] / rms[anchor]))
        lg = res.packet_log[i]
        max_rho = max(max_rho, abs(float(lg["rho"]) - exp_rho))
        max_delta = max(max_delta, abs(float(lg["delta_ps"]) - exp_delta))
        max_phi = max(max_phi, abs(float(lg["phi_rad"]) - exp_phi))
        max_gain = max(max_gain, abs(float(lg["gain_db"]) - exp_gain))
    check("R-3a rho 独立一致", 0.0, max_rho, tol=1e-10)
    check("R-3b delta 独立一致", 0.0, max_delta, tol=1e-3, note="ps")
    check("R-3c phi 独立一致", 0.0, max_phi, tol=1e-9, note="rad")
    check("R-3d gain 独立一致", 0.0, max_gain, tol=1e-9, note="dB")
    check("R-6 重复运行逐位一致", True,
          bool(np.array_equal(res.signals_folded, FG.fold_group(gd).signals_folded)))

    # 每个接受包都参与折叠（账本闭合）
    check("R-7 接受/拒绝账本闭合", int(res.accepted.sum()) + int((~res.accepted).sum()),
          int(res.accepted.size))
    check("R-8 接受包无拒绝原因", True,
          all(not res.packet_log[i]["reject_reasons"] for i in range(len(res.accepted))
              if res.accepted[i]))


def main() -> int:
    print("env: python=%s numpy=%s CONTRACT_VERSION=%s" % (
        sys.version.split()[0], np.__version__, VERSION))
    if VERSION != "D1-2":
        print("[WARN] 当前实现对像不是 D1-2（%r）。按预登记，F1/F2 项应失败，" % VERSION)
        print("       这正是 D1-PREREG-2 套件非空转的证明；D1-2 新 SHA 上应全部 PASS。")
    run_f1()
    run_f2()
    run_regression()
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    print("\n== 汇总: %d passed, %d failed, %d findings ==" % (n_pass, n_fail, len(FINDINGS)))
    out = HERE / "d1_2_independent_results.json"
    out.write_text(json.dumps({"contract_version": VERSION,
                               "env": {"python": sys.version.split()[0],
                                       "numpy": np.__version__},
                               "results": RESULTS, "findings": FINDINGS},
                              ensure_ascii=False, indent=2, allow_nan=False,
                              default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print("JSON -> %s" % out)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
