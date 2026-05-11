# Generated migration for adding model_select operation type
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_add_prompt_operation_types'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activitylog',
            name='operation_type',
            field=models.CharField(choices=[('file_add', '添加文献索引'), ('file_delete', '删除文献索引'), ('criteria_add', '添加纳排标准'), ('criteria_delete', '删除纳排标准'), ('task_start_parse', '启动文献解析'), ('task_start_dedup', '启动文献去重'), ('task_start_ai_screen', '启动AI初筛'), ('task_start_export', '启动结果归纳'), ('task_stop', '暂停任务'), ('task_resume', '继续任务'), ('task_abandon', '放弃任务'), ('prompt_set', '自定义Prompt'), ('prompt_reset', '重置默认Prompt'), ('model_select', '切换AI模型')], max_length=50, verbose_name='操作类型'),
        ),
    ]