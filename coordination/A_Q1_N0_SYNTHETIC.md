# A-Q1-N0 秩 2 合成原型：口径锁定与首轮结果（`N0-SYN-1`）

| 项 | 值 |
|---|---|
| 契约 | `N0-SYN-1`（**合成原型**，不是 N0 实测） |
| 判定口径 | `A-Q1-N0-DEC-2`（`coordination/A_Q1_N0_PROPOSAL.md` @ `4904bc8`） |
| 入口 | `solutions/A/a_e0_n0.py`（`--mode check` / `--mode synthetic`，**无 execute**） |
| 自检 | `solutions/A/test_a_e0_n0.py`（55 项，本机约 151–195 s，全 PASS） |
| 回归 | `solutions/A/a_e0_n0_channel_regression.py`（`N0-CHREG-1`，8 项自检，全 PASS） |
| 产物 | `experiments/A/A-Q1-E0/n0/synthetic/{n0_synthetic_results.json,N0_SYNTHETIC.md,SHA256SUMS.txt}`；`experiments/A/A-Q1-E0/n0/channel_regression/{n0_channel_regression.json,N0_CHANNEL_REGRESSION.md,SHA256SUMS.txt}` |
| 首轮结果 | 合成夹具 **L1 PASS / L2 FAIL（`S8`）**；`real_dat_reads=0`、打开的数据文件数 `=0` |
| 产物溯源 | 产物内含 `implementation_sha / implementation_dirty / generated_at / command / environment`；`--generated-at` 可逐字节复现 |
| 状态 | **待统筹复审**；N0 实测（B-02）、E0-C 重跑、E0-T 均**未放行** |

> 本文与产物一律 `synthetic=true` / `citable=false`：只验证 N0 的代码路径与 L1/L2 判定链条，
> **不是** N0 方法结论，不得进入论文数字、结果表、冻结证据或 E0-T 放行材料。

---

## 1. 本轮锁定的口径与证据链（代码里都是常量/守卫，不是可调参数）

### 1.1 分簇与训练范围

- 折分配**写成常量** `CLUSTERS = {(data1,data2), (data3,data4), (data5,data6), (data7,data8), (data9,data10)}`，
  与提案 §5.1 的固定配对逐项一致；`test_clusters_match_proposal_pairs` 逐对断言。
- 偏移名单 `BASELINE_SHIFTS_S` 直接登记 `b63e217#cal.shifts_s` 的 10 个值；自检会打开归档
  `experiments/A/A-Q1-E0/e0c/results/e0c_results.json` 逐值核对（9 位小数），确保没有编造。
- `assert_fold_lock()` 只做**校验**：10 组、5 簇各 2 组、互斥全覆盖、`max|Δshift| ≤ 0.1 ns`；
  超差即 `S5` 停。模块**没有**“用 N0 自己的 `shifts_s` 重新分簇”的入口——改折必须回统筹。
- 模板池：P1 每折留出**同簇 2 组**、模板恰为**其余 4 簇 8 组**；P2 十折 LOO 模板 9 组；
  目标组（墙体/金属）用全 10 组池。以上都在结果 JSON 的 `fold_plan` 里逐折列出。

### 1.2 跨频相位对齐

- 逐频点 SVD 得到的通道权重 `v(f)` 的相位是**任意**的；不接相位，延迟域投影 `z_D1(τ)` 会散开。
- 锁定做法：`v(f) ← v(f)·exp(-i·arg(v(f)[ref_pos]))`，参考通道 `ref_pos=27`（`rx63[27]==28`，与
  `a_e0_c._REF_POS` 一致）；`|v(ref)| < 1e-3·max|v|` 时退回 `argmax|v|`，并记录 `anchor_idx`。
- 负例自检：把同一权重逐频点乘随机相位，`z_D1` 在各通道 `τ_dir` 上的平均能量塌陷到
  `< 0.1`（`test_random_phase_negative_control_collapses_direct_delay_energy`）。

### 1.3 近零内积（含近零范数）

`build_rank2_basis()` 的守卫链（命中即退化，**不做近零除法**）：

1. `‖T(f)‖² ≤ 0` → 退化；
2. 相对偏差矩阵整列相对范数 `≤ 1e-9`（各组只差一个“整组复标度”或完全相同）→ 退化；
3. 第二模态基向量范数 `≤ 1e-12·‖T(f)‖` → 退化；
4. 与 `T(f)` 做 Gram-Schmidt 后残差相对范数 `< 1e-9`（几乎与 `T` 平行）→ 退化。

退化频率数 `> 0` 即 `near_parallel=true`、`rank_effective=1`，`c2` 自动退化为 `c1`（`b=0`），
结果 JSON 的 `n0.near_zero.events` 逐条登记。拟合侧另有 2×2 Gram 守卫：
`cond > 1e12` 或非有限时加相对岭 `trace·1e-12` 并标 `regularized=true`；第二模态能量占比
（相对**秩 1 拟合后的残余**）`< 1e-6` 时标 `second_mode_used=false`。

### 1.4 字面口径 vs 可实现口径：两处待确认差异 + 一处已修复缺陷（**请建模/统筹确认**）

合成原型把提案 §3 的两处字面写法跑出了可实现性问题，均已按“保留提案语义、写清实现差异”处理，
并在产物里显式记录：

**(a) 第二模态必须是“调制模态”，不能是单位范数的通道向量。**
提案 §3 写 “`D_1(f)` = 中心化偏差矩阵的第一左奇异向量”。若按字面取**单位范数、逐频点独立的通道
向量**（`mode_form="unit"`），它在直射波窗内几乎不携带能量：`A22/A11 ≈ 1e-15`，`c2` 与 `c1`
抑制完全相同（秩 2 名存实亡）。原因：单位范数向量没有 `T` 的频谱包络，压缩到延迟域后不落在
`τ_dir` 附近。原型默认改为**调制模态** `D_1(f) = T(f) ⊙ v(f)`（把通道权重调制到公共波形上），
此时 `A22/A11 ≈ 1.5e-2`、`c2` 比 `c1` 高 **+14.1 dB**（P1 min；修复通道相位约定后，见 (c)）。
→ 请 `@antigravity02` 确认这与 `model_q1.md` §5.2 `M0-DW-Subspace` 的“第二模态”是否等价；
若建模方坚持字面定义，则需明确“秩 2 在该窗内不可识别”，N0 的 P1/P2 只能按秩 1 解释。

**(b) SVD 前必须扣掉“整组复标度”方向。**
相对偏差 `(X_g − T)/T` 里含一项与通道无关的复常数（整组幅相差异），它恰好是 `a·T` 能精确吸收的
方向。若不扣，合成对照里第一奇异向量就是它，`D_1` 只剩一个复标度（`‖D_1‖/‖T‖ ≈ 1.5%`），
`c2` 同样退化。原型在 SVD 前对 `(X_g − T)/T` 做**通道去均值**（等价于强制 `D_1 ⟂ 1`），
保证第二模态只表示跨通道差异。这是可识别性约束，不是调参。

两项都只影响**实现口径**，不新增/放宽任何门槛；`P1/P2/P3/P4/C9b` 数值全按提案原式。

**(c) 通道模态取向量约定（复数相位，codex 2026-11-28 复核发现并已修复）。**
`rel_dev` 是「组 × 通道」矩阵，`numpy` 的 `A = U·S·Vh` 意味着
`A[g,c] = Σ s_k u_k[g]·conj(v_k[c])`，**行方向是 `conj(v_k)`，而 `Vh` 的行正好就是它**。
原型初版写成 `v = vh[0].conj()`，把相对通道相位整体反转。合成/实测流水线里 `T` 是
**组均值**，`rel_dev = (X−T)/T` 带着 `T` 的逐通道相位、行方向本身是复向量，因此这不是
全局相位问题：`D_1` 会变成 `dev ⊙ exp(2i∠T)` 而不是 `dev`。

- 修复：`v = vh[0]`（一行），数值内核零改动；
- 回归：`solutions/A/a_e0_n0_channel_regression.py`（契约 `N0-CHREG-1`）用解析夹具
  `γ = (1, e^{2πi/3}, e^{4πi/3})/√3`（`Σγ = 0` 且 `Σγ² = 0`）在允许任意全局相位的
  判据下验证方向恢复与行重建；旧式 `vh[0].conj()` 作为负例被同一夹具抓住
  （方向误差 √2、行残差 27.7%–50%、`b ≡ 0`）；实方向 + 共用 `T` 的旧夹具则完全
  分辨不出（这正是初版 41 项自检漏掉它的原因）；
- 影响：P1 min **23.179 → 26.115 dB**、P2 min **24.570 → 28.396 dB**、`c2−c1`
  （P1/P2 min）**11.168/11.650 → 14.104/15.476 dB**；**判定不变**（`L1=PASS`、
  `L2=FAIL（S8）`、`P3/P4/C8′/P5a` 仍 PASS）；
- 产物已重新生成；当前 SHA256 见 `SHA256SUMS.txt`
  （`n0_synthetic_results.json = 69aca85a…b3ce07d`、`N0_SYNTHETIC.md = 644e5b4f…a18067ad`）。
  `e235c3a` 的产物（`731d5935…` / `90259f7e…`）可用该提交复跑；修复前字节
  （`e2835b91…` / `0c342a4f…`）可用 `207510c` 逐字节复现，证据见
  `experiments/A/A-Q1-E0/n0/channel_regression/`。

### 1.5 证据链与复算口径（codex 2026-11-28 复审后的修订）

1. **LF 锁定（F1）**：`.gitattributes` 只对纳入 `SHA256SUMS` 的三份 JSON 钉 `eol=lf`
   （synthetic / channel_regression / poststop），避免 `core.autocrlf=true` 的 Windows
   干净检出把 JSON 变成 CRLF 导致摘要必失败；`e0c/results`、`s1s2/results` 等冻结登记
   不在本次覆盖范围，保持原有 CRLF 字节。已在独立 worktree（`core.autocrlf=true`）实测：
   三份 JSON 均为 LF，摘要逐字节一致。
2. **生成溯源（F2）**：产物新增 `provenance` 块——完整 `implementation_sha`、`dirty`、
   `generated_at`（显式参数 > `SOURCE_DATE_EPOCH` > 系统时钟）、实际命令、Python/NumPy/
   平台；`--generated-at` 固定时可逐字节复现。当前合成产物由 `6b08846` 在干净工作区生成
   （`implementation_dirty=false`）。
3. **C8′ 覆盖 P2 十折（F3）**：`C8′` 现在逐值覆盖 P1 五折 30 值 + P2 十折 30 值 + 目标侧
   6 值，共 **66 值**；数组路径改为与 `c0/c1/c2` **同模型**（c0 `a≡1,b=0`；c1 只解 `a`；
   c2 解两系数），不再出现“模型差冒充实现差”。`max|ΔSupp| = 9.67e-12 dB`、
   `max|Δcoeff| = 9.82e-15`。
4. **P3 锚点（F4）**：墙体 `pnr_db` 锚点由 `34.2870` 校正为归档值 `34.293809`；
   自检逐项比对归档 `e0c_results.json`。
5. **P5a/口径（F5/F6）**：`lambda_fixed`、`fit_window_ns` 成为真正参与判定的布尔项；
   `scope.note` 明确 `opened_files`/`real_dat_reads` 只统计实验数据文件，不含 config/归档。

---

## 2. 首轮合成结果（`--mode synthetic`，seed `20261128`，1 mm 剖面网格）

| 臂 | P1 min | P1 median | P1 档 | P2 min | P2 median | P2 档 |
|---|---:|---:|---|---:|---:|---|
| `c0`（Σ 均值，a≡1） | 9.187 | 12.348 | `not_met` | 9.252 | 12.709 | `not_met` |
| `c1`（单秩窗内拟合） | 12.011 | 13.481 | `met` | 12.920 | 14.490 | `met` |
| `c2`（秩 2，本提案） | **26.115** | 26.998 | `met` | **28.396** | 29.971 | `met` |

对照：`c2−c1`（P1 min）`+14.104 dB`、`c2−c0`（P1 min）`+16.928 dB`、`c2−c1`（P2 min）`+15.476 dB`。
（以上为**修复 `vh[0].conj()` 之后**的数值；修复前为 23.179 / 24.570 dB 与 11.168 / 11.650 dB，
判定链相同，见 §1.4(c)。）

目标侧（全 10 组池，c2）：

| 目标 | Supp (dB) | PSLR (dB) | PNR (dB) | `d_hat` (m) | abs_err (cm) | 峰值保留 (dB) | 测距偏移 (mm) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 墙体 `data1-42cm` | 18.697 | 9.388 | 78.339 | 0.421000 | 0.100 | −0.017 | +0.9 |
| 金属 `data1-69cm` | 32.352 | 9.207 | 78.234 | 0.690000 | 0.000 | −0.003 | −0.5 |

守卫：P3 单侧非退化 **PASS**、P4（−0.1 dB / 2 mm）**PASS**、C8′ 固定 λ 逐值复算
`max|Δ| = 9.67e-12 dB` **PASS**（P1/P2/目标侧 **66 值**全覆盖，数组路径与各臂同模型）、
P5a **PASS**、近零内积事件 **0**。

判定链：**L1 = `pass`**（P1/P2 均 `met`，P3/P4/P5a 全过）；**L2 = `fail`**，原因只有
`freeze.status='not_eligible_for_freeze'` 与 `e0c_frozen.json` 不存在 → 落 `S8`
（“抑制方法达标、整轮不可冻结”），与提案 §6 的语义一致。**合成夹具本来就不产生冻结证据，
这不是方法失败，也不是可冻结的证明。**

---

## 3. 与 `25c1f4d` 同批纳入

`25c1f4d` 的 `solutions/A/e0c_official_precheck.py` 复用**主线** `checks/A/e0_c_accept/accept_e0c.py`
（已在本批基线 `934b089` 内），并新增 `test_e0c_official_precheck.py`（报告聚合、C12 判定映射、
缺报告/拒绝覆盖的守卫），因此按 codex “可复用主线验收器且有测试”的条件同批纳入。

## 4. 复跑命令与版本标识

```bash
# 只读自检（不生成合成数据、不读 .dat）
python solutions/A/a_e0_n0.py --mode check

# 合成夹具全流程（本机约 2–3 min）
python solutions/A/a_e0_n0.py --mode synthetic \
  --out experiments/A/A-Q1-E0/n0/synthetic --overwrite

# 复数秩一通道模态回归（N0-CHREG-1，约 0.1 s）
python solutions/A/a_e0_n0_channel_regression.py \
  --out experiments/A/A-Q1-E0/n0/channel_regression

# 自检（55 项，本机约 151–195 s）
python solutions/A/test_a_e0_n0.py
```

- 主分支基线：`934b089`（PR #33 已合入）；本批分支 `data/a-q1-n0-batch`（PR #41）。
- 产物 SHA256 按 **LF 归一化**计算（`lf_sha256`，与 `b63e217` 产物同口径）；纳入摘要的
  三份 JSON 已由 `.gitattributes` 钉 `eol=lf`，`core.autocrlf=true` 的干净检出也可复核。
- 合成夹具：`E0S.synth_group_spectrum`（直射波 + 1/R 回波）+ `E0S.calibrate_air(λ_cal=λ_inv=1e-3)`；
  五簇第一模态通道形状相同、簇复系数不同（秩 2 可精确表示），第二模态逐簇不同（留给残差）。
- 数值内核未改动；`E0-C` 仍硬停、`E0-T` 未放行、N0 实测未开工。

## 5. 交给统筹/建模的具体问题

1. `@codex`：确认 `S8` 作为合成原型的**预期**输出（L2 必 FAIL），并确认 `N0-SYN-1` 只作“代码路径
   + 判定链条”证据、**不**触发 B-02 放行。
2. `@antigravity02`：确认 §1.4(a) 的调制模态 `D_1 = T⊙v` 与 `model_q1.md` §5.2 的等价性；若不等价，
   请给出替代的“第二模态”定义（要求：与 `T` 可分离、在直射波窗内有能量）。
3. `@my_deepseek`：按本文件 §1 的四项锁定搭独立复算（折分、相位锚、近零内积、C8′ 双路径），
   重点检查“退化时 c2 必须逐值等于 c1”与“`anchor_idx` 处处为 27”。
4. `@codex`：PR #41 上要求的**复数秩一回归已交付**（`N0-CHREG-1`）：解析夹具
   `(1, e^{2πi/3}, e^{4πi/3})/√3` 下确认旧式 `vh[0].conj()` 会反转相对通道相位
   （方向误差 √2、行重建残差 27.7%–50%、`b ≡ 0`），已修正为 `vh[0]` 并重生成合成产物；
   证据 `experiments/A/A-Q1-E0/n0/channel_regression/`，请复审后裁定合并。
5. `@codex`：复审后的四项证据链修订（F1 LF、F2 溯源、F3 C8′ 覆盖 P2、F4 PNR 锚点）
   连同 P5a/scope 两项建议（F5/F6）已在 PR #41 同一分支完成，见 §1.5；请按新产物
   SHA（`69aca85a…` / `644e5b4f…`）复审。
