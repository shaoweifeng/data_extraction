"""Persistent inputs and immutable run/review boundaries for SCREEN_2."""
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .storage import PrivateRescreenStorage, rescreen_upload_path, PrivateRescreenExportStorage, rescreen_export_path


class RescreenCorpus(models.Model):
    project = models.OneToOneField('core.Project', on_delete=models.CASCADE, related_name='rescreen_corpus', verbose_name='所属项目')
    revision = models.PositiveBigIntegerField(verbose_name='文献集修订号', default=0)
    active_reference_count = models.PositiveBigIntegerField(verbose_name='有效文献数', default=0)
    current_run = models.ForeignKey('core.RescreenRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='当前复筛运行')
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_corpus'
        verbose_name = '复筛文献集'
        verbose_name_plural = verbose_name


class RescreenImportBatch(models.Model):
    ACTIVE_STATUSES = ('uploaded', 'importing', 'cancelling', 'ready')
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='rescreen_imports', verbose_name='所属项目')
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='imports', verbose_name='复筛文献集')
    source_type = models.CharField(verbose_name='来源类型', max_length=30, choices=[('screening', '初筛导入'), ('bibliography', '上传题录'), ('pdf', '上传全文')])
    status = models.CharField(verbose_name='状态', max_length=20, default='uploaded', choices=[('uploaded', '已上传'), ('importing', '导入中'), ('cancelling', '正在停止'), ('ready', '已就绪'), ('completed', '已完成'), ('failed', '失败'), ('cancelled', '已停止')])
    base_revision = models.PositiveBigIntegerField(verbose_name='导入前修订号')
    target_revision = models.PositiveBigIntegerField(verbose_name='目标修订号')
    source_screening_run = models.ForeignKey('core.ScreeningRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='来源初筛运行')
    source_snapshot = models.JSONField(verbose_name='来源快照', default=dict, blank=True)
    attempts = models.JSONField(verbose_name='重试历史', default=list, blank=True)
    idempotency_key = models.CharField(verbose_name='幂等键', max_length=128)
    request_hash = models.CharField(verbose_name='请求摘要', max_length=64)
    task = models.ForeignKey('core.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='rescreen_imports', verbose_name='关联任务')
    limits_snapshot = models.JSONField(verbose_name='资源限制快照', default=dict)
    accepted_count = models.PositiveBigIntegerField(verbose_name='成功导入数', default=0)
    rejected_count = models.PositiveBigIntegerField(verbose_name='拒绝条目数', default=0)
    skipped_count = models.PositiveBigIntegerField(verbose_name='跳过条目数', default=0)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    error_message = models.CharField(verbose_name='错误说明', max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    finished_at = models.DateTimeField(verbose_name='结束时间', null=True, blank=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_import_batch'
        verbose_name = '复筛导入批次'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['project', 'idempotency_key'], name='rs_import_idempotency_unique')]
        indexes = [models.Index(fields=['project', 'status'], name='rs_import_project_status_idx')]


class RescreenImportFile(models.Model):
    batch = models.ForeignKey(RescreenImportBatch, on_delete=models.CASCADE, related_name='files', verbose_name='导入批次')
    raw_file = models.FileField(verbose_name='原始文件', storage=PrivateRescreenStorage(), upload_to=rescreen_upload_path, max_length=500)
    original_filename = models.CharField(verbose_name='原始文件名', max_length=255)
    source_format = models.CharField(verbose_name='来源格式', max_length=32)
    sha256 = models.CharField(verbose_name='文件 SHA-256', max_length=64)
    size_bytes = models.PositiveBigIntegerField(verbose_name='文件大小（字节）')
    report = models.JSONField(verbose_name='解析报告', default=dict, blank=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_import_file'
        verbose_name = '复筛题录源文件'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['batch', 'sha256'], name='rs_import_file_sha_unique')]


class RescreenReferenceQuerySet(models.QuerySet):
    def published(self):
        return self.filter(import_batch__status='completed', introduced_revision__lte=F('corpus__revision'))

    def active(self):
        return self.published().filter(removed_revision__isnull=True)


class RescreenReference(models.Model):
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='rescreen_references', verbose_name='所属项目')
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='references', verbose_name='复筛文献集')
    import_batch = models.ForeignKey(RescreenImportBatch, on_delete=models.RESTRICT, related_name='references', verbose_name='导入批次')
    import_file = models.ForeignKey(RescreenImportFile, null=True, blank=True, on_delete=models.RESTRICT, related_name='references', verbose_name='来源题录文件')
    source_key = models.CharField(verbose_name='来源唯一键', max_length=160)
    source_record_index = models.PositiveBigIntegerField(verbose_name='来源记录序号', default=1)
    source_identifier = models.CharField(verbose_name='来源标识', max_length=255, blank=True, default='')
    source_reference = models.ForeignKey('core.ScreeningReference', null=True, blank=True, on_delete=models.SET_NULL, related_name='rescreen_references', verbose_name='来源初筛文献')
    source_screening_run = models.ForeignKey('core.ScreeningRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='来源初筛运行')
    source_snapshot = models.JSONField(verbose_name='来源快照', default=dict, blank=True)
    introduced_revision = models.PositiveBigIntegerField(verbose_name='引入修订号')
    removed_revision = models.PositiveBigIntegerField(verbose_name='移除修订号', null=True, blank=True)
    input_version = models.PositiveBigIntegerField(verbose_name='输入版本', default=1)
    title = models.TextField(verbose_name='文献标题')
    abstract = models.TextField(verbose_name='摘要', blank=True, default='')
    authors = models.JSONField(verbose_name='作者', default=list, blank=True)
    journal = models.CharField(verbose_name='期刊', max_length=500, blank=True, default='')
    publication_year = models.CharField(verbose_name='发表年份', max_length=20, blank=True, default='')
    publication_date = models.CharField(verbose_name='发表日期', max_length=50, blank=True, default='')
    doi = models.CharField(verbose_name='DOI', max_length=255, blank=True, default='')
    normalized_doi = models.CharField(verbose_name='标准化 DOI', max_length=255, blank=True, default='')
    pmid = models.CharField(verbose_name='PMID', max_length=64, blank=True, default='')
    pmcid = models.CharField(verbose_name='PMCID', max_length=64, blank=True, default='')
    isbn = models.CharField(verbose_name='ISBN', max_length=64, blank=True, default='')
    issn = models.CharField(verbose_name='ISSN', max_length=64, blank=True, default='')
    url = models.TextField(verbose_name='链接地址', blank=True, default='')
    publication_type = models.CharField(verbose_name='文献类型', max_length=100, blank=True, default='')
    volume = models.CharField(verbose_name='卷', max_length=100, blank=True, default='')
    issue = models.CharField(verbose_name='期', max_length=100, blank=True, default='')
    pages = models.CharField(verbose_name='页码', max_length=100, blank=True, default='')
    keywords = models.JSONField(verbose_name='关键词', default=list, blank=True)
    language = models.CharField(verbose_name='语言', max_length=50, blank=True, default='')
    publisher = models.CharField(verbose_name='出版机构', max_length=500, blank=True, default='')
    database = models.CharField(verbose_name='来源数据库', max_length=255, blank=True, default='')
    organization = models.TextField(verbose_name='作者单位', blank=True, default='')
    address = models.TextField(verbose_name='地址', blank=True, default='')
    normalized_title_hash = models.CharField(verbose_name='标准化标题摘要', max_length=64)
    record_hash = models.CharField(verbose_name='书目内容摘要', max_length=64)
    # Empty until the corresponding later phases expose these features.
    current_binding = models.ForeignKey('core.RescreenFulltextBinding', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='当前全文绑定')
    current_review = models.ForeignKey('core.RescreenReview', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='当前人工审核')
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)
    objects = RescreenReferenceQuerySet.as_manager()

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_reference'
        verbose_name = '复筛文献'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=['project', 'source_key'], name='rs_ref_source_unique'),
            models.CheckConstraint(condition=Q(removed_revision__isnull=True) | Q(removed_revision__gt=F('introduced_revision')), name='rs_ref_revision_order'),
        ]
        indexes = [
            models.Index(fields=['project', 'removed_revision', 'id'], name='rs_ref_project_active_idx'),
            models.Index(fields=['project', 'normalized_doi'], name='rs_ref_doi_idx'),
            models.Index(fields=['project', 'normalized_title_hash'], name='rs_ref_title_idx'),
        ]

    def __str__(self):
        return self.title[:100]


class RescreenReferenceRawMetadata(models.Model):
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='raw_metadata_versions', verbose_name='复筛文献')
    input_version = models.PositiveBigIntegerField(verbose_name='输入版本', default=1)
    raw_fields = models.JSONField(verbose_name='原始元数据', default=dict)
    source_format = models.CharField(verbose_name='来源格式', max_length=32)
    raw_size_bytes = models.PositiveBigIntegerField(verbose_name='原始元数据大小（字节）')
    raw_hash = models.CharField(verbose_name='原始元数据摘要', max_length=64)
    parser_version = models.CharField(verbose_name='解析器版本', max_length=50, blank=True)
    source_extracted_fields = models.JSONField(verbose_name='来源提取字段', default=dict, blank=True)
    source_field_definitions = models.JSONField(verbose_name='来源字段定义', default=dict, blank=True)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_reference_raw'
        constraints = [models.UniqueConstraint(fields=['reference', 'input_version'], name='rs_raw_version_unique')]
        verbose_name = '复筛原始元数据版本'
        verbose_name_plural = verbose_name

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError('原始元数据快照不可覆盖，请创建新版本。')
        return super().save(*args, **kwargs)


class RescreenCriteriaRevision(models.Model):
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='criteria_versions', verbose_name='复筛文献集')
    revision = models.PositiveBigIntegerField(verbose_name='文献集修订号')
    criteria = models.JSONField(verbose_name='排除标准', default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_criteria_revision'
        verbose_name = '复筛排除标准修订'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['corpus', 'revision'], name='rs_criteria_revision_unique')]


class RescreenSettings(models.Model):
    """Private prompt configuration is not part of publicly serialized Stage metadata."""
    corpus = models.OneToOneField(RescreenCorpus, on_delete=models.CASCADE, related_name='settings', verbose_name='复筛文献集')
    version = models.PositiveBigIntegerField(verbose_name='版本号', default=0)
    model_ids = models.JSONField(verbose_name='模型列表', default=list)
    custom_prompt = models.TextField(verbose_name='补充提示词', blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='修改人')
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_settings'
        verbose_name = '复筛设置'
        verbose_name_plural = verbose_name


class RescreenFulltextBinding(models.Model):
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='bindings', verbose_name='复筛文献')
    asset = models.ForeignKey('core.FulltextAsset', on_delete=models.RESTRICT, related_name='rescreen_bindings', verbose_name='共享全文资产')
    input_version = models.PositiveBigIntegerField(verbose_name='输入版本')
    source = models.CharField(verbose_name='来源', max_length=50, default='manual', choices=[('manual', '手工绑定'), ('pdf_upload', '上传全文'), ('local', '本地匹配'), ('manual_link', '手工外链'), ('europe_pmc', 'Europe PMC 开放来源'), ('unpaywall', 'Unpaywall 开放来源')])
    provenance = models.JSONField(verbose_name='来源追溯信息', default=dict, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='确认人')
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_fulltext_binding'
        verbose_name = '复筛全文绑定'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['reference', 'input_version'], name='rs_binding_version_unique')]


class RescreenRun(models.Model):
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='runs', verbose_name='复筛文献集')
    input_revision = models.PositiveBigIntegerField(verbose_name='输入修订号')
    criteria_revision = models.ForeignKey(RescreenCriteriaRevision, on_delete=models.RESTRICT, verbose_name='排除标准修订')
    task = models.OneToOneField('core.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='rescreen_run', verbose_name='关联任务')
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('running', '进行中'), ('cancelling', '正在停止'), ('paused', '已暂停'), ('completed', '已完成'), ('partial', '部分完成'), ('failed', '失败'), ('settlement_pending', '等待积分结算')])
    model_ids = models.JSONField(verbose_name='模型列表', default=list)
    config_snapshot = models.JSONField(verbose_name='运行配置快照', default=dict)
    pricing_version = models.CharField(verbose_name='计费版本', max_length=100, blank=True)
    prompt_version = models.CharField(verbose_name='提示词版本', max_length=100, blank=True)
    total_count = models.PositiveBigIntegerField(verbose_name='文献总数', default=0)
    processed_count = models.PositiveBigIntegerField(verbose_name='已处理文献数', default=0)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    idempotency_key = models.CharField(verbose_name='幂等键', max_length=128, default=uuid4)
    request_hash = models.CharField(verbose_name='请求摘要', max_length=64, default='')
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    finished_at = models.DateTimeField(verbose_name='结束时间', null=True, blank=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_run'
        verbose_name = 'AI 复筛运行'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['corpus', 'idempotency_key'], name='rs_run_idempotency_unique')]


class RescreenRunItem(models.Model):
    run = models.ForeignKey(RescreenRun, on_delete=models.CASCADE, related_name='items', verbose_name='复筛运行')
    reference = models.ForeignKey(RescreenReference, on_delete=models.RESTRICT, related_name='run_items', verbose_name='复筛文献')
    raw_metadata_version = models.ForeignKey(RescreenReferenceRawMetadata, on_delete=models.RESTRICT, verbose_name='原始元数据版本')
    asset = models.ForeignKey('core.FulltextAsset', null=True, blank=True, on_delete=models.RESTRICT, verbose_name='共享全文资产')
    input_version = models.PositiveBigIntegerField(verbose_name='输入版本')
    bibliography_snapshot = models.JSONField(verbose_name='书目快照', default=dict)
    asset_sha256 = models.CharField(verbose_name='全文 SHA-256', max_length=64, blank=True)
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('running', '进行中'), ('completed', '已完成'), ('partial', '部分完成'), ('failed', '失败')])
    consensus = models.CharField(verbose_name='综合判断', max_length=20, blank=True, choices=[('included', '纳入'), ('excluded', '排除'), ('pending', '待定'), ('conflict', '模型意见不一致')])
    evidence_package = models.JSONField(verbose_name='证据包', default=dict)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    result_revision = models.PositiveBigIntegerField(verbose_name='结果修订号', default=0)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_run_item'
        verbose_name = 'AI 复筛运行条目'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['run', 'reference'], name='rs_run_reference_unique')]
        indexes = [models.Index(fields=['run', 'status', 'id'], name='rs_run_item_status_idx')]


class RescreenModelResult(models.Model):
    item = models.ForeignKey(RescreenRunItem, on_delete=models.CASCADE, related_name='model_results', verbose_name='所属条目')
    model_id = models.CharField(verbose_name='模型标识', max_length=100)
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('running', '进行中'), ('completed', '已完成'), ('failed', '失败')])
    decision = models.CharField(verbose_name='判断结果', max_length=20, blank=True, choices=[('included', '纳入'), ('excluded', '排除'), ('pending', '待定')])
    reason = models.TextField(verbose_name='判断理由', blank=True)
    evidence = models.JSONField(verbose_name='证据', default=list)
    criteria_results = models.JSONField(verbose_name='逐项标准判断', default=list)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    error_message = models.CharField(verbose_name='错误说明', max_length=500, blank=True)
    usage = models.JSONField(verbose_name='调用用量', default=dict)
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_model_result'
        verbose_name = 'AI 复筛单模型结果'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['item', 'model_id'], name='rs_item_model_unique')]


class RescreenCall(models.Model):
    """Durable request journal. An interrupted in-flight call is never silently retried."""
    result = models.ForeignKey(RescreenModelResult, on_delete=models.CASCADE, related_name='calls', verbose_name='单模型结果')
    task = models.ForeignKey('core.Task', null=True, on_delete=models.SET_NULL, related_name='rescreen_calls', verbose_name='关联任务')
    attempt = models.PositiveIntegerField(verbose_name='调用序号')
    status = models.CharField(verbose_name='状态', max_length=20, default='calling', choices=[('calling', '调用中'), ('received', '已收到响应'), ('completed', '已完成'), ('invalid', '响应校验失败'), ('unknown', '调用结果未知'), ('acknowledged_unknown', '已确认未知结果')])
    prompt_sha256 = models.CharField(verbose_name='提示词 SHA-256', max_length=64)
    criterion_ids = models.JSONField(verbose_name='标准标识列表', default=list)
    parsed_result = models.JSONField(verbose_name='解析结果', default=dict)
    usage = models.JSONField(verbose_name='调用用量', default=dict)
    response = models.TextField(verbose_name='模型原始响应', blank=True)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    finished_at = models.DateTimeField(verbose_name='结束时间', null=True, blank=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_call'
        verbose_name = 'AI 复筛调用记录'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['result', 'attempt'], name='rs_call_attempt_unique')]


class RescreenReview(models.Model):
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='reviews', verbose_name='复筛文献')
    input_version = models.PositiveBigIntegerField(verbose_name='输入版本')
    run_item = models.ForeignKey(RescreenRunItem, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='关联运行条目')
    decision = models.CharField(verbose_name='判断结果', max_length=20, choices=[('included', '纳入'), ('excluded', '排除'), ('pending', '待定'), ('not_retrieved', '全文未获取')])
    exclusion_reason = models.TextField(verbose_name='排除理由', blank=True)
    note = models.TextField(verbose_name='备注', blank=True)
    version = models.PositiveBigIntegerField(verbose_name='版本号', default=1)
    criteria_revision = models.ForeignKey(RescreenCriteriaRevision, null=True, on_delete=models.RESTRICT, related_name='+', verbose_name='排除标准修订')
    suggestion_revision = models.PositiveBigIntegerField(verbose_name='AI 建议修订号', default=0)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='审核人')
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_review'
        verbose_name = '复筛人工审核'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['reference', 'input_version'], name='rs_review_input_unique')]


class RescreenReviewEvent(models.Model):
    review = models.ForeignKey(RescreenReview, on_delete=models.CASCADE, related_name='events', verbose_name='人工审核')
    version = models.PositiveBigIntegerField(verbose_name='版本号')
    payload = models.JSONField(verbose_name='记录快照', default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_review_event'
        verbose_name = '复筛审核历史'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['review', 'version'], name='rs_review_event_unique')]


class QASourceBibliographySnapshot(models.Model):
    qa_reference = models.OneToOneField('core.QAReference', on_delete=models.CASCADE, related_name='rescreen_source_snapshot', verbose_name='质量评价文献')
    bibliography = models.JSONField(verbose_name='完整书目信息', default=dict)
    raw_metadata = models.JSONField(verbose_name='原始元数据快照', default=dict)
    provenance = models.JSONField(verbose_name='来源追溯信息', default=dict)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_qa_source_bibliography'
        verbose_name = '质量评价来源书目快照'
        verbose_name_plural = verbose_name


class RescreenExport(models.Model):
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='rescreen_exports', verbose_name='所属项目')
    task = models.OneToOneField('core.Task', null=True, on_delete=models.SET_NULL, related_name='rescreen_export', verbose_name='关联任务')
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('running', '进行中'), ('cancelling', '正在停止'), ('cancelled', '已停止'), ('completed', '已完成'), ('failed', '失败')])
    format = models.CharField(verbose_name='导出格式', max_length=20, choices=[('xlsx', 'Excel 表格'), ('xml', '结构化 XML'), ('ris', 'EndNote / RIS'), ('metadata', '原始元数据 JSONL'), ('pdf', '全文 PDF 压缩包'), ('skip', '明确跳过导出')])
    scope = models.CharField(verbose_name='导出范围', max_length=20, default='all', choices=[('all', '所有文献'), ('included', '纳入'), ('excluded', '排除'), ('not_retrieved', '全文未获取'), ('pending', '待定 / 未审阅草稿')])
    mode = models.CharField(verbose_name='处理模式', max_length=20, default='draft', choices=[('draft', '草稿'), ('final', '最终结果')])
    idempotency_key = models.CharField(verbose_name='幂等键', max_length=128)
    request_hash = models.CharField(verbose_name='请求摘要', max_length=64)
    fingerprint = models.CharField(verbose_name='输入状态指纹', max_length=64)
    source_revision = models.PositiveBigIntegerField(verbose_name='来源修订号')
    configuration_snapshot = models.JSONField(verbose_name='配置快照', default=dict)
    total_count = models.PositiveBigIntegerField(verbose_name='文献总数', default=0)
    processed_count = models.PositiveBigIntegerField(verbose_name='已处理文献数', default=0)
    output = models.FileField(verbose_name='导出文件', storage=PrivateRescreenExportStorage(), upload_to=rescreen_export_path, max_length=500, blank=True)
    output_size = models.PositiveBigIntegerField(verbose_name='导出文件大小（字节）', default=0)
    snapshot_size = models.PositiveBigIntegerField(verbose_name='快照大小（字节）', default=0)
    download_name = models.CharField(verbose_name='下载文件名', max_length=150, blank=True)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    finished_at = models.DateTimeField(verbose_name='结束时间', null=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_export'
        verbose_name = '复筛导出任务'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['project', 'idempotency_key'], name='rs_export_key_unique')]


class RescreenExportItem(models.Model):
    export = models.ForeignKey(RescreenExport, on_delete=models.CASCADE, related_name='items', verbose_name='导出任务')
    reference_id_snapshot = models.PositiveBigIntegerField(verbose_name='文献编号快照')
    payload = models.JSONField(verbose_name='记录快照', default=dict)
    asset = models.ForeignKey('core.FulltextAsset', null=True, on_delete=models.RESTRICT, related_name='rescreen_export_items', verbose_name='共享全文资产')

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_export_item'
        verbose_name = '复筛导出条目'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['export', 'reference_id_snapshot'], name='rs_export_ref_unique')]


class FulltextLookupJob(models.Model):
    ACTIVE_STATUSES = ('pending', 'running', 'cancelling')
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='fulltext_lookup_jobs', verbose_name='所属项目')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    task = models.OneToOneField('core.Task', null=True, on_delete=models.SET_NULL, related_name='fulltext_lookup_job', verbose_name='关联任务')
    mode = models.CharField(verbose_name='处理模式', max_length=20, choices=[('local', '本地'), ('online', '开放来源'), ('download', '下载候选'), ('manual', '手工外链')])
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('running', '进行中'), ('cancelling', '正在停止'), ('cancelled', '已停止'), ('completed', '已完成'), ('failed', '失败')])
    idempotency_key = models.CharField(verbose_name='幂等键', max_length=128)
    request_hash = models.CharField(verbose_name='请求摘要', max_length=64)
    input_revision = models.PositiveBigIntegerField(verbose_name='输入修订号')
    settings_snapshot = models.JSONField(verbose_name='查找配置快照', default=dict)
    processed_count = models.PositiveIntegerField(verbose_name='已处理文献数', default=0)
    received_bytes = models.PositiveBigIntegerField(verbose_name='已接收大小（字节）', default=0)
    request_count = models.PositiveIntegerField(verbose_name='请求次数', default=0)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)
    finished_at = models.DateTimeField(verbose_name='结束时间', null=True, blank=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_lookup_job'
        verbose_name = '全文查找任务'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['project', 'idempotency_key'], name='ft_lookup_idempotency_unique')]
        indexes = [models.Index(fields=['project', 'status'], name='ft_lookup_project_status_idx')]


class FulltextLookupItem(models.Model):
    job = models.ForeignKey(FulltextLookupJob, on_delete=models.CASCADE, related_name='items', verbose_name='全文查找任务')
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='fulltext_lookup_items', verbose_name='复筛文献')
    input_version = models.PositiveBigIntegerField(verbose_name='输入版本')
    bibliography_snapshot = models.JSONField(verbose_name='书目快照', default=dict)
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('processing', '处理中'), ('bound', '已绑定'), ('found', '已找到候选'), ('not_found', '未找到全文'), ('failed', '失败'), ('cancelled', '已停止')])
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    resolver_notes = models.JSONField(verbose_name='来源解析说明', default=dict)
    selected_candidate = models.ForeignKey('core.FulltextCandidate', null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='选定候选全文')

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_lookup_item'
        verbose_name = '全文查找条目'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['job', 'reference'], name='ft_lookup_item_unique')]
        indexes = [models.Index(fields=['job', 'status', 'id'], name='ft_lookup_item_status_idx')]


class FulltextCandidate(models.Model):
    item = models.ForeignKey(FulltextLookupItem, on_delete=models.CASCADE, related_name='candidates', verbose_name='所属条目')
    asset = models.ForeignKey('core.FulltextAsset', null=True, on_delete=models.SET_NULL, related_name='lookup_candidates', verbose_name='共享全文资产')
    source = models.CharField(verbose_name='来源', max_length=30, choices=[('local', '本地匹配'), ('manual_link', '手工外链'), ('europe_pmc', 'Europe PMC 开放来源'), ('unpaywall', 'Unpaywall 开放来源')])
    url = models.URLField(verbose_name='链接地址', max_length=2000, blank=True)
    license = models.CharField(verbose_name='许可证', max_length=100, blank=True)
    title = models.TextField(verbose_name='文献标题', blank=True)
    doi = models.CharField(verbose_name='DOI', max_length=255, blank=True)
    pmid = models.CharField(verbose_name='PMID', max_length=64, blank=True)
    confidence = models.CharField(verbose_name='匹配依据', max_length=20, default='candidate', choices=[('candidate', '候选匹配'), ('identifier', '标识符匹配'), ('title', '标题匹配')])
    status = models.CharField(verbose_name='状态', max_length=20, default='offered', choices=[('offered', '待确认'), ('downloaded', '已下载'), ('bound', '已绑定'), ('failed', '失败')])
    provenance = models.JSONField(verbose_name='来源追溯信息', default=dict)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_candidate'
        verbose_name = '候选全文'
        verbose_name_plural = verbose_name
