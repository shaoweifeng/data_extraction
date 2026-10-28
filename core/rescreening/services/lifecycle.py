"""Task terminal synchronization, serialized with import publication."""
from django.db import transaction
from django.utils import timezone
from core.models import Project
from core.rescreening.models import RescreenImportBatch


def finish_unpublished_batch(batch_id, *, cancelled=False, requested=False, task_id=None):
    project_id = RescreenImportBatch.objects.filter(pk=batch_id).values_list('project_id', flat=True).first()
    if project_id is None:
        return
    with transaction.atomic():
        Project.objects.select_for_update().get(pk=project_id)
        batches = RescreenImportBatch.objects.filter(pk=batch_id, status__in=RescreenImportBatch.ACTIVE_STATUSES)
        if task_id is not None:
            batches = batches.filter(task_id=task_id)
        if requested:
            # A running worker must acknowledge cancellation before a retry can reuse this batch.
            batches.filter(status__in=('importing', 'cancelling')).update(status='cancelling')
            batches = batches.exclude(status='cancelling')
        batches.update(
            status='cancelled' if cancelled else 'failed',
            error_code='import_cancelled' if cancelled else 'task_failed',
            error_message='导入任务已停止。' if cancelled else '导入任务未完成，请重试。',
            finished_at=timezone.now(),
        )
