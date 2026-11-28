# A-Q1-N0 求解器 ↔ 验收器字段对照（`E0-N0-INTERFACE-1`）

| 项 | 值 |
|---|---|
| 性质 | **接口预检草案**。不改 `E0-N0-ACCEPT-2` 判据、不改任何阈值、不运行 N0、不读 `.dat`、不写冻结产物 |
| 基线 | `main = c7b841e`；原型 `solutions/A/a_e0_n0.py`（`N0-SYN-1`，仅 `check`/`synthetic`） |
| 对照对象 | `E0-N0-PRODUCER-CONTRACT-1`：29 个 JSON 路径 + 6 个 `.npz` 数组 = **35 项**；外加 `air_loo` 5 项与两进程清单 |
| 依据文件 | 机读契约 `e0_n0_producer_contract.json`、验收器 `accept_e0n0.py`（`E0-N0-ACCEPT-2`）、冻结预登记 `e0_n0_prereg.json`、预登记变更 `A_Q1_N0_PREREG_CHANGE.md`（`cf9c069`） |
| 实现 | `solutions/A/a_e0_n0_package.py`（打包器）+ `solutions/A/test_a_e0_n0_package.py`（20 项自检） |
| 结论 | 35 项全部有来源或明确缺失；**18 项原型没有**，全部 6 个数组需新建；三处歧义已按代码证据定值 |

## 0. 一句话

**现有原型与正式验收器只对上 17/35 项，缺的 18 项里有全部 6 个 `.npz` 数组；若 `execute` 沿用原型 schema，验收器会在 `load()` 阶段判 `INSUFFICIENT`（exit 2），走不到数值判定。本轮已把这 35 项逐项定值，并实现打包器：合成夹具产出的包通过生产侧探针 `READY`（721/721 项 ok），且正式验收器 `N1–N8、N10–N14` 全 PASS，唯一 FAIL 是 `N9`（c0 与**真实**归档基线的等价性，合成值必然不等，属预期，`S9` 停）。**

## 1. 方法

- 字段名不是从文档抄的，而是从**验收器读取点**反推：每个 id 对应 `accept_e0n0.py` 的实际 `read()`/`get()` 位置，再看探针 `probe_producer.py` 的结构校验。
- 变换限定为：`straight / rename / case / reshape / unit / sign / new-computation / constant / absent`。
- 本文件只给**接口**，不给新阈值；`P1/P2/P3/P4/C9b` 数值判定仍由验收器独立重算。

## 2. 35 项逐项对照

### 2.1 顶层 / identity / anchors（1–14）

| # | 契约项 | 原型来源 | 变换 | 生产取值 / 表达式 |
|---|---|---|---|---|
| 1 | `experiment_id` | **ABSENT** | constant | `"A-Q1-N0"`。**不得**沿用 `e0c` 的 `A-Q1-E0`（当前验收器不读，但 ACCEPT-3 会拒收错包） |
| 2 | `phase` | **ABSENT** | constant | `"N0"`（同上） |
| 3 | `method_scope` | `scope.mode`（`="synthetic"`） | new-computation | 方法范围串：`M0-DW-Subspace / rank-2 空场子空间 + 窗内 2 系数 / 臂 C0,C1,C2`；**不得**直接写 `"synthetic"` |
| 4 | `implementation_sha` | `provenance.implementation_sha`（`_git_state`，`a_e0_n0.py:1551-1553`） | straight | 40-hex，且 `== git.head_sha` |
| 5 | `main_commit` | **ABSENT** | absent | `git rev-parse origin/main` → 40 hex；与 `git.origin_main_sha`、`registration.main_commit` **三处同值** |
| 6 | `n0_config_sha256` | **ABSENT**（`n0/n0_config.json` 尚不存在） | absent | 64-hex；LF 归一化口径，与 `registration` 同值，ACCEPT-3 建议再绑实际字节 |
| 7 | `git` | `provenance.implementation_dirty` | reshape | 生产块 `{head_sha,parent_sha,origin_main_sha,working_tree_clean,branch}` **并**兼容键 `{dirty,commit}`（原因见 §4-P1） |
| 8 | `inputs` | **ABSENT** | absent | 整块取 `e0c_results.json#inputs`：96 条 `{rel_path,size_bytes,sha256}`，总 88,073,632 B，等于 `checks/A/e0_c_data_oracle.json`；**只读元数据** |
| 9 | `groups` | `targets`（2 组）+ `e0c#groups`（10 空场） | reshape | 12 条；空场 5 个指标必须 `null`；目标 5 个指标取 `targets.<g>.arms.c2`；`valid_rx=63`、`finite=true` |
| 10 | `array_map` | **ABSENT** | absent | **必须显式三键**：`{"xcluster_prefix":"xcluster","phase_prefix":"phase","air_loo_prefix":"air_loo"}`（`accept_e0n0.py:1055-1065` 缺一即 fail） |
| 11 | `methods` | **ABSENT** | absent | `{n0_enabled:true, rank:2, lambda_selection:"fixed_default", subspace_suppression:true}` |
| 12 | `d_true_usage` | **ABSENT** | constant | `"evaluation_only"` |
| 13 | `freeze` | `l2.freeze_status`/`frozen_present` | reshape | `{status, eligible, written}`；`L2` 未成立时 `eligible=false, written=false`，且**不得**存在 `n0_frozen.json`（`N11`） |
| 14 | `metrics_sha256` | **ABSENT** | absent | `groups` 按 8 键（`group_key,d_hat_m,abs_err_cm,supp_dw_win_db,pslr_db,pnr_db,valid_rx,finite`）**保序**规范化 JSON 后 SHA256（`accept_e0n0.py:1006-1011`） |

### 2.2 `n0` 块（15–29）

| # | 契约项 | 原型来源 | 变换 | 生产取值 / 表达式 |
|---|---|---|---|---|
| 15 | `n0.contract` | 顶层 `contract` | constant | `"E0-N0-1"`（**不是** 原型的 `"N0-SYN-1"`） |
| 16 | `n0.arms` | `n0.arms` | case | `["C0","C1","C2"]`（大写） |
| 17 | `n0.decision_arm` | **ABSENT** | constant | `"C2"`（唯一判定臂） |
| 18 | `n0.rank` | `n0.rank_requested` | rename | `2` |
| 19 | `n0.lambda` | `n0.lambda_fixed` | rename | `[0.001, 0.001]` |
| 20 | `n0.lambda_selection` | **ABSENT** | constant | `"fixed_default"`（不选参） |
| 21 | `n0.eta_wall` | `n0.eta_wall` | straight | `0.25` |
| 22 | `n0.xcluster_fold_map` | `fold_plan.p1_folds` | reshape | 5 折，`fold=0..4`，`cluster` 取冻结 prereg 的 `C0..C4`，`held_out` 按预登记对，`train` = 其余 8 组按 `air_groups` 升序（`N2` 逐项比对） |
| 23 | `n0.xcluster_supp_db` | `p1.c2.values`（fold-major 平铺） | reshape | `[v[0:2],v[2:4],v[4:6],v[6:8],v[8:10]]`；**必须**能由 `xcluster__p_cal/p_sup` 重算到 ≤1e-6（`N3`） |
| 24 | `n0.xcluster_eligibility` | `l1.p1_tier` | case | `met→eligible`、`not_met→below_eligible`、`hard_stop→hard_stop`（由 min 独立分类，`N3` 复算） |
| 25 | `n0.retention` | `p4.items[0]` | **sign** | `{case_id:"E0-S2@0.42", peak_loss_db: −peak_retention_db, range_shift_mm, pass}`；`pass` 由 `≤0.1 / ≤2 mm` 重算（`N6`） |
| 26 | `n0.phase` | `fold_lock`（秒） | unit + new | `contract="E0-N0-PHASE-1"`、`group_order`=10 组空场登记序、`per_group[10]`、`d1_rank∈{1,2}`、`d1_min_abs_inner≥0`；`shift_ns = shifts_s × 1e9` |
| 27 | `n0.judgement` | `l1.l1` / `l2.l2` / `l2.s_code` | case | `{L1:"PASS"/"FAIL", L2:…, stop_condition:S?}`；必须与验收器独立重算一致（`N10`） |
| 28 | `n0.arm_metrics` | `p2.<arm>.values`（**十折 LOO**）+ `targets.<g>.arms.<arm>` | reshape | 三臂各：`air_loo_supp_db[10]` + 两目标组 4 量；**C2 的目标侧必须与 `groups` 中目标行逐位一致** |
| 29 | `n0.registration` | **ABSENT** | absent | `{prereg_id, prereg_sha256, implementation_sha, n0_config_sha256, input_manifest_sha256, main_commit}`；`input_manifest_sha256` = 输入按 `(rel_path,size,sha256)` **排序**后规范化 JSON 的 SHA256（`accept_e0n0.py:723-727`） |

### 2.3 六个数组（30–35）

| # | 契约项 | 原型来源 | 变换 | 形状 / dtype / 语义 |
|---|---|---|---|---|
| 30 | `xcluster__p_cal` | **ABSENT** | absent | `(5,2,63) f8`；每折每留出组校准后逐通道功率 `Σ|x_cal|²` |
| 31 | `xcluster__p_sup` | **ABSENT** | absent | `(5,2,63) f8`；抑制后残差逐通道功率；与 #30 一起重算 `xcluster_supp_db` |
| 32 | `air_loo__p_cal` | **ABSENT** | absent | `(n_grid,10,63) f8`；N0 固定单 λ，`n_grid=1` |
| 33 | `air_loo__p_sup` | **ABSENT** | absent | `(n_grid,10,63) f8`；须与 `e0c_air_loo.json#grid[idx].folds[10]` 逐值一致，`idx` = `lambdas==[1e-3,1e-3]` 项 |
| 34 | `phase__shifts_ns` | `fold_lock.shifts_s`（秒） | **unit** | `(10,) f8`；×1e9，顺序 = 10 组空场登记序 |
| 35 | `phase__coherence` | **ABSENT** | absent | `(10,) f8`；仅约束 `aligned == (ρ ≥ 0.001)`；**ρ 的定义必须先冻结**（§6-2） |

### 2.4 不在 35 项内、但必须给的两块

| 项 | 要求 |
|---|---|
| `e0c_air_loo.json` | `grid` ≥1 项且含固定 λ `(1e-3,1e-3)`；`folds` 10 条 `{held_out,supp_db}`；`selected`=固定 λ；`switched=false`；`min_supp_db`/`median_supp_db` 由该行重算（`N4`） |
| `e0c_repeat.json` + `worker_meta.json`×2 | `runs` 恰 2 条 × 11 字段；两次 `run_id/pid/时间窗/文件`互异；`results_sha256/arrays_sha256` 从**实际字节**取；`preflight.json` 顶层 `passed=32,total=32`，`dryrun.json` 顶层 `passed=11,total=11`（`N13`） |

## 3. 三处歧义（按代码证据定值，请统筹确认后冻结）

### 3.1 P4 符号：`peak_loss_db := −peak_retention_db`（**必须翻转**）

- 原型 `a_e0_n0.py:891-893` 计算 `10·log10(p_after/p_before)`，**负值表示损失**；但 `:907` 把它存成 `peak_retention_db`。
- 原型门 `:1294` 是 `peak_retention_db >= -0.1`；契约与验收器（`accept_e0n0.py:499-506`、`prereg:66`）是 `peak_loss_db <= 0.1`。
- 故 `peak_loss_db = −peak_retention_db`（本例 `+0.016551085305782472`）。**直接照抄会让 P4 永远通过**（+0.5 dB 损失变成 −0.5）。

### 3.2 相位单位：秒 → 纳秒（×1e9）

- 产生：`fold_lock.shifts_s`（`a_e0_n0.py:253`，源 `:92-103`、`:377-380`）；消费：`align_spectra` 用 `exp(+1j·2π·f·shift_s)`（`:416-418`）。
- 契约数组与 `per_group.shift_ns` 是 ns；验收器 `N7` 以 0.1 ns 判簇内差。
- 安全网：`N7` 同时要求 `per_group.shift_ns == 数组`（1e-6），所以“整包都用秒”会**自洽地**通过 N7——必须靠 `×1e9` 与簇内 0.1 ns 门槛挡住；JSON 与数组必须是同一口径。

### 3.3 折序 / 池序：`xcluster_supp_db` 是 **fold-major**，`arm_metrics` 取 **p2（十折）**

- 冻结 order：`[data1,data2] → [data3,data4] → [data5,data6] → [data7,data8] → [data9,data10]`；`train` = 升序补集；`[5][2]` 的第二维 = `held_out` 内序。
- 原型 `p1.c2.values` 是 fold-major 平铺（外层折、内层组，`a_e0_n0.py:1086-1124`），因此 pivot 是 `v[0:2],v[2:4],…`；**按字典序**（`data10 < data2`）会静默错位。
- `n0.arm_metrics.air_loo_supp_db` 是**十折 LOO**，源必须是 `p2`（`a_e0_n0.py:1128-1150`），不是 `p1`。两者都长度 10，互换是“类型正确、实验错误”。

### 3.4 附带：簇名 `C0..C4` 与臂名 `C0..C2` 冲突

- 预登记**叙述**写簇 A–E，但**冻结机读 prereg**（`e0_n0_prereg.json:22-58`）写 `C0..C4`，`N2` 按机器名比对（`accept_e0n0.py:350-352`）。必须写 `C0..C4`。
- 风险：`C0/C1/C2` 同时是簇名与臂名，任何“按名字取字典”的代码会静默取到臂。打包器只按**位置**取值，不按名字合并。

## 4. 验收器侧三处缺口（`E0-N0-ACCEPT-3`，本轮未改）

| 编号 | 问题 | 证据 | 建议（只增严） |
|---|---|---|---|
| P1 | `N12` 读 `git.dirty` / `git.commit`，生产写 `working_tree_clean` / `head_sha` / `origin_main_sha` → **“工作区脏 / commit 漂移”永不触发** | `accept_e0n0.py:698-704` vs `a_e0_s1s2.py:193-223` | 改绑 `working_tree_clean is True`、`head_sha == implementation_sha`、`origin_main_sha == main_commit`；兼容读 `dirty/commit` 但不作唯一依据 |
| P2 | 验收器**不读** `experiment_id/phase/method_scope` → E0-C 包可被当 N0 包解析 | `accept_e0n0.py` 全文无该读取点 | 缺 identity → `INSUFFICIENT`；identity 非 N0 → 拒收 |
| P3 | `n0_config_sha256` 只与 `registration` 自洽，未绑 `n0_config.json` 实际字节 | `accept_e0n0.py:676-681` | 增加文件哈希绑定（raw 与 LF 双口径记录） |

> 本轮的打包器**已经同时写生产 `git` 块与兼容键**，所以 P1 修好后无需改包。

## 5. 可执行验证（合成夹具，非真实结果）

`a_e0_n0_package.py` 把“原型合成输出 + 真实 96 条输入 oracle”组装成契约包，声明值全部由数组重算，再交给**验收方的探针与验收器**：

| 步骤 | 结果 |
|---|---|
| 打包自检 `selfcheck()` | `SELF_OK`（0 problem）；`SHA256SUMS.txt` 覆盖全部必需文件、纯 LF |
| 生产侧探针 `probe_producer.py --results-dir` | **`READY`，721/721 ok，0 missing / 0 mismatch**（exit 0） |
| 正式验收器 `accept_e0n0.py --results-dir` | `N1–N8、N10–N14` **全 PASS**；`N9` **FAIL**（`S9`）；`failed_checks=["N9"]`、`insufficient=[]` |
| 自检用例 | `test_a_e0_n0_package.py` **20/20 OK**（含探针/验收器集成、5 个拒绝用例） |

**`N9` FAIL 是预期，不是接口问题：** `N9` 是 `c0` 臂与 `b63e217` **真实归档**基线的等价性检查（dB ≤1e-6、m ≤1e-9）。夹具用的是 `N0-SYN-1` 合成数，`c0` 必然与真实归档不同 → `S9` 停。这恰好说明验收器**能完整判读**本包并独立重算，而不是在 `load()` 就 `INSUFFICIENT`。

### 复跑命令

```sh
# 1) 组装（夹具：原型合成输出 + 真实输入 oracle）
python solutions/A/a_e0_n0_package.py \
  --from-prototype-synthetic experiments/A/A-Q1-E0/n0/synthetic/n0_synthetic_results.json \
  --inputs-oracle checks/A/e0_c_data_oracle.json \
  --out tmp/n0_pkg --prereg <e0_n0_prereg.json> \
  --main-commit c7b841efe67192a73a96894fb5a0243b336a9468 \
  --n0-config-sha256 <64-hex 占位>

# 2) 结构预检
python <probe_producer.py> --results-dir tmp/n0_pkg \
  --contract <e0_n0_producer_contract.json> --prereg <e0_n0_prereg.json>

# 3) 正式判读（预期：仅 N9 fail / S9）
python <accept_e0n0.py> --results-dir tmp/n0_pkg --prereg <e0_n0_prereg.json> --repo .

# 4) 自检（设 E0N0_PROBE / E0N0_ACCEPT / E0N0_PREREG / E0N0_CONTRACT 可跑集成）
python solutions/A/test_a_e0_n0_package.py -v
```

## 6. 裁定状态（2026-11-28 更新）

1. **`method_scope`**：已定稿为 `M0-DW-Subspace/rank-2/in-window-2coef`（逐字，无后缀）；打包器强制逐字匹配，合成夹具的 `"(synthetic fixture)"` 后缀已移除。见 `coordination/A_Q1_N0_PHASE_EVIDENCE.md` §5-8。
2. **`phase__coherence` 的 ρ**：已冻结为“同预登记簇另一组、参考通道 `rx63[27]`、全 1.4 GHz 频带上的宽带复相干模”，范围 `[0,1]`；`aligned := (ρ ≥ 0.001)`。见 `coordination/A_Q1_N0_PHASE_EVIDENCE.md` §3。
3. **`d1_min_abs_inner`**：已冻结为全池秩 2 基上 `min_f |⟨T(f),D1(f)⟩|/(‖T(f)‖‖D1(f)‖)`，范围 `[0,1]`；正确 Gram-Schmidt 下为 `0`–`1e-16`，是正交化**数值证书**；打包器强制 `rank=2 → ≤1e-6`。见同文件 §4。
4. **`n0_config.json`**：已落 `experiments/A/A-Q1-E0/n0/n0_config.json`，LF SHA256 `ec39673787e5dd05986095bca8f7c6cb41904dc13265e40798157ad9efadd32d`；打包器用 `--n0-config` 绑定 LF/raw 双口径，并把该值写入 `n0_config_sha256` / `n0.registration.n0_config_sha256`。见同文件 §5。
5. **探针 `READY` 是否作为 B-02 受理前置**：仍待统筹裁定；本轮合成包已再次确认 `READY 721/721`。

## 7. 边界

- 本轮**没有**实现 `execute`、**没有**运行 N0、**没有**读任何 `.dat`、**没有**改 `a_e0_n0.py` / `accept_e0n0.py` / `e0_n0_prereg.*` / 任何阈值。
- 打包器只做整形与自洽派生；`L1/L2` 判定仍由验收器重算，夹具里的 `PASS/FAIL` 只是原型合成值。
- 合成夹具**不得**用于论文、冻结材料或任何“方法有效”的表述；`READY` 也不等于验收通过。
