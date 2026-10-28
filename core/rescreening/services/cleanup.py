"""Bounded retention cleanup sharing the existing daily import cleanup schedule."""
from datetime import timedelta
from pathlib import Path
import re
import shutil
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from core.models import Project
from core.rescreening.models import RescreenImportBatch
from core.screening.services.import_limits import ImportLimits


def cleanup_failed_imports(*, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=ImportLimits.from_settings().failed_retention_days)
    candidates = RescreenImportBatch.objects.filter(status__in=('failed', 'cancelled'), finished_at__lt=cutoff)
    files, size = 0, 0
    for batch_id, project_id in candidates.values_list('pk', 'project_id').iterator(chunk_size=500):
        with transaction.atomic():
            if not Project.objects.select_for_update().filter(pk=project_id).first():
                continue
            batch = candidates.filter(pk=batch_id).first()
            if batch is None:
                continue
            batch.references.all().delete()  # Never published; historical successful references are untouched.
            for source in batch.files.all():
                files += 1
                size += source.size_bytes
                source.delete()
    from django.conf import settings
    from core.rescreening.models import RescreenExport
    expired = RescreenExport.objects.filter(status__in=('completed', 'failed', 'cancelled'),
        finished_at__lt=now-timedelta(days=settings.RESCREEN_EXPORT_RETENTION_DAYS)).filter(Q(snapshot_size__gt=0) | ~Q(output=''))
    for job_id, project_id in expired.values_list('pk', 'project_id').iterator(chunk_size=500):
        with transaction.atomic():
            if not Project.objects.select_for_update().filter(pk=project_id).exists():
                continue
            job = expired.filter(pk=job_id).first()
            if job:
                files += bool(job.output)
                size += job.output_size
                from core.rescreening.services.exports import purge_files
                purge_files(job)
    from core.rescreening.storage import PrivateRescreenExportStorage
    root = Path(PrivateRescreenExportStorage().location) / '.tmp'
    if root.is_dir():
        cutoff = now.timestamp() - max(86400, settings.RESCREEN_EXPORT_HARD_TIME_LIMIT * 2)
        for folder in root.iterdir():
            match = re.fullmatch(r'job_(\d+)_[A-Za-z0-9_-]+', folder.name)
            if not match or folder.is_symlink() or not folder.is_dir() or folder.stat().st_mtime >= cutoff:
                continue
            # Never remove a live worker's spool, even when clocks/retention are unusual.
            if RescreenExport.objects.filter(pk=int(match[1]), status__in=('pending','running','cancelling')).exists():
                continue
            shutil.rmtree(folder)
    return {'purged_files': files, 'purged_bytes': size}
