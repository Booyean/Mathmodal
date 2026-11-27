# A 题第一问数学方案（M0：通道校准、直射波抑制与平面目标测距）

- **任务编号**：M0（`model/a-q1-spec`）
- **主责**：`antigravity02`（建模与论文）
- **输入基线**：`main` = `e1f50ec1723ce74ac4ef9d550b50835b0f7e8dd9`（并同步核对最新 `main` = `44c778ead3c3ebd14ab701befbebac22c7480c02`），原始数据基线 = `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9`
- **参考依据**：赛题 PDF 第 1、3–7 页；`附件1-数据读取函数/get_data_iq.m`；`coordination/A_Q1_PLAN.md`；`coordination/A_Q1_METHODS.md`；`checks/A/q1_preflight.md`（V0 PR #4）
- **状态说明**：本文件为数学规范、接口契约与独立闭环验证说明；**须经统筹 `codex` 审阅并记录 `A-Q1-M0` 批复后，方可进入正式求解器与试验实现**。

---

## 1. 数据契约、周期边界与硬件同步假定

### 1.1 阵列通道索引与有效接收掩码
每组测量包含 8 个 `.dat` 文件，后缀 $n \in \{0,1,\dots,7\}$ 对应阵列第 $r = n + 1 \in \{1,\dots,8\}$ 行；每个文件内每包按 `get_data_iq.m` 解出尺寸为 $8 \times N_{\text{pkt}}$ 的矩阵（行内从左至右索引 $k \in \{1,\dots,8\}$，0-based 列索引 $c = k - 1 \in \{0,\dots,7\}$）。

- **全阵列展平通道索引**：$i = 8(r-1) + (k-1) = 8n + c \in \{0,1,\dots,63\}$（保持 64 路完整坐标映射）。
- **发射通道与接收掩码**：第 4 行第 8 列天线（$r=4, k=4$，即 `_3.dat` 第 4 列 / 0-based `n=3, c=3` / 展平索引 $i_{\text{tx}} = 27$）仅作发射端。定义布尔掩码 $\mathcal{M}_{\text{rx}} \in \{\text{True}, \text{False}\}^{64}$，仅 $\mathcal{M}_{\text{rx}}[27] = \text{False}$，有效接收通道集合 $\mathcal{I}_{\text{rx}} = \{i \in \{0,\dots,63\} : i \neq 27\}$，共 $|\mathcal{I}_{\text{rx}}| = 63$ 路。
- **固定参考通道（Gauge Anchor）**：选定第 4 行第 5 副接收天线（$r=4, k=5$，即 `_3.dat` 第 5 列 / 0-based `n=3, c=4` / 展平索引 $i_{\text{ref}} = 28$）作为全局参考通道。该通道与发射天线同处第 4 行且水平紧邻（间距 $0.07\text{ m}$），直达波信噪比最高且不跨采集板。

### 1.2 采样参数与连续循环周期边界
依据赛题补充说明 2（第 3–5 页）：
- 采样率 $f_s = 4.0\times 10^9\text{ Hz}$，采样间隔 $T_s = 1/f_s = 2.5\times 10^{-10}\text{ s} = 0.25\text{ ns}$。
- 单扫频周期样点数 $N_p = 4000$，周期长度 $T_p = N_p T_s = 1.0\times 10^{-6}\text{ s} = 1\,\mu\text{s}$。
- 数字参考扫频范围 $f_{\text{start}} = 0.3\times 10^9\text{ Hz}$，$f_{\text{stop}} = 1.7\times 10^9\text{ Hz}$，带宽 $B = 1.4\times 10^9\text{ Hz}$，调频斜率 $K = B / T_p = 1.4\times 10^{15}\text{ Hz/s}$。
- 离散数字参考序列（$m = 0,1,\dots,N_p-1$）：
  $$s[m] = A\, w[m] \cos\big(\phi_D(m T_s)\big), \quad \phi_D(t) = 2\pi\!\left(f_{\text{start}} t + \frac{K}{2} t^2\right),$$
  其中 $A = 30000$，$w[m] = 0.54 - 0.46\cos\!\left(\frac{2\pi m}{N_p - 1}\right)$（对称汉明窗，对应 Matlab `hamming(Np).'`）。

**周期边界与异步采集说明**：
1. 发射端稳态循环播放 $N_p = 4000$ 点的射频波形，接收端每包连续采集 $N_{\text{pkt}} = 16000 = 4 N_p$ 点。**“16000 点相当于 4 个发射周期”不代表采集起点对齐到扫频周期零点**；每组采集存在未知的连续异步起始偏移 $t_0^{(g)} \in [0, T_p)$。
2. 第一问中目标最大垂直距离 $d_{\max} = 1.21\text{ m}$，对应双程传播时延 $\tau_{\max} \approx 8.1\text{ ns} \ll T_p = 1000\text{ ns}$（不足周期的 $1\%$），无距离模糊（$c_0 T_p / 2 \approx 149.896\text{ m}$）。将单包 $16000$ 点按 $N_p = 4000$ 折迭分段 $x^{(p,q)}[m] = x^{(p)}[q N_p + m]$（$q \in \{0,1,2,3\}$）属于**后续已批复预处理阶段**的工作（不属于 `D0` 读取器职责）。所有单周期内的移位、相关与匹配滤波**必须按长度 $N_p = 4000$ 的循环卷积 / DFT 频域定义**执行，禁止使用零填充线性相关破坏周期衔接。
3. **多包与跨行一致性门控（预处理阶段执行）**：同一测量组内的 8 个 `.dat` 文件由 `D0` 读取器先按 `sync_packet_cnt` 取交集包集合 $\mathcal{P}_g$；进入预处理后，逐包核查包内 4 段相关性及包间参考通道相位一致性，仅当通过一致性阈值时才做相干均值折叠；若某一行板（如侦察中见于 `空场数据/data2` 行 2）出现包间载波滑移，则在候选改进中引入行板级/包级时偏对齐后再叠加。

---

## 2. 坐标系、单位体系与几何传播路径

### 2.1 全局三维直角坐标系（SI 单位，兼容问题 1–3 与 V0 O-03 核对）
统一采用国际单位制（长度 $\text{m}$，时间 $\text{s}$，频率 $\text{Hz}$，相位 $\text{rad}$）；结果表同时按 $\text{cm}$ 汇报（$1\text{ m} = 100\text{ cm}$）。

结合赛题图 1（第 3 页）与问题 2/3 坐标约定（第 7–8 页）：
- 地面为 $z = 0$；阵列平面在第一问静止于 $y = 0$（垂直于地面），目标平面位于 $y = d > 0$。
- **竖直坐标 $z_r$（m）**：第 $r \in \{1,\dots,8\}$ 行天线中心距地面高度为
  $$z_r = \big(75.5 - 7(r - 1)\big)\times 10^{-2}\text{ m}, \quad r=1,\dots,8,$$
  发射天线 $z_{\text{tx}} = z_4 = 0.545\text{ m}$。
- **水平网格列号与局部 $x$ 坐标（m）**：
  $$c_{\text{grid}}(r,k) = \begin{cases} 2k - 1, & r \text{ 为奇数},\\ 2k, & r \text{ 为偶数}, \end{cases} \quad k \in \{1,\dots,8\},\; c_{\text{grid}} \in \{1,\dots,16\}.$$
  列间距 $\Delta u = 0.035\text{ m}$（$3.5\text{ cm}$），发射天线位于 $r=4, k=4 \Rightarrow c_{\text{grid}} = 8$。以图 1 向左（第 1 列方向，“移动前端”）为 $+x$ 轴正方向、第一问发射天线投影为 $x_{\text{tx}} = 0$：
  $$x_{r,k} = \big(8 - c_{\text{grid}}(r,k)\big)\cdot 0.035\text{ m}.$$
  > **与 V0（O-03）坐标符号核对**：V0 预检文档（`checks/A/q1_preflight.md` §2.2）曾提议 $x = 3.5(c_{\text{grid}} - 1) - 24.5\text{ cm} = (c_{\text{grid}} - 8)\cdot 0.035\text{ m}$，与本文仅相差 $x$ 轴正负号定向；就第一问平面目标（墙体/金属板平行于 $xOz$ 平面）而言，所有传播距离仅依赖 $(x_i - x_{\text{tx}})^2 + (z_i - z_{\text{tx}})^2$，两种定向**完全等价且结果严格不变**。同时本规范明确将 $+x$ 固定为第 1 列移动前端方向，以与问题 2/3（第 3 页图 1、第 7 页 $(x_j, 0)$ 沿 $+x$ 移动）保持一致（第 7 页文字“平行于 $yOz$”与同页“$(x_j, y_j)$ 沿 $x$ 轴平移”之笔误亦在此明确按阵面 $xOz$、深度 $+y$ 统一）。

### 2.2 光速约定与直射波/平面目标传播路径
- **第一轮统一光速**：与 V0 保持一致，第一轮统一取真空光速
  $$c = c_0 = 299792458\text{ m/s}.$$
  标准空气折射率 $n_{\text{air}} \approx 1.0003$（对应 $1\text{ m}$ 处约 $0.03\text{ cm}$ 系统差异）列为后续可选敏感性检查，不在第一轮混用不同 $c$ 值。

1. **直射波路径（TX $\to$ RX $i$）**：
   $$R_i^{\text{dir}} = \|\mathbf{p}_i - \mathbf{p}_{\text{tx}}\|_2 = \sqrt{x_i^2 + (z_i - z_{\text{tx}})^2}, \qquad \tau_i^{\text{dir}} = \frac{R_i^{\text{dir}}}{c_0}.$$
   对参考通道 $i_{\text{ref}} = (4,5)$：$R_{\text{ref}}^{\text{dir}} = 0.070000\text{ m}$，$\tau_{\text{ref}}^{\text{dir}} = 0.233495\text{ ns}$。
2. **平面目标镜面反射路径（镜像法，平面 $y = d > 0$）**：
   设墙体前表面或金属板位于平面 $y = d$（垂直距离 $d > 0$）。发射点 $\mathbf{p}_{\text{tx}} = (0, 0, z_{\text{tx}})$ 关于 $y = d$ 的镜像点为 $\mathbf{p}_{\text{tx}}'(d) = (0, 2d, z_{\text{tx}})$，则第 $i$ 路总传播路径与传播时延为：
   $$R_i^{\text{tgt}}(d) = \|\mathbf{p}_i - \mathbf{p}_{\text{tx}}'(d)\|_2 = \sqrt{(R_i^{\text{dir}})^2 + 4 d^2}, \qquad \tau_i^{\text{tgt}}(d) = \frac{\sqrt{(R_i^{\text{dir}})^2 + 4 d^2}}{c_0}.$$
   单通道净传播时延差与精确反演关系为：
   $$\Delta\tau_i^{\text{prop}}(d) = \tau_i^{\text{tgt}}(d) - \tau_i^{\text{dir}}, \qquad d = \frac{1}{2}\sqrt{\big(c_0\,\tau_i^{\text{tgt}}\big)^2 - (R_i^{\text{dir}})^2}.$$

---

## 3. 第二奈奎斯特区射频镜像与带限传播算子

### 3.1 物理射频信号与混叠映射
根据赛题第 4 页，发射链路选取第二奈奎斯特区（$[2.0, 4.0]\text{ GHz}$），连续时间物理射频信号在单个周期 $0 \le t < T_p$ 内为：
$$s_R(t) = A\, w_c(t)\cos\!\big(2\pi f_s t - \phi_D(t)\big), \qquad f_R(t) = f_s - f_D(t) = f_s - f_{\text{start}} - K t.$$
直接按 $f_s$ 采样满足 $s_R(m T_s) = s[m]$。

### 3.2 带限近似下的射频镜像时延算子
**假设与适用边界说明**：$s[m]$ 是有限时长（$T_p = 1\,\mu\text{s}$）加汉明窗的 LFM 信号，其瞬时频率落在 $[0.3, 1.7]\text{ GHz}$，但加窗截断后的离散傅里叶频谱在数学上**并非严格紧支撑于 $\mathcal{B} = [0.3, 1.7]\text{ GHz}$**（带外存在微弱旁瓣泄露；实测带内 $\mathcal{B}$ 能量占全带宽约 $99.9918\%$）。下述频域射频时延算子是在**假设信号能量主集中在工作频带 $\mathcal{B}$ 内、仅保留第二奈奎斯特区主带 $(f_s/2, f_s)$ 内对应 DFT 分量**的带限近似下成立。

将实信号 $s_R(t)$ 分解为正负解析信号：$s_R(t) = \frac{1}{2} z_R(t) + \frac{1}{2} z_R^*(t)$，其中 $z_R(t) = A w_c(t) e^{j(2\pi f_s t - \phi_D(t))}$ 主频谱位于正射频带 $[2.3, 3.7]\text{ GHz} \subset (f_s/2, f_s)$。经历物理时延 $\tau > 0$ 后：
$$z_R^*(m T_s - \tau) = e^{+j 2\pi f_s \tau}\, \Big[A\, w_c(m T_s - \tau)\, e^{+j\phi_D(m T_s - \tau)}\Big].$$
负射频分量 $-f_R = -(f_s - f_D)$ 经 $f_s$ 采样混叠平移 $+f_s$ 后落入离散正数字频率 $f_D \in \mathcal{B} \subset (0, f_s/2)$。因此，在工作频带 $\mathcal{B}$ 的离散 DFT 网格 $f_D = q/(N_p T_s)$（$f_R = f_s - f_D$）上，理想物理时延 $\tau$ 的带限正频谱响应为：
$$\boxed{X_{\text{ideal}}(f_D) \approx S(f_D)\cdot \exp\!\big(+j 2\pi (f_s - f_D)\tau\big) = S(f_D)\cdot e^{+j 2\pi f_s \tau}\cdot e^{-j 2\pi f_D \tau}, \quad f_D \in \mathcal{B}.}$$

**符号与物理意义**：
1. 群时延 $-\frac{1}{2\pi}\frac{\partial\arg}{\partial f_D} = +\tau > 0$（波形包络向右滞后），同时产生 $-2\pi f_D\tau$ 线性数字相位斜率（与赛题第 6 页表格定义一致）。
2. 当 $\tau / T_s \notin \mathbb{Z}$ 时，载波镜像相移项 $e^{+j 2\pi f_s\tau} \neq 1$；不可用仅含 $e^{-j 2\pi f_D\tau}$ 的数字序列平移替代物理时延。
3. 给定已知物理传播时延 $\tau$，带内传播补偿逆算子为：
   $$\mathcal{C}_{-\tau}[X](f_D) = X(f_D)\cdot \exp\!\big(-j 2\pi (f_s - f_D)\tau\big), \quad f_D \in \mathcal{B}.$$

---

## 4. 完整观测模型与严格可识别性分析

对第 $g$ 组采集，设连续异步采样偏移为 $t_0^{(g)} \in [0, T_p)$（可选行板抖动 $\delta t_{g,r}$，基线取 $0$）。在工作频带 $\mathcal{B}$ 内，第 $i \in \mathcal{I}_{\text{rx}}$ 路接收频谱为：
$$X_i^{(g)}(f_D) = H_i(f_D)\, S(f_D)\, e^{+j 2\pi f_R (t_0^{(g)} + \delta t_{g,r(i)})} \Big[ E_i^{\text{dir}}(f_D)\, e^{+j 2\pi f_R \tau_i^{\text{dir}}} + E_i^{\text{bg}}(f_D) + \mathbb{1}_{\text{tgt}}(g)\,\Gamma_g(f_D)\, \frac{e^{+j 2\pi f_R \tau_i^{\text{tgt}}(d_g)}}{R_i^{\text{tgt}}(d_g)} \Big] + N_i^{(g)}(f_D).$$

### 4.1 可识别性边界：哪些自由度不可识别，哪些在约定/差分下唯一确定

1. **不可识别自由度 A — 公共参考响应 $H_{i_{\text{ref}}}(f_D)$ 与物理绝对触发时刻 $t_0^{(g)}$ 的互换**：
   若对所有通道与所有测量组作如下公共规范变换（任意 $a \in \mathbb{R}$）：
   $$H_i'(f_D) = H_i(f_D)\, e^{-j 2\pi f_R a}, \qquad (t_0^{(g)})' = t_0^{(g)} + a \quad (\forall i, \forall g),$$
   则所有相对通道比 $H_i'(f_D)/H_{i_{\text{ref}}}'(f_D) = H_i(f_D)/H_{i_{\text{ref}}}(f_D)$ 与全部观测频谱 $X_i^{(g)}(f_D)$ **保持完全不变**。因此，**仅靠观测数据无法分别唯一识别参考通道的绝对硬件群时延与物理绝对起始时刻 $t_0^{(g)}$**。
   - **闭环消去证明（有效参考零点与差分测距不变性）**：定义吸收了公共参考相位因子后的**有效参考频谱与有效时间零点** $t_{0,\text{eff}}^{(g)}$：
     $$S_{\text{eff}}^{(g)}(f_D) \triangleq H_{i_{\text{ref}}}(f_D)\, S(f_D)\, e^{+j 2\pi f_R t_0^{(g)}}, \qquad t_{0,\text{eff}}^{(g)} \triangleq t_0^{(g)} + \tau_{\text{ref}}^{\text{hw}}.$$
     在相对校准 $X_i^{(g,\text{cal})}(f_D) = X_i^{(g)}(f_D) / H_i^{\text{rel}}(f_D)$ 后，同一组 $g$（或通过空场对齐模板 $\bar{X}^{\text{air,cal}}$）得到的**直射波有效到达时刻**与**目标回波有效到达时刻**共享同一公共因子 $H_{i_{\text{ref}}}(f_D) e^{+j 2\pi f_R t_0^{(g)}}$。在 $(H_i, t_0^{(g)}) \mapsto (H_i e^{-j2\pi f_R a}, t_0^{(g)} + a)$ 变换下，$t_{0,\text{eff}}^{(g)}$ 严格不变；若存在更一般的公共带内色散 $H_{i_{\text{ref}}}(f_D)$，采用由空场直射波反推的有效参考频谱做匹配（或将公共参考时延吸收进 $t_{0,\text{eff}}^{(g)}$）后，测距目标函数仅依赖净传播路径差 $\tau_i^{\text{tgt}}(d_g) - \tau_{i_{\text{ref}}}^{\text{dir}}$，因而平面距离 $d_g$ 对公共规范移位**严格不变**。

2. **不可识别自由度 B — 相对传递函数 $H_i^{\text{rel}}(f_D)$ 内部 $(\Delta\tau_i, \psi_i(f_D))$ 的共线性**：
   固定参考通道规范约束 $H_{i_{\text{ref}}}^{\text{rel}}(f_D) \equiv 1$ 后，仅能确定复比值 $H_i^{\text{rel}}(f_D) = H_i(f_D)/H_{i_{\text{ref}}}(f_D)$。若 $\psi_i(f_D)$ 为不受约束的任意逐频点函数，则对任意 $\delta \in \mathbb{R}$，变换
   $$\Delta\tau_i' = \Delta\tau_i + \delta, \qquad \psi_i'(f_D) = \psi_i(f_D) + 2\pi f_D \delta$$
   给出**完全相同的复响应** $G_i(f_D)\exp(-j2\pi f_D\Delta\tau_i' + j\psi_i'(f_D))$。因此，固定参考通道本身**不能**消除 $\Delta\tau_i$ 与 $\psi_i(f_D)$ 之间的自由度。
   - **约定下的唯一分解（加权线性投影规范）**：在核心子带 $\mathcal{B}_{\text{core}} = [0.4, 1.6]\text{ GHz}$ 内对解卷绕相位 $\phi_i(f_D) = \operatorname{unwrap}(\angle H_i^{\text{rel}}(f_D))$ 取非负权重 $\omega(f_D) > 0$（基线取参考发射能量 $\omega(f_D) = |S(f_D)|^2$ 或 $|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2$），定义 $(\hat{\theta}_{i,0}, \Delta\hat{\tau}_i)$ 为 $\phi_i(f_D)$ 在 $\operatorname{span}\{1, f_D\}$ 上的加权最小二乘投影：
     $$(\hat{\theta}_{i,0}, \Delta\hat{\tau}_i) = \arg\min_{(\theta_0,\Delta\tau)} \sum_{f_D \in \mathcal{B}_{\text{core}}} \omega(f_D)\big(\phi_i(f_D) - (\theta_0 - 2\pi f_D \Delta\tau)\big)^2.$$
     这等价于对未卷绕剩余相位 $\tilde{\psi}_i(f_D) = \phi_i(f_D) + 2\pi f_D \Delta\hat{\tau}_i$ 施加**中心化一阶矩为零**的正交性约束：
     $$\sum_{f_D \in \mathcal{B}_{\text{core}}} \omega(f_D)\big(\tilde{\psi}_i(f_D) - \hat{\theta}_{i,0}\big)(f_D - \bar{f}_D) = 0, \qquad \bar{f}_D = \frac{\sum \omega(f_D) f_D}{\sum \omega(f_D)}, \qquad \psi_i(f_D) = \operatorname{wrap}_{(-\pi,\pi]}\big(\tilde{\psi}_i(f_D)\big).$$
   - **“约定唯一”与“物理硬件真值可识别”的区分**：上述投影约束仅保证了**给定 $H_i^{\text{rel}}(f_D)$ 在固定解卷绕起点枝下的唯一数学分解**；在物理层面上，如果某通道滤波器本身存在色散或空场近场端射互耦 $E_i^{\text{dir}}(f_D)$ 偏离 $1/R_i^{\text{dir}}$（未知 $E_i^{\text{dir}}$ 不能默认剥离），其线性相位成分会并入 $\Delta\hat{\tau}_i$、幅度响应会并入 $\hat{G}_i(f_D)$。因此在校准与测距中，信号逆校正直接使用完整复频响 $\hat{H}_i^{\text{rel}}(f_D)$（该乘积对 $\delta$ 变换不变），并通过对比纯空场校准（`M0-Cal-Base`）与校准集近法向回波联合校准（`M0-Cal-Joint`）来检验端射耦合偏置大小。

3. **行板间异步抖动核查边界**：同板 8 通道共享同一 ADC 时钟，但不同行板（`_0.dat`–`_7.dat`）在跨组或跨包时若存在独立微弱抖动 $\delta t_{g,r}$，跨行 $\Delta\tau_i$ 将与 $\mathbb{E}_g[\delta t_{g,r}]$ 耦合。须在预处理阶段对 8 行板包间相关性与跨空场组相位稳定性先做统计检验。

---

## 5. 分步数学模型：经典基线与候选改进

严格遵循“先基线、再单因素可控改进并做消融”的原则，以下公式与第 8 节可复跑小算例严格一致。

### 5.1 问题 1.1：通道校准

#### 经典基线（`M0-Cal-Base`：空场几何补偿 + 频域正则化比值校准）
1. **空场模板聚合**：对经预处理折迭、一致性检验后的空场各组 $g \in \mathcal{G}_{\text{air}}$，以指定基准组（如 `空场/data1`）为时间原点，通过带内包络粗搜与射频对齐细搜求得各组偏移 $\Delta\hat{t}_0^{(g)}$，对齐平均得 $\bar{X}_i^{\text{air}}(f_D)$。
2. **传播路径几何补偿**：在假设 $E_i^{\text{dir}}(f_D) \approx c_0 / R_i^{\text{dir}}$（待 `M0-Cal-Joint` 对比检验）下，对 $\mathcal{B} = [0.3, 1.7]\text{ GHz}$ 采用 Tikhonov 正则化除法补偿已知几何传播路径差：
   $$\hat{H}_i^{\text{rel}}(f_D) = \frac{\bar{X}_i^{\text{air}}(f_D)\,\big(\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)\big)^*}{|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2 + \lambda_{\text{cal}} \bar{P}_{\text{ref}}} \cdot \frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}} \cdot \exp\!\Big(-j 2\pi f_R \big(\tau_i^{\text{dir}} - \tau_{i_{\text{ref}}}^{\text{dir}}\big)\Big), \quad f_D \in \mathcal{B},$$
   其中 $\bar{P}_{\text{ref}} = \operatorname{mean}_{f_D \in \mathcal{B}} |\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2$，基准无噪下 $\lambda_{\text{cal}} = 0$，实测中 $\lambda_{\text{cal}} \in [10^{-4}, 10^{-2}]$ 在校准集上选定。
3. **投影参数提取**：在 $\mathcal{B}_{\text{core}} = [0.4, 1.6]\text{ GHz}$ 内按第 4.1 节第 2 条加权线性投影提取 $(\Delta\hat{\tau}_i, \hat{G}_i(f_D), \hat{\psi}_i(f_D))$，其中 $\hat{G}_i(f_D) = |\hat{H}_i^{\text{rel}}(f_D)|$。
4. **信号逆校正算子**：
   $$X_i^{\text{cal}}(f_D) = \begin{cases} \dfrac{\big(\hat{H}_i^{\text{rel}}(f_D)\big)^*}{|\hat{H}_i^{\text{rel}}(f_D)|^2 + \lambda_{\text{inv}}}\, X_i(f_D), & f_D \in \mathcal{B}, \\ 0, & f_D \notin \mathcal{B}. \end{cases}$$

#### 改进候选（`M0-Cal-Joint`：空场时延参考 + 校准组近法向镜面回波联合校准）
- **可证伪假设**：相比端射角 $90^\circ$ 的空场直达波，已知距离校准组 $g \in \mathcal{G}_{\text{cal}}$ 扣减直射波后的目标回波接近法向入射，$E_i^{\text{tgt}}$ 更贴近自由空间 $1/R_i^{\text{tgt}}(d_g)$；在固定参考规范下联合多组校准回波估计 $\hat{H}_i^{\text{rel}}(f_D)$，可检验并降低近场端射互耦对 $\hat{G}_i(f_D)$ 与 $\hat{\psi}_i(f_D)$ 的偏置。

---

### 5.2 问题 1.2：直射波抑制

#### 经典基线（`M0-DW-Base`：校准后射频对齐与空场模板减除）
1. 对空场模板 $\bar{X}_i^{\text{air}}(f_D)$ 与目标测量 $X_i^{(g)}(f_D)$ 施加同一逆校正，得 $\bar{X}_i^{\text{air,cal}}(f_D)$ 与 $X_i^{(g,\text{cal})}(f_D)$。
2. 利用直达波强通道权重 $w_i^{\text{dw}} \ge 0$（如先在参考通道粗搜包络峰 $\hat{k}_0$，再在 $(\hat{k}_0 \pm 1)\,T_s$ 精细搜索，小算例中取参考通道权重 $1$），求相对异步偏移：
   $$\Delta\hat{t}_0^{(g)} = \arg\min_{\Delta t_0 \in [0, T_p)} \sum_{i \in \mathcal{I}_{\text{rx}}} w_i^{\text{dw}} \sum_{f_D \in \mathcal{B}} \Big| X_i^{(g,\text{cal})}(f_D) - \bar{X}_i^{\text{air,cal}}(f_D)\, e^{+j 2\pi f_R \Delta t_0} \Big|^2.$$
3. **模板减除**：
   $$\tilde{X}_i^{(g)}(f_D) = X_i^{(g,\text{cal})}(f_D) - \hat{\alpha}_g\,\bar{X}_i^{\text{air,cal}}(f_D)\, e^{+j 2\pi f_R \Delta\hat{t}_0^{(g)}},$$
   基线取 $\hat{\alpha}_g \equiv 1$，并对照检验全局实标量 $\hat{\alpha}_g$。

#### 改进候选（`M0-DW-Subspace`：多组空场子空间 + 时窗约束直射波抑制）
- **可证伪假设**：利用 10 组对齐空场构造低秩子空间（秩 $1$–$2$）且**仅在直射波主时间窗内拟合投影系数**，以吸收微小环境温漂而不误消近距离目标（$42\text{ cm}$ 墙体）回波。需同时报告直射波抑制比（dB）与近距离目标回波保留率。

---

### 5.3 问题 1.3：金属板与墙体测距

#### 经典基线（`M0-Rng-Base`：有效零点锚定 + 归一化 GLRT 相干/包络 DAS 剖面）
1. **有效参考时间零点锚定**：通过已对齐至当前组的校准空场直达波模板，补偿各通道已知直射波路径 $R_i^{\text{dir}}$ 与时延 $\tau_i^{\text{dir}}$，最大化与数字发射参考 $S(f_D)$ 的相干匹配相关，得到第 $g$ 组有效异步零点 $\hat{t}_{0,\text{eff}}^{(g)}$（吸收任何未知公共参考时延）：
   $$\hat{t}_{0,\text{eff}}^{(g)} = \arg\max_{t_0 \in [0, T_p)} \left| \sum_{i \in \mathcal{I}_{\text{rx}}} \frac{w_i^{\text{dw}}}{R_i^{\text{dir}}} \sum_{f_D \in \mathcal{B}} \big(\bar{X}_i^{\text{air,cal}}(f_D) e^{+j 2\pi f_R \Delta\hat{t}_0^{(g)}}\big) \, S^*(f_D)\, e^{-j 2\pi f_R (\tau_i^{\text{dir}} + t_0)} \right|.$$
2. **归一化多通道延迟叠加（GLRT / Cauchy-Schwarz 无偏统计量）**：
   设模型期望回波导向矢量为 $a_{i,f_D}^{(g)}(d) = \dfrac{1}{R_i^{\text{tgt}}(d)}\, S(f_D)\, e^{+j 2\pi f_R (\tau_i^{\text{tgt}}(d) + \hat{t}_{0,\text{eff}}^{(g)})}$，通道权重矩阵 $W$ 对角元为 $w_i > 0$（第一轮经典基线统一取等权 $w_i \equiv 1$；其余权重须经消融对照后启用）。
   - **归一化相干匹配统计量（主基线 `P_norm`）**：
     $$P_{\text{norm}}^{(g)}(d) = \frac{\big|a^{(g)}(d)^H W \tilde{X}^{(g)}\big|^2}{a^{(g)}(d)^H W a^{(g)}(d)} = \frac{\left|\sum_{i \in \mathcal{I}_{\text{rx}}} \frac{w_i}{R_i^{\text{tgt}}(d)} \sum_{f_D \in \mathcal{B}} \tilde{X}_i^{(g)}(f_D)\, S^*(f_D)\, e^{-j 2\pi f_R (\tau_i^{\text{tgt}}(d) + \hat{t}_{0,\text{eff}}^{(g)})}\right|^2}{\left(\sum_{i \in \mathcal{I}_{\text{rx}}} \frac{w_i}{\big(R_i^{\text{tgt}}(d)\big)^2}\right)\left(\sum_{f_D \in \mathcal{B}} |S(f_D)|^2\right)}.$$
     在无噪理想镜面信号 $\tilde{X}_{i}^{(g)}(f_D) = \Gamma a_{i,f_D}^{(g)}(d_0)$ 下，由 Cauchy-Schwarz 不等式可知 $P_{\text{norm}}^{(g)}(d)$ 在 $d = d_0$ 处**严格唯一达到全局最大值** $|\Gamma|^2 \sum_i \frac{w_i}{(R_i^{\text{tgt}}(d_0))^2} \sum_{f_D\in\mathcal{B}} |S(f_D)|^2$，**零估计偏差**。
     > **关于旧版未归一化形式的偏差说明**：若在分子错乘 $R_i^{\text{tgt}}(d)$ 而分母不归一化，真值 $d_0$ 处的一阶导数存在正偏项 $\sum_i (R_i^{\text{tgt}})'(d_0) / R_i^{\text{tgt}}(d_0) > 0$，会导致小算例峰值从 `0.600000 m` 偏移至 `0.620000 m`（已由 `verify_q1_spec.py` 复现验证）。
   - **归一化非相干包络叠加（对照基线 `P_env`）**：令 $z_i^{(g)}(\tau) = \sum_{f_D \in \mathcal{B}} \tilde{X}_i^{(g)}(f_D)\, S^*(f_D)\, e^{-j 2\pi f_R \tau}$ 为第 $i$ 路去直达波后的复匹配滤波响应，定义同样经几何归一化消偏的包络剖面：
     $$P_{\text{env}}^{(g)}(d) = \frac{\left(\sum_{i \in \mathcal{I}_{\text{rx}}} \frac{w_i}{R_i^{\text{tgt}}(d)}\, \big|z_i^{(g)}\big(\tau_i^{\text{tgt}}(d) + \hat{t}_{0,\text{eff}}^{(g)}\big)\big|\right)^2}{\sum_{i \in \mathcal{I}_{\text{rx}}} \frac{w_i}{\big(R_i^{\text{tgt}}(d)\big)^2}}.$$
3. **峰值提取与墙体多次回波甄别**：$\hat{d}_g = \arg\max_{d \in [d_{\min}, d_{\max}]} P^{(g)}(d)$；墙体工况在先导试验中核对前表面主峰与后界面弱回波的分离门限。

#### 改进候选（`M0-Rng-WLS`：宽带鲁棒加权非线性最小二乘）
- **可证伪假设**：在初值 $\hat{d}_g^{(0)}$ 附近用 `scipy.optimize.least_squares`（实虚部分离，`loss='huber'`）联合拟合 $(d_g, \Gamma_g)$ 并按校准集残差/信噪比确定通道权重 $w_i$，抑制近邻通道残余直射波泄露对远距离或弱回波通道的拉偏。

---

## 6. 既有侦察披露与分层 10/10 校准/检验拆分提案（待确认冻结）

### 6.1 截至本方案前已探索/侦察的真实数据组清单
为严守“检验组绝对不得参与探索、拟合或调参”，以下列出 M0 与 V0 阶段曾读取检查的全部测量组：
- `空场数据`：`data1`, `data2`, `data3`, `data4`, `data5`（共 5 组；空场全部归入校准/模板池）。
- `墙体数据`：`data1-42cm`（1 组；已划入下方校准集 $\mathcal{G}_{\text{cal}}^{\text{wall}}$）。
- `金属板数据`：`data1-69cm`（1 组；V0 与 M0 前期侦察曾读取，现已从拟议检验集调入校准集 $\mathcal{G}_{\text{cal}}^{\text{metal}}$，并与 `data10-70cm` 对换，保持 10/10 均衡）。

### 6.2 建议分层 10/10 拆分表（所有拟议检验组均未曾触碰）
当前拆分**尚未冻结**，待 `codex` 与 `my_deepseek` 核对后固化为正式清单；冻结前严禁对任何检验组做参数调整：

| 目标类型 | 用途 | 组数 | 建议目录清单 | 距离覆盖（cm） |
|---|---|---|---|---|
| 空场数据 | 校准/直射波模板 | 10 | `data1`–`data10`（全量用于模板与空场自检） | — |
| 墙体数据 | 校准集 $\mathcal{G}_{\text{cal}}^{\text{wall}}$ | 10 | `data1-42cm`, `data16-46cm`, `data13-56cm`, `data4-62cm`, `data2-71cm`, `data11-76cm`, `data8-78cm`, `data10-82cm`, `data19-93cm`, `data7-106cm` | 42 – 106 |
| 墙体数据 | 检验集 $\mathcal{G}_{\text{test}}^{\text{wall}}$ | 10 | `data5-44cm`, `data14-48cm`, `data15-57cm`, `data12-65cm`, `data20-73cm`, `data3-77cm`, `data17-81cm`, `data9-91cm`, `data18-105cm`, `data6-121cm` | 44 – 121 |
| 金属板数据 | 校准集 $\mathcal{G}_{\text{cal}}^{\text{metal}}$ | 10 | `data2-48cm`, `data13-52cm`, `data3-54cm`, `data16-59cm`, `data11-62cm`, `data20-68cm`, **`data1-69cm`**, `data19-74cm`, `data8-83cm`, `data7-91cm` | 48 – 91 |
| 金属板数据 | 检验集 $\mathcal{G}_{\text{test}}^{\text{metal}}$ | 10 | `data14-48cm`, `data15-53cm`, `data12-55cm`, `data5-60cm`, `data17-65cm`, **`data10-70cm`**, `data18-70cm`, `data9-76cm`, `data4-87cm`, `data6-99cm` | 48 – 99 |

---

## 7. 数据与接口契约（严格区分 D0 读取器与预处理阶段）

### 7.1 `D0` 读取器输出契约（`data/a-q1-reader`，不做折迭与校准）
- `packets`: `int16` 或 `float64` 原始逐包数组，按组内 8 个文件共同 `sync_packet_cnt` 交集配对，形状 `(P_common, 64, 16000)`（或等价 `(P_common, 8, 8, 16000)`）。
- `rx_mask`: `bool` 数组，形状 `(64,)`，`rx_mask[27] == False`，其余 63 项为 `True`。
- `tx_idx`: `int = 27`；`ref_idx`: `int = 28`。
- `positions_m`: `float64` 数组，形状 `(64, 3)`，单位 $\text{m}$（按第 2.1 节坐标公式）。
- `meta`: 组别、目录、共同 `sync_packet_cnt` 列表、每文件缺包/损坏记录、极值 `-32768/+32767` 统计（以 `int32` 升位计数）。

### 7.2 已批复预处理阶段输出（`A-Q1-E0` 前端）
- 经包内 4 段（$N_p = 4000$）与包间一致性门控后，折叠输出单周期实值信号 `signals_folded`: `float64` 数组，形状 `(64, 4000)`，及逐包相位漂移诊断日志。

### 7.3 求解器交付契约（问题 1.1–1.3）
1. **校准参数表**：`channel_idx`, `row`, `col_in_row`, `grid_col`, `delta_tau_s`（投影约定下）, `gain_mag_band`, `residual_phase_rad_band`，及代表性通道校准前后波形/频谱图。
2. **直射波抑制指标**：空场留一交叉抑制比（dB）、校准集直射波时间窗残余功率降幅（dB）与目标回波峰保持率。
3. **测距结果表**：逐组与汇总（按 `wall`/`metal` 与 `cal`/`test` 分列）MAE、RMSE、MaxAE、中位绝对误差（$\text{cm}$）及峰旁瓣比（dB）。

---

## 8. 独立可复跑闭环小算例（附 `solutions/A/verify_q1_spec.py`）

本算例脚本 [verify_q1_spec.py](verify_q1_spec.py) 仅包含第 5 节解析闭环公式与第 4.1 节可识别性反例检验（不读取 `.dat`、不是生产估计器），供统筹与验证方直接复跑核对。

### 8.1 算例参数
- 统一常数：$c_0 = 299792458\text{ m/s}$，$f_s = 4.0\times 10^9\text{ Hz}$，$T_s = 0.25\text{ ns}$，$N_p = 4000$。
- 几何：TX $(0, 0, 0.545)\text{ m}$；RX1 $(-0.07, 0, 0.545)\text{ m}$（参考通道，$R_1^{\text{dir}} = 0.070000\text{ m}$）；RX2 $(-0.07, 0, 0.685)\text{ m}$（$R_2^{\text{dir}} = 0.156525\text{ m}$）。
- 植入偏差（RX2 相对 RX1）：$\Delta\tau_2 = +0.500000\text{ ns}$、$G_2 \equiv 1.250000$、$\psi_2 \equiv +0.300000\text{ rad}$。
- 平面目标与异步偏移：$d_{\text{true}} = 0.600000\text{ m}$，$\Gamma = -0.35$，$t_0^{\text{air}} = 120.25\,T_s$，$t_0^{\text{tgt}} = 250.40\,T_s$（$\Delta t_0 = +130.15\,T_s$）。

### 8.2 运行命令与预期/实测输出
运行命令：
```powershell
python solutions/A/verify_q1_spec.py
```

| 检查项 | 数学预期 | 脚本实测结果 |
|---|---|---|
| 带内能量占比（$[0.3,1.7]\text{ GHz}$） | $\approx 1$（存在约 $0.008\%$ 带外旁瓣） | `0.99991761` |
| 相对校准（投影约定还原） | $\Delta\hat{\tau}_2 = 0.500000\text{ ns},\ \hat{G}_2 = 1.250000,\ \hat{\psi}_2 = 0.300000\text{ rad}$ | `dtau2=0.500000 ns, G2=1.250000, psi2=0.300000 rad` |
| 射频对齐与有效零点 | $\Delta\hat{t}_0 = 130.1500\,T_s,\ \hat{t}_{0,\text{eff}}^{\text{tgt}} = 250.4000\,T_s$ | `dt0=130.1500 Ts, t0_eff_tgt=250.4000 Ts` |
| 旧版未归一化 DAS 偏差对照 | $> 0.60\text{ m}$（存在正一阶导数偏项） | `0.620000 m`（复现 $+2.0\text{ cm}$ 偏差） |
| 归一化 `P_norm` 与 `P_env` 测距（$[0.55, 0.65]\text{ m}$, $10\,\mu\text{m}$ 步长） | `0.600000 m`（零偏差闭环） | `P_norm = 0.600000 m`，`P_env = 0.600000 m` |
| 反例 A（自由 $\psi$ 移位 $\delta = 0.25\text{ ns}$） | $\max|H_2 - H_2'| \approx 0$ | `max|H - H'| = 2.445e-15`（加权投影唯一固定 $\Delta\hat{\tau}_2$） |
| 反例 B（公共 $H_{\text{ref}}$ 与 $t_0$ 移位 $a = 0.35\text{ ns}$） | 相对观测不变，且有效零点消去后 $\hat{d}' = 0.600000\text{ m}$ | `rel\|X_air-X'\|=1.017e-13, rel\|X_tgt-X'\|=2.051e-13, d_norm'=0.600000 m` |

---

## 9. 已知限制与后续推进前提

1. **端射耦合响应 $E_i^{\text{dir}}(f_D)$ 未知**：纯空场校准假定 $E_i^{\text{dir}} \propto 1/R_i^{\text{dir}}$ 可能将阵元端射方向图/互耦并入 $\hat{G}_i, \hat{\psi}_i$；需在 `A-Q1-E0` 中用校准集比较 `M0-Cal-Base` 与 `M0-Cal-Joint`。
2. **行板间异步微漂移检验**：需待 `D0` 完成全量 8 行包间相关性统计后，判定是否需要开启行板级微移参数 $\delta t_{g,r}$。
3. **墙体介质内部多界面反射**：墙体前表面主峰可能受后界面弱反射旁瓣影响，需在先导试验中测试前向首峰门限稳定性。
