from django.db import migrations


ARTIFACT_TYPES_BY_DESCRIPTION = {
    '合并后的文献XML': 'screening_parsed_references_xml',
    '单篇文献XML': 'screening_parsed_reference_xml',
    '去重后的文献XML': 'screening_dedup_reference_xml',
    '去重报告': 'screening_dedup_report_json',
    'AI筛选结果': 'screening_result_json',
    '初筛结果Excel': 'screening_export_xlsx',
    '初筛结果RIS': 'screening_export_ris',
    'QA交通灯图': 'qa_traffic_light_png',
    'QA比例图': 'qa_proportion_png',
}


def backfill_artifact_types(apps, schema_editor):
    DataFile = apps.get_model('core', 'DataFile')
    for data_file in DataFile.objects.filter(description__in=ARTIFACT_TYPES_BY_DESCRIPTION).iterator():
        metadata = dict(data_file.metadata or {})
        if metadata.get('artifact_type'):
            continue
        metadata['artifact_type'] = ARTIFACT_TYPES_BY_DESCRIPTION[data_file.description]
        metadata['_artifact_type_backfilled_by'] = '0020'
        DataFile.objects.filter(pk=data_file.pk).update(metadata=metadata)


def reverse_backfill(apps, schema_editor):
    DataFile = apps.get_model('core', 'DataFile')
    for data_file in DataFile.objects.all().iterator():
        metadata = dict(data_file.metadata or {})
        if metadata.get('_artifact_type_backfilled_by') != '0020':
            continue
        metadata.pop('artifact_type', None)
        metadata.pop('_artifact_type_backfilled_by', None)
        DataFile.objects.filter(pk=data_file.pk).update(metadata=metadata)


class Migration(migrations.Migration):
    dependencies = [('core', '0019_alter_projectstage_status_alter_stagestep_status_and_more')]
    operations = [migrations.RunPython(backfill_artifact_types, reverse_backfill)]
