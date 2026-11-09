"""Verify the bundled wheels and prepare a user-owned runtime without network."""
from __future__ import annotations
import os
import sys
if __name__=='__main__' and (not sys.flags.isolated or not sys.flags.utf8_mode):
    os.execv(sys.executable,[sys.executable,'-I','-X','utf8',os.path.abspath(__file__),*sys.argv[1:]])
import argparse
from contextlib import contextmanager
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]

class BootstrapError(Exception):
    def __init__(self,code,message):
        super().__init__(message)
        self.code=code
    def as_dict(self): return {'ok':False,'error_code':self.code,'message':str(self)}

def check_python():
    if sys.version_info<(3,10):
        raise BootstrapError('PYTHON_VERSION_UNSUPPORTED','Python 3.10 or newer is required; no network installation was attempted.')
    try:
        import venv,ensurepip
    except ImportError as error:
        raise BootstrapError('RUNTIME_MISSING','Python venv and ensurepip are required; ask the user to provide a complete Python installation.') from error
    return {'python':sys.version.split()[0],'platform':sys.platform}

def _safe_file(root,name):
    if not isinstance(name,str) or '\\' in name:
        raise BootstrapError('BUNDLE_TAMPERED','Invalid bundle path.')
    parts=PurePosixPath(name)
    if parts.is_absolute() or '..' in parts.parts or ':' in name:
        raise BootstrapError('BUNDLE_TAMPERED','Bundle path leaves the package.')
    file=root.joinpath(*parts.parts)
    if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(root):
        raise BootstrapError('BUNDLE_INCOMPLETE','A bundled file is missing or is a symbolic link.')
    return file

def verify_bundle(bundle_root=None):
    root=Path(bundle_root).resolve() if bundle_root is not None else ROOT
    try:
        manifest=json.loads((root/'bundle-manifest.json').read_text(encoding='utf-8'))
        assert manifest['schema_version']=='2.0' and manifest['integrity_validated'] is True
        assert isinstance(manifest['files'],list) and manifest['files']
    except (OSError,ValueError,KeyError,AssertionError,TypeError) as error:
        raise BootstrapError('BUNDLE_INCOMPLETE','Use the complete offline Skill archive; the source instruction folder alone has no runtime.') from error
    wheels=[]
    names=set()
    expected_paths=set()
    for entry in manifest['files']:
        try:
            name=entry['path']; expected=entry['sha256']
            if name in expected_paths: raise ValueError()
            expected_paths.add(name)
            file=_safe_file(root,name)
            if file.stat().st_size!=entry['size'] or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
                raise BootstrapError('BUNDLE_TAMPERED','A bundled file failed SHA-256 verification; reinstall a trusted package.')
            if entry['role']=='wheel':
                if not name.startswith('vendor/wheels/') or not file.name.endswith('-py3-none-any.whl'):
                    raise BootstrapError('BUNDLE_TAMPERED','Unsupported bundled wheel path or platform tag.')
                with zipfile.ZipFile(file) as archive:
                    metadata_files=[n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
                    if len(metadata_files)!=1: raise ValueError()
                    metadata=BytesParser().parsebytes(archive.read(metadata_files[0]))
                    project=re.sub(r'[-_.]+','-',metadata['Name']).lower()
                    version=metadata['Version']
                    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',project) or not re.fullmatch(r'[0-9][A-Za-z0-9.!+_-]*',version): raise ValueError()
                    if project in names: raise ValueError()
                    names.add(project)
                    if project!=entry['name'] or version!=entry['version']: raise ValueError()
                    wheels.append({**entry,'file':file})
        except BootstrapError: raise
        except (KeyError,ValueError,TypeError,OSError,zipfile.BadZipFile) as error:
            raise BootstrapError('BUNDLE_TAMPERED','Invalid offline bundle manifest or wheel metadata.') from error
    app=[entry for entry in wheels if entry['name']=='paper-tool']
    if len(app)!=1 or app[0]['version']!=manifest.get('app_version'):
        raise BootstrapError('BUNDLE_TAMPERED','The application version does not match the bundle.')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if any(p.is_symlink() for p in root.rglob('*')):
        raise BootstrapError('BUNDLE_TAMPERED','Symbolic links are not allowed in the Skill package.')
    if actual!=expected_paths|{'bundle-manifest.json'}:
        raise BootstrapError('BUNDLE_TAMPERED','Unexpected or missing files in the Skill package.')
    identity=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'root':root,'manifest':manifest,'wheels':wheels,'identity':identity}

def _cache_base():
    if os.environ.get('CITECARGO_RUNTIME_CACHE'):
        return Path(os.environ['CITECARGO_RUNTIME_CACHE']).expanduser().resolve()
    if sys.platform=='win32':
        base=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')
    elif sys.platform=='darwin': base=Path.home()/'Library/Caches'
    else: base=Path(os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')
    return base.expanduser().resolve()/'CiteCargo/runtimes'

def _runtime(bundle):
    key=bundle['manifest']['app_version']+'-py'+str(sys.version_info[0])+'.'+str(sys.version_info[1])+'-'+sys.platform+'-'+bundle['identity'][:16]
    base=_cache_base()
    if base.is_relative_to(bundle['root']):
        raise BootstrapError('RUNTIME_LOCATION_INVALID','The runtime cache must be outside the read-only Skill package.')
    return base/key

def _python(runtime): return runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def _environment():
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','PIP_REQUIRE_VIRTUALENV'): env.pop(key,None)
    env.update(PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONNOUSERSITE='1')
    return env

@contextmanager
def _runtime_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    handle=path.open('a+b')
    locked=False
    try:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,2)==0: handle.write(b'0');handle.flush()
            handle.seek(0)
            try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError: raise BootstrapError('RUNTIME_LOCKED','Another process is preparing this runtime.')
        else:
            import fcntl
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise BootstrapError('RUNTIME_LOCKED','Another process is preparing this runtime.')
        locked=True
        yield
    finally:
        if locked:
            if os.name=='nt': handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle,fcntl.LOCK_UN)
        handle.close()

def _installed_version(runtime):
    try:
        result=subprocess.run([str(_python(runtime)),'-I','-X','utf8','-m','paper_tool','--version'],
            cwd=runtime,env=_environment(),capture_output=True,text=True,timeout=30)
        return result.stdout.strip().split()[-1] if result.returncode==0 and result.stdout.strip() else None
    except (OSError,subprocess.TimeoutExpired): return None

def _atomic(path,data):
    fd,name=tempfile.mkstemp(prefix='runtime-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle: json.dump(data,handle,sort_keys=True)
        os.replace(name,path)
    finally:
        if Path(name).exists(): Path(name).unlink()

def ensure_runtime():
    check_python()
    bundle=verify_bundle()
    runtime=_runtime(bundle)
    expected=bundle['manifest']['app_version']
    receipt=runtime/'runtime.json'
    with _runtime_lock(runtime.with_name(runtime.name+'.lock')):
        if receipt.is_file():
            try: saved=json.loads(receipt.read_text(encoding='utf-8'))
            except (ValueError,OSError): saved={}
            if saved.get('bundle_identity')==bundle['identity'] and _installed_version(runtime)==expected:
                return runtime
        marker=runtime/'.citecargo-runtime'
        if runtime.exists() and (not marker.is_file() or marker.read_text(encoding='utf-8')!=bundle['identity']):
            raise BootstrapError('RUNTIME_CONFLICT','The dedicated runtime directory has unexpected contents; it was left unchanged.')
        runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
        marker.write_text(bundle['identity'],encoding='utf-8')
        import venv
        try:
            # Relocatable POSIX Python builds need links to their base binary;
            # Windows copies avoid requiring symlink/admin privileges.
            venv.EnvBuilder(with_pip=True,clear=False,symlinks=os.name!='nt').create(runtime)
            requirements=runtime/'requirements.lock'
            requirements.write_text(''.join(w['name']+'=='+w['version']+' --hash=sha256:'+w['sha256']+'\n' for w in bundle['wheels']),encoding='utf-8')
            command=[str(_python(runtime)),'-I','-X','utf8','-m','pip','--isolated','install',
                '--no-index','--no-deps','--only-binary=:all:','--no-cache-dir','--disable-pip-version-check',
                '--force-reinstall','--require-hashes','--find-links',str(bundle['root']/'vendor/wheels'),'-r',str(requirements)]
            result=subprocess.run(command,cwd=runtime,env=_environment(),capture_output=True,text=True,timeout=300)
            (runtime/'setup.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            if result.returncode: raise BootstrapError('RUNTIME_SETUP_FAILED','Offline installation failed; inspect setup.log in the dedicated runtime.')
            checked=subprocess.run([str(_python(runtime)),'-I','-X','utf8','-m','pip','check'],cwd=runtime,env=_environment(),capture_output=True,text=True,timeout=30)
            if checked.returncode or _installed_version(runtime)!=expected:
                raise BootstrapError('RUNTIME_SETUP_FAILED','Installed dependencies or CLI version failed verification; retrying is safe.')
            _atomic(receipt,{'bundle_identity':bundle['identity'],'app_version':expected,'python':sys.version.split()[0]})
        except BootstrapError: raise
        except (OSError,subprocess.SubprocessError) as error:
            raise BootstrapError('RUNTIME_SETUP_FAILED','Local runtime initialization was interrupted; rerun after checking Python and disk access.') from error
    return runtime

def get_cli_command():
    return [str(_python(ensure_runtime())),'-I','-X','utf8','-m','paper_tool']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnose',action='store_true')
    args=parser.parse_args()
    try:
        info=check_python()
        bundle=verify_bundle()
        if args.diagnose:
            result={'ok':True,**info,'app_version':bundle['manifest']['app_version'],
                    'runtime_ready':(_runtime(bundle)/'runtime.json').is_file(),'network_required':False,
                    'release_ready':bundle['manifest']['validation']['release_ready']}
        else: result={'ok':True,**info,'command':get_cli_command(),'network_required':False}
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except BootstrapError as error:
        print(json.dumps(error.as_dict(),ensure_ascii=False))
        return 2
    except (OSError,ValueError,TypeError):
        print(json.dumps({'ok':False,'error_code':'RUNTIME_SETUP_FAILED','message':'Check local cache access and bundle integrity; no network installation was attempted.'}))
        return 2

if __name__=='__main__': raise SystemExit(main())
