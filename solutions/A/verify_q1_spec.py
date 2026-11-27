"""Independent small-example verification for Problem A Q1 math spec (M0).

This script verifies ONLY the analytical formulas and identifiability assertions
in `solutions/A/model_q1.md` on a 2-receiver synthetic closed-loop example.
It does NOT read `.dat` files and is NOT a production solver or estimator.
"""

from __future__ import annotations

import math
import sys
import numpy as np


C0 = 299792458.0  # m/s (first-round unified speed of light)
FS = 4.0e9        # Hz
TS = 1.0 / FS     # 0.25 ns
NP = 4000         # samples per chirp period
TP = NP * TS      # 1 us
F_START = 0.3e9   # Hz
F_STOP = 1.7e9    # Hz
K_SLOPE = (F_STOP - F_START) / TP
AMP = 30000.0


def make_reference_signal() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build discrete digital reference LFM s[n] and frequency axes."""
    n = np.arange(NP, dtype=np.float64)
    t = n * TS
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (NP - 1))
    phase = 2.0 * np.pi * (F_START * t + 0.5 * K_SLOPE * t ** 2)
    s_t = AMP * win * np.cos(phase)
    s_f = np.fft.rfft(s_t)
    freqs = np.fft.rfftfreq(NP, d=TS)
    return s_t, s_f, freqs


def unwrap_weighted_delay_decomp(
    h_band: np.ndarray,
    f_band: np.ndarray,
    weights: np.ndarray,
    core_mask: np.ndarray,
) -> tuple[float, float, np.ndarray]:
    """Project unwrapped phase onto span{1, f_D} under core-band weights.

    Returns (delta_tau_s, theta0_rad, psi_wrapped_band_rad).
    Imposes zero weighted first-order moment of residual phase on `core_mask`.
    """
    phi_core = np.unwrap(np.angle(h_band[core_mask]))
    f_core = f_band[core_mask]
    w_core = weights[core_mask]
    w_sum = float(np.sum(w_core))
    f_bar = float(np.sum(w_core * f_core) / w_sum)
    phi_bar = float(np.sum(w_core * phi_core) / w_sum)
    df = f_core - f_bar
    slope = float(np.sum(w_core * df * (phi_core - phi_bar)) / np.sum(w_core * df ** 2))
    delta_tau_s = -slope / (2.0 * np.pi)
    theta0 = phi_bar - slope * f_bar
    # Verify zero first-order moment orthogonality
    res_core = phi_core + 2.0 * np.pi * f_core * delta_tau_s
    moment = float(np.sum(w_core * (res_core - theta0) * df))
    assert abs(moment) < 1e-6 * w_sum, f"Orthogonality check failed: {moment}"
    psi_band = np.angle(h_band * np.exp(1j * 2.0 * np.pi * f_band * delta_tau_s))
    return delta_tau_s, theta0, psi_band


def rf_envelope_coarse_lag(x_sig: np.ndarray, y_ref: np.ndarray) -> int:
    """Circular cross-correlation analytic envelope peak lag (samples)."""
    cc = np.fft.irfft(np.fft.rfft(x_sig) * np.conj(np.fft.rfft(y_ref)), n=NP)
    h = np.zeros(NP, dtype=np.float64)
    h[0] = 1.0
    h[NP // 2] = 1.0
    h[1 : NP // 2] = 2.0
    env = np.abs(np.fft.ifft(np.fft.fft(cc) * h))
    lag = int(np.argmax(env))
    if lag > NP // 2:
        lag -= NP
    return lag


def run_closed_loop_example(
    common_shift_a: float = 0.0,
) -> dict[str, float]:
    """Run 2-RX closed-loop calibration, DW suppression, and DAS ranging."""
    _, s_f, freqs = make_reference_signal()
    band = (freqs >= F_START) & (freqs <= F_STOP)
    core_in_band = (freqs[band] >= 0.4e9) & (freqs[band] <= 1.6e9)
    f_b = freqs[band]
    f_r_all = FS - freqs
    f_r_b = FS - f_b
    s_b = s_f[band]

    # Geometry: TX=(0,0,0.545), RX1=(-0.07,0,0.545), RX2=(-0.07,0,0.685)
    r_dir = np.array([0.07, math.hypot(0.07, 0.14)], dtype=np.float64)
    tau_dir = r_dir / C0
    d_true = 0.60
    r_tgt_0 = np.sqrt(r_dir ** 2 + (2.0 * d_true) ** 2)
    tau_tgt_0 = r_tgt_0 / C0

    # Planted hardware response on RX1 (ref) and RX2, plus common gauge shift `common_shift_a`
    dtau2_true = 0.50e-9  # +0.5 ns = +2.0 Ts
    g2_true = 1.25
    psi2_true = 0.30
    h1_all = np.exp(-1j * 2.0 * np.pi * f_r_all * common_shift_a)
    h2_all = g2_true * np.exp(-1j * 2.0 * np.pi * freqs * dtau2_true + 1j * psi2_true) * h1_all

    t0_air = 120.25 * TS + common_shift_a
    t0_tgt = 250.40 * TS + common_shift_a
    gamma_tgt = -0.35

    # Forward physical observation (strictly inside Nyquist positive band)
    x_air = np.zeros((2, freqs.size), dtype=np.complex128)
    x_tgt = np.zeros((2, freqs.size), dtype=np.complex128)
    h_true = np.vstack([h1_all, h2_all])
    for idx in range(2):
        amp_dir = 1.0 / r_dir[idx]
        amp_tgt = gamma_tgt / r_tgt_0[idx]
        x_air[idx] = h_true[idx] * amp_dir * np.exp(1j * 2.0 * np.pi * f_r_all * (tau_dir[idx] + t0_air)) * s_f
        x_tgt[idx] = h_true[idx] * (
            amp_dir * np.exp(1j * 2.0 * np.pi * f_r_all * (tau_dir[idx] + t0_tgt))
            + amp_tgt * np.exp(1j * 2.0 * np.pi * f_r_all * (tau_tgt_0[idx] + t0_tgt))
        ) * s_f

    # 1. Band-limited energy fraction check
    band_energy_ratio = float(np.sum(np.abs(s_b) ** 2) / np.sum(np.abs(s_f) ** 2))

    # 2. Calibration relative to RX1 (gauge anchor)
    ratio_21_b = (
        (x_air[1, band] / x_air[0, band])
        * (r_dir[1] / r_dir[0])
        * np.exp(-1j * 2.0 * np.pi * f_r_b * (tau_dir[1] - tau_dir[0]))
    )
    weights_b = np.abs(s_b) ** 2
    dtau2_est, _, psi2_b = unwrap_weighted_delay_decomp(ratio_21_b, f_b, weights_b, core_in_band)
    g2_est = float(np.mean(np.abs(ratio_21_b)))
    psi2_est = float(np.mean(psi2_b))

    h_cal_b = np.vstack([np.ones_like(ratio_21_b), ratio_21_b])
    x_air_cal_b = x_air[:, band] / h_cal_b
    x_tgt_cal_b = x_tgt[:, band] / h_cal_b

    # 3. Direct-wave alignment & subtraction (using band-limited time representation for coarse lag)
    x_tgt_band_t = np.zeros(NP, dtype=np.float64)
    x_air_band_t = np.zeros(NP, dtype=np.float64)
    spec_tmp = np.zeros(freqs.size, dtype=np.complex128)
    spec_tmp[band] = x_tgt_cal_b[0]
    x_tgt_band_t = np.fft.irfft(spec_tmp, n=NP)
    spec_tmp[band] = x_air_cal_b[0]
    x_air_band_t = np.fft.irfft(spec_tmp, n=NP)

    k0 = rf_envelope_coarse_lag(x_tgt_band_t, x_air_band_t)
    dt_grid = np.linspace((k0 - 1.0) * TS, (k0 + 1.0) * TS, 20001)
    # Vectorized search on RX1
    phases = np.exp(1j * 2.0 * np.pi * np.outer(dt_grid, f_r_b))
    res_mat = x_tgt_cal_b[0][None, :] - x_air_cal_b[0][None, :] * phases
    dt0_est = float(dt_grid[int(np.argmin(np.sum(np.abs(res_mat) ** 2, axis=1)))])

    shift_b = np.exp(1j * 2.0 * np.pi * f_r_b * dt0_est)
    x_air_aligned_b = x_air_cal_b * shift_b[None, :]
    x_echo_b = x_tgt_cal_b - x_air_aligned_b

    # 4. Effective reference time anchor t0_eff_tgt
    spec_tmp[band] = x_air_aligned_b[0]
    mf_coarse = rf_envelope_coarse_lag(np.fft.irfft(spec_tmp, n=NP), np.fft.irfft(np.where(band, s_f, 0.0), n=NP))
    t_anc_grid = np.linspace((mf_coarse - 1.0) * TS, (mf_coarse + 1.0) * TS, 4001)
    # Coherent match over both channels compensated for tau_dir
    dw_comp = np.sum(
        (x_air_aligned_b / r_dir[:, None])
        * np.conj(s_b)[None, :]
        * np.exp(-1j * 2.0 * np.pi * np.outer(tau_dir, f_r_b)),
        axis=0,
    )
    anc_scores = np.abs(dw_comp @ np.exp(-1j * 2.0 * np.pi * np.outer(f_r_b, t_anc_grid)))
    t0_eff_tgt_est = float(t_anc_grid[int(np.argmax(anc_scores))])

    # 5. Profile search on [0.55, 0.65] m with 10 um step (matching review grid)
    d_grid = np.linspace(0.55, 0.65, 10001)
    r_d = np.sqrt(r_dir[:, None] ** 2 + (2.0 * d_grid[None, :]) ** 2)  # (2, D)
    tau_d = r_d / C0 + t0_eff_tgt_est

    # Unnormalized legacy heuristic (to verify +2.0 cm bias)
    p_unnorm = np.zeros_like(d_grid)
    # Normalized GLRT matched statistic |a^H W y|^2 / (a^H W a), w_i = 1
    p_norm = np.zeros_like(d_grid)
    # Normalized non-coherent envelope DAS
    p_env = np.zeros_like(d_grid)
    s2_sum = float(np.sum(np.abs(s_b) ** 2))

    y_sconj = x_echo_b * np.conj(s_b)[None, :]  # (2, F)
    for idx_d in range(d_grid.size):
        exp_neg = np.exp(-1j * 2.0 * np.pi * np.outer(tau_d[:, idx_d], f_r_b))
        z_ch = np.sum(y_sconj * exp_neg, axis=1)  # (2,)
        p_unnorm[idx_d] = abs(np.sum(r_d[:, idx_d] * z_ch))
        denom = float(np.sum(1.0 / (r_d[:, idx_d] ** 2)))
        p_norm[idx_d] = (abs(np.sum(z_ch / r_d[:, idx_d])) ** 2) / (denom * s2_sum)
        p_env[idx_d] = (float(np.sum(np.abs(z_ch) / r_d[:, idx_d])) ** 2) / denom

    return {
        "band_energy_ratio": band_energy_ratio,
        "r_dir_1": float(r_dir[0]),
        "r_dir_2": float(r_dir[1]),
        "tau_dir_1_ns": float(tau_dir[0] * 1e9),
        "tau_dir_2_ns": float(tau_dir[1] * 1e9),
        "r_tgt_1": float(r_tgt_0[0]),
        "r_tgt_2": float(r_tgt_0[1]),
        "tau_tgt_1_ns": float(tau_tgt_0[0] * 1e9),
        "tau_tgt_2_ns": float(tau_tgt_0[1] * 1e9),
        "dtau2_est_ns": dtau2_est * 1e9,
        "g2_est": g2_est,
        "psi2_est_rad": psi2_est,
        "dt0_est_samples": dt0_est / TS,
        "t0_eff_tgt_samples": t0_eff_tgt_est / TS,
        "d_est_unnorm_m": float(d_grid[int(np.argmax(p_unnorm))]),
        "d_est_norm_m": float(d_grid[int(np.argmax(p_norm))]),
        "d_est_env_m": float(d_grid[int(np.argmax(p_env))]),
        "x_air": x_air,
        "x_tgt": x_tgt,
    }


def main() -> int:
    res0 = run_closed_loop_example(common_shift_a=0.0)
    print(f"Band energy ratio ([0.3, 1.7] GHz / full): {res0['band_energy_ratio']:.8f}")
    print(f"R_dir = ({res0['r_dir_1']:.6f}, {res0['r_dir_2']:.6f}) m")
    print(f"tau_dir = ({res0['tau_dir_1_ns']:.6f}, {res0['tau_dir_2_ns']:.6f}) ns")
    print(f"R_tgt = ({res0['r_tgt_1']:.6f}, {res0['r_tgt_2']:.6f}) m")
    print(f"tau_tgt = ({res0['tau_tgt_1_ns']:.6f}, {res0['tau_tgt_2_ns']:.6f}) ns")
    print(
        f"Calibrated RX2: dtau2={res0['dtau2_est_ns']:.6f} ns, "
        f"G2={res0['g2_est']:.6f}, psi2={res0['psi2_est_rad']:.6f} rad"
    )
    print(
        f"Alignment: dt0={res0['dt0_est_samples']:.4f} Ts, "
        f"t0_eff_tgt={res0['t0_eff_tgt_samples']:.4f} Ts"
    )
    print(f"Legacy unnormalized DAS d_est = {res0['d_est_unnorm_m']:.6f} m (known +2 cm bias)")
    print(f"Normalized GLRT P_norm  d_est = {res0['d_est_norm_m']:.6f} m")
    print(f"Normalized Env  P_env   d_est = {res0['d_est_env_m']:.6f} m")

    # Counterexample A: unconstrained (delta_tau, psi) gauge invariance
    _, _, freqs = make_reference_signal()
    band = (freqs >= F_START) & (freqs <= F_STOP)
    f_b = freqs[band]
    delta = 0.25e-9
    h2 = 1.25 * np.exp(-1j * 2.0 * np.pi * f_b * 0.50e-9 + 1j * 0.30)
    h2_p = 1.25 * np.exp(-1j * 2.0 * np.pi * f_b * (0.50e-9 + delta) + 1j * (0.30 + 2.0 * np.pi * f_b * delta))
    diff_gauge_a = float(np.max(np.abs(h2 - h2_p)))
    print(f"Counterexample A (unconstrained dtau/psi shift): max|H - H'| = {diff_gauge_a:.3e}")

    # Counterexample B: common H_ref & t0 shift a = 0.35 ns
    res_shift = run_closed_loop_example(common_shift_a=0.35e-9)
    diff_obs_air = float(np.max(np.abs(res0["x_air"] - res_shift["x_air"])))
    diff_obs_tgt = float(np.max(np.abs(res0["x_tgt"] - res_shift["x_tgt"])))
    rel_obs_air = diff_obs_air / float(np.max(np.abs(res0["x_air"])))
    rel_obs_tgt = diff_obs_tgt / float(np.max(np.abs(res0["x_tgt"])))
    print(
        f"Counterexample B (common H_ref/t0 shift a=0.35ns): "
        f"rel|X_air-X'|={rel_obs_air:.3e}, rel|X_tgt-X'|={rel_obs_tgt:.3e}, "
        f"d_norm'={res_shift['d_est_norm_m']:.6f} m"
    )

    # Assertions
    assert abs(res0["dtau2_est_ns"] - 0.500000) < 1e-6
    assert abs(res0["g2_est"] - 1.250000) < 1e-6
    assert abs(res0["psi2_est_rad"] - 0.300000) < 1e-6
    assert abs(res0["dt0_est_samples"] - 130.15) < 1e-3
    assert abs(res0["t0_eff_tgt_samples"] - 250.40) < 1e-3
    assert abs(res0["d_est_unnorm_m"] - 0.620000) < 1e-5
    assert abs(res0["d_est_norm_m"] - 0.600000) < 1e-5
    assert abs(res0["d_est_env_m"] - 0.600000) < 1e-5
    assert diff_gauge_a < 1e-13
    assert rel_obs_air < 1e-12 and rel_obs_tgt < 1e-12
    assert abs(res_shift["d_est_norm_m"] - 0.600000) < 1e-5
    print("ALL M0 CLOSED-LOOP CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
