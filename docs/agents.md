---
name: paper-tool
description: 把 DOI 或参考文献变成「已核验身份的 PDF」，可选写入已有 Zotero 分类；适用于文献批量下载入库、附件完整性核查、中断续跑与 Agent 调用。不适用于绕过付费墙、新建分类或非 Elsevier 订阅全文。
---

# CiteCargo：Agent 技能契约

把本文件复制到 `~/.workbuddy/skills/paper-tool/SKILL.md` 即可在对话中自动加载。
命令与验收依据见 [`usage.md`](usage.md)，字段口径见 [`reports.md`](reports.md)，
功能概览见 [`README.md`](../README.md)。**代码是最终事实。**

## 1. 目标与边界

| 是目标 | 不是目标 |
|---|---|
| Crossref 题录反查、OA 候选、机构订阅浏览器下载 | 文献阅读、摘要、综述生成 |
| 首页题名/DOI/作者核验、逐篇状态记录 | 新建/删除/移动 Zotero 分类与条目 |
| 只补缺失 PDF，已有附件不重复上传 | 绕过付费墙、验证码、Security verification |
| 断点续跑、进度/验收/待办清单 | 代做机构登录与短信验证 |

**四条不变式**：不新建/删除分类、不删除条目、不覆盖已有 PDF、不绕过验证挑战；用户数据只增不删。

## 2. 输入 / 输出契约

- **输入**：一条或多条参考文献条目，或直接给 DOI；可来自对话、`.txt` 清单或 `failures` 输出。
- **输出**：`stdout` 逐行 JSON（便于 Agent 解析）；批次目录里写检查点、PDF 与快照。
- **退出码**：`0` 完成（含 `METADATA_ONLY` 这类题录完成）；`2` 需要人工复核或参数错误。
- **写入开关**：Zotero 写入必须显式 `--zotero`，并给出已存在分类的完整路径。

## 3. 命令速查

```powershell
citecargo fetch '<DOI>' --out <PDF目录>
citecargo batch --input refs.txt --out <批次目录>
citecargo doctor --deep
citecargo collections --json
citecargo preview '<DOI 或参考文献>'
citecargo batch --input refs.txt --out <批次目录> --zotero --collection '<完整路径>' --dry-run
citecargo batch --input refs.txt --out <批次目录> --zotero --collection '<完整路径>' --oa-only --interval 0
citecargo batch --input refs-doi.txt --out <批次目录> --zotero --collection '<完整路径>' --metadata-only --interval 0
citecargo progress --out <批次目录> --json
citecargo audit    --out <批次目录> --json
citecargo failures --out <批次目录> --json
python -m paper_tool.reports translate-todo --out <批次目录>
python -m paper_tool.reports both --out <批次目录> --collection '<完整路径>' --group '<课题组>'
```

九个命令：`doctor` / `browser` / `collections` / `preview` / `fetch` / `batch` /
`progress` / `audit` / `failures`。规模由清单决定，不改代码。

## 4. Agent 使用要点

1. **先理解再执行**：拿到清单先只读预检，列出命中/待复核条数，别一上来就写 Zotero。
2. **分类必须让用户确认**：用 `collections --json` 取完整路径，不要猜分类名。
3. **DOI 回写**：预检查出的 DOI 写回清单，避免整批重复模糊反查；老论文、accepted、
   中文期刊容易判 `NEEDS_REVIEW`，补 DOI 后单独重跑。
4. **两种口径要分清**：汇报里「本轮新下载」与「题录入库」不等价，向用户复述时分开说。
5. **中文题名由 Agent 填**：先跑 `translate-todo`，逐条译好写进 `标题翻译.json`，
   再导出 18 列台账；不要改动脚本去内置翻译模型。
6. **订阅全文别硬来**：浏览器/VPN 未连时如实说明，把 17 篇之类待办列清楚，不要谎报成功。
7. **只读优先**：`doctor` / `collections` / `preview` / `progress` / `audit` / `failures`
   可随时跑；任何写入前先 `--dry-run`。

## 5. 交付物

18 列 `文献清单.xlsx`（含「中文题名」列）、`完成情况汇报.md`、`manifest.json`、
`progress/audit/failures.json`、`PDF/`。这些是运行时数据，不入库。

默认不连接 Zotero。先独立下载、以后入库时复用同一批次目录，再增加 `--zotero --collection`。`failures` 默认只列 PDF 待办，`failures --zotero` 包含归档待办。归档续跑复核当前分类和实时附件；不根据旧成功状态跳过写入目标检查。
