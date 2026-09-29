"""Validation, persistence and bounded processing for QA full-text PDFs."""

import hashlib
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import QAFulltextAsset, QAReference
from core.quality.services.pdf_scanner import scan_pdf
from core.quality.storage import materialized_storage_path


class FulltextUploadError(ValueError):
    def __init__(self, code, message, *, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def validate_fulltext_settings():
    positive = (
        'QA_FULLTEXT_MAX_FILES_PER_REQUEST', 'QA_FULLTEXT_MAX_FILE_BYTES',
        'QA_FULLTEXT_MAX_TOTAL_BYTES', 'QA_FULLTEXT_MAX_PAGES',
        'QA_PDF_TEXT_MAX_PAGES', 'QA_PDF_TEXT_MAX_CHARS', 'QA_AI_MAX_CONTENT_CHARS',
        'QA_PDF_PROCESS_SOFT_TIME_LIMIT', 'QA_PDF_PROCESS_HARD_TIME_LIMIT',
    )
    invalid = [name for name in positive if getattr(settings, name, 0) <= 0]
    if settings.QA_PDF_PROCESS_HARD_TIME_LIMIT <= settings.QA_PDF_PROCESS_SOFT_TIME_LIMIT:
        invalid.append('QA_PDF_PROCESS_HARD_TIME_LIMIT')
    if invalid:
        raise ValueError(f'质量评价全文配置必须为正数且硬超时大于软超时: {", ".join(invalid)}')


def _hash_and_check(uploaded_file):
    digest = hashlib.sha256()
    header = b''
    for chunk in uploaded_file.chunks():
        if len(header) < 5:
            header += chunk[:5 - len(header)]
        digest.update(chunk)
    uploaded_file.seek(0)
    if header != b'%PDF-':
        raise FulltextUploadError('invalid_pdf_signature', '文件内容不是有效的 PDF。')
    return digest.hexdigest()


def validate_uploads(project, files):
    if len(files) > settings.QA_FULLTEXT_MAX_FILES_PER_REQUEST:
        raise FulltextUploadError(
            'too_many_files', f'每次最多上传 {settings.QA_FULLTEXT_MAX_FILES_PER_REQUEST} 个 PDF。'
        )
    total = sum(item.size for item in files)
    if total > settings.QA_FULLTEXT_MAX_TOTAL_BYTES:
        raise FulltextUploadError('total_too_large', '本次上传文件总大小超过限制。')

    checked = []
    batch_hashes = set()
    for item in files:
        safe_name = Path(item.name).name
        if not safe_name or len(safe_name) > 255 or Path(safe_name).suffix.lower() != '.pdf':
            raise FulltextUploadError('invalid_filename', '仅支持文件名不超过 255 字符的 .pdf 文件。')
        if item.size <= 0 or item.size > settings.QA_FULLTEXT_MAX_FILE_BYTES:
            raise FulltextUploadError('file_too_large', f'PDF “{safe_name}”为空或超过单文件大小限制。')
        content_type = (getattr(item, 'content_type', '') or '').lower()
        if content_type not in {'application/pdf', 'application/octet-stream'}:
            raise FulltextUploadError('invalid_mime_type', f'PDF “{safe_name}”的 MIME 类型不正确。')
        sha256 = _hash_and_check(item)
        if sha256 in batch_hashes or QAFulltextAsset.objects.filter(
            project=project, sha256=sha256,
        ).exists():
            raise FulltextUploadError('duplicate_fulltext', f'PDF “{safe_name}”已在该项目中上传。', status=409)
        batch_hashes.add(sha256)
        checked.append((item, safe_name, sha256))
    return checked


def create_fulltext_assets(project, files):
    checked = validate_uploads(project, files)
    created = []
    stored = []
    try:
        with transaction.atomic():
            for uploaded, safe_name, sha256 in checked:
                ref = QAReference.objects.create(
                    project=project,
                    title=Path(safe_name).stem.replace('_', ' '),
                    source_type='fulltext_upload',
                    fulltext_status='pending',
                )
                asset = QAFulltextAsset(
                    qa_reference=ref,
                    project=project,
                    original_filename=safe_name,
                    sha256=sha256,
                    size_bytes=uploaded.size,
                    mime_type='application/pdf',
                )
                asset.raw_file.save(safe_name, uploaded, save=False)
                stored.append((asset.raw_file.storage, asset.raw_file.name))
                asset.save()
                created.append(ref)
    except IntegrityError as exc:
        for storage, name in stored:
            storage.delete(name)
        raise FulltextUploadError(
            'duplicate_fulltext', '相同 PDF 已被并发上传到该项目。', status=409,
        ) from exc
    except Exception:
        for storage, name in stored:
            storage.delete(name)
        raise
    return created


def _reject(asset, code, message, *, failed=False):
    asset.status = 'failed' if failed else 'rejected'
    asset.error_code = code
    asset.error_message = message[:500]
    asset.extraction_status = 'failed'
    asset.save()
    QAReference.objects.filter(pk=asset.qa_reference_id).update(fulltext_status='error')


def mark_processing_timeout(asset_id):
    asset = QAFulltextAsset.objects.filter(pk=asset_id).first()
    if asset:
        _reject(asset, 'pdf_processing_timeout', 'PDF 处理超时。', failed=True)


def process_fulltext_asset(asset_id):
    """Validate, scan and extract one asset with bounded pages and characters."""
    with transaction.atomic():
        asset = QAFulltextAsset.objects.select_for_update().select_related('qa_reference').get(
            pk=asset_id
        )
        if asset.status in {'ready', 'rejected'}:
            return
        if asset.status in {'validating', 'scanning', 'extracting'}:
            return
        if asset.extracted_text_file:
            asset.extracted_text_file.delete(save=False)
            asset.extracted_text_file = ''
            asset.extracted_text_sha256 = ''
            asset.extracted_text_chars = 0
        asset.status = 'validating'
        asset.error_code = ''
        asset.error_message = ''
        asset.save(update_fields=[
            'extracted_text_file', 'extracted_text_sha256', 'extracted_text_chars',
            'status', 'error_code', 'error_message', 'updated_at',
        ])

    try:
        with materialized_storage_path(asset.raw_file, suffix='.pdf') as file_path:
            try:
                import fitz
                document = fitz.open(file_path)
            except Exception:
                _reject(asset, 'pdf_corrupt', 'PDF 已损坏或结构不受支持。')
                return
            try:
                if document.needs_pass:
                    _reject(asset, 'pdf_encrypted', '不支持加密或需要密码的 PDF。')
                    return
                page_count = len(document)
                asset.page_count = page_count
                if page_count <= 0:
                    _reject(asset, 'pdf_empty', 'PDF 不包含可读取页面。')
                    return
                if page_count > settings.QA_FULLTEXT_MAX_PAGES:
                    _reject(asset, 'too_many_pages', f'PDF 页数超过 {settings.QA_FULLTEXT_MAX_PAGES} 页限制。')
                    return
                asset.validated_at = timezone.now()
                asset.status = 'scanning'
                asset.save(update_fields=['page_count', 'validated_at', 'status', 'updated_at'])

                try:
                    scan = scan_pdf(file_path)
                except Exception:
                    asset.scan_status = 'failed'
                    asset.scanned_at = timezone.now()
                    _reject(asset, 'malware_scan_unavailable', '文件安全扫描暂时不可用。', failed=True)
                    return
                asset.scan_status = scan.status
                asset.scanned_at = timezone.now()
                if scan.status == 'infected':
                    _reject(asset, 'malware_detected', '安全扫描发现文件存在威胁。')
                    return
                if scan.status == 'failed' or (
                    settings.QA_FULLTEXT_REQUIRE_CLEAN_SCAN and scan.status != 'clean'
                ):
                    _reject(asset, 'malware_scan_unavailable', '文件安全扫描未通过。', failed=True)
                    return

                asset.status = 'extracting'
                asset.extraction_status = 'running'
                asset.save(update_fields=[
                    'scan_status', 'scanned_at', 'status', 'extraction_status', 'updated_at',
                ])
                metadata = document.metadata or {}
                chunks = []
                chars = 0
                for page_index in range(min(page_count, settings.QA_PDF_TEXT_MAX_PAGES)):
                    text = document[page_index].get_text() or ''
                    remaining = settings.QA_PDF_TEXT_MAX_CHARS - chars
                    if remaining <= 0:
                        break
                    text = text[:remaining]
                    if text.strip():
                        chunks.append(text)
                        chars += len(text)
                extracted = '\n'.join(chunks).strip()
            finally:
                document.close()

        ref_updates = {}
        title = (metadata.get('title') or '').strip()
        author = (metadata.get('author') or '').strip()
        if title:
            ref_updates['title'] = title[:500]
        if author:
            ref_updates['first_author'] = author.split(';')[0].split(',')[0][:200]
        if extracted:
            text_bytes = extracted.encode('utf-8')
            asset.extracted_text_file.save('extracted.txt', ContentFile(text_bytes), save=False)
            asset.extracted_text_sha256 = hashlib.sha256(text_bytes).hexdigest()
            asset.extracted_text_chars = len(extracted)
            asset.extraction_status = 'completed'
            if not asset.qa_reference.abstract:
                ref_updates['abstract'] = extracted[:600]
        else:
            asset.extraction_status = 'skipped'
        asset.extracted_at = timezone.now()
        asset.status = 'ready'
        asset.save()
        ref_updates['fulltext_status'] = 'available'
        QAReference.objects.filter(pk=asset.qa_reference_id).update(**ref_updates)
    except Exception:
        if asset.extracted_text_file:
            asset.extracted_text_file.delete(save=False)
            asset.extracted_text_file = ''
            asset.extracted_text_sha256 = ''
            asset.extracted_text_chars = 0
        _reject(asset, 'pdf_processing_failed', 'PDF 处理失败，请稍后重试。', failed=True)
        raise


def cleanup_expired_fulltext_files(*, now=None):
    """Purge file bodies while retaining audit metadata and error categories."""
    now = now or timezone.now()
    failed_cutoff = now - timedelta(days=max(1, settings.QA_FULLTEXT_FAILED_RETENTION_DAYS))
    text_cutoff = now - timedelta(days=max(1, settings.QA_EXTRACTED_TEXT_RETENTION_DAYS))
    raw_purged = 0
    text_purged = 0
    stale_failed = 0

    stale_cutoff = now - timedelta(seconds=settings.QA_PDF_PROCESS_HARD_TIME_LIMIT * 2)
    stale_assets = QAFulltextAsset.objects.filter(
        status__in=['validating', 'scanning', 'extracting'], updated_at__lt=stale_cutoff,
    )
    for asset in stale_assets.iterator(chunk_size=200):
        _reject(asset, 'worker_interrupted', 'PDF 处理进程异常中断，可以重试。', failed=True)
        stale_failed += 1

    failed_assets = QAFulltextAsset.objects.filter(
        status__in=['failed', 'rejected'], updated_at__lt=failed_cutoff,
    ).exclude(raw_file='')
    for asset in failed_assets.iterator(chunk_size=200):
        asset.raw_file.delete(save=False)
        asset.raw_file = ''
        asset.save(update_fields=['raw_file', 'updated_at'])
        raw_purged += 1

    completed_assets = QAFulltextAsset.objects.filter(
        extraction_status='completed', extracted_at__lt=text_cutoff,
        qa_reference__ai_eval_status='completed',
    ).exclude(extracted_text_file='')
    for asset in completed_assets.iterator(chunk_size=200):
        asset.extracted_text_file.delete(save=False)
        asset.extracted_text_file = ''
        asset.extraction_status = 'purged'
        asset.save(update_fields=['extracted_text_file', 'extraction_status', 'updated_at'])
        text_purged += 1
    return {'stale_assets': stale_failed, 'raw_files': raw_purged, 'text_files': text_purged}
