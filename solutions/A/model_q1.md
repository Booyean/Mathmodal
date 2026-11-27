# A 题第一问数学方案（M0：通道校准、直射波抑制与平面目标测距）

- **任务编号**：M0（`model/a-q1-spec`）
- **主责**：`antigravity02`（建模与论文）
- **输入基线**：`main` = `e1f50ec1723ce74ac4ef9d550b50835b0f7e8dd9`，原始数据基线 = `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9`
- **参考依据**：赛题 PDF 第 1、3–7 页；`附件1-数据读取函数/get_data_iq.m`；`coordination/A_Q1_PLAN.md`；`coordination/A_Q1_METHODS.md`
- **状态说明**：本文件为数学规范与接口契约；**须经统筹 `codex` 审阅并记录 `A-Q1-M0` 批复后，方可进入正式实现与试验**。

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
2. 第一问中目标最大垂直距离 $d_{\max} = 1.21\text{ m}$，对应双程传播时延 $\tau_{\max} \approx 8.1\text{ ns} \ll T_p = 1000\text{ ns}$（不足周期的 $1\%$），无距离模糊（unambiguous range $c T_p / 2 \approx 150\text{ m}$）。由于信号在稳态连续周期循环下采集，将单包 $16000$ 点按 $N_p = 4000$ 折迭分段 $x^{(p,q)}[m] = x^{(p)}[q N_p + m]$（$q \in \{0,1,2,3\}$），其内部 4 段在理想无漂移下具有同一周期相位；所有单周期内的移位、相关与匹配滤波**必须按长度 $N_p = 4000$ 的循环卷积/DFT 频域定义**执行，禁止使用零填充线性相关破坏周期衔接。
3. **多包与跨行一致性校验（前置门控）**：同一测量组内的 8 个 `.dat` 文件先按 `sync_packet_cnt` 取交集包集合 $\mathcal{P}_g$；对每包先计算 4 段周期内相关系数与逐包参考通道包间相位漂移。仅当各段/各包满足一致性阈值时才做相干均值折叠；若某一行板（如部分采集组中的板卡微弱相位漂移）出现包间相位滑移 $\delta\theta_{g,p,r}$，应在候选改进中显式引入板级/包级残余时偏或按包对齐后再叠加。

---

## 2. 坐标系、单位体系与几何传播路径

### 2.1 全局三维直角坐标系（SI 单位，兼容问题 1–3）
统一采用国际单位制（长度 $\text{m}$，时间 $\text{s}$，频率 $\text{Hz}$，相位 $\text{rad}$）；表征结果与赛题对照时换算为 $\text{cm}$（$1\text{ m} = 100\text{ cm}$）。

结合赛题图 1（第 3 页）与问题 2/3 坐标约定（第 7–8 页）：
- 地面为 $z = 0$；阵列平面在第一问静止于 $y = 0$（垂直于地面），目标平面位于 $y = d > 0$。
- **竖直坐标 $z_r$（m）**：第 $r \in \{1,\dots,8\}$ 行天线中心距地面高度为
  $$z_r = \big(75.5 - 7(r - 1)\big)\times 10^{-2}\text{ m}, \quad r=1,\dots,8,$$
  于是发射天线 $z_{\text{tx}} = z_4 = 0.545\text{ m}$。
- **水平网格列号与局部 $x$ 坐标（m）**：奇数行占据奇数列，偶数行占据偶数列，即 16 列网格编号为
  $$c_{\text{grid}}(r,k) = \begin{cases} 2k - 1, & r \text{ 为奇数},\\ 2k, & r \text{ 为偶数}, \end{cases} \quad k \in \{1,\dots,8\},\; c_{\text{grid}} \in \{1,\dots,16\}.$$
  列间距 $\Delta u = 0.035\text{ m}$（$3.5\text{ cm}$），发射天线位于 $r=4, k=4 \Rightarrow c_{\text{grid}} = 8$。以图 1 向左（第 1 列方向）为 $+x$ 轴正方向、以第一问发射天线水平投影为 $x_{\text{tx}} = 0$：
  $$x_{r,k} = \big(8 - c_{\text{grid}}(r,k)\big)\cdot 0.035\text{ m}.$$
  因此第 $i$ 路天线的三维坐标为 $\mathbf{p}_i = (x_i, 0, z_i)$，发射天线坐标为 $\mathbf{p}_{\text{tx}} = (0, 0, 0.545)\text{ m}$。
  > **几何对称性注记**：第一问中墙体与金属板均平行于阵列平面（$y = d$），所有直达路径与镜面反射路径仅依赖阵列面内欧氏距 $\|\mathbf{p}_i - \mathbf{p}_{\text{tx}}\|_2 = \sqrt{(x_i - x_{\text{tx}})^2 + (z_i - z_{\text{tx}})^2}$，对 $\pm x$ 定向完全不变；上述符号约定同时与问题 2/3 的移动方向一致。

### 2.2 直射波与平面目标传播路径
取空气中电磁波传播速度 $c = c_0 / n_{\text{air}}$，其中真空光速 $c_0 = 2.99792458\times 10^8\text{ m/s}$，标准空气折射率 $n_{\text{air}} \approx 1.0003$（对应 $c \approx 2.9970\times 10^8\text{ m/s}$；相比直接使用 $c_0$，在 $1\text{ m}$ 距离上差异仅 $0.03\text{ cm}$）。

1. **直射波路径（TX $\to$ RX $i$）**：
   $$R_i^{\text{dir}} = \|\mathbf{p}_i - \mathbf{p}_{\text{tx}}\|_2 = \sqrt{x_i^2 + (z_i - z_{\text{tx}})^2}, \qquad \tau_i^{\text{dir}} = \frac{R_i^{\text{dir}}}{c}.$$
   对参考通道 $i_{\text{ref}} = (4,5)$：$R_{\text{ref}}^{\text{dir}} = 0.070000\text{ m}$，$\tau_{\text{ref}}^{\text{dir}} \approx 0.2335\text{ ns}$。
2. **平面目标镜面反射路径（镜像法，平面 $y = d > 0$）**：
   设墙体前表面或金属板位于平面 $y = d$（垂直距离 $d > 0$）。由电磁波镜面反射（虚像法），发射点 $\mathbf{p}_{\text{tx}} = (0, 0, z_{\text{tx}})$ 关于反射面 $y = d$ 的镜像点为 $\mathbf{p}_{\text{tx}}'(d) = (0, 2d, z_{\text{tx}})$。由 Fermat 原理，镜面反射点位于连接 $\mathbf{p}_{\text{tx}}'(d)$ 与 $\mathbf{p}_i$ 的直线上，故第 $i$ 路总传播路径与传播时延为：
   $$R_i^{\text{tgt}}(d) = \|\mathbf{p}_i - \mathbf{p}_{\text{tx}}'(d)\|_2 = \sqrt{(R_i^{\text{dir}})^2 + 4 d^2}, \qquad \tau_i^{\text{tgt}}(d) = \frac{\sqrt{(R_i^{\text{dir}})^2 + 4 d^2}}{c}.$$
   单通道目标回波相对其自身直射波的物理传播时延差为：
   $$\Delta\tau_i^{\text{prop}}(d) = \tau_i^{\text{tgt}}(d) - \tau_i^{\text{dir}} = \frac{\sqrt{(R_i^{\text{dir}})^2 + 4 d^2} - R_i^{\text{dir}}}{c} > 0,$$
   其精确反演公式为：
   $$d = \frac{1}{2}\sqrt{\big(c\,\tau_i^{\text{tgt}}\big)^2 - (R_i^{\text{dir}})^2} = \frac{1}{2}\sqrt{\big(c\,\Delta\tau_i^{\text{prop}} + R_i^{\text{dir}}\big)^2 - (R_i^{\text{dir}})^2}.$$

---

## 3. 第二奈奎斯特区射频镜像与传播算子（核心物理模型）

### 3.1 从数字发射序列到物理射频信号
根据赛题第 4 页，发射链路选取第二奈奎斯特区（$f_s/2 = 2.0\text{ GHz}$ 至 $f_s = 4.0\text{ GHz}$）镜像。连续时间物理射频信号在单个周期 $0 \le t < T_p$ 内为：
$$s_R(t) = A\, w_c(t)\cos\!\big(2\pi f_s t - \phi_D(t)\big),$$
其物理射频瞬时频率由 $3.7\text{ GHz}$ 线性下降至 $2.3\text{ GHz}$：
$$f_R(t) = f_s - f_D(t) = f_s - f_{\text{start}} - K t.$$
对理想零时延射频波形直接以 $f_s$ 采样（$f_s m T_s = m \in \mathbb{Z}$），得到 $s_R(m T_s) = A w[m]\cos(2\pi m - \phi_D(mT_s)) = s[m]$。

### 3.2 物理传播时延 $\tau$ 在离散数字频域中的精确表示
**不可直接对数字序列 $s[m]$ 做普通插值/相位斜坡 $e^{-j 2\pi f_D \tau}$ 来等价物理延时！** 推导如下：

将 $s_R(t)$ 拆分为正负解析信号分量：$s_R(t) = \frac{1}{2} z_R(t) + \frac{1}{2} z_R^*(t)$，其中 $z_R(t) = A w_c(t) e^{j(2\pi f_s t - \phi_D(t))}$ 的频谱仅支持在正射频带 $[2.3, 3.7]\text{ GHz} \subset (f_s/2, f_s)$。当电磁波经历物理时延 $\tau > 0$ 时，到达接收端的射频信号为 $s_R(t - \tau)$，以 $t = m T_s$ 采样得：
$$s_R(m T_s - \tau) = \frac{1}{2} z_R(m T_s - \tau) + \frac{1}{2} z_R^*(m T_s - \tau).$$
其中共轭分支在 $t = m T_s$ 处为：
$$z_R^*(m T_s - \tau) = A\, w_c(m T_s - \tau)\, e^{-j 2\pi f_s (m T_s - \tau) + j\phi_D(m T_s - \tau)} = e^{+j 2\pi f_s \tau}\, \Big[A\, w_c(m T_s - \tau)\, e^{+j\phi_D(m T_s - \tau)}\Big].$$
由于信号在基带数字采样前处于 $(f_s/2, f_s)$，连续频谱中位于负射频 $-f_R = -(f_s - f_D)$ 的分量经采样混叠平移 $+f_s$ 后，恰好落入离散正数字频率 $f_D \in [f_{\text{start}}, f_{\text{stop}}] \subset (0, f_s/2)$。因此，对周期信号做 $N_p$ 点 DFT（记数字频率 $f_D \in \{q/(N_p T_s) : q=0,\dots,N_p/2\}$，物理射频映射 $f_R = f_s - f_D$），理想时延 $\tau$ 的离散正频谱响应为：
$$\boxed{X_{\text{ideal}}(f_D) = S(f_D)\cdot \exp\!\big(+j 2\pi (f_s - f_D)\tau\big) = S(f_D)\cdot e^{+j 2\pi f_s \tau}\cdot e^{-j 2\pi f_D \tau}.}$$

**符号与物理意义双重校验**：
1. **群时延 / 包络移动方向**：相位对数字频率 $f_D$ 的导数为 $-\frac{1}{2\pi}\frac{\partial \arg}{\partial f_D} = +\tau > 0$，即包络和瞬时数字频率向右（更晚的采样时刻 $m T_s$）移动 $+\tau$，符合物理因果性；同时与赛题第 6 页表格中“滞后 $\Delta\tau_i > 0$ 在频域产生 $-2\pi f_D \Delta\tau_i$ 线性相位差”的定义完全一致。
2. **射频载波镜像相移项 $e^{+j 2\pi f_s \tau}$**：当 $\tau / T_s \in \mathbb{Z}$ 时，$e^{+j 2\pi f_s \tau} = 1$，此时离散整数移位与物理延迟重合；但当 $\tau$ 存在**亚采样小数时延**时（例如 $\Delta\tau = 0.5 T_s \Rightarrow \Delta R \approx 3.75\text{ cm}$），$2\pi f_s \tau = \pi$ 会带来 $180^\circ$ 载波反转。若忽略 $+2\pi f_s \tau$ 项而直接对数字序列平移，将在多通道相干叠加和空场模板对齐相减中产生高达 $\sim 180^\circ$ 的相消误差。
3. **传播补偿算子**：给定已知物理传播时延 $\tau$，从接收频谱中消除该传播时延的逆算子为：
   $$\mathcal{C}_{-\tau}[X](f_D) = X(f_D)\cdot \exp\!\big(-j 2\pi (f_s - f_D)\tau\big), \quad f_D \in (0, f_s/2).$$
   所有时域重构均通过复共轭对称的 `irfft(..., n=Np)` 返回实值周期序列。

---

## 4. 完整观测模型与参数可识别性分析

对第 $g$ 组采集，设该组共同异步采样偏移为 $t_0^{(g)} \in [0, T_p)$，并允许可选的行板级残余时间抖动 $\delta t_{g,r}$（基线模型中设 $\delta t_{g,r} \equiv 0$，扩展模型中用于检验板卡微弱漂移）。在工作频带 $\mathcal{B} = \{f_D : f_{\text{start}} \le f_D \le f_{\text{stop}}\}$ 内，第 $i \in \mathcal{I}_{\text{rx}}$ 路接收频谱建模为：
$$X_i^{(g)}(f_D) = H_i(f_D)\, S(f_D)\, e^{+j 2\pi f_R (t_0^{(g)} + \delta t_{g,r(i)})} \Big[ E_i^{\text{dir}}(f_D)\, e^{+j 2\pi f_R \tau_i^{\text{dir}}} + E_i^{\text{bg}}(f_D) + \mathbb{1}_{\text{tgt}}(g)\,\Gamma_g(f_D)\, \frac{e^{+j 2\pi f_R \tau_i^{\text{tgt}}(d_g)}}{R_i^{\text{tgt}}(d_g)} \Big] + N_i^{(g)}(f_D),$$
其中：
- $H_i(f_D)$ 为第 $i$ 路设备传递函数（相对参考通道拆解为时延差 $\Delta\tau_i \in \mathbb{R}$、幅度比 $G_i(f_D) > 0$ 与剩余相位差 $\psi_i(f_D) \in (-\pi, \pi]$）：
  $$H_i^{\text{rel}}(f_D) \triangleq \frac{H_i(f_D)}{H_{i_{\text{ref}}}(f_D)} = G_i(f_D)\,\exp\!\big(-j 2\pi f_D \Delta\tau_i + j\psi_i(f_D)\big).$$
  注意此处设备链路自身差异定义在基带/通道观测频率 $f_D$ 上，与物理定义表格（PDF 第 6 页）一致；其中符号约定为 $\Delta\tau_i > 0$ 表示第 $i$ 路相对参考通道硬件滞后（对应线性相位斜率 $-2\pi f_D \Delta\tau_i$）。
- $E_i^{\text{dir}}(f_D)$ 为空场直射波复耦合响应（包含球面扩展 $1/R_i^{\text{dir}}$ 与阵列面内 Vivaldi 单元方向性/互耦响应）。
- $E_i^{\text{bg}}(f_D)$ 为空场固有背景杂波（地面/机架散射）。
- $\Gamma_g(f_D)$ 为平面目标有效复反射响应（理想金属板接近常数负反射 $-|\Gamma_0|$，墙体前表面为与介电常数相关的复反射系数；对远场/正入射平面波可近似各通道共有，大斜视角下的辐射方向图差异由几何权重控制）。

### 可识别性（Identifiability）证明与约束条件
1. **全局尺度与时延规范自由度（Gauge Ambiguity）**：若将所有通道 $H_i(f_D)$ 同乘非零复函数 $C(f_D)$，同时将发射参考 $S(f_D)$ 除以 $C(f_D)$，观测值 $X_i^{(g)}(f_D)$ 保持不变。通过固定参考通道规范约束：
   $$\Delta\tau_{i_{\text{ref}}} \equiv 0, \qquad G_{i_{\text{ref}}}(f_D) \equiv 1, \qquad \psi_{i_{\text{ref}}}(f_D) \equiv 0 \quad (\forall f_D \in \mathcal{B}),$$
   消除了全局参考模糊度，$H_i^{\text{rel}}(f_D)$ 相对 $i_{\text{ref}}$ 唯一确定。
2. **异步启动偏移 $t_0^{(g)}$ 与设备时延 $\Delta\tau_i$ 的分离**：在单次采集中，同板/同组共享 $t_0^{(g)}$，因此在同组比值 $X_i^{(g)}(f_D)/X_{i_{\text{ref}}}^{(g)}(f_D)$ 中，公共因子 $S(f_D) e^{+j 2\pi f_R t_0^{(g)}}$ 完全抵消，故 $\Delta\tau_i$ 与绝对触发时刻 $t_0^{(g)}$ 可分离。但若不同采集行板之间存在未锁相的独立随机抖动 $\delta t_{g,r}$，跨行 $\Delta\tau_i$ 将与均值 $\mathbb{E}_g[\delta t_{g,r}]$ 混叠，因此需跨多组空场与校准组检验 $\delta t_{g,r}$ 的方差量级（基线先行检验各行板一致性）。
3. **设备时延 $\Delta\tau_i$ 与传播时延 $\tau_i^{\text{dir}}$ / $\tau_i^{\text{tgt}}$ 的分离**：两类时延均已知物理几何表达式 $\tau_i^{\text{dir}} = R_i^{\text{dir}}/c$ 与 $\tau_i^{\text{tgt}}(d_g) = \sqrt{(R_i^{\text{dir}})^2+4d_g^2}/c$。扣除已知的几何传播时延差 $\tau_i^{\text{prop}} - \tau_{i_{\text{ref}}}^{\text{prop}}$ 后，剩余的线性相位斜率即为设备自身时延差 $\Delta\tau_i$。
4. **直射波互耦响应 $E_i^{\text{dir}}(f_D)$ 与设备增益 $G_i(f_D)$ 的可分性警告**：在空场直达波中，接收天线处于发射天线近场/端射（$90^\circ$ 掠射）位置，各阵元之间的 E/H 面方向图与互耦差异会进入 $E_i^{\text{dir}}(f_D)$；若仅以自由空间 $1/R_i^{\text{dir}}$ 替代 $E_i^{\text{dir}}(f_D)$ 来反推 $G_i(f_D)$，会把端射耦合系数混入通道硬件增益 $G_i(f_D)$。**解决策略**：利用已知距离校准组 $g \in \mathcal{G}_{\text{cal}}$ 扣除空场直射波后的近法向镜面回波（入射角显著减小、互耦影响远弱于阵列面内直达波），在保留空场独立时延分离的基础上，联合评估或对比纯空场校准与联合校准的留出测距误差。
5. **绝对参考零点 $t_0^{(g)}$ 与测距绝对时延的锚定**：由于采样异步，$t_0^{(g)}$ 未知，无法单独从 $\tau_i^{\text{tgt}} + t_0^{(g)}$ 确定 $d_g$；必须通过同一次测量 $g$ 中**参考通道的直射波到达时刻**（由与空场对齐的直射波模板给出 $\hat{\tau}_{\text{ref,dir}}^{(g)} = \tau_{\text{ref}}^{\text{dir}} + \hat{t}_0^{(g)}$）与目标回波到达时刻做差（或共同锚定 $\hat{t}_0^{(g)}$），从而完全消除异步采集偏移 $t_0^{(g)}$。

---

## 5. 分步数学模型：经典基线与候选改进

严格遵循“先基线、再单因素可控改进并做消融”的原则，不将未验证的改进写为既定方案。

### 5.1 问题 1.1：通道校准

#### 经典基线（`M0-Cal-Base`：空场几何补偿 + 频域正则化比值校准）
1. **空场模板聚合**：对空场各组 $g \in \mathcal{G}_{\text{air}}$（经过包同步与周期折叠验证后），以任意指定空场基准组（如 `空场/data1`）为时间原点，利用参考通道（或全 63 路联合）在 $[0, T_p)$ 搜索每组的射频对齐时移 $\Delta\hat{t}_0^{(g)}$（最大化带内 $\mathcal{B}$ 内积 / 最小化 $L_2$ 残差），将各空场组对齐到同一时间基准后做平均，得到高信噪比空场平均频谱 $\bar{X}_i^{\text{air}}(f_D)$。
2. **传播路径几何补偿**：假设空场以直射波主导且近似满足 $E_i^{\text{dir}} \propto 1/R_i^{\text{dir}}$，对每路相对参考通道补偿已知传播时延差与几何扩散比：
   $$\hat{H}_i^{\text{raw}}(f_D) = \frac{\bar{X}_i^{\text{air}}(f_D)}{\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)} \cdot \frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}} \cdot \exp\!\Big(-j 2\pi f_R \big(\tau_i^{\text{dir}} - \tau_{i_{\text{ref}}}^{\text{dir}}\big)\Big), \quad f_D \in \mathcal{B}.$$
   为避免分母 $|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|$ 在带边汉明窗衰减区过小引发噪声放大，采用 **Tikhonov/Wiener 正则化除法**：
   $$\hat{H}_i^{\text{raw}}(f_D) = \frac{\bar{X}_i^{\text{air}}(f_D)\,\big(\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)\big)^*}{|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2 + \lambda_{\text{cal}} \bar{P}_{\text{ref}}} \cdot \frac{R_i^{\text{dir}}}{R_{i_{\text{ref}}}^{\text{dir}}} \cdot \exp\!\Big(-j 2\pi f_R \big(\tau_i^{\text{dir}} - \tau_{i_{\text{ref}}}^{\text{dir}}\big)\Big),$$
   其中 $\bar{P}_{\text{ref}} = \operatorname{mean}_{f_D \in \mathcal{B}} |\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2$，$\lambda_{\text{cal}} \in [10^{-4}, 10^{-2}]$ 为正则化系数（在校准集上选定）。
3. **三参数提取（$\Delta\tau_i, G_i(f_D), \psi_i(f_D)$）**：
   - 将 $\angle \hat{H}_i^{\text{raw}}(f_D)$ 在有效子带 $\mathcal{B}_{\text{core}} = [0.4, 1.6]\text{ GHz}$ 内解卷绕（`unwrap`），对该子带内相位作带权线性回归 $\angle \hat{H}_i^{\text{raw}}(f_D) \approx \theta_{i,0} - 2\pi \Delta\tau_i f_D$（权重取 $|\bar{X}_{i_{\text{ref}}}^{\text{air}}(f_D)|^2$），解得时延校正量 $\Delta\hat{\tau}_i$（单位：$\text{s}$）。
   - 幅度校正参数：$\hat{G}_i(f_D) = |\hat{H}_i^{\text{raw}}(f_D)|$（无量纲）。
   - 剩余相位校正参数：扣除线性时延项后的残余相位 $\hat{\psi}_i(f_D) = \operatorname{wrap}_{(-\pi,\pi]}\!\big(\angle \hat{H}_i^{\text{raw}}(f_D) + 2\pi f_D \Delta\hat{\tau}_i\big)$（单位：$\text{rad}$）。
4. **信号逆校正算子**：对任意待处理频谱 $X_i(f_D)$，带内正则化逆滤波为：
   $$X_i^{\text{cal}}(f_D) = \begin{cases} \dfrac{\big(\hat{H}_i^{\text{raw}}(f_D)\big)^*}{|\hat{H}_i^{\text{raw}}(f_D)|^2 + \lambda_{\text{inv}}}\, X_i(f_D), & f_D \in \mathcal{B}, \\ 0, & f_D \notin \mathcal{B}. \end{cases}$$

#### 改进候选（`M0-Cal-Joint`：空场时延分离 + 校准组镜面回波联合响应估计）
- **可证伪假设**：由于空场直达波受阵元端射耦合和地面背景散射影响，$E_i^{\text{dir}}$ 偏离纯 $1/R_i^{\text{dir}}$；若利用校准分割集 $g \in \mathcal{G}_{\text{cal}}$（已知距离 $d_g$）中**已抑制直射波的目标回波**，在近正入射方向上联合估计宽带复响应 $\hat{H}_i^{\text{raw}}(f_D)$（结合多组加权最小二乘与正则化平滑），可在不引入检验集标签的前提下降低跨通道幅相残差并改善测距精度。
- **需验证与消融项**：对比 `M0-Cal-Base` 与 `M0-Cal-Joint` 在校准交叉验证与留出检验集上的通道残差及测距 RMSE；检查跨行板是否存在残余同步抖动 $\delta t_{g,r}$。

---

### 5.2 问题 1.2：直射波抑制

#### 经典基线（`M0-DW-Base`：校准后射频对齐与空场模板减除）
1. 对空场模板 $\bar{X}_i^{\text{air}}(f_D)$ 与目标测量 $X_i^{(g)}(f_D)$ 施加同一通道校准算子，得 $\bar{X}_i^{\text{air,cal}}(f_D)$ 与 $X_i^{(g,\text{cal})}(f_D)$。
2. 利用校准后全 63 路（或直达波强通道子集）的带内信号，在 $\Delta t_0 \in [0, T_p)$ 内通过包络粗搜 + 亚采样精确搜索，求取该组相对空场模板的异步采样偏移 $\Delta\hat{t}_0^{(g)}$：
   $$\Delta\hat{t}_0^{(g)} = \arg\min_{\Delta t_0 \in [0, T_p)} \sum_{i \in \mathcal{I}_{\text{rx}}} w_i^{\text{dw}} \sum_{f_D \in \mathcal{B}} \Big| X_i^{(g,\text{cal})}(f_D) - \bar{X}_i^{\text{air,cal}}(f_D)\, e^{+j 2\pi f_R \Delta t_0} \Big|^2.$$
   （其中 $w_i^{\text{dw}}$ 为预设或校准集确定的直达波能量权重；注意使用带通频域 RF 移位 $e^{+j 2\pi f_R \Delta t_0}$，**不得用整数点平移**。）
3. **幅度/模板减除**：
   $$\tilde{X}_i^{(g)}(f_D) = X_i^{(g,\text{cal})}(f_D) - \hat{\alpha}_g\,\bar{X}_i^{\text{air,cal}}(f_D)\, e^{+j 2\pi f_R \Delta\hat{t}_0^{(g)}},$$
   基线取 $\hat{\alpha}_g \equiv 1$（纯模板减除），并对照检验单一全局实标量因子 $\hat{\alpha}_g = \frac{\operatorname{Re}\langle X^{(g,\text{cal})}, \bar{X}^{\text{air,cal}} e^{+j 2\pi f_R \Delta\hat{t}_0} \rangle}{\|\bar{X}^{\text{air,cal}}\|^2}$（仅当目标回波时延与直达波分离充分时安全）。

#### 改进候选（`M0-DW-Subspace`：多组空场子空间 / 时窗约束直射波抑制）
- **可证伪假设**：若不同采集之间存在微小环境温漂或发射功率波动（或跨行板微秒/皮秒级同步偏移），用 10 组对齐空场构造秩-$K_{\text{air}}$ 主成分子空间（$K_{\text{air}} \in \{1,2\}$）并**仅在直射波主到达时间窗 $[0, \tau_{\text{win}}]$（如 $\tau_i^{\text{dir}} \pm 0.5\text{ ns}$）内拟合投影系数**，既能吸收空场微扰，又避免过度拟合消掉近距离目标回波（如 $42\text{ cm}$ 墙体，超前直达波仅 $\approx 2.6\text{ ns}$）。
- **门控核验指标**：必须在最近目标校准样例（$42\text{ cm}$ 墙体 / $48\text{ cm}$ 金属板）上同时报告**直射波残余抑制比（dB）**与**目标回波峰值保留率（relative to 基准减除）**，禁止只刷高抑制比而吞掉目标回波。

---

### 5.3 问题 1.3：金属板与墙体测距

#### 经典基线（`M0-Rng-Base`：匹配滤波 + 镜面几何相干延迟叠加 1D 剖面）
1. **参考直射波零点锚定**：对每组 $g$，通过已对齐的空场参考模板（或目标测量中直达波峰与 $S(f_D)$ 的匹配相关）确定该组的有效异步时间零点 $\hat{t}_0^{(g)}$：
   $$\hat{t}_0^{(g)} = \arg\max_{t_0 \in [0, T_p)} \left| \sum_{i \in \mathcal{I}_{\text{rx}}} w_i^{\text{dw}} \sum_{f_D \in \mathcal{B}} \big(\bar{X}_i^{\text{air,cal}}(f_D) e^{+j 2\pi f_R \Delta\hat{t}_0^{(g)}}\big) \, S^*(f_D)\, e^{-j 2\pi f_R (\tau_i^{\text{dir}} + t_0)} \right|.$$
   该公式给出物理绝对零点（消除了设备相对时延与异步采集偏移）。
2. **多通道相干延迟叠加（Coherent Delay-and-Sum, DAS）**：
   对于候选垂直距离 $d \in [d_{\min}, d_{\max}]$（如 $[0.15, 2.00]\text{ m}$，步长 $1\text{ mm}$ 精搜），第 $i$ 路理论目标回波到达时间为 $\tau_i^{\text{tgt}}(d) + \hat{t}_0^{(g)}$。构造二维对照剖面函数：
   - **非相干包络叠加（对照基线 A）**：先对每路抑制后信号做带内匹配滤波并取解析包络 $|z_i^{(g)}(\tau)|$，在 $\tau = \tau_i^{\text{tgt}}(d) + \hat{t}_0^{(g)}$ 处插值求和：
     $$P_{\text{env}}^{(g)}(d) = \sum_{i \in \mathcal{I}_{\text{rx}}} w_i\, \big|z_i^{(g)}\big(\tau_i^{\text{tgt}}(d) + \hat{t}_0^{(g)}\big)\big|.$$
   - **相干匹配叠加（完整利用校准相位与射频镜像基线 B）**：
     $$P_{\text{coh}}^{(g)}(d) = \left| \sum_{i \in \mathcal{I}_{\text{rx}}} w_i\, R_i^{\text{tgt}}(d)\, \sum_{f_D \in \mathcal{B}} \tilde{X}_i^{(g)}(f_D)\, S^*(f_D)\, e^{-j 2\pi f_R (\tau_i^{\text{tgt}}(d) + \hat{t}_0^{(g)})} \right|.$$
3. **峰值提取与墙体多次回波甄别**：
   $$\hat{d}_g = \arg\max_{d \in [d_{\min}, d_{\max}]} P^{(g)}(d).$$
   **物理注记（墙体前表面 vs 内部/后表面回波）**：金属板为强导体，仅存在前表面一次主反射；墙体为介质体，电磁波部分穿透后可能产生后界面多次弱回波（位于更大 $d$ 处）。故在墙体测距中取**超过噪声门限且位于前向主包络的首个显著主峰**（并在先导试验中核对是否存在第二界面峰干扰）。

#### 改进候选（`M0-Rng-WLS`：宽带鲁棒加权非线性最小二乘）
- **可证伪假设**：实际阵列中，靠近发射天线近旁通道可能受更强的残余直达波泄露，而远离阵元存在幅度衰减和较低信噪比。若在初值 $\hat{d}_g^{(0)}$ 附近，使用有界鲁棒非线性最小二乘（`scipy.optimize.least_squares`，显式拆分为实部与虚部残差，`loss='huber'` 或 `'soft_l1'`），联合估计 $(d_g, \Gamma_g)$（将有效复反射率 $\Gamma_g \in \mathbb{C}$ 线性投影消元或作为变量），并按通道信噪比加权，有望进一步压低测距误差与异常通道敏感性。

---

## 6. 分层 10/10 校准与检验拆分方案（待统筹与验证方确认冻结）

按照 `coordination/A_Q1_PLAN.md` 要求，**检验组真实距离仅用于最终独立评价，绝对不得参与通道校准、正则化系数选择或任何超参数调优**。对墙体 20 组（`42 cm`–`121 cm`）与金属板 20 组（`48 cm`–`99 cm`）分别按真值距离升序排列后取奇偶交替分层抽样（10 组校准 / 10 组留出检验），保证两侧覆盖相同距离跨度：

| 目标类型 | 用途 | 组数 | 建议目录清单（按升序奇偶分层） | 距离覆盖（cm） |
|---|---|---|---|---|
| 空场数据 | 校准/直射波模板 | 10 | `data1`–`data10`（全量用于模板与空场自检） | — |
| 墙体数据 | 校准集 $\mathcal{G}_{\text{cal}}^{\text{wall}}$ | 10 | `data1-42cm`, `data16-46cm`, `data13-56cm`, `data4-62cm`, `data2-71cm`, `data11-76cm`, `data8-78cm`, `data10-82cm`, `data19-93cm`, `data7-106cm` | 42 – 106 |
| 墙体数据 | 检验集 $\mathcal{G}_{\text{test}}^{\text{wall}}$ | 10 | `data5-44cm`, `data14-48cm`, `data15-57cm`, `data12-65cm`, `data20-73cm`, `data3-77cm`, `data17-81cm`, `data9-91cm`, `data18-105cm`, `data6-121cm` | 44 – 121 |
| 金属板数据 | 校准集 $\mathcal{G}_{\text{cal}}^{\text{metal}}$ | 10 | `data2-48cm`, `data13-52cm`, `data3-54cm`, `data16-59cm`, `data11-62cm`, `data20-68cm`, `data10-70cm`, `data19-74cm`, `data8-83cm`, `data7-91cm` | 48 – 91 |
| 金属板数据 | 检验集 $\mathcal{G}_{\text{test}}^{\text{metal}}$ | 10 | `data14-48cm`, `data15-53cm`, `data12-55cm`, `data5-60cm`, `data17-65cm`, `data1-69cm`, `data18-70cm`, `data9-76cm`, `data4-87cm`, `data6-99cm` | 48 – 99 |

---

## 7. 输入输出接口与验收指标契约（供求解与验证方对接）

### 7.1 输入契约（由 `data/a-q1-reader` 提供）
- `signals`: `float64` 数组，形状 `(64, Np)`（单包或经一致性检验后的多包平均周期波形，单位：ADC 量化值），以及逐包原始数组 `(P, 64, 4, Np)` 供包间漂移检查。
- `rx_mask`: `bool` 数组，形状 `(64,)`，`rx_mask[27] == False`，其余 63 项为 `True`。
- `tx_idx`: `int = 27`；`ref_idx`: `int = 28`。
- `positions_m`: `float64` 数组，形状 `(64, 3)`，列为 $(x, y, z)$，单位 $\text{m}$（第 2 节坐标公式）。
- `meta`: 组别标签、数据来源路径、同步 `sync_packet_cnt` 交集、期段相关系数、极值溢出/饱和告警标记。

### 7.2 输出契约（求解器交付物）
1. **问题 1.1 校准参数表**（CSV/NPZ）：
   - `channel_idx` ($0\dots 63$, 仅 `rx_mask`), `row` ($1\dots 8$), `col_in_row` ($1\dots 8$), `grid_col` ($1\dots 16$)
   - `delta_tau_s` ($\text{s}$, 可同步输出 $\text{ns}$)
   - `gain_mag_band`（$f_D \in [0.3, 1.7]\text{ GHz}$ 频谱数组及带内均值，无量纲）
   - `residual_phase_rad_band`（带内剩余相位 $\psi_i(f_D)$，单位 $\text{rad}$）
   - 典型通道（如近邻通道、远端边缘通道、畸变最大通道）校准前后时域波形与幅度/相位频谱对比数据。
2. **问题 1.2 直射波抑制指标**：
   - 空场自留交叉抑制比（Leave-one-air-out suppression ratio, dB）
   - 校准集目标信号直射波时间窗残余功率降幅（dB）与目标回波峰保持度。
3. **问题 1.3 测距结果表**：
   - 逐组输出：`group_id`, `split` (`cal`/`test`), `target_type` (`wall`/`metal`), `d_true_cm`（仅评估时对照）, `d_est_cm`, `abs_err_cm`, `rel_err_pct`, `peak_to_sidelobe_db`
   - 汇总指标（分别按 `wall` / `metal` 与 `cal` / `test` 报告）：MAE ($\text{cm}$)、RMSE ($\text{cm}$)、MaxAE ($\text{cm}$)、中位绝对误差 ($\text{cm}$)。

---

## 8. 独立可手算及代码可复算小算例（2 接收通道解析验证）

本算例仅采用几何公式与解析合成信号（**不依赖生产估计器**），用于验证：**传播几何、第二奈奎斯特区射频镜像相位符号、设备校准参量可分离性、异步平移抵消及平面测距反演**。

### 8.1 算例设定
取 $c = 2.99792458\times 10^8\text{ m/s}$，$f_s = 4.0\times 10^9\text{ Hz}$，$T_s = 0.25\text{ ns}$，$N_p = 4000$，数字扫频参数同第 1.2 节。
- **发射通道 TX**：$(r=4, k=4)$，$\mathbf{p}_{\text{tx}} = (0, 0, 0.545)\text{ m}$。
- **参考通道 RX1**：$(r=4, k=5)$，$\mathbf{p}_1 = (-0.07, 0, 0.545)\text{ m}$，设设备响应完美 $H_1(f_D) \equiv 1$（$\Delta\tau_1 = 0, G_1 = 1, \psi_1 = 0$）。
- **待校准通道 RX2**：$(r=2, k=5)$，$\mathbf{p}_2 = (-0.07, 0, 0.685)\text{ m}$，植入真实设备偏差：
  $$\Delta\tau_2 = +0.500000\text{ ns}\ (= +2.0\,T_s), \quad G_2(f_D) \equiv 1.250000, \quad \psi_2(f_D) \equiv +0.300000\text{ rad},$$
  即 $H_2(f_D) = 1.25\, e^{-j 2\pi f_D (0.5\times 10^{-9}) + j 0.30}$。
- **目标真实垂直距离**：$d_{\text{true}} = 0.600000\text{ m}$ ($60.0\text{ cm}$)，有效反射系数 $\Gamma = -0.35$（金属板反向衰减）。
- **异步采样启动偏移**：空场采集 $t_0^{\text{air}} = 120.25\,T_s$（含亚采样小数）；目标采集 $t_0^{\text{tgt}} = 250.40\,T_s$（两组相对偏移 $\Delta t_0 = t_0^{\text{tgt}} - t_0^{\text{air}} = +130.15\,T_s$）。

### 8.2 手算预期结果（已独立数值验证至小数点后 6 位）
1. **直射波路径与传播时延**：
   - $R_1^{\text{dir}} = 0.070000\text{ m}$，$\tau_1^{\text{dir}} = 0.233495\text{ ns}\ (0.933979\,T_s)$。
   - $R_2^{\text{dir}} = \sqrt{0.07^2 + 0.14^2} = 0.156525\text{ m}$，$\tau_2^{\text{dir}} = 0.522110\text{ ns}\ (2.088442\,T_s)$。
2. **镜面反射路径与传播时延**（$2 d_{\text{true}} = 1.20\text{ m}$）：
   - $R_1^{\text{tgt}} = \sqrt{0.07^2 + 1.20^2} = 1.202040\text{ m}$，$\tau_1^{\text{tgt}} = 4.009574\text{ ns}\ (16.038295\,T_s)$，相对直射波净滞后 $\Delta\tau_1^{\text{prop}} = 3.776079\text{ ns}\ (15.104315\,T_s)$。
   - $R_2^{\text{tgt}} = \sqrt{0.156525^2 + 1.20^2} = 1.210165\text{ m}$，$\tau_2^{\text{tgt}} = 4.036677\text{ ns}\ (16.146707\,T_s)$，相对直射波净滞后 $\Delta\tau_2^{\text{prop}} = 3.514566\text{ ns}\ (14.058266\,T_s)$。
3. **无噪声带内恢复闭环预期**：
   - 经几何路径比 $(R_2^{\text{dir}}/R_1^{\text{dir}})$ 与射频传播相位补偿 $e^{-j 2\pi (f_s - f_D)(\tau_2^{\text{dir}} - \tau_1^{\text{dir}})}$ 后，空场比值频谱线性回归斜率严格还原：
     $$\Delta\hat{\tau}_2 = 0.500000\text{ ns}, \quad \hat{G}_2 = 1.250000, \quad \hat{\psi}_2 = 0.300000\text{ rad}.$$
   - 利用射频镜像对齐算子 $e^{+j 2\pi (f_s - f_D)\Delta t_0}$ 对齐空场至目标组，求得 $\Delta\hat{t}_0 = 130.1500\,T_s$，相减后直达波残余为零（若错用数字平移 $e^{-j 2\pi f_D \Delta t_0}$ 则因缺少 $2\pi f_s (0.15 T_s) = 0.3\pi\text{ rad}$ 载波相移导致明显直达波泄漏）。
   - 锚定 $\hat{t}_0^{\text{tgt}} = 250.4000\,T_s$ 后执行双通道相干 DAS 搜索（步长 $0.1\text{ mm}$），峰值精准收敛至 $\hat{d} = 0.600000\text{ m}$（误差 $0.0000\text{ cm}$）。

---

## 9. 已知局限与后续推进前提

1. **天线近场互耦与射频通道色散**：空场中近邻发射天线的接收单元受阵面耦合影响较大，$E_i^{\text{dir}}(f_D)$ 偏离 $1/R_i^{\text{dir}}$ 的程度需要在先导试验（`A-Q1-E0`）中通过对比 `M0-Cal-Base` 与 `M0-Cal-Joint` 量化验证。
2. **行板间异步抖动核查**：初步侦察中曾观测到个别组内单个行板数据包存在微弱载波相移；需待 `data/a-q1-reader` 完成全量 8 行包间一致性统计后，决定是否激活行板级微移参数 $\delta t_{g,r}$。
3. **墙体多界面反射**：墙体前表面与后界面之间存在介质传播衰减与延时，测距模型需在先导试验中验证“首个显著前向主峰”在远距离/弱反射工况下的稳定性。
