"""Offline tests for batch-level caching and the --metadata-only fast path."""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_tool import batch as b
from paper_tool import reports as deliverables
from paper_tool import core
from paper_tool import cli as t


def bare_client():
    """ZoteroLocal without __init__ (no network, no DPAPI)."""
    z = core.ZoteroLocal.__new__(core.ZoteroLocal)
    z.base = core.BASE
    z.server_id = 'test'
    z.key = ''
    z._items_cache = None
    z._collections_cache = None
    return z


def fetch_args(out, **extra):
    args = argparse.Namespace(command='fetch', out=str(out), oa_only=False, zotero=True,
                              proxy='direct', cdp='http://127.0.0.1:18806',
                              zotero_base=core.BASE, collection='A/B')
    for key, value in extra.items():
        setattr(args, key, value)
    return args


class CacheTests(unittest.TestCase):
    def test_items_reads_the_library_only_once(self):
        z = bare_client()
        payload = [{'data': {'key': 'K1', 'DOI': '10.1/a', 'itemType': 'journalArticle'}}]
        with patch.object(z, 'all_pages', return_value=payload) as pages:
            self.assertEqual(len(z.items()), 1)
            self.assertEqual(len(z.items()), 1)
            pages.assert_called_once()

    def test_collections_are_cached_too(self):
        z = bare_client()
        payload = [{'data': {'key': 'C', 'name': 'B', 'itemType': 'collection'}}]
        with patch.object(z, 'all_pages', return_value=payload) as pages:
            self.assertEqual(len(z.collections()), 1)
            self.assertEqual(len(z.collections()), 1)
            pages.assert_called_once()

    def test_new_item_updates_cache_instead_of_forcing_a_rescan(self):
        z = bare_client()
        z._items_cache = []
        response = {'successful': {'0': {'data': {'key': 'NEW', 'itemType': 'journalArticle',
                                                  'DOI': '10.1/new'}}}}
        with patch.object(z, 'call', return_value=(response, {})):
            z.write_item({'itemType': 'journalArticle'})
        self.assertEqual([x['key'] for x in z._items_cache], ['NEW'])

    def test_attachment_write_does_not_pollute_the_item_cache(self):
        z = bare_client()
        z._items_cache = []
        response = {'successful': {'0': {'data': {'key': 'ATT', 'itemType': 'attachment'}}}}
        with patch.object(z, 'call', return_value=(response, {})):
            z.write_item({'itemType': 'attachment'})
        self.assertEqual(z._items_cache, [])

    def test_paper_from_zotero_maps_journal_and_conference_fields(self):
        journal = core.paper_from_zotero({
            'itemType': 'journalArticle', 'title': 'A paper', 'DOI': '10.1/A',
            'publicationTitle': 'Information Sciences', 'date': '2026-03-01',
            'volume': '755', 'pages': '123800',
            'creators': [{'creatorType': 'author', 'firstName': 'Yinghua', 'lastName': 'Liu'}],
        })
        self.assertEqual(journal['doi'], '10.1/a')
        self.assertEqual(journal['year'], '2026')
        self.assertEqual(journal['journal'], 'Information Sciences')
        self.assertEqual(journal['authors'], [{'first': 'Yinghua', 'last': 'Liu'}])
        self.assertEqual(journal['type'], 'journal-article')

        conference = core.paper_from_zotero({
            'itemType': 'conferencePaper', 'title': 'B paper', 'DOI': '10.2/b',
            'proceedingsTitle': 'NeurIPS 38', 'conferenceName': 'NeurIPS 2025',
            'eventPlace': 'San Diego', 'date': '2025',
        })
        self.assertEqual(conference['journal'], 'NeurIPS 38')
        self.assertEqual(conference['type'], 'proceedings-article')
        self.assertEqual(conference['event_place'], 'San Diego')


class MetadataOnlyTests(unittest.TestCase):
    def test_no_download_and_metadata_only_status(self):
        with tempfile.TemporaryDirectory() as out:
            z = MagicMock()
            z.ensure_item.return_value = ('KEY', False)
            args = fetch_args(out, metadata_only=True, zotero_client=z)
            with patch.object(t.core, 'crossref_metadata', return_value=(t.core.SAMPLE_RECORD, 1)), \
                 patch.object(t.core, 'pdf_candidates') as candidates, \
                 patch.object(t.core, 'download_verified') as download, \
                 patch.object(t.core, 'choose_collection', return_value=({'key': 'C', 'path': 'A/B'}, 1)):
                result = t.run_reference('10.1000/x', args)
            candidates.assert_not_called()
            download.assert_not_called()
            self.assertEqual(result['status'], 'METADATA_ONLY')
            self.assertEqual(result['zotero'], 'reused')
            self.assertEqual(result['zotero_key'], 'KEY')

    def test_known_doi_reuses_zotero_metadata_without_crossref(self):
        with tempfile.TemporaryDirectory() as out:
            z = MagicMock()
            z.ensure_item.return_value = ('KEY', False)
            item = {'itemType': 'journalArticle', 'title': 'Already here',
                    'DOI': '10.1000/x', 'date': '2024', 'publicationTitle': 'J'}
            args = fetch_args(out, metadata_only=True, zotero_client=z,
                              doi_index={'10.1000/x': item})
            with patch.object(t.core, 'crossref_metadata') as crossref, \
                 patch.object(t.core, 'pdf_candidates') as candidates, \
                 patch.object(t.core, 'choose_collection', return_value=({'key': 'C', 'path': 'A/B'}, 1)):
                result = t.run_reference('10.1000/x', args)
            crossref.assert_not_called()
            candidates.assert_not_called()
            self.assertEqual(result['paper']['title'], 'Already here')
            self.assertTrue(any('Reused' in w for w in result['warnings']))

    def test_zotero_failure_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as out:
            args = fetch_args(out, metadata_only=True)
            with patch.object(t.core, 'crossref_metadata', return_value=(t.core.SAMPLE_RECORD, 1)), \
                 patch.object(t.core, 'ZoteroLocal', side_effect=t.core.PaperError('offline')):
                result = t.run_reference('10.1000/x', args)
            self.assertEqual(result['status'], 'NEEDS_REVIEW')
            self.assertEqual(result['zotero'], 'WRITE_PENDING')

    def test_unresolved_collection_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as out:
            z = MagicMock()
            args = fetch_args(out, metadata_only=True, zotero_client=z)
            with patch.object(t.core, 'crossref_metadata', return_value=(t.core.SAMPLE_RECORD, 1)), \
                 patch.object(t.core, 'choose_collection', return_value=(None, [])):
                result = t.run_reference('10.1000/x', args)
            self.assertEqual(result['status'], 'NEEDS_REVIEW')
            self.assertEqual(result['zotero'], 'COLLECTION_REVIEW')

    def test_default_mode_still_downloads(self):
        with tempfile.TemporaryDirectory() as out:
            args = fetch_args(out)
            with patch.object(t.core, 'crossref_metadata', return_value=(t.core.SAMPLE_RECORD, 1)), \
                 patch.object(t.core, 'pdf_candidates', return_value=[]) as candidates, \
                 patch.object(t.core, 'download_verified', return_value=(None, None, [])) as download:
                result = t.run_reference('10.1000/x', args)
            candidates.assert_called_once()
            download.assert_called_once()
            self.assertEqual(result['status'], 'PDF_PENDING')

    def test_batch_reuses_one_client_and_builds_doi_index(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            z = MagicMock()
            z.collections.return_value = [{'key': 'C', 'name': 'B', 'path': 'A/B'}]
            z.items.return_value = [{'key': 'K1', 'DOI': '10.1/a'}]
            seen = []

            def runner(ref, args):
                seen.append(args)
                return {'status': 'METADATA_ONLY', 'paper': {'doi': ref, 'title': 'T'},
                        'warnings': []}

            with patch.object(b.core, 'ZoteroLocal', return_value=z) as factory:
                summary = b.run_batch(['10.1/a'], out, zotero=True, collection='A/B',
                                      interval=0, metadata_only=True, runner=runner)
            factory.assert_called_once()
            self.assertIs(seen[0].zotero_client, z)
            self.assertTrue(seen[0].metadata_only)
            self.assertIn('10.1/a', seen[0].doi_index)
            self.assertEqual(summary['metadata'], 1)
            self.assertTrue(summary['ok'])

    def test_default_batch_does_not_pay_for_a_doi_index(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'batch'
            z = MagicMock()
            z.collections.return_value = [{'key': 'C', 'name': 'B', 'path': 'A/B'}]
            seen = []

            def runner(ref, args):
                seen.append(args)
                return {'status': 'PDF_PENDING', 'warnings': []}

            with patch.object(b.core, 'ZoteroLocal', return_value=z):
                b.run_batch(['10.1/a'], out, zotero=True, collection='A/B',
                            interval=0, runner=runner)
            z.items.assert_not_called()
            self.assertIsNone(seen[0].doi_index)
            self.assertIs(seen[0].zotero_client, z)


class StatusContractTests(unittest.TestCase):
    def test_good_status_is_identical_across_all_three_modules(self):
        self.assertEqual(t.GOOD_STATUS, b.GOOD_STATUS)
        self.assertEqual(t.GOOD_STATUS, deliverables.GOOD_STATUS)
        self.assertIn('METADATA_ONLY', t.GOOD_STATUS)

    def test_progress_counts_metadata_only_without_inflating_review(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'manifest.json').write_text(
                json.dumps([{'number': 1, 'status': 'METADATA_ONLY', 'input': '10.1/a'}]),
                encoding='utf-8')
            snapshot = t.progress_snapshot(d)
        self.assertEqual(snapshot['other'], 0)
        self.assertEqual(snapshot['review'], 0)
        self.assertEqual(snapshot['metadata'], 1)
        self.assertEqual(snapshot['issues'], [])
        self.assertIn('metadata only: 1', t.format_progress(snapshot))

    def test_merge_report_exposes_latest_failure_after_metadata_only(self):
        history = [{'input': '10.1/a', 'status': 'METADATA_ONLY'}]
        results = [{'input': '10.1/a', 'status': 'NEEDS_REVIEW'}]
        merged = t.merge_report(history, results)
        self.assertEqual(merged[0]['status'], 'NEEDS_REVIEW')
        self.assertEqual(merged[0]['previous_status'], 'METADATA_ONLY')


if __name__ == '__main__':
    unittest.main()
