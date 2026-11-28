#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`a_e0_n0_package.py` 的自检（合成夹具，不读 `.dat`、不跑 N0）。

覆盖：
* 声明值一律由数组派生（跨簇 Supp / 空气 LOO min,median / metrics_sha256 /
  input_manifest_sha256），数组与声明值不会“两张皮”；
* 落盘包满足 `E0-N0-PRODUCER-CONTRACT-1` 的文件/台账形态；
* 签名/词表/折序等易错点会**拒绝**而不是静默产出；
* 可选集成：设 `E0N0_PROBE` / `E0N0_ACCEPT` 环境变量时，分别跑
  生产侧探针（必须 READY）与正式验收器（N9 之外必须 PASS）。

用法：
    python solutions/A/test_a_e0_n0_package.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import a_e0_n0_package as pkg  # noqa: E402

SYNTHETIC = os.path.join(ROOT, "experiments", "A", "A-Q1-E0", "n0",
                         "synthetic", "n0_synthetic_results.json")
ORACLE = os.path.join(ROOT, "checks", "A", "e0_c_data_oracle.json")
MAIN_COMMIT = "c7b841efe67192a73a96894fb5a0243b336a9468"
N0_CONFIG_SHA = "a" * 64
PREREG_SHA = "b" * 64


def _inputs() -> list:
    oracle = json.load(open(ORACLE, encoding="utf-8"))
    return [{"rel_path": row["rel_path"], "size_bytes": int(row["size_bytes"]),
             "sha256": row["sha256"]}
            for g in oracle["groups"].values() for row in g.get("files", [])]


def _prereg_sha() -> str:
    path = os.environ.get("E0N0_PREREG")
    return pkg.sha256_file(path) if path and os.path.exists(path) else PREREG_SHA


def _raw() -> dict:
    doc = json.load(open(SYNTHETIC, encoding="utf-8"))
    raw = pkg.from_prototype_synthetic(
        doc, inputs=_inputs(), main_commit=MAIN_COMMIT,
        n0_config_sha256=N0_CONFIG_SHA)
    raw["registration"]["prereg_sha256"] = _prereg_sha()
    return raw


def _repeat() -> dict:
    return {"runs": [
        {"run_id": "run-1", "pid": 1001,
         "started_at": "2026-11-28T00:00:00Z",
         "finished_at": "2026-11-28T00:01:00Z",
         "results_file": "e0c_results.json", "results_sha256": "0" * 64,
         "arrays_file": "e0c_arrays.npz", "arrays_sha256": "0" * 64,
         "wall_time_s": 60.0, "exit_code": 0, "peak_rss_mib": 256.0},
        {"run_id": "run-2", "pid": 1002,
         "started_at": "2026-11-28T00:01:01Z",
         "finished_at": "2026-11-28T00:02:01Z",
         "results_file": "repeat/e0c_results.json",
         "results_sha256": "0" * 64,
         "arrays_file": "repeat/e0c_arrays.npz",
         "arrays_sha256": "0" * 64,
         "wall_time_s": 60.0, "exit_code": 0, "peak_rss_mib": 256.0},
    ]}


def _worker_meta() -> list:
    base = {"started_at": "2026-11-28T00:00:00Z",
            "finished_at": "2026-11-28T00:01:00Z",
            "exit_code": 0, "peak_rss_mib": 256.0}
    return [
        dict(base, run_id="run-1", pid=1001),
        dict(base, run_id="run-2", pid=1002,
             started_at="2026-11-28T00:01:01Z",
             finished_at="2026-11-28T00:02:01Z"),
    ]


class AssembleDerivationTest(unittest.TestCase):
    def setUp(self):
        self.raw = _raw()
        self.built = pkg.assemble(self.raw)

    def test_xcluster_declared_equals_array_recompute(self):
        declared = self.built["results"]["n0"]["xcluster_supp_db"]
        recomputed = pkg.recompute_xcluster(self.built["arrays"])
        for a in range(5):
            for b in range(2):
                self.assertAlmostEqual(declared[a][b], recomputed[a][b], places=12)

    def test_xcluster_eligibility_matches_tier(self):
        n0 = self.built["results"]["n0"]
        mn = min(v for row in n0["xcluster_supp_db"] for v in row)
        self.assertEqual(n0["xcluster_eligibility"], pkg.tier_of_supp(mn))

    def test_air_loo_min_median_derived_from_arrays(self):
        loo = self.built["air_loo"]
        rows = pkg.recompute_air_loo(self.built["arrays"], len(loo["grid"]))
        fixed = rows[0]  # 夹具只有固定 λ 一个候选
        self.assertAlmostEqual(loo["min_supp_db"], min(fixed), places=12)
        self.assertAlmostEqual(loo["median_supp_db"], pkg.median(fixed), places=12)
        self.assertFalse(loo["switched"])
        self.assertEqual(loo["selected"], list(pkg.FIXED_LAMBDA))

    def test_metrics_and_inputs_digest(self):
        res = self.built["results"]
        self.assertEqual(res["metrics_sha256"],
                         pkg.metrics_digest(res["groups"]))
        reg = res["n0"]["registration"]
        self.assertEqual(reg["input_manifest_sha256"],
                         pkg.inputs_digest(res["inputs"]))
        self.assertEqual(reg["prereg_sha256"], _prereg_sha())
        self.assertEqual(reg["main_commit"], MAIN_COMMIT)

    def test_fold_map_is_preregistered_order(self):
        folds = self.built["results"]["n0"]["xcluster_fold_map"]
        self.assertEqual([f["fold"] for f in folds], list(range(5)))
        for i, (_cname, held) in enumerate(pkg.CLUSTERS):
            self.assertEqual(folds[i]["held_out"], list(held))
            self.assertEqual(folds[i]["train"],
                             [g for g in pkg.AIR_GROUPS if g not in held])

    def test_phase_shifts_are_ns(self):
        ph = self.built["results"]["n0"]["phase"]
        self.assertEqual(ph["group_order"], list(pkg.AIR_GROUPS))
        self.assertEqual(len(ph["per_group"]), 10)
        # 原型 shifts_s=1.475e-11 -> 0.01475 ns
        self.assertAlmostEqual(ph["per_group"][1]["shift_ns"], 0.01475, places=12)
        for cname, held in pkg.CLUSTERS:
            a = ph["per_group"][pkg.AIR_GROUPS.index(held[0])]["shift_ns"]
            b = ph["per_group"][pkg.AIR_GROUPS.index(held[1])]["shift_ns"]
            self.assertLessEqual(abs(a - b), 0.1)


class RetentionSignTest(unittest.TestCase):
    def _with_peak(self, peak_loss):
        raw = _raw()
        raw["retention"]["peak_loss_db"] = peak_loss
        return pkg.assemble(raw)["results"]["n0"]["retention"]

    def test_prototype_retention_is_loss_not_retention(self):
        # 原型 peak_retention_db=-0.016551...；契约要 peak_loss_db=+0.016551...
        ret = self._with_peak(0.016551085305782472)
        self.assertTrue(ret["pass"])
        self.assertEqual(ret["case_id"], pkg.RETENTION_CASE)

    def test_loss_over_threshold_fails(self):
        self.assertFalse(self._with_peak(0.2)["pass"])


class RejectTest(unittest.TestCase):
    def test_wrong_arm_names_rejected(self):
        raw = _raw()
        raw["arm_metrics"] = {k.lower(): v for k, v in raw["arm_metrics"].items()}
        with self.assertRaises(pkg.PackageError):
            pkg.assemble(raw)

    def test_wrong_group_count_rejected(self):
        raw = _raw()
        raw["groups"] = raw["groups"][:2]
        with self.assertRaises(pkg.PackageError):
            pkg.assemble(raw)

    def test_wrong_array_shape_rejected(self):
        raw = _raw()
        raw["arrays"]["xcluster__p_cal"] = raw["arrays"]["xcluster__p_cal"][:4]
        with self.assertRaises(pkg.PackageError):
            pkg.assemble(raw)

    def test_wrong_retention_case_rejected(self):
        raw = _raw()
        raw["retention"]["case_id"] = "E0-S2@0.69"
        with self.assertRaises(pkg.PackageError):
            pkg.assemble(raw)

    def test_grid_without_fixed_lambda_rejected(self):
        raw = _raw()
        raw["lambdas"] = [[0.01, 0.01]]
        with self.assertRaises(pkg.PackageError):
            pkg.assemble(raw)

    def test_air_group_with_metrics_rejected(self):
        raw = _raw()
        raw["groups"][0]["pslr_db"] = 1.0
        with self.assertRaises(pkg.PackageError):
            pkg.assemble(raw)


def _is_drive_root(path: str) -> bool:
    tail = os.path.splitdrive(os.path.abspath(path))[1].strip("\\/")
    return tail == ""


def _tmp_base() -> str:
    """首个确实可写的临时目录（优先仓库 tmp/，其次上级/系统临时区）。

    注意：**不碰盘符根目录**——某些沙箱/杀软下 `mkdtemp(dir="D:\\")` 会挂住。
    """
    cands = [os.environ.get("A_N0_TEST_TMP"), os.path.join(ROOT, "tmp"), ROOT]
    p = ROOT
    for _ in range(2):  # 沙箱可能只放开工作区上层目录
        nxt = os.path.dirname(p)
        if nxt == p:
            break
        cands.append(nxt)
        p = nxt
    cands.append(tempfile.gettempdir())
    for cand in cands:
        if not cand or _is_drive_root(cand):
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, "a_n0_probe_%d" % os.getpid())
            os.makedirs(probe, exist_ok=True)
            try:
                os.rmdir(probe)  # 沙箱可能拒绝删除，忽略
            except OSError:
                pass
            return cand
        except OSError:
            continue
    raise RuntimeError("找不到可写的临时目录")


def _new_dir(base: str) -> str:
    """建一个唯一目录；不用 mkdtemp（其 0700 ACL 在部分沙箱下无法再写子目录）。"""
    for i in range(1000):
        p = os.path.join(base, "a_n0_pkg_%d_%d" % (os.getpid(), i))
        try:
            os.makedirs(p)
            return p
        except FileExistsError:
            continue
    raise RuntimeError("无法创建唯一临时目录")


class WritePackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _new_dir(_tmp_base())
        self.built = pkg.assemble(_raw())
        pkg.write_package(
            self.tmp, self.built, repeat=_repeat(),
            worker_meta=_worker_meta(),
            preflight={"passed": 32, "total": 32},
            dryrun={"passed": 11, "total": 11},
            run2_results=self.built["results"],
            run2_arrays=self.built["arrays"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_required_files_written(self):
        for rel in pkg.REQUIRED_FILES + pkg.GATE_FILES:
            self.assertTrue(os.path.exists(os.path.join(self.tmp, *rel.split("/"))),
                            rel)

    def test_selfcheck_ok(self):
        chk = pkg.selfcheck(self.tmp)
        self.assertEqual(chk["verdict"], "SELF_OK", chk["problems"])

    def test_ledger_covers_required_files_and_is_lf(self):
        path = os.path.join(self.tmp, "SHA256SUMS.txt")
        data = open(path, "rb").read()
        self.assertNotIn(b"\r\n", data)
        rows = [ln.split("  ", 1)[1] for ln in
                data.decode("utf-8").splitlines() if ln.strip()]
        for rel in pkg.REQUIRED_FILES:
            if rel == "SHA256SUMS.txt":
                continue
            self.assertIn(rel, rows)

    def test_repeat_digests_backfilled_from_bytes(self):
        rep = json.load(open(os.path.join(self.tmp, "e0c_repeat.json"),
                            encoding="utf-8"))
        for rec in rep["runs"]:
            for kind in ("results", "arrays"):
                p = os.path.join(self.tmp, *rec[kind + "_file"].split("/"))
                self.assertEqual(rec[kind + "_sha256"], pkg.sha256_file(p))

    @unittest.skipUnless(os.environ.get("E0N0_PROBE"), "set E0N0_PROBE to run")
    def test_probe_ready(self):
        out = os.path.join(self.tmp, "probe.json")
        proc = subprocess.run(
            [sys.executable, os.environ["E0N0_PROBE"], "--results-dir", self.tmp,
             "--contract", os.environ.get("E0N0_CONTRACT", ""),
             "--prereg", os.environ.get("E0N0_PREREG", ""), "--json", out],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.load(open(out, encoding="utf-8"))["verdict"], "READY")

    @unittest.skipUnless(os.environ.get("E0N0_ACCEPT"), "set E0N0_ACCEPT to run")
    def test_official_acceptor_reads_package(self):
        out = os.path.join(self.tmp, "accept.json")
        proc = subprocess.run(
            [sys.executable, os.environ["E0N0_ACCEPT"], "--results-dir", self.tmp,
             "--prereg", os.environ.get("E0N0_PREREG", ""),
             "--repo", ROOT, "--report", out],
            capture_output=True, text=True)
        report = json.load(open(out, encoding="utf-8"))
        status = {c["id"]: c["status"] for c in report["checks"]}
        # 唯一允许的 FAIL 是 N9（c0 与真实归档基线的等价性，合成夹具必然不同）
        allowed = {"N9"}
        for cid, st in status.items():
            if cid in allowed:
                continue
            self.assertEqual(st, "pass", "%s=%s" % (cid, st))
        self.assertIn("N9", report.get("failed_checks", []))
        self.assertEqual(report["stop_condition"], "S9")
        self.assertGreater(proc.returncode, 0)  # FAIL 但可判读，不是崩溃


if __name__ == "__main__":
    unittest.main(verbosity=2)
