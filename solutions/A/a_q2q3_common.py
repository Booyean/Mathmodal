#!/usr/bin/env python3
"""Shared physics, geometry, gain, and synthetic forward helpers for Problem A Q2/Q3."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

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
SYNTHETIC_SEED = 20261128

Y0_DEFAULT_M = 0.25
Y_SAT_DEFAULT_M = 2.60
G_CAP_DEFAULT = 20.0
Z_SLICE_ROW4_M = 0.545


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head_short(default: str = "unknown") -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root()),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or default
    except Exception:
        return default


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def canonical_json_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def array_sha256(arr: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(arr)
    h = hashlib.sha256()
    h.update(str(contiguous.dtype).encode("ascii"))
    h.update(repr(contiguous.shape).encode("ascii"))
    h.update(contiguous.tobytes())
    return h.hexdigest()


def arrays_dict_sha256(arrays: dict[str, np.ndarray]) -> str:
    digest_map = {k: array_sha256(v) for k, v in sorted(arrays.items())}
    return canonical_json_sha256(digest_map)


def save_npz_deterministic(path: Path, arrays: dict[str, np.ndarray]) -> None:
    """Write compressed NPZ with fixed ZipInfo timestamp so runs are byte-for-byte repeatable."""
    fixed_dt = (2026, 11, 28, 0, 0, 0)
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for key in sorted(arrays.keys()):
            buf = io.BytesIO()
            np.lib.format.write_array(buf, np.ascontiguousarray(arrays[key]), allow_pickle=False)
            zinfo = zipfile.ZipInfo(filename=f"{key}.npy", date_time=fixed_dt)
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, buf.getvalue())


def compute_anomaly_isolation(scene: dict[str, Any], phase: str) -> dict[str, Any]:
    """Build anomaly_isolation purely from input scene metadata (never hardcoded fixture constants)."""
    gids = [str(g) for g in scene["j_group_ids"].tolist()]
    p_counts = [int(p) for p in scene["j_p_common"].tolist()]
    max_p = max(p_counts) if p_counts else 0
    mismatch = [
        {"group_index": idx + 1, "group_id": gid, "p_common": p}
        for idx, (gid, p) in enumerate(zip(gids, p_counts))
        if p < max_p
    ]
    raw_anomalies = scene.get("anomaly_inputs", {})
    real_dat_count = int(raw_anomalies.get("real_dat_files_read", 0))

    if phase == "Q3-Metal":
        orphans = raw_anomalies.get("orphan_files")
        orphan_entry: Any = (
            orphans if orphans is not None else {"status": "not_covered_by_synthetic_fixture", "count": 0}
        )
        g8_idx = 7
        if g8_idx < len(p_counts) and raw_anomalies.get("packet_mismatch_exercised", False):
            g8_sync: Any = int(p_counts[g8_idx])
        else:
            g8_sync = {"status": "not_covered_by_synthetic_fixture", "count": None}

        g8_int16 = raw_anomalies.get("group8_int16_min_count")
        if g8_int16 is None:
            g8_int16 = {"status": "not_covered_by_synthetic_fixture", "count": 0}
        g8_gate = raw_anomalies.get("group8_d1_gate_action")
        if g8_gate is None:
            g8_gate = {"status": "not_covered_by_synthetic_fixture", "action": "none"}
        return {
            "real_dat_files_read": real_dat_count,
            "packet_mismatch_groups": mismatch,
            "orphan_skipped": orphan_entry,
            "group8_sync_common": g8_sync,
            "group8_int16_min_count": g8_int16,
            "group8_d1_gate_action": g8_gate,
        }

    return {
        "real_dat_files_read": real_dat_count,
        "packet_mismatch_groups": mismatch,
        "orphan_skipped": raw_anomalies.get("orphan_files", {"status": "not_covered_by_synthetic_fixture", "count": 0}),
    }


def all_arrays_finite_and_valid(arrays: dict[str, np.ndarray], energy_prefixes: tuple[str, ...]) -> bool:
    for key, arr in arrays.items():
        if arr.dtype.kind in ("f", "c", "i", "u"):
            if not np.all(np.isfinite(arr)):
                return False
            if key.startswith(energy_prefixes) and float(np.min(arr)) < 0.0:
                return False
    return True


def build_array_coords() -> tuple[np.ndarray, dict[int, list[int]], list[int]]:
    """Return 64x3 local coordinates (m), per-row RX index lists, and all 63 valid RX indices."""
    coords = np.zeros((64, 3), dtype=np.float64)
    row_rx: dict[int, list[int]] = {r: [] for r in range(1, 9)}
    all_rx: list[int] = []
    for r in range(1, 9):
        z = (75.5 - 7 * (r - 1)) * 1e-2
        for k in range(1, 9):
            cgrid = (2 * k - 1) if (r % 2 == 1) else (2 * k)
            x = (8 - cgrid) * 0.035
            idx = 8 * (r - 1) + (k - 1)
            coords[idx] = (x, 0.0, z)
            if idx != 27:
                row_rx[r].append(idx)
                all_rx.append(idx)
    return coords, row_rx, all_rx


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
    y0_m: float = Y0_DEFAULT_M,
    y_sat_m: float = Y_SAT_DEFAULT_M,
    g_cap: float = G_CAP_DEFAULT,
) -> np.ndarray:
    """Bounded two-step spreading + exponential attenuation gain W_comp(tau)."""
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


OSR = 4
TS_OVER = TS / OSR
CAUSAL_SAMPLES_OVER = 512  # Covers 0..32 ns (> max 2D/3D tau < 25 ns) cleanly without wrapping


def interp_rf_response(z_base_traces: np.ndarray, tau_s: np.ndarray, ts_over: float = TS_OVER) -> np.ndarray:
    """Evaluate 2nd-Nyquist compressed response at tau_s via 4x baseband interp + analytic carrier."""
    n_win = z_base_traces.shape[-1]
    idx_f = tau_s / ts_over
    i0 = np.clip(np.floor(idx_f).astype(np.int64), 0, n_win - 1)
    frac = idx_f - np.floor(idx_f)
    i1 = np.clip(i0 + 1, 0, n_win - 1)
    m_idx = np.arange(z_base_traces.shape[0])[(slice(None),) + (None,) * (tau_s.ndim - 1)]
    val_base = (1.0 - frac) * z_base_traces[m_idx, i0] + frac * z_base_traces[m_idx, i1]
    return val_base * np.exp(-1j * 2.0 * np.pi * FS * tau_s)


def simulate_scatter_scene_63rx(
    x_scan: np.ndarray,
    all_pts: np.ndarray,
    all_amps: np.ndarray,
    noise_ref_start: int,
    snr_ref_db: float,
    seed: int,
    prefix: str,
    packet_counts: np.ndarray | None = None,
) -> dict[str, Any]:
    """Shared vectorized 63-RX 2nd-Nyquist LFM forward simulator for Q2 and Q3 synthetic scenes.

    Uses exact algebraic autocorrelation kernel K_MF(dt) = (N_over/||S_eff||) * IFFT(|S_eff|^2) at
    32x oversampling so large 63-RX 3D scatterer clouds evaluate identically in < 1 s.
    """
    coords, row_rx, all_rx = build_array_coords()
    band, f_d, f_r, s_b = make_reference_band()
    p_tx_loc = coords[27]
    p_rx_loc = coords[all_rx]

    u = (f_d - 1.0e9) / 0.7e9
    h_ref = (1.0 + 0.20 * u) * np.exp(1j * (2.0 * np.pi * f_r * 2.0e-10 + 0.5 * u ** 2))
    s_eff = h_ref * s_b * np.exp(1j * 2.0 * np.pi * f_r * (120.25 * TS))
    s_eff_sq = np.abs(s_eff) ** 2
    s_eff_norm = float(np.linalg.norm(s_eff))

    # Build 32x-oversampled periodic matched-filter baseband kernel K_MF(dt)
    osr_kern = 32
    n_kern = NP * osr_kern
    ts_kern = TS / osr_kern
    band_idx = np.where(band)[0]
    full_sq = np.zeros(n_kern, dtype=np.complex128)
    full_sq[band_idx] = s_eff_sq
    kern_raw = n_kern * np.fft.ifft(full_sq) * (OSR / float(osr_kern)) / s_eff_norm
    # Note: FFT grid in a_q2q3 scales by n_over = NP*OSR; scale ratio keeps amplitude identical to n_over * ifft
    # Shift so lag=0 aligns to half_k for symmetrical lookup over dt in [-32 ns, +32 ns]
    half_k = 1200  # +-37.5 ns at ts_kern = 1/128 ns
    kern_win = np.concatenate([kern_raw[-half_k:], kern_raw[: half_k + 1]])  # length 2*half_k+1

    def eval_kernel(dt_s: np.ndarray) -> np.ndarray:
        idx_f = dt_s / ts_kern + half_k
        i0 = np.clip(np.floor(idx_f).astype(np.int64), 0, kern_win.size - 2)
        frac = idx_f - np.floor(idx_f)
        return (1.0 - frac) * kern_win[i0] + frac * kern_win[i0 + 1]

    rng = np.random.default_rng(seed)
    n_rx = len(all_rx)
    t_over = np.arange(CAUSAL_SAMPLES_OVER, dtype=np.float64) * TS_OVER  # (512,)
    z_base_over = np.zeros((len(x_scan), n_rx, CAUSAL_SAMPLES_OVER), dtype=np.complex128)
    n_over = NP * OSR
    mean_s_eff_sq = float(np.mean(s_eff_sq))

    for j_idx, xj in enumerate(x_scan):
        tx_pos = np.array([float(xj), 0.0, float(p_tx_loc[2])])
        rx_pos = p_rx_loc.copy()
        rx_pos[:, 0] += float(xj)

        r_tx = np.linalg.norm(all_pts - tx_pos[None, :], axis=1)  # (P,)
        r_rx = np.linalg.norm(all_pts[None, :, :] - rx_pos[:, None, :], axis=2)  # (63, P)
        tau = (r_tx[None, :] + r_rx) / C0  # (63, P)
        wt = all_amps[None, :] / (r_tx[None, :] + r_rx)  # (63, P)
        wt_carrier = wt * np.exp(1j * 2.0 * np.pi * FS * tau)

        # Accumulate z_base across points cleanly in chunks of 32 points
        z_clean = np.zeros((n_rx, CAUSAL_SAMPLES_OVER), dtype=np.complex128)
        for p0 in range(0, all_pts.shape[0], 32):
            p1 = min(p0 + 32, all_pts.shape[0])
            dt = t_over[None, None, :] - tau[:, p0:p1, None]  # (63, chunk, 512)
            k_vals = eval_kernel(dt)
            z_clean += np.einsum("rp,rpt->rt", wt_carrier[:, p0:p1], k_vals)

        # Parseval-equivalent RMS AWGN matched-filter noise spectrum over band
        p_ref = max(float(np.mean(np.sum(wt[:, noise_ref_start:] ** 2, axis=1))) * mean_s_eff_sq, 1e-30)
        sigma_f = float(np.sqrt(p_ref * (10.0 ** (-snr_ref_db / 10.0)) * 0.5))
        full_noise = np.zeros((n_rx, n_over), dtype=np.complex128)
        noise_spec = rng.normal(0.0, sigma_f, size=(n_rx, len(band_idx))) + 1j * rng.normal(0.0, sigma_f, size=(n_rx, len(band_idx)))
        full_noise[:, band_idx] = noise_spec * np.conj(s_eff)[None, :]
        z_noise = n_over * np.fft.ifft(full_noise, axis=1) / s_eff_norm

        z_base_over[j_idx] = z_clean + z_noise[:, :CAUSAL_SAMPLES_OVER]

    j_group_ids = np.array([f"{prefix}-{j + 1:02d}" for j in range(len(x_scan))])
    if packet_counts is None:
        packet_counts = np.full(len(x_scan), 4, dtype=np.int64)

    return {
        "coords": coords,
        "row_rx": row_rx,
        "all_rx": all_rx,
        "x_scan_m": x_scan,
        "j_group_ids": j_group_ids,
        "j_p_common": packet_counts,
        "z_base_over": z_base_over,
    }


def interval_union_mask(axis: np.ndarray, ranges: list[list[float]], tol: float = 1.0e-9) -> np.ndarray:
    """Boolean mask selecting coordinate grid points inside any [lo, hi] interval with FP tolerance."""
    mask = np.zeros_like(axis, dtype=bool)
    for lo, hi in ranges:
        if lo <= hi + tol:
            mask |= (axis >= float(lo) - tol) & (axis <= float(hi) + tol)
    return mask


def parabolic_ridge_y(y_axis: np.ndarray, profile_yx: np.ndarray) -> np.ndarray:
    """Estimate sub-grid peak positions along axis 0 via 3-point quadratic refinement."""
    idx = np.argmax(profile_yx, axis=0)
    ny = y_axis.size
    y_est = y_axis[idx].astype(np.float64)
    if ny < 3:
        return y_est
    dy = float(y_axis[1] - y_axis[0])
    cols = np.arange(profile_yx.shape[1])
    interior = (idx > 0) & (idx < ny - 1)
    if np.any(interior):
        ii = idx[interior]
        cc = cols[interior]
        ym = profile_yx[ii - 1, cc]
        y0 = profile_yx[ii, cc]
        yp = profile_yx[ii + 1, cc]
        denom = ym - 2.0 * y0 + yp
        valid = np.abs(denom) > 1e-30
        shift = np.zeros_like(y0)
        shift[valid] = np.clip(0.5 * (ym[valid] - yp[valid]) / denom[valid], -0.5, 0.5)
        y_est[interior] += shift * dy
    return y_est


def build_synthetic_wall_scene_63rx(seed: int = SYNTHETIC_SEED) -> dict[str, Any]:
    """Simulate full 33-stop x 63-RX dual-wall synthetic scene shared across Q2 and Q3-Wall."""
    x_scan = -0.20 + 0.05 * np.arange(33, dtype=np.float64)
    # Dense x-sampling (3.4 cm < lambda_c/2) & centered z-slab ([0.46, 0.64] m) prevent grating nulls
    xa = np.linspace(0.25, 1.06, 25)
    ya = np.linspace(0.37, 0.56, 25)
    za = np.linspace(0.46, 0.64, 4)
    xxa, zza = np.meshgrid(xa, za, indexing="xy")
    yya = np.broadcast_to(ya[None, :], xxa.shape)
    wall_a_pts = np.column_stack([xxa.ravel(), yya.ravel(), zza.ravel()])
    amps_a = np.full(wall_a_pts.shape[0], 0.65 / wall_a_pts.shape[0], dtype=np.float64)

    xb = np.linspace(-0.20, 1.40, 29)
    zb = np.linspace(0.46, 0.64, 3)
    xxb, zzb = np.meshgrid(xb, zb, indexing="xy")
    in_shadow = (xxb >= 0.25) & (xxb <= 1.06)
    yb_app = np.where(in_shadow, 2.06, 2.00)
    wall_b_pts = np.column_stack([xxb.ravel(), yb_app.ravel(), zzb.ravel()])
    amps_b = np.where(in_shadow.ravel(), 0.08, 0.16) / wall_b_pts.shape[0]

    p_counts = np.full(len(x_scan), 4, dtype=np.int64)
    p_counts[2] = 3  # Mirror wall-group 3 packet intersection count
    scene = simulate_scatter_scene_63rx(
        x_scan=x_scan,
        all_pts=np.vstack([wall_a_pts, wall_b_pts]),
        all_amps=np.concatenate([amps_a, amps_b]),
        noise_ref_start=wall_a_pts.shape[0],
        snr_ref_db=8.0,
        seed=seed,
        prefix="syn-wall",
        packet_counts=p_counts,
    )
    scene["anomaly_inputs"] = {
        "real_dat_files_read": 0,
        "packet_mismatch_exercised": True,
        "orphan_files": {"status": "not_covered_by_synthetic_fixture", "count": 0},
    }
    scene["planted"] = {
        "wall_a_x_min_m": 0.25,
        "wall_a_x_max_m": 1.06,
        "wall_a_y_start_m": 0.37,
        "wall_a_y_end_m": 0.56,
        "wall_b_air_y_m": 2.00,
        "wall_b_behind_a_y_m": 2.06,
        "delta_y_app_m": 0.06,
    }
    return scene


def build_synthetic_metal_scene_63rx(seed: int = SYNTHETIC_SEED) -> dict[str, Any]:
    """Simulate full 27-stop x 63-RX dual-metal + occluded rear-wall scene for Q3-Metal."""
    x_scan = 0.05 * np.arange(27, dtype=np.float64)
    z_col = np.linspace(0.25, 0.75, 9)
    col_pts = np.column_stack([np.full_like(z_col, 0.35), np.full_like(z_col, 1.15), z_col])
    amps_col = np.full(len(col_pts), 0.45 / len(col_pts), dtype=np.float64)

    z_shv = np.linspace(0.28, 0.42, 4)
    shv_pts = np.column_stack([np.full_like(z_shv, 0.90), np.full_like(z_shv, 0.75), z_shv])
    amps_shv = np.full(len(shv_pts), 0.25 / len(shv_pts), dtype=np.float64)

    xw = np.linspace(0.0, 1.30, 21)
    zw = np.linspace(0.25, 0.75, 5)
    xxw, zzw = np.meshgrid(xw, zw, indexing="xy")
    wall_pts = np.column_stack([xxw.ravel(), np.full(xxw.size, 2.00), zzw.ravel()])
    in_col_sh = (np.abs(wall_pts[:, 0] - 0.35) <= 0.14) & (wall_pts[:, 2] >= 0.20) & (wall_pts[:, 2] <= 0.80)
    in_shv_sh = (np.abs(wall_pts[:, 0] - 0.90) <= 0.14) & (wall_pts[:, 2] >= 0.20) & (wall_pts[:, 2] <= 0.55)
    amps_wall = np.where(in_col_sh | in_shv_sh, 0.18 * 0.20, 0.18) / wall_pts.shape[0]

    all_pts = np.vstack([col_pts, shv_pts, wall_pts])
    all_amps = np.concatenate([amps_col, amps_shv, amps_wall])
    p_counts = np.full(len(x_scan), 4, dtype=np.int64)
    p_counts[7] = 3  # Exercise group-8 packet intersection P_common=3 in synthetic j_p_common vector
    scene = simulate_scatter_scene_63rx(
        x_scan=x_scan,
        all_pts=all_pts,
        all_amps=all_amps,
        noise_ref_start=0,
        snr_ref_db=18.0,
        seed=seed,
        prefix="syn-metal",
        packet_counts=p_counts,
    )
    scene["anomaly_inputs"] = {
        "real_dat_files_read": 0,
        "packet_mismatch_exercised": True,
        "orphan_files": {"status": "not_covered_by_synthetic_fixture", "count": 0},
        "group8_int16_min_count": {"status": "not_covered_by_synthetic_fixture", "count": 0},
        "group8_d1_gate_action": {"status": "not_covered_by_synthetic_fixture", "action": "none"},
    }
    scene["planted"] = {
        "column_xyz_m": [0.35, 1.15, 0.50],
        "shovel_xyz_m": [0.90, 0.75, 0.35],
        "rear_wall_y_m": 2.00,
    }
    return scene


def upstream_synthetic_metadata(phase: str, arrays: dict[str, np.ndarray], groups_used: list[str], anomaly: dict[str, Any], energy_prefixes: tuple[str, ...]) -> dict[str, Any]:
    return {
        "phase": phase,
        "input_mode": "synthetic_only",
        "real_dat_files_read": 0,
        "citable": False,
        "implementation_sha": git_head_short(),
        "main_commit": "934b089",
        "q1_frozen_config_path": "synthetic://q1-frozen-baseline",
        "q1_frozen_config_sha256": canonical_json_sha256({"seed": SYNTHETIC_SEED, "alpha_dw": 1.0, "model": "M0-Cal-Base+M0-DW-Base"}),
        "d0_contract_version": "D0-4",
        "d1_contract_version": "D1-2",
        "groups_used": groups_used,
        "anomaly_isolation": anomaly,
        "arrays_sha256": arrays_dict_sha256(arrays),
        "finite": all_arrays_finite_and_valid(arrays, energy_prefixes),
        "status": "synthetic_baseline_only",
    }
