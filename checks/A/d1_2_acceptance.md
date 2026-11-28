# D1-2 独立验收报告（F1 锚包极性/顺序依赖、F2 非有限值防护）

- **报告编号**：D1-2-ACCEPT-1
- **验证方**：`my_deepseek`（独立验证）
- **被验对象**：`data/a-q1-fold-gate-d1-2` @ `8b1b7454f3fd88d4a2358e949e5b9104bd9829b5`（作者 `moneyforever`，提交时间 2026-11-28 10:38:21 +0800）
- **基线**：`f56dbc0b472008f3a212bcefa47aa0392343d357`（`main`，PR #13 后）；`8b1b745` 的唯一父提交就是 `f56dbc0`
- **预登记**：`checks/A/d1_2_prereg.md`（D1-PREREG-2，21 条硬性性质 + 合成例解析预期）
- **结论**：**通过，无阻断缺陷**。预登记套件 **69/69 硬性检查通过**（1 条 info 观测）；作者套件 **91/91**；版本门控后的 D1-1 套件 **70/70**；`data1` 折叠与 D1-1 **逐位相同**。

---

## 0. 时间线披露（如实记录）

- 本验证方的预登记提交 `3530260` 时间为 **10:40:24 +0800**；D1-2 作者提交 `8b1b745` 时间为 **10:38:21 +0800**（早约 2 分钟）。
- 预登记定稿前最后一次 `git fetch` **未返回** D1-2 分支；本文件与套件在查看 D1-2 内容前已写定，之后未修改任何验收口径。
- 但「预登记绝对早于实现」的说法不成立，已在 `d1_2_prereg.md` 末尾更正并披露。D1-2 分支在提交后复查时才出现，随即开始复验。

## 1. 交付范围与版本

| 项 | 实测 |
|---|---|
| 变更范围 | `f56dbc0..8b1b745` 仅 4 个文件：`a_fold_gate.py`、`fold_gate_contract.md`、`fold_gate_diag_data1.json`、`test_a_fold_gate.py`；未改 D0 读取器、检查目录、数据与清单 |
| 行数 | `+306 / −54`（实现 +132/−35；契约 +45/−16；诊断 JSON +10/−2；作者测试 +119/−1） |
| 版本 | `CONTRACT_VERSION = "D1-2"`；契约头改为 D1-2，补记 F1 新锚包评分、F2 原因码/字段、F3 范围 |
| 是否引入补偿 | **否**：折叠仍为 `seg.mean(axis=1)` 等权平均；未新增旋转/时移/重采样；F1-5 与 `data1` 逐点验证 |
| 是否读取留出数据 | **否**：只用合成例与空场 `data1` |

## 2. 预登记性质逐项结果

### F1（6/6 通过）

| 编号 | 期望 | 实际 | 结果 |
|---|---|---|---|
| P-F1-1 | 翻转包在位置 0/1/2/3 时接受 3 个一致包，锚包在一致簇，翻转包以 `inter_packet_phase_offset` 拒绝，折叠=`s` | 4/4 满足，`max|diff|=0` | PASS |
| P-F1-2 | 3 翻转 + 1 正常：接受多数簇 3 包，输出 `±s` | 接受 3，拒绝 1，`abs` 逐点等于 `abs(s)` | PASS |
| P-F1-3 | 2 vs 2：只接受同簇 2 包，重复调用确定 | 2 包，两次调用逐位一致 | PASS |
| P-F1-4 | 3 `s` + 翻转 + 20 ps 延迟的 5 种循环顺序：接受集按标签不变，折叠=`(3s+d)/4` | 5/5 满足，`max|diff|=0` | PASS |
| P-F1-5 | 锚包不得来自被拒簇 | 4 个位置均满足 | PASS |
| P-F1-6 | 不得补偿：接受包原始段等权平均 | 2 包 `[s,d]` 折叠=`(s+d)/2` 逐点相等；5 包循环亦同 | PASS |

补充独立探针（未依赖作者测试）：

- **24 种包顺序**（1 翻转 + 3 一致）：`bad=0`，接受集与折叠输出全部一致；
- **3 翻转 + 2 正常**：接受多数簇 3 包，锚包在多数簇，输出 `±s`；
- 作者自己的 F1 测试也覆盖 24 序与 1v1；本报告以独立探针为准。

### F2（7/7 通过，含 1 条 info）

| 编号 | 期望 | 实际 | 结果 |
|---|---|---|---|
| P-F2-1 | 非有限输入不得产生非有限输出 | `NaN`/`Inf` 非参考通道：坏包被拒，输出全有限；单坏包：`FoldGateError` | PASS |
| P-F2-2 | 异常显式 | 新原因码 `packet_nonfinite_samples`，`packet_finite=False`，`nonfinite_channels=[5]`；参考通道优先 `reference_channel_nonfinite` | PASS |
| P-F2-3 | 坏包隔离（质量项） | 坏+好包时好包仍接受并进入折叠，输出=`s` | PASS |
| P-F2-4 | 参考通道语义保持 | `reference_channel_nonfinite` 优先，好包仍接受 | PASS |
| P-F2-5 | `channel_valid=False` 的 NaN 通道不污染输出 | 两个含 NaN 的包均整包拒绝并抛 `FoldGateError`，无污染输出 | PASS（1 条 info：整组拒绝） |
| P-F2-6 | 诊断 JSON 无裸 `NaN` | `_json_ready` 后 `json.dumps(allow_nan=False)` 成功；`ref_rms` 非有限转 `null` | PASS |
| P-F2-7 | 输入不可变 | 所有 F2 用例前后逐元素相等（含 `equal_nan`） | PASS |

**info 观测**：当 `channel_valid=False` 的通道含 `NaN` 时，实现仍按「64 通道全有限」整包拒绝；D0 `int16` 路径不可达，且与契约 §3.1 的新判据一致，不构成缺陷。若未来外部浮点输入要保留这类组，可改为「无效通道先零化再判有限」，属后续可选改进。

### 回归（8/8 通过）

| 编号 | 期望 | 实际 | 结果 |
|---|---|---|---|
| P-R-1 | `data1` 4/4 接受，`sync=[114,115,116,117]` | 一致 | PASS |
| P-R-2 | 折叠=接受包双重平均、`(64,4000) float64`、全有限 | `max|diff|=0` | PASS |
| P-R-3 | 锚包相对 `rho/delta/phi/gain` 独立一致 | 差值上限 `rho≤1e-10`、`delta≤1e-3 ps`、`phi≤1e-9 rad`、`gain≤1e-9 dB`，实测 **0.0** | PASS |
| P-R-4 | 阈值不变 | `(0.99,0.95,0.99,50,0.1,3)` | PASS |
| P-R-5 | 版本 D1-2，契约同步 | 实现/契约/诊断 JSON 均为 D1-2 | PASS |
| P-R-6 | 确定性 | 两次折叠逐位相同 | PASS |
| P-R-7 | 作者套件 0 failed | **91 passed / 0 failed / 0 skipped** | PASS |
| P-R-8 | 历史套件 C1 版本门控 | D1-2 上 C1 系列跳过，其余 **70 passed / 0 failed** | PASS |

## 3. 空场 `data1` 数值与 D1-1 对账

- **折叠数组**：D1-2 与 D1-1 在同一份 `data1` 上逐位相同（`np.array_equal=True`，`max|diff|=0.0`），`accepted` 与 `sync` 相同；锚包仍为 `index=1`（`sync=115`）。
- **提交的诊断 JSON vs D1-1**：公共数值字段最大相对差 **0.0**；差异只有 `contract_version`、`gate.rationale` 与新增字段 `packet_finite`/`nonfinite_channels`。
- **本机复跑 vs 提交的 D1-2 JSON**：`status=ok`、锚包、接受集完全一致；数值最大相对差 `1.6e-13`（绝对值 `8.3e-15`，来自 numpy FFT 版本差异，与 D1-1 时结论一致）。
- `segment_coherence` 与独立重算的最大差 `0.0`；`gamma_ref` 最大差 `0.0`；各包 `rho/delta/phi/gain` 与独立实现逐项差 `0.0`。

## 4. 代码审查要点

- **F1 评分与门控同尺**：`_select_anchor` 以候选为锚调用与 §3.2 相同的 `rho/delta/phi/gain` 判据统计 `n_ok`，再按 `(n_ok, median_rho, -index)` 取最大；并列规则确定，写入契约 §3.2。
- **不伪造多数**：1v1 无多数时只保留序号较小一侧，契约明确标为「无法判定、需人工复核」，不混合两侧、不抵消。
- **F2 双保险**：包级拒绝（`packet_nonfinite_samples`）在前，折叠后 `np.isfinite` 不变量在末；后者抛 `RuntimeError` 而非 `FoldGateError`，避免被 `diagnose` 误报为 `all_rejected`，符合契约 §4.4。
- **原因码**：实现中 10 个原因码全部在契约 §3.3 表中；新增码命名与 `nonfinite` 语义一致。
- **无旁路**：未改 D0、未改阈值、未改折叠公式；`_rho`/`_gain_db` 对非有限输入返回 0/None 只影响不可达路径。

## 5. 非阻断项与建议

1. **info（F2-5）**：无效通道含 `NaN` 时整组拒绝。可达性为零（D0 `int16`），记录备查。
2. **1v1 并列**：只保留序号较小一侧。已写入契约「已知限制」，真实数据若出现应人工复核；不属本轮缺陷。
3. **F3 范围**：契约已明确包间门控只以参考通道为判据，不等于全通道一致性；下游与论文不得把它写成全通道保证。
4. **`data1` 锚包未变**：D1-2 诊断数字与 D1-1 相同，这是预期结果，不是「未生效」；F1 的差异只在极性/顺序用例中体现。
5. **格式**：契约末尾仍无换行（D1-1 起如此），纯格式，不阻断。

## 6. 复跑与证据

```powershell
# 被验提交
git switch --detach 8b1b7454f3fd88d4a2358e949e5b9104bd9829b5

# 预登记独立套件（本报告结果：69/69，1 info）
python checks/A/test_d1_2_independent.py

# 作者套件（91/91）
python solutions/A/test_a_fold_gate.py

# 版本门控后的 D1-1 套件（70/70）
python checks/A/test_d1_independent.py

# data1 诊断复跑
python solutions/A/a_fold_gate.py --diagnose "附件2-测距数据/空场数据/data1" --json out/d1_2.json
```

| 交付/证据 | 位置 |
|---|---|
| 预登记 | `checks/A/d1_2_prereg.md` |
| 独立套件 | `checks/A/test_d1_2_independent.py` |
| D1-2 逐项结果（69/69） | `checks/A/d1_2_independent_results.json` |
| D1-1 非空转证据（58/18） | `checks/A/d1_2_prefix_characterization.json` |
| 准备阶段报告 | `checks/A/d1_2_readiness.md` |
| 历史套件版本门控 | `checks/A/test_d1_independent.py` |

## 7. 结论与下一步

**D1-2 通过独立验收，无阻断缺陷。** 建议统筹：

1. 为 `data/a-q1-fold-gate-d1-2` @ `8b1b745` 开 PR 并合并；合并时保留上述 4 个实现/契约/测试文件，验证文件与本报告另行走 `check/` 分支（本分支 `check/a-q1-d1-2-verify`）。
2. 合并后由 `my_deepseek` 在新 `main` 上做一次合并后复跑（D1-2 套件 + 作者套件 + `data1` 折叠逐位对照）。
3. E0 仍按控制表未批准；D1-2 通过不构成 E0 放行，也不构成全通道一致性或正式测距结论。

**已知限制**：真实数据只覆盖空场 `data1` 一组；`data1` 是静止空场，不含墙体/金属板回波；因此本验收只证明门控与防护逻辑，不证明目标场景性能。
