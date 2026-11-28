#!/usr/bin/env python
"""A-Q1-E0-S2 固定种子参数表的独立复现探针（E0-PREREG-1）。

用途
----
1. 不导入任何生产 E0 代码，仅用 numpy 按已批复方案复现 `E0-S2` 的 62 路
   （rx = 0..63，去掉 tx=27 与 ref=28）随机参数抽取：
   每路依次抽 delta_tau ~ U(-0.75, 0.75) ns、gain ~ U(0.5, 1.5)、
   psi0 ~ U(-0.5, 0.5)、psi2 ~ U(-0.3, 0.3)，顺序与 `config.json` 的
   `channel_draw_order` 一致。
2. 与本目录 `e0_s2_param_table.json` 对比，并核对规范 JSON 的 SHA256。
3. 若给出实现侧导出的同格式表，可逐项对比，证明实现使用的是同一组参数。

运行
----
    python checks/A/e0_s2_table_probe.py
    python checks/A/e0_s2_table_probe.py --impl out/e0_s2_params.json

退出码：0 表示完全一致；1 表示不一致（会打印差异）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TABLE_PATH = HERE / "e0_s2_param_table.json"
SEED = 20261128
EXPECTED_SHA256 = "aa86bf56fb138789cd0ad4375691293e7d0e5d65a2daf678d151d44720576e96"
RX_IDX = [i for i in range(64) if i not in (27, 28)]


def build_table() -> dict:
    rng = np.random.default_rng(SEED)
    rows = []
    for i in RX_IDX:
        rows.append([
            i,
            float(rng.uniform(-0.75e-9, 0.75e-9)),
            float(rng.uniform(0.5, 1.5)),
            float(rng.uniform(-0.5, 0.5)),
            float(rng.uniform(-0.3, 0.3)),
        ])
    return {
        "experiment": "A-Q1-E0-S2",
        "seed": SEED,
        "rng": "numpy.random.default_rng(20261128)",
        "draw_order": ("for rx in sorted(0..63 excluding 27,28): "
                       "Uniform(-0.75e-9,0.75e-9), Uniform(0.5,1.5), "
                       "Uniform(-0.5,0.5), Uniform(-0.3,0.3)"),
        "columns": ["rx_idx", "delta_tau_s", "gain_mag", "psi0_rad", "psi2_u2_rad"],
        "rows": rows,
    }


def canonical_sha256(table: dict) -> str:
    blob = json.dumps(table, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compare_tables(got: dict, want: dict) -> int:
    if len(got.get("rows", [])) != len(want["rows"]):
        print("[FAIL] 行数 %d != %d" % (len(got.get("rows", [])), len(want["rows"])))
        return 1
    bad = 0
    for a, b in zip(got["rows"], want["rows"]):
        if len(a) != 5 or int(a[0]) != int(b[0]):
            print("[FAIL] 行索引/列数不符: %r vs %r" % (a, b))
            bad += 1
            continue
        for j, name in enumerate(["delta_tau_s", "gain_mag", "psi0_rad", "psi2_u2_rad"], 1):
            if float(a[j]) != float(b[j]):
                print("[FAIL] rx=%d %s %.17g != %.17g"
                      % (int(a[0]), name, float(a[j]), float(b[j])))
                bad += 1
    print("[%s] 逐项对比：%d 行，%d 处差异"
          % ("PASS" if bad == 0 else "FAIL", len(want["rows"]), bad))
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--impl", metavar="PATH",
                    help="实现侧导出的同格式参数表 JSON（可选）")
    ap.add_argument("--write", metavar="PATH",
                    help="把复现表写到指定路径（可选）")
    args = ap.parse_args(argv)

    table = build_table()
    digest = canonical_sha256(table)
    print("复现表：%d 行；规范 JSON SHA256 = %s" % (len(table["rows"]), digest))
    rc = 0
    if digest != EXPECTED_SHA256:
        print("[FAIL] 规范 SHA256 与预登记值不一致：期望 %s" % EXPECTED_SHA256)
        rc = 1

    if TABLE_PATH.exists():
        committed = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
        committed_digest = canonical_sha256(committed)
        print("入库表：规范 SHA256 = %s" % committed_digest)
        if committed_digest != EXPECTED_SHA256:
            print("[FAIL] 入库表与预登记 SHA256 不一致")
            rc = 1
        rc |= compare_tables(committed, table)
    else:
        print("[WARN] 未找到 %s，仅做内存复现" % TABLE_PATH)

    if args.impl:
        got = json.loads(Path(args.impl).read_text(encoding="utf-8"))
        print("实现表：%s" % args.impl)
        rc |= compare_tables(got, table)

    if args.write:
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(
            json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("已写入 %s" % args.write)

    print("[%s] E0-S2 参数表复现" % ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
