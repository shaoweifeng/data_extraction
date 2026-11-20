"""Explicit corpus reset; QA snapshots/files and settled credit accounting survive."""
import logging
from pathlib import Path
import re
import shutil
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from core.models import ActivityLog, Project, ProjectStage, QAReference, Task
from core.fulltext.models import FulltextAsset
from core.fulltext.services import PROCESSING, asset_is_referenced
from core.models_billing import CreditReservation
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenExport, FulltextLookupJob
from core.rescreening.services.exports import fingerprint
from core.rescreening.services.imports import _require_idle
from core.rescreening.services.qa_identity import source_identities
from core.workflow.services.task_launcher import ACTIVE_EXECUTION_STATUSES


def _cleanup_workspaces(project_id, task_ids):
    root = Path(settings.BASE_DIR) / 'workspaces' / f'project_{project_id}'
    if not root.is_dir() or root.is_symlink():
        return
    for folder in root.iterdir():
        match = re.fullmatch(r'rescreen_[a-z]+_task_(\d+)_\d{8}_\d{6}', folder.name)
        if not match or int(match[1]) not in task_ids or folder.is_symlink() or not folder.is_dir():
            continue
        try:
            shutil.rmtree(folder)
        except OSError:
            logging.getLogger(__name__).exception('复筛任务工作目录清理失败 project_id=%s task_id=%s', project_id, match[1])


def reset_corpus(*, project, user, expected_revision, expected_mode, expected_fingerprint):
    from core.services.project_service import check_delete_permission
    try:
        check_delete_permission(project, user)
    except PermissionError as exc:
        raise RescreenError('permission_denied', str(exc), status=403) from exc
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        project = Project.objects.select_for_update().get(pk=project.pk)
        _require_idle(project)
        # Include PDF processing, exports, QA processing, and unsettled holds.
        if (Task.objects.filter(project=project, status__in=ACTIVE_EXECUTION_STATUSES).exists()
                or RescreenExport.objects.filter(project=project, status__in=('pending', 'running', 'cancelling')).exists()
                or FulltextAsset.objects.filter(project=project, status__in=PROCESSING).exists()):
            raise RescreenError('reset_busy', '项目仍有活动任务，请等待完成或停止后再清空。', status=409)
        tasks = Task.objects.filter(project=project, task_type__startswith='rescreen_')
        task_ids = set(tasks.values_list('pk', flat=True))
        if CreditReservation.objects.filter(task__in=tasks, status__in=('pending', 'reserved')).exists():
            raise RescreenError('settlement_pending', '复筛积分尚未结算或释放，不能清空。', status=409)
        corpus = RescreenCorpus.objects.select_for_update().filter(project=project).first()
        revision = corpus.revision if corpus else 0
        mode = corpus.import_mode if corpus else ''
        if revision != expected_revision or mode != expected_mode or fingerprint(project) != expected_fingerprint:
            raise RescreenError('reset_conflict', '复筛数据已变化，请刷新后重新确认清空。', status=409)
        retained = 0
        linked = QAReference.objects.filter(project=project, source_rescreen_reference__isnull=False).select_related(
            'rescreen_source_snapshot', 'shared_fulltext_asset', 'source_rescreen_reference__current_binding__asset',
            'source_rescreen_reference__import_file')
        for qa in linked.iterator(chunk_size=200):
            snapshot = getattr(qa, 'rescreen_source_snapshot', None)
            if not snapshot:
                raise RescreenError('qa_snapshot_missing', '质量评价来源快照不完整，不能安全清空，请联系管理员。', status=409)
            sha = snapshot.provenance.get('asset_sha256') or (qa.shared_fulltext_asset.sha256 if qa.shared_fulltext_asset_id else '')
            snapshot.provenance = {**snapshot.provenance, 'source_reset': True,
                'handoff_identities': source_identities(qa.source_rescreen_reference, bibliography=snapshot.bibliography, asset_sha=sha)}
            snapshot.save(update_fields=['provenance'])
            retained += 1
        # Project-owned jobs must go first; corpus-owned cross references are
        # collected together so Django RESTRICT is respected without raw SQL.
        RescreenExport.objects.filter(project=project).delete()
        FulltextLookupJob.objects.filter(project=project).delete()
        if corpus:
            corpus.delete()
        RescreenCorpus.objects.create(project=project, revision=revision + 1)
        ActivityLog.objects.filter(project=project).filter(
            Q(operation_type__startswith='rescreen_') | Q(operation_type__startswith='task_start_rescreen_')
            | Q(operation_detail__task_id__in=tasks.values('pk'))).delete()
        tasks.delete()  # Billing rows use SET_NULL; settled debits are not refunded/deleted.
        transaction.on_commit(lambda: _cleanup_workspaces(project.pk, task_ids))
        deleted_assets = 0
        for asset in FulltextAsset.objects.filter(project=project).iterator(chunk_size=200):
            if not asset_is_referenced(asset):
                asset.delete()  # File deletions are deferred until commit by existing signals.
                deleted_assets += 1
        stage = ProjectStage.objects.filter(project=project, stage_key='SCREEN_2').first()
        if stage:
            stage.steps.update(status='pending', started_at=None, completed_at=None, metadata={})
            ProjectStage.objects.filter(pk=stage.pk).update(status='pending', completed_at=None)
        return {'retained_qa': retained, 'deleted_assets': deleted_assets, 'revision': revision + 1}
