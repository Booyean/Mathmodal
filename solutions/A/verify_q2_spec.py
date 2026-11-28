"""Independent pure-synthetic closed-loop verification for Problem A Q2 math spec (M2).

Verifies ONLY the mathematical formulation, geometry, bounded delay/range gain
(M2-Gain-BSEC), and single-row 2D coherent/envelope backprojection (M2-Img-CohBPA / EnvBPA)
defined in `solutions/A/model_q2.md`. Does NOT read real `.dat` files and is NOT a
production Q2 solver.
"""

from __future__ import annotations

import math
import numpy as np


C0 = 299792458.0
FS = 4.0e9
TS = 1.0 / FS
NP = 4000
TP = NP * TS
F_START = 0.3e9
F_STOP = 1.7e9
K_SLOPE = (F_STOP - F_START) / TP
AMP = 30000.0


def build_array_coords() -> tuple[np.ndarray, list[int]]:
    """Return 64x3 local coordinates (m) matching M0 §2.1 and row-4 rx indices."""
    coords = np.zeros((64, 3), dtype=np.float64)
    row4_rx: list[int] = []
    for r in range(1, 9):
        z = (75.5 - 7 * (r - 1)) * 1e-2
        for k in range(1, 9):
            cgrid = (2 * k - 1) if (r % 2 == 1) else (2 * k)
            x = (8 - cgrid) * 0.035
            idx = 8 * (r - 1) + (k - 1)
            coords[idx] = (x, 0.0, z)
            if r == 4 and idx != 27:
                row4_rx.append(idx)
    return coords, row4_rx


def make_reference_band() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = np.arange(NP, dtype=np.float64)
    t = n * TS
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (NP - 1))
    s_t = AMP * win * np.cos(2.0 * np.pi * (F_START * t + 0.5 * K_SLOPE * t ** 2))
    s_f = np.fft.rfft(s_t)
    freqs = np.fft.rfftfreq(NP, d=TS)
    band = (freqs >= F_START) & (freqs <= F_STOP)
    f_d = freqs[band]
    f_r = FS - f_d
    return band, f_d, f_r, s_f[band]


def gain_bsec(
    tau_s: np.ndarray,
    beta: float = 1.0,
    alpha_gain_per_ns: float = 0.14,
    y0_m: float = 0.25,
    y_sat_m: float = 2.60,
    g_cap: float = 20.0,
) -> np.ndarray:
    """Bounded spreading + exponential attenuation compensation M2-Gain-BSEC."""
    tau0 = 2.0 * y0_m / C0
    tau_sat = 2.0 * y_sat_m / C0
    tau_clip = np.clip(tau_s, tau0, tau_sat)
    tau_ns_excess = np.maximum(tau_clip - tau0, 0.0) * 1.0e9
    g = ((tau_clip / tau0) ** beta) * np.exp(alpha_gain_per_ns * tau_ns_excess)
    return np.minimum(g, g_cap)


def aperture_weight(dx: np.ndarray, dy: np.ndarray, deg_flat: float = 35.0, deg_cut: float = 45.0) -> np.ndarray:
    ang_deg = np.degrees(np.arctan2(np.abs(dx), np.maximum(dy, 1e-6)))
    w = np.ones_like(ang_deg, dtype=np.float64)
    trans = (ang_deg > deg_flat) & (ang_deg <= deg_cut)
    w[trans] = 0.5 * (1.0 + np.cos(np.pi * (ang_deg[trans] - deg_flat) / (deg_cut - deg_flat)))
    w[ang_deg > deg_cut] = 0.0
    return w


def simulate_dual_wall_synthetic(
    coords: np.ndarray,
    row4_rx: list[int],
    band: np.ndarray,
    f_d: np.ndarray,
    f_r: np.ndarray,
    s_b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate 33 scan positions x 7 row-4 RX compressed responses z_MF_i(m*Ts)."""
    x_scan = -0.20 + 0.05 * np.arange(33, dtype=np.float64)
    p_tx_loc = coords[27]
    p_rx_loc = coords[row4_rx]

    # Planted common dispersive H_ref (already absorbed in reconstructed S_eff)
    u = (f_d - 1.0e9) / 0.7e9
    h_ref = (1.0 + 0.20 * u) * np.exp(1j * (2.0 * np.pi * f_r * 2.0e-10 + 0.5 * u ** 2))
    s_eff = h_ref * s_b * np.exp(1j * 2.0 * np.pi * f_r * (120.25 * TS))
    s_eff_norm = float(np.linalg.norm(s_eff))

    # Front wall A: tilted line segment from (0.25, 0.37) m to (1.06, 0.56) m
    n_a = 45
    xa = np.linspace(0.25, 1.06, n_a)
    ya = np.linspace(0.37, 0.56, n_a)
    wall_a_pts = np.column_stack([xa, ya, np.full(n_a, p_tx_loc[2])])
    amp_a = 0.60 / n_a

    # Back wall B: horizontal at y = 2.00 m spanning [-0.20, 1.40] m
    # Behind Wall A shadow (x in [0.25, 1.06]), extra front-wall attenuation applies
    n_b = 81
    xb = np.linspace(-0.20, 1.40, n_b)
    yb = np.full(n_b, 2.00)
    wall_b_pts = np.column_stack([xb, yb, np.full(n_b, p_tx_loc[2])])
    in_shadow = (xb >= 0.25) & (xb <= 1.06)
    # 1/R geometric loss already arises from propagation 1/(r_tx*r_rx) or 1/R;
    # set intrinsic weak reflectivity & extra attenuation behind Wall A
    gamma_b = np.where(in_shadow, 0.08, 0.16) / n_b

    rng = np.random.default_rng(20261128)
    band_idx = np.where(band)[0]
    osr = 4  # 4x baseband oversampling so linear interp preserves complex baseband cleanly
    n_over = NP * osr

    # Store 4x-oversampled complex baseband compressed response z_base (carrier e^{-j2pi*f_s*tau} applied analytically)
    z_base_over = np.zeros((len(x_scan), len(row4_rx), n_over), dtype=np.complex128)

    for j_idx, xj in enumerate(x_scan):
        tx_pos = np.array([xj, 0.0, p_tx_loc[2]])
        rx_pos = p_rx_loc.copy()
        rx_pos[:, 0] += xj

        # Wall A scattering (two-way 1/R planar-like attenuation)
        r_tx_a = np.linalg.norm(wall_a_pts - tx_pos[None, :], axis=1)  # (Na,)
        r_rx_a = np.linalg.norm(wall_a_pts[None, :, :] - rx_pos[:, None, :], axis=2)  # (7, Na)
        tau_a = (r_tx_a[None, :] + r_rx_a) / C0
        spread_a = 1.0 / (r_tx_a[None, :] + r_rx_a)
        phase_a = np.exp(1j * 2.0 * np.pi * f_r[:, None, None] * tau_a[None, :, :])
        spec_a = np.einsum("ra,fra->rf", amp_a * spread_a, phase_a)

        # Wall B scattering (weaker due to larger spreading + wall penetration loss)
        r_tx_b = np.linalg.norm(wall_b_pts - tx_pos[None, :], axis=1)
        r_rx_b = np.linalg.norm(wall_b_pts[None, :, :] - rx_pos[:, None, :], axis=2)
        tau_b = (r_tx_b[None, :] + r_rx_b) / C0
        spread_b = 1.0 / (r_tx_b[None, :] + r_rx_b)
        phase_b = np.exp(1j * 2.0 * np.pi * f_r[:, None, None] * tau_b[None, :, :])
        spec_b = np.einsum("ra,fra->rf", gamma_b[None, :] * spread_b, phase_b)

        x_tilde_clean = (spec_a + spec_b) * s_eff[None, :]

        # Add bandlimited AWGN scaled relative to far-wall echo
        spec_b_band = spec_b * s_eff[None, :]
        p_b_ref = float(np.mean(np.abs(spec_b_band) ** 2))
        sigma_f = math.sqrt(p_b_ref * (10.0 ** (-8.0 / 10.0)) * 0.5)
        noise = rng.normal(0.0, sigma_f, size=x_tilde_clean.shape) + 1j * rng.normal(0.0, sigma_f, size=x_tilde_clean.shape)
        x_tilde = x_tilde_clean + noise

        full = np.zeros((len(row4_rx), n_over), dtype=np.complex128)
        full[:, band_idx] = x_tilde * np.conj(s_eff)[None, :]
        z_base_over[j_idx] = n_over * np.fft.ifft(full, axis=1) / s_eff_norm

    return x_scan, p_rx_loc, z_base_over


def reconstruct_2d(
    x_scan: np.ndarray,
    p_tx_loc: np.ndarray,
    p_rx_loc: np.ndarray,
    z_base_over: np.ndarray,
    xg: np.ndarray,
    yg: np.ndarray,
    alpha_gain: float,
    beta: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute I_2D_coh and I_2D_env on (xg, yg) grid at z_slice = z_4 with exact RF carrier restoration."""
    n_over = z_base_over.shape[-1]
    ts_over = TP / n_over
    xx, yy = np.meshgrid(xg, yg, indexing="xy")  # (Ny, Nx)
    num_coh = np.zeros_like(xx, dtype=np.complex128)
    num_env = np.zeros_like(xx, dtype=np.float64)
    den = np.zeros_like(xx, dtype=np.float64)

    for j_idx, xj in enumerate(x_scan):
        w_ap = aperture_weight(xx - xj, yy)
        if not np.any(w_ap > 0.0):
            continue
        r_tx = np.hypot(xx - xj, yy)  # z_slice == z_tx for row 4
        for c_idx in range(p_rx_loc.shape[0]):
            x_rx = xj + p_rx_loc[c_idx, 0]
            r_rx = np.hypot(xx - x_rx, yy)
            tau = (r_tx + r_rx) / C0
            gain = gain_bsec(tau, beta=beta, alpha_gain_per_ns=alpha_gain) if (alpha_gain > 0.0 or beta > 0.0) else 1.0
            # Interpolate analytic baseband (centered around 1 GHz << 8 GHz oversampled rate),
            # then multiply exact 2nd-Nyquist carrier exp(-j*2*pi*fs*tau)!
            idx_f = tau / ts_over
            i0 = np.floor(idx_f).astype(np.int64) % n_over
            frac = idx_f - np.floor(idx_f)
            i1 = (i0 + 1) % n_over
            z_tr = z_base_over[j_idx, c_idx]
            val_base = (1.0 - frac) * z_tr[i0] + frac * z_tr[i1]
            val = val_base * np.exp(-1j * 2.0 * np.pi * FS * tau)
            w_tot = w_ap * gain
            num_coh += w_tot * val
            num_env += w_tot * np.abs(val)
            den += w_ap

    safe_den = np.maximum(den, 1e-12)
    mask_valid = den > 0.0
    i_coh = np.where(mask_valid, np.abs(num_coh / safe_den) ** 2, 0.0)
    i_env = np.where(mask_valid, (num_env / safe_den) ** 2, 0.0)
    return i_coh, i_env


def evaluate_wall_metrics(xg: np.ndarray, yg: np.ndarray, img: np.ndarray) -> dict[str, float]:
    # Near zone A: y in [0.25, 0.80] m; Far zone B: y in [1.75, 2.25] m; median across domain
    mask_a = (yg >= 0.25) & (yg <= 0.80)
    mask_b = (yg >= 1.75) & (yg <= 2.25)
    peak_a = float(np.max(img[mask_a, :]))
    peak_b = float(np.max(img[mask_b, :]))
    bg_med = float(np.median(img[img > 0.0]))
    delta_b_a_db = 10.0 * math.log10(peak_b / peak_a)
    pbr_b_db = 10.0 * math.log10(peak_b / bg_med)

    # Extract Wall A tilt across x in [0.30, 1.00]
    x_a_mask = (xg >= 0.30) & (xg <= 1.00)
    y_a_sub = yg[mask_a]
    idx_a_ridge = np.argmax(img[np.ix_(mask_a, x_a_mask)], axis=0)
    y_a_est = y_a_sub[idx_a_ridge]
    slope, _ = np.polyfit(xg[x_a_mask], y_a_est, 1)
    tilt_deg = math.degrees(math.atan(slope))

    # Extract unshadowed Wall B depth across x in [-0.15, 0.15] and [1.15, 1.35]
    x_b_air = ((xg >= -0.15) & (xg <= 0.15)) | ((xg >= 1.15) & (xg <= 1.35))
    y_b_sub = yg[mask_b]
    idx_b_ridge = np.argmax(img[np.ix_(mask_b, x_b_air)], axis=0)
    y_b_est_med = float(np.median(y_b_sub[idx_b_ridge]))
    return {
        "delta_b_a_db": delta_b_a_db,
        "pbr_b_db": pbr_b_db,
        "tilt_a_deg": tilt_deg,
        "y_b_est_m": y_b_est_med,
    }


def main() -> None:
    coords, row4_rx = build_array_coords()
    band, f_d, f_r, s_b = make_reference_band()

    # 1. Verify exact geometry anchors from Q2 spec
    assert len(row4_rx) == 7 and 28 in row4_rx and 27 not in row4_rx
    assert math.isclose(coords[27, 2], 0.545, abs_tol=1e-9)
    assert math.isclose(coords[28, 0], -0.07, abs_tol=1e-9)

    # 2. Verify bounded gain caps properly
    tau_probe = np.array([0.5e-9, 13.34e-9, 20.0e-9, 500.0e-9])
    g_probe = gain_bsec(tau_probe, beta=1.0, alpha_gain_per_ns=0.14, g_cap=20.0)
    assert math.isclose(g_probe[0], 1.0, abs_tol=1e-9), "Direct-wave transition zone must stay unity"
    assert g_probe[2] <= 20.0 and g_probe[3] == g_probe[2], "Late-delay gain must saturate cleanly"

    # 3. Run synthetic dual-wall closed-loop simulation & compare before/after gain
    x_scan, p_rx_loc, z_mf = simulate_dual_wall_synthetic(coords, row4_rx, band, f_d, f_r, s_b)
    assert math.isclose(x_scan[0], -0.20, abs_tol=1e-9) and math.isclose(x_scan[-1], 1.40, abs_tol=1e-9)

    xg = np.arange(-0.20, 1.4001, 0.02)
    yg = np.arange(0.05, 2.5001, 0.01)

    i0_coh, _ = reconstruct_2d(x_scan, coords[27], p_rx_loc, z_mf, xg, yg, alpha_gain=0.0, beta=0.0)
    ig_coh, ig_env = reconstruct_2d(x_scan, coords[27], p_rx_loc, z_mf, xg, yg, alpha_gain=0.14, beta=1.0)
    i_over, _ = reconstruct_2d(x_scan, coords[27], p_rx_loc, z_mf, xg, yg, alpha_gain=0.35, beta=1.5)

    m0 = evaluate_wall_metrics(xg, yg, i0_coh)
    mg = evaluate_wall_metrics(xg, yg, ig_coh)
    m_env = evaluate_wall_metrics(xg, yg, ig_env)
    m_over = evaluate_wall_metrics(xg, yg, i_over)

    true_tilt_deg = math.degrees(math.atan((0.56 - 0.37) / (1.06 - 0.25)))
    print(f"[Q2-SPEC] Planted Wall A tilt: {true_tilt_deg:.2f} deg, Wall B y_true: 2.000 m")
    print(f"[NO GAIN ] delta_B/A={m0['delta_b_a_db']:+.2f}dB, PBR_B={m0['pbr_b_db']:.2f}dB, yB={m0['y_b_est_m']:.3f}m")
    print(f"[GAIN COH] delta_B/A={mg['delta_b_a_db']:+.2f}dB, PBR_B={mg['pbr_b_db']:.2f}dB, "
          f"tiltA={mg['tilt_a_deg']:.2f}deg, yB={mg['y_b_est_m']:.3f}m")
    print(f"[GAIN ENV] delta_B/A={m_env['delta_b_a_db']:+.2f}dB, PBR_B={m_env['pbr_b_db']:.2f}dB, yB={m_env['y_b_est_m']:.3f}m")
    print(f"[OVERGAIN] delta_B/A={m_over['delta_b_a_db']:+.2f}dB, PBR_B={m_over['pbr_b_db']:.2f}dB")

    gain_improve_db = mg["delta_b_a_db"] - m0["delta_b_a_db"]
    assert m0["delta_b_a_db"] < -15.0, "Baseline without gain should show strongly attenuated back wall"
    assert gain_improve_db >= 10.0, f"Expected >= 10 dB B/A improvement, got {gain_improve_db:.2f} dB"
    assert mg["pbr_b_db"] >= 15.0, f"Expected PBR_B >= 15 dB, got {mg['pbr_b_db']:.2f} dB"
    assert abs(mg["y_b_est_m"] - 2.00) <= 0.02, f"Back wall range error > 2 cm: {mg['y_b_est_m']}"
    assert abs(mg["tilt_a_deg"] - true_tilt_deg) <= 1.5, f"Wall A tilt err > 1.5 deg: {mg['tilt_a_deg']}"
    assert mg["pbr_b_db"] > m_env["pbr_b_db"], "Coherent BPA should outperform envelope BPA in PBR under phase alignment"
    assert mg["pbr_b_db"] > m_over["pbr_b_db"], "Excessive alpha_gain must degrade PBR_B due to noise inflation"
    print("ALL_Q2_SPEC_SYNTHETIC_CHECKS_PASSED")


if __name__ == "__main__":
    main()
