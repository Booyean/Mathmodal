#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D0 读取器测试：合成例（协议分支/异常路径）+ 真实组（完整 8 行/包数不等/-32768/0 字节）。

预期值先按协议和 R0 侦察事实独立写定，再与实现比对；真实组预期值来自：
  * ``recon/manifests/a_group_manifest.csv``（R0，PR #1，已合并到 ``44c778e``）
  * 本文件内的独立解析片段（不复用读取器的 ``parse_bytes``）
  * ``solutions/A/data_contract.md`` §1、§3、§4 的实测记录

用法：
  python solutions/A/test_a_dat_reader.py            # 合成例 + 真实组
  python solutions/A/test_a_dat_reader.py --no-real  # 只跑合成例（无原始数据时）
真实数据缺失时真实组记为 SKIP（不计失败），并在摘要中单列。
"""

from __future__ import annotations

import csv
import json
import shutil
import struct
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import a_dat_reader as R  # noqa: E402

RESULTS: List[Dict[str, Any]] = []
MAGIC = 963072
TYPE_DATA = 102


# ---------------------------------------------------------------- 测试框架
def _eq(expected: Any, actual: Any) -> bool:
    if isinstance(expected, np.ndarray) or isinstance(actual, np.ndarray):
        return bool(np.array_equal(np.asarray(expected), np.asarray(actual)))
    return bool(expected == actual)


def check(name: str, expected: Any, actual: Any, note: str = "") -> bool:
    ok = _eq(expected, actual)
    RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL", "expected": expected, "actual": actual})
    print("[%s] %-62s expected=%r actual=%r%s" % ("PASS" if ok else "FAIL", name, expected, actual, ("  " + note) if note else ""))
    return ok


def skip(name: str, why: str) -> None:
    RESULTS.append({"name": name, "status": "SKIP", "expected": "-", "actual": why})
    print("[SKIP] %-62s %s" % (name, why))


def check_raises(name: str, exc_type: type, fn, expected_rows: Optional[Sequence[int]] = None) -> bool:
    try:
        fn()
    except exc_type as exc:  # noqa: PERF203
        got = getattr(exc, "missing_rows", None)
        ok = expected_rows is None or got == list(expected_rows)
        RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL", "expected": expected_rows, "actual": got})
        print("[%s] %-62s expected_rows=%r actual_rows=%r" % ("PASS" if ok else "FAIL", name, expected_rows, got))
        return ok
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"name": name, "status": "FAIL", "expected": exc_type.__name__, "actual": repr(exc)})
        print("[FAIL] %-62s 期望 %s，实际 %r" % (name, exc_type.__name__, exc))
        return False
    RESULTS.append({"name": name, "status": "FAIL", "expected": exc_type.__name__, "actual": "没有抛异常"})
    print("[FAIL] %-62s 期望 %s，实际没有抛异常" % (name, exc_type.__name__))
    return False


# ---------------------------------------------------------------- 合成数据构造
def packet_bytes(
    sync: int,
    mat: np.ndarray,
    *,
    num: Optional[int] = None,
    length: Optional[int] = None,
    freq: float = 0.0,
    ptype: int = TYPE_DATA,
    total_len: Optional[int] = None,
) -> bytes:
    """按 get_data_iq.m 的协议构造一个包（含 28 字节头）。"""
    m = np.asarray(mat, dtype="<i2")
    if m.ndim != 2 or m.shape[0] != 8:
        raise ValueError("mat 必须是 8 x N")
    n_samp = m.shape[1]
    data = m.T.tobytes()
    n = num if num is not None else n_samp
    ln = length if length is not None else 2 * m.shape[0]
    if n * ln != len(data):
        raise ValueError("num*len=%d 与采样字节数 %d 不一致" % (n * ln, len(data)))
    tl = total_len if total_len is not None else 20 + len(data)
    return struct.pack("<III", MAGIC, tl, ptype) + struct.pack("<fIII", freq, sync, n, ln) + data


def non_data_packet(payload_len: int = 32, ptype: int = 99) -> bytes:
    """type != 102 的包：.m 会跳过 total_len-4 字节。"""
    payload = b"\x11" * payload_len
    return struct.pack("<III", MAGIC, 4 + payload_len, ptype) + payload


def write_group(
    root: Path,
    rel_dir: str,
    prefix: str,
    packets_by_row: Dict[int, List[bytes]],
    *,
    zero_rows: Sequence[int] = (),
    skip_rows: Sequence[int] = (),
) -> None:
    d = root / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    for r, chunks in packets_by_row.items():
        if r in skip_rows:
            continue
        (d / ("%s_%d.dat" % (prefix, r))).write_bytes(b"".join(chunks))
    for r in zero_rows:
        (d / ("%s_%d.dat" % (prefix, r))).write_bytes(b"")


def flat(n_packets: int, syncs: Sequence[int], value: int = 1, n_samp: int = 16000) -> Dict[int, List[bytes]]:
    """所有行同样的包（值全为 value），只用于形状/配对测试。"""
    mat = np.full((8, n_samp), value, dtype="<i2")
    return {r: [packet_bytes(s, mat) for s in syncs] for r in range(8)}


# ---------------------------------------------------------------- 合成测试
def synthetic_tests(tmp: Path) -> None:
    # S1 基本解析 + 通道/时间映射
    n_samp = 32
    mat = np.zeros((8, n_samp), dtype=np.int16)
    for c in range(8):
        for t in range(n_samp):
            mat[c, t] = c * 100 - t  # 可区分通道与时间，值在 int16 内
    buf = packet_bytes(11, mat) + packet_bytes(12, np.full((8, n_samp), -7, dtype="<i2"))
    f = tmp / "basic.dat"
    f.write_bytes(buf)
    df = R.read_dat(f)
    check("S1a 包数", 2, len(df.packets))
    check("S1b 头部字段", (11, 32, 16), (df.packets[0].sync, df.packets[0].num, df.packets[0].length))
    check("S1c header_ok", True, all(p.header_ok for p in df.packets))
    got = df.packet_matrix(0).astype(np.int32)
    check("S1d 通道/时间映射(逐点)", "逐点相等", "逐点相等" if np.array_equal(got, mat.astype(np.int32)) else "不一致")
    check("S1e 第2包值", 12, int(df.packets[1].sync))
    check("S1f sha256 长度", 64, len(df.sha256))
    check("S1g 无异常/无残留", ([], 0, 0), ([p.code for p in df.problems], df.skipped_bytes, df.trailing_bytes))

    # S2 等价头部编码：num=8, len=32000，MATLAB reshape(...,8,[]) 仍应给出 8x16000
    m2 = np.arange(8 * 16000, dtype=np.int32).reshape(16000, 8).T.astype(np.int16)
    f2 = tmp / "alt_encoding.dat"
    f2.write_bytes(packet_bytes(5, m2, num=8, length=32000))
    df2 = R.read_dat(f2)
    check("S2a 等价头部采样点数", 16000, df2.packets[0].n_samples)
    check("S2b 等价头部矩阵", (8, 16000), tuple(df2.packet_matrix(0).shape))

    # S3 非数据包 + 间隙字节
    f3 = tmp / "mixed.dat"
    good_mat = np.full((8, 4), 3, dtype="<i2")
    f3.write_bytes(b"\xde\xad\xbe\xef" * 2 + non_data_packet(16) + b"\x00\x00" + packet_bytes(21, good_mat))
    df3 = R.read_dat(f3)
    codes = [p.code for p in df3.problems]
    check("S3a 非数据包被跳过", (1, 21), (len(df3.packets), df3.packets[0].sync))
    check("S3b 记录 non_data_packet", True, "non_data_packet" in codes)
    check("S3c 间隙字节计数", True, df3.skipped_bytes > 0, note="skipped_bytes=%d" % df3.skipped_bytes)

    # S4 截断采样区
    full = packet_bytes(31, np.ones((8, 64), dtype="<i2"))
    f4 = tmp / "truncated.dat"
    f4.write_bytes(full[:-100])
    df4 = R.read_dat(f4)
    check("S4a 截断包被丢弃", 0, len(df4.packets))
    check("S4b 记录 truncated_samples", ["truncated_samples", "no_data_packet", "trailing_bytes"], [p.code for p in df4.problems])

    # S5 空文件
    f5 = tmp / "empty.dat"
    f5.write_bytes(b"")
    df5 = R.read_dat(f5)
    check("S5 空文件", (0, 0, ["empty_file"]), (df5.size_bytes, len(df5.packets), [p.code for p in df5.problems]))

    # S6 共同 sync 交集 + 丢弃记录
    root = tmp / "附件"
    syncs_by_row = {0: [5, 6, 7], 1: [6, 7, 8]}
    for r in range(2, 8):
        syncs_by_row[r] = [6, 7]
    write_group(
        root,
        "附件2-测距数据/墙体数据/data9-91cm",
        "2026-01-01-00-00-00_16000",
        {r: [packet_bytes(s, np.full((8, 16000), r, dtype="<i2")) for s in ss] for r, ss in syncs_by_row.items()},
    )
    groups, problems = R.discover_groups(root)
    check("S6a 组发现", 1, len(groups))
    check("S6b group_key", "附件2-测距数据/墙体数据/data9-91cm", groups[0].group_key)
    gd = R.load_group(groups[0])
    check("S6c 共同 sync", [6, 7], gd.sync.tolist())
    check("S6d P", 2, int(gd.meta["n_packets"]))
    check("S6e 行0 被丢 sync", [5], gd.meta["row_files"]["0"]["syncs_dropped_not_in_intersection"])
    check("S6f 行1 被丢 sync", [8], gd.meta["row_files"]["1"]["syncs_dropped_not_in_intersection"])
    check("S6g 行值映射(row4)", 4, int(gd.packets[0, 32, 0]))

    # S7 文件内重复 sync
    root7 = tmp / "附件7"
    p6a = packet_bytes(6, np.full((8, 16000), 111, dtype="<i2"))
    p6b = packet_bytes(6, np.full((8, 16000), 222, dtype="<i2"))
    p7 = packet_bytes(7, np.full((8, 16000), 333, dtype="<i2"))
    rows7 = {r: [p6a, p7] for r in range(8)}
    rows7[3] = [p6a, p6b, p7]
    write_group(root7, "附件2-测距数据/空场数据/data1", "2026-01-01-00-00-01_16000", rows7)
    g7 = R.load_group(R.discover_groups(root7)[0][0])
    excl = g7.meta["excluded_packets"]
    check("S7a 重复 sync 排除条数", 1, len(excl))
    check("S7b 重复 sync 原因", "duplicate_sync_in_file", excl[0]["reason"] if excl else None)
    check("S7c 保留第一个包的值", 111, int(g7.packets[0, 24, 0]))

    # S8 形状不符的包
    root8 = tmp / "附件8"
    rows8 = {r: [p6a, p7] for r in range(8)}
    rows8[2] = [p6a, p7, packet_bytes(99, np.full((8, 12000), 5, dtype="<i2"))]
    write_group(root8, "附件2-测距数据/金属板数据/data3-54cm", "2026-01-01-00-00-02_16000", rows8)
    g8 = R.load_group(R.discover_groups(root8)[0][0])
    check("S8a 形状不符被排除", ["samples_per_packet_mismatch"], [e["reason"] for e in g8.meta["excluded_packets"]])
    check("S8b 交集不受影响", [6, 7], g8.sync.tolist())

    # S9 缺行：默认拒绝，显式允许时标记无效通道
    root9 = tmp / "附件9"
    write_group(root9, "附件2-测距数据/空场数据/data2", "2026-01-01-00-00-03_16000", flat(2, [61, 62]), skip_rows=(7,))
    g9ref = R.discover_groups(root9)[0][0]
    check("S9a missing_rows", [7], g9ref.missing_rows())
    check_raises("S9b 默认拒绝缺行", R.IncompleteGroupError, lambda: R.load_group(g9ref), expected_rows=[7])
    g9 = R.load_group(g9ref, require_all_rows=False)
    check("S9c 允许缺行时 P", 2, int(g9.meta["n_packets"]))
    check("S9d 缺行通道无效", [False] * 8, g9.channel_valid[56:].tolist())
    check("S9e 缺行通道未伪造数据", 0, int(np.abs(g9.packets[:, 56:, :]).max()))

    # S10 0 字节行文件
    root10 = tmp / "附件10"
    write_group(root10, "附件3-成像数据/墙体", "2026-01-01-00-00-04_16000", flat(2, [71, 72]), zero_rows=(7,))
    g10ref = R.discover_groups(root10)[0][0]
    check("S10a 0 字节行被定位", 0, g10ref.row_file_counts().get(7))
    check_raises("S10b 0 字节行默认拒绝", R.IncompleteGroupError, lambda: R.load_group(g10ref), expected_rows=[])

    # S11 端点统计口径：-32768 必须用 int32 计数，-32767 不是端点
    mat11 = np.tile(np.array([-32768, 32767, 0, -32767, 12], dtype="<i2"), (8, 1))
    f11 = tmp / "endpoints.dat"
    f11.write_bytes(packet_bytes(81, mat11))
    df11 = R.read_dat(f11)
    ep = df11.endpoint_counts()
    check("S11a 端点计数", (8, 8, 8, 40), (ep["neg_32768"], ep["pos_32767"], ep["zero"], ep["n_samples"]))
    check("S11b int16 绝对值会回绕(协议坑)", -32768, int(np.abs(np.int16(-32768))))

    # S12 组目录 vs 同目录多时间戳
    root12 = tmp / "附件12"
    write_group(root12, "附件3-成像数据/墙体", "2026-01-01-01-00-00_16000", flat(1, [1]))
    write_group(root12, "附件3-成像数据/墙体", "2026-01-01-02-00-00_16000", flat(1, [2]))
    gs12, _ = R.discover_groups(root12)
    keys = sorted(g.group_key for g in gs12)
    check("S12 同目录多组按时间戳区分", ["附件3-成像数据/墙体/2026-01-01-01-00-00_16000", "附件3-成像数据/墙体/2026-01-01-02-00-00_16000"], keys)

    # S13 未命名 .dat
    (root12 / "附件3-成像数据/墙体/notes.dat").write_bytes(b"")
    _, probs13 = R.discover_groups(root12)
    check("S13 非法文件名被记录", ["unexpected_dat_name"], [p.code for p in probs13])

    # S14 截断优先：num*len/2 同时不是 8 的倍数时，必须记 truncated_samples 而不是
    # sample_count_not_multiple_of_8（后者会静默跳过文件尾部，掩盖截断）。
    f14 = tmp / "truncated_mod8.dat"
    f14.write_bytes(
        struct.pack("<III", MAGIC, 23, TYPE_DATA)
        + struct.pack("<fIII", 0.0, 91, 1, 3)  # num=1, len=3 -> n_values=1, data_bytes=3
        + b"\x00"  # 只剩 1 字节，不足 3 字节
    )
    df14 = R.read_dat(f14)
    codes14 = [p.code for p in df14.problems]
    check(
        "S14a 截断优先于 8 倍数检查",
        True,
        "truncated_samples" in codes14 and "sample_count_not_multiple_of_8" not in codes14,
        note=str(codes14),
    )
    check("S14b 截断包不进入读取结果", 0, len(df14.packets))

    # S15 8 行齐全但 sync 无交集：P=0；channel_valid 仍按通道给 64 项，不随包数塌缩。
    root15 = tmp / "附件15"
    rows15 = {r: [packet_bytes(10 + r, np.full((8, 16000), r, dtype="<i2"))] for r in range(8)}
    write_group(root15, "附件2-测距数据/墙体数据/data4-62cm", "2026-01-01-00-00-05_16000", rows15)
    g15 = R.load_group(R.discover_groups(root15)[0][0])
    check("S15a 空交集 P", (0, []), (int(g15.meta["n_packets"]), g15.sync.tolist()))
    check("S15b 空交集形状", (0, 64, 16000), tuple(g15.packets.shape))
    check("S15c 空交集仍给 64 项通道有效性", (64, True), (len(g15.channel_valid), bool(g15.channel_valid.all())))


# ---------------------------------------------------------------- 真实数据独立核对片段
def independent_syncs_and_values(path: Path) -> Dict[int, np.ndarray]:
    """不复用读取器的独立解析（用于校验通道映射）。"""
    b = path.read_bytes()
    out: Dict[int, np.ndarray] = {}
    pos = 0
    while pos + 28 <= len(b):
        magic, total, typ = struct.unpack_from("<III", b, pos)
        if magic != MAGIC:
            pos += 4
            continue
        freq, sync, num, ln = struct.unpack_from("<fIII", b, pos + 12)
        nb = num * ln
        out[sync] = np.frombuffer(b, dtype="<i2", count=nb // 2, offset=pos + 28).reshape(num, ln // 2).T
        pos += 28 + nb
    return out


def real_tests(root: Path) -> None:
    # R1 空场 data1：4 个共同包、完整 8 行
    ref1 = R.find_group(root, "附件2-测距数据/空场数据/data1")
    g1 = R.load_group(ref1)
    check("R1a 空场 data1 共同 sync", [114, 115, 116, 117], g1.sync.tolist())
    check("R1b 形状", (4, 64, 16000), tuple(g1.packets.shape))
    check("R1c rx_mask", (63, False, True), (int(g1.rx_mask.sum()), bool(g1.rx_mask[27]), bool(g1.rx_mask[28])))
    check("R1d 通道有效", True, bool(g1.channel_valid.all()))
    check("R1e 参考/发射坐标", ([-0.07, 0.0, 0.545], [0.0, 0.0, 0.545]), (g1.positions_m[28].tolist(), g1.positions_m[27].tolist()))
    check("R1f 参考-发射间距", 0.07, round(float(np.linalg.norm(g1.positions_m[28] - g1.positions_m[27])), 12))
    check("R1g 行文件 sha256 位数", True, all(len(v["sha256"]) == 64 for v in g1.meta["row_files"].values()))

    # 通道映射独立核对：第 2 行(row=2) 与 sync=114
    ind = independent_syncs_and_values(ref1.files[2])[114]
    diff = int(np.abs(ind.astype(np.int32) - g1.packets[0, 16:24, :].astype(np.int32)).max())
    check("R1h 通道映射 vs 独立解析", 0, diff)

    # R2 包数不等的真实组
    g2 = R.load_group(R.find_group(root, "附件2-测距数据/墙体数据/data10-82cm"))
    counts = [g2.meta["row_files"][str(r)]["n_packets_total"] for r in range(8)]
    check("R2a 逐行原始包数", [2, 2, 3, 3, 2, 2, 3, 3], counts)
    check("R2b 交集", [398, 399], g2.sync.tolist())
    dropped = [g2.meta["row_files"][str(r)]["syncs_dropped_not_in_intersection"] for r in range(8)]
    check("R2c 被丢 sync", [[], [], [400], [400], [], [], [400], [400]], dropped)

    # R3 含 -32768 的真实组：46 个全在不进交集的 sync=250 包内
    g3 = R.load_group(R.find_group(root, "附件3-成像数据/金属柱和金属铲/2026-11-12-22-09-58_16000"))
    check("R3a 交集", [247, 248, 249], g3.sync.tolist())
    check("R3b 共同包端点", 0, g3.meta["extremes"]["neg_32768"])
    check("R3c 全包端点", 46, g3.meta["extremes"]["all_packets_in_group"]["neg_32768"])
    check("R3d 被丢 sync", [250], g3.meta["row_files"]["1"]["syncs_dropped_not_in_intersection"])
    check("R3e 行1 全包 -32768", 46, g3.meta["row_files"]["1"]["endpoint_counts_all_packets"]["neg_32768"])

    # R4 0 字节组
    g4ref = R.find_group(root, "附件3-成像数据/金属柱和金属铲/2026-11-12-22-50-31_16000")
    check("R4a 缺行", [0, 1, 2, 3, 4, 5, 6], g4ref.missing_rows())
    check("R4b 0 字节行", 0, g4ref.row_file_counts().get(7))
    check_raises("R4c 默认拒绝", R.IncompleteGroupError, lambda: R.load_group(g4ref))

    # R5 全量组清单
    groups, scan_problems = R.discover_groups(root)
    from collections import Counter

    per_ds = Counter(g.dataset for g in groups)
    complete = [g for g in groups if len(g.files) == 8 and all(v > 0 for v in g.row_file_counts().values())]
    check("R5a 组总数", 111, len(groups))
    check("R5b 分数据集组数", {
        "附件2-测距数据/金属板数据": 20,
        "附件2-测距数据/墙体数据": 20,
        "附件2-测距数据/空场数据": 10,
        "附件3-成像数据/墙体": 33,
        "附件3-成像数据/金属柱和金属铲": 28,
    }, dict(sorted(per_ds.items())))
    check("R5c 完整组数", 110, len(complete))
    check("R5d 扫描问题", 0, len(scan_problems))

    # R6 与 R0 清单对账（SHA256 + 文件数 + 总字节）
    manifest = HERE.parents[1] / "recon" / "manifests" / "a_dat_manifest.csv"
    if manifest.exists():
        with manifest.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        by_path = {r["rel_path"]: r for r in rows}
        rel = str(ref1.files[0].relative_to(root)).replace("\\", "/")
        check("R6a 清单文件数", 881, len(rows))
        check("R6b 清单总字节", 801111612, sum(int(r["size_bytes"]) for r in rows))
        check("R6c 单文件 SHA256 对账", g1.meta["row_files"]["0"]["sha256"], by_path.get(rel, {}).get("sha256"))
    else:
        skip("R6 与 R0 清单对账", "缺少 %s" % manifest)


# ---------------------------------------------------------------- 入口
def _make_tmpdir() -> Path:
    """优先生成系统临时目录；受限沙箱不允许写入时退到当前工作目录（结束时删除）。"""
    try:
        d = Path(tempfile.mkdtemp(prefix="d0_reader_"))
        probe = d / ".write_probe"
        probe.write_bytes(b"1")
        probe.unlink()
        return d
    except OSError:
        pass
    fallback = Path.cwd() / "_d0_reader_tmp"
    if fallback.exists():
        shutil.rmtree(fallback, ignore_errors=True)
    fallback.mkdir(parents=True)
    return fallback


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    want_real = "--no-real" not in argv
    root = R._default_root()
    print("== D0 读取器测试 ==")
    print("读取器: %s" % (HERE / "a_dat_reader.py"))
    print("真实数据根: %s" % root)
    tmp = _make_tmpdir()
    try:
        synthetic_tests(tmp)
        if want_real:
            if root.is_dir():
                try:
                    real_tests(root)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    RESULTS.append({"name": "real_tests", "status": "FAIL", "expected": "无异常", "actual": traceback.format_exc(limit=2)})
            else:
                skip("真实组测试", "数据根不存在: %s" % root)
        else:
            skip("真实组测试", "--no-real")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    n_skip = sum(1 for r in RESULTS if r["status"] == "SKIP")
    print("\n== 汇总: %d passed, %d failed, %d skipped ==" % (n_pass, n_fail, n_skip))
    if n_fail:
        for r in RESULTS:
            if r["status"] == "FAIL":
                print("FAIL: %s expected=%r actual=%r" % (r["name"], r["expected"], r["actual"]))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
