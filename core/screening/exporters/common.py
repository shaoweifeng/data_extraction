"""Shared export formatting helpers."""

from typing import List


def format_conflict_detail(result: dict) -> str:
    """使用已有模型子结果生成可审计的分歧说明。"""
    lines = ['AI模型存在分歧，最终结论未经人工裁定（已豁免导出）']
    decision_labels = {
        'included': '纳入',
        'excluded': '排除',
        'conflict': '分歧',
        'pending': '待定',
        'error': '错误',
    }
    model_results = result.get('multi_model_results') or []
    for index, model_result in enumerate(model_results, 1):
        if not isinstance(model_result, dict):
            continue
        model_name = (
            model_result.get('model_name')
            or model_result.get('model_id')
            or f'模型{index}'
        )
        decision = model_result.get('decision', '')
        decision_text = decision_labels.get(decision, decision or '未知')
        reason = model_result.get('reason') or model_result.get('error') or '未提供理由'
        reason_id = model_result.get('reason_id')
        criterion = f'（排除标准 {reason_id}）' if reason_id else ''
        lines.append(f'- {model_name}：{decision_text}{criterion}；理由：{reason}')

    if len(lines) == 1:
        fallback = result.get('ai_summary_reason') or result.get('exclusion_reason')
        if fallback:
            lines.append(f'- 模型分歧摘要：{fallback}')

    # Excel 单元格文本上限为 32767，预留少量余量。
    return '\n'.join(lines)[:32000]


def _lookup_criteria_id(reason_text: str, criteria_list: List[str]) -> str:
    """
    通过理由文本在纳排标准列表中查找对应编号（1-based）。
    - 精确匹配优先
    - 其次检查是否包含关系（reason 包含 criteria 文本，或反之）
    - 找不到返回空字符串
    """
    if not reason_text or not criteria_list:
        return ''
    text = reason_text.strip()
    for i, c in enumerate(criteria_list, 1):
        if c.strip() == text:
            return str(i)
    # 模糊匹配：理由文本包含某条标准的内容（或反之）
    for i, c in enumerate(criteria_list, 1):
        c_stripped = c.strip()
        if c_stripped and (c_stripped in text or text in c_stripped):
            return str(i)
    return ''
