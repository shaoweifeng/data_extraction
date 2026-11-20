from django.db import migrations, models


def populate_modes(apps, schema_editor):
    Corpus = apps.get_model('core', 'RescreenCorpus')
    Batch = apps.get_model('core', 'RescreenImportBatch')
    alias = schema_editor.connection.alias
    for corpus in Corpus.objects.using(alias).iterator(chunk_size=500):
        modes = list(Batch.objects.using(alias).filter(corpus_id=corpus.pk).values_list('source_type', flat=True).distinct())
        mode = modes[0] if len(modes) == 1 and modes[0] in ('screening', 'bibliography', 'pdf') else 'mixed' if modes else ''
        Corpus.objects.using(alias).filter(pk=corpus.pk).update(import_mode=mode)


class Migration(migrations.Migration):
    dependencies = [('core', '0056_localize_rescreen_admin')]
    operations = [
        migrations.AddField(model_name='rescreencorpus', name='import_mode',
            field=models.CharField(verbose_name='固定导入模式', max_length=20, blank=True, default='',
                choices=[('screening', '初筛导入'), ('bibliography', '上传题录'), ('pdf', '上传全文'), ('mixed', '历史混合模式')])),
        migrations.RunPython(populate_modes, migrations.RunPython.noop),
    ]
