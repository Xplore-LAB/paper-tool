# paper-tool: contributor and research-agent entry point

Read README.md and docs/SOP.md before changing or using the pipeline. This is a
CLI for DOI/reference resolution, verified PDF retrieval and optional Zotero
archiving. Do not create a second downloader or a background service.

## Downloading papers

- Prefer a DOI; otherwise use a full citation. Never silently choose a different
  paper to make a download succeed. Plain conceptual questions do not trigger downloads.
- Use `paper-tool fetch '<DOI>' --out <paper-directory>` for a few papers or
  `paper-tool batch --input references.txt --out <batch-directory>` for a list.
- Default to the main article, retaining appendices inside its PDF. Download
  separate supporting information only when explicitly requested.
- Reuse verified files, then try OA, then the supported authorized institutional
  browser route. Do not bypass login, verification challenges or access controls.
- Zotero is optional. Write only when authorized, using `--zotero --collection`
  and an existing collection. A download succeeding does not prove archival succeeded.
- Check output statuses and exit codes. Return actual local PDF paths and missing
  steps; do not equate a mock test, a listening proxy or a metadata record with
  real full-text access or a completed Zotero upload.

## Maintaining the program

- Follow the public CLI/status contract in README.md. Keep downloaded artifacts,
  credentials, profiles, personal collections and local machine notes out of Git.
- Never print API keys, VPN credentials, cookies or temporary signed PDF URLs.
- Preserve existing PDF files and Zotero items. Interrupted uploads should reuse
  their original attachment records with the upload protocol's preconditions.
- Run `python -m unittest discover -v` after functional changes. Tests may use
  loopback HTTP and fake Playwright, but never real external services or libraries.
- Build wheels/source archives with `python -m build`; use `build_release.py` for
  the allowlisted downloadable ZIP, including LICENSE and tests.
- If `.local/AGENTS.md` exists, read it for this machine's connection details.
  That file is private and ignored; never copy it into a public artifact.
