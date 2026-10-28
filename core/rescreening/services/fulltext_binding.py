"""Revisioned binding changes and PDF-only bibliography imports."""
from pathlib import Path
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from core.fulltext.errors import FulltextError
from core.fulltext.models import FulltextAsset
from core.models import ActivityLog, Project
from core.rescreening.models import (RescreenCorpus, RescreenImportBatch, RescreenReference,
    RescreenReferenceRawMetadata, RescreenFulltextBinding)
from core.rescreening.services.imports import _require_idle
from core.rescreening.services.persistence import ReferenceWriter
from core.rescreening.services.source import digest
from core.screening.services.import_limits import ImportLimits, validate_projected_reference_count
from core.services.access_policy import ProjectAccessPolicy


def import_pdf_references(project, user, assets):
    """Called under owner/project locks; assets do not invent a SCREEN_1 or QA row."""
    _require_idle(project)
    corpus, _ = RescreenCorpus.objects.get_or_create(project=project)
    existing = {ref.source_key: ref for ref in RescreenReference.objects.filter(
        project=project, source_key__in=[f'pdf:{asset.asset_key}' for asset in assets])}
    new = [asset for asset in assets if f'pdf:{asset.asset_key}' not in existing]
    if not new:
        return list(existing.values())
    limits = ImportLimits.from_settings()
    validate_projected_reference_count(corpus.active_reference_count, len(new), limits)
    batch = RescreenImportBatch.objects.create(project=project, corpus=corpus, source_type='pdf',
        base_revision=corpus.revision, target_revision=corpus.revision+1,
        idempotency_key=str(uuid4()), request_hash=digest([asset.sha256 for asset in new]),
        limits_snapshot=limits.snapshot(), created_by=user)
    writer = ReferenceWriter(batch, limits)
    for index, asset in enumerate(new, 1):
        record = dict(title=Path(asset.original_filename).stem, authors=[], keywords=[], source_position=index,
            source_type='pdf', _raw_metadata={'original_filename': asset.original_filename, 'sha256': asset.sha256})
        writer.add(record, source_key=f'pdf:{asset.asset_key}',
            source_snapshot={'source': 'pdf_upload', 'asset_key': str(asset.asset_key)})
    writer.flush()
    batch.status, batch.accepted_count, batch.finished_at = 'completed', len(new), timezone.now()
    batch.save()
    corpus.revision += 1
    corpus.active_reference_count += len(new)
    corpus.current_run = None
    corpus.save()
    refs = list(batch.references.all())
    by_key = {f'pdf:{asset.asset_key}': asset for asset in new}
    for ref in refs:
        binding = RescreenFulltextBinding.objects.create(reference=ref, asset=by_key[ref.source_key],
            input_version=ref.input_version, source='pdf_upload', confirmed_by=user,
            provenance={'source': 'manual_upload'})
        ref.current_binding = binding
        ref.save(update_fields=['current_binding'])
    return list(existing.values()) + refs


def _copy_raw_version(ref):
    old = ref.raw_metadata_versions.get(input_version=ref.input_version)
    values = {field: getattr(old, field) for field in (
        'raw_fields', 'source_format', 'raw_size_bytes', 'raw_hash', 'parser_version',
        'source_extracted_fields', 'source_field_definitions')}
    RescreenReferenceRawMetadata.objects.create(reference=ref, input_version=ref.input_version+1, **values)


def bind_fulltext(*, reference, asset, user, expected_version, expected_revision=None,
                  source='manual', provenance=None, lookup_job_id=None):
    ProjectAccessPolicy.require_project(user, reference.project_id)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=reference.project.owner_id)
        Project.objects.select_for_update().get(pk=reference.project_id)
        from core.rescreening.models import FulltextLookupJob
        if lookup_job_id:
            if not FulltextLookupJob.objects.filter(pk=lookup_job_id, project_id=reference.project_id,
                    status='running').exists():
                raise FulltextError('lookup_stopped', '全文查找任务已停止。', status=409)
        else:
            _require_idle(reference.project)
        ref = RescreenReference.objects.active().select_for_update().get(pk=reference.pk)
        corpus = RescreenCorpus.objects.select_for_update().get(pk=ref.corpus_id)
        if ref.input_version != expected_version or (expected_revision is not None and corpus.revision != expected_revision):
            raise FulltextError('input_changed', '文献输入已变化，请刷新后重新绑定。', status=409)
        if asset is not None:
            asset = FulltextAsset.objects.select_for_update().get(pk=asset.pk)
            if asset.project_id != ref.project_id:
                raise FulltextError('asset_project_mismatch', '不能绑定其他项目的全文。', status=403)
            if asset.status != 'ready':
                raise FulltextError('asset_not_ready', '请等待 PDF 校验与提取结束后再绑定。', status=409)
            if ref.current_binding_id and ref.current_binding.asset_id == asset.pk:
                return ref
        elif ref.current_binding_id is None:
            return ref
        _copy_raw_version(ref)
        ref.input_version += 1
        binding = None
        if asset is not None:
            binding = RescreenFulltextBinding.objects.create(reference=ref, asset=asset,
                input_version=ref.input_version, source=source, provenance=provenance or {}, confirmed_by=user)
        ref.current_binding, ref.current_review = binding, None
        ref.save(update_fields=['input_version', 'current_binding', 'current_review', 'updated_at'])
        corpus.revision += 1
        corpus.current_run = None
        corpus.save(update_fields=['revision', 'current_run', 'updated_at'])
        ActivityLog.objects.create(project=reference.project, operation_type='rescreen_fulltext_bound',
            operation_detail={'reference_id': ref.pk, 'asset_id': asset.pk if asset else None,
                'input_version': ref.input_version, 'revision': corpus.revision}, created_by=user)
        return ref
