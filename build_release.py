"""Build a source-only ZIP. Never include auth caches or Git history."""
from pathlib import Path
import argparse
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = '''.env.example .gitattributes .gitignore AGENTS.md LICENSE MANIFEST.in DESIGN.md README.md CHANGELOG.md CONTRIBUTING.md pyproject.toml requirements.txt requirements-dev.txt paper_tool.py paper_to_zotero.py batch_runner.py deliverables.py local_auth_cache.py browser_pdf.mjs paper-tool paper-tool.cmd generate-report.cmd progress.cmd _gen_launcher.py build_release.py'''.split()


def build_release(destination):
    destination = Path(destination)
    paths = [ROOT / name for name in FILES]
    for directory, suffixes in [('tests', {'.py'}), ('docs', {'.md'}), ('examples', {'.py', '.txt'}), ('paper_tool_assets', {'.py', '.mjs'})]:
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, 'paper-tool/' + path.relative_to(ROOT).as_posix())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(build_release(parser.parse_args().destination))
