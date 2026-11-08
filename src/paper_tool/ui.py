"""Local browser interface. Foreground process, loopback only, no extra runtime."""
from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlparse
import webbrowser
import zipfile

from . import __version__, batch, core

ASSETS = Path(__file__).with_name('web')
MAX_BODY = 128 * 1024
MAX_REFERENCES = 200


class InputError(ValueError):
    pass


def local_api(value):
    try:
        p = urlparse(str(value))
        _ = p.port
    except ValueError:
        raise InputError('invalid_zotero')
    if (p.scheme != 'http' or p.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or p.username or p.password or p.query or p.fragment
            or p.path.rstrip('/') != '/api'):
        raise InputError('invalid_zotero')
    return str(value).rstrip('/')


class Jobs:
    def __init__(self, folder, *, zotero_base=core.BASE, proxy='direct', runner=None):
        self.folder = Path(folder).expanduser().resolve()
        self.pdf_dir = self.folder / 'PDF'
        self.zotero_base = local_api(zotero_base)
        self.proxy = proxy
        self.runner = runner or batch.run_batch
        self.jobs = {}
        self.lock = threading.Lock()
        self.active = None
        self.verified = {}

    def start(self, payload):
        text = payload.get('references', '')
        if not isinstance(text, str) or len(text) > 50000:
            raise InputError('invalid_references')
        refs = [line.strip() for line in text.splitlines()
                if line.strip() and not line.strip().startswith('#')]
        unique = {}
        for ref in refs:
            unique.setdefault(ref.lower(), ref)
        refs = list(unique.values())
        if not refs:
            raise InputError('empty_references')
        if len(refs) > MAX_REFERENCES:
            raise InputError('too_many_references')
        for name in ('zotero', 'institutional', 'metadata_only'):
            if name in payload and not isinstance(payload[name], bool):
                raise InputError('invalid_options')
        archive = payload.get('zotero', False)
        metadata = payload.get('metadata_only', False)
        collection = payload.get('collection') or ''
        if not isinstance(collection, str) or len(collection) > 500:
            raise InputError('invalid_collection')
        if archive and not collection.strip():
            raise InputError('choose_collection')
        if metadata and not archive:
            raise InputError('choose_collection')
        base = local_api(payload.get('zotero_base') or self.zotero_base)
        with self.lock:
            if self.active:
                raise InputError('busy')
            key = secrets.token_hex(12)
            job = {'id': key, 'refs': refs, 'state': 'running', 'error': '',
                   'created': datetime.now().strftime('%m-%d %H:%M'),
                   'out': self.folder / 'tasks' / key,
                   'options': {'zotero': archive, 'collection': collection.strip(),
                               'zotero_base': base, 'metadata_only': metadata,
                               'oa_only': not payload.get('institutional', False),
                               'proxy': self.proxy}}
            self.jobs[key] = job
            self.active = key
        threading.Thread(target=self._run, args=(key,), daemon=True).start()
        return key

    def _run(self, key, refs=None):
        job = self.jobs[key]
        try:
            result = self.runner(refs or job['refs'], job['out'], pdf_dir=self.pdf_dir,
                                 interval=30, stream=io.StringIO(), **job['options'])
            job['state'] = 'completed' if result['ok'] else 'partial'
        except Exception:
            # Raw provider errors can contain private paths or URLs. Keep them
            # out of the beginner UI; the engine's checkpoint remains available.
            job.update(state='error', error='task_failed')
        finally:
            with self.lock:
                self.active = None

    def _get(self, key):
        if key not in self.jobs:
            raise KeyError(key)
        return self.jobs[key]

    def rows(self, key):
        job = self._get(key)
        try:
            return batch.load_rows(job['out'])
        except ValueError:
            return []

    def file(self, key, index, *, verify=True):
        rows = self.rows(key)
        if not 0 <= index < len(rows):
            raise FileNotFoundError()
        return self._file(rows[index], verify=verify)

    def _file(self, row, *, verify=True):
        if not row.get('pdf'):
            raise FileNotFoundError()
        p = Path(row['pdf']).resolve()
        if p.parent != self.pdf_dir.resolve() or p.suffix.lower() != '.pdf' or not p.is_file():
            raise FileNotFoundError()
        if verify:
            stat = p.stat()
            signature = (stat.st_mtime_ns, stat.st_size, str(row.get('sha256')),
                         str(row.get('doi')), str(row.get('title')))
            cached = self.verified.get(p)
            valid = cached[1] if cached and cached[0] == signature else core.checkpoint_pdf_valid(row)
            self.verified[p] = (signature, valid)
            if not valid:
                raise FileNotFoundError()
        return p

    def snapshot(self, key):
        job = self._get(key)
        rows = self.rows(key)
        results = []
        for index, row in enumerate(rows):
            try:
                self._file(row)
                ready = True
            except (FileNotFoundError, OSError):
                ready = False
            results.append({'number': index + 1,
                            'title': row.get('title') or row.get('input') or '',
                            'doi': row.get('doi') or '',
                            'status': row.get('status') or 'WAITING',
                            'pdf': ready,
                            'archive_pending': row.get('zotero') in {'WRITE_PENDING', 'COLLECTION_REVIEW'}})
        return {'id': key, 'state': job['state'], 'error': job['error'],
                'created': job['created'], 'total': len(job['refs']),
                'processed': sum(bool(r.get('status')) for r in rows),
                'available': sum(r['pdf'] for r in results), 'results': results}

    def retry(self, key, payload=None):
        job = self._get(key)
        options = job['options']
        payload = payload or {}
        if 'institutional' in payload and not isinstance(payload['institutional'], bool):
            raise InputError('invalid_options')
        with self.lock:
            if self.active:
                raise InputError('busy')
            rows = {row['input'].lower(): row for row in self.rows(key)}
            pending = [ref for ref in job['refs']
                       if not batch._succeeded(rows.get(ref.lower(), {}),
                                               options['zotero'], options['metadata_only'])]
            if not pending:
                raise InputError('nothing_pending')
            if 'institutional' in payload:
                options['oa_only'] = not payload['institutional']
            job.update(state='running', error='')
            self.active = key
        # Keep the original checkpoint and attachment state. Only unfinished
        # references run again; the institutional option can be enabled later.
        threading.Thread(target=self._run, args=(key, pending), daemon=True).start()
        return key


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, jobs):
        if address[0] != '127.0.0.1':
            raise ValueError('The browser app is loopback-only')
        self.jobs = jobs
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _allowed(self, mutation=False):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts:
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://' + host for host in hosts}:
            return False
        if mutation:
            token = self.headers.get('X-CiteCargo-Token', '')
            return token.isascii() and secrets.compare_digest(token, self.server.token)
        return True

    def _headers(self, status, mime, length):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self._headers(status, 'application/json; charset=utf-8', len(data))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._allowed():
            return self._json({'error': 'forbidden'}, 403)
        path = urlparse(self.path).path
        jobs = self.server.jobs
        try:
            if path == '/api/settings':
                return self._json({'app': 'citecargo', 'version': __version__,
                                   'token': self.server.token, 'folder': str(jobs.pdf_dir),
                                   'zotero_base': jobs.zotero_base})
            if path == '/api/jobs':
                return self._json({'jobs': [jobs.snapshot(k) for k in list(jobs.jobs)[-20:][::-1]]})
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{24})(?:/(zip|file/\d+))?', path)
            if match:
                key, action = match.groups()
                if action is None:
                    return self._json(jobs.snapshot(key))
                if action.startswith('file/'):
                    file = jobs.file(key, int(action.split('/')[1]))
                    with file.open('rb') as source:
                        return self._send_file(source, file.stat().st_size, 'application/pdf', file.name)
                files = []
                for row in jobs.rows(key):
                    try:
                        p = jobs._file(row)
                        if p not in files:
                            files.append(p)
                    except FileNotFoundError:
                        continue
                if not files:
                    return self._json({'error': 'no_files'}, 409)
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as source:
                    with zipfile.ZipFile(source, 'w', zipfile.ZIP_STORED) as archive:
                        for file in files:
                            archive.write(file, file.name)
                    size = source.tell()
                    source.seek(0)
                    return self._send_file(source, size, 'application/zip', 'CiteCargo-papers.zip')
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in assets:
                file, mime = assets[path]
                data = (ASSETS / file).read_bytes()
                self._headers(200, mime, len(data)); self.end_headers(); self.wfile.write(data)
                return
            return self._json({'error': 'not_found'}, 404)
        except (KeyError, FileNotFoundError, ValueError, OSError):
            return self._json({'error': 'not_found'}, 404)

    def _send_file(self, source, size, mime, name):
        self._headers(200, mime, size)
        # Engine-generated DOI filenames contain no quotes, CR or LF.
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        self.send_header('Content-Disposition', f'attachment; filename="{safe}"')
        self.end_headers()
        shutil.copyfileobj(source, self.wfile)

    def do_POST(self):
        if not self._allowed(mutation=True):
            return self._json({'error': 'forbidden'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_BODY:
                raise InputError('invalid_request')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise InputError('invalid_request')
            path = urlparse(self.path).path
            jobs = self.server.jobs
            if path == '/api/jobs':
                return self._json({'id': jobs.start(data)}, 202)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{24})/retry', path)
            if match:
                return self._json({'id': jobs.retry(match[1], data)}, 202)
            if path == '/api/collections':
                client = core.ZoteroLocal(local_api(data.get('zotero_base') or jobs.zotero_base))
                return self._json({'collections': client.collections()})
            if path == '/api/browser':
                from .cli import start_browser
                state = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local/share') / 'CiteCargo/browser'
                result = start_browser(state)
                return self._json({'ok': bool(result.get('ok')), 'error': '' if result.get('ok') else 'browser_unavailable'})
            if path == '/api/folder':
                jobs.pdf_dir.mkdir(parents=True, exist_ok=True)
                if sys.platform == 'win32':
                    os.startfile(jobs.pdf_dir)
                else:
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(jobs.pdf_dir)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._json({'ok': True})
            return self._json({'error': 'not_found'}, 404)
        except InputError as error:
            return self._json({'error': str(error)}, 409 if str(error) == 'busy' else 400)
        except (ValueError, UnicodeError):
            return self._json({'error': 'invalid_request'}, 400)
        except KeyError:
            return self._json({'error': 'not_found'}, 404)
        except (core.PaperError, OSError):
            return self._json({'error': 'connection_failed'}, 503)


def serve(folder, port=8765, *, open_browser=True, zotero_base=core.BASE, proxy='direct', language='zh'):
    jobs = Jobs(folder, zotero_base=zotero_base, proxy=proxy)
    server = AppServer(('127.0.0.1', port), jobs)
    url = f'http://127.0.0.1:{server.server_port}/' + ('?lang=en' if language == 'en' else '')
    print('CiteCargo: '+url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
