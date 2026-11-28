#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``a_e0_c.py``（E0-C 正式入口）的作者测试。

覆盖
----
* **数学/交付链**：直接调用已验收的 ``a_e0_s1s2`` 合成器生成 10 空场 + 2 目标
  频谱，走 ``solve_bundle`` 的 LOO 选参 → 校准 → DW 抑制 → 0.1 mm 测距 → 门槛，
  验证 ``d_hat`` 与已知 ``d_true`` 一致，且交付数组（0.05 ns τ、0.1 mm d、
  ``p_cal/p_sup``）能按 E0-PREREG-3 §5 重算出同一组指标；
* **I/O 链**：按 D0 契约自行写 8 行 × 2 包的合法 ``.dat`` 合成组，
  用 ``guarded_group_ref`` + ``load_group_spectrum`` 读回，验证
  ``valid_rx == 63``、频谱与写入值一致、且**不调用** ``discover_groups``；
* **编排链**：在临时数据根上桩掉 ``run_preflight`` 后跑完整
  ``run_execute_repeated``（两次独立完整重算），用 ``assemble_results`` 组装
  E0-PREREG-3 的 ``groups[12]``/``inputs[96]``/``array_map``/``repeat_run``，
  核对 96 文件、两例误差、冻结判定、两次运行证据与产物摘要；
* **C12 反例**：把两次运行伪造成同一次（重复序列化口径）、复用同一 npz 证据、
  或缺少 ``repeat_run``，都必须被拒绝；
* **边界**：``--mode execute`` 缺 ``--approval-ref`` 必须拒绝；已有结果必须拒绝
  覆盖；``--repeat-runs < 2`` 必须拒绝；check 模式不解析采样。

用法::

    python solutions/A/test_a_e0_c.py
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import struct
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import a_e0_c as A  # noqa: E402
import a_e0_s1s2 as E0S  # noqa: E402
import a_dat_reader as D0  # noqa: E402

RESULTS: List[Tuple[str, bool, str]] = []
WORK = REPO / "tmp"
WORK.mkdir(parents=True, exist_ok=True)
DAT_MAGIC = 963072
PREFIX = "2026-01-01-00-00-00_16000"
DUMMY_IMPL = "0" * 40
DUMMY_PARENT = "1" * 40
DUMMY_MAIN = "2" * 40


def check(name: str, ok: bool, note: str = "") -> bool:
    RESULTS.append((name, bool(ok), note))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  " + note) if note else ""))
    return bool(ok)


def work_tmp():
    path = WORK / ("a_e0_c_" + uuid.uuid4().hex[:10])
    path.mkdir(parents=True, exist_ok=False)
    return path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# 合法 .dat 写入器（D0-4 契约）
# --------------------------------------------------------------------------
def write_dat(path: Path, rows8: np.ndarray, syncs: List[int]) -> None:
    """写一个行文件：每包 16000 点 = 4 个相同 4000 点周期，8 行交织存放。"""
    chunks = []
    for sync in syncs:
        block = np.tile(rows8, (1, 4))  # (8, 16000)
        payload = block.T.astype("<i2").tobytes()  # (16000, 8) 采样交织
        if len(payload) != 8 * 16000 * 2:
            raise AssertionError("payload 长度异常")
        header = struct.pack(
            "<IIIfIII", DAT_MAGIC, 20 + len(payload), 102, 1.0e9, sync, 8, 32000
        )
        chunks.append(header + payload)
    path.write_bytes(b"".join(chunks))


def build_synthetic_root(
    root: Path,
    setup: "E0S.Setup",
    gen: Dict[str, Any],
) -> Tuple[float, Dict[str, np.ndarray]]:
    """把 E0-S2 的频谱写成 12 组真实格式的 .dat；返回 (量化比例, 时域矩阵)。"""
    items: List[Tuple[str, np.ndarray]] = [
        ("空场数据/data%d" % i, gen["air"][i - 1]) for i in range(1, 11)
    ]
    items += [
        ("墙体数据/data1-42cm", gen["targets"][0]["x"]),
        ("金属板数据/data1-69cm", gen["targets"][1]["x"]),
    ]

    mats: Dict[str, np.ndarray] = {}
    for key, x_band in items:
        t = E0S.to_time(x_band, setup.band_idx, setup.np_n)  # (63, 4000)
        matrix = np.zeros((D0.N_CHANNELS, setup.np_n), dtype=np.float64)
        matrix[setup.rx63] = t
        mats[key] = matrix
    peak = max(float(np.max(np.abs(m))) for m in mats.values())
    scale = 20000.0 / peak

    for key, matrix in mats.items():
        quant = np.clip(np.round(matrix * scale), -32768, 32767).astype(np.int16)
        gdir = root / A.PF.DATA_SUBDIR / Path(key)
        gdir.mkdir(parents=True, exist_ok=True)
        for r in range(8):
            write_dat(gdir / ("%s_%d.dat" % (PREFIX, r)), quant[8 * r : 8 * (r + 1)], [11, 22])
    return scale, mats


# --------------------------------------------------------------------------
# 1) 数学/交付链
# --------------------------------------------------------------------------
def test_solve_bundle_synthetic() -> Dict[str, Any]:
    cfg = A.load_config(A.CONFIG_PATH)
    setup = E0S.Setup(cfg)
    gen = E0S.generate_s2(setup)
    log: List[str] = []
    targets = [
        dict(
            case_id="E0-C/Wall-42cm",
            array_prefix="wall",
            group="墙体数据/data1-42cm",
            target_type="wall",
            d_true_cm=42.0,
            in_split="wall_cal",
            peak_rule="wall",
            x=gen["targets"][0]["x"],
        ),
        dict(
            case_id="E0-C/Metal-69cm",
            array_prefix="metal",
            group="金属板数据/data1-69cm",
            target_type="metal",
            d_true_cm=69.0,
            in_split="metal_cal",
            peak_rule="metal",
            x=gen["targets"][1]["x"],
        ),
    ]
    out = A.solve_bundle(gen["air"], targets, cfg, setup, log)

    loo = out["lambda_loo"]
    check("bundle.loo_grid_9", len(loo["grid"]) == 9 and len(loo["folds"]) == 10,
          "%d pairs" % len(loo["grid"]))
    check("bundle.loo_switch_flag", isinstance(loo["switched"], bool))
    check("bundle.loo_eligibility", loo["eligibility"] in ("eligible", "gray", "hard_stop"),
          loo["eligibility"])
    check("bundle.loo_folds_10_each",
          all(len(g["folds"]) == 10 for g in loo["grid"]))
    check("bundle.arrays_p_cal", out["arrays"]["air_loo__p_cal"].shape == (9, 10, 63),
          str(out["arrays"]["air_loo__p_cal"].shape))
    check("bundle.arrays_p_sup", out["arrays"]["air_loo__p_sup"].shape == (9, 10, 63))

    for case, d_true in zip(out["cases"], (0.42, 0.69)):
        tag = case["case_id"].split("/")[-1]
        check(
            "bundle.%s_err_lt_1cm" % tag,
            case["abs_err_cm"] <= 1.0,
            "d_hat=%.5f m err=%.4f cm" % (case["d_hat_m"], case["abs_err_cm"]),
        )
        check(
            "bundle.%s_gates_present" % tag,
            set(case["gate_results"]) == {"abs_err_cm", "pslr_db", "pnr_db", "valid_rx", "finite"},
        )
        check(
            "bundle.%s_supp" % tag,
            case["supp_dw_win_db"] > 0.0,
            "supp=%.2f dB" % case["supp_dw_win_db"],
        )
        check(
            "bundle.%s_metric_grid" % tag,
            abs(case["metric_grid"]["tau_step_ns"] - 0.05) < 1e-12
            and abs(case["metric_grid"]["d_step_m"] - 1e-4) < 1e-15,
        )
    check("bundle.wall_eta_candidates", len(out["cases"][0]["eta_wall_candidates"]) == 3,
          str([r["eta_wall"] for r in out["cases"][0]["eta_wall_candidates"]]))
    check("bundle.freeze_candidate", all(c["freeze_status"] == "eligible" for c in out["cases"]),
          str([c["freeze_status"] for c in out["cases"]]))

    # p_cal/p_sup 必须能独立还原 LOO 的 90 个抑制值（E0-PREREG-3 C8）
    p_cal = out["arrays"]["air_loo__p_cal"]
    p_sup = out["arrays"]["air_loo__p_sup"]
    worst = 0.0
    for f, g in enumerate(loo["grid"]):
        for gi, fold in enumerate(g["folds"]):
            recomputed = 10.0 * math.log10(float(p_cal[f, gi].sum()) / float(p_sup[f, gi].sum()))
            worst = max(worst, abs(recomputed - float(fold["supp_db"])))
    check("bundle.p_arrays_reproduce_supp", worst < 1e-9, "max |Δ|=%.3g dB" % worst)
    return {"cfg": cfg, "setup": setup, "gen": gen, "bundle": out}


# --------------------------------------------------------------------------
# 2) I/O 链 + 边界（不得 rglob）
# --------------------------------------------------------------------------
def test_dat_io(ctx: Dict[str, Any]) -> None:
    tmp = work_tmp()
    try:
        root = tmp / "data_root"
        setup = ctx["setup"]
        gen = ctx["gen"]
        scale, mats = build_synthetic_root(root, setup, gen)

        key = "空场数据/data1"
        ref, info = A.guarded_group_ref(root, key)
        check("io.group_ref_files_8", len(ref.files) == 8, info["real_dir"])
        check("io.group_key", ref.group_key == key, ref.group_key)

        saved = D0.discover_groups
        D0.discover_groups = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("E0-C 不得调用 rglob 型 discover_groups")
        )
        try:
            item = A.load_group_spectrum(ref, setup, "air")
        finally:
            D0.discover_groups = saved

        check("io.valid_rx_63", item["valid_rx"] == 63, str(item["valid_rx"]))
        check("io.packets_2", item["n_packets"] == 2 and item["n_accepted"] == 2,
              "%d/%d" % (item["n_accepted"], item["n_packets"]))
        check("io.eight_file_sha", len(item["files"]) == 8 and all(len(f["sha256"]) == 64 for f in item["files"]))

        recovered = item["x"] / scale
        original = gen["air"][0]
        rel = float(np.linalg.norm(recovered - original) / np.linalg.norm(original))
        check("io.spectrum_roundtrip", rel < 1e-4, "relative L2 err=%.2e" % rel)

        # 负例：组内混入非白名单行号 → 拒绝，不读
        bad = tmp / "bad_root"
        _scale_b, _mats_b = build_synthetic_root(bad, setup, gen)
        gdir = A.PF.group_dir(bad, key)
        (gdir / ("%s_7.dat" % PREFIX)).unlink()
        try:
            A.guarded_group_ref(bad, key)
            ok = False
        except A.E0CStop as exc:
            ok = "0..7" in str(exc) or "行号" in str(exc)
        check("io.missing_row_rejected", ok)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# 3) 编排链：两个独立进程（测试 worker 桩 preflight）
# --------------------------------------------------------------------------
def test_run_execute_synthetic(ctx: Dict[str, Any]) -> Dict[str, Any]:
    tmp = work_tmp()
    try:
        root = tmp / "data_root"
        setup = ctx["setup"]
        gen = ctx["gen"]
        build_synthetic_root(root, setup, gen)
        out_dir = tmp / "out"
        log: List[str] = []
        worker = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--root",
            str(root),
        ]
        combined = A.run_two_independent_runs(
            worker, out_dir, log, "python solutions/A/a_e0_c.py --mode execute"
        )
        raw = json.loads((out_dir / "e0c_results.json").read_text(encoding="utf-8"))
        run2 = json.loads(
            (out_dir / "repeat_runs/run-2/e0c_results.json").read_text(encoding="utf-8")
        )
        man = json.loads((out_dir / "e0c_repeat.json").read_text(encoding="utf-8"))

        check("exec.out_files", all((out_dir / n).is_file() for n in (
            "e0c_results.json", "e0c_arrays.npz", "e0c_air_loo.json",
            "e0c_frozen.json", "run.log", "SHA256SUMS.txt", "e0c_repeat.json")))
        check("exec.groups_12", len(raw["groups"]) == 12, str(len(raw["groups"])))
        check("exec.inputs_96", len(raw["inputs"]) == 96, str(len(raw["inputs"])))
        check("exec.inputs_rel_prefix",
              all(r["rel_path"].startswith("附件/附件2-测距数据/") for r in raw["inputs"]))
        check("exec.air_loo_folds_10", len(raw["air_loo_folds"]) == 10)
        check("exec.array_map_groups",
              set(raw["array_map"]["group_prefix"]) == {"墙体数据/data1-42cm", "金属板数据/data1-69cm"})
        check("exec.methods_fixed_alpha", raw["methods"]["alpha_mode"] == "fixed_1.0"
              and raw["methods"]["n0_improvements_enabled"] is False)
        check("exec.single_process", raw["resource"]["single_process"] is True)
        check("exec.ancestor_anchors",
              raw["config_sha256_match"] and raw["plan_sha256_match"]
              and raw["split_sha256_match"] and raw["e0_s_results_sha256_match"])
        check("exec.two_cases", len(raw["cases"]) == 2, str(len(raw["cases"])))
        check("exec.errors_lt_1cm",
              all(c["abs_err_cm"] <= 1.0 for c in raw["cases"]),
              str([round(c["abs_err_cm"], 4) for c in raw["cases"]]))
        check("exec.air_loo_eligible", raw["air_loo_eligibility"] == "eligible",
              str(raw["air_loo_eligibility"]))
        check("exec.freeze_eligible", raw["freeze"]["eligible"] is True
              and raw["freeze"]["written"] is True, raw["freeze"]["status"])
        check("exec.no_hard_stops", raw["hard_stops"] == [], str(raw["hard_stops"]))
        check("exec.freeze_file", (out_dir / "e0c_frozen.json").is_file())
        check("exec.d_true_usage", raw["d_true_usage"] == "evaluation_only")
        check("exec.npz_tau_step",
              raw["cases"][0]["metric_grid"]["tau_step_ns"] == 0.05)
        check("exec.results_no_arrays", "arrays" not in raw)

        # --- C12：两次独立进程证据（E0-C-C12-REPEAT-1） ---------------
        check("exec.repeat_manifest_n2",
              man["n_runs"] == 2 and len(man["runs"]) == 2,
              "n_runs=%r" % man.get("n_runs"))
        runs = man["runs"]
        check("exec.repeat_pids_distinct",
              all(isinstance(r["pid"], int) for r in runs)
              and runs[0]["pid"] != runs[1]["pid"],
              "%r" % [r["pid"] for r in runs])
        check("exec.repeat_run_ids_distinct",
              len({r["run_id"] for r in runs}) == 2)
        check("exec.repeat_files_distinct",
              runs[0]["results_file"] != runs[1]["results_file"]
              and runs[0]["arrays_file"] != runs[1]["arrays_file"])
        check("exec.repeat_run0_binds_delivery",
              runs[0]["results_file"] == "e0c_results.json"
              and runs[0]["arrays_file"] == "e0c_arrays.npz")
        check("exec.repeat_hashes_match",
              all(sha256_file(out_dir / r["results_file"]) == r["results_sha256"]
                  and sha256_file(out_dir / r["arrays_file"]) == r["arrays_sha256"]
                  for r in runs))
        check("exec.repeat_windows_ordered",
              runs[0]["finished_at"] <= runs[1]["started_at"])
        check("exec.run2_metrics_equal",
              run2["metrics_sha256"] == raw["metrics_sha256"]
              and run2["groups"] == raw["groups"])
        check("exec.repeat_summary",
              raw["repeat_run"]["runs_file"] == "e0c_repeat.json"
              and "runs" not in raw["repeat_run"]
              and raw["repeat_run"]["arrays_sha256"] == raw["arrays_sha256"]
              and raw["repeat_run"]["metrics_sha256"] == raw["metrics_sha256"])
        check("exec.repeat_verify_ok", bool(A.verify_repeat_manifest(out_dir)))
        check("exec.repeat_in_sums",
              "e0c_repeat.json" in (out_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")
              and "repeat_runs/run-2/e0c_arrays.npz" in
              (out_dir / "SHA256SUMS.txt").read_text(encoding="utf-8"))
        check("exec.resource_repeat_runs",
              raw["resource"]["repeat_runs"] == 2
              and len(raw["resource"]["per_run_wall_time_s"]) == 2
              and raw["resource"]["wall_time_s"] >= max(
                  raw["resource"]["per_run_wall_time_s"]))
        check("exec.arrays_byte_identical",
              sha256_file(out_dir / runs[0]["arrays_file"])
              == sha256_file(out_dir / runs[1]["arrays_file"]))

        # --- C12 反例：重复序列化/复用证据/时间窗重叠必须被拒绝 -------------
        man_path = out_dir / "e0c_repeat.json"
        original = man_path.read_text(encoding="utf-8")

        def rejected(mutate) -> bool:
            fake = copy.deepcopy(man)
            mutate(fake)
            man_path.write_text(
                json.dumps(fake, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            try:
                A.verify_repeat_manifest(out_dir)
                return False
            except A.E0CStop:
                return True
            finally:
                man_path.write_text(original, encoding="utf-8")

        check(
            "exec.repeat_duplicate_record_rejected",
            rejected(lambda m: m["runs"][1].update({
                "pid": m["runs"][0]["pid"],
                "run_id": m["runs"][0]["run_id"],
                "started_at": m["runs"][0]["started_at"],
                "finished_at": m["runs"][0]["finished_at"],
                "results_file": m["runs"][0]["results_file"],
                "arrays_file": m["runs"][0]["arrays_file"],
            })),
        )
        check(
            "exec.repeat_reused_evidence_rejected",
            rejected(lambda m: m["runs"][1].update(
                arrays_file=m["runs"][0]["arrays_file"])),
        )
        check(
            "exec.repeat_overlap_rejected",
            rejected(lambda m: m["runs"][1].update(
                started_at=m["runs"][0]["started_at"])),
        )
        check(
            "exec.repeat_hash_tamper_rejected",
            rejected(lambda m: m["runs"][1].update(arrays_sha256="0" * 64)),
        )
        check("exec.repeat_missing_runs_rejected", rejected(lambda m: m.pop("runs")))

        # ③ 缺 e0c_repeat.json 必须被拒绝（不是“默认通过”）。
        man_path.unlink()
        try:
            A.verify_repeat_manifest(out_dir)
            missing_manifest_rejected = False
        except A.E0CStop:
            missing_manifest_rejected = True
        finally:
            man_path.write_text(original, encoding="utf-8")
        check("exec.repeat_missing_manifest_rejected", missing_manifest_rejected)

        # 第二次运行指标与交付不一致必须被拒绝：同时更新清单里的 results_sha256，
        # 否则先被“SHA 与文件不符”挡住，测不到“指标不一致”这条门。
        run2_path = out_dir / runs[1]["results_file"]
        run2_original = run2_path.read_text(encoding="utf-8")
        tampered = json.loads(run2_original)
        tgt = next(g for g in tampered["groups"] if g.get("d_hat_m") is not None)
        tgt["d_hat_m"] = float(tgt["d_hat_m"]) + 1e-3
        run2_path.write_text(
            json.dumps(tampered, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        fake = copy.deepcopy(man)
        fake["runs"][1]["results_sha256"] = sha256_file(run2_path)
        man_path.write_text(
            json.dumps(fake, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        try:
            A.verify_repeat_manifest(out_dir)
            run2_mismatch_rejected = False
        except A.E0CStop:
            run2_mismatch_rejected = True
        finally:
            run2_path.write_text(run2_original, encoding="utf-8")
            man_path.write_text(original, encoding="utf-8")
        check("exec.repeat_run2_metrics_mismatch_rejected", run2_mismatch_rejected)
        check("exec.repeat_verify_restored", bool(A.verify_repeat_manifest(out_dir)))

        # --- 交付指标可由交付数组按 C10 口径复算 ---------------------------
        with np.load(out_dir / "e0c_arrays.npz") as npz_file:
            arrays = {key: npz_file[key] for key in npz_file.files}
        deltas = A.verify_delivery_metrics(raw, arrays, c0=setup.c0)
        check("exec.delivery_metrics_recompute",
              len(deltas) == 8 and max(deltas.values()) < 1e-9,
              "max |Δ|=%.3g" % max(deltas.values()))
        return {"result": raw, "out_dir": out_dir, "manifest": man}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# 4) 门槛逻辑
# --------------------------------------------------------------------------
def test_gate_logic(ctx: Dict[str, Any]) -> None:
    gates = ctx["cfg"]["gates_and_thresholds"]
    base = {"abs_err_cm": 1.0, "pslr_db": 10.0, "pnr_db": 20.0, "valid_rx": 63, "finite": True}
    g = A.evaluate_case_gates(base, gates)
    check("gate.ok_all_passed", all(v["passed"] for v in g.values()))

    gray = dict(base, abs_err_cm=7.0)
    g = A.evaluate_case_gates(gray, gates)
    check("gate.gray_band", g["abs_err_cm"]["status"] == "gray"
          and A.case_freeze_status(g) == "not_eligible_for_freeze")

    hard = dict(base, abs_err_cm=12.0)
    g = A.evaluate_case_gates(hard, gates)
    check("gate.hard_band", g["abs_err_cm"]["status"] == "failed"
          and A.case_freeze_status(g) == "hard_stop")

    low = dict(base, pnr_db=1.0)
    g = A.evaluate_case_gates(low, gates)
    check("gate.pnr_hard_stop", A.case_freeze_status(g) == "hard_stop")

    g = A.evaluate_air_gate(11.0, 12.0, gates)
    check("gate.air_pass", g["status"] == "passed")
    g = A.evaluate_air_gate(7.0, 8.0, gates)
    check("gate.air_gray", g["status"] == "gray")
    g = A.evaluate_air_gate(3.0, 4.0, gates)
    check("gate.air_fail", g["status"] == "failed")


# --------------------------------------------------------------------------
# 5) 交付工具：确定性 npz / 输入清单 / 指标摘要
# --------------------------------------------------------------------------
def test_delivery_utils() -> None:
    tmp = work_tmp()
    try:
        arrays = {
            "b": np.arange(6, dtype=np.float64).reshape(2, 3),
            "a": np.asarray([1 + 2j, 3 - 4j], dtype=np.complex128),
        }
        p1, p2 = tmp / "a1.npz", tmp / "a2.npz"
        A.save_npz_deterministic(p1, arrays)
        A.save_npz_deterministic(p2, arrays)
        check("delivery.npz_deterministic", sha256_file(p1) == sha256_file(p2))
        loaded = np.load(p1)
        check("delivery.npz_roundtrip",
              np.array_equal(loaded["b"], arrays["b"]) and np.array_equal(loaded["a"], arrays["a"]))

        groups = [
            {"group_key": "g%d" % i, "d_hat_m": float(i), "abs_err_cm": None,
             "supp_dw_win_db": None, "pslr_db": None, "pnr_db": None,
             "valid_rx": 63, "finite": True, "extra": "ignored"}
            for i in range(2)
        ]
        d1 = A.metrics_digest(groups)
        groups2 = [dict(g) for g in groups]
        groups2[0]["extra"] = "changed"
        check("delivery.metrics_digest_stable", d1 == A.metrics_digest(groups2))
        groups2[0]["d_hat_m"] = 9.0
        check("delivery.metrics_digest_sensitive", d1 != A.metrics_digest(groups2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# 6) CLI 边界
# --------------------------------------------------------------------------
def test_cli_boundaries() -> None:
    tmp = work_tmp()
    try:
        code = A.main(["--mode", "execute", "--out", str(tmp / "o1")])
        check("cli.execute_requires_approval", code == 2, "exit=%d" % code)

        out = tmp / "o2"
        out.mkdir(parents=True)
        (out / "e0c_results.json").write_text("{}", encoding="utf-8")
        code = A.main(
            ["--mode", "execute", "--approval-ref", "X", "--out", str(out)]
        )
        check("cli.refuses_overwrite", code == 2, "exit=%d" % code)

        for bad in ("1", "3"):
            code = A.main(
                ["--mode", "execute", "--approval-ref", "X", "--repeat-runs", bad,
                 "--out", str(tmp / ("o3_" + bad))]
            )
            check("cli.repeat_runs_%s_rejected" % bad, code == 2, "exit=%d" % code)

        check_mode_out = tmp / "check"
        code = A.main(["--mode", "check", "--out", str(check_mode_out)])
        payload = json.loads((check_mode_out / "e0c_check.json").read_text(encoding="utf-8"))
        check("cli.check_exit_0", code == 0, "exit=%d" % code)
        check("cli.check_no_packet_parse",
              payload["boundary_scan"]["packets_parsed"] == 0,
              str(payload["boundary_scan"]["packets_parsed"]))
        check("cli.check_ready", payload["ready_for_execute"] is True)
        check("cli.check_open_for_sha256",
              payload["boundary_scan"]["dat_files_open_for_sha256"] == 96,
              str(payload["boundary_scan"]["dat_files_open_for_sha256"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("repo=%s" % REPO)
    ctx = test_solve_bundle_synthetic()
    test_dat_io(ctx)
    test_run_execute_synthetic(ctx)
    test_gate_logic(ctx)
    test_delivery_utils()
    test_cli_boundaries()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("-" * 60)
    print("E0C_RUNNER_TESTS: %d passed, %d failed, %d total" % (
        len(RESULTS) - len(failed), len(failed), len(RESULTS)))
    if failed:
        print("FAILED: %s" % ", ".join(failed))
        return 1
    return 0


def worker_main(argv: List[str]) -> int:
    """测试用的单次运行 worker：桩掉 preflight 后走生产 execute_single_delivery。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    cfg = A.load_config(A.CONFIG_PATH)
    setup = E0S.Setup(cfg)
    stub = {
        "contract_version": A.PF.CONTRACT_VERSION,
        "preconditions_pass": True,
        "execution_ready": True,
        "summary": {"passed": 32, "total": 32, "failed_ids": [], "blocking_ids": []},
        "open_items": [],
        "data": {"path_guard": {"guarded_files": 96, "rejections": []},
                 "signal_files_hashed": 96},
    }
    A.PF.run_preflight = lambda *a, **k: stub
    out = A.execute_single_delivery(
        REPO,
        Path(args.root),
        REPO / "recon/manifests/a_dat_manifest.csv",
        A.CONFIG_PATH,
        cfg,
        setup,
        "TEST-APPROVAL-REF",
        None,
        Path(args.out),
        DUMMY_IMPL,
        DUMMY_PARENT,
        DUMMY_MAIN,
        "python solutions/A/test_a_e0_c.py --worker",
        [],
    )
    status = out["freeze_status"]
    return 0 if status == "eligible" else (3 if status == "hard_stop" else 1)


if __name__ == "__main__":
    if "--worker" in sys.argv[1:]:
        raise SystemExit(worker_main(sys.argv[1:]))
    raise SystemExit(main())
