# E0-C 合并后复测记录（main `7147fb6`）

- **性质**：对已合并的验收检查器做“合并后复测 + 记录更正”，**不重跑实验**、不读取 E0-T / 18 组留出样、不改任何阈值。
- **对象**：`origin/main` @ `7147fb6`（Merge PR #34），验收对象仍是
  `data/a-q1-e0-c-interface` @ `b63e217` 的交付包 `experiments/A/A-Q1-E0/e0c/results/`。
- **环境**：Python 3.11.5（Anaconda）/ numpy 1.26.4；`git` 检出 `core.autocrlf=true`。
- **结论**：合并**没有**改变判定——`FAIL`，失败项仅 **C9**、**C12**，其余 13 项通过。

## 1. 合并完整性

| 项 | 值 |
|---|---|
| 合并提交 | `7147fb6bae9cd9ac9ee34eeadcd8171cdb426660` |
| 父提交 | `bc90e1b`（原 main）+ `4a41e6d`（验收分支 HEAD） |
| `4a41e6d` 是否祖先 | 是 |
| 树哈希 | 合并树 = 分支树 = `efe6ff1e1cb2a5a5aa6dcf163dcc9e5a1e94103f` |
| `git diff 4a41e6d 7147fb6` | 空（0 文件差异） |

即 PR #34 以“原提交 + 合并提交”方式入库，未改写、未重排、未冲突修复，验收分支内容逐字节保留。

## 2. 自检（合并后主线）

```
python checks/A/e0_c_accept/test_accept_e0c.py
Ran 28 tests ... OK
```

- **28/28** 通过：原 27 项不变，新增第 28 项（见 §4 的 F-1）。
- 合并前后各跑一次，均通过；新增项只影响摘要取字节方式，不影响任何 C1–C15 的判定逻辑。

## 3. 合并后复测（同一交付包）

```
python checks/A/e0_c_accept/accept_e0c.py \
  --results-dir <b63e217 的 e0c/results 独立副本> \
  --repo . \
  --report <本机临时路径> \
  --e0s-results experiments/A/A-Q1-E0/s1s2/results/e0_s1s2_results.json
```

| 项 | 合并前（`e2b02f9` 报告） | 合并后（`7147fb6` 复测） |
|---|---|---|
| verdict | FAIL | **FAIL** |
| 失败项 | C9、C12 | **C9、C12** |
| 其余 13 项 | PASS | **PASS** |
| C8 空场 LOO min（默认对 `(1e-3,1e-3)`） | 2.984434 dB | **2.984434 dB**（候选网格整体最小 2.909364 dB） |
| C9 墙体 PSLR | 2.664330 dB < 3.0 | **2.664330 dB < 3.0** |
| C9 金属板 | PSLR 4.172580、PNR 35.429279、4.37 cm | **同上** |
| C10 独立重算 | 最大偏差 4.811e-10 dB | **同上** |
| C12 | 重复序列化、无第二次独立运行 | **同上** |
| 冻结文件 | `hard_stop`、`written=false` | **同上** |

**差异只有路径字段与 §4 的摘要口径**（`results_dir`、`prereg_path`、E0-S 路径；`prereg_sha256` 改为 canonical，另加两个 `*_raw` 字段）；**15 项状态与全部数值字段一致**，`repeat_contract_sha256` 规范化后与历史报告相同。本次复测仍是在**同一份交付数组**上复算，不是第二次独立运行。

## 4. F-1：锚点摘要在 Windows 检出下随行尾变化（已修）

`report_b63e217.json` 中的 `prereg_sha256` / `repeat_contract_sha256` 原先用工作树原始字节计算。本机 `core.autocrlf=true`，`.gitattributes` 只把 `*.md` 固定为 `eol=lf`，JSON 检出为 CRLF，于是同一提交会得到两套摘要：

| 锚点 | 工作树原始字节（旧口径，CRLF） | Git blob / LF 规范化（可复算） |
|---|---|---|
| `checks/A/e0_c_prereg.json` | `ae7c41baa550d77a…` | **`da22fbd0d23cea9a…`** |
| `checks/A/e0_c_repeat_contract.json` | `84951702ea948ed8…` | **`a32429e2a7b396c3…`** |

- 已合并的历史报告 `report_b63e217.json` 因此记的是“一个 raw + 一个 LF”的混合值（prereg=`ae7c41ba…`，contract=`a32429e2…`）：**无法只凭 `git show` 复算**。
- 本分支把 `summary()` 的锚点摘要改为 git-blob 语义（CRLF→LF，已有 `sha256_git_text` 正是 C6 使用的同一函数），并新增 `*_sha256_raw` 保留工作树字节；新增自检 `test_28_anchor_digest_ignores_line_endings`（CRLF 副本与 LF 原件必须给出同一 canonical 摘要、不同 raw 摘要）。
- **历史报告不改写**：`report_b63e217.json` 保持原样作为当时运行记录；规范化后的值以本节与复测报告为准。
- 影响范围：仅摘要字段的可复算性，**不涉及任何通过/失败判据**（C1 的锚点比较来自 `git show` 的 blob，C6 早已使用同一规范化函数）。

## 5. 结论与边界

1. **E0-C 仍为硬停止**：C9（墙体 PSLR 2.6643 dB < 3.0）与 C12（无两次独立运行证据）都未因合并而改变；未写 `e0c_frozen.json`，**E0-T 继续关闭**。
2. 本记录只证明“合并未改变判定、检查器在合并后主线可运行”，**不证明实验可复现**：C12 的实质证据仍缺。
3. 数值引用仍须带交付提交 `b63e217` + 报告 SHA256；本次复测未产生新的实验数值。
4. 未改阈值、未改预登记、未重跑实测、未读取任何留出样。

## 6. 复测环境与命令版本

- 检查器：本分支 `checks/A/e0_c_accept/accept_e0c.py`（相对 `7147fb6` 仅改摘要取字节方式 + 新增测试）。
- 交付包副本 SHA256：`e0c_results.json` = `7d3fbcd5…`，`e0c_arrays.npz` = `03084cff…`，与 `SHA256SUMS.txt` 一致。
- E0-S 前置：`e0_s1s2_results.json` = `171f55f7…`，`overall_pass=true`。
