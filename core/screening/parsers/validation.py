"""Shared validation for normalized screening reference records."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


_STORAGE_FIELD_LIMITS = {
    'journal': 500,
    'year': 20,
    'date': 50,
    'doi': 255,
    'pmcid': 64,
    'reference_type': 100,
    'type': 100,
    'volume': 100,
    'issue': 100,
    'page': 100,
    'source_identifier': 255,
    'record_number': 255,
}


@dataclass(frozen=True)
class ReferenceRecordValidationError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _text_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, Mapping):
        return sum(_text_size(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return sum(_text_size(item) for item in value)
    return len(str(value))


def validate_reference_record(record: Mapping[str, Any], limits) -> None:
    """Reject a pathological normalized record before it reaches persistence."""
    title = str(record.get('title') or '')
    if len(title) > limits.max_title_chars:
        raise ReferenceRecordValidationError(
            'title_too_long',
            f'文献标题长度 {len(title)} 超过 {limits.max_title_chars} 字符上限。',
        )

    abstract = str(record.get('abstract') or '')
    if len(abstract) > limits.max_abstract_chars:
        raise ReferenceRecordValidationError(
            'abstract_too_long',
            f'文献摘要长度 {len(abstract)} 超过 {limits.max_abstract_chars} 字符上限。',
        )

    authors = record.get('authors') or []
    if not isinstance(authors, (list, tuple)):
        raise ReferenceRecordValidationError(
            'invalid_authors', '文献作者字段不是有效列表。',
        )
    if len(authors) > limits.max_authors:
        raise ReferenceRecordValidationError(
            'too_many_authors',
            f'文献作者数 {len(authors)} 超过 {limits.max_authors} 人上限。',
        )

    for field, max_chars in _STORAGE_FIELD_LIMITS.items():
        value = str(record.get(field) or '')
        if len(value) > max_chars:
            raise ReferenceRecordValidationError(
                'field_too_long',
                f'文献字段 {field} 长度 {len(value)} 超过 {max_chars} 字符存储上限。',
            )

    record_text_chars = _text_size({
        key: value for key, value in record.items() if not str(key).startswith('_')
    })
    if record_text_chars > limits.max_record_text_chars:
        raise ReferenceRecordValidationError(
            'record_too_large',
            f'单条文献文本总量 {record_text_chars} 超过 {limits.max_record_text_chars} 字符上限。',
        )

    raw_metadata = record.get('_raw_metadata') or {}
    try:
        raw_size = len(json.dumps(
            raw_metadata, ensure_ascii=False, separators=(',', ':'), default=str,
        ).encode('utf-8'))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReferenceRecordValidationError(
            'invalid_raw_metadata', '原始文献元数据无法安全序列化。',
        ) from exc
    max_raw_metadata_bytes = getattr(limits, 'max_raw_metadata_bytes', 524288)
    if raw_size > max_raw_metadata_bytes:
        raise ReferenceRecordValidationError(
            'raw_metadata_too_large',
            f'单条原始元数据大小 {raw_size} 字节超过 {max_raw_metadata_bytes} 字节上限。',
        )
