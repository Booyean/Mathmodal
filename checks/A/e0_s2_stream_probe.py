#!/usr/bin/env python
"""A-Q1-E0-S2 随机流 oracle 探针（E0-PREREG-2）。

用途
----
不导入任何生产 E0 代码，只按 `coordination/A_Q1_E0_S_DECISION.md` 已裁定的
调用顺序，用 numpy 独立重建 `E0-S2` 的整条随机流：

1. 62 路通道参数（rx=0..63 去掉 tx=27、ref=28；每路依次抽
   `delta_tau_s`、`gain_mag`、`psi0_rad`、`psi2_u2_rad`）；
2. 11 个 `Uniform(0, T_p)` 触发偏移，依次为 `air_1`..`air_9`、
   目标 `0.42 m`、目标 `0.69 m`（`air_0` 固定 `120.25 T_s`，不消耗随机数）；
3. 12 个 `standard_normal((63, 4000))` 噪声矩阵，依次为
   `air_0`..`air_9`、目标 `0.42 m`、目标 `0.69 m`。

触发偏移以**无量纲分位数 `u`** 登记，因而与实现采用“秒 / 纳秒 / 样点”哪种
单位无关；由 `u` 可唯一还原实现侧的偏移。噪声矩阵的 SHA256 依赖 numpy 的
`Generator` 流，故与生成环境的 numpy 版本绑定（本仓库参考环境
CPython 3.11.5 / numpy 1.26.4）；若实现记录的 numpy 版本不同，见
`checks/A/e0_s1s2_prereg.md` 的 P17 处理规则。

用法
----
    python checks/A/e0_s2_stream_probe.py                     # 打印 oracle
    python checks/A/e0_s2_stream_probe.py --check             # 自检 + 与 oracle JSON 比对
    python checks/A/e0_s2_stream_probe.py --json-out out.json # 写出 oracle
    python checks/A/e0_s2_stream_probe.py --params impl_params.json \
        --offsets impl_offsets.json --offset-units samples \
        --noise impl_noise.npz [--noise-sigma impl_sigma.json]

退出码：0 全部通过；1 有差异；2 仅有“环境条件”提示（例如 numpy 版本不同
导致噪声矩阵 SHA 不同，且实现未提供可重算的同版本证据）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ORACLE_PATH = HERE / "e0_s2_stream_oracle.json"

SEED = 20261128
TP_SAMPLES = 4000.0          # T_p = 1000 ns, T_s = 0.25 ns
N_RX = 63
N_SAMPLES = 4000
RX_IDX = [i for i in range(64) if i not in (27, 28)]

EXPECTED_TABLE_SHA256 = (
    "aa86bf56fb138789cd0ad4375691293e7d0e5d65a2daf678d151d44720576e96")
OFFSET_LABELS = ([f"air_{i}" for i in range(1, 10)]
                 + ["E0-S2@0.42", "E0-S2@0.69"])
GROUP_ORDER = ([f"air_{i}" for i in range(10)]
               + ["E0-S2@0.42", "E0-S2@0.69"])
REFERENCE_ENV = {"python": "3.11.5", "numpy": "1.26.4"}
OFFSET_TOL = 2.0e-15


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical_json_sha256(obj) -> str:
    blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")
    return sha256_bytes(blob)


def build_table(rng: np.random.Generator) -> dict:
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


def expected_noise_matrices() -> dict[str, np.ndarray]:
    """按裁定顺序重建 12 个标准正态矩阵（原始、未乘 sigma）。"""
    rng = np.random.default_rng(SEED)
    build_table(rng)
    for _ in OFFSET_LABELS:
        rng.uniform(0.0, TP_SAMPLES)
    return {group: rng.standard_normal((N_RX, N_SAMPLES))
            for group in GROUP_ORDER}


def run_stream() -> dict:
    rng = np.random.default_rng(SEED)
    table = build_table(rng)
    table_sha = canonical_json_sha256(table)

    offsets = []
    for label in OFFSET_LABELS:
        v = float(rng.uniform(0.0, TP_SAMPLES))
        offsets.append({"label": label, "u": v / TP_SAMPLES,
                        "samples": v, "seconds": v * 0.25e-9})
    offset_sha = canonical_json_sha256([[o["label"], o["u"]] for o in offsets])

    noise = []
    concat = hashlib.sha256()
    for group in GROUP_ORDER:
        mat = rng.standard_normal((N_RX, N_SAMPLES))
        raw = np.ascontiguousarray(mat, dtype="<f8").tobytes(order="C")
        concat.update(raw)
        noise.append({"group": group, "sha256": sha256_bytes(raw),
                      "shape": list(mat.shape),
                      "first": float(mat[0, 0]), "last": float(mat[-1, -1])})

    return {
        "experiment": "A-Q1-E0-S2",
        "purpose": ("RNG stream oracle for E0-PREREG-2 (E0-S1/S2 independent "
                    "acceptance); rebuilds table -> 11 offsets -> 12 noise matrices"),
        "source_decision": {
            "path": "coordination/A_Q1_E0_S_DECISION.md",
            "commit": "2ba32107c3cb945a5c96001dd3760d5e3a0a5275",
            "sha256": ("ee2ed0f8d2e1885d5d1ca8cde84857f5"
                       "bc7130b6453b0d07f6ac12866cf21ff5"),
        },
        "environment": {"python": sys.version.split()[0],
                        "numpy": np.__version__},
        "table": {"sha256": table_sha, "rows": len(table["rows"])},
        "offsets": {"labels": OFFSET_LABELS,
                    "fraction_sha256": offset_sha,
                    "rows": offsets},
        "noise": {"group_order": GROUP_ORDER,
                  "matrix_shape": [N_RX, N_SAMPLES],
                  "concat_sha256": concat.hexdigest(),
                  "rows": noise},
    }


# --------------------------------------------------------------------------
# 与实现导出的对比
# --------------------------------------------------------------------------

def compare_params(path: Path) -> list[str]:
    got = json.loads(path.read_text(encoding="utf-8"))
    want = build_table(np.random.default_rng(SEED))
    errs: list[str] = []
    rows = got.get("rows")
    if not isinstance(rows, list) or len(rows) != len(want["rows"]):
        return [f"参数表行数不符：want {len(want['rows'])}，got "
                f"{len(rows) if isinstance(rows, list) else 'missing'}"]
    for a, b in zip(rows, want["rows"]):
        if not isinstance(a, list) or len(a) != 5 or int(a[0]) != int(b[0]):
            errs.append(f"参数表行格式/索引不符：{a!r} vs {b!r}")
            continue
        for j, name in enumerate(["delta_tau_s", "gain_mag", "psi0_rad",
                                  "psi2_u2_rad"], 1):
            if float(a[j]) != float(b[j]):
                errs.append(f"rx={int(a[0])} {name}: {float(a[j])!r} != {float(b[j])!r}")
    return errs


def _offset_values(payload) -> tuple[list[float], str | None]:
    """接受 list[float] 或 {"units": str, "values": [...]} 或 {label: value}。"""
    if isinstance(payload, list):
        return [float(v) for v in payload], None
    if isinstance(payload, dict):
        units = payload.get("units")
        if "values" in payload:
            return [float(v) for v in payload["values"]], units
        values = []
        for label in OFFSET_LABELS:
            if label not in payload:
                raise KeyError(f"偏移 JSON 缺少标签 {label!r}")
            values.append(float(payload[label]))
        return values, units
    raise TypeError("偏移 JSON 既不是数组也不是对象")


def to_fraction(values: list[float], units: str | None) -> list[float]:
    if units in (None, "u", "fraction"):
        return values
    scale = {"samples": TP_SAMPLES, "seconds": 1.0e-6, "ns": 1000.0,
             "s": 1.0e-6, "sample": TP_SAMPLES}.get(units)
    if scale is None:
        raise ValueError(f"未知偏移单位 {units!r}")
    return [v / scale for v in values]


def compare_offsets(path: Path, units: str | None) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values, declared = _offset_values(payload)
    if len(values) != len(OFFSET_LABELS):
        return [f"偏移数量不符：want {len(OFFSET_LABELS)}，got {len(values)}"]
    fracs = to_fraction(values, units or declared)
    want = run_stream()["offsets"]["rows"]
    errs: list[str] = []
    for label, got_u, row in zip(OFFSET_LABELS, fracs, want):
        if not (0.0 <= got_u <= 1.0):
            errs.append(f"{label}: u={got_u!r} 越界（单位声明可能错误）")
            continue
        if abs(got_u - row["u"]) > OFFSET_TOL:
            errs.append(f"{label}: u={got_u!r} != {row['u']!r} "
                        f"(Δ={got_u - row['u']:.3e})")
    return errs


def compare_noise(path: Path, sigma_path: Path | None) -> list[str]:
    data = np.load(path)
    sigma = {}
    if sigma_path is not None:
        sigma = json.loads(sigma_path.read_text(encoding="utf-8"))
    want = {row["group"]: row for row in run_stream()["noise"]["rows"]}
    want_mats = expected_noise_matrices() if sigma else {}
    errs: list[str] = []
    for group in GROUP_ORDER:
        key = group if group in data.files else group.replace("@", "_")
        if key not in data.files:
            errs.append(f"噪声 npz 缺少组 {group!r}（现有键：{data.files}）")
            continue
        arr = np.asarray(data[key])
        if arr.shape != (N_RX, N_SAMPLES):
            errs.append(f"{group}: shape {arr.shape} != {(N_RX, N_SAMPLES)}")
            continue
        if sigma:
            # 已按 sigma 缩放的导出：除回后按容差比对（乘除各一次舍入，最多数 ulp）。
            s = float(sigma[group])
            if not np.isfinite(s) or s <= 0:
                errs.append(f"{group}: sigma={s!r} 非法")
                continue
            diff = float(np.max(np.abs(np.asarray(arr / s, dtype=np.float64)
                                       - want_mats[group])))
            if diff > 2.0e-15:
                errs.append(f"{group}: 还原后与 oracle 最大绝对差 {diff:.3e} > 2e-15")
            continue
        raw = np.ascontiguousarray(arr, dtype="<f8").tobytes(order="C")
        got = sha256_bytes(raw)
        if got != want[group]["sha256"]:
            errs.append(f"{group}: noise sha256 {got[:16]}… != "
                        f"{want[group]['sha256'][:16]}…")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="与入库 oracle JSON 比对，并做同进程二次重建")
    ap.add_argument("--json-out", metavar="PATH", help="写出本次 oracle JSON")
    ap.add_argument("--params", metavar="PATH", help="实现导出的参数表 JSON")
    ap.add_argument("--offsets", metavar="PATH", help="实现导出的触发偏移 JSON")
    ap.add_argument("--offset-units", metavar="UNIT",
                    help="偏移单位：samples/seconds/ns/u（默认读 JSON 的 units 或按 u）")
    ap.add_argument("--noise", metavar="PATH",
                    help="实现导出的噪声矩阵 .npz（键为 air_0..air_9 与两个目标）")
    ap.add_argument("--noise-sigma", metavar="PATH",
                    help="按组噪声标准差的 JSON（若 npz 存的是已缩放噪声）")
    args = ap.parse_args(argv)

    stream = run_stream()
    print("参数表规范 SHA256        :", stream["table"]["sha256"])
    print("触发偏移分位数 SHA256    :", stream["offsets"]["fraction_sha256"])
    print("噪声矩阵连接 SHA256      :", stream["noise"]["concat_sha256"])
    print("环境                      : CPython %s / numpy %s"
          % (stream["environment"]["python"], stream["environment"]["numpy"]))

    print("\n触发偏移（u 无量纲 / 样点 / ns）：")
    for row in stream["offsets"]["rows"]:
        print("  %-12s u=%.17g  samples=%.17g  ns=%.17g"
              % (row["label"], row["u"], row["samples"], row["samples"] * 0.25))

    print("\n噪声矩阵（float64 C-order 原始字节）：")
    for row in stream["noise"]["rows"]:
        print("  %-12s %s" % (row["group"], row["sha256"]))

    status = 0
    if args.check:
        if not ORACLE_PATH.exists():
            print("[FAIL] 找不到 %s" % ORACLE_PATH)
            status = 1
        else:
            oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
            for key, got, label in [
                ("table", stream["table"]["sha256"], "参数表 SHA256"),
                ("offsets", stream["offsets"]["fraction_sha256"], "偏移分位数 SHA256"),
            ]:
                want = oracle[key]["sha256" if key == "table" else "fraction_sha256"]
                ok = got == want
                print("[%s] %s 与 oracle 一致" % ("PASS" if ok else "FAIL", label))
                status |= 0 if ok else 1
            again = run_stream()
            same = (again["offsets"]["fraction_sha256"]
                    == stream["offsets"]["fraction_sha256"]
                    and again["noise"]["concat_sha256"]
                    == stream["noise"]["concat_sha256"])
            print("[%s] 同进程二次重建逐位一致" % ("PASS" if same else "FAIL"))
            status |= 0 if same else 1
            if np.__version__ == REFERENCE_ENV["numpy"]:
                ok = (stream["noise"]["concat_sha256"]
                      == oracle["noise"]["concat_sha256"])
                print("[%s] 噪声矩阵连接 SHA256 与参考环境 oracle 一致"
                      % ("PASS" if ok else "FAIL"))
                status |= 0 if ok else 1
            else:
                print("[INFO] numpy %s != 参考环境 %s：噪声 SHA256 仅作环境条件提示"
                      % (np.__version__, REFERENCE_ENV["numpy"]))

    if args.params:
        errs = compare_params(Path(args.params))
        print("[%s] 实现参数表逐项对比" % ("PASS" if not errs else "FAIL"))
        for e in errs:
            print("   ", e)
        status |= 0 if not errs else 1
    if args.offsets:
        errs = compare_offsets(Path(args.offsets), args.offset_units)
        print("[%s] 实现触发偏移对比" % ("PASS" if not errs else "FAIL"))
        for e in errs:
            print("   ", e)
        status |= 0 if not errs else 1
    if args.noise:
        errs = compare_noise(Path(args.noise),
                             Path(args.noise_sigma) if args.noise_sigma else None)
        print("[%s] 实现噪声矩阵对比" % ("PASS" if not errs else "FAIL"))
        for e in errs:
            print("   ", e)
        if errs and np.__version__ != REFERENCE_ENV["numpy"]:
            print("[INFO] 当前 numpy 与参考环境不同；若实现环境亦不同，"
                  "按 P17 规则需用实现记录的 numpy 版本重算后再判定")
            status = 2 if status == 0 else status
        else:
            status |= 0 if not errs else 1

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stream, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print("已写入 %s" % out)

    print("\n[%s] E0-S2 随机流 oracle 探针"
          % ("PASS" if status == 0 else ("INFO" if status == 2 else "FAIL")))
    return status


if __name__ == "__main__":
    sys.exit(main())
