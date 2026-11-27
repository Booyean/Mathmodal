#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 题原始附件（.dat）清点与协议实测校验。

严格按 附件1-数据读取函数/get_data_iq.m 的二进制协议解析，不假设文件一定规整：
  magic(u32)=963072 -> total_len(u32) -> type(u32)
    若 type != 102 : 跳过 total_len-4 字节后继续找下一个 magic
    若 type == 102 : freq(float32) -> sync(u32) -> num(u32) -> len(u32)
                     -> num*len/2 个 int16（时刻交织，reshape 后 8 x num）
输出：
  recon/manifests/a_dat_manifest.csv   每个 .dat 一行（哈希、包数、包头字段、**全部采样包**的数据统计、异常）
  recon/manifests/a_group_manifest.csv 每个测量组一行（组内 8 行文件是否齐全）
  recon/reports/a_inventory_summary.json
  recon/samples/a_sample_dat_header.json        真实包头原始字节
  recon/samples/a_sample_waveform.csv           小样：某组某行的前 200 个采样点 × 8 通道
  recon/samples/a_period_check.json             周期结构核对（16000 点 vs 题面 12000 点）
用法：
  python recon/scripts/a_inventory.py --root "<A题目录>"
  python recon/scripts/a_inventory.py --self-test   # 边界值/邻界/汇总口径单测（不读原件）
"""

import argparse
import csv
import hashlib
import json
import os
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np

MAGIC = 963072
TYPE_DATA = 102
CHANNELS = 8
INT16_POS_MAX = 32767   # int16 正满量程
INT16_NEG_MIN = -32768  # int16 负满量程（np.abs(int16(-32768)) 会回绕成 -32768）


def find_packets(buf):
    """按 get_data_iq.m 的逻辑逐包解析，返回 (packets, problems)。"""
    n = len(buf)
    pos = 0
    packets = []
    problems = []
    skipped = 0
    while pos + 4 <= n:
        # 找 magic
        magic = struct.unpack_from("<I", buf, pos)[0]
        if magic != MAGIC:
            nxt = buf.find(struct.pack("<I", MAGIC), pos + 1)
            if nxt < 0:
                skipped += n - pos
                pos = n
                break
            skipped += nxt - pos
            pos = nxt
            continue
        if pos + 12 > n:
            problems.append("truncated_header_at_%d" % pos)
            pos = n
            break
        total_len, ptype = struct.unpack_from("<II", buf, pos + 4)
        if ptype != TYPE_DATA:
            problems.append("non_data_packet_type_%d_at_%d" % (ptype, pos))
            # 与 .m 一致：type 已读，跳过 total_len-4
            skip = total_len - 4
            if skip < 0 or pos + 12 + skip > n:
                problems.append("bad_skip_%d_at_%d" % (skip, pos))
                pos = n
                break
            pos += 12 + skip
            continue
        if pos + 28 > n:
            problems.append("truncated_packet_header_at_%d" % pos)
            pos = n
            break
        freq, sync, num, ln = struct.unpack_from("<fIII", buf, pos + 12)
        nbytes = num * ln  # .m 中 num*len/2 个 int16
        start = pos + 28
        end = start + nbytes
        if end > n:
            problems.append("truncated_samples_at_%d_need_%d_have_%d" % (pos, nbytes, n - start))
            pos = n
            break
        packets.append(
            {
                "offset": pos,
                "total_len": total_len,
                "type": ptype,
                "freq": freq,
                "sync": sync,
                "num": num,
                "len": ln,
                "bytes": nbytes,
                "start": start,
                "end": end,
                "hdr_ok": total_len == 20 + nbytes,
            }
        )
        pos = end
    if skipped:
        problems.append("skipped_bytes_%d" % skipped)
    return packets, problems


def stats_from_mat(mat):
    """对一包 int16 数据（channels x samples）做统计。

    关键修复：先升到 int32 再统计，避免 int16 定宽类型的绝对值回绕。
    端点判据用有符号存储端点 +32767 / -32768（不是 |x|>=32767，后者会把 -32767 误计）。
    """
    m = np.asarray(mat)
    if m.dtype != np.int32:
        m = m.astype(np.int32)
    n = int(m.size)
    per_ch_mean = m.mean(axis=1, dtype=np.float64)
    # 满量程判据：有符号存储端点 +32767 或 -32768。
    # 注意不能用 |x| >= 32767：-32767 也满足 |x| >= 32767，但它不是端点，会被错误计入。
    n_endpoint = int(np.count_nonzero((m >= INT16_POS_MAX) | (m <= INT16_NEG_MIN)))
    return {
        "shape": [int(m.shape[0]), int(m.shape[1])],
        "min": int(m.min()),
        "max": int(m.max()),
        "mean": round(float(m.mean(dtype=np.float64)), 3),
        "std": round(float(m.std(dtype=np.float64)), 3),
        "ch_mean_abs": [round(float(v), 1) for v in np.abs(per_ch_mean)],
        "clip_frac": round(float(n_endpoint / n), 6),
        "n_at_pos_max": int(np.count_nonzero(m >= INT16_POS_MAX)),
        "n_at_neg_min": int(np.count_nonzero(m <= INT16_NEG_MIN)),
        "n_zero": int(np.count_nonzero(m == 0)),
        "n_samples": n,
    }


def stats_all_packets(buf, packets):
    """对单个文件的**所有采样包**做幅值统计，并显式记录统计覆盖范围。

    旧版只统计 packets[0]；报告若据此写"全库无削顶"会超出证据范围。
    逐通道均值按各通道自己的样本数计（不等长包按样本加权）。
    """
    n = 0
    total = 0.0
    total_sq = 0.0
    mn = INT16_POS_MAX
    mx = INT16_NEG_MIN
    n_pos = 0
    n_neg = 0
    n_zero = 0
    ch_sum = np.zeros(CHANNELS, dtype=np.float64)
    ch_n = np.zeros(CHANNELS, dtype=np.int64)  # 每通道各自的样本数（不等长包按样本加权）
    for pkt in packets:
        a = np.frombuffer(buf, dtype="<i2", count=pkt["num"] * pkt["len"] // 2, offset=pkt["start"])
        mat = a.reshape(pkt["num"], pkt["len"] // 2).T.astype(np.int32)  # 8 x num
        n += int(mat.size)
        total += float(mat.sum(dtype=np.float64))
        total_sq += float(np.square(mat.astype(np.float64)).sum())
        mn = min(mn, int(mat.min()))
        mx = max(mx, int(mat.max()))
        n_pos += int(np.count_nonzero(mat >= INT16_POS_MAX))
        n_neg += int(np.count_nonzero(mat <= INT16_NEG_MIN))
        n_zero += int(np.count_nonzero(mat == 0))
        ch_sum += mat.sum(axis=1, dtype=np.float64)
        ch_n += int(mat.shape[1])
    if n == 0:
        raise ValueError("no samples to aggregate")
    mean = total / n
    var = max(0.0, total_sq / n - mean * mean)
    # 逐通道均值必须除以该通道自己的样本数；除以 8 通道总样本数 n 会小算 8 倍。
    ch_mean = ch_sum / ch_n
    return {
        "min": mn,
        "max": mx,
        "mean": round(mean, 3),
        "std": round(float(np.sqrt(var)), 3),
        "ch_mean_abs": [round(float(v), 1) for v in np.abs(ch_mean)],
        "clip_frac": round(float((n_pos + n_neg) / n), 6),
        "n_at_pos_max": n_pos,
        "n_at_neg_min": n_neg,
        "n_zero": n_zero,
        "n_samples": n,
        "n_packets": len(packets),
    }


def _synthetic_dat(packet_mats):
    """由 8 x nsamp int16 矩阵列表构造合法 .dat 字节流（仅用于自测）。"""
    chunks = []
    for mat in packet_mats:
        m = np.asarray(mat, dtype="<i2")
        if m.ndim != 2 or m.shape[0] != CHANNELS:
            raise ValueError("expected %d x nsamp matrices" % CHANNELS)
        nsamp = int(m.shape[1])
        data = m.T.tobytes()  # 时间交织：每个时刻依次 8 个通道
        total_len = 20 + len(data)
        chunks.append(struct.pack("<III", MAGIC, total_len, TYPE_DATA))
        chunks.append(struct.pack("<fIII", 4.0e9, 1, nsamp, 16))
        chunks.append(data)
    return b"".join(chunks)


def self_test():
    """边界值单测：正负极值、-32767 相邻边界、单包与多包汇总口径（不依赖原始数据）。"""
    cases = []

    def check(name, mat, expected):
        got = stats_from_mat(mat)
        ok = all(got[k] == v for k, v in expected.items())
        cases.append({"case": name, "ok": ok, "got": {k: got[k] for k in expected}, "expected": expected})
        if not ok:
            raise AssertionError("%s failed: got=%s expected=%s" % (name, got, expected))

    def check_aggregate(name, mats, expected):
        buf = _synthetic_dat(mats)
        packets, probs = find_packets(buf)
        if probs:
            raise AssertionError("%s: unexpected parse problems %s" % (name, probs))
        got = stats_all_packets(buf, packets)
        ok = all(got[k] == v for k, v in expected.items())
        cases.append({"case": name, "ok": ok, "got": {k: got[k] for k in expected}, "expected": expected})
        if not ok:
            raise AssertionError("%s failed: got=%s expected=%s" % (name, got, expected))

    check(
        "all_int16_neg_full_scale",
        np.full((8, 16), INT16_NEG_MIN, dtype="<i2"),
        {"min": -32768, "max": -32768, "clip_frac": 1.0, "n_at_neg_min": 128, "n_at_pos_max": 0, "n_zero": 0},
    )
    check(
        "all_int16_pos_full_scale",
        np.full((8, 16), INT16_POS_MAX, dtype="<i2"),
        {"min": 32767, "max": 32767, "clip_frac": 1.0, "n_at_pos_max": 128, "n_at_neg_min": 0, "n_zero": 0},
    )
    check(
        "all_zero",
        np.zeros((8, 16), dtype="<i2"),
        {"min": 0, "max": 0, "clip_frac": 0.0, "n_zero": 128, "n_at_pos_max": 0, "n_at_neg_min": 0},
    )
    check(
        "mixed_extremes_and_zero",
        np.array([[-32768, 32767, 0, 5], [1, -1, 32767, -32768]], dtype="<i2"),
        {
            "min": -32768,
            "max": 32767,
            "clip_frac": 0.5,
            "n_at_pos_max": 2,
            "n_at_neg_min": 2,
            "n_zero": 1,
            "n_samples": 8,
        },
    )
    # PR review 用例：每个通道都是 [-32768, 32767, 0, -32767, 12]
    # 按有符号端点口径，只有 -32768 与 +32767 是端点 → 2/5 = 0.4，-32767 不计入。
    review_mat = np.tile(np.array([-32768, 32767, 0, -32767, 12], dtype="<i2"), (CHANNELS, 1))
    check(
        "signed_endpoints_review_matrix",
        review_mat,
        {
            "clip_frac": 0.4,
            "n_at_pos_max": 8,
            "n_at_neg_min": 8,
            "n_zero": 8,
            "n_samples": 40,
            # 每通道均值 = (-32768+32767+0-32767+12)/5 = -6551.2
            "ch_mean_abs": [6551.2] * CHANNELS,
        },
    )
    check(
        "minus_32767_is_not_endpoint",
        np.full((8, 16), -32767, dtype="<i2"),
        {"min": -32767, "max": -32767, "clip_frac": 0.0, "n_at_neg_min": 0, "n_at_pos_max": 0},
    )
    check(
        "plus_32766_is_not_endpoint",
        np.full((8, 16), 32766, dtype="<i2"),
        {"min": 32766, "max": 32766, "clip_frac": 0.0, "n_at_neg_min": 0, "n_at_pos_max": 0},
    )
    # 单包：汇总路径必须与单包逐通道路径一致（含逐通道均值分母）
    check_aggregate(
        "aggregate_single_packet_matches_single_packet_stats",
        [review_mat],
        {
            "min": -32768,
            "max": 32767,
            "mean": -6551.2,
            "clip_frac": 0.4,
            "n_at_pos_max": 8,
            "n_at_neg_min": 8,
            "n_zero": 8,
            "n_samples": 40,
            "n_packets": 1,
            "ch_mean_abs": [6551.2] * CHANNELS,
        },
    )
    # 不等长包：包1 每通道 2 个 2，包2 每通道 6 个 6 → 加权均值 = (2*2+6*6)/8 = 5.0
    check_aggregate(
        "aggregate_unequal_packets_sample_weighted",
        [np.full((8, 2), 2, dtype="<i2"), np.full((8, 6), 6, dtype="<i2")],
        {
            "min": 2,
            "max": 6,
            "mean": 5.0,
            "n_samples": 64,
            "n_packets": 2,
            "ch_mean_abs": [5.0] * CHANNELS,
        },
    )
    # 汇总路径的端点口径：包2 全为 -32767，不得被计入削顶
    check_aggregate(
        "aggregate_endpoint_criterion_excludes_minus_32767",
        [review_mat, np.full((8, 3), -32767, dtype="<i2")],
        {
            "clip_frac": 0.25,
            "n_at_pos_max": 8,
            "n_at_neg_min": 8,
            "n_samples": 64,
            "n_packets": 2,
        },
    )
    print(json.dumps({"self_test": cases, "all_ok": all(c["ok"] for c in cases)}, ensure_ascii=False, indent=2))
    return all(c["ok"] for c in cases)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="A 题目录（含 附件/）")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--self-test", action="store_true", help="只跑 -32768/+32767/0 边界值单测后退出")
    args = ap.parse_args()
    if args.self_test:
        return 0 if self_test() else 1
    if not args.root:
        ap.error("--root is required unless --self-test")

    root = os.path.abspath(args.root)
    out = os.path.abspath(args.out)
    man_dir = os.path.join(out, "manifests")
    rep_dir = os.path.join(out, "reports")
    smp_dir = os.path.join(out, "samples")
    for d in (man_dir, rep_dir, smp_dir):
        os.makedirs(d, exist_ok=True)

    dat_files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".dat"):
                dat_files.append(os.path.join(dirpath, fn))
    dat_files.sort()

    rows = []
    problems_all = defaultdict(list)
    size_hist = Counter()
    n_pkt_hist = Counter()
    dup = defaultdict(list)
    sample_header = None
    sample_wave = None

    for fp in dat_files:
        rel = os.path.relpath(fp, root).replace("\\", "/")
        size = os.path.getsize(fp)
        size_hist[size] += 1
        row = {
            "rel_path": rel,
            "size_bytes": size,
            "sha256": "",
            "n_packets": 0,
            "num": "",
            "len": "",
            "sync_ids": "",
            "bytes_consumed": 0,
            "header_ok": "",
            "problems": "",
            "data_min": "",
            "data_max": "",
            "data_mean": "",
            "data_std": "",
            "clip_frac": "",
            "n_packets_stat": 0,
            "n_samples_stat": 0,
            "n_at_int16_pos_max": 0,
            "n_at_int16_neg_min": 0,
            "n_zero": 0,
        }
        if size == 0:
            rows.append(row)
            problems_all["empty_file"].append(rel)
            continue
        with open(fp, "rb") as fh:
            buf = fh.read()
        row["sha256"] = sha256_bytes(buf)
        dup[row["sha256"]].append(rel)
        packets, probs = find_packets(buf)
        row["n_packets"] = len(packets)
        n_pkt_hist[len(packets)] += 1
        if packets:
            row["num"] = packets[0]["num"]
            row["len"] = packets[0]["len"]
            row["sync_ids"] = ",".join(str(p["sync"]) for p in packets)
            row["header_ok"] = all(p["hdr_ok"] for p in packets)
            row["bytes_consumed"] = packets[-1]["end"]
            # 统计覆盖：本文件所有采样包，而不是仅首包
            st = stats_all_packets(buf, packets)
            row["data_min"] = st["min"]
            row["data_max"] = st["max"]
            row["data_mean"] = st["mean"]
            row["data_std"] = st["std"]
            row["clip_frac"] = st["clip_frac"]
            row["n_packets_stat"] = st["n_packets"]
            row["n_samples_stat"] = st["n_samples"]
            row["n_at_int16_pos_max"] = st["n_at_pos_max"]
            row["n_at_int16_neg_min"] = st["n_at_neg_min"]
            row["n_zero"] = st["n_zero"]
            if sample_header is None:
                sample_header = {
                    "file": rel,
                    "size_bytes": size,
                    "raw_first_64_bytes_hex": buf[:64].hex(),
                    "packets": [
                        {k: (round(float(v), 6) if k == "freq" else v) for k, v in p.items() if k != "start" and k != "end"}
                        for p in packets
                    ],
                }
                # 小样：第 0 包前 200 个时刻 × 8 通道
                a = np.frombuffer(buf, dtype="<i2", count=packets[0]["num"] * packets[0]["len"] // 2, offset=packets[0]["start"])
                mat = a.reshape(packets[0]["num"], packets[0]["len"] // 2).T
                sample_wave = {"file": rel, "rows": mat[:CHANNELS, :200].tolist()}
        if probs:
            row["problems"] = ";".join(probs)
            problems_all[rel].extend(probs)
        if packets and packets[-1]["end"] != size:
            problems_all[rel].append("trailing_bytes_%d" % (size - packets[-1]["end"]))
            row["problems"] = (row["problems"] + ";" if row["problems"] else "") + "trailing_bytes_%d" % (size - packets[-1]["end"])
        rows.append(row)

    cols = list(rows[0].keys())
    with open(os.path.join(man_dir, "a_dat_manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # 组级清点：一个"测量组" = 同一目录下同一采集时间戳(文件名去掉 _行号)的 8 个文件。
    # 附件3 把 33/27 组都放在同一目录里，必须按时间戳前缀分组，不能按目录分组。
    groups = defaultdict(dict)
    for r in rows:
        d = os.path.dirname(r["rel_path"])
        base = os.path.basename(r["rel_path"])
        stem, _ext = os.path.splitext(base)
        rowidx = stem.rsplit("_", 1)[-1] if "_" in stem else ""
        prefix = stem.rsplit("_", 1)[0] if "_" in stem else stem
        key = d + "|" + prefix
        groups[key].setdefault("files", []).append(r)
        groups[key].setdefault("rows", {})[rowidx] = r["size_bytes"]
        groups[key]["dir"] = d
        groups[key]["prefix"] = prefix

    g_rows = []
    for key in sorted(groups):
        g = groups[key]
        idxs = sorted(g["rows"].keys(), key=lambda x: int(x) if x.isdigit() else 999)
        counts = sorted(r["n_packets"] for r in g["files"])
        n_pkts = sorted(set(counts))
        g_rows.append(
            {
                "group": g["dir"],
                "timestamp_prefix": g["prefix"],
                "n_files": len(g["files"]),
                "row_indices": ",".join(idxs),
                "complete_0_to_7": "YES" if idxs == [str(i) for i in range(8)] else "NO",
                "packets_per_file": ",".join(str(x) for x in n_pkts),
                "packets_consistent": "YES" if len(n_pkts) == 1 else "NO",
                "zero_byte_files": sum(1 for r in g["files"] if r["size_bytes"] == 0),
                "total_mb": round(sum(r["size_bytes"] for r in g["files"]) / 1048576.0, 3),
            }
        )
    with open(os.path.join(man_dir, "a_group_manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(g_rows[0].keys()))
        w.writeheader()
        w.writerows(g_rows)

    # 按题面声明核对"组数"：空场 10、墙体测距 20、金属板 20、墙体成像 33、金属目标 27
    by_ds = defaultdict(lambda: {"groups": 0, "files": 0, "incomplete": 0, "inconsistent_packets": 0})
    for g in g_rows:
        ds = g["group"].split("/")[1] if g["group"].count("/") > 1 else g["group"]
        # 形如 附件/附件2-测距数据/空场数据/data1  -> 取前 3 段
        parts = g["group"].split("/")
        ds = "/".join(parts[:3]) if len(parts) >= 3 else g["group"]
        b = by_ds[ds]
        b["groups"] += 1
        b["files"] += g["n_files"]
        if g["complete_0_to_7"] != "YES":
            b["incomplete"] += 1
        if g["packets_consistent"] != "YES":
            b["inconsistent_packets"] += 1
    ds_rows = [{"dataset": k, **v} for k, v in sorted(by_ds.items())]
    with open(os.path.join(man_dir, "a_dataset_manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["dataset", "groups", "files", "incomplete", "inconsistent_packets"])
        w.writeheader()
        w.writerows(ds_rows)

    # 周期结构核对：16000 点 = 4 * 4000，题面文字说附件是 12000 点（3 个整周期）
    period = {
        "fs_hz": 4e9,
        "Np": 4000,
        "samples_per_packet": 16000,
        "record_period_multiple": 16000 / 4000,
        "pdf_text_says": "附件为 .txt，每列 12000 点 = 3 个整周期；每个 .dat 包 16000 点",
        "actual_dat_points_per_channel_per_packet": 16000,
        "note": (
            "实测每包 8 通道 x 16000 点，长度是 Np=4000 的 4 倍；但 16000/4000=4 只说明记录长度相当于 4 个周期，"
            "采集起点是否在周期边界、4 段是否与真实发射周期对齐均未验证。"
            "需建模方确认取 12000/16000 点，并先对齐周期边界再截取 3 个整周期。"
        ),
        "packet_counts_observed": {str(k): v for k, v in sorted(n_pkt_hist.items())},
        "size_bytes_histogram": {str(k): v for k, v in sorted(size_hist.items())},
    }
    with open(os.path.join(smp_dir, "a_period_check.json"), "w", encoding="utf-8") as fh:
        json.dump(period, fh, ensure_ascii=False, indent=2)
    if sample_header:
        with open(os.path.join(smp_dir, "a_sample_dat_header.json"), "w", encoding="utf-8") as fh:
            json.dump(sample_header, fh, ensure_ascii=False, indent=2)
    if sample_wave:
        with open(os.path.join(smp_dir, "a_sample_waveform.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", sample_wave["file"]])
            w.writerow(["sample_idx"] + ["ch%d" % i for i in range(CHANNELS)])
            for t in range(len(sample_wave["rows"][0])):
                w.writerow([t] + [sample_wave["rows"][c][t] for c in range(CHANNELS)])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": root,
        "n_dat_files": len(dat_files),
        "total_bytes": sum(r["size_bytes"] for r in rows),
        "n_zero_byte": sum(1 for r in rows if r["size_bytes"] == 0),
        "n_groups": len(g_rows),
        "n_groups_incomplete": sum(1 for g in g_rows if g["complete_0_to_7"] != "YES"),
        "n_groups_inconsistent_packets": sum(1 for g in g_rows if g["packets_consistent"] != "YES"),
        "groups_by_dataset": ds_rows,
        "n_packets_histogram": {str(k): v for k, v in sorted(n_pkt_hist.items())},
        "size_histogram": {str(k): v for k, v in sorted(size_hist.items())},
        "header_ok_ratio": "%.4f" % (sum(1 for r in rows if r["header_ok"] is True) / max(1, sum(1 for r in rows if r["n_packets"]))),
        "duplicate_sha256_groups_gt1": {k: v for k, v in dup.items() if len(v) > 1},
        "problems": {k: v for k, v in problems_all.items()},
        "num_values": sorted({r["num"] for r in rows if r["num"] not in ("", None)}),
        "len_values": sorted({r["len"] for r in rows if r["len"] not in ("", None)}),
        "data_range_global": [
            min(r["data_min"] for r in rows if r["data_min"] != ""),
            max(r["data_max"] for r in rows if r["data_max"] != ""),
        ],
        "clip_frac_max": max(r["clip_frac"] for r in rows if r["clip_frac"] != ""),
        "stats_scope": "每个非空 .dat 的全部采样包（不是仅首包）；n_samples_stat 为全部 int16 采样点数",
        "n_samples_stat": sum(r["n_samples_stat"] for r in rows),
        "n_packets_stat": sum(r["n_packets_stat"] for r in rows),
        "clip_frac_global": round(
            float(
                sum(r["n_at_int16_pos_max"] + r["n_at_int16_neg_min"] for r in rows)
                / max(1, sum(r["n_samples_stat"] for r in rows))
            ),
            6,
        ),
        "int16_extreme_counts": {
            "at_pos_32767": sum(r["n_at_int16_pos_max"] for r in rows),
            "at_neg_-32768": sum(r["n_at_int16_neg_min"] for r in rows),
            "zero": sum(r["n_zero"] for r in rows),
        },
        "files_with_int16_extreme": [
            {
                "rel_path": r["rel_path"],
                "n_at_pos_32767": r["n_at_int16_pos_max"],
                "n_at_neg_-32768": r["n_at_int16_neg_min"],
                "clip_frac": r["clip_frac"],
                "n_samples_stat": r["n_samples_stat"],
            }
            for r in rows
            if r["n_at_int16_pos_max"] or r["n_at_int16_neg_min"]
        ],
        "adc_interpretation": (
            "统计覆盖每个非空 .dat 的全部采样包；实测 +32767 共 %d 个、-32768 共 %d 个。"
            "不能据此宣称'无削顶'：ADC 位深、前端增益/衰减与采集链路均未在附件中定义，不能排除真实 ADC 饱和或前端压缩。"
            "若极值为连续多点，倾向饱和；若为孤立单点（见 files_with_int16_extreme），倾向采集异常/坏点，应标记后交建模决定是否剔除。"
            % (
                sum(r["n_at_int16_pos_max"] for r in rows),
                sum(r["n_at_int16_neg_min"] for r in rows),
            )
        ),
    }
    with open(os.path.join(rep_dir, "a_inventory_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    sys.exit(main())
