# C12 独立运行证据契约（E0-C-C12-REPEAT-1）

- **性质**：对 `E0-PREREG-3` 的 C12 作**证据形态澄清**，不改变 C1–C15 的门槛、容差与
  通过/失败动作；`E0-PREREG-3` 的冻结常量（`checks/A/e0_c_prereg.json`）不动。
- **依据**：统筹 `codex` 2026-11-28 频道裁定——C12 需要**两次独立运行**的证据；
  `repeat_run` 目前是同一批数组的两次序列化，不能作为确定性证据（阻塞 E0-C 放行）。
- **机器可读**：`checks/A/e0_c_repeat_contract.json`（检查器会把它与预登记的 SHA256
  一起写进报告）。

## 1. 什么算“两次独立运行”

必须是**两个独立进程**、各自完整跑完 E0-C、各自产出一套数组与结果文件，并且：

| 要求 | 说明 |
|---|---|
| 两次运行记录 | `e0c_results.json` 的 `repeat_run.runs[2]`，或交付目录下 `e0c_repeat.json` 的 `runs[2]` |
| 必填字段 | `run_id`、`pid`、`started_at`、`finished_at`、`results_file`、`results_sha256`、`arrays_file`、`arrays_sha256`、`wall_time_s` |
| 时间戳 | ISO-8601 且带时区（`Z` 或 `+08:00`）；`started_at < finished_at`；`runs[0]` 先于 `runs[1]`，时间窗不得重叠 |
| 文件 | 相对交付目录，禁止绝对路径与 `..`；每个文件必须存在，实际 SHA256 = 记录值 |
| 绑定 | `runs[0]` 必须就是本次交付的 `e0c_results.json` / `e0c_arrays.npz` |
| 互不相同 | `run_id`、`pid`、两个时间戳、两个文件路径都不得相同；复用同一数组/结果文件直接判“重复序列化” |
| 第二次运行的结果 | 必须是完整结果 JSON：12 组齐全、`metrics_sha256` 与其自身 `groups` 重算一致、`arrays_sha256` 与其自身 npz 一致 |
| 第二次运行的数组 | 组集合与数组名集合必须与第一次相同；检查器用它的 npz **独立重算**两个目标组的 `Supp/PSLR/PNR/d_hat/abs_err`，与交付 JSON 逐项比对（dB `1e-6`、cm/m `1e-9`） |

## 2. 什么不算证据（负例）

- 同一批数组序列化两次（两个相等的哈希）；
- 同一文件被两个记录指向；
- 同一 `pid` / 同一时间窗 / 只改 `run_id` 的两条记录；
- 只写“两次独立序列化逐字节一致”的说明文字，没有第二次运行的产物。

上述任一情况，`accept_e0c.py` 的 C12 判 **FAIL**，并在
`checks[].detail.duplicate_serialization_detected = true` 中标出。

## 3. 交付示例（最小）

```json
{
 "runs": [
  {"run_id": "e0c-run-a", "pid": 41001,
   "started_at": "2026-11-28T06:10:00Z", "finished_at": "2026-11-28T06:12:33Z",
   "results_file": "e0c_results.json", "results_sha256": "<sha>",
   "arrays_file": "e0c_arrays.npz", "arrays_sha256": "<sha>",
   "wall_time_s": 153.2},
  {"run_id": "e0c-run-b", "pid": 41522,
   "started_at": "2026-11-28T06:20:00Z", "finished_at": "2026-11-28T06:22:31Z",
   "results_file": "repeat/e0c_results.json", "results_sha256": "<sha>",
   "arrays_file": "repeat/e0c_arrays.npz", "arrays_sha256": "<sha>",
   "wall_time_s": 151.9}
 ]
}
```

两次运行的数组**允许逐字节相同**（单线程确定性），独立性由 PID、时间窗与各自独立
文件承载；检查器不会因为字节相同而判失败，只会因为“没有第二次运行的产物/进程证据”
或“第二次运行结果与第一次不一致”判失败。

## 4. 复跑

```powershell
python checks/A/e0_c_accept/test_accept_e0c.py   # 正向 + 负向（含重复序列化负例）
python checks/A/e0_c_accept/accept_e0c.py --results-dir <交付目录> --repo . --report report.json
```

`test_accept_e0c.py` 中新增的负例覆盖：只有重复序列化（无 `e0c_repeat.json`）、两次
运行指向同一数组文件、同一 PID/时间窗、第二次运行的 npz 缺失、第二次运行指标不一致、
第二次运行数组被篡改。
