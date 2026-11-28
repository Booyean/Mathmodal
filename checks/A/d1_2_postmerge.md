# A-Q1-D1-2 合并后复验（POSTMERGE-1）

- **验证对象**：已合入主线的 D1-2（F1 锚包极性/包序依赖、F2 非有限值防护）及验证方证据。
- **验证方**：`my_deepseek`（独立验证）。
- **结论**：**通过，无新缺陷**。合并未改写被验生产实现或验证材料；三套件与空场 `data1` 在新主线上复跑全部通过；主线随后只前进了控制表文档，相关 blob 未变。
- **范围**：仅合成例与空场 `data1`。本报告不构成目标组、E0、全量数据或正式测距的验收。

## 1. 版本与合并链

| 项 | 提交 |
|---|---|
| 被验 D1-2 实现 head | `8b1b7454f3fd88d4a2358e949e5b9104bd9829b5` |
| 被验验证 head（PR #16） | `0dd58fba73ede2636ddef7a54f0e02857c66d7ab` |
| D1-2 实现合并（PR #14） | `2b023610a1d4fe31b0438e6891ddef00ecbb0336`（父 `012f2df8…`、`8b1b745`） |
| 验证证据合并（PR #16） | `7d1c62234f719a53b496dba088654ae8ff981090`（父 `2b02361`、`9c76ca08…`） |
| 本次复跑时的主线 | `7d1c622` |
| 当前主线（控制表更新） | `c4378992c4c7249ab0818710a360ff3bbe737f85`（父 `7d1c622`、`58d4ed3`） |
| 合并前基线 | `f56dbc0b472008f3a212bcefa47aa0392343d357` |

- `7d1c622..c437899` 只改 `coordination/A_Q1_PLAN.md`（+9/−2，记录 D1-2 验收与 E0 合成闸门），不含生产或检查代码。
- `f56dbc0..c437899` 共 15 个文件、+2946/−73，全部属于预期范围：D1-2 的 4 个实现/契约/测试文件、验证方 7 个检查文件、E0 方案 3 个文件、控制表 1 个文件。

## 2. 合并零改写核对

| 文件 | `c437899` blob | 对照 head | 结论 |
|---|---|---|---|
| `solutions/A/a_fold_gate.py` | `01be51b388819cb8…` | `8b1b745` 同 | 实现未改写 |
| `solutions/A/fold_gate_contract.md` | `c6826f66a179024e…` | `8b1b745` 同 | 契约未改写 |
| `solutions/A/test_a_fold_gate.py` | `96441f717a677b25…` | `8b1b745` 同 | 作者套件未改写 |
| `solutions/A/fold_gate_diag_data1.json` | `a11161b060d4e8a1…` | `8b1b745` 同 | 诊断 JSON 未改写 |
| `solutions/A/a_dat_reader.py` | `58fbcd6fa231e444…` | `4a21060`/`f56dbc0` 同 | D0 未被改动 |
| `coordination/A_Q1_SPLIT.json` | `2fd2ec777ba5152b…` | `f56dbc0` 同 | 冻结拆分未改动 |
| `checks/A/test_d1_2_independent.py` | `8c47b27d070c52ce…` | `0dd58fb` 同 | 独立套件未改写 |
| `checks/A/d1_2_independent_results.json` | `76733881226a1a39…` | `0dd58fb` 同 | 69/69 证据未改写 |
| `checks/A/d1_2_acceptance.md` | `4e5f524d9e68e66f…` | `0dd58fb` 同 | 验收报告未改写 |
| `checks/A/d1_2_prereg.md` | `88a2c4b2365851f9…` | `0dd58fb` 同 | 预登记未改写 |
| `checks/A/d1_2_prefix_characterization.json` | `5b04643b186314c9…` | `0dd58fb` 同 | 非空转证据未改写 |
| `checks/A/test_d1_independent.py` | `fb167bffdb32de72…` | `0dd58fb` 同 | 版本门控未改写 |

- `git diff 8b1b745 2b02361 -- solutions/A`：空，合并未引入冲突改写。
- `git diff 0dd58fb 7d1c622 -- checks/A`：空，验证材料原样入库。
- 结论：D1-2 通过的是**同一份**实现与证据，不存在“合并时顺手修改后未复测”的缺口。

## 3. 复跑结果（主线 `7d1c622`，生产/检查 blob 与 `c437899` 相同）

| 套件 | 命令 | 结果 |
|---|---|---|
| 作者 D1-2 套件 | `python solutions/A/test_a_fold_gate.py` | **91 passed / 0 failed / 0 skipped**，exit 0 |
| 我的预登记独立套件 | `python checks/A/test_d1_2_independent.py` | **69 passed / 0 failed**，1 条 info finding，exit 0 |
| D1-1 历史回归（C1 按契约版本门控） | `python checks/A/test_d1_independent.py` | **70 passed / 0 failed**，C1a/b/c/x 及同门控内的 C1y 共 5 项未执行（脚本提示只列前四项），exit 0 |

环境：CPython 3.11.5、numpy 1.26.4、Windows；作者环境为 CPython 3.13.5、numpy 2.1.3。两套栈结论一致。

### 空场 `data1` 对照

| 项 | 结果 |
|---|---|
| 诊断状态 | `status=ok`；4/4 包接受；`sync=[114,115,116,117]` |
| 锚包 | `anchor_index=1`，`anchor_sync=115`（与 D1-1/D1-2 一致） |
| `signals_folded` 形状 | `(64, 4000)`，float64，全有限 |
| 折叠 vs D1-1 已交付数组 | `max|diff| = 0.0`（逐位相同） |
| 折叠 vs D1-2 上一轮数组 | `max|diff| = 0.0`（逐位相同） |
| 提交的诊断 JSON vs 本次复跑 | 公共数值最大相对差 `1.6e-13`（绝对 `8.3e-15`），仅 numpy FFT 栈差异；判定与接受集完全一致 |
| 独立重算 `gamma/rho/delta/phi/gain` | 与实现逐项差 `0.0` |

## 4. 非阻断观察（不影响通过结论）

- **O1 证据字节不可复现（低）**：独立套件运行时会重写已跟踪的 `checks/A/d1_2_independent_results.json`；同一 head、同一环境两次运行有 **9 条记录**仅在 Python `set` 的字符串顺序上不同（`0` 条状态或数值变化，来自哈希随机化）。判定稳定，但“证据文件逐字节可复现”不成立。建议对集合字段 `sorted()` 序列化，或把结果写到未跟踪的输出路径。
- **O2 历史证据覆盖陷阱（低）**：`checks/A/test_d1_independent.py` 运行时会把 `checks/A/d1_independent_results.json` 从 D1-1 的 75 条记录改写为 D1-2 下的 70 条（C1a/b/c/x/y 按版本门控跳过）。该文件是 D1-1 历史证据，不应在 D1-2 分支上提交复跑结果；本次已恢复、未提交。建议结果路径参数化或按 head 命名。
- 两项均为**验证工具的证据卫生问题**，不涉及生产实现、数据或科学结论；不影响 D1-2 验收。

## 5. 范围与限制

- 仅覆盖 D1-2 合成例与空场 `data1` 单组；**未读取任何目标组或留出组**，不产生测距、校准或成像结论。
- D1-2 既有已知限定不变：1 对 1 极性冲突无多数时需人工复核；参考通道门控不证明 63 路全部同界。
- 合并零改写只证明“未被改写”，不替代对 D1-2 科学结论的重新裁定；原验收报告的适用范围继续有效。
- 未提交任何主线改动；本报告单独走 `check/` 分支，由统筹决定是否入库。

## 6. 复跑命令

```powershell
git switch --detach c437899   # 或 7d1c622，生产/检查 blob 相同
python solutions/A/test_a_fold_gate.py
python checks/A/test_d1_2_independent.py
python checks/A/test_d1_independent.py
python solutions/A/a_fold_gate.py --diagnose "附件2-测距数据/空场数据/data1" --json out/data1.json --npz out/data1.npz
```

## 7. 下一步

- D1-2 闸门已闭；按控制表下一闸门为 `E0-S1/S2` 的实际实现与合成闭环，由 `dsh` 交付。
- 验证方在实现 SHA 出现前先提交 `E0-PREREG-1`（S1/S2 独立验收预登记），实现交付后按预登记复跑；`E0-C`、`E0-T` 仍未放行。
