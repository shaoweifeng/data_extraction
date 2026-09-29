import hashlib
import json

from django.db import migrations


def move_raw_metadata_to_cold_table(apps, schema_editor):
    Reference = apps.get_model('core', 'ScreeningReference')
    RawMetadata = apps.get_model('core', 'ScreeningReferenceRawMetadata')
    pending = []
    queryset = Reference.objects.select_related('import_batch', 'import_file').order_by('id')
    for reference in queryset.iterator(chunk_size=1000):
        raw_fields = reference.raw_metadata or {}
        serialized = json.dumps(
            raw_fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str,
        )
        encoded = serialized.encode('utf-8')
        pending.append(RawMetadata(
            reference_id=reference.id,
            import_file_id=reference.import_file_id,
            source_format=str(
                raw_fields.get('source_type') or reference.import_file.source_format or ''
            )[:32],
            raw_fields=raw_fields,
            raw_size_bytes=len(encoded),
            raw_hash=hashlib.sha256(encoded).hexdigest(),
            parser_version=reference.import_batch.parser_version,
        ))
        if len(pending) >= 1000:
            RawMetadata.objects.bulk_create(pending, batch_size=1000, ignore_conflicts=True)
            pending = []
    if pending:
        RawMetadata.objects.bulk_create(pending, batch_size=1000, ignore_conflicts=True)


def restore_raw_metadata_to_reference(apps, schema_editor):
    Reference = apps.get_model('core', 'ScreeningReference')
    RawMetadata = apps.get_model('core', 'ScreeningReferenceRawMetadata')
    pending = []
    for raw in RawMetadata.objects.order_by('reference_id').iterator(chunk_size=1000):
        pending.append(Reference(pk=raw.reference_id, raw_metadata=raw.raw_fields or {}))
        if len(pending) >= 1000:
            Reference.objects.bulk_update(pending, ['raw_metadata'], batch_size=1000)
            pending = []
    if pending:
        Reference.objects.bulk_update(pending, ['raw_metadata'], batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_screening_reference_raw_metadata'),
    ]

    operations = [
        migrations.RunPython(
            move_raw_metadata_to_cold_table,
            restore_raw_metadata_to_reference,
        ),
        migrations.RemoveField(
            model_name='screeningreference',
            name='raw_metadata',
        ),
    ]
