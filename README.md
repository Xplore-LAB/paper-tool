<div align="center">

<img src="docs/assets/citecargo.svg" alt="CiteCargo · 文献直达 — Academic paper downloader" width="100%"/>

### 把找论文的时间，还给研究。

**DOI to PDF · 批量收论文 · 按需归档 Zotero**

[![Release](https://img.shields.io/github/v/release/Xplore-LAB/paper-tool)](https://github.com/Xplore-LAB/paper-tool/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

[立即下载](https://github.com/Xplore-LAB/paper-tool/releases/latest) · [English](docs/README.en.md) · [使用手册](docs/usage.md) · [反馈](https://github.com/Xplore-LAB/paper-tool/issues)

</div>

> **交给它：** 一个 DOI、一条完整引用，或一份参考文献清单。<br>
> **带回来：** 核验过的论文 PDF 文件夹；需要时，连题录一起归进 Zotero。

## 一次真实交付

<img src="docs/assets/result.svg" alt="真实 OA 下载结果：PDF 已保存，首页题名核验通过，5 页，89.3 KiB" width="100%"/>

由已完成的真实 `report.json` 生成的结果卡。示例论文：[10.1371/journal.pone.0000308](https://doi.org/10.1371/journal.pone.0000308)。

## 开始收论文

Python 3.10+。从 [Release](https://github.com/Xplore-LAB/paper-tool/releases/latest) 下载 wheel 后安装：

```bash
python -m pip install ./paper_tool-1.1.0-py3-none-any.whl
```

```bash
# 一篇论文：贴 DOI 或完整引用
citecargo fetch "10.1371/journal.pone.0000308" --out papers

# 一份清单：每行一篇，中断后重跑同一命令
citecargo batch --input refs.txt --out library

# 一个文献库：复用这批 PDF，归入已有 Zotero 分类
citecargo batch --input refs.txt --out library --zotero --collection "My Papers"
```

下载不需要 Zotero。归档需 Zotero 10+ 开启本地 API 并授权；旧命令 `paper-tool` 继续可用。

## 它替你做的事

**引用找全文 → PDF 核验 → 记录进度 → 按需入库**

- **少找一遍**：完整引用先匹配 DOI，再查询开放全文；已有学校订阅可接 ScienceDirect 授权浏览器。
- **少下一遍**：已核验文件直接复用，任务按论文续跑，失败项单独补。
- **少整理一轮**：题录与 PDF 对应保存，同一批次以后也能继续归档 Zotero。

机构访问需要已有权限，自动浏览器回退目前覆盖带 Crossref PII 的 ScienceDirect 论文。

[机构访问与续跑](docs/usage.md) · [Excel 清单导出](docs/reports.md) · [开发](.github/CONTRIBUTING.md) · [更新记录](docs/changelog.md)

本地测试、安装与 OA 下载已验证；跨平台 CI 和真实 Zotero 验收状态见 [发布说明](https://github.com/Xplore-LAB/paper-tool/releases/latest)。
