#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent review checks for the A-Q1 math spec (M0, reviewed at 0f521a4).

Version history: V1 reviewed ``a9e2719`` (11 checks); V2 adds the PR #3
second-review boundary checks on ``0f521a4`` (general common dispersion and
strict-uniqueness conditions, checks M0-12..M0-16).  The V1 checks pass on
both spec versions; M0-16 is a wording/shape check that intentionally fails
on the pre-fix ``a9e2719`` text.

This script is written from the formulas and claims in
``solutions/A/model_q1.md`` plus the PR #3 review, not from the production
``solutions/A/verify_q1_spec.py``: it does not import or execute it, and it
does not read ``.dat`` data.

Usage
-----
    python checks/A/test_m0_claims.py
    python checks/A/test_m0_claims.py --spec solutions/A/model_q1.md

The split checks are skipped when the spec file is absent (for example on a
branch where M0 is not merged).  Exit code is 0 only when every executed check
passes.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np

C0 = 299_792_458.0
FS = 4.0e9
TS = 1.0 / FS
NP = 4000
TP = NP * TS
F_START = 0.3e9
F_STOP = 1.7e9
K = (F_STOP - F_START) / TP
AMP = 30000.0

D_TRUE = 0.60
R_DIR = np.array([0.07, math.hypot(0.07, 0.14)])


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def check(self, cid: str, name: str, expected: str, actual: str,
              ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        self.passed += bool(ok)
        self.failed += not ok
        print(f"[{status}] {cid} {name}")
        print(f"        expected: {expected}")
        print(f"        actual  : {actual}")
        if detail:
            print(f"        note    : {detail}")

    def skip(self, cid: str, name: str, reason: str) -> None:
        self.skipped += 1
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
# Reference spectrum and geometry
# ---------------------------------------------------------------------------
def reference_spectrum() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = np.arange(NP)
    t = n * TS
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (NP - 1))
    s = AMP * win * np.cos(2.0 * np.pi * (F_START * t + 0.5 * K * t * t))
    s_f = np.fft.rfft(s)
    freqs = np.fft.rfftfreq(NP, d=TS)
    band = (freqs >= F_START) & (freqs <= F_STOP)
    return s, s_f, freqs, band


def weighted_projection(h: np.ndarray, f: np.ndarray, w: np.ndarray,
                        core: np.ndarray) -> tuple[float, float]:
    """Weighted LS of unwrapped phase on span{1, f}: returns (dtau, theta0)."""
    phi = np.unwrap(np.angle(h[core]))
    fc = f[core]
    wc = w[core]
    wsum = float(wc.sum())
    fbar = float((wc * fc).sum() / wsum)
    pbar = float((wc * phi).sum() / wsum)
    df = fc - fbar
    slope = float((wc * df * (phi - pbar)).sum() / (wc * df * df).sum())
    return -slope / (2.0 * np.pi), pbar - slope * fbar


# ---------------------------------------------------------------------------
# Closed-loop example from section 8.1
# ---------------------------------------------------------------------------
def closed_loop(common_shift_a: float = 0.0,
                dispersion: str | None = None) -> dict[str, object]:
    _, s_f, freqs, band = reference_spectrum()
    f_b = freqs[band]
    s_b = s_f[band]
    f_r = FS - f_b
    core = (f_b >= 0.4e9) & (f_b <= 1.6e9)
    w_b = np.abs(s_b) ** 2

    tau_dir = R_DIR / C0
    r_tgt = np.sqrt(R_DIR ** 2 + (2.0 * D_TRUE) ** 2)
    tau_tgt = r_tgt / C0

    h1 = np.exp(-1j * 2.0 * np.pi * f_r * common_shift_a)
    if dispersion:
        # Boundary C distortion taken from the PR #3 counterexample definition:
        # asymmetric amplitude tilt plus linear/quadratic/cubic phase dispersion.
        u = (f_b - 0.5 * (F_START + F_STOP)) / (0.5 * (F_STOP - F_START))
        g_common = 1.0 + 0.45 * u
        phi_common = -2.0 * np.pi * f_b * 0.40e-9
        if dispersion == "full":
            phi_common = phi_common + 2.5 * u ** 2 + 1.5 * u ** 3
        h1 = h1 * g_common * np.exp(1j * phi_common)
    h2 = (1.25 * np.exp(-1j * 2.0 * np.pi * f_b * 0.50e-9 + 1j * 0.30)) * h1
    h = np.vstack([h1, h2])

    t0_air = 120.25 * TS + common_shift_a
    t0_tgt = 250.40 * TS + common_shift_a
    gamma = -0.35

    x_air = np.zeros((2, f_b.size), dtype=complex)
    x_tgt = np.zeros((2, f_b.size), dtype=complex)
    for i in range(2):
        x_air[i] = (h[i] / R_DIR[i]
                    * np.exp(1j * 2.0 * np.pi * f_r * (tau_dir[i] + t0_air))
                    * s_b)
        x_tgt[i] = h[i] * (
            np.exp(1j * 2.0 * np.pi * f_r * (tau_dir[i] + t0_tgt)) / R_DIR[i]
            + gamma * np.exp(1j * 2.0 * np.pi * f_r * (tau_tgt[i] + t0_tgt))
            / r_tgt[i]) * s_b

    # Relative calibration from the air record: X2/X1 * R2/R1 * prop. phase.
    ratio = (x_air[1] / x_air[0]) * (R_DIR[1] / R_DIR[0]) * np.exp(
        -1j * 2.0 * np.pi * f_r * (tau_dir[1] - tau_dir[0]))
    dtau2, _ = weighted_projection(ratio, f_b, w_b, core)
    g2 = float(np.mean(np.abs(ratio)))
    psi2 = float(np.mean(np.angle(ratio * np.exp(1j * 2.0 * np.pi * f_b * dtau2))))

    h_cal = np.vstack([np.ones_like(ratio), ratio])
    x_air_cal = x_air / h_cal
    x_tgt_cal = x_tgt / h_cal

    # Relative asynchronous offset: scalar search on |X_tgt - X_air e^{jwt}|^2
    # around the nominal 130.15 Ts.  The frequency inner product is sufficient.
    c_vec = x_tgt_cal[0] * np.conj(x_air_cal[0])
    nominal = t0_tgt - t0_air
    coarse = nominal + np.linspace(-2.0 * TS, 2.0 * TS, 401)
    scores = np.array([np.real(np.sum(c_vec * np.exp(-1j * 2.0 * np.pi * f_r * g)))
                       for g in coarse])
    g0 = float(coarse[int(np.argmax(scores))])
    fine = g0 + np.linspace(-0.02 * TS, 0.02 * TS, 4001)
    scores = np.array([np.real(np.sum(c_vec * np.exp(-1j * 2.0 * np.pi * f_r * g)))
                       for g in fine])
    dt0 = float(fine[int(np.argmax(scores))])

    x_air_aligned = x_air_cal * np.exp(1j * 2.0 * np.pi * f_r * dt0)
    x_echo = x_tgt_cal - x_air_aligned

    # Explicit dispersive reference template (section 5.3):
    #   S_eff = sum_i (w_i/R_i^dir) * X_air,cal e^{j2pi f_R dt0} * e^{-j2pi f_R tau_i^dir}
    #           / sum_i w_i / (R_i^dir)^2,   w_i = 1.
    s_eff = (np.sum((x_air_aligned / R_DIR[:, None])
                    * np.exp(-1j * 2.0 * np.pi * np.outer(tau_dir, f_r)), axis=0)
             / float(np.sum(1.0 / R_DIR ** 2)))
    s_true_eff = h1 * s_b * np.exp(1j * 2.0 * np.pi * f_r * t0_tgt)

    # Effective time zero: coherent match of the aligned air template to s.
    dw = np.sum((x_air_aligned / R_DIR[:, None]) * np.conj(s_b)
                * np.exp(-1j * 2.0 * np.pi * np.outer(tau_dir, f_r)), axis=0)
    t_nom = t0_tgt
    coarse = t_nom + np.linspace(-2.0 * TS, 2.0 * TS, 401)
    scores = np.array([abs(np.sum(dw * np.exp(-1j * 2.0 * np.pi * f_r * t)))
                       for t in coarse])
    t0c = float(coarse[int(np.argmax(scores))])
    fine = t0c + np.linspace(-0.02 * TS, 0.02 * TS, 4001)
    scores = np.array([abs(np.sum(dw * np.exp(-1j * 2.0 * np.pi * f_r * t)))
                       for t in fine])
    t0_eff = float(fine[int(np.argmax(scores))])

    d_grid = np.linspace(0.55, 0.65, 10001)
    r_d = np.sqrt(R_DIR[:, None] ** 2 + (2.0 * d_grid[None, :]) ** 2)
    p_norm = np.zeros_like(d_grid)
    p_norm_eff = np.zeros_like(d_grid)
    p_env = np.zeros_like(d_grid)
    p_unnorm = np.zeros_like(d_grid)
    s2 = float(np.sum(np.abs(s_b) ** 2))
    seff2 = float(np.sum(np.abs(s_eff) ** 2))
    for j in range(d_grid.size):
        phase = np.exp(-1j * 2.0 * np.pi * np.outer(
            r_d[:, j] / C0 + t0_eff, f_r))
        phase_raw = np.exp(-1j * 2.0 * np.pi * np.outer(
            r_d[:, j] / C0, f_r))
        z = np.sum(x_echo * np.conj(s_b)[None, :] * phase, axis=1)
        z_eff = np.sum(x_echo * np.conj(s_eff)[None, :] * phase_raw, axis=1)
        inv_r2 = float(np.sum(1.0 / r_d[:, j] ** 2))
        p_norm[j] = abs(np.sum(z / r_d[:, j])) ** 2 / (inv_r2 * s2)
        p_norm_eff[j] = abs(np.sum(z_eff / r_d[:, j])) ** 2 / (inv_r2 * seff2)
        p_env[j] = float(np.sum(np.abs(z) / r_d[:, j])) ** 2 / inv_r2
        p_unnorm[j] = abs(np.sum(r_d[:, j] * z))

    # 1 um local refinement around the true distance: separates genuine bias
    # from the 10 um grid quantization of the quoted boundary-C numbers.
    d_fine = np.linspace(D_TRUE - 0.001, D_TRUE + 0.001, 2001)
    r_fine = np.sqrt(R_DIR[:, None] ** 2 + (2.0 * d_fine[None, :]) ** 2)
    p_norm_f = np.zeros_like(d_fine)
    p_norm_eff_f = np.zeros_like(d_fine)
    for j in range(d_fine.size):
        phase = np.exp(-1j * 2.0 * np.pi * np.outer(
            r_fine[:, j] / C0 + t0_eff, f_r))
        phase_raw = np.exp(-1j * 2.0 * np.pi * np.outer(
            r_fine[:, j] / C0, f_r))
        z = np.sum(x_echo * np.conj(s_b)[None, :] * phase, axis=1)
        z_eff = np.sum(x_echo * np.conj(s_eff)[None, :] * phase_raw, axis=1)
        inv_r2 = float(np.sum(1.0 / r_fine[:, j] ** 2))
        p_norm_f[j] = abs(np.sum(z / r_fine[:, j])) ** 2 / (inv_r2 * s2)
        p_norm_eff_f[j] = abs(np.sum(z_eff / r_fine[:, j])) ** 2 / (inv_r2 * seff2)

    return {
        "band_ratio": float(np.sum(np.abs(s_b) ** 2) / np.sum(np.abs(s_f) ** 2)),
        "dtau2": dtau2,
        "g2": g2,
        "psi2": psi2,
        "dt0": dt0,
        "t0_eff": t0_eff,
        "d_unnorm": float(d_grid[int(np.argmax(p_unnorm))]),
        "d_norm": float(d_grid[int(np.argmax(p_norm))]),
        "d_norm_eff": float(d_grid[int(np.argmax(p_norm_eff))]),
        "d_norm_refined": float(d_fine[int(np.argmax(p_norm_f))]),
        "d_norm_eff_refined": float(d_fine[int(np.argmax(p_norm_eff_f))]),
        "d_env": float(d_grid[int(np.argmax(p_env))]),
        "s_eff": s_eff,
        "s_true_eff": s_true_eff,
        "x_air": x_air,
        "x_tgt": x_tgt,
        "p_unnorm": p_unnorm,
        "p_norm": p_norm,
        "p_norm_eff": p_norm_eff,
        "d_grid": d_grid,
    }


# ---------------------------------------------------------------------------
# Split parsing (section 6)
# ---------------------------------------------------------------------------
def parse_split_table(spec_text: str) -> dict[str, list[str]]:
    sets: dict[str, list[str]] = {"wall_cal": [], "wall_test": [],
                                  "metal_cal": [], "metal_test": []}
    for line in spec_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        head = " ".join(cells[:2])
        names = re.findall(r"`?(data\d+(?:-\d+cm)?)`?", " ".join(cells[2:]))
        names = [n for n in names if "-" in n]   # target groups carry a distance
        if not names:
            continue
        if "墙体" in head and "校准" in head:
            sets["wall_cal"] = names
        elif "墙体" in head and "检验" in head:
            sets["wall_test"] = names
        elif "金属板" in head and "校准" in head:
            sets["metal_cal"] = names
        elif "金属板" in head and "检验" in head:
            sets["metal_test"] = names
    return sets


def indices(names: list[str]) -> list[int]:
    return [int(re.match(r"data(\d+)", n).group(1)) for n in names]


def best_scalar_residual(s_eff: np.ndarray, s_b: np.ndarray,
                         f_r: np.ndarray, t_center: float) -> float:
    """Smallest relative residual after fitting c*S*exp(-j2pi f_R t) to s_eff."""
    norm = float(np.linalg.norm(s_eff))
    best = 1.0
    for t in t_center + np.linspace(-2.0e-9, 2.0e-9, 20001):
        basis = s_b * np.exp(1j * 2.0 * np.pi * f_r * t)
        c = np.vdot(basis, s_eff) / np.vdot(basis, basis)
        best = min(best, float(np.linalg.norm(s_eff - c * basis)) / norm)
    return best


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=Path("solutions/A/model_q1.md"))
    args = parser.parse_args(argv)
    rep = Report()

    res = closed_loop(0.0)

    rep.check("M0-01", "in-band energy fraction",
              "0.99991761 over [0.3,1.7] GHz (0.008% outside)",
              f"{res['band_ratio']:.8f}",
              close(float(res["band_ratio"]), 0.99991761, abs_=5e-9))

    rep.check("M0-02", "relative calibration (dtau2, G2, psi2)",
              "0.500000 ns, 1.250000, 0.300000 rad",
              f"{float(res['dtau2']) * 1e9:.6f} ns, {float(res['g2']):.6f}, "
              f"{float(res['psi2']):.6f} rad",
              close(float(res["dtau2"]) * 1e9, 0.5, abs_=1e-6)
              and close(float(res["g2"]), 1.25, abs_=1e-6)
              and close(float(res["psi2"]), 0.3, abs_=1e-6),
              "recovered from the air record only, with the stated RX2 geometry")

    rep.check("M0-03", "relative asynchronous offset dt0",
              "130.1500 Ts",
              f"{float(res['dt0']) / TS:.4f} Ts",
              close(float(res["dt0"]) / TS, 130.15, abs_=1e-3))

    rep.check("M0-04", "effective reference zero t0_eff (target)",
              "250.4000 Ts",
              f"{float(res['t0_eff']) / TS:.4f} Ts",
              close(float(res["t0_eff"]) / TS, 250.4, abs_=1e-3))

    rep.check("M0-05", "normalized GLRT P_norm peak",
              "0.600000 m (zero bias)",
              f"{float(res['d_norm']):.6f} m",
              close(float(res["d_norm"]), 0.6, abs_=1e-5),
              "denominator (sum_i w_i/R_i^2)(sum|S|^2); peak is a Cauchy-Schwarz equality point")

    rep.check("M0-06", "normalized envelope P_env peak",
              "0.600000 m (zero bias)",
              f"{float(res['d_env']):.6f} m",
              close(float(res["d_env"]), 0.6, abs_=1e-5))

    p_un = np.asarray(res["p_unnorm"])
    d_grid = np.asarray(res["d_grid"])
    k0 = int(np.argmin(np.abs(d_grid - D_TRUE)))
    deriv = (p_un[k0 + 1] - p_un[k0 - 1]) / (d_grid[k0 + 1] - d_grid[k0 - 1])
    rep.check("M0-07", "legacy unnormalized DAS bias and positive slope",
              "peak 0.620000 m; dP/dd > 0 at 0.600000 m",
              f"peak {float(res['d_unnorm']):.6f} m; slope {deriv:+.3e} at 0.6 m",
              close(float(res["d_unnorm"]), 0.62, abs_=1e-4) and deriv > 0)

    # Identifiability A: free per-frequency psi absorbs a delay shift.
    _, s_f, freqs, band = reference_spectrum()
    f_b = freqs[band]
    delta = 0.25e-9
    psi = 0.30 + 0.70 * np.sin(2.0 * np.pi * f_b / 1.4e9)
    h_a = 1.25 * np.exp(-1j * 2.0 * np.pi * f_b * 0.50e-9 + 1j * psi)
    h_b = 1.25 * np.exp(-1j * 2.0 * np.pi * f_b * (0.50e-9 + delta)
                        + 1j * (psi + 2.0 * np.pi * f_b * delta))
    diff = float(np.max(np.abs(h_a - h_b)))
    rep.check("M0-08", "free per-frequency psi: (dtau, psi) gauge invariance",
              "max|H - H'| approximately 0",
              f"max|H - H'| = {diff:.3e}",
              diff < 1e-13,
              "same data, (dtau+delta, psi+2*pi*f*delta); psi cannot be fixed by the data alone")

    # Convention only: a linear phase that looks like an extra delay is folded
    # into dtau_hat, so the projected dtau is not the physical hardware delay.
    h_phys = 1.25 * np.exp(-1j * 2.0 * np.pi * f_b * 0.50e-9
                           + 1j * 2.0 * np.pi * f_b * 0.25e-9)
    dtau_hat, _ = weighted_projection(h_phys, f_b, np.abs(s_f[band]) ** 2,
                                      (f_b >= 0.4e9) & (f_b <= 1.6e9))
    rep.check("M0-09", "projection convention: dtau_hat is not the physical delay",
              "planted 0.500 ns + linear phase 0.250 ns -> dtau_hat = 0.250 ns",
              f"dtau_hat = {dtau_hat * 1e9:.6f} ns",
              close(dtau_hat * 1e9, 0.25, abs_=1e-6),
              "the decomposition is unique only after the projection convention; "
              "the physical hardware delay remains unidentifiable")

    # Identifiability B: common H_ref and t0 swap leaves the observations fixed.
    res_shift = closed_loop(0.35e-9)
    x_air = np.asarray(res["x_air"])
    x_tgt = np.asarray(res["x_tgt"])
    x_air_s = np.asarray(res_shift["x_air"])
    x_tgt_s = np.asarray(res_shift["x_tgt"])
    rel_air = float(np.max(np.abs(x_air - x_air_s)) / np.max(np.abs(x_air)))
    rel_tgt = float(np.max(np.abs(x_tgt - x_tgt_s)) / np.max(np.abs(x_tgt)))
    rep.check("M0-10", "common H_ref / t0 swap leaves observations, dt0 and d fixed",
              "a = 0.35 ns: rel|dX| < 1e-12, dt0 = 130.15 Ts, d = 0.600000 m",
              f"rel air = {rel_air:.2e}, rel tgt = {rel_tgt:.2e}, "
              f"dt0 = {float(res_shift['dt0']) / TS:.4f} Ts, "
              f"d = {float(res_shift['d_norm']):.6f} m",
              rel_air < 1e-12 and rel_tgt < 1e-12
              and close(float(res_shift["dt0"]) / TS, 130.15, abs_=1e-3)
              and close(float(res_shift["d_norm"]), 0.6, abs_=1e-5))

    # Split proposal.
    if not args.spec.is_file():
        rep.skip("M0-11", "10/10 split", f"spec not found: {args.spec}")
    else:
        sets = parse_split_table(args.spec.read_text(encoding="utf-8"))
        wall_cal = sets["wall_cal"]
        wall_test = sets["wall_test"]
        metal_cal = sets["metal_cal"]
        metal_test = sets["metal_test"]
        wall_ok = (len(wall_cal) == 10 and len(wall_test) == 10
                   and not set(wall_cal) & set(wall_test)
                   and sorted(indices(wall_cal + wall_test)) == list(range(1, 21)))
        metal_ok = (len(metal_cal) == 10 and len(metal_test) == 10
                    and not set(metal_cal) & set(metal_test)
                    and sorted(indices(metal_cal + metal_test)) == list(range(1, 21)))
        swapped = ("data1-69cm" in metal_cal and "data10-70cm" in metal_test)
        recon_safe = (not {"data1-42cm"} & set(wall_test)
                      and not {"data1-69cm"} & set(metal_test))
        rep.check("M0-11", "10/10 split: disjoint, complete, recon groups in calibration",
                  "wall and metal each 10/10 and cover data1..data20 once; "
                  "data1-42cm/data1-69cm are calibration; data10-70cm is test",
                  f"wall {len(wall_cal)}/{len(wall_test)} ok={wall_ok}; "
                  f"metal {len(metal_cal)}/{len(metal_test)} ok={metal_ok}; "
                  f"swap={swapped}; recon_safe={recon_safe}",
                  wall_ok and metal_ok and swapped and recon_safe,
                  "freeze is still pending coordinator/validator confirmation")

    # --- V2 boundary checks (spec 0f521a4) --------------------------------
    _, s_f_v2, freqs_v2, band_v2 = reference_spectrum()
    f_b = freqs_v2[band_v2]
    f_r = FS - f_b
    s_b = s_f_v2[band_v2]
    res_disp = closed_loop(common_shift_a=0.10e-9, dispersion="full")
    res_amp = closed_loop(common_shift_a=0.10e-9, dispersion="amp")

    d10 = float(res_disp["d_norm"])
    d1 = float(res_disp["d_norm_refined"])
    rep.check("M0-12", "boundary C: scalar t0_eff anchoring under common dispersion",
              "author quotes 0.600010 m (their 0.5 ps anchor grid); an independent "
              "sub-fs anchor should show whether that residual is real or grid quantization",
              f"10 um grid = {d10:.6f} m, 1 um refine = {d1:.6f} m "
              f"(bias {(d1 - D_TRUE) * 1e6:+.3f} um)",
              abs(d10 - D_TRUE) <= 1e-5 + 1e-12 and abs(d1 - D_TRUE) < 1e-6,
              "the quoted one-step residual tracks the author's 0.5 ps anchor grid; "
              "at the same 10 um profile grid an optimal anchor gives 0.600000 m, "
              "so it must not be cited as a dispersion-induced bias")

    rep.check("M0-13", "boundary C: explicit S_eff template removes the dispersion",
              "0.600000 m on both the 10 um and the refined 1 um grid",
              f"10 um = {float(res_disp['d_norm_eff']):.6f} m, "
              f"1 um = {float(res_disp['d_norm_eff_refined']):.6f} m",
              abs(float(res_disp["d_norm_eff"]) - D_TRUE) < 1e-9
              and abs(float(res_disp["d_norm_eff_refined"]) - D_TRUE) < 1e-9,
              "a_eff(d) = S_eff(f_D) e^{j2pi f_R tau_i(d)} / R_i(d), no scalar anchor")

    ratio = np.asarray(res_disp["s_eff"]) / np.asarray(res_disp["s_true_eff"])
    rel_ratio = float(np.max(np.abs(ratio - ratio.mean())) / abs(ratio.mean()))
    rep.check("M0-14", "explicit S_eff identity: S_eff = H_ref S e^{j2pi f_R t0}",
              "ratio to planted H_ref*S*exp(j2pi f_R t0) constant over the band (< 1e-12)",
              f"max relative spread = {rel_ratio:.2e}, |ratio| = {abs(ratio.mean()):.6f}",
              rel_ratio < 1e-12,
              "reconstructed from the calibrated air record only")

    resid_amp = best_scalar_residual(np.asarray(res_amp["s_eff"]), s_b, f_r,
                                     float(res_amp["t0_eff"]))
    resid_full = best_scalar_residual(np.asarray(res_disp["s_eff"]), s_b, f_r,
                                      float(res_disp["t0_eff"]))
    rep.check("M0-15", "common dispersion is not removable by any scalar time shift",
              "amplitude tilt alone leaves a >1e-3 residual; full dispersion leaves more",
              f"best-shift residual: amplitude-only = {resid_amp:.4f}, "
              f"full dispersion = {resid_full:.4f}",
              resid_amp > 1e-3 and resid_full > resid_amp,
              "quantifies why section 4.1(2) now requires an explicit S_eff template")

    if not args.spec.is_file():
        rep.skip("M0-16", "strict-uniqueness wording and non-collinearity",
                 f"spec not found: {args.spec}")
    else:
        text = args.spec.read_text(encoding="utf-8")
        has_conditions = all(k in text for k in
                             ("严格唯一", "非零回波", "互不共线", "理想无噪"))
        has_noise_caveat = ("有限样本统计无偏性" in text and "不能" in text)
        no_absolute_zero_bias = "零估计偏差" not in text
        # Steering vectors a(d) and a(d0) must not be collinear for d != d0.
        r0 = np.sqrt(R_DIR ** 2 + (2.0 * D_TRUE) ** 2)
        a0 = (np.exp(1j * 2.0 * np.pi * np.outer(r0 / C0, f_r))
              / r0[:, None]).ravel()
        d_probe = np.linspace(0.55, 0.65, 401)
        min_resid = 1.0
        for d in d_probe:
            if abs(d - D_TRUE) < 1e-12:
                continue
            r = np.sqrt(R_DIR ** 2 + (2.0 * d) ** 2)
            a = (np.exp(1j * 2.0 * np.pi * np.outer(r / C0, f_r))
                 / r[:, None]).ravel()
            kappa = np.vdot(a0, a) / np.vdot(a0, a0)
            min_resid = min(min_resid,
                            float(np.linalg.norm(a - kappa * a0) / np.linalg.norm(a)))
        rep.check("M0-16", "strict-uniqueness wording is conditioned; steering vectors non-collinear",
                  "conditions (noiseless mirror, Gamma!=0, non-collinear) stated; "
                  "no unconditional zero-bias claim; min a(d) vs a(d0) residual > 1e-6",
                  f"conditions={has_conditions}, noise caveat={has_noise_caveat}, "
                  f"no 'zero bias'={no_absolute_zero_bias}, "
                  f"min non-collinearity residual={min_resid:.2e}",
                  has_conditions and has_noise_caveat and no_absolute_zero_bias
                  and min_resid > 1e-6,
                  "the residual is the least-squares distance to the a(d0) line")

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
