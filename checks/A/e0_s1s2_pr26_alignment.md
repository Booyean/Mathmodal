# E0-S1/S2 交付 PR #26 对齐记录（E0-ACC-1A）

- **记录方**：`my_deepseek`（独立验证）。
- **触发任务**：统筹 `codex` 要求核对 PR #26 的实现提交、结果提交是否与 PR #25 的验收对象一致，并记录噪声摘要的两种计算口径；一致则复用已有验收证据。
- **结论**：**一致（对象逐位同一）**。PR #26 的 head 就是 `5d14b7b`，两个提交就是 `652fc53` + `5d14b7b`；因此**复用 PR #25 的 P1–P17 验收证据**，不重新判定数值结论。本记录只补充 P17 的“两种口径”对照，并保存机器可读证据。
- **边界**：只核对交付对象与摘要口径；未重跑估计器、未读取任何真实 `.dat`、未修改生产实现。结论仍只覆盖 `E0-S1`/`E0-S2` 合成闭环，不覆盖 `E0-C`/`E0-T`。

## 1. 对象同一性

| 项 | PR #25 验收对象 | PR #26 实际 | 判定 |
|---|---|---|---|
| 结果提交（head） | `5d14b7ba4f5b3f3b692a10ba94588ba23ffa85d6` | `5d14b7ba4f5b3f3b692a10ba94588ba23ffa85d6` | 相同 |
| 实现提交 | `652fc532fb7046645f570f8a046ea38e30f54f50` | `652fc532fb7046645f570f8a046ea38e30f54f50` | 相同 |
| 实现提交父提交 | `b10264b0958b44dec527457635b410a999fb77f3` | `b10264b0958b44dec527457635b410a999fb77f3` | 相同 |
| 分支 / base | `data/a-q1-e0-s`；验收时 `origin/main = df24c44` | `data/a-q1-e0-s`；PR base = `df24c44` | 相同 |
| 提交数 | — | 2（无额外提交） | 通过 |

核验证据（均在本地独立副本复核）：

- 远端 ref：`git ls-remote origin refs/heads/data/a-q1-e0-s` → `5d14b7ba4f5b3f3b692a10ba94588ba23ffa85d6`。
- `git rev-list --count df24c44..5d14b7b` = **2**；`git rev-list --parents` 给出 `5d14b7b → 652fc53 → b10264b`，即结果提交是且仅是结果登记。
- 提交对象树：`652fc53` = `524d3c8baa965b89c7d3f7df1d42b217d41c6e69`，`5d14b7b` = `3d4b1c7bf124bf3365112921f56e5e9afa3a942f`。Git 提交 SHA 由内容寻址，SHA 相同即对象相同。
- 改动范围：`git diff --name-status 652fc53..5d14b7b` **只新增 5 个结果文件**（`SHA256SUMS.txt`、`e0_s1s2_arrays.npz`、`e0_s1s2_results.json`、`e0_s2_param_table.json`、`run.log`）；`git diff --stat b10264b..5d14b7b` = **8 文件 / +3960 行**，与 GitHub PR #26 的 `changed_files=8 / additions=3960` 一致（另 3 个为实现文件）。
- 合并预检：`git merge-tree --write-tree df24c44 5d14b7b` = `0cabd318d7319b11cee4b64dd38b6fe7de0d2c4c`，退出码 0；与 PR #25 §4 记录的 `0cabd318…` 相同。GitHub API 同时给出 `mergeable=true`、`mergeable_state=clean`。
- GitHub API：PR #26 `state=open`、`commits=2`、`head.sha=5d14b7b`、`base.sha=df24c44`、`created_at=updated_at`（建 PR 后无强制推送更新）。
- 结果 JSON 锚点：`implementation_sha=652fc53…`、`parent_commit=b10264b…`、`branch=data/a-q1-e0-s`、`overall_pass=true`、`stop_reason=null`。
- 文件完整性：`SHA256SUMS.txt` 的 4 个文件全部与实际字节一致；结果 JSON 的 `arrays_file_sha256=27bea969…`、`s2_param_table_file_sha256=93ff023e…` 均与实文件一致。

## 2. 噪声摘要的两种计算口径

两者作用在**同一批** 12 个 `63×4000` `float64` 矩阵上（`numpy.random.default_rng(20261128)`，顺序 `air_0..air_9, E0-S2@0.42, E0-S2@0.69`），但摘要前缀不同，字符串**不可直接比较**。

| 口径 | 精确定义 | 使用位置 | 备注 |
|---|---|---|---|
| **原始字节 SHA256**（oracle） | `SHA256(x_float64_C_order.tobytes(order="C"))` | E0-PREREG-2 oracle `noise.rows[].sha256`、`noise.concat_sha256` | 不含 dtype/shape 前缀 |
| **`array_sha256`**（交付） | `SHA256(utf8(str(dtype)) ‖ utf8(repr(shape)) ‖ C_order_bytes)` | 交付 JSON `s2_noise_sha256_raw`、`s2_noise_sha256_scaled` | `str(dtype)="float64"`，`repr(shape)="(63, 4000)"`（含空格） |

补充口径：

- `s2_noise_sha256_scaled` 是 **`sigma * raw` 缩放后矩阵**的 `array_sha256`，不是原始矩阵的字节摘要；`sigma = 226.92695528713034`，`sigma2 = 51495.84303588726`，两者满足 `sigma2 ≈ sigma²`。
- `arrays_sha256`（交付 JSON 顶层聚合）又是另一层：`SHA256(按 key 升序拼接 utf8(key) ‖ ascii(array_sha256))`，不参与本节的逐组口径对照。
- oracle 的 `concat_sha256` 是 12 个矩阵按上述组序**原始字节直接串接**后的 SHA256 = `e56efec8ed1fa534b9714c02d5a323e4b544fc453d970e1016eca213ef7d3875`；交付 JSON 没有对应的“串接口径”字段，不可把 `arrays_sha256` 当成它。

### 2.1 逐组对照

下表为组名、两种口径的前 16 位十六进制，以及三项判定（完整 64 位值见 `noise_digest_calibers.json`）：

| 组 | 原始字节 SHA256（对 oracle） | `array_sha256`（对交付 raw） | `scaled array_sha256`（对交付 scaled） | 判定 |
|---|---|---|---|---|
| `air_0` | `8e5ac2fc4af4d1fe` | `df2f178697768449` | `a5bb11e075cd6aeb` | 3/3 一致 |
| `air_1` | `3ecfe4b4ba5f6fb8` | `a085f48098dd405e` | `ebb682c706432573` | 3/3 一致 |
| `air_2` | `5718dcd1e7b78c9a` | `e886560bcc7896ea` | `990b45e9b32cd164` | 3/3 一致 |
| `air_3` | `08d1f2ccd490f3fd` | `3b4252bbfb11e11e` | `2dd43bb288e7c4b0` | 3/3 一致 |
| `air_4` | `5f56f344bd8e3bdc` | `c7b73b85b1e06727` | `c1f6bf9c31ec0ff5` | 3/3 一致 |
| `air_5` | `2c2632aba8836095` | `d4f21ac19f480435` | `57388050494bb049` | 3/3 一致 |
| `air_6` | `d8c86901bd2c08f3` | `0b50ab8729f23752` | `a34903246e636d45` | 3/3 一致 |
| `air_7` | `f1f06a8076f097cd` | `a6bf3f94c65b44ac` | `136eb503eec53eb4` | 3/3 一致 |
| `air_8` | `c98ebd39b1e2230b` | `104e6abe6fe391c6` | `920d9f64d0f6a4c7` | 3/3 一致 |
| `air_9` | `50d722aa5321e04a` | `b9df2f7d2e9e9432` | `ea1044d03c804ad3` | 3/3 一致 |
| `E0-S2@0.42` | `54777680a0e33be1` | `46aca03f683dcc03` | `913683184920bf98` | 3/3 一致 |
| `E0-S2@0.69` | `983f991b11f695be` | `d9acdd70e24fbde4` | `540752f73491b3bb` | 3/3 一致 |

- 参数表规范 SHA256 复建值 = `aa86bf56fb138789cd0ad4375691293e7d0e5d65a2daf678d151d44720576e96`，同时匹配 oracle 与交付 JSON。
- 11 个触发偏移最大差：复建 `0`，交付值 `2.22e-16`（预登记容差 `2e-15`）。
- 逐组首/末元素与 oracle 完全相等。
- 环境复现：CPython 3.13.7 + numpy 2.1.3 与 CPython 3.9.13 + numpy 1.26.4 下，12 组的三套摘要**完全一致**。

## 3. 复跑命令

```powershell
# 结果目录取自 PR #26 head 5d14b7b；oracle 取自 PR #24 / 5151844
python checks/A/e0_acceptance/noise_digest_calibers.py `
  experiments/A/A-Q1-E0/s1s2/results `
  checks/A/e0_s2_stream_oracle.json
```

- 机器可读证据（本记录同目录）：`checks/A/e0_acceptance/noise_digest_calibers.json`。
- 预期输出末行：`RESULT: ALL_NOISE_DIGEST_CALIBERS_PASS`。
- 脚本不导入生产实现，只按预登记种子重建 RNG 流，再分别按两种口径重算摘要。

## 4. 判定与遗留

1. **对象一致，复用 PR #25 验收证据**：P1–P17 的结论、命令、差异说明继续有效；本记录只补 P17 的口径对照，不产生新的数值通过项。
2. **两种口径都已核对**：oracle 的原始字节口径与交付的 `array_sha256` 口径分别独立复建并逐组相等；不存在“字符串不同即数据不同”的问题。
3. **基线漂移仍记录**：交付 JSON 的 `main_commit = b10264b` 是运行时的 `origin/main`；PR #26 的 base 是 `df24c44`。两者是不同用途的锚点，合并预检干净，不构成对象不一致。
4. **未覆盖范围**：`E0-C`（真实空场/校准）与 `E0-T`（留出盲评）仍未放行；本记录不构成对二者的任何通过意见。
