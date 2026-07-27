"""
AI Provider 抽象层

架构设计：
- BaseAIProvider: 抽象基类，定义统一接口
- OpenAICompatibleProvider: OpenAI 兼容接口实现（DeepSeek / 豆包 / 千问均适用）
- 将来可扩展：ClaudeProvider 等非 OpenAI 接口的模型
"""
from .base import BaseAIProvider, ScreeningResult
from .openai_compatible import OpenAICompatibleProvider


def get_provider(name: str = None, config: dict = None) -> BaseAIProvider:
    """
    Provider 工厂函数

    Args:
        name: provider 名称（deepseek / doubao / qwen），None 时从环境变量 AI_PROVIDER 读取
        config: 额外配置，None 时从 ai_models_config 读取对应配置
    """
    import os
    from core.services.ai_models_config import get_model_config

    provider_name = name or os.environ.get("AI_PROVIDER", "deepseek")

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

    # deepseek / doubao / qwen 均兼容 OpenAI 接口
    registry = {
        "deepseek": OpenAICompatibleProvider,
        "doubao":   OpenAICompatibleProvider,
        "qwen":     OpenAICompatibleProvider,
    }
    cls = registry.get(provider_name.lower())
    if cls is None:
        raise ValueError(f"未知的 AI Provider: {provider_name}，可用: {list(registry.keys())}")
    return cls(config)


__all__ = ["BaseAIProvider", "ScreeningResult", "OpenAICompatibleProvider", "get_provider"]
