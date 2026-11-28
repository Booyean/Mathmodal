# E0-C 独立验收报告（`b63e217`）

- **被验对象**：`data/a-q1-e0-c-interface` @ `b63e217`（PR #33）中登记的 E0-C 真实校准
  运行产物：`experiments/A/A-Q1-E0/e0c/results/`（`e0c_results.json`、`e0c_arrays.npz`、
  `e0c_air_loo.json`、`run.log`、`SHA256SUMS.txt`；无 `e0c_frozen.json`）。
- **实现**：`4cb44a0`（父 `5ad8417`，运行基线 `main=3b8b67e`）。
- **判据**：`E0-PREREG-3`（`checks/A/e0_c_prereg.json`，SHA256 `ae7c41ba…`）+
  `E0-C-C12-REPEAT-1`（`checks/A/e0_c_repeat_contract.json`，SHA256 `a32429e2…`）。
- **命令**：

  ```powershell
  python checks/A/e0_c_accept/accept_e0c.py `
    --results-dir experiments/A/A-Q1-E0/e0c/results `
    --repo . --report checks/A/e0_c_accept/report_b63e217.json `
    --e0s-results experiments/A/A-Q1-E0/s1s2/results/e0_s1s2_results.json
  ```

- **结论**：**FAIL**，失败项 **C9**（墙体 PSLR 硬停）与 **C12**（只有重复序列化，缺两次
  独立运行证据）。其余 13 项通过；数值本身经独立重算复现（C8/C10 通过）。

## 1. 版本与锚点（C1/C2）

| 项 | 值 | 结果 |
|---|---|---|
| config SHA256 | `8fb6821f…` | 与预登记一致；`git show 3b8b67e` 与当前 `origin/main bc90e1b` 均复算一致 |
| PLAN SHA256 | `073511c0…` | 同上 |
| SPLIT SHA256 | `d623da4e…` | 同上 |
| E0-S 结果 SHA256 | `171f55f7…` | 与预登记一致，`overall_pass=true`，三例齐全（C6） |
| 实现 | `implementation_sha=4cb44a0`、`parent_commit=5ad8417`、`main_commit=3b8b67e` | `git rev-parse 4cb44a0^ = 5ad8417`，非自引用 |
| 结果提交 | `b63e217`（父 `4cb44a0`） | 结果与实现分离，未复用实现 SHA 冒充结果 |

锚点文件在当前主线 `bc90e1b` 与运行基线 `3b8b67e` 上逐字节相同，故“结果基于旧 main”
不构成失效。

## 2. C1–C15 逐项

| 项 | 状态 | 关键证据 |
|---|---|---|
| C1 版本锚点 | PASS | 四个 SHA 全匹配；git 在结果声明的 main 上复算一致 |
| C2 实现身份 | PASS | 40 位 hex、父提交可追溯、非自引用 |
| C3 边界 | PASS | 恰好 12 组；无 `_test`/`data20-73cm`/`data5-60cm`/`附件3`/`B题`；`run.log` 干净 |
| C4 数据身份 | PASS | `inputs[96]` 与 oracle 逐文件 size+SHA256 一致；合计 `88,073,632 B` |
| C5 方法范围 | PASS | `alpha_mode=fixed_1.0`、`n0_improvements_enabled=false`、无自适应/子空间/WLS/非等权；源码关键词仅命中声明行 `"subspace_suppression": False`（提示项，不构成失败） |
| C6 E0-S 前置 | PASS | E0-S 结果 SHA256 `171f55f7…`、`overall_pass=true`、三例、S2 `valid_rx=63` |
| C7 通道/有限性 | PASS | 12 组 `valid_rx=63`、`finite=true`；目标组数组无 NaN/Inf |
| C8 空场 LOO | PASS | 9×10 折独立重算全一致；`selected=(0.001,0.001)`、`switched=false`、`eligibility=hard_stop`（min 2.9844 dB < 6.0） |
| C9 目标门控 | **FAIL** | 墙体 `PSLR=2.6643 dB < 3.0`（硬停）；`PNR=34.29`、`abs_err=6.18 cm`（灰区）；金属全过（`PSLR=4.1726`、`PNR=35.43`、`abs_err=4.37 cm`） |
| C10 指标独立重算 | PASS | 见 §3，5 项指标全部在 `1e-6 dB` / `1e-9 m` 内 |
| C11 冻结完整性 | PASS | `freeze.status=hard_stop`、`written=false`、无 `e0c_frozen.json`；`η_wall=0.25` 在候选集内 |
| C12 确定性证据 | **FAIL** | 只有 `arrays_sha256_second_serialization == arrays_sha256`，无第二次独立运行；见 §5 |
| C13 资源 | PASS | `153.236 s ≤ 600 s`、`296.86 MiB ≤ 4096 MiB`、单进程、四线程变量均为 `1` |
| C14 证据完整 | PASS | 必需文件齐全非空；`SHA256SUMS.txt` 覆盖且摘要匹配 |
| C15 真值隔离 | PASS | `d_true_usage=evaluation_only`；数组名无真值字段；源码 `d_true` 仅提示人工复核 |

## 3. 指标独立重算（C10）

从交付的 `z_before/z_after/d_m/P_after` 按 `E0-PREREG-3 §5` 重算，不导入生产代码：

| 指标 | 墙体 data1-42cm 交付 / 重算 | 金属板 data1-69cm 交付 / 重算 |
|---|---|---|
| `Supp_dw-win` (dB) | 3.268659668481 / 3.268659668 | 4.185473074871 / 4.185473075 |
| `PSLR` (dB) | 2.664330228103 / 2.664330228 | 4.172579749859 / 4.172579750 |
| `PNR` (dB) | 34.293809233763 / 34.293809234 | 35.429278994344 / 35.429278994 |
| `d_hat` (m) | 0.481800000000 / 0.481800000000 | 0.733700000000 / 0.733700000000 |
| `abs_err` (cm) | 6.179999999996 / 6.180000000 | 4.369999999994 / 4.370000000 |

最大偏差 `4.811e-10 dB`、`6.421e-12 cm`，远小于容差。**说明 `dsh` 报备的“按离散交付
网格重算”口径与预登记独立实现一致**，C10 无口径分歧。

## 4. 空场 LOO（C8）

- 9 对 λ 的 `J_air` = `[11.636622, 11.800839, 12.227073, 11.626637, 11.793199,
  12.221769, 11.463840, 11.682675, 12.166310]`。
- 默认对 `(1e-3,1e-3)` 的 `min(Supp)=2.984434 dB`，最佳对亦 `2.909364–3.129799 dB`，
  全部 `< 6.0 dB` → `eligibility=hard_stop`；`switched=false`（切换只对“达到 10 dB”有意义）。
- 90 个逐折抑制值与交付 `grid[f].folds[g].supp_db` 全部在 `1e-6 dB` 内；无 `<1e-6 dB`
  近并列（`near_tie_grid` 仅含最佳对自身），`V1-20261128-01` 的并列裁决不影响本次判定。

## 5. C12 确定性证据：为什么判 FAIL

交付的 `repeat_run` 为：

```json
{"arrays_sha256": "03084cff…", "arrays_sha256_second_serialization": "03084cff…",
 "metrics_sha256": "1cce102f…", "metrics_recomputed_from_delivered_arrays": true,
 "note": "两次独立序列化逐字节一致；指标已由交付数组按 E0-PREREG-3 §5 重算核对"}
```

`arrays_sha256_second_serialization` 与 `arrays_sha256` **完全相同**，没有第二套数组/结果
文件、没有第二个进程的 PID/时间窗——这只是**同一批数组序列化两次**，不是两次独立运行。
按 `E0-C-C12-REPEAT-1`（统筹 `codex` 2026-11-28 裁定），C12 判 FAIL，
`duplicate_serialization_detected=true`。

需要 `dsh` 补的证据形态见 `checks/A/e0_c_repeat_contract.md`：`repeat_run.runs[2]` 或
`e0c_repeat.json#runs[2]`，每条带 `run_id/pid/started_at/finished_at/results_file/
results_sha256/arrays_file/arrays_sha256/wall_time_s`；两套文件独立、SHA 匹配、时间窗
不重叠；检查器会用第二次运行的 npz **独立重算**两个目标组指标与交付 JSON 比对。

## 6. 数据、资源与边界

- **数据身份**：交付 `inputs[96]` 与冻结 oracle 一致。本机稀疏检出只含 24 个 `.dat`
  （3 组各 8 个），逐个重算 SHA256+size **24/24 与 oracle 一致**；其余 72 个未在本机
  落地，C4 对这些文件依赖 oracle 身份与交付清单的逐项一致（未重新读盘）。
- **真实执行证据**：`run.log` 16 行、`resource.wall_time_s=153.236`、`peak_rss_mib=296.86`；
  `scope` 明示“非盲测、不含 E0-T”。
- **未读 E0-T**：C3 的禁止对象扫描与 `run.log` 均未命中 E0-T/留出组；本检查器亦未读取
  任何留出组文件。
- **报告路径**：同名 JSON 报告中的 `results_dir`/`prereg_path` 是复跑时的本机路径，
  数值与结构不受影响，可用 §命令 再生。
- **C9 判定修正**：本次同时修正检查器自身的分类优先级缺陷——旧实现把 `abs_err` 灰区
  判在 `PSLR/PNR` 硬停之前，导致失败理由误写成 `status` 不一致；修正后 C9 的真实失败
  原因是“墙体 PSLR=2.6643 dB < 3.0 dB”。门槛、容差与结论均未改变（修正前后 verdict
  都是 FAIL）。

## 7. 结论与影响

1. **E0-C 的数值可信**：C8/C10 的独立重算与交付值一致到 `1e-10` 量级；C1–C8、C10–C11、
   C13–C15 通过。
2. **E0-C 是硬停，不是可冻结**：空场 LOO `min=2.9844 dB < 6.0`、墙体 `PSLR=2.6643 < 3.0`。
   这是数据/方法结论，不是登记错误；`E0-T` 不应读取，论文不得把 E0-C 写成通过。
3. **C12 证据不合格**：补两次独立运行的产物后可复测 C12；但即使 C12 通过，C9 的 PSLR
   硬停仍然成立，E0-C 不能冻结。
4. **待办归属**：`dsh` 补第二次独立运行证据并回应 C9 硬停（是否按 PLAN 登记失败/回退）；
   `codex` 裁定 E0-C 硬停后的路线（修改模型/换基线/是否放弃 E0-T），并决定本验收补丁与
   PR #33 的合并顺序。
