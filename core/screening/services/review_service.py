"""初筛人工审阅写入用例。"""

from django.db import transaction

from core.models import ManualReview
from core.screening.domain.decisions import ai_decision
from core.screening.selectors import load_ai_results_by_source


def _ai_result_map(project_id, source_xmls):
    return load_ai_results_by_source(project_id, source_xmls)


def _upsert(project_id, step, source_xml, decision, reason, user, result):
    original_decision = ai_decision(result or {})
    review, created = ManualReview.objects.update_or_create(
        project_id=project_id,
        source_xml=source_xml,
        defaults={
            'step': step,
            'ai_decision': original_decision,
            'ai_reason': (result or {}).get('exclusion_reason', ''),
            'decision': decision,
            'reason': reason,
            'is_override': bool(original_decision) and original_decision != decision,
            'reviewer': user,
        },
    )
    return review, created


@transaction.atomic
def submit_reviews(project_id, step, review_items, user):
    """批量新增或更新人工审阅记录。"""
    ai_results = _ai_result_map(
        project_id,
        [item['source_xml'] for item in review_items],
    )
    created_count = 0
    updated_count = 0
    for item in review_items:
        source_xml = item['source_xml']
        _, created = _upsert(
            project_id,
            step,
            source_xml,
            item['decision'],
            item.get('reason', ''),
            user,
            ai_results.get(source_xml, {}),
        )
        created_count += int(created)
        updated_count += int(not created)
    return created_count, updated_count


@transaction.atomic
def update_review(project_id, step, source_xml, decision, reason, user):
    """更新一篇文献的人工审阅决定。"""
    result = _ai_result_map(project_id, [source_xml]).get(source_xml, {})
    return _upsert(project_id, step, source_xml, decision, reason, user, result)
