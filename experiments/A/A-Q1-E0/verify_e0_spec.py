"""Validation and synthetic metric/window countercheck for A-Q1-E0.

Checks:
1. Consistency between `experiments/A/A-Q1-E0/config.json`, `PLAN.md`, and the
   frozen split manifest `coordination/A_Q1_SPLIT.json` (Git LF blob SHA256).
2. Pure-synthetic countercheck (zero real `.dat` files read) verifying:
   - Raw periodic LFM waveform vs circular compressed-delay `z_i(tau)` in `[50, 950] ns`.
   - Circular boundary wraparound for `W_dw_i = [tau_dir_i - 1.0 ns, tau_dir_i + 1.0 ns]`.
   - Target sidelobe/tail leakage into `W_dw_i` under planted `0.42 m` / `0.69 m` target
     and planted common dispersion `H_ref` (justifying `alpha = 1.0` only in E0).
   - Explicit dispersive `S_eff` vs scalar-delay `S` comparison under `H_ref`, plus
     verification of `Supp_dw-win`, `PNR`, `PSLR`, and range gates under 25 dB AWGN.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
E0_DIR = Path(__file__).resolve().parent
CONFIG_PATH = E0_DIR / "config.json"
PLAN_PATH = E0_DIR / "PLAN.md"
SPLIT_PATH = REPO_ROOT / "coordination" / "A_Q1_SPLIT.json"


def file_sha256_lf(path: Path) -> str:
    data_lf = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data_lf).hexdigest()


def verify_config_and_split() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    plan_txt = PLAN_PATH.read_text(encoding="utf-8")

    # 1. Version & split hash anchors
    actual_split_blob = file_sha256_lf(SPLIT_PATH)
    expected_split_blob = cfg["version_anchors"]["split_blob_sha256_lf"]
    assert actual_split_blob == expected_split_blob, (
        f"Split blob mismatch: {actual_split_blob} != {expected_split_blob}"
    )
    assert expected_split_blob in plan_txt, "Split blob SHA missing from PLAN.md"
    assert cfg["version_anchors"]["main_baseline_commit"] in plan_txt

    # 2. Frozen baseline constraints & no adaptive alpha fitting
    cal = cfg["methods_classic_baseline_only"]["calibration"]
    dw = cfg["methods_classic_baseline_only"]["direct_wave_suppression"]
    rng_cfg = cfg["methods_classic_baseline_only"]["ranging"]
    gates = cfg["gates_and_thresholds"]

    assert cfg["methods_classic_baseline_only"]["n0_improvements_enabled"] is False
    assert cal["air_loo_budget_pairs"] == len(cal["lambda_cal_grid_air_loo"]) * len(cal["lambda_inv_grid_air_loo"]) == 9
    assert dw["alpha_mode"] == "fixed_1.0"
    assert dw["alpha_fixed_value"] == 1.0
    assert dw["alpha_fitting_in_this_pilot"] is False
    assert rng_cfg["primary_statistic"] == "P_norm_eff"
    assert gates["required_valid_rx_channels"] == 63
    assert gates["allow_dropped_rx_channels"] is False

    # 3. Compressed delay & off-target background proxy assertions
    wm = cfg["windows_and_metrics"]
    assert wm["response_domain"] == "circular_range_compressed_matched_filter_delay_z_i"
    assert wm["off_target_late_delay_bg_window"]["is_proven_noise_only"] is False
    assert wm["off_target_late_delay_bg_window"]["delay_interval_ns"] == [50.0, 950.0]
    assert wm["direct_wave_window"]["rel_tau_dir_ns"] == [-1.0, 1.0]

    # 4. Physical constants cross-check
    pc = cfg["physical_constants"]
    c0 = pc["c0_m_s"]
    fs = pc["fs_hz"]
    b_hz = pc["f_stop_hz"] - pc["f_start_hz"]
    assert math.isclose(pc["rayleigh_range_resolution_cm"], 100.0 * c0 / (2.0 * b_hz), rel_tol=1e-7)
    assert math.isclose(pc["sample_two_way_step_cm"], 100.0 * c0 / (2.0 * fs), rel_tol=1e-9)

    # 5. Dataset membership strictly matches frozen 10/10 split without leakage
    wall_cal = set(split["groups"]["wall_cal"])
    wall_test = set(split["groups"]["wall_test"])
    metal_cal = set(split["groups"]["metal_cal"])
    metal_test = set(split["groups"]["metal_test"])
    air_all = set(split["air_template_groups"])

    assert len(wall_cal) == len(wall_test) == len(metal_cal) == len(metal_test) == len(air_all) == 10
    assert wall_cal.isdisjoint(wall_test) and metal_cal.isdisjoint(metal_test)

    pilot_air = {g.split("/", 1)[1] for g in cfg["pilot_datasets"]["phase_c_calibration_pilot"]["air_groups"]}
    assert pilot_air == air_all

    for entry in cfg["pilot_datasets"]["phase_c_calibration_pilot"]["target_groups"]:
        short_name = entry["group"].split("/", 1)[1]
        if entry["target_type"] == "wall":
            assert entry["in_split"] == "wall_cal" and short_name in wall_cal
        else:
            assert entry["in_split"] == "metal_cal" and short_name in metal_cal

    for entry in cfg["pilot_datasets"]["phase_t_holdout_single_shot_eval"]["target_groups"]:
        short_name = entry["group"].split("/", 1)[1]
        if entry["target_type"] == "wall":
            assert entry["in_split"] == "wall_test" and short_name in wall_test
        else:
            assert entry["in_split"] == "metal_test" and short_name in metal_test

    assert cfg["pilot_datasets"]["phase_t_holdout_single_shot_eval"]["untouched_remaining_holdout_groups_count"] == 16
    return cfg


def build_array_geometry(c0: float) -> tuple[np.ndarray, np.ndarray]:
    coords: list[tuple[float, float]] = []
    for r in range(1, 9):
        z = (75.5 - 7 * (r - 1)) * 1e-2
        for c in range(1, 9):
            cgrid = (2 * c - 1) if (r % 2 == 1) else (2 * c)
            x = (8 - cgrid) * 0.035
            coords.append((x, z))
    x_tx, z_tx = coords[27]
    rx_idx = [i for i in range(64) if i != 27]
    r_dir = np.array([math.hypot(coords[i][0] - x_tx, coords[i][1] - z_tx) for i in rx_idx], dtype=np.float64)
    return r_dir, r_dir / c0


def eval_z_grid(x_band: np.ndarray, tpl_band: np.ndarray, band_idx: np.ndarray, np_n: int) -> np.ndarray:
    """Evaluate circular compressed-delay response z_i(m * Ts) over [0, Tp)."""
    full = np.zeros((x_band.shape[0], np_n), dtype=np.complex128)
    full[:, band_idx] = x_band * np.conj(tpl_band)[None, :]
    return np_n * np.fft.ifft(full, axis=1) / np.linalg.norm(tpl_band)


def eval_z_tau(x_band: np.ndarray, tpl_band: np.ndarray, f_r: np.ndarray, tau_arr: np.ndarray) -> np.ndarray:
    """Evaluate z_i(tau) directly at arbitrary circular delays tau_arr of shape (63, M)."""
    norm_tpl = float(np.linalg.norm(tpl_band))
    xc = x_band * np.conj(tpl_band)[None, :]
    out = np.empty(tau_arr.shape, dtype=np.complex128)
    for c in range(x_band.shape[0]):
        kern = np.exp(-1j * 2.0 * np.pi * f_r[:, None] * tau_arr[c, None, :])
        out[c] = (xc[c] @ kern) / norm_tpl
    return out


def run_synthetic_countercheck(cfg: dict) -> None:
    pc = cfg["physical_constants"]
    c0 = pc["c0_m_s"]
    fs = pc["fs_hz"]
    ts = 1.0 / fs
    np_n = pc["np_samples"]
    tp = np_n * ts
    f_start = pc["f_start_hz"]
    f_stop = pc["f_stop_hz"]
    k_slope = (f_stop - f_start) / tp
    amp = pc["tx_amplitude"]

    r_dir, tau_dir = build_array_geometry(c0)
    n = np.arange(np_n, dtype=np.float64)
    t = n * ts
    win = 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (np_n - 1))
    s_t = amp * win * np.cos(2.0 * np.pi * (f_start * t + 0.5 * k_slope * t ** 2))
    s_f = np.fft.rfft(s_t)
    freqs = np.fft.rfftfreq(np_n, d=ts)
    band = (freqs >= f_start) & (freqs <= f_stop)
    band_idx = np.where(band)[0]
    f_d = freqs[band]
    f_r = fs - f_d
    s_b = s_f[band]

    # Planted common reference dispersion H_ref from E0-S2 + trigger offset t0
    u = (f_d - 1.0e9) / 0.7e9
    h_ref = (1.0 + 0.20 * u) * np.exp(1j * (2.0 * np.pi * f_r * 2.0e-10 + 0.5 * u ** 2))
    t0 = 120.25 * ts
    s_eff_true = h_ref * s_b * np.exp(1j * 2.0 * np.pi * f_r * t0)
    # Scalar template ignores dispersion and only compensates t0_eff = t0 + tau_ref_hw
    s_scalar = s_b * np.exp(1j * 2.0 * np.pi * f_r * (t0 + 2.0e-10))

    bg_mask = (np.arange(np_n) * ts >= 50.0e-9) & (np.arange(np_n) * ts <= 950.0e-9)
    dt_offsets = np.linspace(-1.0e-9, 1.0e-9, 41)
    tau_dw = (tau_dir[:, None] + dt_offsets[None, :]) % tp

    # Check 1: Close-channel wraparound across 0 / 1000 ns (ref_idx=28 -> rx position 27)
    ref_pos = 27  # rx_idx[27] == 28
    assert tau_dir[ref_pos] < 1.0e-9, "Expected ref_idx tau_dir < 1.0 ns so W_dw crosses 0 ns"
    wrapped_pts = tau_dir[ref_pos] + dt_offsets
    n_neg_wrapped = int(np.sum(wrapped_pts < 0.0))
    assert n_neg_wrapped > 10, "Expected significant portion of W_dw to wrap across 0/1000 ns"

    rng = np.random.default_rng(cfg["pilot_datasets"]["phase_s_synthetic"][1]["seed"])
    d_grid = np.arange(0.15, 2.0001, 0.001)
    r_grid = np.sqrt(r_dir[:, None] ** 2 + 4.0 * d_grid[None, :] ** 2)
    tau_grid = r_grid / c0
    ml_half = cfg["windows_and_metrics"]["pslr_mainlobe_half_width_m"]

    for d_true, gamma, is_wall in [(0.42, 0.25, True), (0.69, -0.35, False)]:
        r_tgt = np.sqrt(r_dir ** 2 + 4.0 * d_true ** 2)
        tau_tgt = r_tgt / c0
        x_air = (1.0 / r_dir[:, None]) * s_eff_true[None, :] * np.exp(1j * 2.0 * np.pi * f_r[None, :] * tau_dir[:, None])
        x_tgt = (gamma / r_tgt[:, None]) * s_eff_true[None, :] * np.exp(1j * 2.0 * np.pi * f_r[None, :] * tau_tgt[:, None])
        x_tot = x_air + x_tgt

        # Check 2: Raw waveform [50, 950] ns is NOT silent vs compressed z_i
        spec_tot = np.zeros((len(r_dir), np_n // 2 + 1), dtype=np.complex128)
        spec_tot[:, band] = x_tot
        x_tot_t = np.fft.irfft(spec_tot, n=np_n)
        raw_bg_ratio = float(np.mean(x_tot_t[:, bg_mask] ** 2) / np.mean(x_tot_t ** 2))
        assert raw_bg_ratio > 0.9, f"Expected raw periodic LFM in [50,950]ns to carry full energy, got {raw_bg_ratio}"

        z_air_grid = eval_z_grid(x_air, s_eff_true, band_idx, np_n)
        z_bg_ratio_noiseless = float(np.mean(np.abs(z_air_grid[:, bg_mask]) ** 2) / np.max(np.abs(z_air_grid) ** 2))
        assert z_bg_ratio_noiseless < 1e-7

        # Check 3: Compressed W_dw target leakage under planted d_true=0.42/0.69
        z_dw_air = eval_z_tau(x_air, s_eff_true, f_r, tau_dw)
        z_dw_tgt = eval_z_tau(x_tgt, s_eff_true, f_r, tau_dw)
        leak_ratio = float(np.sum(np.abs(z_dw_tgt) ** 2) / np.sum(np.abs(z_dw_air) ** 2))
        # Also confirm ref channel wrapped side (delta_tau < -tau_dir) holds real DW mainlobe energy
        neg_mask = wrapped_pts < 0.0
        assert float(np.sum(np.abs(z_dw_air[ref_pos, neg_mask]) ** 2)) > 0.1 * float(np.sum(np.abs(z_dw_air[ref_pos]) ** 2))

        # Check 4: Dispersive S_eff vs scalar S compressed peak energy on x_tgt
        z_tgt_eff_peak = eval_z_tau(x_tgt, s_eff_true, f_r, tau_tgt[:, None])[:, 0]
        z_tgt_sca_peak = eval_z_tau(x_tgt, s_scalar, f_r, tau_tgt[:, None])[:, 0]
        eff_over_sca = float(np.mean(np.abs(z_tgt_eff_peak) ** 2) / np.mean(np.abs(z_tgt_sca_peak) ** 2))
        assert eff_over_sca > 1.0, "Explicit S_eff must concentrate dispersed target better than scalar S"

        # Check 5: 25 dB time-domain AWGN closed-loop gates with alpha = 1.0 fixed
        spec_tgt = np.zeros((len(r_dir), np_n // 2 + 1), dtype=np.complex128)
        spec_tgt[:, band] = x_tgt
        x_tgt_t = np.fft.irfft(spec_tgt, n=np_n)
        sigma_n = math.sqrt(float(np.mean(x_tgt_t ** 2)) * (10.0 ** (-25.0 / 10.0)))
        noise_f = np.fft.rfft(rng.normal(0.0, sigma_n, size=(len(r_dir), np_n)), axis=1)[:, band]
        x_meas = x_tot + noise_f
        x_after = x_meas - x_air  # exact alpha = 1.0 subtraction baseline

        z_before_dw = eval_z_tau(x_meas, s_eff_true, f_r, tau_dw)
        z_after_dw = eval_z_tau(x_after, s_eff_true, f_r, tau_dw)
        supp_dw_db = 10.0 * math.log10(float(np.sum(np.abs(z_before_dw) ** 2) / np.sum(np.abs(z_after_dw) ** 2)))

        z_after_grid = eval_z_grid(x_after, s_eff_true, band_idx, np_n)
        bg_proxy = float(np.mean(np.abs(z_after_grid[:, bg_mask]) ** 2))
        z_after_tgt = eval_z_tau(x_after, s_eff_true, f_r, tau_tgt[:, None])[:, 0]
        pnr_db = 10.0 * math.log10(float(np.mean(np.abs(z_after_tgt) ** 2)) / bg_proxy)

        z_d = eval_z_tau(x_after, s_eff_true, f_r, tau_grid)
        p_norm_eff = (np.abs(np.sum(z_d / r_grid, axis=0)) ** 2) / np.sum(1.0 / (r_grid ** 2), axis=0)
        p_max = float(np.max(p_norm_eff))
        if is_wall:
            # Earliest local max >= eta_wall * p_max and >= bg_proxy + 6 dB
            bg_thresh = (10.0 ** 0.6) * bg_proxy
            is_loc = np.zeros_like(p_norm_eff, dtype=bool)
            is_loc[1:-1] = (p_norm_eff[1:-1] > p_norm_eff[:-2]) & (p_norm_eff[1:-1] >= p_norm_eff[2:])
            cand = np.where(is_loc & (p_norm_eff >= 0.25 * p_max) & (p_norm_eff >= bg_thresh))[0]
            assert len(cand) > 0
            idx_hat = int(cand[0])
        else:
            idx_hat = int(np.argmax(p_norm_eff))
        d_hat = float(d_grid[idx_hat])
        sl_mask = np.abs(d_grid - d_hat) > ml_half
        pslr_db = 10.0 * math.log10(float(p_norm_eff[idx_hat] / np.max(p_norm_eff[sl_mask])))
        err_cm = abs(d_hat - d_true) * 100.0

        assert err_cm <= 1.0, f"Range error exceeded 1.0 cm gate: {err_cm:.4f}"
        assert supp_dw_db >= 20.0, f"Supp_dw-win below 20 dB gate: {supp_dw_db:.2f}"
        assert pslr_db >= 3.0 and pnr_db >= 6.0

        print(
            f"[COUNTERCHECK d={d_true:.2f}m] raw_bg={raw_bg_ratio:.3f}, "
            f"z_bg_air={z_bg_ratio_noiseless:.2e}, dw_tgt_leak={leak_ratio:.2e}, "
            f"S_eff/S_sca={eff_over_sca:.3f}, supp_dw={supp_dw_db:.2f}dB, "
            f"pnr={pnr_db:.2f}dB, pslr={pslr_db:.2f}dB, err={err_cm:.3f}cm"
        )


def main() -> None:
    cfg = verify_config_and_split()
    run_synthetic_countercheck(cfg)
    print("ALL_E0_CONFIG_SPLIT_AND_SYNTHETIC_COUNTERCHECKS_PASSED")


if __name__ == "__main__":
    main()
