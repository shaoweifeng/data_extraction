"""Serialized, persistent selection of a single bibliography input mode."""
from django.contrib.auth import get_user_model
from django.db import transaction
from core.models import Project
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus

MODES = ('screening', 'bibliography', 'pdf')


def claim_import_mode(project, mode, expected_revision=None):
    """Caller must hold owner/project locks; also protects direct API uploads."""
    if mode not in MODES:
        raise RescreenError('invalid_import_mode', '无效的导入模式。')
    corpus, _ = RescreenCorpus.objects.get_or_create(project=project)
    if expected_revision is not None and corpus.revision != expected_revision:
        raise RescreenError('input_changed', '复筛文献已变化，请刷新后重新操作。', status=409)
    if corpus.import_mode and corpus.import_mode != mode:
        raise RescreenError('import_mode_locked', '导入模式已固定，请先清空当前复筛文献再更换。', status=409)
    if not corpus.import_mode:
        corpus.import_mode = mode
        corpus.save(update_fields=['import_mode', 'updated_at'])
    return corpus


def select_import_mode(project, user, mode, expected_revision=None):
    from core.rescreening.services.imports import _require_project, _require_idle
    _require_project(project, user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        project = Project.objects.select_for_update().get(pk=project.pk)
        _require_idle(project)
        return claim_import_mode(project, mode, expected_revision).import_mode
