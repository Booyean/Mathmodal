# A 题 D1 契约：单周期折迭与跨包/包内一致性门控

- **任务 / 分支**：D1-2 / `data/a-q1-fold-gate-d1-2`（基线 `main` = `f56dbc0`）
- **主责**：`dsh`（数据与求解）；验收：`my_deepseek`；统筹：`codex`
- **输入基线**：`main` = `f56dbc0`（D1-1 已由 PR #12 合并）；原始数据基线 = `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9`
- **契约版本**：`D1-2`（实现常量 `CONTRACT_VERSION = "D1-2"`）；D1-1 的公式、阈值与验收结论不变，D1-2 只修 F1/F2 两项已知缺陷
- **实现**：`solutions/A/a_fold_gate.py`；测试：`solutions/A/test_a_fold_gate.py`
- **依据**：`solutions/A/model_q1.md` §1.2（周期边界与异步采集）、§1.2.3（多包与跨行一致性门控）、§7.2（已批复预处理输出）；`solutions/A/data_contract.md` D0-4（输入契约）；`coordination/A_Q1_PLAN.md` A-Q1-M0 批复段
- **上级任务**：`codex` 派工——从最新主线开 D1-2，修 F1（锚包极性/包顺序依赖）与 F2（非有限值防护），仅用合成例与空场 `data1` 复核；不得引入相位/时延补偿，E0 实测前须独立复验。

> 本文件只描述 **D1 预处理**：16000 点 → 4×4000 周期折迭、包内 4 段相干性门控、包间参考通道相位门控、拒绝日志。校准、直射波抑制、测距、漂移补偿和任何标签划分都不在本契约内。

---

## 0. 边界

**做**

- 把 D0 `packets (P, 64, 16000)` 按 `Np = 4000` 折迭为 `Q = 4` 段，每段 `(64, 4000)`。
- 在工作频带 `B = [0.3, 1.7] GHz` 内构造每段的带限正频谱，计算**包内 4 段相干增益** `gamma`。
- 以参考通道 `i_ref = 28` 计算**包间复相干** `rho`、**群时延漂移** `delta`、**去时延后的常相位** `phi` 与**增益变化** `gain_db`。
- 只保留通过门控的包做**等权相干平均**，输出 `signals_folded (64, 4000) float64`。
- 每个包输出可复跑的**拒绝日志**（统计量、阈值、原因码）。

**不做**

- 不做逐包/逐行的相位补偿、时偏对齐、载波滑移修正（门控只拒绝，不修正）；不做重采样、插补、去噪、带通滤波后的输出。
- 不做校准、直射波抑制、测距、成像；不改变 D0 的 `packets`/`sync`/`rx_mask`/`channel_valid`。
- 不读写任何校准/检验标签，不按距离或数据集选择门控参数。

---

## 1. 输入

### 1.1 对象

`fold_group(group: GroupData)` 的输入是 D0 `load_group()` 的返回值（`solutions/A/data_contract.md` §2.1）：

| 字段 | 形状 / 类型 | 用途 |
|---|---|---|
| `packets` | `(P, 64, 16000)` `int16` | 原始 ADC 计数，**未标定**；D1 只做升位与平均 |
| `sync` | `(P,)` `int64` | 共同 `sync_packet_cnt` 升序；日志主键 |
| `rx_mask` | `(64,)` `bool` | `rx_mask[27]=False`，其余 63 路为 True |
| `channel_valid` | `(64,)` `bool` | 缺行/整行无有效包时为 False；不参与包内中位数 |
| `positions_m` | `(64,3)` `float64` | 原样透传，D1 不使用几何 |

### 1.2 采样配置（题面补充说明，不是 `.dat` 头字段）

| 量 | 值 |
|---|---|
| 采样率 `fs` | `4.0e9 Hz` |
| 采样间隔 `Ts` | `2.5e-10 s` |
| 单周期点数 `Np` | `4000` |
| 每包点数 | `16000 = 4 Np`，即 `Q = 4` 段 |
| 工作频带 `B` | `[0.3, 1.7] GHz`，对应 `rfft` 整数 bin `k ∈ [300, 1700]`（含端点，共 **1401** bin） |

带内 bin 用整数公式 `k_lo = round(f_start·Np/fs)`、`k_hi = round(f_stop·Np/fs)` 固定，**不用浮点比较**（浮点会漏掉 0.3 GHz 的边界 bin）。

---

## 2. 折叠模型与统计量

### 2.1 分段

第 `p` 个共同包、通道 `i`、第 `q ∈ {0,1,2,3}` 段：

```
x[p,i,q,m] = packets[p,i, q*Np + m],   m = 0..Np-1
```

`q` 的段起点相差恰好 `Np Ts = 1 µs`。按 M0 §1.2，**段与段之间是否同相不是先验已知**，故必须先检验再平均；D1 不假定起点已对齐。

### 2.2 带限正频谱

对每段做实数 FFT 并只保留 `B` 内正频率 bin：

```
S[p,i,q,k] = 2 · rfft(x[p,i,q,:])[k],    k_lo <= k <= k_hi
```

系数 2 是实信号单边谱到复解析信号的约定；它只影响幅度标度，**不影响**下面所有归一化统计量与实值折叠输出。`f_k = k·fs/Np`（1 MHz 栅格）。

### 2.3 包内 4 段相干增益（`gamma`）

```
A[p,i,k] = Σ_{q=0}^{Q-1} S[p,i,q,k]
gamma[p,i] = Σ_k |A[p,i,k]|² / ( Q · Σ_q Σ_k |S[p,i,q,k]|² )   ∈ [0,1]
```

性质与依据：

1. `gamma = 1` 当且仅当 4 段只差一个公共复常数（幅度与相位完全一致）；`gamma = 1/Q = 0.25` 是 4 段相位独立的期望值。
2. 等幅小相位展开时 `gamma ≈ 1 - sigma_phi²`，`sigma_phi` 为 4 段相位的总体标准差（rad）。因此 `gamma ≥ 0.99` 等价于**段间 RMS 相位散布 ≤ 0.1 rad（5.7°）**，相干平均幅度损失 `≤ 0.5%`。
3. `gamma` 同时随**单段信噪比**下降（`gamma ≈ SNR/(1+SNR)`）：弱通道 `gamma` 偏低可能只是噪声大，不一定是"不同相"。故 `gamma` 只作门控与诊断，**不对单通道判死**；包级门控用参考通道 + 有效接收通道中位数（见 §3.1）。

### 2.4 包间参考通道统计量（`rho`、`delta`、`phi`、`gain_db`）

只取参考通道 `i_ref = 28`（第 4 行第 5 列，与发射天线间距 7 cm，直达波最强，M0 §1.1 的 gauge anchor）。记包 `p` 的折迭谱：

```
A_p[k] = A[p, i_ref, k],   k_lo <= k <= k_hi
```

对包 `p` 与锚包 `a`（锚包选择见 §3.2）：

```
C_p[k] = A_p[k] · conj(A_a[k])
rho_p  = |Σ_k C_p[k]| / sqrt( Σ_k |A_p[k]|² · Σ_k |A_a[k]|² )     ∈ [0,1]
```

- `rho_p = 1`：两包折迭波形只差一个公共复常数；`rho_p = 0`：完全不相关。
- 对纯时延 `delta`（包 `p` 相对锚包滞后为正），`C_p[k] ∝ exp(-j 2π f_k delta)`，故 `rho_p = |sinc(π B_eff delta)|`（矩形谱近似）。`rho ≥ 0.99` 对应 `delta ≲ 55 ps`（`B_eff = 1.4 GHz`）。

群时延与常相位（加权最小二乘 + 去时延后的相干相位）：

```
w_k = |C_p[k]|
对 (f_k, unwrap(angle C_p[k])) 做加权直线拟合  phi(f) = phi_0 + slope·f
delta_p = -slope / (2π)                       [s]
phi_p   = angle( Σ_k C_p[k] · exp(+j 2π f_k delta_p) )   [rad]
```

- `delta_p` 是包间**群时延漂移**（正 = 包 `p` 滞后），不是绝对传播时延，也不是距离。
- `phi_p` 是把线性时延项扣掉后的**常相位**；纯时延给出 `phi = 0`，而 `-1` 倍信号（极性/载波翻转）给出 `|phi| = π`。这一项专门拦截 `rho` 无法区分的**载波相位翻转**（`rho = 1` 但相干平均会相互抵消）。
- 相位拟合只在 `|C_p| ≥ 1e-9·max|C_p|` 的 bin 上做，避免近零 bin 破坏 `unwrap`。

增益变化：

```
gain_db[p] = 20·log10( rms_ref[p] / rms_ref[anchor] ),   rms_ref[p] = sqrt(mean(x[p,i_ref,:]²))
```

### 2.5 折叠输出

设通过门控的包集合为 `P_acc`：

```
y[i,m] = (1/|P_acc|) · Σ_{p∈P_acc} (1/Q) · Σ_q x[p,i,q,m]      -> signals_folded (64,4000) float64
```

**等权、无相位补偿**：被接受的包已经通过 `rho/phi/delta` 门控，残余相位散布 `≤ 0.1 rad`，相干平均损失 `≤ 0.5%`；因此不做逐包旋转或时移。未被接受包的任何样本都不进入 `y`。`channel_valid=False` 的通道在 D0 中即为 0，D1 保持 0 并原样透传 `channel_valid`，下游不得当作有效测量。

---

## 3. 门控规则与阈值依据

默认参数 `GateParams`（全部可在调用时覆盖）：

| 参数 | 默认 | 物理含义 | 依据 | 空场 `data1` 实测 | 余量 |
|---|---|---|---|---|---|
| `gamma_ref_min` | `0.99` | 参考通道 4 段相干增益下限 | `gamma ≈ 1-σ_φ²`；`0.99 ⇔ σ_φ ≤ 0.1 rad`，幅度损失 ≤ 0.5% | `0.999876 ~ 0.999983` | `1-gamma` 约 80× |
| `gamma_median_min` | `0.95` | 63 路有效接收通道 `gamma` 中位数下限（整阵粗检） | 容忍孤立弱通道，只拦整阵不同相；`0.95 ⇔ σ_φ ≤ 0.22 rad` | `0.999024 ~ 0.999733` | `1-gamma` 约 20× |
| `rho_min` | `0.99` | 包间参考通道复相干下限 | 归一化失配能量 ≤ 1%；纯时延下 `rho=|sinc(πBδ)| ⇔ δ ≤ 55 ps` | `0.999979 ~ 0.999996` | `1-rho` 约 200× |
| `delta_max_ps` | `50` | 包间群时延漂移硬上限 | `50 ps = 0.2 Ts`；距离涂抹 `c·δ/2 = 0.75 cm`，小于测距采样步长 `3.75 cm` 的 1/5；与 `rho=0.99` 的 55 ps 自洽 | `|δ| ≤ 2.3 ps` | 约 20× |
| `phase_max_rad` | `0.1` | 去时延后常相位上限 | `cos(0.1)=0.995`，相干损失 ≤ 0.5%；拦截 `|phi|=π` 的载波/极性翻转 | `|phi| ≤ 0.026 rad` | 约 4×（对 `π` 翻转约 120×） |
| `gain_max_db` | `3` | 包间参考通道 RMS 变化粗检 | 3 dB = 2 倍功率；采集平稳时不应出现，否则等权平均被大包主导 | `|gain| ≤ 0.005 dB` | 约 600× |

> `gamma` 随单通道 SNR 下降（`gamma ≈ SNR/(1+SNR)`），弱通道 `gamma` 低不等于"不同相"；因此 `gamma` 只对参考通道与整阵中位数设门控，单通道 `gamma` 仅作诊断（`n_rx_below_gamma`），不判死通道。

### 3.1 包内门控

包 `p` 通过包内门控当且仅当：

1. `channel_valid[i_ref] = True` 且参考通道样本有限、`rms_ref[p] > 0`；
2. **该包 64 个通道的样本全部有限**（D1-2/F2；任一通道 NaN/Inf 即整包拒绝）；
3. `gamma[p, i_ref] ≥ gamma_ref_min`；
4. `median_{i ∈ rx_mask ∧ channel_valid} gamma[p,i] ≥ gamma_median_min`。

`gamma_active` 只在 `den > 0` 的通道上定义；非有限通道不进入中位数，但会使整包被拒（不因“该通道无效”而放行）。

### 3.2 包间门控

1. 只在**通过包内门控**的包中选锚包 `a`（D1-2/F1 评分）：
   - 对每个候选 `c`，以 `c` 为锚，按 §2.4 计算其余候选的 `rho/delta/phi/gain_db`，统计**同时通过下面四项门限**的同伴数 `n_ok(c)`；
   - 评分 `(n_ok(c), median_rho(c), -index(c))` 取字典序最大：先比 `n_ok`，再比到其余候选的 `rho` 中位数，最后取共同包序号较小者；
   - 只有一个候选时它就是锚包。
   - 该评分与下面的门控**同一把尺**，因此极性/载波翻转（`rho = 1` 但 `|phi| = π`）不会因 `rho` 并列被选为锚包；D1-1 的“`rho` 中位数最大”规则只在 `n_ok` 并列时作为 tie-break 保留。
2. 包 `p` 通过包间门控当且仅当（锚包自身恒通过）：
   - `rho_p ≥ rho_min`；
   - `|delta_p| ≤ delta_max_ps`；
   - `|phi_p| ≤ phase_max_rad`；
   - `|gain_db[p]| ≤ gain_max_db`。
3. 全部包都未通过时 **抛 `FoldGateError`**（附完整日志），不返回全零/伪造信号。

**已知限制（1 对 1 冲突）**：若只有两个候选且二者互不一致（例如一正一翻转），两者 `n_ok` 都是 1，评分退化为按共同包序号定序：只保留序号较小者那一侧，另一侧被拒。无多数可依时不存在无偏选择；D1-2 不虚构“多数”，也不混合两侧。两个等规模互斥簇同理，按包序号定序。该情形在真实数据的记录中应作为“无法判定”人工复核，不得解释为门控给出了物理结论。

**范围说明（F3）**：包间门控只以参考通道 `i_ref = 28` 为判据。它保证参考通道的相位漂移与相干损失上限，**不保证全部 63 路接收通道**的相位漂移或相干损失都低于同一界；每通道 `segment_coherence` 与 `channel_summary` 只是诊断，不得当作全通道一致性证明。

### 3.3 拒绝原因码

| 码 | 触发 |
|---|---|
| `reference_channel_invalid` | `channel_valid[28] = False`（最先判定） |
| `reference_channel_nonfinite` | 参考通道出现非有限值（优先于 `packet_nonfinite_samples` 记录） |
| `reference_channel_zero_energy` | 参考通道 RMS = 0 |
| `packet_nonfinite_samples` | 参考通道有限，但其余任一通道出现 NaN/Inf（D1-2/F2；`nonfinite_channels` 列出全部通道） |
| `intra_segment_low_gamma_ref` | `gamma[p,28] < gamma_ref_min` |
| `intra_segment_low_gamma_median` | 有效接收通道 `gamma` 中位数 `< gamma_median_min` |
| `inter_packet_low_coherence` | `rho_p < rho_min` |
| `inter_packet_delay_drift` | `|delta_p| > delta_max_ps`，或 `delta_p` 无法估计 |
| `inter_packet_phase_offset` | `|phi_p| > phase_max_rad`，或 `phi_p` 无法估计 |
| `inter_packet_gain_jump` | `|gain_db[p]| > gain_max_db`，或增益无法计算（RMS ≤ 0/非有限） |

---

## 4. 输出

### 4.1 `FoldedGroup`

| 字段 | 类型 | 形状 | 说明 |
|---|---|---|---|
| `signals_folded` | `float64` | `(64, 4000)` | 单周期实值折叠信号；等权相干平均，无相位补偿 |
| `sync` | `int64` | `(P,)` | D0 共同 `sync`，原样 |
| `accepted` | `bool` | `(P,)` | 是否进入折叠 |
| `segment_coherence` | `float64` | `(P,64)` | §2.3 的 `gamma` 全矩阵（诊断） |
| `packet_log` | `list[dict]` | `P` | §4.2 逐包日志 |
| `channel_summary` | `list[dict]` | `64` | 每通道 `gamma` 中位数/最小值、折叠 RMS、`rx`/`valid` 标记（诊断） |
| `meta` | `dict` | — | §4.3 |
| `rx_mask` / `channel_valid` / `positions_m` | 原样 | — | 透传 D0 |

### 4.2 逐包日志字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `index` / `sync` | int | 包序号 / `sync_packet_cnt` |
| `ref_rms` | float | 参考通道全 16000 点 RMS（ADC 计数） |
| `packet_finite` | bool | 该包 64 通道样本是否全有限（D1-2/F2） |
| `nonfinite_channels` | list[int] | 含 NaN/Inf 的通道号（升序；全有限时为空） |
| `gamma_ref` | float | `gamma[p,28]` |
| `gamma_median_rx` / `gamma_min_rx` | float | 有效接收通道 `gamma` 的中位数 / 最小值 |
| `n_rx_below_gamma` | int | 有效接收通道中 `gamma < gamma_ref_min` 的个数（只作诊断，不判死通道） |
| `seg_delta_ps` | list[float] | 段 `q=1..3` 相对段 0 的群时延（ps），诊断包内时钟漂移 |
| `intra_pass` | bool | §3.1 |
| `inter_evaluated` | bool | 是否进入包间比较（仅 `intra_pass` 为真时） |
| `rho` / `delta_ps` / `phi_rad` / `gain_db` | float \| null | §2.4；未评估时为 null |
| `anchor` | bool | 是否为锚包 |
| `inter_pass` | bool | §3.2 |
| `accepted` | bool | 最终是否进入折叠 |
| `reject_reasons` | list[str] | §3.3 原因码，按固定顺序 |

### 4.3 `meta` 关键项

`contract_version`、`group_key`、`n_packets`、`n_intra_pass`、`n_accepted`、`accepted_sync`、`rejected_sync`、`anchor_index`、`anchor_sync`、`n_period_samples`、`n_segments`、`fs_hz`、`ts_s`、`band_hz`、`band_bins`、`n_band_bins`、`gate`（全部阈值）、`fold`（`mode="coherent_equal_weight"`、`phase_compensation="none"`、`n_packets_folded`）、`rx_mask_true_count`、`positions_source`。

### 4.4 输出不变量（D1-2/F2）

1. 成功返回的 `signals_folded` 必须**全有限**（`np.isfinite(...).all()`）。
2. 非有限样本在门控阶段即整包拒绝；折叠后另设最后防线：若仍出现非有限值，抛 `RuntimeError`（属内部不变量破坏，不归类为 `all_rejected`），**不返回**含 NaN/Inf 的信号。
3. `packet_log` 中非有限通道按升序完整记录；`ref_rms` 等统计量若本身非有限，JSON 输出时由 `_json_ready` 转为 `null`（不写 `NaN` 字面量）。

---

## 5. 空场 `data1` 单组诊断（D1-2 复跑；数值与 D1-1 逐位一致）

对象：`附件2-测距数据/空场数据/data1`，`sync_common = [114, 115, 116, 117]`，`P = 4`，8 行齐全，`rx_mask` 63 路。

| 包 | `sync` | `gamma_ref` | `gamma_median_rx` | `rho` | `delta_ps` | `phi_rad` | `gain_db` | 结果 |
|---|---|---|---|---|---|---|---|---|
| 0 | 114 | 0.999891 | 0.999731 | 0.99999556 | −0.253 | −0.00800 | +0.0015 | 接受 |
| 1 | 115 | 0.999983 | 0.999733 | 1.0（锚包） | 0（锚包） | 0（锚包） | 0（锚包） | 接受（锚包） |
| 2 | 116 | 0.999914 | 0.999729 | 0.99999634 | −0.207 | +0.00106 | −0.0041 | 接受 |
| 3 | 117 | 0.999876 | 0.999024 | 0.99997906 | −2.271 | −0.02539 | −0.0022 | 接受 |

- D1-2 复跑：`anchor_index = 1`（与 D1-1 相同，未受锚包评分改动影响）；`contract_version = D1-2`；每包新增 `packet_finite = true`、`nonfinite_channels = []`；`segment_coherence` 与 D1-1 的最大绝对差为 `0.0`。差异仅在版本串与新增字段。
- 包内相位漂移（段 `q=1..3` 相对段 0，仅供参考）：包 0 `[+2.84, +0.18, −0.36] ps`、包 1 `[+1.49, −0.59, −0.76] ps`、包 2 `[−1.24, −0.05, −0.91] ps`、包 3 `[+0.03, −0.57, +1.41] ps`；均 ≪ `1 µs` 周期，支持"公共异步零点"假设在本组成立。
- 有效接收通道中 `gamma < 0.99` 的个数：包 0/1/2/3 = `0/1/2/3`，均为远排弱通道（如 ch62 rms≈306），不是整阵失相；`gamma_median_rx ≥ 0.9990`。
- `signals_folded`：`(64, 4000)` `float64`，全有限；有效接收通道折叠 RMS 中位数 `1950.7`、最小 `302.5`、最大 `10979.4`（参考通道 28 为 `9700.9`）；发射通道 27（`rx=False`）折叠 RMS `13.7`，仅登记不使用。
- 折叠结果与"对通过包直接做双重平均"逐点相等（`max|diff| = 0`，测试 `R1j`）。
- 逐包折迭均值与最终折叠的参考通道相关系数：`0.999987 / 0.999992 / 0.999980 / 0.999973`，与 `rho` 一致。

复跑：

```powershell
python solutions/A/a_fold_gate.py --diagnose "附件2-测距数据/空场数据/data1" --json solutions/A/fold_gate_diag_data1.json
```

诊断 JSON（本分支提交）：`solutions/A/fold_gate_diag_data1.json`（含 `meta`、`packet_log`、`segment_coherence (4,64)`、`channel_summary`；D1-2 新增 `packet_finite`/`nonfinite_channels`）。

**结论（仅限本组）**：4 个共同包全部通过 D1-2 门控，且各项指标对默认阈值有 4×–600× 余量；本组可直接进入后续校准/测距。该结论不外推到墙体/金属板/附件 3，也不代表全通道一致性。

---

## 6. 未知项与待确认

| 编号 | 未知项 | 影响 | 需要什么 |
|---|---|---|---|
| O-D1-01 | 组内包间 `t0` 是否总为公共值 | 若不等且超过门控，D1 只能拒绝而不能对齐（漂移补偿未获批复） | E0 前逐组诊断 |
| O-D1-02 | 行板级异步抖动 `delta t_{g,r}` 的量级 | 跨行相位门控只用参考通道，不覆盖行板差异 | 后续行板相关统计（M0 §4.1.3） |
| O-D1-03 | `gamma` 阈值在弱回波组（附件 3/远距离）的可分性 | 弱通道 `gamma` 受 SNR 限制，可能整阵中位数下降 | E0 登记的逐组预检 |
| O-D1-04 | 段内/包内是否存在器件非线性导致的非纯时延相位 | `phi` 门控只拦常数相位，不拦色散 | M0 的 `S_eff` 环节处理 |
| O-D1-05 | 单组诊断只覆盖空场 `data1` | 阈值尚无非空场组证据 | 按统筹批复在 E0 逐组诊断 |

---

## 7. 复跑与验收

```powershell
# 合成例（预期先写死，含相位翻转/时偏/增益/无效通道/单包/P=0）
python solutions/A/test_a_fold_gate.py --no-real

# 合成例 + 空场 data1 单组真实诊断
python solutions/A/test_a_fold_gate.py

# 单组诊断（JSON + 可选 npz）
python solutions/A/a_fold_gate.py --diagnose "附件2-测距数据/空场数据/data1" --json out/d1_data1.json
python solutions/A/a_fold_gate.py --diagnose "附件2-测距数据/空场数据/data1" --npz out/d1_data1.npz
```

验收口径：

1. 合成例覆盖恒等折叠、段间不同相、整包时延、极性翻转、增益跳变、无效参考通道、单包与 `P=0`；预期值先写死（或由解析式给出），再与实现比对。
2. 空场 `data1`：4 个共同包全部通过门控；`gamma_ref ≥ 0.999`；`rho ≥ 0.9999`；`|delta| ≤ 5 ps`；`|phi| ≤ 0.05 rad`；`signals_folded` 形状 `(64,4000)`、`float64`、全有限，且与直接按 `accepted` 包做双重平均的结果逐点相等。
3. 拒绝日志必须包含每个未通过包的统计量与原因码；全拒时抛异常，不输出伪造信号。
4. **D1-2/F1**：少数（1/4、2/5）极性翻转不得改变锚包所属的多数簇；1 对 3 时 24 种包顺序的接受集（3 个）与折叠输出完全一致；1 对 1 无多数时只保留一侧且不抵消、不造数（按已声明的已知限定接受）。
5. **D1-2/F2**：任一通道 NaN/Inf 的包必须整包拒绝并记录 `nonfinite_channels`；参考通道非有限保留 `reference_channel_nonfinite`；全包非有限抛 `FoldGateError`；任何成功返回的 `signals_folded` 必须全有限。
6. D1-2 复跑空场 `data1` 的 `segment_coherence`、`rho/delta/phi/gain` 必须与 D1-1 数值一致（仅版本串与新增字段变化）。

当前测试总数：`91 passed / 0 failed / 0 skipped`（`python solutions/A/test_a_fold_gate.py`，含真实 `data1`）。

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| D1-1 | 2026-11-28 | 首版：4×4000 折迭；包内 `gamma`、包间 `rho/delta/phi/gain` 门控；等权相干平均；逐包拒绝日志；阈值依据与空场 `data1` 单组诊断 |
| D1-2 | 2026-11-28 | 修 F1：锚包改为“以候选为锚时通过四项门控的同伴数”最大者，`rho` 中位数只作并列 tie-break；极性/载波翻转不再因 `rho` 并列成为锚包，少数翻转不再改变接受集。修 F2：任一通道 NaN/Inf 整包拒绝（`packet_nonfinite_samples` + `packet_finite`/`nonfinite_channels`）；`_rho`/`_gain_db` 对非有限输入返回 0/None；折叠输出增加全有限不变量。公式、阈值与 `data1` 数值不变 |

## D1-1 验收范围与后续修正（统筹补记）

本版本仅在合成例及空场data1验收。F1：绝对相关rho无法区分极性翻转，锚包评分并列可能受包顺序影响；F2：外部浮点输入的非参考通道NaN可能污染输出（D0 int16原始路径不可达）。两项安排D1-2修正，在E0实测前复验。F3：包间门控只以参考通道为判据，不能保证全部接收通道的相位漂移或相干损失上限；每通道诊断与参考通道门控须分开解释。字节级JSON差异可来自numpy FFT版本，应比较数值容差与判定。

**D1-2 处理结果**：F1、F2 已按本文件 §3.1/§3.2/§4.4 修正并有回归测试；F3 不属代码缺陷，按 §3.2 范围说明保留为解释限制。D1-2 仅用合成例与空场 `data1` 复核，不构成 E0 实测或全通道一致性结论；E0 实测前仍须独立复验。