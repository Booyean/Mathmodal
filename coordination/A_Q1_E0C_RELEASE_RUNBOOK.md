# A-Q1-E0-C 放行即跑 Runbook（预演版）

> 契约：`E0C-DRYRUN-1` ｜ 预演脚本：`solutions/A/e0c_release_dryrun.py` ｜ 自检：`solutions/A/test_e0c_release_dryrun.py`（18/18）
> 基线：`origin/main = 934b0893`；脚本提交 `3e5bf1c`（分支 `data/a-q1-n0-batch`，PR #41）
> 预演实测：**11/11 PASS，6.7 s**，`packets_parsed = 0`，未执行 `--mode execute`

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

溯源旁产物（每次运行各一份，**必须随结果包保留**）：`worker_meta.json` 与
`repeat_runs/run-2/worker_meta.json`，记录该次进程的 `pid`、`started_at`/`finished_at`、
结果/数组/指标摘要。`e0c_repeat.json` 是它们的汇总；缺少这两份时，C12 的“两次独立进程”
只能由汇总自述，不能追溯到原始运行。

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

## 7. 本轮预演实测（2026-11-28，提交 `3e5bf1c`）

| 检查 | 结果 | 关键值 |
|---|---|---|
| D1 工作区干净 | PASS | `HEAD=3e5bf1c9`，`origin/main=934b0893` |
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

证据口径：本 PR 只保留上表摘要，**不复制** `dryrun.json`/`preflight.json` 等含机器绝对路径的
运行日志（全量日志在 PR #42 的 `data/a-q1-e0c-release-dryrun`）。需要复核时，在任意干净
worktree 重跑 `python solutions/A/e0c_release_dryrun.py` 即可复现同一 11 项检查。
实测轮（B-02）的 `preflight/dryrun` 与 3 个未共享证据文件另见 §9 的频道证据包。

本轮另修了预演脚本自身的一处状态解析缺陷：`git status --porcelain` 首行的前导状态位空格被 `strip()` 吃掉，
使 ` D <evidence>` 被误判为代码改动（D1 假 FAIL）；已改为 `strip=False` 并加两条例行负例（自检 18/18）。

## 8. 未决项（不写成通过）

1. **放行未签发**：`B-02` 未放行，`--mode execute` 一次都没有跑过；本 runbook 只证明“可以开跑”。
   （2026-11-28 更新：已按 `055f0075…` 完成双跑并归档，见 §9；`E0-T` 仍未放行。）
2. **C12 两进程证据形态**只在合成夹具上被官方检查器接受过（`e0c_official_precheck.py`，C12 PASS、C4 因合成文件名 FAIL）；真实数据上的 C12 仍待放行后产生。
3. **`inputs[96]` 的真实 SHA** 只能在真实运行里写入；预演的 `check` 已核对白名单与清单总 SHA，但不写结果。
4. **逐位复跑**：同机同环境要求指标一致、数组按容差；跨机不宣称数组逐位（E0-S 已记录该边界）。

---

## 9. 实测轮（B-02）证据归档与结果台账的 CRLF 口径

### 9.1 实测轮归档

2026-11-28 按 `B-02`（放行编号 `055f0075-f8eb-401d-8938-fd0b12bbf8f1`）在 `c7b841e`
干净 worktree 完成 E0-C 双跑，写入 `results-r2/`（14 文件）。验收 `FAIL`，唯一失败项 **C9**
（墙体 PSLR `2.664330 dB < 3.0 dB`；空场 LOO min `2.984434 dB < 6.0 dB`），结论维持
`hard_stop`，`E0-T` 仍未放行。该目录**不提交本仓库**，证据包归档在频道：

| 归档件 | 内容 |
|---|---|
| `r2_evidence_bundle.zip` | 3 个此前未共享文件、本轮 `preflight`/`dryrun`/console、独立重算脚本与报告、全量清单 |
| `r2_MANIFEST_14_ORIGINAL.txt` | `results-r2` 14 文件全量 SHA256（聚合摘要 `5d04470f5ec1…`） |
| `r2_worker_meta_run1.json` / `r2_worker_meta_run2.json` | 两次进程的 PID/时间窗/摘要原始来源（`e1a4d1b9…` / `299e3a7a…`） |
| `r2_run2_e0c_results.json` | 第 2 次独立进程的结果文件（`0a76eed0…`） |

补齐后 `results-r2` **14/14 可核**（原 11/14）：顶层台账 7/7、run-2 台账 4/4、两次数组
`03084cff…` 与冻结归档逐字节相同，独立复算确认 C9。复核：

```powershell
python verify_bundle.py --results-dir <results-r2>
python recompute_c9.py  --results-dir <results-r2> --out recompute_report.json
```

### 9.2 为什么同一文件会出现两个 SHA256

`e0c/results/*.json|log` 与 `results-r2` 的台账，登记的是 **Windows 工作树（CRLF）字节**；
git blob 是 **LF**。两种摘要都正确，但不可混用：

| 文件 | 工作树 CRLF（台账值） | git blob（LF） |
|---|---|---|
| `e0c/results/e0c_results.json` | `7d3fbcd582de…`（84,591 B） | `9404b126a2bb…`（82,021 B） |
| `e0c/results/e0c_air_loo.json` | `dc31ffdd9d04…`（13,056 B） | `d31993c5537a…`（12,529 B） |
| `e0c/results/run.log` | `7582d77080cb…`（1,003 B） | `bef1648bdf6d…`（987 B） |
| `e0c/results/e0c_arrays.npz` | `03084cffe041…`（二进制） | 同（二进制，无 EOL 转换） |

`results-r2` 的 `e0c_results.json`、`e0c_air_loo.json`、`run.log`、`worker_meta.json`、
`SHA256SUMS.txt` 同样是 CRLF 台账值；`acceptance.json` 是 LF。

### 9.3 核验规则（写死，避免假 FAIL）

1. 在 **`core.autocrlf=true`**（Windows 默认）或 `.gitattributes` 的 `eol=crlf` 检出下，
   直接对工作树文件算 SHA256，与 `SHA256SUMS.txt` 一致。
2. Linux/macOS（`autocrlf=false`）若得到 LF 摘要，先做 LF→CRLF 归一化再对台账，或直接对
   LF 归一化值（`r2_MANIFEST_14_ORIGINAL_LF.txt`）核验；**不要**拿 raw LF 值对 CRLF 台账。
3. `.npz` 是二进制，**禁止**任何 EOL 归一化（字节里偶然出现 `0d0a` 不是行尾）。
4. `.gitattributes` 已对 `e0c/results`（及 `results-r2`）显式钉 `text eol=crlf`：只影响检出，
   不重写 git blob、不改冻结字节。这样 Linux 干净检出也能复现台账。
   **不要**用 `git add --renormalize` 去“统一钉 LF”：那会改冻结 blob 并让已登记的台账全部失效。

### 9.4 复核命令

```powershell
git check-attr text eol -- experiments/A/A-Q1-E0/e0c/results/e0c_air_loo.json
# 期望: text: set / eol: crlf
git ls-files --eol -- experiments/A/A-Q1-E0/e0c/results
# 期望: i/lf  w/crlf  attr/text eol=crlf
```

> 本节只补口径与归档，**不修改** `e0c/results`、`results-r2` 的任何字节，也不改任何阈值或结论。
