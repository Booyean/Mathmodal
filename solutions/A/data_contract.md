# A 题 D0 数据契约：原始 `.dat` 读取器输出

- **任务 / 分支**：D0 / `data/a-q1-reader`
- **主责**：`dsh`（数据与求解）；接口审阅：`codex`；公式/坐标待 `A-Q1-M0` 批复
- **输入基线**：`main` = `44c778ead3c3ebd14ab701befbebac22c7480c02`；原始数据基线 = `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9`
- **契约版本**：`D0-1`（读取器常量 `CONTRACT_VERSION = "D0-1"`）
- **实现**：`solutions/A/a_dat_reader.py`；测试：`solutions/A/test_a_dat_reader.py`
- **依据**：`附件1-数据读取函数/get_data_iq.m`（同版本原件）；`coordination/A_Q1_PLAN.md` 的 D0 行；`solutions/A/model_q1.md`（PR #3，`a9e2719…`）§1、§2.1、§7.1（**A-Q1-M0 待批复**，本契约只借用其字段与坐标提案）

> 本文件只描述**读取、展平、配对与体检**。折迭、一致性门控、校准、直射波抑制、测距均不在 D0 范围内，字段也不在此定义。

---

## 0. 边界

**做**：按 `get_data_iq.m` 逐字节解析；8 行 × 8 列 → 64 路展平；63 路接收掩码；按组内 8 个文件的**共同 `sync_packet_cnt` 交集**配对；记录缺行、空文件、包数不等、重复 `sync`、形状不符、非数据包、截断、尾部残留；int16 端点计数（`int32` 升位）；可复跑的组清单与 meta。

**不做**：16000 点按 `Np=4000` 折迭；包内 4 段/跨包/跨行一致性门控；相位或频谱处理；校准、直射波抑制、测距；任何标签（校准/检验）划分；任何数据"修正"或插补。原件只读，不复制、不改名、不改写。

---

## 1. 输入

### 1.1 原件与版本锚定（实测）

| 项 | 值 |
|---|---|
| A 题 `.dat` 文件数 | **881** |
| 合计字节 | **801,111,612 B** |
| 数据包总数 | **3129**（全部解析成功，`header_ok` 全为 True） |
| 清单哈希（算法见 `recon/README.md`） | `86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06` |
| 采样包头部字段实测 | `num=16000`、`len=16`、`freq=0.0`，3129/3129 一致 |

逐文件 SHA256 与组清单见 `recon/manifests/a_dat_manifest.csv`、`a_group_manifest.csv`（R0，PR #1 已合并到 `44c778e`）。D0 的 `meta` 内另存每个已装载文件的 `sha256`，用于与 R0 清单逐项对账。

### 1.2 目录与"组"的定义

| 数据集（`meta.dataset`） | 目录 | 组数 | 8 行齐全且非空 |
|---|---|---|---|
| `附件2-测距数据/空场数据` | `附件/附件2-测距数据/空场数据/data1…data10` | 10 | 10 |
| `附件2-测距数据/墙体数据` | `附件/附件2-测距数据/墙体数据/data*-*cm` | 20 | 20 |
| `附件2-测距数据/金属板数据` | `附件/附件2-测距数据/金属板数据/data*-*cm` | 20 | 20 |
| `附件3-成像数据/墙体` | `附件/附件3-成像数据/墙体`（多组同目录） | 33 | 33 |
| `附件3-成像数据/金属柱和金属铲` | `附件/附件3-成像数据/金属柱和金属铲`（多组同目录） | 28 | 27 |
| **合计** | | **111** | **110** |

**组键（`group_key`）规则**：

1. 若 `.dat` 所在目录名形如 `data12` / `data1-42cm`，该目录即一个测量组：`dataset` = 其父目录（去掉最外层 `附件`），`name` = 目录名。
2. 否则（附件 3）同一目录下有多组：`dataset` = 该目录（去掉最外层 `附件`），`name` = **文件名中的采集时间戳前缀**（`2026-11-12-21-29-57_16000`）。
3. `group_key = dataset + "/" + name`，例如：
   - `附件2-测距数据/墙体数据/data1-42cm`
   - `附件3-成像数据/墙体/2026-11-12-21-29-57_16000`

同一 `(目录, 时间戳前缀, 行号)` 出现多个文件时，保留字典序第一个，其余记 `duplicate_row_file`（实测 0 例）。

### 1.3 文件命名

```
<采集时间戳>_<每周期点数>_<行号>.dat     例：2026-11-12-20-50-32_16000_3.dat
```

- 行号 `n ∈ {0,…,7}` 对应阵列第 `r = n+1` 行（`_0.dat` → 第 1 行）。
- 文件名中的 `16000` 与包内每通道点数一致（实测 881/881）。
- 不能按"一行一个文件包数相同"做假设：同一组内不同行文件的包数可差 1（见 §3）。

### 1.4 二进制协议（逐字节复刻 `get_data_iq.m`）

小端（`<`）。一个数据包：

| 偏移 | 字段 | 类型 | 实测值 | 说明 |
|---|---|---|---|---|
| 0 | `magic` | `uint32` | `963072` | 包头起始标记；按 4 字节窗口向后搜索 |
| 4 | `total_len` | `uint32` | `256020` | `.m` 用它跳过非数据包；实测 `= 20 + 采样字节数` |
| 8 | `type` | `uint32` | `102` | 102 = 采样数据包；其它值跳过 `total_len-4` 字节 |
| 12 | `freq` | `float32` | `0.0` | **原样保留、不解释**；实测 3129/3129 为 0.0 |
| 16 | `sync` | `uint32` | 逐包递增 | `sync_packet_cnt`，组内配对键 |
| 20 | `num` | `uint32` | `16000` | 实测等于每通道采样点数 |
| 24 | `len` | `uint32` | `16` | 实测等于每采样时刻字节数（8 通道 × int16） |
| 28 | 采样数据 | `int16 × (num*len/2)` | | 按**采样时刻交织**：每个时刻连续 8 路 |

MATLAB 取数：`data = fread(fid, num*len/2, 'int16'); data_iq = reshape(data, 8, [])`。
即**固定 8 行**、列数 `= (num*len/2)/8`。等价 numpy：

```python
arr = np.frombuffer(buf, dtype="<i2", count=num*len//2, offset=28)
mat = arr.reshape(n_samples, 8).T          # -> (8, n_samples)
```

D0 采用**同一语义**（不假定 `num` 就是点数、`len` 就是字节数）；实测两者正好是 `(16000, 16)`。头部合法缓冲至少 28 字节；`num*len/2` 不是 8 的整数倍时 `.m` 的 `reshape` 会报错，D0 记 `sample_count_not_multiple_of_8` 并跳过该包（实测 0 例）。

**采样配置不是文件头字段**：`fs = 4.0 GHz`、`Ts = 0.25 ns`、`Np = 4000` 取自题面补充说明，作为读取器常量单独配置（`FS_HZ`、`N_PERIOD_SAMPLES`），不从 `freq` 反推。

---

## 2. 输出

`load_group()` 返回 `GroupData`；`--inspect`/`--json` 输出 `meta` 的 JSON。

### 2.1 `GroupData` 字段字典

| 字段 | 类型 | 形状 | 单位 | 来源 | 缺失/异常规则 |
|---|---|---|---|---|---|
| `packets` | `int16` | `(P, 64, 16000)` | ADC 原始计数（**未标定**，见 §2.4） | 共同 `sync` 包逐行拼接 | 默认要求 8 行齐全；`require_all_rows=False` 时缺行通道填 0 且 `channel_valid=False` |
| `sync` | `int64` | `(P,)` | 无量纲（设备包号） | 升序排列的共同 `sync_packet_cnt` | 交集为空时 `P=0` |
| `rx_mask` | `bool` | `(64,)` | — | 仅 `rx_mask[27]=False` | 恒 64 项，实测 63 个 True |
| `channel_valid` | `bool` | `(64,)` | — | 该通道所属行是否存在且已参与配对 | 8 行齐全时全 True；缺行且 `require_all_rows=False` 时对应 8 个通道 False；`P=0` 时数组为空 |
| `tx_idx` | `int` | 标量 | — | 27（第 4 行第 4 列，0-based `row=3, col=3`） | 常量 |
| `ref_idx` | `int` | 标量 | — | 28（第 4 行第 5 列，0-based `row=3, col=4`） | 常量 |
| `positions_m` | `float64` | `(64, 3)` | m | `channel_positions()`，依 **M0 §2.1 提案** | **待 A-Q1-M0 批复**；坐标变更不影响读取/配对 |
| `meta` | `dict` | — | — | 见 §2.2 | 只放事实与异常，不放估计量 |

`packets` 的通道索引：`i = 8*(r-1) + (c) ∈ {0..63}`，其中 `r = 行号+1`、`c = 文件内列号 0..7`（即 `i = 8*n + c`）。
`packets[p, i, m]` = 第 `sync[p]` 包、通道 `i`、第 `m` 个采样点。**存储为 `int16` 原值**：任何比较、`abs`、极值统计前必须升位到 `int32`（`np.abs(np.int16(-32768))` 会回绕）；模块内部已升位，并提供 `packets_int32()`。

### 2.2 `meta` 字段字典（关键项）

| 字段 | 类型 | 说明 |
|---|---|---|
| `contract_version` | str | `D0-1` |
| `group_key` / `dataset` / `name` / `dir_rel` / `prefix` | str | 组标识（§1.2） |
| `n_files_expected` / `n_files_used` | int | 恒 8 / 实际可用行数 |
| `missing_rows` | int[] | 缺文件的行（0-based） |
| `empty_or_unreadable_rows` | int[] | 文件存在但 0 包或读取失败的行 |
| `duplicate_row_files` | int[] | 同行多文件冲突（实测 0） |
| `sync_common` | int[] | 共同 `sync` 升序列表；`len` 即 `P` |
| `n_packets` | int | `P` |
| `n_channels` / `samples_per_packet` / `n_period_samples` | int | 64 / 16000 / 4000（`Np` 仅登记，D0 不折迭） |
| `fs_hz` / `ts_s` | float | `4.0e9` / `2.5e-10`（题面配置，非文件字段） |
| `tx_idx` / `ref_idx` / `rx_mask_true_count` | int | 27 / 28 / 63 |
| `row_files` | dict[str → obj] | 每个已读行文件：`file`、`size_bytes`、`sha256`、`n_packets_total`、`syncs_total`、`n_packets_used`、`syncs_used`、`syncs_dropped_not_in_intersection`、`freq_values`、`endpoint_counts_all_packets`、`problems`、`skipped_bytes`、`trailing_bytes` |
| `excluded_packets` | list | 被排除的包：`row`、`sync`、`reason`（`samples_per_packet_mismatch` / `duplicate_sync_in_file`） |
| `problems` | list | 组级问题（重复行文件等）；文件级问题在 `row_files[r].problems` |
| `extremes` | obj | 端点统计，见 §4 |
| `positions_source` | str | 明确标注坐标公式来源与批复状态 |

问题码（`problems[].code`）：`empty_file`、`no_data_packet`、`read_error`、`truncated_header`、`truncated_packet_header`、`truncated_samples`、`non_data_packet`、`bad_skip`、`zero_length_packet`、`sample_count_not_multiple_of_8`、`header_len_mismatch`、`trailing_bytes`、`duplicate_row_file`、`unexpected_dat_name`。

### 2.3 索引与主键

- 逻辑主键：`(group_key, sync, channel_idx, sample_idx)`，其中 `sync ∈ sync_common`、`channel_idx ∈ 0..63`、`sample_idx ∈ 0..15999`。
- 物理位置：`packets[sync 的升序序号, channel_idx, sample_idx]`；用 `sync` 值反查序号请用 `np.searchsorted(gd.sync, s)`，不要假定 `sync` 连续。
- 组键见 §1.2；行/列到通道的映射见 §2.1。

### 2.4 单位与量纲

| 量 | 单位 | 状态 |
|---|---|---|
| 采样值 `packets` | ADC int16 原始计数 | **未标定**：ADC 位深、前端增益/衰减、天线与电缆频响均未在附件中给出，不能当作电压/场强 |
| 时间 `ts_s`、`sync` | s / 包号 | `Ts` 来自题面；`sync` 无量纲 |
| 坐标 `positions_m` | m | 依 M0 §2.1 提案，待批复 |
| 频率 | Hz | 仅 `fs_hz` 配置；`freq` 字段原样保留，未解释 |

---

## 3. 配对与异常处理规则

| 情形 | 实测例 | 处理 | 记录位置 |
|---|---|---|---|
| 组内 8 个文件包数不等 | `附件2/墙体/data10-82cm`：2,2,3,3,2,2,3,3 | 取**共同 `sync` 交集**（升序），只在交集中的包进入 `packets`；被丢的 `sync` 逐文件列出 | `sync_common`、`row_files[r].syncs_dropped_not_in_intersection` |
| 某行文件 0 字节 | `附件3/金属柱和金属铲/2026-11-12-22-50-31_16000_7.dat`（该组只有这 1 个文件） | 记 `empty_file`；`require_all_rows=True` 抛 `IncompleteGroupError`，**不用 0 填充伪造**；`--allow-incomplete` 时该行通道 `channel_valid=False` | `row_files`、`empty_or_unreadable_rows` |
| 缺行（0..7 中少文件） | 同上组缺 0..6 行 | 同上 | `missing_rows` |
| 同一文件内 `sync` 重复 | 实测 0 例 | 保留第一个，其余 `excluded_packets` 记 `duplicate_sync_in_file` | `excluded_packets` |
| 包形状不是 8×16000 | 实测 0 例 | 不参与配对，记 `samples_per_packet_mismatch` | `excluded_packets` |
| `type != 102` 的包 | 实测 0 例 | 按 `.m` 跳过 `total_len-4` 字节 | `problems` 的 `non_data_packet` |
| 包头前/包间非 magic 字节 | 实测 0 例 | 按 4 字节窗口搜索下一个 magic，计入 `skipped_bytes` | `problems`、`skipped_bytes` |
| 采样区被截断 | 实测 0 例 | 丢弃该包及之后内容，记 `truncated_samples` | `problems`、`trailing_bytes` |
| 最后一个包之后有残留字节 | 实测 0 例 | 计入 `trailing_bytes`，不解释 | `trailing_bytes` |
| 文件名不符合 `<前缀>_<0..7>.dat` | 实测 0 例 | 不进入任何组，记 `unexpected_dat_name` | `--list-groups` 的 `scan_problems` |
| 同行多文件 | 实测 0 例 | 保留字典序第一个，记 `duplicate_row_file` | `duplicate_row_files` |

**不插补、不重采样、不裁齐、不修 `sync`。** 交集为空时返回 `P=0`，`meta` 保留全部证据；是否允许"只用部分行/部分包"由预处理阶段在实验登记中另行决定，D0 不默认放行。

---

## 4. 端点（`+32767` / `-32768`）统计口径

- 判据：`int32` 升位后 `== +32767` 或 `== -32768`。**不用 `|x| >= 32767`**（会把 `-32767` 误计为端点），也不对 `int16` 直接取绝对值（`-32768` 会回绕）。
- 两个口径同时给出，避免混用：
  1. `extremes.*`：**共同包** × 64 通道（含发射通道 27，只统计、不参与接收处理）。
  2. `extremes.all_packets_in_group`：组内 8 个文件**全部包**（含未进入交集的包），用于与 R0 清单对账。
- 实测例：`附件3/金属柱和金属铲/2026-11-12-22-09-58_16000` 的 **46 个 `-32768` 全在 `_1.dat` 的 `sync=250` 包**；该包不在 3 个共同包内，因此共同包口径为 0、全包口径为 46。两种口径都是事实，报告时必须写清是哪一种。
- `-32768` 是否是 ADC 饱和**不能由本读取器判定**：无 ADC 位深、增益与前端链路定义。孤立单点更可能是坏点/采集异常，需在预处理阶段标记，不在此剔除。

---

## 5. 未知项与待确认

| 编号 | 未知项 | 影响 | 需要什么 |
|---|---|---|---|
| O-D0-01 | `freq` 字段物理含义（实测全为 `0.0`） | 不能据此推采样率/载频 | 采集设备说明或原始记录 |
| O-D0-02 | ADC 位深、前端增益/衰减、采样值到电压的换算 | `packets` 只能是未标定计数 | 硬件手册/标定记录 |
| O-D0-03 | 采集起点是否与发射扫频零点对齐 | D0 不判定；折迭前须确认 | 题面/建模方结论 |
| O-D0-04 | 组目录名中的 `42cm`… 是标称还是实测距离 | 会影响"真值"用法 | 采集记录 |
| O-D0-05 | 附件 3 的 0 字节文件是采集失败还是拷贝缺失 | 该组当前不可用 | 原件复核 |
| O-D0-06 | 同组包数 2–6 不等的原因（丢包/停采/配置） | 交集后 `P` 随组变化 | 采集日志 |
| O-D0-07 | `positions_m` 公式（M0 §2.1）是否批复、`+x` 定向 | 只影响几何辅助，不影响读取 | `A-Q1-M0` 批复 |
| O-D0-08 | 10/10 校准/检验拆分未冻结 | D0 不写任何标签 | `codex` + 验证方冻结 |
| O-D0-09 | 光速取值（M0 第一轮取 `c0`） | 属测距阶段，D0 不使用 | `A-Q1-M0` 批复 |

---

## 6. 复跑与验收

```powershell
# 组清单（111 组 / 110 完整）
python solutions/A/a_dat_reader.py --list-groups --json out/groups.json

# 单组：输出 meta（含 sha256、共同 sync、异常、端点统计）
python solutions/A/a_dat_reader.py --inspect "附件2-测距数据/墙体数据/data10-82cm" --json out/g10.json
python solutions/A/a_dat_reader.py --inspect "附件2-测距数据/空场数据/data1" --max-packets 1

# 全量配对体检（只读 header + 交集，不做估计；本机实测约 9 s）
python solutions/A/a_dat_reader.py --verify-all --json out/verify_all.json

# 合成例 + 真实组测试
python solutions/A/test_a_dat_reader.py
```

验收口径：合成例覆盖协议分支与异常路径（预期值先写死、再与实现比对）；真实组覆盖 8 行齐全组、包数不等组、含 `-32768` 组、0 字节组；全量体检核对 111 组、110 完整、扫描问题 0。

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| D0-1 | 2026-11-27 | 首版：协议解析、64/63 路、共同 `sync` 配对、异常规则、双口径端点统计、坐标标注待批复 |
