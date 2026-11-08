"""Build a source-only ZIP; omit runtime data, credentials and Git history."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['.gitattributes', '.gitignore', 'AGENTS.md', 'LICENSE', 'MANIFEST.in',
         'README.md', 'pyproject.toml', '.github/CONTRIBUTING.md']
DIRECTORIES = {
    'src': {'.py', '.mjs'}, 'tests': {'.py'}, 'docs': {'.md', '.svg'},
    'scripts': {'.py', '.cmd', '.mjs'}, 'examples': {'.py', '.txt', '.example'},
}


def build_release(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / name for name in FILES]
    for directory, suffixes in DIRECTORIES.items():
        paths.extend(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and not path.is_symlink()
                     and path.suffix in suffixes and '__pycache__' not in path.parts)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, 'paper-tool/' + path.relative_to(ROOT).as_posix())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(build_release(parser.parse_args().destination))
