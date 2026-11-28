#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1-E0-C 放行前自检（仅元数据，不解析任何 ``.dat`` 采样）。

本工具回答一个问题：**在正式读取 E0-C 真实信号之前，该锁的东西是否仍然锁着、
该在的数据是否齐全、E0-S 前置是否仍然成立？**

- 只读：``config.json`` / ``PLAN.md`` / ``coordination/A_Q1_SPLIT.json`` /
  ``E0-S`` 结果 JSON / R0 清单 CSV / 白名单 96 个 ``.dat`` 的字节摘要。
- 不读：任何包头、任何采样语义、任何检验组、``附件3``、B 题数据。
- 不写：除 ``--out`` 指定的 JSON 之外不写任何文件；不修改原件。
- **读前路径校验**：任何 ``lstat``/``stat``/``open`` 之前先做词法归属、重解析点
  （符号链接/目录联接）与 ``realpath`` 包含性检查，见 ``guard_group_dir`` /
  ``guard_dat_path``；未通过的条目记录为问题且**绝不打开**。

口径（与主管线一致）：

- ``config.json`` 与 ``A_Q1_SPLIT.json`` 的锚点是 **LF 归一化 SHA256**（工作区受
  ``core.autocrlf`` 影响可能是 CRLF）；``PLAN.md`` 锚点是原始字节 SHA256（``.md``
  已由 ``.gitattributes`` 固定为 LF）。
- R0 清单总体 SHA256 的实测口径是：把 ``sha256 + 两个空格 + rel_path`` 按
  **CSV 行序**以 ``\\n`` 连接、末尾补 ``\\n``，再取 SHA256（见
  ``manifest_overall_sha256`` 的说明）。
- ``preconditions_pass`` 只表示**放行前条件自检通过**，不表示 E0-C 已放行；
  ``execution_ready`` 另算（还要求 ``solutions/A/a_e0_c.py`` 已交付）。

用法::

    python solutions/A/e0c_preflight.py --out experiments/A/A-Q1-E0/e0c/preflight.json
    python solutions/A/e0c_preflight.py                      # 只打印到 stdout

退出码：``0`` = 放行前条件全部通过；``1`` = 任一条件失败；``2`` = 用法/环境错误。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

CONTRACT_VERSION = "E0C-PREFLIGHT-2"
SCOPE = "metadata_only_no_signal_parse"

# Windows 重解析点标志（符号链接、目录联接、挂载点共用这一属性）。
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# ---------------------------------------------------------------- 版本锚点
APPROVED_ANCHORS: Dict[str, Any] = {
    # A-Q1-E0 规划批复（codex，2026-11-28）
    "config_sha256_lf": "8fb6821fa3335ef748e16ad2f5b5b8fc818c13cbe9d3315377faf48d5e40e06a",
    "plan_sha256": "073511c0b6ae44dbc90d228b7d79c2de9d0687d4e65949494803b19f24595a88",
    # A-Q1-SPLIT0 冻结（LF blob）
    "split_sha256_lf": "d623da4ea186f372f2be094121c202c55dae0e236f4683005ab88d220a248b3a",
    # R0 清单
    "dat_manifest_overall_sha256": "86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06",
    # E0-S 登记（实现 652fc53 / 结果 5d14b7b / 独立验收 P1–P17）
    "e0s_implementation_sha": "652fc532fb7046645f570f8a046ea38e30f54f50",
    "e0s_arrays_file_sha256": "27bea969f27589bca74031e02b88e163fc5865190a9f555dd4cecd97ee972df5",
    "e0s_param_table_file_sha256": "93ff023efeed5233d0fc152fac95701e544a532cd3035595e742f8df115b272d",
    "e0s_result_commit": "5d14b7ba4f5b3f3b692a10ba94588ba23ffa85d6",
}

REQUIRED_AIR_GROUPS: Tuple[str, ...] = tuple("空场数据/data%d" % i for i in range(1, 11))
REQUIRED_TARGETS: Tuple[Tuple[str, str, float, str], ...] = (
    ("墙体数据/data1-42cm", "wall", 42.0, "wall_cal"),
    ("金属板数据/data1-69cm", "metal", 69.0, "metal_cal"),
)
E0S_CASES: Tuple[Tuple[str, Optional[int]], ...] = (
    ("E0-S1", 2),
    ("E0-S2@0.42", 63),
    ("E0-S2@0.69", 63),
)
DATA_SUBDIR = Path("附件") / "附件2-测距数据"
A_ROOT_DEFAULT = "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题"
RESULTS_REL = Path("experiments/A/A-Q1-E0/s1s2/results")
_ROW_RE = re.compile(r"^(?P<prefix>.+)_(?P<row>[0-7])\.dat$", re.IGNORECASE)
_CHUNK = 1 << 20


# ---------------------------------------------------------------- 基础工具
def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, opened: Optional[List[str]] = None) -> str:
    """原始字节 SHA256。``opened`` 用于登记本进程实际打开过的文件。"""
    digest = hashlib.sha256()
    if opened is not None:
        opened.append(str(path))
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_lf(path: Path) -> str:
    """CRLF→LF 归一化后的 SHA256；锚点按此口径。"""
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def rel_to(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------- 清单
def manifest_rows(manifest_path: Path) -> List[Dict[str, Any]]:
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        rel = str(row.get("rel_path", "")).replace("\\", "/")
        cleaned.append(
            {
                "rel_path": rel,
                "size_bytes": int(row["size_bytes"]),
                "sha256": str(row["sha256"]).strip().lower(),
            }
        )
    return cleaned


def manifest_overall_sha256(rows: Sequence[Dict[str, Any]]) -> str:
    """按 R0 记录的**清单行序**计算总体 SHA256。

    注：``recon/README.md`` 写的是“按相对路径排序”，但实测能复现锚点
    ``86305548…`` 的口径是 **CSV 行序**（文件系统扫描顺序，并非 ``rel_path``
    字典序；两者不同）。本函数按可复现口径实现，并在结果里标注该文档差异。
    """
    lines = ["%s  %s" % (r["sha256"], r["rel_path"]) for r in rows]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return sha256_bytes(payload)


def split_qualified(split: Dict[str, Any]) -> Dict[str, List[str]]:
    """把冻结拆分里的裸组名按数据集限定为 ``group_key``。

    ``A_Q1_SPLIT.json`` 只存 ``data14-48cm`` 这类裸名，墙体和金属板都有同名
    目录（如 ``data14-48cm``）。必须按数据集限定后比较，否则会把两个不同的
    物理组误判为重复。
    """
    datasets = {
        "wall_cal": "墙体数据",
        "wall_test": "墙体数据",
        "metal_cal": "金属板数据",
        "metal_test": "金属板数据",
    }
    groups = split.get("groups", {})
    return {
        fold: ["%s/%s" % (datasets[fold], name) for name in groups.get(fold, [])]
        for fold in datasets
    }


def _cm_of(group_key: str) -> Optional[int]:
    match = re.search(r"-(\d+)cm$", group_key)
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------- 检查器
class Checker:
    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []

    def add(
        self,
        cid: str,
        group: str,
        passed: bool,
        detail: str,
        **extra: Any,
    ) -> None:
        record: Dict[str, Any] = {
            "id": cid,
            "group": group,
            "passed": bool(passed),
            "detail": detail,
        }
        record.update(extra)
        self.checks.append(record)

    @property
    def failed_ids(self) -> List[str]:
        return [c["id"] for c in self.checks if not c["passed"]]


# ---------------------------------------------------------------- 读前路径校验
class PathGuardError(RuntimeError):
    """待读路径未通过白名单归属 / 重解析点 / 实际路径包含性校验。"""


def _is_reparse_point(st: "os.stat_result") -> bool:
    """判断一个 ``lstat`` 结果是否符号链接或其它重解析点。

    Windows 上目录联接（junction）不是 ``stat.S_ISLNK``，但一定带
    ``FILE_ATTRIBUTE_REPARSE_POINT``；仅查 ``islink()`` 会漏掉它。
    """
    attrs = getattr(st, "st_file_attributes", None)
    if attrs is not None:
        return bool(int(attrs) & FILE_ATTRIBUTE_REPARSE_POINT)
    return stat.S_ISLNK(st.st_mode)


def _norm(path: "os.PathLike[str]") -> str:
    """仅做词法规范化（不触碰文件系统），用于父子目录比较。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _check_no_reparse(
    path: Path, lstat: "Any" = None
) -> "os.stat_result":
    """对单个路径做 ``lstat`` 并拒绝重解析点；不跟随链接。"""
    if lstat is None:
        lstat = os.lstat
    try:
        st = lstat(str(path))
    except OSError as exc:
        raise PathGuardError("无法 lstat：%s（%s）" % (path, exc)) from exc
    if _is_reparse_point(st):
        raise PathGuardError("是符号链接/重解析点，拒绝跟随：%s" % path)
    return st


def guard_group_dir(
    group_dir: "os.PathLike[str]",
    data_root: "os.PathLike[str]",
    *,
    lstat: "Any" = None,
    realpath: "Any" = None,
) -> Path:
    """在任何 ``stat``/``iterdir``/``open`` 之前校验一个白名单组目录。

    步骤（顺序即安全边界）：

    1. **词法归属**：``group_dir`` 必须位于 ``data_root`` 之下（纯字符串比较，
       不访问文件系统）；
    2. **逐级反重解析点**：从 ``data_root`` 到 ``group_dir`` 的每一级目录都
       ``lstat`` 一次，任一级是符号链接/目录联接就拒绝——否则后续对孩子节点的
       访问会先穿过它到达白名单之外；
    3. **真实路径包含性**：``realpath(group_dir)`` 必须仍在
       ``realpath(data_root)`` 之内。

    返回经过校验的**真实目录路径**（后续 ``iterdir`` 只用它）。
    """
    root_lex = Path(_norm(data_root))
    gdir_lex = Path(_norm(group_dir))
    if not _is_within(gdir_lex, root_lex) or gdir_lex == root_lex:
        raise PathGuardError("组目录不在数据根之下：%s ∉ %s" % (gdir_lex, root_lex))

    if realpath is None:
        realpath = os.path.realpath
    current = root_lex
    for part in gdir_lex.relative_to(root_lex).parts:
        current = current / part
        st = _check_no_reparse(current, lstat)
        if not stat.S_ISDIR(st.st_mode):
            raise PathGuardError("路径组件不是目录：%s" % current)

    real_gdir = Path(realpath(str(gdir_lex)))
    real_root = Path(realpath(str(root_lex)))
    if not _is_within(real_gdir, real_root) or real_gdir == real_root:
        raise PathGuardError(
            "组目录实际路径越出数据根：%s ∉ %s" % (real_gdir, real_root)
        )
    return real_gdir


def guard_dat_path(
    entry: "os.PathLike[str]",
    group_real_dir: "os.PathLike[str]",
    data_root_real: "os.PathLike[str]",
    *,
    lstat: "Any" = None,
    realpath: "Any" = None,
) -> Path:
    """在 ``stat``/``open`` 之前校验一个待读 ``.dat`` 条目。

    与 ``guard_group_dir`` 同序：词法父目录 → ``lstat`` 反重解析点 → 普通文件
    → ``realpath`` 同时落在组真实目录与数据根真实路径内。返回真实路径；调用方
    只应 ``stat``/``open`` 这个返回值。
    """
    entry_lex = Path(_norm(entry))
    group_lex = Path(_norm(group_real_dir))
    root_real = Path(_norm(data_root_real))

    if _norm(entry_lex.parent) != _norm(group_lex):
        raise PathGuardError(
            "%s 不是白名单组目录 %s 的直接子项" % (entry_lex, group_lex)
        )
    st = _check_no_reparse(entry_lex, lstat)
    if not stat.S_ISREG(st.st_mode):
        raise PathGuardError("不是普通文件：%s" % entry_lex)

    if realpath is None:
        realpath = os.path.realpath
    real = Path(realpath(str(entry_lex)))
    if not _is_within(real, group_lex) or not _is_within(real, root_real):
        raise PathGuardError(
            "实际路径越出白名单（组=%s，根=%s）：%s -> %s"
            % (group_lex, root_real, entry_lex, real)
        )
    return real


# ---------------------------------------------------------------- 白名单
def expected_targets(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(cfg["pilot_datasets"]["phase_c_calibration_pilot"]["target_groups"])


def expected_air_groups(cfg: Dict[str, Any]) -> List[str]:
    return list(cfg["pilot_datasets"]["phase_c_calibration_pilot"]["air_groups"])


def check_allow_list(cfg: Dict[str, Any], split: Dict[str, Any], ck: Checker) -> None:
    air = expected_air_groups(cfg)
    targets = expected_targets(cfg)

    exp_air = list(REQUIRED_AIR_GROUPS)
    ck.add(
        "whitelist.air_groups",
        "whitelist",
        air == exp_air,
        "config.json 空场组 = data1..data10" if air == exp_air else "空场组与冻结白名单不一致",
        actual=air,
        expected=exp_air,
    )

    actual_targets = [[t.get("group"), t.get("target_type"), t.get("d_true_cm"), t.get("in_split")] for t in targets]
    exp_targets = [list(x) for x in REQUIRED_TARGETS]
    ck.add(
        "whitelist.target_groups",
        "whitelist",
        actual_targets == exp_targets,
        "两组校准目标与 PLAN/config 一致" if actual_targets == exp_targets else "校准目标组与冻结口径不一致",
        actual=actual_targets,
        expected=exp_targets,
    )

    allow = set(air) | {str(t.get("group")) for t in targets}
    folds = split_qualified(split)
    wall_test = set(folds["wall_test"])
    metal_test = set(folds["metal_test"])
    wall_cal = set(folds["wall_cal"])
    metal_cal = set(folds["metal_cal"])
    forbidden = wall_test | metal_test
    leak = sorted(allow & forbidden)
    ck.add(
        "whitelist.no_test_groups",
        "whitelist",
        not leak,
        "白名单与 wall_test/metal_test 无交集" if not leak else "白名单混入检验组",
        leaked=leak,
    )

    # 校准目标必须属于对应校准折
    label_ok = True
    label_issues: List[str] = []
    for t in targets:
        g, kind = str(t.get("group")), str(t.get("target_type"))
        pool = wall_cal if kind == "wall" else metal_cal if kind == "metal" else set()
        if g not in pool:
            label_ok = False
            label_issues.append("%s 不在 %s_cal" % (g, kind))
    ck.add(
        "whitelist.cal_labels",
        "whitelist",
        label_ok,
        "两组校准目标均属对应 calibration 折" if label_ok else "; ".join(label_issues),
    )

    e0t = {str(t.get("group")) for t in cfg["pilot_datasets"]["phase_t_holdout_single_shot_eval"]["target_groups"]}
    untouched = forbidden - e0t
    extrapolation = {
        g for g in untouched
        if (g.startswith("墙体数据/") and (_cm_of(g) or 0) > 106)
        or (g.startswith("金属板数据/") and (_cm_of(g) or 0) > 91)
    }
    interp_untouched = untouched - extrapolation
    declared = int(cfg["pilot_datasets"]["phase_t_holdout_single_shot_eval"].get("untouched_remaining_holdout_groups_count", -1))
    ok = (
        len(forbidden) == 20
        and len(untouched) == 18
        and len(extrapolation) == 2
        and len(interp_untouched) == 16
        and declared == 16
    )
    ck.add(
        "whitelist.untouched_count",
        "whitelist",
        ok,
        "20 个检验组；E0-T 取 2 组后剩 18 组未触碰，其中 2 组外推（121cm/99cm）、16 组内插；config 的 16 指内插口径",
        test_groups=len(forbidden),
        untouched=len(untouched),
        extrapolation=sorted(extrapolation),
        interpolation_untouched=len(interp_untouched),
        declared=declared,
    )
    ck.add(
        "whitelist.size",
        "whitelist",
        len(allow) == 12,
        "白名单共 12 组（10 空场 + 2 校准目标）",
        groups=len(allow),
    )


def check_split(split: Dict[str, Any], ck: Checker) -> None:
    folds = split_qualified(split)
    names = ("wall_cal", "wall_test", "metal_cal", "metal_test")
    sizes = {n: len(folds.get(n, [])) for n in names}
    ck.add(
        "split.sizes",
        "split",
        all(sizes[n] == 10 for n in names),
        "四个折各 10 组",
        sizes=sizes,
    )
    sets = [set(folds.get(n, [])) for n in names]
    pairwise = all(not (sets[i] & sets[j]) for i in range(4) for j in range(i + 1, 4))
    union = set().union(*sets)
    ck.add(
        "split.partition",
        "split",
        pairwise and len(union) == 40,
        "按数据集限定后四折互不相交且并集 40 组" if pairwise and len(union) == 40 else "四折存在交集或并集不是 40 组",
        pairwise_disjoint=pairwise,
        union_size=len(union),
        note="裸名 data14-48cm 同时出现在墙体与金属板（两个不同物理组），必须按数据集限定",
    )
    ck.add(
        "split.status_frozen",
        "split",
        split.get("status") == "frozen" and split.get("approval_id") == "A-Q1-SPLIT0",
        "A-Q1-SPLIT0 冻结状态未变",
        status=split.get("status"),
        approval_id=split.get("approval_id"),
    )


def check_anchor_files(repo: Path, ck: Checker) -> Dict[str, Any]:
    anchors: Dict[str, Any] = {}
    for name, rel, lf in (
        ("config", "experiments/A/A-Q1-E0/config.json", True),
        ("plan", "experiments/A/A-Q1-E0/PLAN.md", False),
        ("split", "coordination/A_Q1_SPLIT.json", True),
    ):
        path = repo / rel
        if not path.is_file():
            ck.add("anchor.%s_present" % name, "anchors", False, "缺少 %s" % rel)
            continue
        actual = sha256_file_lf(path) if lf else sha256_file(path)
        key = "%s_sha256_lf" % name if lf else "%s_sha256" % name
        expected = APPROVED_ANCHORS[key]
        anchors[key] = actual
        anchors[key + "_expected"] = expected
        ck.add(
            "anchor.%s" % name,
            "anchors",
            actual == expected,
            "%s 锚点匹配（%s…）" % (rel, actual[:12]) if actual == expected else "%s 锚点不匹配：%s… ≠ %s…" % (rel, actual[:12], expected[:12]),
            actual=actual,
            expected=expected,
        )
    return anchors


def check_config_meta(cfg: Dict[str, Any], ck: Checker) -> None:
    ok = (
        cfg.get("experiment_id") == "A-Q1-E0"
        and int(cfg.get("schema_version", -1)) == 3
    )
    ck.add("config.identity", "config", ok, "experiment_id=A-Q1-E0, schema_version=3",
           experiment_id=cfg.get("experiment_id"), schema_version=cfg.get("schema_version"))

    classic = cfg.get("methods_classic_baseline_only", {})
    dw = classic.get("direct_wave_suppression", {})
    cal = classic.get("calibration", {})
    rng = classic.get("ranging", {})
    ok = (
        classic.get("n0_improvements_enabled") is False
        and dw.get("alpha_mode") == "fixed_1.0"
        and float(dw.get("alpha_fixed_value", 0.0)) == 1.0
        and dw.get("alpha_fitting_in_this_pilot") is False
        and cal.get("freeze_before_holdout") is True
        and rng.get("primary_statistic") == "P_norm_eff"
    )
    ck.add(
        "config.classic_baseline_only",
        "config",
        ok,
        "固定 α=1.0、N0 关闭、P_norm,eff 主统计量、冻结先于留出" if ok else "经典基线口径被改动",
        n0=classic.get("n0_improvements_enabled"),
        alpha_mode=dw.get("alpha_mode"),
        primary_statistic=rng.get("primary_statistic"),
    )

    thr = cfg.get("gates_and_thresholds", {})
    expected = {
        "required_valid_rx_channels": 63,
        "synthetic_noiseless_max_range_err_cm": 0.05,
        "synthetic_noisy_max_range_err_cm": 1.0,
        "synthetic_noisy_min_dw_suppression_db": 20.0,
        "air_loo_eligible_min_suppression_db": 10.0,
        "air_loo_hard_stop_suppression_db": 6.0,
        "target_echo_min_pslr_db": 3.0,
        "target_echo_min_pnr_db": 6.0,
        "cal_pilot_eligible_max_range_err_cm": 5.0,
        "cal_pilot_hard_stop_range_err_cm": 10.71,
    }
    mismatch = {k: {"actual": thr.get(k), "expected": v} for k, v in expected.items() if thr.get(k) != v}
    ck.add(
        "config.gates",
        "config",
        not mismatch,
        "10 项门槛阈值与 PLAN §5.2 一致" if not mismatch else "门槛阈值被改动",
        mismatch=mismatch,
    )

    budget = cfg.get("resource_budget", {})
    ok = int(budget.get("max_wall_time_sec", -1)) == 600 and int(budget.get("max_peak_rss_mib", -1)) == 4096
    ck.add("config.resource_budget", "config", ok, "墙钟 ≤600 s、峰值 RSS ≤4096 MiB",
           max_wall_time_sec=budget.get("max_wall_time_sec"), max_peak_rss_mib=budget.get("max_peak_rss_mib"))


# ---------------------------------------------------------------- E0-S 前置
def check_e0s(repo: Path, ck: Checker) -> Dict[str, Any]:
    results_path = repo / RESULTS_REL / "e0_s1s2_results.json"
    info: Dict[str, Any] = {}
    if not results_path.is_file():
        ck.add("e0s.present", "e0s", False, "缺少 %s" % rel_to(results_path, repo))
        return info
    try:
        res = load_json(results_path)
    except Exception as exc:  # pragma: no cover - 损坏文件才触发
        ck.add("e0s.parse", "e0s", False, "E0-S 结果 JSON 无法解析：%s" % exc)
        return info
    info["implementation_sha"] = res.get("implementation_sha")

    ck.add("e0s.present", "e0s", True, "E0-S 结果 JSON 可读", path=rel_to(results_path, repo))
    ck.add(
        "e0s.phase",
        "e0s",
        res.get("phase") == "E0-S" and res.get("experiment_id") == "A-Q1-E0",
        "phase=E0-S、experiment_id=A-Q1-E0",
        phase=res.get("phase"),
    )
    ck.add(
        "e0s.overall_pass",
        "e0s",
        res.get("overall_pass") is True and res.get("stop_reason") is None,
        "E0-S overall_pass=true 且 stop_reason=null",
        overall_pass=res.get("overall_pass"),
        stop_reason=res.get("stop_reason"),
    )

    cases = {str(c.get("case_id")): c for c in res.get("cases", [])}
    case_issues: List[str] = []
    for case_id, expect_rx in E0S_CASES:
        case = cases.get(case_id)
        if case is None:
            case_issues.append("%s 缺失" % case_id)
            continue
        try:
            rx = int(case.get("valid_rx"))
        except (TypeError, ValueError):
            rx = None
        if expect_rx is not None and rx != expect_rx:
            case_issues.append("%s valid_rx=%r≠%d" % (case_id, case.get("valid_rx"), expect_rx))
        if case.get("finite") is not True:
            case_issues.append("%s finite≠true" % case_id)
        for gate, result in (case.get("gate_results") or {}).items():
            if result.get("passed") is not True:
                case_issues.append("%s 门 %s 未过" % (case_id, gate))
    ck.add(
        "e0s.cases",
        "e0s",
        not case_issues and len(cases) == 3,
        "三例齐全、逐门 passed、S1 valid_rx=2、S2 valid_rx=63" if not case_issues else "; ".join(case_issues),
        issues=case_issues,
    )

    ck.add(
        "e0s.implementation_sha",
        "e0s",
        res.get("implementation_sha") == APPROVED_ANCHORS["e0s_implementation_sha"]
        and res.get("s2_param_table_match") is True
        and res.get("config_sha256_match") is True
        and res.get("plan_sha256_match") is True,
        "实现/参数表/config/PLAN 锚点与独立验收对象一致",
        implementation_sha=res.get("implementation_sha"),
        s2_param_table_match=res.get("s2_param_table_match"),
    )

    arrays_path = repo / RESULTS_REL / "e0_s1s2_arrays.npz"
    if arrays_path.is_file():
        actual = sha256_file(arrays_path)
        ok = actual == res.get("arrays_file_sha256") == APPROVED_ANCHORS["e0s_arrays_file_sha256"]
        ck.add("e0s.arrays_sha256", "e0s", ok,
               "e0_s1s2_arrays.npz 摘要与登记/验收一致" if ok else "数组文件摘要不匹配",
               actual=actual, registered=res.get("arrays_file_sha256"))
    else:
        ck.add("e0s.arrays_sha256", "e0s", False, "缺少 e0_s1s2_arrays.npz")

    table_path = repo / RESULTS_REL / "e0_s2_param_table.json"
    if table_path.is_file():
        actual = sha256_file(table_path)
        ok = actual == res.get("s2_param_table_file_sha256") == APPROVED_ANCHORS["e0s_param_table_file_sha256"]
        ck.add("e0s.param_table_sha256", "e0s", ok,
               "62 路参数表文件摘要与登记/预登记一致" if ok else "参数表文件摘要不匹配",
               actual=actual, registered=res.get("s2_param_table_file_sha256"))
    else:
        ck.add("e0s.param_table_sha256", "e0s", False, "缺少 e0_s2_param_table.json")

    acceptance = repo / "checks/A/e0_s1s2_acceptance.md"
    ok = acceptance.is_file() and acceptance.stat().st_size > 2000
    ck.add("e0s.acceptance_doc", "e0s", ok,
           "独立验收报告在库（checks/A/e0_s1s2_acceptance.md）" if ok else "缺少独立验收报告")
    return info


def check_fold_gate_contract(repo: Path, ck: Checker) -> None:
    path = repo / "solutions/A/a_fold_gate.py"
    if not path.is_file():
        ck.add("code.fold_gate_d1_2", "code", False, "缺少 solutions/A/a_fold_gate.py")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    ok = bool(re.search(r'CONTRACT_VERSION\s*=\s*"D1-2"', text))
    ck.add("code.fold_gate_d1_2", "code", ok,
           "折迭门控契约版本 CONTRACT_VERSION=D1-2" if ok else "折迭门控不是 D1-2")
    ck.add("code.d0_reader", "code", (repo / "solutions/A/a_dat_reader.py").is_file(),
           "D0 读取器在库（solutions/A/a_dat_reader.py）")


def check_runner(repo: Path, ck: Checker) -> bool:
    path = repo / "solutions/A/a_e0_c.py"
    present = path.is_file() and path.stat().st_size > 0
    # 归入 readiness 组：它决定“能否开始执行”，但不是放行前元数据条件本身。
    ck.add("code.e0c_runner_present", "readiness", present,
           "E0-C 主运行程序已交付" if present else "E0-C 主运行程序未交付（solutions/A/a_e0_c.py）")
    return present


# ---------------------------------------------------------------- 数据白名单
def group_dir(data_root: Path, group_key: str) -> Path:
    return data_root / DATA_SUBDIR / Path(group_key.replace("\\", "/"))


def find_out_of_scope(opened: Sequence[str], allowed_dirs: Sequence[Path]) -> List[str]:
    """返回不在任一白名单组目录直接子级的 ``.dat`` 路径（越界读取）。"""
    allowed = {Path(d).resolve() for d in allowed_dirs}
    outside: List[str] = []
    for name in opened:
        path = Path(name).resolve()
        if path.parent not in allowed:
            outside.append(str(path))
    return outside


def check_data(
    repo: Path,
    data_root: Path,
    manifest_path: Path,
    cfg: Dict[str, Any],
    ck: Checker,
) -> Dict[str, Any]:
    info: Dict[str, Any] = {"groups": [], "signal_files_hashed": 0, "opened_dat_files": []}
    if not manifest_path.is_file():
        ck.add("data.manifest_present", "data", False, "缺少 R0 清单 %s" % rel_to(manifest_path, repo))
        rows: List[Dict[str, Any]] = []
    else:
        try:
            rows = manifest_rows(manifest_path)
        except Exception as exc:
            ck.add("data.manifest_parse", "data", False, "R0 清单无法解析：%s" % exc)
            rows = []
        if not rows:
            ck.add("data.manifest_overall_sha256", "data", False, "R0 清单为空或不可解析")
        else:
            overall = manifest_overall_sha256(rows)
            info["manifest_overall_sha256"] = overall
            ck.add(
                "data.manifest_overall_sha256",
                "data",
                overall == APPROVED_ANCHORS["dat_manifest_overall_sha256"],
                "R0 清单总体 SHA256 匹配（881 文件，按清单行序）" if overall == APPROVED_ANCHORS["dat_manifest_overall_sha256"] else "R0 清单总体 SHA256 不匹配",
                actual=overall,
                files=len(rows),
                note="README 写“按路径排序”，实测可复现口径是 CSV 行序",
            )
    index = {r["rel_path"]: r for r in rows}

    if not data_root.is_dir():
        ck.add("data.root", "data", False, "数据根目录不存在：%s" % data_root)
        return info
    ck.add("data.root", "data", True, "数据根目录存在", root=str(data_root))

    air = expected_air_groups(cfg)
    targets = expected_targets(cfg)
    plan: List[Tuple[str, str]] = [(g, "air") for g in air]
    plan += [(str(t["group"]), str(t["target_type"])) for t in targets]

    data_root_real = Path(os.path.realpath(str(data_root)))
    opened: List[str] = []
    guarded: List[str] = []
    rejections: List[Dict[str, str]] = []
    problems: List[str] = []
    total_files = 0
    total_bytes = 0
    for key, role in plan:
        gdir = group_dir(data_root, key)
        # 目录字段用词法相对路径，避免在路径校验之前调用 resolve() 触碰可疑目标。
        summary: Dict[str, Any] = {
            "group": key,
            "role": role,
            "dir": "%s/%s" % (DATA_SUBDIR.as_posix(), key),
            "files": 0,
            "bytes": 0,
        }
        # 读前校验（1/2）：组目录本身必须是白名单内的真实目录，且逐级无重解析点。
        try:
            real_gdir = guard_group_dir(gdir, data_root)
        except PathGuardError as exc:
            problems.append("%s：组目录未通过路径校验 - %s" % (key, exc))
            rejections.append({"group": key, "path": str(gdir), "kind": "group_dir", "reason": str(exc)})
            summary["ok"] = False
            summary["path_guard"] = "rejected"
            info["groups"].append(summary)
            continue
        if not real_gdir.is_dir():
            problems.append("%s：目录不存在" % key)
            summary["ok"] = False
            info["groups"].append(summary)
            continue
        by_row: Dict[int, Path] = {}
        prefixes = set()
        for entry in sorted(real_gdir.iterdir()):
            if entry.suffix.lower() != ".dat":
                continue
            match = _ROW_RE.match(entry.name)
            if not match:
                problems.append("%s：文件名不合协议 %s" % (key, entry.name))
                continue
            row = int(match.group("row"))
            if row in by_row:
                problems.append("%s：行 %d 重复" % (key, row))
                continue
            # 读前校验（2/2）：条目必须在 stat/open 之前通过词法归属、反重解析点
            # 与 realpath 包含性检查；通过后只使用返回的真实路径。
            try:
                real_path = guard_dat_path(entry, real_gdir, data_root_real)
            except PathGuardError as exc:
                problems.append("%s：%s 未通过路径校验 - %s" % (key, entry.name, exc))
                rejections.append(
                    {"group": key, "path": str(entry), "kind": "dat_entry", "reason": str(exc)}
                )
                total_files += 1
                continue
            by_row[row] = real_path
            guarded.append(str(real_path))
            prefixes.add(match.group("prefix"))

        if sorted(by_row) != list(range(8)):
            problems.append("%s：行号 %s，应为 0..7" % (key, sorted(by_row)))
        if len(prefixes) > 1:
            problems.append("%s：组内出现多个时间戳前缀 %s" % (key, sorted(prefixes)))

        group_bytes = 0
        group_bad: List[str] = []
        for row, path in sorted(by_row.items()):
            try:
                size = path.stat().st_size
            except OSError as exc:
                group_bad.append("%s 无法 stat：%s" % (path.name, exc))
                total_files += 1
                continue
            group_bytes += size
            total_files += 1
            if size <= 0:
                group_bad.append("%s 0 字节" % path.name)
                continue
            rel_key = "%s/%s/%s" % (DATA_SUBDIR.as_posix(), key, path.name)
            rec = index.get(rel_key)
            if rec is None:
                group_bad.append("%s 不在 R0 清单" % path.name)
                continue
            if int(rec["size_bytes"]) != size:
                group_bad.append("%s 大小 %d≠清单 %d" % (path.name, size, rec["size_bytes"]))
                continue
            try:
                digest = sha256_file(path, opened)
            except OSError as exc:
                group_bad.append("%s 无法读取：%s" % (path.name, exc))
                continue
            if digest != rec["sha256"]:
                group_bad.append("%s SHA256 不符" % path.name)
        if group_bad:
            problems.extend("%s：%s" % (key, item) for item in group_bad)
        summary.update(
            {
                "files": len(by_row),
                "bytes": group_bytes,
                "prefix": sorted(prefixes)[0] if len(prefixes) == 1 else None,
                "ok": not group_bad and sorted(by_row) == list(range(8)) and len(prefixes) == 1,
            }
        )
        total_bytes += group_bytes
        info["groups"].append(summary)

    info["signal_files_hashed"] = len(opened)
    info["opened_dat_files"] = [rel_to(Path(p), repo) for p in opened]
    info["total_files"] = total_files
    info["total_bytes"] = total_bytes
    info["path_guard"] = {
        "rule": "lexical_parent -> lstat_no_reparse -> realpath_within_group_and_root",
        "applied_before": ["stat", "open"],
        "guarded_files": len(guarded),
        "rejections": rejections,
        "data_root_real": str(data_root_real),
    }

    ck.add(
        "data.inventory",
        "data",
        total_files == 96 and not problems,
        "12 组 × 8 文件 = 96 个非空 .dat，逐文件身份与 R0 清单一致" if total_files == 96 and not problems else "白名单数据不齐或身份不符",
        total_files=total_files,
        total_bytes=total_bytes,
        problems=problems[:20],
        problem_count=len(problems),
    )

    ck.add(
        "data.path_guard",
        "data",
        not rejections and len(guarded) == 96,
        "96 个待读 .dat 在 stat/open 之前均通过词法归属、反重解析点与 realpath 包含性校验"
        if not rejections and len(guarded) == 96
        else "存在未通过读前路径校验的条目（已拒绝访问）",
        guarded_files=len(guarded),
        rejected=len(rejections),
        rejections=rejections[:10],
    )

    allowed_dirs = [group_dir(data_root, key).resolve() for key, _ in plan]
    outside = find_out_of_scope(opened, allowed_dirs)
    ck.add(
        "data.no_out_of_scope_open",
        "data",
        not outside and len(opened) == 96,
        "实际打开并计算摘要的 .dat 全部落在白名单 12 组内" if not outside and len(opened) == 96 else "出现白名单以外的 .dat 读取",
        outside=outside,
    )
    return info


# ---------------------------------------------------------------- 主流程
def run_preflight(
    repo: Path,
    data_root: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    *,
    check_hashes: bool = True,
) -> Dict[str, Any]:
    """执行全部自检，返回机器可读结果；不写文件、不抛业务异常。"""
    started = time.perf_counter()
    repo = repo.resolve()
    data_root = (data_root or (repo / A_ROOT_DEFAULT)).resolve()
    manifest_path = (manifest_path or (repo / "recon/manifests/a_dat_manifest.csv")).resolve()

    ck = Checker()
    cfg_path = repo / "experiments/A/A-Q1-E0/config.json"
    split_path = repo / "coordination/A_Q1_SPLIT.json"

    cfg: Dict[str, Any] = {}
    split: Dict[str, Any] = {}
    anchors = check_anchor_files(repo, ck)
    try:
        cfg = load_json(cfg_path)
    except Exception as exc:
        ck.add("config.parse", "config", False, "config.json 无法解析：%s" % exc)
    try:
        split = load_json(split_path)
    except Exception as exc:
        ck.add("split.parse", "split", False, "A_Q1_SPLIT.json 无法解析：%s" % exc)

    if not isinstance(cfg, dict):
        if cfg:
            ck.add("config.parse", "config", False, "config.json 顶层不是 JSON 对象")
        cfg = {}
    if not isinstance(split, dict):
        if split:
            ck.add("split.parse", "split", False, "A_Q1_SPLIT.json 顶层不是 JSON 对象")
        split = {}

    if cfg:
        check_config_meta(cfg, ck)
        check_allow_list(cfg, split, ck)
    if split:
        check_split(split, ck)
    check_e0s(repo, ck)
    check_fold_gate_contract(repo, ck)
    runner_present = check_runner(repo, ck)

    if cfg and check_hashes:
        data_info = check_data(repo, data_root, manifest_path, cfg, ck)
    elif cfg:
        data_info = {"groups": [], "signal_files_hashed": 0, "opened_dat_files": [], "skipped": True}
        ck.add("data.hash_skipped", "data", False, "--no-hash：未核对 .dat 摘要，不能作为放行证据")
    else:
        data_info = {"groups": [], "signal_files_hashed": 0, "opened_dat_files": []}
        ck.add("data.inventory", "data", False, "config.json 不可用，无法确定白名单")

    failed = ck.failed_ids
    blocking = [c["id"] for c in ck.checks if not c["passed"] and c["group"] != "readiness"]
    preconditions_pass = not blocking
    open_items: List[Dict[str, str]] = []
    if not runner_present:
        open_items.append(
            {
                "id": "B-01",
                "item": "solutions/A/a_e0_c.py 未交付",
                "blocks": "E0-C 真实信号运行",
            }
        )
    open_items.append(
        {
            "id": "B-02",
            "item": "统筹尚未放行 E0-C 真实信号执行",
            "blocks": "E0-C 与后续 E0-T",
        }
    )

    elapsed = time.perf_counter() - started
    summary = {
        "total": len(ck.checks),
        "passed": sum(1 for c in ck.checks if c["passed"]),
        "failed": len(failed),
        "failed_ids": failed,
        "blocking_ids": blocking,
        "elapsed_s": round(elapsed, 3),
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "scope": SCOPE,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "repo": str(repo),
        "data_root": str(data_root),
        "manifest": rel_to(manifest_path, repo),
        "anchors": anchors,
        "expected_anchors": APPROVED_ANCHORS,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "data_allow_list": {
            "air_groups": expected_air_groups(cfg) if cfg else [],
            "targets": [
                {
                    "group": t.get("group"),
                    "target_type": t.get("target_type"),
                    "d_true_cm": t.get("d_true_cm"),
                    "in_split": t.get("in_split"),
                }
                for t in expected_targets(cfg)
            ] if cfg else [],
        },
        "data": data_info,
        "checks": ck.checks,
        "summary": summary,
        "preconditions_pass": preconditions_pass,
        "execution_ready": preconditions_pass and runner_present,
        "overall_pass": preconditions_pass,
        "open_items": open_items,
        "note": "overall_pass 仅表示放行前条件自检通过；execution_ready 另要求 a_e0_c.py 已交付；E0-C 放行仍以统筹书面批复为准。",
    }


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:  # pragma: no cover
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A-Q1-E0-C 放行前自检（仅元数据）")
    parser.add_argument("--repo", default=None, help="仓库根目录（默认本脚本上两级）")
    parser.add_argument("--data-root", default=None, help="A 题根目录（默认仓库内竞赛题目路径）")
    parser.add_argument("--manifest", default=None, help="R0 a_dat_manifest.csv 路径")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径；省略则只打印")
    parser.add_argument("--no-hash", action="store_true", help="跳过 .dat 摘要核对（只用于快速调试，不作为放行证据）")
    args = parser.parse_args(argv)

    _utf8_stdout()
    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[2]
    result = run_preflight(
        repo,
        Path(args.data_root) if args.data_root else None,
        Path(args.manifest) if args.manifest else None,
        check_hashes=not args.no_hash,
    )

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = repo / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        print("preflight JSON: %s" % out)
    else:
        print(payload)

    s = result["summary"]
    print(
        "preflight: %d/%d checks passed, blocking=%s, preconditions_pass=%s, execution_ready=%s, %.3fs"
        % (
            s["passed"],
            s["total"],
            ",".join(s["blocking_ids"]) or "-",
            result["preconditions_pass"],
            result["execution_ready"],
            s["elapsed_s"],
        )
    )
    if not result["execution_ready"]:
        print("open items:")
        for item in result["open_items"]:
            print("  - [%s] %s (%s)" % (item["id"], item["item"], item["blocks"]))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
