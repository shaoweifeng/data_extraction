from django.db import migrations, models


def backfill_flat_raw_metadata(apps, schema_editor):
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

    def values(raw, *keys):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if value not in (None, ''):
                import re
                return [item.strip() for item in re.split(r'[,;]', str(value)) if item.strip()]
        return []

    for raw_row in RawMetadata.objects.select_related('reference').iterator(chunk_size=500):
        raw = raw_row.raw_fields if isinstance(raw_row.raw_fields, dict) else {}
        if 'raw_xml' in raw:
            continue
        reference = raw_row.reference
        updates = {}
        mappings = {
            'pmid': ('pmid', 'PMID'),
            'pmcid': ('pmcid', 'PMCID', 'PMC', 'custom2', 'C2'),
            'isbn': ('isbn', 'ISBN', 'BN'),
            'issn': ('issn', 'ISSN', 'SN', 'serial_number', '%@'),
            'language': ('language', 'LA', '%G'),
            'publisher': ('publisher', 'PB', 'PU', '%I'),
            'database': ('database', 'name_of_database', 'DB', '%W'),
            'organization': ('organization', 'institution', 'OG'),
            'source_identifier': ('source_identifier', 'id', 'ID', 'accession_number', 'AN', '%M'),
        }
        for field, keys in mappings.items():
            if not getattr(reference, field, ''):
                value = first(raw, *keys)
                if value:
                    updates[field] = value
        if not reference.pmid and not updates.get('pmid'):
            database = updates.get('database') or reference.database
            accession = updates.get('source_identifier') or reference.source_identifier
            if database.casefold() in {'pubmed', 'medline'} and accession:
                normalized_pmid = accession.removeprefix('PMID:').strip()
                if normalized_pmid.isdigit():
                    updates['pmid'] = normalized_pmid
        if not reference.keywords:
            keywords = values(raw, 'keywords', 'KW', 'OT', 'MH', 'DE', 'ID', '%K')
            if keywords:
                updates['keywords'] = keywords
        if updates:
            Reference.objects.filter(pk=reference.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [('core', '0043_expand_datafile_storage_path')]

    operations = [
        migrations.AddField(
            model_name='screeningreference', name='issn',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='ISSN'),
        ),
        migrations.AddField(
            model_name='screeningreference', name='publisher',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='出版商'),
        ),
        migrations.AddField(
            model_name='screeningreference', name='database',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='来源数据库'),
        ),
        migrations.AddField(
            model_name='screeningreference', name='organization',
            field=models.TextField(blank=True, default='', verbose_name='机构'),
        ),
        migrations.RunPython(backfill_flat_raw_metadata, migrations.RunPython.noop),
    ]
