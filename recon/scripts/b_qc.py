#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 题数据质量（QC）实测：时间解析、键唯一性、占位符、负时长、实体别名一致性。

只读原始附件，不修改任何数据；所有结论都以计数和样例支撑。
输出：
  recon/manifests/b_qc_time_columns.csv     每个"时间型"列的解析成功率与范围
  recon/manifests/b_qc_keys.csv             每张表 熔炼号 唯一性/覆盖
  recon/manifests/b_qc_join_matrix.csv      各表 熔炼号 集合两两交集
  recon/reports/b_qc_summary.json           汇总（含负时长、制表符、占位符、时间窗）
用法：
  python recon/scripts/b_qc.py --root "<B题目录>"
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
for cand in (
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_here))), "pylibs"),
    r"D:\数模\pylibs",
):
    if os.path.isdir(cand) and cand not in sys.path:
        sys.path.append(cand)

from b_tables import fmt, read_xls, read_xlsx  # noqa: E402

TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$")
DUR_RE = re.compile(r"^-?\d+小时|\d+分钟|\d+秒|^-?\d+\.?\d*$")


def parse_ts(v):
    if isinstance(v, datetime):
        return v, None
    if isinstance(v, str):
        m = TS_RE.match(v.strip())
        if m:
            y, mo, d, hh, mm, ss = m.groups()
            try:
                return datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss or 0)), None
            except ValueError as e:
                return None, str(e)
        if v.strip():
            return None, "unparsed"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=os.path.dirname(_here))
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    out = os.path.abspath(args.out)
    for d in ("manifests", "reports"):
        os.makedirs(os.path.join(out, d), exist_ok=True)

    files = sorted(
        os.path.join(dp, fn)
        for dp, _dn, fns in os.walk(root)
        for fn in fns
        if fn.lower().endswith((".xlsx", ".xls"))
    )

    time_rows = []
    key_rows = []
    mel_sets = {}
    neg_durations = []
    tab_cells = Counter()
    placeholders = Counter()
    all_ts = []
    bad_ts = Counter()
    window_rows = []

    for fp in files:
        base = os.path.basename(fp)
        ext = os.path.splitext(base)[1].lower()
        sheets = read_xlsx(fp) if ext == ".xlsx" else read_xls(fp)
        for sname, header, data in sheets:
            ncols = max([len(header)] + [len(r) for r in data]) if (header or data) else 0
            header = header + [""] * (ncols - len(header))
            data = [list(r) + [None] * (ncols - len(r)) for r in data]
            data = [r for r in data if any(v is not None and v != "" for v in r)]
            if not data:
                continue
            for i in range(ncols):
                vals = [r[i] for r in data]
                h = header[i]
                # --- 时间列：≥80% 非空值可解析为时间戳 ---
                nonnull = [v for v in vals if v is not None and v != ""]
                if not nonnull:
                    continue
                parsed = []
                fails = 0
                for v in nonnull:
                    dt, err = parse_ts(v)
                    if dt:
                        parsed.append(dt)
                    elif isinstance(v, str) and TS_RE.match(v.strip()):
                        fails += 1
                if len(parsed) >= 0.8 * len(nonnull):
                    mn = min(parsed)
                    mx = max(parsed)
                    all_ts.extend(parsed)
                    time_rows.append(
                        {
                            "file": base,
                            "sheet": sname,
                            "col_idx": i + 1,
                            "header": h,
                            "non_null": len(nonnull),
                            "parsed_ts": len(parsed),
                            "parse_fail": fails,
                            "min": fmt(mn),
                            "max": fmt(mx),
                            "n_outside_claim_window": sum(
                                1
                                for d in parsed
                                if d < datetime(2026, 9, 24, 23, 24) or d > datetime(2026, 10, 12, 11, 1)
                            ),
                        }
                    )
                # --- 时长列找负值 / 制表符 ---
                if "时间" in h or "耗时" in h or "等待" in h:
                    neg = [v for v in nonnull if isinstance(v, str) and v.strip().startswith("-")]
                    if neg:
                        neg_durations.append(
                            # 按单元格计数：同一炉次可有多列/多格负值，不能当作"故障炉次数"
                            {"file": base, "sheet": sname, "header": h, "n_negative_cells": len(neg), "sample": fmt(neg[0])[:60]}
                        )
                for v in nonnull:
                    if isinstance(v, str) and ("\t" in v):
                        tab_cells[(base, h)] += 1
                # --- -2 占位 ---
                n_ph = sum(1 for v in nonnull if (isinstance(v, (int, float)) and v == -2) or (isinstance(v, str) and v.strip() == "-2"))
                if n_ph:
                    placeholders[(base, h, sname)] = n_ph
            # --- 熔炼号键 ---
            if "熔炼号" in header:
                ci = header.index("熔炼号")
                vals = [("" if r[ci] is None else str(r[ci]).strip()) for r in data]
                vals = [v for v in vals if v]
                c = Counter(vals)
                dup = {k: v for k, v in c.items() if v > 1}
                key_rows.append(
                    {
                        "file": base,
                        "sheet": sname,
                        "rows": len(data),
                        "n_melt_nonnull": len(vals),
                        "n_distinct": len(c),
                        "n_dup_rows": sum(v - 1 for v in dup.values()),
                        "dup_examples": ";".join(list(dup)[:3]),
                        "melting_no_format": "".join(sorted({re.sub(r"\d", "#", v)[:4] for v in vals})[:3]),
                    }
                )
                mel_sets[base] = set(vals)

    tmin = min(all_ts) if all_ts else None
    tmax = max(all_ts) if all_ts else None
    window_rows.append(
        {
            "claim": "全部实际工序数据统一时间窗 2026-09-24 23:24 ～ 2026-10-12 11:01",
            "observed_min": fmt(tmin),
            "observed_max": fmt(tmax),
            "n_timestamps": len(all_ts),
        }
    )

    # 两两交集
    names = sorted(mel_sets)
    join_rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            inter = len(mel_sets[a] & mel_sets[b])
            join_rows.append(
                {
                    "table_a": a,
                    "table_b": b,
                    "n_a": len(mel_sets[a]),
                    "n_b": len(mel_sets[b]),
                    "intersection": inter,
                    "jaccard": round(inter / max(1, len(mel_sets[a] | mel_sets[b])), 4),
                }
            )

    with open(os.path.join(out, "manifests", "b_qc_time_columns.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(time_rows[0].keys()))
        w.writeheader()
        w.writerows(time_rows)
    with open(os.path.join(out, "manifests", "b_qc_keys.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(key_rows[0].keys()))
        w.writeheader()
        w.writerows(key_rows)
    with open(os.path.join(out, "manifests", "b_qc_join_matrix.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(join_rows[0].keys()))
        w.writeheader()
        w.writerows(join_rows)

    summary = {
        "root": root,
        "time_window_check": window_rows,
        "n_time_columns": len(time_rows),
        "n_time_columns_with_parse_fail": sum(1 for r in time_rows if r["parse_fail"]),
        "nan_outside_claim_window": sum(r["n_outside_claim_window"] for r in time_rows),
        "negative_duration_columns": neg_durations,
        "n_negative_duration_columns": len(neg_durations),
        "n_negative_duration_cells": sum(x["n_negative_cells"] for x in neg_durations),
        "tab_contaminated_columns": [{"file": k[0], "header": k[1], "n": v} for k, v in tab_cells.items()],
        "placeholders_minus2": [{"file": k[0], "header": k[1], "sheet": k[2], "n": v} for k, v in sorted(placeholders.items())],
        "melting_key": key_rows,
        "melting_no_union_size": len(set().union(*mel_sets.values())) if mel_sets else 0,
    }
    with open(os.path.join(out, "reports", "b_qc_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
    txt = json.dumps(
        {
            "time_window_check": window_rows,
            "n_time_columns": len(time_rows),
            "n_time_cols_parse_fail": sum(1 for r in time_rows if r["parse_fail"]),
            "outside_claim_window": sum(r["n_outside_claim_window"] for r in time_rows),
            "neg_durations": neg_durations,
            "placeholders": summary["placeholders_minus2"],
            "melting_key": key_rows,
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    print(txt[:6000])


if __name__ == "__main__":
    sys.exit(main())
