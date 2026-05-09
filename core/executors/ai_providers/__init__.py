"""
AI Provider 抽象层

架构设计：
- BaseAIProvider: 抽象基类，定义统一接口
- DeepSeekProvider: 当前默认实现（OpenAI 兼容格式）
- 将来可扩展：ClaudeProvider, GPT4Provider, QwenProvider 等

多模型支持预留接口（当前未实现）：
- get_provider(name) 工厂函数，按名称获取 provider 实例
- 将来可并发跑多个 provider，对有分歧的文献单独列出
"""

from .base import BaseAIProvider, ScreeningResult
from .deepseek import DeepSeekProvider


def get_provider(name: str = None, config: dict = None) -> BaseAIProvider:
    """
    Provider 工厂函数

    Args:
        name: provider 名称（deepseek / doubao / qwen），None 时从环境变量 AI_PROVIDER 读取
        config: 额外配置，None 时从 ai_models_config 读取对应配置
    """
    import os
    from platform_backend.ai_models_config import get_model_config

    provider_name = name or os.environ.get("AI_PROVIDER", "deepseek")

    # 从配置表读取该模型的 api_url / api_key / model
    if config is None:
        model_cfg = get_model_config(provider_name)
        if model_cfg:
            config = {
                "api_url": model_cfg["api_url"],
                "api_key": model_cfg["api_key"],
                "model":   model_cfg["model"],
                "timeout": model_cfg["timeout"],
            }
        else:
            config = {}

    # 豆包和千问均兼容 OpenAI 接口，直接复用 DeepSeekProvider
    registry = {
        "deepseek": DeepSeekProvider,
        "doubao":   DeepSeekProvider,   # OpenAI 兼容
        "qwen":     DeepSeekProvider,   # OpenAI 兼容（DashScope）
    }

    cls = registry.get(provider_name.lower())
    if cls is None:
        raise ValueError(f"未知的 AI Provider: {provider_name}，可用: {list(registry.keys())}")

    return cls(config)


__all__ = ["BaseAIProvider", "ScreeningResult", "DeepSeekProvider", "get_provider"]
