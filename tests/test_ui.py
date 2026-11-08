"""Local UI behavior: no external requests or personal library access."""
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
import zipfile

from paper_tool import batch, cli, core, ui
from tests.test_workflows import make_pdf, record


def wait_job(jobs):
    deadline = time.monotonic() + 3
    while jobs.active and time.monotonic() < deadline:
        time.sleep(.005)
    if jobs.active:
        raise AssertionError('Local job did not finish')


class LocalUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jobs = ui.Jobs(self.tmp.name)
        self.server = ui.AppServer(('127.0.0.1', 0), self.jobs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = build_opener(ProxyHandler({}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, data=None, headers=None):
        h = {'X-CiteCargo-Token': self.server.token, 'Content-Type': 'application/json'}
        h.update(headers or {})
        request = Request(self.base + path, headers=h,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            response = self.opener.open(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def json(self, path, data=None, headers=None):
        code, _, raw = self.request(path, data, headers)
        return code, json.loads(raw)

    def test_independent_download_to_verified_pdf_and_zip(self):
        def reference(ref, args):
            self.assertFalse(args.zotero)
            self.assertTrue(args.oa_only)
            pdf = make_pdf(Path(args.out) / '10.1000_workflow.pdf')
            return {'status': 'PDF_SAVED', 'paper': core.paper_from_crossref(record()),
                    'pdf': str(pdf), 'sha256': core.pdf_sha256(pdf)}
        with patch.object(cli, 'run_reference', side_effect=reference), \
             patch.object(core, 'ZoteroLocal', side_effect=AssertionError('No archival requested')):
            code, result = self.json('/api/jobs', {'references': record()['DOI']})
            self.assertEqual(code, 202)
            wait_job(self.jobs)
        key = result['id']
        code, job = self.json('/api/jobs/' + key)
        self.assertEqual((code, job['state'], job['available']), (200, 'completed', 1))
        pdf_path = self.jobs.file(key, 0)
        code, headers, raw = self.request(f'/api/jobs/{key}/file/0')
        self.assertEqual((code, headers['Content-Type'], raw), (200, 'application/pdf', pdf_path.read_bytes()))
        code, _, raw = self.request(f'/api/jobs/{key}/zip')
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.namelist(), [pdf_path.name])
            self.assertEqual(archive.read(pdf_path.name), pdf_path.read_bytes())

    def test_foreign_sites_cannot_read_or_start_jobs(self):
        self.assertEqual(self.json('/api/settings', headers={'Origin': 'https://example.org'})[0], 403)
        self.assertEqual(self.json('/api/settings', headers={'Host': 'example.org'})[0], 403)
        self.assertEqual(self.json('/api/jobs', {'references': 'x'}, {'X-CiteCargo-Token': ''})[0], 403)
        self.assertEqual(self.json('/api/jobs', {'references': 'x'}, {'X-CiteCargo-Token': 'wrong'})[0], 403)
        self.assertEqual(self.jobs.jobs, {})
        with self.assertRaises(ValueError):
            ui.AppServer(('0.0.0.0', 0), self.jobs)

    def test_invalid_inputs_and_missing_archive_destination_do_not_write(self):
        payloads = [{}, {'references': []}, {'references': 'x', 'zotero': 'yes'},
                    {'references': 'x', 'zotero': True},
                    {'references': 'x', 'metadata_only': True},
                    {'references': '\n'.join(str(i) for i in range(201))},
                    {'references': 'x', 'zotero_base': 'http://192.168.1.1:23119/api'}]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.json('/api/jobs', payload)[0], 400)
        self.assertFalse((Path(self.tmp.name) / 'tasks').exists())

    def test_loopback_api_validation(self):
        for value in ('http://localhost:23119/api/', 'http://127.0.0.1:23129/api', 'http://[::1]:23119/api'):
            self.assertEqual(ui.local_api(value), value.rstrip('/'))
        for value in ('https://localhost/api', 'http://user:secret@localhost/api',
                      'http://localhost/api?token=secret', 'http://localhost:notaport/api',
                      'http://localhost:23119/anything', 'http://localhost.example.org/api'):
            with self.subTest(value=value), self.assertRaises(ui.InputError):
                ui.local_api(value)

    def test_download_routes_reject_modified_and_outside_files(self):
        self.jobs.runner = lambda *a, **kw: {'ok': True}
        key = self.jobs.start({'references': '10.1000/test'})
        wait_job(self.jobs)
        outside = make_pdf(Path(self.tmp.name) / 'private.pdf')
        row = {'input': '10.1000/test', 'status': 'PDF_SAVED',
               'pdf': str(outside), 'sha256': core.pdf_sha256(outside)}
        batch.save_rows(self.jobs.jobs[key]['out'], [row])
        self.assertEqual(self.request(f'/api/jobs/{key}/file/0')[0], 404)
        self.assertEqual(self.request(f'/api/jobs/{key}/zip')[0], 409)
        pdf = make_pdf(self.jobs.pdf_dir / 'paper.pdf')
        row.update(pdf=str(pdf), sha256=core.pdf_sha256(pdf))
        batch.save_rows(self.jobs.jobs[key]['out'], [row])
        pdf.write_bytes(pdf.read_bytes() + b'changed')
        self.assertEqual(self.jobs.snapshot(key)['available'], 0)
        self.assertEqual(self.request(f'/api/jobs/{key}/file/0')[0], 404)
        self.assertEqual(self.request('/../AGENTS.md')[0], 404)

    def test_busy_job_deduplicates_inputs(self):
        release = threading.Event()
        self.jobs.runner = lambda *a, **kw: (release.wait(2) and {'ok': True})
        try:
            key = self.jobs.start({'references': '# comment\n10.1000/ABC\n\n10.1000/abc\nother'})
            self.assertEqual(self.jobs.jobs[key]['refs'], ['10.1000/ABC', 'other'])
            self.assertEqual(self.json('/api/jobs', {'references': 'another'})[0], 409)
            self.assertEqual(self.json(f'/api/jobs/{key}/retry', {})[0], 409)
        finally:
            release.set()
            wait_job(self.jobs)

    def test_retry_retains_checkpoint_and_enables_institutional_access(self):
        calls = []
        def runner(refs, out, **options):
            calls.append((refs, out, options))
            if len(calls) == 1:
                pdf = make_pdf(self.jobs.pdf_dir / 'ready.pdf')
                batch.save_rows(out, [
                    {'input': 'ready', 'status': 'PDF_SAVED', 'pdf': str(pdf), 'sha256': core.pdf_sha256(pdf)},
                    {'input': 'pending', 'status': 'PDF_PENDING', 'attachment_key': 'KEEP'}])
                return {'ok': False}
            self.assertEqual(batch.load_rows(out)[1]['attachment_key'], 'KEEP')
            return {'ok': True}
        self.jobs.runner = runner
        key = self.jobs.start({'references': 'ready\npending'})
        wait_job(self.jobs)
        self.assertEqual(self.json(f'/api/jobs/{key}/retry', {'institutional': True}), (202, {'id': key}))
        wait_job(self.jobs)
        self.assertEqual(calls[1][0], ['pending'])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertTrue(calls[0][2]['oa_only'])
        self.assertFalse(calls[1][2]['oa_only'])

    def test_retry_includes_references_missing_after_failure(self):
        self.jobs.runner = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('private token'))
        key = self.jobs.start({'references': 'one\ntwo'})
        wait_job(self.jobs)
        _, data = self.json('/api/jobs/' + key)
        self.assertEqual(data['error'], 'task_failed')
        self.assertNotIn('private', json.dumps(data))
        seen = []
        self.jobs.runner = lambda refs, *a, **kw: (seen.extend(refs) or {'ok': True})
        self.jobs.retry(key)
        wait_job(self.jobs)
        self.assertEqual(seen, ['one', 'two'])

    def test_collection_read_is_explicit_and_error_is_sanitized(self):
        with patch.object(core, 'ZoteroLocal') as client:
            self.request('/')
            self.request('/api/settings')
            client.assert_not_called()
            client.return_value.collections.return_value = [{'path': 'A/B', 'key': 'K'}]
            self.assertEqual(self.json('/api/collections', {})[1]['collections'][0]['path'], 'A/B')
            client.return_value.collections.side_effect = core.PaperError('private session')
            self.assertEqual(self.json('/api/collections', {}), (503, {'error': 'connection_failed'}))

    def test_ui_command_forwards_configuration(self):
        with patch.object(ui, 'serve', return_value=0) as serve:
            self.assertEqual(cli.app(['ui', '--no-browser', '--port', '0', '--out', self.tmp.name]), 0)
            self.assertEqual(serve.call_args.args[1], 0)
            self.assertFalse(serve.call_args.kwargs['open_browser'])


if __name__ == '__main__':
    unittest.main()
