"""QA 人工确认用例。"""

from django.db import transaction
from django.utils import timezone

from core.quality.services.domain_results import recalculate_domain_results


@transaction.atomic
def confirm_signal(item, judgment, user):
    """确认单条信号问题，并刷新所属文献的领域结果。"""
    baseline = item.ai_judgment or item.system_recommendation
    if baseline and judgment != baseline and not item.is_modified:
        item.is_modified = True
        item.original_ai_judgment = baseline
    item.human_judgment = judgment
    item.is_confirmed = True
    item.confirmed_by = user
    item.confirmed_at = timezone.now()
    item.save()
    recalculate_domain_results(item.qa_ref)
    return item


@transaction.atomic
def batch_confirm(ref, confirm_mode, signal_keys, user):
    """按预选值、AI 值或指定 signal key 批量确认。"""
    items = ref.signal_items.all()
    if confirm_mode == 'specific_keys':
        items = items.filter(signal_key__in=signal_keys)

    confirmed_count = 0
    now = timezone.now()
    for item in items:
        if confirm_mode == 'adopt_preselected':
            judgment = item.pre_selected
        elif confirm_mode == 'adopt_ai':
            judgment = item.ai_judgment
        else:
            judgment = item.pre_selected or item.ai_judgment
        if not judgment:
            continue

        if item.ai_judgment and judgment != item.ai_judgment and not item.is_modified:
            item.is_modified = True
            item.original_ai_judgment = item.ai_judgment
        item.human_judgment = judgment
        item.is_confirmed = True
        item.confirmed_by = user
        item.confirmed_at = now
        item.save(update_fields=[
            'human_judgment', 'is_confirmed', 'confirmed_by', 'confirmed_at',
            'is_modified', 'original_ai_judgment',
        ])
        confirmed_count += 1

    recalculate_domain_results(ref)
    return confirmed_count
