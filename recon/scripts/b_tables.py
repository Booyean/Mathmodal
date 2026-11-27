#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 题原始附件（12 张表）字段与规模清点，含旧版 .xls。

不假设表头位置与编码，逐单元格读取并统计：
  - 每表：工作表名、有效行数、列数、空行/空列、重复列名
  - 每列：非空数、缺失率、类型推断、去重数、极值、样例值
  - 与题面声明的条数逐项核对（1321/1355/1339/917/650/1176）
输出：
  recon/manifests/b_table_summary.csv
  recon/manifests/b_column_inventory.csv
  recon/reports/b_inventory_summary.json
  recon/samples/b_<表名>_head.csv   每张表前 3 行原始值
用法：
  python recon/scripts/b_tables.py --root "<B题目录>"
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, time

# 工作区自带的 xlrd（pip 在本沙箱无法写临时目录，改用官方 wheel 解包安装）
_here = os.path.dirname(os.path.abspath(__file__))
for cand in (
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_here))), "pylibs"),
    r"D:\数模\pylibs",
):
    if os.path.isdir(cand) and cand not in sys.path:
        sys.path.append(cand)

import openpyxl  # noqa: E402
import xlrd  # noqa: E402


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def classify(values):
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return "empty", None, None, 0
    n_num = sum(1 for v in non_null if is_number(v))
    n_dt = sum(1 for v in non_null if isinstance(v, (datetime, date, time)))
    if n_dt / len(non_null) > 0.9:
        return "datetime", min(non_null), max(non_null), len(set(non_null))
    if n_num / len(non_null) > 0.9:
        return "number", min(non_null), max(non_null), len(set(non_null))
    if n_num == 0 and n_dt == 0:
        return "text", None, None, len(set(non_null))
    return "mixed", None, None, len(set(non_null))


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, time):
        return v.strftime("%H:%M:%S")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("\n", " ").strip()


def read_xlsx(path):
    """返回 [(sheet_name, header(list), rows(list of list))]"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        # 有些导出文件的 <dimension> 被写成 A1，read_only 会只读到 1 个单元格；
        # reset_dimensions() 让迭代器回到整张表扫描。
        if hasattr(ws, "reset_dimensions"):
            ws.reset_dimensions()
        it = ws.iter_rows(values_only=True)
        rows = [list(r) for r in it]
        if not rows:
            out.append((ws.title, [], []))
            continue
        header = ["" if h is None else str(h).strip() for h in rows[0]]
        data = rows[1:]
        out.append((ws.title, header, data))
    wb.close()
    return out


def read_xls(path):
    wb = xlrd.open_workbook(path, formatting_info=False)
    out = []
    for sh in wb.sheets():
        rows = []
        for r in range(sh.nrows):
            vals = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        vals.append(xlrd.xldate_as_datetime(cell.value, wb.datemode))
                    except Exception:
                        vals.append(cell.value)
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    vals.append(None)
                else:
                    vals.append(cell.value)
            rows.append(vals)
        header = ["" if h is None else str(h).strip() for h in rows[0]] if rows else []
        out.append((sh.name, header, rows[1:]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=os.path.dirname(_here) if os.path.basename(_here) == "scripts" else ".")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    out = os.path.abspath(args.out)
    for d in ("manifests", "reports", "samples"):
        os.makedirs(os.path.join(out, d), exist_ok=True)

    files = sorted(
        os.path.join(dp, fn)
        for dp, _dn, fns in os.walk(root)
        for fn in fns
        if fn.lower().endswith((".xlsx", ".xls"))
    )

    table_rows = []
    col_rows = []
    all_time = []
    summaries = []

    for fp in files:
        base = os.path.basename(fp)
        ext = os.path.splitext(base)[1].lower()
        sheets = read_xlsx(fp) if ext == ".xlsx" else read_xls(fp)
        for sname, header, data in sheets:
            ncols = max([len(header)] + [len(r) for r in data]) if (header or data) else 0
            header = header + [""] * (ncols - len(header))
            data = [list(r) + [None] * (ncols - len(r)) for r in data]
            # 去掉全空行
            nonempty = [r for r in data if any(v is not None and v != "" for v in r)]
            empty_rows = len(data) - len(nonempty)
            dup_cols = [k for k, v in Counter([h for h in header if h]).items() if v > 1]
            empty_cols = [i for i in range(ncols) if all((r[i] is None or r[i] == "") for r in nonempty)]
            table = base
            table_rows.append(
                {
                    "file": base,
                    "sheet": sname,
                    "n_data_rows": len(nonempty),
                    "n_raw_rows": len(data),
                    "n_empty_rows": empty_rows,
                    "n_cols": ncols,
                    "n_empty_cols": len(empty_cols),
                    "duplicate_headers": ";".join(dup_cols),
                    "header_sample": "|".join([h for h in header if h][:8]),
                }
            )
            # 列级统计
            for i in range(ncols):
                vals = [r[i] for r in nonempty]
                kind, mn, mx, distinct = classify(vals)
                non_null = sum(1 for v in vals if v is not None and v != "")
                samples = []
                for v in vals:
                    if v is not None and v != "" and fmt(v) not in samples:
                        samples.append(fmt(v))
                    if len(samples) >= 3:
                        break
                if kind == "datetime":
                    all_time.append((base, header[i], mn, mx))
                col_rows.append(
                    {
                        "file": base,
                        "sheet": sname,
                        "col_idx": i + 1,
                        "header": header[i],
                        "non_null": non_null,
                        "missing_rate": round(1 - non_null / max(1, len(nonempty)), 4),
                        "dtype_guess": kind,
                        "distinct": distinct,
                        "min": fmt(mn),
                        "max": fmt(mx),
                        "sample_values": " || ".join(samples),
                    }
                )
            summaries.append(
                {
                    "file": base,
                    "sheet": sname,
                    "rows": len(nonempty),
                    "cols": ncols,
                    "headers": [h for h in header if h],
                }
            )
            # 小样（前 3 行）
            sname_safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in os.path.splitext(base)[0])[:40]
            with open(os.path.join(out, "samples", "b_%s__%s_head.csv" % (sname_safe, "".join(ch if ch.isalnum() else "_" for ch in sname)[:20])), "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                for r in nonempty[:3]:
                    w.writerow([fmt(v) for v in r])

    with open(os.path.join(out, "manifests", "b_table_summary.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table_rows[0].keys()))
        w.writeheader()
        w.writerows(table_rows)
    with open(os.path.join(out, "manifests", "b_column_inventory.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(col_rows[0].keys()))
        w.writeheader()
        w.writerows(col_rows)

    # 与题面声明核对
    declared = {
        "出钢计划表单.xls": {"rows": 1321, "cols": 42, "note": "含 55 条 -2 占位"},
        "工序时间信息.xlsx": {"rows": 1355, "note": "综合主表"},
        "A炉.xlsx+B炉.xlsx+C炉.xlsx": {"rows": 1339},
        "1#LF.xlsx+3#LF.xlsx": {"rows": 917},
        "1#RH.xlsx+2#RH.xlsx": {"rows": 650},
        "1#连铸.xlsx+2#连铸.xlsx+3#连铸.xlsx": {"rows": 1176},
    }
    by_file = {}
    for s in summaries:
        by_file[s["file"]] = sim = by_file.get(s["file"], {"rows": 0, "cols": s["cols"]})
        sim["rows"] += s["rows"]
    actual = {
        "出钢计划表单.xls": by_file.get("出钢计划表单.xls", {}).get("rows"),
        "工序时间信息.xlsx": by_file.get("工序时间信息.xlsx", {}).get("rows"),
        "A炉.xlsx+B炉.xlsx+C炉.xlsx": sum(by_file.get(k, {}).get("rows", 0) for k in ("A炉.xlsx", "B炉.xlsx", "C炉.xlsx")),
        "1#LF.xlsx+3#LF.xlsx": sum(by_file.get(k, {}).get("rows", 0) for k in ("1#LF.xlsx", "3#LF.xlsx")),
        "1#RH.xlsx+2#RH.xlsx": sum(by_file.get(k, {}).get("rows", 0) for k in ("1#RH.xlsx", "2#RH.xlsx")),
        "1#连铸.xlsx+2#连铸.xlsx+3#连铸.xlsx": sum(
            by_file.get(k, {}).get("rows", 0) for k in ("1#连铸.xlsx", "2#连铸.xlsx", "3#连铸.xlsx")
        ),
    }
    check = []
    for k, spec in declared.items():
        a = actual.get(k)
        ok = a == spec["rows"]
        check.append({"item": k, "declared_rows": spec["rows"], "actual_rows": a, "match": "YES" if ok else "NO"})
    cols_declared = declared["出钢计划表单.xls"].get("cols")
    cols_actual = by_file.get("出钢计划表单.xls", {}).get("cols")
    check.append(
        {
            "item": "出钢计划表单.xls 字段数",
            "declared_rows": cols_declared,
            "actual_rows": cols_actual,
            "match": "YES" if cols_declared == cols_actual else "NO",
        }
    )

    tmin = min((t[2] for t in all_time), default=None)
    tmax = max((t[3] for t in all_time), default=None)
    summary = {
        "root": root,
        "n_tables": len(files),
        "tables": summaries,
        "declared_vs_actual": check,
        "time_window_all_datetime_columns": [fmt(tmin), fmt(tmax)],
        "n_datetime_columns": len(all_time),
    }
    with open(os.path.join(out, "reports", "b_inventory_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({k: v for k, v in summary.items() if k != "tables"}, ensure_ascii=False, indent=2, default=str))
    for s in summaries:
        print("%-22s %-18s rows=%-6d cols=%-4d %s" % (s["file"], s["sheet"], s["rows"], s["cols"], "|".join(s["headers"][:6])))


if __name__ == "__main__":
    sys.exit(main())
