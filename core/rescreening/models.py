"""Persistent inputs and immutable run/review boundaries for SCREEN_2."""
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .storage import PrivateRescreenStorage, rescreen_upload_path, PrivateRescreenExportStorage, rescreen_export_path


class RescreenCorpus(models.Model):
    project = models.OneToOneField('core.Project', on_delete=models.CASCADE, related_name='rescreen_corpus')
    revision = models.PositiveBigIntegerField(default=0)
    active_reference_count = models.PositiveBigIntegerField(default=0)
    current_run = models.ForeignKey('core.RescreenRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_corpus'
        verbose_name = '复筛文献集'
        verbose_name_plural = verbose_name


class RescreenImportBatch(models.Model):
    ACTIVE_STATUSES = ('uploaded', 'importing', 'cancelling', 'ready')
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='rescreen_imports')
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='imports')
    source_type = models.CharField(max_length=30, choices=[('screening', '初筛导入'), ('bibliography', '上传题录'), ('pdf', '上传全文')])
    status = models.CharField(max_length=20, default='uploaded', choices=[(v, v) for v in ('uploaded', 'importing', 'cancelling', 'ready', 'completed', 'failed', 'cancelled')])
    base_revision = models.PositiveBigIntegerField()
    target_revision = models.PositiveBigIntegerField()
    source_screening_run = models.ForeignKey('core.ScreeningRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    source_snapshot = models.JSONField(default=dict, blank=True)
    attempts = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    task = models.ForeignKey('core.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='rescreen_imports')
    limits_snapshot = models.JSONField(default=dict)
    accepted_count = models.PositiveBigIntegerField(default=0)
    rejected_count = models.PositiveBigIntegerField(default=0)
    skipped_count = models.PositiveBigIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_import_batch'
        verbose_name = '复筛导入批次'
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=['project', 'idempotency_key'], name='rs_import_idempotency_unique')]
        indexes = [models.Index(fields=['project', 'status'], name='rs_import_project_status_idx')]


class RescreenImportFile(models.Model):
    batch = models.ForeignKey(RescreenImportBatch, on_delete=models.CASCADE, related_name='files')
    raw_file = models.FileField(storage=PrivateRescreenStorage(), upload_to=rescreen_upload_path, max_length=500)
    original_filename = models.CharField(max_length=255)
    source_format = models.CharField(max_length=32)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    report = models.JSONField(default=dict, blank=True)

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
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='rescreen_references')
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='references')
    import_batch = models.ForeignKey(RescreenImportBatch, on_delete=models.RESTRICT, related_name='references')
    import_file = models.ForeignKey(RescreenImportFile, null=True, blank=True, on_delete=models.RESTRICT, related_name='references')
    source_key = models.CharField(max_length=160)
    source_record_index = models.PositiveBigIntegerField(default=1)
    source_identifier = models.CharField(max_length=255, blank=True, default='')
    source_reference = models.ForeignKey('core.ScreeningReference', null=True, blank=True, on_delete=models.SET_NULL, related_name='rescreen_references')
    source_screening_run = models.ForeignKey('core.ScreeningRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    source_snapshot = models.JSONField(default=dict, blank=True)
    introduced_revision = models.PositiveBigIntegerField()
    removed_revision = models.PositiveBigIntegerField(null=True, blank=True)
    input_version = models.PositiveBigIntegerField(default=1)
    title = models.TextField()
    abstract = models.TextField(blank=True, default='')
    authors = models.JSONField(default=list, blank=True)
    journal = models.CharField(max_length=500, blank=True, default='')
    publication_year = models.CharField(max_length=20, blank=True, default='')
    publication_date = models.CharField(max_length=50, blank=True, default='')
    doi = models.CharField(max_length=255, blank=True, default='')
    normalized_doi = models.CharField(max_length=255, blank=True, default='')
    pmid = models.CharField(max_length=64, blank=True, default='')
    pmcid = models.CharField(max_length=64, blank=True, default='')
    isbn = models.CharField(max_length=64, blank=True, default='')
    issn = models.CharField(max_length=64, blank=True, default='')
    url = models.TextField(blank=True, default='')
    publication_type = models.CharField(max_length=100, blank=True, default='')
    volume = models.CharField(max_length=100, blank=True, default='')
    issue = models.CharField(max_length=100, blank=True, default='')
    pages = models.CharField(max_length=100, blank=True, default='')
    keywords = models.JSONField(default=list, blank=True)
    language = models.CharField(max_length=50, blank=True, default='')
    publisher = models.CharField(max_length=500, blank=True, default='')
    database = models.CharField(max_length=255, blank=True, default='')
    organization = models.TextField(blank=True, default='')
    address = models.TextField(blank=True, default='')
    normalized_title_hash = models.CharField(max_length=64)
    record_hash = models.CharField(max_length=64)
    # Empty until the corresponding later phases expose these features.
    current_binding = models.ForeignKey('core.RescreenFulltextBinding', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    current_review = models.ForeignKey('core.RescreenReview', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
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
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='raw_metadata_versions')
    input_version = models.PositiveBigIntegerField(default=1)
    raw_fields = models.JSONField(default=dict)
    source_format = models.CharField(max_length=32)
    raw_size_bytes = models.PositiveBigIntegerField()
    raw_hash = models.CharField(max_length=64)
    parser_version = models.CharField(max_length=50, blank=True)
    source_extracted_fields = models.JSONField(default=dict, blank=True)
    source_field_definitions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='criteria_versions')
    revision = models.PositiveBigIntegerField()
    criteria = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_criteria_revision'
        constraints = [models.UniqueConstraint(fields=['corpus', 'revision'], name='rs_criteria_revision_unique')]


class RescreenSettings(models.Model):
    """Private prompt configuration is not part of publicly serialized Stage metadata."""
    corpus = models.OneToOneField(RescreenCorpus, on_delete=models.CASCADE, related_name='settings')
    version = models.PositiveBigIntegerField(default=0)
    model_ids = models.JSONField(default=list)
    custom_prompt = models.TextField(blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_settings'


class RescreenFulltextBinding(models.Model):
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='bindings')
    asset = models.ForeignKey('core.FulltextAsset', on_delete=models.RESTRICT, related_name='rescreen_bindings')
    input_version = models.PositiveBigIntegerField()
    source = models.CharField(max_length=50, default='manual')
    provenance = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_fulltext_binding'
        constraints = [models.UniqueConstraint(fields=['reference', 'input_version'], name='rs_binding_version_unique')]


class RescreenRun(models.Model):
    corpus = models.ForeignKey(RescreenCorpus, on_delete=models.CASCADE, related_name='runs')
    input_revision = models.PositiveBigIntegerField()
    criteria_revision = models.ForeignKey(RescreenCriteriaRevision, on_delete=models.RESTRICT)
    task = models.OneToOneField('core.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='rescreen_run')
    status = models.CharField(max_length=20, default='pending')
    model_ids = models.JSONField(default=list)
    config_snapshot = models.JSONField(default=dict)
    pricing_version = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=100, blank=True)
    total_count = models.PositiveBigIntegerField(default=0)
    processed_count = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    idempotency_key = models.CharField(max_length=128, default=uuid4)
    request_hash = models.CharField(max_length=64, default='')
    error_code = models.CharField(max_length=64, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_run'
        constraints = [models.UniqueConstraint(fields=['corpus', 'idempotency_key'], name='rs_run_idempotency_unique')]


class RescreenRunItem(models.Model):
    run = models.ForeignKey(RescreenRun, on_delete=models.CASCADE, related_name='items')
    reference = models.ForeignKey(RescreenReference, on_delete=models.RESTRICT, related_name='run_items')
    raw_metadata_version = models.ForeignKey(RescreenReferenceRawMetadata, on_delete=models.RESTRICT)
    asset = models.ForeignKey('core.FulltextAsset', null=True, blank=True, on_delete=models.RESTRICT)
    input_version = models.PositiveBigIntegerField()
    bibliography_snapshot = models.JSONField(default=dict)
    asset_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, default='pending')
    consensus = models.CharField(max_length=20, blank=True)
    evidence_package = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    result_revision = models.PositiveBigIntegerField(default=0)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_run_item'
        constraints = [models.UniqueConstraint(fields=['run', 'reference'], name='rs_run_reference_unique')]
        indexes = [models.Index(fields=['run', 'status', 'id'], name='rs_run_item_status_idx')]


class RescreenModelResult(models.Model):
    item = models.ForeignKey(RescreenRunItem, on_delete=models.CASCADE, related_name='model_results')
    model_id = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default='pending')
    decision = models.CharField(max_length=20, blank=True)
    reason = models.TextField(blank=True)
    evidence = models.JSONField(default=list)
    criteria_results = models.JSONField(default=list)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    usage = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_model_result'
        constraints = [models.UniqueConstraint(fields=['item', 'model_id'], name='rs_item_model_unique')]


class RescreenCall(models.Model):
    """Durable request journal. An interrupted in-flight call is never silently retried."""
    result = models.ForeignKey(RescreenModelResult, on_delete=models.CASCADE, related_name='calls')
    task = models.ForeignKey('core.Task', null=True, on_delete=models.SET_NULL, related_name='rescreen_calls')
    attempt = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default='calling')
    prompt_sha256 = models.CharField(max_length=64)
    criterion_ids = models.JSONField(default=list)
    parsed_result = models.JSONField(default=dict)
    usage = models.JSONField(default=dict)
    response = models.TextField(blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_call'
        constraints = [models.UniqueConstraint(fields=['result', 'attempt'], name='rs_call_attempt_unique')]


class RescreenReview(models.Model):
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='reviews')
    input_version = models.PositiveBigIntegerField()
    run_item = models.ForeignKey(RescreenRunItem, null=True, blank=True, on_delete=models.SET_NULL)
    decision = models.CharField(max_length=20, choices=[(v, v) for v in ('included', 'excluded', 'pending', 'not_retrieved')])
    exclusion_reason = models.TextField(blank=True)
    note = models.TextField(blank=True)
    version = models.PositiveBigIntegerField(default=1)
    criteria_revision = models.ForeignKey(RescreenCriteriaRevision, null=True, on_delete=models.RESTRICT, related_name='+')
    suggestion_revision = models.PositiveBigIntegerField(default=0)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_review'
        constraints = [models.UniqueConstraint(fields=['reference', 'input_version'], name='rs_review_input_unique')]


class RescreenReviewEvent(models.Model):
    review = models.ForeignKey(RescreenReview, on_delete=models.CASCADE, related_name='events')
    version = models.PositiveBigIntegerField()
    payload = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_review_event'
        constraints = [models.UniqueConstraint(fields=['review', 'version'], name='rs_review_event_unique')]


class QASourceBibliographySnapshot(models.Model):
    qa_reference = models.OneToOneField('core.QAReference', on_delete=models.CASCADE, related_name='rescreen_source_snapshot')
    bibliography = models.JSONField(default=dict)
    raw_metadata = models.JSONField(default=dict)
    provenance = models.JSONField(default=dict)

    class Meta:
        app_label = 'core'
        db_table = 'plat_qa_source_bibliography'


class RescreenExport(models.Model):
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='rescreen_exports')
    task = models.OneToOneField('core.Task', null=True, on_delete=models.SET_NULL, related_name='rescreen_export')
    status = models.CharField(max_length=20, default='pending')
    format = models.CharField(max_length=20)
    scope = models.CharField(max_length=20, default='all')
    mode = models.CharField(max_length=20, default='draft')
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)
    source_revision = models.PositiveBigIntegerField()
    configuration_snapshot = models.JSONField(default=dict)
    total_count = models.PositiveBigIntegerField(default=0)
    processed_count = models.PositiveBigIntegerField(default=0)
    output = models.FileField(storage=PrivateRescreenExportStorage(), upload_to=rescreen_export_path, max_length=500, blank=True)
    output_size = models.PositiveBigIntegerField(default=0)
    snapshot_size = models.PositiveBigIntegerField(default=0)
    download_name = models.CharField(max_length=150, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_export'
        constraints = [models.UniqueConstraint(fields=['project', 'idempotency_key'], name='rs_export_key_unique')]


class RescreenExportItem(models.Model):
    export = models.ForeignKey(RescreenExport, on_delete=models.CASCADE, related_name='items')
    reference_id_snapshot = models.PositiveBigIntegerField()
    payload = models.JSONField(default=dict)
    asset = models.ForeignKey('core.FulltextAsset', null=True, on_delete=models.RESTRICT, related_name='rescreen_export_items')

    class Meta:
        app_label = 'core'
        db_table = 'plat_rescreen_export_item'
        constraints = [models.UniqueConstraint(fields=['export', 'reference_id_snapshot'], name='rs_export_ref_unique')]


class FulltextLookupJob(models.Model):
    ACTIVE_STATUSES = ('pending', 'running', 'cancelling')
    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='fulltext_lookup_jobs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    task = models.OneToOneField('core.Task', null=True, on_delete=models.SET_NULL, related_name='fulltext_lookup_job')
    mode = models.CharField(max_length=20, choices=[('local', '本地'), ('online', '开放来源'), ('download', '下载候选'), ('manual', '手工外链')])
    status = models.CharField(max_length=20, default='pending')
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    input_revision = models.PositiveBigIntegerField()
    settings_snapshot = models.JSONField(default=dict)
    processed_count = models.PositiveIntegerField(default=0)
    received_bytes = models.PositiveBigIntegerField(default=0)
    request_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_lookup_job'
        constraints = [models.UniqueConstraint(fields=['project', 'idempotency_key'], name='ft_lookup_idempotency_unique')]
        indexes = [models.Index(fields=['project', 'status'], name='ft_lookup_project_status_idx')]


class FulltextLookupItem(models.Model):
    job = models.ForeignKey(FulltextLookupJob, on_delete=models.CASCADE, related_name='items')
    reference = models.ForeignKey(RescreenReference, on_delete=models.CASCADE, related_name='fulltext_lookup_items')
    input_version = models.PositiveBigIntegerField()
    bibliography_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default='pending')
    error_code = models.CharField(max_length=64, blank=True)
    resolver_notes = models.JSONField(default=dict)
    selected_candidate = models.ForeignKey('core.FulltextCandidate', null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_lookup_item'
        constraints = [models.UniqueConstraint(fields=['job', 'reference'], name='ft_lookup_item_unique')]
        indexes = [models.Index(fields=['job', 'status', 'id'], name='ft_lookup_item_status_idx')]


class FulltextCandidate(models.Model):
    item = models.ForeignKey(FulltextLookupItem, on_delete=models.CASCADE, related_name='candidates')
    asset = models.ForeignKey('core.FulltextAsset', null=True, on_delete=models.SET_NULL, related_name='lookup_candidates')
    source = models.CharField(max_length=30)
    url = models.URLField(max_length=2000, blank=True)
    license = models.CharField(max_length=100, blank=True)
    title = models.TextField(blank=True)
    doi = models.CharField(max_length=255, blank=True)
    pmid = models.CharField(max_length=64, blank=True)
    confidence = models.CharField(max_length=20, default='candidate')
    status = models.CharField(max_length=20, default='offered')
    provenance = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_candidate'
