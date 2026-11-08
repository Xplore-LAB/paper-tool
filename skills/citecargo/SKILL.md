---
name: citecargo
description: "Get academic paper PDFs from DOIs or full citations with CiteCargo, optionally filing them in an existing Zotero collection. Use for requests to 下载论文、补全文 or 批量归档; not for general research discussion or paper summaries."
---

# CiteCargo

Handle installation and command execution for the user. Reply in the user's language; they should not need to learn CLI flags.

## Get ready

Reuse an installed `citecargo` or compatible `paper-tool`; check `--version`.
If unavailable, find Python 3.10+ and install the project in an appropriate isolated environment:

```bash
python -m pip install "https://github.com/Xplore-LAB/paper-tool/releases/download/v1.2.0/paper_tool-1.2.0-py3-none-any.whl"
```

Respect an existing project environment and output folder. If Python is unavailable, explain the missing prerequisite rather than claiming the tool ran. This skill requires an assistant that can execute local commands; a chat-only client cannot run it by importing the text alone.

## Get the papers

- Prefer supplied DOIs. Without a DOI, use the full citation; ambiguous titles need author/year/journal evidence. Do not silently select another paper.
- Download only the main article, including its built-in appendices. Add separate supporting information only when requested.
- For one paper use `citecargo fetch '<DOI or full citation>' --out <folder>`.
- For a list write one reference per line to a UTF-8 input file and use `citecargo batch --input <file> --out <batch-folder>`. Reuse that batch folder to resume.
- Default to PDF retrieval without Zotero. When the user requests archival, reuse the authorized existing collection; list `citecargo collections --json` if needed. Add `--zotero --collection '<existing path>'`; ask only if the destination is missing or ambiguous.
- If the user requests records only, add `--metadata-only` to the archival batch.

## Handle access and outcomes

OA retrieval runs independently. Institutional fallback needs the user's existing entitlement and a logged-in CDP browser. Use `citecargo browser --start` and the configured route when necessary. Ask the user to complete login or verification; do not collect passwords or export cookies. Stop repeated authorization attempts after rejection.

Read the real checkpoint and exit code. `PDF_SAVED` means local retrieval; `PDF_ATTACHED` / `PDF_ALREADY_PRESENT` mean archival confirmation. `PDF_PENDING`, `NEEDS_REVIEW`, `WRITE_PENDING` and `COLLECTION_REVIEW` are unfinished work. Keep verified files if Zotero fails.

Deliver clickable paths to actual PDFs, the completed/pending counts and a short explanation of any next step. Do not dump raw errors, credentials or signed URLs into the response. Do not claim a title record, listening VPN port or mock test is a real downloaded PDF or completed Zotero upload.
