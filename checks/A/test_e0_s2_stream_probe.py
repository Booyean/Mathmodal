#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E0-S2 随机流 oracle 探针的自检套件（E0-PREREG-2，P15 非空转）。

验证 `checks/A/e0_s2_stream_probe.py` 的两类性质：

1. **正向**：用 oracle 自身生成的参数表、偏移、噪声矩阵作为“实现导出”，
   探针必须全部判 PASS（含 seconds / samples 两种偏移单位）。
2. **负向**：逐项注入 1e-15 级或单元素篡改后，探针必须分别判 FAIL。
   这证明探针不是“永远通过”的空转检查。

运行：
    python checks/A/test_e0_s2_stream_probe.py

退出码：0 全通过；1 有失败。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import e0_s2_stream_probe as P  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                        (" — " + detail) if detail else ""))


def main() -> int:
    stream = P.run_stream()
    again = P.run_stream()
    check("二次重建的表/偏移/噪声逐位一致",
          stream["table"]["sha256"] == again["table"]["sha256"]
          and stream["offsets"]["fraction_sha256"] == again["offsets"]["fraction_sha256"]
          and stream["noise"]["concat_sha256"] == again["noise"]["concat_sha256"])
    check("参数表 SHA256 命中预登记值",
          stream["table"]["sha256"] == P.EXPECTED_TABLE_SHA256)
    check("11 个偏移按裁定标签排序",
          [r["label"] for r in stream["offsets"]["rows"]] == P.OFFSET_LABELS)
    check("12 个噪声组按裁定顺序",
          [r["group"] for r in stream["noise"]["rows"]] == P.GROUP_ORDER)

    if np.__version__ == P.REFERENCE_ENV["numpy"] and P.ORACLE_PATH.exists():
        oracle = json.loads(P.ORACLE_PATH.read_text(encoding="utf-8"))
        check("参考环境噪声连接 SHA256 与入库 oracle 一致",
              stream["noise"]["concat_sha256"] == oracle["noise"]["concat_sha256"])
    else:
        print("[INFO] numpy %s != 参考环境 %s，噪声 SHA 跳过（P17 条件项）"
              % (np.__version__, P.REFERENCE_ENV["numpy"]))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # 正向：参数表
        params = {"experiment": "A-Q1-E0-S2", "rows":
                  [[r[0], r[1], r[2], r[3], r[4]] for r in P.build_table(
                      np.random.default_rng(P.SEED))["rows"]]}
        p_params = td / "params.json"
        p_params.write_text(json.dumps(params), encoding="utf-8")
        check("正向：实现参数表逐项一致", P.compare_params(p_params) == [])

        # 负向：参数表 1e-15 级篡改
        bad = json.loads(p_params.read_text(encoding="utf-8"))
        bad["rows"][7][2] = float(bad["rows"][7][2]) + 1.0e-15
        p_bad = td / "params_bad.json"
        p_bad.write_text(json.dumps(bad), encoding="utf-8")
        errs = P.compare_params(p_bad)
        check("负向：参数表 1e-15 篡改被检出", len(errs) >= 1, str(errs[:1]))

        # 正向：偏移（样本单位）
        samples = [r["samples"] for r in stream["offsets"]["rows"]]
        p_off = td / "offsets.json"
        p_off.write_text(json.dumps({"units": "samples", "values": samples}),
                         encoding="utf-8")
        check("正向：偏移按 samples 单位一致",
              P.compare_offsets(p_off, None) == [])
        seconds = [r["seconds"] for r in stream["offsets"]["rows"]]
        p_sec = td / "offsets_sec.json"
        p_sec.write_text(json.dumps({"units": "seconds", "values": seconds}),
                         encoding="utf-8")
        check("正向：偏移按 seconds 单位一致",
              P.compare_offsets(p_sec, None) == [])
        p_u = td / "offsets_u.json"
        p_u.write_text(json.dumps([r["u"] for r in stream["offsets"]["rows"]]),
                       encoding="utf-8")
        check("正向：偏移按无量纲 u 一致", P.compare_offsets(p_u, None) == [])

        # 负向：偏移单值偏移 1e-9（u）
        bad_u = [r["u"] for r in stream["offsets"]["rows"]]
        bad_u[4] += 1.0e-9
        p_bu = td / "offsets_bad.json"
        p_bu.write_text(json.dumps({"units": "u", "values": bad_u}),
                        encoding="utf-8")
        errs = P.compare_offsets(p_bu, None)
        check("负向：单个偏移 1e-9 篡改被检出", len(errs) == 1, str(errs[:1]))

        # 负向：数量不足
        p_short = td / "offsets_short.json"
        p_short.write_text(json.dumps(samples[:-1]), encoding="utf-8")
        check("负向：偏移缺项被拒", len(P.compare_offsets(p_short, None)) >= 1)

        # 正向：噪声 npz
        rng = np.random.default_rng(P.SEED)
        P.build_table(rng)
        for _ in P.OFFSET_LABELS:            # 11 个 Uniform(0,Tp)
            rng.uniform(0.0, P.TP_SAMPLES)
        mats = {}
        for g in P.GROUP_ORDER:
            mats[g] = rng.standard_normal((P.N_RX, P.N_SAMPLES))
        p_npz = td / "noise.npz"
        np.savez(p_npz, **mats)
        check("正向：噪声矩阵逐组 SHA 一致",
              P.compare_noise(p_npz, None) == [])

        # 负向：噪声单元素篡改（1e-15）
        bad = {g: m.copy() for g, m in mats.items()}
        bad["air_5"][17, 123] = float(bad["air_5"][17, 123]) + 1.0e-15
        p_badn = td / "noise_bad.npz"
        np.savez(p_badn, **bad)
        errs = P.compare_noise(p_badn, None)
        check("负向：噪声单元素 1e-15 篡改被检出", len(errs) == 1, str(errs[:1]))

        # 负向：缺组
        p_missing = td / "noise_missing.npz"
        np.savez(p_missing, **{g: m for g, m in mats.items() if g != "air_9"})
        check("负向：噪声缺组被拒", len(P.compare_noise(p_missing, None)) >= 1)

        # 正向：已缩放噪声 + sigma 还原
        sigma = {g: float(0.5 + 0.1 * i) for i, g in enumerate(P.GROUP_ORDER)}
        scaled = {g: mats[g] * sigma[g] for g in P.GROUP_ORDER}
        p_scaled = td / "noise_scaled.npz"
        np.savez(p_scaled, **scaled)
        p_sig = td / "sigma.json"
        p_sig.write_text(json.dumps(sigma), encoding="utf-8")
        check("正向：已缩放噪声按 sigma 还原后一致",
              P.compare_noise(p_scaled, p_sig) == [])

    failed = [r for r in RESULTS if not r[1]]
    print("\n%d passed / %d failed / %d total"
          % (len(RESULTS) - len(failed), len(failed), len(RESULTS)))
    if failed:
        for name, _, detail in failed:
            print("  FAIL:", name, detail)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
