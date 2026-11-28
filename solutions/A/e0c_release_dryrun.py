#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E0-C「放行即跑」预演（DRYRUN，契约 ``E0C-DRYRUN-1``）。

本脚本只回答一个问题：**放行之后，那条命令链在本机是否已经可以照抄执行、
产物落盘位置是否干净、守卫是否会在误操作时先于数据读取拒绝。**

它固定只做四类动作：

1. 元数据自检：复用 ``e0c_preflight.py``，对白名单 96 个 ``.dat`` 只算
   ``size + SHA256``（``packets_parsed = 0``）；
2. 入口 ``--mode check``：拿 ``ready_for_execute`` 与边界扫描结果；
3. 守卫探针：用**非法参数**调用 ``--mode execute``，确认它在触达数据前就以
   退出码 2 拒绝（缺放行编号 / 已存在结果文件 / ``--repeat-runs != 2``）；
4. 既有登记 ``e0c/results``（b63e217）的只读锁定：前后逐文件 SHA256 必须不变。

**绝不执行真实 ``--mode execute`` 或 ``execute-worker``**，不解析任何采样，
不写 ``results-r2``，不覆盖任何已登记证据。

输出：``<staging>/dryrun.json``；退出码 0 = 预演全部通过，1 = 有阻塞项。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

DRYRUN_CONTRACT = "E0C-DRYRUN-1"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
E0_REL = Path("experiments/A/A-Q1-E0")
LEGACY_RESULTS_REL = E0_REL / "e0c" / "results"
DEFAULT_TARGET_REL = E0_REL / "e0c" / "results-r2"
CONFIG_REL = E0_REL / "config.json"
PREFLIGHT_REL = Path("solutions/A/e0c_preflight.py")
ENTRY_REL = Path("solutions/A/a_e0_c.py")
#: 预演证据目录：只追加、由本脚本生成，不算“代码未提交”。
DRYRUN_EVIDENCE_REL = E0_REL / "e0c" / "dryrun"

#: 放行后交付目录必须出现的文件（``e0c_frozen.json`` 仅在可冻结时出现）。
REQUIRED_ARTIFACTS = (
    "e0c_results.json",
    "e0c_arrays.npz",
    "e0c_air_loo.json",
    "e0c_repeat.json",
    "repeat_runs/run-2/e0c_results.json",
    "repeat_runs/run-2/e0c_arrays.npz",
    "run.log",
    "SHA256SUMS.txt",
)
CONDITIONAL_ARTIFACTS = ("e0c_frozen.json", "repeat_runs/run-2/e0c_frozen.json")

#: 既有登记 b63e217 的列表（只读锁定对象）。
LEGACY_FILES = (
    "e0c_results.json",
    "e0c_arrays.npz",
    "e0c_air_loo.json",
    "run.log",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sha256sums(path: Path) -> Dict[str, str]:
    """读 ``SHA256SUMS.txt``（``<hex>  <name>``，两空格）。"""
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            out[parts[1].strip()] = parts[0].strip().lower()
    return out


def split_status(porcelain: str, evidence_prefix: str = "") -> Dict[str, List[str]]:
    """把 ``git status --porcelain`` 拆成代码改动与预演证据目录。

    证据目录里的未跟踪文件由本脚本自己写出，不算“工作区脏”；其余任何
    modified/added/deleted/untracked 都算。
    """
    code: List[str] = []
    evidence: List[str] = []
    prefix = evidence_prefix.replace("\\", "/").strip("/")
    for line in porcelain.splitlines():
        rel = line[3:].strip().strip('"').replace("\\", "/")
        if prefix and (rel == prefix or rel.startswith(prefix + "/")):
            evidence.append(line)
        else:
            code.append(line)
    return {"code": code, "evidence": evidence}


def check_target_dir_contract(target: Path, legacy: Path) -> List[str]:
    """返回目标交付目录的问题列表（空 = 可安全登记）。"""
    issues: List[str] = []
    try:
        if target.resolve() == legacy.resolve():
            issues.append("目标目录等于既有登记 %s，禁止覆盖" % legacy)
    except OSError:  # pragma: no cover - 极端路径
        pass
    if (target / "e0c_results.json").is_file():
        issues.append("目标目录已有 e0c_results.json")
    second = target / "repeat_runs" / "run-2"
    if second.exists() and any(second.iterdir()):
        issues.append("目标目录已有 repeat_runs/run-2 旧证据")
    frozen = target / "e0c_frozen.json"
    if frozen.is_file():
        issues.append("目标目录已有 e0c_frozen.json（冻结证据）")
    return issues


def summarize(checks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    failed = [c["id"] for c in checks if not c.get("passed")]
    return {
        "total": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "failed_ids": failed,
        "ready_for_release_day": not failed,
    }


class Runner:
    """子进程执行器（可注入，便于离线测试）。"""

    def __init__(self, repo: Path, timeout: int = 1200) -> None:
        self.repo = repo
        self.timeout = timeout

    def __call__(self, argv: Sequence[str]) -> Dict[str, Any]:
        proc = subprocess.run(
            list(argv),
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
        )
        return {
            "argv": list(argv),
            "code": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
        }


def _check(cid: str, passed: bool, detail: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"id": cid, "passed": bool(passed), "detail": detail}
    payload.update(extra)
    return payload


def _python() -> str:
    return sys.executable or "python"


def git(repo: Path, *args: str, strip: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    text = proc.stdout or ""
    # `--porcelain` 的首行以状态位（可能是空格）开头，strip() 会吃掉它，
    # 导致 ` D path` 被误判为 `D  path`（路径错位、代码改动误分类）。
    return text.strip() if strip else text.rstrip("\r\n")


def git_state(repo: Path) -> Dict[str, str]:
    return {
        "porcelain": git(repo, "status", "--porcelain", strip=False),
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "origin_main": git(repo, "rev-parse", "origin/main"),
    }


def run_dryrun(
    repo: Path,
    target: Path,
    staging: Path,
    runner: Optional[Callable[[Sequence[str]], Dict[str, Any]]] = None,
    state: Optional[Callable[[Path], Dict[str, str]]] = None,
) -> Dict[str, Any]:
    runner = runner or Runner(repo)
    state = state or git_state
    legacy = repo / LEGACY_RESULTS_REL
    checks: List[Dict[str, Any]] = []
    staging.mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone()

    # ---- D1 仓库状态 ---------------------------------------------------- #
    repo_state = state(repo) if callable(state) else {}
    porcelain = repo_state.get("porcelain", "")
    head = repo_state.get("head", "")
    branch = repo_state.get("branch", "")
    origin_main = repo_state.get("origin_main", "")
    status = split_status(porcelain, str(DRYRUN_EVIDENCE_REL))
    checks.append(
        _check(
            "D1.repo.clean",
            not status["code"],
            "工作区干净（预演证据目录之外无改动）" if not status["code"]
            else "工作区有未提交改动",
            head_sha=head,
            branch=branch,
            origin_main_sha=origin_main,
            dirty_files=status["code"][:20],
            evidence_untracked=status["evidence"][:20],
        )
    )

    # ---- D2 既有登记只读锁定 -------------------------------------------- #
    legacy_sums = read_sha256sums(legacy / "SHA256SUMS.txt")
    legacy_before: Dict[str, str] = {}
    legacy_issues: List[str] = []
    for name in LEGACY_FILES:
        path = legacy / name
        if not path.is_file():
            legacy_issues.append("缺少 %s" % name)
            continue
        digest = sha256_file(path)
        legacy_before[name] = digest
        expected = legacy_sums.get(name)
        if expected is None:
            legacy_issues.append("%s 未登记在 SHA256SUMS.txt" % name)
        elif expected != digest:
            legacy_issues.append("%s 与登记不符" % name)
    checks.append(
        _check(
            "D2.legacy.lock",
            not legacy_issues,
            "b63e217 登记 %d/%d 份摘要与 SHA256SUMS.txt 一致"
            % (len(legacy_before), len(LEGACY_FILES))
            if not legacy_issues
            else "; ".join(legacy_issues),
            legacy_dir=str(legacy.relative_to(repo)),
            files_sha256=legacy_before,
            issues=legacy_issues,
        )
    )

    # ---- D3 目标目录契约 ------------------------------------------------ #
    issues = check_target_dir_contract(target, legacy)
    checks.append(
        _check(
            "D3.target.new",
            not issues,
            "目标目录 %s 可安全登记" % target
            if not issues
            else "; ".join(issues),
            target=str(target),
            issues=issues,
        )
    )

    # ---- D4 元数据自检 -------------------------------------------------- #
    pf_out = staging / "preflight.json"
    res = runner([
        _python(), str(repo / PREFLIGHT_REL), "--out", str(pf_out),
    ])
    pf: Dict[str, Any] = {}
    if pf_out.is_file():
        pf = json.loads(pf_out.read_text(encoding="utf-8"))
    summary = pf.get("summary", {}) or {}
    pf_ok = (
        res["code"] == 0
        and pf.get("preconditions_pass") is True
        and pf.get("execution_ready") is True
        and not summary.get("failed_ids")
    )
    checks.append(
        _check(
            "D4.preflight",
            pf_ok,
            "preconditions_pass=%s execution_ready=%s failed=%s"
            % (pf.get("preconditions_pass"), pf.get("execution_ready"),
               summary.get("failed_ids")),
            exit_code=res["code"],
            json=str(pf_out),
            anchors=pf.get("anchors", {}),
            data_summary={
                "signal_files_hashed": (pf.get("data") or {}).get("signal_files_hashed"),
                "total_bytes": (pf.get("data") or {}).get("total_bytes"),
                "path_guard_rejections": ((pf.get("data") or {}).get("path_guard") or {}).get("rejections"),
            },
            stderr=res["stderr"],
        )
    )

    # ---- D5 入口 check 模式 --------------------------------------------- #
    check_out = staging / "check"
    res = runner([
        _python(), str(repo / ENTRY_REL), "--mode", "check", "--out", str(check_out),
    ])
    chk_path = check_out / "e0c_check.json"
    chk: Dict[str, Any] = {}
    if chk_path.is_file():
        chk = json.loads(chk_path.read_text(encoding="utf-8"))
    boundary = chk.get("boundary_scan", {}) or {}
    pre = chk.get("preflight", {}) or {}
    chk_ok = (
        res["code"] == 0
        and chk.get("ready_for_execute") is True
        and boundary.get("packets_parsed") == 0
        and pre.get("preconditions_pass") is True
    )
    checks.append(
        _check(
            "D5.entry.check",
            chk_ok,
            "ready_for_execute=%s packets_parsed=%s dat_open_for_sha256=%s"
            % (chk.get("ready_for_execute"), boundary.get("packets_parsed"),
               boundary.get("dat_files_open_for_sha256")),
            exit_code=res["code"],
            json=str(chk_path),
            boundary_problems=boundary.get("problems", []),
            stderr=res["stderr"],
        )
    )

    # ---- D6–D8 守卫探针（均应在读数据前以退出码 2 拒绝） ----------------- #
    probe_dir = staging / "guard-no-approval"
    res = runner([
        _python(), str(repo / ENTRY_REL), "--mode", "execute",
        "--out", str(probe_dir),
    ])
    no_artifacts = not (probe_dir / "e0c_results.json").exists() and not (
        probe_dir / "e0c_arrays.npz"
    ).exists()
    checks.append(
        _check(
            "D6.guard.no_approval",
            res["code"] == 2 and no_artifacts,
            "缺 --approval-ref 时退出码 %s，未产生结果文件" % res["code"],
            exit_code=res["code"],
            artifacts_written=not no_artifacts,
            stderr=res["stderr"].strip()[:300],
        )
    )

    overwrite_dir = staging / "guard-overwrite"
    overwrite_dir.mkdir(parents=True, exist_ok=True)
    sentinel = overwrite_dir / "e0c_results.json"
    sentinel_bytes = b'{"sentinel": "dryrun-overwrite-guard"}\n'
    sentinel.write_bytes(sentinel_bytes)
    sentinel_sha = hashlib.sha256(sentinel_bytes).hexdigest()
    res = runner([
        _python(), str(repo / ENTRY_REL), "--mode", "execute",
        "--approval-ref", "DRYRUN-PROBE-NOT-A-RELEASE",
        "--repeat-runs", "2", "--out", str(overwrite_dir),
    ])
    after_sha = sha256_file(sentinel) if sentinel.is_file() else None
    extra_artifacts = (overwrite_dir / "e0c_arrays.npz").exists()
    checks.append(
        _check(
            "D7.guard.overwrite",
            res["code"] == 2 and after_sha == sentinel_sha and not extra_artifacts,
            "已有 e0c_results.json 时退出码 %s，哨兵文件未被改动" % res["code"],
            exit_code=res["code"],
            sentinel_sha256_before=sentinel_sha,
            sentinel_sha256_after=after_sha,
            stderr=res["stderr"].strip()[:300],
        )
    )

    repeat_dir = staging / "guard-repeat"
    res = runner([
        _python(), str(repo / ENTRY_REL), "--mode", "execute",
        "--approval-ref", "DRYRUN-PROBE-NOT-A-RELEASE",
        "--repeat-runs", "3", "--out", str(repeat_dir),
    ])
    checks.append(
        _check(
            "D8.guard.repeat_runs",
            res["code"] == 2 and not (repeat_dir / "e0c_results.json").exists(),
            "--repeat-runs=3 时退出码 %s，未启动运行" % res["code"],
            exit_code=res["code"],
            stderr=res["stderr"].strip()[:300],
        )
    )

    # ---- D9 既有登记与交付契约的差异（必须显式记录，不当作通过） --------- #
    legacy_result_path = legacy / "e0c_results.json"
    legacy_keys: List[str] = []
    if legacy_result_path.is_file():
        legacy_keys = sorted(json.loads(legacy_result_path.read_text(encoding="utf-8")))
    missing_repeat = not (legacy / "e0c_repeat.json").is_file()
    checks.append(
        _check(
            "D9.contract.delta",
            legacy_result_path.is_file() and missing_repeat,
            "既有登记缺 e0c_repeat.json（单次运行，不满足 E0-C-C12-REPEAT-1）"
            "→ 必须写新目录；交付契约 %d 个必产物" % len(REQUIRED_ARTIFACTS),
            legacy_has_results=legacy_result_path.is_file(),
            legacy_missing_repeat=missing_repeat,
            required_artifacts=list(REQUIRED_ARTIFACTS),
            conditional_artifacts=list(CONDITIONAL_ARTIFACTS),
            legacy_result_keys=legacy_keys,
        )
    )

    # ---- D10 资源预算 ---------------------------------------------------- #
    cfg = json.loads((repo / CONFIG_REL).read_text(encoding="utf-8"))
    budget = cfg.get("resource_budget") or {}
    wall = budget.get("max_wall_time_sec")
    rss = budget.get("max_peak_rss_mib")
    checks.append(
        _check(
            "D10.budget",
            wall == 600 and rss == 4096,
            "墙钟 ≤ %s s / 峰值 RSS ≤ %s MiB（两次独立进程合计）" % (wall, rss),
            max_wall_time_sec=wall,
            max_peak_rss_mib=rss,
        )
    )

    # ---- D11 既有登记复检（前后不变） ------------------------------------ #
    drift = {
        name: (digest, sha256_file(legacy / name))
        for name, digest in legacy_before.items()
        if (legacy / name).is_file() and sha256_file(legacy / name) != digest
    }
    checks.append(
        _check(
            "D11.legacy.unchanged",
            not drift,
            "既有登记在预演前后逐文件 SHA256 不变" if not drift
            else "预演期间既有登记被改动：%s" % sorted(drift),
            drift=drift,
        )
    )

    finished = datetime.now().astimezone()
    payload = {
        "contract_version": DRYRUN_CONTRACT,
        "mode": "dryrun_metadata_only",
        "generated_at": finished.isoformat(timespec="seconds"),
        "elapsed_s": round((finished - started).total_seconds(), 3),
        "repo": str(repo),
        "target_out_dir": str(target),
        "staging_dir": str(staging),
        "head_sha": head,
        "branch": branch,
        "origin_main_sha": origin_main,
        "real_dat_packets_parsed": 0,
        "execute_invoked": False,
        "checks": checks,
        "summary": summarize(checks),
        "note": (
            "本预演只证明命令链、目录契约与守卫已就绪，不构成 E0-C 放行；"
            "execute 仍须统筹签发放行编号。"
        ),
    }
    (staging / "dryrun.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="E0-C 放行即跑预演（不执行真实 execute）")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="仓库根目录")
    parser.add_argument("--target", default=str(DEFAULT_TARGET_REL), help="放行后目标交付目录")
    parser.add_argument(
        "--staging", default=None,
        help="预演工作目录（默认 experiments/A/A-Q1-E0/e0c/dryrun/<时间戳>）",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    target = Path(args.target)
    if not target.is_absolute():
        target = repo / target
    if args.staging:
        staging = Path(args.staging).resolve()
    else:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        staging = repo / E0_REL / "e0c" / "dryrun" / stamp

    payload = run_dryrun(repo, target, staging)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    for check in payload["checks"]:
        print("%s %-26s %s" % ("PASS" if check["passed"] else "FAIL", check["id"], check["detail"]))
    print("json: %s" % (staging / "dryrun.json"))
    return 0 if payload["summary"]["ready_for_release_day"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
