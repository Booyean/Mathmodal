#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E0-C 验收检查器的自检（非空转证明）。

本文件不接触任何真实 `.dat`：全部夹具由 `make_fixture.py` 解析构造。
测试分两类：

1. **正向**：完整合规的合成交付 → `PASS`，且 C1–C15 全通过；`C10` 的独立重算
   与手算常数一致（Supp=30 dB、PNR=40 dB、PSLR=10/13.0103 dB、d_hat=0.42/0.69 m）。
2. **负向（每类篡改必须被对应检查抓到）**：指标篡改、NaN、有效通道不足、
   越界加组、锚点不符、灰区仍冻结、丢文件、缺确定性证据、真值泄漏、输入哈希、
   实现自引用、数组映射缺失（应给 INSUFFICIENT 而不是 PASS）、LOO 选择篡改、
   非法 eta_wall、超预算、E0-S 未通过、混入 N0；C12 独立运行证据的 6 类负例：
   只有重复序列化、两次运行指向同一数组文件、同一 PID/时间窗、第二次 npz 缺失、
   第二次运行指标不一致、第二次运行数组被篡改。

运行：
    python checks/A/e0_c_accept/test_accept_e0c.py
"""

import copy
import hashlib
import json
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import accept_e0c as acc  # noqa: E402
import make_fixture as mf  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PREREG_PATH = os.path.join(REPO, "checks", "A", "e0_c_prereg.json")
ORACLE_PATH = os.path.join(REPO, "checks", "A", "e0_c_data_oracle.json")
E0S_PATH = os.path.join(REPO, "experiments", "A", "A-Q1-E0", "s1s2", "results",
                        "e0_s1s2_results.json")

PREREG = acc.load_json(PREREG_PATH)
ORACLE = acc.load_json(ORACLE_PATH)

# 夹具放在仓库外的工作区目录：不污染工作树，也不依赖 git 忽略规则。
FIX_ROOT = os.path.join(os.path.dirname(REPO), "_e0c_accept_fixtures")
RUN_ID = str(os.getpid())


def _load(dirp, name):
    with open(os.path.join(dirp, name), "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _save(dirp, name, obj):
    with open(os.path.join(dirp, name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _write_sums(dirp):
    names = ["e0c_results.json", "e0c_arrays.npz", "e0c_air_loo.json", "run.log"]
    if os.path.exists(os.path.join(dirp, "e0c_frozen.json")):
        names.insert(3, "e0c_frozen.json")
    for n in ("e0c_repeat.json", "repeat/e0c_results.json",
              "repeat/e0c_arrays.npz"):
        if os.path.exists(os.path.join(dirp, *n.split("/"))):
            names.append(n)
    with open(os.path.join(dirp, "SHA256SUMS.txt"), "w", encoding="utf-8",
              newline="\n") as f:
        for n in names:
            f.write(f"{mf.sha256_file(os.path.join(dirp, *n.split('/')))}  {n}\n")


def _refresh(dirp):
    """重算 metrics/arrays 摘要与 SHA256SUMS，让被篡改 JSON 本身保持自洽。"""
    r = _load(dirp, "e0c_results.json")
    metrics = [{k: g.get(k) for k in mf.METRICS_KEYS} for g in r["groups"]]
    digest = hashlib.sha256(mf.canonical_json(metrics).encode("utf-8")).hexdigest()
    r["metrics_sha256"] = digest
    rr = r.setdefault("repeat_run", {})
    rr["metrics_sha256"] = digest
    sha = mf.sha256_file(os.path.join(dirp, "e0c_arrays.npz"))
    r["arrays_sha256"] = sha
    rr["arrays_sha256"] = sha
    _save(dirp, "e0c_results.json", r)
    man_path = os.path.join(dirp, "e0c_repeat.json")
    if os.path.exists(man_path):
        man = _load(dirp, "e0c_repeat.json")
        man["runs"][0]["results_sha256"] = mf.sha256_file(
            os.path.join(dirp, "e0c_results.json"))
        man["runs"][0]["arrays_sha256"] = sha
        _save(dirp, "e0c_repeat.json", man)
    _write_sums(dirp)


class E0CAcceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(FIX_ROOT, exist_ok=True)
        cls.root = os.path.join(FIX_ROOT, "run_" + RUN_ID)
        os.makedirs(cls.root, exist_ok=True)
        cls.base = os.path.join(cls.root, "base")
        built = mf.build_fixture(cls.base, E0S_PATH, ORACLE_PATH)
        cls.base_arrays = built["arrays"]

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self.dir = os.path.join(self.root, self._testMethodName)
        shutil.copytree(self.base, self.dir)

    # -- helpers ----------------------------------------------------------- #
    def run_checker(self, e0s=None):
        return acc.Checker(self.dir, PREREG, PREREG_PATH, ORACLE,
                           e0s_path=e0s or E0S_PATH).evaluate()

    def status(self, report, cid):
        return next(c for c in report["checks"] if c["id"] == cid)["status"]

    def assert_only_fails(self, report, cid):
        self.assertIn(cid, report["failed_checks"],
                      f"{cid} 未失败；失败项={report['failed_checks']}")
        self.assertEqual(report["verdict"], "FAIL")

    # -- 正向 --------------------------------------------------------------- #
    def test_01_valid_fixture_passes_every_check(self):
        rep = self.run_checker()
        self.assertEqual(rep["verdict"], "PASS",
                         json.dumps(rep, ensure_ascii=False)[:1500])
        self.assertEqual(len(rep["checks"]), 15)
        for c in rep["checks"]:
            self.assertEqual(c["status"], "pass", f"{c['id']}: {c['detail']}")

    def test_02_recomputed_metrics_match_hand_constants(self):
        rep = self.run_checker()
        c10 = next(c for c in rep["checks"] if c["id"] == "C10")
        rows = {r["group"]: r["recomputed"] for r in c10["detail"]["groups"]}
        wall = rows["墙体数据/data1-42cm"]
        metal = rows["金属板数据/data1-69cm"]
        self.assertAlmostEqual(wall["supp_dw_win_db"], 30.0, places=9)
        self.assertAlmostEqual(wall["pnr_db"], 40.0, places=9)
        self.assertAlmostEqual(wall["pslr_db"], 10.0, places=9)
        self.assertAlmostEqual(metal["pslr_db"], 13.010299956639813, places=9)
        self.assertAlmostEqual(wall["d_hat_m"], 0.42, places=9)
        self.assertAlmostEqual(metal["d_hat_m"], 0.69, places=9)
        self.assertAlmostEqual(wall["abs_err_cm"], 0.0, places=9)

    # -- 负向：指标/数组 ---------------------------------------------------- #
    def test_03_d_hat_tamper_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["groups"][-2]["d_hat_m"] = 0.44  # 墙体组
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C10")

    def test_04_suppression_tamper_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["groups"][-1]["supp_dw_win_db"] += 0.5
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C10")

    def test_05_nan_in_arrays_is_caught(self):
        arrays = copy.deepcopy(self.base_arrays)
        key = "wall_data1_42cm__z_after"
        self.assertIn(key, arrays)
        arrays[key][2][0] = float("nan")
        mf._write_npz(os.path.join(self.dir, "e0c_arrays.npz"), arrays)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C7")

    def test_06_valid_rx_62_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["groups"][-2]["valid_rx"] = 62
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C7")

    # -- 负向：边界/锚点/身份 ----------------------------------------------- #
    def test_07_holdout_group_insertion_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        extra = copy.deepcopy(r["groups"][-2])
        extra.update({"group_key": "墙体数据/data20-73cm",
                      "split": "wall_test", "d_true_cm": 73.0,
                      "d_hat_m": 0.73, "abs_err_cm": 0.0})
        r["groups"].append(extra)
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C3")

    def test_08_anchor_mismatch_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["config_sha256"] = "0" * 64
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C1")

    def test_09_input_sha_tamper_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["inputs"][0]["sha256"] = "f" * 64
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C4")

    def test_10_implementation_self_reference_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["results_commit"] = r["implementation_sha"]
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C2")

    # -- 负向：冻结语义 ------------------------------------------------------ #
    def test_11_gray_zone_without_freeze_is_consistent(self):
        d = os.path.join(self.root, "gray_ok")
        mf.build_fixture(d, E0S_PATH, ORACLE_PATH,
                         d_hat_overrides={"墙体数据/data1-42cm": 0.49})
        rep = acc.Checker(d, PREREG, PREREG_PATH, ORACLE,
                          e0s_path=E0S_PATH).evaluate()
        self.assertEqual(rep["verdict"], "PASS",
                         json.dumps(rep, ensure_ascii=False)[:1500])
        self.assertFalse(os.path.exists(os.path.join(d, "e0c_frozen.json")))

    def test_12_gray_zone_but_frozen_is_caught(self):
        d = os.path.join(self.root, "gray_bad")
        mf.build_fixture(d, E0S_PATH, ORACLE_PATH,
                         d_hat_overrides={"墙体数据/data1-42cm": 0.49},
                         freeze_status_override="eligible",
                         write_frozen_override=True)
        rep = acc.Checker(d, PREREG, PREREG_PATH, ORACLE,
                          e0s_path=E0S_PATH).evaluate()
        self.assert_only_fails(rep, "C11")

    def test_13_illegal_eta_wall_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["eta_wall"] = 0.3
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C11")

    # -- 负向：LOO ---------------------------------------------------------- #
    def test_14_loo_selection_tamper_is_caught(self):
        loo = _load(self.dir, "e0c_air_loo.json")
        loo["selected"] = [0.01, 0.01]
        loo["switched"] = True
        _save(self.dir, "e0c_air_loo.json", loo)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C8")

    # -- 负向：证据/确定性/真值 --------------------------------------------- #
    def test_15_missing_log_is_caught(self):
        os.remove(os.path.join(self.dir, "run.log"))
        rep = self.run_checker()
        self.assert_only_fails(rep, "C14")

    def test_16_missing_repeat_run_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        del r["repeat_run"]
        _save(self.dir, "e0c_results.json", r)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")

    def test_17_truth_leakage_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["d_true_usage"] = "estimation"
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C15")

    def test_18_over_budget_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["resource"]["wall_time_s"] = 601.0
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C13")

    def test_19_missing_array_map_is_insufficient(self):
        r = _load(self.dir, "e0c_results.json")
        del r["array_map"]
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assertEqual(rep["verdict"], "INSUFFICIENT")
        self.assertEqual(self.status(rep, "C10"), "insufficient")

    # -- 负向：上游前置/方法范围 -------------------------------------------- #
    def test_20_e0s_not_passing_is_caught(self):
        with open(E0S_PATH, "r", encoding="utf-8-sig") as f:
            e0s = json.load(f)
        e0s["overall_pass"] = False
        bad = os.path.join(self.root, "e0s_bad.json")
        with open(bad, "w", encoding="utf-8", newline="\n") as f:
            json.dump(e0s, f, ensure_ascii=False)
        rep = self.run_checker(e0s=bad)
        self.assert_only_fails(rep, "C6")

    def test_21_n0_feature_is_caught(self):
        r = _load(self.dir, "e0c_results.json")
        r["methods"]["n0_improvements_enabled"] = True
        _save(self.dir, "e0c_results.json", r)
        _refresh(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C5")

    # -- 负向：C12 独立运行证据（E0-C-C12-REPEAT-1） ------------------------ #
    def _c12(self, rep):
        return next(c for c in rep["checks"] if c["id"] == "C12")

    def test_22_duplicate_serialization_block_is_caught(self):
        os.remove(os.path.join(self.dir, "e0c_repeat.json"))
        r = _load(self.dir, "e0c_results.json")
        sha = mf.sha256_file(os.path.join(self.dir, "e0c_arrays.npz"))
        r["repeat_run"] = {
            "arrays_sha256": sha,
            "arrays_sha256_second_serialization": sha,
            "metrics_sha256": r["metrics_sha256"],
            "note": "两次独立序列化逐字节一致",
        }
        _save(self.dir, "e0c_results.json", r)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")
        self.assertTrue(self._c12(rep)["detail"]["duplicate_serialization_detected"])

    def test_23_same_arrays_file_for_both_runs_is_caught(self):
        man = _load(self.dir, "e0c_repeat.json")
        man["runs"][1]["arrays_file"] = "e0c_arrays.npz"
        man["runs"][1]["arrays_sha256"] = mf.sha256_file(
            os.path.join(self.dir, "e0c_arrays.npz"))
        _save(self.dir, "e0c_repeat.json", man)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")
        self.assertTrue(self._c12(rep)["detail"]["duplicate_serialization_detected"])

    def test_24_same_provenance_is_caught(self):
        man = _load(self.dir, "e0c_repeat.json")
        for f in ("run_id", "pid", "started_at", "finished_at"):
            man["runs"][1][f] = man["runs"][0][f]
        _save(self.dir, "e0c_repeat.json", man)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")
        self.assertTrue(self._c12(rep)["detail"]["duplicate_serialization_detected"])

    def test_25_missing_second_npz_is_caught(self):
        os.remove(os.path.join(self.dir, "repeat", "e0c_arrays.npz"))
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")

    def test_26_second_run_metric_mismatch_is_caught(self):
        rep2 = _load(os.path.join(self.dir, "repeat"), "e0c_results.json")
        rep2["groups"][-2]["pslr_db"] += 0.5
        _save(os.path.join(self.dir, "repeat"), "e0c_results.json", rep2)
        man = _load(self.dir, "e0c_repeat.json")
        man["runs"][1]["results_sha256"] = mf.sha256_file(
            os.path.join(self.dir, "repeat", "e0c_results.json"))
        _save(self.dir, "e0c_repeat.json", man)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")

    def test_27_second_run_arrays_tampered_is_caught(self):
        arrays = copy.deepcopy(self.base_arrays)
        key = "wall_data1_42cm__P_after"
        k = int(round((1.5 - mf.D_START_M) / mf.D_STEP_M))
        arrays[key][2][k] = 0.5  # 抬高旁瓣 → 从第二次运行的 npz 重算的 PSLR 变了
        rep_npz = os.path.join(self.dir, "repeat", "e0c_arrays.npz")
        mf._write_npz(rep_npz, arrays)
        man = _load(self.dir, "e0c_repeat.json")
        man["runs"][1]["arrays_sha256"] = mf.sha256_file(rep_npz)
        _save(self.dir, "e0c_repeat.json", man)
        rep2 = _load(os.path.join(self.dir, "repeat"), "e0c_results.json")
        rep2["arrays_sha256"] = mf.sha256_file(rep_npz)
        _save(os.path.join(self.dir, "repeat"), "e0c_results.json", rep2)
        man["runs"][1]["results_sha256"] = mf.sha256_file(
            os.path.join(self.dir, "repeat", "e0c_results.json"))
        _save(self.dir, "e0c_repeat.json", man)
        _write_sums(self.dir)
        rep = self.run_checker()
        self.assert_only_fails(rep, "C12")
        c12 = self._c12(rep)
        self.assertIn("recomputed_from_second_run", c12["detail"])

    # -- 锚点摘要：行尾不得改变身份 ---------------------------------------- #
    def test_28_anchor_digest_ignores_line_endings(self):
        anchor_dir = os.path.join(self.root, self._testMethodName + "_anchors")
        os.makedirs(anchor_dir, exist_ok=True)
        contract_path = os.path.join(REPO, "checks", "A", "e0_c_repeat_contract.json")
        crlf_prereg = os.path.join(anchor_dir, "e0_c_prereg.json")
        crlf_contract = os.path.join(anchor_dir, "e0_c_repeat_contract.json")
        for src, dst in ((PREREG_PATH, crlf_prereg),
                         (contract_path, crlf_contract)):
            with open(src, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")
            with open(dst, "wb") as f:
                f.write(data.replace(b"\n", b"\r\n"))
        self.assertNotEqual(acc.sha256_file(crlf_prereg),
                            acc.sha256_git_text(PREREG_PATH))
        rep = acc.Checker(self.dir, _load(anchor_dir, "e0_c_prereg.json"),
                          crlf_prereg, ORACLE, e0s_path=E0S_PATH).evaluate()
        self.assertEqual(rep["verdict"], "PASS",
                         json.dumps(rep, ensure_ascii=False)[:1500])
        self.assertEqual(rep["prereg_sha256"], acc.sha256_git_text(PREREG_PATH))
        self.assertEqual(rep["repeat_contract_sha256"],
                         acc.sha256_git_text(contract_path))
        self.assertNotEqual(rep["prereg_sha256_raw"], rep["prereg_sha256"])
        self.assertNotEqual(rep["repeat_contract_sha256_raw"],
                            rep["repeat_contract_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
