# recon：A/B 两题数据侧侦察（定题前）

本目录是**定题前**的数据侦察成果，只做三件事：**核原件、验协议、出缺项**。不含任何求解代码、不含模型假设、不改动 `竞赛题目/` 下的原件。

- 报告（先读这个）：[`reports/data_recon_report.md`](reports/data_recon_report.md)
- 机器可读清单：`manifests/`
- 真实小样：`samples/`
- 可复跑脚本：`scripts/`

## 版本锚定

| 项 | 值 |
|---|---|
| 基线提交 | `origin/main` = `d8ee44021dd7acec18e7fd608e50835b0f7e8dd9` |
| A 题 `.dat` 清单哈希 | `86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06`（881 文件，801,111,612 B） |
| B 题清单哈希 | `79ce9798af0fe5e0c002f4601c03f1efa3df371bc1a900825250ddedcb5d1dd2`（12 文件） |

清单哈希的算法：把 `sha256 + 两个空格 + 相对路径` 按**清单行序**以 `\n` 连接（末尾补一个 `\n`），取整体 SHA256。该行序来自 `scripts/a_inventory.py` 对 **OS 路径字符串**（`\` 分隔）的排序，等价于直接按 `manifests/a_dat_manifest.csv` 的行序读取。

> 注意：按 CSV 的 `rel_path` 列（`/` 分隔）重新排序会得到 **不同** 的摘要 `02fbffdeb705aa81da9832877bd2d86fbf495efd24ef2530d1cbe5f6d04b0140`——`/`(0x2F) 与 `\`(0x5C) 的码位不同，目录与其子文件的相邻顺序会变。复算请直接用行序，勿再排序。

复算（在仓库根目录执行，输出应与上表 `86305548…` 一致）：

```python
import csv, hashlib
rows = list(csv.DictReader(open("recon/manifests/a_dat_manifest.csv", encoding="utf-8-sig", newline="")))
data = "".join(f"{r['sha256']}  {r['rel_path']}\n" for r in rows)
print(hashlib.sha256(data.encode("utf-8")).hexdigest())  # 86305548ac35e44bf07f15fbbfa2e10c30713d0e64721e7ec81d37939f3cfa06
```

## 复跑

```powershell
python recon/scripts/a_inventory.py    --root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题"
python recon/scripts/a_inventory.py    --self-test   # 边界值单测：±满量程、-32767 邻界、单包/多包汇总口径
python recon/scripts/a_period_check.py --root "竞赛题目/A 题：单发多收下的雷达信号处理及成像问题"
python recon/scripts/b_tables.py       --root "竞赛题目/B题：炼钢厂钢包周转与排产优化问题"
python recon/scripts/b_qc.py           --root "竞赛题目/B题：炼钢厂钢包周转与排产优化问题"
```

只读原件、只写本目录；无随机源，重复运行结果一致。脚本会覆盖自己上一次的输出（先用 git 看 diff 再决定是否提交）。

## 依赖

`numpy`、`openpyxl`、`xlrd==2.0.2`（读旧版 `出钢计划表单.xls`），其余为 Python 标准库。
`xlrd` 若无法用 `pip install` 装（本沙箱内 pip 不能在临时目录建文件），可下载官方 wheel 解包后加入 `sys.path`：

- wheel：`xlrd-2.0.2-py2.py3-none-any.whl`
- SHA256：`ea762c3d29f4cca48d82df517b6d89fbce4db3107f9d78713e48cd321d5c9aa9`
- 脚本默认在 `../pylibs`、`D:\数模\pylibs` 两个位置查找。

## 复现时最容易踩的坑（都已处理）

1. **xlsx 的 `<dimension>` 被写死成 `A1`**：`A炉/B炉/C炉/1#连铸/2#连铸/3#连铸` 这 6 个文件用 openpyxl 只读模式默认只读到 1 个单元格，看起来像空表。必须先 `ws.reset_dimensions()`。
2. **A 题的"组"不是目录**：附件 3 把 33 组（墙体）/27 组（金属目标）全放在同一目录，必须按**文件名里的采集时间戳**分组；按目录分组会把它们算成 1 组。
3. **A 题每文件包数 2–6 不等**：同一组的 8 个行文件偶尔少最后一包，跨行对齐要按组内最小包数。
4. **A 题 `_3` 文件第 4 列是发射天线**，实测无有效信号（RMS 仅最强通道的 0.25%），必须跳过 → 63 路。
5. **B 题的"时长列"不可信**：1044 个负值（例 `-3分钟\t-51秒`，还夹制表符），这是**负时长单元格数，不是故障炉次数**；必须由两列时间戳重算。
6. **B 题熔炼号不唯一**：综合主表 1278 个唯一值/1355 行（1350 非空 → **72 条额外记录**），LF 表也有重复；跨表连接前先去占位符 `-2`、再定义重复的含义。
7. **A 题 int16 极值必须升位统计**：`np.abs(np.int16(-32768))` 会回绕成 `-32768`，导致负满量程漏计；必须先转 int32。且只统计每文件首包会漏掉其它包——实测 46 个 `-32768` 全在 `金属柱/2026-11-12-22-09-58_16000_1.dat` 的最后一个包，均为孤立单点（非持续饱和），统计时应标记异常，不能写"全库无削顶"。端点判据用有符号存储端点 `+32767` / `-32768`，**不要用 `|x| >= 32767`**：它会把 `-32767` 也计入。逐通道 `abs(mean)` 必须除以该通道自己的样本数，不能除以 8 通道总样本数。

## 不包含

- 不做清洗成品（`data/processed/`）、不做求解、不写模型结论——等题号与口径（见报告 §5 D-01～D-08）确定后再落。
- 不复制原始附件：原件以 `竞赛题目/` 下的 git 版本为准，避免仓库里出现两份 800 MB 数据。
