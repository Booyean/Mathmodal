#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 题 D0 原始 ``.dat`` 读取器（读取 / 配对 / 体检，不含任何估计）。

职责边界（D0，A-Q1-PLAN）
  * 只做：二进制协议解析、8 行 x 8 列 -> 64 路展平映射、63 路接收掩码、
    按组内 8 个文件的共同 ``sync_packet_cnt`` 配对、异常记录、int16 端点统计。
  * **不做**：16000 点按 Np=4000 折迭、跨包/跨行一致性门控、校准、直射波抑制、
    测距、任何相位或频谱处理。这些属于后续已批复的预处理/求解阶段。
  * 只读 ``竞赛题目/`` 下的原件，不写入、不复制、不改名。

协议依据
  ``附件1-数据读取函数/get_data_iq.m``（同版本原件），逐字节复刻其行为：
      magic(u32 LE, =963072) -> total_len(u32) -> type(u32)
        type != 102 : 跳过 total_len - 4 字节后继续向后找 magic
        type == 102 : freq(float32) -> sync(u32) -> num(u32) -> len(u32)
                      -> num*len/2 个 int16（按采样时刻交织，每时刻 8 路）
  MATLAB: ``data = fread(fid, num*len/2, 'int16'); reshape(data, 8, [])``
  即**固定 8 行**、列数 = (num*len/2)/8。等价 numpy：
  ``arr.reshape(n_samples, 8).T`` -> (8, n_samples)。
  实测头部字段 num=16000、len=16（8 通道 x 2 字节），故 n_samples=16000。

  ``freq`` 原样保留（float32 值与原始位型都保留），读取器不解释其物理含义；
  采样率/周期长度不是文件头字段，由 ``FS_HZ``/``N_PERIOD_SAMPLES`` 单独配置。

公开接口
  * ``discover_groups(root)`` -> (GroupRef 列表, 扫描问题列表)
  * ``find_group(root, group_key)``
  * ``read_dat(path)`` -> DatFile（包列表、异常、每个包的 (8, N) int16 矩阵）
  * ``load_group(ref, ...)`` -> GroupData（packets/sync/rx_mask/channel_valid/
    positions_m/meta）
  * ``channel_positions()`` -> (64, 3) 几何坐标（**依 M0 §2.1 提案，待 A-Q1-M0 批复**）

命令行
  python solutions/A/a_dat_reader.py --list-groups
  python solutions/A/a_dat_reader.py --inspect "<group_key>"
  python solutions/A/a_dat_reader.py --verify-all
  可选：--root <A 题目录> --json <输出文件> --max-packets N --allow-incomplete

输出契约（字段、类型、单位、缺失规则、未知项）见 ``solutions/A/data_contract.md``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------- 常量（协议 + 题面配置）
MAGIC = 963072
TYPE_DATA = 102
HEADER_BYTES = 28  # magic+total_len+type+freq+sync+num+len = 7 x u32
N_CHANNELS_PER_FILE = 8
N_ROWS = 8
N_COLS = 8
N_CHANNELS = 64
TX_IDX = 27   # 发射通道: 第 4 行第 4 列 (0-based row=3, col=3)
REF_IDX = 28  # 参考通道: 第 4 行第 5 列 (0-based row=3, col=4)
SAMPLES_PER_PACKET = 16000

# 题面补充说明给出的采样配置（不是 .dat 文件头字段，故单独配置，可被调用方覆盖）
FS_HZ = 4.0e9
TS_S = 1.0 / FS_HZ          # 0.25 ns
N_PERIOD_SAMPLES = 4000     # Np，单扫频周期点数；D0 不做折迭

INT16_POS_MAX = 32767
INT16_NEG_MIN = -32768
INT16_MASK = 0xFFFFFFFF

CONTRACT_VERSION = "D0-2"

_ROW_FILE_RE = re.compile(r"^(?P<prefix>.+)_(?P<row>[0-7])\.dat$", re.IGNORECASE)
_GROUP_DIR_RE = re.compile(r"^data\d+(?:-\d+cm)?$", re.IGNORECASE)
_A_QUESTION_DIRNAME = "A 题：单发多收下的雷达信号处理及成像问题"


class DatFormatError(ValueError):
    """文件层面无法继续解析时抛出（仅用于 read_dat 的调用方显式要求严格模式）。"""


class IncompleteGroupError(ValueError):
    """组内缺少行文件 / 行文件无有效包，且调用方要求 8 行齐全时抛出。"""

    def __init__(self, group_key: str, missing_rows: Sequence[int], empty_rows: Sequence[int], detail: str = ""):
        self.group_key = group_key
        self.missing_rows = list(missing_rows)
        self.empty_rows = list(empty_rows)
        msg = "group %r 不完整: missing_rows=%s empty_rows=%s" % (
            group_key,
            self.missing_rows,
            self.empty_rows,
        )
        if detail:
            msg += " (%s)" % detail
        super().__init__(msg)


# ---------------------------------------------------------------- 基础结构
@dataclass
class Problem:
    code: str
    detail: str
    offset: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"code": self.code, "detail": self.detail}
        if self.offset is not None:
            d["offset"] = int(self.offset)
        return d


@dataclass
class PacketHeader:
    """一个采样包的头部与定位信息（数据本身留在文件缓冲区里）。"""

    index: int          # 文件内数据包序号，0-based
    offset: int         # 包头起始字节
    total_len: int      # 头部 total_len 字段原值
    ptype: int          # type 字段原值
    freq: float         # freq(float32) 原值，读取器不解释
    freq_bits: int      # freq 的原始 32 位位型，便于"原样保留"
    sync: int           # sync_packet_cnt 原值
    num: int            # 头部 num 字段原值
    length: int         # 头部 len 字段原值（字节/采样时刻）
    n_channels: int     # 固定 8（MATLAB reshape(...,8,[]) 语义）
    n_samples: int      # 每通道采样点数 = (num*len/2)/8
    data_offset: int
    data_bytes: int
    header_ok: bool     # total_len == 20 + data_bytes（实测成立）

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "offset": self.offset,
            "total_len": self.total_len,
            "type": self.ptype,
            "freq": self.freq,
            "freq_bits": self.freq_bits,
            "sync": self.sync,
            "num": self.num,
            "len": self.length,
            "n_channels": self.n_channels,
            "n_samples": self.n_samples,
            "header_ok": self.header_ok,
        }


@dataclass
class DatFile:
    path: Path
    size_bytes: int
    sha256: str
    packets: List[PacketHeader]
    problems: List[Problem]
    skipped_bytes: int
    trailing_bytes: int
    _buf: bytes = field(repr=False, default=b"")

    def packet_matrix(self, i: int) -> np.ndarray:
        """第 i 个包 -> (8, n_samples) int16，按 MATLAB ``reshape(data,8,[])`` 语义。"""
        p = self.packets[i]
        arr = np.frombuffer(self._buf, dtype="<i2", count=p.data_bytes // 2, offset=p.data_offset)
        return arr.reshape(p.n_samples, N_CHANNELS_PER_FILE).T.copy()

    def packet_int32(self, i: int) -> np.ndarray:
        """升位后的 (8, n_samples) int32；做 ``abs``/极值比较前必须用这个。"""
        return self.packet_matrix(i).astype(np.int32)

    def syncs(self) -> List[int]:
        return [p.sync for p in self.packets]

    def endpoint_counts(self) -> Dict[str, int]:
        """全文件所有包的 int16 端点计数（int32 升位，``== +32767`` / ``== -32768``）。"""
        pos = neg = zero = n = 0
        for i, p in enumerate(self.packets):
            m = self.packet_int32(i)
            n += int(m.size)
            pos += int(np.count_nonzero(m == INT16_POS_MAX))
            neg += int(np.count_nonzero(m == INT16_NEG_MIN))
            zero += int(np.count_nonzero(m == 0))
        return {"pos_32767": pos, "neg_32768": neg, "zero": zero, "n_samples": n}


@dataclass
class GroupRef:
    root: Path
    dir_rel: str          # .dat 所在目录（相对 root）
    prefix: str           # 采集时间戳前缀，如 2026-11-12-20-50-32_16000
    dataset: str          # 数据集，如 附件2-测距数据/墙体数据
    name: str             # 组名：组目录名（data1-42cm）或时间戳前缀
    files: Dict[int, Path] = field(default_factory=dict)       # row -> path
    duplicate_rows: List[int] = field(default_factory=list)    # 同一行出现多个文件

    @property
    def group_key(self) -> str:
        return "%s/%s" % (self.dataset, self.name)

    def missing_rows(self) -> List[int]:
        return [r for r in range(N_ROWS) if r not in self.files]

    def row_file_counts(self) -> Dict[int, int]:
        """行号 -> 文件字节数（只做存在性/空文件检查用）。"""
        return {r: p.stat().st_size for r, p in sorted(self.files.items())}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "group_key": self.group_key,
            "dataset": self.dataset,
            "name": self.name,
            "dir_rel": self.dir_rel,
            "prefix": self.prefix,
            "n_files": len(self.files),
            "missing_rows": self.missing_rows(),
            "duplicate_rows": list(self.duplicate_rows),
            "file_sizes": {str(k): v for k, v in self.row_file_counts().items()},
        }


@dataclass
class GroupData:
    ref: GroupRef
    packets: np.ndarray        # int16 (P, 64, SAMPLES_PER_PACKET)
    sync: np.ndarray           # int64 (P,)
    rx_mask: np.ndarray        # bool (64,)
    channel_valid: np.ndarray  # bool (64,)
    positions_m: np.ndarray    # float64 (64, 3)
    meta: Dict[str, Any]

    def packets_int32(self) -> np.ndarray:
        """整组升位到 int32；比较/求绝对值前必须使用。"""
        return self.packets.astype(np.int32)

    def channel(self, pi: int, ci: int) -> np.ndarray:
        _check_index("channel index", ci, N_CHANNELS)
        return self.packets[pi, ci, :]

    @property
    def group_key(self) -> str:
        return self.ref.group_key


def _check_index(what: str, value: int, limit: int) -> None:
    if not (0 <= int(value) < int(limit)):
        raise IndexError("%s out of range: %r (expected 0..%d)" % (what, value, limit - 1))


# ---------------------------------------------------------------- 解析
def parse_bytes(buf: bytes) -> Tuple[List[PacketHeader], List[Problem], int, int]:
    """按 get_data_iq.m 逐包解析字节流。

    返回 ``(packets, problems, skipped_bytes, trailing_bytes)``。
    ``skipped_bytes`` 为非 magic 前导/间隙字节总数，``trailing_bytes`` 为包序列结束后的
    未解释字节数；两者都为 0 表示字节流被完全消费。
    """
    n = len(buf)
    pos = 0
    packets: List[PacketHeader] = []
    problems: List[Problem] = []
    gaps: List[Tuple[int, int]] = []  # 非 magic 的字节区间，用于区分"跳过"与"尾部残留"
    pkt_counter = 0

    while pos + 4 <= n:
        magic = struct.unpack_from("<I", buf, pos)[0]
        if magic != MAGIC:
            nxt = buf.find(struct.pack("<I", MAGIC), pos + 1)
            end = n if nxt < 0 else nxt
            gaps.append((pos, end))
            if nxt < 0:
                pos = n
                break
            pos = nxt
            continue

        if pos + 12 > n:
            problems.append(Problem("truncated_header", "文件在包头前 12 字节处结束", pos))
            pos = n
            break

        total_len, ptype = struct.unpack_from("<II", buf, pos + 4)
        if ptype != TYPE_DATA:
            problems.append(Problem("non_data_packet", "type=%d，按 .m 跳过 total_len-4=%d 字节" % (ptype, total_len - 4), pos))
            skip = total_len - 4
            if skip < 0 or pos + 12 + skip > n:
                problems.append(Problem("bad_skip", "total_len=%d 无法在文件内跳过" % total_len, pos))
                pos = n
                break
            pos += 12 + skip
            continue

        if pos + HEADER_BYTES > n:
            problems.append(Problem("truncated_packet_header", "数据包头不足 28 字节", pos))
            pos = n
            break

        freq, sync, num, length = struct.unpack_from("<fIII", buf, pos + 12)
        n_values = (int(num) * int(length)) // 2
        data_offset = pos + HEADER_BYTES
        data_bytes = int(num) * int(length)

        if n_values <= 0 or data_bytes <= 0:
            problems.append(Problem("zero_length_packet", "num=%d len=%d" % (num, length), pos))
            pos = data_offset
            continue
        if data_offset + data_bytes > n:
            # 先判截断：否则 num*len/2 同时不是 8 的倍数时会被误记为
            # sample_count_not_multiple_of_8 并静默跳过文件尾部。
            problems.append(
                Problem(
                    "truncated_samples",
                    "需要 %d 字节，剩余 %d 字节" % (data_bytes, n - data_offset),
                    pos,
                )
            )
            pos = n
            break
        if n_values % N_CHANNELS_PER_FILE != 0:
            # MATLAB reshape(data, 8, []) 会直接报错，这里记录并跳过该包
            problems.append(
                Problem("sample_count_not_multiple_of_8", "num*len/2=%d 不是 8 的整数倍" % n_values, pos)
            )
            pos = data_offset + data_bytes
            continue

        packets.append(
            PacketHeader(
                index=pkt_counter,
                offset=pos,
                total_len=int(total_len),
                ptype=int(ptype),
                freq=float(freq),
                freq_bits=struct.unpack_from("<I", buf, pos + 12)[0],
                sync=int(sync),
                num=int(num),
                length=int(length),
                n_channels=N_CHANNELS_PER_FILE,
                n_samples=n_values // N_CHANNELS_PER_FILE,
                data_offset=data_offset,
                data_bytes=data_bytes,
                header_ok=(int(total_len) == 20 + data_bytes),
            )
        )
        pkt_counter += 1
        pos = data_offset + data_bytes

    data_end = (packets[-1].data_offset + packets[-1].data_bytes) if packets else 0
    trailing = n - data_end
    # 只统计数据包序列范围内的间隙；最后一个包之后的字节算作 trailing，不重复计入 skipped
    skipped = sum(max(0, min(e, data_end) - s) for s, e in gaps)
    if packets and any(not p.header_ok for p in packets):
        problems.append(Problem("header_len_mismatch", "有包头 total_len != 20 + 采样字节数"))
    return packets, problems, skipped, trailing


def read_dat(path: os.PathLike, compute_sha256: bool = True) -> DatFile:
    """读一个 .dat 文件并解析全部数据包；文件级异常记录在 ``problems`` 里，不抛异常。"""
    p = Path(path)
    size = p.stat().st_size
    if size == 0:
        return DatFile(
            path=p,
            size_bytes=0,
            sha256=hashlib.sha256(b"").hexdigest() if compute_sha256 else "",
            packets=[],
            problems=[Problem("empty_file", "文件长度为 0 字节")],
            skipped_bytes=0,
            trailing_bytes=0,
            _buf=b"",
        )
    buf = p.read_bytes()
    digest = hashlib.sha256(buf).hexdigest() if compute_sha256 else ""
    packets, problems, skipped, trailing = parse_bytes(buf)
    if not packets and not any(pr.code in ("empty_file",) for pr in problems):
        problems.append(Problem("no_data_packet", "未解析出任何 type=102 的采样包"))
    if trailing:
        problems.append(Problem("trailing_bytes", "包序列之后还有 %d 字节" % trailing, size - trailing))
    return DatFile(
        path=p,
        size_bytes=size,
        sha256=digest,
        packets=packets,
        problems=problems,
        skipped_bytes=skipped,
        trailing_bytes=trailing,
        _buf=buf,
    )


# ---------------------------------------------------------------- 分组发现
def _split_dataset(dir_rel: str) -> Tuple[str, Optional[str]]:
    """目录 -> (dataset, 组名或 None)。

    规则：若最后一级目录名形如 ``data12`` / ``data1-42cm``，它就是一个测量组目录，
    组名取它、dataset 取父目录；否则该目录本身是 dataset，组名留给时间戳前缀。
    最外层名为 ``附件`` 的目录只作容器，不进入 dataset 名。
    """
    parts = [x for x in dir_rel.replace("\\", "/").split("/") if x not in ("", ".")]
    if parts and _GROUP_DIR_RE.match(parts[-1]):
        name = parts[-1]
        dataset_parts = parts[:-1]
    else:
        name = None
        dataset_parts = parts
    if dataset_parts and dataset_parts[0] == "附件":
        dataset_parts = dataset_parts[1:]
    return "/".join(dataset_parts), name


def discover_groups(root: os.PathLike) -> Tuple[List[GroupRef], List[Problem]]:
    """扫描 root 下全部 .dat，按 (目录, 时间戳前缀) 归组。

    附件2 的组目录本身就是组；附件3 把多组放在同一目录，只能按文件名里的采集时间戳前缀
    区分（``2026-11-12-21-29-57_16000_0.dat`` -> prefix=``2026-11-12-21-29-57_16000``）。
    """
    root_p = Path(root)
    if not root_p.is_dir():
        raise FileNotFoundError("root 不是目录: %s" % root_p)

    problems: List[Problem] = []
    buckets: Dict[Tuple[str, str], Dict[int, Path]] = defaultdict(dict)
    duplicates: Dict[Tuple[str, str], List[int]] = defaultdict(list)

    for fp in sorted(root_p.rglob("*.dat")):
        m = _ROW_FILE_RE.match(fp.name)
        rel_dir = str(fp.parent.relative_to(root_p)).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        if not m:
            problems.append(Problem("unexpected_dat_name", "%s/%s" % (rel_dir, fp.name)))
            continue
        key = (rel_dir, m.group("prefix"))
        row = int(m.group("row"))
        if row in buckets[key]:
            duplicates[key].append(row)
            problems.append(
                Problem("duplicate_row_file", "%s/%s 与已有 row=%d 文件冲突，保留字典序第一个" % (rel_dir, fp.name, row))
            )
            continue
        buckets[key][row] = fp

    groups: List[GroupRef] = []
    for (rel_dir, prefix) in sorted(buckets):
        dataset, name = _split_dataset(rel_dir)
        groups.append(
            GroupRef(
                root=root_p,
                dir_rel=rel_dir,
                prefix=prefix,
                dataset=dataset,
                name=name if name is not None else prefix,
                files=dict(buckets[(rel_dir, prefix)]),
                duplicate_rows=list(duplicates[(rel_dir, prefix)]),
            )
        )
    return groups, problems


def find_group(root: os.PathLike, group_key: str) -> GroupRef:
    groups, _ = discover_groups(root)
    norm = group_key.replace("\\", "/").strip("/")
    hits = [g for g in groups if g.group_key == norm]
    if not hits:
        hits = [g for g in groups if g.group_key.endswith("/" + norm) or g.name == norm]
    if not hits:
        raise KeyError("找不到组 %r（用 --list-groups 查看全部 group_key）" % group_key)
    if len(hits) > 1:
        keys = ", ".join(g.group_key for g in hits)
        raise KeyError("组名 %r 不唯一：%s" % (group_key, keys))
    return hits[0]


# ---------------------------------------------------------------- 几何（M0 §2.1，待批复）
def channel_positions() -> np.ndarray:
    """(64, 3) 阵元坐标，单位 m。

    依 M0 §2.1 提案：z_r=(75.5-7(r-1))cm，奇行 c_grid=2k-1、偶行 c_grid=2k，
    x=(8-c_grid)*0.035 m，阵列在 y=0 平面，+x 指向第 1 列移动前端。
    **该公式属 A-Q1-M0（待审）**；若批复修改，此函数与 ``positions_m`` 需同步更新，
    D0 的读取/配对结果不受影响。
    """
    pos = np.zeros((N_CHANNELS, 3), dtype=np.float64)
    for r in range(1, N_ROWS + 1):
        z = (75.5 - 7.0 * (r - 1)) * 1e-2
        for k in range(1, N_COLS + 1):
            c_grid = (2 * k - 1) if (r % 2 == 1) else (2 * k)
            x = (8.0 - c_grid) * 0.035
            idx = N_CHANNELS_PER_FILE * (r - 1) + (k - 1)
            pos[idx] = (x, 0.0, z)
    return pos


# ---------------------------------------------------------------- 组装载
def _row_stats(df: DatFile, used: Sequence[int], dropped: Sequence[int]) -> Dict[str, Any]:
    ep = df.endpoint_counts()
    return {
        "file": df.path.name,
        "size_bytes": df.size_bytes,
        "sha256": df.sha256,
        "n_packets_total": len(df.packets),
        "syncs_total": [int(p.sync) for p in df.packets],
        "n_packets_used": len(used),
        "syncs_used": [int(s) for s in used],
        "syncs_dropped_not_in_intersection": [int(s) for s in dropped],
        "freq_values": sorted({float(p.freq) for p in df.packets}),
        "endpoint_counts_all_packets": ep,
        "problems": [pr.as_dict() for pr in df.problems],
        "skipped_bytes": df.skipped_bytes,
        "trailing_bytes": df.trailing_bytes,
    }


def load_group(
    ref: GroupRef,
    *,
    max_packets: Optional[int] = None,
    require_all_rows: bool = True,
    compute_sha256: bool = True,
) -> GroupData:
    """按共同 ``sync`` 配对装载一个测量组，输出 D0 契约的数组与 meta。

    参数
      max_packets     只保留共同 ``sync`` 排序后的前 N 个包（None=全部；用于快速抽检）。
      require_all_rows
                      True（默认）：8 个行文件必须齐全且各有 ≥1 个可解析包，
                      否则抛 ``IncompleteGroupError``，避免用 0 填充"伪造"缺行数据。
                      False：允许缺行，缺失通道在 ``packets`` 中置 0 且
                      ``channel_valid`` 为 False（meta 明确记录）。
      compute_sha256  是否对每个文件计算 SHA256（默认是；用于版本锚定）。
    """
    group_key = ref.group_key
    rows: Dict[int, DatFile] = {}
    missing_rows: List[int] = []
    empty_rows: List[int] = []
    unreadable_rows: List[int] = []

    for r in range(N_ROWS):
        fp = ref.files.get(r)
        if fp is None:
            missing_rows.append(r)
            continue
        try:
            rows[r] = read_dat(fp, compute_sha256=compute_sha256)
        except OSError as exc:  # 读不动/权限/设备问题
            unreadable_rows.append(r)
            try:
                bad_size = fp.stat().st_size
            except OSError:
                bad_size = 0
            rows[r] = DatFile(
                path=fp,
                size_bytes=bad_size,
                sha256="",
                packets=[],
                problems=[Problem("read_error", str(exc))],
                skipped_bytes=0,
                trailing_bytes=0,
                _buf=b"",
            )
            continue
        if not rows[r].packets:
            empty_rows.append(r)

    if (missing_rows or empty_rows or unreadable_rows) and require_all_rows:
        raise IncompleteGroupError(
            group_key,
            missing_rows,
            sorted(set(empty_rows + unreadable_rows)),
            "require_all_rows=True：缺行/空行不得用 0 填充，请在 meta 中登记后另行处理",
        )

    usable_rows = [r for r in range(N_ROWS) if r in rows and rows[r].packets]
    if not usable_rows:
        raise IncompleteGroupError(group_key, missing_rows, sorted(set(empty_rows + unreadable_rows)), "没有任何可用行文件")

    # ---- 包筛选：只接受 D0 契约形状（8 x 16000）的包参与配对
    excluded: List[Dict[str, Any]] = []
    per_row_packets: Dict[int, Dict[int, PacketHeader]] = {}
    per_row_syncs: Dict[int, List[int]] = {}
    for r in usable_rows:
        df = rows[r]
        by_sync: Dict[int, PacketHeader] = {}
        ordered: List[int] = []
        for p in df.packets:
            if p.n_samples != SAMPLES_PER_PACKET:
                excluded.append(
                    {"row": r, "sync": int(p.sync), "reason": "samples_per_packet_mismatch", "n_samples": int(p.n_samples)}
                )
                continue
            if p.sync in by_sync:
                excluded.append({"row": r, "sync": int(p.sync), "reason": "duplicate_sync_in_file"})
                continue
            by_sync[p.sync] = p
            ordered.append(int(p.sync))
        per_row_packets[r] = by_sync
        per_row_syncs[r] = ordered

    common: List[int] = []
    if all(per_row_syncs[r] for r in usable_rows):
        sets = [set(per_row_syncs[r]) for r in usable_rows]
        common = sorted(set.intersection(*sets))
    if max_packets is not None:
        common = common[: int(max_packets)]

    P = len(common)
    packets = np.zeros((P, N_CHANNELS, SAMPLES_PER_PACKET), dtype=np.int16)
    for pi, sync in enumerate(common):
        for r in usable_rows:
            p = per_row_packets[r].get(sync)
            if p is None:
                continue
            packets[pi, N_CHANNELS_PER_FILE * r : N_CHANNELS_PER_FILE * (r + 1), :] = rows[r].packet_matrix(p.index)

    row_ok = np.zeros(N_ROWS, dtype=bool)
    for r in usable_rows:
        row_ok[r] = True
    if not require_all_rows:
        # 缺行/空行的通道标记为无效，避免下游把 0 当真实样本
        for r in range(N_ROWS):
            if r not in usable_rows:
                row_ok[r] = False
    channel_valid = np.repeat(row_ok, N_CHANNELS_PER_FILE)

    rx_mask = np.ones(N_CHANNELS, dtype=bool)
    rx_mask[TX_IDX] = False

    p32 = packets.astype(np.int32) if P else np.zeros((0, N_CHANNELS, SAMPLES_PER_PACKET), dtype=np.int32)
    if P:
        neg_total = int(np.count_nonzero(p32 == INT16_NEG_MIN))
        pos_total = int(np.count_nonzero(p32 == INT16_POS_MAX))
        zero_total = int(np.count_nonzero(p32 == 0))
        per_ch_neg = np.count_nonzero(p32 == INT16_NEG_MIN, axis=(0, 2)).astype(np.int64).tolist()
        per_ch_pos = np.count_nonzero(p32 == INT16_POS_MAX, axis=(0, 2)).astype(np.int64).tolist()
    else:
        neg_total = pos_total = zero_total = 0
        per_ch_neg = [0] * N_CHANNELS
        per_ch_pos = [0] * N_CHANNELS

    row_meta: Dict[str, Any] = {}
    for r in range(N_ROWS):
        if r in rows:
            used = [s for s in per_row_syncs.get(r, []) if s in common]
            dropped = [s for s in per_row_syncs.get(r, []) if s not in common]
            row_meta[str(r)] = _row_stats(rows[r], used, dropped)

    all_pos = sum(row_meta[str(r)]["endpoint_counts_all_packets"]["pos_32767"] for r in row_meta)
    all_neg = sum(row_meta[str(r)]["endpoint_counts_all_packets"]["neg_32768"] for r in row_meta)
    all_zero = sum(row_meta[str(r)]["endpoint_counts_all_packets"]["zero"] for r in row_meta)
    all_n = sum(row_meta[str(r)]["endpoint_counts_all_packets"]["n_samples"] for r in row_meta)

    meta: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "group_key": group_key,
        "dataset": ref.dataset,
        "name": ref.name,
        "dir_rel": ref.dir_rel,
        "prefix": ref.prefix,
        "n_files_expected": N_ROWS,
        "n_files_used": len(usable_rows),
        "missing_rows": missing_rows,
        "empty_or_unreadable_rows": sorted(set(empty_rows + unreadable_rows)),
        "duplicate_row_files": list(ref.duplicate_rows),
        "row_files": row_meta,
        "sync_common": [int(s) for s in common],
        "n_packets": int(P),
        "n_channels": N_CHANNELS,
        "samples_per_packet": SAMPLES_PER_PACKET,
        "n_period_samples": N_PERIOD_SAMPLES,
        "fs_hz": FS_HZ,
        "ts_s": TS_S,
        "tx_idx": TX_IDX,
        "ref_idx": REF_IDX,
        "rx_mask_true_count": int(rx_mask.sum()),
        "excluded_packets": excluded,
        "problems": [pr.as_dict() for pr in ref_extra_problems(ref)],
        "extremes": {
            "criterion": "int32 升位后 == +32767 / == -32768（不用 |x|>=32767，避免把 -32767 误计）",
            "scope": "全部共同包 x 64 通道（含发射通道，仅统计不参与接收处理）",
            "n_packets": int(P),
            "n_samples": int(p32.size),
            "pos_32767": pos_total,
            "neg_32768": neg_total,
            "zero": zero_total,
            "per_channel_pos_32767": per_ch_pos,
            "per_channel_neg_32768": per_ch_neg,
            "all_packets_in_group": {
                "note": "组内 8 个文件**全部包**（含未进入共同 sync 交集的包）的合计，用于与 R0 清单对账；不等于上面的共同包口径",
                "pos_32767": int(all_pos),
                "neg_32768": int(all_neg),
                "zero": int(all_zero),
                "n_samples": int(all_n),
            },
        },
        "positions_source": "M0 §2.1（A-Q1-M0 待批复）；仅几何辅助，不影响读取/配对",
    }

    return GroupData(
        ref=ref,
        packets=packets,
        sync=np.asarray(common, dtype=np.int64),
        rx_mask=rx_mask,
        channel_valid=channel_valid,
        positions_m=channel_positions(),
        meta=meta,
    )


def ref_extra_problems(ref: GroupRef) -> List[Problem]:
    """组级问题：重复行文件（行内包级异常记录在 meta["row_files"][r]["problems"]）。"""
    out: List[Problem] = []
    for r in ref.duplicate_rows:
        out.append(Problem("duplicate_row_file", "row=%d 存在多个文件，已保留字典序第一个" % r))
    return out


# ---------------------------------------------------------------- 命令行
def _default_root() -> Path:
    return Path(__file__).resolve().parents[2] / "竞赛题目" / _A_QUESTION_DIRNAME


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    return obj


def cmd_list_groups(root: Path) -> Dict[str, Any]:
    groups, problems = discover_groups(root)
    rows = []
    by_dataset: Dict[str, Dict[str, int]] = defaultdict(lambda: {"groups": 0, "complete": 0, "incomplete": 0, "zero_byte_files": 0})
    for g in groups:
        sizes = g.row_file_counts()
        zero = sum(1 for v in sizes.values() if v == 0)
        complete = (len(g.files) == N_ROWS) and zero == 0
        rows.append(
            {
                "group_key": g.group_key,
                "dir_rel": g.dir_rel,
                "prefix": g.prefix,
                "n_files": len(g.files),
                "missing_rows": g.missing_rows(),
                "zero_byte_rows": sorted(r for r, v in sizes.items() if v == 0),
                "complete_8_rows": complete,
            }
        )
        b = by_dataset[g.dataset]
        b["groups"] += 1
        b["complete" if complete else "incomplete"] += 1
        b["zero_byte_files"] += zero
    out = {
        "root": str(root),
        "n_groups": len(groups),
        "n_complete": sum(1 for r in rows if r["complete_8_rows"]),
        "by_dataset": dict(by_dataset),
        "groups": rows,
        "scan_problems": [p.as_dict() for p in problems],
    }
    return out


def cmd_inspect(root: Path, key: str, max_packets: Optional[int], allow_incomplete: bool) -> Dict[str, Any]:
    ref = find_group(root, key)
    try:
        gd = load_group(ref, max_packets=max_packets, require_all_rows=not allow_incomplete)
    except IncompleteGroupError as exc:
        return {
            "group_key": ref.group_key,
            "error": "IncompleteGroupError",
            "message": str(exc),
            "missing_rows": exc.missing_rows,
            "empty_rows": exc.empty_rows,
            "group": ref.as_dict(),
        }
    return gd.meta


def cmd_verify_all(root: Path) -> Dict[str, Any]:
    """逐组只做配对体检（不保留数组、不做任何估计），用于全量可读性核对。"""
    groups, scan_problems = discover_groups(root)
    rows = []
    for g in groups:
        try:
            gd = load_group(g)
            m = gd.meta
            rows.append(
                {
                    "group_key": g.group_key,
                    "n_packets": m["n_packets"],
                    "sync_common": m["sync_common"],
                    "excluded_packets": len(m["excluded_packets"]),
                    "problems": [p["code"] for p in m["problems"]],
                }
            )
            del gd
        except IncompleteGroupError as exc:
            rows.append(
                {
                    "group_key": g.group_key,
                    "error": "IncompleteGroupError",
                    "missing_rows": exc.missing_rows,
                    "empty_rows": exc.empty_rows,
                }
            )
    return {
        "root": str(root),
        "n_groups": len(groups),
        "n_ok": sum(1 for r in rows if "error" not in r),
        "n_incomplete": sum(1 for r in rows if "error" in r),
        "scan_problems": [p.as_dict() for p in scan_problems],
        "groups": rows,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="A 题 D0 原始 .dat 读取器（只读，不做折叠/校准/测距）")
    ap.add_argument("--root", default=str(_default_root()), help="A 题目录（含 附件/）")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-groups", action="store_true", help="列出全部测量组与完整性")
    mode.add_argument("--inspect", metavar="GROUP_KEY", help="装载一个组并输出 meta JSON")
    mode.add_argument("--verify-all", action="store_true", help="逐组做共同 sync 配对体检")
    ap.add_argument("--json", metavar="PATH", help="把结果写入 JSON 文件（默认打印到 stdout）")
    ap.add_argument("--max-packets", type=int, default=None, help="--inspect 时只保留前 N 个共同包")
    ap.add_argument("--allow-incomplete", action="store_true", help="--inspect 时允许缺行（缺失通道标记无效）")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if args.list_groups:
        result = cmd_list_groups(root)
    elif args.verify_all:
        result = cmd_verify_all(root)
    else:
        result = cmd_inspect(root, args.inspect, args.max_packets, args.allow_incomplete)

    payload = json.dumps(_json_ready(result), ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(payload + "\n", encoding="utf-8")
        print("已写入 %s（%d 字节）" % (args.json, len(payload)))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
