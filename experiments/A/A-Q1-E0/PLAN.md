# A 题第一问先导试验登记方案（`A-Q1-E0`）

- **实验编号**：`A-Q1-E0`（Classic Baseline Pilot）
- **所属分支（本登记阶段）**：`coord/a-q1-e0-plan`
- **计划执行分支（待批复后创建）**：`data/a-q1-pilot`
- **撰写人**：`antigravity02`（依据 `codex` 统筹派工与 PR #10 审阅 `6090984574` 修订）
- **状态**：**待统筹 `codex` 审阅并批复 `A-Q1-E0`；当前未实现求解器、未运行真实试验、未触碰任何新增留出样本**

---

## 1. 目标、唯一变化与执行前提

### 1.1 实验目标与可证伪问题
在 `A-Q1-M0` 已批复数学规范下，**仅采用经典基线链路（`M0-Cal-Base` → `M0-DW-Base` → `M0-Rng-Base`）**，按“合成闭环 → 校准实测先导 → 冻结配置 → 单次留出盲评”的严格顺序，验证：
1. 63 路实测阵列的空场校准能否在工作频带内有效压低通道幅相差异；
2. 射频镜像对齐减除能否在直射波窗内有效抑制直达波，同时在近距离墙体（`42 cm`）与金属板（`69 cm`）上保留可辨识目标回波；
3. 归一化匹配统计量（主统计量 `P_norm,eff`，对照 `P_norm` 与 `P_env`）在有限先导样本上的测距精度与峰旁瓣比表现。

### 1.2 边界与唯一变化声明
- **严格不引入 `N0` 改进**：本试验**不包含** `M0-Cal-Joint`、`M0-DW-Subspace`、`M0-Rng-WLS`、非等权信道加权或大范围超参搜索。
- **执行前置状态与门控**：
  1. `D0` 读取器（PR #7 / PR #11）已验收合入主线 `main = 4a21060`；
  2. `D1` 折迭与一致性门控小分支须先完成并验收（交付 `signals_folded (64, 4000)` 与逐包一致性日志）；
  3. 统筹 `codex` 正式记录 `A-Q1-E0` 批复后方可新建 `data/a-q1-pilot` 实施。

---

## 2. 版本锚点与冻结拆分引用

| 锚点项 | 锁定值 |
|---|---|
| 原始数据基线 | `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9` |
| A 题 `.dat` 清单总体 SHA256 | `86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06` |
| `recon/manifests/a_dat_manifest.csv` blob SHA256 | `d5013e9330ded4464d2d6214b382b9436fc53d1436b0442048a61b25cbade8d4` |
| 主线规划基线 | `main` = `4a210601041e842de361c8b08b398343d2fc934a` |
| 已批复数学方案 (`A-Q1-M0`) | `098e17de9f42c843ab48923547d07b80883cf47c`（PR #3） |
| 冻结拆分文件 (`A-Q1-SPLIT0`) | `coordination/A_Q1_SPLIT.json`（Git LF blob SHA256：`d623da4ea186f372f2be094121c202c55dae0e236f4683005ab88d220a248b3a`） |
| 失败回退目标 | `4a210601041e842de361c8b08b398343d2fc934a`（或执行前最近通过验收的 D1 合并提交） |

**拆分与通道铁律**：
- 任何 `wall_test` 与 `metal_test` 标签**严禁**参与通道校准、正则化选参、墙体首峰门限设定或直达波比例诊断。
- **有效通道强制要求全 63 路有效**（`required_valid_rx_channels == 63`，`allow_dropped_rx_channels = false`）：`D0` 全量体检已确认测距全部 50 组均为完整 8 文件组，若任何先导组有效接收通道 `< 63`（或 `ref_idx=28` 无效），**立即硬停止**并排查读取/折迭门控，不得静默丢通道或用部分阵元继续。

---

## 3. 固定经典基线、无量纲正则与确定性选参规则（对应 `config.json`）

物理常量遵循 `solutions/A/model_q1.md`（`098e17d`）：$c_0 = 299792458\text{ m/s}$，$f_s = 4\text{ GHz}$，$N_p = 4000$，$\mathcal{B} = [0.3, 1.7]\text{ GHz}$，$\mathcal{B}_{\text{core}} = [0.4, 1.6]\text{ GHz}$，$\text{tx\_idx}=27$，$\text{ref\_idx}=28$（全 63 路）。

### 3.1 1.1 通道校准（`M0-Cal-Base`）与空场 LOO 确定性选参
- **正则化量纲与定义**（均为**无量纲功率比**）：
  - $\lambda_{\text{cal}}$：相对参考通道带内平均功率 $\bar{P}_{\text{ref}} = \operatorname{mean}_{f\in\mathcal{B}}|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f)|^2$ 的无量纲比值，$\hat{H}_i^{\text{rel}}(f) = \frac{\bar{X}_i \bar{X}_{\text{ref}}^*}{|\bar{X}_{\text{ref}}|^2 + \lambda_{\text{cal}}\bar{P}_{\text{ref}}}\frac{R_i^{\text{dir}}}{R_{\text{ref}}^{\text{dir}}}e^{-j2\pi f_R(\tau_i^{\text{dir}}-\tau_{\text{ref}}^{\text{dir}})}$。
  - $\lambda_{\text{inv}}$：相对参考通道单位增益平方 $|H_{i_{\text{ref}}}^{\text{rel}}|^2 \equiv 1$ 的无量纲逆滤波正则项，$X_i^{\text{cal}}(f) = \frac{(\hat{H}_i^{\text{rel}})^*}{|\hat{H}_i^{\text{rel}}|^2 + \lambda_{\text{inv}}} X_i(f)$。
- **纯空场留一（Air-Only LOO）确定性选参规则**（零目标数据参与，固定预算 $3\times 3 = 9$ 组）：
  - 候选网格：$(\lambda_{\text{cal}}, \lambda_{\text{inv}}) \in \{10^{-4}, 10^{-3}, 10^{-2}\}^2$；默认基线为 $(10^{-3}, 10^{-3})$。
  - 10 折空场留一：每折留出 1 组空场 $g \in \mathcal{G}_{\text{air}}$，仅用其余 9 组对齐聚合校准并在 $g$ 上计算空场抑制比 $\text{Supp}_{\text{air-LOO}}^{(g)}$（定义见第 5 节）。
  - **标量目标函数**：$J_{\text{air}}(\lambda_{\text{cal}}, \lambda_{\text{inv}}) = \operatorname{median}_{g}(\text{Supp}_{\text{air-LOO}}^{(g)}) + 0.5\min_{g}(\text{Supp}_{\text{air-LOO}}^{(g)})$（单位：dB）。
  - **切换触发条件**：仅当 $\max J_{\text{air}} - J_{\text{air}}(10^{-3}, 10^{-3}) \ge 0.5\text{ dB}$，或默认对 $(10^{-3}, 10^{-3})$ 不满足 $\min_g \text{Supp}_{\text{air-LOO}}^{(g)} \ge 10.0\text{ dB}$ 而存在候选对满足时，才切换至最优网格点；否则保留默认 $(10^{-3}, 10^{-3})$。
  - **并列裁决（Tie-break）**：目标差 $< 10^{-6}\text{ dB}$ 时依次选 $\lambda_{\text{cal}}+\lambda_{\text{inv}}$ 更小者 → 距 $(10^{-3},10^{-3})$ 索引更近者 → 字典序更小者。选定后冻结。

### 3.2 1.2 直射波抑制（`M0-DW-Base`）与固定 $\alpha$ 诊断窗口
- 对齐减除：在工作带 $\mathcal{B}$ 内按射频移位 $e^{+j 2\pi f_R \Delta t_0}$ 对齐校准后空场模板（包络粗峰 $\pm 1\,T_s$ 内以 $10^{-3}\,T_s$ 步长细搜）。
- **主基线固定 $\alpha_g \equiv 1.0$**。
- **$\alpha_g$ 诊断拟合窗口（严格隔离目标回波）**：仅在已知几何决定的时域直射波窗 $\tau_{\text{eff}} \in \mathcal{W}_{\text{dw},i} = [\tau_i^{\text{dir}} - 1.0\text{ ns},\ \tau_i^{\text{dir}} + 1.0\text{ ns}]$ 内对校准后带限实波形拟合全局实标量（并限幅至 $[0.5, 2.0]$）：
  $$\hat{\alpha}_g = \operatorname{clip}_{[0.5, 2.0]}\!\left(\frac{\sum_{i\in\mathcal{I}_{\text{rx}}}\sum_{t\in\mathcal{W}_{\text{dw},i}} x_i^{(g,\text{cal})}(t)\,x_i^{\text{air,cal,aligned}}(t)}{\sum_{i\in\mathcal{I}_{\text{rx}}}\sum_{t\in\mathcal{W}_{\text{dw},i}} \big(x_i^{\text{air,cal,aligned}}(t)\big)^2}\right).$$
  因最近目标 `42 cm` 的回波最早到达时间为 $\tau_{\text{ref}}^{\text{tgt}} \approx 2.81\text{ ns}$（距 $\tau_{\text{ref}}^{\text{dir}} + 1.0\text{ ns} \approx 1.23\text{ ns}$ 尚有 $> 1.5\text{ ns}$ 间隔），该窗口保证目标回波不决定模板缩放系数。

### 3.3 1.3 测距（`M0-Rng-Base`）与主统计量选定
- **主测距统计量统一锁定为 `P_norm,eff`**：因真实雷达硬件参考通道 $H_{i_{\text{ref}}}(f_D)$ 含未知一般色散（赛题图 3 所示带内幅度滚降与非线性相位），依据 `M0` §4.1/§5.3 结论，直接采用由对齐校准空场重构的显式模板 $\hat{S}_{\text{eff}}^{(g)}(f_D)$ 与归一化统计量 `P_norm,eff` 作为主统计量，并同步计算 `P_norm`（纯时延标量 `t0_eff`）与 `P_env` 作对照基准。
- 通道权重固定为等权 $w_i \equiv 1.0$；搜索区间固定 $d \in [0.15, 2.00]\text{ m}$（粗搜 $1\text{ mm}$，细搜 $0.1\text{ mm}$）。
- **峰值判别规则**：
  - 金属板：`metal_peak_rule = argmax` over $[0.15, 2.00]\text{ m}$。
  - 墙体：选取满足局部极大、高度 $\ge \eta_{\text{wall}} P_{\max}$ 且超过噪声底 $+6\text{ dB}$ 的**首个（最小 $d$）前向峰**；默认 $\eta_{\text{wall}} = 0.25$，仅在 `E0-C` 校准组 `data1-42cm` 上核对离散候选 $\{0.15, 0.25, 0.35\}$（选满足条件的最接近默认 $0.25$ 者）并在 `E0-Freeze` 锁定。

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

## 5. 可执行指标定义、窗口、门控阈值与灰区动作

### 5.1 固定窗口与可执行指标公式（全程不依赖目标真值）
记 $\tau_{\text{eff}} = t - \hat{t}_{0,\text{eff}}^{(g)}$（若使用显式 $\hat{S}_{\text{eff}}^{(g)}$，则相对该模板时间为零偏移）：
- **直射波窗**：$\mathcal{W}_{\text{dw},i} = [\tau_i^{\text{dir}} - 1.0\text{ ns},\ \tau_i^{\text{dir}} + 1.0\text{ ns}]$（由几何 $R_i^{\text{dir}}$ 唯一固定）。
- **晚时静音噪声窗**：$\mathcal{W}_{\text{noise}} = [50.0\text{ ns},\ 950.0\text{ ns}]$（远超最大搜索上限 $2.00\text{ m} \Leftrightarrow 13.7\text{ ns}$，且避开 $T_p = 1000\text{ ns}$ 边界）。
- **1D 剖面主瓣保护带与旁瓣区**：在搜索区间 $[0.15, 2.00]\text{ m}$ 内对估计峰 $\hat{d}_g$ 定义保护半宽 $\Delta d_{\text{ml}} = 1.5 \times c_0/(2B) = 0.1606031\text{ m}$，旁瓣区 $\mathcal{D}_{\text{sl}}(\hat{d}_g) = [0.15, 2.00]\text{ m} \setminus [\hat{d}_g - \Delta d_{\text{ml}},\ \hat{d}_g + \Delta d_{\text{ml}}]$。

1. **通道校准残差（`1.1`，空场 LOO 上计算）**：
   - 幅度残差 $\text{Res}_{\text{amp}} = \operatorname{rms}_{i\neq i_{\text{ref}}, f\in\mathcal{B}}\big(\big|\frac{X_i^{\text{cal}}(f)}{X_{i_{\text{ref}}}^{\text{cal}}(f)}\frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}}\big| - 1\big)$，降幅 $\text{dB} = 20\log_{10}(\text{Res}_{\text{amp}}^{\text{before}} / \text{Res}_{\text{amp}}^{\text{after}})$。
   - 相位残差 $\text{Res}_{\text{ph}} = \sqrt{\frac{\sum_{i\neq i_{\text{ref}}, f\in\mathcal{B}_{\text{core}}} |S(f)|^2 \cdot \operatorname{wrap}(\angle[\frac{X_i^{\text{cal}}(f)}{X_{i_{\text{ref}}}^{\text{cal}}(f)}e^{-j2\pi f_R(\tau_i^{\text{dir}}-\tau_{i_{\text{ref}}}^{\text{dir}})}])^2}{\sum_{i\neq i_{\text{ref}}, f\in\mathcal{B}_{\text{core}}} |S(f)|^2}}$（rad）。
2. **空场 LOO 与直射波窗抑制比（`1.2`，功率比 $10\log_{10}$）**：
   - $\text{Supp}_{\text{air-LOO}}^{(g)} = 10\log_{10}\frac{\sum_i \sum_{f\in\mathcal{B}} |X_i^{(g,\text{cal})}(f)|^2}{\sum_i \sum_{f\in\mathcal{B}} |\tilde{X}_i^{(g)}(f)|^2}$，across 10 折汇报 `min` 与 `median`。
   - $\text{Supp}_{\text{dw-win}}^{(g)} = 10\log_{10}\frac{\sum_i \sum_{\tau\in\mathcal{W}_{\text{dw},i}} |z_i^{\text{before}}(\tau)|^2}{\sum_i \sum_{\tau\in\mathcal{W}_{\text{dw},i}} |z_i^{\text{after}}(\tau)|^2}$。
3. **目标回波保留与测距剖面质量（`1.2`/`1.3`，二次剖面 $10\log_{10}$）**：
   - $\text{PSLR}_g = 10\log_{10}\big(P(\hat{d}_g) / \max_{d\in\mathcal{D}_{\text{sl}}(\hat{d}_g)} P(d)\big)$；
   - $\text{PNR}_g = 10\log_{10}\big(\text{mean}_i |z_i^{\text{after}}(\tau_i^{\text{tgt}}(\hat{d}_g))|^2 / \text{mean}_{i,\tau\in\mathcal{W}_{\text{noise}}} |z_i^{\text{after}}(\tau)|^2\big)$；
   - **抑制前后峰保留度**（仅针对 $\hat{\alpha}_g$ 对照及校准样诊断）：汇报 `P(\hat{d}_g)` 与抑制前在 $\hat{d}_g$ 处匹配能量的比值（及 $\alpha_{\text{ls}}$ 相对 $\alpha=1.0$ 峰值比）。

### 5.2 门控表、依据与灰区明确动作
| 检查阶段 | 通过（可冻结）门槛 | 灰区（不可冻结，禁入 `E0-T`） | 硬停止（立即退出） | 依据说明 |
|---|---|---|---|---|
| **有效通道/D1** | `valid_rx == 63` 且无 NaN/Inf | — | `valid_rx < 63` 或 NaN/Inf | 全量 `D0` 已证实 50 组均为完整 63 路 |
| **`E0-S1` 无噪** | `abs_err <= 0.05 cm`、`dtau <= 0.001 ns` | — | 超限即停 | $0.1\text{ mm}$ 细搜步长与闭环数值精度 |
| **`E0-S2` 25 dB** | `abs_err <= 1.0 cm`、`DW_supp >= 20 dB` | — | 超限即停 | 63 路相干匹配滤波在每路 25 dB 回波信噪比下的工程容限（远高于单样点 $3.75\text{ cm}$ 步距） |
| **空场 LOO** | `min(Supp) >= 10.0 dB` | **`6.0 <= min < 10.0 dB`** → 仅允许在 9 组空场网格核查；仍 `<10 dB` 则停止，**禁入 `E0-T`** | **`min(Supp) < 6.0 dB`** | `6 dB` 意味着残余幅值 $\ge 50\%$；`10 dB` 为工程先导冻结门槛 |
| **近距回波 PSLR** | `PSLR >= 3.0 dB` & `PNR >= 6.0 dB` | — | `PSLR < 3.0 dB` 或 `PNR < 6.0 dB` | 保证 `42 cm` 等近距回波未被直射波减除吞没 |
| **`E0-C` 校准测距** | `abs_err <= 5.0 cm` | **`5.0 < err <= 10.71 cm`** → 标为 **不可冻结（`not_eligible_for_freeze`）**，做校准内诊断（`P_norm,eff` vs `P_norm`、墙体候选 $\eta_{\text{wall}}$），不通过则停、**禁入 `E0-T`** | **`err > 10.71 cm`** | $10.71\text{ cm} = c_0/(2B)$ 为 1 个瑞利主瓣宽度；$5.0\text{ cm} \approx 1.33$ 个采样步（$3.75\text{ cm}$） |
| **`E0-T` 单次留出** | 仅真实记录与报告全套指标 | — | 禁止二次调参重跑 | 检验标签只进入最终评价 |

---

## 6. 资源预算、硬停止与失败回溯
- **预算**：单进程 CPU（`OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS=1`），总墙钟 $\le 600\text{ s}$（10 分钟），峰值 RSS $\le 4096\text{ MiB}$（4 GiB）。
- **硬停止条件**：超预算、NaN/Inf/文件错误、`< 63` 有效通道、`E0-S1/S2` 失败、`min(Supp_air-LOO) < 6.0 dB`、近距回波 `PSLR < 3.0 dB` 或 `E0-C` `abs_err > 10.71 cm`、或任何越界读取未授权检验样。
- **失败登记与回溯**：触发灰区拒绝冻结或硬停止时，立即中止并留存配置、命令、日志、耗时/峰值内存与退出原因，**严禁自动重跑或扩搜**；回到最近验收提交 `4a21060`（或执行前 D1 验收提交），交统筹诊断。

---

## 7. 待批复事项
请统筹 `codex` 审阅并批复：
1. 本 `A-Q1-E0` 经典基线登记方案与 `config.json`（含固定 `P_norm,eff` 主统计量、无量纲正则网格与纯空场 LOO 确定性选参规则、$\mathcal{W}_{\text{dw}}/\mathcal{W}_{\text{noise}}/\mathcal{D}_{\text{sl}}$ 窗口及 $\hat{\alpha}_g$ 窗口隔离定义）；
2. `E0-S2` 全 63 路可复现合成参数规范与全 63 路有效通道硬门控；
3. 灰区不可冻结规则、`10 分钟 / 4 GiB` 预算与 `E0-C` / `E0-T` 样例清单。
