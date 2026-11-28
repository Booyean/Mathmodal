#!/usr/bin/env python3
"""Q3 3D synthetic solver baseline for full 63-RX wall reconstruction, dual-metal 3D-NMS, and shadow diagnostics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from a_q2q3_common import (
    C0,
    G_CAP_DEFAULT,
    Z_SLICE_ROW4_M,
    compute_anomaly_isolation,
    gain_bsec,
    interp_rf_response,
    interval_union_mask,
    parabolic_ridge_y,
    taper_cos,
    upstream_synthetic_metadata,
)


def reconstruct_3d_decoupled_modes(
    scene: dict[str, Any],
    xg: np.ndarray,
    yg: np.ndarray,
    zg: np.ndarray,
    gain_modes: list[tuple[float, float]],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Reconstruct (Nz, Ny, Nx) fields for multiple (beta, alpha_gain) modes in a single 3D pass."""
    p_tx_loc = scene["coords"][27]
    p_rx_loc = scene["coords"][scene["all_rx"]]
    x_scan = scene["x_scan_m"]
    z_base_over = scene["z_base_over"]
    xx, yy = np.meshgrid(xg, yg, indexing="xy")

    n_modes = len(gain_modes)
    nz, ny, nx = len(zg), len(yg), len(xg)
    num_coh = np.zeros((n_modes, nz, ny, nx), dtype=np.complex128)
    num_env = np.zeros((n_modes, nz, ny, nx), dtype=np.float64)
    den = np.zeros((nz, ny, nx), dtype=np.float64)

    # Precompute z-independent horizontal cone masks and planar (x,y)^2 terms once per scan position
    stop_cache: list[tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for j_idx, xj in enumerate(x_scan):
        dx_tx = xx - float(xj)
        ang_x = np.degrees(np.arctan2(np.abs(dx_tx), np.maximum(yy, 0.05)))
        wx = taper_cos(ang_x, 35.0, 45.0)
        py, px = np.where(wx > 0.0)
        if py.size == 0:
            continue
        yy_act = yy[py, px]
        dx_tx2_yy2 = dx_tx[py, px] ** 2 + yy_act ** 2
        x_rx = float(xj) + p_rx_loc[:, 0]
        dx_rx2_yy2 = (xx[py, px][None, :] - x_rx[:, None]) ** 2 + yy_act[None, :] ** 2
        stop_cache.append((j_idx, py, px, wx[py, px], yy_act, dx_tx2_yy2, dx_rx2_yy2))

    dz_tx_all = zg - float(p_tx_loc[2])
    dz_rx_all = zg[:, None] - p_rx_loc[:, 2][None, :]  # (Nz, 63)

    for j_idx, py, px, wx_act, yy_act, dx_tx2_yy2, dx_rx2_yy2 in stop_cache:
        y_safe = np.maximum(yy_act, 0.05)
        traces = z_base_over[j_idx]
        for kz in range(nz):
            dz_tx2 = float(dz_tx_all[kz]) ** 2
            dz_rx = dz_rx_all[kz]  # (63,)
            ang_z = np.degrees(np.arctan2(np.abs(dz_rx[:, None]), y_safe[None, :]))
            wz = taper_cos(ang_z, 45.0, 55.0)
            w_ap = wx_act[None, :] * wz  # (63, M_act)

            r_tx = np.sqrt(dx_tx2_yy2 + dz_tx2)
            r_rx = np.sqrt(dx_rx2_yy2 + (dz_rx ** 2)[:, None])
            tau = (r_tx[None, :] + r_rx) / C0
            val = interp_rf_response(traces, tau)
            abs_val = np.abs(val)
            den[kz, py, px] += np.sum(w_ap, axis=0)

            for m_idx, (beta_m, alpha_m) in enumerate(gain_modes):
                gain = gain_bsec(tau, beta=beta_m, alpha_gain_per_ns=alpha_m) if (alpha_m > 0.0 or beta_m > 0.0) else 1.0
                w_tot = w_ap * gain
                num_coh[m_idx, kz, py, px] += np.sum(w_tot * val, axis=0)
                num_env[m_idx, kz, py, px] += np.sum(w_tot * abs_val, axis=0)

    safe_den = np.maximum(den, 1e-12)
    valid = den > 0.0
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for m_idx in range(n_modes):
        i_coh = np.where(valid, np.abs(num_coh[m_idx] / safe_den) ** 2, 0.0)
        i_env = np.where(valid, (num_env[m_idx] / safe_den) ** 2, 0.0)
        out.append((i_coh, i_env))
    return out


def reconstruct_3d_decoupled(
    scene: dict[str, Any],
    xg: np.ndarray,
    yg: np.ndarray,
    zg: np.ndarray,
    beta: float = 1.0,
    alpha_gain: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Reconstruct (Nz, Ny, Nx) coherent and envelope 3D energy fields over all 63 RX channels."""
    return reconstruct_3d_decoupled_modes(scene, xg, yg, zg, [(beta, alpha_gain)])[0]


def _extract_z_slice_linear(i3_coh: np.ndarray, zg: np.ndarray, target_z_m: float = Z_SLICE_ROW4_M) -> tuple[np.ndarray, dict[str, Any]]:
    """Deterministically extract exact or linear-interpolated z slice strictly from image_3d_coh + z_grid_m."""
    if not (float(zg[0]) - 1e-12 <= target_z_m <= float(zg[-1]) + 1e-12):
        raise ValueError(f"target_z_m={target_z_m} out of z_grid_m range [{zg[0]}, {zg[-1]}]")
    nearest = int(np.argmin(np.abs(zg - target_z_m)))
    if abs(float(zg[nearest]) - target_z_m) <= 1e-12:
        return i3_coh[nearest].copy(), {
            "target_z_m": float(target_z_m),
            "extraction_rule": "exact_z_grid_index",
            "on_grid": True,
            "z_low_idx": nearest,
            "z_high_idx": nearest,
            "z_low_m": float(zg[nearest]),
            "z_high_m": float(zg[nearest]),
            "weight_high": 0.0,
        }
    hi = int(np.searchsorted(zg, target_z_m, side="right"))
    lo = hi - 1
    z_lo, z_hi = float(zg[lo]), float(zg[hi])
    w = (target_z_m - z_lo) / (z_hi - z_lo)
    slice_xy = ((1.0 - w) * i3_coh[lo] + w * i3_coh[hi]).astype(np.float64)
    return slice_xy, {
        "target_z_m": float(target_z_m),
        "extraction_rule": "linear_z_interp_from_image_3d_coh",
        "on_grid": False,
        "z_low_idx": lo,
        "z_high_idx": hi,
        "z_low_m": z_lo,
        "z_high_m": z_hi,
        "weight_high": float(w),
    }


def solve_q3_wall_synthetic(
    scene_wall: dict[str, Any],
    q2_results: dict[str, Any],
    q2_arrays: dict[str, np.ndarray],
    step_m: tuple[float, float, float] = (0.02, 0.02, 0.02),
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Run Q3.1 63-RX 3D wall reconstruction and cross-reconcile air segments with Q2 z_slice_m=0.545 m."""
    dx_m, dy_m, dz_m = step_m
    nx = int(round((1.40 - (-0.20)) / dx_m)) + 1
    ny = int(round(2.50 / dy_m)) + 1
    nz = int(round((0.80 - 0.20) / dz_m)) + 1
    xg = np.round(np.linspace(-0.20, 1.40, nx), 6).astype(np.float64)
    yg = np.round(np.linspace(0.00, 2.50, ny), 6).astype(np.float64)
    zg = np.round(np.linspace(0.20, 0.80, nz), 6).astype(np.float64)

    beta = float(q2_results["gain_params"]["beta"])
    alpha_gain = float(q2_results["gain_params"]["alpha_gain_per_ns"])

    i3_coh, i3_env = reconstruct_3d_decoupled(scene_wall, xg, yg, zg, beta=beta, alpha_gain=alpha_gain)
    slice_xy_z4, slice_z4_spec = _extract_z_slice_linear(i3_coh, zg, Z_SLICE_ROW4_M)

    proj_xy_max = np.max(i3_coh, axis=0)
    proj_xz_max = np.max(i3_coh, axis=1)
    proj_yz_max = np.max(i3_coh, axis=2)

    # Extract Wall A 3D front envelope
    bg_coh = float(np.median(i3_coh[i3_coh > 0.0]))
    bg_env = float(np.median(i3_env[i3_env > 0.0]))
    mask_a = (yg >= 0.25) & (yg <= 0.85)
    y_a_sub = yg[mask_a]
    wall_a_cfg = q2_results["wall_a_apparent"]
    x_a_min_ref = float(wall_a_cfg["x_min_m"])
    x_a_max_ref = float(wall_a_cfg["x_max_m"])
    x_a_mask = (xg >= x_a_min_ref) & (xg <= x_a_max_ref)

    active_z = []
    front_y_samples = []
    slopes = []
    x_fit_a_mask = (xg >= x_a_min_ref + 0.04) & (xg <= x_a_max_ref - 0.04)
    if int(np.sum(x_fit_a_mask)) < 3:
        x_fit_a_mask = x_a_mask
    for kz, zv in enumerate(zg):
        sl_a = i3_coh[kz][np.ix_(mask_a, x_fit_a_mask)]
        if float(np.max(sl_a)) >= 50.0 * bg_coh:
            active_z.append(float(zv))
            y_ridge = parabolic_ridge_y(y_a_sub, sl_a)
            front_y_samples.append(y_ridge)
            sl_slope, _ = np.polyfit(xg[x_fit_a_mask], y_ridge, 1)
            slopes.append(float(sl_slope))
    front_arr = np.concatenate(front_y_samples) if front_y_samples else np.array([0.46])
    wall_a_3d = {
        "x_span_m": [x_a_min_ref, x_a_max_ref],
        "y_front_mean_m": float(np.mean(front_arr)),
        "y_front_range_m": [float(np.min(front_arr)), float(np.max(front_arr))],
        "z_envelope_m": [min(active_z), max(active_z)] if active_z else [float(zg[0]), float(zg[-1])],
        "tilt_deg": float(math.degrees(math.atan(float(np.median(slopes))))) if slopes else float(wall_a_cfg["tilt_deg"]),
    }

    # Wall B 3D air vs behind-A apparent positions + z consistency
    mask_b = (yg >= 1.75) & (yg <= 2.30)
    y_b_sub = yg[mask_b]
    air_ranges = q2_results["wall_b_apparent"]["air_x_ranges_m"]
    air_mask = interval_union_mask(xg, air_ranges)
    behind_range = q2_results["wall_b_apparent"]["behind_a_x_range_m"]
    behind_mask = interval_union_mask(xg, [behind_range])

    z_air_medians = []
    air_y_slices = []
    behind_y_slices = []
    for kz in range(len(zg)):
        y_air_kz = parabolic_ridge_y(y_b_sub, i3_coh[kz][np.ix_(mask_b, air_mask)])
        y_beh_kz = parabolic_ridge_y(y_b_sub, i3_coh[kz][np.ix_(mask_b, behind_mask)])
        z_air_medians.append(float(np.median(y_air_kz)))
        air_y_slices.append(y_air_kz)
        behind_y_slices.append(y_beh_kz)
    air_y_3d_all = np.concatenate(air_y_slices)
    behind_y_3d_all = np.concatenate(behind_y_slices)
    peak_b_coh = float(np.max(i3_coh[:, mask_b, :]))
    peak_b_env = float(np.max(i3_env[:, mask_b, :]))

    wall_b_3d = {
        "air_y_mean_m": float(np.mean(air_y_3d_all)),
        "behind_a_y_mean_m": float(np.mean(behind_y_3d_all)),
        "z_consistency_cm": float((max(z_air_medians) - min(z_air_medians)) * 100.0),
        "pbr_b_coh_db": float(10.0 * math.log10(peak_b_coh / max(bg_coh, 1e-30))),
        "pbr_b_env_db": float(10.0 * math.log10(peak_b_env / max(bg_env, 1e-30))),
    }

    # Reconcile z=0.545 slice air-segment Wall B ridge with Q2 row-4 Wall B ridge
    xg_q2 = q2_arrays["x_grid_m"]
    yg_q2 = q2_arrays["y_grid_m"]
    img_q2 = q2_arrays["image_after_gain_coh"]
    mask_b_q2 = (yg_q2 >= 1.75) & (yg_q2 <= 2.30)
    air_mask_q2 = interval_union_mask(xg_q2, air_ranges)
    y_q2_air = parabolic_ridge_y(yg_q2[mask_b_q2], img_q2[np.ix_(mask_b_q2, air_mask_q2)])
    y_q2_on_q3x = np.interp(xg[air_mask], xg_q2[air_mask_q2], y_q2_air)
    y_q3_z4_air = parabolic_ridge_y(y_b_sub, slice_xy_z4[np.ix_(mask_b, air_mask)])
    diff_cm = np.abs(y_q3_z4_air - y_q2_on_q3x) * 100.0
    max_diff_cm = float(np.max(diff_cm))
    mae_cm = float(np.mean(diff_cm))

    arrays = {
        "x_grid_m": xg,
        "y_grid_m": yg,
        "z_grid_m": zg,
        "image_3d_coh": i3_coh.astype(np.float64),
        "image_3d_env": i3_env.astype(np.float64),
        "slice_xy_z4": slice_xy_z4.astype(np.float64),
        "proj_xy_max": proj_xy_max.astype(np.float64),
        "proj_xz_max": proj_xz_max.astype(np.float64),
        "proj_yz_max": proj_yz_max.astype(np.float64),
    }

    anomaly = compute_anomaly_isolation(scene_wall, phase="Q3-Wall")
    meta = upstream_synthetic_metadata(
        phase="Q3-Wall",
        arrays=arrays,
        groups_used=scene_wall["j_group_ids"].tolist(),
        anomaly=anomaly,
        energy_prefixes=("image_", "slice_", "proj_"),
    )

    results = {
        **meta,
        "grid_spec": {
            "x_range_m": [-0.20, 1.40],
            "y_range_m": [0.00, 2.50],
            "z_range_m": [0.20, 0.80],
            "dx_m": float(dx_m),
            "dy_m": float(dy_m),
            "dz_m": float(dz_m),
            "nx": int(xg.size),
            "ny": int(yg.size),
            "nz": int(zg.size),
            "coarse_step_m": float(max(step_m)),
            "fine_step_m": float(min(step_m)),
        },
        "aperture_weights": {
            "theta_x_flat_deg": 35.0,
            "theta_x_cut_deg": 45.0,
            "theta_z_flat_deg": 45.0,
            "theta_z_cut_deg": 55.0,
            "valid_rx_count": len(scene_wall["all_rx"]),
        },
        "inherited_gain_params": {
            "beta": beta,
            "alpha_gain_per_ns": alpha_gain,
            "g_cap": float(G_CAP_DEFAULT),
        },
        "slice_z4_spec": slice_z4_spec,
        "wall_a_3d": wall_a_3d,
        "wall_b_3d": wall_b_3d,
        "q2_q3_reconciliation": {
            "z_slice_m": float(Z_SLICE_ROW4_M),
            "air_segment_max_diff_cm": max_diff_cm,
            "air_segment_mae_cm": mae_cm,
            "passed_le_2cm": bool(max_diff_cm <= 2.0),
        },
    }
    return results, arrays


def _detect_metal_objects_3d_nms(
    xg: np.ndarray,
    yg: np.ndarray,
    zg: np.ndarray,
    img_3d: np.ndarray,
    radius_x_m: float = 0.14,
    radius_y_m: float = 0.18,
    min_peak_above_med_db: float = 12.0,
    contour_drop_db: float = -10.0,
) -> list[dict[str, Any]]:
    """Column-wise 3D-NMS over metal forward zone y in [0.15, 1.70] m without coordinate priors."""
    y_mask = (yg >= 0.15) & (yg < 1.70)
    yg_sub = yg[y_mask]
    sub_orig = img_3d[:, y_mask, :]
    sub = sub_orig.copy()

    positive = img_3d[img_3d > 0.0]
    bg_med = max(float(np.median(positive)) if positive.size else 1e-12, 1e-30)
    front_peak = float(np.max(sub_orig)) if sub_orig.size else 0.0
    # Reject both near-noise clutter (+12 dB above bg) and range sidelobes (<-12 dB below primary metal peak)
    thresh = max(bg_med * (10.0 ** (min_peak_above_med_db / 10.0)), front_peak * (10.0 ** (-1.2)))
    drop_lin = 10.0 ** (contour_drop_db / 10.0)

    rx = max(1, int(math.ceil(radius_x_m / float(xg[1] - xg[0]))))
    ry = max(1, int(math.ceil(radius_y_m / float(yg[1] - yg[0]))))

    raw_objs: list[dict[str, Any]] = []
    for _ in range(8):
        flat_idx = int(np.argmax(sub))
        val = float(sub.flat[flat_idx])
        if val < thresh:
            break
        kz, ky, kx = np.unravel_index(flat_idx, sub.shape)
        y0, y1 = max(0, ky - ry), min(sub.shape[1], ky + ry + 1)
        x0, x1 = max(0, kx - rx), min(sub.shape[2], kx + rx + 1)

        roi = sub_orig[:, y0:y1, x0:x1]
        mask_iso = roi >= drop_lin * val
        iz, iy, ix = np.where(mask_iso)
        w = roi[mask_iso]
        w_sum = max(float(np.sum(w)), 1e-30)
        z_vals = zg[iz]
        y_vals = yg_sub[y0 + iy]
        x_vals = xg[x0 + ix]

        raw_objs.append({
            "peak_xyz_m": [float(xg[kx]), float(yg_sub[ky]), float(zg[kz])],
            "centroid_10db_xyz_m": [
                float(np.sum(w * x_vals) / w_sum),
                float(np.sum(w * y_vals) / w_sum),
                float(np.sum(w * z_vals) / w_sum),
            ],
            "bbox_10db_m": [
                float(x_vals.min()),
                float(x_vals.max()),
                float(y_vals.min()),
                float(y_vals.max()),
                float(z_vals.min()),
                float(z_vals.max()),
            ],
            "delta_z_10db_m": float(z_vals.max() - z_vals.min()),
            "peak_above_med_db": float(10.0 * math.log10(val / bg_med)),
        })
        sub[:, y0:y1, x0:x1] = 0.0

    # Classify strictly from intrinsic vertical span and peak height without coordinate priors
    if len(raw_objs) >= 2:
        col_cand = max(range(len(raw_objs)), key=lambda i: (raw_objs[i]["delta_z_10db_m"], raw_objs[i]["peak_xyz_m"][2]))
        col_count = 0
        shv_count = 0
        for idx, obj in enumerate(raw_objs):
            if idx == col_cand:
                col_count += 1
                obj["inferred_class"] = "metal_column"
                obj["object_id"] = "metal_col" if col_count == 1 else f"metal_col_{col_count}"
            else:
                shv_count += 1
                obj["inferred_class"] = "metal_shovel"
                obj["object_id"] = "metal_shv" if shv_count == 1 else f"metal_shv_{shv_count}"
    elif len(raw_objs) == 1:
        raw_objs[0]["inferred_class"] = "metal_column" if raw_objs[0]["delta_z_10db_m"] >= 0.25 else "metal_shovel"
        raw_objs[0]["object_id"] = "metal_obj_1"

    return raw_objs


def solve_q3_metal_synthetic(
    scene_metal: dict[str, Any],
    q2_results: dict[str, Any],
    step_m: tuple[float, float, float] = (0.02, 0.02, 0.02),
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Run Q3.2 63-RX 3D metal localization + rear-wall occlusion diagnostics under PR #38 contract."""
    dx_m, dy_m, dz_m = step_m
    nx = int(round(1.30 / dx_m)) + 1
    ny = int(round(2.50 / dy_m)) + 1
    nz = int(round((0.80 - 0.20) / dz_m)) + 1
    xg = np.round(np.linspace(0.00, 1.30, nx), 6).astype(np.float64)
    yg = np.round(np.linspace(0.00, 2.50, ny), 6).astype(np.float64)
    zg = np.round(np.linspace(0.20, 0.80, nz), 6).astype(np.float64)

    shadow_alpha = float(q2_results["gain_params"]["alpha_gain_per_ns"])
    # Compute primary (beta=1, alpha=0) and shadow diagnostic (beta=1, alpha=shadow_alpha) in a single 3D pass
    (i3_coh, i3_env), (i3_shadow_gain, _) = reconstruct_3d_decoupled_modes(
        scene_metal, xg, yg, zg, [(1.0, 0.0), (1.0, shadow_alpha)]
    )

    radius_x_m, radius_y_m = 0.14, 0.18
    min_peak_db, contour_drop_db = 12.0, -10.0
    metal_objects = _detect_metal_objects_3d_nms(
        xg,
        yg,
        zg,
        i3_coh,
        radius_x_m=radius_x_m,
        radius_y_m=radius_y_m,
        min_peak_above_med_db=min_peak_db,
        contour_drop_db=contour_drop_db,
    )

    # Contiguous rear-wall y-band around 2.00 m: [1.85, 2.15] m
    wall_indices = np.where((yg >= 1.85 - 1e-9) & (yg <= 2.15 + 1e-9))[0]
    idx_start = int(wall_indices[0])
    idx_end = int(wall_indices[-1]) + 1
    y_wall_band_m = yg[idx_start:idx_end].copy()

    # Mid-height rear-wall profile (z in [0.30, 0.55] m covers both tall column and low shovel shadow cones)
    z_band = (zg >= 0.30 - 1e-9) & (zg <= 0.55 + 1e-9)
    shadow_profile_x_y = np.mean(i3_shadow_gain[z_band, idx_start:idx_end, :], axis=0).astype(np.float64)

    # Compute unique global unoccluded median strictly excluding union of all metal [x_min, x_max]
    occ_union = interval_union_mask(xg, [[obj["bbox_10db_m"][0], obj["bbox_10db_m"][1]] for obj in metal_objects])
    unocc_mask = ~occ_union
    if not np.any(unocc_mask):
        unocc_mask = np.ones_like(xg, dtype=bool)
    shadow_unocc_global_med = float(np.median(shadow_profile_x_y[:, unocc_mask]))

    # Compute per-object ShadowRatio using object_id indexing and declared +-0.45 m unoccluded sideband
    per_object_half_w_m = 0.45
    shadow_diagnostics: list[dict[str, Any]] = []
    for obj in metal_objects:
        bx0, bx1 = obj["bbox_10db_m"][0], obj["bbox_10db_m"][1]
        px = obj["peak_xyz_m"][0]
        py = obj["peak_xyz_m"][1]
        x_obj_mask = interval_union_mask(xg, [[bx0, bx1]])
        if not np.any(x_obj_mask):
            x_obj_mask = np.zeros_like(xg, dtype=bool)
            x_obj_mask[int(np.argmin(np.abs(xg - px)))] = True
        i_shadow_bar = float(np.mean(shadow_profile_x_y[:, x_obj_mask]))

        local_side = unocc_mask & (np.abs(xg - px) <= per_object_half_w_m + 1e-9)
        ref_cols = local_side if np.any(local_side) else unocc_mask
        i_unocc_med = float(np.median(shadow_profile_x_y[:, ref_cols]))
        ratio_db = float(10.0 * math.log10(max(i_shadow_bar, 1e-30) / max(i_unocc_med, 1e-30)))
        shadow_diagnostics.append({
            "object_id": obj["object_id"],
            "y_shadow_start_m": float(py + 0.25),
            "y_wall_band_m": [float(y_wall_band_m[0]), float(y_wall_band_m[-1])],
            "i_shadow_bar": i_shadow_bar,
            "i_unocc_med": i_unocc_med,
            "shadow_ratio_db": ratio_db,
            "shadow_confirmed": bool(ratio_db <= -6.0),
        })

    arrays = {
        "x_grid_m": xg,
        "y_grid_m": yg,
        "z_grid_m": zg,
        "y_wall_band_m": y_wall_band_m,
        "image_3d_coh": i3_coh.astype(np.float64),
        "image_3d_env": i3_env.astype(np.float64),
        "image_3d_shadow_gain": i3_shadow_gain.astype(np.float64),
        "shadow_profile_x_y": shadow_profile_x_y,
    }

    anomaly_isolation = compute_anomaly_isolation(scene_metal, phase="Q3-Metal")
    meta = upstream_synthetic_metadata(
        phase="Q3-Metal",
        arrays=arrays,
        groups_used=scene_metal["j_group_ids"].tolist(),
        anomaly=anomaly_isolation,
        energy_prefixes=("image_", "shadow_profile_"),
    )

    results = {
        **meta,
        "grid_spec": {
            "x_range_m": [0.00, 1.30],
            "y_range_m": [0.00, 2.50],
            "z_range_m": [0.20, 0.80],
            "dx_m": float(dx_m),
            "dy_m": float(dy_m),
            "dz_m": float(dz_m),
            "nx": int(xg.size),
            "ny": int(yg.size),
            "nz": int(zg.size),
            "coarse_step_m": float(max(step_m)),
            "fine_step_m": float(min(step_m)),
        },
        "gain_modes": {
            "primary_localization": 0.0,
            "shadow_diagnostic": shadow_alpha,
        },
        "nms_params": {
            "radius_x_m": radius_x_m,
            "radius_y_m": radius_y_m,
            "min_peak_above_med_db": min_peak_db,
            "contour_drop_db": contour_drop_db,
            "bbox_axis_order": ["x_min_m", "x_max_m", "y_min_m", "y_max_m", "z_min_m", "z_max_m"],
        },
        "metal_objects": metal_objects,
        "shadow_diagnostics": shadow_diagnostics,
        "shadow_unocc_global_med": shadow_unocc_global_med,
        "resolution_limits": {
            "dy_res_m": float(C0 / (2.0 * 1.4e9)),
            "dx_res_m": float((C0 / 3.0e9) / (4.0 * math.sin(math.radians(45.0)))),
            "dz_res_at_08m_m": float((C0 / 3.0e9) * 0.8 / 0.490),
            "dz_res_at_20m_m": float((C0 / 3.0e9) * 2.0 / 0.490),
        },
        "shadow_profile_axis_spec": {
            "y_wall_band_idx_start": idx_start,
            "y_wall_band_idx_end": idx_end,
            "ref_energy_key": "shadow_unocc_global_med",
            "multi_target_rule": "exclude_union_of_all_metal_x_boxes",
            "per_object_ratio_source": "shadow_diagnostics[object_id].shadow_ratio_db",
            "per_object_unocc_window_half_width_m": per_object_half_w_m,
            "db_floor_ratio": 1e-12,
        },
    }
    return results, arrays
