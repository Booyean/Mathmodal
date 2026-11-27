#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V0 independent preflight checks for A-Q1 (no production estimator used).

Every expected value in this file is derived from the problem statement
(PDF pages 3-7) and from the public reading helper ``get_data_iq.m``.  The
script never imports the solver/reader owned by the data-and-solver role; the
small packet parser below exists only to check the binary layout and is not a
production reader.

Usage
-----
    python checks/A/test_q1_synthetic.py
    python checks/A/test_q1_synthetic.py --data-root "<...>/附件2-测距数据"
    python checks/A/test_q1_synthetic.py --data-root "..." --verbose

Exit code is 0 only when every executed check passes.  Real-data checks are
skipped when no ``.dat`` file is reachable (a partial/sparse checkout is
normal for this repository).
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Constants fixed by the problem statement (PDF pages 3-4).
# ---------------------------------------------------------------------------
C0 = 299_792_458.0          # m/s; convention used by these checks (see doc)
FS = 4.0e9                  # Hz
TS = 1.0 / FS               # 0.25 ns
NP = 4000                   # samples per period
TP = NP * TS                # 1 us
F0 = 0.3e9                  # digital sweep start, Hz
F1 = 1.7e9                  # digital sweep stop, Hz
B = F1 - F0                 # 1.4 GHz
K = B / TP                  # 1.4e15 Hz/s
AMP = 30000.0               # digital amplitude
MAGIC = 963072              # packet magic, little-endian uint32
TYPE_SAMPLES = 102
PACKET_HEADER = 28          # magic,total,type,freq,sync,num,len
NUM_SAMPLES = 16000         # time samples per packet (4 periods)
ROW_HEIGHTS_CM = (75.5, 68.5, 61.5, 54.5, 47.5, 40.5, 33.5, 26.5)
COL_SPACING_CM = 3.5
ROW_SPACING_CM = 7.0
TX_ROW = 4                  # 1-based row
TX_COL = 8                  # 1-based global column
TX_HEIGHT_CM = ROW_HEIGHTS_CM[TX_ROW - 1]
TX_K = 4                    # 1-based antenna index inside row 4
TX_X_CM = COL_SPACING_CM * (TX_COL - 1)   # 24.5 cm


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------
def reference_waveform() -> np.ndarray:
    n = np.arange(NP)
    t = n * TS
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * t / ((NP - 1) * TS))
    phase = 2.0 * np.pi * (F0 * t + 0.5 * K * t * t)
    return AMP * np.cos(phase) * win


def analytic(x: np.ndarray) -> np.ndarray:
    """One-sided (positive-frequency) analytic signal via FFT."""
    x = np.asarray(x, dtype=float)
    length = x.shape[0]
    spec = np.fft.fft(x)
    h = np.zeros(length)
    h[0] = 1.0
    if length % 2 == 0:
        h[1:length // 2] = 2.0
        h[length // 2] = 1.0
    else:
        h[1:(length + 1) // 2] = 2.0
    return np.fft.ifft(spec * h)


def frac_shift(x: np.ndarray, delay_samples: float) -> np.ndarray:
    """Ideal (band-limited) fractional shift of a periodic real sequence."""
    x = np.asarray(x, dtype=float)
    length = x.shape[0]
    freqs = np.fft.fftfreq(length)
    shifted = np.fft.ifft(np.fft.fft(x) * np.exp(-2j * np.pi * freqs * delay_samples))
    return shifted.real


def rf_delayed(tau: float, n_samples: int = NP) -> np.ndarray:
    """Exact samples of the periodic RF waveform delayed by ``tau`` seconds.

    Implements  y[n] = s_R(n*Ts - tau)  with
    s_R(t) = A w(t mod Tp) cos(2*pi*Fs*t - phi_D(t mod Tp)).
    """
    n = np.arange(n_samples)
    t_local = (n * TS - tau) % TP
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * t_local / ((NP - 1) * TS))
    phase = 2.0 * np.pi * (F0 * t_local + 0.5 * K * t_local * t_local)
    return AMP * win * np.cos(phase + 2.0 * np.pi * FS * tau)


def circular_lag(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Signed circular lag of a relative to b and the normalised peak.

    r[k] = sum_n a[n] * b[n-k]; positive k means a is later than b.
    """
    r = np.fft.ifft(np.fft.fft(a) * np.conj(np.fft.fft(b))).real
    lag = int(np.argmax(r))
    if lag > a.shape[0] // 2:
        lag -= a.shape[0]
    denom = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
    return lag, float(r.max() / denom) if denom else 0.0


def analytic_lag(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Signed circular lag of the analytic signals of ``a`` relative to ``b``.

    Uses the same convention as :func:`circular_lag` (positive = ``a`` later),
    but removes the carrier phase first.  This is the group-delay diagnostic;
    a real-valued correlation is phase-sensitive and can move by one sample.
    """
    aa, ba = analytic(a), analytic(b)
    r = np.fft.ifft(np.fft.fft(aa) * np.conj(np.fft.fft(ba)))
    lag = int(np.argmax(np.abs(r)))
    if lag > a.shape[0] // 2:
        lag -= a.shape[0]
    denom = math.sqrt(float(np.sum(np.abs(aa) ** 2)) *
                      float(np.sum(np.abs(ba) ** 2)))
    return lag, float(np.abs(r).max() / denom) if denom else 0.0


def linear_corr(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """r[k] = sum_n x[n] y[n-k] for non-negative lags k = 0 .. len(x)-1."""
    nfft = 1 << (len(x) + len(y) - 2).bit_length()
    r = np.fft.ifft(np.fft.fft(x, nfft) * np.conj(np.fft.fft(y, nfft)))
    return r[:len(x)].real


def antenna_xy_cm(row: int, k: int) -> tuple[float, float]:
    """Array-local antenna position (x_cm, z_cm); row is 1-based."""
    if row < 1 or row > 8:
        raise ValueError("row must be 1..8")
    if k < 1 or k > 8:
        raise ValueError("k must be 1..8")
    # Odd rows use odd global columns, even rows use even columns.
    col = 2 * k - 1 if row % 2 == 1 else 2 * k
    x_cm = COL_SPACING_CM * (col - 1)
    z_cm = ROW_HEIGHTS_CM[row - 1]
    return x_cm, z_cm


# ---------------------------------------------------------------------------
# Tiny check harness
# ---------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, str]] = []
        self.failed = 0
        self.passed = 0
        self.skipped = 0

    def check(self, cid: str, name: str, expected: str, actual: str, ok: bool,
              detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        self.rows.append((cid, name, status, expected, actual))
        print(f"[{status}] {cid} {name}")
        print(f"        expected: {expected}")
        print(f"        actual  : {actual}")
        if detail:
            print(f"        note    : {detail}")

    def skip(self, cid: str, name: str, reason: str) -> None:
        self.skipped += 1
        self.rows.append((cid, name, "SKIP", reason, "-"))
        print(f"[SKIP] {cid} {name}: {reason}")

    def summary(self) -> int:
        total = self.passed + self.failed
        print("\n" + "=" * 78)
        print(f"SUMMARY: {self.passed}/{total} passed, {self.failed} failed, "
              f"{self.skipped} skipped")
        print("=" * 78)
        return 0 if self.failed == 0 else 1


def close(a: float, b: float, rel: float = 1e-9, abs_: float = 0.0) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_tx_waveform(rep: Report) -> None:
    n = np.arange(NP)
    t = n * TS
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * t / ((NP - 1) * TS))
    s = reference_waveform()

    rep.check("TX-01", "period and sample rate",
              "Np*Ts = 1.000000e-06 s, Ts = 0.25 ns",
              f"Np*Ts = {NP * TS:.6e} s, Ts = {TS * 1e9:.3f} ns",
              close(NP * TS, 1e-6) and close(TS, 0.25e-9))
    rep.check("TX-02", "chirp slope and bandwidth",
              "B = 1.4e9 Hz, K = B/Tp = 1.4e15 Hz/s",
              f"B = {B:.6e} Hz, K = {K:.6e} Hz/s",
              close(B, 1.4e9) and close(K, 1.4e15))
    rep.check("TX-03", "Hamming window endpoints and peak",
              "w[0] = w[Np-1] = 0.08, max(w) = 1.0",
              f"w[0] = {win[0]:.6f}, w[-1] = {win[-1]:.6f}, max = {win.max():.6f}",
              close(win[0], 0.08) and close(win[-1], 0.08) and close(win.max(), 1.0, 1e-3))
    rep.check("TX-04", "first sample of the digital reference",
              "s[0] = A*w[0]*cos(0) = 2400.0",
              f"s[0] = {s[0]:.6f}",
              close(s[0], 2400.0, 1e-9))
    rep.check("TX-05", "peak amplitude",
              "max|s| <= A = 30000 and max|s| > 29999",
              f"max|s| = {np.max(np.abs(s)):.3f}",
              np.max(np.abs(s)) <= AMP + 1e-6 and np.max(np.abs(s)) > 29999.0)


def check_rf_mirror(rep: Report) -> None:
    n = np.arange(NP)
    t = n * TS
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * t / ((NP - 1) * TS))
    phase = 2.0 * np.pi * (F0 * t + 0.5 * K * t * t)
    s = AMP * np.cos(phase) * win

    f_d = F0 + K * t
    f_r = FS - f_d
    f_r_at_tp = FS - (F0 + K * TP)
    rep.check("RF-01", "second-Nyquist mirror band",
              "fR(0) = 3.7 GHz, fR(Tp) = 2.3 GHz; last sample fR = 2.30035 GHz",
              f"fR[0] = {f_r[0] * 1e-9:.4f} GHz, fR[-1] = {f_r[-1] * 1e-9:.4f} GHz, "
              f"fR(Tp) = {f_r_at_tp * 1e-9:.4f} GHz",
              close(f_r[0], 3.7e9) and close(f_r_at_tp, 2.3e9)
              and close(f_r[-1], 2.30035e9, rel=1e-4) and f_r[-1] < f_r[0])
    s_r = AMP * np.cos(2.0 * np.pi * FS * t - phase) * win
    err = float(np.max(np.abs(s_r - s)))
    rep.check("RF-02", "sampling identity sR(nTs) = s[n]",
              "max|sR - s| < 1e-6",
              f"max|sR - s| = {err:.3e}",
              err < 1e-6,
              "cos(2*pi*n - phi) = cos(phi); 2*pi*Fs*n*Ts = 2*pi*n")


def check_delay_phase(rep: Report) -> None:
    s = reference_waveform()
    sa = analytic(s)
    d = 2.0 * 0.42 / C0 * FS          # round trip to a 42 cm plane
    tau = d / FS
    y = rf_delayed(tau)

    # 1. A physical RF delay is NOT a plain fractional shift of s[n].
    naive = frac_shift(s, d)
    ratio = float(np.sqrt(np.mean((y - naive) ** 2)) / np.sqrt(np.mean(s * s)))
    expected_ratio = 2.0 * abs(math.sin(math.pi * d))
    rep.check("DL-01", "physical delay vs naive digital shift",
              f"RMS(y - shift(s,d))/RMS(s) = |1-e^(j2*pi*d)| = {expected_ratio:.6f}",
              f"measured = {ratio:.6f} (d = {d:.6f} samples, tau = {tau * 1e9:.4f} ns)",
              abs(ratio - expected_ratio) < 2e-5,
              "residual is the 2nd-Nyquist carrier phase 2*pi*Fs*tau; "
              "only integer sample delays make it vanish")

    # 2. Analytic correlation recovers the positive group delay.
    ya = analytic(y)
    r = np.fft.ifft(np.fft.fft(ya) * np.conj(np.fft.fft(sa)))
    lag = int(np.argmax(np.abs(r)))
    if lag > NP // 2:
        lag -= NP
    peak = float(np.max(np.abs(r)))
    rep.check("DL-02", "delay sign and sample scale",
              f"analytic peak at +{int(round(d))} samples (nearest integer to {d:.4f})",
              f"peak at {lag:+d} samples, |peak| = {peak:.4e}",
              lag == int(round(d)),
              "positive lag = later arrival; 42 cm round trip = 11.2078 samples")

    # 3. Negative delay (advance) mirrors the sign.
    y_adv = rf_delayed(-tau)
    r_adv = np.fft.ifft(np.fft.fft(analytic(y_adv)) * np.conj(np.fft.fft(sa)))
    lag_adv = int(np.argmax(np.abs(r_adv)))
    if lag_adv > NP // 2:
        lag_adv -= NP
    rep.check("DL-03", "negative delay flips the sign",
              f"advance -tau peaks at {-int(round(d))} samples",
              f"peak at {lag_adv:+d} samples",
              lag_adv == -int(round(d)))

    # 4. Real-valued correlation loses amplitude when the carrier phase is
    #    not removed (a naive implementation can also pick the wrong lag).
    rr = np.fft.ifft(np.fft.fft(y) * np.conj(np.fft.fft(s))).real
    real_peak = float(np.max(np.abs(rr)))
    real_lag = int(np.argmax(np.abs(rr)))
    if real_lag > NP // 2:
        real_lag -= NP
    frac = real_peak / peak
    rep.check("DL-04", "real correlation loses SNR / can mislocate",
              "|real peak| / |analytic peak| < 0.6 for d = 11.2078",
              f"ratio = {frac:.4f}, real peak at {real_lag:+d} samples",
              frac < 0.6,
              "phase 2*pi*d is not removed by real-valued correlation; "
              "use the analytic/RF model or dechirp")


def check_geometry_units(rep: Report) -> None:
    d_cm = 42.0
    tau = 2.0 * (d_cm / 100.0) / C0
    d_samples = tau * FS
    rep.check("UN-01", "two-way delay and sample scale",
              "d=42 cm -> tau = 2.8019 ns -> 11.2078 samples; 1 sample = 3.7474 cm two-way",
              f"tau = {tau * 1e9:.4f} ns, samples = {d_samples:.4f}, "
              f"c/(2*Fs) = {C0 / (2 * FS) * 100:.4f} cm/sample",
              close(d_samples, 11.20775, rel=1e-5) and close(C0 / (2 * FS) * 100, 3.74741, rel=1e-5))
    rep.check("UN-02", "round-trip vs one-way convention",
              "using d/c instead of 2d/c halves the estimated range",
              "factor 2.0", True,
              "any distance estimator must divide the two-way delay by two")

    # Bistatic geometry for a plane wall at distance d.
    def bistatic_path_cm(x_rx_cm: float, z_rx_cm: float,
                         x_tx_cm: float = 0.0, z_tx_cm: float = TX_HEIGHT_CM,
                         d: float = d_cm) -> float:
        return math.sqrt((2.0 * d) ** 2 + (x_rx_cm - x_tx_cm) ** 2 +
                         (z_rx_cm - z_tx_cm) ** 2)

    path = bistatic_path_cm(28.0, TX_HEIGHT_CM)
    bias = path / 2.0 - d_cm
    rep.check("GE-01", "bistatic path for a plane target",
              "RX 28 cm beside TX, d=42 cm -> path 88.543 cm, monostatic bias +2.271 cm",
              f"path = {path:.3f} cm, bias = {bias:+.3f} cm",
              close(path, 88.543, rel=1e-4) and close(bias, 2.271, rel=1e-3),
              "path = sqrt((2d)^2 + dx^2 + dz^2)")
    bias0 = bistatic_path_cm(0.0, TX_HEIGHT_CM) / 2.0 - d_cm
    rep.check("GE-02", "broadside RX has no geometric bias",
              "RX on the TX vertical -> bias = 0",
              f"bias = {bias0:+.3e} cm", abs(bias0) < 1e-9)

    res_cm = C0 / (2 * B) * 100
    unamb_m = C0 * TP / 2
    rep.check("UN-03", "resolution and period ambiguity",
              "range resolution 10.707 cm; 1 period = 149.896 m two-way",
              f"resolution = {res_cm:.4f} cm, unambiguous range = {unamb_m:.3f} m",
              close(res_cm, 10.7069, rel=1e-4) and close(unamb_m, 149.8962, rel=1e-4))


def check_period_shift(rep: Report) -> None:
    s = reference_waveform()
    x = np.tile(s, 3)
    rep.check("PS-01", "record length",
              "12000 = 3 * Np; packet = 16000 = 4 * Np",
              f"12000 / Np = {12000 / NP:.1f}, 16000 / Np = {16000 / NP:.1f}",
              12000 == 3 * NP and 16000 == 4 * NP)

    r = linear_corr(x, s)
    peaks = [abs(float(r[k])) for k in (0, 4000, 8000)]
    spread = (max(peaks) - min(peaks)) / max(peaks)
    rep.check("PS-02", "three equal correlation peaks",
              "peaks at lags 0, 4000, 8000 differ by < 1e-6 relative",
              f"relative spread = {spread:.3e}",
              spread < 1e-6,
              "an unrestricted argmax over 12000 lags can return any of the three")

    # Restrict the search to one period.
    best_lag, best_val = 0, -1.0
    for k in range(0, 2001):
        val = float(r[k])
        if abs(val) > best_val:
            best_lag, best_val = k, abs(val)
    rep.check("PS-03", "unique lag inside one period",
              "restricted to [0, 2000] -> lag 0",
              f"lag = {best_lag}", best_lag == 0)

    # Mid-period acquisition start.
    x2 = np.roll(x, 137)
    r2 = linear_corr(x2, s)
    peak2 = int(np.argmax(np.abs(r2[:4000])))
    aligned = np.roll(x2, -137)
    blocks = [aligned[b * 4000:(b + 1) * 4000] for b in range(3)]
    same = all(np.allclose(blk, s, atol=1e-9) for blk in blocks)
    rep.check("PS-04", "mid-period start shifts the absolute lag only",
              "rolling by 137 -> lag 137; the three extracted periods still equal s",
              f"lag = {peak2}, extracted periods equal s: {same}",
              peak2 == 137 and same,
              "the absolute start phase does not change relative delays within a group")

    one_period_m = C0 * TP / 2
    lag_error_m = 4000 * C0 / (2 * FS)
    rep.check("PS-05", "cost of an unresolved period ambiguity",
              "one Np shift = 149.9 m two-way range error",
              f"one Np = {one_period_m:.3f} m, 4000 samples = {lag_error_m:.3f} m",
              close(one_period_m, 149.8962, rel=1e-4))


def check_lag_diagnostic(rep: Report) -> None:
    """A non-zero template-correlation lag does not prove t0 != 0.

    The lag measured against the ideal template is a composite of the
    acquisition start, the hardware/propagation delay and multipath.  The
    counterexample below uses t0 = 0 with a non-zero hardware delay only.
    """
    s = reference_waveform()
    d_hw = 12.4                       # samples; e.g. 3.1 ns of hardware delay
    y = rf_delayed(d_hw * TS)
    lag, corr = analytic_lag(y, s)
    rep.check("LG-01", "t0 = 0 with a non-zero hardware delay has a non-zero lag",
              f"t0 = 0; delay {d_hw:.1f} samples -> observed lag +{int(round(d_hw))}, not 0",
              f"lag = {lag:+d}, normalised |peak| = {corr:.4f}",
              lag == int(round(d_hw)) and lag != 0,
              "lag = observed template-correlation / alignment diagnostic, "
              "not an acquisition-start estimate")

    y_split = np.roll(rf_delayed(0.4 * TS), 12)   # offset 12 + hw 0.4 samples
    y_total = rf_delayed(12.4 * TS)               # offset 0 + hw 12.4 samples
    rel = float(np.max(np.abs(y_total - y_split)) / AMP)
    lag_a, _ = analytic_lag(y_total, s)
    lag_b, _ = analytic_lag(y_split, s)
    rep.check("LG-02", "same lag from two different (start, hardware) splits",
              "(offset 0, hw 12.4) and (offset 12, hw 0.4) give the same record and lag",
              f"max|diff|/A = {rel:.2e}, lags = {lag_a:+d} / {lag_b:+d}",
              rel < 1e-9 and lag_a == lag_b == int(round(12.4)),
              "the split is not identifiable from the correlation lag alone")


def check_tx_channel(rep: Report) -> None:
    all_pos = []
    for row in range(1, 9):
        for k in range(1, 9):
            all_pos.append((row, k, *antenna_xy_cm(row, k)))
    rep.check("TX-06", "64 antennas, 8 per row, staggered",
              "64 antennas; row 1 odd columns, row 2 even columns",
              f"{len(all_pos)} antennas; row1 cols = {[2 * k - 1 for k in range(1, 9)]}",
              len(all_pos) == 64)

    tx_x, tx_z = antenna_xy_cm(TX_ROW, TX_K)
    rep.check("TX-07", "transmitter position",
              "row 4, column 8 -> x = 24.5 cm, z = 54.5 cm, A4 column 4",
              f"x = {tx_x} cm, z = {tx_z} cm, A4 column = {TX_K}",
              close(tx_x, TX_X_CM) and close(tx_z, 54.5) and TX_K == 4)

    rxs = [p for p in all_pos if not (p[0] == TX_ROW and p[1] == TX_K)]
    rep.check("TX-08", "63 receivers and unique coordinates",
              "63 receivers, all (x,z) distinct",
              f"{len(rxs)} receivers, {len({(p[2], p[3]) for p in rxs})} distinct positions",
              len(rxs) == 63 and len({(p[2], p[3]) for p in rxs}) == 63)

    row4_rx = sorted(p[2] - tx_x for p in rxs if p[0] == TX_ROW)
    expected4 = [-21.0, -14.0, -7.0, 7.0, 14.0, 21.0, 28.0]
    rep.check("TX-09", "row-4 receiver offsets relative to TX",
              f"{expected4} cm",
              f"{row4_rx} cm",
              all(close(a, b) for a, b in zip(row4_rx, expected4)) and len(row4_rx) == 7)

    # Excluding the TX column changes a per-row mean by 12.5 % (7/8) when the
    # TX column is silent, as observed in the real files (RMS ~25).
    col = np.ones((16, 8))
    col[:, TX_K - 1] = 0.0
    with_tx = float(col.mean())
    without_tx = float(np.delete(col, TX_K - 1, axis=1).mean())
    rep.check("TX-10", "including the silent TX column biases row statistics",
              "mean with TX = 0.875, without = 1.0 (12.5 % low)",
              f"with = {with_tx:.4f}, without = {without_tx:.4f}",
              close(with_tx, 0.875) and close(without_tx, 1.0),
              "per-row/per-channel statistics must use the 63 receivers, not 64")


def check_int16(rep: Report) -> None:
    vals = np.array([-32768, -32767, -1, 0, 1, 32767], dtype="<i2")
    back = np.frombuffer(vals.tobytes(), dtype="<i2")
    rep.check("EX-01", "int16 round trip at the boundaries",
              str(vals.tolist()),
              str(back.tolist()),
              np.array_equal(vals, back))

    a16 = np.abs(np.int16(-32768))
    a32 = np.abs(np.int32(-32768))
    rep.check("EX-02", "abs(-32768) must be computed in int32/int64",
              "int16 abs overflows to -32768; int32 abs = 32768",
              f"int16 = {int(a16)}, int32 = {int(a32)}",
              int(a16) == -32768 and int(a32) == 32768)

    data = np.full((16, 8), -32768, dtype="<i2")
    max_abs16 = int(np.max(np.abs(data)))
    max_abs32 = int(np.max(np.abs(data.astype(np.int32))))
    rep.check("EX-03", "per-file extrema when every sample is -32768",
              "int16 path = -32768 (wrong); int32 path = 32768",
              f"int16 path = {max_abs16}, int32 path = {max_abs32}",
              max_abs16 == -32768 and max_abs32 == 32768,
              "a mixed array hides the bug: int16 max|.| returns 32767")

    sentinel = np.array([32767, 0, -32768], dtype="<i2")
    zeros = int(np.count_nonzero(sentinel == 0))
    rep.check("EX-04", "zero / sentinel counting",
              "1 zero sample; explicit -32768 count = 1",
              f"zeros = {zeros}, -32768 count = {int(np.count_nonzero(sentinel == -32768))}",
              zeros == 1 and int(np.count_nonzero(sentinel == -32768)) == 1)


def make_packet(sync: int, fill: int = 0) -> bytes:
    num, ln = NUM_SAMPLES, 16
    payload = np.full((num, 8), fill, dtype="<i2")
    payload[0, 0] = -32768
    payload[-1, 7] = 32767
    data = payload.tobytes()
    total_len = 20 + len(data)          # type..len + payload
    header = struct.pack("<IIIfIII", MAGIC, total_len, TYPE_SAMPLES, 0.0,
                         sync, num, ln)
    return header + data


def parse_packets(blob: bytes) -> list[tuple[int, np.ndarray]]:
    pos, out = 0, []
    while pos < len(blob):
        if len(blob) - pos < PACKET_HEADER:
            raise ValueError(f"truncated header at byte {pos}")
        magic, total, typ, freq, sync, num, ln = struct.unpack_from(
            "<IIIfIII", blob, pos)
        if magic != MAGIC:
            raise ValueError(f"bad magic {magic} at byte {pos}")
        if typ != TYPE_SAMPLES:
            raise ValueError(f"unexpected packet type {typ}")
        nbytes = num * ln
        if len(blob) - pos - PACKET_HEADER < nbytes:
            raise ValueError(f"truncated payload at byte {pos}")
        x = np.frombuffer(blob, dtype="<i2", count=nbytes // 2,
                          offset=pos + PACKET_HEADER).reshape(num, 8)
        out.append((sync, x))
        pos += PACKET_HEADER + nbytes
    return out


def check_packet_layout(rep: Report) -> None:
    one = make_packet(7)
    rep.check("PK-01", "packet size accounting",
              "header 28 + payload 256000 = 256028 bytes; total_len = 256020",
              f"len = {len(one)}, total_len field = {struct.unpack_from('<I', one, 4)[0]}",
              len(one) == 256028 and struct.unpack_from("<I", one, 4)[0] == 256020)
    parsed = parse_packets(one + make_packet(8))
    rep.check("PK-02", "multi-packet parse and sync counter",
              "2 packets, sync 7 then 8, shape (16000, 8)",
              f"{len(parsed)} packets, sync {[p[0] for p in parsed]}, "
              f"shape {parsed[0][1].shape}",
              len(parsed) == 2 and [p[0] for p in parsed] == [7, 8]
              and parsed[0][1].shape == (NUM_SAMPLES, 8))
    rep.check("PK-03", "boundary samples survive the parse",
              "x[0,0] = -32768, x[-1,7] = 32767",
              f"x[0,0] = {int(parsed[0][1][0, 0])}, x[-1,7] = {int(parsed[0][1][-1, 7])}",
              int(parsed[0][1][0, 0]) == -32768 and int(parsed[0][1][-1, 7]) == 32767)
    try:
        parse_packets(one[:-10])
        ok, actual = False, "no exception"
    except ValueError as exc:
        ok, actual = True, f"ValueError: {exc}"
    rep.check("PK-04", "truncated packet is rejected", "ValueError", actual, ok)


def check_real_data(rep: Report, root: Path | None, verbose: bool) -> None:
    if root is None:
        rep.skip("RD-00", "real-data preflight", "no --data-root given")
        return
    if not root.exists():
        rep.skip("RD-00", "real-data preflight", f"path not found: {root}")
        return
    groups = sorted(p for p in root.glob("*/*") if p.is_dir())
    if not groups:
        rep.skip("RD-00", "real-data preflight", f"no group directories under {root}")
        return

    n_groups = 0
    worst_corr = 1.0
    worst_where = ""
    tx_ratios: list[float] = []
    all_lags: list[tuple[str, int]] = []
    for group in groups:
        label = f"{group.parent.name}/{group.name}"
        files = sorted(group.glob("*.dat"))
        by_row: dict[int, Path] = {}
        for f in files:
            try:
                row = int(f.stem.rsplit("_", 1)[1])
            except (ValueError, IndexError):
                continue
            by_row[row] = f
        if len(by_row) != 8:
            rep.skip(f"RD-{label}", "8 row files", f"found {len(by_row)}")
            continue
        packets: dict[int, list[tuple[int, np.ndarray]]] = {}
        ok = True
        for row in range(8):
            blob = by_row[row].read_bytes()
            try:
                packets[row] = parse_packets(blob)
            except ValueError as exc:
                rep.check(f"RD-{label}-row{row}", "packet parse", "valid",
                          str(exc), False)
                ok = False
                break
        if not ok:
            continue
        syncs = [tuple(p[0] for p in packets[r]) for r in range(8)]
        same_sync = len(set(syncs)) == 1
        monotonic = all(b - a == 1 for a, b in zip(syncs[0], syncs[0][1:]))
        rep.check(f"RD-{label}-01", "common packet sync across 8 rows",
                  "identical, strictly +1",
                  f"{syncs[0]} (identical={same_sync}, +1={monotonic})",
                  same_sync and monotonic and len(syncs[0]) >= 3)

        x = packets[3][0][1].astype(float)   # row 4 file, first packet
        tx_rms = float(np.sqrt(np.mean(x[:, TX_K - 1] ** 2)))
        other = np.delete(x, TX_K - 1, axis=1)
        other_rms = float(np.sqrt(np.mean(other ** 2)))
        ratio = tx_rms / other_rms if other_rms else 0.0
        tx_ratios.append(ratio)
        rep.check(f"RD-{label}-02", "A4 column 4 is a silent TX channel",
                  "TX RMS < 5 % of the other columns",
                  f"TX RMS = {tx_rms:.1f}, others = {other_rms:.1f}, ratio = {ratio:.4f}",
                  ratio < 0.05,
                  "the TX column must be dropped, leaving 63 receivers")

        # Periodicity of the 4 blocks inside one 16000-sample packet.
        s = reference_waveform()
        group_min = 1.0
        for row in range(8):
            xr = packets[row][0][1].astype(float)
            for c in range(8):
                if row == 3 and c == TX_K - 1:
                    continue
                base = xr[0:4000, c]
                for b in range(1, 4):
                    blk = xr[b * 4000:(b + 1) * 4000, c]
                    lag, _ = circular_lag(blk, base)
                    aligned = np.roll(blk, -lag)
                    corr = float(np.corrcoef(aligned, base)[0, 1])
                    group_min = min(group_min, corr)
                    if corr < worst_corr:
                        worst_corr, worst_where = corr, f"{label} row{row + 1} ch{c + 1} blk{b}"
        rep.check(f"RD-{label}-03", "packet blocks repeat every Np",
                  "min block correlation after alignment > 0.90",
                  f"min = {group_min:.4f}", group_min > 0.90,
                  "16000 samples = 4 periods; the start phase is not assumed")

        lag, corr = circular_lag(x[0:4000, 0], s)
        all_lags.append((label, lag))
        if verbose:
            print(f"        {label}: packet count = {len(packets[0])}, "
                  f"first lag ch0 = {lag:+d}, corr = {corr:.3f}")
        n_groups += 1

    if all_lags:
        zero_aligned = [name for name, lag in all_lags if lag == 0]
        rep.check("RD-04", "observed template lag is not assumed zero",
                  "at least one sample group has a non-zero observed lag",
                  f"lags = {all_lags}",
                  len(zero_aligned) < len(all_lags),
                  "this is a composite observed-template correlation lag (start + "
                  "hardware + propagation + multipath), not a measured physical "
                  "acquisition start")
    if tx_ratios:
        rep.check("RD-05", "TX suppression is consistent across sample groups",
                  "max TX/other RMS ratio < 0.05",
                  f"ratios = {[round(r, 4) for r in tx_ratios]}",
                  max(tx_ratios) < 0.05)
    print(f"        real-data groups checked: {n_groups}; "
          f"worst block correlation {worst_corr:.4f} ({worst_where})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None,
                        help=".../附件2-测距数据 (optional real-data checks)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    rep = Report()
    check_tx_waveform(rep)
    check_rf_mirror(rep)
    check_delay_phase(rep)
    check_geometry_units(rep)
    check_period_shift(rep)
    check_lag_diagnostic(rep)
    check_tx_channel(rep)
    check_int16(rep)
    check_packet_layout(rep)
    check_real_data(rep, args.data_root, args.verbose)
    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
