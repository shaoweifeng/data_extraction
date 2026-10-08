"""Revision-bound, idempotent database persistence for AI screening runs."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from core.ai import AIUsageContext, AIUsageSettlementService, TokenUsageAccumulator
from core.models import Task
from core.screening.models import (
    DedupRun,
    ReferenceDuplicateMember,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningResult,
    ScreeningRun,
)
from core.screening.services.import_limits import ImportLimits


class ScreeningRunError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def reference_entry(reference: ScreeningReference) -> dict:
    return {
        'reference_id': reference.id,
        'title': reference.title,
        'abstract': reference.abstract,
        'authors': list(reference.authors or []),
        'journal': reference.journal,
        'publication_year': reference.publication_year,
        'publication_date': reference.publication_date,
        'publication_type': reference.publication_type,
        'language': reference.language,
        'keywords': list(reference.keywords or []),
        'volume': reference.volume,
        'issue': reference.issue,
        'pages': reference.pages,
        'doi': reference.doi,
        'pmid': reference.pmid,
        'pmcid': reference.pmcid,
        'isbn': reference.isbn,
        'url': reference.url,
        'address': reference.address,
        'source_identifier': reference.source_identifier,
    }


def run_input_references(corpus: ScreeningCorpus, dedup_run: DedupRun | None):
    queryset = (
        ScreeningReference.objects.filter(corpus=corpus)
        .active_at(corpus.revision)
        .order_by('id')
    )
    if dedup_run is not None:
        duplicate_ids = ReferenceDuplicateMember.objects.filter(
            dedup_run=dedup_run,
            role=ReferenceDuplicateMember.Role.DUPLICATE,
        ).values('reference_id')
        queryset = queryset.exclude(id__in=duplicate_ids)
    return queryset


def _current_dedup_run(corpus: ScreeningCorpus) -> DedupRun | None:
    run = corpus.last_dedup_run
    if (
        run is not None
        and run.status == DedupRun.Status.COMPLETED
        and run.corpus_revision == corpus.revision
    ):
        return run
    return None


def prepare_screening_run(
    *,
    project,
    task: Task,
    criteria: list[str],
    model_ids: list[str],
    config: dict,
) -> tuple[ScreeningRun, bool]:
    """Create or claim a resumable run and seed one idempotent row per input."""
    with transaction.atomic():
        locked_task = Task.objects.select_for_update().get(pk=task.pk)
        resume_run_id = (locked_task.config or {}).get('screening_run_id')
        corpus = ScreeningCorpus.objects.select_for_update().filter(project=project).first()
        if corpus is None or corpus.active_reference_count <= 0:
            raise ScreeningRunError('empty_corpus', '当前项目没有可用于 AI 初筛的已发布文献。')
        dedup_run = _current_dedup_run(corpus)

        if resume_run_id:
            run = ScreeningRun.objects.select_for_update().filter(
                pk=resume_run_id,
                project=project,
                status__in=(ScreeningRun.Status.RUNNING, ScreeningRun.Status.STOPPING),
            ).first()
            if run is None:
                raise ScreeningRunError('invalid_resume_run', '原 AI 初筛运行不可恢复。')
            if run.corpus_revision != corpus.revision or run.dedup_run_id != getattr(dedup_run, 'id', None):
                raise ScreeningRunError('corpus_revision_conflict', '文献集或去重结果已变化，不能继续旧任务。')
            run.status = ScreeningRun.Status.RUNNING
            run.task = locked_task
            run.started_at = run.started_at or timezone.now()
            run.finished_at = None
            run.save(update_fields=['status', 'task', 'started_at', 'finished_at', 'updated_at'])
            run.results.filter(status=ScreeningResult.Status.PROCESSING).update(
                status=ScreeningResult.Status.PENDING,
                started_at=None,
            )
            created = False
        else:
            references = run_input_references(corpus, dedup_run)
            total_count = references.count()
            expected_count = dedup_run.kept_count if dedup_run is not None else corpus.active_reference_count
            if total_count != expected_count:
                raise ScreeningRunError(
                    'screening_input_count_mismatch',
                    f'AI 初筛输入数量不一致：预期 {expected_count}，实际 {total_count}。',
                )
            run = ScreeningRun.objects.create(
                project=project,
                corpus=corpus,
                corpus_revision=corpus.revision,
                dedup_run=dedup_run,
                task=locked_task,
                created_by=locked_task.created_by,
                status=ScreeningRun.Status.RUNNING,
                criteria_snapshot={'criteria': list(criteria)},
                model_config_snapshot={
                    'model_ids': list(model_ids),
                    'enable_thinking': config.get('enable_thinking') is True,
                    'concurrency': config.get('concurrency'),
                },
                prompt_version=str(config.get('prompt_version') or 'current'),
                total_count=total_count,
                started_at=timezone.now(),
            )
            created = True

        task_config = dict(locked_task.config or {})
        task_config['screening_run_id'] = run.id
        locked_task.config = task_config
        locked_task.save(update_fields=['config', 'updated_at'])
        task.config = task_config

    if created:
        _seed_screening_results(run)
    _refresh_run_counters(run.id)
    run.refresh_from_db()
    return run, created


def _seed_screening_results(run: ScreeningRun) -> None:
    references = run_input_references(run.corpus, run.dedup_run)
    batch_size = max(1, ImportLimits.from_settings().db_batch_size)
    pending = []
    try:
        for reference_id in references.values_list('id', flat=True).iterator(chunk_size=batch_size):
            pending.append(ScreeningResult(screening_run=run, reference_id=reference_id))
            if len(pending) >= batch_size:
                ScreeningResult.objects.bulk_create(
                    pending,
                    batch_size=batch_size,
                    ignore_conflicts=True,
                )
                pending = []
        if pending:
            ScreeningResult.objects.bulk_create(
                pending,
                batch_size=batch_size,
                ignore_conflicts=True,
            )
        stored = run.results.count()
        if stored != run.total_count:
            raise ScreeningRunError(
                'screening_result_seed_mismatch',
                f'AI 初筛结果初始化数量不一致：预期 {run.total_count}，实际 {stored}。',
            )
    except Exception:
        fail_screening_run(run.id)
        raise


def next_result_batch(run: ScreeningRun, batch_size: int) -> list[ScreeningResult]:
    max_attempts = max(1, int(getattr(settings, 'SCREENING_AI_MAX_ATTEMPTS', 3)))
    with transaction.atomic():
        rows = list(
            ScreeningResult.objects.select_for_update()
            .filter(screening_run=run)
            .filter(
                Q(status=ScreeningResult.Status.PENDING)
                | Q(status=ScreeningResult.Status.FAILED, attempt_count__lt=max_attempts)
            )
            .select_related('reference')
            .order_by('id')[:batch_size]
        )
        if rows:
            now = timezone.now()
            ScreeningResult.objects.filter(id__in=[row.id for row in rows]).update(
                status=ScreeningResult.Status.PROCESSING,
                started_at=now,
                error_code='',
                error_message='',
                attempt_count=F('attempt_count') + 1,
            )
            for row in rows:
                row.status = ScreeningResult.Status.PROCESSING
                row.started_at = now
                row.attempt_count += 1
        return rows


def persist_result_batch(rows: list[ScreeningResult], provider_results: list[dict]) -> None:
    now = timezone.now()
    ratio = Decimal(str(getattr(settings, 'BILLING_CREDIT_TOKEN_RATIO', 1000)))
    for index, row in enumerate(rows):
        result = provider_results[index] if index < len(provider_results) else {
            'error': '模型未返回该文献的结果。',
        }
        consensus = str(result.get('consensus') or result.get('decision') or 'pending')
        error_message = str(result.get('error') or '')
        if error_message:
            row.status = ScreeningResult.Status.FAILED
            row.decision = ScreeningResult.Decision.UNCERTAIN
            row.consensus = consensus if consensus in ('conflict', 'pending') else 'pending'
            row.error_code = 'provider_error'
            row.error_message = error_message
        else:
            row.status = ScreeningResult.Status.COMPLETED
            row.decision = (
                consensus
                if consensus in (ScreeningResult.Decision.INCLUDED, ScreeningResult.Decision.EXCLUDED)
                else ScreeningResult.Decision.UNCERTAIN
            )
            row.consensus = consensus
            row.error_code = ''
            row.error_message = ''
        row.reason = str(
            result.get('exclusion_reason')
            or result.get('ai_summary_reason')
            or ''
        )
        row.model_results = list(result.get('multi_model_results') or [])
        row.extracted_fields = dict(result.get('extracted_fields') or {})
        previous_usage = dict(row.token_usage or {})
        current_usage = dict(result.get('token_usage') or {})
        row.token_usage = {
            key: int(previous_usage.get(key, 0) or 0) + int(current_usage.get(key, 0) or 0)
            for key in ('prompt', 'completion', 'total')
        }
        total_tokens = Decimal(str(row.token_usage.get('total', 0) or 0))
        row.points_consumed = total_tokens / ratio if ratio > 0 else Decimal('0')
        row.finished_at = now
        row.updated_at = now

    ScreeningResult.objects.bulk_update(
        rows,
        [
            'status', 'decision', 'consensus', 'reason', 'model_results',
            'extracted_fields', 'token_usage', 'points_consumed', 'error_code',
            'error_message', 'started_at', 'finished_at', 'updated_at',
        ],
        batch_size=max(1, ImportLimits.from_settings().db_batch_size),
    )
    if rows:
        _refresh_run_counters(rows[0].screening_run_id)


def _refresh_run_counters(run_id: int) -> dict:
    max_attempts = max(1, int(getattr(settings, 'SCREENING_AI_MAX_ATTEMPTS', 3)))
    counts = ScreeningResult.objects.filter(screening_run_id=run_id).aggregate(
        processed=Count(
            'id',
            filter=(
                Q(status=ScreeningResult.Status.COMPLETED)
                | Q(status=ScreeningResult.Status.FAILED, attempt_count__gte=max_attempts)
            ),
        ),
        included=Count(
            'id',
            filter=Q(status=ScreeningResult.Status.COMPLETED, decision=ScreeningResult.Decision.INCLUDED),
        ),
        excluded=Count(
            'id',
            filter=Q(status=ScreeningResult.Status.COMPLETED, decision=ScreeningResult.Decision.EXCLUDED),
        ),
        uncertain=Count(
            'id',
            filter=Q(status=ScreeningResult.Status.COMPLETED, decision=ScreeningResult.Decision.UNCERTAIN),
        ),
        failed=Count(
            'id',
            filter=Q(status=ScreeningResult.Status.FAILED, attempt_count__gte=max_attempts),
        ),
    )
    ScreeningRun.objects.filter(pk=run_id).update(
        processed_count=counts['processed'],
        included_count=counts['included'],
        excluded_count=counts['excluded'],
        uncertain_count=counts['uncertain'],
        failed_count=counts['failed'],
        updated_at=timezone.now(),
    )
    return counts


def pause_screening_run(run_id: int) -> None:
    ScreeningRun.objects.filter(
        pk=run_id,
        status=ScreeningRun.Status.RUNNING,
    ).update(status=ScreeningRun.Status.STOPPING, updated_at=timezone.now())
    ScreeningResult.objects.filter(
        screening_run_id=run_id,
        status=ScreeningResult.Status.PROCESSING,
    ).update(status=ScreeningResult.Status.PENDING, started_at=None)


def fail_screening_run(run_id: int) -> None:
    ScreeningRun.objects.filter(pk=run_id).exclude(
        status=ScreeningRun.Status.COMPLETED,
    ).update(status=ScreeningRun.Status.FAILED, finished_at=timezone.now(), updated_at=timezone.now())
    ScreeningResult.objects.filter(
        screening_run_id=run_id,
        status=ScreeningResult.Status.PROCESSING,
    ).update(status=ScreeningResult.Status.PENDING, started_at=None)


def collect_run_usage(run: ScreeningRun) -> TokenUsageAccumulator:
    usage = TokenUsageAccumulator()
    queryset = run.results.filter(
        status__in=(ScreeningResult.Status.COMPLETED, ScreeningResult.Status.FAILED),
    ).values_list('token_usage', flat=True)
    for token_usage in queryset.iterator(chunk_size=1000):
        usage.add(token_usage)
    return usage


def complete_screening_run(run_id: int, *, task: Task, model_ids: list[str]) -> tuple[ScreeningRun, dict]:
    run = ScreeningRun.objects.select_related('corpus', 'project', 'created_by', 'dedup_run').get(pk=run_id)
    counts = _refresh_run_counters(run.id)
    run.refresh_from_db()
    if counts['processed'] != run.total_count:
        raise ScreeningRunError('screening_incomplete', '仍有文献尚未完成 AI 初筛。')

    usage = collect_run_usage(run)
    try:
        with transaction.atomic():
            run = ScreeningRun.objects.select_for_update().select_related('dedup_run').get(pk=run_id)
            corpus = ScreeningCorpus.objects.select_for_update().get(pk=run.corpus_id)
            if corpus.revision != run.corpus_revision:
                raise ScreeningRunError('corpus_revision_conflict', 'AI 初筛期间文献集已发生变化。')
            current_dedup_id = getattr(_current_dedup_run(corpus), 'id', None)
            if current_dedup_id != run.dedup_run_id:
                raise ScreeningRunError('dedup_run_conflict', 'AI 初筛期间去重结果已发生变化。')
            settlement = AIUsageSettlementService.settle(
                AIUsageContext(
                    feature='AI筛选',
                    user=run.created_by,
                    project=run.project,
                    task=task,
                    model_ids=model_ids,
                    idempotency_key=f'screening-run:{run.id}:usage',
                ),
                usage,
            )
            run.status = ScreeningRun.Status.COMPLETED
            run.task = task
            run.input_tokens = usage.prompt_tokens
            run.output_tokens = usage.completion_tokens
            run.points_consumed = Decimal(str(settlement.get('credits_consumed', 0) or 0))
            run.finished_at = timezone.now()
            run.save(update_fields=[
                'status', 'task', 'input_tokens', 'output_tokens', 'points_consumed',
                'finished_at', 'updated_at',
            ])
            return run, settlement
    except ScreeningRunError:
        fail_screening_run(run_id)
        raise


def current_completed_screening_run(project_id: int) -> ScreeningRun | None:
    return (
        ScreeningRun.objects.filter(
            project_id=project_id,
            status=ScreeningRun.Status.COMPLETED,
            corpus_revision=F('corpus__revision'),
        )
        .filter(
            Q(dedup_run_id=F('corpus__last_dedup_run_id'))
            | Q(dedup_run__isnull=True, corpus__last_dedup_run__isnull=True)
        )
        .order_by('-finished_at', '-id')
        .first()
    )


def current_screening_run(project_id: int) -> ScreeningRun | None:
    """Return the latest run bound to the project's current corpus revision."""
    return (
        ScreeningRun.objects.filter(
            project_id=project_id,
            corpus_revision=F('corpus__revision'),
        )
        .filter(
            Q(dedup_run_id=F('corpus__last_dedup_run_id'))
            | Q(dedup_run__isnull=True, corpus__last_dedup_run__isnull=True)
        )
        .order_by('-created_at', '-id')
        .first()
    )


def latest_completed_screening_run(project_id: int) -> ScreeningRun | None:
    return (
        ScreeningRun.objects.select_related('corpus', 'dedup_run')
        .filter(project_id=project_id, status=ScreeningRun.Status.COMPLETED)
        .order_by('-finished_at', '-id')
        .first()
    )


def screening_run_is_current(run: ScreeningRun) -> bool:
    corpus = run.corpus
    current_dedup_id = getattr(_current_dedup_run(corpus), 'id', None)
    return (
        run.status == ScreeningRun.Status.COMPLETED
        and run.corpus_revision == corpus.revision
        and run.dedup_run_id == current_dedup_id
    )
