# A 题第二、三问（Q2 / Q3）图表与程序输出字段对照规范

- **所属分支**：`paper/a-q2q3-schema-contract`（基于 `main` = `40c637e066616d9e108f1cbf9d84e0ee33d61167`）
- **上游依据**：
  - [solutions/A/model_q2.md](../../solutions/A/model_q2.md)（`M2-Gain-BSEC` / `M2-Img-CohBPA` / `EnvBPA`）
  - [solutions/A/model_q3.md](../../solutions/A/model_q3.md)（`M3-Img-CohBPA3D` / `EnvBPA3D` / 3D-NMS / `ShadowRatio`）
  - [paper/A/NOTATION_TABLE.md](NOTATION_TABLE.md)、[paper/A/RESULTS_AND_FIGURES_CHECKLIST.md](RESULTS_AND_FIGURES_CHECKLIST.md)、[paper/A/draft_ch5_7.md](draft_ch5_7.md)（§6–§7）
  - JSON/NPZ 命名规范参照已批复之 [solutions/A/e0_s1s2_contract.md](../../solutions/A/e0_s1s2_contract.md)
- **合规声明**：本对照表严格锁定程序交付 JSON / NPZ 字段名、量纲单位、数组维度与论文图表槽位的一一对应关系；**全过程未读取任何 `.dat` 实测信号，全部实测定量指标、图像及表格内容均严格保留 `[待补]`**。

---

## 一、全局量纲、坐标约定与符号别名统一表

1. **单位与后缀铁律（消除 `m` / `cm`、`ns` / `s` 混用风险）**：
   - 程序 JSON 标量与 NPZ 坐标轴统一采用国际单位制（SI）：距离后缀 `_m`（`float64`，米），时间 `_s`（秒）或明确标示 `_ns`（纳秒，$10^9\tau$），角度 `_deg`（度），功率比 `_db`（统一按 $10\log_{10}$ 功率比定义），百分比 `_pct`（%）。
   - 论文展示表格（`Table 2-1` / `Table 3-1` / `Table 3-2`）按题面习惯兼标厘米（$\text{cm}$），回填阶段严格执行唯一换算 `value_cm = value_m * 100.0`，不在中间 JSON 混用厘米标量字段。
   - **符号别名对齐说明**（消除 [PAPER_SCAFFOLD.md](PAPER_SCAFFOLD.md) / [RESULTS_AND_FIGURES_CHECKLIST.md](RESULTS_AND_FIGURES_CHECKLIST.md) 早期预留记号与定稿模型记号差异）：
     - `C_B/A`（早先清单写法）$\equiv \Delta_{\text{B/A}}$（[model_q2.md](../../solutions/A/model_q2.md) §3.2 记号）$\leftrightarrow$ JSON 字段 `delta_ba_db`；
     - `C_B/bg`（早先清单写法）$\equiv \text{PBR}_B$（[model_q2.md](../../solutions/A/model_q2.md) §3.2 记号）$\leftrightarrow$ JSON 字段 `pbr_b_db`。
2. **上游冻结契约继承字段（Q2 与 Q3 结果 JSON 顶层必含）**：
   - `phase`（`"Q2"` / `"Q3-Wall"` / `"Q3-Metal"`）、`implementation_sha`、`main_commit`、`q1_frozen_config_path`、`q1_frozen_config_sha256`、`d0_contract_version`（`"D0-4"`）、`d1_contract_version`（`"D1-2"`）、`groups_used[]`、`anomaly_isolation{}`、`arrays_sha256`、`finite`（全有限布尔门控）、`status`（未验收前保留 `"contract_only"`）。

---

## 二、问题二（`Q2`：远距离增益补偿与二维剖面成像）字段与图表对照

### 2.1 输出文件契约（拟输出 `q2_results.json` 与 `q2_arrays.npz`）

| 产出载体 | 字段 / 数组键名 | 形状 / 类型 | 物理单位 | 物理含义与计算口径 | 对应论文槽位 |
|---|---|---|---|---|---|
| `q2_results.json` | `row_id`, `rx_indices[]`, `z_slice_m` | `int`, `list[int]`, `float` | 无量纲, —, `m` | 主行 `row_id=4`（7 路 `[24..26,28..31]`，`z_slice_m=0.545`）；校验行 `3`/`5`（8 路，`0.615`/`0.475`）须代入三维 $\Delta z$ | §6.1, `Fig 2-2` |
| `q2_results.json` | `gain_params.{beta, alpha_gain_per_ns, alpha_y_per_m, slope_db_per_m, y0_m, tau0_s, y_sat_m, tau_sat_s, g_cap}` | `dict` (`float`) | —, `ns^-1`, `m^-1`, `dB/m`, `m`, `s`, `m`, `s`, 无量纲 | 锁定 $\tilde{\alpha}_y = \frac{2\times 10^9}{c_0}\alpha_{\text{gain}}$、斜率 $57.946\,\alpha_{\text{gain}}\text{ dB/m}$、$G_{\text{cap}}=20.0$（$+26.02\text{ dB}$） | §6.2, `Fig 2-2` |
| `q2_results.json` | `gain_selection.{alpha_grid_per_ns[], delta_far_near_db[], c_far_med_db[], selected_alpha_per_ns}` | `dict` (`list[float]`, `float`) | `ns^-1`, `dB`, `dB`, `ns^-1` | 宽域 $\mathcal{Y}_{\text{near}}=[0.25,1.00]\text{ m}$ 与 $\mathcal{Y}_{\text{far}}=[1.20,2.40]\text{ m}$ 无真值拐点选参轨迹（$C_{\text{far/med}}$ 跌落 $>1.5\text{ dB}$ 截断） | §6.2.2, `Fig 2-2` |
| `q2_results.json` | `metrics_before_gain.{delta_ba_db, pbr_b_db, pslr_b_db, b_coverage_pct, delta_far_near_db, c_far_med_db}` | `dict` (`float`) | `dB`（覆盖率 `%`） | 未增益对照 $I_{\text{2D}}^{(0)}$（$W_{\text{comp}}\equiv 1$）在 $\Omega_A/\Omega_B$ 上的定量指标 | `Table 2-1`, `Fig 2-1` |
| `q2_results.json` | `metrics_after_gain_coh.{delta_ba_db, pbr_b_db, pslr_b_db, b_coverage_pct, delta_far_near_db, c_far_med_db}` | `dict` (`float`) | `dB`（覆盖率 `%`） | `M2-Img-CohBPA` 增益后相干聚焦指标及净变化 $\Delta_{\text{gain}} = \text{after} - \text{before}$ | `Table 2-1`, `Fig 2-1` |
| `q2_results.json` | `metrics_after_gain_env.{delta_ba_db, pbr_b_db, pslr_b_db, b_coverage_pct}` | `dict` (`float`) | `dB`（覆盖率 `%`） | `M2-Img-EnvBPA` 非相干包络对照指标（检验跨 33 组相干稳定性） | `Table 2-1` |
| `q2_results.json` | `wall_a_apparent.{x_min_m, x_max_m, y_start_m, y_end_m, slope_dy_dx, tilt_deg, fit_r2}` | `dict` (`float`) | `m`, `m`, 无量纲, `deg`, 无量纲 | 前墙 A 脊线回归表观前表面轨迹 $y_A(x)$ 与倾角 $\theta_A=\arctan(\mathrm{d}y/\mathrm{d}x)$ | `Table 2-1`, `Fig 2-1` |
| `q2_results.json` | `wall_b_apparent.{air_x_ranges_m, air_y_mean_m, air_tilt_deg, behind_a_x_range_m, behind_a_y_mean_m, delta_y_app_m, eps_r_diag}` | `dict` | `m`, `deg`, `m`, 无量纲 | 分区统计空气直射段与穿墙遮挡段视在深度、错位 $\Delta y_{\text{app}}$ 与可证伪诊断量 $\hat{\varepsilon}_r=(1+\Delta y_{\text{app}}/d_A)^2$ | `Table 2-1`, `Fig 2-1` |
| `q2_results.json` | `row_consistency.{row_3_wall_b_y_m, row_5_wall_b_y_m, max_row_diff_cm}` | `dict` (`float`) | `m`, `m`, `cm` | 第 4 行与第 3/5 行跨行 3D 坐标校正定位一致性偏差 | `Fig 2-2`, §6.4 |
| `q2_arrays.npz` | `x_grid_m`, `y_grid_m` | `(N_x,)`, `(N_y,)` `float64` | `m` | 网格轴：$[-0.20,1.40]\times[0,2.50]\text{ m}$（`0.01 m` $\to 161\times 251$，或 `0.005 m` $\to 321\times 501$） | `Fig 2-1`, `Fig 2-2` |
| `q2_arrays.npz` | `x_scan_m`, `j_group_ids`, `j_p_common` | `(33,)`, `(33,)`, `(33,)` | `m`, str, int | 33 组站位 $x_j=-0.20+0.05(j-1)$ 与共同 `sync` 包数（第 3 组 `P=3` 留痕） | §6.1, `Fig 2-1` |
| `q2_arrays.npz` | `tau_curve_s`, `w_comp_curve` | `(K_tau,)`, `(K_tau,)` `float64` | `s`, 无量纲 | 两步封顶增益曲线 $W_{\text{comp}}(\tau)$（覆盖 $[0, 25]\text{ ns}$） | `Fig 2-2` |
| `q2_arrays.npz` | `image_before_gain_coh`, `image_after_gain_coh`, `image_after_gain_env` | `(N_y, N_x)` `float64` | 归一化聚焦能量 | 未增益相干、增益相干、增益包络二维剖面能量矩阵（绘图取 $10\log_{10}(I/I_{\text{ref}})$ dB） | `Fig 2-1` |
| `q2_arrays.npz` | `image_row3_coh`, `image_row5_coh`（可选） | `(N_y, N_x)` `float64` | 归一化聚焦能量 | 第 3 行 / 第 5 行跨高程对照组二维能量矩阵 | `Fig 2-2` |

### 2.2 Q2 论文图表槽位回填对照表（实测状态全部 `[待补]`）

| 论文图/表编号 | 正文位置 | 所需数据来源字段 / 数组 | 图表呈现维度与单位口径 | 当前状态 |
|---|---|---|---|---|
| **`Fig 2-1`** | §6.4 | `x_grid_m`, `y_grid_m`, `image_before_gain_coh`, `image_after_gain_coh`, `wall_a_apparent`, `wall_b_apparent` | 1×2 共享动态范围色标（dB）2D 剖面热图（坐标 $\text{cm}$）+ 代表 $x$ 纵切线 $y$ 向功率截面曲线（叠加墙 A/B 脊线） | **`[待补]`** |
| **`Fig 2-2`** | §6.4 | `tau_curve_s`, `w_comp_curve`, `gain_selection`, `row_consistency`, `image_row3_coh`, `image_row5_coh` | 左：第 4 行 vs 第 3/5 行跨行一致性剖面/脊线对比（$\text{cm}$）；右：$\alpha_{\text{gain}}$（$\text{ns}^{-1}$）选参拐点曲线（$\Delta_{\text{far/near}}, C_{\text{far/med}}$，dB） | **`[待补]`** |
| **`Table 2-1`** | §6.4 | `metrics_before_gain`, `metrics_after_gain_coh`, `metrics_after_gain_env`, `wall_a_apparent`, `wall_b_apparent` | 对比行：`未增益` / `CohBPA(增益后)` / `EnvBPA(增益后)`；列：`Δ_B/A (dB)`、`PBR_B (dB)`、`PSLR_B (dB)`、覆盖率（%）、前墙 $y_A(x)$ 与倾角（$\text{cm},\ ^\circ$）、后墙 $y_B^{\text{air}}$ / $y_B^{\text{behind-A}}$（$\text{cm}$）及 $\hat{\varepsilon}_r$ 诊断注记 | **`[待补]`** |

---

## 三、问题三（`Q3`：全阵列 63 路三维成像、双金属分离与遮挡阴影）字段与图表对照

### 3.1 问题 3.1 墙体三维成像（拟输出 `q3_wall_results.json` 与 `q3_wall_arrays.npz`）

| 产出载体 | 字段 / 数组键名 | 形状 / 类型 | 物理单位 | 物理含义与计算口径 | 对应论文槽位 |
|---|---|---|---|---|---|
| `q3_wall_results.json` | `grid_spec.{x_range_m, y_range_m, z_range_m, coarse_step_m, fine_step_m}` | `dict` (`float`) | `m` | 区域 $[-0.20,1.40]\times[0,2.50]\times[0.20,0.80]\text{ m}$；粗网格 `(0.02,0.02,0.02)`，细化 ROI `(0.01,0.01,0.01)` | §7.1–§7.2 |
| `q3_wall_results.json` | `aperture_weights.{theta_x_flat_deg, theta_x_cut_deg, theta_z_flat_deg, theta_z_cut_deg, valid_rx_count}` | `dict` | `deg`, 个 | 水平 $35^\circ\text{–}45^\circ$、垂向 $45^\circ\text{–}55^\circ$ 解耦上升余弦窗，$|\mathcal{I}_{\text{rx}}|=63$ | §7.2.1 |
| `q3_wall_results.json` | `inherited_gain_params.{beta, alpha_gain_per_ns, g_cap}` | `dict` (`float`) | —, `ns^-1`, 无量纲 | 严格继承 Q2 锁定之墙体增益参数 | §7.2.2 |
| `q3_wall_results.json` | `wall_a_3d.{x_span_m, y_front_mean_m, y_front_range_m, z_envelope_m, tilt_deg}` | `dict` (`list/float`) | `m`, `deg` | 前墙 A 三维前界面 $\hat{y}_A(x,z)$ 及有限高度包络 $[z_{A,\min}, z_{A,\max}]$ | `Table 3-1`, `Fig 3-1` |
| `q3_wall_results.json` | `wall_b_3d.{air_y_mean_m, behind_a_y_mean_m, z_consistency_cm, pbr_b_coh_db, pbr_b_env_db}` | `dict` (`float`) | `m`, `cm`, `dB` | 后墙 B 全高一致性、空气段 vs 遮挡段三维视在深度及相干/包络对比度 | `Table 3-1`, `Fig 3-1` |
| `q3_wall_results.json` | `q2_q3_reconciliation.{z_slice_m, air_segment_max_diff_cm, air_segment_mae_cm, passed_le_2cm}` | `dict` | `m`, `cm`, `bool` | $z=z_4=0.545\text{ m}$ 切片与 Q2 二维空气段位置交叉对账（门槛 $\le 2.0\text{ cm}$） | `Table 3-1`, §7.3 |
| `q3_wall_arrays.npz` | `x_grid_m`, `y_grid_m`, `z_grid_m` | `(N_x,)`, `(N_y,)`, `(N_z,)` `float64` | `m` | 规则三维坐标网格（$2\text{ cm}$ 粗网格对应 $81\times 126\times 31$） | `Fig 3-1` |
| `q3_wall_arrays.npz` | `image_3d_coh`, `image_3d_env` | `(N_z, N_y, N_x)` `float64` | 归一化聚焦能量 | `M3-Img-CohBPA3D` 与 `EnvBPA3D` 三维体素聚焦能量场 | `Fig 3-1` |
| `q3_wall_arrays.npz` | `slice_xy_z4`, `proj_xy_max`, `proj_xz_max`, `proj_yz_max` | 2D `float64` | 归一化聚焦能量 | $z=0.545\text{ m}$ 水平切片及三视图最大能量投影矩阵 | `Fig 3-1` |

### 3.2 问题 3.2 金属柱与金属铲三维定位及阴影遮挡（拟输出 `q3_metal_results.json` 与 `q3_metal_arrays.npz`）

| 产出载体 | 字段 / 数组键名 | 形状 / 类型 | 物理单位 | 物理含义与计算口径 | 对应论文槽位 |
|---|---|---|---|---|---|
| `q3_metal_results.json` | `grid_spec.{x_range_m, y_range_m, z_range_m, coarse_step_m, fine_step_m}` | `dict` (`float`) | `m` | $[0.00,1.30]\times[0,2.50]\times[0.20,0.80]\text{ m}$（$J_{\text{metal}}=27$，$x_j=0.05(j-1)$） | §7.1–§7.2 |
| `q3_metal_results.json` | `anomaly_isolation.{orphan_skipped, group8_sync_common, group8_int16_min_count, group8_d1_gate_action}` | `dict` | —, 个 | 跳过 `22-50-31_16000_7.dat`（0 B）；第 8 组 `22-09-58_16000` 交集 `P=3` 及末包 `46` 个 `-32768` `D1-2` 核查结论 | `Table 3-2`, §7.1 |
| `q3_metal_results.json` | `gain_modes.{primary_localization, shadow_diagnostic}` | `dict` | `ns^-1` | 定位基线固定纯几何扩散 `beta=1.0, alpha_gain=0.0`；遮挡诊断保留高增益对比 profile | §7.2.2 |
| `q3_metal_results.json` | `nms_params.{radius_x_m, radius_y_m, min_peak_above_med_db, contour_drop_db}` | `dict` (`float`) | `m`, `m`, `dB`, `dB` | $(x,y)$ 柱域 3D-NMS 半径 `(0.14, 0.18) m`、检测门槛 `+12.0 dB`、包围盒阈值 `-10.0 dB` | §7.3.2 |
| `q3_metal_results.json` | `metal_objects[].{object_id, inferred_class, peak_xyz_m[3], centroid_10db_xyz_m[3], bbox_10db_m[6], delta_z_10db_m, peak_above_med_db}` | `list[dict]` | `m`, `dB` | 逐检出目标主峰 $(\hat{x}_p,\hat{y}_p,\hat{z}_p)$、$-10\text{ dB}$ 加权质心 $(\hat{x}_c,\hat{y}_c,\hat{z}_c)$、包围盒与垂向跨度 $\Delta\hat{z}_{10\text{dB}}$（高立柱 vs 低金属铲不硬编码先验坐标） | `Table 3-2`, `Fig 3-2` |
| `q3_metal_results.json` | `shadow_diagnostics[].{object_id, y_shadow_start_m, y_wall_band_m[2], i_shadow_bar, i_unocc_med, shadow_ratio_db, shadow_confirmed}` | `list[dict]` | `m`, 能量, `dB`, `bool` | 后方区间 $y>\hat{y}_p+0.25\text{ m}$ 阴影均能 $\bar{I}_{\text{shadow}}^{(m)}$ 与无遮挡墙面中位数 $\bar{I}_{\text{unocc}}$ 比值（`ShadowRatio <= -6.0 dB` 确证遮挡；注：`ShadowRatio` 指标由本文定义，[8] 支撑遮挡物理机制） | `Table 3-2`, `Fig 3-2` |
| `q3_metal_results.json` | `resolution_limits.{dy_res_m, dx_res_m, dz_res_at_08m_m, dz_res_at_20m_m}` | `dict` (`float`) | `m` | 物理分辨边界：$\Delta y\approx 0.1071\text{ m},\ \Delta x\approx 0.0354\text{ m},\ \Delta z(2\text{ m})\approx 0.41\text{ m}$ | §7.4, §8.2 |
| `q3_metal_arrays.npz` | `x_grid_m`, `y_grid_m`, `z_grid_m` | `(N_x,)`, `(N_y,)`, `(N_z,)` `float64` | `m` | $[0.00,1.30]\times[0,2.50]\times[0.20,0.80]\text{ m}$ 三维坐标轴 | `Fig 3-2` |
| `q3_metal_arrays.npz` | `image_3d_coh`, `image_3d_env`, `image_3d_shadow_gain` | `(N_z, N_y, N_x)` `float64` | 归一化聚焦能量 | 主定位 3D 相干能量、包络对照能量及辅助观察后墙阴影的高增益 3D 能量网格 | `Fig 3-2` |
| `q3_metal_arrays.npz` | `shadow_profile_x_y` | `(N_y_wall, N_x)` `float64` | 归一化聚焦能量 / `dB` | 后墙带沿 $x$ 横向与 $y$ 纵向阴影衰减能量剖面，用于 `Fig 3-2` 右侧遮挡对比图 | `Fig 3-2` |

### 3.3 Q3 论文图表槽位回填对照表（实测状态全部 `[待补]`）

| 论文图/表编号 | 正文位置 | 所需数据来源字段 / 数组 | 图表呈现维度与单位口径 | 当前状态 |
|---|---|---|---|---|
| **`Fig 3-1`** | §7.2–§7.4 | `q3_wall_arrays.npz`: `image_3d_coh`, `proj_xy_max`, `proj_xz_max`, `proj_yz_max`, `slice_xy_z4`；`wall_a_3d`, `wall_b_3d` | 三维 $-10\text{ dB}$ / 阈值等值面立体图 + 三视图正交投影切片（$xOy, xOz, yOz$，单位 $\text{cm}$） | **`[待补]`** |
| **`Table 3-1`** | §7.4 | `wall_a_3d`, `wall_b_3d`, `q2_q3_reconciliation` | 行：`前墙 A`、`后墙 B（空气段 / 遮挡段）`；列：包围盒 $[x,y,z]$（$\text{cm}$）、中心/前界面方程（$\text{cm}, ^\circ$）、与 Q2 $z_4$ 切片偏差（$\text{cm}$）及 `CohBPA3D/EnvBPA3D` 对比度（$\text{dB}$） | **`[待补]`** |
| **`Fig 3-2`** | §7.3–§7.4 | `q3_metal_arrays.npz`: `image_3d_coh`, `shadow_profile_x_y`；`metal_objects[]`, `shadow_diagnostics[]` | 左：金属柱与金属铲三维聚焦高亮等值面及质心/包围盒标注；右：金属后方墙面横向/深度阴影衰减对比剖面（标注 `ShadowRatio` $\text{dB}$） | **`[待补]`** |
| **`Table 3-2`** | §7.4 | `metal_objects[]`, `shadow_diagnostics[]`, `anomaly_isolation` | 严格分列“主峰 vs $-10\text{ dB}$ 质心”与“XY（立柱）vs 3D（金属铲）”口径：$(\hat{x},\hat{y},\hat{z})$（$\text{cm}$）、包围盒与 $\Delta\hat{z}_{10\text{dB}}$（$\text{cm}$）、`ShadowRatio`（$\text{dB}$）及第 8 组/孤儿异常核查结论 | **`[待补]`** |

---

## 四、机器可读契约与核查命令

同目录及方案目录配套以下可验证交付件：
- 机器可读 JSON Schema 对照清单：[solutions/A/q2_q3_output_contract.json](../../solutions/A/q2_q3_output_contract.json)
- 一致性自检脚本（验证所有图/表槽位 `[待补]` 状态、字段单位定义与 `RESULTS_AND_FIGURES_CHECKLIST.md` 对齐，不访问任何 `.dat`）：
  ```powershell
  python solutions/A/test_q2_q3_output_contract.py
  ```
