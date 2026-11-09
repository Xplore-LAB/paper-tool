# 状态、恢复与工作流报告

`plan.json` 固定输入文件、摘要、目标目录、权限和策略。`manifest.json` 保持逐篇列表，`job.json` 保存任务设置、状态、预算与停止原因。`report.json` 是 schema_version=2.0 的机器报告，仍包含 results，便于已有导出器读取。

计划执行前重新读取原始输入并比较摘要；计划变更、输入变更或任务目录不匹配时拒绝执行。计划哈希用于完整性校验，不是对拥有本机修改权限者的身份认证。

`status --out <批次目录> --json` 是离线只读操作。报告区分 metadata_verified、pdf_verified、archive_completed 与 pending，并列出实际来源操作和限流事件；字段定义见 [agent-protocol.schema.json](agent-protocol.schema.json)。

处理顺序：读取 stop_reason 与 error_code → 检查 next_actions → 解决实际问题 → 在原授权范围内续跑同一计划。已核验文件会被复用。

- CHECKPOINT_WRITE_FAILED / LOCAL_IO_FAILURE：检查磁盘与目录权限；保留已完成文件和原检查点。
- USER_CANCELLED：等待用户恢复意图。
- PILOT_REVIEW：先诊断首批未完成项，再决定是否恢复。
- RUNTIME_BUDGET / DOWNLOAD_BUDGET：不要通过改参数、删状态或新建任务自动规避。
- ACCESS_DENIED：让用户检查来源权限，不反复自动请求被暂停来源。
- RATE_LIMITED：遵守 Retry-After 与任务剩余预算。
- AMBIGUOUS_MATCH：补查 DOI、作者或年份。
- PDF_INVALID / PDF_IDENTITY_MISMATCH：保留既有文件；错误论文不能归档。
- ZOTERO_WRITE_FAILED：检查本机连接与已授权分类，保留已下载 PDF。

如果用户明确修正了输入，旧计划将失效；经过范围核对后生成新计划。必要时用 `--pdf-dir` 指向原 PDF 主目录，避免创建第二套文献库。
