# A-Q1-E0-C 放行即跑 Runbook（预演版）

> 契约：`E0C-DRYRUN-1` ｜ 预演脚本：`solutions/A/e0c_release_dryrun.py` ｜ 自检：`solutions/A/test_e0c_release_dryrun.py`（16/16）
> 基线：`origin/main = 934b0893`；预演提交 `54e3ef90`（分支 `data/a-q1-e0c-release-dryrun`）
> 预演实测：**11/11 PASS，7.6 s**，`packets_parsed = 0`，未执行 `--mode execute`

本文只覆盖 **E0-C 命令链、目录契约与守卫**。它不构成放行，也不替代独立验收：
真实 `execute` 仍须统筹签发 `--approval-ref`（当前 `B-02` 未放行）。

---

## 1. 放行前必须已经满足

| 依赖 | 判定依据 | 现状 |
|---|---|---|
| D1-2 折迭门控已验收 | `a_fold_gate.py` `CONTRACT_VERSION == "D1-2"` | 已验收 |
| E0-S 合成闭环 | `s1s2/results/e0_s1s2_results.json`：`overall_pass=true` | 已通过 |
| R0 清单与 96 个 `.dat` 身份 | `recon/manifests/a_dat_manifest.csv` 总 SHA 一致 | 本轮预演通过 |
| 入口就绪 | `a_e0_c.py --mode check` → `ready_for_execute=true` | 本轮预演通过 |
| 放行编号 | 统筹书面 `--approval-ref` | **未签发（B-02）** |

## 2. 放行当天步骤

### 2.0 从实现提交建干净 worktree（不要用开发工作区）

```powershell
git fetch origin
git worktree add ..\Mathmodal-release <impl-sha>
cd ..\Mathmodal-release
git status --porcelain        # 必须为空；有输出就停下
```

### 2.1 锁线程（四个变量都必须为 `"1"`）

```powershell
$env:OMP_NUM_THREADS="1"; $env:OPENBLAS_NUM_THREADS="1"
$env:MKL_NUM_THREADS="1";  $env:NUMEXPR_NUM_THREADS="1"
```

### 2.2 放行前自检（元数据，不解析采样）

```powershell
python solutions/A/e0c_preflight.py --out experiments/A/A-Q1-E0/e0c/preflight.json
python solutions/A/a_e0_c.py --mode check
```

期望：`preconditions_pass=true`、`ready_for_execute=true`、`packets_parsed=0`。

### 2.3 跑一遍预演（应 11/11）

```powershell
python solutions/A/e0c_release_dryrun.py
```

期望：`ready_for_release_day=true`、退出码 `0`。任一 FAIL 即停，按第 5 节处置。

### 2.4 正式执行（两次独立进程，约 300 s，写新目录）

```powershell
python solutions/A/a_e0_c.py --mode execute `
  --approval-ref <approval-ref> `
  --repeat-runs 2 `
  --config experiments/A/A-Q1-E0/config.json `
  --split coordination/A_Q1_SPLIT.json `
  --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" `
  --out experiments/A/A-Q1-E0/e0c/results-r2 `
  --implementation-sha <impl-sha> `
  --parent-commit <parent-sha> `
  --main-commit <origin/main-sha>
```

> 不要加 `--overwrite`，不要写 `e0c/results/`（b63e217 是单次运行，不满足
> `E0-C-C12-REPEAT-1`，必须原样保留）。

### 2.5 交付核对

```powershell
python checks/A/e0_c_accept/accept_e0c.py `
  --results-dir experiments/A/A-Q1-E0/e0c/results-r2 `
  --report experiments/A/A-Q1-E0/e0c/results-r2/acceptance.json
```

期望：C1–C15 中 C12 PASS，其余全 PASS（C4 的 `inputs[]` 必须等真实 SHA）。

## 3. 放行日替换表

| 占位 | 取值 | 来源 |
|---|---|---|
| `<approval-ref>` | 统筹放行编号/链接 | 频道裁定消息 |
| `<impl-sha>` | 运行代码所在提交的**完整** SHA | `git rev-parse HEAD`（worktree） |
| `<parent-sha>` | 该提交的父提交 | `git rev-parse HEAD^` |
| `<main-sha>` | 运行时 `origin/main` | `git rev-parse origin/main` |

## 4. 产物清单（`results-r2/`）

必产物 8 项：

| 文件 | 核对点 |
|---|---|
| `e0c_results.json` | `approval_ref`、`implementation_sha` = 完整 SHA、`groups[12]`、`inputs[96]` |
| `e0c_arrays.npz` | 确定性序列化；`arrays_sha256` 与文件一致 |
| `e0c_air_loo.json` | `folds[10]`、`grid[9]`、`selected`、`min/median_supp_db` |
| `e0c_repeat.json` | `runs[2]`：`pid` 不同、时间窗不重叠、文件路径不同 |
| `repeat_runs/run-2/e0c_results.json` | 第 2 次独立进程产物 |
| `repeat_runs/run-2/e0c_arrays.npz` | 第 2 次数组 |
| `run.log` | 两次运行的诊断日志 |
| `SHA256SUMS.txt` | 覆盖除自身外全部产物 |

条件产物：`e0c_frozen.json`（仅全部门槛可冻结时写出，含 `(λ_cal, λ_inv, η_wall)` 与实现 SHA）、
`repeat_runs/run-2/e0c_frozen.json`。

## 5. 守卫矩阵（本轮实测退出码）

| 误操作 | 期望 | 实测 |
|---|---|---|
| `--mode execute` 缺 `--approval-ref` | 退出码 2，不产生任何结果文件 | **2**，无产物 |
| 目标目录已有 `e0c_results.json` | 退出码 2，原文件字节不变 | **2**，哨兵 SHA 前后一致 |
| `--repeat-runs 3` | 退出码 2，不启动运行 | **2** |

三条守卫都在读取任何 `.dat` 之前返回，因此可以放心在放行前反复演练。

## 6. 中止与回退

触发任一即停，保留 JSON/日志，**禁止自动重跑、改阈值、扩样**：

- 越界读取（白名单外、`*_test` 组、附件 3、B 题）；
- 版本锚点不符（config / PLAN / SPLIT / E0-S）；
- `valid_rx < 63`、NaN/Inf、空场 `min(Supp_air-LOO) < 6.0 dB`、`PSLR < 3.0 dB`、`PNR < 6.0 dB`、`abs_err > 10.71 cm`；
- 墙钟 > 600 s 或峰值 RSS > 4096 MiB；
- 两次运行指标不一致（dB 1e-6、cm/m 1e-9）。

回退点：最近一个通过验收的 `main` 提交（当前 `934b089`，含 E0-S 实现、登记与独立验收）。
`b63e217`（`e0c/results/`）是失败证据，只读保留。

## 7. 本轮预演实测（2026-11-28，提交 `54e3ef9`）

| 检查 | 结果 | 关键值 |
|---|---|---|
| D1 工作区干净 | PASS | `HEAD=54e3ef90`，`origin/main=934b0893` |
| D2 既有登记只读锁定 | PASS | 4/4 份 SHA256 与 `SHA256SUMS.txt` 一致；预演前后不变 |
| D3 目标目录可登记 | PASS | `e0c/results-r2` 不存在、无旧 `run-2`、非冻结目录 |
| D4 元数据自检 | PASS | 32/32 项、96 文件、`88,073,632 B`、路径守卫 0 拒绝 |
| D5 入口 check | PASS | `ready_for_execute=true`、`packets_parsed=0`、`dat_open_for_sha256=96` |
| D6 缺放行编号守卫 | PASS | 退出码 2，无产物 |
| D7 覆盖守卫 | PASS | 退出码 2，哨兵未被改动 |
| D8 `--repeat-runs` 守卫 | PASS | 退出码 2，未启动 |
| D9 交付契约差异 | PASS | 既有登记缺 `e0c_repeat.json` → 必须写新目录 |
| D10 资源预算 | PASS | 600 s / 4096 MiB |
| D11 登记未漂移 | PASS | 4/4 文件预演前后 SHA256 不变 |

锚点（未变）：`config=8fb6821f…`、`PLAN=073511c0…`、`SPLIT=d623da4e…`。

证据：`experiments/A/A-Q1-E0/e0c/dryrun/<时间戳>/dryrun.json`。

## 8. 未决项（不写成通过）

1. **放行未签发**：`B-02` 未放行，`--mode execute` 一次都没有跑过；本 runbook 只证明“可以开跑”。
2. **C12 两进程证据形态**只在合成夹具上被官方检查器接受过（`e0c_official_precheck.py`，C12 PASS、C4 因合成文件名 FAIL）；真实数据上的 C12 仍待放行后产生。
3. **`inputs[96]` 的真实 SHA** 只能在真实运行里写入；预演的 `check` 已核对白名单与清单总 SHA，但不写结果。
4. **逐位复跑**：同机同环境要求指标一致、数组按容差；跨机不宣称数组逐位（E0-S 已记录该边界）。
