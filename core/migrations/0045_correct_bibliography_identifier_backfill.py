from django.db import migrations


def correct_identifier_backfill(apps, schema_editor):
    Reference = apps.get_model('core', 'ScreeningReference')
    RawMetadata = apps.get_model('core', 'ScreeningReferenceRawMetadata')

    def first(raw, *keys):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                value = next((item for item in value if item not in (None, '')), '')
            if value not in (None, ''):
                return str(value).strip()
        return ''

    for raw_row in RawMetadata.objects.select_related('reference').iterator(chunk_size=500):
        raw = raw_row.raw_fields if isinstance(raw_row.raw_fields, dict) else {}
        if 'raw_xml' in raw:
            continue
        reference = raw_row.reference
        explicit_pmid = first(raw, 'pmid', 'PMID')
        accession = first(raw, 'source_identifier', 'id', 'ID', 'accession_number', 'AN', '%M')
        database = first(raw, 'database', 'name_of_database', 'DB', '%W') or reference.database
        updates = {}

        if not reference.source_identifier and accession:
            updates['source_identifier'] = accession

        if explicit_pmid:
            if reference.pmid != explicit_pmid:
                updates['pmid'] = explicit_pmid
        elif accession and reference.pmid == accession:
            normalized_pmid = accession.removeprefix('PMID:').strip()
            if database.casefold() in {'pubmed', 'medline'} and normalized_pmid.isdigit():
                updates['pmid'] = normalized_pmid
            else:
                updates['pmid'] = ''

        if updates:
            Reference.objects.filter(pk=reference.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [('core', '0044_complete_screening_bibliography_fields')]

    operations = [
        migrations.RunPython(correct_identifier_backfill, migrations.RunPython.noop),
    ]
