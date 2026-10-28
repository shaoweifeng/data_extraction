"""Private, staged, revision-bound imports with bounded persistence batches."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import ActivityLog, Project, ProjectStage
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenImportBatch, RescreenImportFile, RescreenReference
from core.rescreening.services.source import digest, source_preview
from core.screening.services.import_limits import ImportLimits
from core.screening.services.import_validation import validate_uploads
from core.services.access_policy import ProjectAccessPolicy
from core.workflow.services.task_launcher import ACTIVE_EXECUTION_STATUSES, create_step_task, dispatch_step_task


def _require_project(project, user):
    ProjectAccessPolicy.require_project(user, project.pk)
    from core.api.common import check_permission
    if not check_permission(user, 'file.upload') or not check_permission(user, 'task.start'):
        raise RescreenError('permission_denied', '没有导入文献或启动任务的权限。', status=403)


def _require_idle(project, *, exclude_batch=None):
    active = RescreenImportBatch.objects.filter(project=project, status__in=RescreenImportBatch.ACTIVE_STATUSES)
    if exclude_batch:
        active = active.exclude(pk=exclude_batch)
    from core.rescreening.models import FulltextLookupJob, RescreenRun
    if (active.exists() or FulltextLookupJob.objects.filter(project=project, status__in=FulltextLookupJob.ACTIVE_STATUSES).exists()
            or RescreenRun.objects.filter(corpus__project=project, status__in=('pending', 'running', 'cancelling', 'settlement_pending')).exists()
            or project.tasks.filter(task_type__in=('rescreen_import', 'rescreen_ai'), status__in=ACTIVE_EXECUTION_STATUSES).exists()):
        raise RescreenError('rescreen_busy', '复筛已有活动任务，请等待完成或停止后再操作。', status=409)


def _require_rate(user, limits):
    from core.models import Task
    if Task.objects.filter(created_by=user, task_type='rescreen_import',
            created_at__gte=timezone.now()-timedelta(seconds=limits.rate_limit_window_seconds)).count() >= limits.rate_limit_requests:
        raise RescreenError('import_rate_limited', '导入过于频繁，请稍后重试。', status=429)


def _new_task(batch, user):
    from core.step_config import get_step_config
    ProjectStage.objects.get_or_create(project=batch.project, stage_key='SCREEN_2', defaults={'name': '文献复筛', 'order': 30})
    task = create_step_task(batch.project_id, 'rescreen_import', user.pk, {
        'rescreen_import_batch_id': batch.pk, **get_step_config('rescreen_import'),
    })
    batch.task = task
    batch.save(update_fields=['task'])
    return task


def _dispatch(batch_id, task_id):
    from core.models import Task
    try:
        dispatch_step_task(Task.objects.get(pk=task_id), 'rescreen_import')
    except Exception:
        RescreenImportBatch.objects.filter(pk=batch_id, task_id=task_id,
            status__in=RescreenImportBatch.ACTIVE_STATUSES).update(
            status='failed', error_code='dispatch_failed', error_message='后台任务派发失败，请重试。', finished_at=timezone.now(),
        )


def start_import(*, project, user, idempotency_key, uploads=None, preview=None):
    _require_project(project, user)
    limits = ImportLimits.from_settings()
    validated = validate_uploads(uploads, limits) if uploads is not None else []
    source_type = 'bibliography' if uploads is not None else 'screening'
    if source_type == 'screening' and not preview:
        raise RescreenError('preview_required', '请先预览初筛来源。')
    payload = ([{'sha256': item.sha256, 'name': item.original_filename} for item in validated]
               if validated else {'run_id': preview['run_id'], 'fingerprint': preview['fingerprint']})
    request_hash = digest({'type': source_type, 'input': payload})
    stored = []
    try:
        # Lock owner before checking idempotency, quota and cross-project limits.
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=project.owner_id)
            project = Project.objects.select_for_update().get(pk=project.pk)
            old = RescreenImportBatch.objects.filter(project=project, idempotency_key=idempotency_key).first()
            if old:
                if old.request_hash != request_hash:
                    raise RescreenError('idempotency_conflict', '同一幂等键已用于不同的导入请求。', status=409)
                return old
            from core.services.storage_quota_service import enforce_user_storage_quota
            enforce_user_storage_quota(project.owner, sum(item.size for item in validated))
            _require_idle(project)
            _require_rate(user, limits)
            if RescreenImportBatch.objects.filter(created_by=user, status__in=RescreenImportBatch.ACTIVE_STATUSES).count() >= limits.max_concurrent_per_user:
                raise RescreenError('import_concurrency_limit', '当前账户已有导入任务，请稍后再试。', status=409)
            if preview and preview['changed_count']:
                raise RescreenError('source_changed', '初筛来源有变化，请先检查差异；不会覆盖已有复筛记录。', status=409)
            if validated:
                for item in validated:
                    if RescreenImportFile.objects.filter(batch__project=project, batch__status='completed', sha256=item.sha256).exists():
                        raise RescreenError('duplicate_file', '此题录文件已成功导入，请勿重复上传；失败批次请使用重试。', status=409)
            corpus, _ = RescreenCorpus.objects.get_or_create(project=project)
            if preview and corpus.active_reference_count + preview['new_count'] > limits.max_references:
                raise RescreenError('too_many_references', '导入后文献数将超过上限。', status=413)
            batch = RescreenImportBatch.objects.create(
                project=project, corpus=corpus, source_type=source_type,
                base_revision=corpus.revision, target_revision=corpus.revision+1,
                idempotency_key=idempotency_key, request_hash=request_hash,
                source_screening_run_id=preview['run_id'] if preview else None,
                source_snapshot=preview or {}, limits_snapshot=limits.snapshot(), created_by=user,
            )
            for item in validated:
                source = RescreenImportFile(batch=batch, original_filename=item.original_filename,
                    source_format=item.source_format, size_bytes=item.size, sha256=item.sha256)
                source.raw_file.save(item.original_filename, item.uploaded_file, save=False)
                stored.append((source.raw_file.storage, source.raw_file.name))
                source.save()
            task = _new_task(batch, user)
            transaction.on_commit(lambda: _dispatch(batch.pk, task.pk))
            ActivityLog.objects.create(project=project, operation_type='rescreen_import_created',
                operation_detail={'batch_id': batch.pk, 'source_type': source_type}, created_by=user)
        batch.refresh_from_db()
        return batch
    except Exception:
        for storage, name in stored:
            storage.delete(name)
        raise


def retry_import(*, batch_id, user):
    batch = RescreenImportBatch.objects.select_related('project').get(pk=batch_id)
    _require_project(batch.project, user)
    preview = source_preview(batch.project) if batch.source_type == 'screening' else None
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=batch.project.owner_id)
        Project.objects.select_for_update().get(pk=batch.project_id)
        batch = RescreenImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status not in ('failed', 'cancelled'):
            raise RescreenError('not_retryable', '只有失败或已取消的批次可以重试。', status=409)
        if batch.source_type == 'bibliography' and not batch.files.exists():
            raise RescreenError('source_expired', '原始题录已超过保留期清理，请重新上传。', status=410)
        _require_idle(batch.project, exclude_batch=batch.pk)
        limits = ImportLimits.from_settings()
        _require_rate(user, limits)
        if RescreenImportBatch.objects.filter(created_by=user, status__in=RescreenImportBatch.ACTIVE_STATUSES).exclude(pk=batch.pk).count() >= limits.max_concurrent_per_user:
            raise RescreenError('import_concurrency_limit', '当前账户已有导入任务，请稍后再试。', status=409)
        if preview and preview['changed_count']:
            raise RescreenError('source_changed', '初筛来源有变化，请先检查差异。', status=409)
        batch.references.all().delete()  # Unpublished staging rows only.
        batch.corpus.refresh_from_db()
        batch.attempts = (batch.attempts + [{'error_code': batch.error_code, 'finished_at': str(batch.finished_at)}])[-10:]
        batch.base_revision = batch.corpus.revision
        batch.target_revision = batch.base_revision+1
        batch.status, batch.error_code, batch.error_message = 'uploaded', '', ''
        batch.limits_snapshot = limits.snapshot()
        batch.accepted_count = batch.rejected_count = batch.skipped_count = 0
        batch.finished_at = None
        if preview:
            batch.source_screening_run_id, batch.source_snapshot = preview['run_id'], preview
        batch.save()
        for source in batch.files.all():
            source.report = {}
            source.save(update_fields=['report'])
        task = _new_task(batch, user)
        transaction.on_commit(lambda: _dispatch(batch.pk, task.pk))
    return batch


def remove_references(*, project, user, ids, expected_revision):
    _require_project(project, user)
    with transaction.atomic():
        Project.objects.select_for_update().get(pk=project.pk)
        _require_idle(project)
        corpus = RescreenCorpus.objects.select_for_update().get(project=project)
        if corpus.revision != expected_revision:
            raise RescreenError('revision_conflict', '文献集已变化，请刷新后重试。', status=409)
        queryset = RescreenReference.objects.active().filter(project=project, pk__in=ids)
        count = queryset.count()
        if count != len(set(ids)):
            raise RescreenError('reference_not_found', '部分文献不存在或已移除。', status=404)
        queryset.update(removed_revision=corpus.revision+1)
        corpus.revision += 1
        corpus.active_reference_count -= count
        corpus.current_run = None
        corpus.save()
        ActivityLog.objects.create(project=project, operation_type='rescreen_references_removed',
            operation_detail={'ids': ids, 'revision': corpus.revision}, created_by=user)
        return {'removed': count, 'revision': corpus.revision, 'total': corpus.active_reference_count}
