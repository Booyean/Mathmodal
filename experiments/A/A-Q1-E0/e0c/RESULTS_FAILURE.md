# E0-C 真实校准执行结果（失败登记，E0C-RUN-1）

- **状态**：**已执行一次，硬停止（exit 3），不冻结、不进入 E0-T**。`e0c_frozen.json` 未写出。
- **执行时间**：2026-11-28 15:40（本地）；**机器**：Windows 11 26200，Python 3.13.5，numpy 2.1.3，单进程单线程。
- **实现提交**：`4cb44a0d59bfc8999187f40efe57318d70a033b7`（父 `5ad8417b677ec727dc77ec0b5f12d00e4efe41f1`，`origin/main = 3b8b67e58156b9618c788ec8e114e50d960bbb0d`，运行树 clean）。
- **放行依据（重要）**：`workspace-approval:fb4c1003-3f83-4a71-b2e3-c80bd3d964d3`（工作区审批，`status=approved`、`resolved_by=policy`，owner `18148140820@163.com`）。**B-02 的 codex 签发在本轮仍未取得**（codex 于 13:01 因配额上限中断）；本结果按工作区审批放行执行，请 codex 上线后追认或裁定重登记。该披露同时写入 `e0c_results.json#approval_ref`。
- **范围（与白名单一致）**：12 组 / 96 个 `.dat` / 88,073,632 B；`path_guard.guarded_files=96`、`rejections=[]`；`valid_rx=63`（每组）；未读 E0-T 两组、其余 18 组留出样、`附件3`、B 题。
- **命令**（单次，无重跑）：
  ```
  python solutions/A/a_e0_c.py --mode execute \
    --approval-ref workspace-approval:fb4c1003-3f83-4a71-b2e3-c80bd3d964d3 \
    --config experiments/A/A-Q1-E0/config.json \
    --split coordination/A_Q1_SPLIT.json \
    --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" \
    --out experiments/A/A-Q1-E0/e0c/results \
    --implementation-sha 4cb44a0 --parent-commit 5ad8417 --main-commit 3b8b67e
  ```
- **锚点**：`config 8fb6821f…e06a`、`PLAN 073511c0…5a88`、`SPLIT d623da4e…8b3a`、`E0-S results 171f55f7…3fdf`，全部匹配。
- **资源**：墙钟 **153.236 s**（预算 600 s），峰值 RSS **296.9 MiB**（预算 4096 MiB）。

## 1. 结果（数值直接取自 `e0c_results.json`，未手算、未四舍五入掩盖灰区）

| 组 | 类型 | `d_hat` | `abs_err` | `Supp_dw-win` | `PSLR` | `PNR` | `valid_rx` | 判定 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `墙体数据/data1-42cm` | 墙（标称 42 cm） | 0.481800 m | **6.180 cm**（灰区） | 3.269 dB | **2.664 dB** | 34.294 dB | 63 | **hard_stop**（`pslr_db`） |
| `金属板数据/data1-69cm` | 金属板（标称 69 cm） | 0.733700 m | 4.370 cm | 4.185 dB | 4.173 dB | 35.429 dB | 63 | eligible |

**空场 10 折 LOO**（λ 网格 9 组，选中默认 `(1e-3, 1e-3)`，未触发切换）：

| 折（held-out） | data1 | data2 | data3 | data4 | data5 | data6 | data7 | data8 | data9 | data10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Supp_air-LOO` (dB) | 4.19 | **2.98** | 9.89 | 10.20 | 12.88 | 13.10 | 12.65 | 12.49 | 10.40 | 9.77 |

- `min = 2.9844 dB`（门槛 `≥ 10.0` 可通过；`< 6.0` 硬停止 → **硬停止**）
- `median = 10.3010 dB`；`J_air(default) = 11.7932 dB`；`J_air(best) = 12.2271 dB @ (1e-4, 1e-2)`，未切换（预算与默认保持规则）。

## 2. 门控判定

| 门 | 实测 | 阈值 | 结果 |
|---|---:|---:|---|
| 空场 `min(Supp_air-LOO)` | 2.984 dB | `≥ 6.0`（可冻结 `≥10`） | **硬停止** |
| 墙体 `PSLR` | 2.664 dB | `≥ 3.0` | **硬停止** |
| 墙体 `abs_err` | 6.180 cm | `≤ 5.0` 可冻结（`>10.71` 硬停） | 灰区 |
| 金属板 `PSLR` / `PNR` / `abs_err` | 4.173 / 35.429 dB / 4.370 cm | 3.0 / 6.0 / 5.0 | 通过 |
| 通道 / 有限值 | 63、全部 finite | 63、no NaN/Inf | 通过 |
| 资源 / 越界 | 153.2 s / 296.9 MiB / 96 文件 | 600 s / 4096 MiB / 白名单 | 通过 |

`stop_reason = "air_loo_hard_stop: min=2.9844 dB < 6.0 dB; E0-C/Wall-42cm: pslr_db(failed)"`。

## 3. 独立验收器交叉核对（E0-PREREG-3，`my_deepseek` 冻结版）

```
python checks/A/e0_c_accept/accept_e0c.py --results-dir experiments/A/A-Q1-E0/e0c/results --repo . 
→ E0-C VERDICT: FAIL
C1–C8 PASS，C9 FAIL（正是上面两个目标组门控），C10–C15 PASS
```

含义：**交付包接口与可复算性是干净的**（C10 由交付数组重算 `Supp/PSLR/PNR/d_hat` 与报告值一致，C12 `metrics_sha256` 一致，C11 冻结状态一致 `hard_stop`），**失败来自实验本身而非接口**。这同时关闭了 `V1-20261128-02` 接口不兼容项在真实数据上的验证。

## 4. 事实性观察与待裁定假设（未改参、未重跑）

1. 空场 LOO 抑制随组差异大：`data1/data2` 仅 4.19/2.98 dB，其余 8 组 9.9–13.1 dB。说明**跨组直射波/背景并非稳定可减**，或空气模板跨组对齐（折叠锚包、载波相位）存在系统性残差。这是 `M0-DW-Base` 的前提假设在实测上的直接反例。
2. 两个目标组的 `Supp_dw-win` 也仅 3.27 / 4.19 dB，与空场 LOO 的低抑制一致；但 `PNR` 仍有 34 dB 量级（背景窗 `[50,950] ns` 不含直射波主瓣），弱抑制未直接摧毁目标检测。
3. 两个目标组 `d_hat` 均比标称距离大约 `+4.4 ~ +6.2 cm`。可能是：标称距离不是物理真值（`O-D0-04`）、参考时刻/硬件时延口径系统偏置、或墙体首峰落在后沿。**现有数据不能区分**，需 codex/建模决定是否作为独立诊断项。
4. 墙体 `PSLR=2.66 dB` 与空场低抑制同向：残余直射波旁瓣抬高了目标峰附近旁瓣。

## 5. 停止与后续选项（不自动重跑、不调参、不扩样）

- 本结果按清单 §4 冻结为**失败证据**：实现/父/主线、锚点、命令、环境、资源、失败门、产物 SHA256 全部在 `e0c_results.json` 与 `SHA256SUMS.txt` 中。
- 待统筹裁定（不预设结论）：
  1. **追认/否决本轮放行依据**（工作区审批 vs B-02）。
  2. 若要继续，须先升级方案并重新登记（例如 N0 单项改进或新的直射波模型），**不得**在本结果上直接改 λ/η/阈值重跑。
  3. 在冻结前，`E0-T` 仍不得触碰。

## 6. 产物

| 文件 | 说明 |
|---|---|
| `e0c_results.json` | 全字段结果（含 `approval_ref`、`groups[12]`、`inputs[96]`、`air_loo`、门控、资源、摘要） |
| `e0c_arrays.npz` | 交付数组（`air_loo__p_cal/p_sup (9,10,63)`、`p_air_loo`、`h_rel`、`S_eff`、压缩剖面等） |
| `e0c_air_loo.json` | 10 折 × 9 组 LOO 明细 |
| `run.log` / `SHA256SUMS.txt` | 日志与产物摘要（`e0c_results.json` 自身摘要只在 `SHA256SUMS.txt`） |
