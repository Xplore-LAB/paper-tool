# 交付物：Excel 台账与完成情况汇报

`deliverables.py` 是**只读导出器**：只读取 `--out` 下的 `manifest.json` /
`report.json` 与可选 CLI 快照，不修改检查点、不联网、不调用 Zotero API、
不解析 PDF 内容（仅判断文件是否存在）。Excel 用 OOXML 直接写出，仅依赖标准库。

## 四个子命令

| 命令 | 作用 |
|---|---|
| `ledger` | 生成 18 列 `文献清单.xlsx` |
| `translate-todo` | 生成/补齐 `标题翻译.json`，列出待译英文题名，**不覆盖已有译文** |
| `summary` | 生成 `完成情况汇报.md` |
| `both` | 一次生成台账 + 汇报 |

```powershell
python deliverables.py translate-todo --out <批次目录>
python deliverables.py both --out <批次目录> --collection '<完整路径>' --group '<课题组>'
```

可用 `--xlsx <路径>`、`--translations <文件>` 指定别处输出与映射；加 `--json`
输出结构化结果（含 `translated` / `untranslated` 计数）。

## 18 列字段

| # | 列 | 来源 |
|---|---|---|
| 1 | 序号 | 检查点行号 |
| 2 | 原始条目 | 用户给的参考文献原文 |
| 3 | 题名 | Crossref 标准题名 |
| 4 | **中文题名** | `标题翻译.json` 映射；中文原题名直接沿用；未译写「待翻译」 |
| 5 | 第一作者 | 题录 / 检查点 |
| 6 | 年份 | 题录 |
| 7 | 类型 | 题录 `type` → 会议名关键词 → DOI 前缀 → 卷期页 → 「待核验」 |
| 8 | 期刊或会议名称 | 题录 `container-title` |
| 9 | 卷期页 | 题录 |
| 10 | DOI | 题录 |
| 11 | 页面 URL | `https://doi.org/<DOI>`（不代表已访问出版社页面） |
| 12 | 课题组 | `--group` → 检查点 `group` → 「待填」 |
| 13 | 分级 | 人工 / 插件填；会议填 CCF 等级，期刊填分区与影响因子 |
| 14 | 下载状态 | 逐篇 `status` |
| 15 | 本地 PDF 路径 | 检查点 `pdf` |
| 16 | Zotero 分类 | `--collection` |
| 17 | 附件状态 | `audit` / 检查点 |
| 18 | 备注 / 待办 | warnings 与待办说明 |

题录 `type` 为 `proceedings-article` 等时按「会议」记；Zotero 里对应
`conferencePaper` + `proceedingsTitle` + `conferenceName` + `eventPlace`。
字符串以 `inlineStr` 写入，题名以 `=` 开头也不会被当成公式；首行冻结并加自动筛选。
第二张工作表「说明」记录生成时间、检查点路径、条数、类型分布、译文条数与各列口径。

## 中文题名

翻译**不在脚本里做**（保持零依赖、不联网）：由 Agent 或人工把
`{ "DOI 或英文题名": "中文题名" }` 写进 `<批次目录>\标题翻译.json`。
`translate-todo` 先按 DOI、再按英文题名匹配；中文原题名自动跳过；已填的译文不会被覆盖。
映射文件可复用、可复核、可改写，改完重导一次台账即可。

## 汇报口径

`完成情况汇报.md` 汇总状态分布、待办清单与验收数字。注意区分两种口径：
「本轮新下载 PDF」只统计本次下载，「题录入库」统计 Zotero 条目写入。
两者不等价时汇报会分别列出。

## Windows 双击入口

`generate-report.cmd` 把批次目录拖进窗口即可生成台账 + 汇报；课题组名称可放在
同目录 `课题组.txt` 第一行，或作为第二个命令行参数传入。
该启动器是 **GBK + CRLF**，由 `python _gen_launcher.py` 生成——改文案请改生成器模板，
不要直接编辑 `.cmd`（详见 [`CONTRIBUTING.md`](../CONTRIBUTING.md)）。
