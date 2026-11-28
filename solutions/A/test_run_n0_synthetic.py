#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`run_n0_synthetic.py`（N0 合成双进程入口）自检。

覆盖：
* preflight 恰 32 项、dryrun 恰 11 项，且都能抓篡改（错 config / 缺 prereg）；
* worker 的退出码 = `worker_meta.exit_code`，字段与台账自洽；
* combine 的 `e0c_repeat.json` 11 字段全部取自实际字节，两次结果/数组逐字节一致；
* 反例：数组被改、时间窗重叠、退出码不同 → combine 必须拒绝；
* 确定性 npz：同一组数组两次序列化逐字节一致；
* 冻结产物零改动、真实 `.dat` 打开计数为 0。

说明：冻结 prereg `e0_n0_prereg.json` 由验收方维护，不在本分支；设
`E0N0_PREREG` 或放到 `checks/A/e0_n0_prereg.json` 才会跑依赖它的用例，
否则跳过（与 `test_a_e0_n0_package.py` 的探针/验收器集成同一约定）。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import run_n0_synthetic as R  # noqa: E402

REPO = R._repo_root() or os.path.dirname(os.path.dirname(HERE))
N0_CONFIG = os.path.join(REPO, "experiments", "A", "A-Q1-E0", "n0", "n0_config.json")
PREREG = os.environ.get("E0N0_PREREG") or os.path.join(
    REPO, "checks", "A", "e0_n0_prereg.json")
ORACLE = os.path.join(REPO, "checks", "A", "e0_c_data_oracle.json")
PROTOTYPE = os.path.join(REPO, "experiments", "A", "A-Q1-E0", "n0",
                         "synthetic", "n0_synthetic_results.json")
PHASE_EVIDENCE = os.path.join(REPO, "experiments", "A", "A-Q1-E0", "n0",
                              "phase_evidence", "synthetic.json")


def _workdir() -> str:
    base = os.path.join(REPO, "tmp", "_test_n0_entry")
    os.makedirs(base, exist_ok=True)
    return R._mktemp_dir(REPO, base, "t_")


def _fake_preflight() -> dict:
    return {
        "contract": R.PREFLIGHT_CONTRACT,
        "mode": "n0-synthetic",
        "synthetic": True,
        "citable": False,
        "passed": 32,
        "total": 32,
        "ok": True,
        "checks": [{"id": "test-32", "ok": True, "detail": ""}],
    }


def _worker_args(out: str, index: int) -> argparse.Namespace:
    return argparse.Namespace(
        out=out, run_index=index, overwrite=True,
        config=str(R.N0.CONFIG_PATH), n0_config=N0_CONFIG, prereg=PREREG,
        oracle=ORACLE, prototype=PROTOTYPE, seed=R.N0.SYNTH_SEED,
        reuse_prototype=PROTOTYPE, reuse_phase_evidence=PHASE_EVIDENCE,
    )


def _run_fast_worker(out: str, index: int) -> int:
    with mock.patch.object(R, "build_preflight", return_value=_fake_preflight()):
        with contextlib.redirect_stdout(io.StringIO()):
            return R.run_worker(_worker_args(out, index))


def _combine_args(run1: str, run2: str, out: str) -> argparse.Namespace:
    return argparse.Namespace(run1=run1, run2=run2, out=out, overwrite=True,
                             driver_meta=None)


class PreflightTests(unittest.TestCase):
    def test_counts_and_ids_are_stable(self) -> None:
        # 不给 prereg 时也必须稳定返回 32 项，且明确报缺
        tmp = _workdir()
        try:
            doc = R.build_preflight(
                repo=REPO, config_path=N0_CONFIG,
                prereg_path=os.path.join(tmp, "missing_prereg.json"),
                oracle_path=ORACLE, out_dir=os.path.join(tmp, "out"),
                overwrite=False)
            self.assertEqual(doc["total"], 32)
            self.assertTrue(any(c["id"] == "prereg_exists" and not c["ok"]
                                for c in doc["checks"]))
            self.assertFalse(doc["ok"])
            self.assertEqual(len(doc["checks"]), 32)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_tampered_method_scope_is_rejected(self) -> None:
        tmp = _workdir()
        try:
            data = json.load(open(N0_CONFIG, encoding="utf-8"))
            data["method_scope"] = "M0-DW-Subspace/rank-2/in-window-2coef/drift"
            bad = os.path.join(tmp, "n0_config.json")
            R._write_json(bad, data)
            doc = R.build_preflight(
                repo=REPO, config_path=bad, prereg_path=PREREG,
                oracle_path=ORACLE, out_dir=os.path.join(tmp, "out"),
                overwrite=False)
            failed = {c["id"] for c in doc["checks"] if not c["ok"]}
            self.assertIn("n0_config_lf_sha256_frozen", failed)
            self.assertIn("identity_method_scope", failed)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(os.path.isfile(PREREG), "set E0N0_PREREG")
    def test_preflight_passes_on_clean_tree(self) -> None:
        dirty = R._git_stdout(REPO, ["status", "--porcelain", "--untracked-files=no"])
        if dirty:
            self.skipTest("工作区有未提交改动（preflight 要求 clean）: %r" % dirty[:120])
        tmp = _workdir()
        try:
            doc = R.build_preflight(
                repo=REPO, config_path=N0_CONFIG, prereg_path=PREREG,
                oracle_path=ORACLE, out_dir=os.path.join(tmp, "out"),
                overwrite=False)
            self.assertEqual(doc["passed"], 32, [c for c in doc["checks"] if not c["ok"]])
            self.assertEqual(doc["total"], 32)
            self.assertTrue(doc["synthetic"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DryrunTests(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(PREREG), "set E0N0_PREREG")
    def test_dryrun_11_checks_and_evidence(self) -> None:
        tmp = _workdir()
        try:
            evidence = json.load(open(PHASE_EVIDENCE, encoding="utf-8"))
            out = R.build_dryrun(
                repo=REPO, config_path=str(R.N0.CONFIG_PATH),
                n0_config_path=N0_CONFIG, prereg_path=PREREG,
                oracle_path=ORACLE, prototype_path=PROTOTYPE,
                evidence=evidence, work_dir=tmp)
            self.assertEqual(out["doc"]["total"], 11)
            self.assertEqual(out["doc"]["passed"], 11,
                             [c for c in out["doc"]["checks"] if not c["ok"]])
            self.assertEqual(len(out["evidence"]["coherence"]), 10)
            self.assertEqual(out["evidence"]["d1"]["d1_rank"], 2)
            self.assertLessEqual(out["evidence"]["d1"]["d1_min_abs_inner"], 1e-6)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class WorkerTests(unittest.TestCase):
    def test_worker_writes_contract_files_and_meta(self) -> None:
        tmp = _workdir()
        try:
            out = os.path.join(tmp, "run1")
            code = _run_fast_worker(out, 1)
            self.assertEqual(code, 0)
            for name in R.RUN_FILES:
                self.assertTrue(os.path.isfile(os.path.join(
                    out, *name.split("/"))), name)
            meta = json.load(open(os.path.join(out, "worker_meta.json"),
                                  encoding="utf-8"))
            rec = json.load(open(os.path.join(out, "run_record.json"),
                                 encoding="utf-8"))
            self.assertEqual(meta["exit_code"], 0)
            self.assertEqual(rec["exit_code"], 0)
            self.assertEqual(meta["pid"], os.getpid())
            self.assertGreater(meta["peak_rss_mib"], 0)
            self.assertEqual(meta["real_dat_files_opened"], 0)
            self.assertEqual(meta["preflight"], {"passed": 32, "total": 32})
            self.assertEqual(meta["dryrun"], {"passed": 11, "total": 11})
            self.assertTrue(R.parse_utc(meta["started_at"]) <
                            R.parse_utc(meta["finished_at"]))
            self.assertTrue(R._hash_matches(
                os.path.join(out, "e0c_results.json"), rec["results_sha256"]))
            self.assertEqual(R._ledger_problems(out), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_worker_failure_exit_code_matches_meta(self) -> None:
        tmp = _workdir()
        try:
            out = os.path.join(tmp, "run_fail")
            bad = dict(_fake_preflight(), passed=31, ok=False)
            with mock.patch.object(R, "build_preflight", return_value=bad):
                code = R.run_worker(_worker_args(out, 1))
            meta = json.load(open(os.path.join(out, "worker_meta.json"),
                                  encoding="utf-8"))
            self.assertEqual(code, 3)
            self.assertEqual(meta["exit_code"], 3)
            self.assertIn("preflight", meta["error"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CombineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _workdir()
        self.run1 = os.path.join(self.tmp, "run1")
        self.run2 = os.path.join(self.tmp, "run2")
        self.pkg = os.path.join(self.tmp, "pkg")
        self.assertEqual(_run_fast_worker(self.run1, 1), 0)
        self.assertEqual(_run_fast_worker(self.run2, 2), 0)
        # 本用例只验证 combine 的判定/摘要逻辑，快路径在同一测试进程里跑两次，
        # 因此把 run-2 的 pid 改成一个不同的值（独立进程的真实性由
        # `--mode two-process` 的父子进程与 driver 退出码核对来保证）。
        meta2_path = os.path.join(self.run2, "worker_meta.json")
        meta2 = R._read_json(meta2_path)
        meta2["pid"] = int(meta2["pid"]) + 101
        R._write_json(meta2_path, meta2)
        rec2_path = os.path.join(self.run2, "run_record.json")
        rec2 = R._read_json(rec2_path)
        rec2["pid"] = meta2["pid"]
        R._write_json(rec2_path, rec2)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_combine_repeat_digests_match_actual_bytes(self) -> None:
        self.assertEqual(R.run_combine(_combine_args(self.run1, self.run2,
                                                     self.pkg)), 0)
        rep = json.load(open(os.path.join(self.pkg, "e0c_repeat.json"),
                             encoding="utf-8"))
        self.assertEqual(len(rep["runs"]), 2)
        for rec in rep["runs"]:
            self.assertEqual(set(rec), set(R.REPEAT_REQUIRED_FIELDS))
            for kind in ("results", "arrays"):
                path = os.path.join(self.pkg, *rec[kind + "_file"].split("/"))
                self.assertTrue(os.path.isfile(path))
                self.assertEqual(rec[kind + "_sha256"], R.sha256_raw(path))
        self.assertEqual(rep["runs"][0]["results_sha256"],
                         rep["runs"][1]["results_sha256"])
        self.assertEqual(rep["runs"][0]["arrays_sha256"],
                         rep["runs"][1]["arrays_sha256"])
        self.assertNotEqual(rep["runs"][0]["pid"], rep["runs"][1]["pid"])
        self.assertNotEqual(rep["runs"][0]["results_file"],
                            rep["runs"][1]["results_file"])
        self.assertLess(R.parse_utc(rep["runs"][0]["finished_at"]),
                        R.parse_utc(rep["runs"][1]["started_at"]))
        self.assertEqual(R._ledger_problems(self.pkg), [])
        self.assertEqual(R.PKG.selfcheck(self.pkg)["verdict"], "SELF_OK")
        for name in ("worker_meta.json", "repeat/worker_meta.json",
                     "two_process.json", "e0c_repeat.json", "preflight.json",
                     "dryrun.json", "run.log"):
            self.assertTrue(os.path.isfile(os.path.join(
                self.pkg, *name.split("/"))), name)

    def test_combine_rejects_tampered_arrays(self) -> None:
        path = os.path.join(self.run2, "e0c_arrays.npz")
        with open(path, "r+b") as fh:
            first = fh.read(1)
            fh.seek(0)
            fh.write(bytes([first[0] ^ 0xFF]))
        self.assertEqual(R.run_combine(_combine_args(self.run1, self.run2,
                                                     self.pkg)), 4)
        self.assertFalse(os.path.isfile(os.path.join(self.pkg, "e0c_repeat.json")))

    def test_combine_rejects_overlapping_windows(self) -> None:
        path = os.path.join(self.run2, "run_record.json")
        rec = json.load(open(path, encoding="utf-8"))
        rec["started_at"] = json.load(open(
            os.path.join(self.run1, "run_record.json"), encoding="utf-8"))["started_at"]
        R._write_json(path, rec)
        self.assertEqual(R.run_combine(_combine_args(self.run1, self.run2,
                                                     self.pkg)), 4)

    def test_combine_rejects_exit_code_difference(self) -> None:
        path = os.path.join(self.run2, "run_record.json")
        rec = json.load(open(path, encoding="utf-8"))
        rec["exit_code"] = 4
        R._write_json(path, rec)
        self.assertEqual(R.run_combine(_combine_args(self.run1, self.run2,
                                                     self.pkg)), 4)


class DeterministicNpzTests(unittest.TestCase):
    def test_same_arrays_two_writes_are_identical(self) -> None:
        tmp = _workdir()
        try:
            arrays = {
                "xcluster__p_cal": [[[1.0] * 63 for _ in range(2)] for _ in range(5)],
                "xcluster__p_sup": [[[2.0] * 63 for _ in range(2)] for _ in range(5)],
                "air_loo__p_cal": [[[3.0] * 63 for _ in range(10)]],
                "air_loo__p_sup": [[[4.0] * 63 for _ in range(10)]],
                "phase__shifts_ns": [0.0] * 10,
                "phase__coherence": [0.5] * 10,
            }
            a = os.path.join(tmp, "a.npz")
            b = os.path.join(tmp, "b.npz")
            R.PKG._write_npz(a, arrays)
            time.sleep(1.2)
            R.PKG._write_npz(b, arrays)
            self.assertEqual(R.sha256_raw(a), R.sha256_raw(b))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DatGuardTests(unittest.TestCase):
    def test_audit_hook_counts_dat_opens(self) -> None:
        tmp = _workdir()
        try:
            path = os.path.join(tmp, "probe.dat")
            with open(path, "wb") as fh:
                fh.write(b"x")
            R._reset_dat_counter()
            with open(path, "rb") as fh:
                fh.read()
            self.assertEqual(R.real_dat_files_opened(), 1)
            R._reset_dat_counter()
            self.assertEqual(R.real_dat_files_opened(), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
