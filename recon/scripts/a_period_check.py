#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 题数据物理一致性核对：发射周期 4000 点、每包 16000 点、包间重复性、发射通道是否为空。

回答建模方必须知道的四件事：
  1) 每包 16000 点是否等于 Np=4000 的整数倍（16000/4000=4），以及**采集起点/周期边界是否已对齐**
     （本脚本只核对倍数与段间相关，不做对齐判定）；
  2) 题面说"附件为 12000 点 = 3 个整周期"，实测每包 16000 点，取哪 12000 点需建模定口径；
  3) 同一文件多个采样包是"重复采集"还是"不同采集"（决定能否平均）；
  4) 第 4 行第 8 列是发射天线，其 _3 文件的第 4 列是否确实是空/噪声（决定跳过哪一路）。

输出：
  recon/reports/a_period_check.json
  recon/manifests/a_period_corr.csv
用法：
  python recon/scripts/a_period_check.py --root "<A题目录>"
"""

import argparse
import csv
import json
import os
import struct
import sys
from collections import defaultdict

import numpy as np

MAGIC = 963072
NP = 4000  # 每周期采样点数（题面 Np=4000）
TX_CHANNEL = 3  # 文件 _3 的第 4 列（0 基）为第 4 行第 8 列的发射天线


def read_packets(path):
    with open(path, "rb") as fh:
        buf = fh.read()
    pos, out = 0, []
    while pos + 4 <= len(buf):
        if struct.unpack_from("<I", buf, pos)[0] != MAGIC:
            nxt = buf.find(struct.pack("<I", MAGIC), pos + 1)
            if nxt < 0:
                break
            pos = nxt
            continue
        total_len, ptype = struct.unpack_from("<II", buf, pos + 4)
        if ptype != 102:
            pos += 12 + total_len - 4
            continue
        if pos + 28 > len(buf):
            break
        freq, sync, num, ln = struct.unpack_from("<fIII", buf, pos + 12)
        nb = num * ln
        if pos + 28 + nb > len(buf):
            break
        a = np.frombuffer(buf, dtype="<i2", count=num * ln // 2, offset=pos + 28)
        mat = a.reshape(num, ln // 2).T.astype(np.float64)  # 8 x num
        out.append((sync, mat))
        pos += 28 + nb
    return out


def ncorr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / d) if d > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "reports"), exist_ok=True)
    os.makedirs(os.path.join(out, "manifests"), exist_ok=True)

    # 每个数据集目录挑 2 个"行号 _3"的文件（阵列第 4 行，含发射天线）
    picks = defaultdict(list)
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".dat") and fn.rsplit("_", 1)[-1].split(".")[0] == "3":
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, root).replace("\\", "/")
                top = "/".join(rel.split("/")[1:3])
                if len(picks[top]) < 2 and os.path.getsize(p) > 0:
                    picks[top].append(p)

    rows = []
    for top, paths in sorted(picks.items()):
        for p in paths:
            rel = os.path.relpath(p, root).replace("\\", "/")
            pk = read_packets(p)
            if not pk:
                continue
            sync0, mat0 = pk[0]
            seg = {c: [mat0[c][k * NP:(k + 1) * NP] for k in range(mat0.shape[1] // NP)] for c in range(8)}
            seg_corr = []
            for c in range(8):
                seg_corr.append([round(ncorr(seg[c][0], seg[c][k]), 5) for k in (1, 2, 3)])
            rms = np.sqrt((mat0 ** 2).mean(axis=1))
            ref = int(np.argmax(rms))
            pkt_corr = [round(ncorr(mat0[ref], pk[k][1][ref]), 5) for k in range(1, len(pk))]
            rows.append(
                {
                    "file": rel,
                    "n_packets": len(pk),
                    "sync_ids": ",".join(str(s) for s, _ in pk),
                    "samples_per_channel": mat0.shape[1],
                    # 记录长度 / Np；只表示倍数，不表示"已对齐的完整周期"
                    "record_period_multiple": round(float(mat0.shape[1] / NP), 3),
                    "period_boundary_alignment": "UNVERIFIED",
                    "rms_ch0..7": ",".join(str(int(round(v))) for v in rms),
                    "tx_ch3_rms_ratio": round(float(rms[TX_CHANNEL] / max(1e-9, rms.max())), 5),
                    "seg_corr_min_ch0..7": ",".join("%.5f" % min(v) for v in seg_corr),
                    "packet_corr_refch": ",".join("%.5f" % c for c in pkt_corr),
                    "ref_channel": ref,
                }
            )

    with open(os.path.join(out, "manifests", "a_period_corr.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "Np": NP,
        "record_period_multiple": 16000 / NP,
        "alignment": {
            "record_len_is_integer_multiple_of_Np": True,
            "acquisition_start_and_period_boundary": "UNVERIFIED",
            "note": (
                "16000/4000=4 只说明记录长度是 Np 的 4 倍，不代表 4 个周期已与真实发射边界对齐。"
                "段间相关高只说明波形高度自相似；任意相位起点的周期信号也会给出高相关。"
                "因此不能宣称'4 个完整且已对齐的周期'，也不能把任取连续 3 段当作题面要求的 3 个整周期；"
                "须先用先验/对齐方法确定周期边界，再截取 3 个完整周期。"
            ),
        },
        "definitions": {
            "seg_corr_min_ch0..7": (
                "每通道把 16000 点按偏移 0 等分成 4 段各 4000 点，第 1 段与后 3 段归一化相关系数的最小值；"
                "接近 1 表示波形以 4000 点高度自相似，不表示采集起点位于周期边界"
            ),
            "tx_ch3_rms_ratio": "文件 _3 第 4 列(发射天线记录)的 RMS 与同文件最强通道 RMS 之比；很小说明该路无有效接收信号",
            "packet_corr_refch": "同一文件内第 k 个采样包与第 1 个包在最强通道上的相关系数",
        },
        "samples": rows,
    }
    with open(os.path.join(out, "reports", "a_period_check.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
