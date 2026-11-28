"""P16/P17: independently rebuild the E0-S2 random stream and compare.

Rebuilds 62-channel parameter table -> 11 trigger offsets -> 12 noise matrices
(no production imports) and compares against the frozen oracle in
``checks/A/e0_s2_stream_oracle.json`` and the delivered results JSON.

Usage:
    python checks/A/e0_acceptance/stream_check.py <results_dir> <oracle_json>

Note: the delivered JSON stores per-group noise digests with the contract's
``array_sha256`` convention (dtype + repr(shape) + C-order bytes), while the
oracle freezes the digest of the raw float64 C-order bytes. Both are checked
here on purpose; only the raw bytes are compared value-for-value.
"""

import hashlib
import json
import os
import sys

import numpy as np

SEED = 20261128
NP_N = 4000
TP_S = 1000e-9
TS = 0.25e-9


def array_sha256(a):
    h = hashlib.sha256()
    h.update(str(a.dtype).encode("utf-8"))
    h.update(repr(a.shape).encode("utf-8"))
    h.update(np.ascontiguousarray(a).tobytes(order="C"))
    return h.hexdigest()


def canonical_json_sha256(obj):
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def rebuild():
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
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    res_dir, oracle_path = sys.argv[1], sys.argv[2]
    res = json.load(open(os.path.join(res_dir, "e0_s1s2_results.json"), encoding="utf-8"))
    ora = json.load(open(oracle_path, encoding="utf-8"))

    table, air, targets, noise = rebuild()
    table_sha = canonical_json_sha256(table)
    raw_byte_sha = [hashlib.sha256(a.tobytes(order="C")).hexdigest() for a in noise]
    array_sha = [array_sha256(a) for a in noise]
    concat = hashlib.sha256(b"".join(a.tobytes(order="C") for a in noise)).hexdigest()

    ok = True
    print("numpy", np.__version__, "python", sys.version.split()[0])
    print("table sha:", table_sha)
    print("  oracle match:", table_sha == ora["table"]["sha256"],
          "| delivered match:", table_sha == res["s2_param_table_sha256"])
    ok &= table_sha == ora["table"]["sha256"] == res["s2_param_table_sha256"]

    oracle_rows = {r["label"]: r["u"] for r in ora["offsets"]["rows"]}
    worst = 0.0
    for label, val in zip(
        ["air_1", "air_2", "air_3", "air_4", "air_5", "air_6", "air_7", "air_8", "air_9",
         "E0-S2@0.42", "E0-S2@0.69"],
        air[1:] + targets,
    ):
        worst = max(worst, abs(val / TP_S - oracle_rows[label]))
    print("worst |du| rebuilt vs oracle: %.3e (tol 2e-15)" % worst)
    ok &= worst <= 2e-15
    delivered = list(res["s2_air_offsets_s"]) + list(res["s2_target_offsets_s"])
    worst_d = 0.0
    for label, val in zip(
        ["air_1", "air_2", "air_3", "air_4", "air_5", "air_6", "air_7", "air_8", "air_9",
         "E0-S2@0.42", "E0-S2@0.69"],
        delivered[1:],
    ):
        worst_d = max(worst_d, abs(val / TP_S - oracle_rows[label]))
    print("worst |du| delivered vs oracle: %.3e (tol 2e-15)" % worst_d)
    ok &= worst_d <= 2e-15
    print("air_0 samples: %.6f (delivered %.6f, expect 120.25)"
          % (air[0] / TS, delivered[0] / TS))

    oracle_noise = {r["group"]: r["sha256"] for r in ora["noise"]["rows"]}
    groups = ["air_0"] + ["air_%d" % i for i in range(1, 10)] + ["E0-S2@0.42", "E0-S2@0.69"]
    per_group = all(oracle_noise[g] == h for g, h in zip(groups, raw_byte_sha))
    print("raw-byte per-group hashes match oracle:", per_group)
    ok &= per_group
    print("raw-byte concat:", concat)
    print("  oracle match:", concat == ora["noise"]["concat_sha256"])
    ok &= concat == ora["noise"]["concat_sha256"]
    print("delivered array_sha256 digests reproduced:", array_sha == res["s2_noise_sha256_raw"])
    ok &= array_sha == res["s2_noise_sha256_raw"]
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
