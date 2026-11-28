#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生产者侧预检：用冻结的官方 ``accept_e0c.py`` 机械验收本分支的两进程合成包。

用途与边界
----------
``E0-C-C12-REPEAT-1`` 要求 C12 有**两次独立进程**的运行证据。本脚本用
``a_e0_c.run_two_independent_runs``（生产链路）在 12 组合成 ``.dat`` 上跑两次，
再用**另一个仓库副本/主线**里的官方 ``checks/A/e0_c_accept/accept_e0c.py``
验收该包，输出逐项 C1–C15 报告。

* 不读取任何真实 ``.dat``，不产生真实 E0-C 结论；
* 合成文件名不是真实白名单文件名，因此 C4（真实输入身份）**必然** FAIL，
  这是夹具性质，不是被测代码缺陷；其余检查应全部 PASS，其中 C12 是本脚本的
  主要目标；
* 本脚本只是**生产者预检**，不代替 ``my_deepseek`` 的独立验收与 codex 的合并裁定。

用法::

    python solutions/A/e0c_official_precheck.py \
        --checker ../main-wt/checks/A/e0_c_accept/accept_e0c.py \
        --report tmp/e0c_official_precheck/report.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import a_e0_c as A  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402
import test_a_e0_c as T  # noqa: E402  （复用作者测试的 12 组合成夹具）


def build_package(work: Path) -> Path:
    """在 ``work`` 下生成 12 组合成 ``.dat``，用两个独立进程产出完整交付包。"""
    data_root = work / "synthetic_data"
    out_dir = work / "package"
    if out_dir.exists():
        raise SystemExit("输出目录已存在，换 --work 以免覆盖证据: %s" % out_dir)
    cfg = A.load_config(A.CONFIG_PATH)
    setup = E0S.Setup(cfg)
    gen = E0S.generate_s2(setup)
    T.build_synthetic_root(data_root, setup, gen)
    worker = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--root",
        str(data_root),
    ]
    log: List[str] = []
    A.run_two_independent_runs(
        worker, out_dir, log,
        "python solutions/A/e0c_official_precheck.py (two independent processes)",
    )
    (out_dir / "precheck_build.log").write_text(
        "\n".join(log) + "\n", encoding="utf-8"
    )
    return out_dir


def run_checker(checker: Path, package: Path, anchor_repo: Path, report: Path) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(checker),
        "--results-dir",
        str(package),
        "--repo",
        str(anchor_repo),
        "--report",
        str(report),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    if not report.is_file():
        raise SystemExit("官方检查器没有写出报告（exit=%d）" % proc.returncode)
    with open(report, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize(rep: Dict[str, Any]) -> Dict[str, Any]:
    """把官方检查器报告压成预检摘要（只做映射，不重判 C1–C15）。"""
    checks = {c["id"]: c["status"] for c in rep["checks"]}
    c12 = next(c for c in rep["checks"] if c["id"] == "C12")
    return {
        "verdict": rep["verdict"],
        "failed_checks": rep.get("failed_checks"),
        "insufficient_checks": rep.get("insufficient_checks"),
        "checks": checks,
        "c12_status": c12["status"],
        "c12_runs": [
            {k: r.get(k) for k in ("run_id", "pid", "started_at", "finished_at",
                                   "results_file", "arrays_file")}
            for r in (c12.get("detail") or {}).get("runs", [])
        ],
        "c12_duplicate_serialization_detected": (
            c12.get("detail") or {}
        ).get("duplicate_serialization_detected"),
        "note": (
            "合成夹具预检：C4 因合成文件名不在真实白名单而必然 FAIL，不代表被测代码缺陷；"
            "真实 E0-C 结论仍需 B-02 放行后的真实双跑。"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="E0-C 两进程合成包的官方检查器预检")
    ap.add_argument("--checker", required=True, help="官方 accept_e0c.py 路径（建议取 main）")
    ap.add_argument("--anchor-repo", default=str(REPO),
                    help="锚点/E0-S 结果所在仓库副本（默认本副本）")
    ap.add_argument("--work", default=str(Path(tempfile.gettempdir()) / "e0c_official_precheck"),
                    help="合成数据与交付包的临时工作目录（默认系统临时目录）")
    ap.add_argument("--report", default=None, help="报告 JSON 路径（默认 <work>/report.json）")
    args = ap.parse_args()

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report) if args.report else work / "report.json"

    package = build_package(work)
    rep = run_checker(Path(args.checker), package, Path(args.anchor_repo), report_path)

    summary = summarize(rep)
    out = work / "summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["c12_status"] == "pass" else 1


if __name__ == "__main__":
    if "--worker" in sys.argv[1:]:
        raise SystemExit(T.worker_main(sys.argv[1:]))
    raise SystemExit(main())
