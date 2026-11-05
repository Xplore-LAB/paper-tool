# 论文快速获取工具：后续会话入口

本机源码 `/home/lab434/src/projects/paper-to-zotero`，命令 `/home/lab434/.local/bin/paper-tool`，私有仓库 `https://github.com/Xplore-LAB/paper-tool`。先读取 README 的当前入口，复用已有工程和 `.venv`，不要重新搭建下载器。

## 何时调用

- 用户明确要求某篇/一组论文，或研究推进确需核对原文时，直接检索和下载，不止返回网站链接。普通概念问答不自动触发下载。
- 优先用 DOI；没有 DOI 时输入完整参考文献。纯题名或候选相近而无法可靠匹配时，补查作者、年份、期刊再继续，不能为下载成功随意选 DOI。
- 单纯下载属于工具工作，无需套完整科研汇报模板。

## 最短工作路径

```bash
paper-tool doctor
paper-tool preview 'DOI或完整参考文献'
paper-tool fetch 'DOI或完整参考文献' --out /home/lab434/data/papers/实际课题
paper-tool fetch --input /已有路径/references.txt --out /home/lab434/data/papers/实际课题
```

若命令不在 PATH，使用 `/home/lab434/.local/bin/paper-tool`。每行一篇的 UTF-8 列表使用 `--input`。没有明确课题目录时，默认 `/home/lab434/data/papers/reference-to-zotero`；已有 PDF 优先复用，不复制第二套主库。先遵循目标研究项目的文件存放及文献集合规则。

## 获取顺序与实际条件

1. 核对 Crossref 题录，再尝试开放 PDF。已有文件须重新核验题名，不仅判断文件存在。
2. 非 OA 的 Elsevier/ScienceDirect 文献，工具可根据题录中的 PII 调用 `browser_pdf.mjs`：RVPN 主站授权 → 浏览器 View PDF → PDF 页面读取 → 本地核验。其他出版商的机构自动下载尚未覆盖，按其官方来源或合适的下载技能处理。
3. 机构分支要求 zju-connect 和既有 Chrome 正在运行。默认 HTTP 代理 `127.0.0.1:1081`、Chrome CDP `127.0.0.1:18806`；`doctor` 仅检查监听端口，不证明 VPN 已认证或具有订阅权限。
4. VPN 未就绪时，客户端位于 `/home/lab434/src/third_party/zju-connect/zju-connect`，本机私有配置位于 `/home/lab434/apps/zju-connect-test/config.toml`。仅在实际需要机构访问时复用配置；不得打印、提交、复制凭据或会话文件到研究记录。短信/机构登录等缺少信息时请用户补充，错误凭据被拒后停止盲目重试。
5. ScienceDirect 正文主站/PDF 使用 VPN；公开静态脚本 CDN 需按现有浏览器后端直连。静态 CDN 被 VPN ACL 拒绝会导致 PDF 按钮未启用。普通 HTTP 请求返回 403 不足以断言学校无订阅，应使用已验证的浏览器路径。不得导出 Cookie 或在报告里保存临时签名 URL。
6. 默认只下载正文，保留 PDF 自带附录；不另外下载 SI，用户明确要求才增加。单篇串行处理，当前不限制传输速度，默认论文间隔 30 秒；尊重用户本轮的新要求，不把单篇成功扩大成不限量抓取。

## 核验、状态与交付

- 核对 `%PDF`、可读性、首页题名、DOI及题录。只因某 DOI 出现在参考文献中，不能认定文件正确；不确定的 PDF 保留待复核，不自动附加到 Zotero。
- 每篇结果写到所选输出目录已有的 `report.json`。查看实际状态与退出码，区分 `PDF_SAVED` / `PDF_ATTACHED`、`PDF_PENDING`、`NEEDS_REVIEW` 及 Zotero 写入待处理；失败不得称为已下载。
- 成功后在对话中给可点击本地 PDF 路径，必要时给题名、DOI和缺失项。无需每次另建总结、下载台账或重复报告。
- 2026-11-05 已实测 DOI `10.1016/j.ins.2026.123800` 经 RVPN＋浏览器取得正文，且验证了独立脚本下载。该历史验证只支持这条路径，不能保证当前会话仍在线或所有数据库可用。

## Zotero 与代码维护

- 默认下载不写 Zotero。只有用户或当前研究项目已授权归档时才加 `--zotero`，并按项目指定已有 Collection；不把其他课题的分类或授权混用。
- 用户的 Zotero 在另一台电脑；通过 SSH 反向转发接入，默认回环 API `http://127.0.0.1:23129/api`。连接步骤见 README，禁止把未认证的本地 API 发布到校园网/公网。真实 Zotero 归档尚待连接验收；模拟测试通过不等于真实入库。
- 功能修改后按影响范围运行 `.venv/bin/python -m unittest -v`。文档改动做命令和路径核对即可，不为说明性更新重复下载论文。
- Git 只提交代码、测试与文档；PDF、`runs/`、`release/`、`.venv/`、VPN 配置、登录状态与密钥不提交。保留既有失败证据，维护 `.gitignore`。
