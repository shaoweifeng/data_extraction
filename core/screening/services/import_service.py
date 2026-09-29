"""Transactional state machine for screening reference imports."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.artifacts.services import reset_downstream_on_input_delete
from core.artifacts.types import ArtifactType
from core.models import ActivityLog, DataFile, ManualReview, Project, ProjectStage, StageStep, Task
from core.screening.models import (
    ReferenceImportBatch,
    ReferenceImportFile,
    ReferenceImportIssue,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningReferenceRawMetadata,
)
from core.screening.services.import_errors import ScreeningImportError
from core.screening.services.import_limits import ImportLimits
from core.screening.services.import_validation import validate_uploads
from core.workflow.domain.statuses import StageStepStatus
from core.workflow.services.lifecycle import transition_step
from core.workflow.services.task_launcher import (
    ACTIVE_EXECUTION_STATUSES,
    create_step_task,
    dispatch_step_task,
)


logger = logging.getLogger(__name__)

ACTIVE_BATCH_STATUSES = (
    ReferenceImportBatch.Status.UPLOADED,
    ReferenceImportBatch.Status.VALIDATING,
    ReferenceImportBatch.Status.IMPORTING,
    ReferenceImportBatch.Status.READY,
    ReferenceImportBatch.Status.PUBLISHING,
)

SCREENING_MUTATING_TASK_TYPES = ('parse', 'dedup', 'ai_screen', 'export')


def _invalidate_downstream(project, *, removed_source_file_id=None) -> None:
    """Invalidate legacy file-backed consumers after a corpus revision changes."""
    ScreeningCorpus.objects.filter(project=project).update(last_dedup_run=None)
    if removed_source_file_id is not None:
        DataFile.objects.filter(
            project=project,
            step__step_key='parse',
            data_category='intermediate',
            metadata__source_file_id=removed_source_file_id,
        ).delete()

    DataFile.objects.filter(
        project=project,
        metadata__artifact_type__in=(
            ArtifactType.SCREENING_DEDUP_REPORT_JSON,
            ArtifactType.SCREENING_EXPORT_XLSX,
            ArtifactType.SCREENING_EXPORT_RIS,
            ArtifactType.SCREENING_EXPORT_XML,
        ),
    ).delete()
    ManualReview.objects.filter(project=project).delete()

    for step in StageStep.objects.filter(
        stage__project=project,
        step_key__in=('dedup', 'ai_screen', 'review', 'export'),
    ):
        if step.status != StageStepStatus.PENDING:
            transition_step(
                step,
                StageStepStatus.PENDING,
                updates={'metadata': {}, 'started_at': None, 'completed_at': None},
            )


def _screening_parse_location(project):
    stage = ProjectStage.objects.filter(project=project, stage_key='SCREEN_1').first()
    step = StageStep.objects.filter(stage=stage, step_key='parse').first() if stage else None
    return stage, step


def _dispatch_batch_task(batch_id: int, task_id: int, errors: list) -> None:
    from core.models import Task

    try:
        task = Task.objects.get(pk=task_id)
        dispatch_step_task(task, 'parse')
    except Exception as exc:
        ReferenceImportBatch.objects.filter(pk=batch_id).update(
            status=ReferenceImportBatch.Status.FAILED,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        errors.append(exc)
        logger.exception('文献导入任务派发失败 batch_id=%s', batch_id)


def create_add_import(*, project: Project, user, uploaded_files):
    limits = ImportLimits.from_settings()
    validated = validate_uploads(uploaded_files, limits)
    saved_private_files = []
    dispatch_errors = []

    try:
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            project = Project.objects.select_for_update().get(pk=project.pk)
            corpus, _ = ScreeningCorpus.objects.select_for_update().get_or_create(project=project)

            if Task.objects.filter(
                project=project,
                task_type__in=SCREENING_MUTATING_TASK_TYPES,
                status__in=ACTIVE_EXECUTION_STATUSES,
            ).exists():
                raise ScreeningImportError(
                    'screening_task_active', '该项目有筛选流程任务正在运行，请结束后再上传。',
                    http_status=409,
                )

            active_for_project = ReferenceImportBatch.objects.filter(
                project=project, status__in=ACTIVE_BATCH_STATUSES,
            ).count()
            if active_for_project >= limits.max_concurrent_per_project:
                raise ScreeningImportError(
                    'import_already_running', '该项目已有导入操作正在进行。', http_status=409,
                )
            active_for_user = ReferenceImportBatch.objects.filter(
                created_by=user, status__in=ACTIVE_BATCH_STATUSES,
            ).count()
            if active_for_user >= limits.max_concurrent_per_user:
                raise ScreeningImportError(
                    'user_import_limit', '当前账户已有导入操作正在进行。', http_status=409,
                )

            window_start = timezone.now() - timedelta(seconds=limits.rate_limit_window_seconds)
            recent_count = ReferenceImportBatch.objects.filter(
                created_by=user, created_at__gte=window_start,
            ).count()
            if recent_count >= limits.rate_limit_requests:
                raise ScreeningImportError(
                    'import_rate_limited', '索引上传过于频繁，请稍后再试。', http_status=429,
                    details={'retry_after_seconds': limits.rate_limit_window_seconds},
                )

            active_hashes = set(
                ReferenceImportFile.objects.filter(
                    import_batch__corpus=corpus,
                    import_batch__status=ReferenceImportBatch.Status.COMPLETED,
                    sha256__in=[item.sha256 for item in validated],
                ).filter(
                    Q(removed_revision__isnull=True) | Q(removed_revision__gt=corpus.revision)
                ).values_list('sha256', flat=True)
            )
            if active_hashes:
                duplicates = [item.original_filename for item in validated if item.sha256 in active_hashes]
                raise ScreeningImportError(
                    'duplicate_file', '项目中已存在内容相同的有效索引文件。', http_status=409,
                    details={'filenames': duplicates},
                )

            batch = ReferenceImportBatch.objects.create(
                project=project,
                corpus=corpus,
                created_by=user,
                operation=ReferenceImportBatch.Operation.ADD,
                status=ReferenceImportBatch.Status.UPLOADED,
                base_revision=corpus.revision,
                target_revision=corpus.revision + 1,
                file_count=len(validated),
                total_bytes=sum(item.size for item in validated),
                config_snapshot=limits.snapshot(),
                parser_version='v1.5.0',
            )
            stage, step = _screening_parse_location(project)
            source_file_ids = []
            for item in validated:
                data_file = DataFile.objects.create(
                    project=project,
                    stage=stage,
                    step=step,
                    filename=item.original_filename,
                    file='',
                    file_size=item.size,
                    file_type=item.source_format,
                    data_category='input',
                    source='upload',
                    description='文献索引原始文件（私有存储）',
                    metadata={
                        'artifact_type': ArtifactType.SCREENING_SOURCE_REFERENCE_FILE,
                        'import_batch_id': batch.id,
                        'sha256': item.sha256,
                    },
                    created_by=user,
                )
                import_file = ReferenceImportFile(
                    import_batch=batch,
                    source_file=data_file,
                    original_filename=item.original_filename,
                    sha256=item.sha256,
                    source_format=item.source_format,
                    introduced_revision=batch.target_revision,
                )
                import_file.raw_file.save(item.original_filename, item.uploaded_file, save=False)
                saved_private_files.append((import_file.raw_file.storage, import_file.raw_file.name))
                import_file.save()
                source_file_ids.append(data_file.id)

            task = create_step_task(
                project.id,
                'parse',
                user.id,
                {'import_batch_id': batch.id, 'file_ids': source_file_ids},
            )
            batch.task = task
            batch.save(update_fields=['task', 'updated_at'])
            ActivityLog.objects.create(
                project=project,
                operation_type='screening_import_create',
                operation_detail={
                    'batch_id': batch.id,
                    'file_count': batch.file_count,
                    'total_bytes': batch.total_bytes,
                    'target_revision': batch.target_revision,
                },
                created_by=user,
            )
            transaction.on_commit(
                lambda: _dispatch_batch_task(batch.id, task.id, dispatch_errors)
            )
    except Exception:
        for storage, name in saved_private_files:
            try:
                storage.delete(name)
            except Exception:
                logger.exception('清理回滚后的私有索引文件失败: %s', name)
        raise

    batch.refresh_from_db()
    task.refresh_from_db()
    if dispatch_errors:
        raise ScreeningImportError(
            'task_dispatch_failed', '文件已安全保存，但解析任务派发失败，可稍后重试。',
            http_status=503, details={'batch_id': batch.id},
        )
    return batch


def claim_import_batch(batch_id: int, task_id: int) -> ReferenceImportBatch:
    with transaction.atomic():
        batch = ReferenceImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.task_id != task_id:
            raise ScreeningImportError('stale_import_task', '导入任务与当前批次不匹配。', http_status=409)
        if batch.status not in (
            ReferenceImportBatch.Status.UPLOADED,
            ReferenceImportBatch.Status.VALIDATING,
            ReferenceImportBatch.Status.IMPORTING,
            ReferenceImportBatch.Status.READY,
        ):
            raise ScreeningImportError(
                'invalid_import_state', f'导入批次当前状态为 {batch.status}。',
                http_status=409,
            )
        batch.status = ReferenceImportBatch.Status.IMPORTING
        batch.started_at = batch.started_at or timezone.now()
        batch.finished_at = None
        batch.save(update_fields=['status', 'started_at', 'finished_at', 'updated_at'])
        batch.references.all().delete()
        batch.files.update(
            detected_count=0,
            parsed_count=0,
            skipped_count=0,
            missing_abstract_count=0,
            warning_count=0,
            error_count=0,
            issues_truncated=False,
        )
        ReferenceImportIssue.objects.filter(import_file__import_batch=batch).delete()
        batch.files.update(
            parse_status=ReferenceImportFile.ParseStatus.PARSING,
            started_at=timezone.now(),
            finished_at=None,
        )
        ReferenceImportBatch.objects.filter(pk=batch.pk).update(
            discovered_count=0,
            accepted_count=0,
            rejected_count=0,
            missing_abstract_count=0,
            warning_count=0,
            error_count=0,
        )
        return batch


def persist_import_reports(batch_id: int, reports: list[dict]) -> dict:
    limits = ImportLimits.from_settings()
    batch = ReferenceImportBatch.objects.get(pk=batch_id)
    import_files = {
        item.original_filename: item for item in batch.files.select_related('source_file')
    }
    totals = {
        'discovered_count': 0,
        'accepted_count': 0,
        'rejected_count': 0,
        'missing_abstract_count': 0,
        'warning_count': 0,
        'error_count': 0,
    }
    remaining_issues = limits.max_reported_errors
    for report in reports:
        import_file = import_files.get(report.get('filename'))
        if import_file is None:
            continue
        status_map = {
            'success': ReferenceImportFile.ParseStatus.PARSED,
            'warning': ReferenceImportFile.ParseStatus.WARNING,
            'partial': ReferenceImportFile.ParseStatus.WARNING,
            'failed': ReferenceImportFile.ParseStatus.FAILED,
        }
        import_file.parse_status = status_map.get(
            report.get('status'), ReferenceImportFile.ParseStatus.FAILED,
        )
        import_file.detected_count = int(report.get('detected_entries') or 0)
        import_file.parsed_count = int(report.get('parsed_entries') or 0)
        import_file.skipped_count = int(report.get('skipped_entries') or 0)
        import_file.missing_abstract_count = int(report.get('missing_abstract_entries') or 0)
        import_file.warning_count = int(report.get('warning_count') or 0)
        import_file.error_count = int(report.get('error_count') or 0)
        issues = list(report.get('issues') or [])
        keep_count = min(len(issues), remaining_issues)
        import_file.issues_truncated = (
            bool(report.get('issues_truncated')) or len(issues) > keep_count
        )
        import_file.finished_at = timezone.now()
        import_file.save(update_fields=[
            'parse_status', 'detected_count', 'parsed_count', 'skipped_count',
            'missing_abstract_count', 'warning_count', 'error_count',
            'issues_truncated', 'finished_at', 'updated_at',
        ])
        import_file.issues.all().delete()
        ReferenceImportIssue.objects.bulk_create([
            ReferenceImportIssue(
                import_file=import_file,
                severity=issue.get('severity', ReferenceImportIssue.Severity.WARNING),
                code=str(issue.get('code') or 'unknown')[:64],
                record_position=issue.get('position'),
                line_number=issue.get('line'),
                source_identifier=str(issue.get('identifier') or '')[:255],
                title_preview=str(issue.get('title') or '')[:500],
                message=str(issue.get('message') or ''),
                suggestion=str(issue.get('suggestion') or ''),
            )
            for issue in issues[:keep_count]
        ])
        remaining_issues -= keep_count
        totals['discovered_count'] += import_file.detected_count
        totals['accepted_count'] += import_file.parsed_count
        totals['rejected_count'] += import_file.skipped_count
        totals['missing_abstract_count'] += import_file.missing_abstract_count
        totals['warning_count'] += import_file.warning_count
        totals['error_count'] += import_file.error_count
    ReferenceImportBatch.objects.filter(pk=batch_id).update(**totals, updated_at=timezone.now())
    return totals


def complete_import_batch(batch_id: int, reports: list[dict]) -> ReferenceImportBatch:
    totals = persist_import_reports(batch_id, reports)
    limits = ImportLimits.from_settings()
    blocking_error_count = sum(
        int(report.get('blocking_error_count', report.get('error_count', 0)) or 0)
        for report in reports
    )
    if totals['accepted_count'] > limits.max_references:
        fail_import_batch(batch_id)
        raise ScreeningImportError(
            'too_many_references', f'解析结果超过 {limits.max_references} 篇上限。',
            details={'limit': limits.max_references, 'actual': totals['accepted_count']},
        )
    if totals['accepted_count'] <= 0:
        fail_import_batch(batch_id)
        raise ScreeningImportError('no_usable_references', '没有解析到可用文献。')
    if blocking_error_count and not limits.allow_partial:
        fail_import_batch(batch_id)
        raise ScreeningImportError(
            'partial_import_rejected', '索引中存在解析错误，当前配置不允许部分导入。',
            details={
                'error_count': totals['error_count'],
                'blocking_error_count': blocking_error_count,
            },
        )

    stored_count = ScreeningReference.objects.filter(import_batch_id=batch_id).count()
    if stored_count != totals['accepted_count']:
        fail_import_batch(batch_id)
        raise ScreeningImportError(
            'reference_count_mismatch',
            '解析成功数与数据库暂存文献数不一致，批次未发布。',
            details={'reported': totals['accepted_count'], 'stored': stored_count},
        )

    raw_metadata_count = ScreeningReferenceRawMetadata.objects.filter(
        reference__import_batch_id=batch_id,
    ).count()
    if raw_metadata_count != stored_count:
        fail_import_batch(batch_id)
        raise ScreeningImportError(
            'raw_metadata_count_mismatch',
            '标准化文献数与原始元数据数不一致，批次未发布。',
            details={'references': stored_count, 'raw_metadata': raw_metadata_count},
        )

    file_counts = dict(
        ScreeningReference.objects.filter(import_batch_id=batch_id)
        .values('import_file_id')
        .annotate(stored_count=Count('id'))
        .values_list('import_file_id', 'stored_count')
    )
    for import_file in ReferenceImportFile.objects.filter(import_batch_id=batch_id):
        actual = file_counts.get(import_file.id, 0)
        if actual != import_file.parsed_count:
            fail_import_batch(batch_id)
            raise ScreeningImportError(
                'reference_file_count_mismatch',
                f'{import_file.original_filename} 的解析数与数据库写入数不一致。',
                details={
                    'import_file_id': import_file.id,
                    'reported': import_file.parsed_count,
                    'stored': actual,
                },
            )

    ReferenceImportBatch.objects.filter(
        pk=batch_id, status=ReferenceImportBatch.Status.IMPORTING,
    ).update(status=ReferenceImportBatch.Status.READY, updated_at=timezone.now())

    try:
        return _publish_ready_import_batch(batch_id, totals, limits, stored_count)
    except ScreeningImportError:
        fail_import_batch(batch_id)
        raise


def _publish_ready_import_batch(
    batch_id: int, totals: dict, limits: ImportLimits, stored_count: int,
) -> ReferenceImportBatch:
    """Publish a fully staged batch in one short, locked transaction."""

    with transaction.atomic():
        batch = ReferenceImportBatch.objects.select_for_update().select_related('corpus').get(pk=batch_id)
        corpus = ScreeningCorpus.objects.select_for_update().get(pk=batch.corpus_id)
        if batch.status != ReferenceImportBatch.Status.READY:
            raise ScreeningImportError(
                'invalid_import_state', f'导入批次当前状态为 {batch.status}。',
                http_status=409,
            )
        if corpus.revision != batch.base_revision:
            raise ScreeningImportError(
                'corpus_revision_conflict', '文献集已发生变化，请重新导入。',
                http_status=409,
            )

        active_reference_count = ScreeningReference.objects.filter(
            corpus=corpus,
        ).active_at(batch.base_revision).count()
        if active_reference_count != corpus.active_reference_count:
            raise ScreeningImportError(
                'corpus_count_mismatch',
                '文献集缓存数量与数据库有效文献数不一致，批次未发布。',
                http_status=409,
                details={
                    'cached': corpus.active_reference_count,
                    'stored': active_reference_count,
                },
            )

        published_source_count = ReferenceImportFile.objects.filter(
            import_batch_id=batch.id,
            parsed_count__gt=0,
        ).count()
        active_source_count = ReferenceImportFile.objects.filter(
            import_batch__corpus=corpus,
            import_batch__status=ReferenceImportBatch.Status.COMPLETED,
            introduced_revision__lte=batch.base_revision,
            parsed_count__gt=0,
        ).filter(
            Q(removed_revision__isnull=True) | Q(removed_revision__gt=batch.base_revision)
        ).count()
        if active_source_count != corpus.active_source_file_count:
            raise ScreeningImportError(
                'corpus_source_count_mismatch',
                '文献集缓存来源数与数据库有效来源数不一致，批次未发布。',
                http_status=409,
                details={
                    'cached': corpus.active_source_file_count,
                    'stored': active_source_count,
                },
            )
        if active_reference_count + stored_count > limits.max_references:
            raise ScreeningImportError(
                'too_many_references',
                f'发布后文献总数将超过 {limits.max_references} 篇上限。',
                details={
                    'limit': limits.max_references,
                    'current': active_reference_count,
                    'incoming': stored_count,
                },
            )

        batch.status = ReferenceImportBatch.Status.PUBLISHING
        batch.save(update_fields=['status', 'updated_at'])
        corpus.publish_revision(
            expected_revision=batch.base_revision,
            target_revision=batch.target_revision,
            active_reference_count=active_reference_count + stored_count,
            active_source_file_count=active_source_count + published_source_count,
            last_import_batch=batch,
        )
        now = timezone.now()
        batch.status = ReferenceImportBatch.Status.COMPLETED
        batch.published_revision = batch.target_revision
        batch.published_at = now
        batch.finished_at = now
        batch.save(update_fields=[
            'status', 'published_revision', 'published_at', 'finished_at', 'updated_at',
        ])
        ActivityLog.objects.create(
            project=batch.project,
            operation_type='screening_import_publish',
            operation_detail={
                'batch_id': batch.id,
                'published_revision': batch.published_revision,
                **totals,
            },
            created_by=batch.created_by,
        )
    try:
        _invalidate_downstream(batch.project)
    except Exception:
        logger.exception('文献批次已发布，但下游失效处理失败 batch_id=%s', batch.id)
    return batch


def fail_import_batch(batch_id: int) -> None:
    with transaction.atomic():
        batch = ReferenceImportBatch.objects.select_for_update().filter(
            pk=batch_id, status__in=ACTIVE_BATCH_STATUSES,
        ).first()
        if batch is None:
            return
        batch.references.all().delete()
        batch.status = ReferenceImportBatch.Status.FAILED
        batch.finished_at = timezone.now()
        batch.save(update_fields=['status', 'finished_at', 'updated_at'])
    ReferenceImportFile.objects.filter(
        import_batch_id=batch_id,
        parse_status__in=(
            ReferenceImportFile.ParseStatus.PENDING,
            ReferenceImportFile.ParseStatus.VALIDATING,
            ReferenceImportFile.ParseStatus.PARSING,
        ),
    ).update(parse_status=ReferenceImportFile.ParseStatus.FAILED, finished_at=timezone.now())


def cancel_import_batch(batch_id: int) -> None:
    with transaction.atomic():
        batch = ReferenceImportBatch.objects.select_for_update().filter(
            pk=batch_id, status__in=ACTIVE_BATCH_STATUSES,
        ).first()
        if batch is None:
            return
        batch.references.all().delete()
        batch.status = ReferenceImportBatch.Status.CANCELLED
        batch.finished_at = timezone.now()
        batch.save(update_fields=['status', 'finished_at', 'updated_at'])
        batch.files.filter(
            parse_status__in=(
                ReferenceImportFile.ParseStatus.PENDING,
                ReferenceImportFile.ParseStatus.VALIDATING,
                ReferenceImportFile.ParseStatus.PARSING,
            ),
        ).update(
            parse_status=ReferenceImportFile.ParseStatus.FAILED,
            finished_at=timezone.now(),
        )


def retry_import_batch(batch: ReferenceImportBatch, user) -> ReferenceImportBatch:
    dispatch_errors = []
    limits = ImportLimits.from_settings()
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        batch = ReferenceImportBatch.objects.select_for_update().get(pk=batch.pk)
        project = Project.objects.select_for_update().get(pk=batch.project_id)
        corpus = ScreeningCorpus.objects.select_for_update().get(pk=batch.corpus_id)
        if batch.status not in (
            ReferenceImportBatch.Status.FAILED,
            ReferenceImportBatch.Status.CANCELLED,
        ):
            raise ScreeningImportError(
                'invalid_import_state', '只有失败或已取消的批次可以重试。',
                http_status=409,
            )
        if not batch.files.exists():
            raise ScreeningImportError(
                'missing_import_files', '该批次已没有可重试的原始文件。',
                http_status=409,
            )
        if ReferenceImportBatch.objects.filter(
            project=project, status__in=ACTIVE_BATCH_STATUSES,
        ).exclude(pk=batch.pk).exists():
            raise ScreeningImportError(
                'import_already_running', '该项目已有导入操作正在进行。',
                http_status=409,
            )
        if ReferenceImportBatch.objects.filter(
            created_by=user, status__in=ACTIVE_BATCH_STATUSES,
        ).exclude(pk=batch.pk).count() >= limits.max_concurrent_per_user:
            raise ScreeningImportError(
                'user_import_limit', '当前账户已有导入操作正在进行。',
                http_status=409,
            )

        batch.base_revision = corpus.revision
        batch.target_revision = corpus.revision + 1
        batch.status = ReferenceImportBatch.Status.UPLOADED
        batch.started_at = None
        batch.finished_at = None
        batch.published_at = None
        batch.published_revision = None
        batch.save(update_fields=[
            'base_revision', 'target_revision', 'status', 'started_at', 'finished_at',
            'published_at', 'published_revision', 'updated_at',
        ])
        batch.references.all().delete()
        ReferenceImportIssue.objects.filter(import_file__import_batch=batch).delete()
        batch.files.update(
            introduced_revision=batch.target_revision,
            parse_status=ReferenceImportFile.ParseStatus.PENDING,
            detected_count=0,
            parsed_count=0,
            skipped_count=0,
            missing_abstract_count=0,
            warning_count=0,
            error_count=0,
            issues_truncated=False,
            started_at=None,
            finished_at=None,
        )
        file_ids = list(batch.files.values_list('source_file_id', flat=True))
        task = create_step_task(
            project.id, 'parse', user.id,
            {'import_batch_id': batch.id, 'file_ids': file_ids},
        )
        batch.task = task
        batch.save(update_fields=['task', 'updated_at'])
        transaction.on_commit(lambda: _dispatch_batch_task(batch.id, task.id, dispatch_errors))

    batch.refresh_from_db()
    if dispatch_errors:
        raise ScreeningImportError(
            'task_dispatch_failed', '重试任务派发失败，请稍后再次重试。',
            http_status=503, details={'batch_id': batch.id},
        )
    return batch


def delete_failed_import_batch(batch: ReferenceImportBatch, user) -> None:
    """Delete an unpublished failed/cancelled batch and all of its retained files."""
    with transaction.atomic():
        batch = ReferenceImportBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status not in (
            ReferenceImportBatch.Status.FAILED,
            ReferenceImportBatch.Status.CANCELLED,
        ):
            raise ScreeningImportError(
                'invalid_import_state', '只有失败或已取消且尚未发布的批次可以整批删除。',
                http_status=409,
            )

        batch_id = batch.id
        project = batch.project
        filenames = list(batch.files.values_list('original_filename', flat=True))
        source_files = list(batch.files.values_list('source_file_id', flat=True))

        # 失败批次正常情况下没有暂存文献；显式删除可兼容历史异常中断状态。
        batch.references.all().delete()
        DataFile.objects.filter(
            project=project,
            metadata__import_batch_id=batch_id,
        ).exclude(pk__in=source_files).delete()
        batch.files.all().delete()
        DataFile.objects.filter(pk__in=source_files, project=project).delete()
        ActivityLog.objects.create(
            project=project,
            operation_type='screening_import_delete_failed',
            operation_detail={
                'batch_id': batch_id,
                'file_count': len(filenames),
                'filenames': filenames,
            },
            created_by=user,
        )
        batch.delete()


def remove_source_file(source_file: DataFile, user) -> None:
    try:
        import_file = source_file.reference_import_file
    except ReferenceImportFile.DoesNotExist:
        reset_downstream_on_input_delete(source_file, user)
        source_file.delete()
        return

    batch = import_file.import_batch
    if batch.status in ACTIVE_BATCH_STATUSES:
        raise ScreeningImportError('import_in_progress', '导入进行中，不能删除该文件。', http_status=409)
    if batch.status != ReferenceImportBatch.Status.COMPLETED:
        with transaction.atomic():
            import_file.delete()
            source_file.delete()
            ReferenceImportBatch.objects.filter(pk=batch.pk).update(
                file_count=max(batch.file_count - 1, 0),
                total_bytes=max(batch.total_bytes - source_file.file_size, 0),
                updated_at=timezone.now(),
            )
        return
    if import_file.removed_revision is not None:
        return

    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=source_file.project_id)
        corpus = ScreeningCorpus.objects.select_for_update().get(pk=batch.corpus_id)
        if ReferenceImportBatch.objects.filter(
            project=project, status__in=ACTIVE_BATCH_STATUSES,
        ).exists():
            raise ScreeningImportError(
                'import_already_running', '该项目已有导入操作正在进行。',
                http_status=409,
            )
        active_references = ScreeningReference.objects.filter(
            import_file=import_file,
        ).active_at(corpus.revision)
        removed_reference_count = active_references.count()
        removal = ReferenceImportBatch.objects.create(
            project=project,
            corpus=corpus,
            created_by=user,
            operation=ReferenceImportBatch.Operation.REMOVE,
            status=ReferenceImportBatch.Status.PUBLISHING,
            base_revision=corpus.revision,
            target_revision=corpus.revision + 1,
            file_count=1,
            total_bytes=source_file.file_size,
            accepted_count=removed_reference_count,
            config_snapshot=ImportLimits.from_settings().snapshot(),
            parser_version=batch.parser_version,
            started_at=timezone.now(),
        )
        import_file.removed_revision = removal.target_revision
        import_file.removed_by_batch = removal
        import_file.save(update_fields=['removed_revision', 'removed_by_batch', 'updated_at'])
        active_references.update(
            removed_revision=removal.target_revision,
        )
        corpus.publish_revision(
            expected_revision=removal.base_revision,
            target_revision=removal.target_revision,
            active_reference_count=max(0, corpus.active_reference_count - removed_reference_count),
            active_source_file_count=max(
                0,
                corpus.active_source_file_count - (1 if removed_reference_count else 0),
            ),
            last_import_batch=removal,
        )
        now = timezone.now()
        removal.status = ReferenceImportBatch.Status.COMPLETED
        removal.published_revision = removal.target_revision
        removal.published_at = now
        removal.finished_at = now
        removal.save(update_fields=[
            'status', 'published_revision', 'published_at', 'finished_at', 'updated_at',
        ])
        ActivityLog.objects.create(
            project=project,
            operation_type='screening_import_remove',
            operation_detail={
                'batch_id': removal.id,
                'source_file_id': source_file.id,
                'filename': source_file.filename,
                'published_revision': removal.published_revision,
            },
            created_by=user,
        )
    _invalidate_downstream(source_file.project, removed_source_file_id=source_file.id)


def batch_payload(batch: ReferenceImportBatch) -> dict:
    task = batch.task
    return {
        'id': batch.id,
        'project': batch.project_id,
        'operation': batch.operation,
        'status': batch.status,
        'base_revision': batch.base_revision,
        'target_revision': batch.target_revision,
        'published_revision': batch.published_revision,
        'file_count': batch.file_count,
        'total_bytes': batch.total_bytes,
        'discovered_count': batch.discovered_count,
        'accepted_count': batch.accepted_count,
        'rejected_count': batch.rejected_count,
        'missing_abstract_count': batch.missing_abstract_count,
        'warning_count': batch.warning_count,
        'error_count': batch.error_count,
        'created_at': batch.created_at,
        'started_at': batch.started_at,
        'finished_at': batch.finished_at,
        'task': ({'id': task.id, 'status': task.status} if task else None),
        'files': [
            {
                'id': item.id,
                'source_file_id': item.source_file_id,
                'filename': item.original_filename,
                'format': item.source_format,
                'status': item.parse_status,
                'bytes': item.source_file.file_size,
                'parsed_count': item.parsed_count,
                'skipped_count': item.skipped_count,
                'warning_count': item.warning_count,
                'error_count': item.error_count,
            }
            for item in batch.files.select_related('source_file').all()
        ],
    }


def cleanup_abandoned_import_files(*, now=None) -> dict:
    """Purge private files retained by old failed/cancelled batches."""
    limits = ImportLimits.from_settings()
    now = now or timezone.now()
    cutoff = now - timedelta(days=limits.failed_retention_days)
    batches = ReferenceImportBatch.objects.filter(
        status__in=(
            ReferenceImportBatch.Status.FAILED,
            ReferenceImportBatch.Status.CANCELLED,
        ),
        finished_at__lt=cutoff,
    )
    purged_files = 0
    purged_bytes = 0
    for batch in batches.iterator():
        for import_file in list(batch.files.select_related('source_file')):
            data_file = import_file.source_file
            purged_bytes += data_file.file_size
            import_file.references.all().delete()
            import_file.delete()
            data_file.delete()
            purged_files += 1
        snapshot = dict(batch.config_snapshot or {})
        snapshot['raw_files_purged_at'] = now.isoformat()
        batch.config_snapshot = snapshot
        batch.save(update_fields=['config_snapshot', 'updated_at'])
    return {'purged_files': purged_files, 'purged_bytes': purged_bytes}
