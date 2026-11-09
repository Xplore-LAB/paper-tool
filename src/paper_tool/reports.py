#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper-tool 交付物导出：只读生成 Excel 台账 + 完成情况汇报。

设计依据：SOP-文献批量下载入库.md §5 (A4 台账) / §8 (B6 汇报) / §9 (E1-E4)。

只读约束（本文件的硬边界）：
  * 只读取 --out 下的 manifest.json / report.json / 标题翻译.json 以及可选的 CLI JSON 快照；
  * 只写 Excel 台账、完成情况汇报，以及 translate-todo 生成的待译清单；不改检查点；
  * 不打开/解析已下载 PDF 的内容（仅 stat 判断文件是否存在）；
  * 不联网、不调用 Zotero 本地 API、不写 Zotero；译文由 Agent / 人工写进映射文件；
  * Excel 用 OOXML 直接写出，仅依赖 Python 标准库，不新增 requirements。

用法：
  python -m paper_tool.reports translate-todo --out <批次目录>     # 生成/补齐 标题翻译.json
  python -m paper_tool.reports ledger  --out <批次目录> [--xlsx <路径>] [--translations f]
  python -m paper_tool.reports summary --out <批次目录> [--progress-json f] [--audit-json f]
  python -m paper_tool.reports both    --out <批次目录> [--collection ...] [--group ...]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

HEADERS = [
    '序号', '原始条目', '题名', '中文题名', '第一作者', '年份', '类型', '期刊或会议名称',
    '卷期页', 'DOI', '页面 URL', '课题组', '分级', '下载状态',
    '本地 PDF 路径', 'Zotero 分类', '附件状态', '备注',
]
WIDTHS = [6, 48, 50, 46, 18, 8, 10, 34, 18, 30, 46, 18, 14, 22, 56, 40, 22, 56]
MISSING = '待核验'
TODO = '待填'
DASH = '—'
TRANSLATE_TODO = '待翻译'
TRANSLATION_FILE = '标题翻译.json'
DOI_RE = re.compile(r'10\.\d{4,9}/[^\s,;]+', re.I)
YEAR_RE = re.compile(r'(19|20)\d{2}')
CJK_RE = re.compile(r'[\u4e00-\u9fff]')
GOOD_STATUS = {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT', '已有PDF已汇总', 'METADATA_ONLY'}
ATTACH_STATUS = {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT', '已有PDF已汇总'}
PROBLEM_STATES = {'NO_ATTACHMENT', 'MISSING_FILE', 'NOT_IN_ZOTERO', 'ERROR'}

TYPE_WORDS = {
    'journal-article': '期刊', 'journal_article': '期刊', 'journalArticle': '期刊',
    'proceedings-article': '会议', 'proceedings_article': '会议',
    'conference-paper': '会议', 'conference_paper': '会议', 'conferencePaper': '会议',
    'posted-content': '预印本', 'preprint': '预印本',
}
CONFERENCE_WORDS = ('proceeding', 'conference', 'workshop', 'symposium', 'lecture notes',
                    'lncs', '会议', '论文集')
JOURNAL_PREFIXES = ('10.1016', '10.1002', '10.1021', '10.1038', '10.1080',
                    '10.1371', '10.3390', '10.1103', '10.1063')
CONFERENCE_PREFIXES = ('10.1145', '10.1109')

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PNS = 'http://schemas.openxmlformats.org/package/2006/relationships'


# ---------------------------------------------------------------- 通用小工具

def _s(value):
    """把任意检查点字段压成可读字符串。"""
    if value is None:
        return ''
    if isinstance(value, (list, tuple, set)):
        return '; '.join(_s(v) for v in value if v not in (None, '', [], {}))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return html.unescape(str(value).strip())


def _pick(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, '', [], {}):
            return value
    return None


def _esc(text):
    """XML 文本转义 + 剔除 OOXML 不允许的控制字符。"""
    kept = []
    for ch in str(text):
        code = ord(ch)
        if code in (9, 10, 13) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD \
                or 0x10000 <= code <= 0x10FFFF:
            kept.append(ch)
    value = ''.join(kept)
    return (value.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _col(number):
    letters = ''
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _load_json(path):
    """兼容 UTF-8 / UTF-8 BOM / GBK / PowerShell 重定向产生的 UTF-16。"""
    target = Path(path).expanduser()
    try:
        raw = target.read_bytes()
    except OSError as error:
        return None, f'无法读取 {target}: {error}'
    try:
        if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
            text = raw.decode('utf-16')
        else:
            text = None
            for encoding in ('utf-8-sig', 'gbk'):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                return None, f'{target} 编码无法识别'
        return json.loads(text), None
    except (UnicodeDecodeError, ValueError) as error:
        return None, f'{target} 不是合法 JSON: {error}'


def load_checkpoint(out):
    """与 paper_tool.checkpoint_rows 相同的优先级：manifest.json > report.json。"""
    folder = Path(out).expanduser()
    if not folder.is_dir():
        raise ValueError(f'批次目录不存在：{folder}')
    for name in ('manifest.json', 'report.json'):
        path = folder / name
        if not path.exists():
            continue
        payload, error = _load_json(path)
        if error:
            raise ValueError(error)
        rows = payload.get('results', []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError(f'{name} 必须包含记录列表')
        return [row for row in rows if isinstance(row, dict)], name, path
    raise ValueError(f'{folder} 下没有 manifest.json 或 report.json')


# ---------------------------------------------------------------- 中文题名映射
# 本模块不联网、不自带翻译模型。译文由 Agent 或人工写进批次目录的
# 「标题翻译.json」，导出时只读合并；这样译文可复核、可改写、可复用。

def _translation_items(payload):
    """支持 {DOI 或英文题名: 中文} 与 [{doi,title,title_zh}, ...] 两种写法。"""
    if isinstance(payload, dict):
        if isinstance(payload.get('items'), list):
            return payload['items']
        return [{'key': key, 'title_zh': value} for key, value in payload.items()
                if isinstance(value, str)]
    if isinstance(payload, list):
        return payload
    return []


def load_translations(out, explicit=''):
    """读取译文映射，返回 (小写 key -> 中文题名, 文件路径)。文件不存在返回空字典。"""
    path = Path(explicit).expanduser() if explicit else Path(out).expanduser() / TRANSLATION_FILE
    if not path.is_file():
        return {}, str(path)
    payload, error = _load_json(path)
    if error:
        raise ValueError(error)
    mapping = {}
    for item in _translation_items(payload):
        if not isinstance(item, dict):
            continue
        zh = _s(item.get('title_zh') or item.get('zh') or item.get('中文题名'))
        if not zh:
            continue
        for key in (item.get('doi'), item.get('title'), item.get('key')):
            if isinstance(key, str) and key.strip():
                mapping[key.strip().lower()] = zh
    return mapping, str(path)


def _is_chinese_title(title):
    """汉字过半才算中文原题名，避免个别中文字符的英文题名被误判。"""
    text = _s(title)
    if not text:
        return False
    han = len(CJK_RE.findall(text))
    return han >= 2 and han / max(1, len(text.replace(' ', ''))) >= 0.5


def translation_of(title, doi, mapping):
    """先按 DOI 命中，再按英文题名命中；题名本身是中文则直接沿用。"""
    for key in (doi, title):
        lookup = _s(key).lower()
        if lookup and lookup in mapping:
            return mapping[lookup]
    if _is_chinese_title(title):
        return _s(title)
    return TRANSLATE_TODO


def build_translation_template(out, rows=None, source_name=''):
    """生成/补齐「标题翻译.json」：保留已有译文，只为新题名补空值。"""
    folder = Path(out).expanduser()
    if rows is None:
        rows, source_name, _ = load_checkpoint(out)
    path = folder / TRANSLATION_FILE
    existing, _ = _load_json(path) if path.is_file() else (None, None)
    template = {}
    if isinstance(existing, dict) and not isinstance(existing.get('items'), list):
        template = {key: value for key, value in existing.items() if isinstance(value, str)}
    added = 0
    chinese = 0
    for row in rows:
        paper = row.get('paper') if isinstance(row.get('paper'), dict) else {}
        title = _s(_pick(row, 'title', 'input_title') or paper.get('title'))
        doi = _s(paper.get('doi') or row.get('doi'))
        key = (doi or title).lower()
        if not key or key in template:
            continue
        if _is_chinese_title(title):
            chinese += 1
            continue
        template[key] = ''
        added += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    translated = sum(1 for value in template.values() if _s(value))
    return {'ok': True, 'file': str(path.resolve()), 'source': source_name,
            'total': len(template), 'translated': translated,
            'added': added, 'chinese_skipped': chinese,
            'todo': len(template) - translated}


# ------------------------------------------------------------ 18 列台账归一化

def author_name(value):
    if isinstance(value, dict):
        family = _s(value.get('family') or value.get('last'))
        given = _s(value.get('given') or value.get('first'))
        if family or given:
            return (given + ' ' + family).strip()
        return _s(value.get('name'))
    return _s(value)


def first_author_of(row, paper):
    authors = _pick(row, 'first_author', 'author') or paper.get('authors') or paper.get('author')
    if isinstance(authors, (list, tuple)):
        return author_name(authors[0]) if authors else ''
    return author_name(authors)


def year_of(row, paper):
    value = _s(_pick(row, 'year', 'date') or paper.get('year') or paper.get('published'))
    found = YEAR_RE.search(value)
    return found.group(0) if found else ''


def container_of(row, paper):
    return _s(_pick(row, 'container_title', 'journal', 'publicationTitle',
                    'proceedingsTitle', 'event') or
              paper.get('journal') or paper.get('container_title'))


def volume_pages_of(row, paper):
    volume = _s(_pick(row, 'volume') or paper.get('volume'))
    issue = _s(_pick(row, 'issue') or paper.get('issue'))
    pages = _s(_pick(row, 'pages', 'page') or paper.get('pages'))
    parts = []
    if volume:
        parts.append(volume)
    if issue:
        parts.append('(' + issue + ')')
    if pages:
        parts.append(':' + pages)
    return ''.join(parts) if parts else DASH


def kind_of(row, paper, doi, container):
    """优先用题录里的类型；否则按会议名关键词、DOI 前缀与卷期信息推断。"""
    explicit = _s(_pick(row, 'type', 'itemType') or paper.get('type')).lower()
    if explicit in TYPE_WORDS:
        return TYPE_WORDS[explicit]
    if any(word in container.lower() for word in CONFERENCE_WORDS):
        return '会议'
    if doi != MISSING and doi.lower().startswith('10.48550'):
        return '预印本'
    if doi != MISSING and doi.lower().startswith(CONFERENCE_PREFIXES) \
            and not _s(_pick(row, 'volume') or paper.get('volume')):
        return '会议'
    if doi != MISSING and doi.lower().startswith(JOURNAL_PREFIXES):
        return '期刊'
    if container and volume_pages_of(row, paper) != DASH:
        return '期刊'
    return MISSING


def rank_of(row, paper):
    return _s(_pick(row, 'rank', 'quartile', 'ccf', 'jcr', 'impact_factor') or
              paper.get('rank')) or TODO


def normalize_rows(rows, collection='', group='', translations=None):
    """把新旧三种检查点行统一成 18 列；不修改入参。"""
    translations = translations or {}
    result = []
    for index, row in enumerate(rows, 1):
        paper = row.get('paper') if isinstance(row.get('paper'), dict) else {}
        candidates = row.get('pdf_candidates') or row.get('candidates') or []
        if not isinstance(candidates, list):
            candidates = []

        raw_input = _s(_pick(row, 'input', 'reference'))
        title = _s(_pick(row, 'title', 'input_title') or paper.get('title'))
        doi = _s(paper.get('doi') or row.get('doi'))
        if not doi and raw_input:
            found = DOI_RE.search(raw_input)
            doi = found.group(0).rstrip('.,;)') if found else ''
        doi = doi or MISSING

        url = _s(paper.get('url') or row.get('url'))
        if not url and doi != MISSING:
            url = 'https://doi.org/' + doi
        if not url and candidates and isinstance(candidates[0], dict):
            url = _s(candidates[0].get('url'))
        url = url or MISSING

        number = _pick(row, 'number')
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = index

        container = container_of(row, paper)
        status = _s(row.get('status')) or '未处理'
        pdf = _s(row.get('pdf'))
        zotero_collection = _s(row.get('collection')) or _s(collection) or '待确认'

        if status in ATTACH_STATUS:
            attachment = status
        elif _s(row.get('zotero')) in ('COLLECTION_REVIEW', 'WRITE_PENDING'):
            attachment = _s(row['zotero'])
        elif status == 'PDF_SAVED':
            attachment = '仅本地（未附加）'
        elif status in ('PDF_PENDING', '待下载', 'PDF_PENDING_VERIFY'):
            attachment = '待补'
        else:
            attachment = DASH

        notes = []
        warnings = row.get('warnings')
        if warnings:
            notes.append(_s(warnings))
        if _s(row.get('verification')):
            notes.append(_s(row['verification']))
        if doi == MISSING:
            notes.append('DOI 缺失，需人工核验题录')
        if url == MISSING:
            notes.append('页面 URL 缺失，需人工补录')
        if not pdf:
            notes.append('本地 PDF 未获取')
        else:
            try:
                if not Path(pdf).is_file():
                    notes.append('检查点记录的 PDF 文件当前不存在')
            except OSError:
                notes.append('PDF 路径无法访问')
        if status in ('PDF_PENDING', '待下载', 'NEEDS_REVIEW', '题录待核验', '待核验/补全'):
            notes.append('待办：需补下载或人工核验')
        if zotero_collection == '待确认':
            notes.append('Zotero 分类待用户确认')

        result.append([
            number,
            raw_input or title or MISSING,
            title or MISSING,
            translation_of(title, doi, translations),
            first_author_of(row, paper) or MISSING,
            year_of(row, paper) or MISSING,
            kind_of(row, paper, doi, container),
            container or MISSING,
            volume_pages_of(row, paper),
            doi,
            url,
            _s(group) or _s(row.get('group') or paper.get('group')) or TODO,
            rank_of(row, paper),
            status,
            pdf or DASH,
            zotero_collection,
            attachment,
            '; '.join(dict.fromkeys(n for n in notes if n)) or DASH,
        ])
    return result


# ------------------------------------------------------------------- xlsx 写出

def _cell(ref, value, style):
    if isinstance(value, int) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    text = _s(value)
    if len(text) > 32000:
        text = text[:32000] + ' ...(truncated)'
    # inlineStr 明确标记为字符串，标题以 = / + / - 开头也不会被当成公式
    return (f'<c r="{ref}" s="{style}" t="inlineStr"><is>'
            f'<t xml:space="preserve">{_esc(text)}</t></is></c>')


def _sheet_xml(headers, rows, widths, autofilter=True):
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{NS}">',
        f'<dimension ref="A1:{_col(len(headers))}{len(rows) + 1}"/>',
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        '<cols>',
    ]
    for index, width in enumerate(widths, 1):
        out.append(f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>')
    out.append('</cols><sheetData><row r="1" ht="28" customHeight="1">')
    for index, header in enumerate(headers, 1):
        out.append(_cell(f'{_col(index)}1', header, 1))
    out.append('</row>')
    for row_index, row in enumerate(rows, 2):
        out.append(f'<row r="{row_index}">')
        for column_index, value in enumerate(row, 1):
            out.append(_cell(f'{_col(column_index)}{row_index}', value, 0))
        out.append('</row>')
    out.append('</sheetData>')
    if autofilter and rows:
        out.append(f'<autoFilter ref="A1:{_col(len(headers))}{len(rows) + 1}"/>')
    out.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" '
               'header="0.3" footer="0.3"/>')
    out.append('</worksheet>')
    return ''.join(out)


STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{NS}">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF2F5597"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''

ROOT_RELS = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PNS}">
<Relationship Id="rId1" Type="{RNS}/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

WORKBOOK = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{NS}" xmlns:r="{RNS}"><sheets>
<sheet name="文献清单" sheetId="1" r:id="rId1"/>
<sheet name="说明" sheetId="2" r:id="rId2"/>
</sheets></workbook>'''

WORKBOOK_RELS = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PNS}">
<Relationship Id="rId1" Type="{RNS}/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="{RNS}/worksheet" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Type="{RNS}/styles" Target="styles.xml"/>
</Relationships>'''


def write_xlsx(path, ledger_rows, notes_rows):
    """零依赖写出双工作表 xlsx。"""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    parts = {
        '[Content_Types].xml': CONTENT_TYPES,
        '_rels/.rels': ROOT_RELS,
        'xl/workbook.xml': WORKBOOK,
        'xl/_rels/workbook.xml.rels': WORKBOOK_RELS,
        'xl/styles.xml': STYLES,
        'xl/worksheets/sheet1.xml': _sheet_xml(HEADERS, ledger_rows, WIDTHS),
        'xl/worksheets/sheet2.xml': _sheet_xml(['项目', '说明'], notes_rows, [26, 110], False),
    }
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode('utf-8'))
    return target


COLUMN_MEANINGS = [
    '清单行号；与 manifest.json 的 number 对应，缺失时用行序',
    '用户给的参考文献原文 / DOI；新旧检查点分别取 input / reference',
    'Crossref 题名；依次取 title / input_title / paper.title',
    '中文题名；读批次目录「标题翻译.json」（key 可为 DOI 或英文题名），中文原题名直接沿用，未译写「待翻译」',
    '第一作者；取 authors 的第一项，缺失写「待核验」',
    '出版年份；从 year / date / published 中取四位年份',
    '期刊 / 会议 / 预印本；优先题录 type，否则按会议名关键词、DOI 前缀与卷期推断',
    '期刊名或会议名；container-title 对期刊是刊名、对会议是论文集名',
    '卷(期):页码；缺失写「—」，会议论文通常为空',
    '题录 DOI；查不到写「待核验」',
    'paper.url 优先；无则按 DOI 生成 https://doi.org/<DOI>',
    '课题组；由 --group 或检查点 group 字段填写，否则「待填」',
    '分级；期刊填中科院分区 / 影响因子，会议填 CCF 等级，由插件或人工填写',
    '检查点原始 status，便于与 progress / audit 对齐',
    '检查点记录的本地 PDF 路径；仅判断文件是否存在',
    '用户确认后的完整层级分类路径；未提供 --collection 时写「待确认」',
    'PDF_ATTACHED / PDF_ALREADY_PRESENT / 仅本地 / 待补 等派生状态',
    'warnings + verification + 待办提示',
]


def build_ledger(out, xlsx=None, collection='', group='', translations=''):
    rows, source_name, checkpoint = load_checkpoint(out)
    mapping, translations_path = load_translations(out, translations)
    ledger_rows = normalize_rows(rows, collection, group, mapping)
    folder = Path(out).expanduser()
    target = Path(xlsx).expanduser() if xlsx else folder / '文献清单.xlsx'
    unique_inputs = len({_s(_pick(r, 'input', 'reference')).lower() for r in rows
                         if _s(_pick(r, 'input', 'reference'))})
    missing_doi = sum(1 for row in ledger_rows if row[9] == MISSING)
    missing_url = sum(1 for row in ledger_rows if row[10] == MISSING)
    kinds = Counter(row[6] for row in ledger_rows)
    translated = sum(1 for row in ledger_rows if row[3] != TRANSLATE_TODO)
    notes = [
        ['生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        ['检查点', f'{source_name} · {checkpoint.resolve()}'],
        ['记录条数', str(len(ledger_rows)) + f'（按原始条目去重后 {unique_inputs} 条）'],
        ['类型分布', '、'.join(f'{k} {v} 条' for k, v in sorted(kinds.items()))],
        ['DOI / URL 待核验', f'{missing_doi} 条 / {missing_url} 条'],
        ['中文题名', f'{translated}/{len(ledger_rows)} 条已译；映射文件 {translations_path}'
                    + (f'（跳过 {len(ledger_rows) - translated} 条，写「{TRANSLATE_TODO}」）'
                       if translated < len(ledger_rows) else '')],
        ['Zotero 分类', collection or '待确认'],
        ['课题组', group or '未指定（列内写「待填」）'],
        ['页面 URL', '按 DOI 规范构造的解析页，不代表已访问出版社页面'],
    ]
    notes += [[f'第 {i} 列 · {HEADERS[i - 1]}', meaning]
              for i, meaning in enumerate(COLUMN_MEANINGS, 1)]
    written = write_xlsx(target, ledger_rows, notes)
    return {
        'ok': True,
        'xlsx': str(written.resolve()),
        'source': source_name,
        'checkpoint': str(checkpoint.resolve()),
        'rows': len(ledger_rows),
        'columns': len(HEADERS),
        'unique_inputs': unique_inputs,
        'missing_doi': missing_doi,
        'missing_url': missing_url,
        'translated': translated,
        'untranslated': len(ledger_rows) - translated,
        'translations_file': translations_path,
        'collection': collection or '待确认',
        'group': group or TODO,
        'kinds': dict(kinds),
    }


# --------------------------------------------------------------- 完成情况汇报

COUNTED_STATUS = {'PDF_ATTACHED', 'PDF_ALREADY_PRESENT', '已有PDF已汇总', 'PDF_SAVED',
                  'PDF_PENDING', '待下载', '待核验/补全', 'NEEDS_REVIEW'}


def local_progress(rows, source_name):
    """未能导入 paper_tool 时的同口径兜底统计（纯检查点，不连 Zotero）。"""
    statuses = Counter(_s(r.get('status')) or '未处理' for r in rows)
    valid_pdf = 0
    for row in rows:
        pdf = row.get('pdf')
        if pdf:
            try:
                if Path(_s(pdf)).is_file():
                    valid_pdf += 1
            except OSError:
                pass
    other = sum(count for status, count in statuses.items() if status not in COUNTED_STATUS)
    return {
        'ok': True, 'source': source_name, 'total': len(rows), 'valid_pdf': valid_pdf,
        'attached': statuses['PDF_ATTACHED'] + statuses['PDF_ALREADY_PRESENT'],
        'existing_pdf': statuses['已有PDF已汇总'],
        'saved_local': statuses['PDF_SAVED'],
        'pending': statuses['PDF_PENDING'] + statuses['待下载'],
        'other': other,
        'review': statuses['待核验/补全'] + statuses['NEEDS_REVIEW'] + other,
        'statuses': dict(statuses), 'issues': [],
    }


def progress_data(out, rows, source_name, explicit=''):
    if explicit:
        payload, error = _load_json(explicit)
        if error:
            return None, error, ''
        return payload, None, f'命令行指定的 progress --json 快照：{explicit}'
    auto = Path(out).expanduser() / 'progress.json'
    if auto.is_file():
        payload, error = _load_json(auto)
        if not error:
            return payload, None, f'自动读取 {auto}'
    # 优先复用 CLI 自身的函数，保证汇报数字与 progress --json 完全同源
    try:
        from . import cli as paper_tool
        snapshot = paper_tool.progress_snapshot(str(Path(out).expanduser()))
        if snapshot.get('ok'):
            return snapshot, None, 'paper_tool.progress_snapshot（与 progress --json 同源）'
    except Exception:
        pass
    return local_progress(rows, source_name), None, '按 progress_snapshot 同口径本地统计（未连接 Zotero）'


def optional_data(out, explicit, filename, label):
    if explicit:
        payload, error = _load_json(explicit)
        if error:
            return None, error, ''
        return payload, None, f'命令行指定的 {label} 快照：{explicit}'
    auto = Path(out).expanduser() / filename
    if auto.is_file():
        payload, error = _load_json(auto)
        if not error:
            return payload, None, f'自动读取 {auto}'
    return None, None, ''


def failures_data(out, rows, explicit=''):
    payload, error, note = optional_data(out, explicit, 'failures.json', 'failures --json')
    if error:
        return None, error, ''
    if payload is not None:
        return payload, None, note
    pending_file = Path(out).expanduser() / 'pending.txt'
    if pending_file.is_file():
        lines = [line.strip() for line in
                 pending_file.read_text(encoding='utf-8', errors='replace').splitlines()]
        refs = [line for line in lines if line and not line.startswith('#')]
        return {'source': str(pending_file), 'pending': len(refs), 'references': refs}, None, \
            f'统计 {pending_file} 的非空行'
    pending = []
    for row in rows:
        if _s(row.get('status')) not in GOOD_STATUS:
            ref = _s((row.get('paper') or {}).get('doi') or row.get('doi')
                     or row.get('input') or row.get('reference'))
            if ref and ref not in pending:
                pending.append(ref)
    return {'source': '按检查点推算（未运行 failures）', 'pending': len(pending),
            'references': pending}, None, '按检查点状态推算（仅供参考，正式清单请跑 failures --write）'


def _int(payload, key, default=0):
    try:
        return int(payload.get(key, default) or 0)
    except (TypeError, ValueError, AttributeError):
        return default


def build_summary(out, report_path=None, collection='', batch='',
                  progress_json='', audit_json='', failures_json=''):
    rows, source_name, checkpoint = load_checkpoint(out)
    folder = Path(out).expanduser()
    name = batch or folder.name
    progress, progress_error, progress_note = progress_data(out, rows, source_name, progress_json)
    audit, audit_error, audit_note = optional_data(out, audit_json, 'audit.json', 'audit --json')
    failures, failures_error, failures_note = failures_data(out, rows, failures_json)
    p = progress if isinstance(progress, dict) else {}

    total = _int(p, 'total', len(rows))
    attached = _int(p, 'attached')
    existing = _int(p, 'existing_pdf')
    saved = _int(p, 'saved_local')
    pending = _int(p, 'pending')
    review = _int(p, 'review')
    valid_pdf = _int(p, 'valid_pdf')
    success = attached + existing + saved
    unique_inputs = len({_s(_pick(r, 'input', 'reference')).lower() for r in rows
                         if _s(_pick(r, 'input', 'reference'))})
    recorded = sorted({_s(r.get('collection')) for r in rows if _s(r.get('collection'))})
    if collection:
        collection_display = f'`{collection}`（本次由 `--collection` 提供）'
    elif len(recorded) == 1:
        collection_display = f'`{recorded[0]}`（来自检查点记录，**未经本次确认**）'
    elif recorded:
        collection_display = '检查点记录了多个分类：' + '、'.join(f'`{c}`' for c in recorded) \
            + '（**未经本次确认**）'
    else:
        collection_display = '未记录（需人工确认；本脚本不擅自决定）'
    xlsx_path = folder / '文献清单.xlsx'
    pdf_dir = folder / 'PDF'
    if not pdf_dir.is_dir():
        pdf_dir = folder

    pending_path = folder / 'pending.txt'
    suggested = (f'.\\paper-tool.cmd batch --input "{pending_path}" --out "{folder}" '
                 '--zotero --collection \'<用户确认的完整路径>\' --skip-done')
    warnings = []
    if progress_error:
        warnings.append(progress_error)
    if audit_error:
        warnings.append(audit_error)
    if failures_error:
        warnings.append(failures_error)
    if audit is None:
        warnings.append('未提供 audit --json 快照：验收数字留空，退出码 0 不代表附件文件本体已确认')

    lines = [
        '# 文献批量下载入库 · 完成情况汇报',
        '',
        f'> 由 `python -m paper_tool.reports summary` 只读生成 · {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        '> 所有数字来自检查点与 CLI JSON 快照，可在 §七 复算；本脚本不写 Zotero、不改检查点。',
        '',
        '## 一、批次与输入',
        '',
        f'- **批次**：`{name}`',
        f'- **批次目录**：`{folder.resolve()}`',
        f'- **检查点**：`{source_name}`（`{checkpoint.resolve()}`）',
        f'- **输入**：{total} 条（按原始条目去重后 {unique_inputs} 条）',
        f'- **PDF 目录**：`{pdf_dir}`',
        f'- **Excel 台账**：`{xlsx_path}`' + ('（已存在）' if xlsx_path.is_file() else '（尚未生成，跑 `ledger`）'),
        '',
        '## 二、下载与入库结果',
        '',
        '| 项 | 数量 | 来源字段 |',
        '|---|---:|---|',
        f'| 成功（已附加 / 已有附件 / 仅本地） | {success} | `progress.attached + existing_pdf + saved_local` |',
        f'| 待办（待下载） | {pending} | `progress.pending` |',
        f'| 需人工（待核验 / 其它） | {review} | `progress.review` |',
        f'| 本地 PDF 文件可读 | {valid_pdf} / {total} | `progress.valid_pdf / total` |',
        '',
        '## 三、Zotero',
        '',
        f'- **目标分类**：{collection_display}',
        f'- **条目 + 附件**：{attached} 条；**已有附件跳过**：{existing} 条；**仅本地未附加**：{saved} 条',
        '- **分区标签**：Zotero IF「自动为新文献更新」是否开启、本次覆盖条数 **未由本工具核验**，'
        '需在 Zotero 客户端人工确认（本地 API 无触发插件动作的端点）',
        '- **E3 分类留痕**：本脚本只读取检查点，无法判定分类数量前后是否变化；人工核对「无新建 / 无删除」',
        '',
        '## 四、只读验收',
        '',
    ]
    if isinstance(audit, dict):
        states = audit.get('states') if isinstance(audit.get('states'), dict) else {}
        lines += [
            f'- 来源：`{audit.get("source", "audit --json")}`；检查 {_int(audit, "total")} 条',
            '',
            '| 状态 | 数量 |',
            '|---|---:|',
        ]
        lines += [f'| {_esc(str(state))} | {count} |' for state, count in sorted(states.items())]
        if not states:
            lines.append('| （无状态记录） | 0 |')
        problems = audit.get('problems') if isinstance(audit.get('problems'), list) else []
        lines += ['', f'- 需处置问题条目：{len(problems)} 条'
                  + ('（见 §六）' if problems else '')]
    else:
        cmd = f'.\\paper-tool.cmd audit --out "{folder}" --json > "{folder / "audit.json"}"'
        lines += [
            '> ⚠️ **未提供 `audit --json` 快照，本节数字为空，不臆造。**',
            f'> 请在批次完成后执行：`{cmd}`，再重新生成本汇报。',
            '> `has_pdf()` 只查附件元数据，`MISSING_FILE` 只有 `audit` 能发现；**退出码 0 ≠ 附件文件本体确认**。',
        ]
    lines += [
        '',
        '## 五、待办与建议命令',
        '',
        f'- 待办清单：{_int(failures, "pending")} 行'
        + (f'（来源：{failures.get("source", "未知")}）' if isinstance(failures, dict) else ''),
        f'- 数据来源说明：{failures_note or "无"}',
        f'- 建议命令：`{suggested}`',
        '- 重跑一次仍失败就停下，优先检查机构登录态 / 验证挑战，不要盲目循环。',
        '',
        '## 六、需人工处置的具体条目',
        '',
    ]
    manual = []
    if isinstance(audit, dict):
        for item in (audit.get('problems') or [])[:20]:
            if isinstance(item, dict):
                manual.append(f'- `[{item.get("state", "?")}]` {item.get("title") or item.get("doi") or "（无题名）"}'
                              + (f' — {item.get("error")}' if item.get('error') else ''))
    if isinstance(p.get('issues'), list):
        for item in p['issues'][:10]:
            if isinstance(item, dict):
                text = (f'- `#{item.get("number", "-")} [{item.get("status", "?")}] '
                        f'{item.get("title", "")} — {item.get("warning", "")}`')
                if text not in manual:
                    manual.append(text)
    lines += manual or ['- （无：检查点未列出需人工处置的条目；仍请以 `audit` 结果为准）']
    lines += [
        '',
        '## 七、数字来源与复算',
        '',
        '| 汇报数字 | 取值来源 | 复算方式 |',
        '|---|---|---|',
        f'| 输入 {total} / 去重 {unique_inputs} 条 | `{source_name}` | 记录条数 / 不同 `input` 的条数 |',
        f'| 成功 {success} | progress JSON | `attached({attached}) + existing_pdf({existing}) + saved_local({saved})` |',
        f'| 待办 {pending} / 需人工 {review} | progress JSON | `progress.pending` / `progress.review` |',
        f'| 本地 PDF {valid_pdf}/{total} | progress JSON | `progress.valid_pdf` / `progress.total` |',
        f'| 附件 {attached} / 跳过 {existing} | progress JSON | `progress.attached` / `progress.existing_pdf` |',
        '| §四 状态分布 | audit --json | `audit.states` 原样引用 |',
        f'| 待办 {_int(failures, "pending")} 行 | failures --json / pending.txt / 检查点推算 | 去重后的非空条目数 |',
        '',
        f'- progress 数据来源：{progress_note or "未取得"}',
        f'- audit 数据来源：{audit_note or "未提供"}',
        f'- failures 数据来源：{failures_note or "未提供"}',
        '',
        '## 八、提醒',
        '',
        '1. **退出码 0 ≠ 附件文件本体确认**；收尾必须跑 `audit`，`MISSING_FILE` / `DUPLICATE` 在 Zotero 客户端人工处理。',
        '2. 四条不变式：不新建/删除分类、不删除条目、不覆盖已有 PDF、不绕过验证挑战。',
        '3. Excel 台账是**只读导出**，不反向写回 `manifest.json` / `report.json`；两套检查点不要互相覆盖。',
        '4. 分类确认、Zotero IF 开关与密钥、机构登录与验证挑战属人工环节，本工具不代做。',
    ]
    if warnings:
        lines += ['', '### 生成时的告警', ''] + [f'- {item}' for item in warnings]
    text = '\n'.join(lines) + '\n'

    target = Path(report_path).expanduser() if report_path else folder / '完成情况汇报.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    return {
        'ok': True,
        'report': str(target.resolve()),
        'batch': name,
        'checkpoint': source_name,
        'numbers': {
            'total': total, 'unique_inputs': unique_inputs, 'success': success,
            'pending': pending, 'review': review, 'valid_pdf': valid_pdf,
            'attached': attached, 'existing_pdf': existing, 'saved_local': saved,
            'audit_total': _int(audit, 'total') if isinstance(audit, dict) else None,
            'failures_pending': _int(failures, 'pending'),
        },
        'audit_available': bool(audit_note),
        'warnings': warnings,
        'text': text,
    }


# ------------------------------------------------------------------------ CLI

def add_common(parser):
    parser.add_argument('--out', required=True, help='批次目录（含 manifest.json 或 report.json）')
    parser.add_argument('--collection', default='', help='用户确认过的 Zotero 完整层级分类路径')
    parser.add_argument('--group', default='', help='课题组名称，写入台账「课题组」列')
    parser.add_argument('--batch', default='', help='批次名，默认取目录名')
    parser.add_argument('--json', action='store_true', help='只在 stdout 打印机器可读 JSON')


def add_ledger_args(parser):
    parser.add_argument('--xlsx', default='', help='输出 xlsx 路径，默认 <out>/文献清单.xlsx')
    parser.add_argument('--translations', default='',
                        help=f'中文题名映射文件，默认 <out>/{TRANSLATION_FILE}')


def add_summary_args(parser):
    parser.add_argument('--report', '--write', dest='report', default='',
                        help='输出汇报路径，默认 <out>/完成情况汇报.md')
    parser.add_argument('--progress-json', default='', help='progress --json 的保存文件')
    parser.add_argument('--audit-json', default='', help='audit --json 的保存文件')
    parser.add_argument('--failures-json', default='', help='failures --json 的保存文件')


def main(argv=None):
    parser = argparse.ArgumentParser(description='paper-tool 只读交付物：Excel 台账 + 完成情况汇报')
    sub = parser.add_subparsers(dest='command', required=True)
    ledger = sub.add_parser('ledger', help='生成 18 列 Excel 台账（含中文题名）', parents=[])
    add_common(ledger)
    add_ledger_args(ledger)
    todo = sub.add_parser('translate-todo',
                          help=f'生成/补齐 {TRANSLATION_FILE}（列出待译英文题名，不覆盖已有译文）')
    add_common(todo)
    summary = sub.add_parser('summary', help='生成完成情况汇报')
    add_common(summary)
    add_summary_args(summary)
    both = sub.add_parser('both', help='一次生成台账 + 汇报')
    add_common(both)
    add_ledger_args(both)
    add_summary_args(both)
    args = parser.parse_args(argv)

    try:
        payload = {}
        if args.command == 'translate-todo':
            rows, source_name, _ = load_checkpoint(args.out)
            payload['translations'] = build_translation_template(args.out, rows, source_name)
            if not args.json:
                info = payload['translations']
                print(f"[OK] 待译清单：{info['file']}")
                print(f"     共 {info['total']} 条，已译 {info['translated']} 条，"
                      f"新增 {info['added']} 条，中文原题名跳过 {info['chinese_skipped']} 条")
                print(f"     未译 {info['todo']} 条；填好中文后重跑 ledger / both 即可带上「中文题名」列")
            if args.json:
                payload['translations'].pop('text', None)
                print(json.dumps(payload['translations'], ensure_ascii=False))
            return 0
        if args.command in ('ledger', 'both'):
            payload['ledger'] = build_ledger(args.out, args.xlsx or None,
                                             args.collection, args.group,
                                             args.translations)
            if not args.json:
                info = payload['ledger']
                print(f"[OK] Excel 台账：{info['xlsx']}")
                print(f"     来源 {info['source']}，{info['rows']} 行 × {info['columns']} 列；"
                      f"DOI 待核验 {info['missing_doi']}，URL 待核验 {info['missing_url']}")
                print(f"     中文题名 {info['translated']} 条已译 / "
                      f"{info['untranslated']} 条待翻译（映射：{info['translations_file']}）")
        if args.command in ('summary', 'both'):
            extra = dict(report_path=args.report or None, collection=args.collection,
                         batch=args.batch)
            if args.command == 'both':
                extra.update(progress_json='', audit_json='', failures_json='')
            else:
                extra.update(progress_json=args.progress_json, audit_json=args.audit_json,
                             failures_json=args.failures_json)
            result = build_summary(args.out, **extra)
            if args.json:
                result.pop('text', None)
            payload['summary'] = result
            if not args.json:
                print()
                print(result['text'])
                print(f"[OK] 汇报已写入：{result['report']}")
        if args.json:
            for value in payload.values():
                value.pop('text', None)
            print(json.dumps(payload if len(payload) > 1 else next(iter(payload.values())),
                             ensure_ascii=False))
        return 0
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        if args.json:
            print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        else:
            print(f'[X] {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())


def agent_report(out):
    """Small, offline AI report; never export candidate URLs or credentials."""
    from . import batch,core
    from .errors import safe_text, ErrorCode
    out=Path(out)
    job=batch.read_job(out)
    settings=job.get('settings') or {}
    rows=batch.load_rows(out)
    unique={}
    for row in rows:
        key=str(row.get('doi') or batch.canonical_ref(row['input'])).lower()
        unique.setdefault(key,row)
    results=[]
    for row in unique.values():
        valid=not settings.get('metadata_only',False) and core.checkpoint_pdf_valid(row)
        archived=bool(settings.get('zotero') and row.get('status') in {'PDF_ATTACHED','PDF_ALREADY_PRESENT','METADATA_ONLY'}
                      and row.get('zotero') not in {'WRITE_PENDING','COLLECTION_REVIEW'})
        done=batch._succeeded(row,settings.get('zotero',False),settings.get('metadata_only',False))
        detail=row.get('error_detail')
        if isinstance(detail,dict):
            detail={k:safe_text(v) if isinstance(v,str) else v for k,v in detail.items()
                    if k in {'error_code','message','retryable','retry_after','http_status','source','stop_reason','next_action'}}
        code=row.get('error_code') or (ErrorCode.PDF_INVALID.value if row.get('pdf') and not valid and not settings.get('metadata_only') else None)
        results.append({'input':row['input'],'title':row.get('title') or (row.get('paper') or {}).get('title') or '',
            'doi':row.get('doi') or '', 'status':row.get('status') or 'WAITING',
            'pdf':row.get('pdf') if valid else None,'sha256':row.get('sha256') if valid else None,
            'pdf_verified':valid,'archive_completed':archived,'completed':done,
            'error_code':code,'error_detail':detail,
            'sources_attempted':row.get('sources_attempted') or [],
            'pdf_source':row.get('pdf_source'),
            'warnings':[safe_text(w) for w in batch._warnings(row)]})
    pending=[r for r in results if not r['completed']]
    actions=[]
    if job.get('stop_reason'): actions.append({'action':'diagnose_stop','reason':job['stop_reason']})
    if pending: actions.append({'action':'review_unfinished','job_id':job['job_id'],'count':len(pending)})
    current_status='PARTIAL' if job['status']=='COMPLETED' and pending else job['status']
    events=[{k:safe_text(v) if isinstance(v,str) else v for k,v in event.items() if k in {'event','source','operation','reason','http_status','retry_after','seconds','attempt','number'}}
            for event in ((job.get('safety') or {}).get('events') or [])]
    return {'schema_version':'2.0','kind':'STATUS','job_id':job['job_id'],'status':current_status,
            'summary':{'total':len(results),'metadata_verified':sum(bool(r['doi'] and r['title']) for r in results),
                       'pdf_verified':sum(r['pdf_verified'] for r in results),
                       'archive_completed':sum(r['archive_completed'] for r in results),'pending':len(pending)},
            'stop_reason':job.get('stop_reason'),'results':results,
            'events':events,'next_actions':actions}
