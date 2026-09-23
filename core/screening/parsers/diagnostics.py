"""Diagnostics and data-quality checks for imported reference files."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List


_EMPTY_ABSTRACT_VALUES = {
    '', 'n/a', 'na', 'none', 'null', 'not available', 'no abstract available',
}


def _line_number(text: str, offset: int) -> int:
    return text.count('\n', 0, offset) + 1


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _text_candidates(path: Path, pattern: str, identifier_group: int | None = None) -> List[Dict[str, Any]]:
    text = _read_text(path)
    candidates = []
    for index, match in enumerate(re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE), 1):
        identifier = match.group(identifier_group).strip() if identifier_group else ''
        candidates.append({
            'position': index,
            'line': _line_number(text, match.start()),
            'identifier': identifier,
        })
    return candidates


def _bibtex_candidates(path: Path) -> List[Dict[str, Any]]:
    text = _read_text(path)
    pattern = r'^[ \t]*@([a-z]+)\s*[\{(]\s*([^,\r\n]*)\s*,'
    candidates = []
    for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
        entry_type = match.group(1).lower()
        if entry_type in {'comment', 'preamble', 'string'}:
            continue
        candidates.append({
            'position': len(candidates) + 1,
            'line': _line_number(text, match.start()),
            'identifier': match.group(2).strip(),
            'entry_type': entry_type,
        })
    return candidates


def _xml_candidates(path: Path) -> List[Dict[str, Any]]:
    def local_name(tag: str) -> str:
        return tag.rsplit('}', 1)[-1].lower()

    def embase_identifier(item) -> str:
        pui = ''
        doi = ''
        for child in item.iter():
            name = local_name(child.tag)
            text = ''.join(child.itertext()).strip()
            if name == 'doi' and text and not doi:
                doi = text
            elif name == 'itemid' and (child.get('idtype') or '').upper() == 'PUI' and text:
                pui = text
        return pui or doi

    candidates = []
    root_tag = None
    for event, elem in ET.iterparse(path, events=('start', 'end')):
        if root_tag is None and event == 'start':
            root_tag = local_name(elem.tag)
            continue
        if event != 'end':
            continue
        tag = local_name(elem.tag)
        is_embase_item = root_tag == 'bibdataset' and tag == 'item'
        is_record = (
            (root_tag == 'xml' and tag == 'record')
            or (root_tag != 'xml' and tag == 'reference')
            or is_embase_item
        )
        if is_record:
            identifier = ''
            if tag == 'record':
                identifier = (elem.findtext('./rec-number') or '').strip()
            elif is_embase_item:
                identifier = embase_identifier(elem)
            candidates.append({
                'position': len(candidates) + 1,
                'line': None,
                'identifier': identifier,
            })
            elem.clear()
    return candidates


def _docx_candidates(path: Path) -> List[Dict[str, Any]]:
    import docx

    doc = docx.Document(path)
    candidates = []
    logical_line = 0
    for para in doc.paragraphs:
        for line in para.text.splitlines() or ['']:
            logical_line += 1
            if re.match(r'^%0\s+', line, re.IGNORECASE):
                candidates.append({
                    'position': len(candidates) + 1,
                    'line': logical_line,
                    'identifier': '',
                })
    return candidates


def detect_candidates(file_path: str) -> List[Dict[str, Any]]:
    """Return lightweight source-record descriptors without normalizing records."""
    path = Path(file_path)
    extension = path.suffix.lower()
    if extension in {'.bib', '.bibtex'}:
        return _bibtex_candidates(path)
    if extension == '.ris':
        return _text_candidates(path, r'^TY\s{1,2}-\s*')
    if extension in {'.nbib', '.medline'}:
        return _text_candidates(path, r'^PMID\s*-\s*(.*)$', 1)
    if extension == '.ciw':
        return _text_candidates(path, r'^PT\s+(.+)$', 1)
    if extension in {'.enw', '.txt'}:
        return _text_candidates(path, r'^%0\s+(.+)$', 1)
    if extension == '.xml':
        return _xml_candidates(path)
    if extension in {'.doc', '.docx'}:
        return _docx_candidates(path)
    return []


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    position: int | None = None,
    line: int | None = None,
    identifier: str = '',
    title: str = '',
    suggestion: str = '',
) -> Dict[str, Any]:
    return {
        'code': code,
        'severity': severity,
        'message': message,
        'position': position,
        'line': line,
        'identifier': identifier,
        'title': title,
        'suggestion': suggestion,
    }


def _is_missing_abstract(value: Any) -> bool:
    return str(value or '').strip().lower() in _EMPTY_ABSTRACT_VALUES


def build_parse_report(
    file_path: str,
    entries: Iterable[Dict[str, Any]],
    *,
    parser_error: Exception | None = None,
) -> Dict[str, Any]:
    """Build an auditable per-file parse report."""
    entries = list(entries)
    candidates: List[Dict[str, Any]] = []
    detection_error = None
    try:
        candidates = detect_candidates(file_path)
    except Exception as exc:  # diagnostics must never hide otherwise usable records
        detection_error = exc

    extension = Path(file_path).suffix.lower().lstrip('.')
    issues: List[Dict[str, Any]] = []

    if parser_error is not None:
        issues.append(_issue(
            'parser_error', 'error', f'文件解析失败：{parser_error}',
            suggestion='请检查文件格式、编码及记录边界后重新上传。',
        ))
    if detection_error is not None:
        issues.append(_issue(
            'candidate_detection_failed', 'warning', f'无法核对源条目数量：{detection_error}',
            suggestion='文献仍已按解析器结果导入，但无法确认是否存在静默跳过。',
        ))
    if parser_error is None and not candidates and not entries:
        issues.append(_issue(
            'no_records_detected', 'error', '文件中没有检测到可解析的文献记录。',
            suggestion='请确认文件内容与扩展名匹配，并从文献数据库重新导出。',
        ))

    if extension in {'bib', 'bibtex'}:
        parsed_ids = {str(entry.get('source_identifier') or '').strip() for entry in entries}
        key_counts = Counter(candidate.get('identifier', '') for candidate in candidates)
        for candidate in candidates:
            key = candidate.get('identifier', '')
            common = {
                'position': candidate.get('position'),
                'line': candidate.get('line'),
                'identifier': key,
            }
            if any(char.isspace() for char in key):
                issues.append(_issue(
                    'invalid_citation_key', 'error', 'BibTeX citation key 包含空白字符，条目可能被跳过。',
                    suggestion='请将 citation key 中的空格替换为下划线或连字符。', **common,
                ))
            elif key_counts[key] > 1:
                issues.append(_issue(
                    'duplicate_citation_key', 'error', 'BibTeX citation key 重复，解析器可能覆盖或跳过条目。',
                    suggestion='请为每条文献使用唯一的 citation key。', **common,
                ))
            if key and key not in parsed_ids and not any(
                issue['identifier'] == key and issue['position'] == candidate.get('position')
                for issue in issues
            ):
                issues.append(_issue(
                    'record_skipped', 'error', '检测到该 BibTeX 条目，但解析器未返回结果。',
                    suggestion='请检查 citation key、花括号和字段分隔符。', **common,
                ))

        position_by_id = {candidate.get('identifier'): candidate for candidate in candidates}
        for entry in entries:
            source_id = str(entry.get('source_identifier') or '').strip()
            if source_id in position_by_id:
                entry['source_position'] = position_by_id[source_id]['position']
    elif candidates and len(candidates) > len(entries):
        issues.append(_issue(
            'record_count_mismatch', 'error',
            f'源文件检测到 {len(candidates)} 条记录，但解析器只返回 {len(entries)} 条。',
            suggestion='请展开原文件检查记录边界、必填标题和格式完整性。',
        ))

    missing_abstract = 0
    for index, entry in enumerate(entries, 1):
        position = entry.get('source_position') or index
        title = str(entry.get('title') or '').strip()
        identifier = str(entry.get('source_identifier') or entry.get('record_number') or '').strip()
        if not title:
            issues.append(_issue(
                'missing_title', 'warning', '文献标题缺失。', position=position,
                identifier=identifier, suggestion='建议补充标题，否则后续去重和筛选准确性会下降。',
            ))
        if _is_missing_abstract(entry.get('abstract')):
            missing_abstract += 1
            issues.append(_issue(
                'missing_abstract', 'warning', '文献摘要缺失。', position=position,
                identifier=identifier, title=title,
                suggestion='可继续后续流程，但摘要缺失可能影响 AI 初筛。',
            ))

    detected = len(candidates) if candidates else len(entries)
    skipped = max(detected - len(entries), 0)
    error_count = sum(issue['severity'] == 'error' for issue in issues)
    warning_count = sum(issue['severity'] == 'warning' for issue in issues)
    if parser_error is not None or not entries:
        status = 'failed'
    elif skipped or error_count:
        status = 'partial'
    elif warning_count:
        status = 'warning'
    else:
        status = 'success'

    return {
        'version': 1,
        'filename': os.path.basename(file_path),
        'format': extension,
        'status': status,
        'detected_entries': detected,
        'parsed_entries': len(entries),
        'skipped_entries': skipped,
        'missing_abstract_entries': missing_abstract,
        'error_count': error_count,
        'warning_count': warning_count,
        'candidate_detection_available': detection_error is None,
        'issues': issues,
    }
