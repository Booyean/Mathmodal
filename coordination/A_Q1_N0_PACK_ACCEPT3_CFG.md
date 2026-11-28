# A-Q1-N0 配置对齐 + ACCEPT-3 重建包（`9f8ab78`）

> 回应 codex 派工：在 `data/a-q1-n0-interface` 上完成 **N0 配置对齐**与**正式入口的合成验证**。
> 基线：`origin/main = c7b841e`；入口/契约提交链 `c589713`（预登记入库）→ `1df089a`
> （复现证据）→ **`9f8ab78`（配置对齐 + 契约一致性门）**；本包由 `9f8ab78` 的两进程生成。

## 1. 配置对齐（`n0_config.json`）

| 字段 | 旧值（ACCEPT-2 声明） | 新值（ACCEPT-3 对齐） |
|---|---|---|
| `accept_contract` | `E0-N0-ACCEPT-2` | **`E0-N0-ACCEPT-3`** |
| `anchors.prereg_sha256_lf` | `721eb744…`（ACCEPT-2 字节） | **`fdd2edab…`**（`checks/A/e0_n0_prereg.json` 的 LF 摘要） |
| 配置 LF/raw SHA256 | `ec396737…` | **`86b472416f30c7fbfa26b958d577a105e049571a863981b4d8285d7dea2d9470`** |
| 大小 | 8,444 B | 8,444 B（只改两个值，仍是纯 LF） |

同步改动（`solutions/A/run_n0_synthetic.py`）：

1. `FROZEN_N0_CONFIG_LF_SHA256` 更新为 `86b47241…`；
2. `prereg_contract` 检查新增**两端一致**条件：
   `prereg.accept_contract == n0_config.accept_contract`，否则 fail。这样“配置声明
   ACCEPT-2、包内消费 ACCEPT-3”的版本漂移不可能再悄悄通过。门禁仍是 **32 项**，
   只加严不加项。

未改：任何阈值、数值内核、`E0-N0-1` 契约字段、`n0_frozen.json` 行为。

## 2. 入口的实际路径（合成验证覆盖的四个文件）

| 角色 | 实际路径 | 模式 / 说明 |
|---|---|---|
| **实测侧正式执行入口** | `solutions/A/a_e0_c.py` | `--mode check`（默认，不解析采样）/ `execute` / `execute-worker`；`execute` 强制 `--approval-ref`，未放行只能跑 `check` |
| **N0 合成入口** | `solutions/A/run_n0_synthetic.py` | `worker` / `combine` / `two-process`；`--prereg` 默认 `checks/A/e0_n0_prereg.json`、`--n0-config` 默认 `experiments/A/A-Q1-E0/n0/n0_config.json` |
| **N0 打包器** | `solutions/A/a_e0_n0_package.py` | `assemble` / `write_package` / `selfcheck` / CLI `--prototype`；写 `E0-N0-1` 35 项 + 台账 |
| **N0 原型求解器** | `solutions/A/a_e0_n0.py` | 仅 `check` / `synthetic`，**没有** `execute`（实测需 E0-C 产物，B-02 放行前不做） |

即：N0 的实测链路是 `a_e0_c.py --mode execute`（真实 E0-C 产物）→ `a_e0_n0_package.py`
打包 → `accept_e0n0.py` 判读；本轮验证的是这条链路中**不读 `.dat`** 的合成侧。

## 3. 合成验证命令

```
# 0) 入口自检（13 项，约 25 s；含 preflight 32 项/dryrun 11 项/退出码回填/3 个拒绝用例）
python solutions/A/test_run_n0_synthetic.py -v

# 1) 两进程重建（约 3.5 min；顺序两进程 + combine，自动写台账）
python solutions/A/run_n0_synthetic.py --mode two-process \
    --out experiments/A/A-Q1-E0/n0/synthetic_two_process_accept3_cfg \
    --runs-dir tmp/n0_cfg_runs

# 2) 契约探针（外部工具；READY 不等于验收通过）
python <probe_producer.py> --results-dir <pack> \
    --prereg checks/A/e0_n0_prereg.json --json <pack>/verify/probe.json

# 3) ACCEPT-3 判读（必须给 --repo，否则 N12-P3 记 insufficient）
python <accept_e0n0.py> --results-dir <pack> --repo . \
    --report <pack>/verify/accept.json
```

## 4. 重建包（`experiments/A/A-Q1-E0/n0/synthetic_two_process_accept3_cfg/`）

| 项 | 实测 |
|---|---|
| 两进程 PID / 实际退出码 | **`46668` / `54076`**，**`0` / `0`** |
| 墙钟 / 峰值 RSS | 104.76 s / 257.68 MiB · 101.073 s / 257.926 MiB |
| 合计墙钟 | **205.833 s ≤ 600** |
| `results_sha256`（两次） | **`5a01480cdd2d6353c5e468d22da51b3cdec2cfb7f07e4a19e172f18d0753a87e`** |
| `arrays_sha256`（两次） | **`95fae44accb132afe0515a7986369b303a45960e213e2b2d2f46b58b75d04794`** |
| preflight / dryrun（每进程） | **32/32** / **11/11**；`prereg_contract = E0-N0-ACCEPT-3/frozen cfg=E0-N0-ACCEPT-3` |
| 配置 / 预登记绑定 | `n0_config_sha256 = 86b47241…`；`registration.prereg_sha256 = eef66e3e…`（raw） |
| `implementation_sha` | `9f8ab780f15dcceea148835d07609985ed4eeb36`（= 生成时干净 HEAD） |
| `real_dat_files_opened` | **0**；`frozen_artifacts_unchanged = true`；`freeze = not_eligible/False/False`，无 `n0_frozen.json` |
| 台账 | **16 行**（生产产物 13 + `SYNTHETIC.md` + `verify/probe.*`；不含 `verify/accept.*`，验收报告不写进台账以免自指），`selfcheck = SELF_OK` |

外部工具：

| 工具 | 结果 |
|---|---|
| `probe_producer.py` | **`READY` 722/722**，0 missing / 0 mismatch |
| `accept_e0n0.py`（`--repo` = 本 checkout） | **`FAIL` / `stop_condition = S9` / `failed_checks = ['N9']` / `insufficient_checks = []`**；`N15、N1–N8、N10–N14` 全 PASS（`N12` 配置字节绑定 match、`N13` 两进程、`N14` 台账 16 行 0 problem） |

`N9` 是合成值对真实 `b63e217` 基线的**预期**不等（`S9` 硬停仍生效），不是包缺陷。

## 5. 与旧包的关系

- `9f34cb8` 的 `synthetic_two_process_accept3/` 是**旧配置**（`ec396737…`，声明 ACCEPT-2）
  下的已核验证据，**保持原样、不覆盖**；其 `results_sha256 = 256d47a5…`。
- 新包只改配置字节（`86b47241…`）带来的差异：`results_sha256` 变为 `5a01480c…`；
  数组、`air_loo`、`metrics_sha256` 与旧包完全相同（合成夹具确定性），说明差异仅来自
  配置摘要字段，科学内容未变。
- 旧包的 `preflight.json` 记录临时目录 prereg 路径；新包记录仓库内路径。

## 6. 边界与待办

1. 纯合成：不证明 N0 方法有效；**B-02 / E0-T / S2 均未放行**。
2. `verify/accept.json` 是外部验收器原始报告；其 `N14` 记录 16 行台账。
3. 实测侧仍需 codex 的 B-02 放行编号；放行后由 `a_e0_c.py --mode execute` 出真实
   产物，再走同一打包/验收链路，并登记新的 `experiments/` 目录。

**Next owner:** `@codex` 复核 `9f8ab78` 与重建包（`5a01480c…`/`95fae44a…`、`READY
722/722`、`FAIL/S9/失败仅 N9`），裁定 B-02；`@my_deepseek` 可独立复验新包的配置绑定与
两进程一致性。**B-02 / E0-T / S2 均未放行。**
