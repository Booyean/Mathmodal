#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A-Q1-SPLIT0 数据级核对（独立验证）。

目的：控制表要求“墙体与金属板各 20 组先提出分层的 10/10 校准/检验拆分，
统筹与验证者核对后固化清单”。此前 M0-18 只把冻结清单与规范 §6.2 的文本逐名
对账，D0 明确“拆分/标签未参与验收”。本脚本补做**数据级**核对：

  * 冻结清单中的每个组是否真实存在、是否 8 行齐全、是否 0 字节；
  * 真实目录里是否还有清单之外的组（漏登记）；
  * 距离标签是否可从目录名解析、是否与清单 limitations 一致、是否覆盖 1..20；
  * 每个组文件的大小/SHA256 是否与 R0 清单逐文件一致（证明数据未被替换）；
  * 全语料文件数与总字节数是否与 R0 记录一致；
  * E0 登记中引用的四个组是否分别落在其声称的拆分集合内，且 73/60 cm
    是否真的位于各自校准集的内插区间内。

本脚本只读 `coordination/A_Q1_SPLIT.json`、原始 `.dat` 目录与（可选）R0 清单，
不导入任何 `solutions/A` 生产代码，不写数据，不做校准/测距。

用法：
    python checks/A/verify_split0.py \
        --data-root "<...>/附件" \
        --manifest recon/manifests/a_dat_manifest.csv \
        --json checks/A/split0_results.json

`--data-root` 是包含 `附件2-测距数据/` 的“附件”目录；缺省为本仓库的
`竞赛题目/A 题：.../附件`。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

DATASET_DIR = "附件2-测距数据"
SPLIT_LISTS = ("wall_cal", "wall_test", "metal_cal", "metal_test")
GROUP_RE = re.compile(r"^data(\d+)-(\d+)cm$")
AIR_RE = re.compile(r"^data(\d+)$")
FILE_RE = re.compile(r"_16000_(\d+)\.dat$")

SPLIT_BLOB_SHA256_LF = (
    "d623da4ea186f372f2be094121c202c55dae0e236f4683005ab88d220a248b3a"
)


class Checker:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def check(self, cid: str, title: str, ok: bool, expected: str, actual: str) -> bool:
        self.checks.append(
            {
                "id": cid,
                "title": title,
                "status": "PASS" if ok else "FAIL",
                "expected": expected,
                "actual": actual,
            }
        )
        return ok

    def summary(self) -> dict:
        n_pass = sum(1 for c in self.checks if c["status"] == "PASS")
        return {
            "n_checks": len(self.checks),
            "n_pass": n_pass,
            "n_fail": len(self.checks) - n_pass,
            "all_pass": n_pass == len(self.checks),
            "checks": self.checks,
        }


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_split(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def list_groups(dataset_root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sub in ("空场数据", "墙体数据", "金属板数据"):
        d = dataset_root / sub
        if d.is_dir():
            out[sub] = sorted(p.name for p in d.iterdir() if p.is_dir())
        else:
            out[sub] = []
    return out


def group_files(group_dir: Path) -> list[Path]:
    return sorted(p for p in group_dir.glob("*.dat") if p.is_file())


def parse_manifest(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows[row["rel_path"]] = row
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A-Q1-SPLIT0 data-level verification")
    ap.add_argument("--data-root", required=True, type=Path,
                    help="directory that contains 附件2-测距数据/")
    ap.add_argument("--split", type=Path,
                    default=Path("coordination/A_Q1_SPLIT.json"))
    ap.add_argument("--manifest", type=Path, default=None,
                    help="optional recon/manifests/a_dat_manifest.csv")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    ck = Checker()
    split = load_split(args.split)
    dataset_root = args.data_root / DATASET_DIR
    results: dict = {
        "tool": "checks/A/verify_split0.py",
        "data_root": str(args.data_root),
        "split": str(args.split),
        "manifest": str(args.manifest) if args.manifest else None,
    }

    # ---- S0-01 冻结记录本身 ----
    ok = (
        split.get("schema_version") == 1
        and split.get("approval_id") == "A-Q1-SPLIT0"
        and split.get("status") == "frozen"
    )
    ck.check("S0-01", "冻结记录字段", ok,
             "schema_version=1, approval_id=A-Q1-SPLIT0, status=frozen",
             f"schema={split.get('schema_version')}, id={split.get('approval_id')}, "
             f"status={split.get('status')}")

    # ---- S0-02/S0-03 四组各 10、组内唯一、索引并集 1..20 ----
    lists = {k: list(split.get("groups", {}).get(k, [])) for k in SPLIT_LISTS}
    ok = all(len(v) == 10 for v in lists.values()) and all(
        len(set(v)) == len(v) for v in lists.values()
    )
    ck.check("S0-02", "四组各 10 项且组内唯一", ok,
             "wall_cal/wall_test/metal_cal/metal_test 各 10 且无重复",
             ", ".join(f"{k}={len(v)} (uniq {len(set(v))})" for k, v in lists.items()))

    def indices(names: list[str]) -> set[int]:
        out = set()
        for n in names:
            m = GROUP_RE.match(n)
            if not m:
                return set()
            out.add(int(m.group(1)))
        return out

    wall_idx = indices(lists["wall_cal"] + lists["wall_test"])
    metal_idx = indices(lists["metal_cal"] + lists["metal_test"])
    ok = (
        len(wall_idx) == 20 and wall_idx == set(range(1, 21))
        and len(metal_idx) == 20 and metal_idx == set(range(1, 21))
        and not (set(lists["wall_cal"]) & set(lists["wall_test"]))
        and not (set(lists["metal_cal"]) & set(lists["metal_test"]))
    )
    ck.check("S0-03", "10/10 拆分索引覆盖与互斥", ok,
             "墙体、金属板各自 1..20 全覆盖且 cal/test 无交集",
             f"wall_idx={sorted(wall_idx)}, metal_idx={sorted(metal_idx)}, "
             f"wall_overlap={sorted(set(lists['wall_cal']) & set(lists['wall_test']))}, "
             f"metal_overlap={sorted(set(lists['metal_cal']) & set(lists['metal_test']))}")

    air_list = list(split.get("air_template_groups", []))
    ok = air_list == [f"data{i}" for i in range(1, 11)]
    ck.check("S0-04", "空场模板组清单", ok, "data1..data10 升序",
             f"{len(air_list)} 项: {air_list[:3]}...{air_list[-1:]}" if air_list else "空")

    # ---- 真实目录清单 ----
    real = list_groups(dataset_root)
    results["real_groups"] = real
    all_split_groups = {k: v for k, v in lists.items()}

    # ---- S0-05 每个组真实存在且 8 行齐全 ----
    missing_dirs: list[str] = []
    bad_rows: list[dict] = []
    zero_byte: list[str] = []
    prefixes: dict[str, set[str]] = {}
    group_files_map: dict[str, list[Path]] = {}
    for dataset, sub in (
        ("墙体数据", "墙体数据"),
        ("金属板数据", "金属板数据"),
        ("空场数据", "空场数据"),
    ):
        names = []
        if sub == "空场数据":
            names = air_list
        else:
            names = all_split_groups["wall_cal" if sub == "墙体数据" else "metal_cal"] + \
                    all_split_groups["wall_test" if sub == "墙体数据" else "metal_test"]
        for name in names:
            gd = dataset_root / sub / name
            if not gd.is_dir():
                missing_dirs.append(f"{sub}/{name}")
                continue
            files = group_files(gd)
            group_files_map[f"{sub}/{name}"] = files
            rows = set()
            for fp in files:
                m = FILE_RE.search(fp.name)
                if m:
                    rows.add(int(m.group(1)))
                if fp.stat().st_size == 0:
                    zero_byte.append(str(fp))
            if rows != set(range(8)) or len(files) != 8:
                bad_rows.append({"group": f"{sub}/{name}", "n_files": len(files),
                                 "rows": sorted(rows)})
            pre = {fp.name.rsplit("_16000_", 1)[0] for fp in files}
            prefixes[f"{sub}/{name}"] = pre
    ok = not missing_dirs and not bad_rows
    ck.check("S0-05", "清单中 50 个组真实存在且 8 行齐全", ok,
             "50/50 组目录存在，每组 8 个 *_16000_0..7.dat",
             f"missing={missing_dirs}, bad_rows={bad_rows}")
    ok = not zero_byte
    ck.check("S0-06", "无 0 字节数据文件", ok, "0 个 0 字节文件",
             f"{len(zero_byte)} 个: {zero_byte[:3]}")

    # ---- S0-07 真实目录没有清单外组（漏登记） ----
    real_wall = set(real.get("墙体数据", []))
    real_metal = set(real.get("金属板数据", []))
    real_air = set(real.get("空场数据", []))
    extra = {
        "墙体数据": sorted(real_wall - set(lists["wall_cal"] + lists["wall_test"])),
        "金属板数据": sorted(real_metal - set(lists["metal_cal"] + lists["metal_test"])),
        "空场数据": sorted(real_air - set(air_list)),
    }
    missing = {
        "墙体数据": sorted(set(lists["wall_cal"] + lists["wall_test"]) - real_wall),
        "金属板数据": sorted(set(lists["metal_cal"] + lists["metal_test"]) - real_metal),
        "空场数据": sorted(set(air_list) - real_air),
    }
    ok = all(not v for v in extra.values()) and all(not v for v in missing.values())
    ck.check("S0-07", "真实目录与清单一致（无漏登记/无多余）", ok,
             "墙体 20、金属板 20、空场 10 与清单集合完全相等",
             f"extra={extra}, missing={missing}, real_counts="
             f"{{{', '.join(f'{k}:{len(v)}' for k, v in real.items())}}}")

    # ---- S0-08 距离标签与 limitations ----
    def distances(names: list[str]) -> list[int]:
        return [int(GROUP_RE.match(n).group(2)) for n in names]

    d_wall_cal = distances(lists["wall_cal"])
    d_wall_test = distances(lists["wall_test"])
    d_metal_cal = distances(lists["metal_cal"])
    d_metal_test = distances(lists["metal_test"])
    lim = split.get("limitations", {})
    wall_limit = lim.get("wall_extrapolation_test_cm_above")
    metal_limit = lim.get("metal_extrapolation_test_cm_above")
    test_max = lim.get("test_max_cm", {})
    ok = (
        max(d_wall_cal) == wall_limit == 106
        and max(d_wall_test) == test_max.get("wall") == 121
        and max(d_metal_cal) == metal_limit == 91
        and max(d_metal_test) == test_max.get("metal") == 99
    )
    ck.check("S0-08", "距离标签与 limitations 一致", ok,
             "墙体校准 max=106、检验 max=121；金属板校准 max=91、检验 max=99",
             f"wall_cal={sorted(d_wall_cal)}, wall_test_max={max(d_wall_test)}, "
             f"metal_cal={sorted(d_metal_cal)}, metal_test_max={max(d_metal_test)}, "
             f"limitations={lim}")

    # ---- S0-09 cal/test 距离交错（内插区存在，不是简单前后切分） ----
    ok = (
        max(d_wall_cal) > min(d_wall_test) and max(d_wall_test) > min(d_wall_cal)
        and max(d_metal_cal) > min(d_metal_test) and max(d_metal_test) > min(d_metal_cal)
    )
    ck.check("S0-09", "校准/检验距离区间交错", ok,
             "两组数据 cal 与 test 距离区间均重叠",
             f"wall cal=[{min(d_wall_cal)},{max(d_wall_cal)}] "
             f"test=[{min(d_wall_test)},{max(d_wall_test)}]; "
             f"metal cal=[{min(d_metal_cal)},{max(d_metal_cal)}] "
             f"test=[{min(d_metal_test)},{max(d_metal_test)}]")

    # ---- S0-10 E0 登记引用的四个组落到声称的拆分集合 ----
    e0_facts = {
        "墙体数据/data1-42cm": ("wall_cal", 42),
        "金属板数据/data1-69cm": ("metal_cal", 69),
        "墙体数据/data20-73cm": ("wall_test", 73),
        "金属板数据/data5-60cm": ("metal_test", 60),
    }
    bad_e0 = []
    for key, (want_set, dist) in e0_facts.items():
        sub, name = key.split("/")
        got_set = None
        for set_name in SPLIT_LISTS:
            if name in lists[set_name]:
                got_set = set_name
                break
        if got_set != want_set:
            bad_e0.append(f"{key}: 期望 {want_set} 实得 {got_set}")
    wall_inside = min(d_wall_cal) <= 73 <= max(d_wall_cal)
    metal_inside = min(d_metal_cal) <= 60 <= max(d_metal_cal)
    ok = not bad_e0 and wall_inside and metal_inside
    ck.check("S0-10", "E0 引用组的拆分归属与内插区间", ok,
             "data1-42cm∈wall_cal、data1-69cm∈metal_cal、"
             "data20-73cm∈wall_test、data5-60cm∈metal_test；73∈墙体校准区间、60∈金属板校准区间",
             f"错配={bad_e0}; 73∈[{min(d_wall_cal)},{max(d_wall_cal)}]={wall_inside}; "
             f"60∈[{min(d_metal_cal)},{max(d_metal_cal)}]={metal_inside}")

    # ---- S0-11 每组时间戳前缀唯一 ----
    multi = {k: sorted(v) for k, v in prefixes.items() if len(v) != 1}
    ck.check("S0-11", "每组文件同一采集前缀", not multi,
             "50/50 组内 8 个文件共享同一 <timestamp>_16000_ 前缀",
             f"前缀不唯一的组={multi}")

    # ---- S0-12 逐文件 size/SHA256 与 R0 清单一致 ----
    if args.manifest is not None:
        man = parse_manifest(args.manifest)
        n_checked = 0
        mismatches: list[str] = []
        for key, files in group_files_map.items():
            sub, name = key.split("/")
            for fp in files:
                rel = (Path(DATASET_DIR) / sub / name / fp.name).as_posix()
                rel = f"附件/{rel}"
                row = man.get(rel)
                if row is None:
                    mismatches.append(f"清单缺 {rel}")
                    continue
                n_checked += 1
                if int(row["size_bytes"]) != fp.stat().st_size:
                    mismatches.append(f"size {rel}")
                    continue
                if sha256_file(fp) != row["sha256"]:
                    mismatches.append(f"sha {rel}")
        ok = not mismatches and n_checked == 400
        ck.check("S0-12", "逐文件 size/SHA256 与 R0 清单一致", ok,
                 "400/400 文件与 a_dat_manifest.csv 的 size、sha256 相同",
                 f"核对 {n_checked} 个，不一致 {len(mismatches)}: {mismatches[:3]}")
    else:
        ck.check("S0-12", "逐文件 size/SHA256 与 R0 清单一致", False,
                 "需要 --manifest", "未提供 --manifest，跳过（记为失败以便显式）")

    # ---- S0-13 全语料文件数与总字节 ----
    corpus = [p for p in args.data_root.rglob("*.dat") if p.is_file()]
    total = sum(p.stat().st_size for p in corpus)
    ok = len(corpus) == 881 and total == 801_111_612
    ck.check("S0-13", "全语料文件数与总字节", ok,
             "881 文件 / 801,111,612 B", f"{len(corpus)} 文件 / {total} B")

    # ---- S0-14 冻结文件 blob SHA256（LF 归一） ----
    raw = args.split.read_bytes()
    blob = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    ok = blob == SPLIT_BLOB_SHA256_LF
    ck.check("S0-14", "冻结文件 LF 归一 SHA256", ok,
             SPLIT_BLOB_SHA256_LF, blob)

    # ---- S0-15 所有目标距离落在 E0 搜索区间内（独立事实） ----
    all_dist = d_wall_cal + d_wall_test + d_metal_cal + d_metal_test
    ok = all(15 <= d <= 200 for d in all_dist)
    ck.check("S0-15", "目标距离落在 0.15–2.00 m 搜索区间", ok,
             "40 个目标距离均 ∈ [15, 200] cm",
             f"min={min(all_dist)} cm, max={max(all_dist)} cm")

    out = ck.summary()
    results.update(out)
    print(f"A-Q1-SPLIT0 data-level verification: {out['n_pass']}/{out['n_checks']} passed")
    for c in out["checks"]:
        print(f"  [{c['status']}] {c['id']} {c['title']}: {c['actual']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"wrote {args.json}")
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
