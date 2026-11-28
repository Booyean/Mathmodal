# ⚠️ 合成夹具证据包（不可引用，ACCEPT-3 + 配置对齐重建）

- **性质**：`synthetic=true`、`citable=false`。本目录是 **A-Q1-N0 合成双进程证据**
  （`E0-N0-C12-SYNTHETIC-1`）在 `E0-N0-ACCEPT-3` 预登记、且 `n0_config.json` 的
  `accept_contract` 已对齐到 ACCEPT-3 之后的**重建包**（提交 `9f8ab78` 起）。它**不是**
  N0 实测结果，不得进入论文数字、结果表、冻结证据或 E0-T 放行材料。
- **它证明什么**：两个独立进程（PID `46668` / `54076`，实际退出码 `0` / `0`）经同一入口
  `solutions/A/run_n0_synthetic.py --mode two-process` 生成的 `E0-N0-1` 包，结果与数组
  **逐字节一致**（`results_sha256=5a01480c…`、`arrays_sha256=95fae44a…`）；合计
  **205.833 s ≤ 600**，峰值 RSS ≤ 257.9 MiB；两次 preflight `32/32`、dryrun `11/11`；
  契约探针 `READY 722/722`；`E0-N0-ACCEPT-3` 验收器 `N15、N1–N8、N10–N14` 全 PASS
  （含 `N12` 预登记/配置字节/生产 git 锚点绑定、`N13` 两进程证据、`N14` 台账），
  唯一 `N9` FAIL → `S9`：这是合成夹具对真实 `b63e217` 基线的**预期**不等。
- **它不证明什么**：不证明 N0 方法有效，不代表 B-02 / E0-T / S2 放行。
- **版本绑定**：
  - 预登记：`checks/A/e0_n0_prereg.json`（`E0-N0-ACCEPT-3`，raw `eef66e3e…` /
    LF `fdd2edab…`），入库提交 `c589713`；
  - 配置：`experiments/A/A-Q1-E0/n0/n0_config.json`（LF/raw 同为 `86b47241…`），
    `accept_contract=E0-N0-ACCEPT-3`、`anchors.prereg_sha256_lf=fdd2edab…`；
  - 入口新增一致性门：`prereg.accept_contract` 必须等于 `n0_config.accept_contract`，
    否则 `prereg_contract` 判 fail（防“配置声明 ACCEPT-2、包内消费 ACCEPT-3”的漂移）。
- **文件**：`e0c_*` 是 `E0-N0-1` 契约规定的固定文件名；`repeat/` 是第二个进程的产物；
  `verify/` 是探针与验收器的原始报告；`e0c_repeat.json` 的 11 个字段全部取自实际字节。
- **台账口径**：`SHA256SUMS.txt` 覆盖生产产物、`SYNTHETIC.md` 与 `verify/probe.*`；
  **不覆盖 `verify/accept.*`**——验收报告是作用于台账的外部判定，把它写进台账会自指。
- **复跑**（N0 合成入口，约 3.5 min）：
  ```
  python solutions/A/run_n0_synthetic.py --mode two-process \
      --out experiments/A/A-Q1-E0/n0/synthetic_two_process_accept3_cfg \
      --runs-dir tmp/n0_cfg_runs
  ```
  预登记与配置都用仓库默认路径（无需 `--prereg`）。验收器需 `--repo <checkout>`：
  ```
  python <accept_e0n0.py> --results-dir <本目录> --repo . --report <本目录>/verify/accept.json
  ```
- **完整说明**：`coordination/A_Q1_N0_PACK_ACCEPT3_CFG.md`。
