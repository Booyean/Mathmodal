#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``e0c_official_precheck.py``（生产者侧预检）的自检。

只验“包装层”的行为，**不跑** 96 个合成 `.dat` 的双进程链路（那属于人工预检）：

1. 官方检查器在本仓库内可取到（`checks/A/e0_c_accept/accept_e0c.py`），说明“复用主线验收器”成立；
2. `summarize()` 对官方报告只做映射：不篡改 C1–C15 状态、C12 换成 PASS 反映到退出码；
3. `run_checker()` 在检查器没有写报告时必须明确失败，不能静默返回；
4. `build_package()` 拒绝在已有交付包的目录上重建（不覆盖证据）。

用法::

    python solutions/A/test_e0c_official_precheck.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import e0c_official_precheck as P  # noqa: E402

WORK = REPO / "tmp"
WORK.mkdir(parents=True, exist_ok=True)


def _report(c12_status: str = "pass", **c12_detail) -> dict:
    return {
        "verdict": "pass" if c12_status == "pass" else "fail",
        "failed_checks": [] if c12_status == "pass" else ["C12"],
        "insufficient_checks": [],
        "checks": [
            {"id": "C1", "status": "pass"},
            {"id": "C4", "status": "fail"},
            {
                "id": "C12",
                "status": c12_status,
                "detail": {"duplicate_serialization_detected": False,
                           "runs": c12_detail.get("runs", [])},
            },
        ],
    }


class PrecheckWrapperTests(unittest.TestCase):
    def test_official_checker_present_in_repo(self):
        checker = REPO / "checks/A/e0_c_accept/accept_e0c.py"
        self.assertTrue(checker.is_file(), checker)
        # 包装层默认要求显式传 --checker；路径存在于本仓库即满足“复用主线验收器”。
        self.assertTrue(str(checker).endswith("accept_e0c.py"))

    def test_summarize_maps_without_rewriting(self):
        rep = _report(
            "pass",
            runs=[{"run_id": "r1", "pid": 111, "started_at": "a", "finished_at": "b",
                   "results_file": "e0c_results.json", "arrays_file": "e0c_arrays.npz"}],
        )
        summary = P.summarize(rep)
        self.assertEqual(summary["c12_status"], "pass")
        self.assertEqual(summary["checks"]["C4"], "fail")
        self.assertEqual(summary["c12_runs"][0]["pid"], 111)
        self.assertFalse(summary["c12_duplicate_serialization_detected"])
        self.assertIn("C4", summary["note"])

    def test_summarize_keeps_failure(self):
        summary = P.summarize(_report("fail"))
        self.assertEqual(summary["c12_status"], "fail")
        self.assertEqual(summary["failed_checks"], ["C12"])

    def test_run_checker_fails_when_no_report(self):
        tmp = WORK / ("precheck_test_" + uuid.uuid4().hex[:8])
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            with mock.patch.object(
                P.subprocess, "run",
                return_value=subprocess.CompletedProcess(args=["x"], returncode=1,
                                                         stdout="", stderr="boom"),
            ):
                with self.assertRaises(SystemExit):
                    P.run_checker(tmp / "fake.py", tmp / "pkg", REPO, tmp / "missing.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_checker_reads_report(self):
        tmp = WORK / ("precheck_test_" + uuid.uuid4().hex[:8])
        tmp.mkdir(parents=True, exist_ok=True)
        report = tmp / "report.json"
        try:
            report.write_text(json.dumps(_report("pass")), encoding="utf-8")
            with mock.patch.object(
                P.subprocess, "run",
                return_value=subprocess.CompletedProcess(args=["x"], returncode=0,
                                                         stdout="", stderr=""),
            ):
                rep = P.run_checker(tmp / "fake.py", tmp / "pkg", REPO, report)
            self.assertEqual(rep["verdict"], "pass")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_build_package_refuses_existing_package(self):
        tmp = WORK / ("precheck_test_" + uuid.uuid4().hex[:8])
        (tmp / "package").mkdir(parents=True, exist_ok=True)
        try:
            with self.assertRaises(SystemExit):
                P.build_package(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
