from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0030_remove_legacy_screening_file_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemoperationstate',
            name='announcement_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='systemoperationstate',
            name='announcement_level',
            field=models.CharField(
                choices=[('info', '通知'), ('success', '成功'), ('warning', '提醒')],
                default='info',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='systemoperationstate',
            name='announcement_message',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='systemoperationstate',
            name='announcement_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
