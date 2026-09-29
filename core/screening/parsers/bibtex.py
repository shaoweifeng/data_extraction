"""BibTeX reference parser."""

import os
import re
from typing import Dict, Iterator, TextIO

from .enw import _detect_text_encoding

try:
    import bibtexparser
except ImportError:  # pragma: no cover - optional dependency guard
    bibtexparser = None


_ENTRY_START = re.compile(r'^\s*@([a-z]+)\s*([\{(])', re.IGNORECASE)


def _iter_bibtex_blocks(source: TextIO) -> Iterator[tuple[str, str]]:
    """Yield one balanced BibTeX declaration at a time."""
    block = []
    entry_type = ''
    opener = ''
    closer = ''
    depth = 0
    quote = False
    escaped = False

    for line in source:
        if not block:
            match = _ENTRY_START.match(line)
            if not match:
                continue
            entry_type = match.group(1).lower()
            opener = match.group(2)
            closer = '}' if opener == '{' else ')'

        block.append(line)
        for char in line:
            if escaped:
                escaped = False
                continue
            if char == '\\':
                escaped = True
                continue
            if char == '"':
                quote = not quote
                continue
            if quote:
                continue
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1

        if depth == 0:
            yield entry_type, ''.join(block)
            block = []
            entry_type = opener = closer = ''
            quote = escaped = False


def parse_bib(file_path: str) -> Iterator[Dict]:
    """Stream BibTeX entries without materializing the complete library."""
    if bibtexparser is None:
        raise ImportError("bibtexparser 未安装，请运行: pip install bibtexparser")

    declarations = []
    candidate_position = 0
    encoding = _detect_text_encoding(file_path)
    with open(file_path, 'r', encoding=encoding, errors='strict') as source:
        blocks = _iter_bibtex_blocks(source)
        for entry_type, block in blocks:
            if entry_type in {'string', 'preamble'}:
                declarations.append(block)
                continue
            if entry_type == 'comment':
                continue
            candidate_position += 1
            library = bibtexparser.loads(''.join(declarations) + block)
            if not library.entries:
                continue
            entry = library.entries[-1]

            # 解析作者列表
            authors = entry.get('author', '').replace('\n', ' ').split(' and ')
            authors = [a.strip() for a in authors if a.strip()]

            # 提取 URL
            url = entry.get('url') or entry.get('link') or entry.get('URL')

            # 构建日期
            year = entry.get('year')
            month = entry.get('month')
            date = f"{month} {year}" if month and year else str(year) if year else None

            normalized = {
                'title': entry.get('title'),
                'authors': authors,
                'journal': entry.get('journal'),
                'year': year,
                'volume': entry.get('volume'),
                'issue': entry.get('number') or entry.get('issue'),
                'page': entry.get('pages'),
                'date': date,
                'doi': entry.get('doi'),
                'pmcid': entry.get('pmcid') or entry.get('PMCID'),
                'abstract': entry.get('abstract'),
                'url': url,
                'address': entry.get('address'),
                'reference_type': entry.get('ENTRYTYPE') or entry.get('type'),
                'source_file': os.path.basename(file_path),
                'source_position': candidate_position,
                'source_identifier': entry.get('ID'),
                'source_type': 'BIB',
            }
            normalized['_raw_metadata'] = entry
            yield normalized
