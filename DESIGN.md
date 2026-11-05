# 参考文献 → PDF → Zotero 自动归档：实施方案与验收协议

## 1. 目标与设计约束

- **输入：** 一条或多条非标准参考文献字符串，未来支持 Word、BibTeX、RIS、CSV。
- **输出：** 经核实的标准题录、可合法获取的 PDF、Zotero 已有 Collection 中的条目/附件、逐篇结果报告。
- **不变量：** 一篇文献对应一个 Zotero 顶层条目；存在 DOI 时以 DOI 为主键；不创建 Collection、不删除现有文献、不覆盖现有 PDF；订阅数据库的登录和授权由本人完成。
- **失败策略：** 题录不可信则暂停该篇；没有 PDF 仍可保留题录；自动分类不可信则暂停 Zotero 写入，保留检索成果。

## 2. 数据与处理阶段

| 阶段 | 核心任务 | 输入/输出 | 失败状态 |
|---|---|---|---|
| P0 文本读取 | 清洗空白、识别 DOI | 原始字符串 | INPUT_INVALID |
| P1 题录匹配 | Crossref bibliographic query；含 DOI 时精确查找；作者/年份/标题复核 | DOI、期刊、作者、标题 | MATCH_REVIEW |
| P2 PDF 发现 | OpenAlex/Unpaywall 的 OA PDF 地址及版本信息 | URL + 来源 | PDF_PENDING |
| P3 下载核验 | HTTPS、体积、PDF 可读性、前三页 DOI/标题 | PDF + 来源证据 | PDF_PENDING，附原因 |
| P4 分类匹配 | 读取已有 Collection 完整路径和代表文献 | Collection Key | COLLECTION_REVIEW |
| P5 Zotero 归档 | DOI 去重；新建或复用条目；增量添加 Collection；上传 PDF 子附件 | Zotero Item Key | 写入异常保留详情 |
| P6 任务报告 | JSON 逐篇结构化记录 | report.json | 无 |

当前 MVP 实现 P1-P6 的核心路径；未实现的订阅机构/人工传递作为 PDF_PENDING 后续任务处理。

## 3. 稳定性策略

1. **检索多候选：** Crossref 前 5 条，使用题名覆盖度、第一作者和发表年份排序。低于 0.87、前两名差异过小则待核对。若输入本身有 DOI，但 DOI 解析出的标题与输入明显冲突，也拒绝自动归档。
2. **来源可追溯：** `pdf_candidates` 记录 URL、版本、许可及来源；`report.json` 保留最终 PDF 路径和获取失败原因。
3. **PDF 可验证：** 只有 PDF 可解析，且 DOI 或正文前几页标题词汇匹配时才关联；网页假 PDF 和无文本扫描件不自动关联。
4. **分类保守：** 优先用户显式指定已有完整路径；未指定则读取 Collection 名称与各 Collection 部分条目标题进行词汇重合度比较。需要分差与绝对阈值同时过线，否则弃权。
5. **增量与幂等：** DOI 已存在复用；不变更现有作者/标题字段；仅补充目标 Collection 和缺失 PDF。再次运行不会重复创建文献条目。
6. **凭据安全：** Zotero API 授权由桌面客户端弹窗确认；本程序不索取学校/出版社账号密码。OpenAlex API Key 和 Unpaywall Email 从环境变量读取，不写入报告。

## 4. 最小验收流程

| 测试 | 操作 | 预期 |
|---|---|---|
| T1 离线模块 | `python -m unittest -v test_paper_to_zotero.py` | 全部测试通过，无真实 API 写入 |
| T2 示例预览 | `python paper_to_zotero.py --demo --no-zotero` | 提取示例论文的 DOI/题录，状态 PREVIEW |
| T3 真实题录 | `--input sample_references.txt --collection "现有路径"` | Crossref 匹配，报告 DOI、Collection；不修改 Zotero |
| T4 Zotero 入库 | 在 T3 基础上加 `--apply` | 已授权后新增或复用条目，归入指定 Collection |
| T5 幂等复跑 | 相同命令第二次运行 | 条目数量不增加；已有 PDF 不重复下载/附加 |
| T6 无 PDF | 使用不能公开获取的文献 | Zotero 有题录，PDF_PENDING，不阻塞后续引用 |
| T7 模糊分类 | 无 `--collection` 且候选分数过低 | 给出候选，停止不确定的归档，不创建 Collection |

**当前验证等级：** T1、T2 已在隔离环境运行；T3-T7 中涉及实际 Zotero 的步骤必须在用户电脑上执行，不能把模拟 API 测试当成真实归档成功。

## 5. 下一阶段增强（建议顺序）

| 优先级 | 增量功能 | 为什么需要 |
|---|---|---|
| 高 | `docx/bib/ris/csv` 批量解析和跨行记录拆分 | 适配真实论文文献列表 |
| 高 | 下载队列、429 重试、逐篇 checkpoint | 适应 50–500 篇长任务和限流 |
| 高 | Zotero 现有附件 PDF 反向校验与重复附件识别 | 防止历史错误附件污染 |
| 中 | Collection 语义分类：利用各分类历史文献构建 embedding 原型，Top-3 候选+置信度 | 中文目录/英文论文的跨语言匹配 |
| 中 | 浏览器协同：在用户已有学校登录状态下，引导合法下载订阅 PDF，再自动监听导入 | 提高付费文献补全率，遵守许可 |
| 中 | PDF 元数据结构化、版本差异和文件哈希索引 | 支持高质量科研资料库 |
| 低 | 公开仓储新版本定期补查 | 后续论文转为开放获取时自动补全 |

## 6. 对几十篇文献的建议评价指标

- 题录匹配准确率：核查的 DOI/题名与人工标准答案一致的比例。
- 题录自动处理率：无需人工确认即可确定 DOI 的比例。
- PDF 获取率：获得并通过身份验证的 PDF / 全部输入条目；区分 OA 获取和机构获取。
- 错误附件率：错误文献 PDF 被关联的比例，目标是零。
- Zotero 正确归档率：落在期望 Collection 且无重复的比例。
- 人工介入量：每 50 篇需确认的匹配或 Collection 数量，以及人工补全 PDF 数量。

建议先用 10 篇混合论文（OA 4、订阅 4、无 DOI 1、易混淆 1）验证流程，再评估 50 篇批量表现。
