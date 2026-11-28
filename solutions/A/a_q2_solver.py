#!/usr/bin/env python3
"""Q2 2D synthetic solver baseline implementing M2-Gain-BSEC and M2-Img-CohBPA / EnvBPA."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from a_q2q3_common import (
    C0,
    G_CAP_DEFAULT,
    Y0_DEFAULT_M,
    Y_SAT_DEFAULT_M,
    Z_SLICE_ROW4_M,
    gain_bsec,
    interp_rf_response,
    parabolic_ridge_y,
    taper_cos,
    upstream_synthetic_metadata,
)


def reconstruct_row_2d(
    scene: dict[str, Any],
    row_id: int,
    xg: np.ndarray,
    yg: np.ndarray,
    alpha_gain: float,
    beta: float = 1.0,
    z_slice_m: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Reconstruct 2D (Ny, Nx) coherent and envelope energy maps for a given row with exact 3D z geometry."""
    coords = scene["coords"]
    all_rx = scene["all_rx"]
    rx_global = scene["row_rx"][row_id]
    rx_pos_in_all = [all_rx.index(idx) for idx in rx_global]
    p_tx_loc = coords[27]
    p_rx_loc = coords[rx_global]
    if z_slice_m is None:
        z_slice_m = float(p_rx_loc[0, 2])

    x_scan = scene["x_scan_m"]
    z_traces_row = scene["z_base_over"][:, rx_pos_in_all, :]  # (33, M_row, N_over)

    xx, yy = np.meshgrid(xg, yg, indexing="xy")
    num_coh = np.zeros_like(xx, dtype=np.complex128)
    num_env = np.zeros_like(xx, dtype=np.float64)
    den = np.zeros_like(xx, dtype=np.float64)

    dz_tx = z_slice_m - float(p_tx_loc[2])
    dz_rx = z_slice_m - p_rx_loc[:, 2]  # (M_row,)

    for j_idx, xj in enumerate(x_scan):
        dx_tx = xx - xj
        ang_x = np.degrees(np.arctan2(np.abs(dx_tx), np.maximum(yy, 0.05)))
        w_ap = taper_cos(ang_x, 35.0, 45.0)
        if not np.any(w_ap > 0.0):
            continue

        r_tx = np.sqrt(dx_tx ** 2 + yy ** 2 + dz_tx ** 2)  # (Ny, Nx)
        x_rx = xj + p_rx_loc[:, 0]  # (M_row,)
        r_rx = np.sqrt((xx[None, :, :] - x_rx[:, None, None]) ** 2 + yy[None, :, :] ** 2 + (dz_rx ** 2)[:, None, None])
        tau = (r_tx[None, :, :] + r_rx) / C0  # (M_row, Ny, Nx)
        gain = gain_bsec(tau, beta=beta, alpha_gain_per_ns=alpha_gain) if (alpha_gain > 0.0 or beta > 0.0) else 1.0
        val = interp_rf_response(z_traces_row[j_idx], tau)  # (M_row, Ny, Nx)
        w_tot = w_ap[None, :, :] * gain
        num_coh += np.sum(w_tot * val, axis=0)
        num_env += np.sum(w_tot * np.abs(val), axis=0)
        den += float(len(rx_global)) * w_ap

    safe_den = np.maximum(den, 1e-12)
    valid = den > 0.0
    i_coh = np.where(valid, np.abs(num_coh / safe_den) ** 2, 0.0)
    i_env = np.where(valid, (num_env / safe_den) ** 2, 0.0)
    return i_coh, i_env


def evaluate_q2_image_metrics(xg: np.ndarray, yg: np.ndarray, img: np.ndarray, include_far_diag: bool = True) -> dict[str, float]:
    """Compute M2 §2.3 & §3.2 quantitative wall-contrast and continuity metrics."""
    mask_a = (yg >= 0.25) & (yg <= 0.80)
    mask_b = (yg >= 1.75) & (yg <= 2.25)
    mask_near = (yg >= 0.25) & (yg <= 1.00)
    mask_far = (yg >= 1.20) & (yg <= 2.40)

    positive = img[img > 0.0]
    bg_med = float(np.median(positive)) if positive.size else 1e-12
    peak_a = max(float(np.max(img[mask_a, :])), 1e-30)
    peak_b = max(float(np.max(img[mask_b, :])), 1e-30)
    peak_near = max(float(np.max(img[mask_near, :])), 1e-30)
    peak_far = max(float(np.max(img[mask_far, :])), 1e-30)

    # Sidelobe guard around far-zone ridge peak per column
    y_far = yg[mask_far]
    img_far = img[mask_far, :]
    col_peaks_b = np.max(img[mask_b, :], axis=0)
    ridge_idx = np.argmax(img_far, axis=0)
    sidelobe_vals = []
    col_cov_hits = 0
    noise_floor_far = np.median(img_far, axis=0)
    for ix in range(len(xg)):
        y_r = y_far[ridge_idx[ix]]
        outside = np.abs(y_far - y_r) > 0.22
        if np.any(outside):
            sidelobe_vals.append(float(np.max(img_far[outside, ix])))
        col_noise = max(float(noise_floor_far[ix]), 1e-30)
        if col_peaks_b[ix] >= 10.0 * bg_med and col_peaks_b[ix] >= (10.0 ** 0.6) * col_noise:
            col_cov_hits += 1
    max_sidelobe_far = max(max(sidelobe_vals) if sidelobe_vals else 1e-30, 1e-30)

    metrics = {
        "delta_ba_db": float(10.0 * math.log10(peak_b / peak_a)),
        "pbr_b_db": float(10.0 * math.log10(peak_b / bg_med)),
        "pslr_b_db": float(10.0 * math.log10(peak_b / max_sidelobe_far)),
        "b_coverage_pct": float(100.0 * col_cov_hits / max(len(xg), 1)),
    }
    if include_far_diag:
        metrics["delta_far_near_db"] = float(10.0 * math.log10(peak_far / peak_near))
        metrics["c_far_med_db"] = float(10.0 * math.log10(peak_far / bg_med))
    return metrics


def extract_wall_boundaries(xg: np.ndarray, yg: np.ndarray, img: np.ndarray) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract tilted Wall A front ridge and segmented air/behind-A Wall B apparent depth."""
    positive = img[img > 0.0]
    bg_med = float(np.median(positive)) if positive.size else 1e-12

    mask_a = (yg >= 0.25) & (yg <= 0.85)
    y_a_sub = yg[mask_a]
    col_max_a = np.max(img[mask_a, :], axis=0)
    peak_a = float(np.max(col_max_a))
    strong_a = col_max_a >= max(0.035 * peak_a, 100.0 * bg_med)

    # Pick longest contiguous horizontal support of primary Wall A
    idx_hits = np.where(strong_a)[0]
    if idx_hits.size >= 3:
        splits = np.where(np.diff(idx_hits) > 2)[0] + 1
        runs = np.split(idx_hits, splits)
        best_run = max(runs, key=lambda r: float(np.sum(col_max_a[r])))
        x_min_a = float(xg[best_run[0]])
        x_max_a = float(xg[best_run[-1]])
    else:
        x_min_a, x_max_a = 0.25, 1.06

    # Restrict regression strictly to high-SNR interior support so edge sidelobes do not bias slope
    x_fit_mask = (xg >= x_min_a + 0.04) & (xg <= x_max_a - 0.04) & strong_a
    if int(np.sum(x_fit_mask)) < 3:
        x_fit_mask = (xg >= x_min_a) & (xg <= x_max_a)
    x_fit = xg[x_fit_mask]
    y_fit = parabolic_ridge_y(y_a_sub, img[np.ix_(mask_a, x_fit_mask)])
    slope, intercept = np.polyfit(x_fit, y_fit, 1)
    y_pred = slope * x_fit + intercept
    ss_res = float(np.sum((y_fit - y_pred) ** 2))
    ss_tot = max(float(np.sum((y_fit - float(np.mean(y_fit))) ** 2)), 1e-12)
    fit_r2 = float(1.0 - ss_res / ss_tot)
    tilt_deg = float(math.degrees(math.atan(slope)))

    wall_a = {
        "x_min_m": x_min_a,
        "x_max_m": x_max_a,
        "y_start_m": float(slope * x_min_a + intercept),
        "y_end_m": float(slope * x_max_a + intercept),
        "slope_dy_dx": float(slope),
        "tilt_deg": tilt_deg,
        "fit_r2": fit_r2,
    }

    # Partition Wall B into air-path segments outside Wall A and behind-Wall-A segment
    mask_b = (yg >= 1.75) & (yg <= 2.30)
    y_b_sub = yg[mask_b]
    left_end = max(float(xg.min()) + 0.08, x_min_a - 0.08)
    right_start = min(float(xg.max()) - 0.08, x_max_a + 0.08)
    air_ranges = [
        [float(xg.min()) + 0.04, left_end],
        [right_start, float(xg.max()) - 0.04],
    ]
    air_mask = ((xg >= air_ranges[0][0]) & (xg <= air_ranges[0][1])) | (
        (xg >= air_ranges[1][0]) & (xg <= air_ranges[1][1])
    )
    behind_range = [x_min_a + 0.08, x_max_a - 0.08]
    behind_mask = (xg >= behind_range[0]) & (xg <= behind_range[1])

    y_b_air = parabolic_ridge_y(y_b_sub, img[np.ix_(mask_b, air_mask)])
    y_b_behind = parabolic_ridge_y(y_b_sub, img[np.ix_(mask_b, behind_mask)])
    air_slope, _ = np.polyfit(xg[air_mask], y_b_air, 1)

    air_y_mean = float(np.mean(y_b_air))
    behind_y_mean = float(np.mean(y_b_behind))
    delta_y_app = float(behind_y_mean - air_y_mean)
    d_wall_a_m = 0.105
    eps_r_diag = float((1.0 + max(delta_y_app, 0.0) / d_wall_a_m) ** 2)

    wall_b = {
        "air_x_ranges_m": air_ranges,
        "air_y_mean_m": air_y_mean,
        "air_tilt_deg": float(math.degrees(math.atan(air_slope))),
        "behind_a_x_range_m": behind_range,
        "behind_a_y_mean_m": behind_y_mean,
        "delta_y_app_m": delta_y_app,
        "eps_r_diag": eps_r_diag,
    }
    return wall_a, wall_b


def solve_q2_synthetic(
    scene: dict[str, Any],
    dx_m: float = 0.04,
    dy_m: float = 0.02,
    alpha_grid: tuple[float, ...] = (0.0, 0.04, 0.08, 0.12, 0.14, 0.20),
    beta: float = 1.0,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Run complete Q2 2D synthetic solver and return contract-compliant (results_json, arrays_dict)."""
    xg = np.round(np.arange(-0.20, 1.40 + 1e-9, dx_m), 6).astype(np.float64)
    yg = np.round(np.arange(0.05, 2.50 + 1e-9, dy_m), 6).astype(np.float64)

    # 1. Ungained baseline (W_comp == 1)
    img_before_coh, _ = reconstruct_row_2d(scene, row_id=4, xg=xg, yg=yg, alpha_gain=0.0, beta=0.0, z_slice_m=Z_SLICE_ROW4_M)
    m_before = evaluate_q2_image_metrics(xg, yg, img_before_coh, include_far_diag=True)

    # 2. Data-driven alpha_gain sweep without target-coordinate pinning
    delta_fn_list: list[float] = []
    c_fm_list: list[float] = []
    sweep_imgs: dict[float, tuple[np.ndarray, np.ndarray]] = {}
    for alpha in alpha_grid:
        i_c, i_e = reconstruct_row_2d(scene, row_id=4, xg=xg, yg=yg, alpha_gain=alpha, beta=beta, z_slice_m=Z_SLICE_ROW4_M)
        sweep_imgs[alpha] = (i_c, i_e)
        met = evaluate_q2_image_metrics(xg, yg, i_c, include_far_diag=True)
        delta_fn_list.append(met["delta_far_near_db"])
        c_fm_list.append(met["c_far_med_db"])

    c_peak = max(c_fm_list)
    admissible = [
        (idx, a, dfn, cfm)
        for idx, (a, dfn, cfm) in enumerate(zip(alpha_grid, delta_fn_list, c_fm_list))
        if cfm >= c_peak - 1.5 and dfn <= 6.0
    ]
    in_balance = [item for item in admissible if item[2] >= -6.0]
    chosen_pool = in_balance if in_balance else (admissible if admissible else [(len(alpha_grid) - 1, alpha_grid[-1], delta_fn_list[-1], c_fm_list[-1])])
    # Pick highest alpha that maintains far-field contrast within 1.5 dB of peak and brings far/near into [-6, +6] dB
    selected_alpha = float(max(chosen_pool, key=lambda item: (item[2] if item[2] < -6.0 else 0.0, item[1]))[1])

    img_after_coh, img_after_env = sweep_imgs[selected_alpha]
    m_after_coh = evaluate_q2_image_metrics(xg, yg, img_after_coh, include_far_diag=True)
    m_after_env = evaluate_q2_image_metrics(xg, yg, img_after_env, include_far_diag=False)
    wall_a_app, wall_b_app = extract_wall_boundaries(xg, yg, img_after_coh)

    # 3. Cross-row elevation 3D consistency (rows 3 and 5 with full 3D dz)
    img_row3_coh, _ = reconstruct_row_2d(scene, row_id=3, xg=xg, yg=yg, alpha_gain=selected_alpha, beta=beta)
    img_row5_coh, _ = reconstruct_row_2d(scene, row_id=5, xg=xg, yg=yg, alpha_gain=selected_alpha, beta=beta)
    _, wall_b_row3 = extract_wall_boundaries(xg, yg, img_row3_coh)
    _, wall_b_row5 = extract_wall_boundaries(xg, yg, img_row5_coh)
    row_ys = [wall_b_row3["air_y_mean_m"], wall_b_app["air_y_mean_m"], wall_b_row5["air_y_mean_m"]]
    max_row_diff_cm = float((max(row_ys) - min(row_ys)) * 100.0)

    tau_curve_s = np.linspace(0.0, 25.0e-9, 251, dtype=np.float64)
    w_comp_curve = gain_bsec(tau_curve_s, beta=beta, alpha_gain_per_ns=selected_alpha)

    alpha_y_per_m = float((2.0e9 / C0) * selected_alpha)
    slope_db_per_m = float(20.0 * math.log10(math.e) * alpha_y_per_m)

    arrays = {
        "x_grid_m": xg,
        "y_grid_m": yg,
        "x_scan_m": scene["x_scan_m"].astype(np.float64),
        "j_group_ids": scene["j_group_ids"],
        "j_p_common": scene["j_p_common"].astype(np.int64),
        "tau_curve_s": tau_curve_s,
        "w_comp_curve": w_comp_curve.astype(np.float64),
        "image_before_gain_coh": img_before_coh.astype(np.float64),
        "image_after_gain_coh": img_after_coh.astype(np.float64),
        "image_after_gain_env": img_after_env.astype(np.float64),
        "image_row3_coh": img_row3_coh.astype(np.float64),
        "image_row5_coh": img_row5_coh.astype(np.float64),
    }

    anomaly = {
        "group3_sync_common": 3,
        "real_dat_files_read": 0,
        "note": "synthetic mirror of wall-group 3 packet intersection P_common=3; no .dat read",
    }
    meta = upstream_synthetic_metadata(
        phase="Q2",
        arrays=arrays,
        groups_used=scene["j_group_ids"].tolist(),
        anomaly=anomaly,
        energy_prefixes=("image_",),
    )

    results = {
        **meta,
        "row_id": 4,
        "rx_indices": [int(i) for i in scene["row_rx"][4]],
        "z_slice_m": float(Z_SLICE_ROW4_M),
        "gain_params": {
            "beta": float(beta),
            "alpha_gain_per_ns": selected_alpha,
            "alpha_y_per_m": alpha_y_per_m,
            "slope_db_per_m": slope_db_per_m,
            "y0_m": float(Y0_DEFAULT_M),
            "tau0_s": float(2.0 * Y0_DEFAULT_M / C0),
            "y_sat_m": float(Y_SAT_DEFAULT_M),
            "tau_sat_s": float(2.0 * Y_SAT_DEFAULT_M / C0),
            "g_cap": float(G_CAP_DEFAULT),
        },
        "gain_selection": {
            "alpha_grid_per_ns": [float(a) for a in alpha_grid],
            "delta_far_near_db": [float(v) for v in delta_fn_list],
            "c_far_med_db": [float(v) for v in c_fm_list],
            "selected_alpha_per_ns": selected_alpha,
        },
        "metrics_before_gain": m_before,
        "metrics_after_gain_coh": m_after_coh,
        "metrics_after_gain_env": m_after_env,
        "wall_a_apparent": wall_a_app,
        "wall_b_apparent": wall_b_app,
        "row_consistency": {
            "row_3_wall_b_y_m": float(wall_b_row3["air_y_mean_m"]),
            "row_4_wall_b_y_m": float(wall_b_app["air_y_mean_m"]),
            "row_5_wall_b_y_m": float(wall_b_row5["air_y_mean_m"]),
            "max_row_diff_cm": max_row_diff_cm,
        },
    }
    return results, arrays
