# A 题 Q2 / Q3 实测准入与执行清单

- **基线版本**：`main` = `c7b841efe67192a73a96894fb5a0243b336a9468`（`c7b841e`）
- **编制角色**：`antigravity02`（建模与论文）
- **裁定放行**：`codex`（统筹）｜ **独立验收**：`my_deepseek`
- **上游依据**：
  - [solutions/A/model_q2.md](../solutions/A/model_q2.md)（`M2-Gain-BSEC` / `M2-Img-CohBPA` / `M2-Img-EnvBPA`）
  - [solutions/A/model_q3.md](../solutions/A/model_q3.md)（`M3-Img-CohBPA3D` / `M3-Img-EnvBPA3D` / 3D-NMS / `ShadowRatio`）
  - [solutions/A/q2_q3_output_contract.json](../solutions/A/q2_q3_output_contract.json) 与 [paper/A/Q2_Q3_OUTPUT_FIGURE_CONTRACT.md](../paper/A/Q2_Q3_OUTPUT_FIGURE_CONTRACT.md)
  - [solutions/A/data_contract.md](../solutions/A/data_contract.md)（`D0-4`）、[solutions/A/fold_gate_contract.md](../solutions/A/fold_gate_contract.md)（`D1-2`）
  - [recon/reports/data_recon_report.md](../recon/reports/data_recon_report.md)（`RECON-0.1`）、[recon/manifests/a_dat_manifest.csv](../recon/manifests/a_dat_manifest.csv)、[recon/manifests/a_group_manifest.csv](../recon/manifests/a_group_manifest.csv)
- **当前状态声明**：
  1. 截至 `main = c7b841e`，Q2/Q3 仅完成**纯合成基线与契约验收**（`experiments/A/A-Q2Q3-SYN/results/`，`status = "synthetic_baseline_only"`，`real_dat_files_read = 0`）；
  2. **`附件3-成像数据` 实测尚未放行**，且主线上**尚未交付实测求解入口脚本**（当前仅有合成入口 `solutions/A/run_q2_q3_synthetic.py`）；
  3. 上游 Q1 `E0-C`（`e0c/results/` 与 `results-r2` 双跑）当前在 `C9` 触发 `hard_stop`（墙体 PSLR `2.664 dB < 3.0 dB`、空场 `min(Supp_air-LOO) = 2.9844 dB < 6.0 dB`），**尚未产生 `e0c_frozen.json`**，`E0-T` 未放行；
  4. 论文全部 Q2/Q3 槽位（`Fig 2-1`、`Fig 2-2`、`Table 2-1`、`Fig 3-1`、`Table 3-1`、`Fig 3-2`、`Table 3-2`）严格维持 `[待补]`。

---

## 1. 依赖关系与先行审批矩阵（`Q1` / `E0-T` vs 可先行项）

本节明确回答：**Q2/Q3 哪些步骤依赖 Q1 校准、哪些完全不依赖 `E0-T`、哪些可立即先行审批**。

### 1.1 总判定原则

| 依赖对象 | 是否阻塞 Q2/Q3 | 说明与边界 |
|---|---|---|
| **`E0-T`（留出测距检验，20 组）** | **不依赖** | Q2/Q3 成像输入全部来自 `附件3-成像数据`，与 `附件2` 的 `wall_test`/`metal_test` 标签及测距评估完全独立；`E0-T` 继续保持封存禁读。 |
| **`D0-4` 读取与 `D1-2` 折叠门控** | **已就绪（无阻塞）** | `a_dat_reader.py`（`D0-4`）与 `a_fold_gate.py`（`D1-2`）已在 `main` 验收合入；附件 3 数据体检与折叠预备无需等待 Q1 校准冻结或 `E0-T`。 |
| **Q1 校准与抑直模板（`h_rel_hat` / `inv_op`, `xbar_air_cal`, `S_eff`）** | **硬依赖（成像主链）** | 按 `model_q2.md §1.3` 与 `model_q3.md §2.1`，Q2/Q3 需应用 Q1 冻结的 63 路校准逆算子 $\hat{H}_i^{\text{rel}}(f_D)$、空场对齐参考 $\bar{X}_i^{\text{air,cal}}(f_D)$ 及显式模板 $\hat{S}_{\text{eff}}^{(j)}(f_D)$。当前 `E0-C` 处于 `hard_stop`（无 `e0c_frozen.json`），构成正式定稿实测的前置阻塞。 |

### 1.2 分阶段任务与建议先行审批清单

| 阶段 / 事项 | 内容 | 依赖 Q1 校准冻结？ | 依赖 `E0-T`？ | 实测读取 `.dat`？ | 建议审批策略 |
|---|---|---|---|---|---|
| **S0：契约与合成复跑** | 运行 `test_q2_q3_output_contract.py`、`validate_q2_q3_outputs.py`、`run_q2_q3_synthetic.py` | 否 | 否 | 否（0 文件） | **已批准 / 可随时复跑** |
| **S1：实测工具链实现与预检** | 新增 `a_q2q3_preflight.py`、`run_q2_q3_empirical.py`（`--mode check / d1-audit / execute` 守卫与两进程框架）、独立验收脚本及纯合成端到端测试 | 否（接口兼容 `e0c_arrays.npz` 及新版 Q1 校准产物） | 否 | `preflight` 仅校验 481 文件 `size + SHA256`（`packets_parsed=0`） | **建议立即先行审批（零信号读取）** |
| **S2：附件 3 `D0-4 + D1-2` 体检** | 仅对附件 3 481 个 `.dat` 运行协议解析、包交集对齐、第 8 组 `-32768` 坏点门控及 `signals_folded` 质量审计 | **否**（只依赖已验收 `D0-4` / `D1-2`） | 否 | 是（仅读 `附件3`，481 文件） | **建议与 Q1 改进并行先行审批**：提前确认 60 组 `valid_rx=63` 与第 8 组真实 `D1-2` 处置结果，不等待 Q1 冻结 |
| **S3-A：正式 Q2/Q3 实测（路径 I）** | 读取经 Q1 验收冻结的新版校准模板（`N0` 或升级方案冻结输出），运行 Q2 2D + Q3 3D 两进程求解与独立验收 | **是（必须等 Q1 校准冻结）** | 否 | 是（`附件3` 481 文件 + 复用已冻结 Q1 输出） | **待 Q1 校准冻结后再放行正式 `--mode execute`** |
| **S3-B：未冻结基线诊断试跑（路径 II，可选）** | 以已双跑复验的 `e0c/results-r2/e0c_arrays.npz`（`inv_op` + `xbar_air_cal`）先行跑通 Q2/Q3 诊断剖面，评估在当前弱抑直基线下墙体/金属成像实际退化表现 | 不等待冻结，但须显式挂载未冻结基线 | 否 | 是（`附件3` 481 文件 + 只读 `e0c/results-r2`） | **需 `codex` 单独裁定是否批复**；若批复，输出强制入 `diag-e0c-r2/`、`citable=false`、`status="hard_stop"`，严禁回填正式论文槽位 |

---

## 2. 输入范围与数据边界（严格白名单）

### 2.1 原件版本锚点

| 锚点 | 值 |
|---|---|
| 原始数据基线提交 | `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9` |
| A 题 `.dat` 全集清单（`recon/manifests/a_dat_manifest.csv`） | 881 文件 / 801,111,612 B，总体 SHA256 `86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06` |
| 组清单 | `recon/manifests/a_group_manifest.csv` |
| 原件约束 | 只读原件；不复制、不改名、不改写、不插补、不静默剔除 `-32768` 或孤儿文件 |

### 2.2 附件 3 允许读取白名单（481 个 `.dat` / 492,853,900 B ≈ 470.0 MiB）

| 数据集 | 磁盘相对路径（相对 A 题根目录） | 有效组数 | 文件数 | 合计字节 | 扫描坐标与已知实盘异常（来源 `RECON-0.1`） |
|---|---|---:|---:|---:|---|
| **Q2 / Q3.1 墙体** | `附件/附件3-成像数据/墙体/` | **33**（完整 8 行组） | **264** | 283,679,024 | 时间戳升序 `2026-11-12-21-29-57_16000` 至 `21-39-38_16000` 对应 $x_j = -0.20 + 0.05(j-1)\text{ m}$；**第 3 组 `21-30-33_16000` 行间包数 `3,4`** → 按 `D0-4` 共同 `sync` 交集取 `P_common = 3`。 |
| **Q3.2 金属目标** | `附件/附件3-成像数据/金属柱和金属铲/` | **27**（有效 8 行组）+ **1 孤儿** | **217**（216 + 1） | 209,174,876 | 时间戳升序 27 组 `22-05-18_16000` 至 `22-15-11_16000` 对应 $x_j = 0.05(j-1)\text{ m}$；① **0 B 孤儿文件** `2026-11-12-22-50-31_16000_7.dat`（无同前缀其余 7 行）须登记于 `orphan_skipped` 并排除于 27 组外；② **第 8 组 `22-09-58_16000` 行间包数 `3,4`**（`P_common = 3`）且 `_1.dat` 末包（`sync=250`）含 **46 个孤立 `-32768` 样点**，须按 `D1-2` 门控逐包裁决并由元数据动态写入 `anomaly_isolation`。 |
| **合计** | `附件/附件3-成像数据/{墙体,金属柱和金属铲}` | **60 有效组 + 1 孤儿** | **481** | **492,853,900** | 全部由显式组清单 + 时间戳前缀定位；**禁止调用 `a_dat_reader.discover_groups()`**（其 `rglob("*.dat")` 会枚举禁止目录）。 |

### 2.3 上游 Q1 校准输入接口

- **正式路径（S3-A）**：读取经 Q1 验收冻结的结果目录（待 Q1 改进冻结后由 `codex` 指定路径与 SHA256），加载每通道校准算子与对齐空场参考谱（及新版抑直/色散模板接口）；**不重新打开** `空场数据/data1..data10`（除非统筹另批现算核验）。
- **诊断路径（S3-B，仅当获批）**：只读挂载 `experiments/A/A-Q1-E0/e0c/results-r2/e0c_arrays.npz`（`inv_op`、`h_rel_hat`、`xbar_air_cal`、`air_shifts_s`、`freq_hz`、`freq_rf_hz`、`tau_dir_s`、`r_dir_m`）与 `e0c_results.json`，并在输出 `provenance` 中锁定其 SHA256 与 `hard_stop` 事实。

### 2.4 明确禁止读取（严格边界守卫）

| 禁止目录 / 对象 | 数量 | 边界规则 |
|---|---:|---|
| `附件/附件2-测距数据/墙体数据/` | 20 组（160 文件） | **全部禁读**（含 `wall_cal` 10 组与 `wall_test` 10 组，特别是 `E0-T` `data20-73cm` 与其余留出样） |
| `附件/附件2-测距数据/金属板数据/` | 20 组（160 文件） | **全部禁读**（含 `metal_cal` 10 组与 `metal_test` 10 组，特别是 `E0-T` `data5-60cm` 与其余留出样） |
| `附件/附件2-测距数据/空场数据/` | 10 组（80 文件） | Q2/Q3 默认直接复用 Q1 输出产物，未经另批不得重开 |
| `附件/附件1-数据读取函数/` | — | 仅协议参考，不作输入信号 |
| B 题全部数据 | — | 未选题 |

> 读前路径校验复用 `solutions/A/e0c_preflight.py` 的 `guard_group_dir()` / `guard_dat_path()`：词法归属白名单组目录 → 逐级检查非重解析点（`FILE_ATTRIBUTE_REPARSE_POINT` / 符号链接 / Windows 目录联接）→ `realpath` 包含性验证 → 仅以校验后真实路径 `stat`/`open`。

---

## 3. 入口命令、执行守卫与环境约束

### 3.1 `main = c7b841e` 现已可跑命令（零 `.dat` 读取）

```powershell
# 1) 契约与论文 7 处 [待补] 槽位自检
python solutions/A/test_q2_q3_output_contract.py

# 2) 校验已提交合成标准结果目录（应返回 ALL_Q2_Q3_CONTRACT_CHECKS_PASSED）
python solutions/A/validate_q2_q3_outputs.py --dir experiments/A/A-Q2Q3-SYN/results

# 3) Q2/Q3 合成求解 + 契约全量单测（12 项）
python -m unittest discover -s solutions/A -p "test_*q2*q3*.py" -v
```

### 3.2 待实现并经审批后放行的实测入口规范（对齐 `E0-C` 守卫体系）

在进入实测前，须先行完成并验收以下入口模块（推荐放在 `solutions/A/`，不破坏既有合成脚本）：

1. **实测预检脚本 `solutions/A/a_q2q3_preflight.py`**（零采样解析，`packets_parsed = 0`）：
   ```powershell
   python solutions/A/a_q2q3_preflight.py `
     --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" `
     --q1-dir <approved-q1-results-dir> `
     --out experiments/A/A-Q2Q3-EMP/preflight.json
   ```
   - 核验 481 个白名单 `.dat` 存在性、字节数与 `recon/manifests/a_dat_manifest.csv` SHA256 逐一匹配；核验反重解析点路径守卫 `rejections == []`；核验 Q1 锚点与 `D0-4` / `D1-2` 合同版本。
2. **实测求解主入口 `solutions/A/run_q2_q3_empirical.py`**（支持 `--mode check | d1-audit | execute`）：
   - **环境硬约束**（导入 `numpy` 前设定）：
     ```powershell
     $env:OMP_NUM_THREADS="1"; $env:OPENBLAS_NUM_THREADS="1"
     $env:MKL_NUM_THREADS="1";  $env:NUMEXPR_NUM_THREADS="1"
     ```
   - **安全守卫（照搬 `a_e0_c.py` 经验证矩阵）**：
     - `--mode check`：只跑 `preflight` + 锚点/参数检查，不读 `.dat` 采样，返回 `ready_for_execute`；
     - `--mode d1-audit` / `--mode execute`：强制要求 `--approval-ref <codex 放行编号>`，缺失直接退出码 `2`；
     - 目标目录已存在结果文件时，无 `--overwrite` 直接退出码 `2`（禁止覆盖既有证据）；
     - 正式 `--mode execute` 强制 `--repeat-runs 2`（两独立子进程顺序执行，第 1 次写主输出目录，第 2 次写 `repeat_runs/run-2/`，其余值退出码 `2`）；
     - 必须从干净代码提交（`git status --porcelain` 为空）通过独立 worktree 检出执行，显式传入完整 40 位 `--implementation-sha`、`--parent-commit`、`--main-commit`。
   - **建议执行命令模板（获批后使用）**：
     ```powershell
     # 阶段 S2（若批复先行体检）：仅 D0-4 + D1-2
     python solutions/A/run_q2_q3_empirical.py --mode d1-audit `
       --approval-ref <codex-d1-audit-approval-ref> `
       --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" `
       --out experiments/A/A-Q2Q3-EMP/d1_audit `
       --implementation-sha <impl-sha> --parent-commit <parent-sha> --main-commit <main-sha>

     # 阶段 S3-A（Q1 冻结后正式全量实测，两独立进程）
     python solutions/A/run_q2_q3_empirical.py --mode execute `
       --approval-ref <codex-q2q3-approval-ref> `
       --repeat-runs 2 `
       --q1-dir <approved-frozen-q1-dir> `
       --data-root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题" `
       --out experiments/A/A-Q2Q3-EMP/results `
       --implementation-sha <impl-sha> --parent-commit <parent-sha> --main-commit <main-sha>
     ```

---

## 4. 输出目录规划与文件契约

### 4.1 目录隔离（严禁混写或覆盖）

| 目录 | 用途 | 状态 |
|---|---|---|
| `experiments/A/A-Q2Q3-SYN/results/` | 纯合成标准契约基线（`5596e34` / `8bc9566`） | **只读保留，禁止覆盖** |
| `experiments/A/A-Q2Q3-EMP/d1_audit/` | 阶段 S2 附件 3 `D0-4 + D1-2` 体检与异常核真产物 | 待批复 S2 后生成 |
| `experiments/A/A-Q2Q3-EMP/diag-e0c-r2/` | （仅若 S3-B 获批）基于未冻结 `e0c/results-r2` 的诊断试跑产物 | `citable = false`，禁入正式论文 |
| `experiments/A/A-Q2Q3-EMP/results/` | 阶段 S3-A 正式 Q2/Q3 实测交付目录（含 `repeat_runs/run-2/`） | 待 Q1 冻结与 S3-A 放行后生成 |

### 4.2 正式实测交付清单（`experiments/A/A-Q2Q3-EMP/results/`）

严格对齐 [q2_q3_output_contract.json](../solutions/A/q2_q3_output_contract.json) 与 `.gitattributes` LF 锁定策略：

| 文件 | 必需内容与契约锁定点 |
|---|---|
| `q2_results.json` + `q2_arrays.npz` | 网格 `161×251`（`[-0.20,1.40]×[0.00,2.50] m`, `dx=dy=0.01 m`）；第 4 行 7 路主剖面（`image_before_gain_coh`, `image_after_gain_coh`, `image_after_gain_env`）与第 3/5 行 8 路 3D 校正剖面（`image_row3_coh`, `image_row5_coh`）；`tau_curve_s`, `w_comp_curve`；`gain_selection`、`wall_a_apparent`、`wall_b_apparent`、`row_consistency`。 |
| `q3_wall_results.json` + `q3_wall_arrays.npz` | 网格 `81×126×31`（`2 cm` 均匀步长）；`image_3d_coh`, `image_3d_env`；按 `slice_z4_spec` 线性插值提取 `slice_xy_z4`（$z=0.545\text{ m}$）；`proj_xy_max`, `proj_xz_max`, `proj_yz_max`；`wall_a_3d`, `wall_b_3d`, `q2_q3_reconciliation`。 |
| `q3_metal_results.json` + `q3_metal_arrays.npz` | 网格 `66×126×31`（`2 cm` 均匀步长）；`image_3d_coh`, `image_3d_env`, `image_3d_shadow_gain`, `y_wall_band_m`, `shadow_profile_x_y`；真实 `anomaly_isolation` + `provenance`（由 `D0-4`/`D1-2` 动态生成）；`metal_objects[]`、`shadow_diagnostics[]`、`shadow_unocc_global_med`、`shadow_profile_axis_spec`、`resolution_limits`。 |
| `preflight.json`、`q2q3_repeat.json`、`run.log`、`SHA256SUMS.txt` | 含 `approval_ref`、`inputs[481]`（实测 `.dat` 路径/字节/SHA256）、两独立进程 `runs[2]` 清单（`pid` / 时间窗 / 结果与数组 SHA256）、`SHA256SUMS.txt`（LF 锁定，覆盖全部交付 JSON/NPZ/日志）。 |
| **顶层元字段约束** | 40 位 `implementation_sha`、`provenance`（含 `q1_source_dir` 与 `q1_arrays_sha256`）、`real_dat_files_read == 481`（Q2 33 组 264 + Q3-Metal 27 组与 1 孤儿 217，各束可分别记录或合并总计）、`arrays_sha256_scope`、`finite == true`、`status` ∈ `status_enum`（实测待验 `"empirical_pending_acceptance"` → 验收通过 `"empirical_accepted"`；诊断或失败 `"hard_stop"`）。 |

---

## 5. 独立验收条件与硬停止条件

### 5.1 工程、安全与数据边界硬门禁（任一失败立即 `hard_stop`）

1. **越界零容忍**：全程未 `open`/`stat`/`glob` 任何 `附件2` 文件（尤其 `wall_test` / `metal_test` / `E0-T`）；`path_guard.rejections == []`；481 个读取文件与 `recon/manifests/a_dat_manifest.csv` 逐一匹配。
2. **D0-4 / D1-2 全员合规**：
   - 有效接收通道恒为 **63/63**（`valid_rx == 63`，禁止静默丢通道或插补）；
   - 墙体 33 组（第 3 组 `P_common = 3`）与金属 27 组（第 8 组 `P_common = 3`）全部通过 `D1-2` 门控并产出全有限 `signals_folded`；
   - `anomaly_isolation` 如实登记 1 个 0 B 孤儿文件（`2026-11-12-22-50-31_16000_7.dat`）及第 8 组 `_1.dat` `sync=250` 46 个 `-32768` 样点的 `D1-2` 实际裁决结果，且每项具备 `{source_path, field, derivation}`。
3. **跨进程复现与台账**：`runs[2]` 的 `pid` 不同、时间窗顺序不重叠、标量指标与定位误差在 `rtol <= 1e-9` 内一致；`SHA256SUMS.txt` 干净检出（含 Windows `core.autocrlf=true`）100% 原始字节命中；`validate_q2_q3_outputs.py` 与独立复验脚本全项通过。

### 5.2 物理可解释性与定量门槛（继承 `model_q2.md` / `model_q3.md`）

| 模块 | 验收项与门槛 | 不通过时的处置（禁止调阈值凑数） |
|---|---|---|
| **Q2 增益与成像** | ① $1.0 \le W_{\text{comp}}(\tau) \le G_{\text{cap}} = 20.0$；② 无真值拐点选参 $\Delta_{\text{far/near}}$ 改善且 $C_{\text{far/med}}$ 未较峰值跌落 $>1.5\text{ dB}$；③ 第 3/4/5 行跨行 3D 校正后后墙定位差 `max_row_diff_cm <= 2.0 cm`；④ 分区报告前墙 A、后墙 B 空气段 vs 穿墙段视在深度及 $\hat{\varepsilon}_r$ 诊断。 | 若 `CohBPA` 劣于 `EnvBPA` 或跨行差 `> 2.0 cm` 或远场增益后仍无法辨识后墙 B，不得放宽门槛或手动改坐标窗口，须如实登记相干退化/杂波受限诊断并停机上报 `codex`。 |
| **Q3.1 墙体 3D** | ① `slice_xy_z4` 严格等于 `image_3d_coh` 按 `slice_z4_spec` 线性插值；② 三视图投影恒等式误差 $\le 10^{-12}$；③ 与 Q2 $z=0.545\text{ m}$ 切片空气段位置交叉对账 `air_segment_max_diff_cm <= 2.0 cm`。 | 若 `air_segment_max_diff_cm > 2.0 cm` 或全高一致性异常，核查 Q2/Q3 行间相位/增益传递差异，不静默修改插值规则。 |
| **Q3.2 金属目标与阴影** | ① 3D-NMS 分离双金属目标（立柱 vs 金属铲），主峰与 $-10\text{ dB}$ 质心落入各自包围盒；② 分列 XY（延展立柱）与 3D（紧凑金属铲）与 $\Delta\hat{z}_{10\text{dB}}$，并附 `resolution_limits`（$y=2\text{ m}$ 处 $\Delta z \approx 0.41\text{ m}$）；③ `shadow_unocc_global_med` 严格按排除全目标横向包围盒并集独立复算一致；④ 各目标 `ShadowRatio` 按 $\pm 0.45\text{ m}$ 局部侧带独立复算一致，核查 `ShadowRatio <= -6.0 dB` 与后方多径虚像边界。 | 若仅检出单目标或阴影比未达预期，须据实记录目标散射/遮挡实测现象及多径干扰边界，禁止硬编码目标框坐标。 |

---

## 6. 论文图表槽位映射（全部实测槽位当前维持 `[待补]`）

回填前铁律：所有图/表仅允许引用**经 `my_deepseek` 独立复验通过且由 `codex` 合入 `main` 的实测交付目录**，表格换算严格执行 `value_cm = value_m * 100.0`，NPZ 能量按线性存储并在绘图时依锁定 $I_{\text{ref}}$ 转 dB。

| 论文槽位 | 正文位置 | 绑定交付文件与必需字段 / 数组 | 绘图与单位口径（锁定） | 当前状态 |
|---|---|---|---|---|
| **`Fig 2-1`** | §6.4 | `q2_arrays.npz`: `x_grid_m`, `y_grid_m`, `image_before_gain_coh`, `image_after_gain_coh`<br>`q2_results.json`: `wall_a_apparent`, `wall_b_apparent` | $I_{\text{ref,Q2}}=\max(I_{\text{2D}}^{\text{coh}})$ 转 dB；坐标 $\text{cm}$；共享色标 1×2 热图 + 代表纵切线截面 | **`[待补]`** |
| **`Fig 2-2`** | §6.4 | `q2_arrays.npz`: `x_grid_m`, `y_grid_m`, `image_after_gain_coh`, `image_row3_coh`, `image_row5_coh`, `tau_curve_s`, `w_comp_curve`<br>`q2_results.json`: `row_consistency`, `gain_selection` | 左：第 4 行 vs 第 3/5 行一致性对照（$\text{cm}$）；右：$\alpha_{\text{gain}}$ 选参拐点曲线（$\text{ns}^{-1}$, $\text{dB}$） | **`[待补]`** |
| **`Table 2-1`** | §6.4 | `q2_results.json`: `metrics_before_gain`, `metrics_after_gain_coh`, `metrics_after_gain_env`, `wall_a_apparent`, `wall_b_apparent` | 对比 `未增益` / `CohBPA` / `EnvBPA`；列含 $\Delta_{\text{B/A}}, \text{PBR}_B, \text{PSLR}_B$, 覆盖率, $y_A(x)$, $y_B^{\text{air}}$, $y_B^{\text{behind-A}}$, $\hat{\varepsilon}_r$（须标视在深度边界） | **`[待补]`** |
| **`Fig 3-1`** | §7.2–§7.4 | `q3_wall_arrays.npz`: `image_3d_coh`, `proj_xy_max`, `proj_xz_max`, `proj_yz_max`, `slice_xy_z4`<br>`q3_wall_results.json`: `slice_z4_spec`, `wall_a_3d`, `wall_b_3d` | $I_{\text{ref,Q3}}=\max(I_{\text{3D}}^{\text{coh}})$ 转 dB；3D $-10\text{ dB}$ 等值面 + 三视图投影切片（$\text{cm}$） | **`[待补]`** |
| **`Table 3-1`** | §7.4 | `q3_wall_results.json`: `wall_a_3d`, `wall_b_3d`, `q2_q3_reconciliation` | 前墙 A / 后墙 B（空气段 / 遮挡段）包围盒、前界面方程、与 Q2 $z_4$ 切片偏差（$\text{cm}$）及 `CohBPA3D/EnvBPA3D` 对比度 | **`[待补]`** |
| **`Fig 3-2`** | §7.3–§7.4 | `q3_metal_arrays.npz`: `x_grid_m`, `y_grid_m`, `z_grid_m`, `y_wall_band_m`, `image_3d_coh`, `shadow_profile_x_y`<br>`q3_metal_results.json`: `shadow_unocc_global_med`, `shadow_profile_axis_spec`, `metal_objects[]`, `shadow_diagnostics[]` | 左：双金属 3D 高亮等值面（$I_{\text{ref,Q3}}$）与质心/包围盒；右：整图后墙阴影剖面（`0 dB = shadow_unocc_global_med`），叠加 `shadow_diagnostics[m].shadow_ratio_db`（**图注须明示分目标 `i_unocc_med` 采用 $\pm 0.45\text{ m}$ 局部侧带及其与整图 `0 dB` 参考差异**） | **`[待补]`** |
| **`Table 3-2`** | §7.4 | `q3_metal_results.json`: `metal_objects[]`, `shadow_diagnostics[]`, `anomaly_isolation` | 分列“主峰 vs $-10\text{ dB}$ 质心”与“XY（立柱）vs 3D（金属铲）”口径，含 $\Delta\hat{z}_{10\text{dB}}$、`ShadowRatio` 及第 8 组/孤儿异常处置结论 | **`[待补]`** |
