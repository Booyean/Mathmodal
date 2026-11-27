#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""D1 折叠/一致性门控：独立预登记探针（D1-PREREG-1）。

为什么有这个脚本
----------------
`data/a-q1-fold-gate`（D1）要交付 16000 → 4×4000 折迭、包内 4 段一致性门控、
包间参考通道相位一致性诊断与拒绝日志。验证方如果等实现出现后再定义"预期"，
就成了事后拟合。所以本脚本在实现之前，用**解析可手算的合成例**校验一致性度量
本身，再用**自写 .dat 解析器**（依 `get_data_iq.m`，不导入 `solutions/` 下任何
读取器或预处理代码）给出空场 `data1` 的真实统计，作为 D1 日志必须能复现的独立
事实。

度量定义（预登记口径，不是从 D1 实现反推）
----------------------------------------
- 段内相关 ``rho_{p,q,i}``：同一包 ``p``、通道 ``i`` 的第 ``q`` 段（q=1..3）与
  第 0 段的 Pearson 相关系数（先去均值，等价于去直流）。取值 ``[-1,1]``。
- 相位漂移 ``dphi_{p,q,i}``：第 ``q`` 段与第 0 段在固定数字频点
  ``k=1000``（``f = k*fs/Np = 1.0 GHz``）的 DFT 系数相位差，卷绕到 ``(-180,180]``
  度。整样本时移 ``d`` 对应 ``dphi = -360*k*d/Np = -90*d`` 度。
  换算到时延：``dt_ns = -dphi_deg/360 * (Np/k) * Ts = dphi_deg * -0.002777... ns``。
- 折迭相干增益 ``coh = |sum_q c_q| / sum_q |c_q|``，``c_q`` 为同频点复系数；
  4 段完全相干时为 1，完全随机时约 ``1/2``（4 个随机相位矢量和的期望模 / 4）。
- 包间：同一通道第 ``p`` 包与第 0 包第 0 段的 Pearson 相关与同频点相位差。

脚本只依赖标准库：本机 Python 3.13 无 numpy，且这正好避免与生产实现共享依赖。

用法::

    python checks/A/d1_prereg_probe.py
    python checks/A/d1_prereg_probe.py --json checks/A/d1_prereg_expected.json
    python checks/A/d1_prereg_probe.py --group "竞赛题目/A 题：.../空场数据/data1"
"""

from __future__ import annotations

import argparse
import array
import json
import math
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

MAGIC = 963072
TYPE_DATA = 102
HEADER_BYTES = 28
SAMPLES_PER_PACKET = 16000
N_PERIOD = 4000
N_CH = 64
N_ROWS = 8
FS_HZ = 4.0e9
TS_S = 2.5e-10
TX_IDX = 27
REF_IDX = 28
DEFAULT_PHASE_BIN = 1000  # 1.0 GHz at fs=4 GHz, Np=4000

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GROUP = ("竞赛题目/A 题：单发多收下的雷达信号处理及成像问题/附件/"
                 "附件2-测距数据/空场数据/data1")

RESULTS: list[dict] = []


# ---------------------------------------------------------------------------
# 1. 独立 .dat 解析器（依据 get_data_iq.m 的字节协议，独立于 D0 读取器）
# ---------------------------------------------------------------------------
def u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def parse_dat(buf: bytes) -> tuple[list[dict], list[str]]:
    """返回 (数据包列表, 问题码列表)；不做任何配对或插补。"""
    n = len(buf)
    pos = 0
    packets: list[dict] = []
    problems: list[str] = []
    seen: set[int] = set()
    while True:
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
        sync = u32(buf, pos + 16)
        num = u32(buf, pos + 20)
        ln = u32(buf, pos + 24)
        nbytes = num * ln
        off = pos + HEADER_BYTES
        if nbytes <= 0:
            problems.append("zero_length_packet")
            pos = off
            continue
        if off + nbytes > n:
            problems.append("truncated_samples")
            break
        if (nbytes // 2) % 8 != 0:
            problems.append("sample_count_not_multiple_of_8")
            pos = off + nbytes
            continue
        if sync in seen:
            problems.append("duplicate_sync")
            pos = off + nbytes
            continue
        seen.add(sync)
        if total_len != 20 + nbytes:
            problems.append("header_len_mismatch")
        packets.append({"sync": sync, "num": num, "len": ln, "off": off,
                        "nbytes": nbytes, "n_samples": nbytes // 16})
        pos = off + nbytes
    return packets, problems


def read_row_file(path: Path) -> tuple[dict[int, array.array], dict]:
    buf = path.read_bytes()
    packets, problems = parse_dat(buf)
    per_sync: dict[int, array.array] = {}
    shapes = set()
    for p in packets:
        if p["num"] != SAMPLES_PER_PACKET or p["len"] != 16:
            shapes.add((p["num"], p["len"]))
            continue
        arr = array.array("h")
        arr.frombytes(buf[p["off"]:p["off"] + p["nbytes"]])
        if sys.byteorder != "little":
            arr.byteswap()
        per_sync.setdefault(p["sync"], arr)
    return per_sync, {"file": path.name, "size": len(buf), "n_packets": len(packets),
                      "syncs": [p["sync"] for p in packets], "problems": problems,
                      "rejected_shapes": sorted(shapes)}


def load_group(dirpath: Path) -> tuple[dict[int, dict], list[int], list[dict]]:
    rows: dict[int, dict] = {}
    meta: list[dict] = []
    for f in sorted(dirpath.glob("*.dat")):
        m = re.match(r"^(.*)_([0-7])\.dat$", f.name)
        if not m:
            continue
        r = int(m.group(2))
        if r in rows:
            meta.append({"row": r, "file": f.name, "error": "duplicate_row_file"})
            continue
        per_sync, info = read_row_file(f)
        rows[r] = per_sync
        meta.append({"row": r, "file": f.name, "size": info["size"],
                     "n_packets": info["n_packets"], "syncs": info["syncs"],
                     "problems": info["problems"],
                     "rejected_shapes": info["rejected_shapes"]})
    if len(rows) != N_ROWS:
        raise SystemExit("组内行文件不全：%r" % sorted(rows))
    common = sorted(set.intersection(*[set(v) for v in rows.values()]))
    return rows, common, meta


# ---------------------------------------------------------------------------
# 2. 一致性度量（合成例与真实数据用同一套函数）
# ---------------------------------------------------------------------------
def seg_values(arr: array.array, col: int, q: int) -> list[float]:
    """第 q 段、文件内第 col 列（0..7）的 4000 点。

    通道索引 i = 8*row + col；包内存储为 reshape(16000, 8)，即
    arr[8*m + col] 是第 m 个采样点上的第 col 路。
    """
    base = q * N_PERIOD
    return [float(arr[8 * (base + m) + col]) for m in range(N_PERIOD)]


def bin_tables(bin_index: int) -> tuple[list[float], list[float]]:
    w = -2.0 * math.pi * bin_index / N_PERIOD
    return ([math.cos(w * m) for m in range(N_PERIOD)],
            [math.sin(w * m) for m in range(N_PERIOD)])


def seg_stats(v: list[float], cos_t: list[float], sin_t: list[float]) -> dict:
    s = s2 = re = im = 0.0
    for x, c, sn in zip(v, cos_t, sin_t):
        s += x
        s2 += x * x
        re += x * c
        im += x * sn
    return {"sum": s, "sumsq": s2, "re": re, "im": im}


def pearson(a: list[float], b: list[float], sa: dict, sb: dict) -> float:
    n = len(a)
    va = sa["sumsq"] - sa["sum"] * sa["sum"] / n
    vb = sb["sumsq"] - sb["sum"] * sb["sum"] / n
    if va <= 0.0 or vb <= 0.0:
        return float("nan")
    ma = sa["sum"] / n
    mb = sb["sum"] / n
    d = 0.0
    for x, y in zip(a, b):
        d += (x - ma) * (y - mb)
    return d / math.sqrt(va * vb)


def wrap_deg(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def phase_deg(st: dict) -> float:
    return math.degrees(math.atan2(st["im"], st["re"]))


def phase_to_ns(dphi_deg: float, bin_index: int) -> float:
    """整样本/小数样本时移换算：dphi = -360*k*d/Np，d 以样本计。"""
    d_samples = -dphi_deg / 360.0 * N_PERIOD / bin_index
    return d_samples * TS_S * 1e9


def coherence(stats: list[dict]) -> float:
    num_re = sum(s["re"] for s in stats)
    num_im = sum(s["im"] for s in stats)
    den = sum(math.hypot(s["re"], s["im"]) for s in stats)
    return math.hypot(num_re, num_im) / den if den > 0 else float("nan")


def rms(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v) / len(v))


# ---------------------------------------------------------------------------
# 3. 合成例：解析预期 vs 同一套度量
# ---------------------------------------------------------------------------
def tone(n: int, k: int, amp: float, phase0: float = 0.0) -> list[float]:
    w = 2.0 * math.pi * k / n
    return [amp * math.cos(w * m + phase0) for m in range(n)]


def circular_shift(v: list[float], d: int) -> list[float]:
    n = len(v)
    return [v[(m - d) % n] for m in range(n)]


def fold_mean(segs: list[list[float]]) -> list[float]:
    n = len(segs[0])
    return [sum(s[m] for s in segs) / len(segs) for m in range(n)]


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def json_safe(obj):
    """把 NaN/Inf 换成 None，保证输出是严格 JSON（NaN 不是合法 JSON 记号）。"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def record(cid: str, name: str, expected: dict, measured: dict, tol: float = 1e-9) -> None:
    checks = {}
    ok_all = True
    for key, exp in expected.items():
        act = measured.get(key)
        if isinstance(exp, float) and math.isnan(exp):
            exp = None
        if isinstance(act, float) and math.isnan(act):
            act = None
        if isinstance(exp, bool):
            ok = bool(act) == exp
        elif exp is None:
            ok = act is None
        else:
            ok = act is not None and close(float(exp), float(act), tol)
        checks[key] = {"expected": exp, "actual": act, "pass": ok}
        ok_all = ok_all and ok
    RESULTS.append({"id": cid, "name": name, "status": "PASS" if ok_all else "FAIL",
                    "checks": checks})
    print("[%s] %-10s %s" % ("PASS" if ok_all else "FAIL", cid, name))
    for key, c in checks.items():
        if not c["pass"] or key in ("rho", "dphi_deg", "coh"):
            print("        %-18s expected=%r actual=%r" % (key, c["expected"], c["actual"]))


def run_synthetic() -> None:
    print("\n== 合成例（解析预期） ==")

    # S1: 4 段完全相同（理想周期），k=1000 单音
    k = 1000
    cos_t, sin_t = bin_tables(k)
    base = tone(N_PERIOD, k, 1000.0, phase0=0.3)
    segs = [list(base) for _ in range(4)]
    stats = [seg_stats(s, cos_t, sin_t) for s in segs]
    fold = fold_mean(segs)
    measured = {
        "rho": pearson(segs[0], segs[1], stats[0], stats[1]),
        "dphi_deg": wrap_deg(phase_deg(stats[1]) - phase_deg(stats[0])),
        "coh": coherence(stats),
        "fold_maxdiff": max(abs(a - b) for a, b in zip(fold, base)),
    }
    record("S1", "理想周期：4 段完全相同 → 折叠=原段、rho=1、dphi=0、coh=1",
           {"rho": 1.0, "dphi_deg": 0.0, "coh": 1.0, "fold_maxdiff": 0.0}, measured)

    # S2: 只把第 1 段整体移 2 个样本，k=100 → 18°
    k2 = 100
    cos2, sin2 = bin_tables(k2)
    base2 = tone(N_PERIOD, k2, 500.0)
    segs2 = [list(base2), circular_shift(base2, 2), list(base2), list(base2)]
    st2 = [seg_stats(s, cos2, sin2) for s in segs2]
    theta = 2.0 * math.pi * k2 * 2 / N_PERIOD
    exp_rho2 = math.cos(theta)
    exp_dphi2 = -math.degrees(theta)
    exp_coh2 = math.hypot(3.0 + math.cos(theta), math.sin(theta)) / 4.0
    measured2 = {
        "rho": pearson(segs2[0], segs2[1], st2[0], st2[1]),
        "dphi_deg": wrap_deg(phase_deg(st2[1]) - phase_deg(st2[0])),
        "coh": coherence(st2),
    }
    record("S2", "单段移 2 样本 @k=100 → rho=cos18°、dphi=-18°、coh=|3+e^-j18°|/4",
           {"rho": exp_rho2, "dphi_deg": exp_dphi2, "coh": exp_coh2}, measured2)

    # S3: 线性相位斜坡（每段再移 1 样本，k=100 → 9°/段）
    segs3 = [circular_shift(base2, q) for q in range(4)]
    st3 = [seg_stats(s, cos2, sin2) for s in segs3]
    th = math.radians(9.0)
    exp_coh3 = abs(math.sin(4 * th / 2.0) / (4.0 * math.sin(th / 2.0)))
    measured3 = {
        "rho_q1": pearson(segs3[0], segs3[1], st3[0], st3[1]),
        "rho_q2": pearson(segs3[0], segs3[2], st3[0], st3[2]),
        "dphi_q3": wrap_deg(phase_deg(st3[3]) - phase_deg(st3[0])),
        "coh": coherence(st3),
    }
    record("S3", "线性相位斜坡 9°/段 → rho_q=cos(9q°)、dphi_q3=-27°、coh=sin36°/(4sin9°)",
           {"rho_q1": math.cos(th), "rho_q2": math.cos(2 * th),
            "dphi_q3": -27.0, "coh": exp_coh3}, measured3)

    # S4: 一段全 0（坏段）→ 该段相关无定义(记 nan)，其余 3 段折叠回原信号
    segs4 = [list(base2), [0.0] * N_PERIOD, list(base2), list(base2)]
    st4 = [seg_stats(s, cos2, sin2) for s in segs4]
    good = [segs4[q] for q in (0, 2, 3)]
    fold4 = fold_mean(good)
    measured4 = {
        "rho_zero": pearson(segs4[0], segs4[1], st4[0], st4[1]),
        "fold_maxdiff": max(abs(a - b) for a, b in zip(fold4, base2)),
    }
    record("S4", "一段全 0 → rho=nan（必须拒绝该段）；只用其余 3 段折叠=原段",
           {"rho_zero": float("nan"), "fold_maxdiff": 0.0}, measured4)

    # S5: 包间公共相位 30°（第二包整体乘 e^{j30°} 的实部形式）
    psi = math.radians(30.0)
    base5 = tone(N_PERIOD, k, 800.0, phase0=0.1 + psi)
    sa = tone(N_PERIOD, k, 800.0, phase0=0.1)
    st_a = seg_stats(sa, cos_t, sin_t)
    st_b = seg_stats(base5, cos_t, sin_t)
    measured5 = {
        "rho": pearson(sa, base5, st_a, st_b),
        "dphi_deg": wrap_deg(phase_deg(st_b) - phase_deg(st_a)),
    }
    record("S5", "包间 30° 公共相位 → rho=cos30°、dphi=+30°",
           {"rho": math.cos(psi), "dphi_deg": 30.0}, measured5)

    # S6: 大幅值（30000）4 段相同 → float64 均值折叠不溢出；若用 int16 累加会回绕
    amp6 = 30000.0
    base6 = tone(N_PERIOD, k, amp6)
    segs6 = [list(base6) for _ in range(4)]
    fold6 = fold_mean(segs6)
    measured6 = {
        "fold_max": max(fold6),
        "fold_max_abs": max(abs(x) for x in fold6),
        "fold_maxdiff": max(abs(a - b) for a, b in zip(fold6, base6)),
    }
    record("S6", "幅值 30000 的 4 段均值折叠：不溢出、不回绕（int16 之和会回绕）",
           {"fold_max": amp6, "fold_max_abs": amp6, "fold_maxdiff": 0.0}, measured6)


# ---------------------------------------------------------------------------
# 4. 真实数据：空场 data1 的独立统计
# ---------------------------------------------------------------------------
def display_path(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def run_group(dirpath: Path, phase_bin: int) -> dict:
    rows, common, meta = load_group(dirpath)
    cos_t, sin_t = bin_tables(phase_bin)
    print("\n== 真实数据：%s ==" % dirpath.as_posix())
    print("行文件 %d/8；共同 sync=%r（P=%d）" % (len(rows), common, len(common)))
    for m in meta:
        print("  row %d %-40s %8d B  packets=%d syncs=%r problems=%r" % (
            m["row"], m["file"], m["size"], m["n_packets"], m["syncs"], m["problems"]))

    rho: list[float] = []
    dphi: list[float] = []
    coh: list[float] = []
    per_packet: dict[int, dict] = {}
    fold_ratio: list[float] = []
    per_channel: dict[int, dict] = {}

    for p in common:
        p_rho: list[float] = []
        p_dphi: list[float] = []
        p_coh: list[float] = []
        for r in range(N_ROWS):
            arr = rows[r][p]
            for c in range(8):
                ch = 8 * r + c
                if ch == TX_IDX:
                    continue
                segs = [seg_values(arr, c, q) for q in range(4)]
                stats = [seg_stats(s, cos_t, sin_t) for s in segs]
                ch_rho: list[float] = []
                ch_dphi: list[float] = []
                for q in range(1, 4):
                    rq = pearson(segs[0], segs[q], stats[0], stats[q])
                    dq = wrap_deg(phase_deg(stats[q]) - phase_deg(stats[0]))
                    ch_rho.append(rq)
                    ch_dphi.append(dq)
                rho.extend(ch_rho)
                dphi.extend(ch_dphi)
                p_rho.extend(ch_rho)
                p_dphi.extend(ch_dphi)
                cg = coherence(stats)
                coh.append(cg)
                p_coh.append(cg)
                fold = fold_mean(segs)
                seg_rms_mean = sum(rms(s) for s in segs) / 4.0
                fold_ratio.append(rms(fold) / seg_rms_mean if seg_rms_mean > 0 else float("nan"))
                d = per_channel.setdefault(ch, {"rho": [], "dphi": [], "coh": []})
                d["rho"].extend(ch_rho)
                d["dphi"].extend(ch_dphi)
                d["coh"].append(cg)
        per_packet[p] = {
            "n_segments": len(p_rho),
            "rho_min": min(p_rho), "rho_median": sorted(p_rho)[len(p_rho) // 2],
            "abs_dphi_max_deg": max(abs(x) for x in p_dphi),
            "coh_min": min(p_coh), "coh_median": sorted(p_coh)[len(p_coh) // 2],
        }

    def pct(vals: list[float], q: float) -> float:
        s = sorted(vals)
        if not s:
            return float("nan")
        i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
        return s[i]

    rho_finite = [x for x in rho if not math.isnan(x)]
    summary = {
        "phase_bin": phase_bin,
        "phase_bin_hz": phase_bin * FS_HZ / N_PERIOD,
        "n_packets": len(common),
        "syncs": common,
        "n_rx_channels": 63,
        "n_segment_pairs": len(rho),
        "rho_min": min(rho_finite),
        "rho_p01": pct(rho_finite, 0.01),
        "rho_median": pct(rho_finite, 0.5),
        "rho_max": max(rho_finite),
        "abs_dphi_deg_max": max(abs(x) for x in dphi),
        "abs_dphi_deg_p99": pct([abs(x) for x in dphi], 0.99),
        "abs_dphi_deg_median": pct([abs(x) for x in dphi], 0.5),
        "abs_dphi_ns_max": abs(phase_to_ns(max(abs(x) for x in dphi), phase_bin)),
        "coh_min": min(coh),
        "coh_median": pct(coh, 0.5),
        "fold_rms_ratio_min": min(x for x in fold_ratio if not math.isnan(x)),
        "fold_rms_ratio_median": pct([x for x in fold_ratio if not math.isnan(x)], 0.5),
    }

    # 候选门限扫描：记录各阈值会拒绝多少段 —— 阈值必须由数据方给出依据
    scan = {}
    for thr in (0.90, 0.95, 0.98, 0.99, 0.995, 0.999):
        scan["rho_lt_%.3f" % thr] = sum(1 for x in rho_finite if x < thr) / len(rho_finite)
    for thr in (1.0, 2.0, 5.0, 10.0, 20.0, 45.0):
        scan["absdphi_gt_%gdeg" % thr] = sum(1 for x in dphi if abs(x) > thr) / len(dphi)
    summary["threshold_scan_fraction"] = scan

    # 包间漂移：同一通道第 p 包与第 0 包（第 0 段）
    cross: dict[str, dict] = {}
    ref_stats = None
    if len(common) >= 2:
        all_rho: list[float] = []
        all_dphi: list[float] = []
        for r in range(N_ROWS):
            for c in range(8):
                ch = 8 * r + c
                if ch == TX_IDX:
                    continue
                seg0 = {p: seg_values(rows[r][p], c, 0) for p in common}
                st = {p: seg_stats(seg0[p], cos_t, sin_t) for p in common}
                for p in common[1:]:
                    rq = pearson(seg0[common[0]], seg0[p], st[common[0]], st[p])
                    dq = wrap_deg(phase_deg(st[p]) - phase_deg(st[common[0]]))
                    all_rho.append(rq)
                    all_dphi.append(dq)
                    if ch == REF_IDX:
                        cross.setdefault("ref_%d_vs_%d" % (p, common[0]), {})
                        cross["ref_%d_vs_%d" % (p, common[0])] = {
                            "rho": rq, "dphi_deg": dq,
                            "dphi_ns": phase_to_ns(dq, phase_bin)}
        cross["all_channels"] = {
            "rho_min": min(all_rho), "rho_median": pct(all_rho, 0.5),
            "abs_dphi_deg_max": max(abs(x) for x in all_dphi),
            "abs_dphi_deg_median": pct([abs(x) for x in all_dphi], 0.5),
            "abs_dphi_ns_max": abs(phase_to_ns(max(abs(x) for x in all_dphi), phase_bin)),
        }

    worst_channels = sorted(((ch, min(d["rho"])) for ch, d in per_channel.items()),
                            key=lambda x: x[1])[:5]
    print("rho   min=%.6f p01=%.6f median=%.6f" % (
        summary["rho_min"], summary["rho_p01"], summary["rho_median"]))
    print("|dphi| deg median=%.4f p99=%.4f max=%.4f (%.6f ns max)" % (
        summary["abs_dphi_deg_median"], summary["abs_dphi_deg_p99"],
        summary["abs_dphi_deg_max"], summary["abs_dphi_ns_max"]))
    print("coh   min=%.6f median=%.6f；fold_rms_ratio median=%.6f" % (
        summary["coh_min"], summary["coh_median"], summary["fold_rms_ratio_median"]))
    print("per-packet:", json.dumps(per_packet, ensure_ascii=False))
    print("threshold scan:", json.dumps(scan, ensure_ascii=False))
    print("worst channels (min rho):", [(ch, round(r, 6)) for ch, r in worst_channels])
    print("cross-packet:", json.dumps({k: v for k, v in cross.items() if k != "all_channels"},
                                       ensure_ascii=False))
    print("cross-packet all:", json.dumps(cross.get("all_channels", {}), ensure_ascii=False))

    return {"group": display_path(dirpath), "row_files": meta, "summary": summary,
            "per_packet": per_packet, "cross_packet": cross,
            "worst_channels_min_rho": worst_channels}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default=str(REPO_ROOT / DEFAULT_GROUP))
    ap.add_argument("--phase-bin", type=int, default=DEFAULT_PHASE_BIN)
    ap.add_argument("--json", default=str(Path(__file__).with_name("d1_prereg_expected.json")))
    args = ap.parse_args()

    run_synthetic()
    real = run_group(Path(args.group), args.phase_bin)

    payload = {
        "probe": "D1-PREREG-1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": "A-Q1-D1 data/a-q1-fold-gate（M0 §7.2 折叠 + 一致性门控）",
        "input_anchor": {"main": "4a210601041e842de361c8b08b398343d2fc934a",
                         "d0_reader_blob": "58fbcd6fa231（D0 读取器 blob，合并后未变）"},
        "metric_definitions": {
            "rho": "同包第 q 段(q=1..3)与第 0 段的 Pearson 相关（去均值）",
            "dphi_deg": "同包第 q 段与第 0 段在 k=%d 的 DFT 相位差，卷绕 (-180,180]" % args.phase_bin,
            "dphi_ns": "dphi 按 -360*k*d/Np 换算的时延（ns），Ts=0.25 ns",
            "coh": "|sum_q c_q| / sum_q |c_q|，k=%d" % args.phase_bin,
            "fold_rms_ratio": "rms(4 段均值)/mean(rms(各段))；均值折叠应为 ~1，求和折叠为 ~4",
        },
        "synthetic": RESULTS,
        "synthetic_all_pass": all(r["status"] == "PASS" for r in RESULTS),
        "real": real,
    }
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2,
                              allow_nan=False), encoding="utf-8")
    print("\nJSON -> %s" % out)
    print("SYNTHETIC: %d/%d PASS" % (
        sum(1 for r in RESULTS if r["status"] == "PASS"), len(RESULTS)))
    return 0 if payload["synthetic_all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
