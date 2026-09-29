import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_qa_fulltext_asset'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScreeningReferenceRawMetadata',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_format', models.CharField(max_length=32, verbose_name='来源格式')),
                ('raw_fields', models.JSONField(blank=True, default=dict, verbose_name='完整原始字段')),
                ('raw_size_bytes', models.PositiveBigIntegerField(default=0, verbose_name='原始字段字节数')),
                ('raw_hash', models.CharField(max_length=64, verbose_name='原始字段哈希')),
                ('parser_version', models.CharField(blank=True, default='', max_length=50, verbose_name='解析器版本')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('import_file', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='raw_metadata_records', to='core.referenceimportfile', verbose_name='导入文件')),
                ('reference', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='raw_metadata_record', to='core.screeningreference', verbose_name='标准化文献')),
            ],
            options={
                'verbose_name': '文献原始元数据',
                'verbose_name_plural': '文献原始元数据',
                'db_table': 'plat_screening_reference_raw',
                'ordering': ['reference_id'],
                'indexes': [models.Index(fields=['import_file', 'source_format'], name='sc_raw_file_format_idx')],
            },
        ),
    ]
