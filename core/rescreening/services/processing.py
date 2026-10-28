"""Worker import execution, diagnostics and atomic revision publication."""
from itertools import islice

from django.db import transaction
from django.utils import timezone

from core.bibliography import bibliography_snapshot, parser_record
from core.models import ActivityLog, Project
from core.quality.storage import materialized_storage_path
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenImportBatch, RescreenReference
from core.rescreening.services.persistence import ReferenceWriter
from core.rescreening.services.source import field_definitions, source_fingerprint, source_preview
from core.screening import parsers
from core.screening.models import ScreeningReferenceRawMetadata
from core.screening.parsers.diagnostics import ParseReportCollector
from core.screening.services.final_results import iter_resolved_screening_records
from core.screening.services.import_limits import ImportLimits, validate_projected_reference_count
from core.screening.services.import_errors import ScreeningImportError


def _check_stop(batch, stop_checker):
    batch.refresh_from_db(fields=['status'])
    if batch.status in ('cancelled', 'cancelling') or stop_checker():
        raise RescreenError('import_cancelled', '复筛导入已停止。', status=409)


def _uploaded_records(batch, limits, writer, stop_checker):
    total, rejected, skipped = 0, 0, 0
    for source in batch.files.order_by('id'):
        rejected_before = rejected
        with materialized_storage_path(source.raw_file, suffix='.' + source.original_filename.rsplit('.', 1)[-1]) as path:
            collector = ParseReportCollector(str(path), max_issues=limits.max_reported_errors)
            parser_error = None
            try:
                for record in parsers.iter_file(str(path)):
                    if (total + rejected) % limits.processing_batch_size == 0:
                        _check_stop(batch, stop_checker)
                    try:
                        parsers.validate_reference_record(record, limits)
                        validate_projected_reference_count(batch.corpus.active_reference_count, total+1, limits)
                        writer.add(record, source_file=source)
                    except (parsers.ReferenceRecordValidationError, RescreenError) as exc:
                        rejected += 1
                        collector.reject_record(exc.code, str(exc), position=record.get('source_position'))
                        continue
                    collector.observe(record)
                    total += 1
            except (RescreenError, ScreeningImportError) as exc:
                source.report = collector.finalize(parser_error=exc)
                source.report['filename'] = source.original_filename
                source.save(update_fields=['report'])
                raise
            except Exception as exc:
                parser_error = exc
            report = collector.finalize(parser_error=parser_error)
            report['filename'] = source.original_filename
            source.report = report
            source.save(update_fields=['report'])
            skipped += max(0, report['skipped_entries'] - (rejected - rejected_before))
            if report['blocking_error_count'] and not limits.allow_partial:
                raise RescreenError('blocking_parse_errors', '题录存在阻断性解析错误，请查看诊断报告后重试。')
    return total, rejected, skipped


def _screening_records(batch, limits, writer, stop_checker):
    run = batch.source_screening_run
    if run is None:
        raise RescreenError('source_missing', '来源初筛运行已不存在。')
    definitions = field_definitions(batch.project_id)
    iterator = iter(iter_resolved_screening_records(run, batch_size=limits.db_batch_size))
    total, skipped = 0, 0
    while rows := list(islice(iterator, limits.db_batch_size)):
        _check_stop(batch, stop_checker)
        existing = set(RescreenReference.objects.filter(project_id=batch.project_id,
            source_key__in=[f'screening:{row.reference.pk}' for row in rows]).values_list('source_key', flat=True))
        raw_rows = {raw.reference_id: raw for raw in ScreeningReferenceRawMetadata.objects.filter(
            reference_id__in=[row.reference.pk for row in rows]).select_related('import_file')}
        for row in rows:
            if row.final_decision != 'included' or f'screening:{row.reference.pk}' in existing:
                skipped += 1
                continue
            validate_projected_reference_count(batch.corpus.active_reference_count, total+1, limits)
            snapshot = bibliography_snapshot(row.reference)
            raw = raw_rows.get(row.reference.pk)
            if raw is None:
                raise RescreenError('raw_metadata_missing', '初筛来源缺少原始元数据，请先修复来源后再导入。')
            record = {**parser_record(snapshot), '_raw_metadata': raw.raw_fields,
                'source_type': raw.source_format, '_parser_version': raw.parser_version,
                'source_position': row.reference.source_record_index}
            writer.add(record, source_reference=row.reference, source_run=run,
                source_snapshot={'source_reference_id': row.reference.pk, 'source_result_id': row.result.pk,
                    'source_run_id': run.pk, 'source_corpus_revision': run.corpus_revision, 'final_decision': row.final_decision,
                    'source_filename': raw.import_file.original_filename,
                    'source_file_sha256': raw.import_file.sha256,
                    'source_fingerprint': source_fingerprint(row, raw.raw_hash, definitions['hash'])},
                extracted_fields=row.result.extracted_fields, field_definitions=definitions)
            total += 1
    return total, skipped


def process_import(batch_id, *, stop_checker=lambda: False, expected_task_id=None):
    with transaction.atomic():
        batch = RescreenImportBatch.objects.select_for_update().select_related('corpus', 'project', 'source_screening_run').get(pk=batch_id)
        if expected_task_id is not None and batch.task_id != expected_task_id:
            raise RescreenError('stale_import_task', '此任务已被新的导入尝试替代。', status=409)
        if batch.status == 'completed':
            return batch
        if batch.status != 'uploaded':
            raise RescreenError('import_already_claimed', '此批次已被领取或已结束。', status=409)
        batch.status = 'importing'
        batch.save(update_fields=['status'])
    limits = ImportLimits(**batch.limits_snapshot)
    writer = ReferenceWriter(batch, limits)
    try:
        limits.validate()
        _check_stop(batch, stop_checker)
        if batch.source_type == 'bibliography':
            count, rejected, skipped = _uploaded_records(batch, limits, writer, stop_checker)
            if count == 0:
                raise RescreenError('no_usable_records', '题录没有可导入的文献，请查看解析诊断。')
        else:
            count, skipped = _screening_records(batch, limits, writer, stop_checker)
            rejected = 0
            preview = source_preview(batch.project, batch_size=limits.db_batch_size)
            if preview['fingerprint'] != batch.source_snapshot['fingerprint'] or preview['run_id'] != batch.source_snapshot['run_id']:
                raise RescreenError('source_changed', '初筛来源在导入期间变化，本次未发布，请预览后重试。', status=409)
        writer.flush()
        with transaction.atomic():
            Project.objects.select_for_update().get(pk=batch.project_id)
            corpus = RescreenCorpus.objects.select_for_update().get(pk=batch.corpus_id)
            _check_stop(batch, stop_checker)
            if corpus.revision != batch.base_revision:
                raise RescreenError('revision_conflict', '文献集已变化，本次导入未发布。', status=409)
            if batch.references.count() != count:
                raise RescreenError('count_mismatch', '暂存文献数量不一致，本次导入未发布。')
            batch.accepted_count, batch.rejected_count, batch.skipped_count = count, rejected, skipped
            batch.status, batch.finished_at = 'completed', timezone.now()
            batch.save()
            if count:
                corpus.revision = batch.target_revision
                corpus.active_reference_count += count
                corpus.current_run = None
                corpus.save()
            ActivityLog.objects.create(project=batch.project, operation_type='rescreen_import_completed',
                operation_detail={'batch_id': batch.pk, 'accepted': count, 'revision': corpus.revision}, created_by=batch.created_by)
        return batch
    except Exception as exc:
        # Only unpublished staging rows are discarded; diagnostics/source files remain retryable.
        batch.references.all().delete()
        RescreenImportBatch.objects.filter(pk=batch.pk).update(
            status='cancelled' if getattr(exc, 'code', '') == 'import_cancelled' else 'failed',
            accepted_count=0, error_code=getattr(exc, 'code', 'import_failed'),
            error_message=str(exc)[:500], finished_at=timezone.now(),
        )
        raise
