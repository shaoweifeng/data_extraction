from uuid import uuid4

from django.db import models

from .storage import PrivateFulltextStorage, fulltext_upload_path


class FulltextAsset(models.Model):
    """Private, project-scoped physical PDF shared through explicit bindings."""

    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='shared_fulltext_assets')
    asset_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    sha256 = models.CharField(max_length=64)
    original_filename = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField(default=0)
    raw_file = models.FileField(storage=PrivateFulltextStorage(), upload_to=fulltext_upload_path, max_length=500)
    extracted_text_file = models.FileField(storage=PrivateFulltextStorage(), upload_to=fulltext_upload_path, max_length=500, blank=True)
    chunk_index_file = models.FileField(storage=PrivateFulltextStorage(), upload_to=fulltext_upload_path, max_length=500, blank=True)
    status = models.CharField(max_length=20, default='pending', choices=[(v, v) for v in (
        'pending', 'validating', 'scanning', 'extracting', 'ready', 'rejected', 'failed',
    )])
    scan_status = models.CharField(max_length=20, default='pending')
    extraction_status = models.CharField(max_length=20, default='pending')
    page_count = models.PositiveIntegerField(null=True, blank=True)
    extracted_page_count = models.PositiveIntegerField(default=0)
    extracted_text_chars = models.PositiveBigIntegerField(default=0)
    extraction_truncated = models.BooleanField(default=False)
    truncated_at_page = models.PositiveIntegerField(null=True, blank=True)
    extraction_version = models.CharField(max_length=50, blank=True)
    chunking_version = models.CharField(max_length=50, blank=True)
    extracted_text_sha256 = models.CharField(max_length=64, blank=True)
    chunk_index_sha256 = models.CharField(max_length=64, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    primary_doi = models.CharField(max_length=255, blank=True)
    primary_pmid = models.CharField(max_length=64, blank=True)
    normalized_title_hash = models.CharField(max_length=64, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    processing_task = models.ForeignKey('core.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='fulltext_assets')
    processing_token = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_asset'
        constraints = [models.UniqueConstraint(fields=['project', 'sha256'], name='ft_project_sha_unique')]
        indexes = [models.Index(fields=['project', 'status'], name='ft_project_status_idx'),
            models.Index(fields=['project', 'primary_doi'], name='ft_project_doi_idx'),
            models.Index(fields=['project', 'normalized_title_hash'], name='ft_project_title_idx')]
        verbose_name = '共享全文资产'
        verbose_name_plural = verbose_name
