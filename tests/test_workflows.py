"""Regression coverage for independent downloads, resume and safe archival."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from paper_tool import batch as b
from paper_tool import cli as t
from paper_tool import core


def make_pdf(path, title='A verified paper about oxygen supply networks'):
    """Real PDF with extractable text; no optional reportlab dependency."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 10 Tf 20 700 Td ({title}) Tj ET'.encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)
    return path


def record():
    return dict(core.SAMPLE_RECORD, DOI='10.1000/workflow',
                title=['A verified paper about oxygen supply networks'])


def args(out, **kwargs):
    values = dict(command='fetch', out=str(out), oa_only=False, zotero=False,
                  collection='A/B', zotero_base=core.BASE, proxy='direct', cdp=t.CDP_DEFAULT)
    values.update(kwargs)
    return argparse.Namespace(**values)


class DownloadTests(unittest.TestCase):
    def test_cli_download_verify_report_and_resume_without_zotero(self):
        class Response(io.BytesIO):
            def geturl(self):
                return 'https://repository.example.edu/paper.pdf'
        with tempfile.TemporaryDirectory() as folder:
            payload = make_pdf(Path(folder) / 'seed.pdf').read_bytes()
            out = Path(folder) / 'download'
            opener = MagicMock()
            opener.open.side_effect = lambda *a, **kw: Response(payload)
            with patch.object(core, 'crossref_metadata', return_value=(record(), 1)) as metadata, \
                 patch.object(core, 'pdf_candidates', return_value=[{'url': 'https://repository.example.edu/paper.pdf', 'source': 'oa'}]), \
                 patch.object(core, 'build_opener', return_value=opener), \
                 patch.object(core, 'LAST_PDF_ATTEMPT', None), \
                 patch.object(core, 'ZoteroLocal', side_effect=AssertionError('Independent mode must not connect')), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                first = t.main(['fetch', record()['DOI'], '--out', str(out), '--oa-only'])
                second = t.main(['fetch', record()['DOI'], '--out', str(out), '--oa-only', '--skip-done'])
            self.assertEqual((first, second), (0, 0))
            metadata.assert_called_once()
            opener.open.assert_called_once()
            row = json.loads((out / 'report.json').read_text())['results'][0]
            self.assertEqual(Path(row['pdf']).read_bytes(), payload)
            self.assertTrue(core.checkpoint_pdf_valid(row))
            self.assertEqual(row['download_state']['status'], 'VERIFIED')

    def test_previous_archive_failure_does_not_block_independent_download(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'p.pdf')
            b.save_rows(out, [{'number': 1, 'input': record()['DOI'], 'status': 'PDF_SAVED',
                              'pdf': str(pdf), 'sha256': core.pdf_sha256(pdf),
                              'zotero': 'WRITE_PENDING', 'archive_state': {'status': 'PENDING'}}])
            runner = MagicMock(side_effect=AssertionError('No work needed'))
            result = b.run_batch([record()['DOI']], out, runner=runner)
            self.assertTrue(result['ok'])
            self.assertEqual(result['skipped'], 1)
            runner.assert_not_called()

    def test_failures_separates_downloads_from_archival_tasks(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'p.pdf')
            b.save_rows(out, [{'number': 1, 'input': record()['DOI'], 'status': 'PDF_SAVED',
                              'pdf': str(pdf), 'sha256': core.pdf_sha256(pdf)}])
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(t.main(['failures', '--out', out, '--json']), 0)
            self.assertEqual(json.loads(output.getvalue())['pending'], 0)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(t.main(['failures', '--out', out, '--json', '--zotero']), 0)
            self.assertEqual(json.loads(output.getvalue())['pending'], 1)

    def test_unavailable_publisher_metadata_becomes_pending_not_a_crash(self):
        with tempfile.TemporaryDirectory() as out:
            paper = core.paper_from_crossref(record())
            options = args(out, doi_index={paper['doi']: {}}, metadata_only=False)
            with patch.object(core, 'paper_from_zotero', return_value=paper), \
                 patch.object(core, 'crossref_metadata', side_effect=core.PaperError('offline')), \
                 patch.object(core, 'pdf_candidates', return_value=[]):
                result = t.run_reference(paper['doi'], options)
            self.assertEqual(result['status'], 'PDF_PENDING')
            self.assertEqual(result['paper'], paper)
            self.assertTrue(any('Publisher metadata unavailable' in warning for warning in result['warnings']))

    def test_local_pdf_precedes_oa_and_browser_even_with_pii(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / '10.1000_workflow.pdf')
            metadata = dict(record(), link=[{'URL': 'https://api.elsevier.com/content/article/PII:S0020025526007310'}])
            with patch.object(core, 'crossref_metadata', return_value=(metadata, 1)), \
                 patch.object(core, 'pdf_candidates') as oa, \
                 patch.object(t.subprocess, 'run') as browser, \
                 patch.object(core, 'ZoteroLocal', side_effect=AssertionError('Zotero must not be used')):
                result = t.run_reference(metadata['DOI'], args(out))
            self.assertEqual(result['pdf'], str(pdf))
            self.assertEqual(result['status'], 'PDF_SAVED')
            oa.assert_not_called()
            browser.assert_not_called()

    def test_oa_success_avoids_browser_even_with_pii(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'oa.pdf')
            metadata = dict(record(), link=[{'URL': 'https://api.elsevier.com/content/article/PII:S0020025526007310'}])
            with patch.object(core, 'crossref_metadata', return_value=(metadata, 1)), \
                 patch.object(core, 'pdf_candidates', return_value=[{'url': 'https://example.org/p.pdf'}]) as oa, \
                 patch.object(core, 'download_verified', return_value=(pdf, {'source': 'oa'}, [])) as download, \
                 patch.object(t.subprocess, 'run') as browser:
                result = t.run_reference(metadata['DOI'], args(out))
            self.assertEqual(result['status'], 'PDF_SAVED')
            oa.assert_called_once()
            download.assert_called_once()
            browser.assert_not_called()

    def test_independent_batch_can_resume_without_zotero_or_metadata_requests(self):
        with tempfile.TemporaryDirectory() as out:
            calls = []
            def runner(ref, options):
                calls.append(ref)
                pdf = make_pdf(Path(options.out) / '10.1000_workflow.pdf')
                return {'status': 'PDF_SAVED', 'pdf': str(pdf), 'paper': core.paper_from_crossref(record())}
            with patch.object(core, 'ZoteroLocal', side_effect=AssertionError('No Zotero')), \
                 patch.object(core, 'crossref_metadata', side_effect=AssertionError('No metadata lookup on resume')):
                first = b.run_batch(['10.1000/workflow'], out, runner=runner, interval=0)
                second = b.run_batch(['10.1000/workflow'], out, runner=runner, interval=0)
            self.assertTrue(first['ok'] and second['ok'])
            self.assertEqual(second['skipped'], 1)
            self.assertEqual(calls, ['10.1000/workflow'])

    def test_corrupted_pdf_is_not_skipped_and_does_not_erase_original(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'PDF' / '10.1000_workflow.pdf')
            b.save_rows(out, [{'number': 1, 'input': '10.1000/workflow',
                              'paper': core.paper_from_crossref(record()), 'doi': record()['DOI'],
                              'title': record()['title'][0], 'status': 'PDF_SAVED', 'pdf': str(pdf),
                              'sha256': core.pdf_sha256(pdf)}])
            pdf.write_bytes(b'%PDF-corrupt')
            runner = MagicMock(return_value={'status': 'PDF_PENDING', 'paper': core.paper_from_crossref(record())})
            result = b.run_batch(['10.1000/workflow'], out, runner=runner, interval=0)
            self.assertEqual(result['skipped'], 0)
            self.assertFalse(result['ok'])
            runner.assert_called_once()
            self.assertEqual(pdf.read_bytes(), b'%PDF-corrupt')

    def test_legacy_file_without_digest_requires_identity_verification(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'a.pdf')
            row = {'status': 'PDF_SAVED', 'pdf': str(pdf), 'paper': core.paper_from_crossref(record())}
            self.assertTrue(b.row_done(row))
            row['paper']['title'] = 'A completely different title'
            self.assertFalse(b.row_done(row))

    def test_downloaded_pdf_and_full_metadata_can_later_be_archived(self):
        with tempfile.TemporaryDirectory() as out:
            paper = core.paper_from_crossref(record())
            def runner(ref, options):
                return {'status': 'PDF_SAVED', 'paper': paper,
                        'pdf': str(make_pdf(Path(options.out) / '10.1000_workflow.pdf'))}
            b.run_batch([paper['doi']], out, runner=runner, interval=0)
            z = MagicMock(server_id='server-A')
            z.collections.return_value = [{'key': 'B', 'path': 'A/B', 'name': 'B'}]
            z.ensure_item.return_value = ('ITEM', True)
            z.ensure_pdf.return_value = {'status': 'PDF_ATTACHED', 'attachment_key': 'ATT'}
            with patch.object(core, 'ZoteroLocal', return_value=z), \
                 patch.object(core, 'crossref_metadata', side_effect=AssertionError('Reuse checkpoint metadata')):
                result = b.run_batch([paper['doi']], out, zotero=True, collection='A/B', interval=0)
            self.assertTrue(result['ok'])
            self.assertEqual(z.ensure_item.call_args.args[0], paper)
            row = b.load_rows(out)[0]
            self.assertEqual(row['download_state']['status'], 'VERIFIED')
            self.assertEqual(row['archive_state']['collection_key'], 'B')

    def test_fetch_skip_done_never_skips_a_new_archival_target(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'p.pdf')
            row = {'input': record()['DOI'], 'paper': core.paper_from_crossref(record()),
                   'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'sha256': core.pdf_sha256(pdf),
                   'collection': 'Old'}
            Path(out, 'report.json').write_text(json.dumps({'results': [row]}))
            with patch.object(t, 'run_reference', return_value=dict(row, collection='New')) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                code = t.main(['fetch', row['input'], '--out', out, '--skip-done', '--zotero', '--collection', 'New'])
            self.assertEqual(code, 0)
            run.assert_called_once()


class ArchiveTests(unittest.TestCase):
    def client(self):
        z = core.ZoteroLocal.__new__(core.ZoteroLocal)
        z.base, z.server_id, z.key = core.BASE, 'server-A', ''
        z._items_cache = z._collections_cache = None
        return z

    def test_switching_collection_rechecks_and_preserves_the_pdf(self):
        with tempfile.TemporaryDirectory() as out:
            paper = core.paper_from_crossref(record())
            pdf = make_pdf(Path(out) / 'PDF' / 'p.pdf')
            b.save_rows(out, [{'number': 1, 'input': paper['doi'], 'paper': paper,
                              'status': 'PDF_ATTACHED', 'pdf': str(pdf), 'sha256': core.pdf_sha256(pdf),
                              'archive_state': {'collection': 'Old', 'server_id': 'server-A'}}])
            z = MagicMock(server_id='server-B')
            z.collections.return_value = [{'key': 'NEW', 'name': 'New', 'path': 'New'}]
            z.ensure_item.return_value = ('NEWITEM', False)
            z.ensure_pdf.return_value = {'status': 'PDF_ALREADY_PRESENT', 'attachment_key': 'ATT'}
            with patch.object(core, 'ZoteroLocal', return_value=z):
                result = b.run_batch([paper['doi']], out, zotero=True, collection='New', interval=0)
            self.assertTrue(result['ok'])
            z.ensure_item.assert_called_once_with(paper, 'NEW')
            z.ensure_pdf.assert_called_once()
            self.assertEqual(b.load_rows(out)[0]['archive_state']['server_id'], 'server-B')

    def test_metadata_only_never_inspects_local_pdfs_or_uploads(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'PDF' / '10.1000_workflow.pdf')
            digest = core.pdf_sha256(pdf)
            z = MagicMock(server_id='server-A')
            z.collections.return_value = [{'key': 'B', 'path': 'A/B', 'name': 'B'}]
            z.items.return_value = [dict(DOI=record()['DOI'], title=record()['title'][0], itemType='journalArticle')]
            z.ensure_item.return_value = ('ITEM', False)
            with patch.object(core, 'ZoteroLocal', return_value=z), \
                 patch.object(b, 'local_pdf_candidates', side_effect=AssertionError('Do not inspect PDFs')), \
                 patch.object(core, 'crossref_metadata', side_effect=AssertionError('Use Zotero metadata')), \
                 patch.object(core, 'pdf_candidates', side_effect=AssertionError('Do not search PDFs')):
                result = b.run_batch([record()['DOI']], out, zotero=True, collection='A/B', metadata_only=True, interval=0)
            self.assertTrue(result['ok'])
            z.ensure_pdf.assert_not_called()
            z.upload_pdf.assert_not_called()
            self.assertEqual(core.pdf_sha256(pdf), digest)

    def test_metadata_only_preserves_an_old_download_without_revalidating_corrupt_bytes(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'p.pdf')
            digest = core.pdf_sha256(pdf)
            b.save_rows(out, [{'number': 1, 'input': record()['DOI'],
                              'status': 'PDF_SAVED', 'pdf': str(pdf), 'sha256': digest}])
            pdf.write_bytes(b'%PDF-corrupted-later')
            z = MagicMock(server_id='server-A')
            z.collections.return_value = [{'key': 'B', 'path': 'A/B', 'name': 'B'}]
            z.items.return_value = [dict(DOI=record()['DOI'], title=record()['title'][0], itemType='journalArticle')]
            z.ensure_item.return_value = ('ITEM', False)
            with patch.object(core, 'ZoteroLocal', return_value=z):
                result = b.run_batch([record()['DOI']], out, zotero=True, collection='A/B', metadata_only=True, interval=0)
            self.assertTrue(result['ok'])
            row = b.load_rows(out)[0]
            self.assertEqual(row['pdf'], str(pdf))
            self.assertEqual(row['sha256'], digest)
            self.assertEqual(row['download_state']['status'], 'PENDING')
            z.ensure_pdf.assert_not_called()

    def test_wrong_paper_in_existing_attachment_is_never_overwritten(self):
        z = self.client()
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'wrong.pdf', title='A completely unrelated article')
            z.children = MagicMock(return_value=[{'key': 'ATT', 'itemType': 'attachment',
                                                 'linkMode': 'imported_file', 'contentType': 'application/pdf'}])
            with patch.object(core, 'request_bytes', return_value=(200, {}, pdf.as_uri().encode(), '')), \
                 patch.object(z, '_upload_pdf_file') as upload, \
                 self.assertRaises(core.PaperError):
                z.ensure_pdf('ITEM', pdf, core.paper_from_crossref(record()))
            upload.assert_not_called()

    def test_archive_failure_preserves_local_download_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'PDF' / '10.1000_workflow.pdf')
            z = MagicMock(server_id='server-A')
            z.collections.return_value = [{'key': 'B', 'path': 'A/B', 'name': 'B'}]
            z.ensure_item.return_value = ('ITEM', False)
            z.ensure_pdf.side_effect = core.PaperError('upload interrupted')
            with patch.object(core, 'ZoteroLocal', return_value=z), \
                 patch.object(core, 'crossref_metadata', return_value=(record(), 1)):
                result = b.run_batch([record()['DOI']], out, zotero=True, collection='A/B', interval=0)
            row = b.load_rows(out)[0]
            self.assertFalse(result['ok'])
            self.assertEqual(row['status'], 'PDF_SAVED')
            self.assertEqual(row['archive_state']['status'], 'PENDING')
            self.assertTrue(core.checkpoint_pdf_valid(row))
            self.assertEqual(row['pdf'], str(pdf))

    def test_live_verified_attachment_avoids_upload(self):
        z = self.client()
        with patch.object(core, 'attachment_health', return_value={'pdf_attachments': [{'verified': True, 'attachment_key': 'ATT'}]}), \
             patch.object(z, 'upload_pdf') as upload:
            self.assertEqual(z.ensure_pdf('ITEM', Path('not-needed'), {})['status'], 'PDF_ALREADY_PRESENT')
        upload.assert_not_called()

    def test_missing_file_resumes_same_attachment_with_md5_precondition(self):
        z = self.client()
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'p.pdf')
            health = {'pdf_attachments': [{'attachment_key': 'ATT', 'missing': True,
                                         'linkMode': 'imported_file', 'md5': 'old-md5'}]}
            with patch.object(core, 'attachment_health', return_value=health), \
                 patch.object(z, '_upload_pdf_file', return_value=True) as upload, \
                 patch.object(z, 'write_item') as create:
                result = z.ensure_pdf('ITEM', pdf, {})
            upload.assert_called_once_with('ATT', pdf, previous_md5='old-md5')
            create.assert_not_called()
            self.assertEqual(result['attachment_key'], 'ATT')

    def test_unverifiable_remote_attachment_is_not_overwritten(self):
        z = self.client()
        with tempfile.TemporaryDirectory() as out:
            pdf = make_pdf(Path(out) / 'p.pdf')
            health = {'pdf_attachments': [{'attachment_key': 'ATT', 'state': 'UNVERIFIED',
                                         'linkMode': 'imported_file', 'md5': 'other-content'}]}
            with patch.object(core, 'attachment_health', return_value=health), \
                 patch.object(z, '_upload_pdf_file') as upload, \
                 self.assertRaises(core.PaperError):
                z.ensure_pdf('ITEM', pdf, {})
            upload.assert_not_called()

    def test_remote_file_path_does_not_prove_a_missing_attachment(self):
        z = self.client()
        z.children = MagicMock(return_value=[{'key': 'ATT', 'itemType': 'attachment',
                                             'contentType': 'application/pdf'}])
        with patch.object(core, 'request_bytes', return_value=(200, {}, b'file:///unavailable-on-this-computer/p.pdf', '')):
            health = core.attachment_health(z, 'ITEM')
        self.assertEqual(health['state'], 'UNVERIFIED')
        self.assertFalse(health['pdf_attachments'][0]['missing'])

    def test_api_404_is_distinguished_from_a_network_failure(self):
        z = self.client()
        z.children = MagicMock(return_value=[{'key': 'ATT', 'itemType': 'attachment',
                                             'contentType': 'application/pdf'}])
        for error, expected in [('HTTP 404 on localhost', 'MISSING_FILE'), ('Network failure', 'UNVERIFIED')]:
            with self.subTest(error=error), patch.object(core, 'request_bytes', side_effect=core.PaperError(error)):
                self.assertEqual(core.attachment_health(z, 'ITEM')['state'], expected)

    def test_patch_updates_cached_version_before_adding_another_collection(self):
        z = self.client()
        z._items_cache = [{'key': 'ITEM', 'DOI': record()['DOI'], 'version': 1, 'collections': []}]
        with patch.object(z, 'call', side_effect=[({}, {'Last-Modified-Version': '7'}), ({}, {'Last-Modified-Version': '9'})]) as call:
            z.ensure_item({'doi': record()['DOI']}, 'A')
            z.ensure_item({'doi': record()['DOI']}, 'B')
        self.assertEqual(call.call_args_list[1].args[2]['version'], 7)
        self.assertEqual(call.call_args_list[1].args[2]['collections'], ['A', 'B'])

    def test_zotero_dry_run_makes_no_connection_or_writes(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'ZoteroLocal') as connect:
            out = Path(folder) / 'not-created'
            summary = b.run_batch([record()['DOI']], out, zotero=True, collection='A/B', dry_run=True)
            self.assertTrue(summary['dry_run'])
            self.assertFalse(out.exists())
            connect.assert_not_called()

    def test_non_record_checkpoint_is_rejected_before_overwrite(self):
        with tempfile.TemporaryDirectory() as out:
            path = Path(out) / 'manifest.json'
            path.write_text('[null]')
            with self.assertRaises(ValueError):
                b.run_batch([record()['DOI']], out)
            self.assertEqual(path.read_text(), '[null]')
