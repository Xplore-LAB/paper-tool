#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reports 模块的离线测试：只读性、三种检查点格式、18 列台账、xlsx 合法性、汇报数字自洽。

全部使用 tempfile，不触碰真实批次目录、不联网、不打开任何 PDF。
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from paper_tool import reports as d


def write_json(folder, name, payload, encoding='utf-8'):
    path = Path(folder) / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding=encoding)
    return path


def read_sheet_texts(xlsx, sheet='xl/worksheets/sheet1.xml'):
    with zipfile.ZipFile(xlsx) as archive:
        root = ET.fromstring(archive.read(sheet))
    ns = {'m': d.NS}
    cells = root.findall('.//m:c', ns)
    return (root, ns, [''.join(t.text or '' for t in cell.findall('.//m:t', ns))
                       for cell in cells])


REPORT_ROWS = [
    {
        'input': 'Y. Liu et al. Long-term demand prediction. Information Sciences, 2026.',
        'status': 'PDF_ATTACHED',
        'pdf': None,
        'warnings': [],
        'paper': {'title': 'Long-term demand prediction', 'doi': '10.1016/j.ins.2026.123800',
                  'url': 'https://doi.org/10.1016/j.ins.2026.123800',
                  'authors': ['Y. Liu', 'S. Shao'], 'year': '2026',
                  'journal': 'Information Sciences', 'volume': '755', 'pages': '123800',
                  'type': 'journal-article'},
        'collection': 'My Library/Papers',
        'pdf_candidates': [{'source': 'institutional_publisher', 'url': 'https://x/y.pdf'}],
        'zotero_key': 'ABC12345',
    },
    {
        'input': 'No DOI reference at all',
        'status': 'NEEDS_REVIEW',
        'pdf': None,
        'warnings': ['Crossref match below threshold'],
        'paper': {'title': '=SUM(1+1) 题名以等号开头', 'doi': '', 'url': ''},
    },
]

LEGACY_ROWS = [
    {
        'number': 7, 'reference': 'Zuhua Xu. Nonlinear MPC using an Identified LPV Model. 2009.',
        'title': 'Nonlinear MPC using an Identified LPV Model', 'doi': '10.1021/ie801057q',
        'status': '已有PDF已汇总', 'pdf': r'C:\tmp\paper.pdf', 'sha256': 'a' * 64,
        'first_author': 'Z. Xu', 'year': '2009',
        'journal': 'Industrial & Engineering Chemistry Research',
        'volume': '48', 'issue': '7', 'pages': '3400-3410', 'type': 'journal-article',
        'verification': '已有附件，未逐页核读', 'in_collection': True,
        'zotero_key': '379QASIK', 'warnings': '',
    },
]

BATCH_ROWS = [
    {'number': 1, 'input': '10.1109/CDC.2020.1234567', 'status': 'PDF_SAVED',
     'doi': '10.1109/CDC.2020.1234567', 'title': 'A control paper',
     'container_title': 'Proceedings of the 59th IEEE Conference on Decision and Control',
     'type': 'proceedings-article', 'year': '2020',
     'pdf': r'C:\tmp\ieee.pdf', 'sha256': 'b' * 64, 'warnings': []},
    {'number': 2, 'input': 'Another reference without DOI', 'status': 'PDF_PENDING',
     'pdf': '', 'warnings': ['Security verification required']},
]

PROGRESS = {'ok': True, 'source': 'manifest.json', 'total': 3, 'valid_pdf': 2,
            'attached': 1, 'existing_pdf': 1, 'saved_local': 0, 'pending': 1,
            'review': 0, 'other': 0, 'statuses': {}, 'issues': []}

AUDIT = {'source': 'manifest.json', 'total': 3,
         'states': {'OK': 2, 'NO_ATTACHMENT': 1, 'MISSING_FILE': 1, 'DUPLICATE': 1},
         'problems': [{'state': 'MISSING_FILE', 'title': 'A control paper', 'doi': '10.1109/x'}]}

FAILURES = {'source': 'manifest.json', 'pending': 1, 'references': ['10.1109/x']}


class LedgerTests(unittest.TestCase):
    def test_report_json_18_columns_and_bibliographic_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'report.json', {'mode': 'fetch', 'results': REPORT_ROWS})
            info = d.build_ledger(tmp, group='工业智能组')
            self.assertTrue(info['ok'])
            self.assertEqual(info['source'], 'report.json')
            self.assertEqual(info['rows'], 2)
            self.assertEqual(info['columns'], 18)
            self.assertEqual(info['unique_inputs'], 2)
            self.assertEqual(info['missing_doi'], 1)
            self.assertEqual(info['missing_url'], 1)
            rows = d.normalize_rows(REPORT_ROWS, group='工业智能组')
            first, second = rows
            self.assertEqual(len(first), 18)
            self.assertEqual(first[4], 'Y. Liu')
            self.assertEqual(first[5], '2026')
            self.assertEqual(first[6], '期刊')
            self.assertEqual(first[7], 'Information Sciences')
            self.assertEqual(first[8], '755:123800')
            self.assertEqual(first[9], '10.1016/j.ins.2026.123800')
            self.assertEqual(first[11], '工业智能组')
            self.assertEqual(first[12], d.TODO)
            self.assertEqual(first[15], 'My Library/Papers')
            self.assertEqual(first[16], 'PDF_ATTACHED')
            self.assertEqual(second[9], d.MISSING)
            self.assertEqual(second[10], d.MISSING)
            self.assertIn('DOI 缺失', second[17])
            self.assertNotIn('SHA256', ''.join(map(str, first)))

    def test_legacy_manifest_and_batch_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'manifest.json', LEGACY_ROWS)
            info = d.build_ledger(tmp)
            self.assertEqual(info['source'], 'manifest.json')
            legacy = d.normalize_rows(LEGACY_ROWS)[0]
            self.assertEqual(legacy[0], 7)
            self.assertEqual(legacy[1], LEGACY_ROWS[0]['reference'])
            self.assertEqual(legacy[4], 'Z. Xu')
            self.assertEqual(legacy[6], '期刊')
            self.assertEqual(legacy[8], '48(7):3400-3410')
            self.assertEqual(legacy[11], d.TODO)
            self.assertEqual(legacy[16], '已有PDF已汇总')
        batch = d.normalize_rows(BATCH_ROWS, collection='我的分类', group='控制组')
        self.assertEqual(batch[0][6], '会议')
        self.assertIn('Decision and Control', batch[0][7])
        self.assertEqual(batch[0][8], d.DASH)
        self.assertEqual(batch[0][11], '控制组')
        self.assertEqual(batch[0][15], '我的分类')
        self.assertEqual(batch[0][16], '仅本地（未附加）')
        self.assertEqual(batch[1][9], d.MISSING)
        self.assertEqual(batch[1][16], '待补')
        self.assertIn('Security verification', batch[1][17])

    def test_conference_detection_without_explicit_type(self):
        rows = [
            {'input': '10.1145/3376890', 'doi': '10.1145/3376890',
             'container_title': 'Proceedings of the ACM Conference', 'status': 'PDF_SAVED'},
            {'input': '10.48550/arXiv.2401.00001', 'doi': '10.48550/arXiv.2401.00001',
             'status': 'PDF_SAVED'},
            {'input': '10.1007/978-3-030-12345-6_7',
             'doi': '10.1007/978-3-030-12345-6_7',
             'container_title': 'Lecture Notes in Computer Science', 'volume': '12001',
             'status': 'PDF_SAVED'},
            {'input': 'no clues', 'status': 'PDF_PENDING'},
        ]
        kinds = [row[6] for row in d.normalize_rows(rows)]
        self.assertEqual(kinds, ['会议', '预印本', '会议', d.MISSING])

    def test_html_entities_in_journal_name(self):
        rows = [{'input': 'x', 'status': 'PDF_SAVED',
                 'journal': 'Computers &amp; Chemical Engineering'}]
        self.assertEqual(d.normalize_rows(rows)[0][7], 'Computers & Chemical Engineering')

    def test_crossref_author_dict_is_formatted(self):
        rows = [{'input': 'x', 'status': 'PDF_SAVED',
                 'paper': {'authors': [{'given': 'Yinghua', 'family': 'Liu'},
                                       {'given': 'Zuhua', 'family': 'Xu'}]}}]
        self.assertEqual(d.normalize_rows(rows)[0][4], 'Yinghua Liu')

    def test_rank_and_group_from_checkpoint(self):
        rows = [{'input': 'x', 'status': 'PDF_SAVED', 'group': 'A 组', 'rank': 'CCF-A'}]
        row = d.normalize_rows(rows)[0]
        self.assertEqual(row[11], 'A 组')
        self.assertEqual(row[12], 'CCF-A')

    def test_normalize_does_not_mutate_input(self):
        before = copy.deepcopy(REPORT_ROWS)
        d.normalize_rows(REPORT_ROWS)
        self.assertEqual(REPORT_ROWS, before)

    def test_xlsx_structure_inline_string_and_formula_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            info = d.build_ledger(tmp)
            with zipfile.ZipFile(info['xlsx']) as archive:
                names = set(archive.namelist())
                self.assertIn('[Content_Types].xml', names)
                self.assertIn('xl/workbook.xml', names)
                self.assertIn('xl/styles.xml', names)
                self.assertIn('xl/worksheets/sheet2.xml', names)
                sheet = archive.read('xl/worksheets/sheet1.xml')
            root, ns, texts = read_sheet_texts(info['xlsx'])
            self.assertEqual(root.find('m:dimension', ns).get('ref'), 'A1:R3')
            self.assertIsNotNone(root.find('m:autoFilter', ns))
            self.assertEqual(texts[:18], d.HEADERS)
            self.assertIn('=SUM(1+1) 题名以等号开头', texts)
            self.assertNotIn(b'<f>', sheet)
            self.assertIn(b't="inlineStr"', sheet)
            self.assertIn('Information Sciences', texts)

    def test_all_rows_have_non_empty_doi_and_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'manifest.json', BATCH_ROWS)
            d.build_ledger(tmp)
            for row in d.normalize_rows(BATCH_ROWS):
                self.assertTrue(row[9].strip())
                self.assertTrue(row[10].strip())

    def test_checkpoint_never_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            before = path.read_bytes()
            d.build_ledger(tmp)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             ['report.json', '文献清单.xlsx'])


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        write_json(self.folder, 'manifest.json', BATCH_ROWS)
        self.progress = write_json(self.folder, 'progress.json', PROGRESS)
        self.audit = write_json(self.folder, 'audit.json', AUDIT)
        self.failures = write_json(self.folder, 'failures.json', FAILURES)

    def tearDown(self):
        self.tmp.cleanup()

    def test_numbers_match_sources(self):
        result = d.build_summary(self.folder, progress_json=str(self.progress),
                                 audit_json=str(self.audit),
                                 failures_json=str(self.failures),
                                 collection='我的分类')
        numbers = result['numbers']
        self.assertEqual(numbers['total'], 3)
        self.assertEqual(numbers['success'], 2)
        self.assertEqual(numbers['attached'], 1)
        self.assertEqual(numbers['existing_pdf'], 1)
        self.assertEqual(numbers['pending'], 1)
        self.assertEqual(numbers['valid_pdf'], 2)
        self.assertEqual(numbers['audit_total'], 3)
        self.assertEqual(numbers['failures_pending'], 1)
        self.assertTrue(result['audit_available'])
        text = result['text']
        for fragment in ('| OK | 2 |', '| MISSING_FILE | 1 |', '| DUPLICATE | 1 |',
                         '成功（已附加 / 已有附件 / 仅本地） | 2', '退出码 0 ≠',
                         '未由本工具核验', '我的分类'):
            self.assertIn(fragment, text)
        self.assertTrue((self.folder / '完成情况汇报.md').is_file())

    def test_missing_audit_is_explicit_not_fabricated(self):
        result = d.build_summary(self.folder, progress_json=str(self.progress),
                                 audit_json=str(self.folder / 'none.json'))
        self.assertIsNone(result['numbers']['audit_total'])
        self.assertFalse(result['audit_available'])
        self.assertIn('不臆造', result['text'])
        self.assertIn('未提供 `audit --json` 快照', result['text'])
        self.assertTrue(any('audit' in w for w in result['warnings']))
        self.assertNotIn('| OK |', result['text'])

    def test_utf16_powershell_snapshot_supported(self):
        # Windows PowerShell 5.1 的 `>` 重定向默认写 UTF-16LE
        utf16 = self.folder / 'progress-utf16.json'
        utf16.write_text(json.dumps(PROGRESS, ensure_ascii=False), encoding='utf-16')
        result = d.build_summary(self.folder, progress_json=str(utf16))
        self.assertEqual(result['numbers']['total'], 3)
        self.assertEqual(result['numbers']['success'], 2)

    def test_checkpoint_only_fallback_progress(self):
        for name in ('progress.json', 'audit.json', 'failures.json'):
            (self.folder / name).unlink()
        result = d.build_summary(self.folder)
        self.assertEqual(result['numbers']['total'], 2)
        self.assertEqual(result['numbers']['attached'], 0)
        self.assertIn('progress_snapshot', result['text'])
        self.assertFalse(result['audit_available'])


class CliTests(unittest.TestCase):
    def test_missing_checkpoint_returns_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = d.main(['ledger', '--out', tmp, '--json'])
            self.assertEqual(code, 2)

    def test_both_command_writes_two_files_with_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            write_json(tmp, 'progress.json', PROGRESS)
            code = d.main(['both', '--out', tmp, '--group', '控制组', '--json'])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / '文献清单.xlsx').is_file())
            self.assertTrue((Path(tmp) / '完成情况汇报.md').is_file())
            rows = d.normalize_rows(REPORT_ROWS, group='控制组')
            self.assertEqual(rows[0][11], '控制组')


class ChineseTitleTests(unittest.TestCase):
    def test_header_order_and_placeholder(self):
        self.assertEqual(d.HEADERS[2], '题名')
        self.assertEqual(d.HEADERS[3], '中文题名')
        self.assertEqual(len(d.HEADERS), 18)
        self.assertEqual(len(d.WIDTHS), 18)
        self.assertEqual(len(d.COLUMN_MEANINGS), 18)
        rows = d.normalize_rows(REPORT_ROWS)
        self.assertEqual(rows[0][3], d.TRANSLATE_TODO)
        self.assertEqual(rows[0][2], 'Long-term demand prediction')

    def test_mapping_by_doi_and_by_english_title(self):
        mapping = {
            '10.1016/j.ins.2026.123800': '供氧网络长期需求预测',
            '=sum(1+1) 题名以等号开头': '以等号开头的中文题名',
        }
        rows = d.normalize_rows(REPORT_ROWS, translations=mapping)
        self.assertEqual(rows[0][3], '供氧网络长期需求预测')
        self.assertEqual(rows[1][3], '以等号开头的中文题名')

    def test_chinese_original_title_is_reused(self):
        rows = d.normalize_rows([{'input': '中文文献', 'status': 'PDF_SAVED',
                                  'title': '多产品空分供气网络生产调度'}])
        self.assertEqual(rows[0][3], '多产品空分供气网络生产调度')

    def test_translation_file_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, d.TRANSLATION_FILE, {
                'items': [{'doi': '10.1016/j.ins.2026.123800',
                           'title': 'Long-term demand prediction',
                           'title_zh': '长期需求预测'}]
            })
            mapping, path = d.load_translations(tmp)
            self.assertTrue(path.endswith(d.TRANSLATION_FILE))
            self.assertEqual(d.translation_of('Long-term demand prediction',
                                              '10.1016/j.ins.2026.123800', mapping),
                             '长期需求预测')
            self.assertEqual(d.translation_of('Long-term demand prediction', '', mapping),
                             '长期需求预测')

    def test_build_ledger_reads_mapping_and_reports_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            write_json(tmp, d.TRANSLATION_FILE,
                       {'10.1016/j.ins.2026.123800': '供氧网络长期需求预测'})
            info = d.build_ledger(tmp)
            self.assertEqual(info['columns'], 18)
            self.assertEqual(info['translated'], 1)
            self.assertEqual(info['untranslated'], 1)
            rows = d.normalize_rows(REPORT_ROWS,
                                    translations=d.load_translations(tmp)[0])
            self.assertEqual(rows[0][3], '供氧网络长期需求预测')
            self.assertEqual(rows[1][3], d.TRANSLATE_TODO)
            root, ns, texts = read_sheet_texts(info['xlsx'], 'xl/worksheets/sheet2.xml')
            self.assertTrue(any('中文题名' in t for t in texts))
            self.assertTrue(any('1/2' in t for t in texts))

    def test_checkpoint_unchanged_when_translation_file_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            mapping = write_json(tmp, d.TRANSLATION_FILE, {'10.1016/j.ins.2026.123800': '译文'})
            before = (checkpoint.read_bytes(), mapping.read_bytes())
            d.build_ledger(tmp)
            self.assertEqual((checkpoint.read_bytes(), mapping.read_bytes()), before)

    def test_translate_todo_creates_template_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            first = d.build_translation_template(tmp)
            self.assertEqual(first['added'], 2)
            self.assertEqual(first['todo'], 2)
            template = json.loads((Path(tmp) / d.TRANSLATION_FILE).read_text(encoding='utf-8'))
            template['10.1016/j.ins.2026.123800'] = '供氧网络长期需求预测'
            (Path(tmp) / d.TRANSLATION_FILE).write_text(
                json.dumps(template, ensure_ascii=False), encoding='utf-8')
            second = d.build_translation_template(tmp)
            self.assertEqual(second['added'], 0)
            self.assertEqual(second['translated'], 1)
            self.assertEqual(second['todo'], 1)
            self.assertEqual(d.load_translations(tmp)[0]['10.1016/j.ins.2026.123800'],
                             '供氧网络长期需求预测')

    def test_translate_todo_cli_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'manifest.json', BATCH_ROWS)
            code = d.main(['translate-todo', '--out', tmp, '--json'])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / d.TRANSLATION_FILE).is_file())

    def test_bad_translation_file_returns_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(tmp, 'report.json', {'results': REPORT_ROWS})
            (Path(tmp) / d.TRANSLATION_FILE).write_text('{ not json', encoding='utf-8')
            self.assertEqual(d.main(['ledger', '--out', tmp, '--json']), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
