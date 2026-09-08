"""PubMed NBIB/Medline reference parser."""

import os
from typing import Dict, List


def parse_nbib(file_path: str) -> List[Dict]:
    """
    解析NBIB/Medline格式文献（PubMed导出）

    Args:
        file_path: NBIB文件路径

    Returns:
        标准化的文献字典列表
    """
    def get_first(d, keys):
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, list):
                return v[0] if v else None
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _extract_year(val):
        """从 DP 字段値中只取年份数字，如 '2023 Jan' → '2023'"""
        import re as _re
        if not val:
            return None
        m = _re.search(r'\b(19|20)\d{2}\b', str(val))
        return m.group(0) if m else val.split()[0] if val.split() else None

    def normalize(record, position):
        # 提取作者列表：FAU（全名，如 "Smith, John A"）优先于 AU（缩写，如 "Smith JA"）
        authors = record.get('FAU') or record.get('AU') or []
        if isinstance(authors, str):
            authors = [authors]

        # 提取DOI
        doi = get_first(record, ['AID', 'LID', 'doi'])
        if doi and '[doi]' in doi:
            doi = doi.replace('[doi]', '').strip()

        # 提取URL
        url = get_first(record, ['url', 'URL', 'AID'])
        if not url:
            pmid = get_first(record, ['PMID'])
            if pmid:
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid.split()[0]}"

        # 处理 AD（机构地址）：可能是列表（多个机构），全部用 '; ' 拼接
        ad_val = record.get('AD')
        if isinstance(ad_val, list):
            address = '; '.join(v.strip() for v in ad_val if v and v.strip())
        elif isinstance(ad_val, str):
            address = ad_val.strip()
        else:
            address = None

        return {
            'title': get_first(record, ['TI', 'BTI']),
            'authors': authors,
            'journal': get_first(record, ['JT', 'TA']),
            'year': _extract_year(get_first(record, ['YR', 'DP'])),  # 只取年份数字，去掉 Jun/Dec 等月份
            'volume': get_first(record, ['VI']),
            'issue': get_first(record, ['IP']),
            'page': get_first(record, ['PG']),
            'date': get_first(record, ['DP', 'EDAT']),
            'reference_type': get_first(record, ['PT']),
            'doi': doi,
            'pmcid': get_first(record, ['PMC', 'PMCID']),  # PMC 是实际标签名称
            'abstract': get_first(record, ['AB']),
            'url': url,
            'address': address,
            'source_file': os.path.basename(file_path),
            'source_position': position,
            'source_type': 'NBIB'
        }

    parsed_entries = []
    current_record = {}
    current_key = None
    current_value = []

    def flush_field():
        nonlocal current_key, current_value
        if not current_key:
            return
        value = ' '.join(current_value).strip()
        if value:
            existing = current_record.get(current_key)
            if existing is None:
                current_record[current_key] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                current_record[current_key] = [existing, value]
        current_key = None
        current_value = []

    def flush_record():
        nonlocal current_record
        flush_field()
        if not current_record:
            return
        parsed_entries.append(normalize(current_record, len(parsed_entries) + 1))
        current_record = {}

    # 单遍逐行解析：不再 readlines()，也不同时保留 lines、records
    # 和 parsed_entries 三份数据。
    with open(file_path, 'r', encoding='utf-8-sig', errors='strict') as source:
        for raw_line in source:
            line = raw_line.rstrip('\r\n')
            if not line.strip():
                continue

            if line[:4] == '    ' and current_key:
                current_value.append(line.strip())
                continue

            if '-' not in line[:5]:
                continue

            tag, value = line.split('-', 1)
            tag = tag.strip()
            value = value.strip()
            flush_field()
            if tag == 'PMID' and current_record:
                flush_record()
            current_key = tag
            current_value = [value] if value else []

    flush_record()

    return parsed_entries
