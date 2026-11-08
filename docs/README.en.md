<div align="center">

<img src="assets/citecargo.svg" alt="CiteCargo — Academic paper downloader, DOI to PDF" width="100%"/>

### Less hunting. More reading.

**DOI to PDF · Batch paper downloads · Optional Zotero import**

[Download](https://github.com/Xplore-LAB/paper-tool/releases/latest) · [简体中文](../README.md) · [Guide](usage.md) · [Feedback](https://github.com/Xplore-LAB/paper-tool/issues)

</div>

> **Give it:** a DOI, a full citation, or a reference list.<br>
> **Take away:** a folder of verified PDFs. File the records and attachments in Zotero when you need to.

## A real delivery

<img src="assets/result.svg" alt="Actual open-access result: a verified 5-page PDF saved locally" width="100%"/>

Result card generated from an actual completed download report. Example: [10.1371/journal.pone.0000308](https://doi.org/10.1371/journal.pone.0000308).

## Start collecting

Python 3.10+. Download the wheel from [Releases](https://github.com/Xplore-LAB/paper-tool/releases/latest):

```bash
python -m pip install ./paper_tool-1.1.0-py3-none-any.whl
```

```bash
# One paper: a DOI or full citation
citecargo fetch "10.1371/journal.pone.0000308" --out papers

# A reference list: one entry per line; rerun to resume
citecargo batch --input refs.txt --out library

# A library: reuse the batch in an existing Zotero collection
citecargo batch --input refs.txt --out library --zotero --collection "My Papers"
```

Downloading needs no Zotero. Archival requires Zotero 10+, its local API and write authorization. The existing `paper-tool` command remains supported.

## Work it takes off your hands

**Resolve references → Verify PDFs → Track progress → Archive on demand**

- **Less searching:** resolve citations to DOIs and open-access sources; connect your existing ScienceDirect entitlement through the optional browser route.
- **Less repeated work:** reuse verified local files, resume per paper and retry unfinished entries.
- **Less filing:** keep PDFs matched to records; add the same batch to Zotero later.

Institutional access requires your own entitlement. Browser fallback currently covers ScienceDirect papers with a Crossref PII.

[Usage](usage.md) · [Spreadsheet exports](reports.md) · [Contributing](../.github/CONTRIBUTING.md) · [Changelog](changelog.md) · [MIT](../LICENSE)

Local tests, installation and real OA retrieval have been verified. Cross-platform CI and live Zotero acceptance status are documented in the [release notes](https://github.com/Xplore-LAB/paper-tool/releases/latest).
