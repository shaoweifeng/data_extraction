from uuid import uuid4

from django.db import models

from .storage import PrivateFulltextStorage, fulltext_upload_path


class FulltextAsset(models.Model):
    """Private, project-scoped physical PDF shared through explicit bindings."""

    project = models.ForeignKey('core.Project', on_delete=models.CASCADE, related_name='shared_fulltext_assets', verbose_name='所属项目')
    asset_key = models.UUIDField(verbose_name='资产唯一标识', default=uuid4, unique=True, editable=False)
    sha256 = models.CharField(verbose_name='文件 SHA-256', max_length=64)
    original_filename = models.CharField(verbose_name='原始文件名', max_length=255)
    size_bytes = models.PositiveBigIntegerField(verbose_name='文件大小（字节）', default=0)
    raw_file = models.FileField(verbose_name='原始文件', storage=PrivateFulltextStorage(), upload_to=fulltext_upload_path, max_length=500)
    extracted_text_file = models.FileField(verbose_name='提取文本文件', storage=PrivateFulltextStorage(), upload_to=fulltext_upload_path, max_length=500, blank=True)
    chunk_index_file = models.FileField(verbose_name='文本分块索引', storage=PrivateFulltextStorage(), upload_to=fulltext_upload_path, max_length=500, blank=True)
    status = models.CharField(verbose_name='状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('validating', '校验中'), ('scanning', '扫描中'), ('extracting', '文本提取中'), ('ready', '已就绪'), ('rejected', '已拒绝'), ('failed', '失败')])
    scan_status = models.CharField(verbose_name='安全扫描状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('clean', '扫描通过'), ('not_configured', '未配置扫描服务'), ('infected', '发现安全风险'), ('failed', '失败')])
    extraction_status = models.CharField(verbose_name='文本提取状态', max_length=20, default='pending', choices=[('pending', '待处理'), ('running', '进行中'), ('completed', '已完成'), ('failed', '失败')])
    page_count = models.PositiveIntegerField(verbose_name='总页数', null=True, blank=True)
    extracted_page_count = models.PositiveIntegerField(verbose_name='已提取页数', default=0)
    extracted_text_chars = models.PositiveBigIntegerField(verbose_name='已提取字符数', default=0)
    extraction_truncated = models.BooleanField(verbose_name='文本是否截断', default=False)
    truncated_at_page = models.PositiveIntegerField(verbose_name='截断所在页', null=True, blank=True)
    extraction_version = models.CharField(verbose_name='文本提取版本', max_length=50, blank=True)
    chunking_version = models.CharField(verbose_name='文本分块版本', max_length=50, blank=True)
    extracted_text_sha256 = models.CharField(verbose_name='提取文本 SHA-256', max_length=64, blank=True)
    chunk_index_sha256 = models.CharField(verbose_name='分块索引 SHA-256', max_length=64, blank=True)
    chunk_count = models.PositiveIntegerField(verbose_name='文本块数', default=0)
    error_code = models.CharField(verbose_name='错误代码', max_length=64, blank=True)
    error_message = models.CharField(verbose_name='错误说明', max_length=500, blank=True)
    metadata = models.JSONField(verbose_name='元数据', default=dict, blank=True)
    primary_doi = models.CharField(verbose_name='主要 DOI', max_length=255, blank=True)
    primary_pmid = models.CharField(verbose_name='主要 PMID', max_length=64, blank=True)
    normalized_title_hash = models.CharField(verbose_name='标准化标题摘要', max_length=64, blank=True)
    provenance = models.JSONField(verbose_name='来源追溯信息', default=dict, blank=True)
    processing_task = models.ForeignKey('core.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='fulltext_assets', verbose_name='全文处理任务')
    processing_token = models.UUIDField(verbose_name='处理代次标识', null=True, blank=True)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    def __str__(self):
        return f'{self._meta.verbose_name} #{self.pk}'

    class Meta:
        app_label = 'core'
        db_table = 'plat_fulltext_asset'
        constraints = [models.UniqueConstraint(fields=['project', 'sha256'], name='ft_project_sha_unique')]
        indexes = [models.Index(fields=['project', 'status'], name='ft_project_status_idx'),
            models.Index(fields=['project', 'primary_doi'], name='ft_project_doi_idx'),
            models.Index(fields=['project', 'normalized_title_hash'], name='ft_project_title_idx')]
        verbose_name = '共享全文资产'
        verbose_name_plural = verbose_name
