"""Task/asset terminal synchronization, with project serialization and generation guards."""
from django.db import transaction
from django.utils import timezone
from core.fulltext.models import FulltextAsset
from core.models import Project
from core.rescreening.models import FulltextLookupJob


def finish_task(task, *, cancelled=False, requested=False):
    if task.task_type not in ('rescreen_pdf', 'rescreen_fetch'):
        return
    with transaction.atomic():
        if not Project.objects.select_for_update().filter(pk=task.project_id).first():
            return
        if task.task_type == 'rescreen_pdf':
            FulltextAsset.objects.filter(project_id=task.project_id, processing_task_id=task.pk,
                status__in=('pending', 'validating', 'scanning', 'extracting')).update(
                    status='failed', extraction_status='failed', processing_token=None,
                    error_code='processing_cancelled' if cancelled else 'processing_failed',
                    error_message='全文处理已停止，可重试。' if cancelled else '全文处理未完成，可重试。',
                    updated_at=timezone.now())
        else:
            jobs = FulltextLookupJob.objects.filter(project_id=task.project_id, task_id=task.pk,
                status__in=FulltextLookupJob.ACTIVE_STATUSES)
            if requested:
                jobs.filter(status__in=('running', 'cancelling')).update(status='cancelling')
                jobs = jobs.exclude(status='cancelling')
            ids = list(jobs.values_list('pk', flat=True))
            jobs.update(status='cancelled' if cancelled else 'failed',
                error_code='lookup_cancelled' if cancelled else 'task_failed', finished_at=timezone.now())
            from core.rescreening.models import FulltextLookupItem
            FulltextLookupItem.objects.filter(job_id__in=ids, status__in=('pending', 'processing')).update(
                status='cancelled' if cancelled else 'failed',
                error_code='lookup_cancelled' if cancelled else 'task_failed')
