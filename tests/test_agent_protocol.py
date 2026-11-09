"""Plans bind scope; execution and status use a stable machine-readable contract."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from paper_tool import agent, batch, cli, core
from paper_tool.errors import ErrorCode, PaperError
from paper_tool.safety import SafetyGuard, SafetyPolicy, use_guard, writer_lock
from tests.test_workflows import make_pdf
from tests.test_safety import Clock

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.input=self.root/'refs.txt'
        self.input.write_text('10.1000/ONE\nhttps://doi.org/10.1000/one\n10.1000/two\n')
        self.out=self.root/'job'

    def plan(self,**kwargs): return agent.make_plan(self.input,self.out,**kwargs)

    def runner(self,ref,args):
        pdf=make_pdf(Path(args.out)/(core.doi_from(ref).replace('/','_')+'.pdf'))
        return {'status':'PDF_SAVED','paper':{'doi':core.doi_from(ref),'title':'A verified paper about oxygen supply networks'},
                'pdf':str(pdf),'sha256':core.pdf_sha256(pdf)}

    def test_offline_plan_deduplicates_dois_without_network_or_archive(self):
        with patch.object(core,'request_bytes',side_effect=AssertionError('Offline plan')), \
             patch.object(core,'ZoteroLocal',side_effect=AssertionError('No archive')):
            plan=self.plan()
        self.assertEqual(len(plan['references']),2)
        self.assertEqual(plan['schema_version'],'2.0')
        self.assertTrue(plan['options']['oa_only'])
        self.assertFalse((self.out/'manifest.json').exists())
        self.assertEqual(agent.load_plan(self.out/'plan.json')['plan_hash'],plan['plan_hash'])

    def test_input_change_and_plan_change_fail_before_network(self):
        self.plan()
        self.input.write_text('10.1000/changed')
        with patch.object(core,'request_bytes',side_effect=AssertionError('No request')),self.assertRaises(PaperError) as error:
            agent.execute_plan(self.out/'plan.json')
        self.assertEqual(error.exception.code,ErrorCode.INVALID_PLAN)
        self.assertFalse((self.out/'manifest.json').exists())
        self.plan()
        path=self.out/'plan.json'
        data=json.loads(path.read_text());data['options']['out']=str(self.root/'other')
        path.write_text(json.dumps(data))
        with self.assertRaises(PaperError): agent.execute_plan(path)

    def test_metadata_preflight_never_downloads_or_connects_zotero(self):
        with patch.object(core,'crossref_metadata',return_value=(core.SAMPLE_RECORD,1)) as lookup, \
             patch.object(core,'download_verified',side_effect=AssertionError('No PDF')), \
             patch.object(core,'ZoteroLocal',side_effect=AssertionError('No Zotero')):
            plan=self.plan(metadata_preflight=True)
        self.assertEqual(lookup.call_count,2)
        self.assertEqual(plan['preflight']['mode'],'metadata')

    def test_job_downloads_and_second_run_reuses_files(self):
        self.plan()
        with patch.object(cli,'run_reference',side_effect=self.runner) as run, \
             patch.object(core,'ZoteroLocal',side_effect=AssertionError('No archival')):
            first=agent.execute_plan(self.out/'plan.json')
            second=agent.execute_plan(self.out/'plan.json')
        self.assertEqual(run.call_count,2)
        self.assertEqual(first['status'],'COMPLETED')
        self.assertEqual(second['summary']['pdf_verified'],2)
        self.assertEqual(second['summary']['archive_completed'],0)
        self.assertEqual(second['summary']['pending'],0)
        self.assertEqual(second['job_id'],first['job_id'])
        self.assertEqual(agent.status(self.out)['status'],'COMPLETED')

    def test_zotero_plan_needs_explicit_job_scope_acknowledgment(self):
        self.plan(zotero=True,collection='Existing/Collection')
        with patch.object(core,'ZoteroLocal',side_effect=AssertionError('Must not connect')),self.assertRaises(PaperError) as error:
            agent.execute_plan(self.out/'plan.json')
        self.assertEqual(error.exception.code,ErrorCode.ACCESS_DENIED)
        self.assertFalse((self.out/'manifest.json').exists())

    def test_pilot_failure_pauses_before_remainder(self):
        self.input.write_text('\n'.join('10.1000/p'+str(i) for i in range(8)))
        self.plan()
        seen=[]
        def runner(ref,args):
            seen.append(ref)
            return {'status':'PDF_PENDING','paper':{'doi':ref,'title':'Missing'}}
        with patch.object(cli,'run_reference',side_effect=runner):
            report=agent.execute_plan(self.out/'plan.json')
        self.assertEqual(len(seen),5)
        self.assertEqual(report['status'],'PAUSED')
        self.assertEqual(report['stop_reason'],'PILOT_REVIEW')
        self.assertEqual(report['summary']['total'],8)
        self.assertEqual(len(batch.load_rows(self.out)),8)

    def test_cancel_keeps_successes_and_resume_does_not_redownload(self):
        self.plan()
        stop=threading.Event(); seen=[]
        def runner(ref,args):
            seen.append(ref)
            result=self.runner(ref,args)
            stop.set()
            return result
        with patch.object(cli,'run_reference',side_effect=runner):
            paused=agent.execute_plan(self.out/'plan.json',stop_token=stop)
        self.assertEqual(paused['status'],'PAUSED')
        self.assertEqual(paused['stop_reason'],'USER_CANCELLED')
        self.assertEqual(paused['summary']['pdf_verified'],1)
        with patch.object(cli,'run_reference',side_effect=self.runner) as run:
            done=agent.execute_plan(self.out/'plan.json')
        self.assertEqual(run.call_count,1)
        self.assertEqual(done['summary']['pdf_verified'],2)

    def test_checkpoint_lock_rejects_second_writer(self):
        self.plan()
        errors=[]
        with writer_lock(self.out):
            def contender():
                try:
                    with writer_lock(self.out): pass
                except PaperError as error: errors.append(error.code)
            t=threading.Thread(target=contender);t.start();t.join(2)
        self.assertEqual(errors,[ErrorCode.JOB_LOCKED])

    def test_status_is_read_only_and_json_cli_is_single_payload(self):
        self.plan()
        before={p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        with patch.object(core,'request_bytes',side_effect=AssertionError('Status is offline')):
            result=agent.status(self.out)
            text=io.StringIO()
            with contextlib.redirect_stdout(text):
                code=cli.app(['status','--out',str(self.out),'--json'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(text.getvalue())['status'],'PLANNED')
        self.assertEqual(result['summary']['pending'],2)
        after={p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        self.assertEqual(before,after)

    def test_plan_status_and_errors_conform_to_json_schema(self):
        import jsonschema
        schema=json.loads((Path(__file__).parents[1]/'skills/citecargo/references/agent-protocol.schema.json').read_text())
        validator=jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())
        plan=self.plan()
        validator.validate(plan)
        validator.validate(agent.status(self.out))
        with patch.object(cli,'run_reference',side_effect=self.runner):
            validator.validate(agent.execute_plan(self.out/'plan.json'))
        self.input.write_text('changed')
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(cli.app(['job','--plan',str(self.out/'plan.json')]),2)
        validator.validate(json.loads(stream.getvalue()))

    def test_changed_pdf_is_not_reported_as_completed(self):
        self.plan()
        with patch.object(cli,'run_reference',side_effect=self.runner):
            result=agent.execute_plan(self.out/'plan.json')
        Path(result['results'][0]['pdf']).write_bytes(b'%PDF-broken')
        status=agent.status(self.out)
        self.assertEqual(status['status'],'PARTIAL')
        self.assertEqual(status['summary']['pdf_verified'],1)
        self.assertEqual(status['summary']['pending'],1)

    def test_preflight_source_pause_carries_into_job(self):
        from urllib.error import HTTPError
        from unittest.mock import MagicMock
        opener=MagicMock()
        opener.open.side_effect=HTTPError('https://api.crossref.org/works/x',403,'Denied',{},io.BytesIO())
        with patch.object(core,'build_opener',return_value=opener):
            self.plan(metadata_preflight=True)
            result=agent.execute_plan(self.out/'plan.json')
        self.assertEqual(opener.open.call_count,1)
        self.assertEqual(result['summary']['pdf_verified'],0)
        self.assertEqual(result['status'],'PAUSED')

    def test_plan_cannot_overwrite_unrelated_input_or_plan_file(self):
        self.out.mkdir()
        path=self.out/'plan.json'
        path.write_text('10.1000/protected\n')
        with self.assertRaises(PaperError): agent.make_plan(path,self.out)
        self.assertEqual(path.read_text(),'10.1000/protected\n')
        with self.assertRaises(PaperError): self.plan()
        self.assertEqual(path.read_text(),'10.1000/protected\n')

    def test_cli_rejects_relaxed_safety_policy(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=cli.app(['plan','--input',str(self.input),'--out',str(self.out),'--min-interval','0'])
        self.assertEqual(code,2)
        self.assertEqual(json.loads(stream.getvalue())['error_code'],'INVALID_PLAN')
        self.assertFalse((self.out/'plan.json').exists())

    def test_foreign_pdf_never_reaches_zotero_attachment(self):
        from unittest.mock import MagicMock
        self.input.write_text('10.1000/one\n')
        self.plan(zotero=True,collection='Existing')
        raw=make_pdf(self.root/'foreign.pdf','Unrelated quantum optics experiment').read_bytes()
        class Response(io.BytesIO):
            status=200;headers={}
            def geturl(self): return 'https://repository.test/foreign.pdf'
        opener=MagicMock();opener.open.side_effect=lambda *a,**kw:Response(raw)
        zotero=MagicMock();zotero.server_id='test-instance'
        zotero.collections.return_value=[{'key':'COL','name':'Existing','path':'Existing'}]
        zotero.ensure_item.return_value=('ITEM',True)
        metadata=dict(core.SAMPLE_RECORD,DOI='10.1000/one',title=['A verified paper about oxygen supply networks'])
        with patch.object(core,'ZoteroLocal',return_value=zotero), \
             patch.object(core,'crossref_metadata',return_value=(metadata,1)), \
             patch.object(core,'pdf_candidates',return_value=[{'url':'https://repository.test/foreign.pdf','source':'test'}]), \
             patch.object(core,'build_opener',return_value=opener):
            report=agent.execute_plan(self.out/'plan.json',allow_zotero=True)
        self.assertEqual(report['summary']['pdf_verified'],0)
        self.assertEqual(report['results'][0]['error_code'],'PDF_IDENTITY_MISMATCH')
        zotero.ensure_pdf.assert_not_called()
        self.assertFalse(list((self.out/'PDF').glob('*.pdf')))

    def test_metadata_only_does_not_inspect_existing_pdf(self):
        from unittest.mock import MagicMock
        self.input.write_text('10.1000/one\n')
        pdf=make_pdf(self.root/'existing.pdf')
        batch.save_rows(self.out,[{'input':'10.1000/one','doi':'10.1000/one','title':'Existing paper',
                                 'status':'PDF_SAVED','pdf':str(pdf),'sha256':core.pdf_sha256(pdf)}])
        self.plan(zotero=True,collection='Existing',metadata_only=True)
        zotero=MagicMock();zotero.server_id='test-instance'
        zotero.collections.return_value=[{'key':'COL','name':'Existing','path':'Existing'}]
        zotero.items.return_value=[{'DOI':'10.1000/one','title':'Existing paper','date':'2026'}]
        zotero.ensure_item.return_value=('ITEM',True)
        with patch.object(core,'ZoteroLocal',return_value=zotero), \
             patch.object(core,'checkpoint_pdf_valid',side_effect=AssertionError('No PDF inspection')), \
             patch.object(core,'download_verified',side_effect=AssertionError('No download')):
            result=agent.execute_plan(self.out/'plan.json',allow_zotero=True)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['summary']['archive_completed'],1)
        self.assertEqual(result['summary']['pdf_verified'],0)
        self.assertIsNone(result['results'][0]['error_code'])
        zotero.ensure_pdf.assert_not_called()
