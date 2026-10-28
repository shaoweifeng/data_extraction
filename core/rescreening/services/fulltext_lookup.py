"""Durable bounded lookup jobs; external identifiers never bypass PDF validation."""
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from core.bibliography import bibliography_snapshot
from core.fulltext.errors import FulltextError
from core.models import Project, ProjectStage
from core.rescreening.models import (FulltextLookupJob, FulltextLookupItem, FulltextCandidate,
    RescreenReference, RescreenCorpus)
from core.rescreening.services.imports import _require_idle, _require_project
from core.rescreening.services.source import digest
from core.workflow.services.task_launcher import create_step_task, dispatch_step_task


def start_lookup(*, project, user, ids, mode, idempotency_key, download=False, auto_bind=False, candidate_id=None, manual_url=''):
    _require_project(project, user)
    from core.operations.services import assert_accepting_new_work
    assert_accepting_new_work()
    if mode not in ('local', 'online', 'download', 'manual'):
        raise FulltextError('invalid_mode', '未知全文查找方式。')
    if mode in ('online', 'download') and not settings.FULLTEXT_LOOKUP_ENABLED:
        raise FulltextError('lookup_disabled', '外部全文查找尚未启用，可先上传 PDF 或使用本地匹配。', status=409)
    if not ids or len(ids) > settings.FULLTEXT_LOOKUP_MAX_REFERENCES or len(ids) != len(set(ids)):
        raise FulltextError('invalid_reference_count', '查找文献数量为空、重复或超过单次上限。')
    if mode == 'manual':
        from core.fulltext.network import checked_url
        manual_url = checked_url(manual_url)
        if len(ids) != 1:
            raise FulltextError('invalid_reference_count', '手工外链必须指定一篇文献。')
    request_hash = digest([ids, mode, download, auto_bind, candidate_id, manual_url])
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        Project.objects.select_for_update().get(pk=project.pk)
        old = FulltextLookupJob.objects.filter(project=project, idempotency_key=idempotency_key).first()
        if old:
            if old.request_hash != request_hash:
                raise FulltextError('idempotency_conflict', '幂等键已用于不同的查找请求。', status=409)
            return old
        _require_idle(project)
        if FulltextLookupJob.objects.filter(project__owner=project.owner,
                status__in=FulltextLookupJob.ACTIVE_STATUSES).exists():
            raise FulltextError('lookup_busy', '账户已有全文查找任务，请稍后再试。', status=409)
        if FulltextLookupJob.objects.filter(created_by=user,
                created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= settings.FULLTEXT_LOOKUP_RATE_PER_MINUTE:
            raise FulltextError('lookup_rate_limited', '全文查找任务创建过于频繁。', status=429)
        refs = list(RescreenReference.objects.active().filter(project=project, pk__in=ids).order_by('pk'))
        if len(refs) != len(ids):
            raise FulltextError('reference_not_found', '部分文献不存在或已移除。', status=404)
        candidate = None
        if mode == 'download':
            if len(refs) != 1 or not candidate_id:
                raise FulltextError('candidate_required', '下载候选必须指定单篇文献和候选 ID。')
            candidate = FulltextCandidate.objects.filter(pk=candidate_id, item__job__project=project,
                item__reference=refs[0]).first()
            if not candidate or not candidate.url:
                raise FulltextError('candidate_not_found', '可下载候选不存在。', status=404)
            if candidate.item.input_version != refs[0].input_version:
                raise FulltextError('input_changed', '候选对应的文献已变化，请重新查找。', status=409)
        midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        today_bytes = FulltextLookupJob.objects.filter(project__owner=project.owner,
            created_at__gte=midnight).aggregate(total=Sum('received_bytes'))['total'] or 0
        budget = min(settings.FULLTEXT_LOOKUP_MAX_BYTES, settings.FULLTEXT_LOOKUP_DAILY_BYTES-today_bytes)
        if mode in ('online', 'download') and budget <= 0:
            raise FulltextError('daily_download_limit', '今日全文网络下载预算已用完。', status=429)
        corpus = RescreenCorpus.objects.get(project=project)
        job = FulltextLookupJob.objects.create(project=project, created_by=user, mode=mode,
            idempotency_key=idempotency_key, request_hash=request_hash, input_revision=corpus.revision,
            settings_snapshot={'max_requests': settings.FULLTEXT_LOOKUP_MAX_REQUESTS,
                'max_bytes': max(0, budget), 'timeout': settings.FULLTEXT_LOOKUP_TIMEOUT,
                'total_seconds': settings.FULLTEXT_LOOKUP_DOWNLOAD_SECONDS,
                'max_redirects': settings.FULLTEXT_LOOKUP_MAX_REDIRECTS,
                'download': download or mode == 'download', 'auto_bind': auto_bind,
                'max_candidates': settings.FULLTEXT_LOOKUP_MAX_CANDIDATES,
                'max_json_bytes': settings.FULLTEXT_LOOKUP_MAX_JSON_BYTES,
                'allowed_licenses': list(settings.FULLTEXT_ALLOWED_LICENSES)})
        FulltextLookupItem.objects.bulk_create([FulltextLookupItem(job=job, reference=ref,
            input_version=ref.input_version, bibliography_snapshot=bibliography_snapshot(ref), selected_candidate=candidate)
            for ref in refs])
        if mode == 'download':
            item = job.items.get()
            clone = FulltextCandidate.objects.create(item=item, asset=candidate.asset,
                source=candidate.source, url=candidate.url, license=candidate.license,
                title=candidate.title, doi=candidate.doi, pmid=candidate.pmid, confidence=candidate.confidence,
                provenance={**candidate.provenance, 'origin_candidate_id': candidate.pk})
            item.selected_candidate = clone
            item.save(update_fields=['selected_candidate'])
        if mode == 'manual':
            item = job.items.get()
            FulltextCandidate.objects.create(item=item, source='manual_link', url=manual_url,
                title=refs[0].title, provenance={'source': 'user_supplied_link'})
            item.status = 'found'
            item.save(update_fields=['status'])
            job.status, job.processed_count, job.finished_at = 'completed', 1, timezone.now()
            job.save(update_fields=['status', 'processed_count', 'finished_at', 'updated_at'])
            return job
        from core.step_config import get_step_config
        ProjectStage.objects.get_or_create(project=project, stage_key='SCREEN_2', defaults={'name': '文献复筛', 'order': 30})
        task = create_step_task(project.pk, 'rescreen_fetch', user.pk,
            dict(get_step_config('rescreen_fetch'), fulltext_lookup_job_id=job.pk))
        job.task = task
        job.save(update_fields=['task'])
        transaction.on_commit(lambda: _dispatch(job.pk, task.pk))
    return job


def _dispatch(job_id, task_id):
    from core.models import Task
    try:
        dispatch_step_task(Task.objects.get(pk=task_id), 'rescreen_fetch')
    except Exception:
        FulltextLookupJob.objects.filter(pk=job_id, task_id=task_id, status='pending').update(
            status='failed', error_code='dispatch_failed', finished_at=timezone.now())


def confirm_candidate(*, candidate, user, expected_version):
    from core.rescreening.services.fulltext_binding import bind_fulltext
    if not candidate.asset_id:
        raise FulltextError('download_required', '请先下载并完成 PDF 校验，再确认绑定。', status=409)
    if candidate.item.input_version != expected_version:
        raise FulltextError('input_changed', '候选对应的文献版本已变化，请重新查找。', status=409)
    ref = bind_fulltext(reference=candidate.item.reference, asset=candidate.asset, user=user,
        expected_version=expected_version, source=candidate.source,
        provenance={'candidate_id': candidate.pk, 'license': candidate.license, 'url': candidate.url})
    candidate.status = 'bound'
    candidate.save(update_fields=['status'])
    return ref
