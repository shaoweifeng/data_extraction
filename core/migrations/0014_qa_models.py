# Generated manually 2026-08-28
# 文献质量评价模块：新增 4 张表，全部前缀 plat_qa_
# 不改动任何已有表结构

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_manualreview_add_notes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── 1. QAReference ────────────────────────────────────────────
        migrations.CreateModel(
            name='QAReference',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=500, verbose_name='文献标题')),
                ('first_author', models.CharField(blank=True, default='', max_length=200, verbose_name='第一作者')),
                ('year', models.IntegerField(blank=True, null=True, verbose_name='发表年份')),
                ('journal', models.CharField(blank=True, default='', max_length=300, verbose_name='期刊')),
                ('abstract', models.TextField(blank=True, default='', verbose_name='摘要')),
                ('doi', models.CharField(blank=True, default='', max_length=200, verbose_name='DOI')),
                ('source_type', models.CharField(
                    choices=[
                        ('screening_import', '从初筛/复筛导入'),
                        ('bibliography_upload', '上传题录'),
                        ('fulltext_upload', '上传全文文件'),
                    ],
                    default='fulltext_upload',
                    max_length=50,
                    verbose_name='来源类型',
                )),
                ('source_ref_id', models.IntegerField(blank=True, null=True, verbose_name='来源文献ID（初筛/复筛导入时）')),
                ('fulltext_status', models.CharField(
                    choices=[
                        ('available', '已有全文'),
                        ('pending', '待获取'),
                        ('missing', '无全文'),
                        ('error', '错误'),
                    ],
                    default='pending',
                    max_length=20,
                    verbose_name='全文状态',
                )),
                ('quality_method', models.CharField(
                    blank=True,
                    choices=[
                        ('QUADAS2', 'QUADAS-2'),
                        ('NOS', 'NOS'),
                        ('ROB2', 'RoB 2'),
                        ('AMSTAR2', 'AMSTAR 2'),
                        ('ROBINS_I', 'ROBINS-I'),
                    ],
                    default='',
                    max_length=20,
                    verbose_name='质量评价方法',
                )),
                ('eval_mode', models.CharField(
                    blank=True,
                    choices=[('single', '单模型评价'), ('dual', '双模型校验')],
                    default='',
                    max_length=20,
                    verbose_name='评价模式',
                )),
                ('selected_models', models.JSONField(blank=True, default=list, verbose_name='选择的模型ID列表')),
                ('ai_eval_status', models.CharField(
                    choices=[
                        ('pending', '待评价'),
                        ('running', '评价中'),
                        ('completed', '已完成'),
                        ('failed', '失败'),
                        ('skipped_no_fulltext', '跳过（无全文/摘要）'),
                        ('skipped_no_method', '跳过（未选方法）'),
                        ('abstract_only', '基于摘要评价'),
                    ],
                    default='pending',
                    max_length=30,
                    verbose_name='AI评价状态',
                )),
                ('review_status', models.CharField(
                    choices=[
                        ('not_started', '未开始'),
                        ('partial', '部分确认'),
                        ('confirmed', '已确认'),
                    ],
                    default='not_started',
                    max_length=20,
                    verbose_name='人工审阅状态',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='qa_references',
                    to='core.project',
                    verbose_name='所属项目',
                )),
                ('fulltext_file', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='qa_references',
                    to='core.datafile',
                    verbose_name='全文PDF文件',
                )),
            ],
            options={
                'verbose_name': '待评价文献',
                'verbose_name_plural': '待评价文献',
                'db_table': 'plat_qa_reference',
                'ordering': ['id'],
                'indexes': [
                    models.Index(fields=['project', 'quality_method'], name='idx_qar_proj_method'),
                    models.Index(fields=['project', 'review_status'], name='idx_qar_proj_review'),
                ],
            },
        ),

        # ── 2. QASignalItem ───────────────────────────────────────────
        migrations.CreateModel(
            name='QASignalItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quality_method', models.CharField(max_length=20, verbose_name='评价方法')),
                ('domain', models.CharField(max_length=50, verbose_name='领域key')),
                ('result_type', models.CharField(
                    choices=[('bias_risk', '风险偏倚'), ('applicability', '适用性担忧')],
                    max_length=20,
                    verbose_name='结果类型',
                )),
                ('signal_key', models.CharField(max_length=100, verbose_name='信号问题标识符')),
                ('signal_question', models.CharField(max_length=500, verbose_name='信号问题')),
                ('signal_description', models.CharField(blank=True, default='', max_length=1000, verbose_name='中文释义')),
                ('options', models.JSONField(default=list, verbose_name='可选值列表')),
                # 单模型
                ('ai_judgment', models.CharField(blank=True, default='', max_length=50, verbose_name='单模型AI判断')),
                ('ai_reason', models.TextField(blank=True, default='', verbose_name='单模型判断理由')),
                ('ai_evidence', models.TextField(blank=True, default='', verbose_name='证据原文')),
                ('ai_evidence_page', models.CharField(blank=True, default='', max_length=100, verbose_name='证据位置')),
                # 双模型
                ('model1_id', models.CharField(blank=True, default='', max_length=100, verbose_name='模型1 ID')),
                ('model1_judgment', models.CharField(blank=True, default='', max_length=50, verbose_name='模型1判断')),
                ('model1_reason', models.TextField(blank=True, default='', verbose_name='模型1理由')),
                ('model2_id', models.CharField(blank=True, default='', max_length=100, verbose_name='模型2 ID')),
                ('model2_judgment', models.CharField(blank=True, default='', max_length=50, verbose_name='模型2判断')),
                ('model2_reason', models.TextField(blank=True, default='', verbose_name='模型2理由')),
                ('consistency', models.CharField(
                    choices=[
                        ('consistent', '模型一致'),
                        ('divergent', '模型分歧'),
                        ('partial', '部分生成'),
                        ('failed', '生成失败'),
                        ('single', '单模型'),
                    ],
                    default='single',
                    max_length=20,
                    verbose_name='一致性状态',
                )),
                ('system_recommendation', models.CharField(blank=True, default='', max_length=50, verbose_name='系统推荐结果')),
                ('pre_selected', models.CharField(blank=True, default='', max_length=50, verbose_name='页面预选值')),
                # 人工确认
                ('human_judgment', models.CharField(blank=True, default='', max_length=50, verbose_name='人工最终判断')),
                ('is_modified', models.BooleanField(default=False, verbose_name='是否修改了AI判断')),
                ('original_ai_judgment', models.CharField(blank=True, default='', max_length=50, verbose_name='修改前原AI判断')),
                ('is_confirmed', models.BooleanField(default=False, verbose_name='是否已人工确认')),
                ('confirmed_at', models.DateTimeField(blank=True, null=True, verbose_name='确认时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('qa_ref', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='signal_items',
                    to='core.qareference',
                    verbose_name='所属文献',
                )),
                ('confirmed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='qa_confirmations',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='确认人',
                )),
            ],
            options={
                'verbose_name': '信号问题评价结果',
                'verbose_name_plural': '信号问题评价结果',
                'db_table': 'plat_qa_signal_item',
                'ordering': ['qa_ref', 'domain', 'id'],
                'indexes': [
                    models.Index(fields=['qa_ref', 'domain'], name='idx_qasi_ref_domain'),
                    models.Index(fields=['qa_ref', 'is_confirmed'], name='idx_qasi_ref_confirmed'),
                ],
            },
        ),

        # ── 3. QADomainResult ─────────────────────────────────────────
        migrations.CreateModel(
            name='QADomainResult',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(max_length=50, verbose_name='领域key')),
                ('domain_name', models.CharField(blank=True, default='', max_length=100, verbose_name='领域显示名称')),
                ('bias_risk_result', models.CharField(
                    choices=[
                        ('low', '低风险'),
                        ('high', '高风险'),
                        ('unclear', '不清楚'),
                        ('pending', '待确认'),
                        ('na', '不适用'),
                    ],
                    default='pending',
                    max_length=20,
                    verbose_name='风险偏倚结果',
                )),
                ('applicability_result', models.CharField(
                    choices=[
                        ('low', '低担忧'),
                        ('high', '高担忧'),
                        ('unclear', '不清楚'),
                        ('pending', '待确认'),
                        ('na', '不适用'),
                    ],
                    default='pending',
                    max_length=20,
                    verbose_name='适用性担忧结果',
                )),
                ('bias_all_confirmed', models.BooleanField(default=False, verbose_name='风险偏倚全部已确认')),
                ('applicability_all_confirmed', models.BooleanField(default=False, verbose_name='适用性全部已确认')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('qa_ref', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='domain_results',
                    to='core.qareference',
                    verbose_name='所属文献',
                )),
            ],
            options={
                'verbose_name': '领域汇总结果',
                'verbose_name_plural': '领域汇总结果',
                'db_table': 'plat_qa_domain_result',
                'ordering': ['qa_ref', 'domain'],
                'unique_together': {('qa_ref', 'domain')},
            },
        ),

        # ── 4. QAChart ────────────────────────────────────────────────
        migrations.CreateModel(
            name='QAChart',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quality_method', models.CharField(max_length=20, verbose_name='评价方法')),
                ('chart_types', models.JSONField(default=list, verbose_name='图表类型列表')),
                ('ref_ids', models.JSONField(default=list, verbose_name='参与作图的文献ID列表')),
                ('generated_at', models.DateTimeField(blank=True, null=True, verbose_name='图表生成时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='qa_charts',
                    to='core.project',
                    verbose_name='所属项目',
                )),
                ('image_file', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='qa_charts_image',
                    to='core.datafile',
                    verbose_name='导出图片文件',
                )),
                ('excel_file', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='qa_charts_excel',
                    to='core.datafile',
                    verbose_name='导出Excel文件',
                )),
            ],
            options={
                'verbose_name': '图表生成记录',
                'verbose_name_plural': '图表生成记录',
                'db_table': 'plat_qa_chart',
                'ordering': ['-created_at'],
            },
        ),
    ]
