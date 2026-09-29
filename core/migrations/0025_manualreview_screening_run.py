import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0024_screeningresult_attempt_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualreview',
            name='screening_run',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='manual_reviews',
                to='core.screeningrun',
                verbose_name='对应 AI 初筛运行',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='manualreview',
            unique_together=set(),
        ),
        migrations.AddIndex(
            model_name='manualreview',
            index=models.Index(
                fields=['screening_run', 'decision'],
                name='idx_mr_run_decision',
            ),
        ),
        migrations.AddConstraint(
            model_name='manualreview',
            constraint=models.UniqueConstraint(
                fields=('screening_run', 'reference'),
                name='uniq_mr_run_reference',
            ),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='operation_type',
            field=models.CharField(
                choices=[
                    ('file_add', '添加文献索引'),
                    ('file_delete', '删除文献索引'),
                    ('criteria_add', '添加纳排标准'),
                    ('criteria_delete', '删除纳排标准'),
                    ('task_start_parse', '启动文献解析'),
                    ('task_start_dedup', '启动文献去重'),
                    ('task_start_ai_screen', '启动AI初筛'),
                    ('task_start_export', '启动结果归纳'),
                    ('task_start_qa_eval', '启动AI质量评价'),
                    ('task_stop', '暂停任务'),
                    ('task_resume', '继续任务'),
                    ('task_abandon', '放弃任务'),
                    ('prompt_set', '自定义Prompt'),
                    ('prompt_reset', '重置默认Prompt'),
                    ('model_select', '切换AI模型'),
                    ('field_extraction_add', '添加提取字段'),
                    ('field_extraction_delete', '删除提取字段'),
                    ('review_decision', '人工审阅决定'),
                    ('review_note', '人工审阅备注'),
                    ('review_complete', '完成人工审阅'),
                    ('qa_import', 'QA导入文献'),
                    ('qa_upload_pdf', 'QA上传全文'),
                    ('qa_set_method', 'QA设置评价方法'),
                    ('qa_confirm_signal', 'QA确认信号问题'),
                    ('qa_batch_confirm', 'QA批量确认'),
                    ('qa_generate_chart', 'QA生成图表'),
                    ('qa_export_excel', 'QA导出Excel'),
                ],
                max_length=50,
                verbose_name='操作类型',
            ),
        ),
    ]
