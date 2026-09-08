"""初筛最终决定规则，不依赖 HTTP 或 Django request。"""

from typing import Any, Mapping, Optional


FINAL_DECISIONS = ('included', 'excluded')
MANUAL_DECISIONS = ('included', 'excluded', 'pending', 'conflict')


def ai_decision(result: Mapping[str, Any]) -> str:
    """统一读取新旧 AI 筛选结果中的决定字段。"""
    decision = result.get('decision', '')
    if decision in ('included', 'excluded', 'conflict'):
        return decision
    legacy = str(result.get('include_or_not', '')).lower()
    if legacy == 'yes':
        return 'included'
    if legacy == 'no':
        return 'excluded'
    return ''


def final_decision(result: Mapping[str, Any], manual_review: Optional[Any] = None) -> str:
    """人工明确决定优先，否则回退到 AI 共识/决定。"""
    manual = getattr(manual_review, 'decision', '') if manual_review else ''
    if manual in MANUAL_DECISIONS:
        return manual

    consensus = result.get('consensus') or ai_decision(result)
    if consensus in ('included', 'excluded', 'conflict'):
        return consensus
    return 'pending'


def is_included(result: Mapping[str, Any], manual_review: Optional[Any] = None) -> bool:
    return final_decision(result, manual_review) == 'included'
