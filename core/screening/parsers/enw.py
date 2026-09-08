"""ProCite/EndNote tagged-text parser."""

import os
from typing import Dict, Iterable, List, Optional


_PROCITE_TAG_MAP = {
    '%0': 'reference_type',
    '%A': 'authors',          # 可多行
    '%+': 'affiliations',
    '%T': 'title',
    '%J': 'journal',
    '%D': 'year',
    '%V': 'volume',
    '%N': 'issue',
    '%P': 'page',
    '%@': 'issn',
    '%L': 'call_number',
    '%U': 'url',
    '%W': 'database',
    '%R': 'doi',
    '%Z': 'notes',
    '%K': 'keywords',
    '%X': 'abstract',
    '%I': 'publisher',
    '%C': 'place_published',
    '%Y': 'editor',
    '%9': 'thesis_type',
    '%G': 'language',
    '%M': 'accession_number',
    '%F': 'label',
    '%2': 'secondary_url',
    '%~': 'name_of_database',
    '%<': 'research_notes',
    '%[': 'access_date',
}


def _normalize_procite_record(rec: Dict) -> Dict:
    raw_doi = rec.get('%R', '')
    doi = raw_doi.replace('DOI:', '').replace('doi:', '').strip() if raw_doi else ''
    url = rec.get('%U') or rec.get('%2') or ''
    if isinstance(url, str):
        url = url.strip()
    authors = rec.get('%A', [])
    if isinstance(authors, str):
        authors = [authors]
    return {
        'title': rec.get('%T', '').strip(),
        'authors': authors,
        'journal': rec.get('%J', '').strip(),
        'year': rec.get('%D', '').strip(),
        'volume': rec.get('%V', '').strip(),
        'issue': rec.get('%N', '').strip(),
        'page': rec.get('%P', '').strip(),
        'date': rec.get('%D', '').strip(),
        'doi': doi,
        'pmcid': '',
        'abstract': rec.get('%X', '').strip(),
        'url': url,
        'address': rec.get('%C', '').strip(),
        'reference_type': rec.get('%0', '').strip(),
        'keywords': rec.get('%K', '').strip(),
        'publisher': rec.get('%I', '').strip(),
        'database': rec.get('%W', '').strip(),
        'source_type': 'ENW',
    }


def _parse_procite_lines(lines: Iterable[str]) -> List[Dict]:
    """逐行解析 ProCite Tagged 记录，不保留原始全文和中间记录列表。"""
    multi_value_tags = {'%A', '%+'}
    parsed = []
    current: Dict = {}
    last_tag: Optional[str] = None

    def _flush(rec):
        if rec:
            parsed.append(_normalize_procite_record(rec))

    for raw_line in lines:
        line = raw_line.rstrip('\r\n')
        # 空行可能出现在同一条文献内（如维普导出的作者与机构之间）。
        # 记录边界由下一个 %0 标签或文件结尾确定。
        if not line.strip():
            continue

        # 判断是否是标签行（以 %? 开头，第2字符是字母/数字/+/~/</ [）
        if len(line) >= 2 and line[0] == '%' and len(line) > 2 and line[2] == ' ':
            tag = line[:2]
            value = line[3:].strip()
            # %0 是记录类型标签，遇到它意味着新记录开始
            if tag == '%0' and current:
                _flush(current)
                current = {}
            last_tag = tag
            if tag in multi_value_tags:
                current.setdefault(tag, [])
                if value:
                    current[tag].append(value)
            else:
                # 部分字段可能多次出现（如 %U），拼接
                if tag in current and tag not in multi_value_tags:
                    current[tag] = str(current[tag]) + '\n' + value
                else:
                    current[tag] = value
        else:
            # 续行：追加到上一标签
            if last_tag and line.strip():
                if last_tag in multi_value_tags:
                    if current.get(last_tag):
                        current[last_tag][-1] += ' ' + line.strip()
                else:
                    current[last_tag] = str(current.get(last_tag, '')) + ' ' + line.strip()

    # 文件末尾最后一条记录（无空行结尾）
    _flush(current)
    return parsed


def _parse_procite_text(text: str) -> List[Dict]:
    """解析内存中的 ProCite Tagged 文本（供 DOCX 等调用者兼容使用）。"""
    return _parse_procite_lines(text.splitlines())


def _detect_text_encoding(file_path: str) -> str:
    """以固定大小块验证 UTF-8；失败时按 GB18030 解码。"""
    import codecs

    with open(file_path, 'rb') as source:
        prefix = source.read(4)
        if prefix.startswith((b'\xff\xfe', b'\xfe\xff')):
            return 'utf-16'
        source.seek(0)
        decoder = codecs.getincrementaldecoder('utf-8-sig')(errors='strict')
        try:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    decoder.decode(b'', final=True)
                    return 'utf-8-sig'
                decoder.decode(chunk, final=False)
        except UnicodeDecodeError:
            return 'gb18030'


def parse_enw(file_path: str) -> List[Dict]:
    """
    解析 ProCite Tagged 格式（.enw 或 .txt）文件。
    """
    encoding = _detect_text_encoding(file_path)
    try:
        with open(file_path, 'r', encoding=encoding, errors='strict') as source:
            entries = _parse_procite_lines(source)
    except UnicodeDecodeError as exc:
        raise UnicodeError(
            '无法识别 TXT/ENW 文件编码，请使用 UTF-8、UTF-16 或 GB18030'
        ) from exc
    for i, e in enumerate(entries, 1):
        e['source_file'] = os.path.basename(file_path)
        e['source_position'] = i
    return entries
