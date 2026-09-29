import core.quality.storage
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0026_qareference_screening_source')]

    operations = [
        migrations.CreateModel(
            name='QAFulltextAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_file', models.FileField(max_length=500, storage=core.quality.storage.qa_fulltext_storage, upload_to=core.quality.storage.qa_fulltext_upload_path, verbose_name='私有 PDF')),
                ('extracted_text_file', models.FileField(blank=True, max_length=500, storage=core.quality.storage.qa_fulltext_storage, upload_to=core.quality.storage.qa_extracted_text_upload_path, verbose_name='私有提取文本')),
                ('original_filename', models.CharField(max_length=255, verbose_name='原始文件名')),
                ('status', models.CharField(choices=[('pending', '等待处理'), ('validating', '正在校验'), ('scanning', '正在扫描'), ('extracting', '正在提取'), ('ready', '可用'), ('rejected', '已拒绝'), ('failed', '处理失败')], db_index=True, default='pending', max_length=20)),
                ('sha256', models.CharField(db_index=True, max_length=64)),
                ('size_bytes', models.PositiveBigIntegerField(default=0)),
                ('mime_type', models.CharField(default='application/pdf', max_length=100)),
                ('page_count', models.PositiveIntegerField(blank=True, null=True)),
                ('scan_status', models.CharField(choices=[('pending', '等待扫描'), ('clean', '安全'), ('not_configured', '未配置扫描器'), ('infected', '发现威胁'), ('failed', '扫描失败')], default='pending', max_length=20)),
                ('extraction_status', models.CharField(choices=[('pending', '等待提取'), ('running', '正在提取'), ('completed', '提取完成'), ('skipped', '无可提取文本'), ('purged', '已按保留策略清理'), ('failed', '提取失败')], default='pending', max_length=20)),
                ('extracted_text_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('extracted_text_chars', models.PositiveIntegerField(default=0)),
                ('error_code', models.CharField(blank=True, default='', max_length=64)),
                ('error_message', models.CharField(blank=True, default='', max_length=500)),
                ('validated_at', models.DateTimeField(blank=True, null=True)),
                ('scanned_at', models.DateTimeField(blank=True, null=True)),
                ('extracted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('qa_reference', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='fulltext_asset', to='core.qareference', verbose_name='质量评价文献')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qa_fulltext_assets', to='core.project', verbose_name='所属项目')),
            ],
            options={
                'verbose_name': '质量评价全文资产',
                'verbose_name_plural': '质量评价全文资产',
                'db_table': 'plat_qa_fulltext_asset',
                'indexes': [models.Index(fields=['status', 'created_at'], name='idx_qafa_status_created')],
                'constraints': [models.UniqueConstraint(fields=('project', 'sha256'), name='uniq_qafa_project_sha256')],
            },
        ),
    ]
