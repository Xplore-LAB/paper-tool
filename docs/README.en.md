<div align="center">

# paper-tool

### Academic Paper Downloader · DOI to PDF · Optional Zotero Import

**Turn a DOI or citation into a verified PDF. Archive it in Zotero when you need to.**

[![Release](https://img.shields.io/github/v/release/Xplore-LAB/paper-tool?display_name=tag)](https://github.com/Xplore-LAB/paper-tool/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://github.com/Xplore-LAB/paper-tool)
[![License: MIT](https://img.shields.io/badge/License-MIT-16A34A)](../LICENSE)

[简体中文](../README.md) · [Quick start](#quick-start) · [Downloads](https://github.com/Xplore-LAB/paper-tool/releases/latest) · [Report an issue](https://github.com/Xplore-LAB/paper-tool/issues)

</div>

**paper-tool is a Python CLI academic paper downloader** for DOI-to-PDF retrieval, full-citation resolution, open-access PDF discovery, resumable batch downloads and optional Zotero import. Downloading papers does not require Zotero.

## Choose your workflow

| Need | Command | Zotero required? |
|---|---|---|
| Download one paper by DOI or citation | `fetch` | No |
| Batch-download a reference list and resume later | `batch` | No |
| Add papers to an existing Zotero collection | `batch --zotero --collection` | Yes |
| Import references without downloading PDFs | `batch --zotero --collection --metadata-only` | Yes |

## What makes it useful

- **Start with a DOI or full citation.** Crossref resolves identifiers and metadata; uncertain matches remain review tasks.
- **Verify the paper, not just the extension.** Check PDF format, readability and first-page title identity. Relevant verification paths also use DOI and author evidence.
- **Resume work you already did.** Checkpoints, SHA-256 hashes, local PDF reuse and retry lists support interrupted batches.
- **Download now, archive later.** Reuse the same batch folder to add records and verified PDFs to Zotero. Archival failure retains your local PDF.
- **Combine open access with authorized institutional access.** OpenAlex / Unpaywall discovery comes before an optional ScienceDirect browser fallback.
- **Use it in scripts and research-agent workflows.** Per-paper JSON and explicit exit codes make results inspectable. Runtime dependencies are Python and `pypdf`; no background service is needed.

The retrieval order is **verified local file → open-access source → authorized institutional browser**. Only the main article is requested; appendices inside the PDF are retained.

## Quick start

Requires **Python 3.10+**. Download the wheel from [GitHub Releases](https://github.com/Xplore-LAB/paper-tool/releases/latest):

```bash
python -m pip install ./paper_tool-1.0.0-py3-none-any.whl
paper-tool --version
paper-tool fetch "10.1371/journal.pone.0000308" --oa-only --out ./PDF
```

Or install from source:

```bash
git clone https://github.com/Xplore-LAB/paper-tool.git
cd paper-tool
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install .
```

You can also run `python paper_tool.py <command>` from the source checkout. This project is distributed through GitHub; it is not currently published to PyPI.

## Batch PDF downloads and resume

Create `references.txt` with one DOI or complete reference per line. UTF-8, blank lines and `#` comments are supported.

```bash
paper-tool batch --input references.txt --out my-batch --oa-only

# Run the same command after interruption
paper-tool batch --input references.txt --out my-batch --oa-only

paper-tool progress --out my-batch
paper-tool failures --out my-batch --write pending.txt
```

Files go to `my-batch/PDF/`; `manifest.json` stores per-paper metadata and status. Independent downloads can skip previously verified files whose hashes have not changed. Legacy checkpoints without hashes require identity verification again.

Resume is per paper: incomplete files are fetched again. Processing is serial, with a default 30-second interval between papers and no transfer-rate limit. Use a single writer for each batch folder.

## Optional Zotero import and PDF attachment

Requires **Zotero 10+**, its local API enabled, and desktop authorization on the first write.

```bash
paper-tool collections --json
paper-tool batch --input references.txt --out my-batch --zotero --collection "Existing collection path"

# Metadata only: no PDF search or attachment upload
paper-tool batch --input references.txt --out my-batch --zotero --collection "Existing collection path" --metadata-only

paper-tool audit --out my-batch --json
paper-tool failures --out my-batch --zotero --json
```

Zotero writes require explicit `--zotero --collection`. Items are reused by DOI and added to the specified existing collection; the tool does not create collections, delete items or overwrite existing bibliographic fields.

The default API is `http://127.0.0.1:23119/api`. To reach Zotero on another computer, use a loopback SSH tunnel and `--zotero-base`; see [advanced configuration](../README.md#进阶配置与接口).

Archival runs check the current collection and live attachment state. Interrupted uploads resume on the original attachment record with MD5 preconditions. An unverifiable remote attachment is retained for review, not silently overwritten.

## Institutional access: ScienceDirect, campus VPN and zju-connect

The optional browser route needs your own valid institutional entitlement, Node.js 22+, `playwright-core`, and Chrome/Edge with CDP enabled:

```bash
npm install playwright-core
paper-tool browser --start
# Complete the institution login in this browser, then:
paper-tool fetch "YOUR_DOI" --out ./PDF

# If an existing zju-connect HTTP proxy is in use:
paper-tool fetch "YOUR_DOI" --out ./PDF --proxy http://127.0.0.1:1081
```

A connected native VPN can use the default direct route. The automated institutional fallback currently covers **ScienceDirect / Elsevier papers with a PII supplied by Crossref**. Other publishers, expired authorization and verification challenges remain pending tasks. `--oa-only` disables this fallback entirely.

The tool uses open-access sources or your existing access rights; it does not bypass access controls or manage university passwords.

## Results you can inspect

| Status | Meaning |
|---|---|
| `PDF_SAVED` | A local PDF was verified; inspect `zotero` separately for archival outcome |
| `PDF_ATTACHED` / `PDF_ALREADY_PRESENT` | Upload or live attachment confirmation completed in this run |
| `METADATA_ONLY` | This run imported bibliographic records only |
| `PDF_PENDING` | No verified full text was obtained in this run |
| `NEEDS_REVIEW` | Metadata, file or environment needs review |

`fetch` writes `report.json`; `batch` writes `manifest.json`. Download and archive state are separate. Latest failures are not masked by historical successes. Optional [deliverables](deliverables.md) include a local Excel bibliography ledger and completion report.

## Configuration and compatibility

Optional environment variables include `OPENALEX_API_KEY`, `UNPAYWALL_EMAIL`, `ZOTERO_LOCAL_API_KEY`, `PAPER_TOOL_OUT`, `PAPER_TOOL_PROXY`, `PAPER_TOOL_ZOTERO_BASE` and `PLAYWRIGHT_CORE_PATH`. `.env.example` is a template, not an automatically loaded configuration file.

The stable 1.x interface is the documented CLI, exit codes (`0` completed; `2` pending/error/review) and checkpoint/status contract. Internal Python functions are not a public API. Full configuration and contract details are in the [main README](../README.md#进阶配置与接口).

Plain-text DOI/citation lists are supported; direct Word, RIS and BibTeX file parsing is not implemented. Scanned or uncertain PDFs need manual review. Do not expose the unauthenticated local Zotero API outside loopback.

## Validation and contributing

[![CI](https://github.com/Xplore-LAB/paper-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Xplore-LAB/paper-tool/actions/workflows/ci.yml)

The v1.0.0 release passed **163 local offline tests**, clean installation, real OA retrieval and resume checks. Linux / Windows / macOS CI is configured, but did not execute at release because of an account restriction. Cross-platform results and live desktop Zotero acceptance are not verified. See the [release validation notes](https://github.com/Xplore-LAB/paper-tool/releases/tag/v1.0.0).

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
python -m build
```

Bug reports and contributions are welcome. Include the command, OS and Python version; remove API keys, cookies, personal-library information and temporary signed URLs. See [CONTRIBUTING.md](../CONTRIBUTING.md).

**Documentation:** [简体中文](../README.md) · [Architecture](../DESIGN.md) · [Operational guide](SOP.md) · [Changelog](../CHANGELOG.md) · [MIT License](../LICENSE)
