<div align="center">

# CiteCargo

### Your reference list. Your paper folder.

**Academic paper downloader · DOI to PDF · Optional Zotero import**

[Download](https://github.com/Xplore-LAB/paper-tool/releases/latest) · [简体中文](../README.md) · [Guide](usage.md)

</div>

Give CiteCargo a DOI or full citation. It resolves metadata, looks for full text, verifies the PDF and saves it locally. Add it to Zotero when you need to.

| Less searching | Less repeated work | Less filing |
|---|---|---|
| Resolve citations without a DOI | Resume batches and reuse verified PDFs | Match PDFs to records in an existing Zotero collection |

## Install

Python 3.10+. Download the wheel from [Releases](https://github.com/Xplore-LAB/paper-tool/releases/latest):

```bash
python -m pip install ./paper_tool-1.1.0-py3-none-any.whl
citecargo --version
```

## Three workflows

```bash
# Get one paper
citecargo fetch "10.1371/journal.pone.0000308" --out papers

# Work through a list; rerun the same command to resume
citecargo batch --input refs.txt --out library

# Reuse the batch and file it in Zotero
citecargo batch --input refs.txt --out library --zotero --collection "My Papers"
```

Put one DOI or full citation per line in `refs.txt`. Downloading needs no Zotero; archival requires Zotero 10+, its local API and write authorization. The existing `paper-tool` command remains supported.

## Files you can use

- Reuse local PDFs, then try open-access sources, then an optional institutional browser.
- Check PDF format, readability and first-page title identity. Keep checksums and per-paper results.
- Resume per paper: completed PDFs are reused; incomplete files are fetched again.
- Use existing institutional entitlement through the ScienceDirect browser route, a native VPN or an existing HTTP proxy such as zju-connect.

Institutional fallback currently covers ScienceDirect papers with a Crossref PII. The tool uses your existing access rights.

## Explore

[Usage](usage.md) · [Spreadsheet exports](reports.md) · [Contributing](../.github/CONTRIBUTING.md) · [Changelog](changelog.md) · [MIT](../LICENSE)

Local offline tests, installation and real OA retrieval have been verified. Cross-platform CI and live Zotero acceptance status are documented in the [release notes](https://github.com/Xplore-LAB/paper-tool/releases/latest).
