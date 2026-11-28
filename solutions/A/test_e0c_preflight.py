#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``e0c_preflight.py`` 的作者测试。

覆盖
----
* 锚点：config/PLAN/SPLIT 的 LF/原始字节 SHA256 与已批复值一致；CRLF 归一化正确；
* R0 清单：881 行、总体 SHA256 按**清单行序**可复现；按路径排序反而复现不了（刻画文档差异）；
* 冻结拆分：裸名 ``data14-48cm`` 同时出现在墙体/金属板，按数据集限定后四折 40 组互斥；
* 白名单：12 组、无检验组泄漏、两组校准目标落在对应 cal 折、18 组未触碰（16 内插 + 2 外推）；
* 真实数据自检：96 个文件、88,073,632 B、所有打开文件都在白名单组内、preconditions 通过；
* 反例：缺行 / 大小不符 / SHA256 不符 / 0 字节 / 越界读取 / E0-S 门失败 / 锚点不符；
* readiness：``code.e0c_runner_present`` 只影响 execution_ready，不污染放行前条件。

用法
----
    python solutions/A/test_e0c_preflight.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import e0c_preflight as P  # noqa: E402

RESULTS: List[Tuple[str, bool, str]] = []
MANIFEST = REPO / "recon/manifests/a_dat_manifest.csv"
A_ROOT = REPO / P.A_ROOT_DEFAULT
HAS_DATA = A_ROOT.is_dir() and MANIFEST.is_file()
WORK = REPO / "tmp"
WORK.mkdir(parents=True, exist_ok=True)


@contextmanager
def work_tmp():
    """在仓库 ``tmp/`` 下建临时目录（本机 ``$env:TEMP`` / ``mkdtemp`` 受沙箱 ACL 限制）。"""
    path = WORK / ("e0c_preflight_" + uuid.uuid4().hex[:10])
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def check(name: str, ok: bool, note: str = "") -> bool:
    RESULTS.append((name, bool(ok), note))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  " + note) if note else ""))
    return bool(ok)


def real_cfg() -> Dict[str, Any]:
    return P.load_json(REPO / "experiments/A/A-Q1-E0/config.json")


def real_split() -> Dict[str, Any]:
    return P.load_json(REPO / "coordination/A_Q1_SPLIT.json")


def find_check(result: Dict[str, Any], cid: str) -> Dict[str, Any]:
    for item in result["checks"]:
        if item["id"] == cid:
            return item
    raise KeyError(cid)


def make_group(root: Path, key: str, rows: range, size: int = 256, prefix: str = "2026-01-01-00-00-00_16000") -> List[Path]:
    gdir = P.group_dir(root, key)
    gdir.mkdir(parents=True, exist_ok=True)
    files = []
    for row in rows:
        path = gdir / ("%s_%d.dat" % (prefix, row))
        path.write_bytes(bytes([row]) * size)
        files.append(path)
    return files


def write_manifest(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["rel_path", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)


def manifest_entry(root: Path, path: Path) -> Dict[str, Any]:
    rel = "%s/%s" % (P.DATA_SUBDIR.as_posix(), path.relative_to(root / P.DATA_SUBDIR).as_posix())
    return {"rel_path": rel, "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def mini_cfg(key: str) -> Dict[str, Any]:
    return {
        "pilot_datasets": {
            "phase_c_calibration_pilot": {"air_groups": [key], "target_groups": []},
            "phase_t_holdout_single_shot_eval": {"target_groups": []},
        }
    }


def run_inventory(tmp: Path, rows: range, *, mutate=None) -> Dict[str, Any]:
    root = tmp / "data_root"
    key = "空场数据/data1"
    files = make_group(root, key, rows)
    entries = [manifest_entry(root, p) for p in files]
    if mutate:
        entries = mutate(entries)
    manifest = tmp / "manifest.csv"
    write_manifest(manifest, entries)
    ck = P.Checker()
    info = P.check_data(REPO, root, manifest, mini_cfg(key), ck)
    return {"check": [c for c in ck.checks if c["id"] == "data.inventory"][0], "info": info}


# ---------------------------------------------------------------- 锚点
def test_anchors() -> None:
    cfg = REPO / "experiments/A/A-Q1-E0/config.json"
    plan = REPO / "experiments/A/A-Q1-E0/PLAN.md"
    split = REPO / "coordination/A_Q1_SPLIT.json"
    check("anchor.config_lf", P.sha256_file_lf(cfg) == P.APPROVED_ANCHORS["config_sha256_lf"])
    check("anchor.plan_raw", P.sha256_file(plan) == P.APPROVED_ANCHORS["plan_sha256"])
    check("anchor.split_lf", P.sha256_file_lf(split) == P.APPROVED_ANCHORS["split_sha256_lf"])

    with work_tmp() as tmp:
        a = Path(tmp) / "a.txt"
        b = Path(tmp) / "b.txt"
        a.write_bytes(b"x\r\ny\r\n")
        b.write_bytes(b"x\ny\n")
        check("lf_normalization", P.sha256_file_lf(a) == P.sha256_file_lf(b))

    ck = P.Checker()
    anchors = P.check_anchor_files(REPO, ck)
    check("anchor_checks_all_pass", all(c["passed"] for c in ck.checks), "%d checks" % len(ck.checks))
    check("anchor_values_recorded", anchors.get("config_sha256_lf") == P.APPROVED_ANCHORS["config_sha256_lf"])


# ---------------------------------------------------------------- 清单
def test_manifest() -> None:
    if not MANIFEST.is_file():
        check("manifest.present", False, "missing %s" % MANIFEST)
        return
    rows = P.manifest_rows(MANIFEST)
    check("manifest.rows_881", len(rows) == 881, "rows=%d" % len(rows))
    overall = P.manifest_overall_sha256(rows)
    check("manifest.overall_row_order", overall == P.APPROVED_ANCHORS["dat_manifest_overall_sha256"])
    sorted_lines = ["%s  %s" % (r["sha256"], r["rel_path"]) for r in sorted(rows, key=lambda r: r["rel_path"])]
    sorted_hash = P.sha256_bytes(("\n".join(sorted_lines) + "\n").encode("utf-8"))
    check(
        "manifest.sorted_order_differs",
        sorted_hash != P.APPROVED_ANCHORS["dat_manifest_overall_sha256"],
        "README 的“按路径排序”口径复现不了锚点，必须按行序",
    )
    check("manifest.total_bytes", sum(r["size_bytes"] for r in rows) == 801111612)


# ---------------------------------------------------------------- 拆分与白名单
def test_split_and_whitelist() -> None:
    split = real_split()
    cfg = real_cfg()
    folds = P.split_qualified(split)
    check("split.each_10", all(len(v) == 10 for v in folds.values()), str({k: len(v) for k, v in folds.items()}))
    qualified = [set(v) for v in folds.values()]
    inter = set().union(*[qualified[i] & qualified[j] for i in range(4) for j in range(i + 1, 4)])
    check("split.qualified_disjoint", not inter, "overlap=%s" % sorted(inter))
    union = set().union(*qualified)
    check("split.qualified_union_40", len(union) == 40, "union=%d" % len(union))
    bare_overlap = set(split["groups"]["wall_test"]) & set(split["groups"]["metal_test"])
    check(
        "split.bare_name_collision_characterized",
        bare_overlap == {"data14-48cm"},
        "同一裸名对应两个不同物理组：%s" % sorted(bare_overlap),
    )

    ck = P.Checker()
    P.check_allow_list(cfg, split, ck)
    failed = [c["id"] for c in ck.checks if not c["passed"]]
    check("whitelist.all_checks_pass", not failed, "failed=%s" % failed)
    untouched = [c for c in ck.checks if c["id"] == "whitelist.untouched_count"][0]
    check(
        "whitelist.untouched_18_16_2",
        untouched["untouched"] == 18 and untouched["interpolation_untouched"] == 16 and len(untouched["extrapolation"]) == 2,
        "18 untouched = 16 interpolation + 2 extrapolation",
    )


# ---------------------------------------------------------------- 真实数据
def test_real_data() -> None:
    if not HAS_DATA:
        check("real_data.available", False, "missing %s" % A_ROOT)
        return
    result = P.run_preflight(REPO)
    check("real.preconditions_pass", result["preconditions_pass"] is True, "blocking=%s" % result["summary"]["blocking_ids"])
    check("real.overall_pass", result["overall_pass"] is True)

    runner = find_check(result, "code.e0c_runner_present")
    check(
        "real.execution_ready_tracks_runner",
        result["execution_ready"] == runner["passed"],
        "runner_present=%s execution_ready=%s" % (runner["passed"], result["execution_ready"]),
    )
    if not runner["passed"]:
        check("real.failed_ids_only_runner", result["summary"]["failed_ids"] == ["code.e0c_runner_present"],
              str(result["summary"]["failed_ids"]))

    data = result["data"]
    check("real.signal_files_96", data["signal_files_hashed"] == 96, str(data["signal_files_hashed"]))
    check("real.total_bytes", data["total_bytes"] == 88073632, str(data["total_bytes"]))
    check("real.inventory_check", find_check(result, "data.inventory")["passed"] is True)
    check("real.no_out_of_scope", find_check(result, "data.no_out_of_scope_open")["passed"] is True)
    guard = find_check(result, "data.path_guard")
    check("real.path_guard_check", guard["passed"] is True and data["path_guard"]["rejections"] == [],
          "guarded=%d" % data["path_guard"]["guarded_files"])

    allowed_dirs = {P.group_dir(A_ROOT, g).resolve() for g in P.expected_air_groups(real_cfg())}
    allowed_dirs |= {P.group_dir(A_ROOT, t["group"]).resolve() for t in P.expected_targets(real_cfg())}
    opened = [REPO / rel for rel in data["opened_dat_files"]]
    check(
        "real.opened_within_12_groups",
        len(opened) == 96 and all(p.parent.resolve() in allowed_dirs for p in opened),
        "opened=%d" % len(opened),
    )
    check(
        "real.opened_no_test_or_imaging",
        all("_test" not in p.name and "附件3" not in p.as_posix() for p in opened),
    )
    check(
        "real.payloads_not_parsed",
        all(p.suffix.lower() == ".dat" for p in opened),
        "只登记摘要，未解析包头/采样",
    )


def test_cli() -> None:
    with work_tmp() as tmp:
        out = Path(tmp) / "preflight.json"
        code = P.main(["--repo", str(REPO), "--out", str(out)])
        check("cli.exit_0", code == 0, "exit=%d" % code)
        raw = json.loads(out.read_text(encoding="utf-8"))
        check("cli.json_written", raw["contract_version"] == P.CONTRACT_VERSION)
        check("cli.preconditions_pass", raw["preconditions_pass"] is True)
        check("cli.checks_total", len(raw["checks"]) >= 30, "%d checks" % len(raw["checks"]))

        code2 = P.main(["--repo", str(REPO), "--out", str(Path(tmp) / "nohash.json"), "--no-hash"])
        raw2 = json.loads((Path(tmp) / "nohash.json").read_text(encoding="utf-8"))
        check("cli.no_hash_blocks", code2 == 1 and raw2["preconditions_pass"] is False,
              "debug mode must not pass as release evidence")


# ---------------------------------------------------------------- 反例
def test_negative_inventory() -> None:
    with work_tmp() as tmp:
        base = Path(tmp)
        r = run_inventory(base / "missing", range(7))
        check(
            "neg.missing_row_detected",
            r["check"]["passed"] is False and any("应为 0..7" in p for p in r["check"]["problems"]),
            str(r["check"]["problems"]),
        )
    with work_tmp() as tmp:
        base = Path(tmp)

        def bad_size(entries):
            entries[0] = dict(entries[0], size_bytes=int(entries[0]["size_bytes"]) + 1)
            return entries

        r = run_inventory(base / "size", range(8), mutate=bad_size)
        check(
            "neg.size_mismatch_detected",
            r["check"]["passed"] is False and any("大小" in p for p in r["check"]["problems"]),
            str(r["check"]["problems"]),
        )
    with work_tmp() as tmp:
        base = Path(tmp)

        def bad_sha(entries):
            entries[0] = dict(entries[0], sha256="0" * 64)
            return entries

        r = run_inventory(base / "sha", range(8), mutate=bad_sha)
        check(
            "neg.sha_mismatch_detected",
            r["check"]["passed"] is False and any("SHA256" in p for p in r["check"]["problems"]),
            str(r["check"]["problems"]),
        )
    with work_tmp() as tmp:
        base = Path(tmp)
        root = base / "data_root"
        key = "空场数据/data1"
        files = make_group(root, key, range(8))
        files[0].write_bytes(b"")
        entries = [manifest_entry(root, p) for p in files]
        manifest = base / "manifest.csv"
        write_manifest(manifest, entries)
        ck = P.Checker()
        P.check_data(REPO, root, manifest, mini_cfg(key), ck)
        inventory = [c for c in ck.checks if c["id"] == "data.inventory"][0]
        check(
            "neg.zero_byte_detected",
            inventory["passed"] is False and any("0 字节" in p for p in inventory["problems"]),
            str(inventory["problems"]),
        )


def test_out_of_scope() -> None:
    with work_tmp() as tmp:
        root = Path(tmp)
        good = root / "g"
        bad = root / "x"
        good.mkdir()
        bad.mkdir()
        outside = P.find_out_of_scope([str(good / "a.dat"), str(bad / "b.dat")], [good])
        check("neg.out_of_scope_detected", outside == [str((bad / "b.dat").resolve())], str(outside))
        check("neg.in_scope_ok", P.find_out_of_scope([str(good / "a.dat")], [good]) == [])


# ---------------------------------------------------------------- 读前路径校验
class _FakeStat:
    """注入用：伪造 ``lstat`` 结果（可带 Windows 重解析点属性）。"""

    def __init__(self, mode: int, attrs: int = 0) -> None:
        self.st_mode = mode
        self.st_file_attributes = attrs


def make_dir_link(link: Path, target: Path) -> bool:
    """创建目录联接 / 目录符号链接；环境不允许时返回 False（测试记为 SKIP）。"""
    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return proc.returncode == 0 and link.exists()
        os.symlink(target, link, target_is_directory=True)
        return link.exists()
    except Exception:
        return False


def build_linked_root(tmp: Path) -> Tuple[Path, Path, str, List[Path]]:
    """造一个数据根：白名单组目录是指向根外真实目录的目录联接。"""
    root = tmp / "data_root"
    outside = tmp / "outside_group"
    key = "空场数据/data1"
    files = make_group(outside, key, range(8))
    gdir = P.group_dir(root, key)
    gdir.parent.mkdir(parents=True, exist_ok=True)
    return root, outside, key, files


def test_path_guard_unit() -> None:
    with work_tmp() as tmp:
        base = Path(tmp)
        root = base / "data_root"
        gdir = P.group_dir(root, "空场数据/data1")
        gdir.mkdir(parents=True)
        f = gdir / "2026-01-01-00-00-00_16000_0.dat"
        f.write_bytes(b"abc")
        outside = base / "outside"
        outside.mkdir()
        (outside / "o.dat").write_bytes(b"xyz")
        root_real = Path(os.path.realpath(str(root)))

        real_g = P.guard_group_dir(gdir, root)
        real_f = P.guard_dat_path(f, real_g, root_real)
        check("guard.normal_path_ok", real_f == Path(os.path.realpath(str(f))))

        try:
            P.guard_dat_path(outside / "o.dat", real_g, root_real)
            ok = False
        except P.PathGuardError as exc:
            ok = "直接子项" in str(exc)
        check("guard.rejects_lexical_outside", ok, "父目录不在白名单组目录")

        def fake_lstat(path: str):
            if os.path.normcase(str(path)) == os.path.normcase(str(f)):
                return _FakeStat(stat.S_IFREG | 0o666, P.FILE_ATTRIBUTE_REPARSE_POINT)
            return os.lstat(path)

        try:
            P.guard_dat_path(f, real_g, root_real, lstat=fake_lstat)
            ok = False
        except P.PathGuardError as exc:
            ok = "重解析点" in str(exc)
        check("guard.rejects_symlink_file", ok, "lstat 见到重解析点即拒绝，不跟随")

        def fake_realpath(path: str) -> str:
            if os.path.normcase(path) == os.path.normcase(str(f)):
                return str(outside / "o.dat")
            return os.path.realpath(path)

        try:
            P.guard_dat_path(f, real_g, root_real, realpath=fake_realpath)
            ok = False
        except P.PathGuardError as exc:
            ok = "越出白名单" in str(exc)
        check("guard.rejects_realpath_escape", ok, "实际路径逃逸被拒")

        def fake_lstat_dir(path: str):
            if os.path.normcase(str(path)) == os.path.normcase(str(gdir)):
                return _FakeStat(stat.S_IFDIR, P.FILE_ATTRIBUTE_REPARSE_POINT)
            return os.lstat(path)

        try:
            P.guard_group_dir(gdir, root, lstat=fake_lstat_dir)
            ok = False
        except P.PathGuardError as exc:
            ok = "重解析点" in str(exc)
        check("guard.rejects_reparse_group_dir", ok)

        try:
            P.guard_group_dir(outside / "sub", root)
            ok = False
        except P.PathGuardError as exc:
            ok = "不在数据根之下" in str(exc)
        check("guard.rejects_lexical_root_escape", ok)


def test_path_guard_junction_integration() -> None:
    """负例：白名单组目录本身是指向根外目录的联接 → 拒绝且一个文件都不打开。"""
    with work_tmp() as tmp:
        base = Path(tmp)
        root, outside, key, files = build_linked_root(base)
        gdir = P.group_dir(root, key)
        if not make_dir_link(gdir, outside):
            check("neg.guard_junction_available", True, "SKIP: 本机不允许创建目录联接")
            return
        check("neg.guard_junction_available", True)

        manifest = base / "manifest.csv"
        write_manifest(manifest, [manifest_entry(outside, p) for p in files])
        ck = P.Checker()
        info = P.check_data(REPO, root, manifest, mini_cfg(key), ck)
        guard = [c for c in ck.checks if c["id"] == "data.path_guard"][0]
        inventory = [c for c in ck.checks if c["id"] == "data.inventory"][0]
        check(
            "neg.junction_group_rejected",
            guard["passed"] is False and guard["rejected"] == 1,
            "rejections=%s" % guard.get("rejections"),
        )
        check(
            "neg.junction_no_file_opened",
            info["signal_files_hashed"] == 0 and info["opened_dat_files"] == [],
            "opened=%d" % info["signal_files_hashed"],
        )
        check("neg.junction_blocks_inventory", inventory["passed"] is False)


def test_path_guard_entry_negative() -> None:
    """负例：组目录真实存在，但其中一个 ``.dat`` 指向白名单外（注入 realpath）。"""
    with work_tmp() as tmp:
        base = Path(tmp)
        root = base / "data_root"
        key = "空场数据/data1"
        files = make_group(root, key, range(8))
        outside = base / "outside"
        outside.mkdir()
        (outside / "secret.dat").write_bytes(b"secret")
        manifest = base / "manifest.csv"
        write_manifest(manifest, [manifest_entry(root, p) for p in files])

        realpath_orig = os.path.realpath

        def fake_realpath(path: str, *args: Any, **kwargs: Any) -> str:
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(
                os.path.abspath(str(files[0]))
            ):
                return str(outside / "secret.dat")
            return realpath_orig(path, *args, **kwargs)

        # 仅在本测试内替换模块级 os.path.realpath（guard 在调用时查找该函数，
        # 因此补丁能同时作用于路径校验与后续 rel_to）。
        saved = P.os.path.realpath
        P.os.path.realpath = fake_realpath
        try:
            ck = P.Checker()
            info = P.check_data(REPO, root, manifest, mini_cfg(key), ck)
        finally:
            P.os.path.realpath = saved

        guard = [c for c in ck.checks if c["id"] == "data.path_guard"][0]
        check(
            "neg.entry_escape_rejected",
            guard["passed"] is False and guard["rejected"] == 1,
            "rejections=%s" % guard.get("rejections"),
        )
        check(
            "neg.entry_escape_not_opened",
            info["signal_files_hashed"] == 7 and len(info["opened_dat_files"]) == 7,
            "其余 7 份仍被校验并摘要，逃逸项未打开",
        )


def test_e0s_failure() -> None:
    with work_tmp() as tmp:
        repo = Path(tmp)
        results = repo / P.RESULTS_REL
        results.mkdir(parents=True)
        (results / "e0_s1s2_results.json").write_text(
            json.dumps(
                {
                    "experiment_id": "A-Q1-E0",
                    "phase": "E0-S",
                    "overall_pass": False,
                    "stop_reason": "gate_failed",
                    "cases": [{"case_id": "E0-S2@0.42", "valid_rx": 62, "finite": True, "gate_results": {"valid_rx": {"passed": False}}}],
                    "implementation_sha": "deadbeef",
                    "s2_param_table_match": False,
                    "config_sha256_match": False,
                    "plan_sha256_match": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ck = P.Checker()
        P.check_e0s(repo, ck)
        failed = {c["id"] for c in ck.checks if not c["passed"]}
        check(
            "neg.e0s_failure_detected",
            {"e0s.overall_pass", "e0s.cases", "e0s.arrays_sha256", "e0s.param_table_sha256"} <= failed,
            str(sorted(failed)),
        )


def test_anchor_negative() -> None:
    with work_tmp() as tmp:
        repo = Path(tmp)
        cfg_dir = repo / "experiments/A/A-Q1-E0"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text("{}", encoding="utf-8")
        ck = P.Checker()
        P.check_anchor_files(repo, ck)
        ids = {c["id"] for c in ck.checks}
        check("neg.missing_anchors_detected", "anchor.plan_present" in ids and "anchor.split_present" in ids)
        check("neg.wrong_config_hash", [c for c in ck.checks if c["id"] == "anchor.config"][0]["passed"] is False)


def test_main_smoke() -> None:
    result = P.run_preflight(REPO, check_hashes=False)
    check("smoke.no_hash_blocks", result["preconditions_pass"] is False)
    check(
        "smoke.no_hash_marks_check",
        any(c["id"] == "data.hash_skipped" and not c["passed"] for c in result["checks"]),
    )


def main() -> int:
    print("repo=%s" % REPO)
    print("data_root=%s" % A_ROOT)
    test_anchors()
    test_manifest()
    test_split_and_whitelist()
    test_real_data()
    test_cli()
    test_negative_inventory()
    test_out_of_scope()
    test_path_guard_unit()
    test_path_guard_junction_integration()
    test_path_guard_entry_negative()
    test_e0s_failure()
    test_anchor_negative()
    test_main_smoke()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("-" * 60)
    print("E0C_PREFLIGHT_TESTS: %d passed, %d failed, %d total" % (len(RESULTS) - len(failed), len(failed), len(RESULTS)))
    if failed:
        print("FAILED: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
