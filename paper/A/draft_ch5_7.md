# A 题论文初稿（第五至第七章：模型建立与推导初稿）

- **所属分支**：`paper/a-ch5-7-draft`（基于 `main` = `df24c4447e5eeea4dd3f571648adda4ab92cb9e4`）
- **衔接基准**：衔接第四章预处理输出与 [PAPER_SCAFFOLD.md](PAPER_SCAFFOLD.md)、[NOTATION_TABLE.md](NOTATION_TABLE.md)、[RESULTS_AND_FIGURES_CHECKLIST.md](RESULTS_AND_FIGURES_CHECKLIST.md)，完整展开已合入主线之数学方案 [model_q1.md](../../solutions/A/model_q1.md)（`A-Q1-M0`）、[PLAN.md](../../experiments/A/A-Q1-E0/PLAN.md)（`A-Q1-E0`）、[model_q2.md](../../solutions/A/model_q2.md)（`M2`）与 [model_q3.md](../../solutions/A/model_q3.md)（`M3`）。
- **数值合规声明**：**本初稿仅包含理论模型推导、求解流程、规格设计阶段纯合成小算例预检边界及检验方案设计；所有实测结果、生产求解器统计、实测图表（`Fig 1-1`~`Fig 3-2`）及量化结果表（`Table 1-1`~`Table 3-2`）均严格标注为 `[待补]`，待对应分支完成独立验收并合入主线后再行回填。**

---

## 五、问题一：通道校准、直射波抑制与平面目标测距

### 5.1 统一频域观测模型与参数可识别性分析

#### 5.1.1 第二奈奎斯特区带限传播与补偿算子
依据赛题补充说明 2（对应假设 A2），设单个扫频周期 $0 \le t < T_p$（$T_p = 1\,\mu\text{s}$，$N_p = 4000$，$f_s = 4\text{ GHz}$）内的数字参考序列为 $s[m] = A\,w[m]\cos\phi_D(mT_s)$（$A=30000$，汉明窗 $w[m]$），其瞬间数字频率由 $f_{\text{start}} = 0.3\text{ GHz}$ 线性扫至 $f_{\text{stop}} = 1.7\text{ GHz}$（斜率 $K = B/T_p$，$B = 1.4\text{ GHz}$）。物理发射端工作于第二奈奎斯特区 $[2.0, 4.0]\text{ GHz}$，空间实际辐射连续实信号：
$$s_R(t) = A\,w_c(t)\cos\!\big(2\pi f_s t - \phi_D(t)\big), \qquad f_R(t) = f_s - f_D(t) \in [2.3, 3.7]\text{ GHz}.$$
将实信号按正负解析分量分解，$s_R(t) = \frac{1}{2}z_R(t) + \frac{1}{2}z_R^*(t)$，其中 $z_R(t) = A w_c(t)\exp\!\big(j[2\pi f_s t - \phi_D(t)]\big)$ 能量主集中在正射频带 $(f_s/2, f_s)$。当波形经历物理正传播时延 $\tau > 0$（即 $s_R(mT_s - \tau)$）并按采样率 $f_s$ 采样时，负射频谱分量 $-f_R = -(f_s - f_D)$ 经采样混叠平移 $+f_s$ 后恰好落入离散正数字频率网格 $f_D = k/(N_p T_s) \in \mathcal{B} = [0.3, 1.7]\text{ GHz}$（整数 bin $k \in \{300, \dots, 1700\}$，共 1401 个频点）。在带限近似下（工作带 $\mathcal{B}$ 内实测能量占比 `0.99991761`），理想物理延迟 $\tau$ 的频域响应算子为：
$$X_{\text{ideal}}(f_D) = S(f_D)\cdot \exp\!\big(+j 2\pi (f_s - f_D)\tau\big) = S(f_D)\,e^{+j2\pi f_s\tau}\,e^{-j2\pi f_D\tau}, \qquad f_D \in \mathcal{B}, \tag{5-1}$$
相应地，给定已知物理传播时延 $\tau$ 时的带内传播逆补偿算子为：
$$\mathcal{C}_{-\tau}[X](f_D) = X(f_D)\cdot \exp\!\big(-j 2\pi f_R \tau\big), \qquad f_R = f_s - f_D,\ f_D \in \mathcal{B}. \tag{5-2}$$
式 (5-1) 表明：群时延 $-\frac{1}{2\pi}\frac{\partial \arg}{\partial f_D} = +\tau > 0$ 表示回波向右滞后，线性斜率项 $-2\pi f_D\tau$ 与赛题第 6 页定义一致；而当 $\tau/T_s \notin \mathbb{Z}$ 时存在非单位载波相移 $e^{+j2\pi f_s\tau} \neq 1$，因此不能以单纯数字序列平移 $e^{-j2\pi f_D\tau}$ 替代物理传播时延。

#### 5.1.2 全阵列频域观测方程与不可识别自由度消解
对于第 $g$ 组经 `D1-2` 门控折迭后的信号（对应假设 A4，基线忽略跨板异步抖动 $\delta t_{g,r}=0$，将其作为可检验假设项），第 $i \in \mathcal{I}_{\text{rx}}$ 路有效接收通道在带内 $f_D \in \mathcal{B}$ 的观测频谱可写为：
$$X_i^{(g)}(f_D) = H_i(f_D)\, S(f_D)\, e^{+j 2\pi f_R t_0^{(g)}} \left[ E_i^{\text{dir}}(f_D)\, e^{+j 2\pi f_R \tau_i^{\text{dir}}} + E_i^{\text{bg}}(f_D) + \mathbb{1}_{\text{tgt}}(g)\,\Gamma_g(f_D)\, \frac{e^{+j 2\pi f_R \tau_i^{\text{tgt}}(d_g)}}{R_i^{\text{tgt}}(d_g)} \right] + N_i^{(g)}(f_D), \tag{5-3}$$
其中 $R_i^{\text{dir}} = \|\mathbf{p}_i^{\text{loc}} - \mathbf{p}_{\text{tx}}^{\text{loc}}\|_2$，$\tau_i^{\text{dir}} = R_i^{\text{dir}}/c_0$（参考通道 $i_{\text{ref}}=28$ 满足 $R_{28}^{\text{dir}} = 0.070000\text{ m},\ \tau_{28}^{\text{dir}} \approx 0.233495\text{ ns}$），$t_0^{(g)} \in [0, T_p)$ 为该组未知连续异步采集起点偏移，$E_i^{\text{dir}}$ 与 $E_i^{\text{bg}}$ 分别为直达波耦合系数与恒定环境背景散射，$N_i^{(g)}$ 为观测噪声。

直接反演式 (5-3) 存在两类严格不可识别自由度，必须通过规范锚定与显式投影予以固定：
1. **自由度 A（公共参考频响 $H_{i_{\text{ref}}}$ 与绝对触发时刻 $t_0^{(g)}$ 的可交换性）**：对任意 $a \in \mathbb{R}$，施加规范变换 $H_i'(f_D) = H_i(f_D)e^{-j2\pi f_R a}$ 与 $(t_0^{(g)})' = t_0^{(g)} + a$（$\forall i, \forall g$），则观测乘积 $H_i(f_D)e^{+j2\pi f_R t_0^{(g)}}$ 及全部相对通道比 $H_i^{\text{rel}}(f_D) = H_i(f_D)/H_{i_{\text{ref}}}(f_D)$ 均保持严格不变。为此引入吸收公共硬件频响与组间偏移的**有效参考频谱**：
   $$S_{\text{eff}}^{(g)}(f_D) \triangleq H_{i_{\text{ref}}}(f_D)\, S(f_D)\, e^{+j 2\pi f_R t_0^{(g)}}. \tag{5-4}$$
   - **纯时延情形**：若参考链路近似纯时延 $H_{i_{\text{ref}}}(f_D) = H_0 e^{+j 2\pi f_R \tau_{\text{ref}}^{\text{hw}}}$（与式 (5-1) 正滞后记号统一），式 (5-4) 退化为 $H_0 S(f_D) e^{+j 2\pi f_R t_{0,\text{eff}}^{(g)}}$，其标量**有效时间零点** $t_{0,\text{eff}}^{(g)} \triangleq t_0^{(g)} + \tau_{\text{ref}}^{\text{hw}}$ 在上述规范变换下严格不变；
   - **一般公共色散情形**：当参考链路存在幅度倾斜或非线性相位色散（如赛题图 3 所示通道畸变）时，单一标量移位无法吸收 $H_{i_{\text{ref}}}(f_D)$，必须利用对齐校准空场直接重构显式模板 $\hat{S}_{\text{eff}}^{(g)}(f_D)$ 消去公共色散因子。
2. **自由度 B（相对频响 $H_i^{\text{rel}}$ 内线性时延与剩余相位的共线性）**：固定 $H_{i_{\text{ref}}}^{\text{rel}}(f_D) \equiv 1$ 后，对任意实数 $\delta$，变换 $(\Delta\tau_i + \delta,\ \psi_i(f_D) + 2\pi f_D\delta)$ 产生逐点相同的复比值 $G_i(f_D)e^{-j2\pi f_D\Delta\tau_i + j\psi_i(f_D)}$。为此在核心子带 $\mathcal{B}_{\text{core}} = [0.4, 1.6]\text{ GHz}$ 上定义非负权 $\omega(f_D) = |S(f_D)|^2$，对解卷绕相位 $\phi_i(f_D) = \operatorname{unwrap}(\angle H_i^{\text{rel}}(f_D))$ 执行加权最小二乘线性投影：
   $$(\hat{\theta}_{i,0}, \Delta\hat{\tau}_i) = \arg\min_{(\theta_0,\Delta\tau)} \sum_{f_D \in \mathcal{B}_{\text{core}}} \omega(f_D)\big(\phi_i(f_D) - (\theta_0 - 2\pi f_D \Delta\tau)\big)^2, \tag{5-5}$$
   从而施加零中心化一阶矩正交约束 $\sum_{f_D\in\mathcal{B}_{\text{core}}} \omega(f_D)(\tilde{\psi}_i(f_D) - \hat{\theta}_{i,0})(f_D - \bar{f}_D) = 0$，在约定下唯一分解出 $\Delta\hat{\tau}_i$、带内幅比 $\hat{G}_i(f_D) = |\hat{H}_i^{\text{rel}}(f_D)|$ 与剩余相位 $\hat{\psi}_i(f_D) = \operatorname{wrap}_{(-\pi,\pi]}(\phi_i(f_D) + 2\pi f_D\Delta\hat{\tau}_i)$。需强调该投影确保的是数学约定唯一性，逆校正在信号端始终直接使用完整复比值 $\hat{H}_i^{\text{rel}}(f_D)$，保证后续测距严格不随分解约定漂移。

---

### 5.2 问题 1.1：基于空场正则比值的通道校准模型（`M0-Cal-Base`）

#### 5.2.1 数学模型与无量纲正则化
依据 `A-Q1-M0` 经典基线与 `A-Q1-E0` 先导规范，仅利用经 `D1-2` 验收的 10 组空场数据 $\mathcal{G}_{\text{air}}$（禁止触碰检验集标签），分三步完成相对校准参数估计：
1. **空场跨组射频对齐聚合**：指定 `空场数据/data1` 为时间原点，对各空场组 $g \in \mathcal{G}_{\text{air}}$ 在工作带 $\mathcal{B}$ 内搜索相对异步偏移 $\Delta\hat{t}_0^{\text{air},(g)}$，使其经 $e^{+j2\pi f_R \Delta t_0}$ 移位后与基准组加权二范数残差最小（粗搜取参考通道解析互相关包络峰 $\hat{k}_0$，细搜在 $[\hat{k}_0 - 1, \hat{k}_0 + 1]\,T_s$ 内以 $10^{-3}\,T_s$ 步长搜索），对齐平均得低噪空场频谱 $\bar{X}_i^{\text{air}}(f_D)$。
2. **传播路径几何补偿与无量纲 Tikhonov 校准**：在假设 A5（$E_i^{\text{dir}} \approx 1/R_i^{\text{dir}}$）下，定义相对参考通道带内平均功率 $\bar{P}_{\text{ref}} = \operatorname{mean}_{f_D\in\mathcal{B}}|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2$，对全部 63 路计算正则化相对频响：
   $$\hat{H}_i^{\text{rel}}(f_D) = \frac{\bar{X}_i^{\text{air}}(f_D)\,\big(\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)\big)^*}{|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2 + \lambda_{\text{cal}}\,\bar{P}_{\text{ref}}} \cdot \frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}}\,\exp\!\Big(-j 2\pi f_R \big(\tau_i^{\text{dir}} - \tau_{i_{\text{ref}}}^{\text{dir}}\big)\Big), \qquad f_D \in \mathcal{B}, \tag{5-6}$$
   其中 $\lambda_{\text{cal}} > 0$ 为相对 $\bar{P}_{\text{ref}}$ 的**无量纲功率比**正则参数（防止参考通道个别带内低谷频点引起除法噪声放大），再代入式 (5-5) 提取 $(\Delta\hat{\tau}_i, \hat{G}_i, \hat{\psi}_i)$。
3. **带内逆校正算子**：对任意测量谱 $X_i(f_D)$，施加相对参考单位增益平方 $|H_{i_{\text{ref}}}^{\text{rel}}|^2 \equiv 1$ 定义的无量纲逆滤波正则算子 $\lambda_{\text{inv}} > 0$：
   $$X_i^{\text{cal}}(f_D) = \begin{cases} \dfrac{\big(\hat{H}_i^{\text{rel}}(f_D)\big)^*}{|\hat{H}_i^{\text{rel}}(f_D)|^2 + \lambda_{\text{inv}}}\, X_i(f_D), & f_D \in \mathcal{B}, \\ 0, & f_D \notin \mathcal{B}. \end{cases} \tag{5-7}$$

#### 5.2.2 纯空场留一（Air-Only LOO）确定性选参规则
为杜绝调参过程中引入任何目标距离标签，正则对 $(\lambda_{\text{cal}}, \lambda_{\text{inv}})$ 在固定 $3\times 3 = 9$ 候选网格 $\{10^{-4}, 10^{-3}, 10^{-2}\}^2$（默认基线为 $(10^{-3}, 10^{-3})$）上通过 10 折纯空场留一交叉验证冻结：每折留出 1 组空场 $g \in \mathcal{G}_{\text{air}}$，由其余 9 组估计 $\hat{H}_i^{\text{rel}}$ 并测试在 $g$ 上的带内功率抑制比 $\text{Supp}_{\text{air-LOO}}^{(g)}$（定义见 5.3.2 节）。定义标量选参目标：
$$J_{\text{air}}(\lambda_{\text{cal}}, \lambda_{\text{inv}}) = \operatorname{median}_{g\in\mathcal{G}_{\text{air}}}\!\big(\text{Supp}_{\text{air-LOO}}^{(g)}\big) + 0.5\min_{g\in\mathcal{G}_{\text{air}}}\!\big(\text{Supp}_{\text{air-LOO}}^{(g)}\big)\quad (\text{dB}). \tag{5-8}$$
仅当网格最优点相对默认对满足 $J_{\text{air}}(\text{best}) - J_{\text{air}}(10^{-3}, 10^{-3}) \ge 0.5\text{ dB}$，或默认对未达到 $\min_g \text{Supp}_{\text{air-LOO}}^{(g)} \ge 10.0\text{ dB}$ 门槛而候选点达到时方切换选参；若目标值差异 $< 10^{-6}\text{ dB}$，依次按 $(\lambda_{\text{cal}} + \lambda_{\text{inv}})$ 更小、距 $(10^{-3}, 10^{-3})$ 更近及字典序更小裁决后全局冻结。
- **校准效果评价指标（空场 LOO 上计算）**：
  - 幅度残差 $\text{Res}_{\text{amp}} = \operatorname{rms}_{i\neq i_{\text{ref}}, f_D\in\mathcal{B}}\!\big(\big|\frac{X_i^{\text{cal}}(f_D)}{X_{i_{\text{ref}}}^{\text{cal}}(f_D)}\frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}}\big| - 1\big)$，降幅 $\Delta\text{Res}_{\text{amp}} = 20\log_{10}(\text{Res}_{\text{amp}}^{\text{before}} / \text{Res}_{\text{amp}}^{\text{after}})$；
  - 带内核心子带能量加权相位残差 $\text{Res}_{\text{ph}} = \sqrt{\frac{\sum_{i\neq i_{\text{ref}}, f_D\in\mathcal{B}_{\text{core}}} |S(f_D)|^2 \cdot \operatorname{wrap}(\angle[\frac{X_i^{\text{cal}}(f_D)}{X_{i_{\text{ref}}}^{\text{cal}}(f_D)}e^{-j2\pi f_R(\tau_i^{\text{dir}}-\tau_{i_{\text{ref}}}^{\text{dir}})}])^2}{\sum_{i\neq i_{\text{ref}}, f_D\in\mathcal{B}_{\text{core}}} |S(f_D)|^2}}$（单位 $\text{rad}$）。
- **对照改进分支预留（`M0-Cal-Joint`，未入基线 E0）**：若校准实测发现端射互耦引起幅相差偏置，可在后续候选研究中引入校准池近法向已知目标回波联合校准作为消融对照，当前不计入经典基线结果。

> **图/表槽位**：代表性通道校准前后波形与频谱对比见 **`Fig 1-1 [待补：依赖 E0-C 验收]`**；63 路校准参数 $(\Delta\hat{\tau}_i, \hat{G}_i, \hat{\psi}_i)$ 与 LOO 残差统计见 **`Table 1-1 [待补：依赖 E0-C 验收]`**。

---

### 5.3 问题 1.2：射频镜像对齐直射波抑制与压缩延迟域度量（`M0-DW-Base`）

#### 5.3.1 对齐减除模型与固定比例约定
将式 (5-7) 施加于空场聚合模板与第 $g$ 组目标测量数据，得 $\bar{X}_i^{\text{air,cal}}(f_D)$ 与 $X_i^{(g,\text{cal})}(f_D)$。在全 63 路有效接收通道等权（$w_i^{\text{dw}} \equiv 1$）下求解目标组相对空场参考模板的连续异步偏移 $\Delta\hat{t}_0^{(g)}$：
$$\Delta\hat{t}_0^{(g)} = \arg\min_{\Delta t_0 \in [0, T_p)} \sum_{i \in \mathcal{I}_{\text{rx}}} w_i^{\text{dw}} \sum_{f_D \in \mathcal{B}} \Big| X_i^{(g,\text{cal})}(f_D) - \bar{X}_i^{\text{air,cal}}(f_D)\, e^{+j 2\pi f_R \Delta t_0} \Big|^2, \tag{5-9}$$
并在经典基线中严格锁定比例系数 $\alpha_g \equiv 1.0$ 执行带内相干减除：
$$\tilde{X}_i^{(g)}(f_D) = X_i^{(g,\text{cal})}(f_D) - \bar{X}_i^{\text{air,cal}}(f_D)\, e^{+j 2\pi f_R \Delta\hat{t}_0^{(g)}}, \qquad f_D \in \mathcal{B}. \tag{5-10}$$
**不采用原始时域拟合 $\hat{\alpha}_g$ 的物理依据**：因 1 $\mu\text{s}$ 周期 LFM 在原始时域上全周期交叠，实测合成反例核验表明，即使 `42 cm` 墙体目标在原始时域直达窗内的目标/直达能量交叠亦达 `1.16e-3`，即便经过脉冲压缩在 $\pm 1.0\text{ ns}$ 直射窗内仍保留约 `-44.4 dB` 的有限带宽尾瓣泄露。基线固定 $\alpha_g \equiv 1.0$ 可严格保证抑制过程零目标信号泄露；可能存在的小幅环境温漂缩放留归受控改进候选（`M0-DW-Subspace`）单独消融检验。

#### 5.3.2 显式压缩延迟域 $z_{\text{MF},i}(\tau)$ 与跨零/背景代理窗口
因为周期性 LFM 原始波形在 $[50, 950]\text{ ns}$ 仍承载全周期约 $110.8\%$ 的平均功率（完全非静音），直射窗抑制比与峰背比必须统一定义在基于显式模板 $\hat{S}_{\text{eff}}^{(g)}(f_D)$（式 (5-13)）的**循环距离压缩延迟域**：
$$z_{\text{MF},i}^{\text{before}}(\tau) = \frac{1}{\|\hat{S}_{\text{eff}}^{(g)}\|_{\mathcal{B}}} \sum_{f_D \in \mathcal{B}} X_i^{(g,\text{cal})}(f_D)\,\big(\hat{S}_{\text{eff}}^{(g)}(f_D)\big)^* e^{-j2\pi f_R \tau}, \qquad z_{\text{MF},i}^{\text{after}}(\tau) = \frac{1}{\|\hat{S}_{\text{eff}}^{(g)}\|_{\mathcal{B}}} \sum_{f_D \in \mathcal{B}} \tilde{X}_i^{(g)}(f_D)\,\big(\hat{S}_{\text{eff}}^{(g)}(f_D)\big)^* e^{-j2\pi f_R \tau}. \tag{5-11}$$
此处负滞后核 $e^{-j2\pi f_R\tau}$ 与式 (5-1) 相位正号匹配，$\tau = 0$ 对齐已由 $\hat{S}_{\text{eff}}^{(g)}$ 吸收的等效发射原点，使直达波与平面目标回波分别聚焦于 $+\tau_i^{\text{dir}}$ 和 $+\tau_i^{\text{tgt}}(d)$，且函数以 $T_p = 1000\text{ ns}$ 为严格周期。定义两个不依赖任何目标真值的固定延迟窗及对应可执行功率指标（统一按 $10\log_{10}$ 计）：
1. **跨零模 $T_p$ 卷绕直射波窗 $\mathcal{W}_{\text{dw},i}$**：针对近阵元（如 $i_{\text{ref}}=28$，其 $\tau_{28}^{\text{dir}} \approx 0.2335\text{ ns}$，左缘 $\tau_{28}^{\text{dir}}-1.0\text{ ns} < 0$），采用中心对称循环卷绕样本 $\tau_{i,u} = (\tau_i^{\text{dir}} + \delta\tau_u) \bmod T_p$（$\delta\tau_u \in [-1.0, +1.0]\text{ ns}$ 等距 41 点，步长 $0.05\text{ ns}$），防止跨零截断：
   $$\text{Supp}_{\text{dw-win}}^{(g)} = 10\log_{10}\frac{\sum_{i\in\mathcal{I}_{\text{rx}}}\sum_{u=0}^{40} |z_{\text{MF},i}^{\text{before}}(\tau_{i,u})|^2}{\sum_{i\in\mathcal{I}_{\text{rx}}}\sum_{u=0}^{40} |z_{\text{MF},i}^{\text{after}}(\tau_{i,u})|^2}, \qquad \text{Supp}_{\text{air-LOO}}^{(g)} = 10\log_{10}\frac{\sum_{i\in\mathcal{I}_{\text{rx}}}\sum_{f_D\in\mathcal{B}}|X_i^{(g,\text{cal})}(f_D)|^2}{\sum_{i\in\mathcal{I}_{\text{rx}}}\sum_{f_D\in\mathcal{B}}|\tilde{X}_i^{(g)}(f_D)|^2}.$$
2. **非目标区 / 晚延迟背景代理窗 $\mathcal{W}_{\text{bg}}$**：在压缩响应 DFT 网格 $\tau_m = m T_s$ 上取 $m \in \{200, \dots, 3800\}$（对应 $[50.0, 950.0]\text{ ns}$，远离最大搜索上限 $2.00\text{ m} \Leftrightarrow 13.47\text{ ns}$ 及 $1000\text{ ns}$ 边界）。**口径界定**：$\mathcal{W}_{\text{bg}}$ 仅作为**非目标区背景代理**（可能含有限带宽旁瓣、残余直达波泄露与晚到多径），不假定为已证明纯热噪声。定义背景代理水平及峰背比：
   $$\text{BG}_{\text{proxy}}^{(g)} = \operatorname{mean}_{i\in\mathcal{I}_{\text{rx}},\, \tau_m\in\mathcal{W}_{\text{bg}}} |z_{\text{MF},i}^{\text{after}}(\tau_m)|^2, \qquad \text{PNR}_g = 10\log_{10}\!\left(\frac{\operatorname{mean}_{i\in\mathcal{I}_{\text{rx}}} |z_{\text{MF},i}^{\text{after}}(\tau_i^{\text{tgt}}(\hat{d}_g)\bmod T_p)|^2}{\text{BG}_{\text{proxy}}^{(g)}}\right). \tag{5-12}$$

> **图/表槽位**：代表组抑制前后压缩延迟剖面对比见 **`Fig 1-2 [待补：依赖 E0-C 验收]`**；空场 LOO 与先导抑制指标及固定 $\alpha=1.0$ 峰保留度见 **`Table 1-2 [待补：依赖 E0-C 验收]`**。

---

### 5.4 问题 1.3：平面目标镜像测距与归一化 GLRT 模型（`M0-Rng-Base`）

#### 5.4.1 平面镜像几何、显式模板与归一化匹配统计量
设金属板或墙体前表面位于平面 $y = d > 0$。由镜像法，发射天线 $\mathbf{p}_{\text{tx}}^{\text{loc}} = (0, 0, z_4^{\text{loc}})$ 关于反射面的镜像位于 $(0, 2d, z_4^{\text{loc}})$，第 $i$ 路总传播路径与时延为：
$$R_i^{\text{tgt}}(d) = \sqrt{\big(R_i^{\text{dir}}\big)^2 + 4 d^2}, \qquad \tau_i^{\text{tgt}}(d) = \frac{R_i^{\text{tgt}}(d)}{c_0}.$$
为完整抵消未知参考硬件色散 $H_{i_{\text{ref}}}(f_D)$，利用对齐至当前组偏移后的校准空场直达波重构显式有效参考模板 $\hat{S}_{\text{eff}}^{(g)}(f_D)$：
$$\hat{S}_{\text{eff}}^{(g)}(f_D) = \frac{\sum_{i\in\mathcal{I}_{\text{rx}}} \frac{w_i^{\text{dw}}}{R_i^{\text{dir}}}\,\big(\bar{X}_i^{\text{air,cal}}(f_D)\,e^{+j2\pi f_R \Delta\hat{t}_0^{(g)}}\big)\,e^{-j2\pi f_R \tau_i^{\text{dir}}}}{\sum_{i\in\mathcal{I}_{\text{rx}}} w_i^{\text{dw}}\,(R_i^{\text{dir}})^{-2}}, \qquad f_D \in \mathcal{B}. \tag{5-13}$$
令导向矢量 $a_{i,f_D}^{\text{eff},(g)}(d) = \frac{1}{R_i^{\text{tgt}}(d)}\,\hat{S}_{\text{eff}}^{(g)}(f_D)\,e^{+j2\pi f_R \tau_i^{\text{tgt}}(d)}$，在第一轮基线等权矩阵 $W = \operatorname{diag}(w_i),\ w_i \equiv 1$ 下构造归一化 GLRT / Cauchy-Schwarz 相干匹配主统计量 **`P_norm,eff`**：
$$P_{\text{norm,eff}}^{(g)}(d) = \frac{\big|a^{\text{eff},(g)}(d)^H W \tilde{X}^{(g)}\big|^2}{a^{\text{eff},(g)}(d)^H W a^{\text{eff},(g)}(d)} = \frac{\left|\sum_{i\in\mathcal{I}_{\text{rx}}} \frac{w_i}{R_i^{\text{tgt}}(d)} \sum_{f_D\in\mathcal{B}} \tilde{X}_i^{(g)}(f_D)\,\big(\hat{S}_{\text{eff}}^{(g)}(f_D)\big)^*\,e^{-j2\pi f_R \tau_i^{\text{tgt}}(d)}\right|^2}{\left(\sum_{i\in\mathcal{I}_{\text{rx}}} \frac{w_i}{(R_i^{\text{tgt}}(d))^2}\right)\left(\sum_{f_D\in\mathcal{B}} |\hat{S}_{\text{eff}}^{(g)}(f_D)|^2\right)}. \tag{5-14}$$
同步保留纯时延标量基准 **`P_norm`**（用理想 $S(f_D)$ 与标量零点 $\hat{t}_{0,\text{eff}}^{(g)}$ 替代 $\hat{S}_{\text{eff}}^{(g)}$）与几何归一化非相干包络对照 **`P_env`**（对各通道先取 $|z_{\text{MF},i}^{\text{after}}(\tau_i^{\text{tgt}}(d))|$ 再几何归一化加权平方）用于检验色散抵消与相干增益的真实效果。在该归一化尺度下，当无目标仅含空间不相关背景噪声时，$\mathbb{E}[P_{\text{norm,eff}}(d)] = \text{BG}_{\text{proxy}}^{(g)}$，与式 (5-12) 严格同量纲。

**理论唯一性与偏置消解条件**：由 Cauchy-Schwarz 不等式，若理想无噪纯镜面模型成立（$\tilde{X}^{(g)} = \Gamma a^{\text{eff},(g)}(d_0),\ \Gamma \neq 0$）且在搜索区间 $[d_{\min}, d_{\max}] = [0.15, 2.00]\text{ m}$ 内导向矢量族 $\{a^{\text{eff},(g)}(d)\}$ 互不共线，则 $P_{\text{norm,eff}}^{(g)}(d)$ 在 $d_0$ 处严格唯一达到全局上界（反观旧版在分子误乘 $R_i^{\text{tgt}}(d)$ 而分母未归一的形式，真值处存在正一阶导数偏项 $\sum_i (R_i^{\text{tgt}})'(d_0)/R_i^{\text{tgt}}(d_0) > 0$，会导致无噪小算例峰值漂移）；上述精确恢复成立边界不能混淆为有噪或多次散射条件下的有限样本统计无偏性。

#### 5.4.2 峰值提取规则、PSLR 度量与 10/10 拆分隔离
在 $[0.15, 2.00]\text{ m}$ 内先以 $1\text{ mm}$ 步长粗搜、再于峰邻域以 $0.1\text{ mm}$ 细搜：
- **金属板**：全局极大值 $\hat{d}_g = \arg\max_{d\in[0.15, 2.00]\text{ m}} P_{\text{norm,eff}}^{(g)}(d)$。
- **墙体（前表面首峰判别）**：鉴于墙体后表面或内部可能存在强多次反射伪峰，选取满足局部极大、$P(d) \ge \eta_{\text{wall}} P_{\max}$ 且超过背景代理 $+6\text{ dB}$（$P(d) \ge 10^{0.6}\,\text{BG}_{\text{proxy}}^{(g)}$）的**首个（最小 $d$）前向峰**；$\eta_{\text{wall}}$ 默认 $0.25$，仅在 `E0-C` 校准样 `data1-42cm` 上核查候选 $\{0.15, 0.25, 0.35\}$ 后与正则对 $(\lambda_{\text{cal}}, \lambda_{\text{inv}})$ 同步写入冻结配置 `config.frozen.json`。
- **峰旁瓣比（PSLR）**：对估计峰 $\hat{d}_g$ 取主瓣保护半宽 $\Delta d_{\text{ml}} = 1.5\cdot c_0/(2B) = 0.1606031\text{ m}$，令旁瓣区 $\mathcal{D}_{\text{sl}}(\hat{d}_g) = [0.15, 2.00]\text{ m} \setminus [\hat{d}_g - \Delta d_{\text{ml}}, \hat{d}_g + \Delta d_{\text{ml}}]$，计算 $\text{PSLR}_g = 10\log_{10}(P(\hat{d}_g) / \max_{d\in\mathcal{D}_{\text{sl}}} P(d))$。
- **分层 10/10 拆分铁律（`A-Q1-SPLIT0`）**：墙体 20 组（校准 `42–106 cm` / 检验 `44–121 cm`）与金属板 20 组（校准 `48–91 cm` / 检验 `48–99 cm`）严格隔离，所有检验组标签严禁参与校准、选参或 $\eta_{\text{wall}}$ 确定；超过校准范围的墙体 $>106\text{ cm}$（含 `121 cm`）与金属 $>91\text{ cm}$（含 `99 cm`）作为外推测试集单独汇总指标，不与内插区间混算掩盖边界性能。

> **图/表槽位**：测距剖面与检验集误差对比见 **`Fig 1-3 [待补：依赖 E0-T 与全量 Q1 验收]`**；分区分组测距误差（MAE/RMSE/MaxAE/PSLR）汇总见 **`Table 1-3 [待补：依赖 E0-T 与全量 Q1 验收]`**。

---

### 5.5 算法求解流程与多维度检验设计

#### 5.5.1 可编码求解流程（伪代码概要）
1. **输入与硬门控**：接收经 `D1-2` 折叠的空场 10 组、校准组与待评组 `signals_folded (64, 4000)`；若任意组有效接收数 `< 63`（或 `ref_idx=28` 无效）或出现非有限值，立即硬停止。
2. **校准与参数冻结**：在 10 组空场按式 (5-6)~(5-8) 执行 9 组网格 LOO 选定并冻结 $(\lambda_{\text{cal}}, \lambda_{\text{inv}})$，在全部 10 组空场上定出 $\hat{H}_i^{\text{rel}}(f_D)$ 与 $(\Delta\hat{\tau}_i, \hat{G}_i, \hat{\psi}_i)$。
3. **抑直与显式模板重构**：对目标组执行逆滤波、式 (5-9) 精搜 $\Delta\hat{t}_0^{(g)}$、式 (5-10) 减除与式 (5-13) 重构 $\hat{S}_{\text{eff}}^{(g)}(f_D)$。
4. **测距与诊断输出**：计算 $P_{\text{norm,eff}}(d)$（及对照 $P_{\text{norm}}, P_{\text{env}}$）与压缩域统计量 $\text{Supp}_{\text{dw-win}}, \text{BG}_{\text{proxy}}, \text{PNR}, \text{PSLR}$；按目标类型提取 $\hat{d}_g$。

#### 5.5.2 规格闭环预检境界与待补实测检验矩阵
- **规格闭环与合成预检范围说明**：在已批复的 `A-Q1-M0`（`098e17d`）与 `A-Q1-E0`（`7f9ad92`）规格核查阶段，独立验证脚本已在**纯合成小算例**上完成数学自洽检验（2 路无噪解析闭环复核旧式未归一化偏移 `0.620000 m` vs 归一化精确值 `0.600000 m` 达 `18/18` 通过；`0.42 m`/`0.69 m` 植入色散度量/窗口核查得 `0.000 cm`）；上述记录**仅用于证实推导与指标边界无内部矛盾，不代表完整求解器及任何实测测距结果通过**。
- **待开展灵敏度与消融检验设计（`Fig 1-4 [待补]`）**：
  1. **参数摄动灵敏度**：在校准与冻结规则下分别摄动 $(\lambda_{\text{cal}}, \lambda_{\text{inv}})$（跨越 $\{10^{-4}, 10^{-3}, 10^{-2}\}$）、墙体首峰系数 $\eta_{\text{wall}} \in \{0.15, 0.25, 0.35\}$ 及光速折射率 $n_{\text{air}} = 1.0003$（对 $1\text{ m}$ 目标影响量级约 $0.03\text{ cm}$），量化测距 MAE 与 PSLR 漂移；
  2. **先导阶段灰区与硬停止门控**：空场 LOO 要求 $\min \text{Supp} \ge 10.0\text{ dB}$（$[6.0, 10.0)\text{ dB}$ 禁止冻结），先导校准组测距要求 $|\hat{d}-d_{\text{true}}| \le 5.0\text{ cm}$（$(5.0, 10.71]\text{ cm}$ 记为不可冻结、`> 10.71 cm` 或 `PSLR < 3.0 dB` / `PNR < 6.0 dB` 立即硬停止）。上述全套实测检验统计与图像均记为 **`[待补]`**。

---

## 六、问题二：远距离回波增益补偿与墙体二维剖面成像

### 6.1 扫描轨迹坐标、主选用行选择与物理模型继承
依据赛题第 7 页与图 5(b)，`附件3-成像数据/墙体` 包含 $J = 33$ 组步进扫描测量数据（按采集时间戳升序排列），每组发射天线在 $xOy$ 平面的投影坐标沿 $+x$ 均匀递增：
$$x_j = -0.20 + 0.05(j - 1)\text{ m}, \qquad j = 1, 2, \dots, 33 \quad (\text{覆盖 } [-20, 140]\text{ cm}).$$
第 $j$ 组全部天线的全局三维坐标为 $\mathbf{p}_{j,\text{tx}} = (x_j, 0, z_4^{\text{loc}})$ 与 $\mathbf{p}_{j,i} = (x_j + x_i^{\text{loc}}, 0, z_i^{\text{loc}})$。在二维成像域 $(x, y) \in \Omega_{\text{2D}} = [-0.20, 1.40]\text{ m} \times [0, 2.50]\text{ m}$ 内，取固定高程平面 $\mathbf{r} = (x, y, z_{\text{slice}})$，自由空间等效双程传播距离与走时为：
$$R_{j,i}(\mathbf{r}) = \|\mathbf{p}_{j,\text{tx}} - \mathbf{r}\|_2 + \|\mathbf{r} - \mathbf{p}_{j,i}\|_2, \qquad \tau_{j,i}(\mathbf{r}) = \frac{R_{j,i}(\mathbf{r})}{c_0}. \tag{6-1}$$
全域最大斜距走时 $< 25\text{ ns} \ll T_p = 1000\text{ ns}$，无跨周期距离模糊。
- **单行选定与跨行三维坐标修正**：主模型选定第 4 行（$r=4$，$\mathcal{I}_4 = \{24,25,26,28,29,30,31\}$ 共 7 路有效接收，包含 `ref_idx=28`），取 $z_{\text{slice}} = z_4^{\text{loc}} = 0.545\text{ m}$ 令收发与成像面严格共面（$\Delta z = 0$）。在模型一致性检验阶段同步选用第 3 行（$z_3^{\text{loc}}=0.615\text{ m}$）与第 5 行（$z_5^{\text{loc}}=0.475\text{ m}$，各有 8 路接收），此时须严格按式 (6-1) 代入非零 $\Delta z = z_r^{\text{loc}} - z_4^{\text{loc}}$ 三维欧氏距离。
- **信号输入继承**：每组经 Q1 冻结 $\hat{H}_i^{\text{rel}}$ 校准、$\alpha_j \equiv 1.0$ 抑直与 $\hat{S}_{\text{eff}}^{(j)}(f_D)$ 归一化后，按式 (5-11) 得到循环距离压缩响应 $z_{\text{MF},j,i}(\tau)$。

---

### 6.2 问题 2.1：有界双分量远距离回波增益模型（`M2-Gain-BSEC`）

#### 6.2.1 数学表达、两步封顶与精确量纲换算
为同时补偿球面/平面几何扩散损耗与穿透前墙 A（厚 $10.5\text{ cm}$）后的介质衰减并防止晚时背景噪声过度抬升，定义**两步截断有界增益补偿函数**：
$$\tau_{\text{clip}}(\tau) = \min\!\big(\max(\tau, \tau_0),\ \tau_{\text{sat}}\big), \qquad [u]_+ = \max(u, 0),$$
$$W_{\text{raw}}(\tau; \beta, \alpha_{\text{gain}}) = \left(\frac{\tau_{\text{clip}}(\tau)}{\tau_0}\right)^{\beta} \cdot \exp\!\Big(10^9\alpha_{\text{gain}}\,\big[\tau_{\text{clip}}(\tau) - \tau_0\big]_+\Big), \tag{6-2}$$
$$W_{\text{comp}}(\tau; \beta, \alpha_{\text{gain}}, G_{\text{cap}}) = \min\!\big(G_{\text{cap}},\ W_{\text{raw}}(\tau; \beta, \alpha_{\text{gain}})\big), \tag{6-3}$$
其中时延 $\tau$ 以秒计（$10^9\tau$ 单位 $\text{ns}$），亦可等效表示为等价单程成像深度 $y_{\text{eq}}(\tau) = c_0\tau/2$ 之函数：
- **起步保护界 $\tau_0 = 2y_0/c_0$**（$y_0 = 0.25\text{ m} \Leftrightarrow \tau_0 \approx 1.668\text{ ns}$）：保证近端 $\tau \le \tau_0$ 增益恒为 $1.0$，避免放大直射窗微弱残余泄漏。
- **法向参考饱和深度 $\tau_{\text{sat}} = 2y_{\text{sat}}/c_0$**（选定 $y_{\text{sat}} = 2.60\text{ m} \Leftrightarrow \tau_{\text{sat}} \approx 17.345\text{ ns}$）**与硬上限 $G_{\text{cap}}$**：注意到在二维成像边界大斜视角下的真实斜距走时 $\tau_{\text{oblique}}$（可达 $20\text{–}24\text{ ns}$）可能超过 $\tau_{\text{sat}}$，式 (6-2) 先用 $\tau_{\text{sat}}$ 限制平台增长值 $W_{\text{raw}}(\tau_{\text{sat}})$，式 (6-3) 再施加独立硬封顶 $G_{\text{cap}} = 20.0$（对应**幅度比**与**平方能量剖面 $I_{\text{2D}} \propto W_{\text{comp}}^2$ 功率比**同为 $20\log_{10}(20) = 10\log_{10}(20^2) \approx +26.02\text{ dB}$）。当 $W_{\text{raw}}(\tau_{\text{sat}}) > G_{\text{cap}}$ 时（如 $\beta=1.0, \alpha_{\text{gain}}=0.14\text{ ns}^{-1}$ 时 $W_{\text{raw}}(\tau_{\text{sat}})\approx 93.45 > 20.0$），硬封顶 $G_{\text{cap}}$ 提前截断以保护斜距角与晚时背景。
- **系数含义与空间换算**：几何扩散幂次 $\beta \in \{0.0, 1.0, 1.5\}$（$\beta = 1.0$ 严格对应镜像平面波 $1/R$ 扩散逆补偿）；时延衰减补偿率 $\alpha_{\text{gain}} \ge 0$（单位 $\text{ns}^{-1}$，网格 $\{0.0, 0.04, 0.08, 0.12, 0.14, 0.20\}$）按等价单程深度 $y_{\text{eq}} = c_0\tau/2$ 折算的空间指数系数与 dB 斜率分别为：
  $$\tilde{\alpha}_y = \frac{2\times 10^9}{c_0}\,\alpha_{\text{gain}}\ (\text{m}^{-1}), \qquad \text{增益斜率} = 20\log_{10}(e)\cdot \tilde{\alpha}_y \approx 57.946\,\alpha_{\text{gain}}\ (\text{dB/m}). \tag{6-4}$$

#### 6.2.2 无真值位置先验选参规则
在实测探索中固定 $\beta = 1.0$ 并在离散 $\alpha_{\text{gain}}$ 网格上扫描，统计**宽域近场区** $\mathcal{Y}_{\text{near}} = [0.25, 1.00]\text{ m}$ 与**宽域远场区** $\mathcal{Y}_{\text{far}} = [1.20, 2.40]\text{ m}$（不硬编码 `200 cm` 位置）的主峰功率比 $\Delta_{\text{far/near}}$ 及全图中位背景对比度 $C_{\text{far/med}} = 10\log_{10}(\max_{y\in\mathcal{Y}_{\text{far}}} I_{\text{2D}} / \operatorname{median}_{\Omega_{\text{2D}}} I_{\text{2D}})$：要求 $\Delta_{\text{far/near}}$ 进入可辨识平衡区间，且当继续增大 $\alpha_{\text{gain}}$ 引起 $C_{\text{far/med}}$ 较其极大值跌落 $> 1.5\text{ dB}$（表明远场噪底开始被过度放大）时立即截断选参。

---

### 6.3 问题 2.2：二维相干孔径反向投影与包络对照（`M2-Img-CohBPA` / `EnvBPA`）

在网格 $\Omega_{\text{2D}} = [-0.20, 1.40]\times[0, 2.50]\text{ m}$（推荐步长 $0.01\text{ m}$，局部细化 $0.005\text{ m}$）上，首先定义随方位角 $\theta_j(x,y) = \arctan2(|x - x_j|, \max(y, 0.05))$ 平滑截断的上升余弦孔径窗（$|\theta_j|\le 35^\circ$ 取 $1$，$35^\circ < |\theta_j|\le 45^\circ$ 取余弦过渡，$\theta_j > 45^\circ$ 置 $0$）及有效权重和 $N_{\text{ap}}(x,y) = \sum_{j=1}^{33}\sum_{i\in\mathcal{I}_r} w_{\text{ap}}(j;x,y)$。值得注意的是，中心射频 $f_c = 3.0\text{ GHz}$ 对应自由空间半波长 $\lambda_c / 2 = 5.0\text{ cm}$，恰好与测量平移步距 $\Delta x_{\text{scan}} = 5.0\text{ cm}$ 一致，结合 $1.4\text{ GHz}$ 宽带压噪与 $45^\circ$ 孔径截断可有效抑制横向栅瓣。

据此建立**增益补偿相干聚焦主模型（`M2-Img-CohBPA`）**与**非相干包络对照（`M2-Img-EnvBPA`）**：
$$U_{\text{coh}}(x,y) = \frac{1}{N_{\text{ap}}(x,y)}\sum_{j=1}^{33}\sum_{i\in\mathcal{I}_r} w_{\text{ap}}(j;x,y)\, W_{\text{comp}}\big(\tau_{j,i}(x,y)\big)\, z_{\text{MF},j,i}\big(\tau_{j,i}(x,y)\big), \qquad I_{\text{2D}}^{\text{coh}}(x,y) = \big|U_{\text{coh}}(x,y)\big|^2, \tag{6-5}$$
$$I_{\text{2D}}^{\text{env}}(x,y) = \left(\frac{1}{N_{\text{ap}}(x,y)}\sum_{j=1}^{33}\sum_{i\in\mathcal{I}_r} w_{\text{ap}}(j;x,y)\, W_{\text{comp}}\big(\tau_{j,i}(x,y)\big)\, \big|z_{\text{MF},j,i}\big(\tau_{j,i}(x,y)\big)\big|\right)^2. \tag{6-6}$$
令 $W_{\text{comp}} \equiv 1$ 得未增益对照剖面 $I_{\text{2D}}^{(0)}(x,y)$。

**第二奈奎斯特区插值红线**：由于连续延迟压缩响应可分解为 $z_{\text{MF}}(\tau) = e^{-j2\pi f_s \tau} z_{\text{base}}(\tau)$，其中心射频 $3.0\text{ GHz} > f_s/2$ 导致未解调复序列在 $T_s = 0.25\text{ ns}$ 原始网格上的相邻样点载波相位跳变达 $270^\circ$。因此**严禁直接在 $T_s$ 网格上线性插值复数 $z_{\text{MF}}$**；代码实现必须先对带内谱零填充作 $4\times$ 过采样 `ifft`（$T_s' = 0.0625\text{ ns}$）得到低频复基带包络 $z_{\text{base}}(\tau)$ 并作线性插值，再解析乘回精准射频因子 $e^{-j2\pi f_s \tau}$（或采用等价的频域复指数直接求和）。

**墙体走向拟合与增益前后定量比较指标**：
- 在每条纵切线 $x$ 分别追踪近/远峰值脊线并做加权直线回归得倾角 $\theta = \arctan(\mathrm{d}y/\mathrm{d}x)$；若前墙仅覆盖中间有限宽度而两侧直达后墙，必须分区统计**未穿过前墙空气段**与**穿过前墙视在遮挡段**的后墙位置并记录错位 $\Delta y_{\text{app}}$。
- 定量指标（均以功率 $10\log_{10}$ 计）：后/前墙均衡比 $\Delta_{\text{B/A}} = 10\log_{10}(\max_{\Omega_B} I_{\text{2D}} / \max_{\Omega_A} I_{\text{2D}})$、后墙对比度 $\text{PBR}_B = 10\log_{10}(\max_{\Omega_B} I_{\text{2D}} / \operatorname{median}_{\Omega_{\text{2D}}} I_{\text{2D}})$、后墙主旁瓣比 $\text{PSLR}_B$ 及后墙可辨识覆盖占比（超过全局中位 $+10\text{ dB}$ 与同列噪底 $+6\text{ dB}$ 之 $x$ 比例）。

---

### 6.4 物理边界说明与结果/检验槽位
1. **介质折射视在深度边界**：穿过介电常数 $\varepsilon_r > 1$、厚度 $d_A = 10.5\text{ cm}$ 前墙 A 的射线，其在自由空间波速 $c_0$ 下成出的后墙位置 $y_B^{\text{app}}(x)$ 将向 $+y$ 后移 $\Delta y_{\text{app}} \approx d_A(\sqrt{\varepsilon_r} - 1)$。基线不预先臆测 $\varepsilon_r$，而是通过无墙/有墙区间观测错位反推等效诊断量 $\hat{\varepsilon}_r \approx (1 + \Delta y_{\text{app}}/d_A)^2$，避免将视在延迟误判为后墙物理弯曲。
2. **跨高波束与表观壁厚展宽**：受单行天线垂向波束张角影响，非共面散射体以 $y_{\text{app}} = \sqrt{y^2 + (\Delta z)^2}$ 拖尾至更深视在距离，导致二维成像墙体表观条带展宽；因此前/后墙定位以主前界面脊线拟合为准，不将条带半高宽直接宣称为砖墙几何物理厚度。
3. **规格合成小算例边界与待补实测检验**：规格阶段纯合成双墙闭环（`solutions/A/verify_q2_spec.py`，零 `.dat` 读取）已验证单位换算、硬封顶行为与增益前后聚焦逻辑自洽性（仅限设计验证，非实测效果）。真实 `附件3-成像数据/墙体` 的增益前后剖面对比（**`Fig 2-1 [待补]`**）、第 4 行与第 3/5 行多行一致性及参数灵敏度分析（**`Fig 2-2 [待补]`**）、以及两面墙精确位置走向与定量提升表（**`Table 2-1 [待补]`**），均待后续独立实测验收后回填。

---

## 七、问题三：全阵列墙体与金属目标三维成像

### 7.1 全 63 路三维孔径配置与数据异常隔离
问题 3 融合 8 行 16 列交错阵列全部 $|\mathcal{I}_{\text{rx}}| = 63$ 路有效接收阵元（局部物理覆盖宽 $0.525\text{ m}$、高 $0.490\text{ m}$，即 $x_i^{\text{loc}} \in [-0.280, +0.245]\text{ m},\ z_i^{\text{loc}} \in [0.265, 0.755]\text{ m}$），其中：
- **问题 3.1 墙体场景**：复用 `附件3-成像数据/墙体` 全部 $J_{\text{wall}} = 33$ 组（$x_j = -0.20 + 0.05(j-1)\text{ m}$，共 $33 \times 63 = 2079$ 条有效迹），成像区域 $\Omega_{\text{3D}}^{\text{wall}} = [-0.20, 1.40]\times[0, 2.50]\times[0.20, 0.80]\text{ m}$。第 3 组包数差异（`3,4`）按 `D0` 共同 `sync` 交集处理。
- **问题 3.2 金属柱与金属铲场景**：采用 `附件3-成像数据/金属柱和金属铲` 经完整性清洗后的 **$J_{\text{metal}} = 27$** 组有效数据（$x_j = 0.05(j-1)\text{ m}$，共 $27 \times 63 = 1701$ 条迹），成像区域 $\Omega_{\text{3D}}^{\text{metal}} = [0.00, 1.30]\times[0, 2.50]\times[0.20, 0.80]\text{ m}$。严格跳过 0 字节孤儿文件 `22-50-31_16000_7.dat`，对第 8 组（`22-09-58_16000`）先取共同 `sync` 交集 $P_{\text{common}}=3$ 并交由 `D1-2` 门控核查其末包 `46` 个 `-32768` 采样异常点，拒绝则仅保留其余一致包。

对体素网格点 $\mathbf{r} = (x, y, z)$，精确三维双程自由空间时延保持 $\tau_{j,i}(\mathbf{r}) = (\|\mathbf{p}_{j,\text{tx}} - \mathbf{r}\|_2 + \|\mathbf{r} - \mathbf{p}_{j,i}\|_2)/c_0$。

---

### 7.2 解耦三维孔径加权与三维反向投影重建模型（`M3-Img-CohBPA3D`）

#### 7.2.1 水平/垂向解耦三维方向孔径窗
由于阵列在水平 $x$ 向具备 $1.3\text{–}1.6\text{ m}$ 机械移动合成孔径，而在垂直 $z$ 向保持静止（发射端恒定于 $z_4 = 0.545\text{ m}$，接收高度覆盖 $[0.265, 0.755]\text{ m}$），采用水平/垂向解耦的三维平滑上升余弦加权以防止近场低矮区被截断：
- 水平方位角 $\theta_x(j;\mathbf{r}) = \arctan2(|x - x_j|, \max(y, 0.05))$：取 $35^\circ\text{–}45^\circ$ 上升余弦窗 $w_x(j;\mathbf{r})$（与 Q2 保持同一栅瓣抑制半角）；
- 通道垂向仰角 $\theta_z(i;\mathbf{r}) = \arctan2(|z - z_i^{\text{loc}}|, \max(y, 0.05))$：放宽为 $45^\circ\text{–}55^\circ$ 上升余弦窗 $w_z(i;\mathbf{r})$，确保在近距低高度角（如 $y=0.40\text{ m}, z=0.20\text{ m}$）下层通道依然有效照明；
- 联合权与有效参与度：$w_{\text{ap},3\text{D}}(j,i;\mathbf{r}) = w_x(j;\mathbf{r})\,w_z(i;\mathbf{r})$，$N_{\text{ap},3\text{D}}(\mathbf{r}) = \sum_{j=1}^J \sum_{i\in\mathcal{I}_{\text{rx}}} w_{\text{ap},3\text{D}}(j,i;\mathbf{r})$。

#### 7.2.2 三维相干与包络聚焦方程及分场景增益模式
直接沿用式 (6-2)~(6-3) 两步封顶增益 $W_{\text{comp}}(\tau; \beta, \alpha_{\text{gain}}, G_{\text{cap}})$ 及第二奈奎斯特区 $4\times$ 基带过采样插值规则，构建全 63 路**三维相干反向投影（`M3-Img-CohBPA3D`）**与**非相干包络对照（`M3-Img-EnvBPA3D`）**：
$$U_{\text{3D}}(\mathbf{r}) = \frac{1}{N_{\text{ap},3\text{D}}(\mathbf{r})}\sum_{j=1}^{J}\sum_{i\in\mathcal{I}_{\text{rx}}} w_{\text{ap},3\text{D}}(j,i;\mathbf{r})\, W_{\text{comp}}\big(\tau_{j,i}(\mathbf{r})\big)\, z_{\text{MF},j,i}\big(\tau_{j,i}(\mathbf{r})\big), \tag{7-1}$$
$$I_{\text{3D}}^{\text{coh}}(\mathbf{r}) = \big|U_{\text{3D}}(\mathbf{r})\big|^2, \qquad I_{\text{3D}}^{\text{env}}(\mathbf{r}) = \left(\frac{1}{N_{\text{ap},3\text{D}}(\mathbf{r})}\sum_{j=1}^{J}\sum_{i\in\mathcal{I}_{\text{rx}}} w_{\text{ap},3\text{D}}(j,i;\mathbf{r})\, W_{\text{comp}}\big(\tau_{j,i}(\mathbf{r})\big)\, \big|z_{\text{MF},j,i}(\tau_{j,i}(\mathbf{r}))\big|\right)^2. \tag{7-2}$$
增益设置按场景物理分化：
- **问题 3.1 墙体场景**：继承问题二经剖面拐点确定的 $(\beta, \alpha_{\text{gain}}, G_{\text{cap}})$ 参数，用于三维重现前墙有限高度包络与穿前墙后的弱后墙分布；
- **问题 3.2 金属目标场景**：金属柱与金属铲在近/中距离形成强直散射，强反射体定位默认采用**纯几何扩散补偿基线** $(\beta = 1.0, \alpha_{\text{gain}} = 0.0\text{ ns}^{-1})$，避免指数增益把金属后方微弱多径伪影过度抬升为假实体；另单独保留开启高增益对比组以辅助检视被金属遮挡后方墙面的残余衰减情况。

在计算策略上，采用“全 3D 域 $2\text{ cm}$ 粗网格初探 + 局域目标 $1\text{ cm}$ 精化”并按 $z$ 切片批处理，确保单进程 CPU 内存占用可控在 `< 2 GiB` 以内。

---

### 7.3 墙体三维界面、双金属目标分离与遮挡阴影定量刻画
1. **问题 3.1 墙体三维表面提取**：逐 $z \in [0.20, 0.80]\text{ m}$ 层提取前墙 A 空间边界 $\hat{y}_A(x,z)$（含有限高度顶沿 $[z_{A,\min}, z_{A,\max}]$）与后墙 B 空间表面 $\hat{y}_B(x,z)$，并在 $z = z_4 = 0.545\text{ m}$ 切片上与问题二二维剖面做定量交叉对账（要求空气直射段深度一致性在 $\le 2\text{ cm}$ 量级）。
2. **问题 3.2 基于水平柱域 3D-NMS 的双金属目标分离**：针对强反射贯高立柱易因中心镜面主峰与上下端绕射边缘峰在 $z$ 向分裂为多个局部极大值的问题，在搜索区对 $I_{\text{3D}}^{\text{coh}}(\mathbf{r})$ 沿水平脚印 $(x,y)$ 柱域（抑制半宽 $\Delta_{xy} = (0.14, 0.18)\text{ m}$）执行非极大抑制，筛选超出全图背景中位数 $+12\text{ dB}$ 之独立强金属目标。对每个检出目标在局部脚印内提取：
   - 离散三维主峰坐标 $(\hat{x}_p, \hat{y}_p, \hat{z}_p)$；
   - **$-10\text{ dB}$ 等值三维包围盒**（体素能量 $\ge 0.10\,P_{\text{peak}}$）及其垂向跨度 $\Delta\hat{z}_{10\text{dB}} = \hat{z}_{\max} - \hat{z}_{\min}$；
   - **$-10\text{ dB}$ 能量加权三维质心** $(\hat{x}_c, \hat{y}_c, \hat{z}_c)$。
   依据主峰高度位置与 $-10\text{ dB}$ 垂向跨度即可在不依赖位置先验下区分贯高金属柱（镜面主峰邻近发射高度 $z_4$ 且含上下端绕射展宽）与低矮局部金属铲，并严格分别报告“主峰 vs 质心”与“XY（立柱）vs 3D（金属铲）”位置精度口径。
3. **金属后方墙面电磁遮挡指标（`ShadowRatio`）**：针对金属强散射导致其后方墙面信号难以辨认的现象（题面第 8 页注），对每个检出金属目标的横向/垂向投影区（后方区间 $y > \hat{y}_p + 0.25\text{ m}$ 至后墙带）计算阴影平均能量 $\bar{I}_{\text{shadow}}^{(m)}$ 与同 $y$ 区间无横向遮挡区墙面能量中位数 $\bar{I}_{\text{unocc}}$ 的功率比：
   $$\text{ShadowRatio}_m = 10\log_{10}\!\left(\frac{\bar{I}_{\text{shadow}}^{(m)}}{\bar{I}_{\text{unocc}}}\right)\quad (\text{dB}). \tag{7-3}$$
   若 $\text{ShadowRatio}_m \le -6.0\text{ dB}$，即定量确证金属前向屏蔽造成了局部能量阴影，从而区别于墙面本身的结构缺失。

---

### 7.4 三维物理分辨率边界与结果/检验槽位
1. **三轴物理分辨率的非对称极限**：距离向分辨率由信号带宽决定（$\Delta y_{\text{res}} = c_0/(2B) \approx 10.71\text{ cm}$），水平向由机械平移合成孔径实现高分辨（$\Delta x_{\text{res}} \approx 3.54\text{ cm}$），而垂直 $z$ 向仅依靠单程固定物理高度孔径 $L_z = 0.490\text{ m}$，导致理论垂向分辨率 $\Delta z_{\text{res}}(y) \approx \lambda_c y / L_z$ 随深度线性展宽（$y=0.8\text{ m}$ 约 $16\text{ cm}$，$y=2.0\text{ m}$ 约 $41\text{ cm}$）。故三维模型具备清晰的紧凑金属高程质心区分能力，但不可宣称在远距 $2\text{ m}$ 墙体处具备厘米级垂向锐度。
2. **高 RCS 目标多次散射虚像排查**：若金属目标之间或金属与地面间存在二次往返耦合，目标后方可能出现延迟虚像，应结合单/双程物理时延几何与阴影区位置剔除虚假目标。
3. **规格合成小算例与待补实测结果/检验**：规格验证阶段纯合成 27 站 $\times$ 63 路三维闭环（`solutions/A/verify_q3_spec.py`，零 `.dat` 读取）已核验立柱与金属铲异峰分离、XY/3D 主峰与 $-10\text{ dB}$ 质心一致定位及后墙遮挡检测逻辑自洽（仅限方法学自洽验证，不代表真实成像效果）。真实 `附件3-成像数据` 的三维墙体重构与截面（**`Fig 3-1 [待补]`**、**`Table 3-1 [待补]`**）、金属柱/金属铲三维位置及阴影衰减定量分析（**`Fig 3-2 [待补]`**、**`Table 3-2 [待补]`**），以及行列抽样消融与相干/包络跨组稳定性检验均标注 **`[待补]`**，待独立验收通过后统一填入。
