#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``e0c_release_dryrun.py``（放行即跑预演）的自检。

只验预演脚本自身的判定逻辑，**不跑真实数据、不跑真实 execute**：

1. 目标目录契约：新建目录通过；已有结果/冻结证据/``run-2`` 旧证据/指向既有登记一律拒绝；
2. ``summarize()`` 只在全部检查通过时给出 ``ready_for_release_day``；
3. ``read_sha256sums()`` 正确解析两空格清单，坏行不污染结果；
4. 端到端（fake runner）：正常路径 11/11 通过；check 失败 → 不 ready；
   guard 探针改哨兵 → D7 失败；预演期间动既有登记 → D11 失败；
   且**从不**以真实目标目录调用 ``--mode execute``。

用法::

    python solutions/A/test_e0c_release_dryrun.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import e0c_release_dryrun as D  # noqa: E402

WORK = REPO / "tmp"
WORK.mkdir(parents=True, exist_ok=True)

LEGACY_FILES = {
    "e0c_results.json": b'{"contract_version": "E0-C-1", "repeat_run": {}}\n',
    "e0c_arrays.npz": b"PK\x03\x04legacy-arrays",
    "e0c_air_loo.json": b'{"folds": [], "grid": {}}\n',
    "run.log": b"legacy run log\n",
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class _Fixture:
    """最小仓库骨架：config + 既有登记 + 清单。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / D.E0_REL).mkdir(parents=True, exist_ok=True)
        (root / D.CONFIG_REL).write_text(
            json.dumps({"resource_budget": {"max_wall_time_sec": 600,
                                            "max_peak_rss_mib": 4096}}),
            encoding="utf-8",
        )
        legacy = root / D.LEGACY_RESULTS_REL
        legacy.mkdir(parents=True, exist_ok=True)
        lines: List[str] = []
        for name, payload in LEGACY_FILES.items():
            (legacy / name).write_bytes(payload)
            lines.append("%s  %s" % (_sha(payload), name))
        (legacy / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.legacy = legacy
        self.target = root / D.DEFAULT_TARGET_REL
        self.staging = root / D.E0_REL / "e0c" / "dryrun" / "t"


class _FakeRunner:
    """按 argv 生成 preflight/check 产物；execute 探针只回退出码，不写结果。"""

    def __init__(self, fixture: _Fixture, *, check_code: int = 0,
                 check_ready: bool = True, tamper_sentinel: bool = False,
                 tamper_legacy: bool = False) -> None:
        self.fixture = fixture
        self.check_code = check_code
        self.check_ready = check_ready
        self.tamper_sentinel = tamper_sentinel
        self.tamper_legacy = tamper_legacy
        self.calls: List[List[str]] = []

    def __call__(self, argv: Sequence[str]) -> Dict[str, Any]:
        argv = list(argv)
        self.calls.append(argv)
        script = Path(argv[1]).name if len(argv) > 1 else ""
        if script == D.PREFLIGHT_REL.name:
            out = Path(argv[argv.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({
                "preconditions_pass": True,
                "execution_ready": True,
                "summary": {"failed_ids": []},
                "anchors": {"config_sha256_lf": "x"},
                "data": {"signal_files_hashed": 96, "total_bytes": 88073632,
                         "path_guard": {"rejections": []}},
            }), encoding="utf-8")
            return {"argv": argv, "code": 0, "stdout": "", "stderr": ""}
        if script == D.ENTRY_REL.name and "--mode" in argv and "check" in argv:
            out = Path(argv[argv.index("--out") + 1])
            (out / "repeat_runs").mkdir(parents=True, exist_ok=True)
            out.mkdir(parents=True, exist_ok=True)
            (out / "e0c_check.json").write_text(json.dumps({
                "ready_for_execute": self.check_ready,
                "preflight": {"preconditions_pass": True},
                "boundary_scan": {"packets_parsed": 0, "problems": [],
                                  "dat_files_open_for_sha256": 96},
            }), encoding="utf-8")
            return {"argv": argv, "code": self.check_code, "stdout": "", "stderr": ""}
        if script == D.ENTRY_REL.name and "execute" in argv:
            if self.tamper_legacy:
                (self.fixture.legacy / "run.log").write_bytes(b"tampered\n")
            if self.tamper_sentinel and "guard-overwrite" in " ".join(argv):
                Path(argv[argv.index("--out") + 1]).joinpath(
                    "e0c_results.json").write_bytes(b"overwritten\n")
            return {"argv": argv, "code": 2, "stdout": "",
                    "stderr": "拒绝执行：dryrun probe"}
        return {"argv": argv, "code": 1, "stdout": "", "stderr": "unexpected"}


class TargetContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = WORK / ("dryrun_test_" + uuid.uuid4().hex[:8])
        self.root.mkdir(parents=True, exist_ok=True)
        self.fx = _Fixture(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_fresh_dir_is_ok(self):
        self.assertEqual(D.check_target_dir_contract(self.fx.target, self.fx.legacy), [])

    def test_existing_results_rejected(self):
        self.fx.target.mkdir(parents=True, exist_ok=True)
        (self.fx.target / "e0c_results.json").write_text("{}", encoding="utf-8")
        issues = D.check_target_dir_contract(self.fx.target, self.fx.legacy)
        self.assertTrue(any("e0c_results.json" in i for i in issues), issues)

    def test_existing_run2_rejected(self):
        run2 = self.fx.target / "repeat_runs" / "run-2"
        run2.mkdir(parents=True)
        (run2 / "e0c_results.json").write_text("{}", encoding="utf-8")
        issues = D.check_target_dir_contract(self.fx.target, self.fx.legacy)
        self.assertTrue(any("run-2" in i for i in issues), issues)

    def test_frozen_rejected(self):
        self.fx.target.mkdir(parents=True, exist_ok=True)
        (self.fx.target / "e0c_frozen.json").write_text("{}", encoding="utf-8")
        issues = D.check_target_dir_contract(self.fx.target, self.fx.legacy)
        self.assertTrue(any("frozen" in i for i in issues), issues)

    def test_legacy_dir_rejected(self):
        issues = D.check_target_dir_contract(self.fx.legacy, self.fx.legacy)
        self.assertTrue(any("既有登记" in i for i in issues), issues)

    def test_empty_subdir_allowed(self):
        self.fx.target.mkdir(parents=True, exist_ok=True)
        self.assertEqual(D.check_target_dir_contract(self.fx.target, self.fx.legacy), [])


class HelperTests(unittest.TestCase):
    def test_summarize_all_pass(self):
        s = D.summarize([{"id": "a", "passed": True}, {"id": "b", "passed": True}])
        self.assertTrue(s["ready_for_release_day"])
        self.assertEqual((s["total"], s["passed"], s["failed"]), (2, 2, 0))

    def test_summarize_one_fail(self):
        s = D.summarize([{"id": "a", "passed": True}, {"id": "b", "passed": False}])
        self.assertFalse(s["ready_for_release_day"])
        self.assertEqual(s["failed_ids"], ["b"])

    def test_split_status_separates_evidence(self):
        porcelain = "\n".join([
            " M solutions/A/a_e0_c.py",
            "?? experiments/A/A-Q1-E0/e0c/dryrun/20261128T200617/dryrun.json",
            "?? solutions/A/e0c_release_dryrun.py",
        ])
        parts = D.split_status(porcelain, str(D.DRYRUN_EVIDENCE_REL))
        self.assertEqual(len(parts["code"]), 2)
        self.assertEqual(len(parts["evidence"]), 1)

    def test_split_status_no_prefix_keeps_all(self):
        porcelain = "?? experiments/A/A-Q1-E0/e0c/dryrun/x.json\n"
        self.assertEqual(len(D.split_status(porcelain)["code"]), 1)

    def test_read_sha256sums_two_space_and_blank(self):
        root = WORK / ("sha_test_" + uuid.uuid4().hex[:8])
        root.mkdir(parents=True, exist_ok=True)
        try:
            path = root / "SHA256SUMS.txt"
            path.write_text(
                "aa11  one.json\n\nbb22  two.npz\nnot-a-valid-line\n", encoding="utf-8"
            )
            sums = D.read_sha256sums(path)
            self.assertEqual(sums, {"one.json": "aa11", "two.npz": "bb22"})
            self.assertEqual(D.read_sha256sums(root / "missing.txt"), {})
        finally:
            shutil.rmtree(root, ignore_errors=True)


class EndToEndDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = WORK / ("dryrun_e2e_" + uuid.uuid4().hex[:8])
        self.root.mkdir(parents=True, exist_ok=True)
        self.fx = _Fixture(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, **kwargs) -> Dict[str, Any]:
        runner = _FakeRunner(self.fx, **kwargs)
        payload = D.run_dryrun(
            self.root, self.fx.target, self.fx.staging,
            runner=runner,
            state=lambda _repo: {
                "porcelain": "", "head": "f" * 40, "branch": "data/a-q1-n0-batch",
                "origin_main": "e" * 40,
            },
        )
        payload["_calls"] = runner.calls
        return payload

    def test_happy_path_all_checks_pass(self):
        payload = self._run()
        ids = [c["id"] for c in payload["checks"]]
        self.assertEqual(len(ids), 11, ids)
        self.assertTrue(payload["summary"]["ready_for_release_day"],
                        payload["summary"])
        self.assertFalse(payload["execute_invoked"])
        self.assertTrue((self.fx.staging / "dryrun.json").is_file())
        # 真实目标目录从未被写出
        self.assertFalse((self.fx.target / "e0c_results.json").exists())
        # 所有 execute 调用都是探针目录，且不是目标目录
        exec_calls = [c for c in payload["_calls"] if "execute" in c and "check" not in c]
        self.assertEqual(len(exec_calls), 3)
        for call in exec_calls:
            self.assertNotIn(str(self.fx.target), call)

    def test_check_failure_blocks_release(self):
        payload = self._run(check_code=1, check_ready=False)
        self.assertFalse(payload["summary"]["ready_for_release_day"])
        self.assertIn("D5.entry.check", payload["summary"]["failed_ids"])

    def test_sentinel_tamper_detected(self):
        payload = self._run(tamper_sentinel=True)
        self.assertIn("D7.guard.overwrite", payload["summary"]["failed_ids"])

    def test_legacy_drift_detected(self):
        payload = self._run(tamper_legacy=True)
        self.assertIn("D11.legacy.unchanged", payload["summary"]["failed_ids"])

    def test_payload_written_with_contract(self):
        payload = self._run()
        self.assertEqual(payload["real_dat_packets_parsed"], 0)
        saved = _read_json(self.fx.staging / "dryrun.json")
        self.assertEqual(saved["contract_version"], D.DRYRUN_CONTRACT)
        self.assertFalse(saved["execute_invoked"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
