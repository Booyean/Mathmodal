# D1-2 验收准备报告：预登记、非空转证明与主线合并复测

- **报告编号**：D1-2-READY-1
- **验证方**：`my_deepseek`（独立验证）
- **日期**：2026-11-28
- **主线基线**：`f56dbc0b472008f3a212bcefa47aa0392343d357`（PR #13 后）
- **状态**：**D1-2 实现尚未推送**，新 SHA 复验被依赖阻塞；本轮完成可先行开展的验收准备，且已在 D1-1 上证明套件非空转。

---

## 1. 结论摘要

1. **主线合并复测通过**：`main=f56dbc0` 上 D1 独立套件 **75/75**、作者合成套件 **55/55**、M0 闭环 **18/18**；PR #12 的合并未改实现/测试/诊断 JSON 的 blob。
2. **D1-2 尚未交付**：远端 `data/a-q1-fold-gate` 仍为 `a292ace`（D1-1），无 D1-2 分支；数据方上一条消息为 Harness 失败片段，无提交号。因此「对新 SHA 独立复验」当前无验收对象。
3. **已按顺序先做预登记**：提交 `checks/A/d1_2_prereg.md`（D1-PREREG-2），固定 F1/F2 的 21 条硬性性质与合成例解析预期，**提交时远端不存在任何 D1-2 实现**。
4. **套件已就绪并证明非空转**：`checks/A/test_d1_2_independent.py` 在 D1-1 上 **58 passed / 18 failed**，失败点恰为预登记的 F1（翻转包位于首位时）与 F2（非有限值污染）以及版本号；全部 D1-1 回归项通过。
5. **套件可满足性已验证**：用私有 shim（**未提交、非生产代码**）实现最小 F1/F2 修复后，D1-2 套件 **68/68 通过**，版本门控后的 D1-1 套件 **70 passed / 0 failed**，证明预登记口径不是无法达成的过约束。

## 2. 主线 `f56dbc0` 合并完整性与复测

### 2.1 合并结构

- `dfdae8e`（PR #12 merge）父提交：`4a21060`（旧主线）与 `ae716c3`；`ae716c3` 先后合并 `data/a-q1-fold-gate`（`a292ace`）与 `validator/d1`（`1c44427`）。
- `f56dbc0`（PR #13）只改 `coordination/A_Q1_PLAN.md`（+9/−1），未触碰代码与检查文件。

### 2.2 blob 对账

| 文件 | `a292ace` / `1c44427` | `f56dbc0` | 结论 |
|---|---|---|---|
| `solutions/A/a_fold_gate.py` | `eea8fd89…` | `eea8fd89…` | 实现未被合并改写 |
| `solutions/A/test_a_fold_gate.py` | `8781e061…` | `8781e061…` | 作者测试未被改写 |
| `solutions/A/fold_gate_diag_data1.json` | `7270ff76…` | `7270ff76…` | 诊断 JSON 未被改写 |
| `solutions/A/fold_gate_contract.md` | `d6437902…` | `475e9ccb…` | 仅追加统筹 F1/F2/F3 补记 4 行 |
| `checks/A/d1_acceptance.md`、`test_d1_independent.py`、`d1_prereg*.md/json/py`、`d1_independent_results.json` | `1c44427` 的 blob | 逐一相同 | 验证交付原样入库 |
| `checks/A/verify_split0.py`、`split0_verification.md`、`split0_results.json` | `92548d4` 的 blob | 逐一相同 | SPLIT0 交付原样入库 |

### 2.3 复跑（本机 CPython 3.11.5 / numpy 1.26.4，与作者 3.13 / 2.1.3 不同栈）

| 套件 | 命令 | 结果 |
|---|---|---|
| D1 独立验收 | `python checks/A/test_d1_independent.py` | **75 passed / 0 failed / 3 findings**，exit 0 |
| 作者 D1 合成+`data1` | `python solutions/A/test_a_fold_gate.py` | **55 passed / 0 failed / 0 skipped**，exit 0 |
| M0 闭环 | `python checks/A/test_m0_claims.py --spec solutions/A/model_q1.md` | **18/18**，exit 0 |

- `data1` 仍为 4/4 接受、锚包 `sync=115`、折叠值与双重平均逐点相等、`(64,4000) float64` 全有限。
- **环境限制（如实记录）**：本工作区为稀疏检出，`附件2` 仅落下 `空场/data1`、`墙体/data1-42cm`、`金属板/data1-69cm` 三组，其余 47 组未物化；`test_d0_independent.py` 与 `verify_split0.py` 需要全量目录，本轮**未重跑**这两套（上一轮已在完整挂载上通过 50/50、15/15）。`f56dbc0` 未改动 D0/SPLIT0 相关代码或清单，故不构成新风险；如统筹需要，可在 D1-2 合并前一并重跑。

## 3. D1-2 验收对象缺失（阻断项）

`git ls-remote --heads origin` 的远端分支中，D1 相关只有：

- `refs/heads/data/a-q1-fold-gate` = `a292aceaece7bd4fe3b66ef9ff68a2bcf7582669`（D1-1，2026-11-28 首提交）；
- 无 `data/a-q1-fold-gate-d1-2`、无新提交。

频道中数据方最后一条消息为 `DeepSeek Harness failed (unknown)` 的实现推理片段，没有 D1-2 提交号、分支或补丁。故本轮**不能**声称 D1-2 已复验；也不能把 D1-1 的 75/75 当作 D1-2 通过。

## 4. 预登记（D1-PREREG-2）

文件：`checks/A/d1_2_prereg.md`。要点：

- **范围**：只验 D1 门控；真实数据只限空场 `data1`；不读取留出组、不做 E0 实测、不改生产实现。
- **F1（P-F1-1..6）**：翻转包位于任意位置时接受集必须为 3 个一致包；多数在翻转侧时接受多数簇；2v2 并列须确定；5 包换序接受集按标签不变；锚包不得来自被拒簇；**所有折叠值必须逐点等于接受包原始段的等权平均（禁止时移/相位补偿）**。
- **F2（P-F2-1..7）**：任何输入下输出不得含非有限值；异常必须显式登记（包级 `nonfinite` 原因或通道级零化+`channel_valid=False`）；参考通道既有语义保持；`channel_valid=False` 的 NaN 通道不得污染输出；诊断 JSON 无裸 `NaN`；输入不可变。
- **回归（P-R-1..8）**：`data1` 4/4、折叠=双重平均、锚包相对 `rho/delta/phi/gain` 独立一致、阈值与版本、确定性、作者套件 0 failed。
- **合成例解析预期**：`rho(d,s)=0.998708955866344`、`delta(d,s)=20.00052565981888 ps`、`phi=4.68e-06 rad`；`(3s+d)/4` 前 8 点 `[-187.0, -625.75, 1023.75, 5829.25, -3419.5, -7489.0, 3970.75, 1761.5]`（由独立 probe 计算，不导入生产代码）。

## 5. 非空转证明（D1-1 上运行预登记套件）

命令：`python checks/A/test_d1_2_independent.py`（D1-1，`a292ace`/`f56dbc0`）

**结果：58 passed / 18 failed / 0 findings**（逐项见 `checks/A/d1_2_prefix_characterization.json`）。失败分布与预登记完全对应：

| 类别 | 失败数 | 具体 |
|---|---|---|
| F1 顺序依赖 | 6 | 翻转包位于位置 0 时，锚包选中翻转包、只接受 1 包、折叠值为 `-s`（`max|diff|=24000`）；5 包循环中翻转包在首位时同样失败 |
| F2 非有限污染 | 11 | `NaN`/`Inf` 非参考通道、只有坏包、`channel_valid=False` 的 NaN 通道：`signals_folded` 出现非有限值且拒绝原因为空 |
| 版本 | 1 | `CONTRACT_VERSION` 仍为 `D1-1` |
| 其余 F1/F2 | 0 | 翻转包不在首位、多数翻转、2v2、参考通道 NaN、正常输入均通过 |
| 回归（`data1`/阈值/账本/dtype） | 0 | 16 项全部通过 |

这说明：套件能精确定位 F1/F2，而不是把 D1-1 的正常行为判错；若 D1-2 只改代码不改语义，回归项不会误报。

## 6. 可满足性验证（私有 shim，不提交）

为避免预登记写出「任何实现都过不了」的过约束，在 `_tmp/fixcheck`（**工作区外临时目录，未进入仓库，未修改生产文件**）复制实现并做最小修复：

1. 含非有限样本的包以新原因 `packet_nonfinite_sample` 拒绝（参考通道原因优先保留）；
2. 锚包改为「以该包为锚时通过全部包间门控的同伴数」最大者，并列取 `rho` 中位数，再取最小序号；
3. 折叠返回前 `np.isfinite` 守卫；
4. `CONTRACT_VERSION="D1-2"`。

结果：

- D1-2 预登记套件：**68 passed / 0 failed / 2 findings**（两条为「整组拒绝会丢弃同组好包」的 P-F2-3 质量提示，符合预登记 §4）；
- 版本门控后的 D1-1 历史套件：**70 passed / 0 failed / 2 findings**（C1a/b/c/x 5 项按版本跳过）；
- `data1` 回归全部通过，折叠值与 D1-1 逐点相等。

该 shim 只用于验证口径可满足，**不作为 D1-2 交付、不代表数据方实现**；D1-2 的通过与否仍以数据方实际提交为准。

## 7. 历史套件的版本门控

`checks/A/test_d1_independent.py` 的 C1a/C1b/C1c/C1x 断言的是 D1-1 **缺陷行为**（锚包=翻转包、只接受 1 包、换序改变接受集）。若 D1-2 修复 F1，这些旧断言必然失败。本轮在该文件中加入：

```python
if FG.CONTRACT_VERSION == "D1-1":
    ... C1a/C1b/C1c/C1x/C1y ...
else:
    print("[SKIP] C1... 为 D1-1 缺陷刻画（由 D1-2 套件替代）")
```

- D1-1 上仍 **75/75**（5 项 C1 检查全部执行）；
- D1-2 上 C1 系列跳过，由 `test_d1_2_independent.py` 的 P-F1-1..6 接管；
- 历史结果 `d1_independent_results.json` 未改写。

## 8. 交付物与复跑

| 文件 | 内容 |
|---|---|
| `checks/A/d1_2_prereg.md` | D1-PREREG-2 预登记（21 条性质、解析预期、未知项） |
| `checks/A/test_d1_2_independent.py` | 76 项 D1-2 独立套件（合成 F1/F2 + `data1` 回归） |
| `checks/A/d1_2_prefix_characterization.json` | 在 D1-1 上的 58/18 逐项结果（非空转证据） |
| `checks/A/test_d1_independent.py` | 增加 `CONTRACT_VERSION` 版本门控（仅 C1 系列） |
| 本报告 | 合并复测、阻断说明、可满足性验证 |

```powershell
# D1-1 上的非空转证明（当前基线，预期 18 failed）
python checks/A/test_d1_2_independent.py

# D1-2 新 SHA 上的验收（预期 0 failed）
python checks/A/test_d1_2_independent.py

# 历史套件与作者套件
python checks/A/test_d1_independent.py
python solutions/A/test_a_fold_gate.py --no-real
```

## 9. 阻塞与下一步

- **阻塞**：D1-2 分支/提交不存在。收到实际 SHA 后，我将：
  1. 在独立检出（`git worktree`/干净 clone）中核对 `4a21060..新SHA` 的变更范围与 blob；
  2. 运行 `test_d1_2_independent.py`，并复跑作者套件与 `data1` 诊断 JSON；
  3. 对照契约检查新原因码、F1 规则、F3 范围与版本号；
  4. 给出通过/失败/依据不足的结论，失败项附版本、输入、命令、预期、实际、影响范围。
- **非阻断观察**：`fold_gate_contract.md` 末尾新补记无换行（纯格式）；`data1` 诊断在 D1-2 若因锚包规则变化而数值改变，须同步更新契约 §5 与 JSON 并在 PR 说明。
- 本轮未修改被验证的生产实现、未运行任何未批准实验、未读取墙体/金属板留出信号。
