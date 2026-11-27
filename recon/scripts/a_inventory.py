#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 题原始附件（.dat）清点与协议实测校验。

严格按 附件1-数据读取函数/get_data_iq.m 的二进制协议解析，不假设文件一定规整：
  magic(u32)=963072 -> total_len(u32) -> type(u32)
    若 type != 102 : 跳过 total_len-4 字节后继续找下一个 magic
    若 type == 102 : freq(float32) -> sync(u32) -> num(u32) -> len(u32)
                     -> num*len/2 个 int16（时刻交织，reshape 后 8 x num）
输出：
  recon/manifests/a_dat_manifest.csv   每个 .dat 一行（哈希、包数、包头字段、数据统计、异常）
  recon/manifests/a_group_manifest.csv 每个测量组一行（组内 8 行文件是否齐全）
  recon/reports/a_inventory_summary.json
  recon/samples/a_sample_dat_header.json        真实包头原始字节
  recon/samples/a_sample_waveform.csv           小样：某组某行的前 200 个采样点 × 8 通道
  recon/samples/a_period_check.json             周期结构核对（16000 点 vs 题面 12000 点）
用法：
  python recon/scripts/a_inventory.py --root "<A题目录>"
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


def stats_from(buf, pkt):
    a = np.frombuffer(buf, dtype="<i2", count=pkt["num"] * pkt["len"] // 2, offset=pkt["start"])
    mat = a.reshape(pkt["num"], pkt["len"] // 2).T  # 8 x num
    per_ch = mat.astype(np.float64)
    return {
        "shape": [int(mat.shape[0]), int(mat.shape[1])],
        "min": int(mat.min()),
        "max": int(mat.max()),
        "mean": round(float(per_ch.mean()), 3),
        "std": round(float(per_ch.std()), 3),
        "ch_mean_abs": [round(float(v), 1) for v in np.abs(per_ch.mean(axis=1))],
        "clip_frac": round(float(np.mean(np.abs(mat) >= 32767)), 6),
    }


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="A 题目录（含 附件/）")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    args = ap.parse_args()

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
            st = stats_from(buf, packets[0])
            row["data_min"] = st["min"]
            row["data_max"] = st["max"]
            row["data_mean"] = st["mean"]
            row["data_std"] = st["std"]
            row["clip_frac"] = st["clip_frac"]
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
        "periods_in_packet": 16000 / 4000,
        "pdf_text_says": "附件为 .txt，每列 12000 点 = 3 个整周期；每个 .dat 包 16000 点",
        "actual_dat_points_per_channel_per_packet": 16000,
        "note": "实测每包 8 通道 x 16000 点(4 个周期)，与题面文字 12000 点(3 个周期)不一致；需建模方确认取哪 12000/16000 点及周期对齐方式。",
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
    }
    with open(os.path.join(rep_dir, "a_inventory_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    sys.exit(main())
