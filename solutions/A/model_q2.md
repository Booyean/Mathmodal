# A 题第二问数学方案（`M2`：远距离回波增益补偿与墙体二维剖面成像）

- **任务编号**：`model/a-q2-spec`（问题 2 数学规范）
- **主责**：`antigravity02`（建模与论文）
- **输入基线**：`main` = `c4378992c4c7249ab0818710a360ff3bbe737f85`
- **前置依据**：
  - 赛题 PDF 第 2、3–5、7–8 页（含图 1 阵列、图 5 墙体实景与 2D 投影）；
  - 已批复数学方案 [solutions/A/model_q1.md](model_q1.md)（`A-Q1-M0`，`098e17d`）；
  - 已批复先导登记 [experiments/A/A-Q1-E0/PLAN.md](../../experiments/A/A-Q1-E0/PLAN.md)（`7f9ad92`）；
  - 数据侦察清单 `recon/manifests/a_group_manifest.csv` 与 `recon/reports/data_recon_report.md`（仅目录与包数核对，未读取真实成像 `.dat` 波形）。
- **状态声明**：本文件为问题 2 数学模型、输入输出契约、适用边界与合成小算例核验规范；**当前未实现生产成像求解器、未读取或运行 `附件3-成像数据/墙体` 实测 `.dat` 试验，须待统筹审阅批复后方可在后续执行分支实施。**

---

## 1. 观测几何、单行阵列选定与数据契约继承

### 1.1 平移轨迹、组数核对与局部/全局坐标统一
依据赛题第 7 页与 `a_group_manifest.csv`：
- **测量组结构**：目录 `附件/附件3-成像数据/墙体` 共含 **$J = 33$** 组完整 8 文件组（按文件名采集时间升序排列 `2026-11-12-21-29-57_16000` 至 `21-39-38_16000`；其中第 3 组 `21-30-33_16000` 存在行间包数差异 `3,4`，按 `D0`/`D1` 共同 `sync` 交集规则对齐取 `P_common = 3`，无 0 字节文件）。
- **局部与全局三维坐标**：继承 `A-Q1-M0`（`098e17d`）地面 $z = 0$、阵面垂直地面且向第 1 列移动前端（$+x$）平移的坐标系。第 $r\in\{1..8\}$ 行第 $k\in\{1..8\}$ 副天线（展平索引 $i = 8(r-1)+(k-1)$）局部固定坐标为：
  $$x_i^{\text{loc}} = \big(8 - c_{\text{grid}}(r,k)\big)\cdot 0.035\text{ m}, \qquad z_i^{\text{loc}} = \big(75.5 - 7(r - 1)\big)\times 10^{-2}\text{ m},$$
  其中 $c_{\text{grid}}(r,k) = 2k-1$（$r$ 奇）或 $2k$（$r$ 偶），$i_{\text{tx}} = 27$（$r=4,k=4$），$i_{\text{ref}} = 28$（$r=4,k=5$）。
  对第 $j \in \{1, 2, \dots, 33\}$ 组测量，阵列整体沿 $+x$ 步进 $5\text{ cm}$，发射天线投影坐标 $x_j = -0.20 + 0.05(j - 1)\text{ m}$（覆盖 $[-0.20, +1.40]\text{ m}$），从而全阵列全局三维坐标为：
  $$\mathbf{p}_{j,\text{tx}} = (x_j,\ 0,\ z_4^{\text{loc}}), \qquad \mathbf{p}_{j,i} = (x_j + x_i^{\text{loc}},\ 0,\ z_i^{\text{loc}}).$$
- **二维成像域（$xOy$ 平行剖面）**：
  $$x \in [-0.20,\ 1.40]\text{ m}\ ([-20, 140]\text{ cm}), \qquad y \in [0,\ 2.50]\text{ m}\ ([0, 250]\text{ cm}).$$
  在此域内，像素 $\mathbf{r} = (x, y, z_{\text{slice}})$ 与第 $j$ 组、第 $i$ 路天线的自由空间等效双程传播距离与时延为：
  $$R_{j,i}(\mathbf{r}) = \|\mathbf{p}_{j,\text{tx}} - \mathbf{r}\|_2 + \|\mathbf{r} - \mathbf{p}_{j,i}\|_2, \qquad \tau_{j,i}(\mathbf{r}) = \frac{R_{j,i}(\mathbf{r})}{c_0}, \quad c_0 = 299792458\text{ m/s}.$$
  区域最远角落（如 $(-0.20, 0)$ 到 $(1.40, 2.50)$）最大双程时延 $< 20\text{ ns} \ll T_p = 1000\text{ ns}$，无周期距离模糊。

### 1.2 单行阵元选择与跨行 3D 几何修正边界
问题 2.2 要求“任选阵列中的一行建立二维成像模型”。规范如下：
1. **主选用行（$r = 4$，第 4 行，$z_{\text{slice}} = z_4^{\text{loc}} = 0.545\text{ m}$）**：
   - 包含第 $4$ 行内除发射天线 $i_{\text{tx}}=27$ 之外全部 **$7$ 路有效接收通道** $\mathcal{I}_{4} = \{24, 25, 26, 28, 29, 30, 31\}$（$x_i^{\text{loc}} \in \{-0.28, -0.21, -0.14, -0.07, +0.07, +0.14, +0.21\}\text{ m}$），且直接包含参考通道 $i_{\text{ref}} = 28$；
   - 因发射天线亦位于 $z_4^{\text{loc}} = 0.545\text{ m}$，令剖面高度 $z_{\text{slice}} = z_4^{\text{loc}}$ 时**收发与成像面严格共面（$\Delta z = 0$）**，无垂直视差。
2. **对照校验行（$r = 3$ 或 $r = 5$，$8$ 路满接收）**：
   - 选用非发射行 $r \neq 4$ 作一致性敏感性验证时，因 $\mathbf{p}_{j,\text{tx}}$ 仍在 $z_4^{\text{loc}}$ 而 $\mathbf{p}_{j,i}$ 在 $z_r^{\text{loc}} \neq z_4^{\text{loc}}$，式 $R_{j,i}(\mathbf{r})$ 必须代入精确三维 $z$ 坐标（不能退化为二维 $\Delta z = 0$ 计算），推荐取中平面或 RX 所在高度 $z_{\text{slice}} = z_r^{\text{loc}}$。

### 1.3 继承 Q1 预处理与信号链输入（不重复建模）
对每一成像组 $j \in \{1,\dots,33\}$，严格复用已验收的 `D0/D1-2` 折迭输出及已批准 `A-Q1-M0` / `A-Q1-E0` 冻结参数：
1. 由全 63 路或选定组应用冻结校准逆算子 $\hat{H}_i^{\text{rel}}(f_D)$，得 $X_{j,i}^{\text{cal}}(f_D)$；
2. 采用纯空场对齐减除（`M0-DW-Base`，$\alpha_j \equiv 1.0$）得直射波抑制后带内频谱 $\tilde{X}_{j,i}(f_D)$ 与显式有效色散模板 $\hat{S}_{\text{eff}}^{(j)}(f_D)$；
   - **前提假设（跨批次通道稳定性）**：要求成像数据采集时硬件链路相对传递函数 $\hat{H}_i^{\text{rel}}$ 与空场基线一致；若现场发生不可忽略漂移，需通过空窗/直射波对齐残差监测（$\text{Supp}_{\text{dw-win}}^{(j)}$ 门控）预警并转入人工复核。
3. 定义与 `A-Q1-E0` 完全一致的单位模板归一化**循环距离压缩响应**：
   $$z_{\text{MF},j,i}(\tau) = \frac{1}{\|\hat{S}_{\text{eff}}^{(j)}\|_{\mathcal{B}}} \sum_{f_D \in \mathcal{B}} \tilde{X}_{j,i}(f_D)\, \big(\hat{S}_{\text{eff}}^{(j)}(f_D)\big)^* \, e^{-j 2\pi f_R \tau}, \qquad f_R = f_s - f_D,$$
   其中 $\tau = 0$ 对应相对有效发射原点的零传播时延，$\tau \in [0, T_p)$ 满足 $T_p = 1000\text{ ns}$ 循环边界。

---

## 2. 问题 2.1：物理驱动的有界远距离回波增益模型（`M2-Gain-BSEC`）

### 2.1 问题本质与衰减来源建模
设前墙 A 厚度 $d_A = 10.5\text{ cm}$、后墙 B 厚度 $d_B = 35\text{ cm}$。后墙 B（$y \approx 200\text{ cm}$）回波相对前墙 A（$y \approx 37\text{–}56\text{ cm}$）大幅衰减的物理原因包括两项乘性因子：
1. **双程几何扩散衰减**：理想平面镜面反射回波幅值按 $\propto 1 / R_{j,i}$ 衰减（点散射或粗糙面散射按 $\propto 1/(r_{\text{tx}} r_{\text{rx}}) \sim 1/R^2$ 衰减）；仅由前墙到后墙的自由空间路径比即可带来 $13\text{–}26\text{ dB}$ 能量落差。
2. **前墙穿透与介质损耗**：穿过倾斜前墙 A 照射后墙 B 的路径，经历前/后界面双程菲涅耳透射损失及厚度 $d_A$ 砖墙内的指数电磁吸收 $\exp(-2\alpha_{\text{wall}} L_A)$。

### 2.2 增益函数设计：几何扩散补偿 + 饱和指数衰减补偿（BSEC）
同时兼顾“按回波时延”或“按等价双程成像距离 $y_{\text{eq}}(\tau) = c_0 \tau / 2$”两种表达，定义统一光滑**有界双分量增益函数** $W_{\text{comp}}(\tau)$（直接作用于 $\tau \in [0, 30\text{ ns})$ 成像时延窗内，且严格限制最大值以防晚时噪声爆炸）：
$$W_{\text{comp}}(\tau; \beta, \alpha_{\text{gain}}) = \left(\frac{\tau_{\text{clip}}(\tau)}{\tau_0}\right)^{\beta} \cdot \exp\!\Big(\alpha_{\text{gain}}\, \big[\tau_{\text{clip}}(\tau) - \tau_0\big]_+\Big),$$
$$\tau_{\text{clip}}(\tau) = \min\!\big(\max(\tau, \tau_0),\ \tau_{\text{sat}}\big), \qquad [u]_+ = \max(u, 0).$$

**各参数物理含义与固定边界**：
- **起点保护时延 $\tau_0 = 2 y_0 / c_0$**：基线取 $y_0 = 0.25\text{ m}$（$\tau_0 \approx 1.668\text{ ns}$），位于主要目标搜索起始区且避开最近直射波残余区，保证 $\tau \le \tau_0$ 内增益恒为 $1.0$（不放大残余直射波泄漏）。
- **饱和截断时延 $\tau_{\text{sat}} = 2 y_{\text{sat}} / c_0$**：取 $y_{\text{sat}} = 2.60\text{ m}$（$\tau_{\text{sat}} \approx 17.35\text{ ns}$，略高于成像边界 $y_{\max}=2.50\text{ m}$ 的最大双程斜距对应延迟）；对于 $\tau > \tau_{\text{sat}}$（包含背景代理窗 $\mathcal{W}_{\text{bg}}=[50, 950]\text{ ns}$），增益锁定为常上限 $G_{\text{cap}} = W_{\text{comp}}(\tau_{\text{sat}})$，不随 $\tau$ 发散。
- **几何扩散幂指数 $\beta \in \{0.0, 1.0, 1.5\}$**：$\beta = 1.0$ 严格对应平面镜面波 $1/R$ 幅度衰减的逆补偿（$y_{\text{eq}}$ 从 $0.45\text{ m}$ 到 $2.00\text{ m}$ 提供约 $+13\text{ dB}$ 能量补偿）；$\beta = 0.0$ 与 $1.5$ 用作模型对比与灵敏度校验。
- **介质/超额衰减补偿率 $\alpha_{\text{gain}} \ge 0$（单位 $\text{ns}^{-1}$，等价距离衰减系数 $\tilde{\alpha}_y = \frac{c_0}{2}\alpha_{\text{gain}}\ \text{Np/m}$ 或 $8.686\,\tilde{\alpha}_y\ \text{dB/m}$）**：
  - 候选小网格：$\alpha_{\text{gain}} \in \{0.0, 0.04, 0.08, 0.12, 0.16, 0.20\}\text{ ns}^{-1}$（在 $\tau_0 = 1.67\text{ ns}$ 至 $\tau_B \approx 13.34\text{ ns}$ 间提供 $0\text{ dB}$ 至 $+20.3\text{ dB}$ 额外幅度增益），硬约束总最大幅度增益上限 $G_{\text{cap}} \le 20.0$（$26\text{ dB}$ 幅度 / $52\text{ dB}$ 能量），禁止无上限放大噪声。

### 2.3 替代方案对比与无目标真值选参准则
- **为什么不采用无界指数 AGC（如传统 SEC）或逐时刻瞬时 AGC？**
  - 瞬时滑窗 AGC 会拉平前/后墙与空白区的绝对幅度差异，破坏成像散射强度可比性且使纯噪声段与目标段等幅；
  - 无界指数 SEC 在远端（尤其空白区域或高延时杂波处）会引发噪声呈指数级抬升而产生虚警条带。
- **无目标坐标先验的参数选定原则（数据驱动、非真值中心化）**：
  固定默认对照 $\beta = 1.0$ 后，在实测探索中评估指标随 $\alpha_{\text{gain}}$ 的权衡轨迹：
  1. **近/远动态均衡改善**：分别记近场区 $\mathcal{Y}_{\text{near}} = [0.25, 1.00]\text{ m}$ 主峰与远场区 $\mathcal{Y}_{\text{far}} = [1.20, 2.40]\text{ m}$ 主峰（注意区间宽达 $1.2\text{ m}$，不中心锁定到 $200\text{ cm}$），要求增益后远/近主峰比 $\Delta_{\text{far/near}}$ 提升并进入 $[-6, +6]\text{ dB}$ 可辨识区间；
  2. **背景杂波压制门限（对比度增益比）**：设整幅图像中位背景基线为 $I_{\text{med}} = \operatorname{median}_{(x,y)\in\Omega} I_{\text{2D}}(x,y)$，记远场信噪代理比 $C_{\text{far/med}} = 20\log_{10}\big(\max_{y\in\mathcal{Y}_{\text{far}}} \sqrt{I_{\text{2D}}} \big/ \sqrt{I_{\text{med}}}\big)$（若用幅度图则直接比）。若继续增大 $\alpha_{\text{gain}}$ 导致 $C_{\text{far/med}}$ 较其峰值下降 $> 1.5\text{ dB}$（即开始过度放大远场噪声抬高全图中位噪底），则停止增大并取折中拐点。

---

## 3. 问题 2.2：二维剖面聚焦成像与增益效果评价模型

### 3.1 相干孔径后向投影成像（`M2-Img-CohBPA`）与包络对照（`M2-Img-EnvBPA`）
在网格 $x \in [-0.20, 1.40]\text{ m}$、$y \in [0, 2.50]\text{ m}$（推荐步长 $\Delta x = \Delta y = 0.01\text{ m}$，细化可取 $0.005\text{ m}$）上，使用单行有效接收集 $\mathcal{I}_r$（主模型 $r=4$ 共 7 路，共 33 个移动站位 $\Rightarrow$ 至多 $33 \times 7 = 231$ 条收发通道对）：

1. **角度孔径权重与防伪影截断**：
   计算点 $\mathbf{r}=(x,y,z_{\text{slice}})$ 相对测点 $j$ 发射阵元方位角 $\theta_j(x,y) = \arctan2(|x - x_j|, y)$。定义平滑上升余弦截断角窗（最大半视角 $\theta_{\max} = 45^\circ$，过渡带 $35^\circ\text{–}45^\circ$）：
   $$w_{\text{ap}}(j; x, y) = \begin{cases} 1, & |\theta_j| \le 35^\circ, \\ \frac{1}{2}\big[1 + \cos\!\big(\pi\frac{|\theta_j|-35^\circ}{10^\circ}\big)\big], & 35^\circ < |\theta_j| \le 45^\circ, \\ 0, & |\theta_j| > 45^\circ. \end{cases}$$
   设有效参与数 $N_{\text{ap}}(x,y) = \sum_{j=1}^{33}\sum_{i\in\mathcal{I}_r} w_{\text{ap}}(j;x,y)$（若 $N_{\text{ap}} = 0$ 则像素置 $0$）。
   *(注：中心射频 $f_c = 3.0\text{ GHz}$ 对应自由空间半波长 $\lambda_c/2 = 5.0\text{ cm}$，恰与沿 $x$ 平移步长 $\Delta x_{\text{scan}} = 5.0\text{ cm}$ 相等；结合 $B=1.4\text{ GHz}$ 宽带脉冲压缩与 $\le 45^\circ$ 孔径窗，可抑制合成孔径栅瓣。)*

2. **主成像模型：增益补偿相干聚焦能量分布 $I_{\text{2D}}^{\text{coh}}(x, y)$（`M2-Img-CohBPA`）**：
   $$U_{\text{coh}}(x, y) = \frac{1}{N_{\text{ap}}(x, y)} \sum_{j=1}^{33}\sum_{i\in\mathcal{I}_r} w_{\text{ap}}(j; x, y)\, W_{\text{comp}}\big(\tau_{j,i}(x, y)\big)\, z_{\text{MF},j,i}\big(\tau_{j,i}(x, y)\big),$$
   $$I_{\text{2D}}^{\text{coh}}(x, y) = \big|U_{\text{coh}}(x, y)\big|^2 \quad \text{（幅值图像取 } \sqrt{I_{\text{2D}}^{\text{coh}}(x,y)} = |U_{\text{coh}}(x,y)|\text{）}.$$
   - **第二奈奎斯特区插值红线（关键数值准则）**：因 $f_R = f_s - f_D \in [2.3, 3.7]\text{ GHz}$ 中心射频为 $3.0\text{ GHz} > f_s/2$，连续延时的复响应 $z_{\text{MF}}(\tau) = e^{-j2\pi f_s \tau} z_{\text{base}}(\tau)$ 在 $T_s = 0.25\text{ ns}$ 网格上相邻样点间载波相位跳变达 $270^\circ$，**严禁在 $T_s$ 原始延迟网格上直接对复数 $z_{\text{MF}}$ 做线性插值**（实测该错误会使合成倾斜前墙倾角重建退化至 $3.17^\circ$ 并产生 $2\text{ cm}$ 偏移）。实现必须采用等效恒等式：先通过频域补零高倍（如 $4\times$，$T_s'=0.0625\text{ ns}$）`ifft` 评估低频复基带包络 $z_{\text{base}}(\tau) = \sum_{f_D\in\mathcal{B}} \tilde{X}(f_D)\hat{S}_{\text{eff}}^*(f_D) e^{+j2\pi f_D\tau} / \|\hat{S}_{\text{eff}}\|$ 并线性插值，再解析乘回精准载波相移因子 $e^{-j2\pi f_s \tau}$（或直接采用频域精确复指数求和）。
   - **选型理由与替代对比**：相比直接对包络 $|z_{\text{MF}}|$ 叠加，复相干叠加利用第二奈奎斯特区精准射频相位（由 $\hat{S}_{\text{eff}}^{(j)}$ 对齐），横向空间分辨率由合成孔径长度决定并显著压低非相干噪声与散射旁瓣；但若实测中跨 33 组站位之间出现超越 Q1 模板校平能力的微小载波相位漂移，相干叠加可能出现部分相消，故强制并行计算**非相干包络均值剖面**作为鲁棒对照基准（`M2-Img-EnvBPA`）：
     $$I_{\text{2D}}^{\text{env}}(x, y) = \left(\frac{1}{N_{\text{ap}}(x, y)} \sum_{j=1}^{33}\sum_{i\in\mathcal{I}_r} w_{\text{ap}}(j; x, y)\, W_{\text{comp}}\big(\tau_{j,i}(x, y)\big)\, \big|z_{\text{MF},j,i}\big(\tau_{j,i}(x, y)\big)\big|\right)^2.$$
   - **未增益对照基线**：令 $W_{\text{comp}} \equiv 1$ 所得分布记为 $I_{\text{2D}}^{(0)}(x,y)$，直接用于 2.2 增益前后可辨识度定量比较。

### 3.2 墙体位置/走向提取与增益前后定量比较指标
1. **逐横坐标双墙边界追踪（不硬编码具体坐标）**：
   - 在每条纵切面 $x \in [-0.20, 1.40]\text{ m}$ 上，于近场与远场深度窗内检索局部主峰并结合 2D 连通域峰值脊线（或加权 RANSAC / 最小二乘直线拟合）提取前墙 A 与后墙 B 前表面轮廓 $y_A(x), y_B(x)$ 及其方位倾角 $\theta = \arctan(\mathrm{d}y/\mathrm{d}x)$。
   - **无前墙遮挡段 vs 穿墙遮挡段分区报告**：如实际场景中前墙为有限长度斜墙而局部 $x$ 区间无前墙遮挡，必须分别统计“未穿过前墙 A 的直射空气区间后墙位置”与“穿过前墙 A 后的表观后墙位置”，并在定量分析中计算两者深度错位 $\Delta y_{\text{app}}$。
2. **增益前后可辨识度定量评价指标（均采用功率比 $10\log_{10}$）**：
   - **后/前墙峰值均衡比**：$\Delta_{\text{B/A}} = 10\log_{10}\big(\max_{\mathbf{r}\in\Omega_B} I_{\text{2D}}(\mathbf{r}) \big/ \max_{\mathbf{r}\in\Omega_A} I_{\text{2D}}(\mathbf{r})\big)$；
   - **后墙-背景对比度（PBR）**：$\text{PBR}_B = 10\log_{10}\big(\max_{\mathbf{r}\in\Omega_B} I_{\text{2D}}(\mathbf{r}) \big/ \operatorname{median}_{\mathbf{r}\in\Omega} I_{\text{2D}}(\mathbf{r})\big)$；
   - **后墙-局部杂波峰旁瓣比（PSLR）**：$\text{PSLR}_B$ 定义为后墙主脊峰相对其 $\pm 2\Delta y_{\text{ml}}$（主瓣保护带）之外远场区域内最高假峰的功率比（$\text{dB}$）；
   - **后墙连续性覆盖率**：在扫描域 $x \in [-0.20, 1.40]\text{ m}$ 内，后墙 B 峰值超过全图背景中位数 $+10\text{ dB}$（且高于该列局部噪声基底 $+6\text{ dB}$）的横坐标占比（%）。

---

## 4. 关键物理边界与不可逾越声明（Applicability & Limitations）

1. **自由空间等效成像与介质折射率 $\varepsilon_r$ 耦合（关键不可识别边界）**：
   - 本基准模型使用均匀自由空间波速 $c_0$ 进行双向反演走时 $\tau_{j,i}(x,y)$ 映射，因而对后墙 B 中**穿过 $d_A=10.5\text{ cm}$ 前墙 A 路径段**得到的 $y_B^{\text{app}}(x)$ 为**视在成像深度**而非物理真实位置：电磁波在介电常数为 $\varepsilon_r > 1$、实际几何厚度 $d_A$ 的前墙中传播速度降至 $c_0/\sqrt{\varepsilon_r}$，导致后墙表观影像沿 $+y$ 向后错位约 $d_A(\sqrt{\varepsilon_r} - 1)$。
   - **严谨性要求**：题目未给定前墙砖石精确介电常数 $\varepsilon_r$，因此**不允许直接假定 $\varepsilon_r$ 真值并在基线中静默改写波速**；反之，若实测二维剖面中无前墙遮挡两侧呈现平直后墙 $y_B^{\text{air}}$ 而墙后区域出现固定视在后移 $\Delta y_{\text{app}} > 0$，可反推出**等效折射率估计量** $\hat{\varepsilon}_r \approx (1 + \Delta y_{\text{app}} / d_A)^2$ 作为可证伪物理诊断量，并严禁将视在后移误解为后墙本身物理弯曲。
2. **三维波束跨剖面导致的表观壁厚展宽**：
   - 依据题面第 7 页说明，单行天线的波束在垂直 $z$ 向具有较大张角，来自非共面高度 $z \neq z_{\text{slice}}$ 的强反射会在固定 $y$ 处拖尾至更长双程延时 $y_{\text{app}} = \sqrt{y^2 + (z - z_{\text{slice}})^2}$，导致二维成像墙体条带厚度偏宽；因此**不得**仅据二维剖面纵深带宽直接反读为真实物理厚度 $10.5\text{ cm}$ 或 $35\text{ cm}$，位置与走向以主前表面脊线拟合为准。
3. **跨组相位一致性退化边界**：
   - 若实测不同移动测点 $j=1\dots 33$ 间的残余载波偏移超越单周期折叠稳健区间，相干成像 $I_{\text{2D}}^{\text{coh}}$ 性能将劣于非相干包络成像 $I_{\text{2D}}^{\text{env}}$；因此在实施阶段必须并行输出两种剖面作为对比诊断依据。

---

## 5. 输入输出接口契约

- **输入**：
  - Q1 已冻结校准模板与参数：$\hat{H}_i^{\text{rel}}(f_D)$、空场参考聚合 $\bar{X}_i^{\text{air,cal}}(f_D)$、`rx_mask`、`positions_m`；
  - `附件3-成像数据/墙体` 经 `D0`/`D1-2` 预处理后的 33 组折迭信号 `signals_folded_33` 形状 `(33, 64, 4000)`、有效包日志及测点坐标 $x_j$；
  - 选定成像行 `row_id`（默认 `4`）与增益超参 $(\beta, \alpha_{\text{gain}}, y_0, y_{\text{sat}}, G_{\text{cap}})$。
- **输出**：
  - `gain_profile`: $W_{\text{comp}}(\tau)$ 曲线与上限饱和参数记录；
  - `image_before_gain_coh`, `image_after_gain_coh`, `image_after_gain_env`: 规则网格 $(x, y)$ 上的二维剖面矩阵；
  - `metrics_q2`: 增益前后 $\Delta_{\text{B/A}}$、$\text{PBR}_B$、$\text{PSLR}_B$、后墙连续性覆盖率及前/后墙脊线位置走向回归表。

---

## 6. 独立可复现合成闭环小算例（附 `solutions/A/verify_q2_spec.py`）

[verify_q2_spec.py](verify_q2_spec.py) 构造零真实 `.dat` 读取的纯合成双墙二维闭环例，独立核验：
1. **几何与信号规范**：构造精确 64 阵元阵列、$J = 33$ 组 $x_j = -0.20 + 0.05(j-1)\text{ m}$ 扫描站位及第 4 行 $7$ 路接收几何（含第 2 奈奎斯特区色散 $H_{\text{ref}}$ 与加窗 LFM）。
2. **植入双墙场景**：
   - **倾斜有限前墙 A**：前表面由 $(0.25, 0.37)\text{ m}$ 至 $(1.06, 0.56)\text{ m}$（离散面元点散射叠加，斜率角 $13.20^\circ$），设定高反射幅值；
   - **水平弱后墙 B**：位于 $y = 2.00\text{ m}$（$-0.20 \le x \le 1.40\text{ m}$），相对前墙施加以距离扩展叠加透过斜墙后的额外 `-18 dB` 衰减（共约 `-30 dB` 幅/能落差），并加入等效折射光程延后（若光线穿越前墙线段则增加可诊断视在延后 $\Delta y_{\text{app}} = 0.06\text{ m}$ 对比无折射基准，或纯几何基准），外加时域高斯白噪声。
3. **运行命令行与闭环实测表现**：
   ```powershell
   python solutions/A/verify_q2_spec.py
   ```
   - **未增益对照 $I_{\text{2D}}^{(0)}$**：$\Delta_{\text{B/A}} = -25.95\text{ dB}$，$\text{PBR}_B = 26.32\text{ dB}$，$y_B = 2.000\text{ m}$；
   - **有界增益相干成像 `M2-Gain-BSEC + M2-Img-CohBPA`**（$\beta=1.0, \alpha_{\text{gain}}=0.14\text{ ns}^{-1}, G_{\text{cap}}=20$）：$\Delta_{\text{B/A}}$ 提升至 $-6.99\text{ dB}$（净改善 $+18.96\text{ dB} \ge +10\text{ dB}$），后墙对比度提升至 $\text{PBR}_B = 35.85\text{ dB}$（高于非相干包络 `EnvBPA` 的 $18.04\text{ dB}$），前墙倾角拟合 $13.64^\circ$（相对植入 $13.20^\circ$ 误差 $0.44^\circ \le 1.5^\circ$），两端无墙段后墙深度精确还原为 $2.000\text{ m}$（$\le 2\text{ cm}$ 门槛），且 $\max W_{\text{comp}} \le 20.0$ 严格受限；
   - **过度增益反例**（$\beta=1.5, \alpha_{\text{gain}}=0.35\text{ ns}^{-1}$）：`PBR_B` 从 $35.85\text{ dB}$ 跌落至 $30.90\text{ dB}$，定量验证了过强指数补偿对远场背景噪底的抬升惩罚（约束判定非空转）。
