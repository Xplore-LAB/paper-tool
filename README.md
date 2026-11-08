<div align="center">

# CiteCargo · 文献直达

### 把参考文献清单，变成论文文件夹。

**论文 PDF 下载 · DOI to PDF · 按需归档 Zotero**

[![Release](https://img.shields.io/github/v/release/Xplore-LAB/paper-tool)](https://github.com/Xplore-LAB/paper-tool/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

[下载安装](https://github.com/Xplore-LAB/paper-tool/releases/latest) · [English](docs/README.en.md) · [使用手册](docs/usage.md)

</div>

贴入 DOI 或完整引用，自动匹配题录、寻找全文、核验 PDF。下载好的论文留在本地，需要时再送进 Zotero。

| 少花时间找 | 中断也不白跑 | 下载后少整理 |
|---|---|---|
| 引用没有 DOI？先匹配，再找全文 | 已核验 PDF 直接复用，失败项单独补 | 同一批次随时入库，题录与 PDF 对应归档 |

## 装好就能用

需要 Python 3.10+。从 [Release](https://github.com/Xplore-LAB/paper-tool/releases/latest) 下载 wheel：

```bash
python -m pip install ./paper_tool-1.1.0-py3-none-any.whl
citecargo --version
```

## 三种用法

**拿到一篇论文** — 输入 DOI 或完整参考文献：

```bash
citecargo fetch "10.1371/journal.pone.0000308" --out papers
```

**找齐一份清单** — `refs.txt` 每行一篇，中断后用同一条命令续跑：

```bash
citecargo batch --input refs.txt --out library
```

**送进 Zotero** — 复用刚才的 `library`，加入已有分类：

```bash
citecargo batch --input refs.txt --out library --zotero --collection "My Papers"
```

前两种用法无需 Zotero；第三种需要 Zotero 10+ 开启本地 API 并授权。原 `paper-tool` 命令继续可用。

## 从“找到链接”到“文件可用”

- **优先复用，再找全文**：本地已核验文件 → 开放获取来源 → 可选机构浏览器。
- **拿回的是哪篇，先核对**：检查格式、可读性和首页题名；用哈希确认文件没有变化。
- **进度看得见**：成功、待补、需复核分别记录；归档失败仍保留本地 PDF。
- **已有学校订阅也能接上**：支持 ScienceDirect 授权浏览器路径，可搭配原生 VPN 或 zju-connect 代理。

机构访问需要你已有的权限；浏览器自动回退目前覆盖带 Crossref PII 的 ScienceDirect 论文。

## 继续上手

[批量续跑与机构访问](docs/usage.md) · [Excel 清单导出](docs/reports.md) · [开发与贡献](.github/CONTRIBUTING.md) · [更新记录](docs/changelog.md)

```text
src/       程序
scripts/   启动与打包
examples/  输入与配置示例
docs/      手册
tests/     测试
```

本地离线测试、安装与 OA 下载已验证。跨平台 CI 和真实 Zotero 验收状态见 [发布说明](https://github.com/Xplore-LAB/paper-tool/releases/latest)。
