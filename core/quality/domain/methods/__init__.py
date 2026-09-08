"""
质量评价方法配置包
每种方法对应一个 _config.py 文件，返回 get_config() 标准结构
"""
from .quadas2_config import get_config as get_quadas2_config
from .nos_config import get_config as get_nos_config
from .rob2_config import get_config as get_rob2_config
from .amstar2_config import get_config as get_amstar2_config
from .robins_i_config import get_config as get_robins_i_config

METHOD_REGISTRY = {
    'QUADAS2':  get_quadas2_config,
    'NOS':      get_nos_config,
    'ROB2':     get_rob2_config,
    'AMSTAR2':  get_amstar2_config,
    'ROBINS_I': get_robins_i_config,
}

METHOD_DISPLAY = {
    'QUADAS2':  'QUADAS-2',
    'NOS':      'NOS',
    'ROB2':     'RoB 2',
    'AMSTAR2':  'AMSTAR 2',
    'ROBINS_I': 'ROBINS-I',
}

# 当前已有完整AI评价支持的方法
AI_SUPPORTED_METHODS = {'QUADAS2', 'NOS'}


def get_method_config(method_key: str) -> dict:
    """
    获取指定质量评价方法的完整配置
    返回结构：
    {
      "key": "QUADAS2",
      "name": "QUADAS-2",
      "description": "...",
      "domains": [...],        # 领域列表（有序）
      "signal_items": [...],   # 信号问题列表（含 domain/result_type/signal_key/...）
      "ai_supported": True,
    }
    """
    factory = METHOD_REGISTRY.get(method_key)
    if factory is None:
        raise ValueError(f"未知的质量评价方法: {method_key}")
    return factory()


def get_all_methods_meta() -> list:
    """返回所有方法的基本元信息（前端方法选择下拉用）"""
    result = []
    for key, factory in METHOD_REGISTRY.items():
        cfg = factory()
        result.append({
            'key': key,
            'name': cfg['name'],
            'description': cfg['description'],
            'ai_supported': cfg['ai_supported'],
            'signal_count': len(cfg['signal_items']),
        })
    return result


__all__ = ['get_method_config', 'get_all_methods_meta', 'METHOD_REGISTRY', 'AI_SUPPORTED_METHODS']
