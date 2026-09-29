"""Bounded-memory persistence for normalized screening references."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from django.db import DatabaseError

from core.screening.models import (
    ReferenceImportBatch,
    ScreeningReference,
    ScreeningReferenceRawMetadata,
)
from core.screening.services.import_errors import ScreeningImportError
from core.screening.services.import_limits import ImportLimits


def _text(value: Any) -> str:
    return str(value or '').strip()


def normalize_title(value: Any) -> str:
    return ''.join(char.lower() for char in _text(value) if char.isalnum())


def normalize_doi(value: Any) -> str:
    doi = _text(value).lower()
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi)
    doi = re.sub(r'^doi\s*:\s*', '', doi)
    return doi.rstrip('.,; ')


def _string_list(value: Any, *, separators=r'[;\n]') -> list[str]:
    if not value:
        return []
    values = value if isinstance(value, (list, tuple)) else re.split(separators, str(value))
    return [str(item).strip() for item in values if str(item).strip()]


def _pubmed_identifier(record: Mapping[str, Any]) -> str:
    source_type = _text(record.get('source_type')).upper()
    identifier = _text(record.get('source_identifier') or record.get('record_number'))
    if source_type == 'NBIB' and identifier.isdigit():
        return identifier
    match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', _text(record.get('url')))
    return match.group(1) if match else ''


def _record_hash_payload(record: Mapping[str, Any], normalized_title: str, normalized_doi: str) -> dict:
    return {
        'title': normalized_title,
        'doi': normalized_doi,
        'authors': _string_list(record.get('authors')),
        'year': _text(record.get('year')),
        'journal': _text(record.get('journal')).casefold(),
        'abstract': _text(record.get('abstract')),
    }


def _raw_metadata_payload(record: Mapping[str, Any]) -> tuple[dict, int, str]:
    """Return JSON-safe source fields, their UTF-8 size and a stable digest."""
    raw_fields = record.get('_raw_metadata') or {}
    if not isinstance(raw_fields, Mapping):
        raw_fields = {'value': raw_fields}
    serialized = json.dumps(
        raw_fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str,
    )
    encoded = serialized.encode('utf-8')
    return json.loads(serialized), len(encoded), hashlib.sha256(encoded).hexdigest()


def build_reference(
    record: Mapping[str, Any], *, batch: ReferenceImportBatch, import_file,
) -> ScreeningReference:
    """Map one parser record to the database schema without silent truncation."""
    title = _text(record.get('title'))
    normalized_title = normalize_title(title)
    normalized_doi = normalize_doi(record.get('doi'))
    source_identifier = _text(
        record.get('source_identifier') or record.get('record_number')
    )
    position = int(record.get('source_position') or 0)
    if position <= 0:
        raise ScreeningImportError(
            'invalid_source_position', '解析器返回了无效的来源记录序号。',
            details={'filename': import_file.original_filename, 'position': position},
        )

    record_payload = _record_hash_payload(record, normalized_title, normalized_doi)
    return ScreeningReference(
        project_id=batch.project_id,
        corpus_id=batch.corpus_id,
        import_batch_id=batch.id,
        import_file_id=import_file.id,
        source_file_id=import_file.source_file_id,
        source_record_index=position,
        source_record_key=source_identifier,
        source_identifier=source_identifier,
        introduced_revision=batch.target_revision,
        title=title,
        abstract=_text(record.get('abstract')),
        authors=_string_list(record.get('authors')),
        journal=_text(record.get('journal')),
        publication_year=_text(record.get('year')),
        publication_date=_text(record.get('date')),
        doi=_text(record.get('doi')),
        normalized_doi=normalized_doi,
        pmid=_pubmed_identifier(record),
        pmcid=_text(record.get('pmcid')),
        url=_text(record.get('url')),
        publication_type=_text(record.get('reference_type') or record.get('type')),
        volume=_text(record.get('volume')),
        issue=_text(record.get('issue')),
        pages=_text(record.get('page')),
        keywords=_string_list(record.get('keywords')),
        language=_text(record.get('language')),
        address=_text(record.get('address')),
        normalized_title_hash=hashlib.sha256(normalized_title.encode('utf-8')).hexdigest(),
        record_hash=hashlib.sha256(
            json.dumps(
                record_payload, ensure_ascii=False, sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')
        ).hexdigest(),
    )


class ScreeningReferenceBulkWriter:
    """Write one import batch in fixed-size committed chunks."""

    def __init__(
        self, batch_id: int, *, limits: ImportLimits | None = None,
        on_flush=None,
    ):
        self.limits = limits or ImportLimits.from_settings()
        self.batch = ReferenceImportBatch.objects.select_related('corpus').get(pk=batch_id)
        self.import_files = {
            item.source_file_id: item
            for item in self.batch.files.select_related('source_file').all()
        }
        self.pending: list[tuple[ScreeningReference, dict]] = []
        self.written_count = 0
        self.on_flush = on_flush

    def add(self, record: Mapping[str, Any]) -> None:
        source_file_id = record.get('_source_file_id')
        import_file = self.import_files.get(source_file_id)
        if import_file is None:
            raise ScreeningImportError(
                'invalid_reference_source', '解析结果无法关联到本次导入来源文件。',
                details={'source_file_id': source_file_id},
            )
        raw_fields, raw_size, raw_hash = _raw_metadata_payload(record)
        reference = build_reference(record, batch=self.batch, import_file=import_file)
        self.pending.append((reference, {
            'import_file_id': import_file.id,
            'source_format': _text(record.get('source_type') or import_file.source_format)[:32],
            'raw_fields': raw_fields,
            'raw_size_bytes': raw_size,
            'raw_hash': raw_hash,
            'parser_version': self.batch.parser_version,
        }))
        if len(self.pending) >= self.limits.db_batch_size:
            self.flush()

    def flush(self) -> int:
        if not self.pending:
            return 0
        pending = self.pending
        self.pending = []
        rows = [reference for reference, _raw in pending]
        try:
            ScreeningReference.objects.bulk_create(
                rows, batch_size=self.limits.db_batch_size,
            )
            positions = {reference.source_record_index for reference in rows}
            import_file_ids = {reference.import_file_id for reference in rows}
            stored_references = ScreeningReference.objects.filter(
                import_batch_id=self.batch.id,
                import_file_id__in=import_file_ids,
                source_record_index__in=positions,
            ).only('id', 'import_file_id', 'source_record_index')
            reference_ids = {
                (reference.import_file_id, reference.source_record_index): reference.id
                for reference in stored_references
            }
            raw_rows = []
            for reference, raw in pending:
                reference_id = reference_ids.get(
                    (reference.import_file_id, reference.source_record_index)
                )
                if reference_id is None:
                    raise ScreeningImportError(
                        'raw_metadata_reference_missing',
                        '原始元数据无法关联到已写入的标准化文献。',
                    )
                raw_rows.append(ScreeningReferenceRawMetadata(
                    reference_id=reference_id,
                    **raw,
                ))
            ScreeningReferenceRawMetadata.objects.bulk_create(
                raw_rows, batch_size=self.limits.db_batch_size,
            )
        except DatabaseError as exc:
            raise ScreeningImportError(
                'reference_persistence_failed', '标准化文献分批写入数据库失败。',
            ) from exc
        self.written_count += len(rows)
        if self.on_flush is not None:
            self.on_flush(len(rows), self.written_count)
        return len(rows)

    def finalize(self) -> int:
        self.flush()
        return self.written_count
