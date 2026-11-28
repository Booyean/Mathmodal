# A-Q1-E0-S1/S2 独立验收报告（E0-ACC-1）

- **验收方**：`my_deepseek`（独立验证）。
- **被验对象**：`data/a-q1-e0-s` 分支
  - 结果登记提交：`5d14b7ba4f5b3f3b692a10ba94588ba23ffa85d6`（父提交 `652fc53`）
  - 实现提交：`652fc532fb7046645f570f8a046ea38e30f54f50`（父提交 `b10264b`）
  - 结果文件：`experiments/A/A-Q1-E0/s1s2/results/`（`e0_s1s2_results.json`、`e0_s1s2_arrays.npz`、`e0_s2_param_table.json`、`run.log`、`SHA256SUMS.txt`）
- **验收依据**：E0-PREREG-2（`checks/A/e0_s1s2_prereg.md`，PR #24 / `5151844`）、统筹裁定 `2ba3210`、E0 方案 `7f9ad92`、`config.json` LF SHA256 `8fb6821f…e06a`、已批复 M0 `098e17d`。
- **验收环境**：CPython 3.13.7 + numpy 2.1.3（交付记录为 3.13.5 / 2.1.3，同 numpy 主版本）；随机流另在 CPython 3.9.13 + numpy 1.26.4 下复核。
- **结论**：**通过**。P1–P17 全项通过；结论仅覆盖 `E0-S1`/`E0-S2` 合成闭环，**不覆盖** `E0-C` 真实校准、`E0-T` 留出盲评，也不代表正式测距精度。

## 1. 结果摘要（交付 JSON，已独立复算）

| 指标 | E0-S1 | E0-S2@0.42 m | E0-S2@0.69 m | 门控 |
|---|---|---|---|---|
| `d_hat_m` | 0.6000000000000004 | 0.42000000000000026 | 0.6900000000000005 | — |
| `abs_err_cm` | 4.44e-14 | 2.78e-14 | 5.55e-14 | ≤0.05（S1）/≤1.0（S2） |
| `dtau_err_ns` | 1.03e-16 | 不适用 | 不适用 | ≤0.001 |
| `Supp_dw_win_db` | 不适用（2 路无噪） | 44.260620 | 78.497262 | ≥20 |
| `PSLR_db` | 不适用 | 9.348883 | 9.267955 | ≥3.0 |
| `PNR_db` | 不适用 | 55.763155 | 54.567960 | ≥6.0 |
| `valid_rx` | 2（S1 例外） | 63 | 63 | 63 |

`t0_eff,tgt = 251.200000 Ts`、`Δt0 = 130.150 Ts`、`Δτ̂2 = 0.4999999999999999 ns`、`Ĝ2 = 1.25`、`ψ̂2 = 0.29999999999999927 rad`。

## 2. P1–P17 逐项判定

| 编号 | 检查 | 判定 | 证据 |
|---|---|---|---|
| P1 | 版本锚点 | 通过 | `5d14b7b` 的父提交 = `652fc53`；JSON `implementation_sha` = `652fc53`、`parent_commit` = `b10264b`；结果提交 ≠ 实现提交（无自引用）；`config.json` LF SHA256 由 `git show 652fc53:…` 重算 = `8fb6821f…e06a`；`plan_sha256_match`/`s2_param_table_match` 均为 true；`SHA256SUMS.txt` 4 个文件全部与实际字节一致；`arrays_file_sha256` 与 npz 一致 |
| P2 | S 阶段不读真实 `.dat` | 通过 | 实现提交树内无 `.dat`、无 `竞赛题目` 路径；在**没有任何真实数据目录**的 worktree 中完整跑通 S1/S2；运行期只读 `config.json` |
| P3 | 代码范围（无 N0） | 通过（含说明） | `assert alpha == 1.0`；无自适应 α、无子空间抑制、无 WLS、无逐通道非等权；唯一“选参”是 PLAN §3.1 明文规定的**固定 3×3 空场 LOO**，实际选中默认 `(1e-3,1e-3)`、`triggered=False`，等价于固定默认值，不属于“大范围超参搜索” |
| P4 | S1 参数与期望 | 通过 | 代码常量与预登记 §3.1 一致（RX 28/12、`Δτ2=0.5 ns`、`G2=1.25`、`ψ2=0.30`、`d=0.6`、`Γ=-0.35`、`τ_hw=0.2 ns`、`t0_air=120.25 Ts`、`t0_tgt=250.40 Ts`）；`abs_err=4.4e-14 cm`、`|Δτ̂2−0.5|=1.0e-16 ns`、`t0_eff=251.20000000000033 Ts` |
| P5 | S2 参数表 | 通过 | 规范 JSON SHA256 = `aa86bf56…6e96`（由交付行与由 oracle 两条路径分别重算，均一致） |
| P6 | 通道与有限性 | 通过 | `rx_idx` 63 路、含 `ref=28`、不含 `tx=27`；`x_cal/x_after/s_eff/…` 全部有限；形状 `(63,1401)` |
| P7 | S2 测距 | 通过 | `2.8e-14 cm`、`5.6e-14 cm`（门控 ≤1.0 cm） |
| P8 | 直射波抑制 | 通过 | `44.2606 dB`、`78.4973 dB`（门控 ≥20 dB） |
| P9 | 目标回波质量 | 通过 | 两目标均 `PSLR≥3 dB`（9.3489 / 9.2680）、`PNR≥6 dB`（55.7632 / 54.5680） |
| P10 | 指标独立重算 | 通过 | 由交付数组独立重算（`checks/A/e0_acceptance/recompute_metrics.py`）：Supp 差 `3.6e-13/4.7e-12 dB`、BG 相对差 `1.5e-15`、PNR 差 `0`、PSLR 差 `8.9e-15/1.8e-15 dB`、`d_hat` 与 `abs_err` 差 `0`；三条剖面相对差 `≤3.7e-15` |
| P11 | 确定性 | 通过 | 同一命令连续两次：64 个数组**逐位一致**，`arrays_file_sha256` 同为 `1352a1a3…`，结果 JSON（除耗时/RSS/路径/日志外）完全一致 |
| P12 | 不读真值 | 通过 | `d_true` 仅出现在合成生成、真值元数据、`abs_err` 与门控计算；估计链路（对齐、校准、减除、`S_eff`、剖面、峰值规则）不含真值分支；我由 `x_after`+`S_eff` 独立重算的 `d_hat` 与交付值一致 |
| P13 | 资源 | 通过 | 交付：墙钟 `25.18 s`、峰值 RSS `204.0 MiB`；本机复跑 `18.1–18.2 s`、`200.6–202.9 MiB`（限 600 s / 4096 MiB）；导入 numpy 前强制 `OMP/OPENBLAS/MKL/NUMEXPR=1`；单进程计算（`subprocess` 仅用于读取 git 版本信息） |
| P14 | 证据完整 | 通过（含说明） | 命令、环境、日志、数组、SHA256、失败原因齐全；原始噪声矩阵未直接入库，但给出种子、σ 与逐组摘要，可由种子逐位重建（见 P17） |
| P15 | 非空转 | 通过 | 5/5 篡改被检出：`d_hat` 移 2 cm、`Supp` 改 19.9 dB、`x_after` 注入 NaN、`valid_rx` 改 62、参数表 `1e-15` 篡改（`checks/A/e0_acceptance/p15_tamper.py`） |
| P16 | 触发偏移 oracle | 通过 | 交付偏移按无量纲 `u` 与 oracle 逐项比较，最大差 `2.22e-16`（容差 `2e-15`）；`air_0 = 120.25` 样点固定 |
| P17 | 噪声矩阵 oracle | 通过 | 独立重建的 12 个 `63×4000` 矩阵原始 float64 C-order 字节与 oracle **逐组一致**，连接 SHA256 = `e56efec8…3875`；在 numpy 2.1.3（交付记录版本）与 numpy 1.26.4 下**均逐位一致**；交付 JSON 的逐组 `array_sha256`（dtype+shape+字节）也被完整复现 |

## 3. 复跑命令

```powershell
# 交付运行（结果所用代码提交固定为 652fc53，避免自引用）
python solutions/A/a_e0_s1s2.py --out <out-dir> `
  --implementation-sha 652fc532fb7046645f570f8a046ea38e30f54f50 `
  --parent-commit b10264b0958b44dec527457635b410a999fb77f3 `
  --main-commit df24c4447e5eeea4dd3f571648adda4ab92cb9e4

# 本报告的独立复核（结果目录取自上面的 --out）
python checks/A/e0_acceptance/stream_check.py <out-dir> checks/A/e0_s2_stream_oracle.json
python checks/A/e0_acceptance/recompute_metrics.py <out-dir>
python checks/A/e0_acceptance/p15_tamper.py <out-dir>
```

`stream_check.py` 依赖 `checks/A/e0_s2_stream_oracle.json`（PR #24 / E0-PREREG-2）；请先合并该 PR 或同时检出。

## 4. 差异与说明（不影响判定）

1. **跨机非逐位**：交付数组与本机复跑数组有 19/64 个在 `≤7.9e-14` 相对量级上不同（指标差 `≤9e-15 dB/dB`），源于 FFT/超越函数在不同 CPU/libm 上的末位差；随机流、参数表与偏移**逐位一致**。故 P11 的“逐位一致”在**同一环境内**成立；跨机复现以预登记门控容差为准。
2. **噪声摘要口径**：JSON 的逐组噪声摘要使用契约 §3 的 `array_sha256`（dtype+shape+字节），而 oracle 冻结的是原始字节摘要；两者不可直接按字符串比较。本报告用独立重建同时核对了两种口径（均一致），建议后续实现说明中显式标注字段口径。
3. **基线漂移**：交付 JSON 记录 `main_commit = b10264b`，验收时 `origin/main = df24c44`；`git merge-tree df24c44 5d14b7b` 干净（`0cabd318…`），无冲突。
4. **交付分支尚无 PR**：验收时 `origin` 上只有分支 `data/a-q1-e0-s`，未见对应 PR；合并前需实现方补 PR 或由统筹指定合并方式。
5. **S1 `seed` 为 `null`**：S1 为 2 路无噪解析闭环，不使用随机数，属预期而非缺项。

## 5. 后续

- 建议统筹 `codex` 复核后合并 `5d14b7b`（或实现方补 PR 后合并），并把 `E0-S` 的通过状态与上述差异说明记入控制表。
- `E0-C`（真实空场/校准）与 `E0-T`（留出盲评）仍未放行；本报告不构成对二者的任何通过意见。
