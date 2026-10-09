from django.db import migrations, models

import core.quality.storage


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0031_system_operation_announcement'),
    ]

    operations = [
        migrations.AddField(
            model_name='qafulltextasset',
            name='chunk_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='chunk_index_file',
            field=models.FileField(
                blank=True,
                max_length=500,
                storage=core.quality.storage.qa_fulltext_storage,
                upload_to=core.quality.storage.qa_chunk_index_upload_path,
                verbose_name='私有全文分块索引',
            ),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='chunk_index_sha256',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='chunking_version',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='extracted_page_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='extraction_truncated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='extraction_version',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='qafulltextasset',
            name='truncated_at_page',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
