"""
consensus_service.py
--------------------
多模型筛选共识计算服务。

当前策略（CONSENSUS_STRATEGY = "manual"）：
    - 所有模型一致 included  → consensus = "included"
    - 所有模型一致 excluded  → consensus = "excluded"
    - 任何分歧               → consensus = "conflict"（强制进入人工审阅）

预留扩展点（v2 可切换为 majority_vote）：
    将 CONSENSUS_STRATEGY 改为 "majority_vote" 即可，无需改其他代码。
"""

from __future__ import annotations

# ─── 策略开关 ────────────────────────────────────────────────────────────────
# "manual"        — 有任何分歧则标记 conflict，强制人工定夺
# "majority_vote" — 多数表决，过半数为准，无需人工介入
CONSENSUS_STRATEGY: str = "manual"


def resolve_consensus(model_results: list[dict]) -> str:
    """
    根据多个模型的筛选结果，计算共识结论。

    Parameters
    ----------
    model_results : list[dict]
        每个元素格式：
        {
            "model_id":   "deepseek-r1",
            "model_name": "DeepSeek-R1",
            "decision":   "included" | "excluded",
            "reason":     "...",
            "tokens":     {"prompt": 0, "completion": 0, "total": 0}
        }

    Returns
    -------
    str : "included" | "excluded" | "conflict" | "pending"
    """
    if not model_results:
        return "pending"

    valid = [r for r in model_results if r.get("decision") in ("included", "excluded")]
    if not valid:
        return "pending"

    decisions = {r["decision"] for r in valid}

    if len(decisions) == 1:
        # 所有模型结论一致
        return decisions.pop()

    # 存在分歧
    if CONSENSUS_STRATEGY == "majority_vote":
        included_count = sum(1 for r in valid if r["decision"] == "included")
        return "included" if included_count > len(valid) / 2 else "excluded"

    # 默认 manual：分歧即 conflict
    return "conflict"


def build_summary_reason(model_results: list[dict]) -> str:
    """
    为 ManualReview.ai_reason 生成可读的多模型摘要文本。
    单模型时直接返回该模型的 reason。
    多模型时按 "模型名: 决定 — 理由" 格式拼接。
    """
    if not model_results:
        return ""

    if len(model_results) == 1:
        r = model_results[0]
        return r.get("reason") or ""

    lines = []
    for r in model_results:
        decision_label = "纳入" if r.get("decision") == "included" else "排除"
        reason = r.get("reason") or "（无理由）"
        name = r.get("model_name") or r.get("model_id") or "未知模型"
        lines.append(f"[{name}] {decision_label}：{reason}")

    return "\n".join(lines)


def get_model_display_name(model_id: str) -> str:
    """
    将 model_id 转换为可读名称，优先从 ai_models_config 读取，
    找不到时直接返回 model_id。
    """
    try:
        from core.services.ai_models_config import get_model_config
        cfg = get_model_config(model_id)
        if cfg:
            return cfg.get("name") or model_id
    except Exception:
        pass
    return model_id
