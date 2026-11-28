#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-Q1-N0 合成双进程入口：两个独立进程 → 同一 `E0-N0-1` 交付包。

契约边界
--------
* 只跑 `N0-SYN-1` **合成夹具**（seed 固定）：`real_dat_files_opened == 0`；
* 不实现、不调用 `--mode execute`；不读 `.dat`；不写 `n0_frozen.json`；
* 不改数值内核、不改任何阈值、不改 `accept_e0n0.py`；
* 所有产物一律 `synthetic=true` / `citable=false`，不得进入论文或冻结材料。

三个模式
--------
``worker``
    **一个进程**的完整执行：preflight(32) → dryrun(11) → 合成求解 → 相位证据 →
    打包 → `worker_meta.json` / `run_record.json` / `SHA256SUMS.txt`。
``combine``
    把两个 worker 目录合成一个 `E0-N0-1` 交付包（run-1 为顶层，run-2 在
    ``repeat/``）；`e0c_repeat.json` 的 11 个字段全部取自**实际落盘字节**。
``two-process``
    顺序启动两个 ``worker`` 子进程（各自独立 PID），记录两者**实际退出码**，
    再 ``combine``，写出 ``two_process.json``。

用法
----
```sh
# 一条命令产出两进程证据包（约 4–5 min，顺序执行以满足 C12 时间窗）
python solutions/A/run_n0_synthetic.py --mode two-process \
    --out experiments/A/A-Q1-E0/n0/synthetic_two_process \
    --runs-dir tmp/n0_two_runs \
    --prereg checks/A/e0_n0_prereg.json

# 分步：两个独立进程 + 合并
python solutions/A/run_n0_synthetic.py --mode worker --run-index 1 --out tmp/n0_r1 ...
python solutions/A/run_n0_synthetic.py --mode worker --run-index 2 --out tmp/n0_r2 ...
python solutions/A/run_n0_synthetic.py --mode combine --run1 tmp/n0_r1 --run2 tmp/n0_r2 --out tmp/n0_pkg
```
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import a_e0_n0 as N0  # noqa: E402
import a_e0_n0_package as PKG  # noqa: E402
import a_e0_n0_phase as PH  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402

#: 本入口的合成证据契约。
TWO_PROCESS_CONTRACT = "E0-N0-C12-SYNTHETIC-1"
PREFLIGHT_CONTRACT = "E0-C-PREFLIGHT-1"
DRYRUN_CONTRACT = "E0-C-DRYRUN-1"
#: 本入口可消费的冻结 prereg 契约（必须 `status=frozen`、`n0_contract=E0-N0-1`）。
#: `E0-N0-ACCEPT-3` 只加严验收口径、不改阈值，因此同一打包器可直接消费；
#: 包内 `registration.prereg_sha256` 记录实际消费的那份 prereg 字节，不预设版本。
PREREG_ACCEPT_CONTRACTS = ("E0-N0-ACCEPT-2", "E0-N0-ACCEPT-3")
#: 冻结的 `n0_config.json`（纯 LF 口径；见 coordination/A_Q1_N0_PHASE_EVIDENCE.md §5）。
#: `86b47241…` = 2026-11-28 对齐 `accept_contract=E0-N0-ACCEPT-3` 与
#: `anchors.prereg_sha256_lf=fdd2edab…` 之后的字节；旧值 `ec396737…` 为 ACCEPT-2 声明。
FROZEN_N0_CONFIG_LF_SHA256 = (
    "86b472416f30c7fbfa26b958d577a105e049571a863981b4d8285d7dea2d9470"
)
#: 合成夹具固定生成时间，保证两次进程的结果 JSON 有同一来源标签。
FIXED_GENERATED_AT = "2026-11-28T12:48:38Z"
#: C12 契约预算（与冻结 prereg `repeat` 块同值，只读）。
TOTAL_WALL_MAX_S = 600.0
PEAK_RSS_MAX_MIB = 4096.0
ALLOWED_EXIT_CODES = (0, 3, 4)
REPEAT_REQUIRED_FIELDS = (
    "run_id", "pid", "started_at", "finished_at", "results_file",
    "results_sha256", "arrays_file", "arrays_sha256", "wall_time_s",
    "exit_code", "peak_rss_mib",
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")

#: worker 目录 / 交付包里由本入口生成的文件（台账口径）。
RUN_FILES: Tuple[str, ...] = (
    "e0c_results.json", "e0c_air_loo.json", "e0c_arrays.npz",
    "preflight.json", "dryrun.json", "worker_meta.json", "run.log",
    "phase_evidence.json", "run_record.json",
)
PACKAGE_FILES: Tuple[str, ...] = tuple(PKG.REQUIRED_FILES) + tuple(PKG.GATE_FILES) + (
    "repeat/e0c_arrays.npz", "phase_evidence.json", "two_process.json",
)

# --------------------------------------------------------------------------- #
# 真实数据访问审计：任何 `.dat` 打开都会被计数（证据里必须为 0）
# --------------------------------------------------------------------------- #
_REAL_DAT_OPENS = 0
_HOOK_INSTALLED = False


def _install_dat_audit_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return

    def _hook(event: str, args: Tuple[Any, ...]) -> None:
        global _REAL_DAT_OPENS
        if event != "open" or not args:
            return
        try:
            path = os.fspath(args[0])
        except TypeError:
            return
        if not isinstance(path, str):
            return
        low = path.replace("\\", "/").lower()
        if low.endswith(".dat") or "竞赛题目/" in low:
            _REAL_DAT_OPENS += 1

    sys.addaudithook(_hook)
    _HOOK_INSTALLED = True


def _reset_dat_counter() -> None:
    global _REAL_DAT_OPENS
    _REAL_DAT_OPENS = 0


#: 导入即安装：任何路径（含测试、直接函数调用）打开 `.dat` 都会被计数。
_install_dat_audit_hook()


def real_dat_files_opened() -> int:
    return int(_REAL_DAT_OPENS)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def utc_now_ms() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_utc(text: str) -> float:
    s = str(text).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    stamp = _dt.datetime.fromisoformat(s)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_dt.timezone.utc)
    return stamp.timestamp()


def sha256_raw(path: str) -> str:
    return PKG.sha256_file(path)


def sha256_lf(path: str) -> str:
    return PKG.sha256_file_lf(path)


def _hash_matches(path: str, want: Optional[str]) -> bool:
    if not want or not os.path.isfile(path):
        return False
    return want in (sha256_raw(path), sha256_lf(path))


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, obj: Any, default: Any = None) -> None:
    """与 `PKG._write_json` 同格式（indent=1 / 保序 / LF），可选 numpy 默认值。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=False,
                  default=default)
        fh.write("\n")


def _read_ledger(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            out[parts[1].lstrip("*")] = parts[0]
    return out


def _ledger_problems(dirpath: str, ledger_name: str = "SHA256SUMS.txt") -> List[str]:
    ledger = _read_ledger(os.path.join(dirpath, ledger_name))
    problems: List[str] = []
    if not ledger:
        return ["台账为空或缺失"]
    for rel, want in ledger.items():
        path = os.path.join(dirpath, *rel.replace("\\", "/").split("/"))
        if not os.path.isfile(path):
            problems.append("台账文件不存在: %s" % rel)
        elif not _hash_matches(path, want):
            problems.append("台账哈希不符: %s" % rel)
    return problems


def _write_ledger(dirpath: str, names: Sequence[str]) -> List[str]:
    lines: List[str] = []
    written: List[str] = []
    for rel in names:
        rel = rel.replace("\\", "/")
        if rel == "SHA256SUMS.txt":  # 台账不登记自身（否则哈希自指）
            continue
        path = os.path.join(dirpath, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        lines.append("%s  %s\n" % (sha256_raw(path), rel))
        written.append(rel)
    with open(os.path.join(dirpath, "SHA256SUMS.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    return written


def _repo_root() -> str:
    return _git_stdout(HERE, ["rev-parse", "--show-toplevel"]) or ""


def _git_stdout(repo: str, args: Sequence[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", repo, *args], check=True,
                             capture_output=True, text=True)
        return out.stdout.strip()
    except Exception:
        return ""


def _git_rc(repo: str, args: Sequence[str]) -> int:
    try:
        return subprocess.run(["git", "-C", repo, *args],
                              capture_output=True, text=True).returncode
    except Exception:
        return 1


def _rel(repo: str, path: str) -> str:
    try:
        return os.path.relpath(os.path.abspath(path), repo).replace("\\", "/")
    except Exception:
        return os.path.abspath(path).replace("\\", "/")


def peak_rss_mib() -> float:
    """当前进程的峰值工作集（MiB）。"""
    if os.name == "nt":
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = k32.GetCurrentProcess()
        fn = getattr(k32, "K32GetProcessMemoryInfo", None)
        if fn is not None:
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            pmc = _PMC()
            pmc.cb = ctypes.sizeof(_PMC)
            if fn(handle, ctypes.byref(pmc), pmc.cb):
                return float(pmc.PeakWorkingSetSize) / (1024.0 * 1024.0)
        return 0.0
    try:  # pragma: no cover - 非 Windows 分支
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value / 1024.0 if sys.platform != "darwin" else value / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def _sha_of(path: str) -> Optional[str]:
    return sha256_raw(path) if os.path.isfile(path) else None


# --------------------------------------------------------------------------- #
# preflight：32 项
# --------------------------------------------------------------------------- #
def build_preflight(*, repo: str, config_path: str, prereg_path: str,
                    oracle_path: str, out_dir: str,
                    overwrite: bool) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def ck(cid: str, ok: bool, detail: Any = "") -> None:
        checks.append({"id": cid, "ok": bool(ok), "detail": str(detail)[:400]})

    root = _git_stdout(repo, ["rev-parse", "--show-toplevel"])
    ck("repo_root", bool(root) and os.path.isdir(root), root or "git rev-parse 失败")
    head = _git_stdout(repo, ["rev-parse", "HEAD"])
    ck("head_sha_40hex", HEX40.match(head) is not None, head)
    main = _git_stdout(repo, ["rev-parse", "origin/main"])
    ck("origin_main_sha_40hex", HEX40.match(main) is not None, main)
    ck("origin_main_ancestor_of_head",
       bool(main) and _git_rc(repo, ["merge-base", "--is-ancestor", "origin/main", "HEAD"]) == 0,
       "origin/main=%s" % main)
    dirty = _git_stdout(repo, ["status", "--porcelain", "--untracked-files=no"])
    ck("worktree_clean_tracked", dirty == "", dirty[:200] or "clean")

    cfg: Dict[str, Any] = {}
    ck("n0_config_exists", os.path.isfile(config_path), config_path)
    if os.path.isfile(config_path):
        ck("n0_config_lf_sha256_frozen",
           sha256_lf(config_path) == FROZEN_N0_CONFIG_LF_SHA256,
           sha256_lf(config_path))
        try:
            cfg = _read_json(config_path)
            ok_cfg = isinstance(cfg, dict)
        except Exception as exc:  # pragma: no cover - 损坏文件
            cfg, ok_cfg = {}, False
            ck("n0_config_parses", False, "%s: %s" % (type(exc).__name__, exc))
        else:
            ck("n0_config_parses", ok_cfg, cfg.get("id"))
    else:
        ck("n0_config_lf_sha256_frozen", False, "missing")
        ck("n0_config_parses", False, "missing")
    ck("identity_method_scope", cfg.get("method_scope") == PKG.METHOD_SCOPE,
       cfg.get("method_scope"))
    decisions = cfg.get("frozen_decisions") or {}
    p4 = decisions.get("p4_sign") or {}
    ck("p4_sign_rule",
       "peak_loss_db := -peak_retention_db" in str(p4.get("rule", "")),
       p4.get("rule"))
    unit = decisions.get("phase_unit") or {}
    ck("phase_unit_rule",
       "shifts_s" in str(unit.get("source", "")) and "1e9" in str(unit.get("rule", "")),
       unit.get("rule"))
    p1 = decisions.get("p1_expansion") or {}
    ck("fold_order_rule",
       p1.get("axes") == "[fold][held_out_index]"
       and "not lexicographic" in str(p1.get("rule", "")).lower(),
       p1.get("axes"))

    pre: Dict[str, Any] = {}
    ck("prereg_exists", os.path.isfile(prereg_path), prereg_path)
    if os.path.isfile(prereg_path):
        try:
            pre = _read_json(prereg_path)
        except Exception:
            pre = {}
    # 契约版本必须两端一致：prereg 的 `accept_contract` 与 n0_config 的声明同值，
    # 否则“配置声明 ACCEPT-2、包内消费 ACCEPT-3”的漂移会悄悄通过。
    ck("prereg_contract",
       pre.get("id") in PREREG_ACCEPT_CONTRACTS and pre.get("status") == "frozen"
       and pre.get("n0_contract") == "E0-N0-1"
       and pre.get("accept_contract") == cfg.get("accept_contract"),
       "%s/%s cfg=%s" % (pre.get("id"), pre.get("status"),
                         cfg.get("accept_contract")))
    th = pre.get("thresholds") or {}
    method = cfg.get("method") or {}
    ck("prereg_thresholds_match_config",
       th.get("rank") == method.get("rank") == 2
       and [float(v) for v in (th.get("lambda") or [])] == [0.001, 0.001]
       and [float(v) for v in (method.get("lambda") or [])] == [0.001, 0.001]
       and abs(float(th.get("eta_wall", -1)) - float(method.get("eta_wall", -2))) <= 1e-12
       and float(th.get("p1_min_db", -1)) == 10.0
       and float(th.get("p2_min_db", -1)) == 10.0
       and float(th.get("p4_peak_loss_db", -1)) == 0.1
       and float(th.get("p4_range_shift_mm", -1)) == 2.0,
       th)
    ck("prereg_air_groups_10",
       [str(x) for x in (pre.get("air_groups") or [])] == list(PKG.AIR_GROUPS),
       len(pre.get("air_groups") or []))
    clusters = pre.get("clusters") or []
    ck("prereg_clusters_5_pairs",
       [c.get("name") for c in clusters] == [name for name, _h in PKG.CLUSTERS]
       and [list(c.get("held_out") or []) for c in clusters] ==
       [list(h) for _name, h in PKG.CLUSTERS],
       len(clusters))
    rep = pre.get("repeat") or {}
    ck("prereg_repeat_block",
       int(rep.get("n_runs", -1)) == 2
       and float(rep.get("total_wall_time_max_s", -1)) == TOTAL_WALL_MAX_S
       and float(rep.get("peak_rss_max_mib", -1)) == PEAK_RSS_MAX_MIB
       and [int(v) for v in (rep.get("allowed_exit_codes") or [])] == list(ALLOWED_EXIT_CODES)
       and [str(v) for v in (rep.get("required_run_fields") or [])] ==
       list(REPEAT_REQUIRED_FIELDS),
       rep.get("contract"))

    oracle: Dict[str, Any] = {}
    ck("inputs_oracle_exists", os.path.isfile(oracle_path), oracle_path)
    if os.path.isfile(oracle_path):
        try:
            oracle = _read_json(oracle_path)
        except Exception:
            oracle = {}
    groups = oracle.get("groups") or {}
    files = [row for g in groups.values() for row in (g.get("files") or [])]
    ck("inputs_oracle_groups_12", len(groups) == 12, len(groups))
    ck("inputs_oracle_files_96", len(files) == 96, len(files))
    ck("inputs_oracle_total_bytes",
       int(oracle.get("total_bytes", -1)) == 88073632
       and sum(int(row.get("size_bytes", -1)) for row in files) == 88073632,
       oracle.get("total_bytes"))

    e0c_dir = os.path.join(repo, "experiments", "A", "A-Q1-E0", "e0c", "results")
    e0c_ledger = _read_ledger(os.path.join(e0c_dir, "SHA256SUMS.txt"))
    for cid, name in (("frozen_e0c_results_ledger", "e0c_results.json"),
                      ("frozen_e0c_arrays_ledger", "e0c_arrays.npz"),
                      ("frozen_e0c_air_loo_ledger", "e0c_air_loo.json")):
        ck(cid, _hash_matches(os.path.join(e0c_dir, name), e0c_ledger.get(name)),
           e0c_ledger.get(name))
    proto_dir = os.path.join(repo, "experiments", "A", "A-Q1-E0", "n0", "synthetic")
    proto_problems = _ledger_problems(proto_dir)
    ck("synthetic_prototype_ledger", not proto_problems, proto_problems)

    def _find_frozen(root_dir: str) -> List[str]:
        hits: List[str] = []
        if not os.path.isdir(root_dir):
            return hits
        for base, _dirs, names in os.walk(root_dir):
            if any(name in base for name in (".git", "__pycache__")):
                continue
            for name in names:
                if name == "n0_frozen.json":
                    hits.append(os.path.join(base, name))
        return hits

    try:
        frozen_hits = _find_frozen(os.path.join(repo, "experiments", "A", "A-Q1-E0"))
        if os.path.isfile(os.path.join(repo, "n0_frozen.json")):
            frozen_hits.append(os.path.join(repo, "n0_frozen.json"))
    except Exception:  # pragma: no cover - 权限受限目录
        frozen_hits = []
    ck("no_n0_frozen_artifact", not frozen_hits, frozen_hits)

    out_abs = os.path.abspath(out_dir).replace("\\", "/")
    frozen_markers = ("/e0c/results", "/e0c/dryrun", "/e0c/check")
    ck("out_dir_not_frozen_dir",
       not any(marker in out_abs for marker in frozen_markers), out_abs)
    exists_nonempty = os.path.isdir(out_dir) and bool(os.listdir(out_dir))
    ck("out_dir_writable_contract",
       (not exists_nonempty) or bool(overwrite),
       "exists_nonempty=%s overwrite=%s" % (exists_nonempty, overwrite))
    ck("environment_recorded",
       bool(platform.python_version()) and bool(np.__version__) and bool(platform.platform()),
       "python %s / numpy %s" % (platform.python_version(), np.__version__))
    ck("solver_entry_api",
       all(hasattr(N0, name) for name in
           ("run_synthetic", "write_outputs", "generate_synthetic_pool")),
       "N0-SYN-1")
    ck("package_module_api",
       PKG.METHOD_SCOPE == "M0-DW-Subspace/rank-2/in-window-2coef"
       and all(hasattr(PKG, name) for name in ("assemble", "from_prototype_synthetic")),
       PKG.PRODUCER_CONTRACT)

    passed = sum(1 for c in checks if c["ok"])
    return {
        "contract": PREFLIGHT_CONTRACT,
        "mode": "n0-synthetic",
        "synthetic": True,
        "citable": False,
        "real_dat_files_opened": real_dat_files_opened(),
        "started_at": utc_now_ms(),
        "finished_at": utc_now_ms(),
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "ok": passed == len(checks),
        "note": "N0 合成模式 preflight：32 项真实断言；不是 E0-C 实测 preflight 的转发。",
    }


# --------------------------------------------------------------------------- #
# dryrun：11 项（真跑小链路 + 夹具映射 + 玩具包自检）
# --------------------------------------------------------------------------- #
def _mktemp_dir(repo: str, work_dir: Optional[str], prefix: str) -> str:
    """在指定工作目录（默认仓库 tmp/）下建临时目录。

    注意：不用 `tempfile.mkdtemp`——它按 mode 0700 建目录，在本机受限令牌下会生成
    一个连本进程都无法再写入子项的 ACL（WinError 5）。这里用 `os.makedirs` 默认
    ACL + uuid 命名，行为与其它工作目录一致。
    """
    base = os.path.abspath(work_dir or os.path.join(repo, "tmp"))
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "%s%s" % (prefix, uuid.uuid4().hex[:10]))
    os.makedirs(path, exist_ok=True)
    return path


def _oracle_inputs(oracle: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = [row for g in (oracle.get("groups") or {}).values()
            for row in (g.get("files") or [])]
    return [{"rel_path": str(row["rel_path"]),
             "size_bytes": int(row["size_bytes"]),
             "sha256": str(row["sha256"])} for row in rows]


def build_dryrun(*, repo: str, config_path: str, n0_config_path: str,
                 prereg_path: str,
                 oracle_path: str, prototype_path: str,
                 seed: int = N0.SYNTH_SEED,
                 evidence: Optional[Dict[str, Any]] = None,
                 work_dir: Optional[str] = None) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def ck(cid: str, ok: bool, detail: Any = "") -> None:
        checks.append({"id": cid, "ok": bool(ok), "detail": str(detail)[:400]})

    cfg = E0S.load_config(Path(config_path))
    ck("config_load",
       isinstance(cfg, dict) and bool(cfg.get("experiment_id"))
       and "physical_constants" in cfg,
       cfg.get("experiment_id"))
    setup = E0S.Setup(cfg)
    ck("setup_geometry",
       setup.f_r.size == 1401 and abs(float(setup.d_min) - 0.15) <= 1e-12
       and abs(float(setup.d_max) - 2.0) <= 1e-12,
       "n_f=%d d=[%g,%g]" % (setup.f_r.size, setup.d_min, setup.d_max))

    synth = N0.generate_synthetic_pool(setup, seed=int(seed))
    ck("synth_pool_shapes",
       len(synth["air"]) == 10
       and all(np.asarray(x).shape == (63, setup.f_r.size) for x in synth["air"])
       and set(synth["targets"]) == set(PKG.TARGET_GROUPS),
       "air=%d targets=%d" % (len(synth["air"]), len(synth["targets"])))

    cal = N0.calibrate_pool(synth["air"], setup)
    inv = np.asarray(cal["inv"], dtype=np.complex128)
    ck("calibrate_inverse",
       inv.size in (63, 63 * setup.f_r.size) and bool(np.isfinite(inv).all())
       and bool(np.isfinite(np.asarray(cal["xbar_cal"])).all()),
       inv.shape)
    shifts_s = [float(v) for v in synth["shifts_s"][: len(N0.AIR_GROUPS)]]
    air_cal = [x * inv for x in synth["air"]]
    aligned = [N0.align_spectra(x, s, setup.f_r) for x, s in zip(air_cal, shifts_s)]
    stack = np.stack(aligned, axis=0)
    ck("align_shapes_finite",
       stack.shape == (10, 63, setup.f_r.size) and bool(np.isfinite(stack).all()),
       stack.shape)
    basis = N0.build_rank2_basis(stack)
    ck("basis_rank2",
       int(basis["rank_effective"]) == 2 and not bool(basis["near_parallel"]),
       "rank=%s near_parallel=%s" % (basis["rank_effective"], basis["near_parallel"]))

    if evidence is None:
        evidence = PH.build_synthetic_evidence(seed=int(seed))
    rows = evidence.get("coherence") or []
    d1 = evidence.get("d1") or {}
    rho_ok = all(0.0 <= float(r.get("rho", -1)) <= 1.0 for r in rows)
    d1_rank = int(d1.get("d1_rank", 0))
    d1_min = float(d1.get("d1_min_abs_inner", -1))
    ck("phase_evidence_ranges",
       evidence.get("contract") == PH.PHASE_EVIDENCE_CONTRACT
       and len(rows) == 10 and rho_ok
       and d1_rank in (1, 2) and d1_min >= 0.0
       and (d1_min <= PKG.D1_ORTHO_TOL if d1_rank == 2 else d1_min == 0.0),
       "rho_n=%d d1_rank=%d d1_min=%.3g" % (len(rows), d1_rank, d1_min))

    prototype = _read_json(prototype_path)
    oracle = _read_json(oracle_path)
    raw = PKG.from_prototype_synthetic(
        prototype,
        inputs=_oracle_inputs(oracle),
        main_commit=_git_stdout(repo, ["rev-parse", "origin/main"]) or "0" * 40,
        n0_config_sha256=sha256_lf(n0_config_path),
        phase_evidence=evidence,
    )
    built = PKG.assemble(raw, prereg_path=prereg_path)
    res = built["results"]
    xc = res["n0"]["xcluster_supp_db"]
    ck("fixture_mapping_35",
       len(res["inputs"]) == 96
       and len(xc) == 5 and all(len(row) == 2 for row in xc)
       and set(built["arrays"]) == {spec[0] for spec in PKG.ARRAY_SPECS}
       and len(res["n0"]["phase"]["per_group"]) == 10
       and len(res["n0"]["arm_metrics"]["C2"]["air_loo_supp_db"]) == 10,
       "inputs=%d xcluster=%dx%d arrays=%d"
       % (len(res["inputs"]), len(xc), len(xc[0]) if xc else 0,
          len(built["arrays"])))

    toy = _mktemp_dir(repo, work_dir, prefix="n0_toy_")
    try:
        repeat = {"runs": [
            {"run_id": "toy-1", "results_file": "e0c_results.json",
             "arrays_file": "e0c_arrays.npz"},
            {"run_id": "toy-2", "results_file": "repeat/e0c_results.json",
             "arrays_file": "repeat/e0c_arrays.npz"},
        ]}
        metas = [{"run_id": "toy-1", "pid": 1},
                 {"run_id": "toy-2", "pid": 2}]
        PKG.write_package(toy, built, repeat=repeat, worker_meta=metas,
                          preflight={"passed": 32, "total": 32},
                          dryrun={"passed": 11, "total": 11},
                          run2_results=built["results"],
                          run2_arrays=built["arrays"])
        chk = PKG.selfcheck(toy)
        ck("toy_package_selfcheck", chk["verdict"] == "SELF_OK", chk["verdict"])
    finally:
        shutil.rmtree(toy, ignore_errors=True)

    frozen_problems = _frozen_problems(repo)
    ck("frozen_artifacts_unchanged", not frozen_problems, frozen_problems)
    ck("no_real_dat_opened", real_dat_files_opened() == 0,
       "real_dat_files_opened=%d" % real_dat_files_opened())

    passed = sum(1 for c in checks if c["ok"])
    doc = {
        "contract": DRYRUN_CONTRACT,
        "mode": "n0-synthetic",
        "synthetic": True,
        "citable": False,
        "real_dat_files_opened": real_dat_files_opened(),
        "started_at": utc_now_ms(),
        "finished_at": utc_now_ms(),
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "ok": passed == len(checks),
        "note": "N0 合成模式 dryrun：真跑生成/校准/对齐/基/相位 + 夹具映射 + 玩具包自检；不读 .dat。",
    }
    return {"doc": doc, "evidence": evidence, "setup": setup, "built": built,
            "prototype": prototype, "oracle": oracle}


def _frozen_problems(repo: str) -> List[str]:
    e0c_dir = os.path.join(repo, "experiments", "A", "A-Q1-E0", "e0c", "results")
    return _ledger_problems(e0c_dir)


# --------------------------------------------------------------------------- #
# worker：一个独立进程
# --------------------------------------------------------------------------- #
def _prepare_out_dir(out: str, overwrite: bool) -> Optional[str]:
    if os.path.isdir(out) and os.listdir(out) and not overwrite:
        return "输出目录非空且未给 --overwrite: %s" % out
    os.makedirs(out, exist_ok=True)
    return None


def _build_package(*, repo: str, n0_config_path: str, prereg_path: str,
                   oracle_path: str, prototype_doc: Dict[str, Any],
                   evidence: Dict[str, Any]) -> Dict[str, Any]:
    cfg_lf = sha256_lf(n0_config_path)
    cfg_raw = sha256_raw(n0_config_path)
    raw = PKG.from_prototype_synthetic(
        prototype_doc,
        inputs=_oracle_inputs(_read_json(oracle_path)),
        main_commit=_git_stdout(repo, ["rev-parse", "origin/main"]) or "0" * 40,
        n0_config_sha256=cfg_lf,
        phase_evidence=evidence,
    )
    raw.setdefault("anchors", {})["n0_config"] = {
        "path": _rel(repo, n0_config_path),
        "sha256_lf": cfg_lf,
        "sha256_raw": cfg_raw,
    }
    raw["anchors"]["n0_config_sha256"] = cfg_lf
    return PKG.assemble(raw, prereg_path=prereg_path)


def run_worker(args: argparse.Namespace) -> int:
    _install_dat_audit_hook()
    repo = _repo_root()
    out = os.path.abspath(args.out)
    started_at = utc_now_ms()
    t_perf = time.perf_counter()
    code_start = _REAL_DAT_OPENS
    run_id = "run-%d" % int(args.run_index)
    error: Optional[str] = None
    pre: Optional[Dict[str, Any]] = None
    dry: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None
    code = 4
    built: Optional[Dict[str, Any]] = None

    problem = _prepare_out_dir(out, bool(args.overwrite))
    if problem is not None:
        print("worker: %s" % problem, file=sys.stderr)
        return 4

    stage = "preflight"
    try:
        pre = build_preflight(
            repo=repo, config_path=args.n0_config, prereg_path=args.prereg,
            oracle_path=args.oracle, out_dir=out, overwrite=bool(args.overwrite))
        _write_json(os.path.join(out, "preflight.json"), pre)
        if not pre["ok"]:
            failed = [c["id"] for c in pre["checks"] if not c["ok"]]
            raise _StageError(3, "preflight 未通过: %s" % failed)

        stage = "dryrun"
        evidence = None
        if args.reuse_phase_evidence:
            evidence = _read_json(args.reuse_phase_evidence)
        dry = build_dryrun(
            repo=repo, config_path=args.config, n0_config_path=args.n0_config,
            prereg_path=args.prereg,
            oracle_path=args.oracle, prototype_path=args.prototype,
            seed=int(args.seed), evidence=evidence, work_dir=out)
        _write_json(os.path.join(out, "dryrun.json"), dry["doc"])
        if not dry["doc"]["ok"]:
            failed = [c["id"] for c in dry["doc"]["checks"] if not c["ok"]]
            raise _StageError(3, "dryrun 未通过: %s" % failed)
        evidence = dry["evidence"]

        stage = "solve"
        if args.reuse_prototype:
            doc = _read_json(args.reuse_prototype)
        else:
            doc = N0.run_synthetic(seed=int(args.seed), setup=dry["setup"])
            scratch = os.path.join(out, "_prototype")
            command = ("python solutions/A/run_n0_synthetic.py --mode worker "
                       "--run-index %d --out %s"
                       % (int(args.run_index), N0._display_path(Path(out))))
            N0.write_outputs(doc, Path(scratch), overwrite=True,
                             command=command, generated_at=FIXED_GENERATED_AT)
            doc = _read_json(os.path.join(scratch, "n0_synthetic_results.json"))

        stage = "package"
        built = _build_package(repo=repo, n0_config_path=args.n0_config,
                               prereg_path=args.prereg, oracle_path=args.oracle,
                               prototype_doc=doc, evidence=evidence)
        _write_json(os.path.join(out, "e0c_results.json"), built["results"])
        _write_json(os.path.join(out, "e0c_air_loo.json"), built["air_loo"])
        PKG._write_npz(os.path.join(out, "e0c_arrays.npz"), built["arrays"])
        code = 0
    except _StageError as exc:
        code, error = exc.code, str(exc)
    except Exception as exc:  # noqa: BLE001 - 证据必须记录真实异常
        code = 4 if stage == "package" else 3
        error = "%s: %s [stage=%s]" % (type(exc).__name__, exc, stage)

    def _finalize(exit_code: int, err: Optional[str]) -> Dict[str, Any]:
        finished_at = utc_now_ms()
        wall = round(time.perf_counter() - t_perf, 3)
        frozen_problems = _frozen_problems(repo)
        dat_reads = _REAL_DAT_OPENS - code_start
        meta = {
            "contract": "E0-C-WORKER-META-1",
            "run_id": run_id,
            "run_index": int(args.run_index),
            "pid": os.getpid(),
            "command": "python solutions/A/run_n0_synthetic.py --mode worker "
                       "--run-index %d --out %s"
                       % (int(args.run_index), _rel(repo, out)),
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": int(exit_code),
            "error": err,
            "wall_time_s": wall,
            "peak_rss_mib": round(peak_rss_mib(), 3),
            "synthetic": True,
            "citable": False,
            "seed": int(args.seed),
            "generated_at": FIXED_GENERATED_AT,
            "solve_skipped": bool(args.reuse_prototype),
            "phase_evidence_reused": bool(args.reuse_phase_evidence),
            "real_dat_files_opened": int(dat_reads),
            "frozen_artifacts_unchanged": not frozen_problems,
            "n0_frozen_written": os.path.isfile(os.path.join(out, "n0_frozen.json")),
            "preflight": {"passed": (pre or {}).get("passed"),
                          "total": (pre or {}).get("total")},
            "dryrun": {"passed": (dry or {}).get("doc", {}).get("passed"),
                       "total": (dry or {}).get("doc", {}).get("total")},
            "environment": {"python": platform.python_version(),
                            "numpy": np.__version__,
                            "platform": platform.platform()},
        }
        if evidence is not None:
            _write_json(os.path.join(out, "phase_evidence.json"),
                        evidence, default=PH._json_default)
        log_lines = [
            "contract=%s mode=worker run_id=%s" % (TWO_PROCESS_CONTRACT, run_id),
            "synthetic=true citable=false",
            "pid=%d exit_code=%d wall_time_s=%.3f peak_rss_mib=%.3f"
            % (meta["pid"], exit_code, wall, meta["peak_rss_mib"]),
            "preflight=%s/%s dryrun=%s/%s"
            % (meta["preflight"]["passed"], meta["preflight"]["total"],
               meta["dryrun"]["passed"], meta["dryrun"]["total"]),
            "real_dat_files_opened=%d frozen_artifacts_unchanged=%s"
            % (dat_reads, meta["frozen_artifacts_unchanged"]),
            "error=%s" % (err or "none"),
        ]
        with open(os.path.join(out, "run.log"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write("\n".join(log_lines) + "\n")
        _write_json(os.path.join(out, "worker_meta.json"), meta)
        record = {
            "contract": TWO_PROCESS_CONTRACT,
            "run_id": run_id,
            "run_index": int(args.run_index),
            "pid": os.getpid(),
            "exit_code": int(exit_code),
            "started_at": started_at,
            "finished_at": finished_at,
            "wall_time_s": wall,
            "peak_rss_mib": meta["peak_rss_mib"],
            "results_file": "e0c_results.json",
            "results_sha256": _sha_of(os.path.join(out, "e0c_results.json")),
            "arrays_file": "e0c_arrays.npz",
            "arrays_sha256": _sha_of(os.path.join(out, "e0c_arrays.npz")),
            "air_loo_sha256": _sha_of(os.path.join(out, "e0c_air_loo.json")),
            "preflight_sha256": _sha_of(os.path.join(out, "preflight.json")),
            "dryrun_sha256": _sha_of(os.path.join(out, "dryrun.json")),
            "phase_evidence_sha256": _sha_of(os.path.join(out, "phase_evidence.json")),
            "worker_meta_sha256": _sha_of(os.path.join(out, "worker_meta.json")),
            "metrics_sha256": ((built or {}).get("results") or {}).get("metrics_sha256"),
            "real_dat_files_opened": int(dat_reads),
            "frozen_artifacts_unchanged": not frozen_problems,
            "synthetic": True,
            "citable": False,
            "error": err,
        }
        _write_json(os.path.join(out, "run_record.json"), record)
        _write_ledger(out, RUN_FILES)
        return meta

    meta = _finalize(code, error)
    if built is not None:
        chk = PKG.selfcheck(out)
        if chk["verdict"] != "SELF_OK":
            code = 4
            error = "打包自检失败: %s" % chk["problems"]
            meta = _finalize(code, error)
    print(json.dumps({
        "mode": "worker", "run_id": run_id, "pid": os.getpid(),
        "exit_code": code, "wall_time_s": meta["wall_time_s"],
        "peak_rss_mib": meta["peak_rss_mib"],
        "preflight": meta["preflight"], "dryrun": meta["dryrun"],
        "error": error,
    }, ensure_ascii=False))
    return int(code)


class _StageError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = int(code)


# --------------------------------------------------------------------------- #
# combine：两个 worker 目录 → 一个交付包
# --------------------------------------------------------------------------- #
def _load_run_record(run_dir: str) -> Dict[str, Any]:
    path = os.path.join(run_dir, "run_record.json")
    if not os.path.isfile(path):
        raise _StageError(4, "缺少 run_record.json: %s" % path)
    return _read_json(path)


def _check_run_pair(rec1: Dict[str, Any], rec2: Dict[str, Any],
                    run1: str, run2: str) -> List[str]:
    problems: List[str] = []
    exits = [int(rec1.get("exit_code", -1)), int(rec2.get("exit_code", -2))]
    if exits[0] != exits[1]:
        problems.append("两次运行退出码不同: %r" % exits)
    if any(code not in ALLOWED_EXIT_CODES for code in exits):
        problems.append("退出码 %r 不在契约集合 %r" % (exits, list(ALLOWED_EXIT_CODES)))
    if exits != [0, 0]:
        problems.append("本次证据要求两次都成功（exit 0），实为 %r" % exits)
    if int(rec1.get("pid", 0)) == int(rec2.get("pid", 0)):
        problems.append("两次运行 pid 相同，不是独立进程")
    if str(rec1.get("run_id")) == str(rec2.get("run_id")):
        problems.append("两次运行 run_id 相同")
    for kind in ("results", "arrays"):
        p1 = os.path.join(run1, *str(rec1.get(kind + "_file")).split("/"))
        p2 = os.path.join(run2, *str(rec2.get(kind + "_file")).split("/"))
        if not os.path.isfile(p1) or not os.path.isfile(p2):
            problems.append("%s 文件缺失" % kind)
            continue
        if sha256_raw(p1) != sha256_raw(p2):
            problems.append("两次运行 %s 字节不一致" % kind)
        want1 = rec1.get(kind + "_sha256")
        want2 = rec2.get(kind + "_sha256")
        if not _hash_matches(p1, want1) or not _hash_matches(p2, want2):
            problems.append("%s 摘要与 run_record 不符" % kind)
    try:
        start1 = parse_utc(rec1["started_at"])
        end1 = parse_utc(rec1["finished_at"])
        start2 = parse_utc(rec2["started_at"])
        end2 = parse_utc(rec2["finished_at"])
        if not start1 < end1:
            problems.append("run-1 时间窗非正")
        if not start2 < end2:
            problems.append("run-2 时间窗非正")
        if end1 > start2:
            problems.append("两次运行时间窗重叠/顺序颠倒")
    except Exception as exc:
        problems.append("时间戳不可解析: %s" % exc)
    try:
        total = float(rec1["wall_time_s"]) + float(rec2["wall_time_s"])
        if total > TOTAL_WALL_MAX_S:
            problems.append("两次合计墙钟 %.1f s > %.1f s" % (total, TOTAL_WALL_MAX_S))
        for rec in (rec1, rec2):
            if float(rec["peak_rss_mib"]) <= 0:
                problems.append("%s peak_rss_mib 非正" % rec.get("run_id"))
            if float(rec["peak_rss_mib"]) > PEAK_RSS_MAX_MIB:
                problems.append("%s peak_rss_mib 超预算" % rec.get("run_id"))
    except (KeyError, TypeError, ValueError):
        problems.append("资源字段不可解析")
    if rec1.get("real_dat_files_opened") != 0 or rec2.get("real_dat_files_opened") != 0:
        problems.append("合成入口打开了真实 .dat")
    if not rec1.get("frozen_artifacts_unchanged") or not rec2.get("frozen_artifacts_unchanged"):
        problems.append("冻结产物在运行期间被改动")
    if rec1.get("metrics_sha256") != rec2.get("metrics_sha256"):
        problems.append("两次 metrics_sha256 不一致")
    for kind in ("preflight", "dryrun"):
        for rec in (rec1, rec2):
            got = rec.get(kind + "_sha256")
            if not got:
                problems.append("%s 缺 %s 日志" % (rec.get("run_id"), kind))
    return problems


def run_combine(args: argparse.Namespace) -> int:
    repo = _repo_root()
    out = os.path.abspath(args.out)
    run1 = os.path.abspath(args.run1)
    run2 = os.path.abspath(args.run2)
    problem = _prepare_out_dir(out, bool(args.overwrite))
    if problem is not None:
        print("combine: %s" % problem, file=sys.stderr)
        return 4
    try:
        rec1 = _load_run_record(run1)
        rec2 = _load_run_record(run2)
        problems = _check_run_pair(rec1, rec2, run1, run2)
        if problems:
            raise _StageError(4, "两进程证据不成立: %s" % problems)

        pre1 = _read_json(os.path.join(run1, "preflight.json"))
        dry1 = _read_json(os.path.join(run1, "dryrun.json"))
        pre2 = _read_json(os.path.join(run2, "preflight.json"))
        dry2 = _read_json(os.path.join(run2, "dryrun.json"))
        for name, doc, need in (("preflight", pre1, 32), ("dryrun", dry1, 11),
                                ("preflight", pre2, 32), ("dryrun", dry2, 11)):
            if int(doc.get("passed", -1)) != need or int(doc.get("total", -1)) != need:
                raise _StageError(4, "%s 未达 %d/%d: %r"
                                  % (name, need, need, doc.get("passed")))
        if not pre1.get("synthetic") or not dry1.get("synthetic"):
            raise _StageError(4, "门禁日志未标记 synthetic，拒绝冒充实测门禁")

        def copy(src: str, rel: str) -> None:
            dst = os.path.join(out, *rel.split("/"))
            os.makedirs(os.path.dirname(dst) or out, exist_ok=True)
            shutil.copyfile(src, dst)

        copy(os.path.join(run1, "e0c_results.json"), "e0c_results.json")
        copy(os.path.join(run1, "e0c_arrays.npz"), "e0c_arrays.npz")
        copy(os.path.join(run1, "e0c_air_loo.json"), "e0c_air_loo.json")
        copy(os.path.join(run1, "preflight.json"), "preflight.json")
        copy(os.path.join(run1, "dryrun.json"), "dryrun.json")
        copy(os.path.join(run1, "worker_meta.json"), "worker_meta.json")
        if os.path.isfile(os.path.join(run1, "phase_evidence.json")):
            copy(os.path.join(run1, "phase_evidence.json"), "phase_evidence.json")
        copy(os.path.join(run2, "e0c_results.json"), "repeat/e0c_results.json")
        copy(os.path.join(run2, "e0c_arrays.npz"), "repeat/e0c_arrays.npz")
        copy(os.path.join(run2, "worker_meta.json"), "repeat/worker_meta.json")

        for rec, prefix in ((rec1, ""), (rec2, "repeat/")):
            res_path = os.path.join(out, *(prefix + "e0c_results.json").split("/"))
            arr_path = os.path.join(out, *(prefix + "e0c_arrays.npz").split("/"))
            if sha256_raw(res_path) != sha256_raw(os.path.join(out, "e0c_results.json")):
                raise _StageError(4, "%s 结果字节与 run-1 不同" % prefix)
            if sha256_raw(arr_path) != sha256_raw(os.path.join(out, "e0c_arrays.npz")):
                raise _StageError(4, "%s 数组字节与 run-1 不同" % prefix)

        runs = []
        for rec, prefix in ((rec1, ""), (rec2, "repeat/")):
            runs.append({
                "run_id": rec["run_id"],
                "pid": int(rec["pid"]),
                "started_at": rec["started_at"],
                "finished_at": rec["finished_at"],
                "results_file": prefix + "e0c_results.json",
                "results_sha256": sha256_raw(os.path.join(out, *(prefix + "e0c_results.json").split("/"))),
                "arrays_file": prefix + "e0c_arrays.npz",
                "arrays_sha256": sha256_raw(os.path.join(out, *(prefix + "e0c_arrays.npz").split("/"))),
                "wall_time_s": float(rec["wall_time_s"]),
                "exit_code": int(rec["exit_code"]),
                "peak_rss_mib": float(rec["peak_rss_mib"]),
            })
        total_wall = sum(r["wall_time_s"] for r in runs)
        repeat = {
            "contract": "E0-C-C12-REPEAT-1",
            "n_runs": 2,
            "synthetic": True,
            "citable": False,
            "entry": "solutions/A/run_n0_synthetic.py",
            "allowed_exit_codes": list(ALLOWED_EXIT_CODES),
            "total_wall_time_s": total_wall,
            "total_wall_time_max_s": TOTAL_WALL_MAX_S,
            "peak_rss_max_mib": PEAK_RSS_MAX_MIB,
            "runs": runs,
            "note": ("两次证据为同一合成入口的两个独立进程；"
                     "摘要均取自实际落盘字节。N0 实测未放行。"),
        }
        _write_json(os.path.join(out, "e0c_repeat.json"), repeat)

        with open(os.path.join(out, "run.log"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("contract=%s mode=two-process synthetic=true citable=false\n"
                     % TWO_PROCESS_CONTRACT)
            for rec, prefix in ((rec1, ""), (rec2, "repeat/")):
                fh.write("run=%s pid=%d exit_code=%d wall_time_s=%.3f "
                         "peak_rss_mib=%.3f results=%s arrays=%s\n"
                         % (rec["run_id"], rec["pid"], rec["exit_code"],
                            rec["wall_time_s"], rec["peak_rss_mib"],
                            sha256_raw(os.path.join(out, *(prefix + "e0c_results.json").split("/"))),
                            sha256_raw(os.path.join(out, *(prefix + "e0c_arrays.npz").split("/")))))
            fh.write("total_wall_time_s=%.3f limit=%.1f\n"
                     % (total_wall, TOTAL_WALL_MAX_S))

        driver = getattr(args, "driver_meta", None)
        two = {
            "contract": TWO_PROCESS_CONTRACT,
            "synthetic": True,
            "citable": False,
            "entry": "solutions/A/run_n0_synthetic.py",
            "runs": [
                {"run_index": 1, "run_id": rec1["run_id"], "pid": int(rec1["pid"]),
                 "exit_code": int(rec1["exit_code"]),
                 "started_at": rec1["started_at"], "finished_at": rec1["finished_at"],
                 "wall_time_s": float(rec1["wall_time_s"]),
                 "results_sha256": runs[0]["results_sha256"],
                 "arrays_sha256": runs[0]["arrays_sha256"]},
                {"run_index": 2, "run_id": rec2["run_id"], "pid": int(rec2["pid"]),
                 "exit_code": int(rec2["exit_code"]),
                 "started_at": rec2["started_at"], "finished_at": rec2["finished_at"],
                 "wall_time_s": float(rec2["wall_time_s"]),
                 "results_sha256": runs[1]["results_sha256"],
                 "arrays_sha256": runs[1]["arrays_sha256"]},
            ],
            "byte_identical_results": True,
            "byte_identical_arrays": True,
            "total_wall_time_s": total_wall,
            "peak_rss_mib": [r["peak_rss_mib"] for r in runs],
            "real_dat_files_opened": 0,
            "frozen_artifacts_unchanged": True,
            "n0_frozen_written": False,
            "budget": {"total_wall_time_max_s": TOTAL_WALL_MAX_S,
                       "peak_rss_max_mib": PEAK_RSS_MAX_MIB,
                       "allowed_exit_codes": list(ALLOWED_EXIT_CODES)},
            "gate_logs": {"preflight": "32/32", "dryrun": "11/11",
                          "synthetic": True,
                          "note": "N0 合成模式门禁（真实断言）；不是 E0-C 实测门禁的转发"},
        }
        if isinstance(driver, dict):
            two["driver"] = driver
        _write_json(os.path.join(out, "two_process.json"), two)

        _write_ledger(out, PACKAGE_FILES)
        chk = PKG.selfcheck(out)
        if chk["verdict"] != "SELF_OK":
            raise _StageError(4, "合并包自检失败: %s" % chk["problems"])
        print(json.dumps({
            "mode": "combine", "out": out, "exit_code": 0,
            "runs": [{"run_id": r["run_id"], "pid": r["pid"],
                      "exit_code": r["exit_code"],
                      "results_sha256": r["results_sha256"],
                      "arrays_sha256": r["arrays_sha256"]} for r in runs],
            "total_wall_time_s": total_wall,
            "files": [n for n in _read_ledger(os.path.join(out, "SHA256SUMS.txt"))],
        }, ensure_ascii=False))
        return 0
    except _StageError as exc:
        print("combine: %s" % exc, file=sys.stderr)
        return int(exc.code)
    except Exception as exc:  # noqa: BLE001
        print("combine: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 4


# --------------------------------------------------------------------------- #
# two-process：顺序启动两个独立 worker 子进程
# --------------------------------------------------------------------------- #
def run_two_process(args: argparse.Namespace) -> int:
    _install_dat_audit_hook()
    repo = _repo_root()
    out = os.path.abspath(args.out)
    runs_dir = os.path.abspath(args.runs_dir)
    os.makedirs(runs_dir, exist_ok=True)
    runs: List[Dict[str, Any]] = []
    parent_pid = os.getpid()
    for index in (1, 2):
        run_dir = os.path.join(runs_dir, "run%d" % index)
        os.makedirs(run_dir, exist_ok=True)
        cmd = [sys.executable, os.path.abspath(__file__),
               "--mode", "worker", "--run-index", str(index),
               "--out", run_dir,
               "--config", args.config, "--n0-config", args.n0_config,
               "--prereg", args.prereg,
               "--oracle", args.oracle, "--prototype", args.prototype,
               "--seed", str(args.seed)]
        if args.overwrite:
            cmd.append("--overwrite")
        started = utc_now_ms()
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, cwd=repo)
        wall = round(time.perf_counter() - t0, 3)
        finished = utc_now_ms()
        rec = _load_run_record(run_dir) if os.path.isfile(
            os.path.join(run_dir, "run_record.json")) else {}
        if proc.returncode != int(rec.get("exit_code", -999)):
            print("two-process: 子进程实际退出码 %d 与 run_record %r 不符"
                  % (proc.returncode, rec.get("exit_code")), file=sys.stderr)
            return 4
        if proc.returncode != 0:
            print("two-process: run-%d 退出码 %d，停止" % (index, proc.returncode),
                  file=sys.stderr)
            return 4
        runs.append({"run_index": index, "command": cmd,
                     "pid": int(rec.get("pid", -1)),
                     "exit_code": int(proc.returncode),
                     "driver_started_at": started,
                     "driver_finished_at": finished,
                     "driver_wall_time_s": wall,
                     "worker_started_at": rec.get("started_at"),
                     "worker_finished_at": rec.get("finished_at"),
                     "results_sha256": rec.get("results_sha256"),
                     "arrays_sha256": rec.get("arrays_sha256")})

    driver_meta = {
        "contract": TWO_PROCESS_CONTRACT,
        "driver": "solutions/A/run_n0_synthetic.py --mode two-process",
        "driver_pid": parent_pid,
        "started_at": runs[0]["driver_started_at"],
        "finished_at": runs[-1]["driver_finished_at"],
        "runs": runs,
        "note": "driver 记录的子进程退出码 = worker_meta.exit_code（已逐项核对）",
    }
    args.run1 = os.path.join(runs_dir, "run1")
    args.run2 = os.path.join(runs_dir, "run2")
    args.driver_meta = driver_meta
    code = run_combine(args)
    if code == 0:
        print(json.dumps({
            "mode": "two-process", "out": out, "exit_code": 0,
            "pids": [r["pid"] for r in runs],
            "driver_exit_codes": [r["exit_code"] for r in runs],
        }, ensure_ascii=False))
    return code


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A-Q1-N0 synthetic two-process entry")
    ap.add_argument("--mode", choices=("worker", "combine", "two-process"),
                    required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-index", type=int, choices=(1, 2), default=1)
    ap.add_argument("--run1")
    ap.add_argument("--run2")
    ap.add_argument("--runs-dir")
    ap.add_argument("--config", default=str(N0.CONFIG_PATH),
                    help="求解器数据配置（E0-C/E0-S config.json）")
    ap.add_argument("--n0-config",
                    default=os.path.join(_repo_root(), "experiments", "A",
                                         "A-Q1-E0", "n0", "n0_config.json"),
                    help="冻结的 N0 决策配置（LF SHA256 绑定）")
    ap.add_argument("--prereg",
                    default=os.environ.get(
                        "E0N0_PREREG",
                        os.path.join(_repo_root(), "checks", "A", "e0_n0_prereg.json")))
    ap.add_argument("--oracle",
                    default=os.path.join(_repo_root(), "checks", "A",
                                         "e0_c_data_oracle.json"))
    ap.add_argument("--prototype",
                    default=os.path.join(_repo_root(), "experiments", "A",
                                         "A-Q1-E0", "n0", "synthetic",
                                         "n0_synthetic_results.json"))
    ap.add_argument("--seed", type=int, default=N0.SYNTH_SEED)
    ap.add_argument("--reuse-prototype",
                    help="测试/复算：复用既有合成原型 JSON（跳过求解）")
    ap.add_argument("--reuse-phase-evidence",
                    help="测试/复算：复用既有相位证据 JSON（跳过重算）")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    if args.mode == "worker":
        return run_worker(args)
    if args.mode == "combine":
        if not args.run1 or not args.run2:
            ap.error("--mode combine 需要 --run1/--run2")
        return run_combine(args)
    if not args.runs_dir:
        ap.error("--mode two-process 需要 --runs-dir")
    return run_two_process(args)


if __name__ == "__main__":
    sys.exit(main())
