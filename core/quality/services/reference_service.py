"""QA reference import and quality-method assignment services."""

from collections import Counter

from django.db import transaction
from django.db.models import Count

from core.models import QAChart, QAChartSettings, QAReference, RescreenReference
from core.screening.services.final_results import iter_resolved_screening_records
from core.screening.services.import_limits import ImportLimits
from core.screening.services.screening_run_service import current_completed_screening_run


class QualityImportError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_int(value):
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _first_author(authors) -> str:
    if isinstance(authors, list):
        return str(authors[0] if authors else '')[:200]
    return str(authors or '').split(';')[0].split(',')[0][:200]


def _clear_quality_results(project) -> None:
    QAReference.objects.filter(project=project).delete()
    QAChart.objects.filter(project=project).delete()
    QAChartSettings.objects.filter(project=project).delete()


def _flush(buffer: list[QAReference], batch_size: int) -> None:
    if buffer:
        QAReference.objects.bulk_create(buffer, batch_size=batch_size)
        buffer.clear()


def _rebuild_from_database(project, screening_run) -> dict:
    batch_size = max(1, ImportLimits.from_settings().db_batch_size)
    counts = Counter()
    pending: list[QAReference] = []
    for resolved in iter_resolved_screening_records(screening_run, batch_size=batch_size):
        counts['total'] += 1
        counts[resolved.final_decision] += 1
        if resolved.final_decision != 'included':
            continue
        reference = resolved.reference
        pending.append(QAReference(
            project=project,
            title=reference.title or f'文献 {reference.id}',
            first_author=_first_author(reference.authors),
            year=_safe_int(reference.publication_year),
            journal=(reference.journal or '')[:300],
            abstract=reference.abstract or '',
            doi=(reference.doi or '')[:200],
            source_type='screening_import',
            source_reference=reference,
            source_screening_run=screening_run,
            source_screening_decision='included',
            fulltext_status='pending',
        ))
        if len(pending) >= batch_size:
            _flush(pending, batch_size)
    _flush(pending, batch_size)
    ref_ids = list(
        QAReference.objects.filter(
            project=project,
            source_screening_run=screening_run,
        ).order_by('id').values_list('id', flat=True)
    )
    return {
        'imported': len(ref_ids),
        'skipped': counts['total'] - len(ref_ids),
        'skipped_by_decision': {
            key: counts[key] for key in ('excluded', 'pending', 'conflict') if counts[key]
        },
        'ref_ids': ref_ids,
        'screening_run_id': screening_run.id,
        'corpus_revision': screening_run.corpus_revision,
        'source_stage': 'SCREEN_1',
    }


def _rebuild_from_rescreening(project) -> dict:
    """Rebuild QA snapshots from manually included SCREEN_2 references."""
    imported_ids = []
    qs = RescreenReference.objects.filter(
        project=project,
        human_decision='included',
    ).select_related('fulltext_file').order_by('id')

    for rescreen_ref in qs:
        ref = QAReference.objects.create(
            project=project,
            title=rescreen_ref.title or f'复筛文献 {rescreen_ref.id}',
            first_author=(rescreen_ref.first_author or '')[:200],
            year=_safe_int(rescreen_ref.year),
            journal=(rescreen_ref.journal or '')[:300],
            abstract=rescreen_ref.abstract or '',
            doi=(rescreen_ref.doi or '')[:200],
            source_type='screening_import',
            source_screening_decision='included',
            fulltext_file=rescreen_ref.fulltext_file,
            fulltext_status='available' if rescreen_ref.fulltext_file_id else 'pending',
        )
        imported_ids.append(ref.id)

    total = project.rescreen_references.count()
    skipped = max(total - len(imported_ids), 0)
    skipped_by_decision = {
        decision or 'not_reviewed': count
        for decision, count in project.rescreen_references.exclude(human_decision='included')
        .values_list('human_decision')
        .order_by()
        .annotate(count=Count('id'))
    }
    return {
        'imported': len(imported_ids),
        'skipped': skipped,
        'skipped_by_decision': skipped_by_decision,
        'ref_ids': imported_ids,
        'screening_run_id': None,
        'corpus_revision': None,
        'source_stage': 'SCREEN_2',
    }


@transaction.atomic
def rebuild_from_screening(project, source_stage='SCREEN_1'):
    """Rebuild QA snapshots from one explicit, current screening/rescreening result source."""
    _clear_quality_results(project)

    if source_stage == 'SCREEN_2':
        return _rebuild_from_rescreening(project)

    screening_run = current_completed_screening_run(project.id) if source_stage == 'SCREEN_1' else None
    if screening_run is None:
        raise QualityImportError(
            'current_screening_run_required',
            '当前文献集没有匹配的已完成 AI 初筛运行，请完成本版本筛选后再导入质量评价。',
        )

    return _rebuild_from_database(project, screening_run)


@transaction.atomic
def assign_quality_method(refs, quality_method, quality_method_variant=''):
    """为同一项目的一组 QA 文献设置评价方法。"""
    return refs.update(
        quality_method=quality_method,
        quality_method_variant=quality_method_variant,
    )
