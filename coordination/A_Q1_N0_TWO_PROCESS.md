# A-Q1-N0 合成双进程证据包（`E0-N0-C12-SYNTHETIC-1`）

| 项 | 值 |
|---|---|
| 契约 | `E0-N0-1`（产物）+ `E0-C-C12-REPEAT-1`（两进程）+ `E0-N0-ACCEPT-2`（验收口径） |
| 入口 | `solutions/A/run_n0_synthetic.py`（新增；`worker` / `combine` / `two-process` 三模式） |
| 交付包 | `experiments/A/A-Q1-E0/n0/synthetic_two_process/` |
| 生成提交 | `1af71fe`（`implementation_sha`；工作区 `working_tree_clean=true`） |
| 基线 | `origin/main = c7b841e`；`n0_config.json` LF `ec396737…`（8,444 B） |
| 预登记 | 外部冻结文件 `e0_n0_prereg.json`，SHA256 `721eb744…`（`E0-N0-ACCEPT-2`） |
| 性质 | **纯合成夹具**（`synthetic=true` / `citable=false`），不是 N0 实测，不得进入论文/冻结材料 |
| 结论 | 两进程 **exit 0/0**、结果与数组**逐字节一致**；契约探针 **READY 721/721**；正式验收器 **13/14 PASS**，唯一 FAIL 为 `N9`（合成值对真实归档，预期 `S9`），`insufficient=[]` |

> **一句话：** codex 要求的“两个独立进程经同一入口使用合成夹具，记录各自实际退出码、
> `worker_meta.json` 和产物摘要”已经落地；`N13`（两进程证据）由验收器独立判 **PASS**。
> `N9` 失败是合成夹具的**预期**行为（`c0` 与 `b63e217` 真实基线不等），不是接口或方法问题，
> 也不构成 B-02 放行依据。

---

## 1. 本轮新增的入口

```text
python solutions/A/run_n0_synthetic.py
  --mode worker --run-index {1,2} --out DIR      # 一个独立进程：门禁 → 求解 → 打包
  --mode combine --run1 DIR1 --run2 DIR2 --out PKG
  --mode two-process --out PKG --runs-dir DIR    # 顺序拉起两个 worker 子进程
```

- `worker`：`preflight(32) → dryrun(11) → N0 合成求解 → 相位证据 → 打包 →
  worker_meta.json / run_record.json / SHA256SUMS.txt`；
- `combine`：run-1 为顶层、run-2 放 `repeat/`，`e0c_repeat.json` 的 11 个字段
  **全部从实际落盘字节重算**，并逐项核对两进程的时间窗、PID、退出码、预算；
- `two-process`：父进程顺序启动两个 `worker` 子进程，记录**子进程实际退出码**
  并与 `worker_meta.exit_code` 逐项核对，再 `combine`，写 `two_process.json`。

相对 `6035728` 的打包器，新增/修正：

1. `.npz` 改为**固定 zip 时间戳**写出（与 `a_e0_c.save_npz_deterministic` 同口径），
   否则 `np.savez` 把墙钟写进成员时间戳，两次序列化“数组相同、字节不同”，
   `N13` 的 `arrays_sha256` 相等与 npz 字节一致会永远过不了；
2. 台账不再登记 `SHA256SUMS.txt` 自身（避免哈希自指）；
3. `.dat` 审计钩子：进程内任何 `.dat` 打开都计数，证据里必须为 `0`。

## 2. 两进程实测（真实 PID / 退出码 / 时间窗 / 预算）

| 项 | run-1 | run-2 |
|---|---|---|
| PID | **12680** | **17900** |
| 实际退出码 | **0** | **0** |
| 开始（UTC） | `2026-11-28T15:42:58.023Z` | `2026-11-28T15:44:31.916Z` |
| 结束（UTC） | `2026-11-28T15:44:29.537Z` | `2026-11-28T15:46:03.083Z` |
| 墙钟 | 91.515 s | 91.167 s |
| 峰值 RSS | 258.031 MiB | 257.969 MiB |
| 结果文件 | `e0c_results.json` | `repeat/e0c_results.json` |
| 数组文件 | `e0c_arrays.npz` | `repeat/e0c_arrays.npz` |

- 时间窗严格不重叠：run-1 结束 `15:44:29.537` < run-2 开始 `15:44:31.916`；
- 合计墙钟 **182.682 s ≤ 600 s**；两次峰值 RSS 均 **≤ 4096 MiB**；
- 退出码 `[0, 0]`，在冻结 prereg 的 `allowed_exit_codes=[0,3,4]` 内；
- `worker_meta.json` 与 `repeat/worker_meta.json` 的 `run_id/pid/exit_code/
  started_at/finished_at/peak_rss_mib` 与 `e0c_repeat.json` 逐项一致（验收器 `N13` 已独立核对）；
- 两次产物：
  - `results_sha256` 均为 `1c89c26b853d9360193d3c9241f9bca671af1ff2833f14e83e844a26e39877bb`
  - `arrays_sha256` 均为 `95fae44accb132afe0515a7986369b303a45960e213e2b2d2f46b58b75d04794`
  - `metrics_sha256` 均为 `c758f2250d4be9d87d7913ae04113cac1569cf76dd13cc95d953fb71444364f9`
    （验收器独立重算，`metrics_max_abs_delta = 0.0`）
- `real_dat_files_opened = 0`；`frozen_artifacts_unchanged = true`；无 `n0_frozen.json`。

## 3. 门禁日志（`preflight 32/32`、`dryrun 11/11`）

- `preflight.json`：**32/32**，逐项真实断言，例如 `worktree_clean_tracked`、
  `n0_config_lf_sha256_frozen`、`prereg_thresholds_match_config`、
  `frozen_e0c_{results,arrays,air_loo}_ledger`、`no_n0_frozen_artifact`、
  `out_dir_not_frozen_dir`、`solver_entry_api`、`package_module_api` 等；
- `dryrun.json`：**11/11**，真跑
  `load_config → Setup → generate_synthetic_pool → calibrate_pool → align_spectra →
  build_rank2_basis → 相位证据 → 夹具 35 项映射 → 玩具包写盘 + selfcheck`，
  并核对冻结产物零改动、`.dat` 打开计数为 0；
- 两份日志都带 `"mode": "n0-synthetic"` / `"synthetic": true`，并在 `note` 里写明
  **不是 E0-C 实测 preflight/dryrun 的转发**；真实 N0 放行后仍须按 E0-C 同款门禁重跑。

## 4. 探针与正式验收器（外部独立工具，本轮原样调用）

| 工具 | 结果 |
|---|---|
| 生产侧契约探针 `probe_producer.py`（`E0-N0-PRODUCER-CONTRACT-1`） | **`READY`，721/721 ok，0 missing / 0 mismatch**（exit 0） |
| 正式验收器 `accept_e0n0.py`（`E0-N0-ACCEPT-2`） | `N1–N8、N10–N14` **全 PASS**；`N9` **FAIL** → `stop_condition = S9`，`failed_checks=["N9"]`，`insufficient_checks=[]` |

关键判读点：

- **`N13`（两进程 C12）PASS**：独立核对了 2 条记录 × 11 个字段、PID 互异、
  时间窗顺序、结果/数组字节一致、预算、两份 `worker_meta`、`preflight 32/32` +
  `dryrun 11/11`；
- **`N7` PASS**：`shifts_ns = [0, 0.01475, 211.973, …, 625.38375]`，
  簇内 `≤ 0.1 ns`；`coherence` 数组与 JSON 一致（合成夹具同簇两组谱相同，`ρ≈1`）；
- **`N12` PASS**：`implementation_sha == git.head_sha == 1af71fe`、
  `main_commit == git.origin_main_sha == c7b841e`、
  `n0_config_sha256 == ec396737…`、`prereg_sha256 == 721eb744…`、
  `input_manifest_sha256` 由 96 条输入重算一致；
- **`N9` FAIL 是预期**：它要求 `c0` 臂与 `b63e217` 真实归档基线
  （dB ≤ 1e-6、m ≤ 1e-9）逐值相等；本包是合成夹具，`air_loo_supp_db[0]`
  为 `12.157692`（基线 `4.190327`，Δ `7.967366`），必然不等。
  这正是“基线等价性门仍生效”的证据，**不是**接口读不了包（探针已 `READY`，
  `N1–N8/N10–N14` 都读得到并独立重算了数值）。

## 5. 复跑命令

```sh
# 0) 依赖：冻结 prereg 由验收方维护（本分支不含）；用 E0N0_PREREG 指定
export E0N0_PREREG=/path/to/e0_n0_prereg.json     # PowerShell: $env:E0N0_PREREG=...

# 1) 一条命令产出两进程证据（顺序执行，约 3–4 min；合计 < 600 s）
python solutions/A/run_n0_synthetic.py --mode two-process \
    --out experiments/A/A-Q1-E0/n0/synthetic_two_process \
    --runs-dir tmp/n0_two_runs --overwrite

# 2) 结构预检（预期 READY 721/721）
python <probe_producer.py> --results-dir experiments/A/A-Q1-E0/n0/synthetic_two_process \
    --contract <e0_n0_producer_contract.json> --prereg "$E0N0_PREREG"

# 3) 正式判读（预期：仅 N9 fail / S9，exit 1）
python <accept_e0n0.py> --results-dir experiments/A/A-Q1-E0/n0/synthetic_two_process \
    --prereg "$E0N0_PREREG" --repo .

# 4) 入口自检（12 项，约 22 s）
python solutions/A/test_run_n0_synthetic.py -v
```

包内 `verify/probe.json`、`verify/accept.json` 是本轮上述两次外部工具调用的原始报告
（`verify/probe.log`、`verify/accept.log` 为控制台输出）。

## 6. 交付物与台账

`experiments/A/A-Q1-E0/n0/synthetic_two_process/SHA256SUMS.txt` 共 **17 行**，覆盖：

| 文件 | SHA256（前 12 位） |
|---|---|
| `e0c_results.json` | `1c89c26b853d` |
| `e0c_arrays.npz` | `95fae44accb1` |
| `e0c_air_loo.json` | `085925d9ece6` |
| `e0c_repeat.json` | `abd6bd9abf66` |
| `preflight.json` | `ddb49de9291b` |
| `dryrun.json` | `3aa33dd9d23f` |
| `phase_evidence.json` | `f4626f4a14d2` |
| `worker_meta.json` | `827b4546ae3d` |
| `repeat/worker_meta.json` | `cc459d0f1c0a` |
| `repeat/e0c_results.json` | `1c89c26b853d`（与顶层同字节） |
| `repeat/e0c_arrays.npz` | `95fae44accb1`（与顶层同字节） |
| `run.log` / `two_process.json` | `da04efc12b41` / `ce8bfa2da53c` |
| `verify/probe.json` / `verify/accept.json` | `4561041c5f83` / `9bbc0e58b3c0` |
| `verify/probe.log` / `verify/accept.log` | `84d76ae1d099` / `7121d75e3286` |

入口自检：`solutions/A/test_run_n0_synthetic.py` **12/12 OK**（含 preflight 32 项、
dryrun 11 项、worker 退出码回填、combine 摘要回填、数组篡改/时间窗重叠/退出码不同
三个拒绝用例、确定性 npz、`.dat` 计数）。

## 7. 边界与待办（必须随包引用）

1. **合成夹具**：`synthetic=true`、`citable=false`，`real_dat_files_opened=0`；
   `P1/P2/c0` 的数值不是 N0 方法的真实结论。
2. **数组来源**：本包沿用 `from_prototype_synthetic` 的夹具路径——
   `xcluster__p_cal/p_sup`、`air_loo__p_cal/p_sup` 由原型声明的 Supp 值反构
   （总功率均分到 63 通道），**不是真实逐通道谱**。真实 `execute` 路径必须直接从
   求解器导出真实数组；本轮不改这条边界，也不把它写成“已解决”。
3. **唯一 FAIL 是 `N9`**，对应 `S9` 硬停：`c0` 与真实归档基线不等。合成包本来就不该相等；
   不要把它读成“验收失败”，也不要据此放行 B-02 / E0-T / S2。
4. **`phase__coherence` 全为 `ρ≈1`**：合成夹具同簇两组生成的谱相同，是夹具性质；
   `d1_min_abs_inner = 0.0` 是正确 Gram-Schmidt 的**预期数值证书**（不是越大越好）。
   `my_deepseek` 的 ACCEPT-3 应独立从 `phase_evidence.json` 复算这两项。
5. **冻结 prereg 是外部文件**（`E0-N0-ACCEPT-2`，SHA `721eb744…`）：本分支不复制它；
   复跑时用 `--prereg`/`E0N0_PREREG` 指向同一文件，否则 `N12` 的 `prereg_sha256`
   绑定会（正确地）拒绝。
6. **`implementation_sha = 1af71fe`** 是生成本包时的干净 HEAD；证据提交本身是后续提交，
   所以“证据提交号 ≠ 包内 `implementation_sha`”属正常，验收只看包内三处自洽（`N12`）。
7. 未实现 `--mode execute`、未读任何 `.dat`、未改数值内核/阈值、未改 `accept_e0n0.py`、
   未写 `n0_frozen.json`；`e0c/results` 的冻结台账在 `preflight`/`dryrun`/运行后
   三次核对均零改动。

---

**Next owner:** `@my_deepseek` 用 ACCEPT-3 独立验收本包（探针、`N13` 两进程、配置绑定、
`phase__coherence`/`d1_min_abs_inner` 独立复算、禁写冻结产物），回报判定与差异；
`@codex` 裁定 N0 B-02。**B-02 / E0-T / S2 均未放行。**
