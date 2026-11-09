# CiteCargo 使用手册

## V2 任务接口

V2 保留旧 CLI 与检查点格式。计划默认离线：

```bash
citecargo plan --input refs.txt --out library --oa-only
citecargo job --plan library/plan.json
citecargo status --out library --json
```

`plan` 只读取输入并持久化计划，不下载、不写 Zotero；增加 `--metadata-preflight` 才查询公开题录。
`job` 重新校验计划与输入摘要，先试运行至多 5 篇，通过后每批至多 10 篇。首批异常时暂停剩余任务，记录 `PILOT_REVIEW`。
`status` 离线只读，结果、错误和恢复建议遵循[机器接口定义](../skills/citecargo/references/agent-protocol.schema.json)。

输入、输出目录、安全策略和归档范围绑定在计划里。输入变更后旧计划不能执行；新计划不能覆盖已绑定任务。哈希用于完整性校验，并非身份签名。
`manifest.json` 继续保存逐篇记录，新增 `job.json` 保存任务状态；单写入锁防止同一批次并发写坏。中断后沿用同一计划，复用已核验文件。

归档必须在计划中给出已有分类，执行时明确认可写入范围：

```bash
citecargo plan --input refs.txt --out library --zotero --collection "已有分类完整路径"
citecargo job --plan library/plan.json --allow-zotero
```

仅题录在计划时增加 `--metadata-only`。默认计划仅开放全文；计划时使用 `--institutional` 才启用已有授权浏览器路径。
本机接口与远程请求分开处理，下载仍无需 Zotero。UI 和浏览器后端本轮保持原有交互。

远程请求由任务专属策略调度：每来源串行、请求间隔至少 30 秒；每篇最多 2 次自动重试；运行预算 7200 秒，PDF 传输预算 2 GiB。
旧 `--interval 0` 仍能解析，但不能关闭远程来源的最小间隔。429 遵守 Retry-After，401/403 停用该任务中的来源；已完成文件保留。
预算、暂停来源和事件随任务持久化，恢复时沿用。策略作用于单个任务，不是跨进程、跨机器的统一出口计数器。

Python 的元数据、OA 下载和重定向逐请求受控；可选浏览器仍在 Python 操作入口管理，浏览器内部页面资源未逐请求接入。严格要求逐请求计量时使用 `--oa-only`。
更多停止原因与错误处理见[恢复规则](../skills/citecargo/references/recovery.md)。

V2 Skill 将 CLI 和锁定依赖内置为 wheel，初始化离线；Python、venv 或 ensurepip 缺失时只报诊断，不联网补装。构建清单区分 wheel 兼容性和已实测平台，按真实结果记录验证范围；需要严格要求六组运行验证时，可在构建时显式使用 `--require-matrix`。

## 本地操作页

Windows 用户下载发布页的操作页压缩包，解压整个文件夹后双击 `Start-CiteCargo.cmd`。
首次需要 Python 3.10+；基础依赖已打包，启动时在包内创建独立运行环境。
页面打开后粘贴 DOI 或完整参考文献，每行一篇，点击“开始下载”。
默认只查开放全文；勾选“使用学校订阅”启用机构浏览器回退，需完成下文的组件配置与机构登录。

macOS、Linux 或已安装工具的用户运行：

```bash
citecargo ui
citecargo ui --lang en
```

默认保存到用户目录 `Downloads/CiteCargo/PDF`，也可通过 `PAPER_TOOL_OUT` 或 `--out` 配置。
页面只在本机回环地址打开，启动窗口需保持运行。任务历史保留在本次运行内；重开后可重新粘贴清单，已核验 PDF 会被复用。
“补下未完成的论文”保留原归档设置，并采用当前“使用学校订阅”选项，不重复处理已完成条目。
归档需要主动勾选 Zotero、读取分类并选择已有目标；不勾选就不会连接 Zotero。

远程服务器运行时用 `citecargo ui --no-browser`，在自己电脑通过 SSH 转发页面：

```bash
ssh -N -L 8765:127.0.0.1:8765 user@server
```

再打开 `http://127.0.0.1:8765`。可通过页面取回 PDF；“打开文件夹”打开的是服务所在电脑的目录。

## 安装与源码运行

需要 Python 3.10+。安装发布页中的 Python 安装包（`.whl`），或在源码目录执行：

```bash
python -m pip install -e ".[dev]"
citecargo --version
```

`citecargo` 是新入口，`paper-tool` 保留兼容；`python -m paper_tool` 也可运行。

## 下载与续跑

```bash
citecargo preview "完整参考文献或 DOI"
citecargo fetch "10.1371/journal.pone.0000308" --out papers --oa-only
citecargo batch --input refs.txt --out library
citecargo progress --out library
citecargo failures --out library --write pending.txt
```

清单每行一篇，接受 DOI 或含作者、题名、期刊、年份的完整引用；UTF-8，支持空行和 `#` 注释。
按论文记录进度，重跑同一命令即可继续。已核验的文件按 SHA-256 复用；旧检查点缺少哈希时重新核验身份。
未完成文件会重新获取。默认正文，不另外下载 SI；串行处理，默认论文间隔 30 秒。
不要让多个进程同时写同一批次目录。

## Zotero 归档

需要 Zotero 10+ 开启本地 API，并在首次写入时授权。默认 `http://127.0.0.1:23119/api`。

```bash
citecargo collections --json
citecargo batch --input refs.txt --out library --zotero --collection "已有分类完整路径"
citecargo batch --input refs.txt --out library --zotero --collection "已有分类完整路径" --metadata-only
citecargo audit --out library --json
citecargo failures --out library --zotero --json
```

只接受已有分类。按 DOI 复用条目并增量加入分类；不覆盖题录、不删除条目。
每次归档复核本轮目标分类和实时附件，上传中断优先在原附件记录补传。
`--metadata-only` 仅处理题录，不检索或上传 PDF；需要全文时去掉参数重跑。

Zotero 在另一台电脑时，在那台电脑建立 SSH 反向转发：

```bash
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:23129:127.0.0.1:23119 user@server
```

服务器侧命令增加 `--zotero-base http://127.0.0.1:23129/api`。不要把未认证 API 暴露到公网。
远程 `file://` 属于 Zotero 所在电脑，无法读取时审计标记 `UNVERIFIED`；不会据此覆盖原附件。

## 机构订阅全文

```bash
npm install playwright-core
citecargo browser --start
# 在该浏览器完成机构登录，再下载
citecargo fetch "你的 DOI" --out papers
citecargo fetch "你的 DOI" --out papers --proxy http://127.0.0.1:1081
```

浏览器路径需 Node.js 22+、Chrome/Edge CDP 及已有访问权限。
原生 VPN 使用默认直连；已有 zju-connect 等 HTTP 代理可传 `--proxy`。
当前自动回退覆盖 Crossref 带 PII 的 ScienceDirect；其他出版商、授权失效或验证挑战保留待处理。
`--oa-only` 关闭机构浏览器；`doctor --deep` 仅检查环境，不证明订阅有效。

## 配置

模板见 [config.env.example](../examples/config.env.example)，需手动设置系统环境变量，不自动加载 `.env`。

| 变量 | 默认值或用途 |
|---|---|
| `PAPER_TOOL_OUT` | 当前目录 `downloads/` |
| `PAPER_TOOL_PROXY` | `direct` |
| `PAPER_TOOL_ZOTERO_BASE` | 本机回环 23119 |
| `OPENALEX_API_KEY` / `UNPAYWALL_EMAIL` | 可选 OA 检索配置 |
| `ZOTERO_LOCAL_API_KEY` | 可选本地 API 密钥，通常由桌面授权获取 |
| `PLAYWRIGHT_CORE_PATH` | 非标准位置的 Playwright |

Windows 记住的授权以 DPAPI 加密存入当前用户 LocalAppData，不放进源码或发布包。

## 1.x 接口与状态

稳定接口是 CLI；内部 Python 函数不作为公共 API。

- 子命令：`plan`、`job`、`status`、`ui`、`fetch`、`batch`、`preview`、`collections`、`browser`、`doctor`、`progress`、`audit`、`failures`。
- 退出码：`0` 表示所选任务完成；`2` 表示参数错误、待补或需复核。
- `fetch` 的 `report.json` 包含 `results` 列表；`batch` 的 `manifest.json` 是逐篇列表。
- 结果包含 `status`，按阶段提供 `paper`、`pdf`、`sha256`、`warnings`、`download_state`、`archive_state`；空值或缺字段不表示成功。
- 后续 1.x 可增加字段和警告，但不移除或改变这些接口的含义。

| 状态 | 含义 |
|---|---|
| `PREVIEW` | 只读题录及候选来源预览 |
| `PDF_SAVED` | 本地 PDF 已核验；归档结果另看 `zotero` 字段 |
| `PDF_ATTACHED` / `PDF_ALREADY_PRESENT` | 本轮上传或实时确认完成 |
| `METADATA_ONLY` | 仅完成题录入库 |
| `PDF_PENDING` | 未取得可核验全文 |
| `NEEDS_REVIEW` | 题录、文件或环境需复核 |

归档失败仍保留本地文件，任务返回非零。扫描件、提取失败或身份不确定的 PDF 留待人工复核。
`failures` 默认只列缺少有效本地 PDF 的论文，增加 `--zotero` 才包含归档待办。

## 导出与旧版迁移

```bash
python -m paper_tool.reports both --out library
```

详见 [清单导出](reports.md)。旧的 `python paper_tool.py` 改为 `python -m paper_tool`；
旧的 `python deliverables.py` 改为 `python -m paper_tool.reports`。
Windows 双击脚本移至 `scripts/windows/`，源码开发步骤见 [贡献指南](../.github/CONTRIBUTING.md)。
