"""QA reference import and quality-method assignment services."""

from collections import Counter

from django.db import transaction

from core.models import QAChart, QAChartSettings, QAReference
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
    }


@transaction.atomic
def rebuild_from_screening(project, source_stage='SCREEN_1'):
    """Rebuild QA snapshots from one explicit, current screening result source."""
    screening_run = current_completed_screening_run(project.id) if source_stage == 'SCREEN_1' else None
    if screening_run is None:
        raise QualityImportError(
            'current_screening_run_required',
            '当前文献集没有匹配的已完成 AI 初筛运行，请完成本版本筛选后再导入质量评价。',
        )

    _clear_quality_results(project)
    return _rebuild_from_database(project, screening_run)


@transaction.atomic
def assign_quality_method(refs, quality_method):
    """为同一项目的一组 QA 文献设置评价方法。"""
    return refs.update(quality_method=quality_method)
