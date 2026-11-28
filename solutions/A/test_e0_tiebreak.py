#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1 空场 LOO 选参并列裁决的定向单测（``V1-20261128-01``）。

对象
----
``solutions/A/a_e0_s1s2.py::rank_lambda_candidates`` 与
``select_lambdas_air_loo`` 的并列裁决口径（PLAN §3.1 / 论文 §5.2.2）：

* 目标差 ``>= 1e-6 dB``：按 ``J_air`` 严格降序取最优；
* 目标差 ``< 1e-6 dB``：视为并列，依次比较
  ``λ_cal + λ_inv`` 更小 → 距默认点的网格索引 Manhattan 距离更近
  （等价时 Euclidean）→ 字典序更小。

覆盖
----
T1 无并列时严格按 J 取最优；T2 近并列按 λ 和改选；T3 近并列同 λ 和按字典序；
T4 近并列同 λ 和按网格索引距离（回归旧实现 ``|Δlogλ_cal + Δlogλ_inv|`` 的距离
错误）；T5 容差边界外仍严格比较；T6 E0-S 实测 9 对网格复算最优仍为
``(1e-4, 1e-3)`` 且无并列；T7 ``select_lambdas_air_loo`` 已接入该规则。

本测试不读取任何 ``.dat``，也不修改生产实现。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import a_e0_s1s2 as E  # noqa: E402

RESULTS: List[Dict[str, Any]] = []

GRID = [1e-4, 1e-3, 1e-2]


def check(name: str, cond: bool, note: str = "") -> bool:
    RESULTS.append({"name": name, "status": "PASS" if cond else "FAIL"})
    print("[%s] %-62s %s" % ("PASS" if cond else "FAIL", name, note))
    return bool(cond)


def row(lc: float, li: float, j: float) -> Dict[str, Any]:
    return {
        "lambda_cal": lc,
        "lambda_inv": li,
        "J_air_db": j,
        "min_supp_db": j - 25.0,
        "median_supp_db": j - 25.0,
        "supp_db": [j - 25.0],
    }


def pick(rows: Sequence[Dict[str, Any]], grid_cal=GRID, grid_inv=GRID,
         default_cal=1e-3, default_inv=1e-3) -> Dict[str, Any]:
    return E.rank_lambda_candidates(rows, grid_cal, grid_inv, default_cal, default_inv)


def test_t1_no_tie() -> None:
    rows = [row(1e-4, 1e-3, 74.10493189810367), row(1e-3, 1e-3, 74.00437176551410)]
    r = pick(rows)
    check("T1a_no_tie_picks_max_J", r["best"]["lambda_cal"] == 1e-4 and r["best"]["lambda_inv"] == 1e-3)
    check("T1b_no_tie_flag_false", r["near_tie"] is False)


def test_t2_near_tie_lambda_sum() -> None:
    rows = [
        row(1e-2, 1e-2, 80.0),
        row(1e-4, 1e-3, 80.0 - 5e-7),
        row(1e-3, 1e-3, 70.0),
    ]
    r = pick(rows)
    check(
        "T2_near_tie_prefers_smaller_lambda_sum",
        r["best"]["lambda_cal"] == 1e-4 and r["best"]["lambda_inv"] == 1e-3,
        "sum=%.2e < 2.0e-2" % (1e-4 + 1e-3),
    )
    check("T2b_near_tie_flag_true", r["near_tie"] is True)
    check("T2c_tied_size", len(r["tied"]) == 2)


def test_t3_near_tie_lexicographic() -> None:
    # 同 λ 和、同网格索引距离，仅字典序不同；J 更高的反而字典序更大。
    rows = [row(1e-3, 1e-4, 80.0), row(1e-4, 1e-3, 80.0 - 5e-7)]
    r = pick(rows)
    check(
        "T3_near_tie_lexicographic",
        r["best"]["lambda_cal"] == 1e-4 and r["best"]["lambda_inv"] == 1e-3,
    )


def test_t4_near_tie_index_distance() -> None:
    # 自定义 4 点网格：默认 (2,2)。(1,4) 与 (2,3) 的 λ 和同为 5，
    # 但 (2,3) 的 Manhattan 索引距离为 1、(1,4) 为 3。旧实现把
    # |Δlogλ_cal + Δlogλ_inv| 当距离，会给 (1,4) 算成 0。
    grid = [1.0, 2.0, 3.0, 4.0]
    rows = [row(1.0, 4.0, 90.0), row(2.0, 3.0, 90.0 - 5e-7)]
    r = pick(rows, grid_cal=grid, grid_inv=grid, default_cal=2.0, default_inv=2.0)
    check(
        "T4_near_tie_manhattan_index_distance",
        r["best"]["lambda_cal"] == 2.0 and r["best"]["lambda_inv"] == 3.0,
    )


def test_t5_tolerance_boundary() -> None:
    rows = [row(1e-2, 1e-2, 80.0), row(1e-4, 1e-4, 80.0 - 2e-6)]
    r = pick(rows)
    check(
        "T5_gap_gt_tol_is_not_tie",
        r["best"]["lambda_cal"] == 1e-2 and r["best"]["lambda_inv"] == 1e-2,
        "gap=2e-6 dB",
    )
    check("T5b_not_tied", r["near_tie"] is False)


def test_t6_e0s_regression() -> None:
    res_path = (
        HERE.parent.parent
        / "experiments"
        / "A"
        / "A-Q1-E0"
        / "s1s2"
        / "results"
        / "e0_s1s2_results.json"
    )
    if not res_path.is_file():
        check("T6a_results_json_present", False, str(res_path))
        return
    res = json.loads(res_path.read_text(encoding="utf-8"))
    rows = res["lambda_loo"]["grid_rows"]
    check("T6a_grid_size_9", len(rows) == 9)
    r = pick(rows, default_cal=1e-3, default_inv=1e-3)
    check(
        "T6b_e0s_best_unchanged",
        r["best"]["lambda_cal"] == 1e-4 and r["best"]["lambda_inv"] == 1e-2,
        "J=%.6f dB (E0-S 实测最大)" % r["best"]["J_air_db"],
    )
    check("T6c_e0s_no_near_tie", r["near_tie"] is False)
    js = sorted(float(x["J_air_db"]) for x in rows)
    gaps = [b - a for a, b in zip(js, js[1:])]
    check(
        "T6d_e0s_min_gap_far_above_tol",
        min(gaps) > 1e-4,
        "min_gap=%.6e dB" % min(gaps),
    )


def test_t7_wiring() -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    aligned = [rng.normal(size=(5, 7)) + 1j * rng.normal(size=(5, 7)) for _ in range(3)]
    f_r = np.linspace(0.3e9, 1.7e9, 7)
    r_dir = np.linspace(1.0, 2.0, 5)
    tau_dir = np.linspace(0.0, 1e-9, 5)
    cfg = {
        "lambda_cal_grid_air_loo": GRID,
        "lambda_inv_grid_air_loo": GRID,
        "lambda_cal_default": 1e-3,
        "lambda_inv_default": 1e-3,
    }
    out = E.select_lambdas_air_loo(aligned, 2, r_dir, tau_dir, f_r, cfg)
    ref = E.rank_lambda_candidates(
        out["grid_rows"], GRID, GRID, 1e-3, 1e-3
    )
    check(
        "T7a_selector_uses_ranked_best",
        out["best"] is ref["best"] or (
            out["best"]["lambda_cal"] == ref["best"]["lambda_cal"]
            and out["best"]["lambda_inv"] == ref["best"]["lambda_inv"]
        ),
    )
    check("T7b_selector_reports_tolerance", out["tie_tolerance_db"] == E.TIE_TOL_DB == 1e-6)
    check("T7c_selector_reports_near_tie", isinstance(out["near_tie"], bool) and len(out["tied_candidates"]) >= 1)
    check(
        "T7d_tied_candidates_cover_best",
        any(
            c["lambda_cal"] == out["best"]["lambda_cal"]
            and c["lambda_inv"] == out["best"]["lambda_inv"]
            for c in out["tied_candidates"]
        ),
    )


def test_t8_empty_rows() -> None:
    try:
        pick([])
        raised = False
    except ValueError:
        raised = True
    check("T8_empty_grid_raises", raised)


def main() -> int:
    check("T0_spec_tolerance_is_1e-6_dB", math.isclose(E.TIE_TOL_DB, 1e-6, rel_tol=0.0, abs_tol=0.0))
    test_t1_no_tie()
    test_t2_near_tie_lambda_sum()
    test_t3_near_tie_lexicographic()
    test_t4_near_tie_index_distance()
    test_t5_tolerance_boundary()
    test_t6_e0s_regression()
    test_t7_wiring()
    test_t8_empty_rows()
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    n_fail = len(RESULTS) - n_pass
    print("\n== summary: %d passed, %d failed ==" % (n_pass, n_fail))
    if n_fail:
        for r in RESULTS:
            if r["status"] == "FAIL":
                print("FAIL:", r["name"])
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
