"""Build a source-only ZIP; omit runtime data, credentials and Git history."""
import argparse
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['.gitattributes', '.gitignore', 'AGENTS.md', 'LICENSE', 'MANIFEST.in',
         'README.md', 'pyproject.toml', '.github/CONTRIBUTING.md']
DIRECTORIES = {
    'src': {'.py', '.mjs', '.html', '.css', '.js'}, 'tests': {'.py'}, 'docs': {'.md', '.svg'},
    'scripts': {'.py', '.cmd', '.mjs'}, 'examples': {'.py', '.txt', '.example'},
    'skills': {'.md', '.yaml'},
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


def build_skill(destination):
    """An importable skill folder, without runtime or machine data."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('SKILL.md', 'agents/openai.yaml'):
            archive.write(ROOT / 'skills/citecargo' / name, 'citecargo/' + name)
        archive.write(ROOT / 'LICENSE', 'LICENSE')
    return destination


def build_windows(destination, wheel, dependencies):
    """Bundle pure-Python wheels for local installation; Python stays a prerequisite."""
    version = re.search(r'^version = "([^"]+)"', (ROOT / 'pyproject.toml').read_text(), re.M)[1]
    wheel = Path(wheel)
    dependencies = [Path(p) for p in dependencies]
    if (wheel.name != f'paper_tool-{version}-py3-none-any.whl'
            or not any(p.name.startswith('pypdf-') for p in dependencies)
            or not any(p.name.startswith('typing_extensions-') for p in dependencies)
            or any(not p.name.endswith('-py3-none-any.whl') for p in dependencies)):
        raise ValueError('Expected the current app wheel, pypdf and typing_extensions universal wheels')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / 'scripts/windows/start.cmd', 'CiteCargo/Start-CiteCargo.cmd')
        for file in (wheel, *dependencies):
            archive.write(file, 'CiteCargo/app/' + file.name)
        archive.write(ROOT / 'LICENSE', 'CiteCargo/LICENSE')
        archive.writestr('CiteCargo/开始使用.txt',
            'CiteCargo 文献直达\n\n1. 电脑需要 Python 3.10 或更高版本：https://www.python.org/downloads/\n'
            '2. 将整个压缩包解压到一个固定文件夹，双击 Start-CiteCargo.cmd。\n'
            '3. 浏览器打开后，粘贴 DOI 或完整参考文献，每行一篇，点击“开始下载”。\n'
            '4. 默认保存到当前用户的 Downloads/CiteCargo/PDF；页面可打开文件夹或打包取回。\n\n'
            '运行时保留启动窗口；结束时关闭窗口。程序重开后可重新粘贴清单，核验后复用已有文件。\n'
            '默认不连接 Zotero，也不需要 VPN。学校订阅下载需另外配置浏览器组件与已有访问权限。\n'
            '本包不是独立可执行安装包，不包含 Python。详细说明：https://github.com/Xplore-LAB/paper-tool\n')
        archive.writestr('CiteCargo/START-HERE.txt',
            'CiteCargo\n\n1. Install Python 3.10+ from https://www.python.org/downloads/\n'
            '2. Extract the entire ZIP to a fixed folder and double-click Start-CiteCargo.cmd.\n'
            '3. Switch to English in the browser, paste DOIs or full citations, then start downloading.\n'
            '4. PDFs are saved to Downloads/CiteCargo/PDF in your user folder by default.\n\n'
            'Keep the launcher window open while working. Close it to stop the application.\n'
            'Paste the list again after a restart; verified local files will be reused.\n'
            'Zotero and institutional access are optional. This package does not bundle Python.\n'
            'Guide: https://github.com/Xplore-LAB/paper-tool/blob/main/docs/README.en.md\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--kind', choices=('source', 'skill', 'windows'), default='source')
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--dependency', type=Path, action='append')
    args = parser.parse_args()
    if args.kind == 'windows':
        if not args.wheel or not args.dependency:
            parser.error('--kind windows requires --wheel and --dependency')
        print(build_windows(args.destination, args.wheel, args.dependency))
    else:
        print((build_skill if args.kind == 'skill' else build_release)(args.destination))
