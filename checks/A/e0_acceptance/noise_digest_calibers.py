"""P17 addendum: crosswalk of the two noise-digest conventions.

The delivered results JSON and the frozen E0-PREREG-2 oracle describe the same
12 S2 noise matrices with *different* digest conventions:

* raw-byte caliber (oracle):
      SHA256(matrix.astype(float64).tobytes(order="C"))
  no dtype/shape prefix; 12 per-group digests + one concatenation digest in
  group order ``air_0 .. air_9, E0-S2@0.42, E0-S2@0.69``.

* array_sha256 caliber (delivery, ``solutions/A/e0_s1s2_contract.md`` §3):
      SHA256(utf8(str(dtype)) || utf8(repr(shape)) || C-order bytes)
  the raw standard-normal matrix and the sigma-scaled matrix are stored as
  ``s2_noise_sha256_raw`` and ``s2_noise_sha256_scaled``.

The two sets therefore cannot be compared as strings.  This script rebuilds the
RNG stream independently (no production imports), computes both calibers for
each group, and checks each against the artifact that froze it.  It is a
recording/alignment check only; it does not re-run the estimator or add new
numerical acceptance claims.

Usage:
    python checks/A/e0_acceptance/noise_digest_calibers.py <results_dir> <oracle_json> [--out out.json]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

SEED = 20261128
NP_N = 4000
TP_S = 1000e-9
TS = 0.25e-9

GROUPS = (
    ["air_0"]
    + ["air_%d" % i for i in range(1, 10)]
    + ["E0-S2@0.42", "E0-S2@0.69"]
)


def raw_byte_sha256(a):
    """Oracle caliber: SHA256 of float64 C-order bytes, no metadata prefix."""
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes(order="C")).hexdigest()


def array_sha256(a):
    """Delivery caliber: dtype string + repr(shape) + C-order bytes."""
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode("ascii"))
    h.update(repr(a.shape).encode("ascii"))
    h.update(a.tobytes(order="C"))
    return h.hexdigest()


def canonical_json_sha256(obj):
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def rebuild():
    """Rebuild 62-row table -> 11 offsets -> 12 noise matrices from the seed."""
    rng = np.random.default_rng(SEED)
    rows = []
    for i in (j for j in range(64) if j not in (27, 28)):
        rows.append(
            [
                int(i),
                float(rng.uniform(-0.75e-9, 0.75e-9)),
                float(rng.uniform(0.5, 1.5)),
                float(rng.uniform(-0.5, 0.5)),
                float(rng.uniform(-0.3, 0.3)),
            ]
        )
    air = [120.25 * TS]
    air += [float(rng.uniform(0.0, TP_S)) for _ in range(9)]
    targets = [float(rng.uniform(0.0, TP_S)) for _ in range(2)]
    noise = [rng.standard_normal((63, NP_N)) for _ in range(12)]
    table = {
        "experiment": "A-Q1-E0-S2",
        "seed": SEED,
        "rng": "numpy.random.default_rng(20261128)",
        "draw_order": (
            "for rx in sorted(0..63 excluding 27,28): "
            "Uniform(-0.75e-9,0.75e-9), Uniform(0.5,1.5), "
            "Uniform(-0.5,0.5), Uniform(-0.3,0.3)"
        ),
        "columns": ["rx_idx", "delta_tau_s", "gain_mag", "psi0_rad", "psi2_u2_rad"],
        "rows": rows,
    }
    return table, air, targets, noise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("oracle_json", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    res = json.loads((args.results_dir / "e0_s1s2_results.json").read_text(encoding="utf-8"))
    ora = json.loads(args.oracle_json.read_text(encoding="utf-8"))
    sigma = float(res["s2_noise_sigma"])
    sigma2 = float(res["s2_noise_sigma2"])

    table, air, targets, noise = rebuild()
    table_sha = canonical_json_sha256(table)

    oracle_noise = {r["group"]: r for r in ora["noise"]["rows"]}
    delivered_raw = list(res["s2_noise_sha256_raw"])
    delivered_scaled = list(res["s2_noise_sha256_scaled"])

    checks = {}
    checks["table_sha_matches_oracle"] = table_sha == ora["table"]["sha256"]
    checks["table_sha_matches_delivery"] = table_sha == res["s2_param_table_sha256"]

    oracle_rows = {r["label"]: r["u"] for r in ora["offsets"]["rows"]}
    rebuilt_offsets = air[1:] + targets
    labels = ["air_%d" % i for i in range(1, 10)] + ["E0-S2@0.42", "E0-S2@0.69"]
    worst_u = max(abs(v / TP_S - oracle_rows[k]) for k, v in zip(labels, rebuilt_offsets))
    checks["offsets_abs_err_u"] = worst_u
    checks["offsets_within_2e-15"] = worst_u <= 2e-15
    delivered_offsets = list(res["s2_air_offsets_s"]) + list(res["s2_target_offsets_s"])
    worst_u_delivered = max(
        abs(v / TP_S - oracle_rows[k]) for k, v in zip(labels, delivered_offsets[1:])
    )
    checks["delivered_offsets_abs_err_u"] = worst_u_delivered
    checks["delivered_offsets_within_2e-15"] = worst_u_delivered <= 2e-15

    rows = []
    all_raw = all_arr = all_scaled = all_firstlast = True
    for idx, group in enumerate(GROUPS):
        raw = noise[idx]
        scaled = sigma * raw
        raw_sha = raw_byte_sha256(raw)
        arr_sha = array_sha256(raw)
        scaled_sha = array_sha256(scaled)
        scaled_raw_sha = raw_byte_sha256(scaled)
        oracle_row = oracle_noise[group]
        row = {
            "group": group,
            "shape": list(raw.shape),
            "dtype": str(raw.dtype),
            "raw_byte_sha256": raw_sha,
            "array_sha256": arr_sha,
            "scaled_array_sha256": scaled_sha,
            "scaled_raw_byte_sha256": scaled_raw_sha,
            "oracle_raw_byte_sha256": oracle_row["sha256"],
            "delivered_array_sha256": delivered_raw[idx],
            "delivered_scaled_array_sha256": delivered_scaled[idx],
            "raw_byte_match_oracle": raw_sha == oracle_row["sha256"],
            "array_match_delivery": arr_sha == delivered_raw[idx],
            "scaled_array_match_delivery": scaled_sha == delivered_scaled[idx],
            "first": float(raw.flat[0]),
            "last": float(raw.flat[-1]),
            "first_match_oracle": float(raw.flat[0]) == float(oracle_row["first"]),
            "last_match_oracle": float(raw.flat[-1]) == float(oracle_row["last"]),
        }
        all_raw &= row["raw_byte_match_oracle"]
        all_arr &= row["array_match_delivery"]
        all_scaled &= row["scaled_array_match_delivery"]
        all_firstlast &= row["first_match_oracle"] and row["last_match_oracle"]
        rows.append(row)

    concat = hashlib.sha256(
        b"".join(np.ascontiguousarray(a, dtype=np.float64).tobytes(order="C") for a in noise)
    ).hexdigest()
    concat_match = concat == ora["noise"]["concat_sha256"]

    checks.update(
        {
            "raw_byte_per_group_match_oracle": all_raw,
            "array_sha256_per_group_match_delivery": all_arr,
            "scaled_array_sha256_per_group_match_delivery": all_scaled,
            "first_last_match_oracle": all_firstlast,
            "raw_byte_concat_sha256": concat,
            "raw_byte_concat_match_oracle": concat_match,
            "group_count": len(rows),
            "sigma": sigma,
            "sigma2": sigma2,
            "sigma2_consistent": abs(sigma2 - sigma * sigma) <= 1e-9 * max(1.0, sigma2),
        }
    )
    overall = all(
        [
            checks["table_sha_matches_oracle"],
            checks["table_sha_matches_delivery"],
            checks["offsets_within_2e-15"],
            checks["delivered_offsets_within_2e-15"],
            all_raw,
            all_arr,
            all_scaled,
            all_firstlast,
            concat_match,
            checks["sigma2_consistent"],
            len(rows) == 12,
        ]
    )

    evidence = {
        "experiment": "A-Q1-E0-S2",
        "purpose": "P17 addendum: crosswalk between the oracle raw-byte digest and the delivery array_sha256 digest",
        "object": {
            "branch": "data/a-q1-e0-s",
            "pull_request": 26,
            "results_commit": "5d14b7ba4f5b3f3b692a10ba94588ba23ffa85d6",
            "implementation_commit": res.get("implementation_sha"),
            "preregistration_commit": "5151844e598690f2bd47b3e31b0b993268864d56",
        },
        "calibers": {
            "raw_byte_sha256": "SHA256(float64 C-order bytes); no dtype/shape prefix; used by the oracle per-group and concatenation digests",
            "array_sha256": "SHA256(utf8(str(dtype)) || utf8(repr(shape)) || C-order bytes); used by s2_noise_sha256_raw/s2_noise_sha256_scaled in the delivery JSON",
            "note": "The two conventions are not string-comparable; equality must be established by rebuilding the matrices or by re-hashing the bytes with the other prefix rule.",
        },
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
        },
        "checks": checks,
        "groups": rows,
        "overall_pass": bool(overall),
    }

    out = args.out or (Path(__file__).resolve().parent / "noise_digest_calibers.json")
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("numpy", np.__version__, "python", sys.version.split()[0])
    print("table sha:", table_sha, "| oracle", checks["table_sha_matches_oracle"],
          "| delivery", checks["table_sha_matches_delivery"])
    print("offsets worst |du|: rebuilt %.3e delivered %.3e (tol 2e-15)"
          % (worst_u, worst_u_delivered))
    print()
    print("%-13s %-16s %-16s %-16s %-4s %-4s %-4s" %
          ("group", "raw-byte(oracle)", "array(delivery)", "scaled-array", "raw", "arr", "scl"))
    for r in rows:
        print("%-13s %-16s %-16s %-16s %-4s %-4s %-4s" % (
            r["group"], r["raw_byte_sha256"][:16], r["array_sha256"][:16],
            r["scaled_array_sha256"][:16],
            "OK" if r["raw_byte_match_oracle"] else "BAD",
            "OK" if r["array_match_delivery"] else "BAD",
            "OK" if r["scaled_array_match_delivery"] else "BAD",
        ))
    print()
    print("raw-byte concat:", concat, "| oracle match:", concat_match)
    print("sigma=%.12g sigma2=%.12g consistent=%s" % (sigma, sigma2, checks["sigma2_consistent"]))
    print("evidence:", out)
    print("RESULT:", "ALL_NOISE_DIGEST_CALIBERS_PASS" if overall else "NOISE_DIGEST_CALIBER_MISMATCH")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
