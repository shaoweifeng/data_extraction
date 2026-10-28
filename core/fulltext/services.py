"""Private PDF persistence, quota accounting, retry and protected deletion."""
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from core.fulltext.errors import FulltextError
from core.fulltext.models import FulltextAsset
from core.models import Project, ProjectStage
from core.fulltext.validation import hash_and_check
from core.services.access_policy import ProjectAccessPolicy
from core.services.storage_quota_service import enforce_user_storage_quota

PROCESSING = ('pending', 'validating', 'scanning', 'extracting')


def require_upload(project, user):
    from core.api.common import check_permission
    ProjectAccessPolicy.require_project(user, project.pk)
    if not check_permission(user, 'file.upload'):
        raise FulltextError('permission_denied', '没有上传全文的权限。', status=403)


def checked_uploads(files):
    files = list(files)
    if not files or len(files) > settings.QA_FULLTEXT_MAX_FILES_PER_REQUEST:
        raise FulltextError('invalid_file_count', '上传 PDF 数量为空或超过单次上限。')
    if sum(item.size for item in files) > settings.QA_FULLTEXT_MAX_TOTAL_BYTES:
        raise FulltextError('total_too_large', '上传 PDF 总大小超过限制。', status=413)
    checked = []
    for item in files:
        name = str(item.name or '')
        if not name or len(name) > 255 or '/' in name or '\\' in name or '\x00' in name or Path(name).suffix.lower() != '.pdf':
            raise FulltextError('invalid_filename', '仅支持安全文件名的 .pdf 文件。')
        if not 0 < item.size <= settings.QA_FULLTEXT_MAX_FILE_BYTES:
            raise FulltextError('file_too_large', 'PDF 为空或超过单文件大小限制。', status=413)
        if getattr(item, 'content_type', 'application/pdf').lower() not in ('application/pdf', 'application/octet-stream'):
            raise FulltextError('invalid_mime_type', 'PDF 的 MIME 类型不正确。')
        sha = hash_and_check(item)
        checked.append((item, name, sha))
    return checked


def schedule_processing(asset, user):
    from core.step_config import get_step_config
    from core.workflow.services.task_launcher import create_step_task
    ProjectStage.objects.get_or_create(project=asset.project, stage_key='SCREEN_2',
        defaults={'name': '文献复筛', 'order': 30})
    task = create_step_task(asset.project_id, 'rescreen_pdf', user.pk,
        dict(get_step_config('rescreen_pdf'), fulltext_asset_id=asset.pk), exclusive=False)
    asset.processing_task = task
    asset.processing_token = None
    asset.save(update_fields=['processing_task', 'processing_token'])
    transaction.on_commit(lambda: _dispatch_processing(asset.pk, task.pk))


def _dispatch_processing(asset_id, task_id):
    from core.models import Task
    from core.workflow.services.task_launcher import dispatch_step_task
    try:
        dispatch_step_task(Task.objects.get(pk=task_id), 'rescreen_pdf')
    except Exception:
        FulltextAsset.objects.filter(pk=asset_id, processing_task_id=task_id, status='pending').update(
            status='failed', error_code='dispatch_failed', error_message='全文处理任务派发失败，请重试。')


def create_assets(*, project, user, files, create_references=False, schedule=True, provenance=None):
    require_upload(project, user)
    from core.operations.services import assert_accepting_new_work
    assert_accepting_new_work()
    checked = checked_uploads(files)
    stored, assets = [], []
    try:
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=project.owner_id)
            project = Project.objects.select_for_update().get(pk=project.pk)
            existing = {asset.sha256: asset for asset in FulltextAsset.objects.filter(
                project=project, sha256__in=[sha for _, _, sha in checked])}
            unique = {sha: (item, name) for item, name, sha in checked if sha not in existing}
            if FulltextAsset.objects.filter(project=project).count()+len(unique) > settings.FULLTEXT_MAX_ASSETS_PER_PROJECT:
                raise FulltextError('asset_count_limit', '项目物理全文资产数量已达上限。', status=413)
            from datetime import timedelta
            recent = FulltextAsset.objects.filter(project__owner=project.owner,
                created_at__gte=timezone.now()-timedelta(minutes=1)).count()
            if recent+len(unique) > settings.FULLTEXT_UPLOAD_RATE_PER_MINUTE:
                raise FulltextError('upload_rate_limited', '新增 PDF 过于频繁，请稍后上传。', status=429)
            pending = FulltextAsset.objects.filter(project__owner=project.owner, status__in=PROCESSING).count()
            if pending + len(unique) > settings.FULLTEXT_MAX_PENDING_PER_USER:
                raise FulltextError('too_many_pending', '账户已有过多等待处理的 PDF，请稍后上传。', status=429)
            enforce_user_storage_quota(project.owner, sum(item.size for item, _ in unique.values()))
            for sha, (uploaded, name) in unique.items():
                asset = FulltextAsset(project=project, original_filename=name, sha256=sha,
                    size_bytes=uploaded.size, provenance=provenance or {'source': 'manual_upload', 'user_id': user.pk})
                import hashlib
                from core.screening.services.reference_persistence import normalize_title
                asset.normalized_title_hash = hashlib.sha256(normalize_title(Path(name).stem).encode()).hexdigest()
                asset.raw_file.save(name, uploaded, save=False)
                stored.append((asset.raw_file.storage, asset.raw_file.name))
                asset.save()
                existing[sha] = asset
                if schedule:
                    schedule_processing(asset, user)
            assets = list({sha: existing[sha] for _, _, sha in checked}.values())
            refs = []
            if create_references:
                from core.rescreening.services.fulltext_binding import import_pdf_references
                refs = import_pdf_references(project, user, assets)
        return assets, refs
    except Exception:
        for storage, name in stored:
            storage.delete(name)
        raise


def retry_asset(asset, user):
    require_upload(asset.project, user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=asset.project.owner_id)
        Project.objects.select_for_update().get(pk=asset.project_id)
        asset = FulltextAsset.objects.select_for_update().get(pk=asset.pk)
        if asset.status != 'failed':
            raise FulltextError('not_retryable', '只有处理失败的 PDF 可以重试。', status=409)
        if not asset.raw_file or not asset.raw_file.storage.exists(asset.raw_file.name):
            raise FulltextError('source_missing', '原始 PDF 不存在，请重新上传。', status=410)
        if FulltextAsset.objects.filter(project__owner=asset.project.owner, status__in=PROCESSING).count() >= settings.FULLTEXT_MAX_PENDING_PER_USER:
            raise FulltextError('too_many_pending', '等待处理的 PDF 已达上限。', status=429)
        from datetime import timedelta
        from core.models import Task
        if Task.objects.filter(created_by=user, task_type='rescreen_pdf',
                created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= settings.FULLTEXT_MAX_PENDING_PER_USER:
            raise FulltextError('retry_rate_limited', 'PDF 重试过于频繁，请稍后再试。', status=429)
        asset.status, asset.extraction_status = 'pending', 'pending'
        asset.error_code = asset.error_message = ''
        asset.save(update_fields=['status', 'extraction_status', 'error_code', 'error_message', 'updated_at'])
        schedule_processing(asset, user)
    return asset


def asset_is_referenced(asset):
    from core.models import QAReference
    from core.rescreening.models import RescreenFulltextBinding, RescreenRunItem, RescreenExportItem
    return (RescreenFulltextBinding.objects.filter(asset=asset).exists()
        or RescreenRunItem.objects.filter(asset=asset).exists()
        or QAReference.objects.filter(shared_fulltext_asset=asset).exists()
        or RescreenExportItem.objects.filter(asset=asset).exists())


def rebuild_asset(asset, user, *, schedule=True):
    """Only unused assets may replace their derived evidence bodies in place."""
    require_upload(asset.project, user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=asset.project.owner_id)
        Project.objects.select_for_update().get(pk=asset.project_id)
        asset = FulltextAsset.objects.select_for_update().get(pk=asset.pk)
        if asset.status in PROCESSING or asset_is_referenced(asset):
            raise FulltextError('asset_in_use', '正在处理或被引用的全文不能原地重建证据，请保留历史。', status=409)
        if not asset.raw_file or not asset.raw_file.storage.exists(asset.raw_file.name):
            raise FulltextError('source_missing', '原始 PDF 已不存在。', status=410)
        asset.status, asset.extraction_status, asset.processing_token = 'pending', 'pending', None
        asset.error_code = asset.error_message = ''
        asset.save(update_fields=['status', 'extraction_status', 'processing_token', 'error_code', 'error_message', 'updated_at'])
        if schedule:
            schedule_processing(asset, user)
    return asset


def delete_asset(asset, user):
    require_upload(asset.project, user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=asset.project.owner_id)
        Project.objects.select_for_update().get(pk=asset.project_id)
        asset = FulltextAsset.objects.select_for_update().get(pk=asset.pk)
        if asset.status in PROCESSING or asset_is_referenced(asset):
            raise FulltextError('asset_in_use', '全文仍在处理或被文献、历史运行或质量评价引用，不能删除。', status=409)
        asset.delete()
