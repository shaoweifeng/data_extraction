"""Shared export formatting helpers."""

from typing import List


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
