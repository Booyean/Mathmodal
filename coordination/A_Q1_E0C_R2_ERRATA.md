# `results-r2` 证据勘误与复核结论（`E0-C-R2-ERRATA-1`）

| 项 | 值 |
|---|---|
| 性质 | dsh 对**自己上一份交付**（`r2_evidence_bundle.zip` + `README` + `EVIDENCE_CHAIN.md`，2026-11-28 14:02Z）的独立复核与勘误 |
| 方法 | 重新下载工作区 9 个文件 + 解压 zip，逐文件按**原始字节**重算 SHA256；两进程按元数据与产物交叉核对 |
| 结论 | **证据成立：14/14 可核（raw 字节口径），零哈希失配**；但有 **3 条表述必须更正**，其中 1 条涉及 `worker_meta` 是否“原始未洗改” |
| 影响 | 不改 `C9` 硬停结论（`accept_e0c.py` 复跑仅 `C9` FAIL）；不改任何阈值；不改冻结归档 |

## 0. 一句话

**数字都对，话说过头了。** 14 个文件在 raw 字节口径下全部命中清单，两进程 PID/时间窗/RSS/预算成立，`metrics_sha256` 逐位一致；但“两份结果 JSON 只差放行编号/来源/时间戳”“`worker_meta` 是原始未洗改”这两句**说过宽了**，会被独立复核判为矛盾，现按实测更正如下。

## 1. 复核通过项（可引用）

| 检查 | 实测 |
|---|---|
| zip 完整性 / 24 条清单 | 26 文件 + 9 目录，`testzip` 干净；24/24 raw SHA256 命中；0 缺 0 失配 |
| 14 条清单（raw 口径） | **14/14** 命中原始字节；LF 口径仅 12 条文本命中，2 个 `.npz` 显式 raw-only、禁止 EOL 归一化 |
| 两进程（C12） | PID `25608` vs `10504`；`run_id` 不同；窗口 `13:54:58.119–13:57:21.244Z` / `13:57:23.518–13:59:44.097Z`，间隔 2.274 s、**严格不重叠**；两次退出码均 `3`（`hard_stop` 哨兵，非崩溃） |
| 预算 S6 | 两次 `wall_time_s` 合计 `280.647 s ≤ 600`；单次峰值 RSS 最大 `298.551 MiB ≤ 4096` |
| preflight / dryrun | `32/32`（96 文件 / 88,073,632 B，21:53:20+08，早于 `START 21:54:55.954` 95.954 s）；`11/11`、`execute_invoked=false`（21:53:47+08，早 68.954 s） |
| 数值一致性 | 两次运行 `metrics_sha256` 均复算为 `1cce102f…`；`groups/cases/cal/lambda_loo/air_loo_raw` **0 处差异、最大绝对差 0.0** |
| 14 行聚合摘要 | 按 `EVIDENCE_CHAIN` 的 results-r2 顺序复算 = `5d04470f…`，**复现一致** |
| 正式验收器 | `accept_e0c.py --results-dir` → `FAIL`（exit 1），唯一失败 `C9`（墙体 PSLR `2.664330228102982 < 3.0`），`C12/C13` PASS |

## 2. 必须更正的三条表述

### E-1 “两份 `e0c_results.json` 不同仅因放行编号/来源/时间戳” —— **不成立**

实测两次运行的结果 JSON 有 **17 个路径不同**：`/repeat_run` 整块、`/resource/*` 5 项、`/preflight/summary/elapsed_s`、`/files_sha256*` 5 项、`/git/working_tree_clean`、`/output_dir`、`/command`、`/generated_at`。而且 `approval_ref` 两次**相同**，两份文件里**没有 `source` 键**，所以“放行编号/来源”这一解释本身也不对。

正确表述：**“两次运行的差异全部落在运行编排/资源/时间戳字段，`groups`、`cases`、`cal`、`lambda_loo`、`air_loo_raw` 与 `metrics_sha256` 逐位相同。”**

### E-2 “`worker_meta.json` 为原始证据，未洗改” —— **对 run-1 不成立**

run-1 的 `worker_meta.json` 在进程结束后被编排器回填了 `results_sha256`（C12 之后才有的哈希）并写入绝对路径 `_dir`（`a_e0_c.py:1523,1662-1664`）；run-2 的 `worker_meta.json` 未被改动。

正确表述：**“`worker_meta` 是运行后由编排器补齐的记账文件：`results_sha256` 为事后回填、`_dir` 为绝对路径；两进程的 `run_id/pid/时间窗/exit_code/peak_rss_mib` 未被改写。需要‘进程原始写盘’的复核应改用 `run.log` 与 `e0c_repeat.json` 的时间窗，二者与 `worker_meta` 一致。”**

### E-3 “三份 `e0c_results.json` 只差放行编号/来源/时间戳” —— **相对 `b63e217` 说过宽**

对 `b63e217` 归档包，两次运行结果分别有 34 / 18 个路径不同（含旧/新 C12 块、resource 汇总），但**全部科学指标一致**。

正确表述：**“三份结果 JSON 的科学指标（`groups`/`cases`/`cal`/`lambda_loo`/`air_loo_raw`/`metrics_sha256`）逐位相同；差异集中在 C12 块、资源计数与时间戳。”**

## 3. 打包口径的两条披露（不影响 14/14）

1. **zip 只逐字节含 14 个载荷文件中的 6 个**：其余 8 个（含 `e0c_arrays.npz`、`e0c_air_loo.json`、`run.log` 等）是**引用**到 `experiments/A/A-Q1-E0/e0c/results-r2/` 与 `b63e217` 的 git blob，复核时按“清单 + 被引用文件”核对，故 14/14 成立但**不是**“14 个载荷都在 zip 里”。要么补全 zip，要么在 README 明确“zip 为索引包”。
2. **`e0c_repeat.json#total_wall_time_s = 286.763` ≠ 两次 `wall_time_s` 之和 `280.647`**：前者是外层计时（含 2.274 s 间隔与启动）。预算在三种口径下都成立（求和 280.647 / 跨度 285.978 / 控制台 288.5 s ≤ 600），但字段名容易被读成“两进程合计”，建议改名为 `outer_elapsed_s` 或在 runbook 注明口径。

## 4. 对统筹裁定的影响

- `C9` 硬停、`E0-T` 不放行的结论**不变**；本勘误只改**措辞与打包口径**，不改任何数字。
- 若统筹需要“两次独立进程”的**不可洗改**证据，当前可用的最强组合是：`run.log`（两次 START/END/EXIT）+ `e0c_repeat.json#runs` 的窗口 + 两份 `worker_meta` 的 `pid/exit_code`；`worker_meta` 的 `results_sha256` 应视为事后记账，不作独立性依据。
- 建议在 `results-r2` 入库前：补全 zip 载荷（或改称索引包）、给 `total_wall_time_s` 加口径注、把本文件与复核报告一起归档。

## 5. 附件

- 独立复核报告：`S4_evidence_verification.md`（逐项 PASS/FAIL、17 条 JSON 差异全表、哈希对照）
- 复核脚本与产物：`tmp/r2verify/`（raw/LF 双口径清单重算、zip 成员比对、两进程元数据比对）
