from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0025_manualreview_screening_run'),
    ]

    operations = [
        migrations.AddField(
            model_name='qareference',
            name='source_screening_decision',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='导入时最终筛选决定'),
        ),
        migrations.AddField(
            model_name='qareference',
            name='source_screening_run',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='qa_references', to='core.screeningrun', verbose_name='来源 AI 初筛运行'),
        ),
        migrations.AddIndex(
            model_name='qareference',
            index=models.Index(fields=['source_screening_run', 'source_reference'], name='idx_qar_run_ref'),
        ),
    ]
