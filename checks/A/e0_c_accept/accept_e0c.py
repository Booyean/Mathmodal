#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E0-C 独立验收检查器（E0-PREREG-3）。

对象：`dsh` 交付的 E0-C 真实校准先导产物目录（`e0c_results.json`、
`e0c_arrays.npz`、`e0c_air_loo.json`、`e0c_frozen.json`、`run.log`、
`SHA256SUMS.txt`）。本检查器**不导入任何生产求解器**，只读交付数组与冻结的
预登记常量，独立重算可判定量并逐门比对。

判据来源：`checks/A/e0_c_prereg.json`（E0-PREREG-3 冻结常量）与
`checks/A/e0_c_data_oracle.json`（96 个 `.dat` 的身份清单）。

只依赖 Python 标准库：`.npz` 用 `zipfile` + `struct`/`array` 直接解析，避免
numpy 版本差异影响复算口径。

用法：
    python checks/A/e0_c_accept/accept_e0c.py --results-dir <dir> \
        --report <out.json> [--repo <repo-root>] [--e0s-results <json>]

退出码：0 = PASS；1 = FAIL；2 = 证据不足（INSUFFICIENT）；3 = 用法/环境错误。
"""

from __future__ import annotations

import argparse
import array
import ast
import datetime
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

C0_M_S = 299792458.0
TP_NS = 1000.0
PSLR_HALF_M = 0.1606031

REQUIRED_FILES = (
    "e0c_results.json",
    "e0c_arrays.npz",
    "e0c_air_loo.json",
    "SHA256SUMS.txt",
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# C12 独立运行证据契约（E0-C-C12-REPEAT-1，见 checks/A/e0_c_repeat_contract.json）。
# 契约缺失时退回本文件的默认值：两次独立进程、各自交付数组/结果文件与独立时间窗。
DEFAULT_REPEAT_CONTRACT = {
    "n_runs": 2,
    "required_run_fields": ["run_id", "pid", "started_at", "finished_at",
                            "results_file", "results_sha256",
                            "arrays_file", "arrays_sha256", "wall_time_s"],
    "provenance_must_differ": ["run_id", "pid", "started_at", "finished_at",
                               "arrays_file", "results_file"],
}


def load_repeat_contract(prereg_path: str):
    """Load the C12 amendment contract next to the frozen prereg, if present."""
    path = os.path.join(os.path.dirname(prereg_path), "e0_c_repeat_contract.json")
    if not os.path.exists(path):
        return path, dict(DEFAULT_REPEAT_CONTRACT)
    doc = load_json(path)
    merged = dict(DEFAULT_REPEAT_CONTRACT)
    merged.update(doc)
    return path, merged



# --------------------------------------------------------------------------- #
# 基础 I/O
# --------------------------------------------------------------------------- #
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_git_text(path: str) -> str:
    """SHA256 of text content with CRLF normalised to LF (git blob semantics)."""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def load_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def git_show_bytes(repo: str, ref: str, path: str):
    """Return blob bytes via `git show ref:path`, or None."""
    fd, tmp = tempfile.mkstemp(prefix="e0cgit")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo,
                               stdout=f, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return None
        with open(tmp, "rb") as f:
            return f.read()
    except OSError:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 纯标准库 .npy / .npz 读取
# --------------------------------------------------------------------------- #
class NpzFile:
    """Minimal .npz reader for '<f8' and '<c16' arrays (C-order)."""

    def __init__(self, path: str):
        self.path = path
        self._zip = zipfile.ZipFile(path)
        self._members = list(self._zip.namelist())
        self._alias = {}
        for n in self._members:
            self._alias[n] = n
            if n.endswith(".npy"):
                self._alias.setdefault(n[:-4], n)
        self.names = set(self._alias)
        self._cache = {}

    def __contains__(self, name: str) -> bool:
        return name in self._alias

    def read(self, name: str):
        """Return (shape, flat list) — flat holds interleaved re/im for c16."""
        if name in self._cache:
            return self._cache[name]
        if name not in self._alias:
            raise KeyError(f"npz 缺少成员 {name!r}")
        data = self._zip.read(self._alias[name])
        shape, kind, flat = _parse_npy(data, name)
        self._cache[name] = (shape, kind, flat)
        return self._cache[name]

    def close(self):
        self._zip.close()


def _parse_npy(data: bytes, name: str):
    magic = b"\x93NUMPY"
    if data[:6] != magic:
        raise ValueError(f"{name}: 不是 .npy")
    major = data[6]
    if major == 1:
        hlen = struct.unpack("<H", data[8:10])[0]
        off = 10
    elif major in (2, 3):
        hlen = struct.unpack("<I", data[8:12])[0]
        off = 12
    else:
        raise ValueError(f"{name}: 未知 .npy 版本 {major}")
    header = data[off:off + hlen].decode("latin1")
    meta = ast.literal_eval(header.strip())
    descr = meta["descr"]
    shape = tuple(int(x) for x in meta["shape"])
    if meta.get("fortran_order"):
        raise ValueError(f"{name}: 不支持 Fortran 顺序")
    n = 1
    for s in shape:
        n *= s
    payload = data[off + hlen:]
    if descr == "<f8" or descr == "|f8":
        need = n * 8
        if len(payload) < need:
            raise ValueError(f"{name}: float64 载荷不足")
        arr = array.array("d")
        arr.frombytes(payload[:need])
        if sys.byteorder != "little":
            arr.byteswap()
        return shape, "f8", arr
    if descr == "<c16" or descr == "|c16":
        need = n * 16
        if len(payload) < need:
            raise ValueError(f"{name}: complex128 载荷不足")
        arr = array.array("d")
        arr.frombytes(payload[:need])
        if sys.byteorder != "little":
            arr.byteswap()
        return shape, "c16", arr
    raise ValueError(f"{name}: 未登记的 dtype {descr!r}（预登记只允许 <f8/<c16）")


def _check_finite(flat, kind: str):
    if kind == "c16":
        for v in flat:
            if not math.isfinite(v):
                return False
        return True
    for v in flat:
        if not math.isfinite(v):
            return False
    return True


def _abs2(flat, idx: int) -> float:
    re_ = flat[2 * idx]
    im_ = flat[2 * idx + 1]
    return re_ * re_ + im_ * im_


# --------------------------------------------------------------------------- #
# 验收检查器
# --------------------------------------------------------------------------- #
class Checker:
    def __init__(self, results_dir, prereg, prereg_path, oracle, repo=None,
                 e0s_path=None, repeat_contract=None):
        self.dir = results_dir
        self.prereg = prereg
        self.prereg_path = prereg_path
        self.oracle = oracle
        self.repo = repo
        self.e0s_path = e0s_path
        if repeat_contract is None:
            self.repeat_contract_path, repeat_contract = load_repeat_contract(
                prereg_path)
        else:
            self.repeat_contract_path = os.path.join(
                os.path.dirname(prereg_path), "e0_c_repeat_contract.json")
        self.repeat_contract = repeat_contract
        self.results = None
        self.air_loo = None
        self.npz = None
        self.checks = []
        self._arrays = {}
        self._notes = []
        self._load_error = None

    # -- plumbing ---------------------------------------------------------- #
    def add(self, cid: str, blocking: bool, status: str, detail):
        self.checks.append({"id": cid, "blocking": bool(blocking),
                            "status": status, "detail": detail})

    def run(self, cid: str, blocking: bool, fn):
        try:
            status, detail = fn()
        except Exception as exc:  # 证据不足，而不是伪装通过
            status, detail = "insufficient", f"{type(exc).__name__}: {exc}"
        self.add(cid, blocking, status, detail)
        return status

    # -- 载入 --------------------------------------------------------------- #
    def load(self):
        missing = [f for f in REQUIRED_FILES
                   if not os.path.exists(os.path.join(self.dir, f))]
        if missing:
            self._load_error = f"缺少必需文件: {missing}"
            return
        try:
            self.results = load_json(os.path.join(self.dir, "e0c_results.json"))
            self.air_loo = load_json(os.path.join(self.dir, "e0c_air_loo.json"))
            self.npz = NpzFile(os.path.join(self.dir, "e0c_arrays.npz"))
        except Exception as exc:
            self._load_error = f"交付 JSON/NPZ 不可解析: {type(exc).__name__}: {exc}"

    def arr(self, key: str):
        if key not in self._arrays:
            self._arrays[key] = self.npz.read(key)
        return self._arrays[key]

    # -- C1 锚点 ------------------------------------------------------------ #
    def c1(self):
        a = self.prereg["anchors"]
        r = self.results
        got = {
            "config_sha256": r.get("config_sha256"),
            "plan_sha256": r.get("plan_sha256"),
            "split_sha256": r.get("split_sha256"),
            "e0_s_results_sha256": r.get("e0_s_results_sha256"),
        }
        want = {
            "config_sha256": a["config_sha256"],
            "plan_sha256": a["plan_sha256"],
            "split_sha256": a["split_sha256"],
            "e0_s_results_sha256": a["e0_s_results_sha256"],
        }
        bad = {k: {"expected": want[k], "actual": got[k]}
               for k in want if got[k] != want[k]}
        if r.get("fold_gate_contract_version") != a["fold_gate_contract_version"]:
            bad["fold_gate_contract_version"] = {
                "expected": a["fold_gate_contract_version"],
                "actual": r.get("fold_gate_contract_version")}
        detail = {"mismatches": bad}
        if self.repo:
            git_checked = {}
            for name, path in (("config.json", "experiments/A/A-Q1-E0/config.json"),
                               ("PLAN.md", "experiments/A/A-Q1-E0/PLAN.md"),
                               ("split", "coordination/A_Q1_SPLIT.json"),
                               ("e0_s_results",
                                "experiments/A/A-Q1-E0/s1s2/results/e0_s1s2_results.json")):
                blob = git_show_bytes(self.repo, r.get("main_commit") or "HEAD", path)
                if blob is None:
                    git_checked[name] = "unavailable"
                else:
                    git_checked[name] = hashlib.sha256(blob).hexdigest()
            detail["git_recomputed_at_main"] = git_checked
            exp_git = {
                "config.json": a["config_sha256"],
                "PLAN.md": a["plan_sha256"],
                "split": a["split_sha256"],
                "e0_s_results": a["e0_s_results_sha256"],
            }
            for name, sha in git_checked.items():
                if sha != "unavailable" and sha != exp_git[name]:
                    bad[f"git:{name}"] = {"expected": exp_git[name], "actual": sha}
            detail["mismatches"] = bad
        if bad:
            return "fail", detail
        return "pass", detail

    # -- C2 实现身份 -------------------------------------------------------- #
    def c2(self):
        r = self.results
        bad = []
        for f in ("implementation_sha", "parent_commit", "main_commit"):
            if not HEX40.match(str(r.get(f, ""))):
                bad.append(f"{f} 不是 40 位小写 hex: {r.get(f)!r}")
        impl = r.get("implementation_sha")
        if r.get("results_commit") and r.get("results_commit") == impl:
            bad.append("implementation_sha 与 results_commit 相同（自引用）")
        detail = {"implementation_sha": impl, "parent_commit": r.get("parent_commit"),
                  "main_commit": r.get("main_commit"), "problems": bad}
        if self.repo and HEX40.match(str(impl or "")):
            parent = git_show_bytes(self.repo, f"{impl}^", "AGENTS.md")
            # 用 `git rev-parse` 判定存在性与父子关系
            def rev_parse(expr):
                fd, tmp = tempfile.mkstemp(prefix="e0crev")
                os.close(fd)
                try:
                    with open(tmp, "wb") as f:
                        p = subprocess.run(["git", "rev-parse", expr], cwd=self.repo,
                                           stdout=f, stderr=subprocess.DEVNULL)
                    if p.returncode != 0:
                        return None
                    with open(tmp, "r", encoding="utf-8", errors="replace") as f:
                        return f.read().strip()
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            detail["git_parent_of_impl"] = rev_parse(f"{impl}^")
            detail["git_impl_exists"] = rev_parse(f"{impl}^{{commit}}") is not None
            if detail["git_parent_of_impl"] not in (None, "unknown") and \
                    detail["git_parent_of_impl"] != r.get("parent_commit"):
                detail["advisory"] = "parent_commit 与 git 实际父提交不同"
        if bad:
            return "fail", detail
        return "pass", detail

    # -- C3 边界白名单 ------------------------------------------------------ #
    def c3(self):
        wl = self.prereg["whitelist"]
        allowed = set(wl["groups"])
        groups = self.results.get("groups") or []
        keys = [g.get("group_key") for g in groups]
        problems = []
        if len(keys) != len(set(keys)):
            problems.append("group_key 重复")
        extra = sorted(set(keys) - allowed)
        missing = sorted(allowed - set(keys))
        if extra:
            problems.append(f"出现白名单之外的组: {extra}")
        if missing:
            problems.append(f"缺少白名单组: {missing}")
        # split 标签
        want_split = self.prereg["target_groups"]
        for g in groups:
            k = g.get("group_key")
            if k in want_split:
                if g.get("split") != want_split[k]["split"]:
                    problems.append(f"{k}: split={g.get('split')!r} 应为 "
                                    f"{want_split[k]['split']!r}")
            elif k in allowed and g.get("split") not in ("air", None):
                problems.append(f"{k}: 空场组 split 应为 'air'/null，实为 {g.get('split')!r}")
        # 禁止对象（组名/输入路径/日志）
        for pat in wl["forbidden_patterns"]:
            for k in keys:
                if pat in (k or ""):
                    problems.append(f"组名命中禁止对象 {pat!r}: {k}")
            for row in (self.results.get("inputs") or []):
                if pat in str(row.get("rel_path", "")):
                    problems.append(f"输入路径命中禁止对象 {pat!r}: {row.get('rel_path')}")
        logp = os.path.join(self.dir, "run.log")
        if os.path.exists(logp):
            with open(logp, "r", encoding="utf-8", errors="replace") as f:
                log = f.read()
            for pat in wl["forbidden_patterns"]:
                if pat in log:
                    problems.append(f"run.log 命中禁止对象 {pat!r}")
        else:
            problems.append("run.log 不存在")
        detail = {"n_groups": len(groups), "extra": extra, "missing": missing,
                  "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C4 数据身份 -------------------------------------------------------- #
    def c4(self):
        o = self.oracle
        exp = {}
        for g, info in o["groups"].items():
            for row in info["files"]:
                exp[row["rel_path"]] = (row["size_bytes"], row["sha256"])
        inputs = self.results.get("inputs")
        problems = []
        source = None
        got = {}
        if inputs:
            source = "results.inputs"
            for row in inputs:
                got[row.get("rel_path")] = (row.get("size_bytes"), row.get("sha256"))
        else:
            sums = os.path.join(self.dir, "SHA256SUMS.txt")
            if os.path.exists(sums):
                source = "SHA256SUMS.txt"
                with open(sums, "r", encoding="utf-8-sig", errors="replace") as f:
                    for line in f:
                        parts = line.strip().split(None, 1)
                        if len(parts) != 2:
                            continue
                        sha, rel = parts[0].lower(), parts[1].strip().lstrip("*")
                        if rel.endswith(".dat"):
                            got[rel] = None, sha
        if source is None:
            return "insufficient", "既无 results.inputs 也无含 .dat 的 SHA256SUMS.txt，无法核验输入身份"
        extra = sorted(set(got) - set(exp))
        missing = sorted(set(exp) - set(got))
        if extra:
            problems.append(f"白名单外/多余输入 {extra[:5]}（共 {len(extra)}）")
        if missing:
            problems.append(f"缺少输入清单 {missing[:5]}（共 {len(missing)}）")
        bad_sha = [p for p in exp if p in got and got[p][1] != exp[p][1]]
        bad_size = [p for p in exp if p in got and got[p][0] is not None
                    and got[p][0] != exp[p][0]]
        if bad_sha:
            problems.append(f"SHA256 不符 {len(bad_sha)} 个，例 {bad_sha[:3]}")
        if bad_size:
            problems.append(f"size 不符 {len(bad_size)} 个，例 {bad_size[:3]}")
        total = sum(exp[p][0] for p in exp)
        if len(exp) != self.prereg["whitelist"]["total_files"]:
            problems.append("oracle 文件数异常")
        detail = {"source": source, "expected_files": len(exp), "got_files": len(got),
                  "expected_bytes": self.prereg["whitelist"]["total_bytes"],
                  "computed_bytes": total, "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C5 方法范围（无 N0） ----------------------------------------------- #
    BANNED_TOKENS = ("alpha_hat", "fit_alpha", "subspace", "Subspace", "WLS",
                     "weighted_least_squares", "M0-DW-Subspace", "M0-Cal-Joint",
                     "M0-Rng-WLS")

    def c5(self):
        m = self.results.get("methods") or {}
        want = {
            "alpha_mode": "fixed_1.0",
            "n0_improvements_enabled": False,
            "adaptive_alpha": False,
            "subspace_suppression": False,
            "wls_ranging": False,
            "nonuniform_channel_weights": False,
        }
        problems = [f"{k}={m.get(k)!r} 应为 {v!r}" for k, v in want.items()
                    if m.get(k) != v]
        detail = {"declared": m, "problems": problems}
        if self.repo:
            blob = git_show_bytes(self.repo, self.results.get("implementation_sha", ""),
                                  "solutions/A/a_e0_c.py")
            if blob is not None:
                src = blob.decode("utf-8", errors="replace")
                hits = sorted({t for t in self.BANNED_TOKENS if t in src})
                detail["static_scan_hits"] = hits
                detail["static_scan_note"] = "关键词扫描仅作提示，不作为通过依据"
            else:
                detail["static_scan_note"] = "实现源码不可从 git 取得；仅核验声明"
        return ("fail" if problems else "pass"), detail

    # -- C6 E0-S 前置 ------------------------------------------------------- #
    def c6(self):
        path = self.e0s_path or os.path.join(
            self.repo or "", "experiments/A/A-Q1-E0/s1s2/results/e0_s1s2_results.json")
        if not os.path.exists(path):
            return "insufficient", f"找不到 E0-S 结果 JSON: {path}"
        sha = sha256_git_text(path)
        problems = []
        if sha != self.prereg["anchors"]["e0_s_results_sha256"]:
            problems.append("E0-S 结果文件 SHA256 与冻结验收版本不同")
        d = load_json(path)
        if d.get("overall_pass") is not True:
            problems.append(f"E0-S overall_pass={d.get('overall_pass')!r}")
        cases = d.get("cases") or []
        ids = [c.get("case_id") for c in cases]
        if ids != ["E0-S1", "E0-S2@0.42", "E0-S2@0.69"]:
            problems.append(f"E0-S 案例集不符: {ids}")
        for c in cases:
            if str(c.get("case_id", "")).startswith("E0-S2") and c.get("valid_rx") != 63:
                problems.append(f"{c.get('case_id')}: valid_rx={c.get('valid_rx')}")
        detail = {"path": path, "sha256": sha, "overall_pass": d.get("overall_pass"),
                  "cases": ids, "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- 按组取数组 --------------------------------------------------------- #
    def group_arrays(self, group_key: str, npz=None, amap=None):
        npz = npz or self.npz
        amap = amap if amap is not None else (self.results.get("array_map") or {})
        prefixes = amap.get("group_prefix") or {}
        if group_key not in prefixes:
            raise KeyError(f"array_map.group_prefix 未给出 {group_key!r}")
        p = prefixes[group_key]

        def read(name):
            if npz is self.npz:
                return self.arr(name)
            return npz.read(name)

        tau_shape, tau_kind, tau = read(f"{p}__tau_ns")
        dir_shape, dir_kind, tau_dir = read(f"{p}__tau_dir_ns")
        zb_shape, zb_kind, zb = read(f"{p}__z_before")
        za_shape, za_kind, za = read(f"{p}__z_after")
        d_shape, d_kind, d_m = read(f"{p}__d_m")
        pa_shape, pa_kind, pa = read(f"{p}__P_after")
        if tau_kind != "f8" or dir_kind != "f8" or d_kind != "f8" or pa_kind != "f8":
            raise ValueError(f"{group_key}: tau/tau_dir/d_m/P_after 必须为 float64")
        if zb_kind != "c16" or za_kind != "c16":
            raise ValueError(f"{group_key}: z_before/z_after 必须为 complex128")
        n = tau_shape[0]
        if len(dir_shape) != 1 or dir_shape[0] != 63:
            raise ValueError(f"{group_key}: tau_dir_ns 形状应为 (63,)，实为 {dir_shape}")
        if zb_shape != (63, n) or za_shape != (63, n):
            raise ValueError(f"{group_key}: z_* 形状应为 (63,{n})，实为 {zb_shape}/{za_shape}")
        if len(d_shape) != 1 or len(pa_shape) != 1 or d_shape[0] != pa_shape[0]:
            raise ValueError(f"{group_key}: d_m/P_after 形状不一致")
        return {"tau": list(tau), "tau_dir": list(tau_dir), "zb": zb, "za": za,
                "d_m": list(d_m), "P": list(pa), "n": n}

    def _recompute_group(self, g, npz=None, amap=None, eta=None):
        key = g["group_key"]
        A = self.group_arrays(key, npz=npz, amap=amap)
        tau = A["tau"]
        n = A["n"]
        bg_idx = [k for k, t in enumerate(tau) if 50.0 <= t <= 950.0]
        if not bg_idx:
            raise ValueError(f"{key}: tau 网格不含背景代理窗 [50,950] ns")
        bg_sum = 0.0
        for i in range(63):
            base = i * n
            acc = 0.0
            for k in bg_idx:
                acc += _abs2(A["za"], base + k)
            bg_sum += acc
        bg = bg_sum / (63.0 * len(bg_idx))
        if not (bg > 0):
            raise ValueError(f"{key}: BG_proxy 非正 ({bg})")

        def wrap(x):
            return (x + TP_NS / 2.0) % TP_NS - TP_NS / 2.0

        win_cnt = 0
        supp_before = 0.0
        supp_after = 0.0
        for i in range(63):
            base = i * n
            td = A["tau_dir"][i]
            idxs = [k for k, t in enumerate(tau) if abs(wrap(t - td)) <= 1.0]
            win_cnt += len(idxs)
            for k in idxs:
                supp_before += _abs2(A["zb"], base + k)
                supp_after += _abs2(A["za"], base + k)
        if not (supp_after > 0):
            raise ValueError(f"{key}: 直射波窗内 after 功率非正")

        d_hat = float(g["d_hat_m"])
        tau_tgt = 2.0 * d_hat / C0_M_S * 1e9
        k_tgt = min(range(n), key=lambda k: abs(tau[k] - tau_tgt))
        p_tgt = sum(_abs2(A["za"], i * n + k_tgt) for i in range(63)) / 63.0
        pnr_db = 10.0 * math.log10(p_tgt / bg)
        supp_db = 10.0 * math.log10(supp_before / supp_after)

        d_m = A["d_m"]
        P = A["P"]
        if len(P) < 5:
            raise ValueError(f"{key}: P_after 点数过少")
        pk = min(range(len(d_m)), key=lambda k: abs(d_m[k] - d_hat))
        p_peak = P[pk]
        sidelobe = [P[k] for k in range(len(d_m))
                    if abs(d_m[k] - d_hat) > PSLR_HALF_M and 0.15 <= d_m[k] <= 2.0]
        if not sidelobe:
            raise ValueError(f"{key}: 旁瓣区为空")
        pslr_db = 10.0 * math.log10(p_peak / max(sidelobe))

        # 测距判定（按目标类型规则独立重选）
        typ = g.get("target_type")
        if typ == "metal":
            d_sel = d_m[max(range(len(P)), key=lambda k: P[k])]
            rule = "global_argmax"
        elif typ == "wall":
            if eta is None:
                eta = float(self.results.get("eta_wall",
                                             self.prereg["eta_wall_default"]))
            eta = float(eta)
            pmax = max(P)
            thr = max(eta * pmax, 10.0 ** 0.6 * bg)
            cand = None
            for k in range(1, len(P) - 1):
                if P[k] >= P[k - 1] and P[k] >= P[k + 1] and P[k] >= thr:
                    cand = d_m[k]
                    break
            if cand is None:
                raise ValueError(f"{key}: 墙体首峰规则无候选（thr={thr:.6g}, pmax={pmax:.6g}）")
            d_sel = cand
            rule = "wall_first_peak"
        else:
            raise ValueError(f"{key}: target_type={typ!r} 未登记")
        abs_err = abs(d_sel - float(g["d_true_cm"]) / 100.0) * 100.0
        return {"bg_proxy": bg, "pnr_db": pnr_db, "supp_dw_win_db": supp_db,
                "pslr_db": pslr_db, "d_hat_recomputed_m": d_sel, "rule": rule,
                "abs_err_recomputed_cm": abs_err, "window_samples": win_cnt,
                "tau_tgt_ns": tau_tgt, "k_tgt": k_tgt}

    # -- C7 有效通道与有限性 ------------------------------------------------ #
    def c7(self):
        problems = []
        groups = self.results.get("groups") or []
        target_keys = set(self.prereg["target_groups"])
        for g in groups:
            if g.get("valid_rx") != 63 or g.get("finite") is not True:
                problems.append(f"{g.get('group_key')}: valid_rx={g.get('valid_rx')} "
                                f"finite={g.get('finite')}")
        finite_checked = []
        for key in sorted(target_keys):
            if key not in {g.get("group_key") for g in groups}:
                continue
            A = self.group_arrays(key)
            ok = (_check_finite(A["zb"], "c16") and _check_finite(A["za"], "c16")
                  and all(math.isfinite(v) for v in A["tau"] + A["tau_dir"]
                          + A["d_m"] + A["P"]))
            finite_checked.append({"group": key, "arrays_finite": ok})
            if not ok:
                problems.append(f"{key}: 交付数组含 NaN/Inf")
        return ("fail" if problems else "pass"), {"problems": problems,
                                                  "arrays_finite": finite_checked}

    # -- C8 空场 LOO -------------------------------------------------------- #
    def c8(self):
        pr = self.prereg["loo"]
        grid_want = pr["lambda_grid"]
        default = tuple(pr["default"])
        loo = self.air_loo
        folds = loo.get("folds") or []
        air = self.prereg["air_groups"]
        problems = []
        if [f.get("held_out") for f in folds] != air:
            problems.append(f"折顺序与预登记的 10 组空场顺序不一致: "
                            f"{[f.get('held_out') for f in folds]}")
        grid = loo.get("grid") or []
        if len(grid) != 9:
            problems.append(f"网格应为 9 对，实为 {len(grid)}")
        got_pairs = [tuple(g.get("lambdas", [])) for g in grid]
        want_pairs = [(a, b) for a in grid_want for b in grid_want]
        if got_pairs != want_pairs:
            problems.append(f"网格顺序/取值不符，期望 {want_pairs}，实为 {got_pairs}")
        if default not in got_pairs:
            problems.append("网格缺少默认对 (1e-3, 1e-3)")
        amap = (self.results.get("array_map") or {})
        pre = amap.get("air_loo_prefix") or "air_loo"
        p_cal = self.arr(f"{pre}__p_cal")
        p_sup = self.arr(f"{pre}__p_sup")
        if p_cal[0] != (9, 10, 63) or p_sup[0] != (9, 10, 63):
            raise ValueError(f"p_cal/p_sup 形状应为 (9,10,63)，实为 {p_cal[0]}/{p_sup[0]}")
        cal = p_cal[2]
        sup = p_sup[2]

        supp = [[0.0] * 10 for _ in range(9)]
        for f in range(9):
            for gidx in range(10):
                num = 0.0
                den = 0.0
                for c in range(63):
                    num += cal[(f * 10 + gidx) * 63 + c]
                    den += sup[(f * 10 + gidx) * 63 + c]
                if not (num > 0 and den > 0):
                    raise ValueError(f"p_cal/p_sup 非正: pair {f} fold {gidx}")
                supp[f][gidx] = 10.0 * math.log10(num / den)

        def median(v):
            s = sorted(v)
            n = len(s)
            return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])

        J = []
        mins = []
        meds = []
        for f in range(9):
            J.append(median(supp[f]) + 0.5 * min(supp[f]))
            mins.append(min(supp[f]))
            meds.append(median(supp[f]))

        # 逐折比对
        for f in range(9):
            jf = grid[f].get("folds") or []
            if len(jf) != 10:
                problems.append(f"grid[{f}].folds 长度 {len(jf)} != 10")
                continue
            for gidx in range(10):
                got = jf[gidx].get("supp_db")
                if got is None or abs(float(got) - supp[f][gidx]) > pr["tolerances_db"]:
                    problems.append(f"grid[{f}].folds[{gidx}].supp_db={got} "
                                    f"与独立重算 {supp[f][gidx]:.9f} 不符")

        best = max(J)
        near = [f for f in range(9) if best - J[f] < pr["tie_tol_db"]]
        if default not in got_pairs:
            chosen_idx = None
        else:
            d_idx = got_pairs.index(default)
            di, dj = divmod(d_idx, 3)

            def key(f):
                i, j = divmod(f, 3)
                return (got_pairs[f][0] + got_pairs[f][1],
                        abs(i - di) + abs(j - dj),
                        got_pairs[f])
            chosen_idx = min(near, key=key)
        chosen = got_pairs[chosen_idx] if chosen_idx is not None else None
        d_idx = got_pairs.index(default)
        switch = ((best - J[d_idx] >= pr["switch_margin_db"])
                  or (mins[d_idx] < self.prereg["gates"]["air_loo_eligible_min_db"]
                      and mins[chosen_idx] >= self.prereg["gates"]["air_loo_eligible_min_db"]))
        selected = chosen if switch else default
        sel_idx = got_pairs.index(selected) if selected in got_pairs else None

        got_sel = tuple(loo.get("selected") or [])
        if got_sel != selected:
            problems.append(f"selected={got_sel} 与独立判定 {selected} 不符"
                            f"（switch={switch}）")
        if bool(loo.get("switched")) != bool(switch):
            problems.append(f"switched={loo.get('switched')} 与独立判定 {switch} 不符")
        if sel_idx is not None:
            if loo.get("min_supp_db") is None or \
                    abs(float(loo["min_supp_db"]) - mins[sel_idx]) > pr["tolerances_db"]:
                problems.append(f"min_supp_db={loo.get('min_supp_db')} 与重算 "
                                f"{mins[sel_idx]:.9f} 不符")
            if loo.get("median_supp_db") is None or \
                    abs(float(loo["median_supp_db"]) - meds[sel_idx]) > pr["tolerances_db"]:
                problems.append(f"median_supp_db={loo.get('median_supp_db')} 与重算 "
                                f"{meds[sel_idx]:.9f} 不符")
            for f in range(9):
                gf = grid[f]
                if gf.get("j_air_db") is None or \
                        abs(float(gf["j_air_db"]) - J[f]) > pr["tolerances_db"]:
                    problems.append(f"grid[{f}].j_air_db={gf.get('j_air_db')} 与重算 "
                                    f"{J[f]:.9f} 不符")
                if gf.get("min_db") is None or \
                        abs(float(gf["min_db"]) - mins[f]) > pr["tolerances_db"]:
                    problems.append(f"grid[{f}].min_db 与重算不符")
                if gf.get("median_db") is None or \
                        abs(float(gf["median_db"]) - meds[f]) > pr["tolerances_db"]:
                    problems.append(f"grid[{f}].median_db 与重算不符")

        # 门槛分类
        g = self.prereg["gates"]
        if mins[sel_idx] >= g["air_loo_eligible_min_db"]:
            elig = "eligible"
        elif mins[sel_idx] >= g["air_loo_hard_stop_db"]:
            elig = "gray"
        else:
            elig = "hard_stop"
        if str(loo.get("eligibility")) != elig:
            problems.append(f"eligibility={loo.get('eligibility')!r} 与独立判定 {elig!r} 不符")
        detail = {"j_air": [round(x, 9) for x in J], "min": [round(x, 9) for x in mins],
                  "selected": list(selected), "switched": switch, "eligibility": elig,
                  "near_tie_grid": [list(got_pairs[f]) for f in near],
                  "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C9 目标组门控 ------------------------------------------------------ #
    def c9(self):
        g = self.prereg["gates"]
        problems = []
        rows = []
        tgt = self.prereg["target_groups"]
        for key, info in tgt.items():
            grp = next((x for x in (self.results.get("groups") or [])
                        if x.get("group_key") == key), None)
            if grp is None:
                problems.append(f"缺少目标组 {key}")
                continue
            if grp.get("target_type") != info["type"]:
                problems.append(f"{key}: target_type={grp.get('target_type')!r}")
            if grp.get("d_true_cm") != info["d_true_cm"]:
                problems.append(f"{key}: d_true_cm={grp.get('d_true_cm')!r} 应为 "
                                f"{info['d_true_cm']}")
            d_hat = float(grp.get("d_hat_m", float("nan")))
            d_true = float(info["d_true_cm"]) / 100.0
            abs_err = abs(d_hat - d_true) * 100.0
            got_err = float(grp.get("abs_err_cm", float("nan")))
            if not math.isfinite(got_err) or abs(got_err - abs_err) > 1e-9:
                problems.append(f"{key}: abs_err_cm={grp.get('abs_err_cm')!r} "
                                f"与 |d_hat-d_true| 重算 {abs_err:.9f} 不符")
            checks = {
                "pslr_ge_3db": float(grp.get("pslr_db", -1e9)) >= g["pslr_min_db"],
                "pnr_ge_6db": float(grp.get("pnr_db", -1e9)) >= g["pnr_min_db"],
                "abs_err_eligible": abs_err <= g["cal_err_eligible_max_cm"],
                "abs_err_not_hard": abs_err <= g["cal_err_hard_stop_cm"],
            }
            declared = grp.get("gate_results") or {}
            for name, val in checks.items():
                if name in declared and bool(declared[name]) != bool(val):
                    problems.append(f"{key}: gate_results.{name}={declared[name]} "
                                    f"与独立判定 {val} 不符")
            # 门控本身：PSLR/PNR 无灰区，任一不达标即硬停；abs_err 超过硬停线亦为硬停。
            # 灰区只对 abs_err 成立（5.0 < err <= 10.71 cm），不掩盖 PSLR/PNR 失败。
            if not checks["pslr_ge_3db"]:
                problems.append(f"{key}: PSLR={grp.get('pslr_db')!r} dB < "
                                f"{g['pslr_min_db']} dB（硬停）")
            if not checks["pnr_ge_6db"]:
                problems.append(f"{key}: PNR={grp.get('pnr_db')!r} dB < "
                                f"{g['pnr_min_db']} dB（硬停）")
            if not checks["abs_err_not_hard"]:
                problems.append(f"{key}: abs_err={abs_err:.9f} cm > "
                                f"{g['cal_err_hard_stop_cm']} cm（硬停）")
            if not checks["pslr_ge_3db"] or not checks["pnr_ge_6db"] \
                    or not checks["abs_err_not_hard"]:
                status = "hard_stop"
            elif not checks["abs_err_eligible"]:
                status = "gray"
            else:
                status = "eligible"
            want_status = {"eligible": "eligible", "gray": "not_eligible_for_freeze",
                           "hard_stop": "hard_stop"}[status]
            if grp.get("status") != want_status:
                problems.append(f"{key}: status={grp.get('status')!r} 与独立分类 "
                                f"{want_status!r} 不符")
            rows.append({"group": key, "abs_err_cm": abs_err, "status": status,
                         "pslr_db": grp.get("pslr_db"), "pnr_db": grp.get("pnr_db")})
        detail = {"groups": rows, "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C10 指标独立重算 --------------------------------------------------- #
    def c10(self):
        pr = self.prereg["tolerances"]
        problems = []
        rows = []
        for key in self.prereg["target_groups"]:
            grp = next((x for x in (self.results.get("groups") or [])
                        if x.get("group_key") == key), None)
            if grp is None:
                problems.append(f"缺少目标组 {key}")
                continue
            rc = self._recompute_group(grp)
            comparisons = (
                ("supp_dw_win_db", rc["supp_dw_win_db"], pr["db"]),
                ("pslr_db", rc["pslr_db"], pr["db"]),
                ("pnr_db", rc["pnr_db"], pr["db"]),
                ("abs_err_cm", rc["abs_err_recomputed_cm"], pr["cm"]),
                ("d_hat_m", rc["d_hat_recomputed_m"], pr["meters"]),
            )
            for field, want, tol in comparisons:
                got = grp.get(field)
                if got is None or not math.isfinite(float(got)) or \
                        abs(float(got) - want) > tol:
                    problems.append(f"{key}.{field}={got!r} 与独立重算 {want:.9f} 不符"
                                    f"（容差 {tol}）")
            rows.append({"group": key, "recomputed": {
                "supp_dw_win_db": round(rc["supp_dw_win_db"], 9),
                "pslr_db": round(rc["pslr_db"], 9),
                "pnr_db": round(rc["pnr_db"], 9),
                "d_hat_m": rc["d_hat_recomputed_m"],
                "abs_err_cm": round(rc["abs_err_recomputed_cm"], 9),
                "bg_proxy": rc["bg_proxy"],
                "window_samples": rc["window_samples"],
                "ranging_rule": rc["rule"]}})
        detail = {"groups": rows, "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C11 冻结完整性 ------------------------------------------------------ #
    def c11(self):
        problems = []
        fz_path = os.path.join(self.dir, "e0c_frozen.json")
        gates = self.prereg["gates"]
        cats = []
        for key in self.prereg["target_groups"]:
            grp = next((x for x in (self.results.get("groups") or [])
                        if x.get("group_key") == key), None)
            if grp is None:
                problems.append(f"缺少目标组 {key}")
                continue
            abs_err = abs(float(grp.get("d_hat_m")) -
                          float(grp.get("d_true_cm")) / 100.0) * 100.0
            hard = (abs_err > gates["cal_err_hard_stop_cm"]
                    or float(grp.get("pslr_db", -1e9)) < gates["pslr_min_db"]
                    or float(grp.get("pnr_db", -1e9)) < gates["pnr_min_db"]
                    or grp.get("valid_rx") != 63 or grp.get("finite") is not True)
            elig = (abs_err <= gates["cal_err_eligible_max_cm"]
                    and float(grp.get("pslr_db", -1e9)) >= gates["pslr_min_db"]
                    and float(grp.get("pnr_db", -1e9)) >= gates["pnr_min_db"]
                    and grp.get("valid_rx") == 63 and grp.get("finite") is True)
            cats.append("hard_stop" if hard else ("eligible" if elig else "gray"))
        loo = self.air_loo
        loo_cat = str(loo.get("eligibility"))
        freeze = self.results.get("freeze") or {}
        if "hard_stop" in cats or loo_cat == "hard_stop":
            want_status = "hard_stop"
        elif all(c == "eligible" for c in cats) and loo_cat == "eligible":
            want_status = "eligible"
        else:
            want_status = "not_eligible_for_freeze"
        got_status = freeze.get("status")
        if got_status != want_status:
            problems.append(f"freeze.status={got_status!r} 与逐门结论 {want_status!r} 不符")
        eta = self.results.get("eta_wall")
        if eta not in self.prereg["eta_wall_candidates"]:
            problems.append(f"eta_wall={eta!r} 不在预登记候选 "
                            f"{self.prereg['eta_wall_candidates']} 内")
        has_file = os.path.exists(fz_path)
        if want_status == "eligible":
            if not has_file:
                problems.append("状态为 eligible 但未写 e0c_frozen.json")
            else:
                fz = load_json(fz_path)
                sel = list(loo.get("selected") or [])
                got = list(fz.get("lambdas") or [])
                if len(got) != 2 or any(abs(a - b) > 0 for a, b in zip(got, sel)):
                    problems.append(f"冻结 λ={got} 与选定 λ={sel} 不符")
                if fz.get("eta_wall") != eta:
                    problems.append(f"冻结 eta_wall={fz.get('eta_wall')!r} 与结果 {eta!r} 不符")
                if fz.get("implementation_sha") != self.results.get("implementation_sha"):
                    problems.append("冻结文件 implementation_sha 与结果不符")
                if freeze.get("written") is not True:
                    problems.append("freeze.written 应为 true")
        else:
            if has_file:
                problems.append("未达可冻结状态却写出 e0c_frozen.json")
            if freeze.get("written") is True:
                problems.append("freeze.written=true 但状态不可冻结")
        detail = {"status_expected": want_status, "status_actual": got_status,
                  "eta_wall": eta, "frozen_file": has_file, "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C12 确定性证据 ------------------------------------------------------ #
    def _repeat_manifest(self):
        """Return (source, runs, error) for the two-independent-run evidence."""
        rr = self.results.get("repeat_run") or {}
        runs = rr.get("runs")
        if isinstance(runs, list) and runs:
            return "e0c_results.json#repeat_run.runs", runs, None
        path = os.path.join(self.dir, "e0c_repeat.json")
        if os.path.exists(path):
            try:
                man = load_json(path)
            except Exception as exc:
                return "e0c_repeat.json", None, (
                    f"e0c_repeat.json 不可解析: {type(exc).__name__}: {exc}")
            runs = man.get("runs") if isinstance(man, dict) else None
            if isinstance(runs, list) and runs:
                return "e0c_repeat.json#runs", runs, None
            return "e0c_repeat.json", None, "e0c_repeat.json 缺少 runs 列表"
        return None, None, None

    def _rel_file(self, rel):
        if not isinstance(rel, str) or not rel.strip():
            raise ValueError("路径为空")
        raw = rel.replace("\\", "/")
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            raise ValueError(f"不允许绝对路径: {rel!r}")
        norm = os.path.normpath(raw).replace("\\", "/")
        if norm == ".." or norm.startswith("../"):
            raise ValueError(f"路径逃出交付目录: {rel!r}")
        return os.path.join(self.dir, *norm.split("/")), norm

    @staticmethod
    def _parse_utc(value):
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        ts = datetime.datetime.fromisoformat(text)
        if ts.tzinfo is None:
            raise ValueError(f"时间戳缺少时区: {value!r}")
        return ts

    def c12(self):
        pr = self.prereg["tolerances"]
        contract = self.repeat_contract or DEFAULT_REPEAT_CONTRACT
        problems = []
        rr = self.results.get("repeat_run") or {}
        metrics = []
        for grp in self.results.get("groups") or []:
            metrics.append({k: grp.get(k) for k in (
                "group_key", "d_hat_m", "abs_err_cm", "supp_dw_win_db",
                "pslr_db", "pnr_db", "valid_rx", "finite")})
        digest = hashlib.sha256(canonical_json(metrics).encode("utf-8")).hexdigest()
        detail = {"duplicate_serialization_detected": False,
                  "run_evidence": "missing",
                  "metrics_sha256_recomputed": digest,
                  "metrics_sha256_reported": self.results.get("metrics_sha256")}
        if not rr:
            problems.append("缺少 repeat_run 证据块（两次运行一致性）")
        else:
            if rr.get("arrays_sha256") != self.results.get("arrays_sha256"):
                problems.append("repeat_run.arrays_sha256 与 arrays_sha256 不同")
            actual = sha256_file(os.path.join(self.dir, "e0c_arrays.npz"))
            if rr.get("arrays_sha256") != actual:
                problems.append("repeat_run.arrays_sha256 与实际 npz 文件不同")
            if rr.get("metrics_sha256") != self.results.get("metrics_sha256"):
                problems.append("repeat_run.metrics_sha256 与 metrics_sha256 不同")
            if rr.get("metrics_sha256") != digest:
                problems.append("repeat_run.metrics_sha256 与按 groups 规范化重算的摘要不同")
        if self.results.get("metrics_sha256") != digest:
            problems.append("metrics_sha256 与按 groups 规范化重算的摘要不同")

        source, runs, err = self._repeat_manifest()
        detail["manifest_source"] = source
        if err:
            problems.append(err)
        if not runs:
            # 只有同一批交付数组的重复序列化/哈希相等，不构成两次独立运行。
            detail["duplicate_serialization_detected"] = True
            hint = ""
            if isinstance(rr, dict):
                sig = sorted(k for k in rr if "serializ" in k.lower())
                if sig:
                    hint = f"；现有字段 {sig} 只证明同一批数组被序列化两次"
            problems.append("缺少两次独立运行证据：未提供 repeat_run.runs 或 "
                            "e0c_repeat.json" + hint)
            detail["problems"] = problems
            return "fail", detail

        need = int(contract.get("n_runs", 2))
        required = list(contract.get("required_run_fields")
                        or DEFAULT_REPEAT_CONTRACT["required_run_fields"])
        differ = list(contract.get("provenance_must_differ")
                      or DEFAULT_REPEAT_CONTRACT["provenance_must_differ"])
        if len(runs) != need:
            problems.append(f"独立运行次数应为 {need}，实为 {len(runs)}")
        recs = []
        for idx, rec in enumerate(runs[:need]):
            if not isinstance(rec, dict):
                problems.append(f"runs[{idx}] 不是对象")
                continue
            miss = [f for f in required if f not in rec]
            if miss:
                problems.append(f"runs[{idx}] 缺少字段 {miss}")
                continue
            ok = True
            for hf in ("results_sha256", "arrays_sha256"):
                if not HEX64.match(str(rec.get(hf) or "")):
                    problems.append(f"runs[{idx}].{hf} 不是 64 位小写 hex")
                    ok = False
            entry = {"run_id": rec.get("run_id"), "pid": rec.get("pid"),
                     "started_at": rec.get("started_at"),
                     "finished_at": rec.get("finished_at"),
                     "wall_time_s": rec.get("wall_time_s"),
                     "results_sha256": rec.get("results_sha256"),
                     "arrays_sha256": rec.get("arrays_sha256")}
            for kind in ("results", "arrays"):
                try:
                    path, norm = self._rel_file(rec[kind + "_file"])
                except (TypeError, ValueError) as exc:
                    problems.append(f"runs[{idx}].{kind}_file 非法: {exc}")
                    ok = False
                    continue
                entry[kind + "_file"] = norm
                entry["_" + kind + "_path"] = path
                if not os.path.exists(path):
                    problems.append(f"runs[{idx}].{kind}_file 不存在: {norm}")
                    ok = False
                    continue
                if sha256_file(path) != rec[kind + "_sha256"]:
                    problems.append(f"runs[{idx}].{kind}_sha256 与文件 {norm} 不符")
                    ok = False
            try:
                if float(rec.get("wall_time_s")) <= 0:
                    problems.append(f"runs[{idx}].wall_time_s 非正")
            except (TypeError, ValueError):
                problems.append(f"runs[{idx}].wall_time_s 不是数值")
            if ok:
                recs.append(entry)

        detail["run_evidence"] = "present"
        detail["runs"] = [{k: v for k, v in r.items() if not k.startswith("_")}
                          for r in recs]
        if len(recs) != need:
            detail["problems"] = problems
            return "fail", detail

        # 0) runs[0] 必须绑定本次交付的顶层文件
        top_npz = os.path.realpath(os.path.join(self.dir, "e0c_arrays.npz"))
        top_res = os.path.realpath(os.path.join(self.dir, "e0c_results.json"))
        if os.path.realpath(recs[0]["_arrays_path"]) != top_npz:
            problems.append("runs[0].arrays_file 不是本次交付的 e0c_arrays.npz")
        if os.path.realpath(recs[0]["_results_path"]) != top_res:
            problems.append("runs[0].results_file 不是本次交付的 e0c_results.json")

        # 1) 独立进程/时间窗/文件必须互不相同（重复序列化的特征）
        for field in differ:
            vals = [canonical_json(r.get(field)) for r in recs]
            if len(set(vals)) != len(vals):
                detail["duplicate_serialization_detected"] = True
                problems.append(f"两次运行的 {field} 相同 → 不是独立运行（重复序列化）")
        if len({os.path.realpath(r["_arrays_path"]) for r in recs}) != need or \
                len({os.path.realpath(r["_results_path"]) for r in recs}) != need:
            detail["duplicate_serialization_detected"] = True
            problems.append("两次运行复用同一数组/结果文件 → 重复序列化")
        try:
            windows = []
            for r in recs:
                s = self._parse_utc(r["started_at"])
                f_ = self._parse_utc(r["finished_at"])
                if not s < f_:
                    problems.append(f"run {r['run_id']}: started_at 不早于 finished_at")
                windows.append((s, f_))
            for i in range(len(windows) - 1):
                if windows[i][1] > windows[i + 1][0]:
                    problems.append("两次运行的时间窗重叠/顺序颠倒 → 不构成顺序独立复跑")
            for p in (r.get("pid") for r in recs):
                if not isinstance(p, int) or p <= 0:
                    problems.append(f"pid 非法: {p!r}")
        except (TypeError, ValueError) as exc:
            problems.append(f"运行时间戳不可解析: {exc}")

        # 2) 第二次运行的 JSON 必须与第一次一致，且绑定它自己的 npz
        second = recs[1]
        try:
            rep = load_json(second["_results_path"])
        except Exception as exc:
            problems.append(f"第二次运行结果不可解析: {type(exc).__name__}: {exc}")
            rep = None
        if rep is not None:
            rep_groups = rep.get("groups") or []
            base = {g.get("group_key"): g for g in (self.results.get("groups") or [])}
            got = {g.get("group_key"): g for g in rep_groups}
            if set(got) != set(base):
                problems.append(f"两次运行的组集合不同: 仅第一次 "
                                f"{sorted(set(base) - set(got))}，仅第二次 "
                                f"{sorted(set(got) - set(base))}")
            for key in base:
                if key not in got:
                    continue
                a, b = base[key], got[key]
                for field, tol in (("d_hat_m", pr["meters"]),
                                   ("abs_err_cm", pr["cm"]),
                                   ("supp_dw_win_db", pr["db"]),
                                   ("pslr_db", pr["db"]),
                                   ("pnr_db", pr["db"])):
                    av, bv = a.get(field), b.get(field)
                    if av is None and bv is None:
                        continue
                    if av is None or bv is None or abs(float(av) - float(bv)) > tol:
                        problems.append(f"{key}.{field}: 运行1={av!r} 运行2={bv!r} 不一致")
                for field in ("valid_rx", "finite"):
                    if a.get(field) != b.get(field):
                        problems.append(f"{key}.{field}: 运行1={a.get(field)!r} "
                                        f"运行2={b.get(field)!r} 不一致")
            rep_metrics = [{k: g.get(k) for k in (
                "group_key", "d_hat_m", "abs_err_cm", "supp_dw_win_db",
                "pslr_db", "pnr_db", "valid_rx", "finite")} for g in rep_groups]
            rep_digest = hashlib.sha256(
                canonical_json(rep_metrics).encode("utf-8")).hexdigest()
            if rep.get("metrics_sha256") != rep_digest:
                problems.append("第二次运行自身 metrics_sha256 与其 groups 重算不符")
            if rep_digest != digest:
                problems.append("两次运行的指标摘要不同（第一次与第二次结果不一致）")
            if not rep.get("arrays_sha256"):
                problems.append("第二次运行结果缺少 arrays_sha256，无法绑定其数组文件")
            elif rep["arrays_sha256"] != second["arrays_sha256"]:
                problems.append("第二次运行结果中的 arrays_sha256 与其 npz 文件不符")

            # 3) 用第二次运行的 npz 独立重算 C10 指标
            try:
                npz2 = NpzFile(second["_arrays_path"])
            except Exception as exc:
                problems.append(f"第二次运行 npz 不可解析: {type(exc).__name__}: {exc}")
                npz2 = None
            if npz2 is not None:
                try:
                    if self.npz is not None and set(npz2.names) != set(self.npz.names):
                        problems.append("两次运行的数组集合不同")
                    amap2 = rep.get("array_map") or self.results.get("array_map")
                    eta2 = rep.get("eta_wall", self.results.get("eta_wall"))
                    rows2 = []
                    for key in self.prereg["target_groups"]:
                        g1 = base.get(key)
                        if g1 is None:
                            continue
                        rc = self._recompute_group(g1, npz=npz2, amap=amap2, eta=eta2)
                        for field, want, tol in (
                                ("supp_dw_win_db", rc["supp_dw_win_db"], pr["db"]),
                                ("pslr_db", rc["pslr_db"], pr["db"]),
                                ("pnr_db", rc["pnr_db"], pr["db"]),
                                ("abs_err_cm", rc["abs_err_recomputed_cm"], pr["cm"]),
                                ("d_hat_m", rc["d_hat_recomputed_m"], pr["meters"])):
                            gotv = g1.get(field)
                            if gotv is None or abs(float(gotv) - want) > tol:
                                problems.append(f"{key}.{field} 与第二次运行数组重算 "
                                                f"{want:.9f} 不符（容差 {tol}）")
                        rows2.append({"group": key, "recomputed": {
                            "supp_dw_win_db": round(rc["supp_dw_win_db"], 9),
                            "pslr_db": round(rc["pslr_db"], 9),
                            "pnr_db": round(rc["pnr_db"], 9),
                            "d_hat_m": rc["d_hat_recomputed_m"],
                            "abs_err_cm": round(rc["abs_err_recomputed_cm"], 9)}})
                    detail["recomputed_from_second_run"] = rows2
                except Exception as exc:
                    problems.append(f"第二次运行数组重算失败: "
                                    f"{type(exc).__name__}: {exc}")
                finally:
                    npz2.close()

        detail["arrays_byte_identical_between_runs"] = (
            recs[0]["arrays_sha256"] == recs[1]["arrays_sha256"])
        detail["note"] = ("两次运行字节相同可接受（单线程确定性）；独立性由进程 PID、"
                          "运行时间窗与各自独立文件承载，不接受同一批数组的重复序列化")
        detail["problems"] = problems
        return ("fail" if problems else "pass"), detail

    # -- C13 资源预算 -------------------------------------------------------- #
    def c13(self):
        g = self.prereg["gates"]
        res = self.results.get("resource") or {}
        env = self.results.get("environment") or {}
        problems = []
        wall = res.get("wall_time_s")
        rss = res.get("peak_rss_mib")
        if wall is None or float(wall) > g["max_wall_s"]:
            problems.append(f"wall_time_s={wall!r} 超预算 {g['max_wall_s']} s")
        if rss is None or float(rss) > g["max_rss_mib"]:
            problems.append(f"peak_rss_mib={rss!r} 超预算 {g['max_rss_mib']} MiB")
        if res.get("single_process") is not True:
            problems.append(f"single_process={res.get('single_process')!r}")
        threads = env.get("threads") or {}
        for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "NUMEXPR_NUM_THREADS"):
            if str(threads.get(k)) != "1":
                problems.append(f"threads.{k}={threads.get(k)!r} 应为 '1'")
        detail = {"wall_time_s": wall, "peak_rss_mib": rss,
                  "single_process": res.get("single_process"), "threads": threads,
                  "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C14 证据完整 -------------------------------------------------------- #
    def c14(self):
        problems = []
        present = {}
        for f in REQUIRED_FILES:
            p = os.path.join(self.dir, f)
            present[f] = os.path.exists(p) and os.path.getsize(p) > 0
            if not present[f]:
                problems.append(f"{f} 缺失或为空")
        fz = os.path.join(self.dir, "e0c_frozen.json")
        present["e0c_frozen.json"] = os.path.exists(fz)
        sums_path = os.path.join(self.dir, "SHA256SUMS.txt")
        covered = {}
        if os.path.exists(sums_path):
            with open(sums_path, "r", encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        covered[parts[1].strip().lstrip("*")] = parts[0].lower()
        for f in ("e0c_results.json", "e0c_arrays.npz", "e0c_air_loo.json", "run.log"):
            p = os.path.join(self.dir, f)
            if not os.path.exists(p):
                problems.append(f"{f} 缺失")
                continue
            if f not in covered:
                problems.append(f"SHA256SUMS.txt 未覆盖 {f}")
                continue
            actual = sha256_file(p)
            if covered[f] != actual:
                problems.append(f"SHA256SUMS.txt 中 {f} 摘要与文件不符")
        if os.path.exists(fz):
            if "e0c_frozen.json" not in covered:
                problems.append("SHA256SUMS.txt 未覆盖 e0c_frozen.json")
            elif covered["e0c_frozen.json"] != sha256_file(fz):
                problems.append("SHA256SUMS.txt 中 e0c_frozen.json 摘要与文件不符")
        logp = os.path.join(self.dir, "run.log")
        if os.path.exists(logp):
            with open(logp, "r", encoding="utf-8", errors="replace") as f:
                log = f.read()
            if len(log.strip()) < 40:
                problems.append("run.log 内容过短，无法作为诊断日志")
        detail = {"present": present, "problems": problems}
        return ("fail" if problems else "pass"), detail

    # -- C15 真值隔离 -------------------------------------------------------- #
    def c15(self):
        problems = []
        r = self.results
        if r.get("d_true_usage") != "evaluation_only":
            problems.append(f"d_true_usage={r.get('d_true_usage')!r} 应为 'evaluation_only'")
        for name in (self.npz.names if self.npz else []):
            if "d_true" in name.lower():
                problems.append(f"数组名出现真值字段: {name}")
        detail = {"declared": r.get("d_true_usage"), "problems": problems}
        if self.repo:
            blob = git_show_bytes(self.repo, r.get("implementation_sha", ""),
                                  "solutions/A/a_e0_c.py")
            if blob is not None:
                src = blob.decode("utf-8", errors="replace")
                detail["static_scan_note"] = (
                    "d_true 出现次数: %d（仅提示，人工复核是否只进入评价）" % src.count("d_true"))
        return ("fail" if problems else "pass"), detail

    # -- 汇总 --------------------------------------------------------------- #
    def evaluate(self):
        self.load()
        if self._load_error:
            self.add("C0", True, "fail", self._load_error)
            return self.summary()
        plan = [
            ("C1", True, self.c1), ("C2", True, self.c2), ("C3", True, self.c3),
            ("C4", True, self.c4), ("C5", True, self.c5), ("C6", True, self.c6),
            ("C7", True, self.c7), ("C8", True, self.c8), ("C9", True, self.c9),
            ("C10", True, self.c10), ("C11", True, self.c11), ("C12", True, self.c12),
            ("C13", True, self.c13), ("C14", True, self.c14), ("C15", True, self.c15),
        ]
        for cid, blocking, fn in plan:
            self.run(cid, blocking, fn)
        return self.summary()

    def summary(self):
        fails = [c["id"] for c in self.checks if c["blocking"] and c["status"] == "fail"]
        insuff = [c["id"] for c in self.checks if c["blocking"]
                  and c["status"] == "insufficient"]
        if fails:
            verdict = "FAIL"
        elif insuff:
            verdict = "INSUFFICIENT"
        else:
            verdict = "PASS"
        # 锚点摘要用 git-blob 语义（CRLF→LF），否则 Windows 检出（core.autocrlf）
        # 会把同一提交算成不同摘要；raw 值仅作工作树字节留痕。
        contract_exists = os.path.exists(self.repeat_contract_path)
        report = {"prereg_id": self.prereg.get("prereg_id"),
                  "prereg_path": self.prereg_path,
                  "prereg_sha256": sha256_git_text(self.prereg_path),
                  "prereg_sha256_raw": sha256_file(self.prereg_path),
                  "repeat_contract_id": self.repeat_contract.get("id"),
                  "repeat_contract_sha256": (
                      sha256_git_text(self.repeat_contract_path)
                      if contract_exists else None),
                  "repeat_contract_sha256_raw": (
                      sha256_file(self.repeat_contract_path)
                      if contract_exists else None),
                  "results_dir": os.path.abspath(self.dir),
                  "verdict": verdict,
                  "failed_checks": fails,
                  "insufficient_checks": insuff,
                  "checks": self.checks}
        return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="E0-C 独立验收检查器（E0-PREREG-3）")
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--e0s-results", default=None)
    ap.add_argument("--prereg", default=None)
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    prereg_path = args.prereg or os.path.join(repo_root, "checks", "A",
                                              "e0_c_prereg.json")
    oracle_path = os.path.join(repo_root, "checks", "A", "e0_c_data_oracle.json")
    try:
        prereg = load_json(prereg_path)
        oracle = load_json(oracle_path)
    except FileNotFoundError as exc:
        print(f"ERROR: 预登记/清单文件缺失: {exc}", file=sys.stderr)
        return 3

    checker = Checker(args.results_dir, prereg, prereg_path, oracle,
                      repo=args.repo, e0s_path=args.e0s_results)
    report = checker.evaluate()
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print(f"E0-C VERDICT: {report['verdict']}")
    for c in report["checks"]:
        mark = {"pass": "PASS", "fail": "FAIL", "insufficient": "INSUFF"}[c["status"]]
        print(f"  {c['id']:<4} {mark:<6} {json.dumps(c['detail'], ensure_ascii=False)[:220]}")
    return {"PASS": 0, "FAIL": 1, "INSUFFICIENT": 2}[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
