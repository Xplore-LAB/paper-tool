# Changelog

All notable changes to this project are documented here.

## 2.0.0 — Offline Agent workflow

- Added bound offline plans, optional metadata preflight, pilot execution and unified JSON status.
- Added task-scoped source scheduling, retry/transfer/runtime budgets, source suspension and structured errors.
- Retained manifest rows and added atomic job metadata plus exclusive writer locks.
- Added a wheel-only offline Skill with hash checks, isolated cache runtimes and interrupted-install recovery.
- Added one-payload validation receipts and optional complete-matrix validation.
- Kept the existing UI, browser backend and Zotero protocol; browser internals remain outside per-request Python metering.
- Runtime acceptance is recorded per actual platform; untested combinations remain explicitly unverified.

## 1.2.0 — A simpler way in

- Added a bilingual local browser interface for references, progress, PDF retrieval and optional Zotero archival.
- Added the CiteCargo AI skill, sharing the existing CLI and retrieval engine.
- Added a Windows launcher bundle with offline Python dependencies; Python 3.10+ remains required.
- Kept retry checkpoints and completed files; enabled institutional access when retrying an OA-only task.
- Separated Chinese and English landing-page copy and illustrations.
- Added loopback HTTP tests for independent downloads, ZIP delivery, access boundaries and recovery.

## 1.1.0 — CiteCargo

- Introduced CiteCargo (文献直达) and the `citecargo` command; retained `paper-tool`.
- Consolidated implementation into `src/paper_tool/` with explicit module roles.
- Moved launchers/build tools to `scripts/`, guides to `docs/`, templates to `examples/`.
- Reduced the repository root to standard project files and shortened both landing pages.
- Consolidated dependency declarations in `pyproject.toml`.

## 1.0.0

First public release. The stable interface is the documented CLI, exit codes and
checkpoint/status contract. Institutional browser access and Zotero integration
remain optional and require acceptance in the user's own environment.

- Promoted the repaired pipeline into the main source tree and default launcher.
- Added `paper-tool --version`, MIT license in distribution archives, source and
  wheel installation instructions, and reproducible release builds.
- Made direct networking and local Zotero the generic defaults; deployments can
  configure output, proxy and forwarded API endpoints through environment variables.
- Moved encrypted Windows authorization caches into user-local application data.
- Added Linux / Windows / macOS CI and removed deployment-specific public docs.
- Retained independent PDF retrieval, verified resume and optional archival fixes
  from 0.3.2; no bundled credentials, papers or machine authorization state.

## 0.3.2

- Unified local-PDF → open-access → institutional-browser retrieval order.
- Independent downloads resume by verified SHA-256, without any Zotero connection.
- Preserve full bibliographic records and separate download / archive checkpoints.
- Recheck the current collection and live attachments on every archival run.
- Route metadata-only imports before PDF recovery; never upload PDF attachments.
- Resume interrupted uploads on the same attachment with MD5 preconditions.
- Distinguish remote file URLs from missing files; never overwrite unverified attachments.
- Show latest failures instead of masking them with historical success.
- Keep dry runs fully offline; reject malformed checkpoints before writing.
- Browser retries use unique partial files and refuse racing output replacement.
- 161 offline tests, including real Node file-saving and loopback HTTP upload recovery.

## 0.3.1

- Packaged the browser backend and removed machine state from release ZIPs.
- Fixed cached-Zotero metadata fallback and clarified environment configuration.

## 0.3.0

- Added `--metadata-only`: import bibliographic records without any download.
  Known DOIs reuse Zotero metadata; a 65-row batch completes in ~3 s with no
  external requests.
- Cached the Zotero item / collection snapshots per run instead of reloading
  the whole library for every row (about 190 s saved on a 65-row batch).
- `paper_from_crossref()` now keeps Crossref `type` and `event`; conference
  papers are created as `conferencePaper` with `conferenceName`,
  `proceedingsTitle` and `eventPlace` instead of `journalArticle`.
- Excel ledger grew to 18 columns with a translated Chinese title column.
  Added `deliverables.py translate-todo` and a non-overwriting translation map.
- Launcher scripts now fall back to a system interpreter, so a fresh clone
  works before a virtualenv is created.
- 131 offline tests.

## 0.2.0

- `batch` subcommand with resumable checkpoints, `--dry-run`, `--oa-only`,
  local-PDF recovery and per-row status / warnings.
- Read-only `progress`, `audit`, `failures`, `collections` and `preview`.
- Deliverables: 17-column Excel ledger (OOXML, standard library only) and a
  completion report.
- Windows launcher with GBK-safe encoding.

## 0.1.0

- Single-reference pipeline: Crossref matching, OA candidate discovery,
  first-page PDF identity verification, Zotero item reuse and attachment upload.
- Optional institutional ScienceDirect retrieval through an existing Chrome
  session via CDP.
