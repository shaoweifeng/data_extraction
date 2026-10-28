"""Lease-guarded processing of private assets; no provider/model requests."""
import hashlib
import re
from uuid import uuid4
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from core.fulltext.chunks import build_chunks, serialize_chunks, CHUNKING_VERSION
from core.fulltext.errors import FulltextError
from core.fulltext.extraction import extract_page_text, EXTRACTION_VERSION
from core.fulltext.models import FulltextAsset
from core.fulltext.scanner import scan_pdf
from core.fulltext.storage import materialized_storage_path
from core.services.storage_quota_service import user_storage_quota_guard


def _fail(asset_id, token, code, message, *, rejected=False, scan_status=None):
    updates = dict(status='rejected' if rejected else 'failed', extraction_status='failed',
        error_code=code, error_message=str(message)[:500], updated_at=timezone.now())
    if scan_status:
        updates['scan_status'] = scan_status
    changed = FulltextAsset.objects.filter(pk=asset_id, processing_token=token).update(**updates)
    from core.models import QAReference
    if changed:
        QAReference.objects.filter(shared_fulltext_asset_id=asset_id).update(fulltext_status='error')


def process_asset(asset_id, *, expected_task_id=None, check_stop=None):
    with transaction.atomic():
        asset = FulltextAsset.objects.select_for_update().select_related('project__owner').get(pk=asset_id)
        if expected_task_id is not None and asset.processing_task_id != expected_task_id:
            raise FulltextError('stale_task', '全文处理任务已被替代。', status=409)
        if asset.status != 'pending':
            return asset
        token = uuid4()
        asset.processing_token, asset.status = token, 'validating'
        asset.save(update_fields=['processing_token', 'status', 'updated_at'])

    def checkpoint():
        if (check_stop and check_stop()) or not FulltextAsset.objects.filter(
                pk=asset.pk, processing_token=token, status__in=('validating', 'scanning', 'extracting')).exists():
            raise FulltextError('processing_cancelled', '全文处理已停止。', status=409)

    new_files = []
    try:
        checkpoint()
        with materialized_storage_path(asset.raw_file, suffix='.pdf', max_bytes=min(asset.size_bytes, settings.QA_FULLTEXT_MAX_FILE_BYTES)) as path:
            digest, size = hashlib.sha256(), 0
            with open(path, 'rb') as raw:
                while body := raw.read(1024*1024):
                    checkpoint()
                    size += len(body)
                    if size > settings.QA_FULLTEXT_MAX_FILE_BYTES or size > asset.size_bytes:
                        raise FulltextError('pdf_hash_mismatch', '私有 PDF 大小与上传记录不一致。')
                    digest.update(body)
            if size != asset.size_bytes or digest.hexdigest() != asset.sha256:
                raise FulltextError('pdf_hash_mismatch', '私有 PDF 校验失败。')
            try:
                import fitz
                document = fitz.open(path)
            except Exception as exc:
                raise FulltextError('pdf_corrupt', 'PDF 已损坏或结构不受支持。') from exc
            with document:
                if document.needs_pass:
                    raise FulltextError('pdf_encrypted', '不支持加密的 PDF。')
                page_count = len(document)
                if not 0 < page_count <= settings.QA_FULLTEXT_MAX_PAGES:
                    raise FulltextError('too_many_pages', 'PDF 页面为空或超过页数限制。')
                FulltextAsset.objects.filter(pk=asset.pk, processing_token=token).update(status='scanning', page_count=page_count)
                try:
                    scan = scan_pdf(path)
                except Exception as exc:
                    raise FulltextError('malware_scan_unavailable', '文件安全扫描暂时不可用。') from exc
                checkpoint()
                if scan.status == 'infected':
                    _fail(asset.pk, token, 'malware_detected', 'PDF 安全扫描发现威胁。', rejected=True, scan_status=scan.status)
                    return FulltextAsset.objects.get(pk=asset.pk)
                if scan.status == 'failed' or (settings.QA_FULLTEXT_REQUIRE_CLEAN_SCAN and scan.status != 'clean'):
                    _fail(asset.pk, token, 'malware_scan_unavailable', 'PDF 安全扫描未通过。', scan_status=scan.status)
                    return FulltextAsset.objects.get(pk=asset.pk)
                FulltextAsset.objects.filter(pk=asset.pk, processing_token=token).update(
                    status='extracting', scan_status=scan.status, extraction_status='running')
                extraction = extract_page_text(document, max_chars=settings.QA_PDF_TEXT_MAX_CHARS, check_stop=checkpoint)
                # Diagnostic metadata only; never overwrite the confirmed bibliography with PDF producer names.
                metadata = {str(key): str(value or '')[:500] for key, value in (document.metadata or {}).items()}
                first_pages = '\n'.join(page.text for page in extraction['pages'] if page.page_number <= 2)[:20000]
                metadata['dois'] = list(dict.fromkeys(value.rstrip('.,;:)]}') for value in re.findall(
                    r'10\.\d{4,9}/[^\s<>"\u4e00-\u9fff]+', first_pages, flags=re.I)))[:20]
                metadata['pmids'] = list(dict.fromkeys(re.findall(r'PMID\s*:\s*(\d+)', first_pages, flags=re.I)))[:20]
        chunks = build_chunks(extraction['pages'], target_tokens=settings.QA_CHUNK_TARGET_TOKENS,
                              overlap_tokens=settings.QA_CHUNK_OVERLAP_TOKENS)
        text_bytes = extraction['text'].encode('utf-8')
        chunk_bytes = serialize_chunks(chunks) if chunks else b''
        checkpoint()
        with user_storage_quota_guard(asset.project.owner, len(text_bytes)+len(chunk_bytes)), transaction.atomic():
            locked = FulltextAsset.objects.select_for_update().get(pk=asset.pk)
            if locked.processing_token != token or locked.status != 'extracting':
                raise FulltextError('stale_task', '全文处理租约已失效。', status=409)
            old_files = [(getattr(locked, field).storage, getattr(locked, field).name)
                         for field in ('extracted_text_file', 'chunk_index_file') if getattr(locked, field)]
            for field, name, body in (('extracted_text_file', 'extracted.txt', text_bytes),
                                      ('chunk_index_file', 'chunks.jsonl', chunk_bytes)):
                if body:
                    getattr(locked, field).save(name, ContentFile(body), save=False)
                    new_files.append((getattr(locked, field).storage, getattr(locked, field).name))
            locked.extracted_text_sha256 = hashlib.sha256(text_bytes).hexdigest() if text_bytes else ''
            locked.chunk_index_sha256 = hashlib.sha256(chunk_bytes).hexdigest() if chunk_bytes else ''
            locked.extracted_text_chars = len(extraction['text'])
            locked.extracted_page_count = extraction['extracted_page_count']
            locked.extraction_truncated = extraction['truncated']
            locked.truncated_at_page = extraction['truncated_at_page']
            locked.chunk_count = len(chunks)
            locked.extraction_version, locked.chunking_version = EXTRACTION_VERSION, CHUNKING_VERSION
            locked.extraction_status = 'completed' if text_bytes else 'skipped'
            locked.metadata, locked.status = metadata, 'ready'
            from core.screening.services.reference_persistence import normalize_doi
            locked.primary_doi = normalize_doi(metadata['dois'][0])[:255] if len(metadata['dois']) == 1 else ''
            locked.primary_pmid = metadata['pmids'][0][:64] if len(metadata['pmids']) == 1 else ''
            locked.error_code = locked.error_message = ''
            locked.save()
            from core.models import QAReference
            QAReference.objects.filter(shared_fulltext_asset=locked).update(fulltext_status='available')
            for storage, name in old_files:
                transaction.on_commit(lambda storage=storage, name=name: storage.delete(name))
        return locked
    except BaseException as exc:
        for storage, name in new_files:
            storage.delete(name)
        code = getattr(exc, 'code', 'pdf_processing_failed')
        _fail(asset.pk, token, code, str(exc) if isinstance(exc, (FulltextError, ValueError)) else 'PDF 处理失败，请重试。',
              rejected=code in ('pdf_corrupt', 'pdf_encrypted', 'too_many_pages'))
        raise
