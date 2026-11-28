"""P15: the acceptance checks must actually reject tampered inputs.

Runs a compact version of the P10 gate checks on the delivered arrays, then on
five tampered variants; each tampering must be detected.
"""

import copy
import hashlib
import json
import os
import sys

import numpy as np

C0 = 299792458.0
NP = 4000
TP = 1e-6
GUARD = 0.1606031
ETA = 0.25

RES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    "experiments", "A", "A-Q1-E0", "s1s2", "results"
)
NEED = [
    "freq_rf_hz",
    "band_k",
    "s2_r_dir_m",
    "s2_042_freq_rf_hz",
    "s2_042_x_cal",
    "s2_042_x_after",
    "s2_042_s_eff",
    "s2_042_tau_dir_s",
    "s2_042_profile_d_grid_m",
    "s2_042_profile_p_norm_eff",
    "s2_042_p_at_d_hat",
    "s2_042_bg_proxy",
    "s2_042_z_dw_before",
    "s2_042_z_dw_after",
    "s2_042_z_after_tgt",
    "s2_042_d_hat_m",
    "s2_069_x_cal",
    "s2_069_x_after",
    "s2_069_s_eff",
    "s2_069_freq_rf_hz",
    "s2_069_tau_dir_s",
    "s2_069_profile_d_grid_m",
    "s2_069_profile_p_norm_eff",
    "s2_069_p_at_d_hat",
    "s2_069_bg_proxy",
    "s2_069_z_dw_before",
    "s2_069_z_dw_after",
    "s2_069_z_after_tgt",
    "s2_069_d_hat_m",
]


def load():
    z = np.load(os.path.join(RES, "e0_s1s2_arrays.npz"))
    A = {k: z[k].copy() for k in NEED}
    R = json.load(open(os.path.join(RES, "e0_s1s2_results.json"), encoding="utf-8"))
    return A, R


def z_at(x, tpl, f_r, delays):
    norm = float(np.linalg.norm(tpl))
    xc = x * np.conj(tpl)[None, :]
    out = np.empty(delays.shape, dtype=np.complex128)
    for i in range(x.shape[0]):
        out[i] = xc[i] @ np.exp(-1j * 2.0 * np.pi * np.outer(f_r, delays[i]))
    return out / norm


def p_eff_at(x_after, s_eff, r_dir, f_r, d):
    r_t = np.sqrt(r_dir ** 2 + 4.0 * d ** 2)
    z = z_at(x_after, s_eff, f_r, (r_t / C0)[:, None])[:, 0]
    return float(abs(np.sum(z / r_t)) ** 2 / np.sum(1.0 / r_t ** 2))


def canon_table_sha(rows):
    rows = [[int(r[0])] + [float(v) for v in r[1:]] for r in rows]
    table = {
        "experiment": "A-Q1-E0-S2",
        "seed": 20261128,
        "rng": "numpy.random.default_rng(20261128)",
        "draw_order": (
            "for rx in sorted(0..63 excluding 27,28): "
            "Uniform(-0.75e-9,0.75e-9), Uniform(0.5,1.5), "
            "Uniform(-0.5,0.5), Uniform(-0.3,0.3)"
        ),
        "columns": ["rx_idx", "delta_tau_s", "gain_mag", "psi0_rad", "psi2_u2_rad"],
        "rows": rows,
    }
    s = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def run_checks(A, R):
    """Return (computed dict, list of failed check names)."""
    fails = []
    out = {}
    cases = {c["case_id"]: c for c in R["cases"]}
    for tag, cid in (("s2_042", "E0-S2@0.42"), ("s2_069", "E0-S2@0.69")):
        c = cases[cid]
        f_r = A[tag + "_freq_rf_hz"]
        x_after = A[tag + "_x_after"]
        x_cal = A[tag + "_x_cal"]
        s_eff = A[tag + "_s_eff"]
        r_dir = A["s2_r_dir_m"]
        d_grid = A[tag + "_profile_d_grid_m"]
        d_hat_decl = float(c["d_hat_m"])

        # finiteness / valid channels
        valid_rx = int(np.sum(np.all(np.isfinite(x_cal), axis=1)))
        out[cid + ".valid_rx"] = valid_rx
        if not (valid_rx == int(c["valid_rx"]) == 63):
            fails.append(cid + ".valid_rx")
        if not np.all(np.isfinite(x_after)):
            fails.append(cid + ".finite_x_after")

        # suppression
        supp = 10.0 * np.log10(
            np.sum(np.abs(A[tag + "_z_dw_before"]) ** 2)
            / np.sum(np.abs(A[tag + "_z_dw_after"]) ** 2)
        )
        out[cid + ".supp"] = float(supp)
        if abs(supp - c["supp_dw_win_db"]) > 1e-9:
            fails.append(cid + ".supp")

        # background and PNR
        bg = float(np.mean(np.abs(np.fft.ifft(
            np.pad(
                (x_after * np.conj(s_eff)[None, :]),
                ((0, 0), (0, NP - x_after.shape[1])),
            ),
            axis=1,
        ) * NP / np.linalg.norm(s_eff))[:, 200:3801] ** 2))
        out[cid + ".bg"] = bg
        if abs(bg - c["bg_proxy"]) > 1e-9 * abs(c["bg_proxy"]):
            fails.append(cid + ".bg")
        pnr = 10.0 * np.log10(
            float(np.mean(np.abs(A[tag + "_z_after_tgt"]) ** 2)) / bg
        )
        out[cid + ".pnr"] = pnr
        if abs(pnr - c["pnr_db"]) > 1e-9:
            fails.append(cid + ".pnr")

        # d_hat from profile (coarse argmax is enough for tamper detection)
        p = np.abs(A[tag + "_profile_p_norm_eff"])
        d_coarse = float(d_grid[int(np.argmax(p))])
        d_hat = d_coarse
        out[cid + ".d_hat"] = d_hat
        if abs(d_hat - d_hat_decl) > 1e-9:
            fails.append(cid + ".d_hat")
        out[cid + ".abs_err_cm"] = abs(d_hat - c["d_true_m"]) * 100.0
        if abs(out[cid + ".abs_err_cm"] - c["abs_err_cm"]) > 1e-6:
            fails.append(cid + ".abs_err")

        # PSLR
        mask = np.abs(d_grid - d_hat) > GUARD
        pslr = 10.0 * np.log10(float(p[int(np.argmax(p))]) / float(np.max(p[mask])))
        out[cid + ".pslr"] = float(pslr)
        if abs(pslr - c["pslr_db"]) > 1e-9:
            fails.append(cid + ".pslr")

    out["param_table_sha"] = canon_table_sha(R["s2_param_rows"])
    if out["param_table_sha"] != "aa86bf56fb138789cd0ad4375691293e7d0e5d65a2daf678d151d44720576e96":
        fails.append("param_table_sha")
    return out, fails


A0, R0 = load()
base, base_fails = run_checks(A0, R0)
print("baseline fails:", base_fails)
print("baseline:", json.dumps({k: (round(v, 12) if isinstance(v, float) else v) for k, v in base.items()}, ensure_ascii=False))

variants = {}

# 1 d_hat shifted by 2 cm
A, R = copy.deepcopy(A0), copy.deepcopy(R0)
R["cases"][1]["d_hat_m"] = R["cases"][1]["d_hat_m"] + 0.02
variants["d_hat+2cm"] = (A, R)

# 2 Supp forced to 19.9 dB
A, R = copy.deepcopy(A0), copy.deepcopy(R0)
R["cases"][1]["supp_dw_win_db"] = 19.9
variants["supp=19.9"] = (A, R)

# 3 NaN injected into one channel row of x_after
A, R = copy.deepcopy(A0), copy.deepcopy(R0)
A["s2_042_x_after"][5, :] = np.nan
variants["nan_in_x_after"] = (A, R)

# 4 valid_rx claims 62
A, R = copy.deepcopy(A0), copy.deepcopy(R0)
R["cases"][2]["valid_rx"] = 62
variants["valid_rx=62"] = (A, R)

# 5 param table 1e-15 relative tamper
A, R = copy.deepcopy(A0), copy.deepcopy(R0)
R["s2_param_rows"][7][2] = R["s2_param_rows"][7][2] * (1.0 + 1e-15)
variants["param_1e-15"] = (A, R)

print("\nP15 tamper detection:")
detected = 0
for name, (A, R) in variants.items():
    _, fails = run_checks(A, R)
    ok = len(fails) > 0
    detected += ok
    print(("  DETECTED " if ok else "  MISSED   ") + name, "->", fails)
print("\n%d/%d tamper variants detected" % (detected, len(variants)))
