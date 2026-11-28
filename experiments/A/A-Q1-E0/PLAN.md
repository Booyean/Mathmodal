# A 题第一问先导试验登记方案（`A-Q1-E0`）

- **实验编号**：`A-Q1-E0`（Classic Baseline Pilot）
- **所属分支（本登记阶段）**：`coord/a-q1-e0-plan`
- **计划执行分支（待批复后创建）**：`data/a-q1-pilot`
- **撰写人**：`antigravity02`（依据 `codex` 统筹派工与 PR #10 审阅 `6090984574` / `6091456988` 修订）
- **状态**：**待统筹 `codex` 审阅并批复 `A-Q1-E0`；当前未实现求解器、未运行真实试验、未触碰任何新增留出样本**

---

## 1. 目标、唯一变化与执行前提

### 1.1 实验目标与可证伪问题
在 `A-Q1-M0` 已批复数学规范下，**仅采用经典基线链路（`M0-Cal-Base` → `M0-DW-Base` → `M0-Rng-Base`）**，按“合成闭环 → 校准实测先导 → 冻结配置 → 单次留出盲评”的严格顺序，验证：
1. 63 路实测阵列的空场校准能否在工作频带内有效压低通道幅相差异；
2. 射频镜像对齐减除（固定 $\alpha_g \equiv 1.0$）能否在压缩延迟直射波窗内有效抑制直达波，同时在近距离墙体（`42 cm`）与金属板（`69 cm`）上保留可辨识目标回波；
3. 归一化匹配统计量（主统计量 `P_norm,eff`，对照 `P_norm` 与 `P_env`）在有限先导样本上的测距精度与峰旁瓣比表现。

### 1.2 边界与唯一变化声明
- **严格不引入 `N0` 改进**：本试验**不包含** `M0-Cal-Joint`、`M0-DW-Subspace`、自适应 $\hat{\alpha}_g$ 拟合、`M0-Rng-WLS`、非等权信道加权或大范围超参搜索。
- **执行前置状态与门控**：
  1. `D0` 读取器（PR #7 / PR #11）与 `D1-1` 单组折叠/一致性基线（PR #12 `dfdae8ed27065acaf51dcfa67d650ea600bceb67`，含 `SPLIT0` 15/15 核查）已合入主线 `main = f56dbc0b472008f3a212bcefa47aa0392343d357`；
  2. `D1-2` 小修（`F1` 锚包极性/包顺序依赖及 `F2` 非有限值输入/输出防护）须先完成并**独立复验通过**后，方可启动真实信号执行；
  3. 统筹 `codex` 正式记录 `A-Q1-E0` 批复后方可新建 `data/a-q1-pilot` 实施。

---

## 2. 版本锚点与冻结拆分引用

| 锚点项 | 锁定值 |
|---|---|
| 原始数据基线 | `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9` |
| A 题 `.dat` 清单总体 SHA256 | `86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06` |
| `recon/manifests/a_dat_manifest.csv` blob SHA256 | `d5013e9330ded4464d2d6214b382b9436fc53d1436b0442048a61b25cbade8d4` |
| 主线规划基线 | `main` = `f56dbc0b472008f3a212bcefa47aa0392343d357`（含 PR #12 `dfdae8e` 与 PR #13） |
| 已批复数学方案 (`A-Q1-M0`) | `098e17de9f42c843ab48923547d07b80883cf47c`（PR #3） |
| 冻结拆分文件 (`A-Q1-SPLIT0`) | `coordination/A_Q1_SPLIT.json`（Git LF blob SHA256：`d623da4ea186f372f2be094121c202c55dae0e236f4683005ab88d220a248b3a`） |
| 失败回退目标 | `f56dbc0b472008f3a212bcefa47aa0392343d357`（或执行前最近通过验收的 `D1-2` 合并提交） |

**拆分与通道铁律**：
- 任何 `wall_test` 与 `metal_test` 标签**严禁**参与通道校准、正则化选参或墙体首峰门限设定。
- **有效通道强制要求全 63 路有效**（`required_valid_rx_channels == 63`，`allow_dropped_rx_channels = false`）：`D0`/`SPLIT0` 全量核查已确认测距全部 50 组均为完整 8 文件组，若任何先导组有效接收通道 `< 63`（或 `ref_idx=28` 无效），**立即硬停止**并排查读取/折迭门控，不得静默丢通道或用部分阵元继续。

---

## 3. 固定经典基线、无量纲正则与确定性选参规则（对应 `config.json`）

物理常量遵循 `solutions/A/model_q1.md`（`098e17d`）：$c_0 = 299792458\text{ m/s}$，$f_s = 4\text{ GHz}$，$N_p = 4000$，$T_p = 1000\text{ ns}$，$\mathcal{B} = [0.3, 1.7]\text{ GHz}$，$\mathcal{B}_{\text{core}} = [0.4, 1.6]\text{ GHz}$，$\text{tx\_idx}=27$，$\text{ref\_idx}=28$（全 63 路）。

### 3.1 1.1 通道校准（`M0-Cal-Base`）与空场 LOO 确定性选参
- **正则化量纲与定义**（均为**无量纲功率比**）：
  - $\lambda_{\text{cal}}$：相对参考通道带内平均功率 $\bar{P}_{\text{ref}} = \operatorname{mean}_{f_D\in\mathcal{B}}|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2$ 的无量纲比值，$\hat{H}_i^{\text{rel}}(f_D) = \frac{\bar{X}_i \bar{X}_{\text{ref}}^*}{|\bar{X}_{\text{ref}}|^2 + \lambda_{\text{cal}}\bar{P}_{\text{ref}}}\frac{R_i^{\text{dir}}}{R_{\text{ref}}^{\text{dir}}}e^{-j2\pi f_R(\tau_i^{\text{dir}}-\tau_{\text{ref}}^{\text{dir}})}$。
  - $\lambda_{\text{inv}}$：相对参考通道单位增益平方 $|H_{i_{\text{ref}}}^{\text{rel}}|^2 \equiv 1$ 的无量纲逆滤波正则项，$X_i^{\text{cal}}(f_D) = \frac{(\hat{H}_i^{\text{rel}})^*}{|\hat{H}_i^{\text{rel}}|^2 + \lambda_{\text{inv}}} X_i(f_D)$。
- **纯空场留一（Air-Only LOO）确定性选参规则**（零目标数据参与，固定预算 $3\times 3 = 9$ 组）：
  - 候选网格：$(\lambda_{\text{cal}}, \lambda_{\text{inv}}) \in \{10^{-4}, 10^{-3}, 10^{-2}\}^2$；默认基线为 $(10^{-3}, 10^{-3})$。
  - 10 折空场留一：每折留出 1 组空场 $g \in \mathcal{G}_{\text{air}}$，仅用其余 9 组对齐聚合校准并在 $g$ 上计算空场抑制比 $\text{Supp}_{\text{air-LOO}}^{(g)}$（定义见第 5 节）。
  - **标量目标函数**：$J_{\text{air}}(\lambda_{\text{cal}}, \lambda_{\text{inv}}) = \operatorname{median}_{g}(\text{Supp}_{\text{air-LOO}}^{(g)}) + 0.5\min_{g}(\text{Supp}_{\text{air-LOO}}^{(g)})$（单位：dB）。
  - **切换触发条件**：仅当 $\max J_{\text{air}} - J_{\text{air}}(10^{-3}, 10^{-3}) \ge 0.5\text{ dB}$，或默认对 $(10^{-3}, 10^{-3})$ 不满足 $\min_g \text{Supp}_{\text{air-LOO}}^{(g)} \ge 10.0\text{ dB}$ 而存在候选对满足时，才切换至最优网格点；否则保留默认 $(10^{-3}, 10^{-3})$。
  - **并列裁决（Tie-break）**：目标差 $< 10^{-6}\text{ dB}$ 时依次选 $\lambda_{\text{cal}}+\lambda_{\text{inv}}$ 更小者 → 距 $(10^{-3},10^{-3})$ 索引更近者 → 字典序更小者。选定后冻结。

### 3.2 1.2 直射波抑制（`M0-DW-Base`，仅固定 $\alpha_g \equiv 1.0$）
- 对齐减除：在工作带 $\mathcal{B}$ 内按射频移位 $e^{+j 2\pi f_R \Delta t_0}$ 对齐校准后空场模板（包络粗峰 $\pm 1\,T_s$ 内以 $10^{-3}\,T_s$ 步长细搜），按 $\tilde{X}_i^{(g)}(f_D) = X_i^{(g,\text{cal})}(f_D) - \alpha_g \bar{X}_i^{\text{air,cal}}(f_D) e^{+j 2\pi f_R \Delta\hat{t}_0^{(g)}}$ 减除。
- **本先导试验仅保留固定 $\alpha_g \equiv 1.0$（移除 $\hat{\alpha}_g$ 拟合诊断）**：
  - 原因说明：发射信号为占满整周期 $T_p = 1\,\mu\text{s}$ 的周期 LFM 波形，原始带限波形在时域上各回波全程交叠，无法通过到达时间分离严格排除目标回波；即使在距离压缩延迟域 $z_i(\tau)$，有限带宽加窗主/旁瓣拖尾、循环卷绕以及未知公共色散残差也可能导致目标回波渗入直射波窗（`verify_e0_spec.py` 合成反例实测：即使经过压缩，在 `0.42 m` 工况 $\mathcal{W}_{\text{dw},i}$ 内仍存在约 `-44.4 dB` 目标尾瓣泄漏，而原始时域更达 `1.16e-3`）。为确保经典基线在 `E0` 中零目标泄漏、零自适应缩放偏差，本试验严格锁定 **`alpha_g = 1.0`（不做任何 $\hat{\alpha}_g$ 拟合）**；若后续需要环境漂移缩放或时窗子空间减除，统一归入 `A-Q1-N0`（`M0-DW-Subspace`）另行报批验证。

### 3.3 1.3 测距（`M0-Rng-Base`）与主统计量选定
- **主测距统计量统一锁定为 `P_norm,eff`**：因真实雷达硬件参考通道 $H_{i_{\text{ref}}}(f_D)$ 含未知一般色散（赛题图 3 所示带内幅度滚降与非线性相位），依据 `M0` §4.1/§5.3 结论，直接采用由对齐校准空场重构的显式模板 $\hat{S}_{\text{eff}}^{(g)}(f_D)$ 与归一化统计量 `P_norm,eff` 作为主统计量，并同步计算 `P_norm`（纯时延标量 `t0_eff`）与 `P_env` 作对照基准。
- 通道权重固定为等权 $w_i \equiv 1.0$；搜索区间固定 $d \in [0.15, 2.00]\text{ m}$（粗搜 $1\text{ mm}$，细搜 $0.1\text{ mm}$）。
- **峰值判别规则**：
  - 金属板：`metal_peak_rule = argmax` over $[0.15, 2.00]\text{ m}$。
  - 墙体：选取满足局部极大、高度 $\ge \eta_{\text{wall}} P_{\max}$ 且超过压缩延迟背景代理水平 $\text{BG}_{\text{proxy}}^{(g)}$ 至少 $+6\text{ dB}$（即 $P(d) \ge 10^{0.6}\,\text{BG}_{\text{proxy}}^{(g)}$，量纲定义见第 5.1 节）的**首个（最小 $d$）前向峰**；默认 $\eta_{\text{wall}} = 0.25$，仅在 `E0-C` 校准组 `data1-42cm` 上核对离散候选 $\{0.15, 0.25, 0.35\}$（选满足条件的最接近默认 $0.25$ 者）并在 `E0-Freeze` 锁定。

---

## 4. 严格三阶段执行顺序与完整可复现样本定义

### 阶段 1：合成例闭环（`Phase E0-S`，不读取真实 `.dat`）
1. **`E0-S1`（2 路解析闭环，复用 M0 §8）**：$d_{\text{true}} = 0.600000\text{ m}$、$\Delta\tau_2 = 0.50\text{ ns}$、$G_2 = 1.25$、$\psi_2 = 0.30\text{ rad}$、$\tau_{\text{ref}}^{\text{hw}} = 0.20\text{ ns}$、无噪声。
2. **`E0-S2`（63 路全阵列可复现带噪合成闭环）**：
   - **随机数生成器与绘制顺序**：固定 `rng = numpy.random.default_rng(20261128)`；按升序索引 $i \in \{0,\dots,63\}\setminus\{27, 28\}$（共 62 路非参考接收通道）逐一抽取：
     - $\Delta\tau_i \sim \text{Uniform}(-0.75\text{ ns}, +0.75\text{ ns})$（$\pm 3\,T_s$），
     - $G_i \sim \text{Uniform}(0.5, 1.5)$（带内平坦增益比），
     - $\psi_{i,0} \sim \text{Uniform}(-0.5, +0.5)\text{ rad}$，$\psi_{i,2} \sim \text{Uniform}(-0.3, +0.3)\text{ rad}$（剩余相位 $\psi_i(f_D) = \psi_{i,0} + \psi_{i,2} u(f_D)^2$，$u(f_D) = \frac{f_D - 1.0\text{ GHz}}{0.7\text{ GHz}}$）。
   - **植入公共参考色散 $H_{i_{\text{ref}}}(f_D)$**：$\tau_{\text{ref}}^{\text{hw}} = 0.20\text{ ns}$，幅度倾斜 $1 + 0.20\,u(f_D)$，二次相位 $+0.5\,u(f_D)^2\text{ rad}$，即 $H_{i_{\text{ref}}}(f_D) = (1 + 0.20\,u(f_D))\exp\big(j[+2\pi f_R (0.20\text{ ns}) + 0.5\,u(f_D)^2]\big)$。
   - **触发偏移与物理信号幅度**：空场第 0 组 $t_0^{\text{air},0} = 120.25\,T_s$，其余 9 组空场与 2 组目标分别从 $\text{Uniform}(0, T_p)$ 抽取；直达波 $E_i^{\text{dir}} = 1.0 / R_i^{\text{dir}}$；目标测试 $d_{\text{true}} = 0.42\text{ m}$（$\Gamma = +0.25$）与 $d_{\text{true}} = 0.69\text{ m}$（$\Gamma = -0.35$），回波幅度 $\Gamma / R_i^{\text{tgt}}(d_{\text{true}})$。
   - **噪声基准与加噪位置**：在**时域**（经过 $H_i$ 与传播延迟并重构为 4000 点实序列后）对每通道独立叠加实白高斯噪声 $n_i^{(g)}[m] \sim \mathcal{N}(0, \sigma_{\text{noise}}^2)$；$\text{SNR} = 25.0\text{ dB}$ 明确以**63 路纯目标回波的平均时域功率**为基准：
     $$\sigma_{\text{noise}}^2 = 10^{-25/10} \cdot \operatorname{mean}_{i\in\mathcal{I}_{\text{rx}}}\left(\frac{1}{N_p}\sum_{m=0}^{N_p-1} |x_{i,\text{tgt-only}}^{(g)}[m]|^2\right).$$

### 阶段 2：校准实测先导与配置冻结（`Phase E0-C` → `E0-Freeze`）
- **输入范围（严格锁定，无自动扩样）**：
  - 10 组空场 `空场数据/data1`–`data10`（纯空场 LOO 选参 + 聚合模板）；
  - 2 组已披露校准目标：`墙体数据/data1-42cm`（`wall_cal`）与 `金属板数据/data1-69cm`（`metal_cal`）。
  - 注：如需扩展至剩余 8+8 组校准集，必须于 `E0` 完成后另行提交申请并获统筹明确批复，本配置文件**禁止**自动扩样。
- **配置冻结闸门（`E0-Freeze`）**：仅当第 5 节全部适用性门控为“通过/可冻结”时，写入 `config.frozen.json`（锁定 $(\lambda_{\text{cal}}, \lambda_{\text{inv}}, \eta_{\text{wall}})$ 与实现 SHA）；一旦冻结，严禁再改。

### 阶段 3：单次留出样例盲评（`Phase E0-T`，冻结后仅运行一次）
- **输入范围（仅 1+1 组内插留出样，其余 16 组留出样不读取不查看）**：
  - `墙体数据/data20-73cm`（`wall_test`，真值 `73 cm`，位于 `42–106 cm` 内部）；
  - `金属板数据/data5-60cm`（`metal_test`，真值 `60 cm`，位于 `48–91 cm` 内部）。

---

## 5. 压缩延迟域定义、窗口规范、门控阈值与灰区动作

### 5.1 显式压缩延迟域 $z_i(\tau)$ 与可执行指标公式（全程不依赖目标真值）
**为什么必须在压缩域而非原始时域定义延迟窗**：发射波形为占满 $T_p = 1000\text{ ns}$ 整周期的周期性 LFM 脉冲，`verify_e0_spec.py` 合成反例验证：原始时域波形在 $[50, 950]\text{ ns}$ 的平均功率高达全周期均值的 `1.1075` 倍（完全非静音），只有经带内匹配滤波/脉冲压缩后，直达波与目标回波才会聚焦到纳米秒级主瓣。

1. **统一响应域 $z_i(\tau)$（循环距离压缩 / 匹配滤波延迟域）**：
   设 $f_D = k/(N_p T_s) \in \mathcal{B} = [0.3, 1.7]\text{ GHz}$（$k \in \{300,\dots,1700\}$），$f_R = f_s - f_D$；参考模板取 `M0-Rng-Base` 由对齐校准空场重构的显式色散有效模板 $\hat{S}_{\text{eff}}^{(g)}(f_D)$，模长为 $\|\hat{S}_{\text{eff}}^{(g)}\|_{\mathcal{B}} = \sqrt{\sum_{f_D\in\mathcal{B}}|\hat{S}_{\text{eff}}^{(g)}(f_D)|^2}$。对任意校准后信号频谱（抑制前 $X_i^{(g,\text{cal})}$ 或抑制后 $\tilde{X}_i^{(g)}$），定义单位模板能量归一化的**循环匹配滤波延迟响应**：
   $$z_i^{\text{before}}(\tau) = \frac{1}{\|\hat{S}_{\text{eff}}^{(g)}\|_{\mathcal{B}}} \sum_{f_D \in \mathcal{B}} X_i^{(g,\text{cal})}(f_D)\, \big(\hat{S}_{\text{eff}}^{(g)}(f_D)\big)^* \, e^{-j 2\pi f_R \tau},$$
   $$z_i^{\text{after}}(\tau) = \frac{1}{\|\hat{S}_{\text{eff}}^{(g)}\|_{\mathcal{B}}} \sum_{f_D \in \mathcal{B}} \tilde{X}_i^{(g)}(f_D)\, \big(\hat{S}_{\text{eff}}^{(g)}(f_D)\big)^* \, e^{-j 2\pi f_R \tau}.$$
   - **符号、零点与循环边界**：因物理到达时延 $+\tau_{\text{arr}}$ 在 `M0` 第二奈奎斯特区模型下携带相位 $\exp(+j2\pi f_R \tau_{\text{arr}})$，核函数取负滞后符号 $\exp(-j2\pi f_R \tau)$；$\hat{S}_{\text{eff}}^{(g)}$ 已同时吸收未知异步偏移 $t_0^{(g)}$ 与公共硬件响应 $H_{i_{\text{ref}}}(f_D)$，故**零延迟 $\tau = 0$ 对应相对有效发射原点的物理零传播时延**（直达波峰值落在 $\tau = +\tau_i^{\text{dir}}$，距离 $d$ 的平面目标回波峰值落在 $\tau = +\tau_i^{\text{tgt}}(d)$）。由于 DFT 频点步长 $\Delta f = 1/T_p$，$z_i(\tau + T_p) \equiv z_i(\tau)$ 严格以 $T_p = 1000\text{ ns}$ 为循环周期；所有窗口隶属与差值均按循环卷绕 $\operatorname{wrap}_{[-T_p/2, T_p/2)}(\tau - \tau_c) \in [-T_p/2, T_p/2)$ 计算。
   - **量纲一致性**：在该归一化下，单通道无信号仅含空间无关背景/噪声时 $\mathbb{E}[P_{\text{norm,eff}}(d)] = \mathbb{E}[|z_i(\tau)|^2]$，与背景代理功率 $\text{BG}_{\text{proxy}}^{(g)}$ 严格同量纲。

2. **压缩延迟域固定窗口（跨零循环处理 + 背景代理边界）**：
   - **直射波延迟窗（$\mathcal{W}_{\text{dw},i}$，循环卷绕）**：
     $$\mathcal{W}_{\text{dw},i} = \big\{\tau \in [0, T_p) : \big|\operatorname{wrap}_{[-T_p/2, T_p/2)}(\tau - \tau_i^{\text{dir}})\big| \le 1.0\text{ ns}\big\}.$$
     可执行离散网格取通道中心均匀采样 $\tau_{i,u} = (\tau_i^{\text{dir}} + \delta\tau_u) \bmod T_p$（$\delta\tau_u \in [-1.0, +1.0]\text{ ns}$ 共 41 点，步长 $0.05\text{ ns}$）。因近阵元（如 $i_{\text{ref}}=28$ 满足 $\tau_{28}^{\text{dir}} = 0.2335\text{ ns}$）的窗口 $[\tau_{28}^{\text{dir}}-1.0, \tau_{28}^{\text{dir}}+1.0]\text{ ns} = [-0.7665, 1.2335]\text{ ns}$ 会跨越 `0 / 1000 ns` 循环边界，采用上述模 $T_p$ 卷绕可完整保留左半主瓣而不发生截断。
   - **非目标区 / 晚延迟背景代理窗（$\mathcal{W}_{\text{bg}}$，非“纯噪声认证窗”）**：
     $$\mathcal{W}_{\text{bg}} = \big\{\tau_m = m T_s \in [50.0,\ 950.0]\text{ ns} \mid m \in \{200, 201, \dots, 3800\}\big\}$$
     （在压缩响应 $z_i(\tau)$ 上通过 $N_p$ 点 `ifft` 评估）。主搜区 $[0.15, 2.00]\text{ m}$ 最大到达时延仅 $\sim 13.47\text{ ns}$，该窗距搜区上界 $> 36.5\text{ ns}$（$>50$ 个压缩宽度 $1/B$）且距 $T_p = 1000\text{ ns}$ 循环边界 $50\text{ ns}$。**明确声明**：$\mathcal{W}_{\text{bg}}$ 仅作为**非目标区/晚延迟背景代理（off-target / late-delay background proxy）**，**不假定为已证明纯热噪声**——其能量可同时包含有限带宽压缩旁瓣尾、残余直射波/色散失配泄漏及实测中的晚到多径或墙后多次反射。
   - **1D 剖面主瓣保护带与旁瓣区**：在搜索区间 $[0.15, 2.00]\text{ m}$ 内对估计峰 $\hat{d}_g$ 定义保护半宽 $\Delta d_{\text{ml}} = 1.5 \times c_0/(2B) = 0.1606031\text{ m}$，旁瓣区 $\mathcal{D}_{\text{sl}}(\hat{d}_g) = [0.15, 2.00]\text{ m} \setminus [\hat{d}_g - \Delta d_{\text{ml}},\ \hat{d}_g + \Delta d_{\text{ml}}]$。

3. **可执行指标公式**：
   - **通道校准残差（`1.1`，空场 LOO 上计算）**：
     - 幅度残差 $\text{Res}_{\text{amp}} = \operatorname{rms}_{i\neq i_{\text{ref}}, f_D\in\mathcal{B}}\big(\big|\frac{X_i^{\text{cal}}(f_D)}{X_{i_{\text{ref}}}^{\text{cal}}(f_D)}\frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}}\big| - 1\big)$，降幅 $\text{dB} = 20\log_{10}(\text{Res}_{\text{amp}}^{\text{before}} / \text{Res}_{\text{amp}}^{\text{after}})$。
     - 相位残差 $\text{Res}_{\text{ph}} = \sqrt{\frac{\sum_{i\neq i_{\text{ref}}, f_D\in\mathcal{B}_{\text{core}}} |S(f_D)|^2 \cdot \operatorname{wrap}(\angle[\frac{X_i^{\text{cal}}(f_D)}{X_{i_{\text{ref}}}^{\text{cal}}(f_D)}e^{-j2\pi f_R(\tau_i^{\text{dir}}-\tau_{i_{\text{ref}}}^{\text{dir}})}])^2}{\sum_{i\neq i_{\text{ref}}, f_D\in\mathcal{B}_{\text{core}}} |S(f_D)|^2}}$（rad）。
   - **空场 LOO 与压缩直射波窗抑制比（`1.2`，功率比 $10\log_{10}$）**：
     - $\text{Supp}_{\text{air-LOO}}^{(g)} = 10\log_{10}\frac{\sum_i \sum_{f_D\in\mathcal{B}} |X_i^{(g,\text{cal})}(f_D)|^2}{\sum_i \sum_{f_D\in\mathcal{B}} |\tilde{X}_i^{(g)}(f_D)|^2}$，across 10 折汇报 `min` 与 `median`。
     - $\text{Supp}_{\text{dw-win}}^{(g)} = 10\log_{10}\frac{\sum_{i\in\mathcal{I}_{\text{rx}}} \sum_{u=0}^{40} |z_i^{\text{before}}(\tau_{i,u})|^2}{\sum_{i\in\mathcal{I}_{\text{rx}}} \sum_{u=0}^{40} |z_i^{\text{after}}(\tau_{i,u})|^2}$。
   - **目标回波保留与测距剖面质量（`1.2`/`1.3`，统一使用 `z_i` 与二次剖面 `P_norm,eff`，取 $10\log_{10}$）**：
     - 背景代理水平：$\text{BG}_{\text{proxy}}^{(g)} = \operatorname{mean}_{i\in\mathcal{I}_{\text{rx}},\, \tau_m \in \mathcal{W}_{\text{bg}}} |z_i^{\text{after}}(\tau_m)|^2$；
     - $\text{PNR}_g = 10\log_{10}\big(\operatorname{mean}_{i\in\mathcal{I}_{\text{rx}}} |z_i^{\text{after}}(\tau_i^{\text{tgt}}(\hat{d}_g)\bmod T_p)|^2 \big/ \text{BG}_{\text{proxy}}^{(g)}\big)$；
     - $\text{PSLR}_g = 10\log_{10}\big(P(\hat{d}_g) / \max_{d\in\mathcal{D}_{\text{sl}}(\hat{d}_g)} P(d)\big)$；
     - **固定 $\alpha=1.0$ 峰保留度**：$\text{EchoRet}_g = 10\log_{10}\big(P_{\text{norm,eff}}^{\text{after}}(\hat{d}_g) / P_{\text{norm,eff}}^{\text{before}}(\hat{d}_g)\big)$（仅记录于诊断日志）。

4. **合成反例核验（`experiments/A/A-Q1-E0/verify_e0_spec.py`，零真实 `.dat`）**：
   运行后在植入 `H_ref` 色散（`0.20 ns` + `0.20u` 幅度倾斜 + `0.5u^2` 二次相位）与 `0.42 m`（$\Gamma=+0.25$）/ `0.69 m`（$\Gamma=-0.35$）目标及 `25 dB` AWGN 下独立复核：(a) 原始时域 vs 压缩域 $\mathcal{W}_{\text{bg}}$ 功率对比；(b) `ref_idx=28` 跨零卷绕样本完整性；(c) 压缩域 $\mathcal{W}_{\text{dw},i}$ 目标微弱尾瓣泄漏量级（`-44.4 dB` at `0.42 m`）；(d) 显式 `S_eff` 与纯标量 `S` 在植入色散下的对比；(e) `Supp_dw-win`、`PNR`、`PSLR` 与测距门控一致性。

### 5.2 门控表、依据与灰区明确动作
| 检查阶段 | 通过（可冻结）门槛 | 灰区（不可冻结，禁入 `E0-T`） | 硬停止（立即退出） | 依据说明 |
|---|---|---|---|---|
| **有效通道/D1-2** | `valid_rx == 63` 且无 NaN/Inf | — | `valid_rx < 63` 或 NaN/Inf | 全量 `D0`/`SPLIT0` 已证实 50 组均为完整 63 路；实测前须完成 `D1-2` 验收 |
| **`E0-S1` 无噪** | `abs_err <= 0.05 cm`、`dtau <= 0.001 ns` | — | 超限即停 | $0.1\text{ mm}$ 细搜步长与闭环数值精度 |
| **`E0-S2` 25 dB** | `abs_err <= 1.0 cm`、`Supp_dw-win >= 20 dB` | — | 超限即停 | 63 路相干匹配滤波在每路 25 dB 回波信噪比下的工程容限 |
| **空场 LOO** | `min(Supp) >= 10.0 dB` | **`6.0 <= min < 10.0 dB`** → 仅允许在 9 组空场网格核查；仍 `<10 dB` 则停止，**禁入 `E0-T`** | **`min(Supp) < 6.0 dB`** | `6 dB` 意味着残余幅值 $\ge 50\%$；`10 dB` 为工程先导冻结门槛 |
| **近距回波质量** | `PSLR >= 3.0 dB` & `PNR >= 6.0 dB` | — | `PSLR < 3.0 dB` 或 `PNR < 6.0 dB` | 保证 `42 cm` 等近距回波在压缩域未被减除吞没并高于背景代理 |
| **`E0-C` 校准测距** | `abs_err <= 5.0 cm` | **`5.0 < err <= 10.71 cm`** → 标为 **不可冻结（`not_eligible_for_freeze`）**，做校准内诊断（`P_norm,eff` vs `P_norm`、墙体候选 $\eta_{\text{wall}}$），不通过则停、**禁入 `E0-T`** | **`err > 10.71 cm`** | $10.71\text{ cm} = c_0/(2B)$ 为 1 个瑞利主瓣宽度；$5.0\text{ cm} \approx 1.33$ 个采样步（$3.75\text{ cm}$） |
| **`E0-T` 单次留出** | 仅真实记录与报告全套指标 | — | 禁止二次调参重跑 | 检验标签只进入最终评价 |

---

## 6. 资源预算、硬停止与失败回溯
- **预算**：单进程 CPU（`OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS=1`），总墙钟 $\le 600\text{ s}$（10 分钟），峰值 RSS $\le 4096\text{ MiB}$（4 GiB）。
- **硬停止条件**：超预算、NaN/Inf/文件错误、`< 63` 有效通道、`D1-2` 未验收、`E0-S1/S2` 失败、`min(Supp_air-LOO) < 6.0 dB`、近距回波 `PSLR < 3.0 dB` 或 `PNR < 6.0 dB`、`E0-C` `abs_err > 10.71 cm`、或任何越界读取未授权检验样。
- **失败登记与回溯**：触发灰区拒绝冻结或硬停止时，立即中止并留存配置、命令、日志、耗时/峰值内存与退出原因，**严禁自动重跑或扩搜**；回到最近验收提交 `f56dbc0`（或执行前 `D1-2` 验收提交），交统筹诊断。

---

## 7. 待批复事项
请统筹 `codex` 审阅并批复：
1. 统一以 `M0-Rng-Base` 循环距离压缩延迟响应 $z_i(\tau)$（含显式色散参考模板 $\hat{S}_{\text{eff}}^{(g)}$、模长归一化、符号、零点映射、跨零卷绕 $\mathcal{W}_{\text{dw},i}$ 与非静音背景代理 $\mathcal{W}_{\text{bg}}$）定义 `Supp_dw-win` 与 `PNR_g`；
2. 在 `A-Q1-E0` 中严格保持固定 $\alpha_g \equiv 1.0$、移除自适应 $\hat{\alpha}_g$ 拟合诊断（统一后移至 `A-Q1-N0`），并以 `verify_e0_spec.py` 合成反例闭环佐证度量与窗口行为；
3. 更新 `main`/`D1-1` 锚点并保留 `D1-2`（F1/F2）独立复验作为真实信号执行前置门控，`E0-S1/S2`、`E0-C`、`E0-T` 与灰区规则维持锁定。
