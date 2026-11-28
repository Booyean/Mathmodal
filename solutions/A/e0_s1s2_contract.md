# A-Q1-E0-S1/S2 合成闭环接口与实现说明

- **实现**：`solutions/A/a_e0_s1s2.py`（作者实现，纯合成，不读取真实 `.dat`）
- **作者测试**：`solutions/A/test_a_e0_s1s2.py`
- **范围**：仅 `experiments/A/A-Q1-E0/PLAN.md` 的阶段 1（`E0-S1` + `E0-S2`），**不含** `E0-C` 真实校准、`E0-T` 留出评价、`N0` 改进、成像或任何真实测距结论。
- **依据**：`checks/A/e0_s1s2_prereg.md`（E0-PREREG-1）、`coordination/A_Q1_E0_S_DECISION.md`（裁定 2026-11-28）、`experiments/A/A-Q1-E0/PLAN.md` / `config.json`（`schema_version=3`）、`solutions/A/model_q1.md`（M0，`098e17d`）。
- **版本锚点**：`config.json` 的 LF 归一化 SHA256 `8fb6821f…e06a`；`PLAN.md` SHA256 `073511c0…5a88`；S2 参数表规范 SHA256 `aa86bf56…6e96`。

本说明锁定结果 JSON/数组的字段语义、生成器与估计器的可复跑口径，以及已知边界。字段名可自定，但语义与预登记一致；本文件即字段映射。

---

## 1. 运行方式与输出

### 1.1 命令

```powershell
python solutions/A/a_e0_s1s2.py --out experiments/A/A-Q1-E0/s1s2/results
```

可选参数：`--config`（默认 `experiments/A/A-Q1-E0/config.json`）、`--implementation-sha`、`--parent-commit`、`--main-commit`（登记结果时应显式传入结果所用代码提交，避免自引用）。

退出码：`0` = 三个 case 的全部门控通过且 config/PLAN/参数表锚点匹配；`1` = 任一适用门控或锚点失败（JSON 仍写出，含 `gate_results` 与 `stop_reason`）；异常则非零退出并保留日志。

### 1.2 输出文件

| 文件 | 内容 |
|---|---|
| `e0_s1s2_results.json` | 机器可读结果（见 §2） |
| `e0_s1s2_arrays.npz` | 用于独立重算的数组（见 §3）及 SHA256 |
| `e0_s2_param_table.json` | 62 路 S2 参数表（与预登记同格式） |
| `run.log` | 关键诊断、LOO 9 组结果、逐案指标 |
| `SHA256SUMS.txt` | 上述文件的 SHA256 |

运行期只读取 `config.json`；数组/JSON/日志均写入 `--out`。**不打开任何 `.dat`**（作者测试用 `sys.addaudithook` 审计全部 `open` 事件）。

与预登记 JSON 的字段对应：`implementation_sha`、`phase`、`config_sha256`、`main_commit`、`environment`、`command`、`resource`、`cases[].{case_id,d_true_m,d_hat_m,abs_err_cm,dtau_err_ns,supp_dw_win_db,pslr_db,pnr_db,valid_rx,finite,seed,arrays_sha256}` 均保留；`arrays_sha256` 的 `case_arrays` 即该 case 数组集合的规范摘要，`x_after`/`s_eff` 另列。

---

## 2. 结果 JSON 语义

### 2.1 顶层

| 键 | 语义 |
|---|---|
| `experiment_id` / `phase` / `scope` | `"A-Q1-E0"` / `"E0-S"` / `"synthetic_only_no_real_dat"` |
| `implementation_sha` / `parent_commit` / `main_commit` / `branch` | 结果所用代码提交与父提交；`main_commit` 为运行时 `origin/main` |
| `config_sha256` / `config_sha256_expected` / `config_sha256_match` | `config.json` 的 LF 归一化 SHA256 及锚点比对 |
| `plan_sha256` / `plan_sha256_expected` / `plan_sha256_match` | `PLAN.md` 原始字节 SHA256 及锚点比对 |
| `s2_param_table_sha256` / `s2_param_table_expected_sha256` / `s2_param_table_match` | 62 路参数表规范 SHA256 及预登记比对 |
| `s2_param_rows` / `s2_air_offsets_s` / `s2_target_offsets_s` | 62 行参数与 10+2 组触发偏移（秒） |
| `s2_offsets_sha256` | 上述 12 组偏移（固定顺序 `air_0..air_9,target_0.42,target_0.69`）的规范 JSON SHA256 |
| `s2_noise_sigma` / `s2_noise_sigma2` / `s2_echo_power_042` | 时域噪声标准差/方差与 0.42 m **纯目标回波**（不含直达波）平均时域功率 |
| `s2_noise_sha256_raw` / `s2_noise_sha256_scaled` | 12 组 `standard_normal((63,4000))` 原始矩阵、乘 σ 后噪声矩阵的 SHA256（float64 C 顺序） |
| `lambda_loo` | 9 组 LOO 的 `J_air/min/median/supp_db`、default/best/selected、切换触发与原因 |
| `air_alignment_shifts_s` | 10 组空场相对 `data1` 的对齐位移（秒，模 `Tp`） |
| `resource` | 计算段墙钟秒数与进程峰值工作集 MiB（Windows `GetProcessMemoryInfo`） |
| `arrays_sha256` | 全部交付数组的规范摘要；与 `e0_s1s2_arrays.npz` 内容一一对应 |
| `overall_pass` / `stop_reason` | 全部门控（含 config 与参数表锚点）是否通过 |

### 2.2 `cases[]`

- `E0-S1`：`d_hat_m` 取主统计量 `P_norm,eff`；同时给 `d_hat_p_norm_m`、`d_hat_p_env_m`。`dtau2_hat_s`、`dtau_err_ns`、`g2_hat`、`psi2_hat_rad`、`dt0_samples`、`t0_eff_tgt_samples` 为相对校准/对齐诊断。`supp_dw_win_db`/`pslr_db`/`pnr_db` 按预登记填 `null`，`not_applicable` 给出原因（2 路无噪例外，不给伪零）。
- `E0-S2@0.42` / `E0-S2@0.69`：`supp_dw_win_db`、`pslr_db`、`pnr_db`、`bg_proxy`、`valid_rx`、`finite`、`echo_ret_db`（仅诊断）、`t_anchor_samples`、`dt0_samples`、`d_hat_p_norm_m`、`d_hat_p_env_m`。`dtau_err_ns` 为 `null`（S2 无相对校准参数门控）。
- 每个 case 的 `gate_results` 给出适用门控的 `value`、`threshold`、`passed`；`gates_applied` 列出适用项。`t0_eff`/`dt0` 标 `role="diagnostic"` 但仍按预登记容差检查。每例另有 `stop_reason`：通过为 `null`，失败为 `"gate_failed: <gate>..."`；顶层 `stop_reason` 汇总配置/参数表锚点与全部 case 的失败项。

`E0-S1` 的搜索全程使用 `[0.15, 2.00] m`、粗 1 mm、细 0.1 mm；`P_norm` 与 `P_env` 同时报告。`E0-S2@0.42` 使用墙体规则（局部极大、`≥η_wall·P_max`、且 `≥BG_proxy+6 dB` 的**最小 d 前向峰**，`η_wall=0.25`）；`E0-S2@0.69` 使用金属板全局 `argmax`。两者均在粗峰 ±1 mm 内以 0.1 mm 细搜。

---

## 3. 数组文件 `.npz` 键与单位

公共轴：

| 键 | 形状 | 单位/语义 |
|---|---|---|
| `freq_hz` | (1401,) | 数字频率 `f_D = k/(Np·Ts) = k·1 MHz`，`k=300..1700` |
| `freq_rf_hz` | (1401,) | 第二奈奎斯特区物理射频 `f_R = fs - f_D`，Hz |
| `band_k` | (1401,) int64 | 整数 bin 索引 `k` |
| `s2_rx_idx` / `s2_r_dir_m` / `s2_tau_dir_s` | (63,) | 有效接收通道、直达路径 `R_i^dir`、`τ_i^dir=R_i/c0` |
| `s2_param_rows` | (62,5) | `[rx_idx, Δτ, G, ψ0, ψ2]`，单位 s/1/rad/rad |
| `s2_air_offsets_s` / `s2_target_offsets_s` | (10,)/(2,) | 触发偏移（秒） |
| `s2_noise_sigma` | (1,) | 噪声标准差 |
| `s2_h_hat` | (63,1401) complex128 | 校准得到的 `Ĥ_i^rel(f_D)`（参考通道规范为 1） |

每个 S2 case（键前缀 `s2_042` / `s2_069`）：

| 键后缀 | 形状 | 语义 |
|---|---|---|
| `_x_cal` | (63,1401) | 减除前、校准后带内频谱 `X_i^(g,cal)(f_D)`（含噪声） |
| `_x_after` | (63,1401) | 固定 `α=1.0` 减除后频谱 `X̃_i^(g)(f_D)` |
| `_s_eff` | (1401,) | 显式色散有效模板 `Ŝ_eff^(g)(f_D)` |
| `_z_dw_before` / `_z_dw_after` | (63,41) | `W_dw,i` 41 点上的 `z_i(τ)`（归一化 `1/‖Ŝ_eff‖`） |
| `_z_after_tgt` | (63,) | `z_i(τ_i^tgt(d_hat))`（PNR/PSLR 峰值复算） |
| `_profile_d_grid_m` | (1851,) | 粗搜距离网格 0.15–2.00 m，1 mm |
| `_profile_p_norm_eff` / `_profile_p_norm` / `_profile_p_env` | (1851,) | 三个统计量的粗剖面 |
| `_d_hat_m` / `_t_anchor_s` / `_p_at_d_hat` / `_bg_proxy` | (1,) | 主峰、标量锚点、`P_norm,eff(d_hat)`、背景代理 |

S1（前缀 `s1_`）：`r_dir_m`、`tau_dir_s`、`x_air`、`x_target`、`h_rel_hat`、`x_cal`、`x_after`、`s_eff_hat`、`z_dw_before/after`、三个剖面、`p_at_d_hat`、`bg_proxy`、`d_hat_m`、`t_anchor_s`（形状同 2 路）。

所有数组 float64/complex128，无 NaN/Inf；无单位换算隐藏：长度 m、时间 s、频率 Hz、相位 rad。归一化压缩响应定义为
`z_i(τ) = (1/‖Ŝ_eff‖_B) Σ_{f_D∈B} X_i(f_D) conj(Ŝ_eff(f_D)) exp(-j2π f_R τ)`，因此可由 `_x_cal`/`_x_after`、`_s_eff`、`freq_rf_hz` 精确重算任意 `τ`（包括 `τ_i^tgt(d_hat)`、`W_dw`、`W_bg`）。

摘要口径（可独立复算）：`array_sha256 = SHA256(utf8(str(dtype)) ‖ utf8(repr(shape)) ‖ C 顺序原始字节)`；`arrays_sha256 = SHA256(按 key 升序拼接 utf8(key) ‖ utf8(array_sha256))`；文件 SHA256 为原始文件字节（`config.json` 例外，按 LF 归一化）。`case.arrays_sha256.case_arrays` 是该 case 数组集合的 `arrays_sha256`。

---

## 4. 生成器（只用于 S 阶段）

### 4.1 公共设置

- `c0=299792458 m/s`、`fs=4 GHz`、`Np=4000`、`Ts=0.25 ns`、`Tp=1000 ns`、`f_start=0.3 GHz`、`f_stop=1.7 GHz`、`A=30000`、对称 Hamming 窗。
- 频带显式取 `k=300..1700`（1401 bins；`f_D=k·1 MHz`）。注：`np.fft.rfftfreq` 的浮点端点比较会丢掉 `k=300`（1400 bins）；本实现按 PLAN §3/§5.1 的整数定义取 1401 bins，并在数组中显式给出 `band_k`，避免端点歧义。
- 阵列几何、`tx=27`、`ref=28` 与 `R_i^dir` 完全按 M0 §2.1；`R_ref^dir=0.07 m`、`τ_ref^dir=0.2334948666 ns`。
- 仅用带内复频谱生成，再 `irfft` 回 4000 点实序列；噪声在时域叠加后 `rfft` 取带内。

### 4.2 `E0-S1`

`t0_air=120.25 Ts`、`t0_tgt=250.40 Ts`、`τ_ref^hw=0.20 ns`、`H_ref=exp(+j2πf_R·0.20 ns)`、`RX=[28,12]`、`Δτ2=+0.500 ns`、`G2=1.25`、`ψ2=+0.30 rad`、`d=0.600 m`、`Γ=-0.35`、无噪声。`H_2^rel=G2·exp(-j2πf_DΔτ2+jψ2)`。

### 4.3 `E0-S2`

- **参数表**：`default_rng(20261128)`；`rx` 升序去掉 27、28；每路依次 `Δτ~U(-0.75,0.75) ns`、`G~U(0.5,1.5)`、`ψ0~U(-0.5,0.5) rad`、`ψ2~U(-0.3,0.3) rad`。规范 JSON 的 SHA256 与 `aa86bf56…6e96` 一致（测试与运行均断言）。
- **公共参考色散**：`H_ref(f)=(1+0.20u)exp(j[+2πf_R·0.20 ns+0.5u²])`，`u=(f_D-1 GHz)/0.7 GHz`。
- **触发偏移**：`air_0=120.25 Ts` 固定；随后连续抽 11 个 `U(0,Tp)`，依次给 `air_1..air_9`、目标 0.42 m、目标 0.69 m。
- **信号**：`X_i = H_i^rel·s_eff·[(1/R_i)e^{+j2πf_Rτ_i} + 1_tgt·Γ/R_i^tgt·e^{+j2πf_Rτ_i^tgt}]`，`s_eff=H_ref·S·e^{+j2πf_R t0}`；`R_i^tgt=√(R_i²+4d²)`。目标 `Γ=+0.25@0.42 m`、`Γ=-0.35@0.69 m`。
- **噪声**：`σ²=10^{-25/10}·mean_{i,m}(x_{i,0.42-only}^{echo}[m]²)`（同一 σ 用于全部 12 组）；`x^{echo}` 是 **0.42 m 纯目标回波**（`Γ=+0.25`，**不含直达波**），与裁定 §2“63 路纯回波平均时域功率”一致。直达波幅度约为回波的 20 倍，若误把直达波计入基准会把 σ 放大约 22 倍、使等效 SNR 远离 25 dB；作者测试对此有回归检查。随后按 `air_0..air_9`、0.42、0.69 的顺序各抽一次 `standard_normal((63,4000))`，行按有效 RX 升序（含参考 28）。
- **复现**：参数表、触发偏移、σ、原始/缩放噪声矩阵 SHA256 均写入 JSON；同一 numpy/运行环境下可逐位重建。

---

## 5. 估计器链路

1. **空场对齐**：以 `air_0` 为原点，粗搜用 8 倍过采样 lag 网格上的包络 `|Q(s)|`（避免 4 GHz 载波下整数样点实部振荡错峰），再在粗峰 ±1 Ts 内以 `1e-3 Ts` 细搜 `Re Q(s)`；`Q(s)=Σ_{i,f}X_i conj(A_i)e^{+j2πf_R s}`，返回 `s∈[0,Tp)`。空场对齐位移写入 JSON。
2. **校准 `M0-Cal-Base`**：`Ĥ_i^rel = X̄_i conj(X̄_ref)/(|X̄_ref|²+λ_cal P̄_ref)·(R_i^dir/R_ref^dir)·exp(-j2πf_R(τ_i^dir-τ_ref^dir))`，参考通道规范 `Ĥ_ref^rel≡1`；`X^cal=conj(Ĥ)/(|Ĥ|²+λ_inv)·X`。`λ_cal/λ_inv` 由 10 折空场 LOO 在 3×3 网格上按 PLAN §3.1 的 `J_air=median+0.5·min` 与切换规则确定性选择；S2 选中 `(1e-3,1e-3)`（default），不触发切换。S1 是 2 路无噪解析例外，按 M0 §8 取 `λ=0`。
3. **对齐减除 `M0-DW-Base`**：以校准后空场均值模板对目标组做同一 ±1 Ts 细搜，`X̃=X^cal-1.0·X̄^air,cal·e^{+j2πf_RΔt0}`；固定 `α=1.0`，无自适应缩放。
4. **有效模板**：`Ŝ_eff=Σ_i(1/R_i)X̄_i^air,cal e^{+j2πf_RΔt0}e^{-j2πf_Rτ_i}/Σ_i(1/R_i²)`（等权 `w_i=1`）。
5. **压缩响应与统计量**：按 §3 的 `z_i(τ)` 定义；`P_norm,eff(d)=|Σ_i z_i(τ_i^tgt(d))/R_i^tgt|²/Σ_i(1/(R_i^tgt)²)`；`P_norm` 用纯时延 `S` + 标量锚点 `t0_eff`；`P_env` 用非相干包络。`P_norm,eff` 为主统计量，后两者为对照。
6. **指标**：`Supp_dw-win=10log10(Σ|z_before(W_dw)|²/Σ|z_after(W_dw)|²)`（每通道 41 点、按 `Tp` 卷绕）；`BG_proxy=mean_{i,m∈[200,3800]}|z_after(mTs)|²`；`PNR=10log10(mean_i|z_after(τ_i^tgt(d_hat))|²/BG_proxy)`；`PSLR=10log10(P_norm,eff(d_hat)/max_{|d-d_hat|>0.1606031 m}P_norm,eff(d))`。`BG_proxy` 是**非目标区/晚延迟背景代理**，不宣称纯热噪声。
7. **门控**：S1 `abs_err≤0.05 cm`、`|Δτ2-0.5 ns|≤0.001 ns`（`t0_eff`/`Δt0` 为 1e-3 Ts 容差诊断项）；S2 两目标各自 `abs_err≤1.0 cm`、`Supp≥20 dB`、`PSLR≥3 dB`、`PNR≥6 dB`、`valid_rx=63`、全有限。任一失败即 JSON 记录失败并退出 1，**不自动改种子/参数/阈值重跑**。

---

## 6. 复跑、确定性与证据

```powershell
# 作者测试（含两次全量运行的确定性比对、数组独立重算、文件审计、反例）
python solutions/A/test_a_e0_s1s2.py

# 登记运行（实现提交固定后）
python solutions/A/a_e0_s1s2.py --out experiments/A/A-Q1-E0/s1s2/results `
  --implementation-sha <impl-sha> --parent-commit <parent-sha> --main-commit <main-sha>
```

- 单进程；模块在导入 numpy 前设置 `OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS=1`。
- 无随机过程之外的非确定性；同一环境下连续两次运行的数组摘要与逐案数值逐位一致（作者测试断言）。
- 峰值工作集由 Windows `psapi.GetProcessMemoryInfo` 读取；非 Windows 返回 `null` 并在 `resource` 中显式记录。
- 登记运行的环境、命令、耗时、RSS、文件 SHA256 均写入 JSON/`SHA256SUMS.txt`。

---

## 7. 已知边界与不宣称的事项

1. **仅合成**：S1/S2 通过不代表 `E0-C` 真实校准或 `E0-T` 留出会通过，更不代表真实测距精度；本实现不读取任何 `.dat`，也不产生正式测距/成像结论。
2. **S1 是明确例外**：2 路无噪解析闭环，63 路门控与 S2 回波质量门控不适用；未用补零/复制通道伪装 63 路。
3. **S2 的两目标规则不同**：0.42 m 用墙体首峰规则、0.69 m 用金属板全局 `argmax`，与 `verify_e0_spec.py` 的合成检查一致；`η_wall` 只取默认 0.25，不在 S 阶段调参。
4. **标量锚点 `t0_eff` 是诊断/对照量**：一般公共色散下它不能消去色散；主统计量使用显式 `Ŝ_eff`。`P_norm`/`P_env` 只为对照，不参与 S2 门控。
5. **背景窗不是纯噪声认证**：`BG_proxy` 可能包含有限带宽旁瓣、残余直射/色散泄漏或晚到多径；`PNR` 的解释受此限制。
6. **`PSLR` 的主瓣保护带**固定为 `1.5·c0/(2B)=0.1606031 m`；`PSLR` 用粗 1 mm 剖面的旁瓣最大值与细搜峰值计算。
7. **频带端点**：按 PLAN 的整数 `k=300..1700`（1401 bins）实现；若复核方按 `rfftfreq` 浮点掩码会得到 1400 bins（少 `k=300`），两者差异只在 0.3 GHz 单 bin；交付数组已显式给出 `band_k`/`freq_hz`，重算应以数组轴为准。
8. **噪声矩阵不逐位入库**：只入库 `σ` 与原始/缩放矩阵 SHA256；逐位复现要求同一 numpy 版本与运行环境（`default_rng` 的 PCG64 在同一环境内确定）。
9. **`E0-S` 不涉及**：空场 LOO 的 10 组真实空场、校准集 10 组目标、`E0-Freeze`、`E0-T` 单次盲评、`N0`（自适应 α、子空间、WLS、非等权）均未启用/未执行。
10. **提交范围**：本实现只改 `solutions/A/` 与 `experiments/A/A-Q1-E0/s1s2/` 结果；不修改冻结拆分、`PLAN.md`、`config.json`、D0/D1-2 生产代码或真实数据。

---

## 8. 结果摘要（登记运行）

见 `experiments/A/A-Q1-E0/s1s2/results/e0_s1s2_results.json` 与 `run.log`。摘要以 JSON 为准；本文件不重复复制可能随新 SHA 变化的数值，避免说明与结果脱节。登记运行的 `implementation_sha`、`parent_commit`、`main_commit`、`config_sha256`、数组文件 SHA256、墙钟与 RSS 均已写入 JSON 与 `SHA256SUMS.txt`。
