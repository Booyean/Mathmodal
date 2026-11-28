"""P10: independent metric recomputation from the delivered arrays.

Implements the contract's definitions directly (no import of the production
module): z(tau) from delivered spectra/templates, Supp over W_dw, BG over
W_bg, PNR, PSLR, d_hat by the declared peak rules, abs_err.
"""

import json
import os
import sys

import numpy as np

C0 = 299792458.0
NP = 4000
TP = 1e-6
TS = 0.25e-9
PSLR_GUARD = 1.5 * C0 / (2 * 1.4e9)  # 0.1606031 m
ETA_WALL = 0.25

RES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    "experiments", "A", "A-Q1-E0", "s1s2", "results"
)
Z = np.load(os.path.join(RES, "e0_s1s2_arrays.npz"))
R = json.load(open(os.path.join(RES, "e0_s1s2_results.json"), encoding="utf-8"))
cases = {c["case_id"]: c for c in R["cases"]}

FAILS = []


def cmp(name, mine, theirs, tol, unit=""):
    d = abs(mine - theirs)
    ok = d <= tol
    print(("PASS " if ok else "FAIL ") + f"{name}: mine={mine!r} delivered={theirs!r} |d|={d:.3e}{unit} (tol {tol:g})")
    if not ok:
        FAILS.append(name)
    return ok


def z_at(x, tpl, f_r, delays):
    norm = float(np.linalg.norm(tpl))
    xc = x * np.conj(tpl)[None, :]
    out = np.empty(delays.shape, dtype=np.complex128)
    for i in range(x.shape[0]):
        out[i] = xc[i] @ np.exp(-1j * 2.0 * np.pi * np.outer(f_r, delays[i]))
    return out / norm


def z_grid(x, tpl, f_r_band_idx):
    norm = float(np.linalg.norm(tpl))
    full = np.zeros((x.shape[0], NP), dtype=np.complex128)
    full[:, f_r_band_idx] = x * np.conj(tpl)[None, :]
    return NP * np.fft.ifft(full, axis=1) / norm


def p_eff_from_profile(x_after, s_eff, r_dir, f_r, d_grid):
    r_t = np.sqrt(r_dir[:, None] ** 2 + 4.0 * d_grid[None, :] ** 2)
    z = z_at(x_after, s_eff, f_r, r_t / C0)
    num = np.abs(np.sum(z / r_t, axis=0)) ** 2
    den = np.sum(1.0 / r_t ** 2, axis=0)
    return num / den, z


def p_eff_at(x_after, s_eff, r_dir, f_r, d):
    r_t = np.sqrt(r_dir ** 2 + 4.0 * d ** 2)
    z = z_at(x_after, s_eff, f_r, (r_t / C0)[:, None])[:, 0]
    return float(abs(np.sum(z / r_t)) ** 2 / np.sum(1.0 / r_t ** 2))


def pick_peak(p, d_grid, rule, bg):
    if rule == "metal":
        return int(np.argmax(p)), "global argmax"
    p_max = float(np.max(p))
    local = np.zeros_like(p, dtype=bool)
    local[1:-1] = (p[1:-1] > p[:-2]) & (p[1:-1] >= p[2:])
    cand = np.where(local & (p >= ETA_WALL * p_max) & (p >= 10.0 ** 0.6 * bg))[0]
    if cand.size == 0:
        return int(np.argmax(p)), "fallback argmax"
    return int(cand[0]), "wall first peak (idx %d)" % cand[0]


print("=" * 70)
print("S2 cases")
band_idx = Z["band_k"]
for tag, case_id in (("s2_042", "E0-S2@0.42"), ("s2_069", "E0-S2@0.69")):
    print("-" * 70)
    f_r = Z[tag + "_freq_rf_hz"] if tag + "_freq_rf_hz" in Z else Z["freq_rf_hz"]
    x_after = Z[tag + "_x_after"]
    x_cal = Z[tag + "_x_cal"]
    s_eff = Z[tag + "_s_eff"]
    r_dir = Z["s2_r_dir_m"]
    tau_dir = Z[tag + "_tau_dir_s"]
    d_grid = Z[tag + "_profile_d_grid_m"]
    c = cases[case_id]
    d_true = c["d_true_m"]

    # 1) template normalisation / z convention: reproduce stored z_dw_after
    dw = np.linspace(-1.0, 1.0, 41) * 1e-9
    delays = (tau_dir[:, None] + dw[None, :]) % TP
    z_b = z_at(x_cal, s_eff, f_r, delays)
    z_a = z_at(x_after, s_eff, f_r, delays)
    print("max|z_dw_before - stored| =", float(np.max(np.abs(z_b - Z[tag + "_z_dw_before"]))))
    print("max|z_dw_after  - stored| =", float(np.max(np.abs(z_a - Z[tag + "_z_dw_after"]))))
    supp = 10.0 * np.log10(np.sum(np.abs(z_b) ** 2) / np.sum(np.abs(z_a) ** 2))
    cmp("supp(%s)" % case_id, float(supp), c["supp_dw_win_db"], 1e-9, " dB")

    # 2) BG over tau_m = m*Ts, m=200..3800 (ifft reconstruction)
    zg = z_grid(x_after, s_eff, band_idx)
    bg = float(np.mean(np.abs(zg[:, 200:3801]) ** 2))
    cmp("bg_proxy(%s)" % case_id, bg, c["bg_proxy"], 1e-9 * abs(c["bg_proxy"]), "")
    cmp("bg_proxy stored(%s)" % case_id, bg, float(Z[tag + "_bg_proxy"][0]), 1e-9 * abs(bg), "")

    # 3) profile recomputation over the delivered coarse grid
    p, _ = p_eff_from_profile(x_after, s_eff, r_dir, f_r, d_grid)
    p_stored = Z[tag + "_profile_p_norm_eff"]
    rel = float(np.max(np.abs(p - p_stored)) / np.max(np.abs(p_stored)))
    print("profile P_norm_eff max rel diff vs stored =", rel)
    if rel > 1e-12:
        FAILS.append("profile(%s)" % case_id)

    # 4) d_hat by declared rule + 0.1 mm refinement
    rule = "wall" if tag == "s2_042" else "metal"
    idx, why = pick_peak(p, d_grid, rule, bg)
    d_coarse = float(d_grid[idx])
    d_fine = np.clip(d_coarse + np.arange(-10, 11) * 1e-4, d_grid[0], d_grid[-1])
    p_fine = np.array([p_eff_at(x_after, s_eff, r_dir, f_r, d) for d in d_fine])
    k = int(np.argmax(p_fine))
    d_hat = float(d_fine[k])
    print(f"peak rule '{rule}': {why}; d_coarse={d_coarse:.6f} d_hat={d_hat:.12f}")
    cmp("d_hat(%s)" % case_id, d_hat, c["d_hat_m"], 1e-12, " m")
    cmp("p_at_d_hat(%s)" % case_id, float(p_fine[k]), float(Z[tag + "_p_at_d_hat"][0]), 1e-9 * abs(float(p_fine[k])), "")
    err_cm = abs(d_hat - d_true) * 100.0
    cmp("abs_err_cm(%s)" % case_id, err_cm, c["abs_err_cm"], 1e-9, " cm")

    # 5) PNR at the target delays
    r_t = np.sqrt(r_dir ** 2 + 4.0 * d_hat ** 2)
    z_tgt = z_at(x_after, s_eff, f_r, (r_t / C0)[:, None])[:, 0]
    print("max|z_after_tgt - stored| =", float(np.max(np.abs(z_tgt - Z[tag + "_z_after_tgt"]))))
    pnr = 10.0 * np.log10(np.mean(np.abs(z_tgt) ** 2) / bg)
    cmp("pnr(%s)" % case_id, float(pnr), c["pnr_db"], 1e-9, " dB")

    # 6) PSLR on the coarse profile with the declared guard
    mask = np.abs(d_grid - d_hat) > PSLR_GUARD
    pslr = 10.0 * np.log10(float(p_fine[k]) / float(np.max(p[mask])))
    cmp("pslr(%s)" % case_id, float(pslr), c["pslr_db"], 1e-9, " dB")

    # 7) gates
    print("gates applied:", c.get("gates_applied"))
    gr = c.get("gate_results") or {}
    for gname, g in (gr.items() if isinstance(gr, dict) else [(x.get("name"), x) for x in gr]):
        print("   gate", gname, "value", g.get("value"), "thr", g.get("threshold"), "passed", g.get("passed"))

print("=" * 70)
print("S1 case")
tag = "s1"
f_r = Z["freq_rf_hz"]
r_dir = Z["s1_r_dir_m"]
x_after = Z["s1_x_after"]
s_eff = Z["s1_s_eff_hat"]
d_grid = Z["s1_profile_d_grid_m"]
c = cases["E0-S1"]
p, z = p_eff_from_profile(x_after, s_eff, r_dir, f_r, d_grid)
p_stored = Z["s1_profile_p_norm_eff"]
print("profile max rel diff vs stored =", float(np.max(np.abs(p - p_stored)) / np.max(np.abs(p_stored))))
idx = int(np.argmax(p))
d0 = float(d_grid[idx])
d_fine = np.clip(d0 + np.arange(-10, 11) * 1e-4, d_grid[0], d_grid[-1])
p_fine = np.array([p_eff_at(x_after, s_eff, r_dir, f_r, d) for d in d_fine])
k = int(np.argmax(p_fine))
d_hat = float(d_fine[k])
cmp("d_hat(E0-S1)", d_hat, c["d_hat_m"], 1e-12, " m")
cmp("abs_err_cm(E0-S1)", abs(d_hat - c["d_true_m"]) * 100.0, c["abs_err_cm"], 1e-9, " cm")

# S1 relative calibration from the delivered h_rel_hat phase slope
h = Z["s1_h_rel_hat"]
f_d = Z["freq_hz"]
phase = np.unwrap(np.angle(h[1] / h[0]))
slope = np.polyfit(f_d, phase, 1)[0]
dtau2 = -slope / (2.0 * np.pi)
g2 = float(np.mean(np.abs(h[1] / h[0])))
print("from h_rel_hat: dtau2=%.12e s  g2=%.9f" % (dtau2, g2))
cmp("dtau2_hat(E0-S1)", dtau2 * 1e9, 0.5, 2e-12, " ns")
cmp("g2(E0-S1)", g2, 1.25, 1e-9)
# psi2 is only identifiable modulo 2*pi on the sampled band; compare delivered
print("delivered dtau2_hat_s:", c.get("dtau2_hat_s"), "g2:", c.get("g2_hat"), "psi2:", c.get("psi2_hat_rad"))

print("=" * 70)
print("FAILS:", FAILS)
