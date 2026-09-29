"""Database models for the screening corpus and its versioned processing runs."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.screening.storage import PrivateScreeningStorage, screening_import_upload_path


class ScreeningCorpus(models.Model):
    """Current published revision and aggregate counters for one project."""

    project = models.OneToOneField(
        'core.Project', on_delete=models.CASCADE, related_name='screening_corpus',
        verbose_name='所属项目',
    )
    revision = models.PositiveBigIntegerField(default=0, verbose_name='当前修订号')
    active_reference_count = models.PositiveBigIntegerField(default=0, verbose_name='有效文献数')
    active_source_file_count = models.PositiveIntegerField(default=0, verbose_name='有效来源文件数')
    last_import_batch = models.ForeignKey(
        'core.ReferenceImportBatch', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='最近导入批次',
    )
    last_dedup_run = models.ForeignKey(
        'core.DedupRun', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='最近去重运行',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_screening_corpus'
        verbose_name = '初筛文献集'
        verbose_name_plural = '初筛文献集'

    def __str__(self):
        return f'{self.project} (revision {self.revision})'

    def save(self, *args, **kwargs):
        if self.pk:
            stored_revision = type(self).objects.filter(pk=self.pk).values_list('revision', flat=True).first()
            if stored_revision is not None and self.revision < stored_revision:
                raise ValidationError({'revision': '文献集修订号不能回退。'})
        return super().save(*args, **kwargs)

    def publish_revision(
        self,
        *,
        expected_revision: int,
        target_revision: int,
        active_reference_count: int,
        active_source_file_count: int,
        last_import_batch=None,
    ) -> None:
        """Atomically publish a strictly newer revision using optimistic locking."""
        if target_revision != expected_revision + 1:
            raise ValidationError('目标修订号必须是当前修订号的下一版。')
        updates = {
            'revision': target_revision,
            'active_reference_count': active_reference_count,
            'active_source_file_count': active_source_file_count,
            'updated_at': timezone.now(),
        }
        if last_import_batch is not None:
            updates['last_import_batch'] = last_import_batch
        changed = type(self).objects.filter(
            pk=self.pk, revision=expected_revision,
        ).update(**updates)
        if changed != 1:
            raise ValidationError('文献集修订号已变化，请重新发起操作。')
        self.refresh_from_db()


class ReferenceImportBatch(models.Model):
    class Operation(models.TextChoices):
        ADD = 'add', '新增'
        REMOVE = 'remove', '删除'
        REBUILD = 'rebuild', '重建'

    class Status(models.TextChoices):
        UPLOADED = 'uploaded', '已上传'
        VALIDATING = 'validating', '校验中'
        IMPORTING = 'importing', '导入中'
        READY = 'ready', '待发布'
        PUBLISHING = 'publishing', '发布中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'
        CANCELLED = 'cancelled', '已取消'

    project = models.ForeignKey(
        'core.Project', on_delete=models.CASCADE, related_name='reference_import_batches',
        verbose_name='所属项目',
    )
    corpus = models.ForeignKey(
        ScreeningCorpus, on_delete=models.CASCADE, related_name='import_batches',
        verbose_name='所属文献集',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reference_import_batches', verbose_name='创建者',
    )
    task = models.ForeignKey(
        'core.Task', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reference_import_batches', verbose_name='后台任务',
    )
    operation = models.CharField(max_length=20, choices=Operation.choices, verbose_name='操作')
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED, verbose_name='状态',
    )
    base_revision = models.PositiveBigIntegerField(verbose_name='基准修订号')
    target_revision = models.PositiveBigIntegerField(verbose_name='目标修订号')
    published_revision = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='已发布修订号')
    file_count = models.PositiveIntegerField(default=0, verbose_name='文件数')
    total_bytes = models.PositiveBigIntegerField(default=0, verbose_name='总字节数')
    discovered_count = models.PositiveBigIntegerField(default=0, verbose_name='检测条数')
    accepted_count = models.PositiveBigIntegerField(default=0, verbose_name='接收条数')
    rejected_count = models.PositiveBigIntegerField(default=0, verbose_name='拒绝条数')
    missing_abstract_count = models.PositiveBigIntegerField(default=0, verbose_name='缺摘要条数')
    warning_count = models.PositiveBigIntegerField(default=0, verbose_name='警告数')
    error_count = models.PositiveBigIntegerField(default=0, verbose_name='错误数')
    config_snapshot = models.JSONField(default=dict, blank=True, verbose_name='配置快照')
    parser_version = models.CharField(max_length=50, blank=True, default='', verbose_name='解析器版本')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='发布时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_reference_import_batch'
        verbose_name = '文献导入批次'
        verbose_name_plural = '文献导入批次'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['corpus', 'status'], name='sc_imp_corpus_status_idx'),
            models.Index(fields=['project', 'created_at'], name='sc_imp_project_time_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(target_revision=F('base_revision') + 1),
                name='sc_imp_target_next_rev',
            ),
            models.CheckConstraint(
                condition=Q(published_revision__isnull=True) | Q(published_revision=F('target_revision')),
                name='sc_imp_published_target',
            ),
        ]

    def __str__(self):
        return f'{self.project} {self.operation} r{self.base_revision}→{self.target_revision}'

    def clean(self):
        super().clean()
        if self.corpus_id and self.project_id:
            corpus_project_id = ScreeningCorpus.objects.filter(pk=self.corpus_id).values_list(
                'project_id', flat=True,
            ).first()
            if corpus_project_id is not None and corpus_project_id != self.project_id:
                raise ValidationError({'corpus': '文献集与导入批次必须属于同一项目。'})


class ReferenceImportFile(models.Model):
    class ParseStatus(models.TextChoices):
        PENDING = 'pending', '待处理'
        VALIDATING = 'validating', '校验中'
        PARSING = 'parsing', '解析中'
        PARSED = 'parsed', '解析完成'
        WARNING = 'warning', '存在警告'
        FAILED = 'failed', '失败'

    import_batch = models.ForeignKey(
        ReferenceImportBatch, on_delete=models.CASCADE, related_name='files',
        verbose_name='导入批次',
    )
    source_file = models.OneToOneField(
        'core.DataFile', on_delete=models.RESTRICT, related_name='reference_import_file',
        verbose_name='原始文件',
    )
    raw_file = models.FileField(
        storage=PrivateScreeningStorage(), upload_to=screening_import_upload_path,
        max_length=500, verbose_name='私有原始文件',
    )
    original_filename = models.CharField(max_length=255, verbose_name='原始文件名')
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name='SHA-256')
    source_format = models.CharField(max_length=32, verbose_name='来源格式')
    parse_status = models.CharField(
        max_length=20, choices=ParseStatus.choices, default=ParseStatus.PENDING,
        verbose_name='解析状态',
    )
    introduced_revision = models.PositiveBigIntegerField(verbose_name='引入修订号')
    removed_revision = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='移除修订号')
    removed_by_batch = models.ForeignKey(
        ReferenceImportBatch, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='removed_files', verbose_name='移除批次',
    )
    detected_count = models.PositiveBigIntegerField(default=0, verbose_name='检测条数')
    parsed_count = models.PositiveBigIntegerField(default=0, verbose_name='解析条数')
    skipped_count = models.PositiveBigIntegerField(default=0, verbose_name='跳过条数')
    missing_abstract_count = models.PositiveBigIntegerField(default=0, verbose_name='缺摘要条数')
    warning_count = models.PositiveBigIntegerField(default=0, verbose_name='警告数')
    error_count = models.PositiveBigIntegerField(default=0, verbose_name='错误数')
    issues_truncated = models.BooleanField(default=False, verbose_name='问题明细已截断')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_reference_import_file'
        verbose_name = '文献导入文件'
        verbose_name_plural = '文献导入文件'
        ordering = ['import_batch_id', 'id']
        indexes = [
            models.Index(fields=['import_batch', 'parse_status'], name='sc_file_batch_status_idx'),
            models.Index(fields=['removed_revision'], name='sc_file_removed_rev_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(removed_revision__isnull=True) | Q(removed_revision__gt=F('introduced_revision')),
                name='sc_file_removed_gt_intro',
            ),
        ]

    def __str__(self):
        return self.original_filename


class ReferenceImportIssue(models.Model):
    class Severity(models.TextChoices):
        WARNING = 'warning', '警告'
        ERROR = 'error', '错误'

    import_file = models.ForeignKey(
        ReferenceImportFile, on_delete=models.CASCADE, related_name='issues',
        verbose_name='导入文件',
    )
    severity = models.CharField(max_length=10, choices=Severity.choices, verbose_name='级别')
    code = models.CharField(max_length=64, verbose_name='问题代码')
    record_position = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='记录位置')
    line_number = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='行号')
    source_identifier = models.CharField(max_length=255, blank=True, default='', verbose_name='来源标识')
    title_preview = models.CharField(max_length=500, blank=True, default='', verbose_name='标题预览')
    message = models.TextField(verbose_name='问题说明')
    suggestion = models.TextField(blank=True, default='', verbose_name='处理建议')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_reference_import_issue'
        verbose_name = '文献导入问题'
        verbose_name_plural = '文献导入问题'
        ordering = ['import_file_id', 'record_position', 'id']
        indexes = [
            models.Index(fields=['import_file', 'severity'], name='sc_issue_file_level_idx'),
            models.Index(fields=['import_file', 'record_position'], name='sc_issue_file_pos_idx'),
        ]

    def __str__(self):
        return f'{self.import_file}: {self.code}'


class ScreeningReferenceQuerySet(models.QuerySet):
    def active_at(self, revision: int):
        return self.filter(introduced_revision__lte=revision).filter(
            Q(removed_revision__isnull=True) | Q(removed_revision__gt=revision)
        )

    def current(self):
        return self.filter(introduced_revision__lte=F('corpus__revision')).filter(
            Q(removed_revision__isnull=True) | Q(removed_revision__gt=F('corpus__revision'))
        )


class ScreeningReference(models.Model):
    project = models.ForeignKey(
        'core.Project', on_delete=models.CASCADE, related_name='screening_references',
        verbose_name='所属项目',
    )
    corpus = models.ForeignKey(
        ScreeningCorpus, on_delete=models.CASCADE, related_name='references',
        verbose_name='所属文献集',
    )
    import_batch = models.ForeignKey(
        ReferenceImportBatch, on_delete=models.RESTRICT, related_name='references',
        verbose_name='导入批次',
    )
    import_file = models.ForeignKey(
        ReferenceImportFile, on_delete=models.RESTRICT, related_name='references',
        verbose_name='导入文件',
    )
    source_file = models.ForeignKey(
        'core.DataFile', on_delete=models.RESTRICT, related_name='screening_references',
        verbose_name='来源文件',
    )
    source_record_index = models.PositiveBigIntegerField(verbose_name='来源记录序号')
    source_record_key = models.CharField(max_length=255, blank=True, default='', verbose_name='来源记录键')
    source_identifier = models.CharField(max_length=255, blank=True, default='', verbose_name='来源标识')
    introduced_revision = models.PositiveBigIntegerField(verbose_name='引入修订号')
    removed_revision = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='移除修订号')

    title = models.TextField(verbose_name='标题')
    abstract = models.TextField(blank=True, default='', verbose_name='摘要')
    authors = models.JSONField(default=list, blank=True, verbose_name='作者')
    journal = models.CharField(max_length=500, blank=True, default='', verbose_name='期刊')
    publication_year = models.CharField(max_length=20, blank=True, default='', verbose_name='发表年份')
    publication_date = models.CharField(max_length=50, blank=True, default='', verbose_name='发表日期')
    doi = models.CharField(max_length=255, blank=True, default='', verbose_name='DOI')
    normalized_doi = models.CharField(max_length=255, blank=True, default='', verbose_name='规范化 DOI')
    pmid = models.CharField(max_length=64, blank=True, default='', verbose_name='PMID')
    pmcid = models.CharField(max_length=64, blank=True, default='', verbose_name='PMCID')
    isbn = models.CharField(max_length=64, blank=True, default='', verbose_name='ISBN')
    url = models.TextField(blank=True, default='', verbose_name='URL')
    publication_type = models.CharField(max_length=100, blank=True, default='', verbose_name='文献类型')
    volume = models.CharField(max_length=100, blank=True, default='', verbose_name='卷')
    issue = models.CharField(max_length=100, blank=True, default='', verbose_name='期')
    pages = models.CharField(max_length=100, blank=True, default='', verbose_name='页码')
    keywords = models.JSONField(default=list, blank=True, verbose_name='关键词')
    language = models.CharField(max_length=50, blank=True, default='', verbose_name='语言')
    address = models.TextField(blank=True, default='', verbose_name='地址')
    normalized_title_hash = models.CharField(max_length=64, verbose_name='规范化标题哈希')
    record_hash = models.CharField(max_length=64, verbose_name='记录哈希')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    objects = ScreeningReferenceQuerySet.as_manager()

    class Meta:
        app_label = 'core'
        db_table = 'plat_screening_reference'
        verbose_name = '标准化文献'
        verbose_name_plural = '标准化文献'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['import_file', 'source_record_index'], name='sc_ref_unique_source_pos',
            ),
            models.CheckConstraint(
                condition=Q(removed_revision__isnull=True) | Q(removed_revision__gt=F('introduced_revision')),
                name='sc_ref_removed_gt_intro',
            ),
        ]
        indexes = [
            models.Index(
                fields=['project', 'introduced_revision', 'removed_revision'],
                name='sc_ref_project_rev_idx',
            ),
            models.Index(fields=['corpus', 'source_file', 'removed_revision'], name='sc_ref_corpus_file_idx'),
            models.Index(fields=['project', 'normalized_title_hash'], name='sc_ref_title_hash_idx'),
            models.Index(fields=['project', 'normalized_doi'], name='sc_ref_doi_idx'),
        ]

    def __str__(self):
        return self.title[:100]


class ScreeningReferenceRawMetadata(models.Model):
    """Cold, lossless source metadata kept outside the hot reference row."""

    reference = models.OneToOneField(
        ScreeningReference, on_delete=models.CASCADE, related_name='raw_metadata_record',
        verbose_name='标准化文献',
    )
    import_file = models.ForeignKey(
        ReferenceImportFile, on_delete=models.CASCADE, related_name='raw_metadata_records',
        verbose_name='导入文件',
    )
    source_format = models.CharField(max_length=32, verbose_name='来源格式')
    raw_fields = models.JSONField(default=dict, blank=True, verbose_name='完整原始字段')
    raw_size_bytes = models.PositiveBigIntegerField(default=0, verbose_name='原始字段字节数')
    raw_hash = models.CharField(max_length=64, verbose_name='原始字段哈希')
    parser_version = models.CharField(max_length=50, blank=True, default='', verbose_name='解析器版本')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_screening_reference_raw'
        verbose_name = '文献原始元数据'
        verbose_name_plural = '文献原始元数据'
        ordering = ['reference_id']
        indexes = [
            models.Index(fields=['import_file', 'source_format'], name='sc_raw_file_format_idx'),
        ]

    def __str__(self):
        return f'{self.reference_id}: {self.source_format}'


class DedupRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待处理'
        RUNNING = 'running', '运行中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'
        CANCELLED = 'cancelled', '已取消'

    project = models.ForeignKey(
        'core.Project', on_delete=models.CASCADE, related_name='dedup_runs', verbose_name='所属项目',
    )
    corpus = models.ForeignKey(
        ScreeningCorpus, on_delete=models.CASCADE, related_name='dedup_runs', verbose_name='所属文献集',
    )
    corpus_revision = models.PositiveBigIntegerField(verbose_name='文献集修订号')
    task = models.ForeignKey(
        'core.Task', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='dedup_runs', verbose_name='后台任务',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='dedup_runs', verbose_name='创建者',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name='状态')
    rule_version = models.CharField(max_length=50, verbose_name='规则版本')
    rule_snapshot = models.JSONField(default=dict, blank=True, verbose_name='规则快照')
    total_count = models.PositiveBigIntegerField(default=0, verbose_name='总文献数')
    kept_count = models.PositiveBigIntegerField(default=0, verbose_name='保留数')
    duplicate_count = models.PositiveBigIntegerField(default=0, verbose_name='重复数')
    group_count = models.PositiveBigIntegerField(default=0, verbose_name='重复组数')
    failed_count = models.PositiveBigIntegerField(default=0, verbose_name='失败数')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_dedup_run'
        verbose_name = '去重运行'
        verbose_name_plural = '去重运行'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['corpus', 'corpus_revision', 'status'], name='sc_dedup_corpus_rev_idx'),
        ]

    def __str__(self):
        return f'{self.project} r{self.corpus_revision} #{self.pk}'


class ReferenceDuplicateGroup(models.Model):
    dedup_run = models.ForeignKey(
        DedupRun, on_delete=models.CASCADE, related_name='groups', verbose_name='去重运行',
    )
    sequence = models.PositiveBigIntegerField(verbose_name='稳定序号')
    representative_reference = models.ForeignKey(
        ScreeningReference, on_delete=models.RESTRICT, related_name='represented_duplicate_groups',
        verbose_name='代表文献',
    )
    match_type = models.CharField(max_length=50, verbose_name='匹配类型')
    match_key_hash = models.CharField(max_length=64, verbose_name='匹配键哈希')
    display_title = models.TextField(blank=True, default='', verbose_name='展示标题')
    member_count = models.PositiveIntegerField(default=0, verbose_name='成员数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_reference_duplicate_group'
        verbose_name = '重复文献组'
        verbose_name_plural = '重复文献组'
        ordering = ['dedup_run_id', 'sequence']
        constraints = [
            models.UniqueConstraint(fields=['dedup_run', 'sequence'], name='sc_dup_group_run_sequence'),
        ]
        indexes = [
            models.Index(fields=['dedup_run', 'sequence'], name='sc_dup_group_run_seq_idx'),
        ]

    def __str__(self):
        return f'#{self.sequence} {self.display_title[:80]}'


class ReferenceDuplicateMember(models.Model):
    class Role(models.TextChoices):
        KEPT = 'kept', '保留'
        DUPLICATE = 'duplicate', '重复'

    dedup_run = models.ForeignKey(
        DedupRun, on_delete=models.CASCADE, related_name='members', verbose_name='去重运行',
    )
    group = models.ForeignKey(
        ReferenceDuplicateGroup, on_delete=models.CASCADE, related_name='members',
        verbose_name='重复组',
    )
    reference = models.ForeignKey(
        ScreeningReference, on_delete=models.RESTRICT, related_name='duplicate_memberships',
        verbose_name='文献',
    )
    role = models.CharField(max_length=20, choices=Role.choices, verbose_name='组内角色')
    match_reason = models.CharField(max_length=255, blank=True, default='', verbose_name='匹配原因')
    match_score = models.DecimalField(
        max_digits=7, decimal_places=6, null=True, blank=True, verbose_name='匹配分数',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_reference_duplicate_member'
        verbose_name = '重复文献成员'
        verbose_name_plural = '重复文献成员'
        constraints = [
            models.UniqueConstraint(fields=['dedup_run', 'reference'], name='sc_dup_member_run_ref'),
            models.UniqueConstraint(fields=['group', 'reference'], name='sc_dup_member_group_ref'),
        ]
        indexes = [
            models.Index(fields=['group', 'role'], name='sc_dup_member_group_role_idx'),
        ]

    def __str__(self):
        return f'{self.group_id}: {self.reference_id} ({self.role})'

    def clean(self):
        super().clean()
        if self.group_id and self.dedup_run_id:
            group_run_id = ReferenceDuplicateGroup.objects.filter(pk=self.group_id).values_list(
                'dedup_run_id', flat=True,
            ).first()
            if group_run_id is not None and group_run_id != self.dedup_run_id:
                raise ValidationError({'group': '重复组与成员必须属于同一次去重运行。'})


class ScreeningRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待处理'
        RUNNING = 'running', '运行中'
        STOPPING = 'stopping', '停止中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'
        CANCELLED = 'cancelled', '已取消'

    project = models.ForeignKey(
        'core.Project', on_delete=models.CASCADE, related_name='screening_runs', verbose_name='所属项目',
    )
    corpus = models.ForeignKey(
        ScreeningCorpus, on_delete=models.CASCADE, related_name='screening_runs', verbose_name='所属文献集',
    )
    corpus_revision = models.PositiveBigIntegerField(verbose_name='文献集修订号')
    dedup_run = models.ForeignKey(
        DedupRun, null=True, blank=True, on_delete=models.RESTRICT,
        related_name='screening_runs', verbose_name='去重运行',
    )
    task = models.ForeignKey(
        'core.Task', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='screening_runs', verbose_name='后台任务',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='screening_runs', verbose_name='创建者',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name='状态')
    criteria_snapshot = models.JSONField(default=dict, blank=True, verbose_name='纳排标准快照')
    model_config_snapshot = models.JSONField(default=dict, blank=True, verbose_name='模型配置快照')
    prompt_version = models.CharField(max_length=100, blank=True, default='', verbose_name='提示词版本')
    total_count = models.PositiveBigIntegerField(default=0, verbose_name='总文献数')
    processed_count = models.PositiveBigIntegerField(default=0, verbose_name='已处理数')
    included_count = models.PositiveBigIntegerField(default=0, verbose_name='纳入数')
    excluded_count = models.PositiveBigIntegerField(default=0, verbose_name='排除数')
    uncertain_count = models.PositiveBigIntegerField(default=0, verbose_name='待定数')
    failed_count = models.PositiveBigIntegerField(default=0, verbose_name='失败数')
    input_tokens = models.PositiveBigIntegerField(default=0, verbose_name='输入 Token')
    output_tokens = models.PositiveBigIntegerField(default=0, verbose_name='输出 Token')
    points_consumed = models.DecimalField(max_digits=14, decimal_places=4, default=0, verbose_name='消耗积分')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_screening_run'
        verbose_name = 'AI 初筛运行'
        verbose_name_plural = 'AI 初筛运行'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['corpus', 'corpus_revision', 'status'], name='sc_run_corpus_rev_idx'),
            models.Index(fields=['project', 'created_at'], name='sc_run_project_time_idx'),
        ]

    def __str__(self):
        return f'{self.project} r{self.corpus_revision} #{self.pk}'


class ScreeningResult(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待处理'
        PROCESSING = 'processing', '处理中'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '失败'
        SKIPPED = 'skipped', '已跳过'

    class Decision(models.TextChoices):
        INCLUDED = 'included', '纳入'
        EXCLUDED = 'excluded', '排除'
        UNCERTAIN = 'uncertain', '待定'

    screening_run = models.ForeignKey(
        ScreeningRun, on_delete=models.CASCADE, related_name='results', verbose_name='初筛运行',
    )
    reference = models.ForeignKey(
        ScreeningReference, on_delete=models.RESTRICT, related_name='screening_results',
        verbose_name='文献',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name='状态')
    decision = models.CharField(max_length=20, choices=Decision.choices, blank=True, default='', verbose_name='决定')
    consensus = models.CharField(max_length=20, blank=True, default='', verbose_name='多模型共识')
    reason = models.TextField(blank=True, default='', verbose_name='判断理由')
    model_results = models.JSONField(default=list, blank=True, verbose_name='各模型结果')
    extracted_fields = models.JSONField(default=dict, blank=True, verbose_name='提取字段')
    token_usage = models.JSONField(default=dict, blank=True, verbose_name='Token 用量')
    points_consumed = models.DecimalField(max_digits=14, decimal_places=4, default=0, verbose_name='消耗积分')
    error_code = models.CharField(max_length=100, blank=True, default='', verbose_name='错误代码')
    error_message = models.TextField(blank=True, default='', verbose_name='错误信息')
    attempt_count = models.PositiveSmallIntegerField(default=0, verbose_name='尝试次数')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        app_label = 'core'
        db_table = 'plat_screening_result'
        verbose_name = 'AI 初筛结果'
        verbose_name_plural = 'AI 初筛结果'
        constraints = [
            models.UniqueConstraint(fields=['screening_run', 'reference'], name='sc_result_run_reference'),
        ]
        indexes = [
            models.Index(fields=['screening_run', 'status'], name='sc_result_run_status_idx'),
            models.Index(fields=['screening_run', 'decision'], name='sc_result_run_decision_idx'),
        ]

    def __str__(self):
        return f'{self.screening_run_id}: {self.reference_id} ({self.status})'
