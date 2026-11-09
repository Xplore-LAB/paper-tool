# Contributing to CiteCargo

## Develop

```bash
python -m venv .venv
# Activate .venv, then:
python -m pip install -e ".[dev]"
python -m unittest discover -v
python -m build
python scripts/release.py dist/citecargo-source.zip
python -m pip download --no-deps --only-binary=:all: pypdf==6.21.4 typing_extensions==4.16.0 --dest dist/dependencies
python scripts/release.py dist/citecargo-skill.zip --kind skill --wheel dist/paper_tool-2.0.0rc1-py3-none-any.whl --dependency dist/dependencies/pypdf-6.21.4-py3-none-any.whl --dependency dist/dependencies/typing_extensions-4.16.0-py3-none-any.whl --receipt-out dist/local-validation.json
python scripts/release.py dist/citecargo-windows.zip --kind windows --wheel dist/paper_tool-2.0.0rc1-py3-none-any.whl --dependency path/to/pypdf-wheel.whl --dependency path/to/typing_extensions-wheel.whl
```

## Layout

- `src/paper_tool/`: CLI, retrieval, batch recovery, reports and authorization.
- `src/paper_tool/browser/`: optional Node browser backend.
- `src/paper_tool/web/`: local UI assets; no frontend build dependency.
- `skills/citecargo/`: AI skill over the same engine.
- `scripts/`: launchers and source ZIP builder.
- `examples/`: public input/config templates.
- `docs/`: operational and architecture details.

## Rules

- Keep the `paper-tool` CLI compatible; `citecargo` is the new primary entry.
- Keep browser UI requests on loopback and preserve the origin/token protections.
- Require explicit Zotero write authorization and an existing collection.
- Preserve user files and items; resume uploads on the original attachment.
- Tests use temporary files, loopback HTTP and fake Playwright. No real external services or personal libraries.
- No credentials, PDFs, browser profiles or personal batch records in Git.
- Windows `scripts/windows/export.cmd` is GBK/CRLF; edit its template in
  `scripts/windows/build_menu.py` and regenerate it.

CI is configured for Linux, Windows and macOS with Python 3.10 / 3.13.

A candidate Skill contains only one engine wheel plus reviewed dependencies. Do not publish it as cross-platform validated until `--require-matrix` accepts all six runtime receipts for the same payload. CI builds the application wheel once and shares it across the matrix so receipts are comparable.
