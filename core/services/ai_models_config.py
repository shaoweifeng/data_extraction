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
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "logo": "deepseek",
        "description": "深度求索",
        "api_url": os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1"),
        "api_key": os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "sub_models": [
            {
                "id": "deepseek",
                "name": "DeepSeek Chat",
                "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "description": "均衡型，性价比高",
                "is_default": True,
            },
            # 未来可扩展，追加此处：
            # {
            #     "id": "deepseek-r1",
            #     "name": "DeepSeek R1",
            #     "model": "deepseek-reasoner",
            #     "description": "推理增强型",
            #     "is_default": False,
            # },
        ],
    },
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
                "id": "doubao",
                "name": "豆包 Pro",
                "model": os.environ.get("DOUBAO_MODEL", "ep-20250509-xxxxxx"),
                "description": "标准型",
                "is_default": False,
            },
        ],
    },
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
                "id": "qwen",
                "name": "Qwen Max",
                "model": os.environ.get("QWEN_MODEL", "qwen-max"),
                "description": "旗舰型",
                "is_default": False,
            },
        ],
    },
]


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
    for provider, sm in _iter_sub_models():
        if sm["id"] == model_id:
            return {
                "id":       sm["id"],
                "name":     sm["name"],
                "model":    sm["model"],
                "logo":     provider["logo"],
                "provider": provider["id"],
                "api_url":  provider["api_url"],
                "api_key":  provider["api_key"],
                "timeout":  provider["timeout"],
                "is_default": sm.get("is_default", False),
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
