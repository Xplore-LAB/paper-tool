# 执行手册（SOP）

本文是唯一的命令与验收依据。接口契约见 [`workbuddy-skill.md`](workbuddy-skill.md)，
功能概览见仓库根目录 [`README.md`](../README.md)。**代码是最终事实**。

## 1. 流程

```
清单（参考文献 / DOI）
  → preview 或批量预检：Crossref 反查题录，低置信度标 NEEDS_REVIEW
  → 已有本地 PDF？是 → 首页题名/DOI 核验 → 复用
  → 否：OA 候选（OpenAlex / Unpaywall）→ 下载 → 核验
  → 订阅全文（仅非 --oa-only，且需已登录 Chrome + CDP）
  → Zotero：按 DOI 去重 → 复用/新建条目 → 增量加入目标分类 → 传 PDF 附件
  → manifest.json 逐篇记录 → progress / audit / failures → 导出台账与汇报
```

所有下载统一先核验本地文件，再尝试 OA；仅在失败后，且含支持的 Elsevier PII、未加 `--oa-only` 时尝试浏览器。默认不连接 Zotero，只有显式 `--zotero --collection` 才归档。

## 2. 人工前置（工具不代做）

| 事项 | 说明 |
|---|---|
| Zotero 授权 | 桌面端运行，首次调用时在弹出的对话框点「始终允许」；密钥在 Windows 上经 DPAPI 缓存到当前用户 LocalAppData 的 `paper-tool/auth/`（不入库） |
| 分类确认 | 用 `collections --json` 取**已存在**分类的完整路径，由用户确认；工具不新建分类 |
| 机构登录 | 订阅全文需要你本人登录、完成短信/出版社验证挑战 |
| 分级与课题组 | 台账的「分级」「课题组」由人工或插件提供，工具不臆测 |
| 中文题名 | 由 Agent / 人工填 `标题翻译.json`，工具不联网翻译 |

## 3. 标准步骤

```powershell
# 1. 体检（只读）
.\paper-tool.cmd doctor --deep
.\paper-tool.cmd collections --json

# 2. 只读预演
.\paper-tool.cmd preview '<DOI 或参考文献>'
.\paper-tool.cmd batch --input refs.txt --out <批次目录> --zotero \
  --collection '<完整路径>' --oa-only --dry-run

# 3. 正式执行（去掉 --dry-run）
.\paper-tool.cmd batch --input refs.txt --out <批次目录> --zotero \
  --collection '<完整路径>' --oa-only --interval 0

# 4. 验收快照
.\paper-tool.cmd progress --out <批次目录> --json > <批次目录>\progress.json
.\paper-tool.cmd audit    --out <批次目录> --json > <批次目录>\audit.json
.\paper-tool.cmd failures --out <批次目录> --json > <批次目录>\failures.json

# 5. 导出交付物
python deliverables.py translate-todo --out <批次目录>
#   填写 <批次目录>\标题翻译.json 后再：
python deliverables.py both --out <批次目录> --collection '<完整路径>' --group '<课题组>'
```

Linux/macOS 用 `./paper-tool`；任何平台都可用 `python paper_tool.py <command>`。

### 快速路径

```powershell
# 只要题录：命中库内 DOI 直接复用 Zotero 元数据，跳过 Crossref/OpenAlex/下载
.\paper-tool.cmd batch --input refs-doi.txt --out <批次目录> --zotero \
  --collection '<完整路径>' --metadata-only --interval 0
```

先跑 `python 文献工具箱\生成DOI清单.py <批次目录>` 一类工具把预检得到的 DOI
回写进清单，避免整批再做一次模糊反查。`--metadata-only` 算题录完成（退出码 0），
但 `failures` 仍列为「待补 PDF」；去掉该参数用同一目录续跑即可补全文。

## 4. 状态与失败分支

| 状态 | 含义 | 后续动作 |
|---|---|---|
| `PDF_ATTACHED` / `PDF_ALREADY_PRESENT` | 附件已挂、文件可读 | 无 |
| `METADATA_ONLY` | 题录已入库，本轮未下载 | 需要全文时去掉 `--metadata-only` 续跑 |
| `PDF_SAVED` | 本地 PDF 已核验 | 独立下载已完成；需要归档时加 `--zotero --collection` |
| `PDF_PENDING` | 未拿到可用全文 | 查 `failures`；订阅期刊需浏览器 + VPN |
| `NEEDS_REVIEW` / `MATCH_REVIEW` | 题录匹配不可信 | 人工补 DOI 后重跑 |
| `COLLECTION_REVIEW` | 分类路径未确认 | `collections --json` 后指定完整路径 |

上传中断后在原附件记录补传，使用 `If-Match` / `If-None-Match` 防止覆盖并发修改；不根据附件记录存在就认定全文已入库。远程文件无法直接读取时，`audit` 标记 `UNVERIFIED`，不会误报丢失。

不变式：单篇失败不影响后续；不新建/删除分类、不删除条目、不覆盖已有 PDF；
用户数据只增不删。题录不可信或分类不确定时**拒绝写入**并保留检索结果。

## 5. 验收判据

1. `manifest.json` 每行有 `doi` / `title` / `status`，Zotero 行有 `zotero_key`；
2. 目标分类内 DOI 数与清单一致（用 `collections` + 本地 API 只读核对）；
3. `audit` 的 `OK` 数为本机实际可读附件数；远程无法读取、缺失和损坏分开列出；
4. `failures` 只列真正待办的条目；
5. 汇报区分「本轮新下载」与「题录入库」两种口径，不混为一谈。

## 6. 性能建议

- 大批量优先 `--metadata-only`；已做过预检就把 DOI 回写清单。
- 批次内 Zotero 全库快照只加载一次，新建条目增量更新，不要恢复成逐行重扫。
- 模块级 `PDF_INTERVAL` 是全局限速；连续 OA 下载时可按需调整 `--interval`。
- 外部请求串行执行；高并发改造前先确认出版社条款。

## 7. 目录与文件约定

`<批次目录>` 下：`manifest.json`（检查点）、`PDF/`、`progress.json`、
`audit.json`、`failures.json`、`文献清单.xlsx`、`完成情况汇报.md`、`标题翻译.json`。
这些都是**运行时数据，不进版本库**（见 `.gitignore`）。

独立下载可直接运行 `python paper_tool.py batch --input refs.txt --out my-batch`。归档续跑会复核当前分类和实时附件；下载续跑只跳过哈希未改变的已核验 PDF。`--dry-run` 不连接 Zotero，仅给离线计划，分类在正式运行前验证。
