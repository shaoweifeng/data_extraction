"""Immutable, bounded export snapshots; only successful current final exports complete step 6."""
import hashlib
import json
from datetime import timedelta
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

from core.bibliography import BIBLIOGRAPHY_FIELDS, bibliography_snapshot
from core.models import ActivityLog, Project, ProjectStage, Task
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenExport, RescreenExportItem, RescreenReferenceRawMetadata, RescreenModelResult
from core.rescreening.services.ai_runs import _permission
from core.rescreening.services.imports import _require_idle
from core.rescreening.services.source import digest
from core.rescreening.services.workspace import configuration, reference_query
from core.services.storage_quota_service import enforce_user_storage_quota
from core.workflow.services.task_launcher import create_step_task, dispatch_step_task
from core.rescreening.services.export_rendering import write_export

FORMATS = {'xlsx', 'xml', 'ris', 'metadata', 'pdf'}
FINAL = ('included', 'excluded', 'not_retrieved')


def fingerprint(project):
    corpus = RescreenCorpus.objects.filter(project=project).first()
    from core.rescreening.models import RescreenReviewEvent
    # Append-only event ID and monotonic input/run revisions avoid reading 100k rows into Python on each poll.
    state = reference_query(project).aggregate(total=Count('pk'), last=Max('pk'), inputs=Sum('input_version'),
        last_suggestion=Max('suggestion_id'), suggestion_revisions=Sum('suggestion_revision'),
        asset_updated=Max('current_binding__asset__updated_at'))
    event = RescreenReviewEvent.objects.filter(review__reference__project=project).aggregate(last=Max('pk'))['last']
    return digest({'revision': corpus.revision if corpus else 0, 'criteria': configuration(project)['criteria_revision_id'],
                   'state': state, 'last_review_event': event})


def current_final_export(project, current_fingerprint=None):
    return RescreenExport.objects.filter(project=project, status='completed', mode='final',
        fingerprint=current_fingerprint or fingerprint(project)).exclude(format__in=('pdf', 'metadata')).order_by('-pk').first()


def snapshot_rows(project, scope='all', *, offset=0, limit=None):
    """Batch joins of cold metadata/model results, never N+1 or a whole-corpus list."""
    queryset = reference_query(project)
    if scope == 'pending':
        from django.db.models import Q
        queryset = queryset.filter(Q(review_valid=False) | Q(current_review__decision='pending'))
    elif scope != 'all':
        queryset = queryset.filter(review_valid=True, current_review__decision=scope)
    config = configuration(project)
    queryset = queryset.select_related('current_review', 'current_binding__asset').order_by('pk')
    queryset = queryset[offset:offset+limit] if limit is not None else queryset[offset:]
    iterator = queryset.iterator(chunk_size=500)
    while rows := list(islice(iterator, 500)):
        from django.db.models import Q
        versions = Q(pk__in=[])
        for r in rows:
            versions |= Q(reference_id=r.pk, input_version=r.input_version)
        raw = {(r.reference_id, r.input_version): r for r in RescreenReferenceRawMetadata.objects.filter(versions)}
        models = {}
        for result in RescreenModelResult.objects.filter(item_id__in=[r.suggestion_id for r in rows if r.suggestion_id]).values(
                'item_id', 'model_id', 'status', 'decision', 'reason', 'evidence', 'criteria_results'):
            models.setdefault(result.pop('item_id'), []).append(result)
        for ref in rows:
            source = raw.get((ref.pk, ref.input_version))
            if source is None:
                raise RescreenError('raw_metadata_missing', '文献缺少当前原始元数据版本，不能静默导出不完整结果。', status=409)
            review = ref.current_review
            asset = ref.current_binding.asset if ref.current_binding_id else None
            yield ref, {'schema_version': 'metaflow-rescreen-export-v1', 'reference_id': ref.pk, 'input_version': ref.input_version,
                'bibliography': bibliography_snapshot(ref),
                'criteria_revision_id': config['criteria_revision_id'], 'criteria': config['criteria'],
                'fulltext': {'status': asset.status if asset else 'missing', 'asset_id': asset.pk if asset else None,
                    'sha256': asset.sha256 if asset else '', 'page_count': asset.page_count if asset else None,
                    'source': ref.current_binding.source if ref.current_binding_id else ''},
                'field_mapping': {'bibliography': list(BIBLIOGRAPHY_FIELDS), 'vendor_fields': 'raw_metadata.raw_fields',
                    'extracted_fields': 'raw_metadata.source_extracted_fields', 'field_definitions': 'raw_metadata.source_field_definitions'},
                'raw_metadata': {key: getattr(source, key) for key in ('raw_fields', 'source_format', 'raw_hash',
                    'parser_version', 'source_extracted_fields', 'source_field_definitions')},
                'provenance': ref.source_snapshot,
                'decision': review.decision if review and ref.review_valid else 'pending',
                'needs_reconfirmation': bool(review and not ref.review_valid),
                'review': {'id': review.pk, 'version': review.version, 'decision': review.decision,
                    'exclusion_reason': review.exclusion_reason, 'note': review.note,
                    'reviewed_by_id': review.reviewed_by_id, 'updated_at': review.updated_at.isoformat()} if review else None,
                'ai_suggestion': ref.suggestion_decision, 'model_results': models.get(ref.suggestion_id, [])}


def start_export(*, project, user, format, scope, mode, idempotency_key, expected_fingerprint, offset=0, limit=None):
    _permission(project, user)
    if (any(not isinstance(value, str) for value in (format, scope, mode))
            or format not in FORMATS or scope not in ('all', 'pending', *FINAL) or mode not in ('final', 'draft')):
        raise RescreenError('invalid_export', '无效的导出格式、范围或模式。')
    if (type(offset) is not int or not 0 <= offset <= 100000 or
            (limit is not None and (type(limit) is not int or not 1 <= limit <= 100000))):
        raise RescreenError('invalid_selection', '分批起点必须非负，条数为 1～100000 的整数。')
    request_hash = digest([format, scope, mode, expected_fingerprint, offset, limit])
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        Project.objects.select_for_update().get(pk=project.pk)
        old = RescreenExport.objects.filter(project=project, idempotency_key=idempotency_key).first()
        if old:
            if old.request_hash != request_hash:
                raise RescreenError('idempotency_conflict', '此幂等键已用于不同导出。', status=409)
            return old
        _require_idle(project)
        if RescreenExport.objects.filter(project=project, status__in=('pending', 'running', 'cancelling')).exists():
            raise RescreenError('export_busy', '已有导出任务，请等待完成或停止。', status=409)
        if RescreenExport.objects.filter(created_by=user, created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= settings.RESCREEN_EXPORT_RATE_PER_MINUTE:
            raise RescreenError('export_rate_limited', '导出过于频繁，请稍后再试。', status=429)
        actual = fingerprint(project)
        if actual != expected_fingerprint:
            raise RescreenError('export_source_changed', '审核结果已变化，请刷新统计后导出。', status=409)
        refs = reference_query(project)
        if not refs.exists():
            raise RescreenError('no_references', '没有可导出的文献。')
        if mode == 'final' and refs.exclude(review_valid=True, current_review__decision__in=FINAL).exists():
            raise RescreenError('review_required', '仍有待审核或待重新确认的文献，只能导出草稿。', status=409)
        corpus = RescreenCorpus.objects.get(project=project)
        job = RescreenExport.objects.create(project=project, format=format, scope=scope, mode=mode,
            idempotency_key=idempotency_key, request_hash=request_hash, fingerprint=actual,
            source_revision=corpus.revision, created_by=user,
            configuration_snapshot={**configuration(project), 'selection': {'offset': offset, 'limit': limit}})
        buffer, pdf_bytes = [], 0
        for ref, payload in snapshot_rows(project, scope, offset=offset, limit=limit):
            if scope != 'all' and payload['decision'] != scope:
                continue
            asset = ref.current_binding.asset if ref.current_binding_id and ref.current_binding.asset.status == 'ready' else None
            job.snapshot_size += len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            if job.snapshot_size > settings.RESCREEN_EXPORT_MAX_BYTES:
                raise RescreenError('export_too_large', '导出快照超过大小上限，请缩小范围。', status=413)
            if format == 'pdf' and asset:
                pdf_bytes += asset.size_bytes
                if pdf_bytes > settings.RESCREEN_EXPORT_MAX_BYTES:
                    raise RescreenError('export_too_large', 'PDF 包超过导出大小上限，请按结果范围分批。', status=413)
            buffer.append(RescreenExportItem(export=job, reference_id_snapshot=ref.pk, payload=payload, asset=asset))
            job.total_count += 1
            if len(buffer) >= 500:
                RescreenExportItem.objects.bulk_create(buffer)
                buffer.clear()
        if buffer:
            RescreenExportItem.objects.bulk_create(buffer)
        if not job.total_count:
            raise RescreenError('empty_export', '此范围没有可导出的文献。')
        enforce_user_storage_quota(project.owner, job.snapshot_size + (pdf_bytes if format == 'pdf' else 0))
        ProjectStage.objects.get_or_create(project=project, stage_key='SCREEN_2', defaults={'name': '文献复筛', 'order': 30})
        from core.step_config import get_step_config
        task = create_step_task(project.pk, 'rescreen_export', user.pk, {**get_step_config('rescreen_export'), 'rescreen_export_id': job.pk})
        job.task, job.download_name = task, f'rescreen_{scope}_{mode}_{job.pk}.{"jsonl" if format == "metadata" else "zip" if format == "pdf" else format}'
        if offset or limit is not None:
            stem, suffix = job.download_name.rsplit('.', 1)
            job.download_name = f'{stem}_part_{offset+1}_{offset+job.total_count}.{suffix}'
        job.save()
        transaction.on_commit(lambda: _dispatch(job.pk, task.pk))
        return job


def _dispatch(job_id, task_id):
    try:
        dispatch_step_task(Task.objects.get(pk=task_id), 'rescreen_export')
    except Exception:
        RescreenExport.objects.filter(pk=job_id, status='pending').update(status='failed', error_code='dispatch_failed', finished_at=timezone.now())


def finish_task(task, *, cancelled=False):
    if task.task_type == 'rescreen_export':
        RescreenExport.objects.filter(task=task, status__in=('pending', 'running', 'cancelling')).update(
            status='cancelled' if cancelled else 'failed', error_code='cancelled' if cancelled else 'task_failed', finished_at=timezone.now())


def purge_files(job):
    """Caller holds the project lock. Preserve the durable receipt, free bodies after commit."""
    if job.status not in ('completed', 'failed', 'cancelled'):
        raise RescreenError('export_busy', '导出仍在运行，不能清理。', status=409)
    if job.output:
        storage, name = job.output.storage, job.output.name
        transaction.on_commit(lambda: storage.delete(name))
    job.items.all().delete()
    job.output, job.output_size, job.snapshot_size = '', 0, 0
    job.save(update_fields=['output', 'output_size', 'snapshot_size'])


def skip_export(*, project, user, idempotency_key, expected_fingerprint):
    _permission(project, user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        Project.objects.select_for_update().get(pk=project.pk)
        old = RescreenExport.objects.filter(project=project, idempotency_key=idempotency_key).first()
        request_hash = digest(['skip', expected_fingerprint])
        if old:
            if old.request_hash != request_hash:
                raise RescreenError('idempotency_conflict', '幂等键已用于不同请求。', status=409)
            return old
        _require_idle(project)
        if fingerprint(project) != expected_fingerprint:
            raise RescreenError('export_source_changed', '来源已变化，请刷新后再确认跳过。', status=409)
        refs = reference_query(project)
        if not refs.exists() or refs.exclude(review_valid=True, current_review__decision__in=FINAL).exists():
            raise RescreenError('review_required', '全部文献须最终确认后才可跳过导出。', status=409)
        # Repeated confirmation for the same state reuses its receipt, regardless of a new browser key.
        old = RescreenExport.objects.filter(project=project, format='skip', fingerprint=expected_fingerprint).first()
        if old:
            return old
        corpus = RescreenCorpus.objects.get(project=project)
        job = RescreenExport.objects.create(project=project, status='completed', mode='final', scope='all', format='skip',
            fingerprint=expected_fingerprint, request_hash=request_hash, idempotency_key=idempotency_key,
            source_revision=corpus.revision, created_by=user, finished_at=timezone.now(), configuration_snapshot=configuration(project))
        ProjectStage.objects.filter(project=project, stage_key='SCREEN_2').update(status='completed', completed_at=job.finished_at)
        ActivityLog.objects.create(project=project, created_by=user, operation_type='rescreen_export_skipped',
                                   operation_detail={'export_id': job.pk, 'fingerprint': expected_fingerprint})
        return job




def process_export(job_id, *, expected_task_id=None, check_stop=lambda: False, progress=lambda current,total: None):
    with transaction.atomic():
        job = RescreenExport.objects.select_for_update().select_related('project__owner').get(pk=job_id)
        if expected_task_id is not None and job.task_id != expected_task_id:
            raise RescreenError('stale_export_task', '导出任务已变化。', status=409)
        if job.status == 'completed':
            return job
        if job.status != 'pending':
            raise RescreenError('export_claimed', '导出已领取或已结束。', status=409)
        job.status = 'running'
        job.save(update_fields=['status'])
    stored = None
    try:
        from core.rescreening.storage import PrivateRescreenExportStorage
        temporary_root = Path(PrivateRescreenExportStorage().location) / '.tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=f'job_{job.pk}_', dir=temporary_root) as folder:
            path = Path(folder) / job.download_name
            last_reported = -1
            def tick(index):
                nonlocal last_reported
                if check_stop() or not RescreenExport.objects.filter(pk=job_id, status='running').exists():
                    raise RescreenError('export_cancelled', '导出已停止。', status=409)
                if path.exists() and path.stat().st_size > settings.RESCREEN_EXPORT_MAX_BYTES:
                    raise RescreenError('export_too_large', '导出超过文件大小上限。', status=413)
                if (index % 100 == 0 or index == job.total_count) and index != last_reported:
                    last_reported = index
                    workbook = getattr(job, '_export_workbook', None)
                    temporary_bytes = sum(Path(sheet._writer.out).stat().st_size for sheet in workbook.worksheets
                        if getattr(sheet, '_writer', None) and Path(sheet._writer.out).exists()) if workbook else 0
                    if temporary_bytes > settings.RESCREEN_EXPORT_MAX_BYTES * 4:
                        raise RescreenError('export_too_large', 'Excel 临时数据超过安全上限，请缩小范围。', status=413)
                    RescreenExport.objects.filter(pk=job_id, status='running').update(processed_count=index)
                    progress(index, job.total_count)
            write_export(job, path, tick)
            tick(job.total_count)
            size = path.stat().st_size
            if size > settings.RESCREEN_EXPORT_MAX_BYTES:
                raise RescreenError('export_too_large', '导出超过文件大小上限。', status=413)
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=job.project.owner_id)
                Project.objects.select_for_update().get(pk=job.project_id)
                current = RescreenExport.objects.select_for_update().get(pk=job_id)
                if current.status != 'running' or check_stop():
                    raise RescreenError('export_cancelled', '导出已停止。', status=409)
                enforce_user_storage_quota(job.project.owner, size)
                with path.open('rb') as source:
                    job.output.save(job.download_name, File(source), save=False)
                stored = (job.output.storage, job.output.name)
                job.status, job.output_size, job.finished_at = 'completed', size, timezone.now()
                job.processed_count = job.total_count
                job.save()
                if job.mode == 'final' and job.format not in ('pdf', 'metadata') and fingerprint(job.project) == job.fingerprint:
                    ProjectStage.objects.filter(project=job.project, stage_key='SCREEN_2').update(status='completed', completed_at=job.finished_at)
                ActivityLog.objects.create(project=job.project, created_by=job.created_by, operation_type='rescreen_export_completed',
                    operation_detail={'export_id': job.pk, 'format': job.format, 'scope': job.scope, 'mode': job.mode})
        return job
    except Exception as exc:
        if stored:
            stored[0].delete(stored[1])
        RescreenExport.objects.filter(pk=job_id).exclude(status='completed').update(
            status='cancelled' if getattr(exc, 'code', '') == 'export_cancelled' else 'failed',
            error_code=getattr(exc, 'code', 'export_failed'), finished_at=timezone.now())
        raise
    finally:
        # openpyxl write-only sheets allocate temporary XML outside our output directory.
        # Close generators and remove those bodies even when cancellation/size/quota checks fail.
        workbook = getattr(job, '_export_workbook', None)
        if workbook:
            for sheet in workbook.worksheets:
                if not sheet.closed:
                    sheet.close()
                writer = getattr(sheet, '_writer', None)
                if writer and Path(writer.out).exists():
                    writer.cleanup()
            workbook.close()
