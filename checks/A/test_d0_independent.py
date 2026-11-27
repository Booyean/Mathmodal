#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D0 独立验收：字节级独立解析 + 与作者读取器逐项对照 + 边界用例。

这个脚本的期望值来自 ``get_data_iq.m`` 的协议定义和题面配置，不是来自
``solutions/A/a_dat_reader.py``：独立实现扫描 881 个 ``.dat``（魔数 4 字节对齐、
``total_len`` 语义、``num*len/2`` 个 int16、``reshape(8, [])``），再与作者读取器的
输出、R0 清单和契约条款对照。

用法::

    python checks/A/test_d0_independent.py
    python checks/A/test_d0_independent.py --root "竞赛题目/A 题：..." --reader solutions/A/a_dat_reader.py
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import struct
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np

MAGIC = 963072
TYPE_DATA = 102
HEADER_BYTES = 28
SAMPLES = 16000
N_CH = 64
N_ROWS = 8

RESULTS: list[dict] = []


def check(name: str, expected, actual, note: str = "") -> bool:
    ok = bool(np.array_equal(np.asarray(expected), np.asarray(actual))) if isinstance(
        expected, np.ndarray) else (expected == actual)
    RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL",
                    "expected": expected, "actual": actual})
    print("[%s] %-58s expected=%r actual=%r%s" % (
        "PASS" if ok else "FAIL", name, expected, actual,
        ("  " + note) if note else ""))
    return ok


def skip(name: str, why: str) -> None:
    RESULTS.append({"name": name, "status": "SKIP", "expected": "-", "actual": why})
    print("[SKIP] %-58s %s" % (name, why))


# --------------------------------------------------------------------------
# Independent parser (written from get_data_iq.m, not from the reader)
# --------------------------------------------------------------------------
def u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def scan_dat(buf: bytes) -> tuple[list[dict], list[str], int, int]:
    """Return (packets, problem_codes, skipped_bytes, trailing_bytes)."""
    n = len(buf)
    pos = 0
    packets: list[dict] = []
    problems: list[str] = []
    first_data_off = None
    data_end = 0
    while True:
        # get_data_iq.m reads uint32 at 4-byte steps, so search is 4-byte aligned.
        while pos + 4 <= n and u32(buf, pos) != MAGIC:
            pos += 4
        if pos + 4 > n:
            break
        if pos + 12 > n:
            problems.append("truncated_header")
            break
        total_len = u32(buf, pos + 4)
        ptype = u32(buf, pos + 8)
        if ptype != TYPE_DATA:
            problems.append("non_data_packet")
            pos = pos + 12 + (total_len - 4)
            if pos > n:
                problems.append("bad_skip")
                break
            continue
        if pos + HEADER_BYTES > n:
            problems.append("truncated_packet_header")
            break
        freq_bits = u32(buf, pos + 12)
        freq = struct.unpack_from("<f", buf, pos + 12)[0]
        sync = u32(buf, pos + 16)
        num = u32(buf, pos + 20)
        ln = u32(buf, pos + 24)
        nbytes = num * ln
        nvals = nbytes // 2
        off = pos + HEADER_BYTES
        if nbytes <= 0 or nvals <= 0:
            problems.append("zero_length_packet")
            pos = off
            continue
        if off + nbytes > n:
            problems.append("truncated_samples")
            break
        if nvals % 8 != 0:
            problems.append("sample_count_not_multiple_of_8")
            pos = off + nbytes
            continue
        if first_data_off is None:
            first_data_off = pos
        packets.append({"sync": sync, "num": num, "len": ln, "freq": freq,
                        "freq_bits": freq_bits, "off": off, "nbytes": nbytes,
                        "n_samples": nvals // 8,
                        "header_ok": total_len == 20 + nbytes})
        data_end = off + nbytes
        pos = data_end
    trailing = n - data_end
    if trailing:
        problems.append("trailing_bytes")
    return packets, problems, 0, trailing


def matrix(buf: bytes, pkt: dict) -> np.ndarray:
    arr = np.frombuffer(buf, dtype="<i2", count=pkt["nbytes"] // 2, offset=pkt["off"])
    return arr.reshape(pkt["n_samples"], 8).T


def endpoints(arr: np.ndarray) -> tuple[int, int, int]:
    a = arr.astype(np.int32)
    return (int(np.count_nonzero(a == 32767)),
            int(np.count_nonzero(a == -32768)),
            int(np.count_nonzero(a == 0)))


# --------------------------------------------------------------------------
# Synthetic writer (independent of the reader)
# --------------------------------------------------------------------------
def mk_packet(sync: int, num: int = SAMPLES, ln: int = 16, ptype: int = TYPE_DATA,
              fill: int = 0, data: np.ndarray | None = None,
              total_len: int | None = None) -> bytes:
    if data is None:
        vals = (np.arange(num * ln // 2, dtype=np.int32) % 1000 + fill).astype(np.int16)
    else:
        vals = np.asarray(data, dtype=np.int16)
    body = vals.tobytes()
    tl = 20 + len(body) if total_len is None else int(total_len)
    return (struct.pack("<III", MAGIC, tl, ptype)
            + struct.pack("<fIII", 0.0, sync, num, ln) + body)


def write_group(root: Path, name: str, rows: dict[int, list[bytes]],
                prefix: str = "2026-01-01-00-00-00_16000") -> Path:
    d = root / "附件2-测距数据" / "墙体数据" / name
    d.mkdir(parents=True, exist_ok=True)
    for r, packets in rows.items():
        (d / f"{prefix}_{r}.dat").write_bytes(b"".join(packets))
    return d


def load_reader(path: Path):
    spec = importlib.util.spec_from_file_location("d0_reader_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclasses resolves cls.__module__ via sys.modules
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# A. Full-corpus independent scan and manifest reconciliation
# --------------------------------------------------------------------------
def corpus_scan(root: Path) -> dict:
    files = sorted(root.rglob("*.dat"))
    total_bytes = 0
    total_packets = 0
    bad_headers = []
    bad_fields = []
    problem_files = []
    per_file = {}
    for fp in files:
        buf = fp.read_bytes()
        packets, problems, _, trailing = scan_dat(buf)
        total_bytes += len(buf)
        total_packets += len(packets)
        if any(not p["header_ok"] for p in packets):
            bad_headers.append(str(fp.relative_to(root)))
        if any(p["num"] != SAMPLES or p["len"] != 16 or p["freq"] != 0.0 for p in packets):
            bad_fields.append(str(fp.relative_to(root)))
        if problems:
            problem_files.append((str(fp.relative_to(root)), problems))
        pos = neg = zero = 0
        for p in packets:
            a, b, c = endpoints(matrix(buf, p))
            pos += a; neg += b; zero += c
        per_file[str(fp.relative_to(root)).replace("\\", "/")] = {
            "size": len(buf), "sha256": hashlib.sha256(buf).hexdigest(),
            "syncs": [p["sync"] for p in packets], "n": len(packets),
            "num": sorted({p["num"] for p in packets}),
            "len": sorted({p["len"] for p in packets}),
            "pos": pos, "neg": neg, "zero": zero, "trailing": trailing,
        }
    return {"files": files, "per_file": per_file, "total_bytes": total_bytes,
            "total_packets": total_packets, "bad_headers": bad_headers,
            "bad_fields": bad_fields, "problem_files": problem_files}


def reconcile_manifest(root: Path, per_file: dict) -> tuple[int, int, int, list[str]]:
    repo = root.parents[1]
    csv = repo / "recon" / "manifests" / "a_dat_manifest.csv"
    if not csv.is_file():
        return 0, 0, 0, ["manifest missing"]
    import csv as _csv
    rows = list(_csv.DictReader(csv.open(encoding="utf-8")))
    sha_ok = cnt_ok = endp_ok = 0
    diffs = []
    for row in rows:
        rel = row["rel_path"].replace("\\", "/")
        mine = per_file.get(rel)
        if mine is None:
            diffs.append("missing " + rel)
            continue
        if mine["sha256"] == row["sha256"] or (
                not row["sha256"].strip() and int(row["size_bytes"]) == 0):
            sha_ok += 1
        else:
            diffs.append("sha " + rel)
        if (mine["n"] == int(row["n_packets"])
                and mine["syncs"] == [int(x) for x in row["sync_ids"].split(",")
                                      if x.strip()]):
            cnt_ok += 1
        else:
            diffs.append("count/sync " + rel)
        def _i(key: str) -> int:
            v = row.get(key, "")
            return int(v) if str(v).strip() else 0
        if (mine["pos"] == _i("n_at_int16_pos_max")
                and mine["neg"] == _i("n_at_int16_neg_min")
                and mine["zero"] == _i("n_zero")):
            endp_ok += 1
        else:
            diffs.append("endpoint " + rel)
    return sha_ok, cnt_ok, endp_ok, diffs


# --------------------------------------------------------------------------
# B. Grouping and specific corpus facts
# --------------------------------------------------------------------------
ROW_RE = re.compile(r"^(?P<prefix>.+)_(?P<row>[0-7])\.dat$")
GROUP_RE = re.compile(r"^data\d+(?:-\d+cm)?$")


def my_groups(root: Path) -> dict[str, dict[int, Path]]:
    buckets: dict[tuple[str, str], dict[int, Path]] = defaultdict(dict)
    for fp in sorted(root.rglob("*.dat")):
        m = ROW_RE.match(fp.name)
        if not m:
            continue
        rel = fp.parent.relative_to(root).as_posix()
        buckets[(rel, m.group("prefix"))][int(m.group("row"))] = fp
    out = {}
    for (rel, prefix), files in buckets.items():
        parts = rel.split("/")
        if GROUP_RE.match(parts[-1]):
            name, ds = parts[-1], "/".join(parts[:-1])
        else:
            name, ds = prefix, "/".join(parts)
        if ds.startswith("附件/"):
            ds = ds[len("附件/"):]
        out[f"{ds}/{name}"] = files
    return out


def group_files(root: Path, key: str) -> dict[int, Path]:
    groups = my_groups(root)
    return groups[key]


def run_corpus(root: Path, reader) -> None:
    scan = corpus_scan(root)
    files = scan["files"]
    check("D0-A1 .dat 文件数", 881, len(files))
    check("D0-A2 总字节", 801111612, scan["total_bytes"])
    check("D0-A3 采样包总数", 3129, scan["total_packets"])
    check("D0-A4 全部包头 header_ok", [], scan["bad_headers"])
    check("D0-A5 全部包 num=16000/len=16/freq=0", [], scan["bad_fields"])
    check("D0-A6 无文件级问题（截断/残留/非数据包）", [], scan["problem_files"])

    sha_ok, cnt_ok, endp_ok, diffs = reconcile_manifest(root, scan["per_file"])
    n = len(scan["per_file"])
    check("D0-A7 R0 清单 SHA256 对账", n, sha_ok)
    check("D0-A8 R0 清单包数/sync 对账", n, cnt_ok)
    check("D0-A9 R0 清单端点对账", n, endp_ok)
    if diffs:
        print("   manifest diffs (first 5):", diffs[:5])

    # Independent grouping vs the reader's discover_groups
    mine = my_groups(root)
    theirs, scan_problems = reader.discover_groups(root)
    their_keys = [g.group_key for g in theirs]
    check("D0-B1 组数", 111, len(mine))
    check("D0-B2 组键集合与作者一致", sorted(mine), sorted(their_keys))
    check("D0-B3 扫描问题", [], [p.as_dict()["code"] for p in scan_problems])
    # Independent completeness: 8 rows and every file non-empty
    complete, incomplete = 0, []
    zero_files = []
    for k, files in mine.items():
        sizes = [fp.stat().st_size for fp in files.values()]
        if len(files) == 8 and all(s > 0 for s in sizes):
            complete += 1
        else:
            incomplete.append(k)
        zero_files += [str(fp.relative_to(root)).replace("\\", "/")
                       for fp, s in zip(files.values(), sizes) if s == 0]
    check("D0-B4b 完整组数 / 不完整组", (110, [
        "附件3-成像数据/金属柱和金属铲/2026-11-12-22-50-31_16000"]),
        (complete, sorted(incomplete)))
    check("D0-B4c 0 字节文件只有 1 个",
          ["附件/附件3-成像数据/金属柱和金属铲/2026-11-12-22-50-31_16000_7.dat"],
          zero_files)
    ds_count = defaultdict(int)
    for k in mine:
        ds_count[k.rsplit("/", 1)[0]] += 1
    check("D0-B4 各数据集组数", {
        "附件2-测距数据/空场数据": 10, "附件2-测距数据/墙体数据": 20,
        "附件2-测距数据/金属板数据": 20, "附件3-成像数据/墙体": 33,
        "附件3-成像数据/金属柱和金属铲": 28}, dict(ds_count))

    # data10-82cm: per-row packet counts and common intersection
    g = group_files(root, "附件2-测距数据/墙体数据/data10-82cm")
    counts = []
    syncs = {}
    for r in range(8):
        buf = g[r].read_bytes()
        pk, probs, _, _ = scan_dat(buf)
        counts.append(len(pk))
        syncs[r] = [p["sync"] for p in pk]
    common = sorted(set.intersection(*(set(v) for v in syncs.values())))
    check("D0-C1 data10-82cm 逐行包数", [2, 2, 3, 3, 2, 2, 3, 3], counts)
    check("D0-C2 data10-82cm 共同 sync", [398, 399], common)
    rows400 = [r for r in range(8) if 400 in syncs[r]]
    check("D0-C3 sync=400 只出现在 4 行", 4, len(rows400))

    # -32768 case
    key = "附件3-成像数据/金属柱和金属铲/2026-11-12-22-09-58_16000"
    g = group_files(root, key)
    per_row_neg = {}
    neg_detail = []
    for r, fp in g.items():
        buf = fp.read_bytes()
        pk, _, _, _ = scan_dat(buf)
        tot = 0
        for p in pk:
            a = matrix(buf, p).astype(np.int32)
            k = int(np.count_nonzero(a == -32768))
            tot += k
            if k:
                neg_detail.append((r, p["sync"], k))
        per_row_neg[r] = tot
    check("D0-C4 -32768 总数", 46, sum(per_row_neg.values()))
    check("D0-C5 -32768 全部在 row1/sync250", [(1, 250, 46)], neg_detail)
    common = sorted(set.intersection(*(set(p["sync"] for p in scan_dat(fp.read_bytes())[0])
                                      for fp in g.values())))
    check("D0-C6 该组共同包不含 sync250", True, 250 not in common)
    check("D0-C7 该组共同包数", 3, len(common))

    # 0-byte group
    key = "附件3-成像数据/金属柱和金属铲/2026-11-12-22-50-31_16000"
    g = group_files(root, key)
    check("D0-C8 0 字节组只有 row7 且为 0 字节",
          ([7], 0), (sorted(g), g[7].stat().st_size))
    ref = reader.find_group(root, key)
    try:
        reader.load_group(ref)
        raised = None
    except reader.IncompleteGroupError as exc:
        raised = (exc.missing_rows, exc.empty_rows)
    check("D0-C9 strict 模式拒绝缺行/空行", ([0, 1, 2, 3, 4, 5, 6], [7]), raised)
    # 该组没有任何可用行；实现即使 allow-incomplete 也报“没有可用行文件”。
    # 契约 §3 写的是“allow-incomplete 时该行通道无效”，这里按实际行为核对，
    # 并把措辞差异作为非阻断发现记录。
    try:
        gd = reader.load_group(ref, require_all_rows=False)
        behavior = "returned P=%d" % gd.packets.shape[0]
    except reader.IncompleteGroupError:
        behavior = "IncompleteGroupError: 没有任何可用行文件"
    check("D0-C10 全空组的 allow-incomplete 行为", "IncompleteGroupError: 没有任何可用行文件",
          behavior)
    # 契约 D0-2 的“P=0 仍返回 64 项 channel_valid”由可用的部分行用例覆盖（S4）。

    # data1-42cm: array-level equality with the independent parser
    key = "附件2-测距数据/墙体数据/data1-42cm"
    g = group_files(root, key)
    ref = reader.find_group(root, key)
    gd = reader.load_group(ref)
    indep_buf = {r: g[r].read_bytes() for r in range(8)}
    indep_sync = {r: [p["sync"] for p in scan_dat(indep_buf[r])[0]] for r in range(8)}
    common = sorted(set.intersection(*(set(v) for v in indep_sync.values())))
    check("D0-D1 data1-42cm sync", common, gd.sync.tolist())
    ok_all = True
    for pi, s in enumerate(common):
        for r in range(8):
            pk = scan_dat(indep_buf[r])[0]
            idx = [p["sync"] for p in pk].index(s)
            m = matrix(indep_buf[r], pk[idx])
            if not np.array_equal(m, gd.packets[pi, 8 * r:8 * r + 8, :]):
                ok_all = False
    check("D0-D2 data1-42cm 全通道数组逐点一致", True, ok_all)
    check("D0-D3 packets dtype/shape", ("int16", (3, 64, 16000)),
          (str(gd.packets.dtype), gd.packets.shape))
    check("D0-D4 contract_version", "D0-4", gd.meta["contract_version"])
    check("D0-D5 常量", (16000, 4000, 4.0e9, 2.5e-10, 27, 28, 63),
          (gd.meta["samples_per_packet"], gd.meta["n_period_samples"],
           gd.meta["fs_hz"], gd.meta["ts_s"], gd.meta["tx_idx"],
           gd.meta["ref_idx"], gd.meta["rx_mask_true_count"]))
    check("D0-D6 rx_mask", (False, 63), (bool(gd.rx_mask[27]), int(gd.rx_mask.sum())))
    check("D0-D7 坐标 TX/REF 间距与 TX 高度", (0.070000, 0.545000, 0.545000),
          (float(np.linalg.norm(gd.positions_m[28] - gd.positions_m[27])),
           float(gd.positions_m[27][2]), float(gd.positions_m[28][2])))

    # --max-packets metadata semantics
    gd2 = reader.load_group(ref, max_packets=2)
    check("D0-D8 max-packets: P / 完整交集 / applied",
          (2, [79, 80, 81], 2),
          (int(gd2.packets.shape[0]), gd2.meta["sync_common_all"],
           gd2.meta["max_packets_applied"]))
    dropped = {r: gd2.meta["row_files"][str(r)]["syncs_dropped_not_in_intersection"]
               for r in range(8)}
    check("D0-D9 max-packets 不污染丢包记录", {r: [] for r in range(8)}, dropped)


# --------------------------------------------------------------------------
# C. Synthetic boundary cases through the production loader
# --------------------------------------------------------------------------
def run_synthetic(reader) -> None:
    base = Path(tempfile.mkdtemp(prefix="d0-synth-"))
    try:
        # S1: duplicate sync inside one row file
        rows = {r: [mk_packet(7, fill=r), mk_packet(8, fill=r)] for r in range(8)}
        rows[0] = [mk_packet(7, fill=0), mk_packet(7, fill=1), mk_packet(8, fill=0)]
        root = base / "s1"; write_group(root, "data1", rows)
        gd = reader.load_group(reader.find_group(root, "附件2-测距数据/墙体数据/data1"))
        check("D0-S1 文件内重复 sync 只保留第一个", ([7, 8], 1),
              (gd.sync.tolist(), len(gd.meta["excluded_packets"])))
        check("D0-S1b 重复原因", ["duplicate_sync_in_file"],
              [e["reason"] for e in gd.meta["excluded_packets"]])

        # S2: one row has packets of the wrong shape only
        rows = {r: [mk_packet(10, fill=r), mk_packet(11, fill=r)] for r in range(8)}
        rows[3] = [mk_packet(10, num=8000, fill=3), mk_packet(11, num=8000, fill=3)]
        root = base / "s2"; write_group(root, "data2", rows)
        ref = reader.find_group(root, "附件2-测距数据/墙体数据/data2")
        try:
            reader.load_group(ref)
            raised = None
        except reader.IncompleteGroupError as exc:
            raised = "IncompleteGroupError"
        check("D0-S2 整行无契约形状包 strict 拒绝", "IncompleteGroupError", raised)
        gd = reader.load_group(ref, require_all_rows=False)
        check("D0-S2b rows_without_valid_packet", [3], gd.meta["rows_without_valid_packet"])
        check("D0-S2c 该行 8 通道无效", [False] * 8, gd.channel_valid[24:32].tolist())
        check("D0-S2d 该行数据为 0", 0, int(np.abs(gd.packets[:, 24:32, :]).max()))
        check("D0-S2e 交集仍来自其余 7 行", [10, 11], gd.sync.tolist())

        # S3: truncated samples where num*len/2 is also not a multiple of 8
        rows = {r: [mk_packet(5, fill=r)] for r in range(8)}
        bad = mk_packet(5, num=9, ln=2, fill=0)[:HEADER_BYTES + 10]  # 18 declared, 10 present
        rows[0] = [bad]
        root = base / "s3"; write_group(root, "data3", rows)
        ref = reader.find_group(root, "附件2-测距数据/墙体数据/data3")
        gd = reader.load_group(ref, require_all_rows=False)
        problems = [p["code"] for p in gd.meta["row_files"]["0"]["problems"]]
        check("D0-S3 截断优先记 truncated_samples", True, "truncated_samples" in problems)
        check("D0-S3b 不同时误记 non-multiple-of-8", False,
              "sample_count_not_multiple_of_8" in problems)

        # S4: P=0 from disjoint sync sets with partial rows
        rows = {0: [mk_packet(1), mk_packet(2)], 1: [mk_packet(3), mk_packet(4)]}
        root = base / "s4"; write_group(root, "data4", rows)
        gd = reader.load_group(reader.find_group(root, "附件2-测距数据/墙体数据/data4"),
                               require_all_rows=False)
        check("D0-S4 交集为空时 P=0", (0, []), (int(gd.packets.shape[0]), gd.sync.tolist()))
        check("D0-S4b channel_valid 恒 64 项（前两行有效）",
              ([True] * 16 + [False] * 48), gd.channel_valid.tolist())

        # S5: non-data packet + leading gap + trailing bytes
        junk = b"\x00\x00\x00\x00"
        nondata = mk_packet(0, ptype=7, data=np.zeros(10, dtype=np.int16))  # 20 payload bytes
        data = mk_packet(9, fill=0)
        rows = {0: [junk + nondata + data + b"\x01\x02\x03\x04\x05"]}
        root = base / "s5"; write_group(root, "data5", rows)
        gd = reader.load_group(reader.find_group(root, "附件2-测距数据/墙体数据/data5"),
                               require_all_rows=False)
        rf = gd.meta["row_files"]["0"]
        codes = [p["code"] for p in rf["problems"]]
        check("D0-S5 跳过非 magic 前导字节", 4, rf["skipped_bytes"])
        check("D0-S5b type!=102 记录并跳过", (True, [9]),
              ("non_data_packet" in codes, gd.sync.tolist()))
        check("D0-S5c 尾部残留字节", (5, True), (rf["trailing_bytes"], "trailing_bytes" in codes))

        # S6: total_len mismatch
        rows = {0: [mk_packet(4, total_len=256000)]}
        root = base / "s6"; write_group(root, "data6", rows)
        gd = reader.load_group(reader.find_group(root, "附件2-测距数据/墙体数据/data6"),
                               require_all_rows=False)
        codes = [p["code"] for p in gd.meta["row_files"]["0"]["problems"]]
        check("D0-S6 total_len 不符记录 header_len_mismatch", True,
              "header_len_mismatch" in codes)

        # S7: unexpected dat name is a scan problem, not a group
        root = base / "s7"
        d = write_group(root, "data7", {0: [mk_packet(1)]})
        (d / "weird.dat").write_bytes(mk_packet(2))
        groups, problems = reader.discover_groups(root)
        check("D0-S7 非法文件名不进入组", (1, ["unexpected_dat_name"]),
              (len(groups), [p.as_dict()["code"] for p in problems]))
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--reader", type=Path, default=None)
    args = ap.parse_args(argv)
    here = Path(__file__).resolve()
    repo = here.parents[2]
    a_dir = repo / "竞赛题目" / "A 题：单发多收下的雷达信号处理及成像问题"
    root = args.root or a_dir
    reader_path = args.reader or (repo / "solutions" / "A" / "a_dat_reader.py")
    if not (root / "附件").is_dir():
        print("找不到数据根：%s" % root)
        return 2
    if not reader_path.is_file():
        print("找不到读取器：%s" % reader_path)
        return 2
    print("root=%s\nreader=%s" % (root, reader_path))
    reader = load_reader(reader_path)
    run_corpus(root, reader)
    run_synthetic(reader)
    bad = [r for r in RESULTS if r["status"] == "FAIL"]
    print("\n" + "=" * 78)
    print("SUMMARY: %d checks, %d passed, %d failed, %d skipped"
          % (len(RESULTS), sum(r["status"] == "PASS" for r in RESULTS),
             len(bad), sum(r["status"] == "SKIP" for r in RESULTS)))
    for r in bad:
        print("FAIL: %s expected=%r actual=%r" % (r["name"], r["expected"], r["actual"]))
    print("=" * 78)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
