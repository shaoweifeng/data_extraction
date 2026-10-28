"""Bounded staging writes; no row becomes active until batch publication."""
import hashlib
from django.db import transaction

from core.bibliography import bibliography_fields
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenReference, RescreenReferenceRawMetadata
from core.rescreening.services.source import digest
from core.screening.services.reference_persistence import _raw_metadata_payload, normalize_doi, normalize_title


class ReferenceWriter:
    def __init__(self, batch, limits):
        self.batch, self.limits, self.buffer, self.written = batch, limits, [], 0

    def add(self, record, *, source_file=None, source_reference=None, source_run=None,
            source_snapshot=None, extracted_fields=None, field_definitions=None, source_key=None):
        from core.screening.parsers.validation import validate_reference_record
        validate_reference_record(record, self.limits)
        fields = bibliography_fields(record)
        for name, value in fields.items():
            maximum = RescreenReference._meta.get_field(name).max_length
            if maximum and len(value) > maximum:
                raise RescreenError('field_too_long', f'字段 {name} 超过存储上限 {maximum}，不会静默截断。')
        position = int(record.get('source_position') or 0)
        if position < 1:
            raise RescreenError('invalid_source_position', '来源记录序号无效。')
        key = source_key or (f'screening:{source_reference.pk}' if source_reference else f'file:{source_file.pk}:{position}')
        ref = RescreenReference(
            project_id=self.batch.project_id, corpus_id=self.batch.corpus_id, import_batch=self.batch,
            import_file=source_file, source_key=key, source_record_index=position,
            source_reference=source_reference, source_screening_run=source_run,
            source_snapshot=source_snapshot or {}, introduced_revision=self.batch.target_revision,
            normalized_doi=normalize_doi(fields['doi']),
            normalized_title_hash=hashlib.sha256(normalize_title(fields['title']).encode('utf-8')).hexdigest(),
            record_hash=digest(fields), **fields,
        )
        raw_fields, raw_size, raw_hash = _raw_metadata_payload(record)
        self.buffer.append((ref, dict(raw_fields=raw_fields, raw_size_bytes=raw_size, raw_hash=raw_hash,
            source_format=record.get('source_type') or (source_file.source_format if source_file else 'screening'),
            parser_version=str(record.get('_parser_version') or 'shared-reference-v1'),
            source_extracted_fields=extracted_fields or {}, source_field_definitions=field_definitions or {})))
        if len(self.buffer) >= self.limits.db_batch_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        with transaction.atomic():
            references = [row[0] for row in self.buffer]
            RescreenReference.objects.bulk_create(references, batch_size=self.limits.db_batch_size)
            # MySQL doesn't return auto-increment IDs from bulk_create.
            persisted = {row.source_key: row for row in RescreenReference.objects.filter(
                import_batch=self.batch, source_key__in=[ref.source_key for ref in references],
            ).only('pk', 'source_key')}
            RescreenReferenceRawMetadata.objects.bulk_create([
                RescreenReferenceRawMetadata(reference=persisted[ref.source_key], **raw)
                for ref, raw in self.buffer
            ], batch_size=self.limits.db_batch_size)
        self.written += len(self.buffer)
        self.buffer.clear()
