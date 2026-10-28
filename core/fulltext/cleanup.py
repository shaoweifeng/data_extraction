"""Daily interrupted-worker recovery and conservative, reference-safe retention."""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from core.fulltext.models import FulltextAsset
from core.fulltext.services import asset_is_referenced
from core.models import Project, Task
from core.rescreening.models import FulltextLookupJob


def cleanup_fulltext(*, now=None):
    now = now or timezone.now()
    stale = now-timedelta(seconds=settings.QA_PDF_PROCESS_HARD_TIME_LIMIT*2)
    abandoned = FulltextAsset.objects.filter(Q(status__in=('validating', 'scanning', 'extracting'), updated_at__lt=stale)
        | Q(status='pending', updated_at__lt=now-timedelta(days=1)))
    recovered = 0
    for pk, project_id in abandoned.values_list('pk', 'project_id').iterator(chunk_size=100):
        with transaction.atomic():
            if not Project.objects.select_for_update().filter(pk=project_id).first():
                continue
            asset = abandoned.select_for_update().filter(pk=pk).first()
            if not asset:
                continue
            task_id = asset.processing_task_id
            asset.status, asset.extraction_status, asset.processing_token = 'failed', 'failed', None
            asset.error_code, asset.error_message = 'worker_interrupted', 'PDF 处理进程已中断，可重试。'
            asset.save(update_fields=['status', 'extraction_status', 'processing_token', 'error_code', 'error_message', 'updated_at'])
            _fail_task(task_id, now)
            recovered += 1
    lookup_stale = now-timedelta(seconds=settings.FULLTEXT_LOOKUP_HARD_TIME_LIMIT*2)
    jobs = FulltextLookupJob.objects.filter(Q(status__in=('running', 'cancelling'), updated_at__lt=lookup_stale)
        | Q(status='pending', updated_at__lt=now-timedelta(days=1)))
    recovered_jobs = 0
    for pk, project_id in jobs.values_list('pk', 'project_id').iterator(chunk_size=100):
        with transaction.atomic():
            if not Project.objects.select_for_update().filter(pk=project_id).first():
                continue
            job = jobs.select_for_update().filter(pk=pk).first()
            if not job:
                continue
            job.status, job.error_code, job.finished_at = 'failed', 'worker_interrupted', now
            job.save(update_fields=['status', 'error_code', 'finished_at', 'updated_at'])
            job.items.filter(status__in=('pending', 'processing')).update(status='failed', error_code='worker_interrupted')
            _fail_task(job.task_id, now)
            recovered_jobs += 1
    cutoff = now-timedelta(days=settings.QA_FULLTEXT_FAILED_RETENTION_DAYS)
    deleted = 0
    for pk, project_id in FulltextAsset.objects.filter(status__in=('failed', 'rejected'),
            updated_at__lt=cutoff).values_list('pk', 'project_id').iterator(chunk_size=100):
        with transaction.atomic():
            if not Project.objects.select_for_update().filter(pk=project_id).first():
                continue
            asset = FulltextAsset.objects.select_for_update().filter(pk=pk, status__in=('failed', 'rejected'), updated_at__lt=cutoff).first()
            if asset and not asset_is_referenced(asset):
                asset.delete()
                deleted += 1
    return dict(recovered_assets=recovered, recovered_lookups=recovered_jobs, deleted_assets=deleted)


def _fail_task(task_id, now):
    from core.workflow.services.lifecycle import transition_task, InvalidStateTransition
    from core.workflow.domain.statuses import TaskStatus
    task = Task.objects.filter(pk=task_id, status__in=(TaskStatus.PENDING, TaskStatus.QUEUING, TaskStatus.RUNNING)).first()
    if task:
        try:
            transition_task(task, TaskStatus.FAILED, expected_from={TaskStatus.PENDING, TaskStatus.QUEUING, TaskStatus.RUNNING},
                updates={'error_message': '全文任务进程已中断，请从对应批次重试。', 'completed_at': now})
        except InvalidStateTransition:
            pass
