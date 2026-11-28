# ⚠️ 合成夹具证据包（不可引用）

- **性质**：`synthetic=true`、`citable=false`。本目录是 **A-Q1-N0 合成双进程证据**
  （`E0-N0-C12-SYNTHETIC-1`），不是 N0 实测结果，**不得**进入论文数字、结果表、
  冻结证据或 E0-T 放行材料。
- **它证明什么**：两个独立进程（PID `12680` / `17900`，实际退出码 `0` / `0`）经同一入口
  `solutions/A/run_n0_synthetic.py` 生成的 `E0-N0-1` 包，其结果与数组**逐字节一致**；
  契约探针 `READY 721/721`；正式验收器 `N1–N8、N10–N14` 全 PASS（含 `N13` 两进程证据），
  唯一 `N9` FAIL → `S9`，这是合成夹具对真实 `b63e217` 基线的**预期**不等。
- **它不证明什么**：不证明 N0 方法有效，不代表 B-02 / E0-T / S2 放行。
- **文件**：`e0c_*` 是 `E0-N0-1` 契约规定的固定文件名；`repeat/` 是第二个进程的产物；
  `verify/` 是本轮探针与验收器的原始报告；`e0c_repeat.json` 的 11 个字段全部取自实际字节。
- **完整说明**：`coordination/A_Q1_N0_TWO_PROCESS.md`。
- **复跑**：`python solutions/A/run_n0_synthetic.py --mode two-process --out <dir> --runs-dir <runs> --prereg <e0_n0_prereg.json>`（约 3–4 min，顺序两进程）。
