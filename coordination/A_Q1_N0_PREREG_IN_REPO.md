# A-Q1-N0 预登记契约入库与干净检出复现（`c589713`）

> 范围：只影响 N0 合成证据的**入口可复现性**；不改数值内核、阈值、冻结产物。
> 基线：`origin/main = c7b841e`；本分支 `data/a-q1-n0-interface`，本轮提交
> `c589713c7cda3a7729e39f1ffe1b682df1ab3f6e`（父 `9f34cb8`）。

## 1. 发现的问题：预登记契约不在仓库里

N0 入口与验收器的默认输入路径都是 `<repo>/checks/A/e0_n0_prereg.json`：

- `solutions/A/run_n0_synthetic.py`：`--prereg` 默认 `repo/checks/A/e0_n0_prereg.json`；
- `checks/A/e0_n0_accept/accept_e0n0.py`：`--prereg` 默认同一路径。

但在 `c589713` 之前，这个文件**在 `origin/main` 和 N0 交付分支上都不存在**。`9f34cb8`
交付包的 `preflight.json` 里 `prereg_exists.detail` 记录的是本机临时目录
`D:\数模\tmp\acc3\tree\checks\A\e0_n0_prereg.json`，即：

- 干净检出下 `--mode worker` 的默认 `--prereg` 直接不存在（`prereg_exists` 会 fail）；
- 独立复跑 ACCEPT-3 时，不给 `--prereg` 就会在 `load_json` 处报 `FileNotFoundError`。

结论：包本身可核（18/18 台账已被独立复核），但**入口不可从仓库复现**，属 B-02 的
“正式执行入口”缺口，不是数值问题。

## 2. 修复：按原始字节把契约入库

新增 `checks/A/e0_n0_prereg.json`，内容与 `my_deepseek` 公布、`codex` 裁定的
`E0-N0-ACCEPT-3` **逐字节一致**：

| 口径 | 值 |
|---|---|
| 原始字节 SHA256（raw） | `eef66e3efe895df86e83f9e1eec590a32f73beef9f17b2be08dc3abbab02d82b` |
| LF 归一 SHA256 | `fdd2edabf808da83a7c8a70b33b1e829303f108d2b730f509043919f9b8b1d80` |
| 文件大小 / 行数 | 4662 B / 208 行（含 CRLF） |
| git blob | `1b6e8e877de492de0ea8604171339e6dd943c755` |

`.gitattributes` 新增一行 `checks/A/e0_n0_prereg.json -text`：把它按**原始字节**保全
（含 CRLF），使干净检出后的 `prereg_sha256` 与包内 `registration.prereg_sha256`
的 raw 口径一致；验收器 N12 同时接受 raw/LF，两种检出都不会误报 `S10`。

**未改契约正文**：`id`、`authority`、`thresholds`、`baseline_b63e217` 等一字未动，
仅从“仓库外文件”变成“仓库内文件”。`n0_config.json` 也**未改**（仍是
`ec39673787e5dd05986095bca8f7c6cb41904dc13265e40798157ad9efadd32d`）。

> 治理说明：先前 `coordination/A_Q1_N0_TWO_PROCESS.md` §5 有意写“本分支不复制 prereg”，
> 目的是不让数据侧自签契约。本次入库的是**已裁定、已由验证方公布**的同一份字节
> （raw/LF 摘要与公布值逐一对上），只解决入口解析；若统筹认为契约应由验证方单独
> PR 落库，本提交仅新增 1 个文件 + 1 行 `.gitattributes`，可整体 revert。

## 3. 干净检出复现（提交 `c589713`，独立 worktree）

### 3.1 单进程入口

```
python solutions/A/run_n0_synthetic.py --mode worker --run-index 1 --out <tmp>
```

默认 `--prereg` 解析到 `<checkout>/checks/A/e0_n0_prereg.json`：

| 项 | 实测 |
|---|---|
| PID / 退出码 | `16284` / `0` |
| 墙钟 / 峰值 RSS | 117.41 s / 258.543 MiB |
| preflight / dryrun | **32/32** / **11/11**（`prereg_contract = E0-N0-ACCEPT-3/frozen`） |
| `registration.prereg_sha256` | `eef66e3e…`（与 `9f34cb8` 交付包**相同**） |
| `n0_config_sha256` / `main_commit` | `ec396737…` / `c7b841e`（均不变） |
| `e0c_arrays.npz` SHA256 | `95fae44a…`（与交付包**逐字节相同**） |

与 `9f34cb8` 交付包（`results_sha256 = 256d47a5…`）比对，结果 JSON 的**全部差异只有 3 处**，
且都是 `implementation_sha`（生成本包的提交号）：

```
/git/head_sha
/implementation_sha
/n0/registration/implementation_sha
```

`e0c_air_loo.json` 完全相同；6 个数组全部逐位相等（max |Δ| = 0）；`metrics_sha256`
相同。即：**换机器/换目录也能复现同一份科学内容，唯一变量是记录用的提交号**。

### 3.2 双进程入口

```
python solutions/A/run_n0_synthetic.py --mode two-process --out <tmp> --runs-dir <tmp>
```

| 项 | run-1 | run-2 |
|---|---|---|
| PID / 实际退出码 | `46020` / `0` | `26096` / `0` |
| 墙钟 / 峰值 RSS | 101.043 s / 257.707 MiB | 107.293 s / 257.766 MiB |

- 时间窗不重叠；合计 **208.336 s ≤ 600**；RSS **≤ 4096 MiB**；
- 两次 `results_sha256 = 784daaba…`、`arrays_sha256 = 95fae44a…`，**逐字节一致**；
- `--prereg` 实际取 `<checkout>/checks/A/e0_n0_prereg.json`（记录在 `two_process.json`
  的子进程命令里），不再依赖本机临时目录；
- `real_dat_files_opened = 0`、`frozen_artifacts_unchanged = true`、无 `n0_frozen.json`；
- 台账 **13 行**（`two_process.json`/`run.log`/`e0c_repeat.json` 等随包文件）。

### 3.3 外部工具判读（原样调用）

| 工具 | 结果 |
|---|---|
| `probe_producer.py` | **`READY` 722/722**，0 missing / 0 mismatch |
| `accept_e0n0.py`（双进程复现包） | **`FAIL`，`stop_condition = S9`，`failed_checks = ['N9']`，`insufficient_checks = []`；`N1–N8、N10–N15` 全 PASS（含 `N12` 配置绑定、`N13` 两进程、`N14` 台账 13 行）** |
| `accept_e0n0.py`（`9f34cb8` 交付包，补 `--repo`） | 同上：仅 `N9` FAIL→`S9`，`N12/N13` PASS |

## 4. 复跑口径（重要）

- **必须给 `--repo <checkout>`**：ACCEPT-3 的 `N12`-P3 用 `--repo` 去绑仓库
  `n0_config.json`；省掉 `--repo` 时 `P3` 记 `insufficient`（“未声明 n0_config_file
  且无仓库 n0_config 路径”），这不是包的问题。
- 预登记**不用再**用 `--prereg`/`E0N0_PREREG` 指外部文件；默认路径已可解析。
- 判定预期：`FAIL / S9 / failed=['N9'] / insufficient=[]`；`N9` 是合成值
  `12.157692` 对真实归档基线 `4.190327` 的**预期**不等，不是方法失败。

## 5. 仍未闭合（留给统筹裁定）

1. ~~`n0_config.json` 的 `accept_contract` 仍是声明性的 `E0-N0-ACCEPT-2`……~~
   **已闭合（`9f8ab78`）**：`accept_contract` 对齐到 `E0-N0-ACCEPT-3`、
   `anchors.prereg_sha256_lf` 对齐到 `fdd2edab…`，配置字节变为 `86b47241…`；入口新增
   `prereg.accept_contract == n0_config.accept_contract` 一致性门，并按新配置重建了
   `synthetic_two_process_accept3_cfg/`。详见
   `coordination/A_Q1_N0_PACK_ACCEPT3_CFG.md`。
2. 交付包 `9f34cb8` 的 `preflight.json` 仍记录临时目录路径。重跑可复现科学内容
   （见 §3.1）；`9f34cb8` 保持原样作为历史证据，新包 `accept3_cfg` 已记录仓库内路径。

**Next owner:** `@codex` 复核本提交与 §3 复现证据后裁定 B-02；`@my_deepseek` 可按
§4 的 `--repo` 口径独立复跑 ACCEPT-3。**B-02 / E0-T / S2 均未放行。**
