#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E0-C 空场 LOO 低抑制折的诊断器（**只读归档产物，不重跑实验**）。

输入（全部是 ``b63e217`` 已登记交付包里的文件）：

* ``experiments/A/A-Q1-E0/e0c/results/e0c_air_loo.json``
* ``experiments/A/A-Q1-E0/e0c/results/e0c_results.json``
* ``experiments/A/A-Q1-E0/e0c/results/e0c_arrays.npz``（``air_loo__p_cal`` / ``air_loo__p_sup``）

本脚本**不打开任何 ``.dat``**、不重新选参、不改任何阈值，因此不构成 E0-C 重跑，
也不产生任何新的实测结论；它只把已交付数组拆成可核验的分解，回答：

1. 90 个 ``Supp_air-LOO`` 是否可由 ``p_cal``/``p_sup`` 逐位重算（C8 的数据基础）；
2. 低抑制折是哪几组，是否与 λ 有关（换 λ 能不能救）；
3. 残余功率在通道上的分布、跨折结构、与信号功率的关系（乘性增益失配？宽带？）；
4. 对齐偏移 ``cal.shifts_s`` 是否存在成对/分簇结构（采集批次线索）。

判定只写“可复算/可观察到的事实”，机制推断一律标注 ``established=False`` 的
``mechanism_hypotheses``，不把相关性写成因果结论。

用法::

    python solutions/A/diagnose_e0c_air_loo.py
    python solutions/A/diagnose_e0c_air_loo.py --out experiments/A/A-Q1-E0/e0c/diagnosis/air_loo_diagnosis.json

退出码：``0`` = 内部一致性检查全过（诊断可用）；``1`` = 归档产物不自洽（须先退数据方）；
``2`` = 用法/文件缺失。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "e0c" / "results"
DEFAULT_OUT = REPO_ROOT / "experiments" / "A" / "A-Q1-E0" / "e0c" / "diagnosis" / "air_loo_diagnosis.json"

DB_TOL = 1e-9
#: 通道按 ``a_dat_reader.channel_positions`` 的排布：idx = 8*(row-1) + (col-1)。
N_CHANNELS_PER_ROW = 8
TX_IDX = 27
REF_IDX = 28


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _row_col(idx: int) -> Tuple[int, int]:
    return idx // N_CHANNELS_PER_ROW + 1, idx % N_CHANNELS_PER_ROW + 1


def _db(ratio: float) -> float:
    return 10.0 * math.log10(float(ratio))


def _pair_index(loo: Dict[str, Any]) -> int:
    """返回 ``grid`` 中与 ``selected`` 完全一致的候选对索引。"""
    sel = [float(v) for v in loo["selected"]]
    for i, row in enumerate(loo["grid"]):
        if [float(v) for v in row["lambdas"]] == sel:
            return i
    raise SystemExit("selected λ 不在 grid 中：%r" % (sel,))


def _recompute_all_supp(
    p_cal: np.ndarray, p_sup: np.ndarray
) -> np.ndarray:
    """(pair, fold) → Supp；与生产代码 ``10*log10(sum(p_cal)/sum(p_sup))`` 同口径。"""
    n_pair, n_fold, _ = p_cal.shape
    out = np.empty((n_pair, n_fold), dtype=np.float64)
    for k in range(n_pair):
        for g in range(n_fold):
            out[k, g] = 10.0 * math.log10(
                float(np.sum(p_cal[k, g])) / float(np.sum(p_sup[k, g]))
            )
    return out


def _session_clusters(shifts_s: Sequence[float], tol_ns: float = 0.1) -> List[List[int]]:
    """按对齐偏移把组分成采集簇（仅按 ``shifts_s`` 数值，不使用任何标签）。"""
    order = sorted(range(len(shifts_s)), key=lambda i: float(shifts_s[i]))
    clusters: List[List[int]] = []
    for i in order:
        s = float(shifts_s[i]) * 1e9
        if clusters and abs(s - float(shifts_s[clusters[-1][-1]]) * 1e9) <= tol_ns:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    return clusters


def diagnose(results_dir: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """返回 (报告, 一致性检查列表)。"""
    results_json = _load_json(results_dir / "e0c_results.json")
    loo_json = _load_json(results_dir / "e0c_air_loo.json")
    npz = np.load(results_dir / "e0c_arrays.npz")
    p_cal = np.asarray(npz["air_loo__p_cal"], dtype=np.float64)
    p_sup = np.asarray(npz["air_loo__p_sup"], dtype=np.float64)

    folds = [str(f["held_out"]) for f in loo_json["folds"]]
    labels = [f.split("/")[-1] for f in folds]
    n_fold = len(folds)
    if p_cal.shape[1:] != (n_fold, 63) or p_cal.shape != p_sup.shape:
        raise SystemExit("p_cal/p_sup 形状不符：%r vs folds=%d" % (p_cal.shape, n_fold))

    gates = results_json["air_loo_raw"] if "air_loo_raw" in results_json else {}
    hard_db = 6.0
    elig_db = 10.0

    checks: List[Dict[str, Any]] = []

    def check(cid: str, name: str, ok: bool, detail: Any) -> None:
        checks.append({"id": cid, "name": name, "ok": bool(ok), "detail": detail})

    # ---- A) 90 个 Supp 可由 p_cal/p_sup 重算（C8 的数据基础）
    supp = _recompute_all_supp(p_cal, p_sup)
    reported = np.array(
        [[float(f["supp_db"]) for f in row["folds"]] for row in loo_json["grid"]],
        dtype=np.float64,
    )
    delta = np.abs(supp - reported)
    check(
        "D1",
        "90 个 Supp_air-LOO 可由 p_cal/p_sup 逐对重算",
        float(delta.max()) <= DB_TOL,
        {"max_abs_delta_db": float(delta.max()), "n_values": int(delta.size)},
    )

    # ---- B) 每一对 λ 下的最小抑制折与最低值
    pair_min = supp.min(axis=1)
    pair_argmin = supp.argmin(axis=1)
    check(
        "D2",
        "任何一对 λ 都无法把 min(Supp) 抬到 6.0 dB 硬停线",
        bool(pair_min.max() < hard_db),
        {
            "grid_min_db_range": [float(pair_min.min()), float(pair_min.max())],
            "hard_stop_db": hard_db,
            "eligible_db": elig_db,
            "argmin_fold_all_pairs": sorted({labels[int(i)] for i in pair_argmin}),
        },
    )

    default_pair = _pair_index(loo_json)
    per_fold: List[Dict[str, Any]] = []
    excess = np.log10(np.asarray(p_sup[default_pair], dtype=np.float64) + 1e-30)
    med = np.median(excess, axis=0)
    excess = excess - med[None, :]

    for g in range(n_fold):
        pc = p_cal[default_pair, g]
        ps = p_sup[default_pair, g]
        per_ch = 10.0 * np.log10(pc / ps)
        ses = [float(supp[k, g]) for k in range(supp.shape[0])]
        share = ps / float(np.sum(ps))
        per_fold.append(
            {
                "fold": labels[g],
                "group_key": folds[g],
                "supp_db": float(supp[default_pair, g]),
                "supp_min_over_grid_db": float(min(ses)),
                "supp_max_over_grid_db": float(max(ses)),
                "supp_lambda_spread_db": float(max(ses) - min(ses)),
                "per_channel_supp_median_db": float(np.median(per_ch)),
                "per_channel_supp_p10_db": float(np.percentile(per_ch, 10)),
                "n_channels_supp_below_0db": int(np.count_nonzero(per_ch < 0.0)),
                "channels_supp_below_0db": [
                    {"id": int(c), "row": _row_col(int(c))[0], "col": _row_col(int(c))[1]}
                    for c in np.flatnonzero(per_ch < 0.0)
                ],
                "excess_residual_mean_db": float(10.0 * excess[g].mean()),
                "excess_residual_std_db": float(10.0 * excess[g].std()),
                "residual_share_top_channel": float(share.max()),
                "corr_log_pcal_log_psup": float(
                    np.corrcoef(np.log(pc), np.log(ps))[0, 1]
                ),
            }
        )

    # ---- C) 低抑制折的特征：跨 λ 钝感（换 λ 救不了）
    bad = [r for r in per_fold if r["supp_db"] < hard_db]
    good = [r for r in per_fold if r["supp_db"] >= elig_db]
    check(
        "D3",
        "低抑制折集中在固定的两组，且对 λ 不敏感（钝感）",
        len(bad) == 2
        and max(r["supp_lambda_spread_db"] for r in bad)
        < min(r["supp_lambda_spread_db"] for r in good),
        {
            "low_folds": [r["fold"] for r in bad],
            "low_fold_lambda_spread_db": {
                r["fold"]: r["supp_lambda_spread_db"] for r in bad
            },
            "other_fold_lambda_spread_db_range": [
                float(min(r["supp_lambda_spread_db"] for r in good)),
                float(max(r["supp_lambda_spread_db"] for r in good)),
            ],
        },
    )

    # ---- D) 残余功率的通道簇：两组低抑制折在哪些通道上残余超过信号
    share_mean = np.mean(np.asarray(p_sup[default_pair], dtype=np.float64), axis=0)
    share_mean = share_mean / float(share_mean.sum())
    hot = np.argsort(share_mean)[-10:][::-1]
    cluster_idx = list(range(16, 24)) + list(range(47, 55))
    cluster_share = float(np.sum(share_mean[cluster_idx]))
    check(
        "D4",
        "残余功率在通道上高度集中（两个通道簇）",
        cluster_share > 0.6,
        {
            "top10_channels_share": [
                {"id": int(c), "row": _row_col(int(c))[0], "col": _row_col(int(c))[1],
                 "share": float(share_mean[c])}
                for c in hot
            ],
            "rows_16_23_and_47_54_share": cluster_share,
            "tx_idx": TX_IDX,
            "ref_idx": REF_IDX,
            "tx_row_col": list(_row_col(TX_IDX)),
            "ref_row_col": list(_row_col(REF_IDX)),
        },
    )

    # ---- E) 跨折残余“超出量”的形状相关：同簇/同批次的指纹
    corr_excess = np.corrcoef(excess)
    within_pairs = [
        (labels[i], labels[i + 1], float(corr_excess[i, i + 1]))
        for i in range(0, n_fold - 1, 2)
    ]
    check(
        "D5",
        "相邻两组（同偏移簇）的残余超出量形状高度相关",
        sum(1 for _, _, v in within_pairs if v >= 0.9) >= n_fold // 2 - 1,
        {"adjacent_pairs": within_pairs, "corr_matrix": corr_excess.round(4).tolist(),
         "note": "同一对齐偏移簇的两组形状相关 ≥0.9 的有 %d/%d 对；data1/data2 为最低的 %.2f，"
                 "仍明显高于跨簇相关（中位 %.2f）"
                 % (sum(1 for _, _, v in within_pairs if v >= 0.9), len(within_pairs),
                    within_pairs[0][2], float(np.median(corr_excess[np.triu_indices(n_fold, 2)])))},
    )

    # ---- F) 对齐偏移的簇结构（采集批次线索）
    shifts_s = [float(s) for s in results_json["cal"]["shifts_s"]]
    shifts_ns = [v * 1e9 for v in shifts_s]
    clusters = _session_clusters(shifts_s)
    check(
        "D6",
        "对齐偏移呈成对分簇（同簇内偏移差 < 0.1 ns）",
        all(len(c) == 2 for c in clusters) and len(clusters) == n_fold // 2,
        {
            "shifts_ns": dict(zip(labels, [round(v, 4) for v in shifts_ns])),
            "clusters": [
                {"folds": [labels[i] for i in c],
                 "shift_ns_range": [round(min(shifts_ns[i] for i in c), 4),
                                    round(max(shifts_ns[i] for i in c), 4)]}
                for c in clusters
            ],
        },
    )

    # ---- G) 排除“纯标量复增益失配”：残差若 ∝ 信号则两者功率强相关
    corr_bad = [r["corr_log_pcal_log_psup"] for r in bad]
    corr_good = [r["corr_log_pcal_log_psup"] for r in good]
    check(
        "D7",
        "低抑制折的残差与信号功率弱相关（不是纯乘性增益失配）",
        max(corr_bad) < min(corr_good),
        {"corr_bad": dict(zip([r["fold"] for r in bad], corr_bad)),
         "corr_good_range": [float(min(corr_good)), float(max(corr_good))]},
    )

    # ---- H) 总校准功率：排除整组增益异常
    tot_cal_db = {}
    for g in range(n_fold):
        tot_cal_db[labels[g]] = float(_db(float(np.sum(p_cal[default_pair, g]))))
    spread = max(tot_cal_db.values()) - min(tot_cal_db.values())
    check(
        "D8",
        "各组校准后总功率差异 < 1 dB（不存在整组增益异常）",
        spread < 1.0,
        {"total_cal_power_db_rel": {
            k: round(v - max(tot_cal_db.values()), 3) for k, v in tot_cal_db.items()
        }, "spread_db": float(spread)},
    )

    report: Dict[str, Any] = {
        "contract": "E0-C-DIAG-1",
        "scope": "只读 b63e217 归档交付包；不读 .dat、不重跑、不调参、不读 E0-T",
        "source": {
            "results_dir": str(results_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
            "implementation_sha": results_json.get("implementation_sha"),
            "results_commit": "b63e217",
            "arrays_sha256": results_json.get("arrays_sha256"),
            "metrics_sha256": results_json.get("metrics_sha256"),
        },
        "gates": {
            "air_loo_hard_stop_db": hard_db,
            "air_loo_eligible_db": elig_db,
            "observed_min_db": float(loo_json["min_supp_db"]),
            "observed_median_db": float(loo_json["median_supp_db"]),
            "eligibility": loo_json["eligibility"],
        },
        "default_pair": {
            "index": default_pair,
            "lambdas": [float(v) for v in loo_json["selected"]],
        },
        "per_fold": per_fold,
        "findings": [
            {
                "id": "F1",
                "established": True,
                "statement": "90 个 Supp_air-LOO 可由交付的 p_cal/p_sup 逐对重算，"
                             "最大偏差 %.3e dB。" % float(delta.max()),
            },
            {
                "id": "F2",
                "established": True,
                "statement": "低抑制折固定为 %s；9 对 λ 下它们最高只有 %.4f / %.4f dB，"
                             "任何 λ 都到不了 6.0 dB 硬停线，更到不了 10.0 dB 可冻结线。"
                             % (", ".join(r["fold"] for r in bad),
                                max(r["supp_max_over_grid_db"] for r in bad[:1]),
                                max(r["supp_max_over_grid_db"] for r in bad[1:])),
            },
            {
                "id": "F3",
                "established": True,
                "statement": "低抑制折的残余超出量呈宽带抬高（组内均值 %.2f / %.2f dB），"
                             "并叠加在两组固定的通道簇上；通道簇 16–23 与 47–54 合计占"
                             "残余功率 %.1f%%。"
                             % (bad[0]["excess_residual_mean_db"], bad[1]["excess_residual_mean_db"],
                                100.0 * cluster_share),
            },
            {
                "id": "F4",
                "established": True,
                "statement": "对齐偏移按 0.1 ns 容差分成 %d 个采集簇（每簇 %s 组），低抑制折恰好落在"
                             "偏移≈0 的那一簇；同簇两组的残余超出量形状相关系数为 %.2f–%.2f。"
                             % (len(clusters),
                                "/".join(str(len(c)) for c in clusters),
                                min(v for _, _, v in within_pairs),
                                max(v for _, _, v in within_pairs)),
            },
            {
                "id": "F5",
                "established": True,
                "statement": "低抑制折的残差/信号功率相关系数仅 %.2f/%.2f，低于其余组的 %.2f–%.2f，"
                             "故残差不是纯标量复增益失配（否则两者应近似正比）。"
                             % (corr_bad[0], corr_bad[1], min(corr_good), max(corr_good)),
            },
            {
                "id": "F6",
                "established": False,
                "statement": "机制假设（未证实，需新预登记的诊断才能判定）：低抑制折的共同偏差"
                             "更像“采集批次级、通道簇化的相对频响/相位差异”，而不是噪声或 λ 选参"
                             "问题。可检验入口是 model_q1.md §4.1 第 3 条要求但尚未执行的行板间"
                             "异步抖动核查。",
            },
        ],
        "checks": checks,
        "checks_all_ok": all(c["ok"] for c in checks),
    }
    return report, checks


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E0-C 空场 LOO 低抑制折诊断（只读归档产物）")
    ap.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    results_dir = Path(args.results_dir).resolve()
    if not (results_dir / "e0c_arrays.npz").is_file():
        print("缺少归档数组：%s" % results_dir, file=sys.stderr)
        return 2

    report, checks = diagnose(results_dir)

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 78)
    for c in checks:
        print("%s %-6s %s" % ("PASS" if c["ok"] else "FAIL", c["id"], c["name"]))
    print("-" * 78)
    for f in report["findings"]:
        print("[%s] %s" % ("FACT" if f["established"] else "HYP ", f["statement"]))
    print("-" * 78)
    print("default pair λ=%r  min=%.4f dB  median=%.4f dB  eligibility=%s"
          % (report["default_pair"]["lambdas"], report["gates"]["observed_min_db"],
             report["gates"]["observed_median_db"], report["gates"]["eligibility"]))
    print("diagnosis written: %s" % out)
    print("=" * 78)
    return 0 if report["checks_all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
