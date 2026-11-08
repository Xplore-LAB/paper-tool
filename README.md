# paper-tool

**DOI / 参考文献 → 已核验 PDF → 可选 Zotero 归档。**

[![CI](https://github.com/Xplore-LAB/paper-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Xplore-LAB/paper-tool/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/Xplore-LAB/paper-tool/releases/tag/v1.0.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A small CLI for resolving citations, downloading verified academic PDFs, and
optionally archiving them in an existing Zotero collection. Zotero is not
required for downloading papers.

## 安装

需要 Python 3.10+，运行时仅依赖 `pypdf`。从 GitHub Release 下载 wheel 后：

```bash
python -m pip install ./paper_tool-1.0.0-py3-none-any.whl
paper-tool --version
```

或从源码安装：

```bash
git clone https://github.com/Xplore-LAB/paper-tool.git
cd paper-tool
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install .
```

在源码目录也可用 `python paper_tool.py <command>`；没有发布到 PyPI，不要使用
`pip install paper-tool` 来假定安装的是本项目。

## 下载几篇文献：完全不依赖 Zotero

```bash
paper-tool fetch '10.1371/journal.pone.0000308' --out ./PDF
paper-tool fetch --input references.txt --out ./PDF --skip-done
```

输入可以是 DOI 或完整参考文献；文本清单每行一篇，支持 UTF-8、BOM 和 `#` 注释。
有歧义时补充作者、年份、期刊或 DOI，不会随意挑选一个结果。

获取顺序：**核验已有本地 PDF → 开放全文 → 可选机构浏览器回退**。默认只下载
正文，保留正文自带附录，不另外下载 Supporting Information。

## 批量续跑与扩充 Zotero

```bash
# 先只下载，不连接 Zotero
paper-tool batch --input references.txt --out my-batch

# 以后入库：复用同一批次目录及已核验文件
paper-tool collections --json
paper-tool batch --input references.txt --out my-batch --zotero --collection '已有分类完整路径'

# 只扩充题录：不查找、不上传 PDF
paper-tool batch --input references.txt --out my-batch --zotero --collection '已有分类完整路径' --metadata-only
```

Zotero 写入必须显式指定 `--zotero --collection`。目标分类必须已存在；不创建分类、
不删除条目、不覆盖已有题录。需 Zotero 10+ 开启本地 API，并在首次写入时授权。
默认地址为 `http://127.0.0.1:23119/api`。

当 Zotero 位于另一台电脑时，在那台电脑建立只绑定服务器回环的 SSH 反向转发：

```bash
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:23129:127.0.0.1:23119 user@server
paper-tool collections --zotero-base http://127.0.0.1:23129/api
```

上面的 `paper-tool` 在服务器运行；后续归档也传相同的 `--zotero-base`。不要把
未认证的本地 API 直接发布到校园网或公网。

## 机构订阅全文：可选集成

需要自己的有效机构访问权限、Node.js 22+、`playwright-core` 和带 CDP 的 Chrome/Edge：

```bash
npm install playwright-core
paper-tool browser --start
# 在这个浏览器完成必要的机构登录，再运行：
paper-tool fetch '你的 DOI' --out ./PDF
```

默认使用直连路由；原生 VPN 已连接时无需额外代理。使用已有 zju-connect HTTP
代理时可加 `--proxy http://127.0.0.1:1081`。工具不安装或登录 VPN，不保存学校密码。
浏览器自动下载目前只覆盖带 Crossref PII 的 ScienceDirect。其他出版商、无权限、
验证码或登录失效会保留待处理状态；`--oa-only` 可以完全关闭机构浏览器分支。

**验证边界**：1.0.0 的稳定范围是下述 CLI、状态与检查点契约。Zotero/机构浏览器
属于可选集成：有模拟协议、文件恢复和浏览器后端测试，仍需在实际桌面客户端及
机构环境验收；测试通过不证明任意论文具有订阅权限或所有出版社都可自动下载。

## 状态与恢复

| 状态 | 含义 |
|---|---|
| `PREVIEW` | 只读题录与候选来源预览 |
| `PDF_SAVED` | PDF 已在本地核验；归档结果另看 `zotero` 字段 |
| `PDF_ATTACHED` / `PDF_ALREADY_PRESENT` | 本轮附件上传或实时确认完成 |
| `METADATA_ONLY` | 本轮仅完成题录入库 |
| `PDF_PENDING` | 本轮没有取得可核验全文 |
| `NEEDS_REVIEW` | 题录、环境或处理失败，需要复核 |

```bash
paper-tool progress --out my-batch
paper-tool failures --out my-batch --write pending.txt
paper-tool failures --out my-batch --zotero --json
paper-tool audit --out my-batch --json
```

- 独立下载可跳过 SHA-256 未变化的已核验 PDF；无哈希的旧检查点重新核验身份。
- 归档每次复核本轮分类与实时附件，避免切换分类/数据库后沿用旧完成状态。
- 上传中断时向原附件记录补传，使用 MD5 前置条件防止覆盖并发修改。
- 远程 `file://` 路径不属于本机。只读审计无法直接读取时标为 `UNVERIFIED`，
  不据此误报丢失；安全条件不足时保留原附件并提示复核。
- 归档失败仍保留已核验 PDF，任务返回失败；最新失败不会被历史成功掩盖。
- 单篇串行处理，默认论文间隔 30 秒，不限制文件传输速度。

## 1.x 公共契约

稳定接口是 CLI，不是内部 Python 函数：

- 子命令：`fetch`、`batch`、`preview`、`collections`、`browser`、`doctor`、
  `progress`、`audit`、`failures`；归档必须显式启用。
- 退出码：`0` 表示所选任务完成；`2` 表示参数错误、待补或需复核。
- `fetch` 的 `report.json` 包含 `results` 列表；`batch` 的 `manifest.json` 是逐篇列表。
  结果包含 `status`，并按阶段提供 `paper`、`pdf`、`sha256`、`warnings`、
  `download_state`、`archive_state`。空值/缺字段表示该阶段未完成，不代表成功。
- 后续 1.x 可以增加字段和警告，但不移除或改变这些接口的含义。

PDF 文件不覆盖；历史检查点与运行数据不提交到仓库。不要同时用多个进程写同一
批次目录。扫描件、无法可靠提取文本或身份不确定的 PDF 需要人工复核。

## 配置

系统环境变量可选；`.env.example` 仅为模板，程序不自动加载 `.env`。

| 变量 | 用途 |
|---|---|
| `OPENALEX_API_KEY` / `UNPAYWALL_EMAIL` | 可选的开放全文检索配置 |
| `ZOTERO_LOCAL_API_KEY` | 可选本地 API 密钥，通常由桌面授权获取 |
| `PAPER_TOOL_OUT` | 默认输出目录，未设置时为当前目录 `downloads/` |
| `PAPER_TOOL_PROXY` | 机构浏览器代理，默认 `direct` |
| `PAPER_TOOL_ZOTERO_BASE` | Zotero 地址，默认本机回环 23119 |
| `PLAYWRIGHT_CORE_PATH` | 非标准位置的 `playwright-core` |

Windows 记住的 Zotero 授权通过 DPAPI 保存在当前用户的 LocalAppData 下，
不写入源码目录或发布包。程序不托管机构密码或导出浏览器 Cookie。

## 开发与发布

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
python -m build
python build_release.py dist/paper-tool-1.0.0-source.zip
```

离线测试使用临时目录、回环 HTTP 模拟服务器和 fake Playwright；不会访问真实
论文服务或 Zotero 库。CI 配置覆盖 Linux、Windows、macOS 与 Python 3.10/3.13，
并检查安装包；实际执行状态见工作流和对应 Release 的验证说明。可选的 `deliverables.py` 提供本地 Excel 台账与完成情况导出。

更多说明：[SOP](docs/SOP.md)、[架构](DESIGN.md)、[贡献指南](CONTRIBUTING.md)、
[变更记录](CHANGELOG.md)。MIT 许可证见 [LICENSE](LICENSE)。
