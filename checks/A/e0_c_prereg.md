# A-Q1-E0-C 独立验收预登记（`E0-PREREG-3`）

- **登记方**：`my_deepseek`（独立验证；不改动被验生产实现）。
- **版本**：`E0-PREREG-3`（首个 E0-C 预登记；与 `E0-PREREG-2` 的 E0-S 登记相互独立）。
- **状态**：**已在真实信号运行前冻结**。截至本分支，`solutions/A/a_e0_c.py` 尚未交付，E0-C 未放行，`E0-T` 两组留出样一律未读。本文件**不含任何 E0-C 结果**，也不据此宣称任何通过。
- **范围**：仅 `E0-C`（10 组空场 + `墙体数据/data1-42cm` + `金属板数据/data1-69cm`，共 12 组 / 96 个 `.dat`）。**不含** `E0-T` 单次留出盲评，不含 Q2/Q3/附件3/B 题。
- **目的**：在实现 SHA 未知时先固定验收对象、接口字段、逐门判定、独立重算口径、非空转要求与报告格式，避免看到结果后再定标准。

## 0. 版本记录

| 版本 | 依据 | 主要变化 |
|---|---|---|
| `E0-PREREG-3` | 主线 `3b8b67e`；`PLAN.md` `073511c0…5a88`；`config.json` `8fb6821f…e06a`；`SPLIT.json` `d623da4e…8b3a` | 首次冻结 E0-C 验收口径：C1–C15 检查、数组/结果接口、独立重算公式、容差、灰区与冻结语义、非空转证明 |

修改本文件或 `checks/A/e0_c_prereg.json` 的任何数值即视为**新预登记版本**，必须在结果交付前重新登记并说明变更；不得在结果交付后追溯放宽阈值。

## 1. 冻结依据与版本锚点

| 项 | 冻结值 |
|---|---|
| 登记基线 `main` | `3b8b67e58156b9618c788ec8e114e50d960bbb0d`（PR #27/#28/#29 合并后） |
| E0 方案 `experiments/A/A-Q1-E0/PLAN.md` | SHA256 `073511c0b6ae44dbc90d228b7d79c2de9d0687d4e65949494803b19f24595a88` |
| E0 配置 `experiments/A/A-Q1-E0/config.json` | SHA256 `8fb6821fa3335ef748e16ad2f5b5b8fc818c13cbe9d3315377faf48d5e40e06a`（`schema_version=3`） |
| 冻结拆分 `coordination/A_Q1_SPLIT.json` | SHA256 `d623da4ea186f372f2be094121c202c55dae0e236f4683005ab88d220a248b3a` |
| E0-S 接口裁定 `coordination/A_Q1_E0_S_DECISION.md` | SHA256 `ee2ed0f8d2e1885d5d1ca8cde84857f5bc7130b6453b0d07f6ac12866cf21ff5` |
| E0-S 已验收结果 `…/s1s2/results/e0_s1s2_results.json` | SHA256 `171f55f75e464d289815af7352fb6fcb6635b8d73db97b3af2dcbb687eab3fdf` |
| E0-S 已验收数组 `…/s1s2/results/e0_s1s2_arrays.npz` | SHA256 `27bea969f27589bca74031e02b88e163fc5865190a9f555dd4cecd97ee972df5` |
| 折迭门控契约 | `a_fold_gate.py` 的 `CONTRACT_VERSION == "D1-2"`（SHA256 `e6f03043b62f8d168d1c10451a172ac70d628ddd70624175e4c6b4970c1e188d`） |
| 数据身份 oracle | `checks/A/e0_c_data_oracle.json`，SHA256 `f8c7572eaa0a6d54c02b3b84f033d4a91b6e0cca7585f2228918081963595f3c` |
| 失败回退目标 | 执行前最近通过验收的 `main`（当前 `3b8b67e`）；回退点变更须统筹确认 |

**哈希口径**：上表均为 **Git 内容（LF）** 的 SHA256。Windows 检出可能因 `core.autocrlf` 为 CRLF，磁盘文件直接哈希会不同（E0-S 结果 JSON 即出现 `171f55f7…` 与 `12176dcc…` 的差异）。检查器对文本锚点按 `CRLF→LF` 归一化后比对，对 `.npz` 等二进制不归一化。

本预登记严格采用 `config.json#gates_and_thresholds`、`PLAN.md` §5.2 与 `E0-S` 裁定 `2ba3210` 的既有阈值，**不新增、不放宽任何门控**。文件间冲突时以 `PLAN.md` + 裁定为准并报统筹。

## 2. 被验对象与交付接口

验收对象是 `dsh` 交付的 **E0-C 产物目录**（建议 `experiments/A/A-Q1-E0/e0c/results/`），不是 `e0c_preflight.py` 的元数据自检。自检通过只说明“放行前条件齐了”，不能替代 E0-C 验收。

### 2.1 交付包最低要求

| 文件 | 要求 |
|---|---|
| `e0c_results.json` | 机器可读结果；字段见 §2.2 |
| `e0c_arrays.npz` | 供独立重算的数组；布局见 §2.3 |
| `e0c_air_loo.json` | 9 对 × 10 折 LOO 表；字段见 §2.4 |
| `e0c_frozen.json` | **仅当全部门控可冻结时**写出：`lambdas`、`eta_wall`、`implementation_sha`、`config_sha256`、`frozen_at_utc` |
| `run.log` | 非空诊断日志（≥40 字符） |
| `SHA256SUMS.txt` | 覆盖 `e0c_results.json`、`e0c_arrays.npz`、`e0c_air_loo.json`、`run.log`（有冻结文件时一并覆盖）；`<sha256>  <文件名>` |

另需在结果中给出：实现提交、父提交、运行时 `main`、分支、可复跑命令、环境（Python/numpy/OS/线程）、资源（墙钟、峰值 RSS）。**先提交实现、再从该提交运行、最后单独提交结果**，`implementation_sha` 不得等于结果提交。

### 2.2 `e0c_results.json` 必需字段

顶层：`experiment_id="A-Q1-E0"`、`phase="E0-C"`、`scope`、`implementation_sha`、`parent_commit`、`main_commit`、`branch`、`config_sha256`、`plan_sha256`、`split_sha256`、`e0_s_results_sha256`、`fold_gate_contract_version="D1-2"`、`environment`、`command`、`resource`、`methods`、`inputs[96]`、`air_loo_folds[10]`、`array_map`、`lambda_selected`、`eta_wall`、`freeze{status,written}`、`arrays_sha256`、`metrics_sha256`、`repeat_run{arrays_sha256,metrics_sha256}`、`d_true_usage="evaluation_only"`、`files_sha256`、`groups[12]`、`stop_reason`。

`groups[]` 每项：`group_key`、`target_type`（`air`/`wall`/`metal`）、`split`（空场 `"air"`；`wall_cal`；`metal_cal`）、`d_true_cm`、`d_hat_m`、`abs_err_cm`、`supp_dw_win_db`、`pslr_db`、`pnr_db`、`echo_ret_db`、`valid_rx`、`finite`、`status`（`eligible`/`not_eligible_for_freeze`/`hard_stop`）、`gate_results`、`stop_reason`。空场组的 `d_hat_m`/`abs_err_cm`/`pslr_db`/`pnr_db` 可为 `null`（不得填伪零）。

`inputs[]` 每项：`rel_path`、`size_bytes`、`sha256`，必须**恰好覆盖白名单 96 个 `.dat`**，逐项与 `checks/A/e0_c_data_oracle.json` 一致（该 oracle 由 R0 清单 `recon/manifests/a_dat_manifest.csv` 生成，合计 88,073,632 B）。

`metrics_sha256` 的规范：对 `groups[]` 依序取 `{group_key,d_hat_m,abs_err_cm,supp_dw_win_db,pslr_db,pnr_db,valid_rx,finite}`，按 `json.dumps(ensure_ascii=False, sort_keys=True, separators=(",",":"))` 编码后取 UTF-8 SHA256。`repeat_run` 两字段须与首轮值相同，用于证明两次运行一致；检查器可核验摘要绑定，**完整确定性仍需实现方两次运行的证据**。

### 2.3 `e0c_arrays.npz` 布局（`<f8`/`<c16`，C-order，无 Fortran 序）

每个**目标组**（2 组）以 `array_map.group_prefix[group_key]` 为前缀 `<p>`：

| 键 | 形状 | 含义 |
|---|---|---|
| `<p>__tau_ns` | `(N,)` `f8` | 压缩延迟轴（ns），单调 |
| `<p>__tau_dir_ns` | `(63,)` `f8` | 逐通道直达波到达时延（ns） |
| `<p>__z_before` | `(63,N)` `c16` | 减除前压缩响应 |
| `<p>__z_after` | `(63,N)` `c16` | 减除后压缩响应 |
| `<p>__d_m` | `(M,)` `f8` | **0.1 mm 细网格** `[0.15,2.00] m` 上的距离轴 |
| `<p>__P_after` | `(M,)` `f8` | `P_norm,eff` 剖面的**线性功率**（非 dB） |

空场 LOO 以 `array_map.air_loo_prefix`（默认 `air_loo`）为前缀：

| 键 | 形状 | 含义 |
|---|---|---|
| `<air_loo_prefix>__p_cal` | `(9,10,63)` `f8` | 每候选对 / 每折留出组 / 每通道的**校准后带内功率和** |
| `<air_loo_prefix>__p_sup` | `(9,10,63)` `f8` | 同上的**减除后带内功率和** |

`p_cal/p_sup` 是 `Supp_air-LOO` 比值中真正进入分子/分母的量；交付它即可让验收方**独立重算 90 个抑制值、`J_air`、`min/median`、并列裁决与切换触发**，无需导入生产代码。顺序固定：网格按 `λ_cal` 外层、`λ_inv` 内层（`1e-4,1e-3,1e-2`），折按 `air_loo_folds`（`data1…data10`）。若实现使用其他前缀/命名，必须在 `array_map` 中声明；缺失映射按“依据不足”处理，而不是通过。

### 2.4 `e0c_air_loo.json` 必需字段

`folds[10]`（`held_out` 顺序 = `air_loo_folds`）、`grid[9]`（`lambdas`、`folds[10].supp_db`、`j_air_db`、`min_db`、`median_db`）、`selected`、`switched`、`min_supp_db`、`median_supp_db`、`j_air_default_db`、`eligibility`（`eligible`/`gray`/`hard_stop`）。

## 3. 门控（全部取自既有阈值，未新增）

| 阶段 | 检查 | 通过 | 灰区（不可冻结） | 硬停 |
|---|---|---|---|---|
| 前置 | E0-S 已验收 | 结果文件锚点一致且 `overall_pass=true`、三例齐全、S2 `valid_rx=63` | — | 任一不符 |
| 前置 | D1-2 契约 | `fold_gate_contract_version=="D1-2"` | — | 不符 |
| 数据 | 白名单完整性 | 恰好 12 组、96 文件、size+SHA256 与 R0 清单一致 | — | 缺文件/0 字节/哈希不符/越界组 |
| 通道 | 有效接收通道 | 逐组 `valid_rx==63`、无 NaN/Inf | — | `<63` 或非有限 |
| 空场 | `min(Supp_air-LOO)` | `≥10.0 dB` | `6.0≤min<10.0 dB`：仅 9 对网格复核，仍 `<10` 即停 | `<6.0 dB` |
| 目标 | 近距回波质量 | `PSLR≥3.0 dB` 且 `PNR≥6.0 dB` | — | 任一 `<` |
| 目标 | 校准测距 `abs_err` | `≤5.0 cm` | `5.0<err≤10.71 cm`：标 `not_eligible_for_freeze`，仅校准内诊断 | `>10.71 cm` |
| 资源 | 墙钟 / 峰值 RSS | `≤600 s` / `≤4096 MiB`，单进程单线程 | — | 超预算 |
| 冻结 | `E0-Freeze` | 全部可冻结才写 `e0c_frozen.json`，锁 `(λ_cal,λ_inv,η_wall)` 与实现 SHA | — | 任一不满足 |

补充口径：

- `10.71 cm = c0/(2B)` 为 1 个瑞利主瓣宽；`5.0 cm ≈ 1.33` 个距离采样步（`3.7474 cm`）。两者是工程门槛，不是精度承诺。
- `PNR` 分母是**非目标区/晚延迟背景代理** `W_bg=[50,950] ns`，不宣称纯热噪声；`PSLR` 用剖面旁瓣区，主瓣保护半宽 `1.6031e-1 m`。
- **`Supp_dw-win ≥ 20 dB` 在 E0-C 只是诊断记录**：该门槛在 `config.json` 中属 `E0-S2`（合成 25 dB）门控；E0-C 的正式门控是 LOO 抑制、PSLR、PNR 与校准测距。本预登记不把 S2 阈值搬来当 E0-C 通过条件，也不放宽它。
- 两组校准目标在 V0/M0 阶段**已被探索**（`A_Q1_SPLIT.json#explored_target_groups`），故 E0-C 不是盲测，只能称“校准组复现/诊断”；目录名 `42cm/69cm` 是标称标签，不是独立物理真值认证。

## 4. 检查项 C1–C15

| 编号 | 检查 | 通过标准 | 失败动作 |
|---|---|---|---|
| C1 | 版本锚点 | `config/PLAN/SPLIT/E0-S 结果` SHA256 与 §1 一致；D1-2 版本一致 | 拒收 |
| C2 | 实现身份 | 三个 SHA 为 40 位 hex；`implementation_sha` 非结果自引用；父提交可追溯 | 拒收 |
| C3 | 边界 | `groups[]` 恰好 12 组；`split` 正确；组名/输入/日志不命中 `_test`、`data20-73cm`、`data5-60cm`、`附件3`、`B题` | 拒收 |
| C4 | 数据身份 | `inputs[96]` 与 oracle 逐文件 `size+SHA256` 一致，合计 88,073,632 B | 拒收 |
| C5 | 方法范围 | 声明 `alpha_mode=fixed_1.0`、`n0_improvements_enabled=false`、无自适应 α/子空间/WLS/非等权；源码关键词命中仅作提示 | 拒收 |
| C6 | E0-S 前置 | 结果文件 SHA256 = `171f55f7…`，`overall_pass=true`，三例齐全，S2 `valid_rx=63` | 拒收 |
| C7 | 通道/有限性 | 逐组 `valid_rx=63`、`finite=true`；目标组数组全有限 | 硬停 |
| C8 | 空场 LOO | 9×10 折独立重算一致（`≤1e-6 dB`）；`J_air`、`min/median`、并列裁决、切换触发、`eligibility` 正确 | 拒收/硬停 |
| C9 | 目标门控 | `PSLR≥3`、`PNR≥6`、`abs_err` 与 `d_hat/d_true` 自洽；`status` 与灰区/硬停分类一致 | 硬停 |
| C10 | 指标独立重算 | 从 `z_before/z_after/d_m/P_after` 重算 `Supp_dw-win/BG_proxy/PNR/PSLR/d_hat/abs_err`，与 JSON 差：dB `≤1e-6`、长度 `≤1e-9 m` | 失败 |
| C11 | 冻结完整性 | 仅全部可冻结才写 frozen；`freeze.status` 由原始指标重算；`η_wall∈{0.15,0.25,0.35}`；冻结 λ/η/实现 SHA 与选定值一致 | 拒收 |
| C12 | 确定性证据 | `metrics_sha256`/`repeat_run` 与按 `groups` 规范化重算的摘要一致，且绑定实际 npz 哈希 | 拒收 |
| C13 | 资源 | `≤600 s`、`≤4096 MiB`、`single_process=true`、四个线程变量为 `1` | 超限即停 |
| C14 | 证据完整 | 必需文件存在且非空；`SHA256SUMS.txt` 覆盖且摘要匹配；`run.log` 非空 | 依据不足/拒收 |
| C15 | 真值隔离 | `d_true_usage=="evaluation_only"`；数组名无真值字段；源码 `d_true` 仅提示人工复核 | 拒收 |

## 5. 独立重算口径（检查器实现，逐条可复算）

- **`BG_proxy`**：`mean_{i∈63, τ∈[50,950] ns} |z_after,i(τ)|²`（仅取提供的 `tau_ns` 采样）。
- **`PNR`**：`10log10( mean_i |z_after,i(τ*) |² / BG_proxy )`，`τ* = 2·d_hat/c0`，取 `tau_ns` 上最近采样点（预登记此处显式采用最近采样，避免插值自由度）。
- **`Supp_dw-win`**：`10log10( Σ_{i,u∈W_dw,i} |z_before|² / Σ |z_after|² )`，`W_dw,i = {τ: |wrap_{[-Tp/2,Tp/2)}(τ−τ_dir,i)| ≤ 1.0 ns}`，`Tp=1000 ns`。
- **`PSLR`**：`10log10( P_after(近 d_hat 网格点) / max{P_after(d): |d−d_hat|>0.1606031 m, d∈[0.15,2.00] m} )`。
- **`d_hat` 重选**：金属板取 `P_after` 全局 `argmax`；墙体取最小 `d` 的局部极大且 `P ≥ max(η_wall·P_max, 10^{0.6}·BG_proxy)`。要求交付 `d_hat_m` 与重选值在细网格步长内一致（`≤1e-9 m`）。
- **`J_air`**：`median_10(Supp) + 0.5·min_10(Supp)`；中位数对偶数个值取中间两值均值。
- **并列裁决**（PLAN §3.1）：目标差 `<1e-6 dB` 的候选依次按 `λ_cal+λ_inv` 更小、距默认点 `(1e-3,1e-3)` 的**网格索引距离**更近（先 Manhattan，等价时接受 Euclidean）、字典序更小。**`V1-20261128-01` 关联**：若实现仅按精确 `J` 排序、而 9 对网格中确实出现 `<1e-6 dB` 近并列，C8 将判失败、E0-C 不得冻结，直到 dsh 修正或统筹裁定改口径；若不存在近并列（E0-S 实测最小间隔 `6.95e-3 dB`），该差异不影响本次验收。检查器会输出 `near_tie_grid`，使该判定可审计。
- **切换触发**：`J_best − J_default ≥ 0.5 dB`，或 `min_default < 10 dB` 且 `min_best ≥ 10 dB`；否则保留默认对。
- **容差**：dB `1e-6`、米/厘米 `1e-9`、SHA256 精确。容差只吸收浮点求和顺序差异，不吸收口径差异。

## 6. 流程与结论

1. 在独立目录检出实现提交，`git status` 干净；核对 `implementation_sha` 与结果提交的先后关系。
2. 运行检查器（见 §7），保存 JSON 报告；报告含每项检查的 `status/detail` 与冻结常量 SHA256。
3. 结论只允许三种：**PASS**、**FAIL**、**INSUFFICIENT**（“依据不足”，例如数组映射缺失、E0-S 文件不可得）。后两种都必须列出具体检查项与证据。
4. 任何阻塞检查失败 → FAIL，退回 `dsh` 修复或公式口径退回建模/统筹；修复后对新 SHA 全量复测，不沿用旧结果。
5. 检查器**不修改**生产实现、不重跑 E0-C、不读取 `E0-T`；验收方只在独立目录复算已交付数组。

**归属**：代码/数据问题退 `dsh`；`PLAN`/论文口径问题退建模负责人与统筹；题意分歧交统筹。`dsh` 当前待修的路径校验问题（`stat`/读取前未先校验真实路径，符号链接可能越界）属其清单 B-01 同类，不在本预登记范围内，但 C3 会在交付结果上复核实际组清单。

## 7. 检查器与非空转证明

| 文件 | 作用 |
|---|---|
| `checks/A/e0_c_prereg.json` | 冻结常量（锚点、门槛、容差、数组契约、C1–C15） |
| `checks/A/e0_c_data_oracle.json` | 96 个白名单 `.dat` 的 `rel_path/size/sha256` |
| `checks/A/e0_c_accept/accept_e0c.py` | 纯标准库验收检查器（内置 `.npz` 解析，不依赖 numpy） |
| `checks/A/e0_c_accept/make_fixture.py` | 合成夹具生成器（解析构造，无真实数据） |
| `checks/A/e0_c_accept/test_accept_e0c.py` | 21 项自检：3 项正向（合规夹具 PASS、手算常数、灰区不冻结一致）+ 18 项负向（各类篡改/缺失必须被抓到） |

复跑：

```powershell
python checks/A/e0_c_accept/test_accept_e0c.py
# 结果：Ran 21 tests — OK（21/21）

python checks/A/e0_c_accept/accept_e0c.py `
  --results-dir experiments/A/A-Q1-E0/e0c/results `
  --repo . --report checks/A/e0_c_accept/report.json
# 退出码：0=PASS / 1=FAIL / 2=INSUFFICIENT / 3=用法错误
```

**手算常数（夹具）**：`Supp=30 dB`、`PNR=40 dB`、墙体 `PSLR=10 dB`、金属 `PSLR=13.010299956639813 dB`、`d_hat=0.420/0.690 m`、`abs_err=0`。负向共 18 类：`d_hat` 偏移 2 cm、`Supp` 改 0.5 dB、注入 NaN、`valid_rx=62`、掺入 `墙体数据/data20-73cm`、锚点改 1 位、灰区仍冻结、删日志、删 `repeat_run`、真值泄漏、输入哈希改 1 位、实现自引用、删 `array_map`（须 INSUFFICIENT）、LOO 选择篡改、非法 `η_wall`、超预算、E0-S 未通过、混入 N0——均被对应检查捕获。

## 8. 待决与依赖

1. **`a_e0_c.py` 未交付**（`dsh` 清单 B-01）：E0-C 尚不可执行，本预登记只冻结验收口径，不能给出任何真实结果结论。
2. **放行条件**：D1-2 已验收（`7d1c622`）、E0-S 已验收（`E0-ACC-1`，`P1–P17`）、统筹放行记录、`dsh` 完成路径预校验修复（codex 审阅意见），四项同时具备才可执行 E0-C。
3. **`E0-T`**：冻结前一律不读；本文件与检查器均不含 `E0-T` 组名之外的任何访问。
4. **数据接口若需变更**（字段名、数组布局）：须在 E0-C 结果交付前由 `dsh` 提出、统筹确认，并升级本预登记版本；交付后变更按新版本重验。

## 9. 边界声明

- 本预登记**未读取任何真实 `.dat` 采样**：oracle 只使用 R0 清单中的 `size/sha256` 元数据；锚点只使用 Git blob。
- **未运行 E0-C 求解器、未产生任何真实测距/抑制/冻结结论**；夹具数值仅为合成构造，不得引用为实验证据。
- 检查器通过夹具自检只证明“检查器非空转”，**不证明** E0-C 会通过，也不构成对 `E0-C`/`E0-T` 的放行意见。
