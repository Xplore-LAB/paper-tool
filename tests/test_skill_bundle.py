"""Real offline bootstrap against universal fixture wheels; no online resolution."""
import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import release
PROJECT=Path(__file__).resolve().parents[1]


def wheel(folder,name,version,files,requires=()):
    normalized=name.replace('-','_')
    prefix=normalized+'-'+version+'.dist-info/'
    files=dict(files)
    files[prefix+'METADATA']=('Metadata-Version: 2.1\nName: '+name+'\nVersion: '+version+'\nRequires-Python: >=3.10\n'+''.join('Requires-Dist: '+r+'\n' for r in requires)+'\n').encode()
    files[prefix+'WHEEL']=b'Wheel-Version: 1.0\nGenerator: offline-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    record=io.StringIO(); writer=csv.writer(record,lineterminator='\n')
    for path,data in files.items():
        sha=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow((path,'sha256='+sha,str(len(data))))
    writer.writerow((prefix+'RECORD','',''))
    files[prefix+'RECORD']=record.getvalue().encode()
    path=folder/(normalized+'-'+version+'-py3-none-any.whl')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        for path_in_zip,data in files.items(): archive.writestr(path_in_zip,data)
    return path


class SkillBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='citecargo-bundle-tests-')
        cls.root=Path(cls.tmp.name)
        cls.project=cls.root/'project';cls.project.mkdir()
        for name in ('pyproject.toml','LICENSE'):
            shutil.copyfile(PROJECT/name,cls.project/name)
        shutil.copytree(PROJECT/'skills/citecargo',cls.project/'skills/citecargo',ignore=shutil.ignore_patterns('__pycache__','vendor','bundle-manifest.json'))
        cls.version=release._version()
        folder=cls.root/'wheels';folder.mkdir()
        sources={p.relative_to(PROJECT/'src').as_posix():p.read_bytes() for p in (PROJECT/'src/paper_tool').rglob('*') if p.is_file() and p.suffix in {'.py','.mjs','.js','.html','.css'} and '__pycache__' not in p.parts}
        cls.app=wheel(folder,'paper-tool',cls.version,sources,['pypdf>=4,<7'])
        cls.pdf=wheel(folder,'pypdf','6.0.0',{'pypdf/__init__.py':b'__version__="6.0.0"\n'},['typing_extensions>=4; python_version < "3.11"'])
        cls.typing=wheel(folder,'typing-extensions','4.0.0',{'typing_extensions.py':b'# offline fixture\n'})
        cls.dependencies=[cls.pdf,cls.typing]
        lock={'wheels':[{'filename':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in cls.dependencies]}
        (cls.project/'skills/citecargo/references/wheels.lock.json').write_text(json.dumps(lock))
        cls.bundle=cls.root/'Skill.zip'
        with patch.object(release,'ROOT',cls.project):
            release.build_skill(cls.bundle,app_wheel=cls.app,dependency_wheels=cls.dependencies)
        cls.extracted=cls.root/'extracted'
        with zipfile.ZipFile(cls.bundle) as archive: archive.extractall(cls.extracted)
        cls.skill=cls.extracted/'citecargo'
        spec=importlib.util.spec_from_file_location('_test_citecargo_bootstrap',PROJECT/'skills/citecargo/scripts/bootstrap.py')
        cls.bootstrap=importlib.util.module_from_spec(spec)
        with patch.object(sys,'dont_write_bytecode',True): spec.loader.exec_module(cls.bootstrap)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_contains_one_engine_in_wheels_and_no_machine_state(self):
        with zipfile.ZipFile(self.bundle) as archive:
            names=archive.namelist()
        self.assertIn('citecargo/scripts/bootstrap.py',names)
        self.assertEqual(sum(n.endswith('.whl') and 'paper_tool-' in n for n in names),1)
        self.assertFalse(any('/paper_tool/' in n or '/.venv/' in n or n.endswith(('.pdf','.dpapi')) for n in names))
        checked=self.bootstrap.verify_bundle(self.skill)
        self.assertFalse(checked['manifest']['validation']['release_ready'])
        self.assertEqual(len(checked['manifest']['validation']['wheel_coverage']),6)

    def test_launcher_is_offline_independent_of_cwd_and_does_not_modify_package(self):
        before={p.relative_to(self.skill):p.read_bytes() for p in self.skill.rglob('*') if p.is_file()}
        cache=self.root/'launcher-cache'
        env={**os.environ,'CITECARGO_RUNTIME_CACHE':str(cache),'PIP_INDEX_URL':'http://127.0.0.1:1/should-not-be-used'}
        command=[sys.executable,str(self.skill/'scripts/citecargo.py'),'--version']
        for _ in range(2):
            result=subprocess.run(command,cwd=self.root,env=env,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.strip(),'citecargo '+self.version)
        receipts=list(cache.glob('*/runtime.json'))
        self.assertEqual(len(receipts),1)
        # An interrupted setup has no receipt. Repeating it uses only bundled wheels.
        receipts[0].unlink()
        result=subprocess.run(command,cwd=self.root,env=env,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        after={p.relative_to(self.skill):p.read_bytes() for p in self.skill.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_tampered_wheel_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'skill'
            shutil.copytree(self.skill,root)
            file=next((root/'vendor/wheels').glob('*.whl'))
            file.write_bytes(file.read_bytes()+b'tampered')
            with self.assertRaises(self.bootstrap.BootstrapError) as error:
                self.bootstrap.verify_bundle(root)
            self.assertEqual(error.exception.code,'BUNDLE_TAMPERED')

    def test_unlisted_files_and_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'skill';shutil.copytree(self.skill,root)
            (root/'unexpected.py').write_text('raise RuntimeError("must never run")')
            with self.assertRaises(self.bootstrap.BootstrapError): self.bootstrap.verify_bundle(root)
            (root/'unexpected.py').unlink()
            path=root/'bundle-manifest.json';data=json.loads(path.read_text())
            data['files'][0]['path']='../../outside'
            path.write_text(json.dumps(data))
            with self.assertRaises(self.bootstrap.BootstrapError): self.bootstrap.verify_bundle(root)

    def test_missing_py310_dependency_is_detected_for_all_build_hosts(self):
        with patch.object(release,'ROOT',self.project),self.assertRaises(ValueError):
            release.build_skill(self.root/'missing.zip',app_wheel=self.app,dependency_wheels=[self.pdf])
        self.assertFalse((self.root/'missing.zip').exists())

    def test_hash_verification_cannot_be_disabled(self):
        with self.assertRaises(ValueError):
            release.build_skill(self.root/'unsafe.zip',app_wheel=self.app,dependency_wheels=self.dependencies,verify_hashes=False)

    def test_direct_url_dependency_is_not_offline_compatible(self):
        item=release.inspect_wheel(self.app)
        item['requires_dist']=['pypdf @ https://example.test/untrusted.whl']
        with self.assertRaises(ValueError): release.wheel_coverage([item])

    def test_old_python_and_source_only_skill_report_diagnostics(self):
        with patch.object(sys,'version_info',(3,9,0)),self.assertRaises(self.bootstrap.BootstrapError) as error:
            self.bootstrap.check_python()
        self.assertEqual(error.exception.code,'PYTHON_VERSION_UNSUPPORTED')
        with tempfile.TemporaryDirectory() as temp,self.assertRaises(self.bootstrap.BootstrapError) as error:
            self.bootstrap.verify_bundle(Path(temp))
        self.assertEqual(error.exception.code,'BUNDLE_INCOMPLETE')
