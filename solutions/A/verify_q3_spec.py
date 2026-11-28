"""Independent pure-synthetic closed-loop verification for Problem A Q3 math spec (M3).

Verifies ONLY the mathematical formulation, 63-RX 3D geometry, decoupled 3D
aperture weighting, coherent vs envelope 3D backprojection (with 2nd-Nyquist
carrier restoration), 3D-NMS dual-metal localization (column vs shovel), and
behind-metal occlusion ShadowRatio defined in `solutions/A/model_q3.md`.
Does NOT read real `.dat` files and is NOT a production Q3 solver.
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
    """Return 64x3 local coordinates (m) matching M0 §2.1 and 63 valid rx indices."""
    coords = np.zeros((64, 3), dtype=np.float64)
    rx_idx: list[int] = []
    for r in range(1, 9):
        z = (75.5 - 7 * (r - 1)) * 1e-2
        for k in range(1, 9):
            cgrid = (2 * k - 1) if (r % 2 == 1) else (2 * k)
            x = (8 - cgrid) * 0.035
            idx = 8 * (r - 1) + (k - 1)
            coords[idx] = (x, 0.0, z)
            if idx != 27:
                rx_idx.append(idx)
    return coords, rx_idx


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
    alpha_gain_per_ns: float = 0.0,
    y0_m: float = 0.25,
    y_sat_m: float = 2.60,
    g_cap: float = 20.0,
) -> np.ndarray:
    tau0 = 2.0 * y0_m / C0
    tau_sat = 2.0 * y_sat_m / C0
    tau_clip = np.clip(tau_s, tau0, tau_sat)
    tau_ns_excess = np.maximum(tau_clip - tau0, 0.0) * 1.0e9
    g_raw = ((tau_clip / tau0) ** beta) * np.exp(alpha_gain_per_ns * tau_ns_excess)
    return np.minimum(g_cap, g_raw)


def taper_cos(ang_deg: np.ndarray, deg_flat: float, deg_cut: float) -> np.ndarray:
    w = np.ones_like(ang_deg, dtype=np.float64)
    trans = (ang_deg > deg_flat) & (ang_deg <= deg_cut)
    w[trans] = 0.5 * (1.0 + np.cos(np.pi * (ang_deg[trans] - deg_flat) / (deg_cut - deg_flat)))
    w[ang_deg > deg_cut] = 0.0
    return w


def simulate_metal_and_wall_3d(
    coords: np.ndarray,
    rx_idx: list[int],
    band: np.ndarray,
    f_d: np.ndarray,
    f_r: np.ndarray,
    s_b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate 27 stops x 63 RX with a tall metal cylinder, a low metal shovel, and an occluded rear wall."""
    x_scan = 0.05 * np.arange(27, dtype=np.float64)  # 0.00 to 1.30 m
    p_tx_loc = coords[27]
    p_rx_loc = coords[rx_idx]

    # Planted common dispersive H_ref absorbed into S_eff
    u = (f_d - 1.0e9) / 0.7e9
    h_ref = (1.0 + 0.20 * u) * np.exp(1j * (2.0 * np.pi * f_r * 2.0e-10 + 0.5 * u ** 2))
    s_eff = h_ref * s_b * np.exp(1j * 2.0 * np.pi * f_r * (120.25 * TS))
    s_eff_norm = float(np.linalg.norm(s_eff))

    # Planted Target 1: Tall metal column at (0.35, 1.15, z in [0.25, 0.75])
    z_col = np.linspace(0.25, 0.75, 11)
    col_pts = np.column_stack([np.full_like(z_col, 0.35), np.full_like(z_col, 1.15), z_col])
    amp_col = 0.45 / len(z_col)

    # Planted Target 2: Compact low metal shovel at (0.90, 0.75, z in [0.28, 0.42], center z=0.35)
    z_shv = np.linspace(0.28, 0.42, 5)
    shv_pts = np.column_stack([np.full_like(z_shv, 0.90), np.full_like(z_shv, 0.75), z_shv])
    amp_shv = 0.25 / len(z_shv)

    # Background rear wall at y = 2.00 m spanning x in [0, 1.30], z in [0.25, 0.75]
    # Attenuated by -14 dB (~0.20 in amplitude) inside shadow cones behind targets
    xw = np.linspace(0.0, 1.30, 27)
    zw = np.linspace(0.25, 0.75, 6)
    xxw, zzw = np.meshgrid(xw, zw, indexing="xy")
    wall_pts = np.column_stack([xxw.ravel(), np.full(xxw.size, 2.00), zzw.ravel()])
    in_col_shadow = (np.abs(wall_pts[:, 0] - 0.35) <= 0.14) & (wall_pts[:, 2] >= 0.20) & (wall_pts[:, 2] <= 0.80)
    in_shv_shadow = (np.abs(wall_pts[:, 0] - 0.90) <= 0.14) & (wall_pts[:, 2] >= 0.20) & (wall_pts[:, 2] <= 0.50)
    amp_wall = np.where(in_col_shadow | in_shv_shadow, 0.18 * 0.20, 0.18) / wall_pts.shape[0]

    all_pts = np.vstack([col_pts, shv_pts, wall_pts])
    all_amps = np.concatenate([
        np.full(len(col_pts), amp_col),
        np.full(len(shv_pts), amp_shv),
        amp_wall,
    ])

    rng = np.random.default_rng(20261128)
    band_idx = np.where(band)[0]
    osr = 4
    n_over = NP * osr
    z_base_over = np.zeros((len(x_scan), len(rx_idx), n_over), dtype=np.complex128)

    for j_idx, xj in enumerate(x_scan):
        tx_pos = np.array([xj, 0.0, p_tx_loc[2]])
        rx_pos = p_rx_loc.copy()
        rx_pos[:, 0] += xj

        r_tx = np.linalg.norm(all_pts - tx_pos[None, :], axis=1)  # (P,)
        r_rx = np.linalg.norm(all_pts[None, :, :] - rx_pos[:, None, :], axis=2)  # (63, P)
        tau = (r_tx[None, :] + r_rx) / C0
        wt = all_amps[None, :] / (r_tx[None, :] + r_rx)
        # Evaluate spectral response vectorized: (63, F)
        phase = np.exp(1j * 2.0 * np.pi * np.einsum("f,rp->frp", f_r, tau))  # (F, 63, P)
        x_clean = np.einsum("rp,frp->rf", wt, phase) * s_eff[None, :]

        # Moderate AWGN preserving rear wall observability outside shadow
        p_sig = float(np.mean(np.abs(x_clean) ** 2))
        sigma_f = math.sqrt(p_sig * (10.0 ** (-18.0 / 10.0)) * 0.5)
        noise = rng.normal(0.0, sigma_f, size=x_clean.shape) + 1j * rng.normal(0.0, sigma_f, size=x_clean.shape)
        x_tilde = x_clean + noise

        full = np.zeros((len(rx_idx), n_over), dtype=np.complex128)
        full[:, band_idx] = x_tilde * np.conj(s_eff)[None, :]
        z_base_over[j_idx] = n_over * np.fft.ifft(full, axis=1) / s_eff_norm

    return x_scan, p_rx_loc, z_base_over


def reconstruct_3d_slices(
    x_scan: np.ndarray,
    p_tx_loc: np.ndarray,
    p_rx_loc: np.ndarray,
    z_base_over: np.ndarray,
    xg: np.ndarray,
    yg: np.ndarray,
    zg: np.ndarray,
    beta: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute I_3D_coh and I_3D_env on (Nz, Ny, Nx) voxel grid with decoupled 3D aperture weights."""
    n_over = z_base_over.shape[-1]
    ts_over = TP / n_over
    xx, yy = np.meshgrid(xg, yg, indexing="xy")  # (Ny, Nx)

    i_coh = np.zeros((len(zg), len(yg), len(xg)), dtype=np.float64)
    i_env = np.zeros_like(i_coh)

    for z_idx, zv in enumerate(zg):
        num_coh = np.zeros_like(xx, dtype=np.complex128)
        num_env = np.zeros_like(xx, dtype=np.float64)
        den = np.zeros_like(xx, dtype=np.float64)

        dz_tx = zv - p_tx_loc[2]
        dz_rx = zv - p_rx_loc[:, 2]  # (63,)
        ang_z = np.degrees(np.arctan2(np.abs(dz_rx[:, None, None]), np.maximum(yy[None, :, :], 0.05)))
        wz_all = taper_cos(ang_z, 45.0, 55.0)  # (63, Ny, Nx)

        for j_idx, xj in enumerate(x_scan):
            dx_tx = xx - xj
            ang_x = np.degrees(np.arctan2(np.abs(dx_tx), np.maximum(yy, 0.05)))
            wx = taper_cos(ang_x, 35.0, 45.0)
            if not np.any(wx > 0.0):
                continue
            r_tx = np.sqrt(dx_tx ** 2 + yy ** 2 + dz_tx ** 2)
            for c_idx in range(p_rx_loc.shape[0]):
                w_ap = wx * wz_all[c_idx]
                if not np.any(w_ap > 0.0):
                    continue
                x_rx = xj + p_rx_loc[c_idx, 0]
                r_rx = np.sqrt((xx - x_rx) ** 2 + yy ** 2 + dz_rx[c_idx] ** 2)
                tau = (r_tx + r_rx) / C0
                gain = gain_bsec(tau, beta=beta, alpha_gain_per_ns=0.0)
                idx_f = tau / ts_over
                i0 = np.floor(idx_f).astype(np.int64) % n_over
                frac = idx_f - np.floor(idx_f)
                i1 = (i0 + 1) % n_over
                z_tr = z_base_over[j_idx, c_idx]
                val = ((1.0 - frac) * z_tr[i0] + frac * z_tr[i1]) * np.exp(-1j * 2.0 * np.pi * FS * tau)
                w_tot = w_ap * gain
                num_coh += w_tot * val
                num_env += w_tot * np.abs(val)
                den += w_ap

        safe_den = np.maximum(den, 1e-12)
        valid = den > 0.0
        i_coh[z_idx] = np.where(valid, np.abs(num_coh / safe_den) ** 2, 0.0)
        i_env[z_idx] = np.where(valid, (num_env / safe_den) ** 2, 0.0)

    return i_coh, i_env


def detect_metal_peaks_3d(
    xg: np.ndarray,
    yg: np.ndarray,
    zg: np.ndarray,
    img_3d: np.ndarray,
) -> list[dict[str, float]]:
    """Extract separated compact metal targets via (x,y) column 3D-NMS over y < 1.70 m.

    For each detected target, computes discrete peak, -10 dB bounding box,
    -10 dB vertical span, and -10 dB intensity-weighted 3D centroid inside the local NMS box.
    """
    y_front = yg < 1.70
    sub_orig = img_3d[:, y_front, :]
    sub = sub_orig.copy()
    yg_sub = yg[y_front]
    bg_med = float(np.median(img_3d[img_3d > 0.0]))
    thresh = bg_med * (10.0 ** 1.2)  # +12 dB above median background

    peaks: list[dict[str, float]] = []
    # Suppress full vertical column at each detected (x, y) footprint so a tall pole stays one object
    rx = max(1, int(math.ceil(0.14 / (xg[1] - xg[0]))))
    ry = max(1, int(math.ceil(0.18 / (yg[1] - yg[0]))))

    for _ in range(5):
        flat_idx = int(np.argmax(sub))
        val = float(sub.flat[flat_idx])
        if val < thresh:
            break
        kz, ky, kx = np.unravel_index(flat_idx, sub.shape)
        y0, y1 = max(0, ky - ry), min(sub.shape[1], ky + ry + 1)
        x0, x1 = max(0, kx - rx), min(sub.shape[2], kx + rx + 1)

        # Evaluate -10 dB (>= 0.10 * val) bounding box and energy-weighted centroid within local column ROI
        roi = sub_orig[:, y0:y1, x0:x1]
        mask_10db = roi >= 0.10 * val
        assert np.any(mask_10db), "Expected at least peak voxel inside -10 dB ROI"
        iz, iy, ix = np.where(mask_10db)
        w = roi[mask_10db]
        w_sum = float(np.sum(w))
        z_vals = zg[iz]
        y_vals = yg_sub[y0 + iy]
        x_vals = xg[x0 + ix]

        peaks.append({
            "x_m": float(xg[kx]),
            "y_m": float(yg_sub[ky]),
            "z_m": float(zg[kz]),
            "xc_m": float(np.sum(w * x_vals) / w_sum),
            "yc_m": float(np.sum(w * y_vals) / w_sum),
            "zc_m": float(np.sum(w * z_vals) / w_sum),
            "val": val,
            "z_span_10db_m": float(z_vals.max() - z_vals.min()),
            "bbox_x_min": float(x_vals.min()),
            "bbox_x_max": float(x_vals.max()),
            "bbox_y_min": float(y_vals.min()),
            "bbox_y_max": float(y_vals.max()),
            "bbox_z_min": float(z_vals.min()),
            "bbox_z_max": float(z_vals.max()),
        })
        sub[:, y0:y1, x0:x1] = 0.0

    return peaks


def main() -> None:
    coords, rx_idx = build_array_coords()
    band, f_d, f_r, s_b = make_reference_band()

    # 1. Verify full 63-RX 3D local coordinate bounds
    assert len(rx_idx) == 63 and 27 not in rx_idx and 28 in rx_idx
    p_rx = coords[rx_idx]
    assert math.isclose(float(p_rx[:, 0].min()), -0.280, abs_tol=1e-9)
    assert math.isclose(float(p_rx[:, 0].max()), +0.245, abs_tol=1e-9)
    assert math.isclose(float(p_rx[:, 2].min()), 0.265, abs_tol=1e-9)
    assert math.isclose(float(p_rx[:, 2].max()), 0.755, abs_tol=1e-9)

    # Verify near-field low-height corner (y=0.40 m, z=0.20 m) keeps non-zero 3D aperture weights
    dz_low = np.abs(0.20 - p_rx[:, 2])
    ang_low = np.degrees(np.arctan2(dz_low, 0.40))
    wz_low = taper_cos(ang_low, 45.0, 55.0)
    assert int(np.sum(wz_low > 0.5)) >= 16, "Decoupled elevation window must illuminate z=0.20 m at y=0.40 m"

    # 2. Simulate 27 stops x 63 RX with column + shovel + occluded rear wall
    x_scan, p_rx_loc, z_base_over = simulate_metal_and_wall_3d(coords, rx_idx, band, f_d, f_r, s_b)
    assert math.isclose(x_scan[0], 0.00, abs_tol=1e-9) and math.isclose(x_scan[-1], 1.30, abs_tol=1e-9)

    # Use coarse-medium 3D grid (dx=0.05, dy=0.05, dz=0.04 m) for fast self-check (< 10 s CPU)
    xg = np.arange(0.00, 1.3001, 0.05)
    yg = np.arange(0.20, 2.3001, 0.05)
    zg = np.arange(0.20, 0.8001, 0.04)

    i3_coh, i3_env = reconstruct_3d_slices(x_scan, coords[27], p_rx_loc, z_base_over, xg, yg, zg, beta=1.0)
    peaks = detect_metal_peaks_3d(xg, yg, zg, i3_coh)
    assert len(peaks) >= 2, f"Expected >= 2 metal objects detected, got {len(peaks)}"

    # Match planted column (0.35, 1.15) and shovel (0.90, 0.75, z=0.35), requiring DISTINCT peak indices
    idx_col = min(range(len(peaks)), key=lambda idx: math.hypot(peaks[idx]["x_m"] - 0.35, peaks[idx]["y_m"] - 1.15))
    idx_shv = min(range(len(peaks)), key=lambda idx: math.hypot(peaks[idx]["x_m"] - 0.90, peaks[idx]["y_m"] - 0.75))
    assert idx_col != idx_shv, "Planted column and shovel matched the same detected peak"
    col_det = peaks[idx_col]
    shv_det = peaks[idx_shv]

    # Column: evaluate XY errors (peak and -10 dB centroid) explicitly
    err_col_peak_xy = math.hypot(col_det["x_m"] - 0.35, col_det["y_m"] - 1.15)
    err_col_cent_xy = math.hypot(col_det["xc_m"] - 0.35, col_det["yc_m"] - 1.15)
    # Shovel: evaluate 3D Euclidean errors (peak and -10 dB centroid) explicitly
    err_shv_peak_3d = math.sqrt((shv_det["x_m"] - 0.90) ** 2 + (shv_det["y_m"] - 0.75) ** 2 + (shv_det["z_m"] - 0.35) ** 2)
    err_shv_cent_3d = math.sqrt((shv_det["xc_m"] - 0.90) ** 2 + (shv_det["yc_m"] - 0.75) ** 2 + (shv_det["zc_m"] - 0.35) ** 2)

    assert err_col_peak_xy <= 0.055 and err_col_cent_xy <= 0.055, (
        f"Column XY errors exceeded 5.5 cm gate: peak={err_col_peak_xy:.3f}, centroid={err_col_cent_xy:.3f}"
    )
    assert err_shv_peak_3d <= 0.060 and err_shv_cent_3d <= 0.060, (
        f"Shovel 3D errors exceeded 6.0 cm gate: peak={err_shv_peak_3d:.3f}, centroid={err_shv_cent_3d:.3f}"
    )
    assert col_det["z_span_10db_m"] - shv_det["z_span_10db_m"] >= 0.08, (
        f"Tall column 10dB z-span ({col_det['z_span_10db_m']:.2f} m) must exceed shovel ({shv_det['z_span_10db_m']:.2f} m) by >= 0.08 m"
    )
    assert col_det["z_m"] - shv_det["z_m"] >= 0.08, (
        f"Column specular peak ({col_det['z_m']:.2f} m) should exceed lower shovel ({shv_det['z_m']:.2f} m) by >= 0.08 m"
    )

    # 3. Check Coherent PBR vs Envelope PBR on column peak
    bg_coh = float(np.median(i3_coh[i3_coh > 0.0]))
    bg_env = float(np.median(i3_env[i3_env > 0.0]))
    pbr_coh = 10.0 * math.log10(col_det["val"] / bg_coh)
    kx_c = int(np.argmin(np.abs(xg - col_det["x_m"])))
    ky_c = int(np.argmin(np.abs(yg - col_det["y_m"])))
    kz_c = int(np.argmin(np.abs(zg - col_det["z_m"])))
    pbr_env = 10.0 * math.log10(float(i3_env[kz_c, ky_c, kx_c]) / bg_env)
    assert pbr_coh > pbr_env, "Coherent 3D BPA should outperform envelope 3D BPA in PBR"

    # 4. Check ShadowRatio behind metal targets on rear wall y in [1.90, 2.10] m
    y_wall = (yg >= 1.90) & (yg <= 2.10)
    z_mid = (zg >= 0.30) & (zg <= 0.65)
    shadow_col = (np.abs(xg - col_det["x_m"]) <= 0.10)
    unocc_x = (xg >= 0.55) & (xg <= 0.70)
    i_shadow = float(np.mean(i3_coh[np.ix_(z_mid, y_wall, shadow_col)]))
    i_unocc = float(np.mean(i3_coh[np.ix_(z_mid, y_wall, unocc_x)]))
    shadow_ratio_db = 10.0 * math.log10(i_shadow / i_unocc)
    assert shadow_ratio_db <= -6.0, f"Expected rear-wall shadow <= -6 dB, got {shadow_ratio_db:.2f} dB"

    print(
        f"[Q3-COL] peak=({col_det['x_m']:.2f},{col_det['y_m']:.2f},{col_det['z_m']:.2f}), "
        f"cent=({col_det['xc_m']:.3f},{col_det['yc_m']:.3f},{col_det['zc_m']:.3f}), "
        f"z_span_10dB={col_det['z_span_10db_m']:.2f}m, err_xy_peak={err_col_peak_xy*100:.1f}cm, "
        f"err_xy_cent={err_col_cent_xy*100:.1f}cm, PBR_coh={pbr_coh:.2f}dB (vs env {pbr_env:.2f}dB)"
    )
    print(
        f"[Q3-SHV] peak=({shv_det['x_m']:.2f},{shv_det['y_m']:.2f},{shv_det['z_m']:.2f}), "
        f"cent=({shv_det['xc_m']:.3f},{shv_det['yc_m']:.3f},{shv_det['zc_m']:.3f}), "
        f"z_span_10dB={shv_det['z_span_10db_m']:.2f}m, err_3d_peak={err_shv_peak_3d*100:.1f}cm, "
        f"err_3d_cent={err_shv_cent_3d*100:.1f}cm"
    )
    print(f"[Q3-SHADOW] behind_column_wall_ShadowRatio={shadow_ratio_db:.2f}dB")
    print("ALL_Q3_SPEC_SYNTHETIC_CHECKS_PASSED")


if __name__ == "__main__":
    main()
