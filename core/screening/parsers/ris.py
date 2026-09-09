"""RIS reference parser."""

import os
from typing import Dict, List

try:
    import rispy
    from rispy.config import LIST_TYPE_TAGS
except ImportError:  # pragma: no cover - optional dependency guard
    rispy = None
    LIST_TYPE_TAGS = []


def parse_ris(file_path: str) -> List[Dict]:
    """
    解析RIS格式文献

    Args:
        file_path: RIS文件路径

    Returns:
        标准化的文献字典列表
    """
    if rispy is None:
        raise ImportError("rispy 未安装，请运行: pip install rispy")

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        # rispy 默认把 AD 映射为 author_address，且按单值字段处理，重复的
        # AD 会被覆盖。显式将其声明为列表，确保多机构地址全部保留下来。
        entries = rispy.load(f, list_tags=[*LIST_TYPE_TAGS, 'AD'])

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

    parsed_entries = []
    for i, entry in enumerate(entries, start=1):
        # 提取URL（多来源尝试）
        url = entry.get('url') or entry.get('urls')
        if isinstance(url, list) and url:
            url = url[0]
        if not url:
            url = entry.get('UR') or entry.get('L1')

        # 提取页码
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

        # 提取日期
        date = first_value(entry, ['date', 'publication_date', 'DA', 'Y1'])

        # 提取DOI
        doi = entry.get('doi') or entry.get('DO')
        if isinstance(doi, list):
            doi = doi[0] if doi else None

        parsed_entries.append({
            'title': entry.get('title') or entry.get('primary_title'),
            'authors': entry.get('authors', []),
            # JF(期刊全名) → alternate_title3；JO(期刊缩写) → journal_name；T2 → secondary_title
            'journal': (entry.get('journal_name')
                        or entry.get('alternate_title3')
                        or entry.get('secondary_title')
                        or entry.get('alternate_title1')
                        or entry.get('alternate_title2')),
            'year': entry.get('year'),
            'volume': first_value(entry, ['volume', 'VL']),
            'issue': first_value(entry, ['number', 'issue', 'IS']),
            'page': page,
            'date': date,
            'doi': doi,
            'pmcid': first_value(entry, ['pmcid', 'PMCID']),
            'abstract': entry.get('abstract'),
            'url': url,
            'address': joined_values(entry, ['author_address', 'address', 'AD']),
            'reference_type': first_value(entry, ['type_of_reference', 'type', 'TY']),
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'source_type': 'RIS'
        })

    return parsed_entries
