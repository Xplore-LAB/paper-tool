"""Build a source-only ZIP; omit runtime data, credentials and Git history."""
import argparse
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['.gitattributes', '.gitignore', 'AGENTS.md', 'LICENSE', 'MANIFEST.in',
         'README.md', 'pyproject.toml', '.github/CONTRIBUTING.md', '.github/workflows/ci.yml']
DIRECTORIES = {
    'src': {'.py', '.mjs', '.html', '.css', '.js'}, 'tests': {'.py'}, 'docs': {'.md', '.svg'},
    'scripts': {'.py', '.cmd', '.mjs'}, 'examples': {'.py', '.txt', '.example'},
    'skills': {'.md', '.yaml', '.py', '.json'},
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


def _version():
    return re.search(r'^version = "([^"]+)"',(ROOT/'pyproject.toml').read_text(),re.M)[1]


def inspect_wheel(path,*,expected_sha256=None):
    """Validate wheel RECORD, identity and universal tags before any installation."""
    import base64,csv,hashlib,io,stat
    from email.parser import BytesParser
    path=Path(path)
    if path.is_symlink() or not path.name.endswith('-py3-none-any.whl'):
        raise ValueError('Only regular universal Python wheels are supported in V2')
    raw=path.read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha!=expected_sha256: raise ValueError('Wheel SHA-256 does not match its lock')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist()
        names=[entry.filename for entry in entries if not entry.is_dir()]
        if len(names)!=len(set(names)) or len(entries)>10000 or sum(e.file_size for e in entries)>200*1024**2:
            raise ValueError('Invalid or oversized wheel')
        for entry in entries:
            parts=Path(entry.filename).parts
            if entry.filename.startswith(('/','\\')) or '..' in parts or '\\' in entry.filename or ':' in entry.filename or stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Unsafe wheel member')
        metadata=[name for name in names if name.endswith('.dist-info/METADATA')]
        records=[name for name in names if name.endswith('.dist-info/RECORD')]
        if len(metadata)!=1 or len(records)!=1: raise ValueError('Missing wheel metadata or RECORD')
        record={row[0]:row[1:] for row in csv.reader(io.StringIO(archive.read(records[0]).decode()))}
        if set(record)!=set(names): raise ValueError('Wheel RECORD file list differs')
        for name in names:
            if name==records[0]: continue
            expected,size=record[name]
            if not expected.startswith('sha256='): raise ValueError('Wheel member has no SHA-256')
            data=archive.read(name)
            actual=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            if actual!=expected.split('=',1)[1] or len(data)!=int(size): raise ValueError('Wheel RECORD hash mismatch')
        meta=BytesParser().parsebytes(archive.read(metadata[0]))
    name=re.sub(r'[-_.]+','-',meta['Name']).lower()
    return {'name':name,'version':meta['Version'],'sha256':sha,'size':len(raw),'file':path,
            'requires_python':meta.get('Requires-Python') or '', 'requires_dist':meta.get_all('Requires-Dist') or []}


def wheel_coverage(wheels):
    try:
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        from packaging.markers import default_environment
    except ImportError:
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.specifiers import SpecifierSet
        from pip._vendor.packaging.version import Version
        from pip._vendor.packaging.markers import default_environment
    by_name={wheel['name']:wheel for wheel in wheels}
    if len(by_name)!=len(wheels): raise ValueError('Duplicate wheel distribution')
    matrix=[]
    for platform,system,os_name in [('win32','Windows','nt'),('linux','Linux','posix'),('darwin','Darwin','posix')]:
        for python in ('3.10','3.13'):
            env={**default_environment(),'sys_platform':platform,'platform_system':system,'os_name':os_name,
                 'python_version':python,'python_full_version':python+'.0','extra':''}
            for wheel in wheels:
                if not SpecifierSet(wheel['requires_python']).contains(Version(python+'.0')):
                    raise ValueError('Wheel does not support required Python '+python)
                for raw in wheel['requires_dist']:
                    requirement=Requirement(raw)
                    if requirement.url is not None: raise ValueError('Direct URL dependencies are not allowed offline')
                    if requirement.marker and not requirement.marker.evaluate(env): continue
                    name=re.sub(r'[-_.]+','-',requirement.name).lower()
                    if name not in by_name or not requirement.specifier.contains(Version(by_name[name]['version'])):
                        raise ValueError('Offline dependency closure is incomplete: '+name+' for '+platform+' '+python)
                    if requirement.extras: raise ValueError('Dependency extras need an explicit V2 lock')
            matrix.append({'platform':platform,'python':python,'wheel_compatible':True})
    return matrix


def build_skill(destination,*,app_wheel,dependency_wheels,verify_hashes=True,
                validation_receipts=(),require_matrix=False,receipt_out=None):
    """Build one wheel-only offline Skill and record its actual validation scope."""
    import hashlib,json,os,platform,subprocess,sys,tempfile
    if verify_hashes is not True: raise ValueError('Bundle integrity verification cannot be disabled')
    version=_version()
    app=inspect_wheel(app_wheel)
    if app['name']!='paper-tool' or app['version']!=version: raise ValueError('Application wheel version differs from pyproject.toml')
    lock=json.loads((ROOT/'skills/citecargo/references/wheels.lock.json').read_text())
    expected={item['filename']:item['sha256'] for item in lock['wheels']}
    dependencies=[]
    for file in dependency_wheels:
        file=Path(file)
        if file.name not in expected: raise ValueError('Dependency wheel is not in the reviewed lock')
        dependencies.append(inspect_wheel(file,expected_sha256=expected[file.name]))
    wheels=[app,*dependencies]
    coverage=wheel_coverage(wheels)
    files=[]
    for name in ('SKILL.md','agents/openai.yaml','scripts/bootstrap.py','scripts/citecargo.py'):
        files.append((ROOT/'skills/citecargo'/name,name,'instructions'))
    files.extend((p,'references/'+p.name,'reference') for p in sorted((ROOT/'skills/citecargo/references').iterdir()) if p.is_file() and not p.is_symlink() and p.suffix in {'.md','.json'})
    files.append((ROOT/'LICENSE','LICENSE','license'))
    files.extend((w['file'],'vendor/wheels/'+w['file'].name,'wheel') for w in wheels)
    entries=[]
    for file,name,role in files:
        if file.is_symlink(): raise ValueError('No symbolic links in a Skill archive')
        raw=file.read_bytes()
        item={'path':name,'role':role,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
        if role=='wheel': item.update(next({k:w[k] for k in ('name','version')} for w in wheels if w['file']==file))
        entries.append(item)
    payload_hash=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    manifest={'schema_version':'2.0','app_version':version,'integrity_validated':True,'payload_sha256':payload_hash,
              'files':entries,'validation':{'wheel_coverage':coverage,'runtime_tested':[],'matrix_complete':False}}
    receipts=[]
    for receipt in validation_receipts:
        data=json.loads(Path(receipt).read_text()) if not isinstance(receipt,dict) else receipt
        if (data.get('payload_sha256')!=payload_hash or data.get('status')!='PASSED'
                or not {'offline_bootstrap','version','plan','status'}.issubset(set(data.get('checks') or []))
                or data.get('platform') not in {'linux','darwin','win32'}
                or data.get('python') not in {'3.10','3.11','3.12','3.13'} or not isinstance(data.get('machine'),str)):
            raise ValueError('Stale, incomplete or failed validation receipt')
        receipts.append(data)
    with tempfile.TemporaryDirectory(prefix='citecargo-bundle-check-') as temp:
        temp=Path(temp)
        root=temp/'citecargo'
        for file,name,_role in files:
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(file.read_bytes())
        (root/'bundle-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2),encoding='utf-8')
        env={**os.environ,'CITECARGO_RUNTIME_CACHE':str(temp/'runtime-cache'),'PIP_NO_INDEX':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
        command=[sys.executable,'-I',str(root/'scripts/bootstrap.py')]
        checked=subprocess.run(command,cwd=temp,env=env,capture_output=True,text=True,timeout=360)
        if checked.returncode: raise ValueError('Offline Skill initialization failed: '+checked.stdout[:500])
        prepared=json.loads(checked.stdout)
        cli=prepared['command']
        source=temp/'references.txt';source.write_text('10.1000/offline-check\n')
        out=temp/'offline-job'
        for args in (['plan','--input',str(source),'--out',str(out),'--oa-only'],['status','--out',str(out),'--json']):
            run=subprocess.run([*cli,*args],cwd=temp,env=env,capture_output=True,text=True,timeout=30)
            if run.returncode: raise ValueError('Offline plan/status check failed')
            json.loads(run.stdout)
        receipt={'payload_sha256':payload_hash,'platform':sys.platform,'python':str(sys.version_info[0])+'.'+str(sys.version_info[1]),
                 'machine':platform.machine(),'status':'PASSED','checks':['offline_bootstrap','version','plan','status']}
        receipts=[r for r in receipts if (r['platform'],r['python'])!=(receipt['platform'],receipt['python'])]+[receipt]
        manifest['validation']['runtime_tested']=receipts
        passed={(r['platform'],r['python']) for r in receipts}
        required={(r['platform'],r['python']) for r in coverage}
        manifest['validation']['matrix_complete']=required.issubset(passed)
        if require_matrix and not manifest['validation']['matrix_complete']:
            raise ValueError('Required Windows/Linux/macOS Python 3.10/3.13 runtime matrix is incomplete')
        destination=Path(destination)
        destination.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
            for file,name,_role in files: archive.write(file,'citecargo/'+name)
            archive.writestr('citecargo/bundle-manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
        if receipt_out:
            path=Path(receipt_out);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(receipt,sort_keys=True,indent=2))
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
        archive.writestr('CiteCargo/Start-CiteCargo.cmd',(ROOT/'scripts/windows/start.cmd').read_bytes().replace(b'paper-tool==1.2.0',('paper-tool=='+version).encode()))
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
    parser.add_argument('--receipt',type=Path,action='append',default=[])
    parser.add_argument('--receipt-out',type=Path)
    parser.add_argument('--require-matrix',action='store_true')
    args = parser.parse_args()
    if args.kind == 'windows':
        if not args.wheel or not args.dependency:
            parser.error('--kind windows requires --wheel and --dependency')
        print(build_windows(args.destination, args.wheel, args.dependency))
    elif args.kind=='skill':
        if not args.wheel or not args.dependency: parser.error('--kind skill requires --wheel and --dependency')
        print(build_skill(args.destination,app_wheel=args.wheel,dependency_wheels=args.dependency,
            validation_receipts=args.receipt,require_matrix=args.require_matrix,receipt_out=args.receipt_out))
    else:
        print(build_release(args.destination))
