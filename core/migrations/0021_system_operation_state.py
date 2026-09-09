from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0020_backfill_artifact_types'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemOperationState',
            fields=[
                ('singleton_id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('mode', models.CharField(choices=[('normal', '正常运行'), ('draining', '正在排空'), ('maintenance', '维护中')], default='normal', max_length=20)),
                ('message', models.CharField(blank=True, default='', max_length=500)),
                ('scheduled_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='system_operation_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '系统运行状态',
                'verbose_name_plural': '系统运行状态',
                'db_table': 'plat_system_operation_state',
            },
        ),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['status', 'created_at'], name='task_status_created_idx'),
        ),
    ]
