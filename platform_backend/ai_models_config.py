"""
AI 模型配置表
- 所有支持的大模型均在此维护
- api_key 优先读环境变量；留空则表示未配置
- 通过 /api/ai-models/ 接口暴露给前端（不含 api_key 明文）
"""

import os

AI_MODELS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "logo": "deepseek",                        # 前端 icon 标识
        "description": "深度求索 · 推理能力强",
        "api_url": os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1"),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "api_key": os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "is_default": True,
    },
    {
        "id": "doubao",
        "name": "豆包",
        "logo": "doubao",
        "description": "字节跳动 · 中文理解出色",
        "api_url": os.environ.get("DOUBAO_API_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "model": os.environ.get("DOUBAO_MODEL", "ep-20250509-xxxxxx"),   # 填入实际 endpoint id
        "api_key": os.environ.get("DOUBAO_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "is_default": False,
    },
    {
        "id": "qwen",
        "name": "千问",
        "logo": "qwen",
        "description": "阿里云 · 长文本处理优秀",
        "api_url": os.environ.get("QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": os.environ.get("QWEN_MODEL", "qwen-max"),
        "api_key": os.environ.get("QWEN_API_KEY", ""),
        "timeout": int(os.environ.get("AI_TIMEOUT", "120")),
        "is_default": False,
    },
]


from typing import Optional


def get_model_config(model_id: str) -> Optional[dict]:
    """按 id 查找模型配置，返回完整配置（含 api_key）"""
    for m in AI_MODELS:
        if m["id"] == model_id:
            return m
    return None


def get_models_for_frontend() -> list:
    """返回前端可见的模型列表（不暴露 api_key，仅标示是否已配置）"""
    result = []
    for m in AI_MODELS:
        result.append({
            "id": m["id"],
            "name": m["name"],
            "logo": m["logo"],
            "description": m["description"],
            "model": m["model"],
            "is_default": m["is_default"],
            "configured": bool(m["api_key"]),   # 有 key 才可用
        })
    return result
