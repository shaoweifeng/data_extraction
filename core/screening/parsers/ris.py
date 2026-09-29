"""RIS reference parser."""

import os
from typing import Dict, Iterator

from .enw import _detect_text_encoding

try:
    import rispy
    from rispy.config import LIST_TYPE_TAGS
except ImportError:  # pragma: no cover - optional dependency guard
    rispy = None
    LIST_TYPE_TAGS = []


def _normalize_ris_entry(entry: Dict, file_path: str, position: int) -> Dict:
    def first_value(d, keys):
        """获取第一个非空值"""
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (int, float)):
                return str(v)
        return None

    def joined_values(d, keys):
        """合并 RIS 单值/多值字段，同时兼容不同 rispy 版本的字段名。"""
        for k in keys:
            value = d.get(k)
            if isinstance(value, (list, tuple)):
                parts = [str(item).strip() for item in value if str(item).strip()]
                if parts:
                    return '; '.join(parts)
            elif value is not None and str(value).strip():
                return str(value).strip()
        return None

    url = entry.get('url') or entry.get('urls')
    if isinstance(url, list) and url:
        url = url[0]
    if not url:
        url = entry.get('UR') or entry.get('L1')

    pages = first_value(entry, ['pages'])
    start_page = first_value(entry, ['start_page', 'sp', 'SP'])
    end_page = first_value(entry, ['end_page', 'ep', 'EP'])
    page = pages
    if not page:
        if start_page and end_page:
            page = f"{start_page}-{end_page}"
        elif start_page:
            page = start_page
        elif end_page:
            page = end_page

    doi = entry.get('doi') or entry.get('DO')
    if isinstance(doi, list):
        doi = doi[0] if doi else None

    normalized = {
        'title': entry.get('title') or entry.get('primary_title'),
        'authors': entry.get('authors', []),
        'journal': (entry.get('journal_name')
                    or entry.get('alternate_title3')
                    or entry.get('secondary_title')
                    or entry.get('alternate_title1')
                    or entry.get('alternate_title2')),
        'year': entry.get('year'),
        'volume': first_value(entry, ['volume', 'VL']),
        'issue': first_value(entry, ['number', 'issue', 'IS']),
        'page': page,
        'date': first_value(entry, ['date', 'publication_date', 'DA', 'Y1']),
        'doi': doi,
        'pmcid': first_value(entry, ['pmcid', 'PMCID']),
        'abstract': entry.get('abstract'),
        'url': url,
        'address': joined_values(entry, ['author_address', 'address', 'AD']),
        'reference_type': first_value(entry, ['type_of_reference', 'type', 'TY']),
        'source_file': os.path.basename(file_path),
        'source_position': position,
        'source_type': 'RIS',
    }
    normalized['_raw_metadata'] = entry
    return normalized


def parse_ris(file_path: str) -> Iterator[Dict]:
    """Stream RIS records while retaining rispy's established field mapping."""
    if rispy is None:
        raise ImportError("rispy 未安装，请运行: pip install rispy")

    parser = rispy.RisParser(list_tags=[*LIST_TYPE_TAGS, 'AD'])
    position = 0
    encoding = _detect_text_encoding(file_path)
    with open(file_path, 'r', encoding=encoding, errors='strict') as source:
        lines = iter(source)
        while True:
            try:
                record = parser._iter_till_start(lines)
            except StopIteration:
                return
            last_tag = None
            for line in lines:
                tag, content = parser.parse_line(line)
                if tag is None:
                    if last_tag is not None:
                        parser._add_tag(record, last_tag, content, extend_multiline=True)
                    continue
                if tag in parser.ignore:
                    continue
                if tag == parser.END_TAG:
                    position += 1
                    yield _normalize_ris_entry(record, file_path, position)
                    break
                parser._add_tag(record, tag, content)
                last_tag = tag
            else:
                return
