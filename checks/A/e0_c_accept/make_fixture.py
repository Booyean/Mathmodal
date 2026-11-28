#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 E0-C 验收检查器的**合成夹具**（不含任何真实 `.dat` 数据）。

用途：在 `dsh` 交付真实 E0-C 结果之前，先用解析上可手算的夹具证明检查器
（a）对一份完整、合规的交付给 PASS；（b）对每一类篡改/越界/漏证据给 FAIL 或
INSUFFICIENT。夹具数值全部由简单解析构造，期望指标可手算，不依赖生产代码。

夹具几何约定（单位：ns / m）：
- 压缩延迟网格 `tau = k*0.25 ns, k=0..3999`（与 PLAN 的 4000 点、`T_p=1000 ns` 一致）
- 全 63 路 `tau_dir = 0.2 ns`；背景幅度 0.1（|·|²=0.01）
- 直射波窗内 `z_after` 幅度 1.0、`z_before` 幅度 sqrt(1000) → Supp = 30 dB
- 目标处 `z_after` 幅度 10.0 → PNR = 10log10(100/0.01) = 40 dB
- 剖面 `P_after`：峰值 1.0；墙体旁瓣 0.1（PSLR=10 dB）、金属旁瓣 0.05（13.0103 dB）

用法（测试内部调用）：
    build_fixture(out_dir, e0s_path, oracle_path)
    build_fixture(..., d_hat_overrides={"墙体数据/data1-42cm": 0.49})
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import zipfile

C0 = 299792458.0
N_TAU = 4000
TAU_STEP_NS = 0.25
TAU_DIR_NS = 0.2
N_CH = 63
D_STEP_M = 0.0001
D_START_M = 0.15
D_STOP_M = 2.0
N_D = int(round((D_STOP_M - D_START_M) / D_STEP_M)) + 1

AIR_GROUPS = [f"空场数据/data{i}" for i in range(1, 11)]
LAMBDA_GRID = [1e-4, 1e-3, 1e-2]
DEFAULT = (1e-3, 1e-3)

TARGETS = [
    ("墙体数据/data1-42cm", "wall", 42.0, 0.42),
    ("金属板数据/data1-69cm", "metal", 69.0, 0.69),
]

METRICS_KEYS = ("group_key", "d_hat_m", "abs_err_cm", "supp_dw_win_db",
                "pslr_db", "pnr_db", "valid_rx", "finite")

PSLR_HALF_M = 0.1606031
GATE_PSLR = 3.0
GATE_PNR = 6.0
GATE_CAL_ELIGIBLE = 5.0
GATE_CAL_HARD = 10.71


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_git_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _npy_bytes(shape, kind: str, flat) -> bytes:
    if kind == "f8":
        descr = "<f8"
        payload = struct.pack("<%dd" % len(flat), *flat)
    elif kind == "c16":
        descr = "<c16"
        payload = struct.pack("<%dd" % len(flat), *flat)
    else:
        raise ValueError(kind)
    header = "{'descr': '%s', 'fortran_order': False, 'shape': (%s), }" % (
        descr, ", ".join(str(int(s)) for s in shape)
        + ("," if len(shape) == 1 else ""))
    header = header.encode("latin1")
    total = 10 + len(header) + 1
    pad = (64 - total % 64) % 64
    header = header + b" " * pad + b"\n"
    return (b"\x93NUMPY" + bytes([1, 0]) + struct.pack("<H", len(header))
            + header + payload)


def _write_npz(path: str, arrays: dict) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        for name, (shape, kind, flat) in arrays.items():
            z.writestr(name + ".npy", _npy_bytes(shape, kind, flat))


def _wrap(x: float) -> float:
    return (x + 500.0) % 1000.0 - 500.0


def _prefix(group_key: str) -> str:
    return (group_key.replace("空场数据/", "air_").replace("墙体数据/", "wall_")
            .replace("金属板数据/", "metal_").replace("/", "_")
            .replace("-", "_").replace(".", "_"))


def _build_group_arrays(group_key: str, target_type: str, d_hat: float):
    n = N_TAU
    tau = [k * TAU_STEP_NS for k in range(n)]
    tau_dir = [TAU_DIR_NS] * N_CH
    zb = [0.0] * (2 * N_CH * n)
    za = [0.0] * (2 * N_CH * n)

    k_win = [k for k, t in enumerate(tau) if abs(_wrap(t - TAU_DIR_NS)) <= 1.0]
    tau_tgt = 2.0 * d_hat / C0 * 1e9
    k_tgt = min(range(n), key=lambda k: abs(tau[k] - tau_tgt))
    if k_tgt in k_win:
        raise AssertionError("夹具设计错误：目标落在直射波窗内")

    amp_bg = 0.1
    amp_win_after = 1.0
    amp_win_before = math.sqrt(1000.0)
    for i in range(N_CH):
        base = i * n
        for k in range(n):
            zb[2 * (base + k)] = amp_bg
            za[2 * (base + k)] = amp_bg
        for k in k_win:
            zb[2 * (base + k)] = amp_win_before
            za[2 * (base + k)] = amp_win_after
        za[2 * (base + k_tgt)] = 10.0

    d_m = [D_START_M + k * D_STEP_M for k in range(N_D)]
    P = [1e-6] * N_D
    k_peak = min(range(N_D), key=lambda k: abs(d_m[k] - d_hat))
    P[k_peak] = 1.0
    if target_type == "wall":
        k_sl = min(range(N_D), key=lambda k: abs(d_m[k] - 1.5))
    else:
        k_sl = min(range(N_D), key=lambda k: abs(d_m[k] - 1.2))
    P[k_sl] = 0.1 if target_type == "wall" else 0.05

    arrays = {
        f"{_prefix(group_key)}__tau_ns": ((n,), "f8", tau),
        f"{_prefix(group_key)}__tau_dir_ns": ((N_CH,), "f8", tau_dir),
        f"{_prefix(group_key)}__z_before": ((N_CH, n), "c16", zb),
        f"{_prefix(group_key)}__z_after": ((N_CH, n), "c16", za),
        f"{_prefix(group_key)}__d_m": ((N_D,), "f8", d_m),
        f"{_prefix(group_key)}__P_after": ((N_D,), "f8", P),
    }
    side = [P[k] for k in range(N_D)
            if abs(d_m[k] - d_hat) > PSLR_HALF_M and 0.15 <= d_m[k] <= 2.0]
    pslr = 10.0 * math.log10(1.0 / max(side))
    return arrays, pslr


def _air_loo_arrays():
    p_cal = [0.0] * (9 * 10 * N_CH)
    p_sup = [0.0] * (9 * 10 * N_CH)
    supp = [[0.0] * 10 for _ in range(9)]
    pairs = [(a, b) for a in LAMBDA_GRID for b in LAMBDA_GRID]
    d_idx = pairs.index(DEFAULT)
    for f in range(9):
        for g in range(10):
            s = (11.0 if f == d_idx else 10.0) + 0.2 * g
            supp[f][g] = s
            factor = 10.0 ** (s / 10.0)
            for c in range(N_CH):
                cal = 1.0 + 0.01 * c
                idx = (f * 10 + g) * N_CH + c
                p_cal[idx] = cal
                p_sup[idx] = cal / factor
    return {"air_loo__p_cal": ((9, 10, N_CH), "f8", p_cal),
            "air_loo__p_sup": ((9, 10, N_CH), "f8", p_sup)}, supp


def _median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def build_fixture(out_dir: str, e0s_path: str, oracle_path: str,
                  d_hat_overrides=None, freeze_status_override=None,
                  write_frozen_override=None, e0s_sha_override=None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    with open(oracle_path, "r", encoding="utf-8-sig") as f:
        oracle = json.load(f)
    overrides = d_hat_overrides or {}

    arrays = {}
    groups = []
    for key, typ, d_true_cm, d_hat_default in TARGETS:
        d_hat = float(overrides.get(key, d_hat_default))
        arrs, pslr = _build_group_arrays(key, typ, d_hat)
        arrays.update(arrs)
        abs_err = abs(d_hat - d_true_cm / 100.0) * 100.0
        pnr = 40.0
        supp = 30.0
        if abs_err > GATE_CAL_HARD or pslr < GATE_PSLR or pnr < GATE_PNR:
            status = "hard_stop"
        elif abs_err > GATE_CAL_ELIGIBLE:
            status = "not_eligible_for_freeze"
        else:
            status = "eligible"
        groups.append({
            "group_key": key,
            "target_type": typ,
            "split": "wall_cal" if typ == "wall" else "metal_cal",
            "d_true_cm": d_true_cm,
            "d_hat_m": d_hat,
            "abs_err_cm": abs_err,
            "supp_dw_win_db": supp,
            "pslr_db": pslr,
            "pnr_db": pnr,
            "echo_ret_db": 0.0,
            "valid_rx": 63,
            "finite": True,
            "status": status,
            "gate_results": {
                "pslr_ge_3db": pslr >= GATE_PSLR,
                "pnr_ge_6db": pnr >= GATE_PNR,
                "abs_err_eligible": abs_err <= GATE_CAL_ELIGIBLE,
                "abs_err_not_hard": abs_err <= GATE_CAL_HARD,
            },
            "stop_reason": None if status == "eligible" else "gate_not_eligible",
        })

    air_arrs, supp = _air_loo_arrays()
    arrays.update(air_arrs)
    groups = [{
        "group_key": g, "target_type": "air", "split": "air",
        "d_true_cm": None, "d_hat_m": None, "abs_err_cm": None,
        "supp_dw_win_db": None, "pslr_db": None, "pnr_db": None,
        "echo_ret_db": None, "valid_rx": 63, "finite": True,
        "status": "eligible", "gate_results": {}, "stop_reason": None,
    } for g in AIR_GROUPS] + groups
    pairs = [(a, b) for a in LAMBDA_GRID for b in LAMBDA_GRID]
    grid = []
    for f in range(9):
        med = _median(supp[f])
        mn = min(supp[f])
        grid.append({"lambdas": list(pairs[f]),
                     "folds": [{"held_out": AIR_GROUPS[g], "supp_db": supp[f][g]}
                               for g in range(10)],
                     "j_air_db": med + 0.5 * mn, "min_db": mn, "median_db": med})
    d_idx = pairs.index(DEFAULT)
    sel_idx = d_idx
    air_loo = {
        "folds": [{"held_out": g} for g in AIR_GROUPS],
        "grid": grid,
        "selected": list(pairs[sel_idx]),
        "switched": False,
        "min_supp_db": grid[sel_idx]["min_db"],
        "median_supp_db": grid[sel_idx]["median_db"],
        "j_air_default_db": grid[d_idx]["j_air_db"],
        "eligibility": "eligible",
        "objective": "median + 0.5*min",
        "note": "synthetic fixture; not real data",
    }

    npz_path = os.path.join(out_dir, "e0c_arrays.npz")
    _write_npz(npz_path, arrays)

    groups_prefix = {k: _prefix(k) for k, _, _, _ in TARGETS}
    inputs = [{"rel_path": row["rel_path"], "size_bytes": row["size_bytes"],
               "sha256": row["sha256"]}
              for g in oracle["groups"].values() for row in g["files"]]

    metrics = [{k: g[k] for k in METRICS_KEYS} for g in groups]
    metrics_sha = hashlib.sha256(canonical_json(metrics).encode("utf-8")).hexdigest()

    if any(g["status"] == "hard_stop" for g in groups):
        overall = "hard_stop"
    elif all(g["status"] == "eligible" for g in groups):
        overall = "eligible"
    else:
        overall = "not_eligible_for_freeze"
    if freeze_status_override is not None:
        overall = freeze_status_override
    write_frozen = (overall == "eligible") if write_frozen_override is None \
        else bool(write_frozen_override)

    results = {
        "experiment_id": "A-Q1-E0",
        "phase": "E0-C",
        "scope": "real_calibration_pilot_non_blind_no_E0_T",
        "implementation_sha": "1" * 40,
        "parent_commit": "2" * 40,
        "main_commit": "3" * 40,
        "branch": "data/a-q1-e0-c",
        "config_sha256": "8fb6821fa3335ef748e16ad2f5b5b8fc818c13cbe9d3315377faf48d5e40e06a",
        "plan_sha256": "073511c0b6ae44dbc90d228b7d79c2de9d0687d4e65949494803b19f24595a88",
        "split_sha256": "d623da4ea186f372f2be094121c202c55dae0e236f4683005ab88d220a248b3a",
        "e0_s_results_sha256": e0s_sha_override or sha256_git_text(e0s_path),
        "fold_gate_contract_version": "D1-2",
        "environment": {"python": "3.12.11", "numpy": "1.26.4", "os": "fixture",
                        "threads": {"OMP_NUM_THREADS": "1",
                                    "OPENBLAS_NUM_THREADS": "1",
                                    "MKL_NUM_THREADS": "1",
                                    "NUMEXPR_NUM_THREADS": "1"}},
        "command": "python solutions/A/a_e0_c.py --config ... (fixture)",
        "resource": {"wall_time_s": 123.4, "peak_rss_mib": 512.0,
                     "single_process": True},
        "methods": {"alpha_mode": "fixed_1.0", "n0_improvements_enabled": False,
                    "adaptive_alpha": False, "subspace_suppression": False,
                    "wls_ranging": False, "nonuniform_channel_weights": False},
        "inputs": inputs,
        "air_loo_folds": AIR_GROUPS,
        "array_map": {"npz": "e0c_arrays.npz",
                      "group_prefix": groups_prefix,
                      "air_loo_prefix": "air_loo"},
        "lambda_selected": list(pairs[sel_idx]),
        "eta_wall": 0.25,
        "freeze": {"status": overall, "written": write_frozen, "eta_wall": 0.25},
        "arrays_sha256": "",
        "metrics_sha256": metrics_sha,
        "repeat_run": {"arrays_sha256": "", "metrics_sha256": metrics_sha},
        "d_true_usage": "evaluation_only",
        "files_sha256": {},
        "groups": groups,
        "stop_reason": None if overall == "eligible" else "gate_not_eligible",
    }

    results_path = os.path.join(out_dir, "e0c_results.json")
    with open(results_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
        f.write("\n")

    frozen = {"lambdas": list(pairs[sel_idx]), "eta_wall": 0.25,
              "implementation_sha": results["implementation_sha"],
              "config_sha256": results["config_sha256"],
              "frozen_at_utc": "2026-11-28T00:00:00Z",
              "note": "synthetic fixture; not real data"}
    if write_frozen:
        with open(os.path.join(out_dir, "e0c_frozen.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(frozen, f, ensure_ascii=False, indent=1)
            f.write("\n")

    with open(os.path.join(out_dir, "run.log"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("E0-C fixture run log\n"
                "12 whitelisted groups; 96 files; valid_rx=63; no holdout read\n"
                "lambda=(0.001,0.001) eta_wall=0.25 "
                f"freeze={overall}\n")

    with open(os.path.join(out_dir, "e0c_air_loo.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump(air_loo, f, ensure_ascii=False, indent=1)
        f.write("\n")

    arrays_sha = sha256_file(npz_path)
    results["arrays_sha256"] = arrays_sha
    results["repeat_run"]["arrays_sha256"] = arrays_sha
    files = ["e0c_results.json", "e0c_arrays.npz", "e0c_air_loo.json", "run.log"]
    if write_frozen:
        files.insert(3, "e0c_frozen.json")
    with open(results_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
        f.write("\n")

    with open(os.path.join(out_dir, "SHA256SUMS.txt"), "w", encoding="utf-8",
              newline="\n") as f:
        for n in files:
            f.write(f"{sha256_file(os.path.join(out_dir, n))}  {n}\n")

    return {"groups": groups, "air_loo": air_loo, "results": results,
            "arrays": arrays}
