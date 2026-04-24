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
        name: provider 名称，None 时从环境变量 AI_PROVIDER 读取
        config: 额外配置，None 时从环境变量读取
    
    Returns:
        AIProvider 实例
    
    预留扩展点：
        将来可在此注册更多 provider，如 ClaudeProvider、GPT4Provider 等
    """
    import os
    provider_name = name or os.environ.get("AI_PROVIDER", "deepseek")
    
    registry = {
        "deepseek": DeepSeekProvider,
        # "claude": ClaudeProvider,     # 将来扩展
        # "gpt4": GPT4Provider,         # 将来扩展
        # "qwen": QwenProvider,         # 将来扩展
    }
    
    cls = registry.get(provider_name.lower())
    if cls is None:
        raise ValueError(f"未知的 AI Provider: {provider_name}，可用: {list(registry.keys())}")
    
    return cls(config or {})


__all__ = ["BaseAIProvider", "ScreeningResult", "DeepSeekProvider", "get_provider"]
