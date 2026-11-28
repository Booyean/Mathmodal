#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``a_e0_poststop.py``（E0-C-POSTSTOP-1）的自检。

覆盖
----
1. **真实归档包**：``b63e217`` 的 ``e0c/results``（硬停、无 frozen 文件）上重算两组
   目标，``reported`` 与 ``recomputed`` 的 ``d_hat/abs_err/Supp/PSLR/PNR`` 全部在
   ``1e-9 m / 1e-6 dB`` 内，输出 ``citable=false`` 且不写冻结文件；
2. **引用隔离**：输出必须带 ``may_enter_paper_numbers=false``、
   ``may_be_used_for_e0t=false``；Markdown 必须含"不得进入"声明；
3. **守卫**：``eligible`` / 灰区 / 已有 ``e0c_frozen.json`` / 混入 ``data20-73cm``
   / 数组 SHA 不符 / 报告指标被篡改，全部必须被拒绝或标为不一致；
4. **CLI**：默认参数可写出 ``poststop_targets.json``、``POSTSTOP_TARGETS.md``
   与 ``SHA256SUMS.txt``，退出码 ``0``。

用法::

    python solutions/A/test_a_e0_poststop.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import a_e0_poststop as P  # noqa: E402

RESULTS_DIR = REPO / "experiments/A/A-Q1-E0/e0c/results"
CONFIG = REPO / "experiments/A/A-Q1-E0/config.json"
WORK = REPO / "tmp"
WORK.mkdir(parents=True, exist_ok=True)


def _work_tmp() -> Path:
    path = WORK / ("poststop_test_" + uuid.uuid4().hex[:10])
    path.mkdir(parents=True, exist_ok=False)
    return path


class PostStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = json.loads((RESULTS_DIR / "e0c_results.json").read_text(encoding="utf-8"))
        with np.load(RESULTS_DIR / str(cls.result["arrays_file"])) as npz:
            cls.arrays = {key: npz[key] for key in npz.files}
        cls.c0 = P.load_c0(CONFIG)

    # ------------------------------------------------------------------
    # 正向：真实归档包可复算，且显式不可引用
    # ------------------------------------------------------------------
    def test_archived_package_recompute(self):
        doc, problems = P.build_poststop_document(
            self.result, self.arrays, RESULTS_DIR, c0=self.c0
        )
        self.assertEqual(problems, [])
        self.assertEqual(doc["contract"], "E0-C-POSTSTOP-1")
        self.assertEqual(doc["checks"]["targets_recomputed"], 2)
        self.assertTrue(doc["checks"]["all_within_tolerance"])
        self.assertEqual(doc["checks"]["max_delta_db"], 0.0)
        self.assertEqual(doc["checks"]["max_delta_m"], 0.0)
        self.assertFalse(doc["hard_stop"]["frozen_file_present"])
        self.assertEqual(doc["hard_stop"]["freeze_status"], "hard_stop")
        self.assertAlmostEqual(doc["hard_stop"]["air_loo_min_supp_db"], 2.984434, places=5)
        keys = {t["group_key"] for t in doc["targets"]}
        self.assertEqual(keys, set(P.WHITELIST_GROUPS[10:]))
        for tgt in doc["targets"]:
            self.assertFalse(tgt["citable"])
            self.assertAlmostEqual(
                tgt["recomputed"]["d_hat_m"], tgt["reported"]["d_hat_m"], places=12
            )
            self.assertAlmostEqual(
                tgt["recomputed"]["pslr_db"], tgt["reported"]["pslr_db"], places=9
            )
            self.assertTrue(tgt["finite"])
            self.assertEqual(tgt["valid_rx"], 63)

    def test_policy_and_markdown(self):
        doc, _ = P.build_poststop_document(self.result, self.arrays, RESULTS_DIR, c0=self.c0)
        policy = doc["policy"]
        self.assertFalse(policy["citable"])
        self.assertFalse(policy["may_enter_results_table"])
        self.assertFalse(policy["may_enter_paper_numbers"])
        self.assertFalse(policy["may_be_used_for_freeze"])
        self.assertFalse(policy["may_be_used_for_e0t"])
        self.assertEqual(policy["usage"], "diagnostic_only_after_hard_stop")
        md = P.render_markdown(doc)
        self.assertIn("不可引用声明", md)
        self.assertIn("不得", md)
        self.assertIn("DIAGNOSIS_AIR_LOO.md", md)
        self.assertIn("citable", md)

    # ------------------------------------------------------------------
    # 守卫：非硬停 / 冻结证据 / 留出组 / 数组摘要 / 空目标
    # ------------------------------------------------------------------
    def test_rejects_eligible_package(self):
        fake = copy.deepcopy(self.result)
        fake["freeze"]["status"] = "eligible"
        fake["freeze"]["eligible"] = True
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    def test_rejects_gray_package(self):
        fake = copy.deepcopy(self.result)
        fake["freeze"]["status"] = "not_eligible_for_freeze"
        fake["freeze"]["eligible"] = False
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    def test_rejects_package_without_hard_stops(self):
        fake = copy.deepcopy(self.result)
        fake["hard_stops"] = []
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    def test_rejects_frozen_file(self):
        tmp = _work_tmp()
        try:
            (tmp / "e0c_results.json").write_text(
                json.dumps(self.result, ensure_ascii=False), encoding="utf-8"
            )
            (tmp / "e0c_frozen.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(P.PostStopError):
                P.build_poststop_document(self.result, self.arrays, tmp, c0=self.c0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rejects_holdout_group(self):
        fake = copy.deepcopy(self.result)
        fake["groups"].append({"group_key": "墙体数据/data20-73cm", "d_hat_m": None})
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    def test_rejects_non_whitelisted_group(self):
        fake = copy.deepcopy(self.result)
        fake["groups"].append({"group_key": "空场数据/data99", "d_hat_m": None})
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    def test_rejects_arrays_sha_mismatch(self):
        fake = copy.deepcopy(self.result)
        fake["arrays_sha256"] = "0" * 64
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    def test_rejects_package_without_targets(self):
        fake = copy.deepcopy(self.result)
        for group in fake["groups"]:
            group["d_hat_m"] = None
        with self.assertRaises(P.PostStopError):
            P.build_poststop_document(fake, self.arrays, RESULTS_DIR, c0=self.c0)

    # ------------------------------------------------------------------
    # 一致性：报告值被篡改必须判不一致（退出码 3 的依据）
    # ------------------------------------------------------------------
    def test_metric_tamper_is_reported(self):
        fake = copy.deepcopy(self.result)
        wall = next(g for g in fake["groups"] if g["group_key"] == "墙体数据/data1-42cm")
        wall["d_hat_m"] = float(wall["d_hat_m"]) + 1e-3
        doc, problems = P.build_poststop_document(
            fake, self.arrays, RESULTS_DIR, c0=self.c0
        )
        self.assertFalse(doc["checks"]["all_within_tolerance"])
        self.assertTrue(any("d_hat_m" in p for p in problems))
        self.assertTrue(problems)

    # ------------------------------------------------------------------
    # CLI 与落盘
    # ------------------------------------------------------------------
    def test_cli_writes_outputs(self):
        tmp = _work_tmp()
        try:
            code = P.main([
                "--results-dir", str(RESULTS_DIR),
                "--out", str(tmp / "out"),
                "--config", str(CONFIG),
            ])
            self.assertEqual(code, 0)
            out = tmp / "out"
            for name in ("poststop_targets.json", "POSTSTOP_TARGETS.md", "SHA256SUMS.txt"):
                self.assertTrue((out / name).is_file(), name)
            doc = json.loads((out / "poststop_targets.json").read_text(encoding="utf-8"))
            self.assertFalse(doc["policy"]["citable"])
            sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
            self.assertIn("poststop_targets.json", sums)
            self.assertIn("POSTSTOP_TARGETS.md", sums)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_refuses_overwrite_without_flag(self):
        tmp = _work_tmp()
        try:
            out = tmp / "out"
            out.mkdir()
            (out / "keep.txt").write_text("x", encoding="utf-8")
            code = P.main([
                "--results-dir", str(RESULTS_DIR),
                "--out", str(out),
                "--config", str(CONFIG),
            ])
            self.assertEqual(code, 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
