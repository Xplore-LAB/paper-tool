# Contributing to CiteCargo

## Develop

```bash
python -m venv .venv
# Activate .venv, then:
python -m pip install -e ".[dev]"
python -m unittest discover -v
python -m build
python scripts/release.py dist/citecargo-source.zip
```

## Layout

- `src/paper_tool/`: CLI, retrieval, batch recovery, reports and authorization.
- `src/paper_tool/browser/`: optional Node browser backend.
- `scripts/`: launchers and source ZIP builder.
- `examples/`: public input/config templates.
- `docs/`: operational and architecture details.

## Rules

- Keep the `paper-tool` CLI compatible; `citecargo` is the new primary entry.
- Require explicit Zotero write authorization and an existing collection.
- Preserve user files and items; resume uploads on the original attachment.
- Tests use temporary files, loopback HTTP and fake Playwright. No real external services or personal libraries.
- No credentials, PDFs, browser profiles or personal batch records in Git.
- Windows `scripts/windows/export.cmd` is GBK/CRLF; edit its template in
  `scripts/windows/build_menu.py` and regenerate it.

CI is configured for Linux, Windows and macOS with Python 3.10 / 3.13.
