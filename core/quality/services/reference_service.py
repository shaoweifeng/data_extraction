"""QA 文献导入和方法分配用例。"""

from django.db import transaction

from core.models import ManualReview, QAChart, QAChartSettings, QAReference
from core.screening.selectors import load_ai_results
from core.screening.services.decision_service import ScreeningDecisionService


def _safe_int(value):
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


@transaction.atomic
def rebuild_from_screening(project, source_stage='SCREEN_1'):
    """清空当前 QA 结果，并按初筛最终决定重建 QAReference。"""
    QAReference.objects.filter(project=project).delete()
    QAChart.objects.filter(project=project).delete()
    QAChartSettings.objects.filter(project=project).delete()

    manual_reviews = {
        review.source_xml: review
        for review in ManualReview.objects.filter(
            project=project,
            step__stage__stage_key=source_stage,
        )
    }
    imported = []
    seen_xml = set()
    for result in load_ai_results(project.id):
        source_xml = result.get('source_xml', '')
        if not source_xml or source_xml in seen_xml:
            continue
        seen_xml.add(source_xml)
        review = manual_reviews.get(source_xml)
        if not ScreeningDecisionService.is_included(result, review):
            continue

        authors = result.get('authors') or ''
        if isinstance(authors, list):
            first_author = authors[0] if authors else ''
        else:
            first_author = authors.split(';')[0].split(',')[0]
        ref = QAReference.objects.create(
            project=project,
            title=result.get('title', '') or source_xml,
            first_author=first_author[:100],
            year=_safe_int(result.get('year', '')),
            journal=(result.get('journal') or '')[:300],
            doi=(result.get('doi') or '')[:200],
            source_type='screening_import',
            source_ref_id=review.id if review else None,
            fulltext_status='pending',
        )
        imported.append(ref.id)
    return imported


@transaction.atomic
def assign_quality_method(refs, quality_method):
    """为同一项目的一组 QA 文献设置评价方法。"""
    return refs.update(quality_method=quality_method)
