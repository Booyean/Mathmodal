# A 题论文参考文献核验与断言映射台账（Ch.1–Ch.7）

- **所属分支**：`paper/a-citations`（基于 `main` = `81a066f`）
- **作用域说明**：本台账覆盖全篇第 1 至第 7 章所需的外部学术参考文献；为避免与尚在复核阶段的 PR #27（`paper/A/draft_ch5_7.md`）发生并发合并冲突，本分支已直接补全 [draft_ch1_4.md](draft_ch1_4.md) 中的全部 4 处 `[文献引用待补]` 槽位及 [PAPER_SCAFFOLD.md](PAPER_SCAFFOLD.md) 第九节参考文献清单，并将第 5–7 章各技术断言对应的精确引用锚点统一登记于下表，待 PR #27 合入主线并在最终集成阶段一次性挂接正文编号。
- **核验原则**：全部条目均选用正式出版的同行评议 IEEE 期刊论文或学术专著，逐条核对作者、篇名、刊名/出版社、卷期页码/ISBN、年份及 DOI 链接，未编造任何数字或未经核实的网络来源。

---

## 一、已核验学术参考文献条目（GB/T 7714 风格）

| 编号 | 完整文献著录 | DOI 与官方出版链接 | 核心覆盖主题 |
|---|---|---|---|
| **[1]** | Grove R L, Dall J, Leth-Espensen P. Mutual Coupling and Channel Imbalance Calibration of Colocated MIMO Radars[J]. *IEEE Open Journal of Antennas and Propagation*, 2022, 3: 511–522. | `10.1109/OJAP.2022.3174246` ([DOI](https://doi.org/10.1109/OJAP.2022.3174246)) | 共址多通道雷达幅相差不一致性与阵元互耦校准模型 |
| **[2]** | Hao X, Chen J, Guo S, Li N, Yao Y, Qiu C, Cui G. A Robust Multichannel Calibration Method for MIMO Through-the-Wall Radar Systems[J]. *IEEE Transactions on Antennas and Propagation*, 2026, 74(7): 7118–7123. | `10.1109/TAP.2026.3684987` ([DOI](https://doi.org/10.1109/TAP.2026.3684987)) | MIMO 穿墙雷达实测多通道稳健校准方法 |
| **[3]** | Tivive F H C, Bouzerdoum A, Amin M G. A Subspace Projection Approach for Wall Clutter Mitigation in Through-the-Wall Radar Imaging[J]. *IEEE Transactions on Geoscience and Remote Sensing*, 2015, 53(4): 2108–2122. | `10.1109/TGRS.2014.2354755` ([DOI](https://doi.org/10.1109/TGRS.2014.2354755)) | 穿墙雷达强静态杂波/直达干扰的子空间投影抑制框架 |
| **[4]** | Jol H M (Ed.). *Ground Penetrating Radar: Theory and Applications*[M]. Amsterdam: Elsevier, 2009. ISBN 978-0-444-53348-7. | `10.1016/B978-0-444-53348-7.X0001-4` ([DOI](https://doi.org/10.1016/B978-0-444-53348-7.X0001-4)) | 探地雷达几何扩散与介质衰减物理规律、SEC 时变增益补偿与噪底放大权衡 |
| **[5]** | Ahmad F, Amin M G, Kassam S A. Synthetic aperture beamformer for imaging through a dielectric wall[J]. *IEEE Transactions on Aerospace and Electronic Systems*, 2005, 41(1): 271–283. | `10.1109/TAES.2005.1413761` ([DOI](https://doi.org/10.1109/TAES.2005.1413761)) | 穿墙宽带合成孔径波束形成/反向投影（BPA）及介质墙折射走时偏移原理 |
| **[6]** | Ahmad F, Amin M G, Mandapati G. Autofocusing of through-the-wall radar imagery under unknown wall characteristics[J]. *IEEE Transactions on Image Processing*, 2007, 16(7): 1785–1795. | `10.1109/TIP.2007.899030` ([DOI](https://doi.org/10.1109/TIP.2007.899030)) | 未知前墙介电常数与厚度引起之后墙散焦、位置偏移与自聚焦修正 |
| **[7]** | Zhang W, Hoorfar A. Three-Dimensional Real-Time Through-the-Wall Radar Imaging With Diffraction Tomographic Algorithm[J]. *IEEE Transactions on Geoscience and Remote Sensing*, 2013, 51(7): 4155–4163. | `10.1109/TGRS.2012.2227059` ([DOI](https://doi.org/10.1109/TGRS.2012.2227059)) | 多收发/MIMO 阵列三维穿墙雷达层析与空间聚焦重建框架 |
| **[8]** | Hu J, Song Y, Jin T, Lu B, Zhu G, Zhou Z. Shadow Effect Mitigation in Indication of Moving Human Behind Wall via MIMO TWIR[J]. *IEEE Geoscience and Remote Sensing Letters*, 2015, 12(3): 453–457. | `10.1109/LGRS.2014.2346766` ([DOI](https://doi.org/10.1109/LGRS.2014.2346766)) | MIMO 穿墙成像中前向遮挡引起之后方目标电磁阴影区物理机制与刻画 |
| **[9]** | Leigsnering M, Ahmad F, Amin M G, Zoubir A M. Multipath Exploitation and Suppression for SAR Imaging of Building Interiors[J]. *IEEE Signal Processing Magazine*, 2014, 31(4): 110–119. | `10.1109/MSP.2014.2312683` ([DOI](https://doi.org/10.1109/MSP.2014.2312683)) | 室内墙体结构多次反射鬼影、伪峰识别与多径干扰抑制 |
| **[10]** | Amin M G (Ed.). *Through-the-Wall Radar Imaging*[M]. Boca Raton, FL: CRC Press, 2011. ISBN 978-1-4398-1476-5. | `10.1201/9781315218144` ([DOI](https://doi.org/10.1201/9781315218144)) | 穿墙成像雷达体制、信号模型、传播与多维孔径分辨率系统理论专著 |

---

## 二、正文 Ch.1–Ch.7 逐条断言—文献支撑映射表

### 2.1 已写入正文的 Ch.1–Ch.4 挂接清单（[draft_ch1_4.md](draft_ch1_4.md)）

| 章节位置 | 支撑的正文论断 | 对应引用 | 状态 |
|---|---|---|---|
| `§1.1`（L12） | SIMO 二维平面阵列多角度散射响应获取与三维聚焦成像孔径基础 | `[10]` | 已写入正文 |
| `§2.1`（L35，原槽位 1） | 多通道硬件幅相失配、端射互耦及穿墙雷达阵列相对校准机理 | `[1, 2]` | 已补全替换 |
| `§2.1`（L37） | 静态直达与强前墙杂波对消中的固定模板减除 vs 子空间投影（`M0-DW-Subspace`）对比 | `[3]` | 已写入正文 |
| `§2.2`（L41，原槽位 2） | 探地/穿墙双程几何扩散与介质衰减规律、无界指数时间增益（SEC）高时延噪底放大风险 | `[4]` | 已补全替换 |
| `§2.2`（L42，原槽位 3） | 穿墙宽带后向投影（`CohBPA`/`EnvBPA`）聚焦机理及未知介质墙参数引起的散焦与视在深度偏移 $\Delta y_{\text{app}}$ | `[5, 6]` | 已补全替换 |
| `§2.3`（L47，原槽位 4） | 全阵列三维穿墙空间重建，以及前向强散射遮挡引起之后方墙面电磁阴影区辨识（`ShadowRatio`） | `[7, 8]` | 已补全替换 |

### 2.2 第五至第七章（`draft_ch5_7.md`）合并后待挂接引用映射清单

*(待 PR #27 合入 `main` 后，于统一排版合稿阶段按本表位置插入编号引用，不更改任何公式及未定实验 `[待补]` 槽位。)*

| 目标章节 | 拟挂接的具体建模/分析论断 | 建议编号 | 支撑理由 |
|---|---|---|---|
| `§5.1–§5.2.1` | 通道相对频响标定模型 `M0-Cal-Base` 与对照分支 `M0-Cal-Joint`（考虑近场端射互耦对幅相差校准之影响） | `[1, 2]` | `[1]` 给出共址阵元互耦与通道不平衡联合校准表述；`[2]` 论证穿墙阵列实测多通道稳健校准设计 |
| `§5.3.1` | `M0-DW-Base` 与对照组 `M0-DW-Subspace` 在强直射波与静态杂波抑制中的原理划分 | `[3]` | `[3]` 奠定基于子空间投影剥离强静态/直达干扰、保留弱目标回波的穿墙杂波抑制理论 |
| `§5.4.2` | 墙体前表面首峰判别规则（与后表面或内部多次反射强伪峰区分） | `[9]` | `[9]` 阐述室内墙体及结构界面的多次反射鬼影/伪峰形成机理 |
| `§6.2.1` | 有界双分量增益补偿模型 `M2-Gain-BSEC`（球面/平面扩散幂次 $\beta$ 与指数衰减因子 $\alpha_{\text{gain}}$ 结合硬截断 $G_{\text{cap}}$） | `[4]` | `[4]` 为 GPR 球面与指数衰减补偿（SEC）标准参考体系，直接对应双分量衰减物理来源与噪底防过放大边界 |
| `§6.3.1–§6.3.2` | 单行 2D 相干反向投影（`CohBPA`）、包络对比（`EnvBPA`）及未知前墙 $(\varepsilon_r, d_A)$ 导致的后墙视在后移 $\Delta y_{\text{app}}$ | `[5, 6, 10]` | `[5]` 给出穿透介质墙宽带合成孔径延迟叠加聚焦模型；`[6]` 量化未知墙参对后向投影偏移/散焦的影响；`[10]` 覆盖总体波束形成框架 |
| `§7.1–§7.2` | 全 63 路三维反向投影重建框架与有限垂向孔径分辨界讨论 | `[7, 10]` | `[7]` 覆盖三维穿墙成像空间重建算法；`[10]` 给出穿墙三维阵列孔径与分辨率物理制约 |
| `§7.3.2` | 金属柱与金属铲后方墙面电磁阴影遮挡区识别及 `ShadowRatio` 定量度量 | `[8]` | `[8]` 针对 MIMO 穿墙雷达场景直接分析前向遮挡引起之后方墙面/目标阴影效应及定量评价 |
