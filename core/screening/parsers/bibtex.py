"""BibTeX reference parser."""

import os
from typing import Dict, List

try:
    import bibtexparser
except ImportError:  # pragma: no cover - optional dependency guard
    bibtexparser = None


def parse_bib(file_path: str) -> List[Dict]:
    """
    解析BibTeX格式文献

    Args:
        file_path: BibTeX文件路径

    Returns:
        标准化的文献字典列表
    """
    if bibtexparser is None:
        raise ImportError("bibtexparser 未安装，请运行: pip install bibtexparser")

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        library = bibtexparser.load(f)

    parsed_entries = []
    for i, entry in enumerate(library.entries, start=1):
        # 解析作者列表
        authors = entry.get('author', '').replace('\n', ' ').split(' and ')
        authors = [a.strip() for a in authors if a.strip()]

        # 提取URL
        url = entry.get('url') or entry.get('link') or entry.get('URL')

        # 构建日期
        year = entry.get('year')
        month = entry.get('month')
        date = None
        if month and year:
            date = f"{month} {year}"
        elif year:
            date = str(year)

        parsed_entries.append({
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
            'source_position': i,
            'source_type': 'BIB'
        })

    return parsed_entries
