"""Generic, list-driven batch engine for paper-tool.

One checkpoint per batch folder (``manifest.json``, keyed by the input line), so
any list size works: 3 papers or 300. Every stage is code, not a manual step:

1. merge the reference list into the checkpoint (existing rows are never dropped)
2. reuse a PDF that is already on disk and passes identity verification
3. otherwise resolve -> download -> verify -> attach through ``paper_tool``
4. rewrite the checkpoint atomically after every paper

Nothing here deletes a file, overwrites an existing PDF, creates a collection or
bypasses a verification challenge. Re-running the same command only continues
the rows that are not confirmed yet.
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import paper_to_zotero as core

# Identical to paper_tool.GOOD_STATUS: the attachment is confirmed. Kept as a
# separate copy so this module stays importable on its own; a test asserts that
# the two sets never drift apart.
GOOD_STATUS = {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT', '已有PDF已汇总', 'METADATA_ONLY'}
MANIFEST = 'manifest.json'


def _stamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _warnings(result):
    value = (result or {}).get('warnings')
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def _emit(payload, stream):
    print(json.dumps(payload, ensure_ascii=False), file=stream, flush=True)


def _safe_stem(value):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', str(value or '')).strip('._')


def load_rows(out):
    """Rows from the batch checkpoint; an unreadable checkpoint is never overwritten."""
    path = Path(out) / MANIFEST
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(f'{path} is unreadable ({error}); keep or move it aside first')
    rows = payload.get('results', []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f'{path} must contain a list of records')
    if any(not str(row.get('input') or '').strip() for row in rows if isinstance(row, dict)):
        # Older batch scripts keyed rows by "reference"; merging would duplicate
        # every row because nothing matches an input line.
        raise ValueError(f'{path} was written by an older batch script (rows have no "input" field); '
                         'use a new --out folder for batch, or keep using that legacy script')
    return rows


def save_rows(out, rows):
    """Atomic replace, so an interrupted write cannot truncate the checkpoint."""
    target = Path(out) / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(MANIFEST + '.tmp')
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(target)


def merge_rows(rows, refs):
    """One row per new input line; rows outside the list are kept as history."""
    seen = {str(row.get('input') or '').strip().lower() for row in rows if row.get('input')}
    number = max([int(row.get('number') or 0) for row in rows] or [0])
    for ref in refs:
        key = str(ref).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        number += 1
        rows.append({'number': number, 'input': str(ref).strip(), 'status': '',
                     'pdf': '', 'attempts': 0, 'warnings': []})
    return rows


def row_done(row, *, zotero=False, metadata_only=False):
    """A download can be skipped; an archive always needs live confirmation.

    This deliberately rechecks Zotero membership and attachment health on every
    archival run, even if a checkpoint claims success in another collection.
    """
    if zotero or metadata_only:
        return False
    if row.get('status') not in GOOD_STATUS | {'PDF_SAVED'}:
        return False
    return core.checkpoint_pdf_valid(row)


def local_pdf_candidates(row, folders):
    """PDF files on disk that may belong to this row, best guess first."""
    stems = [_safe_stem(row.get('doi')), _safe_stem(row.get('input'))]
    stems = [stem for stem in dict.fromkeys(stems) if len(stem) >= 6]
    found = []
    if row.get('pdf') and Path(row['pdf']).is_file():
        found.append(Path(row['pdf']))
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for stem in stems:
            for path in sorted(folder.glob(stem + '*.pdf')):
                if path.is_file() and path not in found:
                    found.append(path)
    return found


def resolve_collection(path, zotero_base, client=None):
    """Fail before the first write when the configured collection is wrong."""
    zotero = client or core.ZoteroLocal(zotero_base)
    collections = zotero.collections()
    exact = [item for item in collections if item['path'] == path]
    if len(exact) == 1:
        return exact[0], None
    named = [item for item in collections if item['name'] == path]
    if len(named) == 1:
        return named[0], None
    if len(named) > 1:
        return None, f'Collection name is ambiguous: {path}; use the full path from paper-tool collections'
    return None, f'Collection not found: {path}; run paper-tool collections and copy the full path'


def attach_pdf(paper, pdf, collection, zotero_base, client=None):
    """Reuse or create the item, then attach at most one PDF."""
    zotero = client or core.ZoteroLocal(zotero_base)
    selected, _candidates = core.choose_collection(zotero, paper, collection)
    if selected is None:
        return {'status': 'PDF_SAVED', 'zotero': 'COLLECTION_REVIEW',
                'archive_state': {'status': 'PENDING'},
                'warnings': ['Target collection unresolved; pass --collection with a full path']}
    key, created = zotero.ensure_item(paper, selected['key'])
    update = {'zotero_key': key, 'collection': selected['path'],
              'zotero': 'created' if created else 'reused'}
    update.update(zotero.ensure_pdf(key, pdf, paper))
    update['archive_state'] = {
        'status': update['status'], 'server_id': zotero.server_id,
        'collection_key': selected['key'], 'collection': selected['path'],
        'zotero_key': key, 'attachment_key': update.get('attachment_key'),
    }
    return update


def _plan(row, folders):
    """Static, offline plan for --dry-run: no request, no write."""
    candidates = local_pdf_candidates(row, folders)
    route = 'open-access, then browser fallback (ScienceDirect PII required)'
    if candidates:
        return {'action': 'recover', 'reason': f'{len(candidates)} local PDF candidate(s)',
                'candidates': [str(path) for path in candidates], 'route_estimate': route}
    return {'action': 'download', 'reason': 'no local PDF', 'route_estimate': route}


def known_paper(row):
    """Reconstruct the minimum identity a checkpoint row already holds."""
    if row.get('paper'):
        return dict(row['paper'])
    doi = str(row.get('doi') or row.get('input') or '').strip()
    title = str(row.get('title') or '').strip()
    if not doi or not title:
        return None
    authors = row.get('authors')
    if isinstance(authors, str):
        parts = [part.strip() for part in authors.split(';') if part.strip()]
        authors = [{'first': '', 'last': name.split()[-1]} for name in parts]
    return {'doi': doi.lower(), 'title': title, 'authors': authors or [],
            **{key: row.get(key) or '' for key in ('year', 'journal', 'volume', 'issue', 'pages', 'url')}}


def _process(row, ref, folders, options, runner):
    """Return (row update, whether a network request was made)."""
    rejected = []
    # A metadata-only task must not inspect, recover or attach local PDFs.
    candidates = [] if options.get('metadata_only') else local_pdf_candidates(row, folders)
    if candidates:
        # A checkpoint row may already carry DOI and title, which is enough to
        # verify a local file when Crossref cannot be reached at all.
        paper = known_paper(row)
        used_network = paper is None
        if paper is None:
            record, _score = core.crossref_metadata(ref)
            paper = core.paper_from_crossref(record)
        for candidate in candidates:
            valid, why = core.verify_pdf(candidate, paper)
            if not valid:
                rejected.append(f'Local file kept but not reused: {candidate.name} ({why})')
                continue
            update = {'doi': paper['doi'], 'title': paper['title'], 'paper': paper,
                      'pdf': str(candidate), 'sha256': core.pdf_sha256(candidate),
                      'source': 'local_file', 'verification': why, 'status': 'PDF_SAVED'}
            if options['zotero']:
                try:
                    update.update(attach_pdf(paper, candidate, options['collection'],
                                             options['zotero_base'],
                                             options.get('zotero_client')))
                except (core.PaperError, OSError, ValueError) as error:
                    update.update(zotero='WRITE_PENDING', warnings=[str(error)])
                    update['archive_state'] = {'status': 'PENDING'}
            update['warnings'] = rejected + _warnings(update)
            return update, used_network

    args = SimpleNamespace(command='fetch', out=str(folders[0]), oa_only=options['oa_only'],
                           proxy=options['proxy'], cdp=options['cdp'],
                           zotero=options['zotero'], zotero_base=options['zotero_base'],
                           collection=options['collection'],
                           metadata_only=options.get('metadata_only', False),
                           zotero_client=options.get('zotero_client'),
                           doi_index=options.get('doi_index'))
    result = runner(ref, args)
    paper = result.get('paper') or {}
    update = {'doi': paper.get('doi') or row.get('doi', ''), 'paper': paper,
              'title': paper.get('title') or row.get('title', ''),
              'status': result.get('status', 'NEEDS_REVIEW'),
              'pdf': result.get('pdf') or (row.get('pdf') if options.get('metadata_only') else '') or '',
              'zotero_key': result.get('zotero_key', ''),
              'attachment_key': result.get('attachment_key', ''),
              'source': 'downloaded',
              'warnings': rejected + _warnings(result)}
    if result.get('zotero'):
        update['zotero'] = result['zotero']
    if update['pdf']:
        update['sha256'] = (row.get('sha256') if options.get('metadata_only') else
                            result.get('sha256') or core.pdf_sha256(Path(update['pdf'])))
    if result.get('archive_state'):
        update['archive_state'] = result['archive_state']
    return update, True


def _succeeded(row, zotero_requested, metadata_only=False):
    if zotero_requested and row.get('zotero') in {'WRITE_PENDING', 'COLLECTION_REVIEW'}:
        return False
    if metadata_only:
        return row.get('status') == 'METADATA_ONLY'
    if zotero_requested and row.get('status') not in {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT'}:
        return False
    return row.get('status') in GOOD_STATUS | {'PDF_SAVED'} and core.checkpoint_pdf_valid(row)


def format_summary(summary):
    lines = [
        'paper-tool batch',
        f"Checkpoint: {summary['checkpoint']}",
        f"References: {summary['total']} | skipped this run: {summary['skipped']}",
        f"Attached: {summary['attached']} | already present: {summary['already']} | local only: {summary['saved']}",
        f"Pending: {summary['pending']} | needs review: {summary['review']}"
        + (f" | metadata only: {summary['metadata']}" if summary.get('metadata') else ''),
    ]
    if summary.get('dry_run'):
        lines.append('Dry run: nothing was downloaded and no file was written.')
    elif summary.get('ok'):
        lines.append('All tracked rows are confirmed.')
    else:
        lines.append('Next: read the warnings, fix the cause, then run the same command again; '
                     'finished rows are skipped.')
    return '\n'.join(lines)


def run_batch(refs, out, *, zotero=False, collection=None, proxy='direct',
              cdp='http://127.0.0.1:18806', interval=30.0, oa_only=False,
              pdf_dir=None, zotero_base=None, force=False, dry_run=False,
              runner=None, sleeper=None, stream=None, metadata_only=False):
    """Run one batch over ``refs``; returns a summary dict (also printed as JSON)."""
    out = Path(out).expanduser().resolve()
    folders = [Path(pdf_dir).expanduser().resolve()] if pdf_dir else [out / 'PDF']
    if zotero_base is None:
        zotero_base = core.BASE
    if stream is None:
        stream = sys.stdout
    if runner is None:
        import paper_tool
        runner = paper_tool.run_reference
    sleep = sleeper or time.sleep
    if metadata_only and not zotero:
        raise ValueError('--metadata-only requires --zotero')
    if zotero and not collection:
        raise ValueError('--zotero requires an existing --collection path')

    refs = [str(ref).strip() for ref in refs if str(ref).strip()]
    unique = {}
    for ref in refs:
        unique.setdefault(ref.lower(), ref)
    refs = list(unique.values())
    if not refs:
        raise ValueError('No references to process')

    rows = load_rows(out)
    merge_rows(rows, refs)
    index = {str(row.get('input') or '').strip().lower(): row for row in rows}
    tracked = [index[ref.lower()] for ref in refs]

    client, doi_index = None, None
    if zotero and not dry_run:
        # One connection and one full-library read for the whole batch instead
        # of repeating both for every reference (21 paginated GETs per row).
        client = core.ZoteroLocal(zotero_base)
        _match, problem = resolve_collection(collection, zotero_base, client)
        if problem:
            raise ValueError(problem)
        if metadata_only and not dry_run:
            doi_index = {str(x.get('DOI') or '').lower(): x
                         for x in client.items() if x.get('DOI')}

    options = {'zotero': zotero, 'collection': collection, 'proxy': proxy, 'cdp': cdp,
               'oa_only': oa_only, 'zotero_base': zotero_base,
               'metadata_only': metadata_only, 'zotero_client': client,
               'doi_index': doi_index}

    summary = {'batch': str(out), 'checkpoint': str(out / MANIFEST), 'total': len(tracked),
               'dry_run': dry_run, 'skipped': 0, 'attached': 0, 'already': 0, 'saved': 0,
               'pending': 0, 'review': 0, 'metadata': 0, 'ok': False}
    if dry_run:
        summary['rows'] = []
    else:
        save_rows(out, rows)

    for position, row in enumerate(tracked):
        ref = str(row.get('input'))
        if row_done(row, zotero=zotero, metadata_only=metadata_only) and not force:
            summary['skipped'] += 1
            if dry_run:
                summary['rows'].append({'number': row.get('number'), 'input': ref,
                                        'status': row.get('status'), 'action': 'skip'})
            continue
        if dry_run:
            summary['rows'].append({'number': row.get('number'), 'input': ref,
                                    'status': row.get('status') or '',
                                    **({'action': 'metadata', 'reason': 'import bibliographic records only'}
                                       if metadata_only else _plan(row, folders))})
            continue

        started = time.monotonic()
        row['attempts'] = int(row.get('attempts') or 0) + 1
        try:
            update, network = _process(row, ref, folders, options, runner)
        except (core.PaperError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            update, network = ({'status': 'NEEDS_REVIEW', 'error': type(error).__name__,
                               'warnings': [str(error)]}, False)
            if zotero:
                update['archive_state'] = {'status': 'PENDING'}
        row.update(update)
        if row.get('pdf') and core.checkpoint_pdf_valid(row):
            row['download_state'] = {'status': 'VERIFIED', 'pdf': row['pdf'],
                                     'sha256': row.get('sha256') or core.pdf_sha256(Path(row['pdf']))}
        else:
            row['download_state'] = {'status': 'PENDING'}
        row['seconds'] = round(time.monotonic() - started, 1)
        row['updated'] = _stamp()
        save_rows(out, rows)
        _emit({'number': row.get('number'), 'input': ref, 'status': row.get('status'),
               'doi': row.get('doi', ''), 'pdf': row.get('pdf', ''),
               'zotero_key': row.get('zotero_key', ''),
               'warnings': _warnings(row)}, stream)
        if network and position < len(tracked) - 1:
            sleep(interval)

    counts = Counter(str(row.get('status') or '未处理') for row in tracked)
    summary.update(attached=counts['PDF_ATTACHED'], already=counts['PDF_ALREADY_PRESENT'],
                   saved=counts['PDF_SAVED'], pending=counts['PDF_PENDING'],
                   review=counts['NEEDS_REVIEW'], metadata=counts['METADATA_ONLY'])
    summary['ok'] = all(_succeeded(row, zotero, metadata_only) for row in tracked)
    return summary
