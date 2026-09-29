"""Diagnostics and data-quality checks for imported reference files."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List

from .enw import _detect_text_encoding


_EMPTY_ABSTRACT_VALUES = {
    '', 'n/a', 'na', 'none', 'null', 'not available', 'no abstract available',
}


def _iter_text_candidates(
    path: Path, pattern: str, identifier_group: int | None = None,
) -> Iterator[Dict[str, Any]]:
    matcher = re.compile(pattern, re.IGNORECASE)
    encoding = _detect_text_encoding(str(path))
    position = 0
    with path.open('r', encoding=encoding, errors='strict') as source:
        for line_number, line in enumerate(source, 1):
            match = matcher.search(line)
            if not match:
                continue
            position += 1
            identifier = match.group(identifier_group).strip() if identifier_group else ''
            yield {
                'position': position,
                'line': line_number,
                'identifier': identifier,
            }


def _iter_bibtex_candidates(path: Path) -> Iterator[Dict[str, Any]]:
    pattern = r'^[ \t]*@([a-z]+)\s*[\{(]\s*([^,\r\n]*)\s*,'
    matcher = re.compile(pattern, re.IGNORECASE)
    encoding = _detect_text_encoding(str(path))
    position = 0
    with path.open('r', encoding=encoding, errors='strict') as source:
        for line_number, line in enumerate(source, 1):
            match = matcher.search(line)
            if not match:
                continue
            entry_type = match.group(1).lower()
            if entry_type in {'comment', 'preamble', 'string'}:
                continue
            position += 1
            yield {
                'position': position,
                'line': line_number,
                'identifier': match.group(2).strip(),
                'entry_type': entry_type,
            }


def _iter_xml_candidates(path: Path) -> Iterator[Dict[str, Any]]:
    from .xml import _reject_unsafe_xml

    _reject_unsafe_xml(str(path))

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

    root_tag = None
    position = 0
    element_stack = []
    for event, elem in ET.iterparse(path, events=('start', 'end')):
        if event == 'start':
            element_stack.append(elem)
            if len(element_stack) > 128:
                raise ValueError('XML 嵌套深度超过 128 层上限')
            if root_tag is None:
                root_tag = local_name(elem.tag)
            continue
        tag = local_name(elem.tag)
        is_embase_item = root_tag == 'bibdataset' and tag == 'item'
        is_record = (
            (root_tag == 'xml' and tag == 'record')
            or (root_tag != 'xml' and tag == 'reference')
            or is_embase_item
        )
        if is_record:
            position += 1
            identifier = ''
            if tag == 'record':
                identifier = (elem.findtext('./rec-number') or '').strip()
            elif is_embase_item:
                identifier = embase_identifier(elem)
            yield {
                'position': position,
                'line': None,
                'identifier': identifier,
            }
            if len(element_stack) > 1:
                element_stack[-2].remove(elem)
            elem.clear()
        element_stack.pop()


def _iter_docx_candidates(path: Path) -> Iterator[Dict[str, Any]]:
    import docx

    doc = docx.Document(path)
    logical_line = 0
    position = 0
    for para in doc.paragraphs:
        for line in para.text.splitlines() or ['']:
            logical_line += 1
            if re.match(r'^%0\s+', line, re.IGNORECASE):
                position += 1
                yield {
                    'position': position,
                    'line': logical_line,
                    'identifier': '',
                }


def iter_candidates(file_path: str) -> Iterator[Dict[str, Any]]:
    """Stream lightweight source-record descriptors."""
    path = Path(file_path)
    extension = path.suffix.lower()
    if extension in {'.bib', '.bibtex'}:
        yield from _iter_bibtex_candidates(path)
    elif extension == '.ris':
        yield from _iter_text_candidates(path, r'^TY\s{1,2}-\s*')
    elif extension in {'.nbib', '.medline'}:
        yield from _iter_text_candidates(path, r'^PMID\s*-\s*(.*)$', 1)
    elif extension == '.ciw':
        yield from _iter_text_candidates(path, r'^PT\s+(.+)$', 1)
    elif extension in {'.enw', '.txt'}:
        yield from _iter_text_candidates(path, r'^%0\s+(.+)$', 1)
    elif extension == '.xml':
        yield from _iter_xml_candidates(path)
    elif extension in {'.doc', '.docx'}:
        yield from _iter_docx_candidates(path)


def detect_candidates(file_path: str) -> List[Dict[str, Any]]:
    """Return lightweight source-record descriptors without normalizing records."""
    return list(iter_candidates(file_path))


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
    max_issues: int | None = None,
) -> Dict[str, Any]:
    """Compatibility helper that consumes records once and keeps only bounded issues."""
    collector = ParseReportCollector(file_path, max_issues=max_issues)
    for entry in entries:
        collector.observe(entry)
    return collector.finalize(parser_error=parser_error)


class ParseReportCollector:
    """Incrementally collect one file's parse diagnostics with bounded issue memory."""

    def __init__(self, file_path: str, *, max_issues: int | None = None):
        self.file_path = file_path
        self.extension = Path(file_path).suffix.lower().lstrip('.')
        self.max_issues = max_issues
        self.issues: List[Dict[str, Any]] = []
        self.issues_truncated = False
        self.parsed_entries = 0
        self.missing_abstract_entries = 0
        self.error_count = 0
        self.warning_count = 0
        self.blocking_error_count = 0
        self._parsed_ids = set()
        self._explicit_candidate_issues = set()

    def _add_issue(self, issue: Dict[str, Any], *, blocks_import: bool = False) -> None:
        if issue['severity'] == 'error':
            self.error_count += 1
            if blocks_import:
                self.blocking_error_count += 1
        elif issue['severity'] == 'warning':
            self.warning_count += 1
        if self.max_issues is None or len(self.issues) < self.max_issues:
            self.issues.append(issue)
        else:
            self.issues_truncated = True
            if issue['severity'] == 'error':
                for index in range(len(self.issues) - 1, -1, -1):
                    if self.issues[index]['severity'] == 'warning':
                        self.issues[index] = issue
                        break

    def observe(self, entry: Dict[str, Any]) -> None:
        """Observe one accepted parser record without retaining its field payload."""
        self.parsed_entries += 1
        position = entry.get('source_position') or self.parsed_entries
        title = str(entry.get('title') or '').strip()
        identifier = str(entry.get('source_identifier') or entry.get('record_number') or '').strip()
        if self.extension in {'bib', 'bibtex'}:
            self._parsed_ids.add(identifier)
        if not title:
            self._add_issue(_issue(
                'missing_title', 'warning', '文献标题缺失。', position=position,
                identifier=identifier, suggestion='建议补充标题，否则后续去重和筛选准确性会下降。',
            ))
        if _is_missing_abstract(entry.get('abstract')):
            self.missing_abstract_entries += 1
            self._add_issue(_issue(
                'missing_abstract', 'warning', '文献摘要缺失。', position=position,
                identifier=identifier, title=title,
                suggestion='可继续后续流程，但摘要缺失可能影响 AI 初筛。',
            ))

    def reject_record(
        self, code: str, message: str, *, position: int | None = None,
        identifier: str = '', title: str = '', suggestion: str = '',
    ) -> None:
        """Record a normalized item rejected by the shared field validator."""
        self._add_issue(_issue(
            code, 'error', message, position=position, identifier=identifier,
            title=title, suggestion=suggestion,
        ), blocks_import=True)

    def _inspect_bibtex_candidate(
        self, candidate: Dict[str, Any], key_counts: Counter,
    ) -> None:
        key = candidate.get('identifier', '')
        position = candidate.get('position')
        common = {'position': position, 'line': candidate.get('line'), 'identifier': key}
        if any(char.isspace() for char in key):
            self._add_issue(_issue(
                'invalid_citation_key', 'error', 'BibTeX citation key 包含空白字符，条目可能被跳过。',
                suggestion='请将 citation key 中的空格替换为下划线或连字符。', **common,
            ))
            self._explicit_candidate_issues.add((position, key))
        elif key_counts[key] > 1:
            self._add_issue(_issue(
                'duplicate_citation_key', 'error', 'BibTeX citation key 重复，解析器可能覆盖或跳过条目。',
                suggestion='请为每条文献使用唯一的 citation key。', **common,
            ))
            self._explicit_candidate_issues.add((position, key))
        if key and key not in self._parsed_ids and (position, key) not in self._explicit_candidate_issues:
            self._add_issue(_issue(
                'record_skipped', 'error', '检测到该 BibTeX 条目，但解析器未返回结果。',
                suggestion='请检查 citation key、花括号和字段分隔符。', **common,
            ))

    def finalize(self, *, parser_error: Exception | None = None) -> Dict[str, Any]:
        detection_error = None
        detected_entries = 0
        candidates = iter_candidates(self.file_path)
        try:
            if self.extension in {'bib', 'bibtex'}:
                # Citation keys are compact metadata; retaining their counts avoids
                # retaining complete records while preserving duplicate diagnostics.
                key_counts = Counter()
                for candidate in candidates:
                    detected_entries += 1
                    key_counts[candidate.get('identifier', '')] += 1
                for candidate in iter_candidates(self.file_path):
                    self._inspect_bibtex_candidate(candidate, key_counts)
            else:
                for _candidate in candidates:
                    detected_entries += 1
        except Exception as exc:  # diagnostics must never hide otherwise usable records
            detection_error = exc

        if parser_error is not None:
            self._add_issue(_issue(
                'parser_error', 'error', f'文件解析失败：{parser_error}',
                suggestion='请检查文件格式、编码及记录边界后重新上传。',
            ), blocks_import=True)
        if detection_error is not None:
            self._add_issue(_issue(
                'candidate_detection_failed', 'warning', f'无法核对源条目数量：{detection_error}',
                suggestion='文献仍已按解析器结果导入，但无法确认是否存在静默跳过。',
            ))
        if parser_error is None and detected_entries == 0 and self.parsed_entries == 0:
            self._add_issue(_issue(
                'no_records_detected', 'error', '文件中没有检测到可解析的文献记录。',
                suggestion='请确认文件内容与扩展名匹配，并从文献数据库重新导出。',
            ), blocks_import=True)

        if (
            self.extension not in {'bib', 'bibtex'}
            and detected_entries > self.parsed_entries
        ):
            self._add_issue(_issue(
                'record_count_mismatch', 'error',
                f'源文件检测到 {detected_entries} 条记录，但解析器只返回 {self.parsed_entries} 条。',
                suggestion='请展开原文件检查记录边界、必填标题和格式完整性。',
            ))

        detected = detected_entries or self.parsed_entries
        skipped = max(detected - self.parsed_entries, 0)
        if parser_error is not None or self.parsed_entries == 0:
            status = 'failed'
        elif skipped or self.error_count:
            status = 'partial'
        elif self.warning_count:
            status = 'warning'
        else:
            status = 'success'

        return {
            'version': 1,
            'filename': os.path.basename(self.file_path),
            'format': self.extension,
            'status': status,
            'detected_entries': detected,
            'parsed_entries': self.parsed_entries,
            'skipped_entries': skipped,
            'missing_abstract_entries': self.missing_abstract_entries,
            'error_count': self.error_count,
            # 诊断 error 不必然阻止发布。citation key、重复 key 和源/解析器
            # 数量差异属于可定位的记录级异常；字段硬限制和解析器崩溃才阻断。
            'blocking_error_count': self.blocking_error_count,
            'warning_count': self.warning_count,
            'candidate_detection_available': detection_error is None,
            'issues_truncated': self.issues_truncated,
            'issues': self.issues,
        }
