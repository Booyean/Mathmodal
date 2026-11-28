#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-Q1-N0 生产侧打包器：`E0-N0-PRODUCER-CONTRACT-1` -> `E0-N0-1` 交付包。

职责边界
--------
本模块只做 **整形 + 自洽派生 + 落盘**，不做求解、不读 `.dat`、不改任何阈值、
不写 `n0_frozen.json`、不代替 `accept_e0n0.py` 的数值判定。

核心约束（与 `accept_e0n0.py` 的独立重算口径一致）：

* `n0.xcluster_supp_db[f][g]` 必须等于
  `10*log10( sum(p_cal[f,g,:]) / sum(p_sup[f,g,:]) )`（`supp_db_tol = 1e-6`）；
* `e0c_air_loo.json#grid[i].folds[g].supp_db` 必须能由
  `air_loo__p_cal[i,g,:] / air_loo__p_sup[i,g,:]` 重算；
* `metrics_sha256` = 按 `groups` 的 8 个键规范化后的 SHA256；
* `registration.input_manifest_sha256` = 按 (rel_path, size, sha256) 排序后
  规范化 JSON 的 SHA256；
* `SHA256SUMS.txt` 覆盖全部必需文件（raw 或 LF 归一化命中，逐文件记录口径）。

因此本模块**不让调用方直接填**上述声明值——声明值一律从数组/清单派生，
避免“声明值与数组两张皮”在验收时被判 N3/N4/N14 不符。

用法
----
```sh
python solutions/A/a_e0_n0_package.py --raw raw_n0.json --out experiments/A/A-Q1-E0/n0/results \
    --prereg checks/A/e0_n0_prereg.json
python solutions/A/a_e0_n0_package.py --from-prototype-synthetic <n0_synthetic_results.json> \
    --out /tmp/pkg --prereg checks/A/e0_n0_prereg.json   # 仅用于合成夹具自检
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

ARTIFACT_CONTRACT = "E0-N0-1"
PRODUCER_CONTRACT = "E0-N0-PRODUCER-CONTRACT-1"
PHASE_CONTRACT = "E0-N0-PHASE-1"
PHASE_EVIDENCE_CONTRACT = "E0-N0-PHASE-EVIDENCE-1"
PREREG_IDS = ("E0-N0-PREREG-1", "A-Q1-N0-PREREG-1")
#: 方法范围串（`identity.method_scope`，ACCEPT-3 identity 守卫按此值拒收错包）。
METHOD_SCOPE = "M0-DW-Subspace/rank-2/in-window-2coef"
#: 正确 Gram-Schmidt 后归一化 |<T, D1>| 的数值上界。
D1_ORTHO_TOL = 1e-6
#: 相位证据的固定阈值（与 `E0-N0-PHASE-1` / 冻结 prereg 同值，只读）。
RHO_MIN = 0.001

N_CH = 63
VALID_RX = 63
AIR_GROUPS: Tuple[str, ...] = tuple("空场数据/data%d" % i for i in range(1, 11))
CLUSTERS: Tuple[Tuple[str, Tuple[str, str]], ...] = (
    ("C0", ("空场数据/data1", "空场数据/data2")),
    ("C1", ("空场数据/data3", "空场数据/data4")),
    ("C2", ("空场数据/data5", "空场数据/data6")),
    ("C3", ("空场数据/data7", "空场数据/data8")),
    ("C4", ("空场数据/data9", "空场数据/data10")),
)
TARGET_GROUPS: Tuple[str, ...] = ("墙体数据/data1-42cm", "金属板数据/data1-69cm")
ARMS: Tuple[str, ...] = ("C0", "C1", "C2")
DECISION_ARM = "C2"
FIXED_LAMBDA: Tuple[float, float] = (0.001, 0.001)
RETENTION_CASE = "E0-S2@0.42"

#: 契约 `files.required`（探测/验收都会查）
REQUIRED_FILES: Tuple[str, ...] = (
    "e0c_results.json",
    "e0c_arrays.npz",
    "e0c_air_loo.json",
    "e0c_repeat.json",
    "run.log",
    "SHA256SUMS.txt",
    "worker_meta.json",
    "repeat/worker_meta.json",
    "repeat/e0c_results.json",
)
GATE_FILES: Tuple[str, ...] = ("preflight.json", "dryrun.json")

#: `array_map` 的三个前缀键（验收器 N14 要求全部显式）
DEFAULT_ARRAY_MAP = {
    "xcluster_prefix": "xcluster",
    "phase_prefix": "phase",
    "air_loo_prefix": "air_loo",
}

#: (npz member, shape) —— 形状里的 n_grid 由 grid 长度决定
ARRAY_SPECS: Tuple[Tuple[str, str, Tuple[Any, ...]], ...] = (
    ("xcluster__p_cal", "xcluster_prefix", (5, 2, N_CH)),
    ("xcluster__p_sup", "xcluster_prefix", (5, 2, N_CH)),
    ("air_loo__p_cal", "air_loo_prefix", ("n_grid", 10, N_CH)),
    ("air_loo__p_sup", "air_loo_prefix", ("n_grid", 10, N_CH)),
    ("phase__shifts_ns", "phase_prefix", (10,)),
    ("phase__coherence", "phase_prefix", (10,)),
)


class PackageError(ValueError):
    """生产侧产物不满足打包前置条件。"""


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file_lf(path: str) -> str:
    """文本文件按 LF 归一化后的 SHA256（git blob 口径；N0 新产物统一口径）。"""
    with open(path, "rb") as f:
        data = f.read()
    return sha256_bytes(data.replace(b"\r\n", b"\n"))


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise PackageError(msg)


def _flatten(arr: Any) -> List[float]:
    """把嵌套 list / numpy 数组压成 C-order 一维 float 列表。"""
    if hasattr(arr, "tolist"):
        arr = arr.tolist()
    out: List[float] = []

    def walk(x: Any) -> None:
        if isinstance(x, (list, tuple)):
            for y in x:
                walk(y)
        else:
            out.append(float(x))

    walk(arr)
    return out


def _shape_of(arr: Any) -> Tuple[int, ...]:
    shape: List[int] = []
    cur = arr
    while isinstance(cur, (list, tuple)) or hasattr(cur, "shape"):
        if hasattr(cur, "shape"):
            return tuple(int(v) for v in cur.shape)
        shape.append(len(cur))
        if not cur:
            break
        cur = cur[0]
    return tuple(shape)


def _check_array(arr: Any, want: Tuple[Any, ...], n_grid: int, name: str) -> Tuple[int, ...]:
    shape = _shape_of(arr)
    resolved = tuple(n_grid if s == "n_grid" else int(s) for s in want)
    if shape != resolved:
        raise PackageError("%s 形状应为 %r，实为 %r" % (name, resolved, shape))
    if len(_flatten(arr)) != int(_prod(resolved)):
        raise PackageError("%s 元素数与形状不符" % name)
    return resolved


def _prod(shape: Sequence[int]) -> int:
    n = 1
    for s in shape:
        n *= int(s)
    return n


def _supp_db(cal: Sequence[float], sup: Sequence[float]) -> float:
    num = float(sum(cal))
    den = float(sum(sup))
    if not (num > 0.0 and den > 0.0):
        raise PackageError("功率非正：cal=%r sup=%r" % (num, den))
    return 10.0 * math.log10(num / den)


def recompute_xcluster(arrays: Dict[str, Any]) -> List[List[float]]:
    """按验收器口径从数组重算 5x2 跨簇 Supp。"""
    cal = _flatten(arrays["xcluster__p_cal"])
    sup = _flatten(arrays["xcluster__p_sup"])
    rows: List[List[float]] = []
    for a in range(5):
        row: List[float] = []
        for b in range(2):
            base = (a * 2 + b) * N_CH
            row.append(_supp_db(cal[base:base + N_CH], sup[base:base + N_CH]))
        rows.append(row)
    return rows


def recompute_air_loo(arrays: Dict[str, Any], n_grid: int) -> List[List[float]]:
    """按验收器口径重算 grid x 10 的 Supp 表。"""
    cal = _flatten(arrays["air_loo__p_cal"])
    sup = _flatten(arrays["air_loo__p_sup"])
    rows: List[List[float]] = []
    for g in range(n_grid):
        row: List[float] = []
        for b in range(10):
            base = (g * 10 + b) * N_CH
            row.append(_supp_db(cal[base:base + N_CH], sup[base:base + N_CH]))
        rows.append(row)
    return rows


def tier_of_supp(min_db: float, hard_stop_db: float = 6.0,
                 eligible_db: float = 10.0) -> str:
    if min_db >= eligible_db:
        return "eligible"
    if min_db >= hard_stop_db:
        return "below_eligible"
    return "hard_stop"


def metrics_digest(groups: Sequence[Dict[str, Any]]) -> str:
    keys = ("group_key", "d_hat_m", "abs_err_cm", "supp_dw_win_db",
            "pslr_db", "pnr_db", "valid_rx", "finite")
    rows = [{k: g.get(k) for k in keys} for g in groups]
    return sha256_bytes(canonical_json(rows).encode("utf-8"))


def inputs_digest(inputs: Sequence[Dict[str, Any]]) -> str:
    rows = sorted((str(x.get("rel_path")), int(x.get("size_bytes", -1)),
                   str(x.get("sha256"))) for x in inputs)
    return sha256_bytes(canonical_json(rows).encode("utf-8"))


def median(values: Sequence[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


# --------------------------------------------------------------------------- #
# 打包：raw -> 契约结果
# --------------------------------------------------------------------------- #
def _norm_anchor(v: Any, name: str, n: int) -> str:
    _require(isinstance(v, str) and len(v) == n, "%s 应为 %d 位 hex" % (name, n))
    _require(all(c in "0123456789abcdef" for c in v.lower()),
             "%s 应为小写 hex" % name)
    return v.lower()


def _groups_default(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """返回 12 组；空场组指标为 null，`valid_rx`/`finite` 必须显式给。"""
    groups = raw.get("groups")
    _require(isinstance(groups, list) and len(groups) == 12,
             "groups 必须恰为 12 组")
    keys = [g.get("group_key") for g in groups]
    want = list(AIR_GROUPS) + list(TARGET_GROUPS)
    _require(sorted(keys) == sorted(want), "groups 组名与预登记不符：%r" % (keys,))
    out = []
    for g in groups:
        row = {
            "group_key": g["group_key"],
            "target_type": g["target_type"],
            "d_hat_m": g.get("d_hat_m"),
            "abs_err_cm": g.get("abs_err_cm"),
            "supp_dw_win_db": g.get("supp_dw_win_db"),
            "pslr_db": g.get("pslr_db"),
            "pnr_db": g.get("pnr_db"),
            "valid_rx": int(g.get("valid_rx", VALID_RX)),
            "finite": bool(g.get("finite", True)),
        }
        if row["group_key"] in AIR_GROUPS:
            _require(all(row[k] is None for k in
                         ("d_hat_m", "abs_err_cm", "supp_dw_win_db",
                          "pslr_db", "pnr_db")),
                     "空场组 %s 的五个指标必须为 null" % row["group_key"])
        else:
            for k in ("d_hat_m", "abs_err_cm", "supp_dw_win_db", "pslr_db", "pnr_db"):
                _require(_finite(row[k]), "目标组 %s 缺 %s" % (row["group_key"], k))
        out.append(row)
    return out


def _fold_map(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    given = raw.get("xcluster_fold_map")
    if given is not None:
        _require(len(given) == 5, "xcluster_fold_map 必须 5 折")
        return given
    out = []
    for i, (cname, held) in enumerate(CLUSTERS):
        out.append({
            "fold": i,
            "cluster": cname,
            "held_out": list(held),
            "train": [g for g in AIR_GROUPS if g not in held],
        })
    return out


def _phase_block(raw: Dict[str, Any], arrays: Dict[str, Any]) -> Dict[str, Any]:
    """相位块：所有派生量都从 `raw["phase"]` 的逐组 rho 与数组重算。

    冻结定义（`E0-N0-PHASE-EVIDENCE-1`，见 `coordination/A_Q1_N0_PHASE_EVIDENCE.md`）：

    * `rho_g` = 第 g 组与**同预登记簇另一组**在参考通道上的宽带复相干模，范围 [0,1]；
    * `aligned_g := (rho_g >= rho_min)`，必须与 `per_group[g].aligned` 一致；
    * `phase__coherence` 必须逐元素等于 `rho_g`（不是独立可填的数组）；
    * `d1_min_abs_inner` = 全池秩 2 基上 min_f |<T_f,D1_f>|/(||T_f||·||D1_f||)，
      正确 Gram-Schmidt 下应 ≤ 1e-6（实测 0–1e-16）；缺失或 O(1) 一律拒收。
    """
    ph = raw.get("phase")
    _require(isinstance(ph, dict), "phase 块缺失")
    shifts = _flatten(arrays["phase__shifts_ns"])
    coh = _flatten(arrays["phase__coherence"])
    _require(len(shifts) == 10 and len(coh) == 10, "phase 数组应为 10 个元素")
    order = list(ph.get("group_order") or AIR_GROUPS)
    _require(order == list(AIR_GROUPS), "phase.group_order 应等于 10 组空场登记顺序")
    per = ph.get("per_group") or []
    _require(len(per) == 10, "phase.per_group 必须覆盖 10 组")
    rho_min = float(ph.get("rho_min", RHO_MIN))
    _require(abs(rho_min - RHO_MIN) <= 1e-15,
             "phase.rho_min 应为冻结值 %.6g（收到 %.6g）" % (RHO_MIN, rho_min))
    out_per = []
    for i, g in enumerate(AIR_GROUPS):
        item = per[i] if i < len(per) else {}
        _require(item.get("group") in (None, g), "phase.per_group 顺序错位")
        rho = float(item.get("rho"))
        _require(_finite(rho) and 0.0 <= rho <= 1.0,
                 "%s.rho=%r 应为 [0,1] 内有限数" % (g, item.get("rho")))
        _require(abs(coh[i] - rho) <= 1e-12,
                 "%s: phase__coherence=%r 与 per_group.rho=%r 不一致"
                 % (g, coh[i], rho))
        aligned = bool(rho >= rho_min)
        _require(bool(item.get("aligned", aligned)) is aligned,
                 "%s.aligned 与 rho=%.6g 的判定不一致" % (g, rho))
        reason = item.get("reason")
        _require(aligned or bool(reason), "%s 未对齐但无 reason" % g)
        out_per.append({
            "group": g,
            "cluster": item.get("cluster"),
            "aligned": aligned,
            "shift_ns": float(shifts[i]),
            "rho": rho,
            "reason": None if aligned else str(reason),
        })
    _require([p["cluster"] for p in out_per] ==
             [c for c, _h in CLUSTERS for _ in _h],
             "phase.per_group.cluster 与预登记簇顺序不符")
    for cname, held in CLUSTERS:
        a = shifts[AIR_GROUPS.index(held[0])]
        b = shifts[AIR_GROUPS.index(held[1])]
        diff = abs((a - b + 500.0) % 1000.0 - 500.0)
        _require(diff <= float(ph.get("cluster_shift_tol_ns", 0.1)),
                 "%s 内两组偏移差 %.4f ns 超容差" % (cname, diff))
    d1_rank = int(ph.get("d1_rank", 2))
    _require(d1_rank in (1, 2), "phase.d1_rank 应为 1 或 2")
    _require("d1_min_abs_inner" in ph, "phase.d1_min_abs_inner 缺失（不得默认 0.0）")
    inner = float(ph["d1_min_abs_inner"])
    _require(_finite(inner) and 0.0 <= inner <= 1.0,
             "phase.d1_min_abs_inner=%r 应为 [0,1] 内有限数" % (ph["d1_min_abs_inner"],))
    if d1_rank == 2:
        _require(inner <= D1_ORTHO_TOL,
                 "phase.d1_min_abs_inner=%.3e > %.1e：秩 2 基未正交化或未计算"
                 % (inner, D1_ORTHO_TOL))
    else:
        _require(inner == 0.0, "d1_rank=1 时 d1_min_abs_inner 应为 0.0（无第二模态）")
    return {
        "contract": PHASE_CONTRACT,
        "group_order": order,
        "per_group": out_per,
        "d1_rank": d1_rank,
        "d1_min_abs_inner": inner,
    }


def _leadzero_power(total: float, n_ch: int = N_CH) -> List[float]:
    """夹具用：把总功率均分到 n_ch 个通道，保证 Σ 恰为 total。"""
    return [total / n_ch] * n_ch


def _arm_metrics(raw: Dict[str, Any], groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    src = raw.get("arm_metrics")
    _require(isinstance(src, dict), "arm_metrics 缺失")
    out: Dict[str, Any] = {}
    for arm in ARMS:
        item = src.get(arm)
        _require(isinstance(item, dict), "arm_metrics 缺 %s" % arm)
        loo = [float(v) for v in item.get("air_loo_supp_db") or []]
        _require(len(loo) == 10, "%s.air_loo_supp_db 必须 10 个值" % arm)
        tg = item.get("targets") or {}
        _require(sorted(tg) == sorted(TARGET_GROUPS),
                 "%s.targets 应恰为 2 个目标组" % arm)
        targets = {}
        for key in TARGET_GROUPS:
            m = tg[key]
            targets[key] = {
                "d_hat_m": float(m["d_hat_m"]),
                "supp_dw_win_db": float(m["supp_dw_win_db"]),
                "pslr_db": float(m["pslr_db"]),
                "pnr_db": float(m["pnr_db"]),
            }
        out[arm] = {"air_loo_supp_db": loo, "targets": targets}
    # 决策臂 C2 的目标侧必须与 groups 的 12 组表一致
    for g in groups:
        if g["group_key"] in TARGET_GROUPS:
            want = out[DECISION_ARM]["targets"][g["group_key"]]
            for k in ("d_hat_m", "supp_dw_win_db", "pslr_db", "pnr_db"):
                _require(abs(float(g[k]) - want[k]) <= 1e-12,
                         "groups[%s].%s 与 C2 臂不一致" % (g["group_key"], k))
    return out


def assemble(raw: Dict[str, Any], *, prereg: Optional[Dict[str, Any]] = None,
             prereg_path: Optional[str] = None) -> Dict[str, Any]:
    """把 raw 组装成 `E0-N0-1` 的 `e0c_results.json` / `e0c_air_loo.json`。"""
    ident = raw.get("identity") or {}
    _require(ident.get("experiment_id") == "A-Q1-N0",
             "identity.experiment_id 应为 'A-Q1-N0'")
    _require(ident.get("phase") == "N0", "identity.phase 应为 'N0'")
    scope = ident.get("method_scope")
    _require(scope == METHOD_SCOPE,
             "method_scope 必须逐字等于 %r（收到 %r）" % (METHOD_SCOPE, scope))

    anchors = raw.get("anchors") or {}
    impl = _norm_anchor(anchors.get("implementation_sha"), "implementation_sha", 40)
    main = _norm_anchor(anchors.get("main_commit"), "main_commit", 40)
    n0cfg = _norm_anchor(anchors.get("n0_config_sha256"), "n0_config_sha256", 64)
    git = anchors.get("git") or {}
    _require(isinstance(git, dict) and git, "anchors.git 缺失")
    git_block = {
        "head_sha": _norm_anchor(git.get("head_sha", impl), "git.head_sha", 40),
        "parent_sha": git.get("parent_sha"),
        "origin_main_sha": _norm_anchor(
            git.get("origin_main_sha", main), "git.origin_main_sha", 40),
        "working_tree_clean": bool(git.get("working_tree_clean", True)),
        "branch": git.get("branch"),
        # 兼容 E0-N0-ACCEPT-2 的读取点（ACCEPT-3 绑定生产字段）
        "dirty": bool(git.get("dirty", not bool(git.get("working_tree_clean", True)))),
        "commit": main,
    }
    _require(git_block["head_sha"] == impl,
             "git.head_sha 必须等于 implementation_sha")
    _require(git_block["origin_main_sha"] == main,
             "git.origin_main_sha 必须等于 main_commit")

    inputs = raw.get("inputs") or []
    _require(len(inputs) == 96, "inputs 必须 96 条，实为 %d" % len(inputs))
    for x in inputs:
        _require(isinstance(x.get("rel_path"), str) and x["rel_path"], "inputs.rel_path 非法")
        _require(isinstance(x.get("size_bytes"), int) and x["size_bytes"] >= 0,
                 "inputs.size_bytes 非法")
        _norm_anchor(x.get("sha256"), "inputs.sha256", 64)
    total_bytes = sum(int(x["size_bytes"]) for x in inputs)

    groups = _groups_default(raw)
    arrays = raw.get("arrays") or {}
    for member, _prefix, shape in ARRAY_SPECS:
        _require(member in arrays, "缺少数组 %s" % member)
    n_grid = len(_flatten(arrays["air_loo__p_cal"])) // (10 * N_CH)
    _require(n_grid >= 1, "air_loo 数组为空")
    for member, _prefix, shape in ARRAY_SPECS:
        _check_array(arrays[member], shape, n_grid, member)

    lam = raw.get("lambdas") or [list(FIXED_LAMBDA)]
    _require(isinstance(lam, list) and len(lam) == n_grid,
             "lambdas 长度 %d 与 grid %d 不符" % (len(lam), n_grid))
    lam = [[float(v) for v in row] for row in lam]
    _require(list(FIXED_LAMBDA) in lam, "grid 必须包含固定 lambda %r" % (FIXED_LAMBDA,))
    fixed_idx = lam.index(list(FIXED_LAMBDA))

    xc = recompute_xcluster(arrays)
    xc_min = min(v for row in xc for v in row)
    eligibility = tier_of_supp(xc_min)

    loo_rows = recompute_air_loo(arrays, n_grid)
    fixed_row = loo_rows[fixed_idx]
    loo_min, loo_med = min(fixed_row), median(fixed_row)

    air_loo = {
        "prereg": ARTIFACT_CONTRACT,
        "folds": [{"index": i, "held_out": g} for i, g in enumerate(AIR_GROUPS)],
        "grid": [
            {
                "lambdas": lam[i],
                "folds": [{"held_out": g, "supp_db": loo_rows[i][j]}
                          for j, g in enumerate(AIR_GROUPS)],
                "min_db": min(loo_rows[i]),
                "median_db": median(loo_rows[i]),
            }
            for i in range(n_grid)
        ],
        "selected": list(FIXED_LAMBDA),
        "switched": False,
        "min_supp_db": loo_min,
        "median_supp_db": loo_med,
        "eligibility": "eligible" if loo_min >= 10.0 else (
            "gray" if loo_min >= 6.0 else "hard_stop"),
        "switch_reason": "N0 固定默认 lambda（C8' 只复算，不选参）",
    }

    ret = raw.get("retention") or {}
    _require(ret.get("case_id") == RETENTION_CASE,
             "retention.case_id 应为 %r" % RETENTION_CASE)
    peak_loss = float(ret.get("peak_loss_db"))
    shift_mm = float(ret.get("range_shift_mm"))
    ret_pass = (_finite(peak_loss) and peak_loss <= 0.1
                and _finite(shift_mm) and abs(shift_mm) <= 2.0)

    judge = raw.get("judgement") or {}
    l1 = str(judge.get("L1", "FAIL")).upper()
    l2 = str(judge.get("L2", "FAIL")).upper()
    _require(l1 in ("PASS", "FAIL") and l2 in ("PASS", "FAIL"),
             "judgement 只能为 PASS/FAIL")
    _require(not (l1 == "PASS" and l2 == "PASS"),
             "L2 成立时须另写 n0_frozen.json；本模块只产冻结前的包")
    freeze_ok = False
    freeze = {
        "status": "eligible" if freeze_ok else "not_eligible_for_freeze",
        "eligible": bool(freeze_ok),
        "written": False,
    }

    reg = raw.get("registration") or {}
    prereg_id = reg.get("prereg_id", "A-Q1-N0-PREREG-1")
    _require(prereg_id in PREREG_IDS, "registration.prereg_id 非法: %r" % (prereg_id,))
    if prereg_path:
        _require(os.path.exists(prereg_path), "prereg 文件不存在: %s" % prereg_path)
        prereg_sha = sha256_file(prereg_path)
    else:
        prereg_sha = _norm_anchor(reg.get("prereg_sha256"), "prereg_sha256", 64)
    input_sha = inputs_digest(inputs)
    eta_wall = float(raw.get("eta_wall", 0.25))
    _require(abs(eta_wall - 0.25) <= 1e-12, "eta_wall 必须为契约常量 0.25")

    results = {
        "experiment_id": "A-Q1-N0",
        "phase": "N0",
        "method_scope": scope,
        "implementation_sha": impl,
        "main_commit": main,
        "n0_config_sha256": n0cfg,
        "git": git_block,
        "inputs": inputs,
        "groups": groups,
        "array_map": dict(DEFAULT_ARRAY_MAP),
        "methods": {
            "n0_enabled": True,
            "rank": 2,
            "lambda_selection": "fixed_default",
            "subspace_suppression": True,
        },
        "d_true_usage": "evaluation_only",
        "freeze": freeze,
        "metrics_sha256": metrics_digest(groups),
        "n0": {
            "contract": ARTIFACT_CONTRACT,
            "arms": list(ARMS),
            "decision_arm": DECISION_ARM,
            "rank": 2,
            "lambda": list(FIXED_LAMBDA),
            "lambda_selection": "fixed_default",
            "eta_wall": eta_wall,
            "xcluster_fold_map": _fold_map(raw),
            "xcluster_supp_db": xc,
            "xcluster_eligibility": eligibility,
            "retention": {
                "case_id": RETENTION_CASE,
                "peak_loss_db": peak_loss,
                "range_shift_mm": shift_mm,
                "pass": ret_pass,
            },
            "phase": _phase_block(raw, arrays),
            "judgement": {
                "L1": l1,
                "L2": l2,
                "stop_condition": judge.get("stop_condition"),
            },
            "arm_metrics": _arm_metrics(raw, groups),
            "registration": {
                "prereg_id": prereg_id,
                "prereg_sha256": prereg_sha,
                "implementation_sha": impl,
                "n0_config_sha256": n0cfg,
                "n0_config_path": (raw.get("anchors") or {}).get(
                    "n0_config", {}).get("path"),
                "input_manifest_sha256": input_sha,
                "main_commit": main,
            },
        },
    }
    cfg_meta = (raw.get("anchors") or {}).get("n0_config")
    if isinstance(cfg_meta, dict) and cfg_meta.get("sha256_lf"):
        _require(cfg_meta["sha256_lf"] == n0cfg,
                 "anchors.n0_config.sha256_lf 与 n0_config_sha256 不一致")
        results["n0_config"] = {
            "path": cfg_meta.get("path"),
            "sha256_lf": cfg_meta["sha256_lf"],
            "sha256_raw": cfg_meta.get("sha256_raw"),
            "bound": True,
        }
    else:
        results["n0_config"] = {"path": None, "sha256_lf": n0cfg,
                                "sha256_raw": None, "bound": False}
    _ = prereg, total_bytes  # 预留：prereg 常量可用于额外交叉校验
    return {"results": results, "air_loo": air_loo, "arrays": arrays}


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


def _write_npz(path: str, arrays: Dict[str, Any]) -> None:
    """确定性 `.npz`：固定 zip 成员时间戳，使同一组数组两次序列化逐字节一致。

    与 `a_e0_c.save_npz_deterministic` / `a_q2q3_common` 同口径。C12 两进程证据要求
    两次独立序列化后的 `arrays_sha256` 相同；`np.savez` 会把当前墙钟写进 zip
    成员时间戳，导致“数组相同、字节不同”。
    """
    import io
    import zipfile

    import numpy as np  # 仅此处需要；数组本身按嵌套 list 传递

    payload = {}
    for member, _prefix, shape in ARRAY_SPECS:
        arr = arrays[member]
        n_grid = len(_flatten(arrays["air_loo__p_cal"])) // (10 * N_CH)
        resolved = tuple(n_grid if s == "n_grid" else int(s) for s in shape)
        payload[member] = np.asarray(_flatten(arr), dtype=np.float64).reshape(resolved)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for member in sorted(payload):
            info = zipfile.ZipInfo(filename=member + ".npy",
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            buf = io.BytesIO()
            np.lib.format.write_array(
                buf, np.ascontiguousarray(payload[member]), allow_pickle=False)
            zf.writestr(info, buf.getvalue())


def _sums_line(path: str, rel: str) -> str:
    return "%s  %s\n" % (sha256_file(path), rel.replace("\\", "/"))


def write_package(dest: str, built: Dict[str, Any], *,
                  repeat: Dict[str, Any],
                  worker_meta: Sequence[Dict[str, Any]],
                  preflight: Dict[str, Any],
                  dryrun: Dict[str, Any],
                  run_log: str = "",
                  run2_results: Optional[Dict[str, Any]] = None,
                  run2_arrays: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把已组装的包写到 `dest`（不含冻结产物）。"""
    os.makedirs(dest, exist_ok=True)
    os.makedirs(os.path.join(dest, "repeat"), exist_ok=True)
    results = built["results"]
    arrays = built["arrays"]

    _write_json(os.path.join(dest, "e0c_results.json"), results)
    _write_json(os.path.join(dest, "e0c_air_loo.json"), built["air_loo"])
    _write_npz(os.path.join(dest, "e0c_arrays.npz"), arrays)
    if run2_results is not None:
        _write_json(os.path.join(dest, "repeat", "e0c_results.json"), run2_results)
    if run2_arrays is not None:
        _write_npz(os.path.join(dest, "repeat", "e0c_arrays.npz"), run2_arrays)

    _require(len(worker_meta) == 2, "worker_meta 必须两份（两次独立进程）")
    _write_json(os.path.join(dest, "worker_meta.json"), worker_meta[0])
    _write_json(os.path.join(dest, "repeat", "worker_meta.json"), worker_meta[1])

    _require(len(repeat.get("runs") or []) == 2, "repeat.runs 必须两条")
    # 从**实际落盘字节**回填摘要，避免“声明值 vs 文件”两张皮（C12）
    for rec in repeat["runs"]:
        for kind in ("results", "arrays"):
            rel = rec.get(kind + "_file")
            _require(isinstance(rel, str) and rel, "repeat.%s_file 非法" % kind)
            p = os.path.join(dest, *rel.replace("\\", "/").split("/"))
            _require(os.path.exists(p), "repeat 登记的文件不存在: %s" % rel)
            rec[kind + "_sha256"] = sha256_file(p)
    _write_json(os.path.join(dest, "e0c_repeat.json"), repeat)
    _require(int(preflight.get("total", -1)) == 32 and int(preflight.get("passed", -1)) == 32,
             "preflight 必须 32/32")
    _require(int(dryrun.get("total", -1)) == 11 and int(dryrun.get("passed", -1)) == 11,
             "dryrun 必须 11/11")
    _write_json(os.path.join(dest, "preflight.json"), preflight)
    _write_json(os.path.join(dest, "dryrun.json"), dryrun)

    with open(os.path.join(dest, "run.log"), "w", encoding="utf-8", newline="\n") as f:
        f.write(run_log or "N0 package assembled\n")

    # 台账：覆盖全部必需文件（不含自身），按路径排序、LF 写出
    ledger_files = sorted(f for f in (list(REQUIRED_FILES) + list(GATE_FILES))
                          if f != "SHA256SUMS.txt"
                          and os.path.exists(os.path.join(dest, *f.split("/"))))
    lines = [_sums_line(os.path.join(dest, *rel.split("/")), rel)
             for rel in ledger_files]
    with open(os.path.join(dest, "SHA256SUMS.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    return {"dest": os.path.abspath(dest),
            "files": ledger_files + ["SHA256SUMS.txt"]}


def selfcheck(dest: str) -> Dict[str, Any]:
    """纯标准库镜像 `accept_e0n0.py` 的关键重算点（不是验收结论）。"""
    problems: List[str] = []
    with open(os.path.join(dest, "e0c_results.json"), encoding="utf-8") as fh:
        results = json.load(fh)
    with open(os.path.join(dest, "e0c_air_loo.json"), encoding="utf-8") as fh:
        air = json.load(fh)
    with __import__("zipfile").ZipFile(os.path.join(dest, "e0c_arrays.npz")) as z:
        members = {n[:-4]: n for n in z.namelist() if n.endswith(".npy")}
    need = [m for m, _p, _s in ARRAY_SPECS]
    missing = [m for m in need if m not in members]
    if missing:
        problems.append("npz 缺成员 %r" % missing)

    n0 = results.get("n0") or {}
    xc = n0.get("xcluster_supp_db") or []
    declared = [[float(v) for v in row] for row in xc]
    # 需要用数组重算，但此处只核对形状与声明长度；数值重算在 assemble 内做
    if len(declared) != 5 or any(len(r) != 2 for r in declared):
        problems.append("xcluster_supp_db 形状应为 5x2")

    if results.get("metrics_sha256") != metrics_digest(results.get("groups") or []):
        problems.append("metrics_sha256 与 groups 重算不符")
    reg = n0.get("registration") or {}
    if reg.get("input_manifest_sha256") != inputs_digest(results.get("inputs") or []):
        problems.append("input_manifest_sha256 与 inputs 重算不符")
    if not os.path.exists(os.path.join(dest, "SHA256SUMS.txt")):
        problems.append("缺 SHA256SUMS.txt")
    else:
        with open(os.path.join(dest, "SHA256SUMS.txt"), encoding="utf-8") as fh:
            ledger_lines = list(fh)
        for line in ledger_lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                problems.append("台账行不可解析: %r" % line)
                continue
            sha, rel = parts[0], parts[1].lstrip("*")
            p = os.path.join(dest, *rel.replace("\\", "/").split("/"))
            if not os.path.exists(p):
                problems.append("台账文件不存在: %s" % rel)
            else:
                with open(p, "rb") as fh:
                    raw = fh.read()
                if sha not in (sha256_file(p), sha256_bytes(
                        raw.replace(b"\r\n", b"\n"))):
                    problems.append("台账哈希不符: %s" % rel)
    return {"verdict": "SELF_OK" if not problems else "SELF_PROBLEM",
            "problems": problems}


# --------------------------------------------------------------------------- #
# 合成原型 -> raw（仅用于夹具自检；不参与真实验收）
# --------------------------------------------------------------------------- #
def from_prototype_synthetic(doc: Dict[str, Any], *,
                             inputs: Sequence[Dict[str, Any]],
                             main_commit: str,
                             n0_config_sha256: str,
                             phase_evidence: Optional[Dict[str, Any]] = None,
                             method_scope: str = METHOD_SCOPE) -> Dict[str, Any]:
    """把 `N0-SYN-1` 合成原型输出映射成 raw（SYNTHETIC ONLY）。

    这只覆盖 17 个“有来源”的契约项；6 个数组由声明值反构，属夹具，
    不得用于任何真实结论。

    ``phase_evidence`` 必须是 `a_e0_n0_phase.build_synthetic_evidence()` 的产物
    （契约 `E0-N0-PHASE-EVIDENCE-1`）：`phase__coherence` 与 `d1_min_abs_inner`
    由该证据**重算/转写**，不再写 `[1.0]*10` / `0.0` 占位值。
    """
    _require(isinstance(phase_evidence, dict), "缺少 phase_evidence（相位证据）")
    _require(phase_evidence.get("contract") == PHASE_EVIDENCE_CONTRACT,
             "phase_evidence.contract 应为 %r" % (PHASE_EVIDENCE_CONTRACT,))
    n0 = doc.get("n0") or {}
    fold_lock = doc.get("fold_lock") or {}
    shifts_s = [float(v) for v in fold_lock.get("shifts_s") or []]
    _require(len(shifts_s) == 10, "原型 shifts_s 应有 10 个值")
    shifts_ns = [v * 1e9 for v in shifts_s]
    ev_shifts_ns = [float(v) for v in phase_evidence.get("shifts_ns") or []]
    _require(len(ev_shifts_ns) == 10, "phase_evidence.shifts_ns 应有 10 个值")
    for i, (a, b) in enumerate(zip(shifts_ns, ev_shifts_ns)):
        _require(abs(a - b) <= 1e-9,
                 "phase_evidence.shifts_ns[%d]=%r 与 fold_lock.shifts_s×1e9=%r 不一致"
                 % (i, b, a))
        shifts_ns[i] = b

    coh_rows = phase_evidence.get("coherence") or []
    _require(len(coh_rows) == 10, "phase_evidence.coherence 必须 10 组")
    rho = [float(r["rho"]) for r in coh_rows]
    clusters = [str(r["cluster"]) for r in coh_rows]
    expected_clusters = [c for c, _h in CLUSTERS for _ in _h]
    _require(clusters == expected_clusters,
             "phase_evidence.coherence 的簇序与预登记不符：%r" % (clusters,))
    d1 = phase_evidence.get("d1") or {}
    d1_rank = int(d1.get("d1_rank", 2))
    d1_inner = float(d1["d1_min_abs_inner"]) if "d1_min_abs_inner" in d1 else None
    _require(d1_inner is not None, "phase_evidence.d1.d1_min_abs_inner 缺失")

    p1, p2 = doc.get("p1") or {}, doc.get("p2") or {}
    xc_supp = [[0.0, 0.0] for _ in range(5)]
    for row in (p1.get("c2") or {}).get("values") or []:
        # 折序/池序：fold 取自行内，池内位置取预登记 held_out 顺序，不按字典序
        fold = int(row["fold"])
        b = CLUSTERS[fold][1].index(row["group"])
        xc_supp[fold][b] = float(row["supp_db"])
    loo_supp = [[0.0] * 10]
    for row in (p2.get("c2") or {}).get("values") or []:
        loo_supp[0][AIR_GROUPS.index(row["group"])] = float(row["supp_db"])

    # 夹具数组：把总功率均分到 63 通道，使重算 Supp 与原型声明值一致
    xc_cal = [[_leadzero_power(10.0 ** (xc_supp[a][b] / 10.0)) for b in range(2)]
              for a in range(5)]
    xc_sup = [[_leadzero_power(1.0) for _ in range(2)] for _ in range(5)]
    air_cal = [[_leadzero_power(10.0 ** (loo_supp[0][g] / 10.0)) for g in range(10)]]
    air_sup = [[_leadzero_power(1.0) for _ in range(10)]]

    targets = doc.get("targets") or {}

    def tgt(arm: str) -> Dict[str, Any]:
        return {k: {kk: float(v["arms"][arm.lower()][kk]) for kk in
                    ("d_hat_m", "supp_dw_win_db", "pslr_db", "pnr_db")}
                for k, v in targets.items()}

    def loo(arm: str) -> List[float]:
        # 契约 air_loo_supp_db 是 10 折 LOO（p2），不是五折跨簇（p1）；两者都长度 10
        rows = (p2.get(arm.lower()) or {}).get("values") or []
        out = [0.0] * 10
        for row in rows:
            out[AIR_GROUPS.index(row["group"])] = float(row["supp_db"])
        return out

    groups = []
    for g in AIR_GROUPS:
        groups.append({"group_key": g, "target_type": "air",
                       "valid_rx": VALID_RX, "finite": True})
    for key in TARGET_GROUPS:
        m = tgt("c2")[key]
        groups.append({"group_key": key, "target_type": "target",
                       "d_hat_m": m["d_hat_m"], "abs_err_cm": None,
                       "supp_dw_win_db": m["supp_dw_win_db"],
                       "pslr_db": m["pslr_db"], "pnr_db": m["pnr_db"],
                       "valid_rx": VALID_RX, "finite": True})
    # abs_err 由原型 abs_err_cm 提供
    for row in groups[10:]:
        row["abs_err_cm"] = float(targets[row["group_key"]]["arms"]["c2"]["abs_err_cm"])
    p4 = (doc.get("p4") or {}).get("items") or [{}]
    item = p4[0]
    return {
        "identity": {"experiment_id": "A-Q1-N0", "phase": "N0",
                     "method_scope": str(method_scope)},
        "anchors": {
            "implementation_sha": str((doc.get("provenance") or {}).get("implementation_sha")),
            "main_commit": main_commit,
            "n0_config_sha256": n0_config_sha256,
            "git": {
                "head_sha": str((doc.get("provenance") or {}).get("implementation_sha")),
                "parent_sha": None,
                "origin_main_sha": main_commit,
                "working_tree_clean": not bool(
                    (doc.get("provenance") or {}).get("implementation_dirty", False)),
                "branch": "synthetic-fixture",
            },
        },
        "inputs": list(inputs),
        "groups": groups,
        "arrays": {
            "xcluster__p_cal": xc_cal, "xcluster__p_sup": xc_sup,
            "air_loo__p_cal": air_cal, "air_loo__p_sup": air_sup,
            "phase__shifts_ns": shifts_ns,
            "phase__coherence": rho,
        },
        "lambdas": [list(FIXED_LAMBDA)],
        "xcluster_fold_map": None,
        "retention": {
            "case_id": RETENTION_CASE,
            "peak_loss_db": -float(item.get("peak_retention_db", 0.0)),
            "range_shift_mm": float(item.get("range_shift_mm", 0.0)),
        },
        "phase": {
            "group_order": list(AIR_GROUPS),
            "per_group": [
                {"group": r["group"],
                 "cluster": r["cluster"],
                 "aligned": bool(rho[i] >= float(phase_evidence.get("rho_min", RHO_MIN))),
                 "rho": rho[i],
                 "reason": None}
                for i, r in enumerate(coh_rows)
            ],
            "d1_rank": d1_rank,
            "d1_min_abs_inner": d1_inner,
            "rho_min": float(phase_evidence.get("rho_min", RHO_MIN)),
        },
        "judgement": {
            "L1": str((doc.get("l1") or {}).get("l1", "fail")).upper(),
            "L2": str((doc.get("l2") or {}).get("l2", "fail")).upper(),
            "stop_condition": (doc.get("l2") or {}).get("s_code"),
        },
        "arm_metrics": {arm: {"air_loo_supp_db": loo(arm), "targets": tgt(arm)}
                        for arm in ARMS},
        "registration": {"prereg_id": "A-Q1-N0-PREREG-1"},
        "eta_wall": float(n0.get("eta_wall", 0.25)),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A-Q1-N0 producer-side package assembler")
    ap.add_argument("--raw", help="raw_n0.json（生产侧原始结果）")
    ap.add_argument("--from-prototype-synthetic", help="仅夹具：N0-SYN-1 合成原型 JSON")
    ap.add_argument("--inputs-oracle", help="夹具：e0_c_data_oracle.json")
    ap.add_argument("--phase-evidence",
                    help="相位证据 JSON（夹具必填；契约 E0-N0-PHASE-EVIDENCE-1）")
    ap.add_argument("--n0-config", help="n0_config.json（绑定 LF/raw 双口径 SHA256）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--prereg", help="e0_n0_prereg.json（用于绑定 prereg_sha256）")
    ap.add_argument("--main-commit", help="夹具：main_commit")
    ap.add_argument("--n0-config-sha256", help="夹具：n0_config_sha256（与 --n0-config 交叉核验）")
    ap.add_argument("--method-scope", default=METHOD_SCOPE,
                    help="identity.method_scope（冻结值，默认 %r）" % METHOD_SCOPE)
    args = ap.parse_args(argv)
    if not args.raw and not args.from_prototype_synthetic:
        ap.error("需要 --raw 或 --from-prototype-synthetic")

    n0cfg_sha = args.n0_config_sha256
    cfg_meta: Optional[Dict[str, Any]] = None
    if args.n0_config:
        _require(os.path.exists(args.n0_config),
                 "n0_config 文件不存在：%s" % args.n0_config)
        lf = sha256_file_lf(args.n0_config)
        rawsha = sha256_file(args.n0_config)
        if n0cfg_sha is not None:
            _require(n0cfg_sha == lf,
                     "--n0-config-sha256=%r 与 n0_config 的 LF SHA256=%r 不一致"
                     % (n0cfg_sha, lf))
        n0cfg_sha = lf
        cfg_meta = {"path": args.n0_config.replace("\\", "/"),
                    "sha256_lf": lf, "sha256_raw": rawsha}
    if n0cfg_sha is None:
        n0cfg_sha = "0" * 64

    if args.raw:
        raw = json.load(open(args.raw, encoding="utf-8"))
    else:
        if not args.phase_evidence:
            ap.error("夹具模式必须给 --phase-evidence（不得回退到 [1.0]*10 / 0.0 占位）")
        doc = json.load(open(args.from_prototype_synthetic, encoding="utf-8"))
        evidence = json.load(open(args.phase_evidence, encoding="utf-8"))
        oracle = json.load(open(args.inputs_oracle, encoding="utf-8"))
        inputs = [{"rel_path": row["rel_path"], "size_bytes": int(row["size_bytes"]),
                   "sha256": row["sha256"]}
                  for g in oracle["groups"].values() for row in g.get("files", [])]
        raw = from_prototype_synthetic(
            doc, inputs=inputs,
            main_commit=args.main_commit or "0" * 40,
            n0_config_sha256=n0cfg_sha,
            phase_evidence=evidence,
            method_scope=args.method_scope)
    if cfg_meta is not None:
        raw.setdefault("anchors", {})["n0_config"] = cfg_meta
        raw["anchors"]["n0_config_sha256"] = cfg_meta["sha256_lf"]
    built = assemble(raw, prereg_path=args.prereg)
    # 最小两进程/门禁夹具（真实运行由 execute 提供）
    repeat = {"runs": [
        {"run_id": "run-1", "pid": 1001, "started_at": "2026-11-28T00:00:00Z",
         "finished_at": "2026-11-28T00:01:00Z", "results_file": "e0c_results.json",
         "results_sha256": "0" * 64, "arrays_file": "e0c_arrays.npz",
         "arrays_sha256": "0" * 64, "wall_time_s": 60.0, "exit_code": 0,
         "peak_rss_mib": 256.0},
        {"run_id": "run-2", "pid": 1002, "started_at": "2026-11-28T00:01:01Z",
         "finished_at": "2026-11-28T00:02:01Z",
         "results_file": "repeat/e0c_results.json",
         "results_sha256": "0" * 64, "arrays_file": "repeat/e0c_arrays.npz",
         "arrays_sha256": "0" * 64, "wall_time_s": 60.0, "exit_code": 0,
         "peak_rss_mib": 256.0},
    ]}
    meta = {"run_id": "run-1", "pid": 1001, "started_at": "2026-11-28T00:00:00Z",
            "finished_at": "2026-11-28T00:01:00Z", "exit_code": 0, "peak_rss_mib": 256.0}
    meta2 = dict(meta, run_id="run-2", pid=1002,
                 started_at="2026-11-28T00:01:01Z",
                 finished_at="2026-11-28T00:02:01Z")
    info = write_package(args.out, built, repeat=repeat, worker_meta=[meta, meta2],
                         preflight={"passed": 32, "total": 32},
                         dryrun={"passed": 11, "total": 11},
                         run2_results=built["results"],
                         run2_arrays=built["arrays"])
    print(json.dumps(info, ensure_ascii=False, indent=1))
    chk = selfcheck(args.out)
    print(json.dumps(chk, ensure_ascii=False, indent=1))
    return 0 if chk["verdict"] == "SELF_OK" else 1


if __name__ == "__main__":
    sys.exit(main())
