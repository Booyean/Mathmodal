# A-Q1-E0-C 执行清单（放行前自检 · 允许数据 · 复跑命令 · 门槛与停止条件）

- **任务 / 分支**：E0-C 执行清单准备 / `data/a-q1-e0-c-checklist`
- **主责**：`dsh`（数据与求解）；放行与验收：`codex`；前置 `E0-S` 独立验收：`my_deepseek`
- **依据**：`experiments/A/A-Q1-E0/PLAN.md`（`073511c0…5a88`）、`experiments/A/A-Q1-E0/config.json`（`schema_version=3`，LF 归一化 `8fb6821f…e06a`）、`coordination/A_Q1_SPLIT.json`（`A-Q1-SPLIT0` 冻结，LF `d623da4e…8b3a`）、`coordination/A_Q1_E0_S_DECISION.md`、`solutions/A/data_contract.md`（`D0-4`）、`solutions/A/fold_gate_contract.md`（`D1-2`）、`solutions/A/e0_s1s2_contract.md`
- **状态**：**清单 + 元数据自检 + 正式执行入口已交付（`a_e0_c.py`）**。截至本分支，E0-C **未获统筹放行**，`E0-T` 冻结前不得触碰；入口的 `--mode execute` 强制要求 `--approval-ref`，未放行时只能跑 `--mode check`（不解析采样）。

> 本清单只回答四件事：**能用哪些数据、用什么命令复跑、什么算通过、什么必须停**。不产生、也不预设任何真实测距结论。

---

## 1. 允许使用的数据（白名单，严格锁定）

### 1.1 磁盘位置与组定义

A 题原始附件在仓库内：

```
竞赛题目/A 题：单发多收下的雷达信号处理及成像问题/附件/附件2-测距数据/
```

`group_key` 规则见 `data_contract.md` §1.2：`附件2-测距数据/` 下的组目录名即组名，`dataset` 为去掉最外层 `附件` 后的父目录。下表的磁盘相对路径均相对 A 题根目录。

### 1.2 允许读取的 12 组（96 个 `.dat`）

| # | `group_key` | 磁盘相对路径 | 角色 | `split` 标签 | 文件数 | 共同包数 | 合计字节 |
|---|---|---|---|---|---:|---:|---:|
| 1 | `空场数据/data1` | `附件/附件2-测距数据/空场数据/data1` | 空场模板原点 / LOO 折 | — | 8 | 4 | 8,192,896 |
| 2 | `空场数据/data2` | `附件/附件2-测距数据/空场数据/data2` | 空场 LOO 折 | — | 8 | 5 | 10,241,120 |
| 3 | `空场数据/data3` | `附件/附件2-测距数据/空场数据/data3` | 空场 LOO 折 | — | 8 | 2 | 4,096,448 |
| 4 | `空场数据/data4` | `附件/附件2-测距数据/空场数据/data4` | 空场 LOO 折 | — | 8 | 4 | 8,192,896 |
| 5 | `空场数据/data5` | `附件/附件2-测距数据/空场数据/data5` | 空场 LOO 折 | — | 8 | 3 | 6,144,672 |
| 6 | `空场数据/data6` | `附件/附件2-测距数据/空场数据/data6` | 空场 LOO 折 | — | 8 | 4 | 8,192,896 |
| 7 | `空场数据/data7` | `附件/附件2-测距数据/空场数据/data7` | 空场 LOO 折 | — | 8 | 2 | 4,096,448 |
| 8 | `空场数据/data8` | `附件/附件2-测距数据/空场数据/data8` | 空场 LOO 折 | — | 8 | 3 | 6,144,672 |
| 9 | `空场数据/data9` | `附件/附件2-测距数据/空场数据/data9` | 空场 LOO 折 | — | 8 | 4 | 8,192,896 |
| 10 | `空场数据/data10` | `附件/附件2-测距数据/空场数据/data10` | 空场 LOO 折 | — | 8 | 6 | 12,289,344 |
| 11 | `墙体数据/data1-42cm` | `附件/附件2-测距数据/墙体数据/data1-42cm` | 校准目标（墙） | `wall_cal` | 8 | 3 | 6,144,672 |
| 12 | `金属板数据/data1-69cm` | `附件/附件2-测距数据/金属板数据/data1-69cm` | 校准目标（金属板） | `metal_cal` | 8 | 3 | 6,144,672 |

- 合计 **12 组 / 96 个 `.dat` / 88,073,632 B（≈84.0 MiB）**。上表的文件数、共同包数与合计字节来自 R0 清单 `recon/manifests/a_dat_manifest.csv`，不是本清单的估计。
- 空场 10 组只用于：① 聚合空场模板；② 9 组选参 + 1 组评价的 10 折 LOO（`λ_cal, λ_inv ∈ {1e-4,1e-3,1e-2}²`，固定 9 组预算）。**不用目标组参与 λ 选择。**

### 1.3 明确禁止读取（本轮）

| 禁止对象 | 数量 | 说明 |
|---|---:|---|
| `wall_test` 组 | 10 | 冻结拆分中的检验组，含 `data20-73cm`、`data6-121cm` 等；E0-T 前不读、不看、不统计 |
| `metal_test` 组 | 10 | 同上，含 `data5-60cm`、`data6-99cm` 等 |
| 其余 18 组留出样 | 18 | 即上述 20 组中除 E0-T 指定的 `墙体数据/data20-73cm`、`金属板数据/data5-60cm` 之外的组；其中 **16 组内插 + 2 组外推**（`墙体121cm`、`金属99cm`）。`config.json` 记的 `16` 是内插口径，执行时 18 组一律不读 |
| `附件3-成像数据` 全目录 | 33 + 28 组 | 属 Q2/Q3，不在 Q1 E0-C 范围 |
| `附件1-数据读取函数` | — | 仅协议依据，不是输入信号 |
| B 题全部数据 | — | 未选题 |

**边界铁律**：E0-C 主运行只允许打开上表 96 个 `.dat`；任何对禁止组的 `open/stat/glob` 都算越界，触发硬停止并登记。`E0-T` 指定的两组在冻结前一律不读。

**入口侧的强制约束（E0C-CL-3）**：`solutions/A/a_e0_c.py` **不调用** `a_dat_reader.discover_groups()`（该函数 `rglob("*.dat")` 整棵 A 题目录，会 glob 到禁止组），组清单由本表显式给出；每个组目录、每个待读文件在 `stat`/`open` 之前都要过 §2.4 的读前路径校验。

### 1.4 原件与版本

| 项 | 值 |
|---|---|
| 原始数据基线 | `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9` |
| A 题 `.dat` 清单总体 SHA256 | `86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06`（881 文件 / 801,111,612 B） |
| 逐文件清单 | `recon/manifests/a_dat_manifest.csv`（`rel_path,size_bytes,sha256`） |
| 冻结拆分 | `coordination/A_Q1_SPLIT.json`，LF blob `d623da4e…8b3a` |
| 配置 / 方案 | `config.json` LF `8fb6821f…e06a`；`PLAN.md` `073511c0…5a88` |

原件只读：不复制、不改名、不改写、不插补、不剔除 `-32768`（D0 只登记）。任何“数据修正”都不在本清单授权内。

---

## 2. 复跑命令

### 2.1 本轮可执行的元数据自检（不解析采样，可立即跑）

```powershell
# 1) 清单自检：锚点、白名单、96 个文件身份、读前路径校验、E0-S 前置、D1-2 契约
python solutions/A/e0c_preflight.py `
  --out experiments/A/A-Q1-E0/e0c/preflight.json

# 2) 自检测试（含篡改反例：缺行、改大小、改 SHA、掺入检验组、E0-S 门失败、
#    符号链接/目录联接指向白名单外、realpath 逃逸）
python solutions/A/test_e0c_preflight.py

# 3) 正式入口的 check 模式：放行前自检 + 12 组白名单边界扫描（不解析采样）
python solutions/A/a_e0_c.py --mode check

# 4) 正式入口的自检测试（合成 .dat 端到端 + 门槛 + CLI 边界；零真实信号）
python solutions/A/test_a_e0_c.py
```

- 退出码：`e0c_preflight.py` `0` = 放行前条件（`preconditions_pass`）全部通过；`1` = 任一条件失败；`2` = 用法/环境错误。JSON 始终写出。
- `a_e0_c.py --mode check` 退出码：`0` = 入口就绪（`ready_for_execute`）；`1` = 前置或边界扫描有问题。
- 两级判定，避免把“条件齐了”误读成“可以开跑”：
  - `preconditions_pass`：锚点、白名单、96 个文件身份、读前路径校验、E0-S 前置、D1-2 契约全部通过；
  - `execution_ready = preconditions_pass AND a_e0_c.py 已交付`；**现已为 true**（入口已交付）；
  - `overall_pass` 只等于 `preconditions_pass`，**不等于放行**。`--no-hash` 会把 `data.hash_skipped` 记为失败，调试模式不能充当放行证据。
- 自检只做：读 `config.json` / `PLAN.md` / `SPLIT.json` / `E0-S` 结果 JSON / R0 清单；对白名单 96 个 `.dat` 只算 `size + SHA256`（不解析包头、不读采样语义）；落盘一份 JSON。
- 自检**不等于** E0-C 通过，也不构成放行。它只证明“放行前该齐的东西齐了、该锁的东西没被改、越界文件没被打开”。

输出 JSON 关键字段：`preconditions_pass`、`execution_ready`、`overall_pass`、`checks[]`（`id/group/passed/detail`）、`summary.failed_ids` / `summary.blocking_ids`、`data_allow_list`、`data.signal_files_hashed`、`data.opened_dat_files`、`data.path_guard`（`guarded_files` / `rejections`）、`anchors`、`open_items`。

### 2.2 E0-C 主运行命令（入口已交付，**未放行，现在不得执行**）

入口：`solutions/A/a_e0_c.py`（`CONTRACT_VERSION = "E0-C-1"`）。三种模式：默认 `--mode check`；真实执行必须 `--mode execute --approval-ref <统筹放行编号/链接>`，否则直接退出码 `2`；`execute-worker` 是 `execute` 内部派生的单次运行入口。`--repeat-runs` 必须等于 `2`（C12 冻结契约 `E0-C-C12-REPEAT-1`，其它值直接退出码 `2`）。若输出目录已有 `e0c_results.json`，无 `--overwrite` 时拒绝启动（失败证据不得被覆盖）；若 `repeat_runs/run-2/` 已有旧证据，一律拒绝并提示换新目录。

```powershell
$env:OMP_NUM_THREADS="1"; $env:OPENBLAS_NUM_THREADS="1"
$env:MKL_NUM_THREADS="1"; $env:NUMEXPR_NUM_THREADS="1"

python solutions/A/a_e0_c.py --mode execute `
  --approval-ref <codex 放行消息编号/链接> `
  --repeat-runs 2 `
  --config experiments/A/A-Q1-E0/config.json `
  --split coordination/A_Q1_SPLIT.json `
  --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" `
  --out experiments/A/A-Q1-E0/e0c/results-r2 `
  --implementation-sha <impl-sha> `
  --parent-commit <parent-sha> `
  --main-commit <main-sha>
```

> 旧登记 `b63e217`（`e0c/results/`）是**一次**运行，缺少 `E0-C-C12-REPEAT-1` 要求的两进程证据，不再满足新 C12；不要用 `--overwrite` 覆盖它。放行后按上面的命令写到新目录（示例 `results-r2`），两次独立进程合计约 300 s。

退出码：`0` 全部门槛可冻结（写 `e0c_frozen.json`）；`1` 灰区/不可冻结；`2` 用法错误（缺 `--approval-ref`、拒绝覆盖）；`3` 硬停止（前置未过、越界、`valid_rx<63`、NaN/Inf、超预算、空场 `<6 dB`、`abs_err>10.71 cm` 等）。

必须产出：

| 文件 | 内容 |
|---|---|
| `e0c_results.json` | 机器可读：版本锚点、`approval_ref`、参数、逐组指标、逐门 `value/threshold/status/passed`、`hard_stops` / `gray_reasons`、资源用量、`files_sha256`、`repeat_run` 摘要 |
| `e0c_arrays.npz` | 第 1 次运行的交付数组：逐通道校准谱、对齐空场谱、`h_rel`、减除前后谱、`S_eff`、压缩响应、剖面与采样轴 |
| `e0c_air_loo.json` | 10 折 × 9 组 `Supp_air-LOO`、`J_air`、`min/median`、选中对与切换原因 |
| `e0c_frozen.json` | **仅当全部门槛可冻结时**写出：`(λ_cal, λ_inv, η_wall)`、实现 SHA、配置 SHA、冻结时间 |
| `e0c_repeat.json` | **C12 两次独立运行清单**：`runs[2]`，每项含 `run_id`/`pid`/`started_at`/`finished_at`/`wall_time_s`/`results_file`/`results_sha256`/`arrays_file`/`arrays_sha256`；`runs[0]` 绑定顶层交付文件，`runs[1]` 绑定 `repeat_runs/run-2/` |
| `repeat_runs/run-2/` | 第 2 次独立进程的完整产物：`e0c_results.json`、`e0c_arrays.npz`、`e0c_air_loo.json`、`run.log`（及可冻结时的 `e0c_frozen.json`）；与第 1 次 PID/时间窗/文件均不同 |
| `run.log` / `SHA256SUMS.txt` | 两次运行的诊断日志与全部产物的 SHA256（含 `e0c_repeat.json` 与 `repeat_runs/run-2/`；`e0c_results.json` 自身摘要只在 `SHA256SUMS.txt` 中，避免自引用） |

实现约束（与 `PLAN.md` 一致，不得夹带 `N0`）：

- 链路固定 `M0-Cal-Base → M0-DW-Base（α_g ≡ 1.0）→ M0-Rng-Base（P_norm,eff 主统计量）`；`P_norm`、`P_env` 仅作对照。数学原语直接复用已验收的 `a_e0_s1s2.py`，不另写一套。
- 折迭统一用 `solutions/A/a_fold_gate.py`（`D1-2`），每包 16000 点 → 4 段 × 4000 点，等权折叠、无相位补偿；任一通道 NaN/Inf 整包拒绝。
- 有效通道必须 **63/63**（含 `ref_idx=28`），禁止静默丢通道或补零；`valid_rx < 63` 即硬停止。
- 搜索区间 `[0.15, 2.00] m`：粗 1 mm、细 0.1 mm；`PSLR` 主瓣保护半宽 `1.6031e-1 m`。
- 墙体首峰规则默认 `η_wall=0.25`；`{0.15,0.25,0.35}` 只允许在 `墙体数据/data1-42cm` 上按“满足条件且最接近默认 0.25”核对（确定序：`(round(|η-0.25|,12), η)`，即 `0.25 → 0.15 → 0.35`），冻结后不得再改。金属板用全局 `argmax`。
- 单进程单线程；每次运行总墙钟 ≤ 600 s、峰值 RSS ≤ 4096 MiB；两次顺序运行合计墙钟也是登记的 `resource.wall_time_s`（须 ≤ 600 s），任一时刻只有一个进程。

### 2.3 复跑登记规则

- 先提交实现与测试（implementation commit），再 `git archive`/新 worktree 从该提交运行，`--implementation-sha` 填该提交，`--parent-commit` 填其父提交，`--main-commit` 填运行时 `origin/main`。
- 结果单独提交（只加 `experiments/A/A-Q1-E0/e0c/` 产物）。失败实验也保留提交、配置、日志、退出原因，不删证据。
- 同一环境内重复运行应逐位一致；跨机只要求指标一致，不宣称数组逐位（`E0-S` 验收已记录该边界）。
- **C12 的两次独立运行（`E0-C-C12-REPEAT-1`）**：`--mode execute` 顺序启动**两个独立进程**，每个进程都把整条链路（preflight → 读 96 个 `.dat` → 选参 → 校准 → DW → 测距 → 门槛）完整跑一遍，互不共享数组/中间结果。第 1 次运行写交付目录顶层（`e0c_results.json`/`e0c_arrays.npz`），第 2 次写 `repeat_runs/run-2/`。
- `e0c_repeat.json#runs` 记录两次运行的 `run_id`、`pid`、`started_at`/`finished_at`、`wall_time_s`、`results_file`/`results_sha256`、`arrays_file`/`arrays_sha256`。**PID 必须不同、时间窗必须顺序不重叠、结果/数组文件路径必须不同**；两次的组指标（dB 1e-6、cm/m 1e-9）必须一致。顶层 `repeat_run` 只放摘要与 `runs_file: "e0c_repeat.json"`，**不内嵌 runs**（否则 `runs[0].results_sha256` 会变成 results 文件自引用，无法闭环）。
- 若两次运行的数组/指标/分类/停止原因不一致，运行器拒绝登记；**不做择优**：第 1 次运行就是交付运行。`--repeat-runs` 只接受 `2`；“同一批数组两次序列化”或同一 PID 的两条记录都不构成 C12 证据。
- 资源预算按两次进程的总墙钟计（合成端到端实测约 **300 s** / 单次约 150 s < 600 s）。

### 2.4 读前路径校验（E0C-CL-3 新增，回应统筹“stat/读取前校验实际路径”）

`solutions/A/e0c_preflight.py` 新增并导出 `guard_group_dir()` / `guard_dat_path()`，`a_e0_c.py` 复用同一实现。顺序即安全边界：

1. **词法归属**（只做字符串规范化，不触碰文件系统）：组目录必须在数据根之下；待读文件必须是白名单组目录的直接子项；
2. **逐级反重解析点**：从数据根到组目录的每一级、以及文件本身，先 `lstat`；带 `FILE_ATTRIBUTE_REPARSE_POINT`（符号链接、Windows 目录联接、挂载点）一律拒绝。仅查 `os.path.islink()` 会漏掉目录联接（实测 `islink=False`、属性 `0x400`）；
3. **真实路径包含性**：`realpath` 必须同时落在组真实目录与数据根真实路径之内；
4. 通过后才 `stat`/`open`，且**只使用校验返回的真实路径**；未通过记入 `data.path_guard.rejections` 并计入 `data.path_guard` 失败，绝不打开。

反例（`test_e0c_preflight.py`，均实际跑通）：

| 反例 | 构造 | 断言 |
|---|---|---|
| 词法越界 | 文件不在白名单组目录下 | `PathGuardError`（“直接子项”） |
| 文件级重解析点 | 注入 `lstat` 返回 `0x400` | 拒绝，不跟随 |
| `realpath` 逃逸 | 注入 `realpath` 指向根外 | 拒绝（“越出白名单”） |
| 组目录本身是联接 | `cmd /c mklink /J` 指向根外真实目录 | `data.path_guard` 失败；`signal_files_hashed==0`；一个文件都不打开 |
| 单文件逃逸（端到端） | 组内 8 文件中 1 个 `realpath` 指向根外 | `rejected==1`，其余 7 份仍摘要，逃逸项未打开 |

---

### 2.5 E0-PREREG-3 交付接口（E0C-CL-4 新增；E0C-CL-5 补 C12）

`my_deepseek` 冻结的 `E0-PREREG-3`（`checks/A/e0_c_accept/accept_e0c.py`）与 `E0-C-C12-REPEAT-1`（`checks/A/e0_c_repeat_contract.json`）要求 execute 产物可直接机械验收；`a_e0_c.py` 现已按该契约落盘：

| 契约项 | 实现 |
|---|---|
| 顶层 `groups[12]` | 空场 10 组（`split="air"`，指标 `null`）+ 2 目标组（`wall_cal`/`metal_cal`，含 `d_hat_m`/`abs_err_cm`/`supp_dw_win_db`/`pslr_db`/`pnr_db`/`echo_ret_db`/`valid_rx`/`finite`/`status`/`gate_results`/`stop_reason`） |
| `inputs[96]` | 逐文件 `rel_path`（`附件/附件2-测距数据/<组>/<文件>`）、`size_bytes`、`sha256`；顺序与 R0 清单一致 |
| `array_map` + `p_cal/p_sup` | `{"air_loo_prefix":"air_loo","group_prefix":{2 组}}`；`air_loo__p_cal`、`air_loo__p_sup` 形状 `(9,10,63)`，仅凭它们可独立重算 90 个 `Supp_air-LOO` |
| `arrays_sha256`/`metrics_sha256` | 确定性 npz（固定 zip 时间戳）；`metrics_sha256` 按 `groups` 的 8 个键规范化 |
| C12 两次独立运行 | 两个独立进程（`pid` 不同）顺序各跑完整链路；`runs[0]` 绑定顶层 `e0c_results.json`/`e0c_arrays.npz`，`runs[1]` 绑定 `repeat_runs/run-2/`；`e0c_repeat.json#runs` 具备 `run_id`/`pid`/`started_at`/`finished_at`/`wall_time_s`/`results_file`/`results_sha256`/`arrays_file`/`arrays_sha256`；顶层 `repeat_run` 只放摘要 + `runs_file` |
| `resource.single_process` | `true`（每次运行单进程单线程；两次顺序执行，任一时刻一个进程）；四个线程变量均为 `"1"` |
| `e0c_air_loo.json` | `folds[10]`、`grid[9]{lambdas,folds[10].supp_db,j_air_db,min_db,median_db}`、`selected`、`switched`、`min/median_supp_db`、`j_air_default_db`、`eligibility` |
| 预览/阻断 | 空场 `status` 与目标 `status` 分别映射 `eligible` / `not_eligible_for_freeze` / `hard_stop`；仅全部门控可冻结才写 `e0c_frozen.json`（含 `lambdas`/`eta_wall`/`implementation_sha`） |

**指标口径（随结果登记，须与验收方一致）**：`Supp_dw-win`、`PNR`、`PSLR`、`d_hat` 由**交付数组**按 `E0-PREREG-3` §5 的离散重算口径产生：

- `τ` 轴非均匀、严格单调：`[0,20)` ns 用 0.05 ns（覆盖直射波窗与目标峰），`[20,950]` ns 用 0.25 ns（`[50,950]` 与 PLAN §5.1 的 `m=200..3800` 完全对齐），`[999,1000)` ns 用 0.05 ns（跨 0/Tp 循环边界的左半主瓣）。
- 每通道直射波窗 `|wrap(τ−τ_dir)|≤1 ns` 恰为 PLAN 的 41 点；`τ_dir` 量化到 0.05 ns（≤0.025 ns）以对齐交付网格。
- 目标剖面 `P_after` 在 0.1 mm 网格 `[0.15,2.00] m`；`d_hat` 按预登记规则在该网格重选；`PSLR` 在同一网格计算。
- `BG_proxy` 取交付 τ 轴的 `[50,950] ns`（0.25 ns、3601 点）；`PNR` 取 `2·d_hat/c0` 在交付 τ 轴上的最近采样。

与 E0-S 的“连续时延 / 1 mm 网格”口径相比，上述离散化会带来微小差异；合成闭环实测 `C10` 重算差 `<1e-9`（dB/米），不影响门控。若统筹/建模要求改用连续口径，必须先升级 `E0-PREREG-3`（预登记版本变更），否则 `C10` 无法机械复算。

**独立验收器实测（合成，非真实数据）**：官方 `accept_e0c.py` 对合成端到端交付包给出 **`PASS`（C1–C15 全过）**；其中 C4 的 `inputs[]` 用真实数据 oracle 身份替换（合成 `.dat` 不可能携带真实 SHA），其余字段全部由生产链路产生。该结果只证明“接口/口径与检查器兼容”，**不证明**真实 E0-C 会通过门槛。

**`E0C-CL-6` 两进程合成包的生产者预检（2026-11-28，官方检查器实测）**：用 `python solutions/A/e0c_official_precheck.py --checker <main>/checks/A/e0_c_accept/accept_e0c.py` 在 12 组合成 `.dat` 上按生产链路跑**两个独立进程**，再由官方 `accept_e0c.py`（main `0386055`；`E0-PREREG-3` + `E0-C-C12-REPEAT-1`）验收：**C12 PASS**——`manifest_source="e0c_repeat.json#runs"`，两次 `pid` 为 26288 / 7604，时间窗 `09:24:53→09:27:21` 与 `09:27:23→09:29:52`（UTC）不重叠，`runs[0]` 绑定顶层 `e0c_results.json`/`e0c_arrays.npz`、`runs[1]` 绑定 `repeat_runs/run-2/`，用第二次运行的 npz 独立重算两组 `Supp/PSLR/PNR/d_hat/abs_err` 与交付 JSON 一致，`duplicate_serialization_detected=false`；C1–C3、C5–C15 全 PASS，**仅 C4 FAIL**——96 个合成文件总字节与 oracle 相同（`88,073,632 B`），但文件名不是真实白名单（`2026-01-01-00-00-00_16000_*` vs `2026-11-12-20-50-32_16000_*`），属合成夹具性质。该结果只证明**接口与 C12 证据形态**能被官方检查器机械接受，**不证明**真实 E0-C 会通过门槛；独立复验仍归 `my_deepseek`。

---

## 3. 通过门槛（可冻结条件）

全部数值取自 `config.json#gates_and_thresholds` 与 `PLAN.md` §5.2；本清单不新增、不放宽任何阈值。

| 阶段 | 检查 | 通过（可冻结） | 灰区（不可冻结） | 硬停止 |
|---|---|---|---|---|
| 前置 | D1-2 契约与验收 | `a_fold_gate.py` `CONTRACT_VERSION=="D1-2"`，且统筹已记录 D1-2 验收 | — | 未验收 / 版本不符 |
| 前置 | E0-S 合成闭环 | `e0_s1s2_results.json`：`overall_pass=true`、三例门全过、S2 `valid_rx=63`、数组与参数表 SHA 匹配 | — | 任一失败 |
| 数据 | 白名单完整性 | 12 组 × 8 文件齐全、非空、`size+SHA256` 与 R0 清单一致 | — | 缺文件/0 字节/哈希不符/出现禁止组 |
| 通道 | 有效接收通道 | `valid_rx==63` 且无 NaN/Inf（每组） | — | `<63` 或 NaN/Inf |
| 空场 | LOO 抑制 `min(Supp_air-LOO)` | `≥ 10.0 dB` | `6.0 ≤ min < 10.0 dB`：只允许在 9 组空场网格复核，仍 `<10` 即停、禁入 E0-T | `< 6.0 dB` |
| 目标 | 近距回波质量（两组校准目标各查） | `PSLR ≥ 3.0 dB` 且 `PNR ≥ 6.0 dB` | — | 任一 `<` 阈值 |
| 目标 | 校准测距误差 `abs_err` | `≤ 5.0 cm` | `5.0 < err ≤ 10.71 cm`：标 `not_eligible_for_freeze`，只做校准内诊断（`P_norm,eff` vs `P_norm`、`η_wall` 候选），不得冻结 | `> 10.71 cm` |
| 资源 | 墙钟 / 峰值 RSS | `≤ 600 s` / `≤ 4096 MiB` | — | 超预算 |
| 冻结 | `E0-Freeze` | 以上全部“可冻结”才写 `e0_frozen.json` 并锁 `(λ_cal, λ_inv, η_wall)` 与实现 SHA | — | 任一不满足 |

补充口径（必须写进结果说明，避免误读）：

- `10.71 cm = c0/(2B)` 是 1 个瑞利主瓣宽度；`5.0 cm` 约为 1.33 个距离采样步（`3.75 cm`）。两者都是工程门槛，不是精度承诺。
- `PNR` 的分母是**非目标区/晚延迟背景代理** `W_bg=[50,950] ns`，不宣称纯热噪声；`PSLR` 用 `P_norm,eff` 的粗剖面旁瓣区。
- 两组校准目标（`data1-42cm`、`data1-69cm`）在 V0/M0 阶段**已被探索过**（`A_Q1_SPLIT.json#explored_target_groups`），因此 E0-C 结果**不是盲测**，只能称“校准组复现/诊断”。
- 目录名里的 `42cm`、`69cm` 是标称距离标签，不是独立物理真值认证（`data_contract.md` O-D0-04）。

---

## 4. 停止条件与失败处置

触发**任一**条件即立即中止本次 E0-C，写出/保留 JSON 与日志，**禁止自动重跑、改种子/参数/阈值、扩样或补组**：

1. 越界读取：打开/统计了白名单以外的 `.dat`，或读取任 `*_test` 组、`附件3`、B 题数据。
2. 版本不符：`config.json` LF SHA、`PLAN.md` SHA、`SPLIT.json` LF SHA、`E0-S` 结果锚点任一不匹配。
3. 前置未过：D1-2 未验收；`E0-S` `overall_pass` 非真；实现 SHA 与结果登记不一致。
4. 数据异常：组文件缺失、0 字节、跨行 `sync` 交集为空、`valid_rx < 63`、任一通道 NaN/Inf、折叠抛 `FoldGateError`。
5. 门槛失败：空场 `min(Supp_air-LOO) < 6.0 dB`；近距 `PSLR < 3.0 dB` 或 `PNR < 6.0 dB`；校准 `abs_err > 10.71 cm`；或落入灰区后复核仍不达标。
6. 资源超限：墙钟 > 600 s 或峰值 RSS > 4096 MiB。
7. 任何未登记的自动扩样、阈值调整、`N0` 改进混入，或对 E0-T 的提前读取。

失败登记必须包含：实现提交 / 父提交 / 主线、配置与拆分 SHA、输入组清单、完整命令、环境（Python/numpy/OS/线程数）、墙钟与峰值 RSS、`stop_reason`、失败组与失败门、日志与产物 SHA256。

**回溯**：回到执行前最近一个通过验收的 `main` 提交（当前为 `81a066f`，含 E0-S 实现、登记与独立验收）；`PLAN.md` §6 记的 `f56dbc0` 是 D1-2 之前的旧回退点，已被 E0-S 验收取代。**该替代关系请统筹在放行时确认**；未确认前不修改 `PLAN.md`。

---

## 5. 结果登记与交接格式

`e0c_results.json` 至少包含（`E0-PREREG-3` §2.2 全字段）：

- `experiment_id="A-Q1-E0"`、`phase="E0-C"`、`scope`（明确“真实校准组、非盲测、不含 E0-T”）
- `implementation_sha` / `parent_commit` / `main_commit` / `branch`；`config_sha256`、`plan_sha256`（LF 口径）、`split_sha256`、`e0_s_results_sha256` 及匹配布尔、`fold_gate_contract_version="D1-2"`
- `environment`（Python/numpy/OS/线程）、`command`、`resource`（墙钟 s、峰值 RSS MiB、`single_process=true`）
- `methods`（`alpha_mode=fixed_1.0`、`n0_improvements_enabled=false` 等六项）
- `inputs[96]`、`air_loo_folds[10]`、`array_map`、`lambda_selected`、`eta_wall`
- `air_loo` 子表：9 组网格、每折抑制、`J_air`、`min/median`、选中对、是否触发切换及原因（另见 `e0c_air_loo.json`）
- `groups[12]`：`group_key`、`target_type`、`split`、`d_true_cm`（标称，仅评价用）、`d_hat_m`、`abs_err_cm`、`supp_dw_win_db`、`pslr_db`、`pnr_db`、`echo_ret_db`（诊断）、`valid_rx`、`finite`、`status`、`gate_results`、`stop_reason`
- `freeze{status,written}`，以及冻结的三元组（仅 eligible 时）
- `arrays_sha256`、`metrics_sha256`、`repeat_run`、`d_true_usage="evaluation_only"`、`files_sha256`、`stop_reason`

`repeat_run` / `e0c_repeat.json` 的机械可核验字段（供 C12 与验收方负例使用）：

| 位置 | 字段 | 含义 |
|---|---|---|
| 顶层 `repeat_run` | `n_runs` / `runs_file` | 固定 `2`，并指向 `e0c_repeat.json`；**不内嵌 `runs`**，避免 `runs[0].results_sha256` 自引用 |
| 顶层 `repeat_run` | `arrays_sha256` / `metrics_sha256` | 与顶层 `arrays_sha256`/`metrics_sha256` 相同 |
| 顶层 `repeat_run` | `arrays_identical` / `metrics_identical` / `metrics_max_abs_delta` | 两次运行逐位一致的声明；差值应为 `0.0` |
| `e0c_repeat.json#runs[]` | `run_id`、`pid`、`started_at`、`finished_at`、`wall_time_s` | 每次运行身份与时间窗；`pid` 必须不同、时间窗顺序不重叠、带时区 |
| `e0c_repeat.json#runs[]` | `results_file` / `results_sha256`、`arrays_file` / `arrays_sha256` | 相对交付目录的路径与实际 SHA256；`runs[0]` 绑定顶层文件，`runs[1]` 绑定 `repeat_runs/run-2/`，两两不同 |
| `e0c_repeat.json` | `arrays_identical` / `metrics_identical` / `metrics_max_abs_delta` / `problems` | 汇总判定与不一致清单（应为空） |

验收方的最小负例集（E0C-CL-5 建议）：① `runs[1]` 与 `runs[0]` 的 `pid`/时间窗/文件相同（重复序列化口径）→ 必须失败；② 两次运行复用同一 `arrays_file`/`results_file` → 必须失败；③ 缺少 `e0c_repeat.json` 或 `runs` 列表 → 必须失败；④ 证据文件被替换、SHA256 不符 → 必须失败；⑤ 时间窗重叠 → 必须失败；⑥ 第二次运行指标与交付不一致（且清单 SHA 已同步更新，以隔离“SHA 不符”这条门）→ 必须失败。作者测试 `test_a_e0_c.py` 已覆盖 ①②③④⑤⑥（E0C-CL-6 补齐 ③ 与 ⑥）。

频道回传用下表，数值直接抄 JSON，不手算、不四舍五入掩盖灰区：

| 组 | 类型 | `d_hat` | `abs_err` | `Supp_dw-win` | `PSLR` | `PNR` | `valid_rx` | 判定 |
|---|---|---:|---:|---:|---:|---:|---:|---|

---

## 6. 依赖、未知项与剩余阻碍

| 编号 | 事项 | 状态 / 需要什么 |
|---|---|---|
| B-01 | `solutions/A/a_e0_c.py` 主运行程序 | **已交付（E0C-CL-4/-6）**：`--mode check/execute/execute-worker`、`--approval-ref` 强制、C12 两独立进程运行与 `e0c_repeat.json`、`repeat_runs/run-2/` 证据、E0-PREREG-3 全字段接口、**83 项作者测试**（合成 `.dat` 端到端 + 7 类 C12 反例）。**已补**：CL-6 的两进程合成包已用官方 `accept_e0c.py`（main `0386055`）预检，**C12 PASS**，仅 C4 因合成文件名非真实白名单而 FAIL（见 §2.5）；独立复验仍归验证方。真实运行仍待 B-02 |
| B-02 | 真实信号执行放行 | **未获**。需 `codex` 核对本清单白名单、读前路径校验与停止条件后明确放行；放行前 `--mode execute` 一律拒绝 |
| B-03 | `E0-T` | **禁止**。须 E0-C 全部门槛可冻结并锁配置后单次盲评 |
| B-04 | 目标组标称距离与真实物理距离的关系 | 未知（O-D0-04）；只按标称标签报告误差，不宣称绝对测距精度 |
| B-05 | 实测 SNR / 直达波泄漏量级 | 未知；只有合成反例（`verify_e0_spec.py`）与 S2 数值，不能外推为实测结论 |
| B-06 | `η_wall` 候选核对仅 `data1-42cm` | 已由 PLAN 限定；冻结后不得改 |
| B-07 | 回退点 `f56dbc0` → `81a066f` 的替代 | 待统筹确认（见 §4） |
| B-08 | 阵列坐标 `positions_m` | M0 已批复 `098e17d`；读取/折迭阶段不受影响 |
| B-09 | R0 清单“总体 SHA256”的算法说明 | `recon/README.md` 写“按相对路径排序”，但实测只有按 **CSV 行序** 才能复现 `86305548…`；本清单自检按可复现行序实现，建议统筹安排一次文档更正（不改数据、不重算锚点） |
| B-10 | 冻结拆分的裸组名有跨数据集同名 | `data14-48cm` 同时出现在 `wall_test` 与 `metal_test`（分别是墙体与金属板的两个物理组）；按数据集限定后四折 40 组互斥。自检已按 `墙体数据/…`、`金属板数据/…` 限定，建议拆分说明补一句“组名以数据集限定” |
| B-11 | “16 组未触碰”的口径 | 20 个检验组减去 E0-T 的 2 组后剩 **18** 组；其中 2 组外推（`墙体121cm`、`金属99cm`）、**16** 组内插。`config.json#untouched_remaining_holdout_groups_count=16` 取的是内插口径，字段名未区分。执行时按“18 组一律不读”执行 |

---

## 7. 本轮自检结论（2026-11-28 实测，E0C-CL-6）

命令：`python solutions/A/e0c_preflight.py --out experiments/A/A-Q1-E0/e0c/preflight.json`

| 项 | 实测 |
|---|---|
| 检查项 | **32 / 32 通过**（`code.e0c_runner_present` 已过：入口交付后 readiness 满足） |
| `preconditions_pass` | **true**（`blocking_ids=[]`）；退出码 `0` |
| `execution_ready` | **true**（`a_e0_c.py` 已交付） |
| 锚点 | `config` `8fb6821f…e06a`、`PLAN` `073511c0…5a88`、`SPLIT` `d623da4e…8b3a` 全部匹配 |
| 白名单 | 12 组 / 96 文件 / **88,073,632 B**；逐文件 `size+SHA256` 与 R0 清单一致 |
| 读前路径校验 | `data.path_guard` 通过：`guarded_files=96`、`rejections=[]`；12 组目录逐级无重解析点 |
| R0 清单 | 881 行，总体 SHA256 `86305548…fa06` 按 **CSV 行序** 复现（B-09） |
| 越界读取 | 打开并摘要的 96 个 `.dat` 全部落在白名单 12 组内；无检验组、无 `附件3`、无 B 题 |
| E0-S 前置 | `overall_pass=true`、三例逐门通过、数组/参数表摘要匹配、验收报告在库 |
| D1-2 | `CONTRACT_VERSION="D1-2"`；D0 读取器在库 |
| 自检测试 | **55 / 55 通过**（含缺行、大小/摘要不符、0 字节、越界、E0-S 门失败、锚点不符、词法越界、重解析点、`realpath` 逃逸、目录联接组 等反例） |
| 入口 check | `a_e0_c.py --mode check` 退出码 `0`、`ready_for_execute=true`、`packets_parsed=0`、12 组边界扫描无问题 |
| 入口测试 | **83 / 83 通过**（合成频谱数学链 + 合法 `.dat` 写读回 + 桩 preflight 的**两个独立进程**完整 E0-C + E0-PREREG-3/C12 交付接口 + `e0c_repeat.json` 两次进程证据 + 7 类 C12 反例 + 门槛/CLI 边界） |
| C12 证据 | 合成端到端包：`n_runs=2`、两次进程 `pid` 互异、时间窗顺序不重叠、`run_id` 互异、`runs[0]` 绑定顶层 `e0c_results.json`/`e0c_arrays.npz`、`runs[1]` 绑定 `repeat_runs/run-2/`、两次数组逐字节相同、指标 `max|Δ|=0`、分类一致；7 类反例（缺清单、缺 `runs`、重复记录、复用证据、时间窗重叠、SHA 被换、第二次指标不一致）全部被拒绝；任一时刻单进程单线程 |
| E0-PREREG-3 接口 | `E0C-CL-5` 时官方 `accept_e0c.py` 对生产链路合成端到端包 **`PASS`（C1–C15 全过）**；`E0C-CL-6` 的两进程包已于 2026-11-28 用官方检查器（main `0386055`）预检：**C12 PASS、仅 C4 FAIL**（合成文件名不在真实白名单；96 文件仍为 `88,073,632 B`），详见 §2.5。独立复验仍属验证方；C4 的真实输入身份只能由真实包证明 |

- **本清单不产生任何真实测距数值**：入口已交付但 E0-C 未放行（B-02），`--mode execute` 缺 `--approval-ref` 时拒绝启动。
- 本清单不修改 `PLAN.md`、`config.json`、`SPLIT.json`、D0/D1-2/E0-S 生产代码或任何原始数据；只新增文档、只读自检工具、读前路径校验与 E0-C 入口/测试。

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| E0C-CL-1 | 2026-11-28 | 首版：12 组白名单（96 文件）、E0-C 命令契约、按 `PLAN.md` §5.2 的门槛表、停止/回溯/登记格式、依赖与未知项；新增元数据自检与 43 项测试 |
| E0C-CL-2 | 2026-11-28 | 记录实测自检 30/31（`preconditions_pass=true`、`execution_ready=false`）；补 B-09（清单哈希行序）、B-10（跨数据集同名组）、B-11（18 未触碰 = 16 内插 + 2 外推）三项口径差异 |
| E0C-CL-3 | 2026-11-28 | 回应统筹复核意见：① `e0c_preflight.py` 在 `stat`/`open` **之前**做词法归属、逐级反重解析点（含 Windows 目录联接）与 `realpath` 包含性校验，新增 `data.path_guard` 与 4 类负例（含 `mklink /J` 指向根外的端到端负例）；② 交付 `solutions/A/a_e0_c.py` 正式入口（`check`/`execute` 双模式、`--approval-ref` 强制、拒绝覆盖失败证据、六类产物）与 `test_a_e0_c.py`（47 项，含合法 `.dat` 合成端到端）；③ 实测更新为自检 31/32、`execution_ready=true`、测试 55/55 与 47/47；B-01 结项，B-02 仍未放行 |
| E0C-CL-4 | 2026-11-28 | 回应 `V1-20261128-01/-02`（`E0-PREREG-3` 接口冻结）：① 合入 PLAN §3.1 近并列兜底（`1e-6 dB` → λ 和 → 索引距离 → 字典序）；② execute 产物补齐顶层 `groups[12]`、`inputs[96]`、`array_map` + `p_cal/p_sup (9,10,63)`、`arrays_sha256`/`metrics_sha256`/`repeat_run`、`resource.single_process`、`e0c_air_loo.json` 冻结结构；③ 目标指标改为按交付数组（0.05/0.25 ns τ、0.1 mm d）离散重算，写前自检 C10；④ 确定性 npz 两次序列化比对；⑤ 官方 `accept_e0c.py` 对合成端到端包 C1–C15 全过，作者测试 72/72 |
| E0C-CL-5 | 2026-11-28 | 回应 `PR #33` 的 C12 阻塞（“两次序列化”不是两次独立运行）：① `run_execute` 增加 `run_execute_repeated`，`--mode execute` 默认 `--repeat-runs 2` 顺序做两次**完整独立重算**（重新 preflight、重读 96 个 `.dat`、不共享数组），各自落盘 `repeat_runs/run-K/e0c_arrays.npz` + `run_manifest.json` + `run.log`；② `repeat_run` 改为两次运行记录（`run_id`/`pid`/起止时间/墙钟/摘要/分类/逐案指标），写盘前 `verify_repeat_evidence` 重算证据摘要，`write_outputs` 拒绝重复序列化/复用证据/缺证据；③ `--repeat-runs<2` 用法拒绝；④ 作者测试扩至 **90/90**，含重复序列化、复用 npz 证据、缺 `repeat_run` 三类反例；⑤ 官方 `accept_e0c.py` 对生产链路合成端到端包 **C1–C15 PASS**（总墙钟 301.1 s，C12 通过），真实执行仍待 B-02 |
| E0C-CL-6 | 2026-11-28 | 对齐验证方冻结契约 **`E0-C-C12-REPEAT-1`**（`checks/A/e0_c_repeat_contract.json`，main `40c637e` 已含）：① 把“同进程两次重算”改为**顺序启动两个独立进程**（新增 `--mode execute-worker`），第 1 次写交付顶层、第 2 次写 `repeat_runs/run-2/`；`pid`/时间窗/`run_id`/结果文件/数组文件五类来源必须互异，同一进程或重叠时间窗不再算证据；② 新增 `e0c_repeat.json#runs[2]`（`run_id`/`pid`/`started_at`/`finished_at`/`wall_time_s`/`results_file`/`results_sha256`/`arrays_file`/`arrays_sha256`），顶层 `repeat_run` 只放摘要 + `runs_file`、**不内嵌 `runs`**（避免 `results_sha256` 自引用）；③ 写盘后 `verify_repeat_manifest` 机械核验：缺清单/缺 `runs`/重复记录/复用证据/时间窗重叠/SHA 被换/第二次运行指标不一致一律拒绝；④ `--repeat-runs` 只接受 `2`；⑤ 作者测试 **83/83**（新增 7 类 C12 反例，其中“缺清单”“缺 `runs`”“第二次指标不一致”为 CL-6 补齐）；⑥ 旧登记 `b63e217` 仍按“单次运行、不满足新 C12”保留，不覆盖 |
| E0C-CL-7 | 2026-11-28 | 补齐 CL-6 的官方验收器预检项：新增 `solutions/A/e0c_official_precheck.py`（12 组合成 `.dat` + 生产链路两独立进程 + 官方 `accept_e0c.py` 机械验收，不读真实 `.dat`）。实测（main `0386055`）：**C12 PASS**（`pid` 26288/7604、时间窗不重叠、`e0c_repeat.json#runs`、第二次 npz 独立重算一致、`duplicate_serialization_detected=false`），C1–C3、C5–C15 PASS，仅 C4 FAIL（合成文件名非真实白名单，字节数仍为 `88,073,632 B`）。作者测试复跑 **83/83**。此为生产者预检，不代替独立验收；B-02 仍未放行 |
