# A-Q1-E0-C 执行清单（放行前自检 · 允许数据 · 复跑命令 · 门槛与停止条件）

- **任务 / 分支**：E0-C 执行清单准备 / `data/a-q1-e0-c-checklist`
- **主责**：`dsh`（数据与求解）；放行与验收：`codex`；前置 `E0-S` 独立验收：`my_deepseek`
- **依据**：`experiments/A/A-Q1-E0/PLAN.md`（`073511c0…5a88`）、`experiments/A/A-Q1-E0/config.json`（`schema_version=3`，LF 归一化 `8fb6821f…e06a`）、`coordination/A_Q1_SPLIT.json`（`A-Q1-SPLIT0` 冻结，LF `d623da4e…8b3a`）、`coordination/A_Q1_E0_S_DECISION.md`、`solutions/A/data_contract.md`（`D0-4`）、`solutions/A/fold_gate_contract.md`（`D1-2`）、`solutions/A/e0_s1s2_contract.md`
- **状态**：**清单草案 + 元数据自检（尚未运行 E0-C 真实信号）**。截至本分支，E0-C **未获统筹放行**，`E0-T` 冻结前不得触碰。

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
# 1) 清单自检：锚点、白名单、96 个文件身份、E0-S 前置、D1-2 契约
python solutions/A/e0c_preflight.py `
  --out experiments/A/A-Q1-E0/e0c/preflight.json

# 2) 自检测试（含篡改反例：缺行、改大小、改 SHA、掺入检验组、E0-S 门失败）
python solutions/A/test_e0c_preflight.py
```

- 退出码：`0` = 放行前条件（`preconditions_pass`）全部通过；`1` = 任一条件失败；`2` = 用法/环境错误。JSON 始终写出。
- 两级判定，避免把“条件齐了”误读成“可以开跑”：
  - `preconditions_pass`：锚点、白名单、96 个文件身份、E0-S 前置、D1-2 契约全部通过；
  - `execution_ready = preconditions_pass AND a_e0_c.py 已交付`；当前为 **false**（缺实现，见 §6 B-01）；
  - `overall_pass` 只等于 `preconditions_pass`，**不等于放行**。`--no-hash` 会把 `data.hash_skipped` 记为失败，调试模式不能充当放行证据。
- 自检只做：读 `config.json` / `PLAN.md` / `SPLIT.json` / `E0-S` 结果 JSON / R0 清单；对白名单 96 个 `.dat` 只算 `size + SHA256`（不解析包头、不读采样语义）；落盘一份 JSON。
- 自检**不等于** E0-C 通过，也不构成放行。它只证明“放行前该齐的东西齐了、该锁的东西没被改、越界文件没被打开”。

输出 JSON 关键字段：`preconditions_pass`、`execution_ready`、`overall_pass`、`checks[]`（`id/group/passed/detail`）、`summary.failed_ids` / `summary.blocking_ids`、`data_allow_list`、`data.signal_files_hashed`、`data.opened_dat_files`、`anchors`、`open_items`。

### 2.2 E0-C 主运行命令（**待实现、未放行，现在不得执行**）

`a_e0_c.py` 尚未交付；下列接口是本清单锁定的**实现契约**，实现分支需按此交付，并在实现提交后从该提交运行、再登记结果（避免自引用 SHA）：

```powershell
$env:OMP_NUM_THREADS="1"; $env:OPENBLAS_NUM_THREADS="1"
$env:MKL_NUM_THREADS="1"; $env:NUMEXPR_NUM_THREADS="1"

python solutions/A/a_e0_c.py `
  --config experiments/A/A-Q1-E0/config.json `
  --split coordination/A_Q1_SPLIT.json `
  --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" `
  --out experiments/A/A-Q1-E0/e0c/results `
  --implementation-sha <impl-sha> `
  --parent-commit <parent-sha> `
  --main-commit <main-sha>
```

必须产出（文件名可自定，但同一提交的接口说明要给出映射）：

| 文件 | 内容 |
|---|---|
| `e0c_results.json` | 机器可读：版本锚点、参数、逐组指标、逐门 `value/threshold/passed`、`stop_reason`、资源用量 |
| `e0c_arrays.npz` | 用于独立重算的逐通道校准谱、减除前后谱、压缩响应、剖面与采样轴 |
| `e0c_air_loo.json` | 10 折 × 9 组 `Supp_air-LOO`、`J_air`、`min/median`、选中对与切换原因 |
| `e0c_frozen.json` | **仅当全部门槛可冻结时**写出：`(λ_cal, λ_inv, η_wall)`、实现 SHA、配置 SHA、冻结时间 |
| `run.log` / `SHA256SUMS.txt` | 诊断日志与全部产物的 SHA256 |

实现约束（与 `PLAN.md` 一致，不得夹带 `N0`）：

- 链路固定 `M0-Cal-Base → M0-DW-Base（α_g ≡ 1.0）→ M0-Rng-Base（P_norm,eff 主统计量）`；`P_norm`、`P_env` 仅作对照。
- 折迭统一用 `solutions/A/a_fold_gate.py`（`D1-2`），每包 16000 点 → 4 段 × 4000 点，等权折叠、无相位补偿；任一通道 NaN/Inf 整包拒绝。
- 有效通道必须 **63/63**（含 `ref_idx=28`），禁止静默丢通道或补零；`valid_rx < 63` 即硬停止。
- 搜索区间 `[0.15, 2.00] m`：粗 1 mm、细 0.1 mm；`PSLR` 主瓣保护半宽 `1.6031e-1 m`。
- 墙体首峰规则默认 `η_wall=0.25`；`{0.15,0.25,0.35}` 只允许在 `墙体数据/data1-42cm` 上核对，冻结后不得再改。金属板用全局 `argmax`。
- 单进程单线程；总墙钟 ≤ 600 s、峰值 RSS ≤ 4096 MiB；超预算即停。

### 2.3 复跑登记规则

- 先提交实现与测试（implementation commit），再 `git archive`/新 worktree 从该提交运行，`--implementation-sha` 填该提交，`--parent-commit` 填其父提交，`--main-commit` 填运行时 `origin/main`。
- 结果单独提交（只加 `experiments/A/A-Q1-E0/e0c/` 产物）。失败实验也保留提交、配置、日志、退出原因，不删证据。
- 同一环境内重复运行应逐位一致；跨机只要求指标一致，不宣称数组逐位（`E0-S` 验收已记录该边界）。

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

`e0c_results.json` 至少包含：

- `experiment_id="A-Q1-E0"`、`phase="E0-C"`、`scope`（明确“真实校准组、非盲测、不含 E0-T”）
- `implementation_sha` / `parent_commit` / `main_commit` / `branch`；`config_sha256`、`plan_sha256`、`split_sha256` 及匹配布尔
- `environment`（Python/numpy/OS/线程）、`command`、`resource`（墙钟 s、峰值 RSS MiB）
- `lambda_loo`：9 组网格、每折抑制、`J_air`、`min/median`、选中对、是否触发切换及原因
- `groups[]`：`group_key`、`d_true_cm`（标称，仅评价用）、`d_hat_m`、`abs_err_cm`、`supp_dw_win_db`、`pslr_db`、`pnr_db`、`echo_ret_db`（诊断）、`valid_rx`、`finite`、`gate_results`、`stop_reason`
- `freeze`：`eligible` / `not_eligible_for_freeze` / `hard_stop`，以及冻结的三元组（仅 eligible 时）
- `arrays_sha256`、`files_sha256`

频道回传用下表，数值直接抄 JSON，不手算、不四舍五入掩盖灰区：

| 组 | 类型 | `d_hat` | `abs_err` | `Supp_dw-win` | `PSLR` | `PNR` | `valid_rx` | 判定 |
|---|---|---:|---:|---:|---:|---:|---:|---|

---

## 6. 依赖、未知项与剩余阻碍

| 编号 | 事项 | 状态 / 需要什么 |
|---|---|---|
| B-01 | `solutions/A/a_e0_c.py` 主运行程序 | **未实现**。需另立实现分支（`PLAN.md` 原记 `data/a-q1-pilot`，E0-S 实际用 `data/a-q1-e0-s`），交付 CLI + 结果接口 + 测试，再申请放行 |
| B-02 | 真实信号执行放行 | **未获**。需 `codex` 核对本清单白名单与停止条件后明确放行 |
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

## 7. 本轮自检结论（2026-11-28 实测）

命令：`python solutions/A/e0c_preflight.py --out experiments/A/A-Q1-E0/e0c/preflight.json`

| 项 | 实测 |
|---|---|
| 检查项 | **30 / 31 通过**（唯一未过：`code.e0c_runner_present`，属 readiness，不是数据/锚点问题） |
| `preconditions_pass` | **true**（`blocking_ids=[]`）；退出码 `0` |
| `execution_ready` | **false**（`a_e0_c.py` 未交付） |
| 锚点 | `config` `8fb6821f…e06a`、`PLAN` `073511c0…5a88`、`SPLIT` `d623da4e…8b3a` 全部匹配 |
| 白名单 | 12 组 / 96 文件 / **88,073,632 B**；逐文件 `size+SHA256` 与 R0 清单一致 |
| R0 清单 | 881 行，总体 SHA256 `86305548…fa06` 按 **CSV 行序** 复现（B-09） |
| 越界读取 | 打开并摘要的 96 个 `.dat` 全部落在白名单 12 组内；无检验组、无 `附件3`、无 B 题 |
| E0-S 前置 | `overall_pass=true`、三例逐门通过、数组/参数表摘要匹配、验收报告在库 |
| D1-2 | `CONTRACT_VERSION="D1-2"`；D0 读取器在库 |
| 自检测试 | **43 / 43 通过**（含缺行、大小/摘要不符、0 字节、越界、E0-S 门失败、锚点不符等反例） |

- **本清单不产生任何真实测距数值**：`a_e0_c.py` 未交付（B-01），E0-C 未放行（B-02）。
- 本清单不修改 `PLAN.md`、`config.json`、`SPLIT.json`、D0/D1-2/E0-S 生产代码或任何原始数据；只新增文档与只读自检工具。

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| E0C-CL-1 | 2026-11-28 | 首版：12 组白名单（96 文件）、E0-C 命令契约、按 `PLAN.md` §5.2 的门槛表、停止/回溯/登记格式、依赖与未知项；新增元数据自检与 43 项测试 |
| E0C-CL-2 | 2026-11-28 | 记录实测自检 30/31（`preconditions_pass=true`、`execution_ready=false`）；补 B-09（清单哈希行序）、B-10（跨数据集同名组）、B-11（18 未触碰 = 16 内插 + 2 外推）三项口径差异 |
