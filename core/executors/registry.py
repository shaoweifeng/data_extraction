"""
步骤 Handler 注册表

职责：
- 维护 step_key → Handler 类的映射
- 提供 get_handler(step_key) 工厂方法
- 提供 register 装饰器供 handler 自注册

注册表规则：
- 每个 step_key 只能注册一个 handler
- 注册发生在 handlers/__init__.py 导入时（模块加载时自动注册）
- SyncExecutor / AsyncExecutor 的 execute() 通过注册表分发步骤

使用示例：
    from core.executors.registry import get_handler
    handler_cls = get_handler("parse")
    handler = handler_cls(executor)
    handler.execute()
"""

import logging
from typing import Dict, Type, Optional

logger = logging.getLogger(__name__)

# step_key → Handler 类
_REGISTRY: Dict[str, Type] = {}


def register(step_key: str):
    """
    Handler 自注册装饰器。

    用法：
        @register("parse")
        class ParseHandler(BaseStepHandler):
            ...
    """
    def decorator(cls):
        if step_key in _REGISTRY:
            logger.warning(f"[registry] 覆盖已注册的 handler: step_key={step_key!r}")
        _REGISTRY[step_key] = cls
        cls.step_key = step_key
        return cls
    return decorator


def get_handler(step_key: str) -> Optional[Type]:
    """
    根据 step_key 获取对应的 Handler 类。

    Returns:
        Handler 类，未找到返回 None
    """
    return _REGISTRY.get(step_key)


def list_registered() -> Dict[str, str]:
    """返回所有已注册 handler 的 {step_key: class_name} 字典（用于调试）。"""
    return {k: v.__name__ for k, v in _REGISTRY.items()}
