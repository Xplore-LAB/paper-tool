# Reference → PDF → Zotero 10+：最小可运行版本

## 推荐入口：paper-tool

仓库只保存源码、说明和测试。论文 PDF、运行报告、虚拟环境、VPN 配置和登录状态均不提交；文中本机路径及历史验证结果描述的是开发服务器，克隆仓库后需配置自己的环境。Zotero 真实跨电脑归档尚未完成验收。

本机已安装 `/home/lab434/.local/bin/paper-tool`，实现为项目内 Python 命令入口＋浏览器下载后端。适合终端使用、Agent 调用及逐篇批处理，不新增后台 Web 服务。

```bash
paper-tool doctor
paper-tool preview '10.1016/j.ins.2026.123800'
paper-tool fetch '10.1016/j.ins.2026.123800'
paper-tool fetch --input references.txt
paper-tool fetch --input references.txt --oa-only
```

默认 PDF 保存到 `/home/lab434/data/papers/reference-to-zotero/`，可用 `--out` 指定原有目录。流程为 Crossref 识别、开放 PDF、ScienceDirect 浏览器回退、首页题名核验、哈希、逐篇更新 report.json；已核验的本地 PDF 直接复用。参考文献有歧义、PDF 不匹配或需要登录验证时不宣称成功，返回非零退出码和逐篇状态。批处理按原始输入去重、串行执行，默认论文间隔 30 秒，不限制文件传输速率；历史报告按 DOI 合并保留。

需要机构下载时，zju-connect 和现有 Chrome 必须已运行；`doctor` 只检查端口，并不证明账号或订阅权限。VPN 短信验证、出版社交互验证需要人工完成后重新执行。浏览器回退目前支持 Crossref 给出 Elsevier PII 的 ScienceDirect 文献；其他出版社不会假装同样可用。

Zotero 写入默认关闭。在另一台电脑建立前文的 SSH 反向转发后，先预览，再显式指定写入与已有分类：

```bash
paper-tool fetch '10.1016/j.ins.2026.123800' --zotero --collection '已有分类完整路径'
```

默认转发 API 是 `http://127.0.0.1:23129/api`，可用 `--zotero-base` 更改为另一本机回环端口。分类不确定不写入；首次归档仍需在真实 Zotero 确认授权。原有题录/附件写入只有模拟协议验证，尚未连接另一台电脑做实际验收。

开发验证：`.venv/bin/python -m unittest -v`。完整项目包含旧接口兼容入口与新 `paper_tool.py`、`paper-tool`、`browser_pdf.mjs`、`test_tool.py`。


## 服务器适配版 v0.2（2026-11-05）

工程位于 `/home/lab434/src/projects/paper-to-zotero`，使用独立 `.venv`。正文下载，不另外获取 SI。

本版新增 PDF 专用 HTTP 代理、明确授权的出版社全文尝试、显式 PDF 地址、Zotero SSH 转发地址，以及 HTTP 协议集成测试。修复授权重试丢失 JSON Content-Type、附件上传地址使用远端原始端口、仅因参考文献含目标 DOI 而误认 PDF、同名出版物未按期刊区分的问题。Zotero 10 本地接口默认不分页，本版使用显式分页分批读取，不表示旧版必然漏项。

Linux 安装和测试：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest -v
```

服务器真实运行（Zotero 不连接）：

```bash
.venv/bin/python paper_to_zotero.py --ref 'Piwowar HA, Day RS, Fridsma DB. Sharing Detailed Research Data Is Associated with Increased Citation Rate. PLoS ONE, 2007.' --no-zotero --apply --out runs/reference-to-pdf
.venv/bin/python paper_to_zotero.py --input sample_references.txt --institutional --no-zotero --apply --out runs/user-paper-institutional
```

`--institutional` 使用 Crossref 给出的出版社 PDF 链接，或从 Elsevier 的明确 PII 构造出版社下载入口。学校授权、浏览器登录和验证仍以实际站点响应为准；HTML/403 不会保存成 PDF。可通过 `--pdf-url 'https://…/paper.pdf'` 提供一个已知授权 PDF 地址，仅适用于单篇输入。PLOS ONE 提供无需 API key 的 OA 出版社回退；其他出版商仍依赖开放元数据或显式 PDF 地址。

使用已运行的 zju-connect HTTP 代理时，给下载命令加 `--pdf-proxy http://127.0.0.1:1081`；实际端口以客户端配置为准。默认 PDF 直连，元数据检索保留原网络配置，Zotero 回环请求始终绕过代理。RVPN 授权下载已按下述浏览器协同路径实测通过。

下载节奏默认：单进程串行，不限制传输速度（--pdf-rate-kib 0）；每次 PDF 获取尝试结束后至少间隔 30 秒再试下一份。失败链接也计入间隔；已核验的本地文件直接复用。可用 `--pdf-rate-kib` 和 `--download-interval` 调整。限速与间隔通过模拟时钟和响应流验证。

2026-11-05 RVPN 实测结果：zju-connect v1.3.1（官方发行包 SHA-256 已核对）已建立 aTrust 连接，只监听回环 1080/1081。ScienceDirect 主站与 PDF 主机走 VPN，公开静态 CDN *.elseviercdn.cn 直连，避免 VPN ACL 拒绝前端脚本后 PDF 按钮失效。浏览器显示 Zhejiang University Library / Full text access，沿实际 View PDF 链接打开 PDF 页面后，在该页面上下文中读取 PDF，未导出 Cookie 或保存临时签名 URL。目标 DOI 10.1016/j.ins.2026.123800 正文已保存，18 页、8,718,456 字节，首页题名与 DOI 均核验通过。普通脚本请求仍可能返回 403，不能把它当作无订阅权限；此路径实际需要浏览器协同。此次未连接另一台电脑的真实 Zotero。

### Zotero 在另一台电脑

在 Zotero 电脑开启本地 API，并在该电脑终端建立仅绑定服务器回环的 SSH 反向转发：

```bash
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:23129:127.0.0.1:23119 lab434@服务器地址
```

然后服务器上读取已有分类：

```bash
.venv/bin/python paper_to_zotero.py --list-collections --zotero-base http://127.0.0.1:23129/api
```

先不带 `--apply` 检查匹配结果与已有 Collection，再加 `--apply` 归档。首次写入需要在 Zotero 电脑确认授权。上传 URL 自动适配转发端口。不要将 Zotero API 直接监听或发布到校园网/公网；SSH 连接保持运行。

验证范围：真实 Crossref、PLOS 下载和 PDF 首页题名核验已通过；Zotero 授权、创建条目、三阶段上传、重复运行复用通过回环 HTTP 模拟服务器验证，未连接实际桌面 Zotero。原始 v0.1 的 10 项测试保留，新增测试见 `test_transport.py`。

官方协议依据：https://www.zotero.org/support/dev/web_api/v3/local_api

以下为原始 v0.1 使用说明，PDF 身份核验以本版“首页题名必须匹配”为准。

输入原始参考文献（无需 DOI），匹配 Crossref 题录，在 OpenAlex/Unpaywall 查找合法开放获取 PDF，验证文件身份后关联到 **已有** Zotero Collection。若 PDF 受限，仍可将准确题录入库，并在报告中保留待补状态。

本版本面向在 **运行 Zotero 的同一台电脑** 上使用的 Codex CLI / Python。它不访问浏览器登录状态、不获取学校账户密码、不绕过付费墙。

完整架构、验收协议和下一阶段计划见 `DESIGN.md`。

## 1. 安装

要求：Python 3.10+、Zotero 10+（本地写 API 已启用）、网络可访问 Crossref/OpenAlex。

```powershell
py -3 -m pip install pypdf
```

在 Zotero 中打开 **设置 → 高级**，勾选 **Allow other applications on this computer to communicate with Zotero**（允许其他程序与 Zotero 通信），并保持 Zotero 桌面端运行。

> Zotero 10+ 首次写入会弹出授权对话框，请核对程序名称后授权。选择 Always Allow 可以减少再次授权；不要对不信任的本机程序授权。

`OPENALEX_API_KEY`（可选，建议免费注册）和 `UNPAYWALL_EMAIL`（可选）通过环境变量配置；不要写入共享仓库：

```powershell
$env:OPENALEX_API_KEY = "你的OpenAlexKey"
$env:UNPAYWALL_EMAIL = "你的学术邮箱"
```

## 2. 先做完全离线的最小测试

```powershell
py -3 -m unittest -v test_paper_to_zotero.py
py -3 paper_to_zotero.py --demo --no-zotero
```

预期：单元测试通过，第二个命令输出 `PREVIEW` 和报告文件 `paper_downloads/report.json`。这里采用本项目中已验证的示例元数据，并**模拟没有开放 PDF**；它不测试真实网络/真实 Zotero。

## 3. 查看 Zotero 已有 Collection

```powershell
py -3 paper_to_zotero.py --list-collections
```

会输出形如 `工业人工智能/工业时序预测` 的完整层级路径。不会新建 Collection。

## 4. 用实际参考文献试运行（只读预览）

```powershell
py -3 paper_to_zotero.py --input sample_references.txt --collection "你的已有Collection完整路径"
```

不传 `--collection` 时，会读取现有 Collection 及其中部分文献标题，尝试自动匹配；仅在重合度足够高、第一名和第二名差距明显时选定。否则会要求用 `--collection` 显式指定，避免把论文放错文件夹。

这一步会请求文献检索接口、读取本地 Zotero，但**不下载 PDF、不修改 Zotero**；会写入本地 `report.json` 供检查。

## 5. 真正执行

确认预览中 DOI、标题和目标 Collection 正确后：

```powershell
py -3 paper_to_zotero.py --input sample_references.txt --collection "你的已有Collection完整路径" --apply
```

执行后：

- 不存在的文献创建为 Zotero 条目；已经存在的 DOI 复用原条目，并补充目标 Collection；
- 找到可公开获取且经身份验证的 PDF 时，下载并作为子附件上传；
- 无 PDF 时保留准确题录，并在 `report.json` 标记 `PDF_PENDING`；
- 不新建 Collection、不删除已有条目、不覆盖你已有的本地 PDF。

**特别说明：** `PDF_PENDING` 仅表示本轮合法开放来源未成功获取，可能仍有浙大图书馆授权全文。通过学校 WebVPN/CARSI 登录后，可在浏览器中下载，再手动拖入 Zotero 的现有条目。本 MVP 不自动跨站继承订阅登录。

## 6. 批量输入

将每篇完整参考文献放在**独立一行**的 UTF-8 文本文件中。例如 50 篇放在 `references.txt` 中，调用 `--input references.txt`。如只有 DOI，也可以一行一个 DOI。

```powershell
py -3 paper_to_zotero.py --input references.txt --collection "你的已有Collection完整路径" --apply --out downloads
```

输出 PDF 和下载报告在 `downloads/` 下。对复杂的跨行参考文献、DOCX/BibTeX/RIS 批量解析，建议后续接入现有 Paper Search MCP 的解析模块，本 MVP 尚未实现这些输入格式。

## 7. 当前版本的边界与后续迭代

1. **匹配安全性：** 无 DOI 时由 Crossref 检索，标题/作者/年份匹配不可靠或候选接近时返回 `MATCH_REVIEW`，不进行 Zotero 写入。
2. **自动分类：** 当前是基于已有 Collection 名称及少量馆藏标题的保守词汇匹配，不是 LLM 语义分类。中文分类与英文标题难以对应或分类没有样本时必须显式指定路径。
3. **PDF 验证：** 基于 PDF 格式、前三页提取文本中的 DOI/标题。扫描件、全文被加密或排版导致文本提取失败时跳过自动附加；可人工复核。
4. **订阅数据库：** Zotero Local API 只负责入库与附件；出版社站点的机构授权需要浏览器登录，是否能批量访问以机构许可为准。
5. **稳健性：** 具备单篇失败不影响后续条目的结构、API 超时和 PDF 容量上限；尚未具备任务队列数据库、完整指数退避重试或 PDF 来源长期刷新机制。
6. **验证范围：** 离线单元测试已覆盖核心规则，但真实 Zotero 写入/文件上传尚需你在本机授权并完成 1 篇端到端验收。

## 8. 官方文档

- [Crossref Metadata API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [OpenAlex API](https://help.openalex.org/api/)
- [Unpaywall API](https://unpaywall.org/api)
- [Zotero Local API](https://www.zotero.org/support/dev/web_api/v3/local_api)
- [Zotero Web API v3 写入](https://www.zotero.org/support/dev/web_api/v3/write_requests)
- [Zotero API 文件上传](https://www.zotero.org/support/dev/web_api/v3/file_upload)

## 可重复执行的浏览器下载脚本

`browser_pdf.mjs` 使用既有 Chrome CDP 与 zju-connect 回环代理，自动处理 ScienceDirect 的页面、View PDF 链接、PDF 页面和文件保存。出版社主站/PDF 走 VPN，公开脚本 CDN 直连；不导出 Cookie、不记录临时签名 URL、不覆盖已有文件，默认不限速。脚本不自动完成机构登录、短信验证或出版社验证挑战；这些情况返回非零退出码。

```bash
node browser_pdf.mjs --pii S0020025526007310 --out downloads/10.1016_j.ins.2026.123800.pdf
```

默认 CDP 为 `http://127.0.0.1:18806`，代理为 `http://127.0.0.1:1081`，可用 `--cdp` / `--proxy` 指定。Node 依赖 playwright-core；本机复用 literature-browser 的既有安装，其他电脑需 `npm install playwright-core`。脚本先输出格式/哈希结果，题名与 DOI 还须由 Python `verify_pdf` 核验。本机真实脚本运行已保存并核验目标论文，证据位于 `runs/script-browser-test/report.json`。这一路径需要 Chrome 进程，但下载步骤不需要人工点击；纯 urllib/requests PDF 请求仍可能是 403。
