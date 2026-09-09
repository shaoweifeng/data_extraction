"""
AI 模型配置表

结构设计：
- 每个顶层厂家（provider）下可配置多个子模型（sub_models）
- 每个子模型有独立的 id（全局唯一）、model 字符串、展示名
- 同一厂家的子模型共用 api_url、api_key、timeout
- get_model_config(model_id) 按子模型 id 查找完整配置（含 api_key）
- get_models_for_frontend() 返回前端分组结构（不含 api_key）

扩展方式：在某厂家的 sub_models 列表中追加条目即可，id 需全局唯一。
"""

import os
from typing import Optional, List

AI_PROVIDERS = [
    # ── DeepSeek ──────────────────────────────────────────────────────────────
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "logo": "deepseek",
        "description": "深度求索 · 均衡性价比",
        "api_url": os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1"),
        "api_key": os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "sub_models": [
            {
                "id": "deepseek-v4-flash",
                "name": "DeepSeek V4 Flash",
                "model": "deepseek-v4-flash",
                "description": "高速版，价格极低",
                "is_default": True,
                "is_reasoning": True,   # 推理模型，需禁用 thinking 以直接输出结构化内容
            },
            {
                "id": "deepseek-v4-pro",
                "name": "DeepSeek V4 Pro",
                "model": "deepseek-v4-pro",
                "description": "旗舰版，效果最佳",
                "is_default": False,
                "is_reasoning": True,   # 推理模型，需禁用 thinking 以直接输出结构化内容
            },
        ],
    },
    # ── 豆包（字节跳动 Volcengine ARK）────────────────────────────────────────
    {
        "id": "doubao",
        "name": "豆包",
        "logo": "doubao",
        "description": "字节跳动 · 中文理解出色",
        "api_url": os.environ.get("DOUBAO_API_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "api_key": os.environ.get("DOUBAO_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "sub_models": [
            {
                "id": "doubao-seed-2-1-turbo",
                "name": "Doubao-Seed-2.1-Turbo",
                "model": "doubao-seed-2-1-turbo-260628",
                "description": "Seed 2.1 低价高速版，适合大批量初筛",
                "is_default": True,
                "is_reasoning": True,
            },
        ],
    },
    # ── 千问（阿里云 DashScope）────────────────────────────────────────────────
    {
        "id": "qwen",
        "name": "千问",
        "logo": "qwen",
        "description": "阿里云 · 长文本处理优秀",
        "api_url": os.environ.get("QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": os.environ.get("QWEN_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "sub_models": [
            {
                "id": "qwen3-7-flash",
                "name": "Qwen3.7-Flash",
                "model": "qwen3.7-flash",
                "description": "闪速版，价格极低",
                "is_default": False,
                "is_reasoning": True,
            },
            {
                "id": "qwen3-7-plus",
                "name": "Qwen3.7-Plus",
                "model": "qwen3.7-plus",
                "description": "增强版，均衡性价比",
                "is_default": False,
                "is_reasoning": True,
            },
            {
                "id": "qwen3-7-max",
                "name": "Qwen3.7-Max",
                "model": "qwen3.7-max",
                "description": "旗舰稳定版，效果最强",
                "is_default": True,
                "is_reasoning": True,
            },
        ],
    },
]


# 已保存的筛选/质量评价任务可能仍引用旧 ID。旧 ID 仅用于兼容读取，
# 不再出现在前端模型列表中，实际请求统一路由到当前的 Qwen/豆包模型。
MODEL_ID_ALIASES = {
    "qwen3-6-flash": "qwen3-7-flash",
    "qwen3-6-plus": "qwen3-7-plus",
    "qwen3-6-max-preview": "qwen3-7-max",
    "doubao-seed-1.8": "doubao-seed-2-1-turbo",
    "doubao-seed-2.0-lite": "doubao-seed-2-1-turbo",
    "seedance-1.6-flash": "doubao-seed-2-1-turbo",
    "seedance-2.0-mini": "doubao-seed-2-1-turbo",
}


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _iter_sub_models():
    """遍历所有 (provider, sub_model) 元组。"""
    for provider in AI_PROVIDERS:
        for sm in provider.get("sub_models", []):
            yield provider, sm


def get_model_config(model_id: str) -> Optional[dict]:
    """
    按子模型 id 查找完整配置（含 api_key、api_url、model 字符串）。
    向后兼容：model_id 可以是旧格式的 provider id（如 'deepseek'）。
    """
    model_id = MODEL_ID_ALIASES.get(model_id, model_id)
    for provider, sm in _iter_sub_models():
        if sm["id"] == model_id:
            return {
                "id":           sm["id"],
                "name":         sm["name"],
                "model":        sm["model"],
                "logo":         provider["logo"],
                "provider":     provider["id"],
                "api_url":      provider["api_url"],
                "api_key":      provider["api_key"],
                "timeout":      provider["timeout"],
                "is_default":   sm.get("is_default", False),
                "is_reasoning": sm.get("is_reasoning", False),  # 推理模型标志
            }
    return None


def get_models_for_frontend() -> list:
    """
    返回前端可见的分组模型列表（不暴露 api_key）。

    格式（供前端分组渲染）：
    [
      {
        "id": "deepseek",
        "name": "DeepSeek",
        "logo": "deepseek",
        "description": "...",
        "configured": True,
        "sub_models": [
          {"id": "deepseek", "name": "DeepSeek Chat", "description": "均衡型",
           "is_default": True, "configured": True},
          ...
        ]
      }, ...
    ]
    """
    result = []
    for provider in AI_PROVIDERS:
        has_key = bool(provider["api_key"])
        sub_models = []
        for sm in provider.get("sub_models", []):
            sub_models.append({
                "id":          sm["id"],
                "name":        sm["name"],
                "description": sm.get("description", ""),
                "is_default":  sm.get("is_default", False),
                "configured":  has_key,
            })
        result.append({
            "id":          provider["id"],
            "name":        provider["name"],
            "logo":        provider["logo"],
            "description": provider["description"],
            "configured":  has_key,
            "sub_models":  sub_models,
        })
    return result


def get_models_for_frontend_flat() -> list:
    """
    平铺版本，供 export_handler 等需要 id→name 映射的地方使用。
    返回格式：[{"id": "deepseek", "name": "DeepSeek Chat", "logo": "deepseek", ...}, ...]
    """
    flat = []
    for provider, sm in _iter_sub_models():
        has_key = bool(provider["api_key"])
        flat.append({
            "id":          sm["id"],
            "name":        sm["name"],
            "logo":        provider["logo"],
            "description": sm.get("description", ""),
            "model":       sm["model"],
            "is_default":  sm.get("is_default", False),
            "configured":  has_key,
        })
    return flat
