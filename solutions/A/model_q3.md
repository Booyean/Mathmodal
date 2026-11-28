# A 题第三问数学方案（`M3`：全阵列三维聚焦成像、金属目标定位与遮挡阴影诊断）

- **任务编号**：`model/a-q3-spec`（问题 3 数学规范）
- **主责**：`antigravity02`（建模与论文）
- **输入基线**：`main` = `b10264b0958b44dec527457635b410a999fb77f3`（并衔接未合并审阅中之 [PR #19](https://github.com/Booyean/Mathmodal/pull/19) `model/a-q2-spec` 修订版 `1fad17f05659f75f6d9cffc3775e03144c89301a`）
- **前置依据**：
  - 赛题 PDF 第 2、3–5、8–9 页（含图 1 阵列、图 6 墙体场景及图 7 金属柱和金属铲）；
  - 已批复数学方案 [solutions/A/model_q1.md](model_q1.md)（`A-Q1-M0`，`098e17d`）与先导登记 [experiments/A/A-Q1-E0/PLAN.md](../../experiments/A/A-Q1-E0/PLAN.md)（`7f9ad92`）；
  - 数据侦察清单 [a_group_manifest.csv](../../recon/manifests/a_group_manifest.csv) 与 [data_recon_report.md](../../recon/reports/data_recon_report.md)（仅核对目录、文件完整性及包数异常记录，未读取真实成像 `.dat` 波形）。
- **状态声明**：本文件为问题 3 数学模型、数据异常处置、输入输出契约、分辨/遮挡物理边界与纯合成小算例核验规范；**当前未实现生产三维成像求解器、未读取或运行 `附件3-成像数据` 实测 `.dat` 试验，须待统筹审阅批复后方可在后续执行分支实施。**

---

## 1. 三维观测几何、两类场景数据契约与异常隔离

### 1.1 全 63 路三维阵列孔径与扫查轨迹
继承 `A-Q1-M0`（`098e17d`）地面 $z = 0$、阵面垂直地面（$y=0$）且向第 1 列移动前端（$+x$）平移之全局右手直角坐标系。
- **阵元三维局部坐标**：第 $r\in\{1..8\}$ 行第 $k\in\{1..8\}$ 副天线（展平索引 $i = 8(r-1)+(k-1)\in\{0..63\}$）满足：
  $$x_i^{\text{loc}} = \big(8 - c_{\text{grid}}(r,k)\big)\cdot 0.035\text{ m}, \qquad z_i^{\text{loc}} = \big(75.5 - 7(r - 1)\big)\times 10^{-2}\text{ m},$$
  其中 $c_{\text{grid}}(r,k) = 2k-1$（$r$ 奇）或 $2k$（$r$ 偶），$i_{\text{tx}}=27$ 固定为发射端，全部 **$|\mathcal{I}_{\text{rx}}| = 63$** 路接收阵元局部覆盖：
  $$x_i^{\text{loc}} \in [-0.280,\ +0.245]\text{ m}\ (\text{宽 } 0.525\text{ m}), \qquad z_i^{\text{loc}} \in [0.265,\ 0.755]\text{ m}\ (\text{高 } 0.490\text{ m}).$$
- **两场景扫描站位与全局坐标**：对第 $j \in \{1,\dots,J\}$ 组有效测量，收发天线全局三维坐标为 $\mathbf{p}_{j,\text{tx}} = (x_j, 0, z_4^{\text{loc}})$（$z_4^{\text{loc}}=0.545\text{ m}$）、$\mathbf{p}_{j,i} = (x_j + x_i^{\text{loc}}, 0, z_i^{\text{loc}})$：
  1. **问题 3.1 墙体场景（`附件3-成像数据/墙体`）**：$J_{\text{wall}} = 33$ 组完整 8 文件组，按时间戳升序对应 $x_j = -0.20 + 0.05(j-1)\text{ m}$（$[-0.20, 1.40]\text{ m}$），总有效迹数 $33 \times 63 = 2079$；成像域：
     $$\Omega_{\text{3D}}^{\text{wall}} = [-0.20, 1.40]\text{ m} \times [0, 2.50]\text{ m} \times [0.20, 0.80]\text{ m}.$$
  2. **问题 3.2 金属目标场景（`附件3-成像数据/金属柱和金属铲`）**：$J_{\text{metal}} = 27$ 组有效 8 文件组，按时间戳升序对应 $x_j = 0.05(j-1)\text{ m}$（$[0, 1.30]\text{ m}$），总有效迹数 $27 \times 63 = 1701$；成像域：
     $$\Omega_{\text{3D}}^{\text{metal}} = [0.00, 1.30]\text{ m} \times [0, 2.50]\text{ m} \times [0.20, 0.80]\text{ m}.$$
- **空间体素 $\mathbf{r} = (x, y, z)$ 双程自由空间等效走时**：
  $$R_{j,i}(\mathbf{r}) = \|\mathbf{p}_{j,\text{tx}} - \mathbf{r}\|_2 + \|\mathbf{r} - \mathbf{p}_{j,i}\|_2, \qquad \tau_{j,i}(\mathbf{r}) = \frac{R_{j,i}(\mathbf{r})}{c_0}, \quad c_0 = 299792458\text{ m/s}.$$
  全域最大斜距双程延迟 $\tau_{\max} < 25\text{ ns} \ll T_p = 1000\text{ ns}$，无周期距离模糊。

### 1.2 实盘数据异常与 `D0/D1-2` 门控处置契约（严禁静默丢弃或篡改）
依据 `recon/reports/data_recon_report.md` 与 `a_group_manifest.csv`：
1. **0 字节孤儿文件**：`2026-11-12-22-50-31_16000_7.dat` 大小为 0 B 且无同前缀其他 7 行，**不构成第 28 组**，保留台账记录后严格排除于 27 组轨迹之外（$j=1\dots 27$ 仍严格一一对应前面 27 个时间戳组）。
2. **行间包数不一致**：墙体第 3 组（`21-30-33_16000`，包数 `3,4`）与金属第 8 组（`22-09-58_16000`，包数 `3,4`）均按 `D0` 共同 `sync_packet_cnt` 交集截取（$P_{\text{common}} = 3$）。
3. **末包孤立 `-32768` 采样异常点**：金属第 8 组 `_1.dat` 末包（`sync=250`）检出 46 个孤立 `-32768` 样点；进入 `D1-2` 门控后严格逐包按段内/包间门控与 F2 非有限值规则裁决，仅保留通过门控之包折叠输出 `signals_folded (64, 4000)`，严禁人为插值捏造包内波形。

---

## 2. 信号链路继承与三维聚焦成像模型

### 2.1 继承 Q1 校准/直达波抑制与 Q2 有界增益公式
1. **校准与压缩响应 $z_{\text{MF},j,i}(\tau)$**：与 Q1/Q2 保持同一接口：应用冻结 $\hat{H}_i^{\text{rel}}(f_D)$ 校准、固定 $\alpha_j \equiv 1.0$ 空场对齐减除（`M0-DW-Base`）及显式有效色散模板 $\hat{S}_{\text{eff}}^{(j)}(f_D)$，得到单位模板能量归一化循环匹配滤波响应 $z_{\text{MF},j,i}(\tau)$。
2. **两步硬封顶增益函数（直接对齐 Q2 `M2-Gain-BSEC`）**：
   $$W_{\text{raw}}(\tau; \beta, \alpha_{\text{gain}}) = \left(\frac{\tau_{\text{clip}}(\tau)}{\tau_0}\right)^{\beta} \cdot \exp\!\Big(10^9 \alpha_{\text{gain}}\,[\tau_{\text{clip}}(\tau) - \tau_0]_+\Big),$$
   $$W_{\text{comp}}(\tau; \beta, \alpha_{\text{gain}}, G_{\text{cap}}) = \min\!\big(G_{\text{cap}},\ W_{\text{raw}}(\tau; \beta, \alpha_{\text{gain}})\big), \quad \tau_{\text{clip}}(\tau)=\min(\max(\tau,\tau_0),\tau_{\text{sat}}),$$
   其中 $\tau_0 = 2(0.25)/c_0 \approx 1.668\text{ ns}$，$\tau_{\text{sat}} = 2(2.60)/c_0 \approx 17.345\text{ ns}$，$G_{\text{cap}} = 20.0$（幅值与平方能量功率比同为 $+26.02\text{ dB}$）；空间距离衰减指数换算 $\tilde{\alpha}_y = \frac{2\times 10^9}{c_0}\alpha_{\text{gain}}\ (\text{m}^{-1})$。
   - **Q3.1 墙体场景参数继承**：直接继承并交叉检验 Q2 经剖面对比锁定的 $(\beta, \alpha_{\text{gain}})$ 参数（因穿前墙探测后墙仍为关键物理场景）；
   - **Q3.2 金属目标场景模式**：金属目标在强直反射下主导近/中距离动态范围，默认采用**纯几何扩散补偿基线** $(\beta = 1.0, \alpha_{\text{gain}} = 0.0\text{ ns}^{-1})$ 对强金属一次回波定位（避免指数超额增益过度抬高金属后方多径或杂波假峰），同时保留启用 Q2 $(\beta, \alpha_{\text{gain}})$ 剖面用于检视被遮挡后墙衰减对比。

### 2.2 三维方向孔径权重（兼顾近场低高度照明与水平栅瓣抑制）
因阵列仅沿水平 $x$ 移动而垂直 $z$ 方向不移动，采用**水平/垂向解耦三维孔径加权**：
- 水平合成孔径方位角：$\theta_{x}(j; \mathbf{r}) = \arctan2\big(|x - x_j|,\ \max(y, 0.05)\big)$，保留 $\theta_{x,\text{flat}} = 35^\circ$、$\theta_{x,\text{cut}} = 45^\circ$ 上升余弦窗 $w_{x}(j;\mathbf{r})$；
- 单通道垂向仰角：$\theta_{z}(i; \mathbf{r}) = \arctan2\big(|z - z_i^{\text{loc}}|,\ \max(y, 0.05)\big)$，设宽视场垂向窗 $\theta_{z,\text{flat}} = 45^\circ$、$\theta_{z,\text{cut}} = 55^\circ$ 对应的上升余弦窗 $w_{z}(i;\mathbf{r})$（保证在 $y = 0.40\text{ m}$ 近场、低高度 $z = 0.20\text{ m}$ 处，$z_i^{\text{loc}}\in[0.265, 0.475]\text{ m}$ 的下排通道仰角 $\le 35^\circ < 45^\circ$，不因固定发射高度 $z_4=0.545\text{ m}$ 误截断低矮金属铲底部照明）。
- 联合三维孔径权与归一化总孔径数：
  $$w_{\text{ap},3\text{D}}(j,i; \mathbf{r}) = w_x(j;\mathbf{r})\, w_z(i;\mathbf{r}), \qquad N_{\text{ap},3\text{D}}(\mathbf{r}) = \sum_{j=1}^{J}\sum_{i\in\mathcal{I}_{\text{rx}}} w_{\text{ap},3\text{D}}(j,i; \mathbf{r}).$$

### 2.3 三维相干反向投影主模型（`M3-Img-CohBPA3D`）与包络对照（`M3-Img-EnvBPA3D`）
在体素网格 $\mathbf{r}=(x,y,z)$（推荐探索粗步长 $(2, 2, 2)\text{ cm}$，目标邻域局部细化至 $(1, 1, 1)\text{ cm}$）上定义：
$$U_{\text{3D}}(\mathbf{r}) = \frac{1}{N_{\text{ap},3\text{D}}(\mathbf{r})} \sum_{j=1}^{J}\sum_{i\in\mathcal{I}_{\text{rx}}} w_{\text{ap},3\text{D}}(j,i;\mathbf{r})\, W_{\text{comp}}\big(\tau_{j,i}(\mathbf{r})\big)\, z_{\text{MF},j,i}\big(\tau_{j,i}(\mathbf{r})\big),$$
$$I_{\text{3D}}^{\text{coh}}(\mathbf{r}) = \big|U_{\text{3D}}(\mathbf{r})\big|^2, \qquad I_{\text{3D}}^{\text{env}}(\mathbf{r}) = \left(\frac{1}{N_{\text{ap},3\text{D}}(\mathbf{r})} \sum_{j=1}^{J}\sum_{i\in\mathcal{I}_{\text{rx}}} w_{\text{ap},3\text{D}}(j,i;\mathbf{r})\, W_{\text{comp}}\big(\tau_{j,i}(\mathbf{r})\big)\, \big|z_{\text{MF},j,i}(\tau_{j,i}(\mathbf{r}))\big|\right)^2.$$
- **第二奈奎斯特区插值约束（继承 Q2 红线）**：严格使用 $4\times$ 过采样复基带插值再乘解析载波 $e^{-j2\pi f_s \tau_{j,i}(\mathbf{r})}$（或等价频域直接相移），禁止在 $T_s = 0.25\text{ ns}$ 原始网格直接线性插值 $z_{\text{MF}}$ 复数值。
- **工程计算预算保障**：63 路三维反投影可按固定 $z$ 层分片、利用多核或矢量查表批处理，在 CPU 单/可控线程下先算 $2\text{ cm}$ 粗网格（墙体约 $81\times 126\times 31\approx 3.16\times 10^5$ 体素）再做 ROI 局部细化，内存可控在 $< 2\text{ GiB}$。

---

## 3. 目标位置提取与金属后方遮挡阴影诊断模型

### 3.1 问题 3.1 墙体空间位置提取
1. 对各高度切片 $z \in [0.20, 0.80]\text{ m}$，提取近场前墙 A 主峰脊面 $\hat{y}_A(x,z)$ 及有效高度包络 $[z_{A,\min}, z_{A,\max}]$（检验前墙有限宽高轮廓），并与 Q2 主行 $z = z_4 = 0.545\text{ m}$ 剖面交叉对账（要求无折射空气段二维/三维 $y$ 向位置偏差 $\le 2\text{ cm}$）。
2. 提取后墙 B 前表面主脊面 $\hat{y}_B(x,z)$，分区汇报空气直射段与穿墙遮挡段的视在位置，分析全高范围 $z\in[0.20, 0.80]\text{ m}$ 内墙体一致性。

### 3.2 问题 3.2 金属柱与金属铲分离定位及遮挡阴影定量刻画
1. **基于三维局部极大值非极大抑制（3D-NMS）的双金属目标分离（不硬编码几何先验坐标）**：
   - 将空间搜索划分在金属前向区（去除最后墙体边带或联合检测最强局域紧凑峰值），对归一化能量 $I_{\text{3D}}(\mathbf{r})$ 沿水平脚印 $(x,y)$ 柱域施加非极大抑制（保护半径 $\Delta_{xy} = (0.14, 0.18)\text{ m}$，避免竖直贯高立柱因中心镜面主峰与上下端绕射边缘峰沿 $z$ 被拆分为多个伪目标），筛选超过全图背景中位数 $+12\text{ dB}$ 之独立强散射目标；
   - 对各检出目标在水平保护脚印内统计主峰位置 $(\hat{x}_p, \hat{y}_p, \hat{z}_p)$ 及 **$-10\text{ dB}$ 阈值区**（体素能量 $\ge 0.10\, P_{\text{peak}}$）的三维等值包围盒 $[\hat{x}_{\min}, \hat{x}_{\max}]\times[\hat{y}_{\min}, \hat{y}_{\max}]\times[\hat{z}_{\min}, \hat{z}_{\max}]$、垂向跨度 $\Delta\hat{z}_{10\text{dB}} = \hat{z}_{\max} - \hat{z}_{\min}$ 及能量加权质心 $(\hat{x}_c, \hat{y}_c, \hat{z}_c)$，依垂向跨度与主峰高度区分贯高型立柱（镜面中心靠近阵面发射高度且 $-10\text{ dB}$ 跨度含上下端绕射边界）与低矮局域金属铲。
2. **金属后方墙面阴影遮挡指标（ShadowRatio）**：
   依据第 8 页题注“金属目标会反射较多入射能量，因此金属目标后方的部分墙面可能在图像中难以辨认”，对每个检出金属目标包围盒 $[\hat{x}_{m,\min}, \hat{x}_{m,\max}]\times[\hat{z}_{m,\min}, \hat{z}_{m,\max}]$，考察其后方远区（$y > \hat{y}_m + 0.25\text{ m}$ 至后墙带）能量 $\bar{I}_{\text{shadow}}^{(m)}$ 相对同 $y$ 区间**无金属横向遮挡区域**墙面能量中位数 $\bar{I}_{\text{unocc}}$ 的功率衰减比：
   $$\text{ShadowRatio}_m = 10\log_{10}\!\left(\frac{\bar{I}_{\text{shadow}}^{(m)}}{\bar{I}_{\text{unocc}}}\right)\quad (\text{dB}).$$
   显著负值（如 $< -6\text{ dB}$）即从能量守恒与射线遮挡角度解释后方墙面隐没现象，避免将遮挡区误判为墙体几何空洞。

---

## 4. 三维分辨率极限与核心物理边界（Applicability & Limitations）

1. **横跨（$x$）与垂向（$z$）分辨率显著非对称边界**：
   - 距离向 $y$ 理论分辨率由带宽决定：$\Delta y_{\text{res}} = \frac{c_0}{2B} \approx 10.71\text{ cm}$；
   - 水平向 $x$ 靠移动合成孔径（$\pm 45^\circ$ 截断），$f_c=3.0\text{ GHz}$ 下 $\Delta x_{\text{res}} \approx \frac{\lambda_c}{4\sin 45^\circ} \approx 3.54\text{ cm}$；
   - **垂向 $z$ 无物理机械平移**，发射端始终固定在 $z_4 = 0.545\text{ m}$，仅接收端拥有 $L_z = 0.490\text{ m}$ 有限物理孔径（单程接收孔径决定 $\Delta z_{\text{res}}(y) \approx \frac{\lambda_c y}{L_z}$）：在 $y = 0.8\text{ m}$ 处约为 $16\text{ cm}$，在 $y = 2.0\text{ m}$ 后墙处展宽至 $\approx 41\text{ cm}$。因此三维模型对 $x, y$ 定位及紧凑金属质心 $z$ 区分（高立柱 vs 低矮金属铲）具较高辨识力，但**不可宣称在 $y=2\text{ m}$ 处具备与 $x$ 同等的厘米级 $z$ 向锐利边界**。
2. **多次散射与表面爬行波旁瓣**：高 RCS 金属柱/铲之间或金属与地面之间若存在多次往返散射，可能在该目标后方生成延迟虚像（$y_{\text{ghost}} > y_{\text{metal}}$），在阴影检测后需核查其是否符合单/双程物理可达几何，避免将其误识为独立实体或后墙局部凸起。
3. **跨组一致性与相干退化对冲**：并行保留 $I_{\text{3D}}^{\text{env}}$ 对照，检验 63 路全阵跨行板在 33/27 组连续扫描期间是否存在超出单周期折叠容限的相干退化。

---

## 5. 输入输出接口契约

- **输入**：
  - Q1 冻结校准参数与参考模板数据；
  - `附件3-成像数据/墙体`（`33` 组 `signals_folded` 形状 `(33, 64, 4000)`）或 `附件3-成像数据/金属柱和金属铲`（跳过 0 字节孤儿、对齐缺包/异常后 `27` 组 `signals_folded` 形状 `(27, 64, 4000)`）；
  - 三维体素网格边界 $(\Omega_{\text{3D}}, \Delta x, \Delta y, \Delta z)$ 与增益参数 $(\beta, \alpha_{\text{gain}}, G_{\text{cap}})$。
- **输出**：
  - `image_3d_coh`, `image_3d_env`: 三维聚焦能量网格（形状 $(N_z, N_y, N_x)$）及正交三视图切片；
  - `q3_wall_surfaces`: 前/后墙体三维界面坐标分布与 Q2 二维切片对照误差；
  - `q3_metal_objects`: 检出金属柱/金属铲 3D 主峰、$-10\text{ dB}$ 能量加权质心、$-10\text{ dB}$ 等值三维包围盒（含 $\Delta\hat{z}_{10\text{dB}}$）及 `ShadowRatio_m` 遮挡诊断表。

---

## 6. 独立可复现合成闭环小算例（附 `solutions/A/verify_q3_spec.py`）

[verify_q3_spec.py](verify_q3_spec.py) 构造零真实 `.dat` 读取的纯合成 63 路全阵列三维金属+后墙闭环算例：
1. **场景构造**：严格使用 64 阵元（63 路有效 RX + 发射 $i_{\text{tx}}=27$）与 $J=27$ 组 $x_j = 0.05(j-1)\text{ m}$ 扫查轨迹，在带 `H_ref` 色散的 2nd-Nyquist LFM 体制下植入：
   - **金属柱**：位于 $(x=0.35\text{ m}, y=1.15\text{ m})$，垂向跨度 $z \in [0.25, 0.75]\text{ m}$（高度跨度 $0.50\text{ m}$）；
   - **金属铲**：位于 $(x=0.90\text{ m}, y=0.75\text{ m})$，局部低矮靶标 $z \in [0.28, 0.42]\text{ m}$（中心 $z=0.35\text{ m}$）；
   - **背景后墙**：位于 $y=2.00\text{ m}$，当射线穿透金属柱/铲横向几何投影区时附加 `-14 dB` 遮挡衰减，并叠加带内 AWGN。
2. **运行命令行**：
   ```powershell
   python solutions/A/verify_q3_spec.py
   ```
3. **验证内容（全非空转门槛，口径与脚本严格一致）**：
   - 验证 63 路局部几何跨度（$x^{\text{loc}} \in [-0.280, +0.245]\text{ m}$，$z^{\text{loc}} \in [0.265, 0.755]\text{ m}$）、第 4 行与 Q2 一致、以及近场低高度角 $(y=0.40, z=0.20)$ 在解耦三维仰角窗下保持 $>0$ 有效孔径覆盖；
   - 在 `(dx, dy, dz) = (5, 5, 4) cm` 合成网格上运行三维 `M3-Img-CohBPA3D`（$4\times$ 基带过采样 + $e^{-j2\pi f_s \tau}$），以 $(x,y)$ 柱域 3D-NMS 分离双金属目标并**强制断言两个植入目标匹配到不同检出峰索引**（`idx_col != idx_shv`）；
   - 如实分别校验**主峰与 $-10\text{ dB}$ 质心 / XY 与 3D 误差**：
     - 竖直延展金属柱（主峰与质心均仅校验水平 XY 误差）：离散主峰 XY 误差与 $-10\text{ dB}$ 加权质心 XY 误差均 $\le 5.5\text{ cm}$；
     - 紧凑金属铲（校验完整三维欧氏误差）：离散主峰 3D 误差与 $-10\text{ dB}$ 加权质心 3D 误差均 $\le 6.0\text{ cm}$；
   - 校验立柱 `-10 dB` 包围盒垂向跨度 $\Delta\hat{z}_{10\text{dB}}$ 与主峰高度均显著大于低矮金属铲（差值 $\ge 8.0\text{ cm}$），相干 `PBR` 严格优于包络 `EnvBPA3D`，且金属后方墙面 `ShadowRatio <= -6.0 dB` 准确检出阴影衰减区。
