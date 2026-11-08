import argparse
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from paper_tool import cli as t


class ToolTests(unittest.TestCase):
    def args(self, out):
        return argparse.Namespace(command='fetch',out=out,oa_only=False,zotero=False,proxy='http://127.0.0.1:1081',cdp='http://127.0.0.1:18806')

    def test_preview_never_downloads(self):
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.command='preview'
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified') as download:
                self.assertEqual(t.run_reference('test',args)['status'],'PREVIEW')
                download.assert_not_called()

    def test_browser_fallback_validates_before_acceptance(self):
        record=dict(t.core.SAMPLE_RECORD,link=[{'URL':'https://api.elsevier.com/content/article/PII:S0020025526007310'}])
        for verified in (True,False):
            with self.subTest(verified=verified),tempfile.TemporaryDirectory() as out:
                def browser(cmd,**kwargs):
                    Path(cmd[cmd.index('--out')+1]).write_bytes(b'%PDF-test')
                    return argparse.Namespace(returncode=0)
                with patch.object(t.core,'crossref_metadata',return_value=(record,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(None,None,[])),patch.object(t.subprocess,'run',side_effect=browser),patch.object(t.core,'verify_pdf',return_value=(verified,'fixture')):
                    r=t.run_reference('test',self.args(out))
                    self.assertEqual(r['status'],'PDF_SAVED' if verified else 'PDF_PENDING')

    def test_oa_only_never_opens_institutional_browser(self):
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.oa_only=True
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(None,None,[])),patch.object(t.subprocess,'run') as browser:
                self.assertEqual(t.run_reference('test',args)['status'],'PDF_PENDING')
                browser.assert_not_called()

    def test_zotero_failure_preserves_successful_pdf(self):
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.zotero=True;args.zotero_base='http://127.0.0.1:23129/api';args.collection='Test'
            pdf=Path(out)/'paper.pdf';pdf.write_bytes(b'%PDF-fixture')
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(pdf,{'source':'fixture'},[])),patch.object(t.core,'ZoteroLocal',side_effect=t.core.PaperError('unavailable')):
                result=t.run_reference('test',args)
                self.assertEqual(result['status'],'PDF_SAVED')
                self.assertEqual(result['zotero'],'WRITE_PENDING')
                self.assertTrue(Path(result['pdf']).is_file())

    def test_progress_reports_files_and_issues_without_writing(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = Path(out) / 'saved.pdf'; pdf.write_bytes(b'%PDF-fixture')
            manifest = [
                {'number': 1, 'title': 'Attached', 'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'sha256': t.core.pdf_sha256(pdf)},
                {'number': 2, 'title': 'Pending', 'status': 'PDF_PENDING', 'warnings': 'Security verification'},
                {'number': 3, 'input_title': 'Review', 'status': '待核验/补全'},
            ]
            (Path(out) / 'manifest.json').write_text(__import__('json').dumps(manifest), encoding='utf-8')
            snapshot = t.progress_snapshot(out)
            self.assertTrue(snapshot['ok'])
            self.assertEqual(snapshot['valid_pdf'], 1)
            self.assertEqual(snapshot['pending'], 1)
            self.assertEqual(snapshot['review'], 1)
            self.assertIn('Security verification', t.format_progress(snapshot))

    def test_doctor_direct_route_does_not_require_proxy_port(self):
        from unittest.mock import MagicMock

        def probe(address, timeout=None):
            if address[1] == 1081:
                raise OSError('no local HTTP proxy')
            return MagicMock()

        with patch.object(t.socket, 'create_connection', side_effect=probe):
            result = t.doctor('direct')
        self.assertTrue(result['ok'])
        self.assertEqual(result['required'], ['browser_cdp'])
        self.assertFalse(result['checks']['vpn_proxy'])

    def test_doctor_proxy_route_still_requires_proxy_port(self):
        from unittest.mock import MagicMock

        def probe(address, timeout=None):
            if address[1] == 1081:
                raise OSError('no local HTTP proxy')
            return MagicMock()

        with patch.object(t.socket, 'create_connection', side_effect=probe):
            result = t.doctor('http://127.0.0.1:1081')
        self.assertFalse(result['ok'])
        self.assertEqual(result['required'], ['vpn_proxy', 'browser_cdp'])

    def test_progress_falls_back_to_report_json(self):
        import json
        with tempfile.TemporaryDirectory() as out:
            pdf = Path(out) / 'saved.pdf'; pdf.write_bytes(b'%PDF-fixture')
            report = {'results': [
                {'paper': {'title': 'Saved paper'}, 'status': 'PDF_SAVED', 'pdf': str(pdf), 'sha256': t.core.pdf_sha256(pdf), 'warnings': []},
                {'paper': {'title': 'Pending paper'}, 'status': 'NEEDS_REVIEW', 'warnings': ['network timeout']},
            ]}
            (Path(out) / 'report.json').write_text(json.dumps(report), encoding='utf-8')
            snapshot = t.progress_snapshot(out)
            self.assertTrue(snapshot['ok'])
            self.assertEqual(snapshot['source'], 'report.json')
            self.assertEqual(snapshot['total'], 2)
            self.assertEqual(snapshot['valid_pdf'], 1)
            self.assertEqual(snapshot['saved_local'], 1)
            self.assertEqual(snapshot['review'], 1)
            self.assertIn('network timeout', t.format_progress(snapshot))
            self.assertIn('Source: report.json', t.format_progress(snapshot))

    def test_progress_prefers_manifest_over_report(self):
        import json
        with tempfile.TemporaryDirectory() as out:
            (Path(out) / 'manifest.json').write_text(json.dumps([
                {'number': 1, 'title': 'Batch row', 'status': 'PDF_ATTACHED'}]), encoding='utf-8')
            (Path(out) / 'report.json').write_text(json.dumps({'results': [
                {'status': 'PDF_SAVED'}]}), encoding='utf-8')
            snapshot = t.progress_snapshot(out)
            self.assertEqual(snapshot['source'], 'manifest.json')
            self.assertEqual(snapshot['total'], 1)

    def test_progress_without_any_checkpoint_names_both_files(self):
        with tempfile.TemporaryDirectory() as out:
            snapshot = t.progress_snapshot(out)
            self.assertFalse(snapshot['ok'])
            self.assertIn('report.json', snapshot['error'])

class FlowFixTests(unittest.TestCase):
    def args(self, out):
        return argparse.Namespace(command='fetch',out=out,oa_only=False,zotero=False,
                                  proxy='http://127.0.0.1:1081',cdp='http://127.0.0.1:18806')

    def test_browser_output_path_skips_stale_file(self):
        with tempfile.TemporaryDirectory() as out:
            stale = Path(out)/'paper-browser.pdf'; stale.write_bytes(b'%PDF-stale')
            with patch.object(t.core,'verify_pdf',return_value=(False,'identity mismatch')):
                target, reused, notes = t.browser_output_path(stale,{})
            self.assertEqual(target.name,'paper-browser-2.pdf')
            self.assertFalse(reused)
            self.assertTrue(any('failed identity check' in n for n in notes))
            self.assertEqual(stale.read_bytes(),b'%PDF-stale')
            self.assertFalse(target.exists())

    def test_browser_output_path_reuses_verified_file(self):
        with tempfile.TemporaryDirectory() as out:
            kept = Path(out)/'paper.pdf'; kept.write_bytes(b'%PDF-kept')
            with patch.object(t.core,'verify_pdf',return_value=(True,'title match')):
                target, reused, notes = t.browser_output_path(kept,{})
            self.assertEqual(target,kept)
            self.assertTrue(reused)
            self.assertEqual(notes,[])

    def test_browser_route_recovers_from_stale_file(self):
        import re
        record=dict(t.core.SAMPLE_RECORD,link=[{'URL':'https://api.elsevier.com/content/article/PII:S0020025526007310'}])
        with tempfile.TemporaryDirectory() as out:
            paper=t.core.paper_from_crossref(t.core.SAMPLE_RECORD)
            stem=re.sub(r'[^A-Za-z0-9_.-]','_',paper['doi']).strip('._')
            dest=Path(out)/(stem+'.pdf'); dest.write_bytes(b'%PDF-old-dest')
            stale=Path(out)/(stem+'-browser.pdf'); stale.write_bytes(b'%PDF-stale')
            def verify(p,_paper):
                return (True,'ok') if p.name.endswith('-2.pdf') else (False,'identity mismatch')
            def browser(cmd,**kwargs):
                Path(cmd[cmd.index('--out')+1]).write_bytes(b'%PDF-new')
                return argparse.Namespace(returncode=0,stderr='')
            with patch.object(t.core,'crossref_metadata',return_value=(record,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(None,None,[])),patch.object(t.core,'verify_pdf',side_effect=verify),patch.object(t.subprocess,'run',side_effect=browser):
                result=t.run_reference('test',self.args(out))
            self.assertEqual(result['status'],'PDF_SAVED')
            self.assertTrue(result['pdf'].endswith(stem+'-browser-2.pdf'))
            self.assertEqual(stale.read_bytes(),b'%PDF-stale')
            self.assertEqual(dest.read_bytes(),b'%PDF-old-dest')
            self.assertTrue(any('failed identity check' in w for w in result['warnings']))

    def test_existing_attachment_marks_present_and_skips_upload(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as out:
            args=self.args(out);args.zotero=True;args.zotero_base='http://127.0.0.1:23119/api';args.collection='Test'
            pdf=Path(out)/'paper.pdf';pdf.write_bytes(b'%PDF-fixture')
            z=MagicMock();z.ensure_pdf.return_value={'status':'PDF_ALREADY_PRESENT','attachment_key':'ATT'};z.ensure_item.return_value=('K',False)
            with patch.object(t.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(t.core,'pdf_candidates',return_value=[]),patch.object(t.core,'download_verified',return_value=(pdf,{'source':'fixture'},[])),patch.object(t.core,'choose_collection',return_value=({'key':'K','path':'Test'},1)),patch.object(t.core,'ZoteroLocal',return_value=z):
                result=t.run_reference('test',args)
            self.assertEqual(result['status'],'PDF_ALREADY_PRESENT')
            self.assertEqual(result['zotero_key'],'K')
            z.upload_pdf.assert_not_called()

    def test_already_present_is_success_but_pending_still_fails(self):
        import json
        for status,code in (('PDF_ALREADY_PRESENT',0),('PDF_PENDING',2)):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as out:
                with patch.object(t,'run_reference',return_value={'status':status}):
                    self.assertEqual(t.main(['fetch','10.test/x','--out',out]),code)
                rows=json.loads((Path(out)/'report.json').read_text(encoding='utf-8'))['results']
                self.assertEqual(rows[0]['status'],status)

    def test_merge_report_exposes_latest_failure(self):
        old={'paper':{'doi':'d1'},'status':'PDF_ATTACHED','attachment_key':'A','warnings':[]}
        new={'paper':{'doi':'d1'},'status':'NEEDS_REVIEW','error':'OSError'}
        rows=t.merge_report([old],[new])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'NEEDS_REVIEW')
        self.assertEqual(rows[0]['previous_status'],'PDF_ATTACHED')
        self.assertEqual(old['warnings'],[])

    def test_merge_report_new_success_overrides_pending(self):
        rows=t.merge_report([{'paper':{'doi':'d1'},'status':'PDF_PENDING'}],
                            [{'paper':{'doi':'d1'},'status':'PDF_ATTACHED'}])
        self.assertEqual(rows[0]['status'],'PDF_ATTACHED')

    def test_progress_unknown_status_is_visible(self):
        import json
        with tempfile.TemporaryDirectory() as out:
            pdf=Path(out)/'saved.pdf';pdf.write_bytes(b'%PDF-fixture')
            report={'results':[
                {'paper':{'title':'Already attached'},'status':'PDF_ALREADY_PRESENT','pdf':str(pdf)},
                {'paper':{'title':'Preview row'},'status':'PREVIEW'},
                {'paper':{'title':'Metadata row'},'status':'题录待核验'},
            ]}
            (Path(out)/'report.json').write_text(json.dumps(report),encoding='utf-8')
            snapshot=t.progress_snapshot(out)
            self.assertEqual(snapshot['attached'],1)
            self.assertEqual(snapshot['other'],2)
            self.assertEqual(snapshot['review'],2)
            self.assertIn('PREVIEW',[i['status'] for i in snapshot['issues']])
            self.assertIn('other: 2',t.format_progress(snapshot))

    def test_doctor_note_clarifies_zotero_port(self):
        from unittest.mock import MagicMock
        with patch.object(t.socket,'create_connection',return_value=MagicMock()):
            result=t.doctor('direct')
        self.assertTrue(result['ok'])
        self.assertIn('not part of ok',result['note'])

    def recover_fixture(self,out):
        import json
        import re
        from examples import recover_local_pdfs as rec
        manifest=Path(out)/'manifest.json'
        pdfdir=Path(out)/'PDF';pdfdir.mkdir()
        doi='10.1000/abc'
        stem=re.sub(r'[^A-Za-z0-9_.-]','_',doi).strip('._')
        pdf=pdfdir/(stem+'.pdf');pdf.write_bytes(b'%PDF-fixture')
        manifest.write_text(json.dumps([{'number':7,'doi':doi,'pdf':'','status':'PDF_PENDING'}]),encoding='utf-8')
        return rec,manifest,pdf

    def test_recover_local_pdfs_skips_existing_attachment(self):
        import json
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as out:
            rec,manifest,pdf=self.recover_fixture(out)
            z=MagicMock();z.collections.return_value=[{'key':'K','path':rec.os.environ.get('PAPER_COLLECTION','My Library/Papers')}]
            z.ensure_pdf.return_value={'status':'PDF_ALREADY_PRESENT','attachment_key':'ATT'};z.ensure_item.return_value=('K',False)
            with patch.object(rec,'MANIFEST',manifest),patch.object(rec,'PDF_DIR',pdf.parent),patch.object(rec.core,'ZoteroLocal',return_value=z),patch.object(rec.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(rec.core,'verify_pdf',return_value=(True,'fixture')),patch('builtins.print'):
                rec.main()
            z.upload_pdf.assert_not_called()
            row=json.loads(manifest.read_text(encoding='utf-8'))[0]
            self.assertEqual(row['status'],'PDF_ALREADY_PRESENT')
            self.assertTrue(row['pdf'])
            z.ensure_pdf.assert_called_once()

    def test_recover_local_pdfs_uploads_when_attachment_missing(self):
        import json
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as out:
            rec,manifest,pdf=self.recover_fixture(out)
            z=MagicMock();z.collections.return_value=[{'key':'K','path':rec.os.environ.get('PAPER_COLLECTION','My Library/Papers')}]
            z.ensure_pdf.return_value={'status':'PDF_ATTACHED','attachment_key':'ATT'};z.ensure_item.return_value=('K',False)
            with patch.object(rec,'MANIFEST',manifest),patch.object(rec,'PDF_DIR',pdf.parent),patch.object(rec.core,'ZoteroLocal',return_value=z),patch.object(rec.core,'crossref_metadata',return_value=(t.core.SAMPLE_RECORD,1)),patch.object(rec.core,'verify_pdf',return_value=(True,'fixture')),patch('builtins.print'):
                rec.main()
            z.ensure_pdf.assert_called_once()
            row=json.loads(manifest.read_text(encoding='utf-8'))[0]
            self.assertEqual(row['attachment_key'],'ATT')
            self.assertEqual(row['warnings'],'')

    def test_read_references_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as ctx:
                t.read_references(Path(d)/'absent.txt')
            self.assertIn('not found',str(ctx.exception))

    def test_read_references_skips_comments_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'refs.txt'
            f.write_bytes(('# 临时停用这一篇\n\n10.1016/j.cie.2025.111463\n  \n10.1016/j.cie.2025.111463\n').encode('utf-8'))
            self.assertEqual(t.read_references(f),['10.1016/j.cie.2025.111463'])

    def test_read_references_falls_back_to_gbk(self):
        import contextlib,io
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'refs.txt'
            f.write_bytes('# 中文注释\n10.1016/j.cie.2025.111463\n'.encode('gbk'))
            err=io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(t.read_references(f),['10.1016/j.cie.2025.111463'])
            self.assertIn('not UTF-8',err.getvalue())

    def test_main_rejects_empty_reference_list(self):
        import contextlib,io
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'refs.txt';f.write_text('# nothing here\n',encoding='utf-8')
            err=io.StringIO()
            with contextlib.redirect_stderr(err),self.assertRaises(SystemExit) as ctx:
                t.main(['preview','--input',str(f)])
            self.assertEqual(ctx.exception.code,2)
            self.assertIn('No references found',err.getvalue())

    def test_main_rejects_blank_reference(self):
        import contextlib,io
        err=io.StringIO()
        with contextlib.redirect_stderr(err),self.assertRaises(SystemExit) as ctx:
            t.main(['preview','   '])
        self.assertEqual(ctx.exception.code,2)
        self.assertIn('cannot be empty',err.getvalue())

    def test_collections_lists_paths_read_only(self):
        from unittest.mock import MagicMock
        fake=MagicMock()
        fake.collections.return_value=[{'key':'K2','name':'B','path':'A/B'},{'key':'K1','name':'A','path':'A'}]
        with patch.object(t.core,'ZoteroLocal',return_value=fake),patch('builtins.print') as printed:
            self.assertEqual(t.main(['collections']),0)
        self.assertEqual([c.args[0] for c in printed.call_args_list],['A\tK1','A/B\tK2'])
        fake.ensure_item.assert_not_called();fake.upload_pdf.assert_not_called()

    def health_fixture(self, children, files):
        from unittest.mock import MagicMock
        import re as _re
        z=MagicMock();z.base='http://127.0.0.1:23119/api';z.children.return_value=children
        def fake_request(_method,url,**kwargs):
            key=_re.search(r'/items/([^/]+)/file/view/url',url).group(1)
            return (200,{},files[key].encode(),'')
        return z,fake_request

    def test_attachment_health_states(self):
        with tempfile.TemporaryDirectory() as d:
            from pypdf import PdfWriter
            good=Path(d)/'a.pdf'
            writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(good)
            ghost=Path(d)/'ghost.pdf'
            pdf=lambda key,name:{'key':key,'itemType':'attachment','contentType':'application/pdf','filename':name}
            cases=[([],{},'NO_ATTACHMENT'),
                   ([pdf('A','a.pdf')],{'A':good.as_uri()},'OK'),
                   ([pdf('B','b.pdf')],{'B':ghost.as_uri()},'UNVERIFIED'),
                   ([pdf('A','a.pdf'),pdf('A2','a2.pdf')],{'A':good.as_uri(),'A2':good.as_uri()},'DUPLICATE')]
            for children,files,expected in cases:
                z,fake=self.health_fixture(children,files)
                with patch.object(t.core,'request_bytes',side_effect=fake):
                    self.assertEqual(t.core.attachment_health(z,'PARENT')['state'],expected)

    def test_audit_flags_missing_file(self):
        import json
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'report.json').write_text(json.dumps({'results':[{'zotero_key':'K','paper':{'doi':'10.1/x','title':'T'}}]}),encoding='utf-8')
            with patch.object(t.core,'ZoteroLocal',return_value=MagicMock()),patch.object(t.core,'attachment_health',return_value={'state':'MISSING_FILE','pdf_attachments':[]}),patch('builtins.print') as printed:
                self.assertEqual(t.main(['audit','--out',d]),2)
            self.assertIn('MISSING_FILE',printed.call_args_list[-1].args[0])

    def test_audit_returns_zero_when_healthy(self):
        import json
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'report.json').write_text(json.dumps({'results':[{'zotero_key':'K','paper':{'doi':'10.1/x','title':'T'}}]}),encoding='utf-8')
            with patch.object(t.core,'ZoteroLocal',return_value=MagicMock()),patch.object(t.core,'attachment_health',return_value={'state':'OK','pdf_attachments':[]}),patch('builtins.print'):
                self.assertEqual(t.main(['audit','--out',d]),0)

    def test_failures_lists_and_writes_input(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'ok.pdf';pdf.write_bytes(b'%PDF-1.4')
            rows=[{'input':'A','paper':{'doi':'10.1/a'},'status':'PDF_ATTACHED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)},
                  {'input':'B','paper':{'doi':'10.1/b'},'status':'PDF_PENDING','pdf':''},
                  {'input':'C','paper':{'doi':'10.1/c'},'status':'PDF_SAVED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)}]
            (Path(d)/'manifest.json').write_text(json.dumps(rows),encoding='utf-8')
            target=Path(d)/'pending.txt'
            with patch('builtins.print'):
                self.assertEqual(t.main(['failures','--out',d,'--write',str(target)]),0)
            self.assertEqual(target.read_text(encoding='utf-8').split(),['10.1/b'])

    def test_failures_reports_nothing_pending(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'ok.pdf';pdf.write_bytes(b'%PDF-1.4')
            (Path(d)/'manifest.json').write_text(json.dumps([{'input':'A','paper':{'doi':'10.1/a'},'status':'PDF_ATTACHED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)}]),encoding='utf-8')
            with patch('builtins.print') as printed:
                self.assertEqual(t.main(['failures','--out',d]),0)
            self.assertTrue(any('Nothing pending' in str(c.args[0]) for c in printed.call_args_list if c.args))

    def fetch_report_fixture(self, folder, doi, pdf):
        import json
        (Path(folder)/'report.json').write_text(json.dumps({'results':[{'input':doi,'paper':{'doi':doi},'status':'PDF_ATTACHED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)}]}),encoding='utf-8')

    def test_skip_done_only_retries_unfinished(self):
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'a.pdf';pdf.write_bytes(b'%PDF-1.4')
            self.fetch_report_fixture(d,'10.1000/a',pdf)
            refs=Path(d)/'refs.txt';refs.write_text('10.1000/a\n10.1000/other\n',encoding='utf-8')
            with patch.object(t,'run_reference',side_effect=lambda ref,args:{'status':'PDF_SAVED','warnings':[]}) as run,patch('builtins.print'):
                self.assertEqual(t.main(['fetch','--input',str(refs),'--skip-done','--interval','0','--out',d]),0)
            self.assertEqual([c.args[0] for c in run.call_args_list],['10.1000/other'])

    def test_skip_done_all_completed_does_no_work(self):
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'a.pdf';pdf.write_bytes(b'%PDF-1.4')
            self.fetch_report_fixture(d,'10.1000/a',pdf)
            refs=Path(d)/'refs.txt';refs.write_text('10.1000/a\n',encoding='utf-8')
            with patch.object(t,'run_reference') as run,patch('builtins.print'):
                self.assertEqual(t.main(['fetch','--input',str(refs),'--skip-done','--interval','0','--out',d]),0)
            run.assert_not_called()

    def test_skip_done_rejected_for_preview(self):
        import contextlib,io
        with tempfile.TemporaryDirectory() as d:
            refs=Path(d)/'refs.txt';refs.write_text('10.1000/a\n',encoding='utf-8')
            err=io.StringIO()
            with contextlib.redirect_stderr(err),self.assertRaises(SystemExit) as ctx:
                t.main(['preview','--input',str(refs),'--skip-done','--interval','0','--out',d])
            self.assertEqual(ctx.exception.code,2)
            self.assertIn('only applies to fetch',err.getvalue())

    def test_skip_done_skips_verified_download_without_zotero(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'a.pdf';pdf.write_bytes(b'%PDF-1.4')
            (Path(d)/'report.json').write_text(json.dumps({'results':[
                {'input':'10.1000/a','paper':{'doi':'10.1000/a'},'status':'PDF_SAVED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)}]}),encoding='utf-8')
            refs=Path(d)/'refs.txt';refs.write_text('10.1000/a\n',encoding='utf-8')
            with patch.object(t,'run_reference',side_effect=lambda ref,args:{'status':'PDF_SAVED','warnings':[]}) as run,patch('builtins.print'):
                self.assertEqual(t.main(['fetch','--input',str(refs),'--skip-done','--interval','0','--out',d]),0)
            run.assert_not_called()

    def test_skip_done_rechecks_legacy_rows_without_status(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'a.pdf';pdf.write_bytes(b'%PDF-1.4')
            (Path(d)/'report.json').write_text(json.dumps({'results':[
                {'input':'10.1000/a','paper':{'doi':'10.1000/a'},'pdf':str(pdf)}]}),encoding='utf-8')
            refs=Path(d)/'refs.txt';refs.write_text('10.1000/a\n',encoding='utf-8')
            with patch.object(t,'run_reference', return_value={'status':'PDF_PENDING'}) as run,patch('builtins.print'):
                self.assertEqual(t.main(['fetch','--input',str(refs),'--skip-done','--interval','0','--out',d]),2)
            run.assert_called_once()

    def test_failures_and_skip_done_agree_on_pending(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'a.pdf';pdf.write_bytes(b'%PDF-1.4')
            (Path(d)/'report.json').write_text(json.dumps({'results':[
                {'input':'10.1000/a','paper':{'doi':'10.1000/a'},'status':'PDF_SAVED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)},
                {'input':'10.1000/b','paper':{'doi':'10.1000/b'},'status':'PDF_ATTACHED','pdf':str(pdf),'sha256':t.core.pdf_sha256(pdf)}]}),encoding='utf-8')
            target=Path(d)/'pending.txt'
            with patch('builtins.print'):
                self.assertEqual(t.main(['failures','--out',d,'--write',str(target)]),0)
            listed=target.read_text(encoding='utf-8').split()
            refs=Path(d)/'refs.txt';refs.write_text('10.1000/a\n10.1000/b\n',encoding='utf-8')
            with patch.object(t,'run_reference',side_effect=lambda ref,args:{'status':'PDF_SAVED','warnings':[]}) as run,patch('builtins.print'):
                self.assertEqual(t.main(['fetch','--input',str(refs),'--skip-done','--interval','0','--out',d]),0)
            self.assertEqual(sorted(listed),sorted(c.args[0] for c in run.call_args_list))
            self.assertEqual(listed,[])

class BatchTests(unittest.TestCase):
    """The batch engine must work for any list size and never lose a row."""

    def manifest(self, out):
        import json
        return json.loads((Path(out) / 'manifest.json').read_text(encoding='utf-8'))

    def local_pdf(self, out, doi='10.1000/local'):
        folder = Path(out) / 'PDF'; folder.mkdir(parents=True, exist_ok=True)
        stem = doi.replace('/', '_')
        pdf = folder / (stem + '.pdf'); pdf.write_bytes(b'%PDF-1.4 fixture')
        return pdf

    def record(self, doi='10.1000/local'):
        return dict(t.core.SAMPLE_RECORD, DOI=doi, title=['Fixture paper about control'])

    def test_good_status_matches_main_entry(self):
        self.assertEqual(t.batch_runner.GOOD_STATUS, t.GOOD_STATUS)

    def test_dry_run_plans_without_writing(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            summary = b.run_batch(['10.1016/x1', '10.1002/x2'], out, dry_run=True,
                                  runner=lambda ref, args: self.fail('dry run must not download'))
            self.assertFalse((out / 'manifest.json').exists())
            self.assertFalse(out.exists())
            self.assertTrue(summary['dry_run'])
            self.assertEqual([row['action'] for row in summary['rows']], ['download', 'download'])
            self.assertIn('browser', summary['rows'][0]['route_estimate'])

    def test_checkpoint_is_created_from_the_list(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            def runner(ref, args):
                pdf = Path(args.out) / (ref.replace('/', '_') + '.pdf')
                pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': ref}, 'warnings': []}
            summary = b.run_batch(['10.1/a', '10.1/b', '10.1/c'], out, runner=runner, interval=0)
            rows = self.manifest(out)
            self.assertEqual([row['number'] for row in rows], [1, 2, 3])
            self.assertEqual([row['input'] for row in rows], ['10.1/a', '10.1/b', '10.1/c'])
            self.assertTrue(summary['ok'])
            self.assertEqual(summary['attached'], 3)

    def test_rerun_skips_confirmed_rows(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            calls = []
            def runner(ref, args):
                calls.append(ref)
                pdf = Path(args.out) / 'done.pdf'
                pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': ref}, 'warnings': []}
            b.run_batch(['10.1/a'], out, runner=runner, interval=0)
            summary = b.run_batch(['10.1/a'], out, runner=runner, interval=0)
            self.assertEqual(calls, ['10.1/a'])
            self.assertEqual(summary['skipped'], 1)
            self.assertTrue(summary['ok'])

    def test_failure_keeps_completed_rows_and_retries_only_that_row(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            def runner(ref, args):
                if ref == '10.1/bad':
                    raise t.core.PaperError('network down')
                pdf = Path(args.out) / 'good.pdf'
                pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': ref}, 'warnings': []}
            summary = b.run_batch(['10.1/good', '10.1/bad'], out, runner=runner, interval=0)
            self.assertFalse(summary['ok'])
            rows = {row['input']: row for row in self.manifest(out)}
            self.assertEqual(rows['10.1/good']['status'], 'PDF_ATTACHED')
            self.assertEqual(rows['10.1/bad']['status'], 'NEEDS_REVIEW')
            self.assertEqual(rows['10.1/bad']['attempts'], 1)
            b.run_batch(['10.1/good', '10.1/bad'], out, runner=runner, interval=0)
            rows = {row['input']: row for row in self.manifest(out)}
            self.assertEqual(rows['10.1/bad']['attempts'], 2)
            self.assertEqual(rows['10.1/good']['attempts'], 1)

    def test_duplicate_references_run_once(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            calls = []
            def runner(ref, args):
                calls.append(ref)
                pdf = Path(args.out) / 'a.pdf'
                pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': ref}, 'warnings': []}
            summary = b.run_batch(['10.1/a', ' 10.1/a ', '10.1/b'], out, runner=runner, interval=0)
            self.assertEqual(calls, ['10.1/a', '10.1/b'])
            self.assertEqual(summary['total'], 2)
            self.assertEqual(len(self.manifest(out)), 2)

    def test_offline_recovery_uses_the_checkpoint_identity(self):
        import json
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            self.local_pdf(out)
            (out / 'manifest.json').write_text(json.dumps([
                {'number': 1, 'input': '10.1000/local', 'doi': '10.1000/local',
                 'title': 'Fixture paper about control', 'status': 'PDF_PENDING', 'pdf': ''}]),
                encoding='utf-8')
            with patch.object(t.core, 'crossref_metadata', side_effect=t.core.PaperError('offline')), \
                 patch.object(t.core, 'verify_pdf', return_value=(True, 'title match')):
                summary = b.run_batch(['10.1000/local'], out, interval=0,
                                      runner=lambda ref, args: self.fail('must not download'))
            row = self.manifest(out)[0]
            self.assertEqual(row['status'], 'PDF_SAVED')
            self.assertEqual(row['source'], 'local_file')
            self.assertTrue(summary['ok'])

    def test_offline_recovery_still_requires_identity(self):
        import json
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            self.local_pdf(out)
            (out / 'manifest.json').write_text(json.dumps([
                {'number': 1, 'input': '10.1000/local', 'doi': '10.1000/local',
                 'title': 'Fixture paper about control', 'status': 'PDF_PENDING', 'pdf': ''}]),
                encoding='utf-8')
            with patch.object(t.core, 'verify_pdf', return_value=(False, 'identity unclear')):
                summary = b.run_batch(['10.1000/local'], out, interval=0,
                                      runner=lambda ref, args: {'status': 'PDF_PENDING', 'warnings': ['offline']})
            row = self.manifest(out)[0]
            self.assertEqual(row['status'], 'PDF_PENDING')
            self.assertFalse(summary['ok'])

    def test_legacy_checkpoint_is_refused_instead_of_duplicated(self):
        import json
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'; out.mkdir(parents=True)
            (out / 'manifest.json').write_text(json.dumps(
                [{'number': 1, 'reference': '10.1/a', 'status': 'PDF_ATTACHED'}]), encoding='utf-8')
            with self.assertRaises(ValueError) as ctx:
                b.run_batch(['10.1/a'], out, dry_run=True)
            self.assertIn('new --out', str(ctx.exception))

    def test_rows_outside_the_list_are_preserved(self):
        import json
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'; out.mkdir(parents=True)
            (out / 'manifest.json').write_text(json.dumps(
                [{'number': 9, 'input': '10.1/old', 'status': 'PDF_PENDING'}]), encoding='utf-8')
            b.run_batch(['10.1/new'], out, dry_run=True)
            rows = self.manifest(out)
            self.assertEqual(self.manifest(out), [{'number': 9, 'input': '10.1/old', 'status': 'PDF_PENDING'}])
            b.run_batch(['10.1/new'], out, runner=lambda ref, args: {'status': 'PDF_PENDING', 'warnings': ['x']}, interval=0)
            rows = self.manifest(out)
            self.assertEqual([row['input'] for row in rows], ['10.1/old', '10.1/new'])
            self.assertEqual(rows[1]['number'], 10)

    def test_local_verified_pdf_is_reused_without_downloading(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            pdf = self.local_pdf(out)
            with patch.object(t.core, 'crossref_metadata', return_value=(self.record(), 1)), \
                 patch.object(t.core, 'verify_pdf', return_value=(True, 'title match')):
                summary = b.run_batch(['10.1000/local'], out, interval=0,
                                      runner=lambda ref, args: self.fail('must reuse the local PDF'))
            row = self.manifest(out)[0]
            self.assertEqual(row['status'], 'PDF_SAVED')
            self.assertEqual(row['pdf'], str(pdf))
            self.assertEqual(row['source'], 'local_file')
            self.assertTrue(summary['ok'])

    def test_local_recovery_does_not_upload_a_second_attachment(self):
        from paper_tool import batch as b
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            pdf = self.local_pdf(out)
            zotero = MagicMock(server_id='test-instance'); zotero.server_id = 'test-instance'
            zotero.collections.return_value = [{'key': 'C', 'name': 'B', 'path': 'A/B'}]
            zotero.ensure_pdf.return_value = {'status': 'PDF_ALREADY_PRESENT', 'attachment_key': 'ATT'}
            zotero.ensure_item.return_value = ('KEY', False)
            with patch.object(t.core, 'crossref_metadata', return_value=(self.record(), 1)), \
                 patch.object(t.core, 'verify_pdf', return_value=(True, 'title match')), \
                 patch.object(t.core, 'choose_collection', return_value=({'key': 'C', 'path': 'A/B'}, 1)), \
                 patch.object(t.core, 'ZoteroLocal', return_value=zotero):
                summary = b.run_batch(['10.1000/local'], out, zotero=True, collection='A/B', interval=0)
            zotero.upload_pdf.assert_not_called()
            row = self.manifest(out)[0]
            self.assertEqual(row['status'], 'PDF_ALREADY_PRESENT')
            zotero.ensure_pdf.assert_called_once()
            self.assertTrue(summary['ok'])

    def test_local_recovery_uploads_once_when_attachment_missing(self):
        from paper_tool import batch as b
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            self.local_pdf(out)
            zotero = MagicMock(server_id='test-instance'); zotero.server_id = 'test-instance'
            zotero.collections.return_value = [{'key': 'C', 'name': 'B', 'path': 'A/B'}]
            zotero.ensure_pdf.return_value = {'status': 'PDF_ATTACHED', 'attachment_key': 'ATT'}
            zotero.ensure_item.return_value = ('KEY', False)
            zotero.upload_pdf.return_value = 'ATT'
            with patch.object(t.core, 'crossref_metadata', return_value=(self.record(), 1)), \
                 patch.object(t.core, 'verify_pdf', return_value=(True, 'title match')), \
                 patch.object(t.core, 'choose_collection', return_value=({'key': 'C', 'path': 'A/B'}, 1)), \
                 patch.object(t.core, 'ZoteroLocal', return_value=zotero):
                b.run_batch(['10.1000/local'], out, zotero=True, collection='A/B', interval=0)
            zotero.ensure_pdf.assert_called_once()
            row = self.manifest(out)[0]
            self.assertEqual(row['status'], 'PDF_ATTACHED')
            self.assertEqual(row['attachment_key'], 'ATT')

    def test_rejected_local_pdf_is_kept_and_download_still_runs(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            stale = self.local_pdf(out)
            def runner(ref, args):
                pdf = Path(args.out) / 'fresh.pdf'; pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_SAVED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': 'T'}, 'warnings': []}
            with patch.object(t.core, 'crossref_metadata', return_value=(self.record(), 1)), \
                 patch.object(t.core, 'verify_pdf', return_value=(False, 'identity unclear')):
                b.run_batch(['10.1000/local'], out, runner=runner, interval=0)
            self.assertTrue(stale.is_file())
            row = self.manifest(out)[0]
            self.assertEqual(row['status'], 'PDF_SAVED')
            self.assertTrue(any('not reused' in note for note in row['warnings']))

    def test_unknown_collection_stops_before_any_write(self):
        from paper_tool import batch as b
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            zotero = MagicMock(server_id='test-instance'); zotero.collections.return_value = []
            with patch.object(t.core, 'ZoteroLocal', return_value=zotero):
                with self.assertRaises(ValueError) as ctx:
                    b.run_batch(['10.1/a'], out, zotero=True, collection='Nope', interval=0,
                                runner=lambda ref, args: self.fail('must not run'))
            self.assertIn('collections', str(ctx.exception))
            self.assertFalse((out / 'manifest.json').exists())

    def test_force_reruns_confirmed_rows(self):
        from paper_tool import batch as b
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            calls = []
            def runner(ref, args):
                calls.append(ref)
                pdf = Path(args.out) / 'again.pdf'
                pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': ref}, 'warnings': []}
            b.run_batch(['10.1/a'], out, runner=runner, interval=0)
            b.run_batch(['10.1/a'], out, runner=runner, interval=0, force=True)
            self.assertEqual(calls, ['10.1/a', '10.1/a'])

    def test_interval_only_between_papers_that_used_the_network(self):
        from paper_tool import batch as b
        from unittest.mock import MagicMock
        sleep = MagicMock()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            def runner(ref, args):
                pdf = Path(args.out) / (ref.replace('/', '_') + '.pdf')
                pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b'%PDF-1.4')
                return {'status': 'PDF_SAVED', 'pdf': str(pdf), 'paper': {'doi': ref, 'title': ref}, 'warnings': []}
            b.run_batch(['10.1/a', '10.1/b', '10.1/c'], out, runner=runner, interval=30, sleeper=sleep)
            self.assertEqual(sleep.call_count, 2)

    def test_cli_dry_run_exits_zero_without_side_effects(self):
        import contextlib, io, json
        with tempfile.TemporaryDirectory() as d:
            refs = Path(d) / 'refs.txt'; refs.write_text('# note\n10.1/a\n\n10.1/b\n', encoding='utf-8')
            out = Path(d) / 'batch'
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
                code = t.main(['batch', '--input', str(refs), '--out', str(out), '--dry-run'])
            self.assertEqual(code, 0)
            lines = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
            self.assertEqual([line['input'] for line in lines[:2]], ['10.1/a', '10.1/b'])
            self.assertTrue(lines[-1]['dry_run'])
            self.assertFalse(out.exists())

    def test_cli_rejects_empty_list(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as d:
            refs = Path(d) / 'refs.txt'; refs.write_text('# nothing\n', encoding='utf-8')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = t.main(['batch', '--input', str(refs), '--out', str(Path(d) / 'b')])
            self.assertEqual(code, 2)
            self.assertIn('No references found', err.getvalue())

    def test_cli_requires_input(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                t.main(['batch', '--out', str(Path(d) / 'b')])
            self.assertEqual(ctx.exception.code, 2)


class BrowserTests(unittest.TestCase):
    def response(self, payload):
        from unittest.mock import MagicMock
        handle = MagicMock()
        handle.__enter__ = lambda self: handle
        handle.__exit__ = lambda *args: False
        handle.read.return_value = payload
        return handle

    def test_missing_listener_is_reported_as_such(self):
        from urllib.error import URLError
        with patch.object(t, 'build_opener', side_effect=URLError(ConnectionRefusedError(10061, 'refused'))):
            result = t.cdp_status()
        self.assertFalse(result['ok'])
        self.assertIn('nothing is listening', result['reason'])

    def test_foreign_service_on_the_port_is_not_mistaken_for_chrome(self):
        from urllib.error import HTTPError
        error = HTTPError('http://127.0.0.1:18806/json/version', 502, 'Bad Gateway', {}, None)
        with patch.object(t, 'build_opener', side_effect=error):
            result = t.cdp_status()
        self.assertFalse(result['ok'])
        self.assertIn('not a Chrome debugging endpoint', result['reason'])

    def test_running_browser_is_detected(self):
        from unittest.mock import MagicMock
        opener = MagicMock()
        opener.open.return_value = self.response(b'{"Browser":"Chrome/120","webSocketDebuggerUrl":"ws://x"}')
        with patch.object(t, 'build_opener', return_value=opener):
            result = t.cdp_status()
        self.assertTrue(result['ok'])
        self.assertEqual(result['browser'], 'Chrome/120')

    def test_loopback_check_bypasses_system_proxy(self):
        from unittest.mock import MagicMock
        opener = MagicMock()
        opener.open.return_value = self.response(b'{"Browser":"Chrome/120"}')
        with patch.object(t, 'ProxyHandler') as handler, patch.object(t, 'build_opener', return_value=opener):
            t.cdp_status()
        handler.assert_called_once_with({})

    def test_start_reuses_a_listening_browser(self):
        with patch.object(t, 'cdp_status', return_value={'ok': True, 'cdp': 'x', 'browser': 'Chrome'}), \
             patch.object(t.subprocess, 'Popen') as popen:
            result = t.start_browser('profile')
        self.assertTrue(result['ok'])
        self.assertFalse(result['started'])
        popen.assert_not_called()

    def test_start_without_a_browser_reports_how_to_fix_it(self):
        with patch.object(t, 'cdp_status', return_value={'ok': False}), \
             patch.object(t, 'chrome_candidates', return_value=[]):
            result = t.start_browser('profile', timeout=1)
        self.assertFalse(result['ok'])
        self.assertIn('--chrome', result['error'])

    def test_start_waits_for_the_debugging_port(self):
        from unittest.mock import MagicMock
        states = [{'ok': False}, {'ok': True, 'cdp': 'x', 'browser': 'Chrome'}]
        with tempfile.TemporaryDirectory() as d, \
             patch.object(t, 'cdp_status', side_effect=states), \
             patch.object(t, 'chrome_candidates', return_value=[Path(d) / 'chrome.exe']), \
             patch.object(t.subprocess, 'Popen', return_value=MagicMock(pid=7)), \
             patch.object(t.time, 'sleep'):
            (Path(d) / 'chrome.exe').write_bytes(b'')
            result = t.start_browser(Path(d) / 'profile', timeout=5)
        self.assertTrue(result['started'])
        self.assertEqual(result['pid'], 7)

    def test_deep_doctor_keeps_ok_semantics(self):
        from unittest.mock import MagicMock
        with patch.object(t.socket, 'create_connection', return_value=MagicMock()), \
             patch.object(t, 'deep_checks', return_value={'node': 'node'}):
            result = t.doctor('direct', deep=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['deep'], {'node': 'node'})
        self.assertEqual(result['required'], ['browser_cdp'])


if __name__=='__main__':unittest.main()
