# E0-C 硬停后的目标结果再生（`E0-C-POSTSTOP-1`）

> **不可引用声明**：本文件的目标数值来自一次**未通过门控**的硬停运行；按 E0-C 预登记与
> `DIAGNOSIS_AIR_LOO.md` §8，硬停运行的 `d_hat` **不得**进入结果表、论文数字、冻结或 `E0-T`，
> 只能用于失败登记、诊断与局限性说明。

| 项 | 值 |
|---|---|
| 生成时间（UTC） | `2026-11-28T10:36:43.906218Z` |
| 源结果包 | `experiments/A/A-Q1-E0/e0c/results` |
| 源 results SHA256 | `7d3fbcd582de301127cb5200d20093f4efcfa8adc295a6c1cb6fdd618f0aeba8` |
| 源 arrays SHA256 | `03084cffe041900d6a9aa82b5492e6fb64474d971c37e0560adbd115ce4962ff` |
| 实现提交 | `4cb44a0d59bfc8999187f40efe57318d70a033b7` |
| 放行引用 | `workspace-approval:fb4c1003-3f83-4a71-b2e3-c80bd3d964d3` |
| `freeze.status` | **`hard_stop`**（eligible=`False`，frozen 文件存在=`False`）|
| `stop_reasons` | `air_loo_hard_stop: min=2.9844 dB < 6.0 dB`；`E0-C/Wall-42cm: pslr_db(failed)` |
| 空场 LOO | `eligibility=hard_stop`，`min=2.9844 dB`，`median=10.3010 dB` |
| 一致性 | `all_within_tolerance=True`，`max|Δ|_dB=0`，`max|Δ|_m=0` |

## 1. 两目标组（重算值 / 报告值）

| 目标组 | 类型 | `d_hat` (m) | `abs_err` (cm) | `Supp` (dB) | `PSLR` (dB) | `PNR` (dB) | 组状态 | 可引用 |
|---|---|---:|---:|---:|---:|---:|---|---|
| `墙体数据/data1-42cm` | wall | 0.481800 / 0.481800 | 6.180 / 6.180 | 3.269 / 3.269 | 2.664 / 2.664 | 34.29 / 34.29 | `hard_stop` | **否** |
| `金属板数据/data1-69cm` | metal | 0.733700 / 0.733700 | 4.370 / 4.370 | 4.185 / 4.185 | 4.173 / 4.173 | 35.43 / 35.43 | `eligible` | **否** |

> 每格为「本次从交付数组重算值 / `e0c_results.json` 报告值」。全部差值须 ≤ `1e-6 dB`
> （长度 ≤ `1e-9 m`）；不满足时本入口以退出码 `3` 拒绝出具。

## 2. 引用隔离字段

| 字段 | 值 |
|---|---|
| `citable` | `False` |
| `usage` | `diagnostic_only_after_hard_stop` |
| 可进结果表 / 论文数字 | `False` / `False` |
| 可用于冻结 / `E0-T` | `False` / `False` |

## 3. 守卫与边界

- 只接受 `freeze.status == "hard_stop"` 且无 `e0c_frozen.json` 的包；`eligible`/灰区包直接拒绝。
- 只允许 12 组白名单；出现 `data20-73cm`、`data5-60cm`、`_test`、`附件3`、`B题` 直接拒绝。
- 不打开任何 `.dat`、不重跑、不选参、不改阈值、不写冻结文件。
- 重算复用 `a_e0_c.py` 的度量原语，用于核对报告值；独立复核仍由验证方完成。

## 4. 复跑

```sh
python solutions/A/a_e0_poststop.py --results-dir experiments/A/A-Q1-E0/e0c/results --out experiments/A/A-Q1-E0/e0c/poststop
```

## 5. 机器可读产物

- `poststop_targets.json`：同名字段 + `checks.problems`；`citable=false`。
- 每个目标含 `reported` / `recomputed` / `delta` 三组值，便于逐项复核。
