# A-Q1-N0 相位证据定义（`E0-N0-PHASE-EVIDENCE-1`）

| 项 | 值 |
|---|---|
| 定义编号 | `E0-N0-PHASE-EVIDENCE-1` |
| 作用对象 | `n0.phase`（契约 `E0-N0-PHASE-1`）中的 `phase__coherence` 与 `d1_min_abs_inner` |
| 基线 | `main = c7b841e`；N0 接口分支 `data/a-q1-n0-interface`；冻结预登记 `checks/A/e0_n0_prereg.json`（LF `721eb744…`） |
| 实现 | `solutions/A/a_e0_n0_phase.py`（度量）+ `solutions/A/a_e0_n0_package.py`（转写/校验） |
| 配置 | `experiments/A/A-Q1-E0/n0/n0_config.json`（LF `ec396737…`） |
| 自检 | `test_a_e0_n0_phase.py` 11/11、`test_a_e0_n0_package.py` 32/32 |
| 性质 | **只定义相位证据的度量口径**。不改 `accept_e0n0.py` 判据、不改任何数值门槛、不读 `.dat`、不跑 `execute`、不写冻结产物 |
| 边界 | 合成夹具只证明度量可复算与契约可读；不构成 N0 方法结论，不得进入论文或冻结材料 |

## 0. 一句话

**把两个原本“没有可复算语义”的字段钉死：`phase__coherence[g]` = 第 g 组与同预登记簇另一组在参考通道上的宽带复相干模（范围 `[0,1]`，由“校准 + 对齐后的复谱”直接算出）；`d1_min_abs_inner` = 全池秩 2 基 `[T, D1]` 上 `min_f |⟨T(f),D1(f)⟩| / (‖T(f)‖‖D1(f)‖)`（范围 `[0,1]`，正确 Gram-Schmidt 下为 `0`–`1e-16`，是正交化数值证书）。两者都由 `solutions/A/a_e0_n0_phase.py` 从数据重算，打包器只转写并校验，不再写 `[1.0]*10` / `0.0` 占位值。**

## 1. 为什么必须现在定义

验收器 `N7` 对这两个字段的现有约束是：

- `aligned == (rho >= 0.001)`：`0.001` 是预登记常量；但若 `rho` 没有定义，这条约束只是“`aligned` 与一个可随意填的数一致”；
- `d1_min_abs_inner` 只查“有限非负”：`0.0`、`1e-30`、`123` 都能过；
- 数组本身没有与任何复谱或基向量绑定。

因此在 B-02 之前必须给出**公式、范围、可复算来源**，否则 N0 的相位块只是形式证据。本定义同时满足：

1. 输入只依赖 `--mode execute` 已经在内存里的量（校准复谱、对齐偏移、秩 2 基），不新增数据读取；
2. 输出是标量/长度 10 的数组，能落进既有 `E0-N0-1` 契约，不改验收器；
3. 打包器能从证据文件**重算/逐元素校验**，不会出现“声明值 vs 数组两张皮”。

## 2. 符号与数据源

| 符号 | 含义 | 来源 |
|---|---|---|
| `g ∈ {data1…data10}` | 10 组空场，顺序 = 预登记 `air_groups` | `e0_n0_prereg.json#air_groups` |
| `(g_{k,0}, g_{k,1})` | 第 `k` 个预登记簇的两组，`k=0..4` | `e0_n0_prereg.json#clusters`（`C0..C4`） |
| `x_g(c,f)` | 第 g 组**校准后**复谱，`c` 为 63 个有效通道，`f` 为 1401 个频点 | `calibrate_pool(air_groups, λ=(1e-3,1e-3))`（`a_e0_n0.py`） |
| `x̃_g(c,f)` | 再乘 `exp(+1j·2π·f·shift_s[g])` 的**对齐后**复谱 | `align_spectra`（`a_e0_n0.py:416-418`） |
| `r*` | 参考通道，`r* = REF_POS = 27`（`rx63[27]`） | `a_e0_c._REF_POS` |
| `F` | 频带，`f ∈ [3.7, 2.3] GHz`，步长 `-1 MHz`，`|F| = 1401` | `E0S.Setup.f_r` |
| `T(f), D1(f)` | 全池（10 组对齐谱）秩 2 基 | `build_rank2_basis(stack)`（`a_e0_n0.py:424-557`） |

`stack` 的构造与 `run_synthetic` 完全一致：
`generate_synthetic_pool → calibrate_pool → x·inv → align_spectra → np.stack`。
`a_e0_n0_phase.py` **不运行 P1/P2 臂拟合**，只重建这同一条前处理链。

## 3. `phase__coherence`（ρ）

### 3.1 定义

对每个空场组 `g`，取同簇的另一组 `h`（锚点），在参考通道 `r*` 上算宽带复相干模：

```
z_g(f) = x̃_g(r*, f)                                      (f ∈ F)
ρ_g = | Σ_f conj(z_g(f)) · z_h(f) | / ( ‖z_g‖₂ · ‖z_h‖₂ )   ∈ [0, 1]
```

- 内积口径与 `np.vdot` 相同：`⟨a,b⟩ = Σ_f conj(a_f)·b_f`；
- 分子取复模，故 `ρ` 是实数、无量纲；
- 由 Cauchy–Schwarz，`ρ ∈ [0,1]`，`ρ=1` 当且仅当两序列在 `F` 上复正比（差一个复常数）；
- 簇内两组**共享同一个 `ρ`**（互为锚点，`|⟨z0,z1⟩|` 与 `‖z0‖‖z1‖` 都对交换对称）；
- 若任一侧范数为 0，按 `ρ := 0.0` 处理（退化，不抛异常）。

### 3.2 为什么用“同簇伙伴 + 参考通道”

- 相位对齐（`align_spectra`）是按**登记偏移**做的纯延迟校正，作用在全部通道上；参考通道正是秩 2 基 `D1` 的相位锚（`phase_anchor="ref_channel"`），用它不会引入额外的通道加权选择。
- 同簇伙伴是**预登记**的配对，不是看结果后挑的；`ρ` 因此不依赖任何拟合系数或阈值。
- 纯延迟残差会直接压低 `ρ`，与 `N7` 的 0.1 ns 簇内门槛形成同一物理量的两种表达：

| 簇内偏移误差 | `ρ`（1.4 GHz 带宽，解析 `|sinc(π·δ·Δf)|`） |
|---:|---:|
| 0 | 1.000 |
| 0.1 ns | 0.968 |
| 0.5 ns | 0.368 |
| 1.5 ns | 0.047 |

（表中 0.1 ns 的理论值 0.968 已由 `test_a_e0_n0_phase.py::test_pure_delay_reduces_coherence` 锁定为“严格小于 0.99”。）

### 3.3 `aligned` 判定

```
aligned_g := (ρ_g >= rho_min),  rho_min = 0.001   （预登记常量，不得改）
```

- `aligned = false` 时必须在 `per_group[g].reason` 写非空原因（打包器强制）；
- `phase__coherence[g]` 必须逐元素等于 `per_group[g].rho`（打包器强制，`1e-12`）；
- `0.001` 是**退化下限**（“完全没有相干”），不是“相位质量合格线”。N7 的 0.1 ns 簇内门槛才是精度门槛；两者分工不同，不能用一个替代另一个。

## 4. `d1_min_abs_inner`

### 4.1 定义

对全池秩 2 基 `T(f), D1(f) ∈ C^63`，逐频点算归一化复内积模，再取**未退化频点**上的最小值：

```
e_f = | ⟨T(f), D1(f) ⟩ | / ( ‖T(f)‖₂ · ‖D1(f)‖₂ )        ∈ [0, 1]
d1_min_abs_inner = min_{f ∈ F, ‖D1(f)‖ > 1e-12·‖T(f)‖} e_f
```

- 范围 `[0,1]`，无量纲；`D1` 近零的频点（Gram-Schmidt 判退化、`D1(f):=0`）不计入，并单独计数；
- 若全部频点退化 → `d1_rank := 1`，`d1_min_abs_inner := 0.0`（没有第二模态，按秩 1 解释）；
- 若 `d1_rank = 2`，打包器要求 `0.0 ≤ d1_min_abs_inner ≤ 1e-6`；超出即拒收（说明基未正交化，或值被手工填写）。

### 4.2 它是什么、不是什么

- **是** Gram-Schmidt 的**数值恒等式证书**：`D1` 由 `mode = T ⊙ v` 减去 `T` 分量得到，正确实现下 `⟨T,D1⟩` 应为 0；实测为 `0.0`–`2.2e-16`。若某版本漏做正交化，`e_f` 会变成 `O(1)`，该字段立即失败。
- **不是**“越大越好”的质量指标，也不是第二模态有效性的证明。第二模态质量看：
  - `d1_rank ∈ {1,2}`（是否退化）；
  - `sigma2_over_sigma1_median`（第二奇异值占比，合成夹具约 `0.11`）；
  - `ortho_rel`（近零内积事件的相对残差）。
- **`0.0` 是正确实现的期望值，不是占位符**。区别在于：旧包里的 `0.0` 是硬编码常量；本定义下它由交付的 `T/D1` 逐频点重算，基一变它就变。证据文件同时记录 `d1_max_abs_inner`（同一量的逐频点最大值）供审计；`max` 与 `min` 都远小于 `1e-6` 才说明整个频带都正交。

### 4.3 为什么取 `min` 而不是 `max`

契约字段名已冻结为 `d1_min_abs_inner`，且提案 §6-3 明确写“绑定 `|⟨D_1,T⟩|` 的最小绝对值”。本定义逐字采用；`max` 作为附加诊断写入证据文件（`d1.d1_max_abs_inner`），不进入 `E0-N0-1` 契约。若后续 ACCEPT-3 要提高强度，建议新增字段 `d1_max_abs_inner <= 1e-6`，而不是改动本字段的语义。

## 5. 打包器强制的不可变量

`a_e0_n0_package.py::_phase_block` / `from_prototype_synthetic` 现在强制：

1. `phase.rho_min == 0.001`（逐位）；
2. `per_group` 恰 10 组、顺序 = 预登记 `air_groups`、簇序 = `C0,C0,C1,C1,…,C4,C4`；
3. 每组 `rho` 为 `[0,1]` 内有限数；
4. `phase__coherence[i] == per_group[i].rho`（`1e-12`）；
5. `aligned[i] == (rho >= rho_min)`，且 `aligned=false` 必有 `reason`；
6. `shift_ns = shift_s × 1e9`；证据文件与 `fold_lock` 的换算值一致到 `1e-9 ns`；簇内两组差 `≤ 0.1 ns`；
7. `d1_min_abs_inner` **必须存在**（不得默认 `0.0`）；`rank=2` 时 `≤1e-6`，`rank=1` 时必须为 `0.0`；
8. `identity.method_scope` 逐字等于 `M0-DW-Subspace/rank-2/in-window-2coef`。

## 6. 合成夹具证据（不可引用）

命令：

```sh
python solutions/A/a_e0_n0_phase.py --synthetic-fixture \
    --out tmp/phase_evidence_synthetic.json
```

输入：`N0-SYN-1` 合成池（`seed=20261128`，`E0S.Setup(config.json)`），不读 `.dat`。
产物 SHA256（LF 口径）：`f4626f4a14d2d7bbc79982fc6b09ba031f2b7c92ad96ca01b8060e268f18b31a`（5,579 B）。

| 量 | 合成值 |
|---|---|
| `shifts_ns` | `0, 0.01475, 211.973, 211.97275, 723.26425, 723.2635, 340.13875, 340.1375, 625.38425, 625.38375` |
| 簇内最大偏移差 | `0.0 ns`（`max_dev_ns = 0.0`） |
| `rho` data1/data2 | `0.9999999999999998` |
| `rho` 其余 8 组 | `1.0`（合成组间只差复标度 + 1e-3 噪声） |
| `aligned` | 10/10 `true` |
| `d1_rank` | `2` |
| `d1_min_abs_inner` | `0.0` |
| `d1_max_abs_inner` | `2.1799e-16` |
| 非退化频点 | `1401 / 1401` |
| `sigma2/sigma1` 中位 | `0.11031` |

**说明：** 合成夹具的 `ρ≈1` 是构造使然（同簇两组只差复标度与 1e-3 噪声），只证明公式、范围、契约链路可跑通；**不能**据此声称真实数据相位质量。真实 N0 的 `ρ` 由 `--mode execute` 在同一函数上对 96 个 `.dat` 计算。

## 7. 可复算来源（真实执行路径）

`--mode execute` 已具备同一条前处理链（`run_synthetic` 的 `air_cal / air_aligned / stack`）。实现时直接调用：

```python
import a_e0_n0_phase as PH

ev = PH.build_phase_evidence(stack, basis_full, shifts_s)  # 核心字段
ev["seed"] = ...          # 可选元数据
ev["band_hz"] = ...
```

`build_phase_evidence` 内部就是 `coherence_table` + `d1_inner_stats`；`execute` 只需把
`cluster_shift_tol_ns` / `band_hz` 等元数据补齐，写成与合成证据同 schema 的
`phase_evidence.json`，随结果包一起交付。打包器用 `--phase-evidence` 读入并逐项校验；
**不接受**调用方直接填 `phase__coherence` 或 `d1_min_abs_inner`。

本轮已验证的入口是合成夹具：

```sh
python solutions/A/a_e0_n0_phase.py --synthetic-fixture --out tmp/phase_evidence_synthetic.json
```

它与 `build_phase_evidence` 共用同一对纯函数；真实执行不新增算法，只换输入谱。

## 8. 本轮没有证明什么

- 没有运行 `--mode execute`，没有读任何 `.dat`，没有产生真实 N0 数值；
- `N9`（`c0` 与 `b63e217` 基线等价性）仍按预期在合成包上 `FAIL → S9`，说明真实基线门仍生效，也说明本包**不是**真实验收通过；
- `d1_min_abs_inner` 的上界 `1e-6` 目前由**打包器**强制；`accept_e0n0.py`（ACCEPT-2）仍只查“有限非负”。建议 ACCEPT-3 增加 `d1_min_abs_inner <= 1e-6`（只增严），本轮不改验收器；
- `rho_min = 0.001` 仍是预登记常量；本轮不提议改阈值，只把 `ρ` 定义成可在 `[0,1]` 上解释的量。

## 9. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| `E0-N0-PHASE-EVIDENCE-1` | 2026-11-28 | 首次冻结：`ρ` = 同簇参考通道宽带复相干模；`d1_min_abs_inner` = 全池基归一化 `|⟨T,D1⟩|` 最小值；给出范围、来源、退化处理、打包器强制项与合成值 |
