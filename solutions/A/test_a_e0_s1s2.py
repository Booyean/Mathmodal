#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1-E0-S1/S2 合成求解器的作者测试与自检（零真实 ``.dat`` 读取）。

覆盖
----
* 预登记锚点：config/config.json、PLAN.md、62 路参数表规范 SHA256；
* 几何/频带常数：参考通道 R=0.07 m、k=300..1700 共 1401 bins；
* ``E0-S1`` 解析闭环：d、Δτ2、G2、ψ2、Δt0、t0_eff 与 P_norm/P_env 对照；
* ``E0-S2`` 门控：两目标测距/DW 抑制/PSLR/PNR、63 路有效、全有限；
* 交付数组独立重算：Supp_dw-win、BG_proxy、PNR、PSLR 与 JSON 差 <= 1e-9 dB；
* 确定性：同一命令/同一环境两次独立的数组与指标逐位一致；
* 真值隔离：修改 d_true 字段不影响 d_hat（估计器不读取真值）；
* 资源与证据：墙钟 <= 600 s、峰值 RSS <= 4096 MiB、无裸 NaN/Inf；
* 文件访问审计：运行期未打开任何 ``.dat``；
* P15 式反例：篡改 d_hat/Supp/valid_rx/finite 时校验器必须失败。

用法
----
    python solutions/A/test_a_e0_s1s2.py
    python solutions/A/test_a_e0_s1s2.py --quick   # 跳过第二次全量确定性复跑
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# 与 CLI 相同的资源口径：在导入 numpy 前固定单线程 BLAS/OpenMP。
for _thread_env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_env] = "1"

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import a_e0_s1s2 as E  # noqa: E402

RESULTS: List[Dict[str, Any]] = []
OPENED_PATHS: List[str] = []


def check(name: str, expected: Any, actual: Any, tol: Optional[float] = None, note: str = "") -> bool:
    if tol is not None:
        try:
            ok = bool(
                np.all(
                    np.abs(
                        np.asarray(expected, dtype=float) - np.asarray(actual, dtype=float)
                    )
                    <= tol
                )
            )
        except (TypeError, ValueError):
            ok = False
    else:
        ok = bool(expected == actual)
    RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL", "expected": expected, "actual": actual})
    print("[%s] %-60s expected=%r actual=%r%s" % ("PASS" if ok else "FAIL", name, expected, actual, ("  " + note) if note else ""))
    return ok


def ok(name: str, cond: bool, note: str = "") -> bool:
    RESULTS.append({"name": name, "status": "PASS" if cond else "FAIL", "expected": True, "actual": bool(cond)})
    print("[%s] %-60s %s" % ("PASS" if cond else "FAIL", name, note))
    return bool(cond)


def approx_rel(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(b))


def validate_case_fields(case: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """从 case 字段重算门控，而不是相信 JSON 自带的 passed。"""
    gates = cfg["gates_and_thresholds"]
    if case["case_id"] == "E0-S1":
        if not bool(case["finite"]):
            return False
        if abs(case["d_hat_m"] - case["d_true_m"]) * 100.0 > gates["synthetic_noiseless_max_range_err_cm"]:
            return False
        if case["dtau_err_ns"] is None or case["dtau_err_ns"] > gates["synthetic_noiseless_max_dtau_err_ns"]:
            return False
        return True
    if not bool(case["finite"]):
        return False
    if int(case["valid_rx"]) != int(gates["required_valid_rx_channels"]):
        return False
    if abs(case["d_hat_m"] - case["d_true_m"]) * 100.0 > gates["synthetic_noisy_max_range_err_cm"]:
        return False
    if case["supp_dw_win_db"] is None or case["supp_dw_win_db"] < gates["synthetic_noisy_min_dw_suppression_db"]:
        return False
    if case["pslr_db"] is None or case["pslr_db"] < gates["target_echo_min_pslr_db"]:
        return False
    if case["pnr_db"] is None or case["pnr_db"] < gates["target_echo_min_pnr_db"]:
        return False
    return True


def z_at(xc: np.ndarray, f_r: np.ndarray, delays: np.ndarray, norm: float) -> np.ndarray:
    out = np.empty(delays.shape, dtype=np.complex128)
    for i in range(xc.shape[0]):
        out[i] = xc[i] @ np.exp(-1j * 2.0 * np.pi * np.outer(f_r, delays[i])) / norm
    return out


def recompute_case_metrics(
    arr: Any, res: Dict[str, Any], case: Dict[str, Any], key: str, c0: float, tp: float
) -> Dict[str, float]:
    f_r = arr["freq_rf_hz"]
    r_dir = arr["s2_r_dir_m"]
    tau_dir = arr["s2_tau_dir_s"]
    s_eff = arr[key + "_s_eff"]
    x_cal = arr[key + "_x_cal"]
    x_after = arr[key + "_x_after"]
    norm = float(np.linalg.norm(s_eff))
    dw = np.linspace(-1.0, 1.0, 41) * 1e-9
    delays = (tau_dir[:, None] + dw[None, :]) % tp
    z_b = z_at(x_cal * np.conj(s_eff)[None, :], f_r, delays, norm)
    z_a = z_at(x_after * np.conj(s_eff)[None, :], f_r, delays, norm)
    supp = 10.0 * math.log10(
        float(np.sum(np.abs(z_b) ** 2)) / float(np.sum(np.abs(z_a) ** 2))
    )

    xab = x_after * np.conj(s_eff)[None, :]
    zg = np.empty((x_after.shape[0], 4000), dtype=np.complex128)
    band = arr["band_k"]
    full = np.zeros((x_after.shape[0], 4000), dtype=np.complex128)
    full[:, band] = xab
    zg = 4000.0 * np.fft.ifft(full, axis=1) / norm
    bg = float(np.mean(np.abs(zg[:, 200:3801]) ** 2))

    d_hat = float(case["d_hat_m"])
    r_t = np.sqrt(r_dir ** 2 + 4.0 * d_hat ** 2)
    tau = r_t / c0
    z_t = np.empty(r_dir.size, dtype=np.complex128)
    for i in range(r_dir.size):
        z_t[i] = xab[i] @ np.exp(-1j * 2.0 * np.pi * f_r * tau[i]) / norm
    pnr = 10.0 * math.log10(float(np.mean(np.abs(z_t) ** 2)) / bg)
    p_d = float(np.abs(np.sum(z_t / r_t)) ** 2 / np.sum(1.0 / r_t ** 2))
    p_sl = float(
        np.max(
            arr[key + "_profile_p_norm_eff"][
                np.abs(arr[key + "_profile_d_grid_m"] - d_hat) > 0.1606031
            ]
        )
    )
    pslr = 10.0 * math.log10(p_d / p_sl)
    return {"supp": supp, "bg": bg, "pnr": pnr, "pslr": pslr, "p_at_d_hat": p_d}


def main(argv: Optional[Sequence[str]] = None) -> int:
    quick = bool(argv and "--quick" in argv)
    cfg = E.load_config()
    base = E.Setup(cfg)

    # ---- 锚点与常数 -------------------------------------------------
    check("config_sha256_lf", E.EXPECTED_CONFIG_SHA256_LF, cfg["_config_sha256_lf"])
    plan_path = E.REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "PLAN.md"
    check("plan_sha256", E.EXPECTED_PLAN_SHA256, E.file_sha256(plan_path))
    table, rows, _ = E.draw_s2_param_table()
    check("s2_param_table_sha256", E.EXPECTED_S2_PARAM_TABLE_SHA256, E.canonical_json_sha256(table))
    check("s2_param_table_rows", 62, rows.shape[0])
    ok(
        "s2_param_table_rx_order",
        list(rows[:, 0].astype(int)) == [i for i in range(64) if i not in (27, 28)],
    )
    check("R_ref_m", 0.07, float(base.r_dir_all[28]), tol=1e-12)
    check("tau_ref_ns", 0.23349486663870647, float(base.tau_dir_all[28]) * 1e9, tol=1e-12)
    check("R_rx12_m", 0.15652475842498528, float(base.r_dir_all[12]), tol=1e-15)
    check("band_bins", 1401, base.n_band)
    check("band_k_ends", [300, 1700], [int(base.band_idx[0]), int(base.band_idx[-1])])
    check("f_D_first_Hz", 3.0e8, float(base.f_d[0]), tol=1e-3)

    # ---- 文件访问审计（P2 的作者侧证据） ---------------------------
    def _audit(event: str, args: Any) -> None:
        if event != "open" or not args:
            return
        try:
            p = os.fsdecode(args[0])
        except Exception:
            return
        OPENED_PATHS.append(p)

    sys.addaudithook(_audit)

    # ---- 运行 CLI（写文件、跑 S1/S2） -----------------------------
    # 输出目录放在工作区顶层 tmp/（可写且可清理）。仓库内目录受 DSH 的
    # DeleteSubdirectoriesAndFiles 限制，测试临时产物不应留在仓库树里。
    tmp_root = E.REPO_ROOT.parent / "tmp"
    if not tmp_root.is_dir():
        tmp_root = E.REPO_ROOT / "experiments" / "A" / "A-Q1-E0"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmpdir = tmp_root / "_s1s2_test_tmp"
    if tmpdir.exists():
        shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = E.main(
            [
                "--out",
                str(tmpdir),
                "--implementation-sha",
                "0" * 40,
                "--parent-commit",
                "1" * 40,
                "--main-commit",
                "2" * 40,
            ]
        )
    elapsed = time.perf_counter() - t0
    check("cli_exit_code", 0, rc)
    res = json.loads((tmpdir / "e0_s1s2_results.json").read_text(encoding="utf-8"))
    with np.load(tmpdir / "e0_s1s2_arrays.npz") as _npz:
        arr = {k: _npz[k] for k in _npz.files}
    check("overall_pass", True, res["overall_pass"])
    check("json_no_nan", False, ("NaN" in (tmpdir / "e0_s1s2_results.json").read_text(encoding="utf-8")) or ("Infinity" in (tmpdir / "e0_s1s2_results.json").read_text(encoding="utf-8")))
    check("config_match", True, res["config_sha256_match"])
    check("param_table_match", True, res["s2_param_table_match"])

    # 文件 SHA 证据
    check(
        "arrays_file_sha256",
        E.file_sha256(tmpdir / "e0_s1s2_arrays.npz"),
        res["arrays_file_sha256"],
    )
    check(
        "param_table_file_sha256",
        E.file_sha256(tmpdir / "e0_s2_param_table.json"),
        res["s2_param_table_file_sha256"],
    )
    for name in ("e0_s1s2_arrays.npz", "e0_s1s2_results.json", "e0_s2_param_table.json", "run.log"):
        ok("file_exists_%s" % name, (tmpdir / name).exists())

    # ---- E0-S1 -----------------------------------------------------
    s1 = res["cases"][0]
    check("s1_case_id", "E0-S1", s1["case_id"])
    check("s1_d_hat_m", 0.6, s1["d_hat_m"], tol=1e-9)
    check("s1_abs_err_cm", 0.0, s1["abs_err_cm"], tol=1e-9)
    check("s1_dtau2_s", 0.5e-9, s1["dtau2_hat_s"], tol=1e-12)
    check("s1_dtau_err_ns", 0.0, s1["dtau_err_ns"], tol=1e-9)
    check("s1_g2", 1.25, s1["g2_hat"], tol=1e-12)
    check("s1_psi2_rad", 0.30, s1["psi2_hat_rad"], tol=1e-12)
    check("s1_dt0_Ts", 130.15, s1["dt0_samples"], tol=1e-3)
    check("s1_t0_eff_Ts", 251.20, s1["t0_eff_tgt_samples"], tol=1e-3)
    check("s1_p_norm_m", 0.6, s1["d_hat_p_norm_m"], tol=1e-9)
    check("s1_p_env_m", 0.6, s1["d_hat_p_env_m"], tol=1e-9)
    ok(
        "s1_not_applicable_metrics_null",
        s1["supp_dw_win_db"] is None and s1["pslr_db"] is None and s1["pnr_db"] is None,
    )
    check("s1_valid_rx", 2, s1["valid_rx"])

    # ---- E0-S2 门控 ------------------------------------------------
    s2_cases = res["cases"][1:]
    for case, key in zip(s2_cases, ("s2_042", "s2_069")):
        cid = case["case_id"]
        ok("%s_finite" % cid, bool(case["finite"]))
        check("%s_valid_rx" % cid, 63, case["valid_rx"])
        ok("%s_abs_err_cm<=1.0" % cid, case["abs_err_cm"] <= 1.0, "err=%.6f" % case["abs_err_cm"])
        ok("%s_supp>=20dB" % cid, case["supp_dw_win_db"] >= 20.0, "supp=%.6f" % case["supp_dw_win_db"])
        ok("%s_pslr>=3dB" % cid, case["pslr_db"] >= 3.0, "pslr=%.6f" % case["pslr_db"])
        ok("%s_pnr>=6dB" % cid, case["pnr_db"] >= 6.0, "pnr=%.6f" % case["pnr_db"])
        ok("%s_field_validator" % cid, validate_case_fields(case, cfg))

        # 对齐/锚点诊断：期望 = 目标触发偏移 - air0（模 Tp），锚点 = 目标偏移 + 0.2 ns。
        t0_tgt = float(res["s2_target_offsets_s"][0 if key == "s2_042" else 1])
        t0_air0 = float(res["s2_air_offsets_s"][0])
        dt0_expected = (t0_tgt - t0_air0) % base.tp
        check(
            "%s_dt0_vs_truth_Ts" % cid,
            dt0_expected / base.ts,
            case["dt0_samples"],
            tol=0.05,
            note="diagnostic",
        )
        check(
            "%s_anchor_vs_truth_Ts" % cid,
            (t0_tgt + 0.2e-9) / base.ts,
            case["t_anchor_samples"],
            tol=0.05,
            note="diagnostic",
        )

        rec = recompute_case_metrics(arr, res, case, key, base.c0, base.tp)
        check("%s_supp_recompute_dB" % cid, rec["supp"], case["supp_dw_win_db"], tol=1e-9)
        check("%s_bg_recompute_rel" % cid, 0.0, (rec["bg"] - case["bg_proxy"]) / case["bg_proxy"], tol=1e-12)
        check("%s_pnr_recompute_dB" % cid, rec["pnr"], case["pnr_db"], tol=1e-9)
        check("%s_pslr_recompute_dB" % cid, rec["pslr"], case["pslr_db"], tol=1e-9)
        ok(
            "%s_p_at_d_hat_relative" % cid,
            approx_rel(rec["p_at_d_hat"], float(arr[key + "_p_at_d_hat"][0]), 1e-14),
        )

    # ---- S2 噪声基准：25 dB 必须相对“纯目标回波”功率 -----------------
    # 预登记/裁定 §2：σ²=10^{-2.5}·mean_{i,m}(纯 0.42 m 回波²)，不得把强
    # 直达波计入基准。此检查独立重建 0.42 m 纯回波并与 JSON 对账。
    rows_meta = np.asarray(res["s2_param_rows"], dtype=np.float64)
    h_ref_meta = E.planted_h_ref(base.f_d, base.f_r)
    h_rel_meta = E.h_rel_from_rows(rows_meta, base.rx63, base.f_d)
    t0_042 = float(res["s2_target_offsets_s"][0])
    s_eff0_meta = (
        h_ref_meta
        * base.s_band
        * np.exp(1j * 2.0 * np.pi * base.f_r * t0_042)
    )
    echo_meta = E.synth_group_spectrum(
        h_rel_meta,
        s_eff0_meta,
        base.r_dir_all[base.rx63],
        base.tau_dir_all[base.rx63],
        base.f_r,
        base.c0,
        d_true=0.42,
        gamma=0.25,
        include_direct=False,
    )
    echo_meta_t = E.to_time(echo_meta, base.band_idx, base.np_n)
    p_echo_meta = float(np.mean(echo_meta_t ** 2))
    check(
        "s2_echo_power_pure_target_rel",
        0.0,
        abs(p_echo_meta - res["s2_echo_power_042"]) / p_echo_meta,
        tol=1e-12,
    )
    check(
        "s2_sigma2_is_25dB_pure_echo",
        res["s2_echo_power_042"] * 10.0 ** (-25.0 / 10.0),
        res["s2_noise_sigma2"],
        tol=0.0,
    )

    # LOO 预算与选择
    loo = res["lambda_loo"]
    check("loo_budget_pairs", 9, loo["budget_pairs"])
    ok(
        "loo_selected_in_grid",
        loo["selected"]["lambda_cal"] in (1e-4, 1e-3, 1e-2)
        and loo["selected"]["lambda_inv"] in (1e-4, 1e-3, 1e-2),
    )
    ok("loo_default_row_present", abs(loo["default"]["lambda_cal"] - 1e-3) < 1e-15 and abs(loo["default"]["lambda_inv"] - 1e-3) < 1e-15)

    # ---- 资源与证据 ------------------------------------------------
    wall = float(res["resource"]["wall_time_s"])
    rss = res["resource"]["peak_rss_mib"]
    ok("wall_time_le_600s", wall <= 600.0, "wall=%.2fs" % wall)
    ok("peak_rss_available", rss is not None)
    if rss is not None:
        ok("peak_rss_le_4096MiB", float(rss) <= 4096.0, "rss=%.1fMiB" % float(rss))
    ok("alpha_fixed_1_0", float(cfg["methods_classic_baseline_only"]["direct_wave_suppression"]["alpha_fixed_value"]) == 1.0)
    ok("n0_disabled", cfg["methods_classic_baseline_only"]["n0_improvements_enabled"] is False)

    # ---- 真值隔离（P12）：估计器接口不含 d_true，改真值字段不改变估计 ----
    import inspect as _inspect

    ok(
        "solve_case_has_no_truth_param",
        "d_true" not in _inspect.signature(E.solve_case).parameters,
    )
    gen1 = E.generate_s1(base)
    cal1 = E.calibrate_air(
        gen1["air"], 0, gen1["r_dir"], gen1["tau_dir"], gen1["f_r"],
        base.band_idx, base.np_n, base.ts, base.tp,
        lam_cal=0.0, lam_inv=0.0,
    )
    solved_a = E.solve_case(
        gen1["target"], cal1, gen1["s_band"], gen1["r_dir"], gen1["tau_dir"],
        gen1["f_r"], base.c0, base, "metal", 0.25, cfg,
    )
    gen1["truth"]["d_true_m"] = 1.99
    gen1["truth"]["gamma"] = 123.0
    solved_b = E.solve_case(
        gen1["target"], cal1, gen1["s_band"], gen1["r_dir"], gen1["tau_dir"],
        gen1["f_r"], base.c0, base, "metal", 0.25, cfg,
    )
    check("truth_isolation_d_hat", solved_a["d_hat_m"], solved_b["d_hat_m"], tol=0.0)
    check("truth_isolation_supp", solved_a["supp_dw_win_db"], solved_b["supp_dw_win_db"], tol=0.0)

    # ---- 确定性（P11） ---------------------------------------------
    if not quick:
        result2, arrays2, *_ = E.run_all(cfg, base, [])
        check("determinism_arrays_sha256", res["arrays_sha256"], result2["arrays_sha256"])
        for c1, c2 in zip(res["cases"], result2["cases"]):
            ok("%s_deterministic_numeric" % c1["case_id"],
               c1["d_hat_m"] == c2["d_hat_m"]
               and c1["abs_err_cm"] == c2["abs_err_cm"]
               and c1["supp_dw_win_db"] == c2["supp_dw_win_db"]
               and c1["pslr_db"] == c2["pslr_db"]
               and c1["pnr_db"] == c2["pnr_db"])

    # ---- 文件审计：未打开 .dat / 未触碰真实数据 -------------------
    bad = [p for p in OPENED_PATHS if p.lower().endswith(".dat") or "竞赛题目" in p]
    ok("no_real_dat_opened", len(bad) == 0, "bad=%r" % bad[:3])

    # ---- P15 式篡改反例 -------------------------------------------
    def tamper_ok(mutator: Any) -> bool:
        case = json.loads(json.dumps(s2_cases[0]))
        mutator(case)
        return not validate_case_fields(case, cfg)

    ok("tamper_d_hat_detected", tamper_ok(lambda c: c.__setitem__("d_hat_m", c["d_hat_m"] + 0.02)))
    ok("tamper_supp_detected", tamper_ok(lambda c: c.__setitem__("supp_dw_win_db", 19.9)))
    ok("tamper_finite_detected", tamper_ok(lambda c: c.__setitem__("finite", False)))
    ok("tamper_valid_rx_detected", tamper_ok(lambda c: c.__setitem__("valid_rx", 62)))

    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print("\n== 汇总: %d passed, %d failed ==" % (n_pass, n_fail))
    if n_fail:
        for r in RESULTS:
            if r["status"] == "FAIL":
                print("FAIL: %s expected=%r actual=%r" % (r["name"], r["expected"], r["actual"]))
    print("临时输出目录:", tmpdir)
    if n_fail == 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
