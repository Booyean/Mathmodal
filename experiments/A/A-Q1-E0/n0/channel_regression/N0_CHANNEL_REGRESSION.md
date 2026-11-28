# N0 复数秩一通道模态回归（`N0-CHREG-1`）

> 合成专用回归：`real_dat_files_read = 0`，未改数值内核；`build_rank2_basis` 的取向量约定在本次修复（`vh[0].conj()` → `vh[0]`），`n0/synthetic` 产物已重新生成并另行登记 SHA256。

## 结论

| 项 | 结果 |
|---|---|
| 方向恢复（允许任意全局相位） | **PASS** |
| 行方向重建 + `b_g = α_g` | **PASS** |
| 变异（旧式 `vh[0].conj()`）可探测 | **PASS** |
| 本地同式实现 == 生产 `D_1` | **PASS** |
| 总体 | **PASS** |

## 逐夹具数值

| 夹具 | 方向误差（对真值） | 方向误差（对共轭） | 行重建残差 max | `b−α` 相对误差 max | 负例方向误差 | 负例行残差 min |
|---|---|---|---|---|---|---|
| `flat_T` | 0.000e+00 | 1.414214 | 5.939e-16 | 1.003e-15 | 1.414214 | 0.277350 |
| `ramp_T` | 0.000e+00 | 1.414214 | 4.408e-16 | 1.144e-15 | 1.414214 | 0.263783 |

## 为什么旧夹具漏检

- 实方向 `[0.8165, -0.4082, -0.4082]`：`conj(γ)` 与 `γ` 只差全局相位（`conjugate_is_equivalent=True`），生产与变异的方向误差分别为 `0.000e+00` / `0.000e+00`，行残差分别为 `8.915e-16` / `8.915e-16`。
- 复方向 `(1, e^{2πi/3}, e^{4πi/3})/√3` 满足 `Σγ = 0`（扣整组复标度不变）与 `Σγ² = 0`（`γ ⟂ conj(γ)`），因此相位反转的实现与原方向正交，判据解析可证。

## 缺陷与数值影响

- 位置：`solutions/A/a_e0_n0.py::build_rank2_basis（逐频点 SVD 取通道权重）`；修复前 `v = vh[0].conj()` → 修复后 `v = vh[0]`（`found_and_fixed_in_this_commit`）。
- 合成夹具影响：`P1 min` **23.1791 → 26.1152 dB**、`P2 min` **24.5702 → 28.3957 dB**、`c2/c1` P1 **11.1677 → 14.1038 dB**、`c2/c1` P2 **11.6502 → 15.4757 dB**；判定不变（`L1=PASS`、`L2=FAIL（S8）`、`P3/P4/C8′` 仍 PASS）。

| 产物 | 修复前 SHA256（`207510c` 可复现） | 修复后 SHA256（当前提交产物） |
|---|---|---|
| `N0_SYNTHETIC.md` | `0c342a4f896c31a07fc7e4760c86d7af3274a62ab9958aab712b8bd2d27fbc5a` | `644e5b4f533f609ae940e0411bd0a2b40280d58d7f3a262e0090f691a18067ad` |
| `n0_synthetic_results.json` | `e2835b91ecc688b7f7bdf0ea427176e93911054b70820c658e53ccdb5631b6b0` | `69aca85a79a8f8180ec5960a3840de739185ed902b15c694e2754b118b3ce07d` |


## 生成溯源

| 项 | 值 |
|---|---|
| 生成代码 | `4b9d8f17a014006dbecbeaefbcad5dc3c4ea6a64` |
| 生成时间（UTC） | `2026-11-28T12:49:15Z`（system_clock） |
| 生成命令 | `python solutions/A/a_e0_n0_channel_regression.py --n-f 4 --out experiments/A/A-Q1-E0/n0/channel_regression` |

## 复跑

```
python solutions/A/a_e0_n0_channel_regression.py --n-f 4 --out experiments/A/A-Q1-E0/n0/channel_regression
python solutions/A/test_a_e0_n0.py ComplexChannelRegressionTests
```

逐字节复现：在同上命令后追加 `--generated-at 2026-11-28T12:49:15Z`（或设 `SOURCE_DATE_EPOCH=...`），并要求 `implementation_dirty=false` 且运行环境一致。

> SHA256 按 **LF 归一化**计算（`lf_sha256`，与 `b63e217` 产物同口径）；本仓 `core.autocrlf=true`，CRLF 检出不会让复核值漂移。

