#!/usr/bin/env python3
"""One command for reference resolution, authorized PDF retrieval and Zotero."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import SimpleNamespace
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
import batch_runner
import paper_to_zotero as core
from paper_tool_assets import __version__
ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = Path(os.environ.get('PAPER_TOOL_OUT') or Path.cwd() / 'downloads').expanduser()
DEFAULT_ZOTERO = os.environ.get('PAPER_TOOL_ZOTERO_BASE') or core.BASE
DEFAULT_PROXY = os.environ.get('PAPER_TOOL_PROXY') or 'direct'
CDP_DEFAULT = 'http://127.0.0.1:18806'

STATUS_RANK = {'PREVIEW':0,'NEEDS_REVIEW':1,'PDF_PENDING':2,'PDF_SAVED':3,
               'METADATA_ONLY':3,'PDF_ATTACHED':4,'PDF_ALREADY_PRESENT':4,'已有PDF已汇总':4,
               '待下载':2,'待核验/补全':1,'题录待核验':1}


def merge_report(history, results):
    """Keep the latest attempt visible; never mask failure with old success."""
    merged = {}
    for row in history + results:
        key = row.get('paper',{}).get('doi') or row.get('input')
        previous = merged.get(key)
        if previous is None:
            merged[key] = row
            continue
        latest = dict(row)
        if previous.get('status') != row.get('status'):
            latest['previous_status'] = previous.get('status')
        # Preserve the available local artifact separately from task completion.
        if not row.get('pdf') and core.checkpoint_pdf_valid(previous):
            latest.update(pdf=previous['pdf'], sha256=previous.get('sha256'),
                          paper=previous.get('paper') or row.get('paper'))
        merged[key] = latest
    return list(merged.values())


def browser_output_path(candidate, paper):
    """Pick a writable path without overwriting or deleting any retained file."""
    notes = []
    for n in range(1,100):
        target = candidate if n == 1 else candidate.with_name(f'{candidate.stem}-{n}{candidate.suffix}')
        if not target.exists():
            return target, False, notes
        valid, why = core.verify_pdf(target, paper)
        if valid:
            return target, True, notes
        notes.append(target.name+' failed identity check; retained and skipped ('+why+').')
    raise core.PaperError('No writable PDF file name available: '+candidate.name)



def read_references(path):
    """Read a reference list without crashing on ordinary Windows input.

    Accepts UTF-8 (with or without BOM) and falls back to GBK for files saved
    by Chinese editions of Excel/Notepad; blank lines and lines starting with
    '#' are ignored so a paper can be commented out temporarily.
    """
    folder = Path(path).expanduser()
    if not folder.exists():
        raise ValueError(f'Input file not found: {folder}')
    if folder.is_dir():
        raise ValueError(f'Input must be a file, not a folder: {folder}')
    raw_bytes = folder.read_bytes()
    for encoding in ('utf-8-sig', 'gbk'):
        try:
            text = raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding != 'utf-8-sig':
            print(f'Warning: {folder.name} is not UTF-8; decoded as {encoding}. '
                  'Re-save as UTF-8 to avoid ambiguous characters.', file=sys.stderr)
        break
    else:
        raise ValueError(f'Cannot decode {folder}; save the list as UTF-8, one reference per line')
    refs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        refs.append(line)
    return list(dict.fromkeys(refs))


def doctor(proxy='direct', deep=False, zotero_base=None):
    # `ok` reflects only the ports required by the chosen network route.
    checks = {}
    from urllib.parse import urlparse
    endpoint = urlparse(zotero_base or DEFAULT_ZOTERO)
    for name, port in (('vpn_proxy',urlparse(proxy).port or 1081),('browser_cdp',18806),('zotero_local',endpoint.port or 23119)):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=2):
                checks[name] = True
        except OSError:
            checks[name] = False
    required = ['browser_cdp'] if proxy == 'direct' else ['vpn_proxy','browser_cdp']
    result = {'ok': all(checks[name] for name in required), 'checks':checks,
            'required':required, 'proxy':proxy,
            'note':'Listening ports only; a direct route does not need port 1081. The Zotero port (23119/23129) is reported but not part of ok; VPN entitlement and Zotero authorization need a real request.'}
    if deep:
        # Everything the SOP used to ask a person to type by hand.
        result['deep'] = deep_checks(zotero_base or DEFAULT_ZOTERO)
    return result


def deep_checks(zotero_base):
    """Read-only check of Node, Playwright and the Zotero local API."""
    import shutil
    found = {'node': shutil.which('node') or '', 'playwright': False,
             'browser_cdp': cdp_status()}
    if found['node']:
        try:
            probe = subprocess.run([found['node'], '-e', "require('playwright-core');console.log('ok')"],
                                   cwd=str(ROOT), capture_output=True, text=True, timeout=20,
                                   stdin=subprocess.DEVNULL)
            found['playwright'] = probe.returncode == 0 and 'ok' in probe.stdout
        except (OSError, subprocess.SubprocessError):
            found['playwright'] = False
    try:
        zotero = core.ZoteroLocal(zotero_base)
        found['zotero_server_id'] = zotero.server_id or ''
        found['zotero_authorized'] = bool(zotero.key)
        found['zotero_collections'] = len(zotero.collections())
    except (core.PaperError, OSError) as error:
        found['zotero_error'] = str(error)
    return found


def cdp_status(cdp=CDP_DEFAULT, timeout=3.0):
    """Ask the debugging endpoint whether a usable browser is already listening."""
    url = str(cdp).rstrip('/') + '/json/version'
    try:
        # A loopback request must never go through a system proxy: with one
        # configured, the proxy answers 502 and a healthy browser looks broken.
        with build_opener(ProxyHandler({})).open(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8', 'replace'))
        return {'ok': True, 'cdp': cdp, 'browser': payload.get('Browser', ''),
                'websocket': payload.get('webSocketDebuggerUrl', '')}
    except HTTPError as error:
        return {'ok': False, 'cdp': cdp, 'error': f'HTTP {error.code} from {url}',
                'reason': 'the port is taken by something that is not a Chrome debugging endpoint'}
    except (URLError, OSError) as error:
        detail = getattr(error, 'reason', error)
        refused = isinstance(detail, ConnectionRefusedError) or any(
            marker in str(detail) for marker in ('refused', '10061', 'actively refused'))
        return {'ok': False, 'cdp': cdp, 'error': f'{type(error).__name__}: {detail}',
                'reason': 'nothing is listening on this port' if refused
                          else 'the debugging endpoint did not answer'}


def chrome_candidates():
    """Chrome first, Edge second: both speak CDP and both honour --user-data-dir."""
    import os
    import shutil
    paths = []
    if sys.platform == 'win32':
        for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
                     os.environ.get('LocalAppData')):
            if root:
                paths.append(Path(root) / 'Google/Chrome/Application/chrome.exe')
                paths.append(Path(root) / 'Microsoft/Edge/Application/msedge.exe')
        for name in ('chrome.exe', 'msedge.exe'):
            paths.extend(Path(found) for found in [shutil.which(name)] if found)
    else:
        for name in ('google-chrome', 'chromium', 'chromium-browser'):
            found = shutil.which(name)
            if found:
                paths.append(Path(found))
    return list(dict.fromkeys(path for path in paths if path.is_file()))


def start_browser(profile, chrome=None, cdp=CDP_DEFAULT, timeout=25.0):
    """Start the dedicated browser on a loopback debugging port, or reuse it."""
    from urllib.parse import urlparse
    state = cdp_status(cdp, timeout=2)
    if state['ok']:
        return {**state, 'started': False,
                'note': 'Reusing the browser already listening on this port; do not start a second one.'}
    target = Path(chrome).expanduser() if chrome else next(iter(chrome_candidates()), None)
    if not target or not Path(target).is_file():
        return {'ok': False, 'cdp': cdp, 'started': False,
                'error': 'Chrome/Edge not found; pass --chrome with the full executable path'}
    profile = Path(profile).expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    port = urlparse(cdp).port or 18806
    command = [str(target), f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1',
               f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check', 'about:blank']
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = cdp_status(cdp, timeout=1)
        if state['ok']:
            return {**state, 'started': True, 'pid': process.pid, 'chrome': str(target),
                    'profile': str(profile),
                    'note': 'Finish the institution login in this window; the tool never does it for you.'}
        time.sleep(0.5)
    return {'ok': False, 'cdp': cdp, 'started': False, 'pid': process.pid, 'chrome': str(target),
            'error': f'Browser started but the debugging port did not answer within {timeout:.0f}s'}

def progress_snapshot(out):
    """Read the checkpoint only; never changes a running batch job.

    Batch jobs maintain manifest.json; the single-paper entry point writes
    report.json instead, so fall back to it when no manifest exists.
    """
    folder = Path(out).expanduser()
    manifest = folder / 'manifest.json'
    report = folder / 'report.json'
    checkpoint, source = (manifest, 'manifest.json') if manifest.exists() else (report, 'report.json')
    try:
        payload = json.loads(checkpoint.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'ok': False, 'error': f'No manifest.json or report.json in {folder}'}
    except (OSError, ValueError):
        return {'ok': False, 'error': 'Checkpoint is being updated; retry in a moment'}
    rows = payload.get('results', []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {'ok': False, 'error': f'{source} must contain a list of records'}

    def warning_text(value):
        if isinstance(value, (list, tuple)):
            return '; '.join(str(v) for v in value)
        return str(value or '')

    def title(row):
        return row.get('title') or row.get('input_title') or (row.get('paper') or {}).get('title') or row.get('input') or 'Untitled'

    valid_pdf = [row for row in rows if core.checkpoint_pdf_valid(row)]
    statuses = Counter(row.get('status') or '未处理' for row in rows)
    counted = {'PDF_ATTACHED','PDF_ALREADY_PRESENT','已有PDF已汇总','PDF_SAVED',
               'METADATA_ONLY','PDF_PENDING','待下载','待核验/补全','NEEDS_REVIEW'}
    other = sum(count for status,count in statuses.items() if status not in counted)
    issues = [row for row in rows if row.get('warnings')
              or (row.get('status') or '未处理') not in counted
              or row.get('status') in {'待核验/补全','NEEDS_REVIEW'}]
    return {
        'ok': True, 'source': source, 'checkpoint': str(checkpoint.resolve()),
        'updated': checkpoint.stat().st_mtime,
        'total': len(rows),
        'valid_pdf': len(valid_pdf),
        'attached': statuses['PDF_ATTACHED'] + statuses['PDF_ALREADY_PRESENT'],
        'existing_pdf': statuses['已有PDF已汇总'],
        'saved_local': statuses['PDF_SAVED'],
        'metadata': statuses['METADATA_ONLY'],
        'pending': statuses['PDF_PENDING'] + statuses['待下载'],
        'other': other,
        'review': statuses['待核验/补全'] + statuses['NEEDS_REVIEW'] + other,
        'statuses': dict(statuses),
        'issues': [
            {'number': row.get('number') or '-', 'title': title(row), 'status': row.get('status') or '未处理', 'warning': warning_text(row.get('warnings'))}
            for row in issues[:10]
        ],
    }


GOOD_STATUS = {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT', '已有PDF已汇总', 'METADATA_ONLY'}
PROBLEM_STATES = {'NO_ATTACHMENT', 'MISSING_FILE', 'INVALID_FILE', 'UNVERIFIED', 'NOT_IN_ZOTERO', 'ERROR'}


def checkpoint_rows(out):
    """Rows from manifest.json, else report.json; same precedence as progress."""
    folder = Path(out).expanduser()
    for name in ('manifest.json', 'report.json'):
        path = folder / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding='utf-8'))
        rows = payload.get('results', []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError(f'{name} must contain a list of records')
        return rows, name
    raise ValueError(f'No manifest.json or report.json in {folder}')


def reference_of(row):
    """Best identifier for re-running one row: DOI, then raw input."""
    paper = row.get('paper') or {}
    return str(paper.get('doi') or row.get('doi') or row.get('input') or '').strip()


def pdf_missing(row):
    pdf = row.get('pdf')
    return not (pdf and Path(pdf).is_file())


def audit_findings(rows, zotero):
    """Read-only attachment audit for checkpoint rows or collection items."""
    findings = []
    for row in rows:
        paper = row.get('paper') or {}
        base = {'doi': reference_of(row),
                'title': paper.get('title') or row.get('title') or ''}
        key = row.get('zotero_key')
        if not key:
            findings.append({**base, 'state': 'NOT_IN_ZOTERO', 'pdf_attachments': []})
            continue
        try:
            identity = paper if paper.get('title') and paper.get('doi') else None
            findings.append({**base, **core.attachment_health(zotero, key, identity)})
        except (core.PaperError, OSError) as error:
            findings.append({**base, 'state': 'ERROR', 'error': str(error), 'pdf_attachments': []})
    return findings


def format_audit(findings, source='checkpoint'):
    counts = Counter(item['state'] for item in findings)
    lines = ['paper-tool audit', f'Source: {source}', f'Checked: {len(findings)} item(s)',
             'States: ' + (', '.join(f'{name}={count}' for name, count in sorted(counts.items())) or 'none')]
    problems = [item for item in findings if item['state'] in PROBLEM_STATES]
    for item in problems[:20]:
        lines.append(f"  [{item['state']}] {item['title'][:70] or item['doi'] or 'Untitled'}")
    if len(problems) > 20:
        lines.append(f'  ... and {len(problems) - 20} more')
    duplicates = [item for item in findings if item['state'] == 'DUPLICATE']
    if duplicates:
        lines.append('Duplicate PDF attachments (resolve in Zotero; this tool never deletes):')
        for item in duplicates[:10]:
            missing = sum(1 for a in item['pdf_attachments'] if not a['exists'])
            lines.append(f"  [DUPLICATE] {item['title'][:60] or item['doi'] or 'Untitled'}"
                         f" — {len(item['pdf_attachments'])} PDF(s)"
                         + (f', {missing} unreadable' if missing else ''))
        if len(duplicates) > 10:
            lines.append(f'  ... and {len(duplicates) - 10} more')
    if problems:
        lines.append('Next: repair these in Zotero (file body first), then run: paper-tool failures --out <dir>')
    return '\n'.join(lines)


def format_progress(snapshot):
    if not snapshot['ok']:
        return 'Progress unavailable: ' + snapshot['error']
    percent = 0 if not snapshot['total'] else 100 * snapshot['valid_pdf'] / snapshot['total']
    updated = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snapshot['updated']))
    lines = [
        'paper-tool progress',
        f"Checkpoint: {snapshot['checkpoint']}",
        f"Source: {snapshot.get('source','manifest.json')}",
        f"Updated: {updated}",
        f"PDF files: {snapshot['valid_pdf']}/{snapshot['total']} ({percent:.1f}%)",
        f"Zotero attached: {snapshot['attached']} | existing attachments copied: {snapshot['existing_pdf']} | local only: {snapshot['saved_local']}"
        + (f" | metadata only: {snapshot['metadata']}" if snapshot.get('metadata') else ''),
        f"Pending: {snapshot['pending']} | review needed: {snapshot['review']} | other: {snapshot.get('other',0)}",
    ]
    if snapshot['issues']:
        lines.append('Recent issues:')
        for item in snapshot['issues']:
            warning = str(item['warning']).replace('\n', ' ')[:160] or 'Metadata needs review'
            lines.append(f"  #{item['number']} [{item['status']}] {item['title'][:80]} — {warning}")
    return '\n'.join(lines)


def run_reference(reference, args):
    metadata_only = bool(getattr(args, 'metadata_only', False))
    client = getattr(args, 'zotero_client', None)
    doi_index = getattr(args, 'doi_index', None)
    record, paper, confidence, note = None, None, 1.0, None
    if doi_index:
        doi = (core.doi_from(reference) or '').lower()
        hit = doi_index.get(doi)
        if hit is not None:
            paper = core.paper_from_zotero(hit)
            note = 'Reused metadata from the existing Zotero item'
    if paper is None:
        record, confidence = core.crossref_metadata(reference)
        paper = core.paper_from_crossref(record)
    out = Path(args.out).expanduser().resolve()
    filename = re.sub(r'[^A-Za-z0-9_.-]','_',paper['doi']).strip('._')+'.pdf'
    dest = out / filename
    result = {'paper':paper,'confidence':confidence,'status':'PREVIEW','pdf':None,
              'warnings':[note] if note else []}
    if args.command == 'preview':
        result['candidates'] = core.pdf_candidates(paper['doi'], errors=result['warnings'])
        return result
    out.mkdir(parents=True,exist_ok=True)
    if metadata_only:
        path, location, errors = None, None, []
    else:
        path, location, errors = None, None, []
        for candidate in batch_runner.local_pdf_candidates({'doi': paper['doi']}, [out]):
            valid, why = core.verify_pdf(candidate, paper)
            if valid:
                path, location = candidate, {'source': 'existing_local', 'version': 'unknown'}
                break
            errors.append('Local file retained but not reused: '+candidate.name+' ('+why+')')
        if path is None:
            path, location, download_errors = core.download_verified(
                paper, core.pdf_candidates(paper['doi'], errors=result['warnings']), out)
            errors.extend(download_errors)
    result['warnings'].extend(errors)
    if path is None and not args.oa_only and not metadata_only:
        # Cached Zotero metadata has no publisher links. Resolve them only when
        # OA retrieval failed, preserving the zero-lookup metadata-only path.
        if record is None:
            try:
                record, _ = core.crossref_metadata(paper['doi'])
            except core.PaperError as error:
                record = {}
                result['warnings'].append('Publisher metadata unavailable: '+str(error))
        pii = next((m.group(1) for link in record.get('link',[]) if (m:=re.search(r'/PII:([A-Z0-9]+)',link.get('URL','')))),None)
        if pii:
            candidate = dest if not dest.exists() else dest.with_name(dest.stem+'-browser.pdf')
            target, reused, notes = browser_output_path(candidate,paper)
            result['warnings'].extend(notes)
            if reused:
                path=target
            else:
                try:
                    process = subprocess.run(['node',str(ROOT/'paper_tool_assets'/'browser_pdf.mjs'),'--pii',pii,'--out',str(target),'--cdp',args.cdp,'--proxy',args.proxy],capture_output=True,text=True,timeout=180)
                except (OSError, subprocess.TimeoutExpired) as error:
                    process = SimpleNamespace(returncode=1, stderr='')
                    result['warnings'].append('Browser download did not complete: '+str(error))
                if process.returncode == 0 and target.exists():
                    valid, why = core.verify_pdf(target,paper)
                    if valid:
                        path=target
                        location={'source':'authorized_browser_via_vpn','version':'publishedVersion'}
                    else:
                        result['warnings'].append('Downloaded file needs review: '+why)
                else:
                    try:
                        result['warnings'].append(json.loads(process.stderr.strip().splitlines()[-1])['error']['message'])
                    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
                        pass
                    result['warnings'].append('Browser route needs attention; run paper-tool doctor and inspect the authorized browser.')
    if path:
        result.update(status='PDF_SAVED',pdf=str(path),sha256=core.pdf_sha256(path),location=location)
    else:
        result['status']='METADATA_ONLY' if metadata_only else 'PDF_PENDING'
    if args.zotero:
        try:
            z=client or core.ZoteroLocal(args.zotero_base)
            if path:
                result.update(batch_runner.attach_pdf(paper, path, args.collection,
                                                      args.zotero_base, z))
            else:
                selected,_=core.choose_collection(z,paper,args.collection)
                if selected is None:
                    result['zotero']='COLLECTION_REVIEW'
                    if metadata_only:
                        result['status']='NEEDS_REVIEW'
                else:
                    key,created=z.ensure_item(paper,selected['key'])
                    result.update(zotero_key=key,zotero='created' if created else 'reused',collection=selected['path'])
                    result['archive_state'] = {
                        'status': 'METADATA_SAVED', 'server_id': z.server_id,
                        'collection_key': selected['key'], 'collection': selected['path'],
                        'zotero_key': key,
                    }
        except (core.PaperError, OSError, ValueError) as error:
            result['zotero']='WRITE_PENDING'
            result['archive_state'] = {'status': 'PENDING'}
            if metadata_only:
                result['status']='NEEDS_REVIEW'
            result['warnings'].append('Zotero write not completed; any downloaded PDF is retained. '+str(error))
    result['download_state'] = ({'status': 'VERIFIED', 'pdf': str(path), 'sha256': result['sha256']}
                                if path else {'status': 'PENDING'})
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='paper-tool '+__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    doc = commands.add_parser('doctor',help='Check browser, Zotero and (if needed) VPN proxy ports')
    doc.add_argument('--proxy',default=DEFAULT_PROXY,help='Use direct for the native VPN route, or an HTTP proxy URL')
    doc.add_argument('--deep',action='store_true',help='Also check Node, Playwright, the debugging browser and Zotero authorization')
    doc.add_argument('--zotero-base',default=DEFAULT_ZOTERO)
    brw = commands.add_parser('browser',help='Check or start the dedicated browser used for subscription PDFs')
    brw.add_argument('--start',action='store_true',help='Start it when nothing is listening on the port')
    brw.add_argument('--check',action='store_true',help='Report the debugging endpoint only (default)')
    brw.add_argument('--chrome',help='Full path to chrome.exe / msedge.exe')
    brw.add_argument('--profile',default=str(Path.cwd()/'browser-profile'),help='Dedicated profile folder')
    brw.add_argument('--cdp',default=CDP_DEFAULT)
    brw.add_argument('--timeout',type=float,default=25.0)
    bat = commands.add_parser('batch',help='Run or resume any-length reference list from one command')
    bat.add_argument('--input',type=Path,required=True,help='UTF-8 references, one per line')
    bat.add_argument('--out',default=str(DEFAULT_OUT),help='Batch folder; manifest.json is its checkpoint')
    bat.add_argument('--pdf-dir',type=Path,help='Where PDFs go (default <out>/PDF)')
    bat.add_argument('--zotero',action='store_true',help='Explicitly allow Zotero writes')
    bat.add_argument('--collection',help='Existing collection full path; checked before the first write')
    bat.add_argument('--zotero-base',default=DEFAULT_ZOTERO)
    bat.add_argument('--proxy',default=DEFAULT_PROXY)
    bat.add_argument('--cdp',default=CDP_DEFAULT)
    bat.add_argument('--interval',type=float,default=30,help='Pause between papers that used the network')
    bat.add_argument('--oa-only',action='store_true',help='Open access only; never the institutional browser')
    bat.add_argument('--force',action='store_true',help='Re-run rows whose attachment is already confirmed')
    bat.add_argument('--dry-run',action='store_true',help='Print the plan; download nothing, write nothing')
    bat.add_argument('--metadata-only',action='store_true',
                     help='Import bibliographic records only; reuse Zotero metadata for known DOIs, never download PDFs')
    progress = commands.add_parser('progress',help='Show checkpointed batch progress and warnings')
    progress.add_argument('--out',default=str(DEFAULT_OUT),help='Folder containing manifest.json (falls back to report.json)')
    progress.add_argument('--watch',type=float,default=0,help='Refresh every N seconds; Ctrl+C stops watching')
    progress.add_argument('--json',action='store_true',help='Print machine-readable status')
    cols=commands.add_parser('collections',help='List existing Zotero collections with full paths (read-only)')
    cols.add_argument('--zotero-base',default=DEFAULT_ZOTERO)
    cols.add_argument('--json',action='store_true',help='Print machine-readable records')
    aud=commands.add_parser('audit',help='Read-only check that items have a readable PDF file in Zotero')
    aud.add_argument('--out',default=str(DEFAULT_OUT),help='Checkpoint folder (manifest.json or report.json)')
    aud.add_argument('--collection',help='Audit every item in this existing collection path instead')
    aud.add_argument('--zotero-base',default=DEFAULT_ZOTERO)
    aud.add_argument('--json',action='store_true',help='Print machine-readable findings')
    fail=commands.add_parser('failures',help='List papers still missing a verified PDF, ready for --input')
    fail.add_argument('--out',default=str(DEFAULT_OUT),help='Checkpoint folder (manifest.json or report.json)')
    fail.add_argument('--write',type=Path,help='Write the list to a UTF-8 file usable by fetch --input')
    fail.add_argument('--json',action='store_true',help='Print machine-readable result')
    fail.add_argument('--zotero',action='store_true',help='Include rows whose Zotero archival is incomplete')
    for command in ('fetch','preview'):
        p=commands.add_parser(command,help='Retrieve PDF' if command=='fetch' else 'Read-only metadata preview')
        p.add_argument('reference',nargs='?',help='DOI or full bibliographic reference')
        p.add_argument('--input',type=Path,help='UTF-8 references, one per line')
        p.add_argument('--out',default=str(DEFAULT_OUT))
        p.add_argument('--oa-only',action='store_true')
        p.add_argument('--proxy',default=DEFAULT_PROXY,help='Use direct for the native VPN route, or an HTTP proxy URL')
        p.add_argument('--cdp',default='http://127.0.0.1:18806')
        p.add_argument('--interval',type=float,default=30,help='Pause between papers; no transfer-rate limit')
        p.add_argument('--zotero',action='store_true',help='Explicitly allow Zotero writes (fetch only)')
        p.add_argument('--zotero-base',default=DEFAULT_ZOTERO)
        p.add_argument('--collection')
        p.add_argument('--skip-done',action='store_true',help='Skip references already completed in the existing report')
    args=parser.parse_args(argv)
    if args.command=='doctor':
        result=doctor(args.proxy,deep=args.deep,zotero_base=args.zotero_base);print(json.dumps(result,ensure_ascii=False));return 0 if result['ok'] else 2
    if args.command=='browser':
        if args.timeout<=0:parser.error('--timeout must be positive')
        result=start_browser(args.profile,args.chrome,args.cdp,args.timeout) if args.start else cdp_status(args.cdp)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['ok'] else 2
    if args.command=='batch':
        if args.interval<0:parser.error('--interval cannot be negative')
        if args.metadata_only and not args.zotero:
            parser.error('--metadata-only requires --zotero and --collection')
        if args.zotero and not args.collection:
            parser.error('--zotero requires an existing --collection path')
        if args.zotero:
            from urllib.parse import urlparse
            u=urlparse(args.zotero_base)
            if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.username or u.password:parser.error('Zotero must use a loopback address; use SSH forwarding')
        try:
            refs=read_references(args.input)
        except (OSError,ValueError) as error:
            print(f'Cannot read {args.input}: {error}',file=sys.stderr)
            return 2
        if not refs:
            print(f'No references found in {args.input}; put one DOI per line, or use # to comment',file=sys.stderr)
            return 2
        core.PDF_RATE_KIB=0
        try:
            summary=batch_runner.run_batch(
                refs,args.out,zotero=args.zotero,collection=args.collection,proxy=args.proxy,
                cdp=args.cdp,interval=args.interval,oa_only=args.oa_only,pdf_dir=args.pdf_dir,
                zotero_base=args.zotero_base,force=args.force,dry_run=args.dry_run,
                metadata_only=args.metadata_only)
        except (core.PaperError,OSError,ValueError) as error:
            print(f'Batch could not start: {error}',file=sys.stderr)
            return 2
        if args.dry_run:
            for row in summary.get('rows',[]):
                print(json.dumps(row,ensure_ascii=False))
        print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))
        print(batch_runner.format_summary(summary),file=sys.stderr)
        return 0 if summary['ok'] or args.dry_run else 2
    if args.command=='progress':
        if args.watch < 0: parser.error('--watch cannot be negative')
        try:
            while True:
                result = progress_snapshot(args.out)
                print(json.dumps(result,ensure_ascii=False) if args.json else format_progress(result), flush=True)
                if not args.watch:
                    return 0 if result['ok'] else 2
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0
    if args.command=='collections':
        from urllib.parse import urlparse
        u=urlparse(args.zotero_base)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.username or u.password:parser.error('Zotero must use a loopback address; use SSH forwarding')
        try:
            rows=core.ZoteroLocal(args.zotero_base).collections()
        except (core.PaperError,OSError) as error:
            print(f'Zotero unavailable: {error}', file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(rows,ensure_ascii=False))
        else:
            for row in sorted(rows,key=lambda x:x['path']):
                print(f"{row['path']}\t{row['key']}")
        return 0
    if args.command in {'audit','failures'}:
        from urllib.parse import urlparse
        if args.command=='failures':
            try:
                rows,_source=checkpoint_rows(args.out)
            except (OSError,ValueError) as error:
                print(f'Checkpoint unavailable: {error}', file=sys.stderr)
                return 2
            pending=[row for row in rows if not core.checkpoint_pdf_valid(row)
                     or (args.zotero and (row.get('status') not in {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT'}
                                          or row.get('zotero') in {'WRITE_PENDING', 'COLLECTION_REVIEW'}))]
            refs=list(dict.fromkeys(ref for ref in (reference_of(row) for row in pending) if ref))
            if args.json:
                print(json.dumps({'source':_source,'pending':len(refs),'references':refs},ensure_ascii=False))
            else:
                for ref in refs:
                    print(ref)
                if not refs:
                    print('Nothing pending: every checkpointed paper has a verified PDF.')
            if args.write:
                target=args.write.expanduser()
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text('\n'.join(refs)+('\n' if refs else ''),encoding='utf-8')
                print(f'Wrote {len(refs)} reference(s) to {target}', file=sys.stderr)
            return 0
        u=urlparse(args.zotero_base)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.username or u.password:parser.error('Zotero must use a loopback address; use SSH forwarding')
        try:
            z=core.ZoteroLocal(args.zotero_base)
        except (core.PaperError,OSError) as error:
            print(f'Zotero unavailable: {error}', file=sys.stderr)
            return 2
        if args.collection:
            cols=z.collections()
            match=[c for c in cols if c['path']==args.collection] or [c for c in cols if c['name']==args.collection]
            if len(match)!=1:
                print(f'Collection missing or ambiguous: {args.collection}; run collections', file=sys.stderr)
                return 2
            _source='collection:'+match[0]['path']
            raw=z.all_pages(f"/users/0/collections/{match[0]['key']}/items?itemType=-attachment")
            rows=[{'zotero_key':(item.get('data') or item).get('key'),'paper':{'doi':(item.get('data') or item).get('DOI',''),'title':(item.get('data') or item).get('title','')}} for item in raw]
        else:
            try:
                rows,_source=checkpoint_rows(args.out)
            except (OSError,ValueError) as error:
                print(f'Checkpoint unavailable: {error}', file=sys.stderr)
                return 2
        findings=audit_findings(rows,z)
        counts=Counter(item['state'] for item in findings)
        problems=[item for item in findings if item['state'] in PROBLEM_STATES]
        if args.json:
            print(json.dumps({'source':args.collection or _source,'total':len(findings),'states':dict(counts),'problems':problems},ensure_ascii=False))
        else:
            print(format_audit(findings, args.collection or _source))
        return 2 if problems else 0
    if bool(args.reference)==bool(args.input):parser.error('Supply either one reference or --input')
    if args.interval<0:parser.error('--interval cannot be negative')
    if args.command=='preview' and args.zotero:parser.error('preview never writes Zotero')
    if args.command=='preview' and args.skip_done:parser.error('--skip-done only applies to fetch')
    if args.zotero:
        from urllib.parse import urlparse
        u=urlparse(args.zotero_base)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.username or u.password:parser.error('Zotero must use a loopback address; use SSH forwarding')
        if not args.collection:
            parser.error('--zotero requires an existing --collection path')
    if args.reference is not None and not args.reference.strip():
        parser.error('Reference cannot be empty')
    try:
        refs=[args.reference.strip()] if args.reference else read_references(args.input)
    except (OSError,ValueError) as error:
        parser.error(str(error))
    if not refs:
        parser.error(f'No references found in {args.input}; put one DOI per line, or use # to comment')
    core.PDF_RATE_KIB=0
    results=[]
    history=[]
    report_path=Path(args.out).expanduser()/'report.json'
    if args.command=='fetch' and report_path.exists():
        try:history=json.loads(report_path.read_text(encoding='utf-8')).get('results',[])
        except (OSError,ValueError):parser.error('Existing report is unreadable; choose another output folder')
    if args.skip_done and not args.zotero:
        done=set()
        for row in history:
            if batch_runner.row_done(row):
                for name in (reference_of(row).lower(), str(row.get('input') or '').strip().lower()):
                    if name:
                        done.add(name)
        before=len(refs)
        refs=[ref for ref in refs if ref.strip().lower() not in done]
        if len(refs)!=before:
            print(f'Skipped {before-len(refs)} already-completed paper(s).', file=sys.stderr)
        if not refs:
            print('Nothing to do: every reference is already completed.', file=sys.stderr)
            return 0
    for i,ref in enumerate(refs):
        if i and args.command=='fetch':time.sleep(args.interval)
        try:result=run_reference(ref,args)
        except (core.PaperError,OSError,ValueError,subprocess.TimeoutExpired) as error:
            result={'status':'NEEDS_REVIEW','error':type(error).__name__, 'warnings':[str(error)]}
        result['input']=ref
        results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if args.command=='fetch':
            target=Path(args.out).expanduser();target.mkdir(parents=True,exist_ok=True)
            rows=merge_report(history,results)
            temp=target/'report.json.tmp';temp.write_text(json.dumps({'results':rows},ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target/'report.json')
    good={'PDF_SAVED','PDF_ATTACHED','PDF_ALREADY_PRESENT'} if args.command=='fetch' else {'PREVIEW'}
    return 0 if results and all(r['status'] in good and r.get('zotero') not in {'COLLECTION_REVIEW','WRITE_PENDING'} for r in results) else 2


if __name__=='__main__':
    raise SystemExit(main())
