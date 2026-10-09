"""Validated registry for quality-assessment method configurations."""

from copy import deepcopy

from .quadas2_config import get_config as get_quadas2_config
from .nos_config import get_config as get_nos_config
from .rob2_config import get_config as get_rob2_config
from .amstar2_config import get_config as get_amstar2_config
from .robins_i_config import get_config as get_robins_i_config
from .schema import MethodConfigError, validate_method_config

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

_VALIDATED_CONFIGS = {
    key: validate_method_config(factory(), registry_key=key)
    for key, factory in METHOD_REGISTRY.items()
}


def ai_supported_method_keys() -> frozenset[str]:
    """Return method keys whose validated configuration enables AI evaluation."""
    return frozenset(
        key for key, config in _VALIDATED_CONFIGS.items()
        if config['ai_supported']
    )


def get_method_config(method_key: str, variant_key: str | None = None) -> dict:
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
    source = _VALIDATED_CONFIGS.get(method_key)
    if source is None:
        raise ValueError(f"未知的质量评价方法: {method_key}")
    config = deepcopy(source)
    variants = config.get('variants') or {}
    if variants:
        selected = variant_key or config['default_variant']
        if selected not in variants:
            raise ValueError(f'未知的 {method_key} 研究设计: {selected}')
        variant = config['variants'][selected]
        config['variant_key'] = selected
        config['variant_name'] = variant['name']
        config['domains'] = deepcopy(variant['domains'])
        config['signal_items'] = deepcopy(variant['signal_items'])
    elif variant_key:
        raise ValueError(f'{method_key} 不支持研究设计变体')
    return config


def method_supports_ai(method_key: str, variant_key: str | None = None) -> bool:
    try:
        return bool(get_method_config(method_key, variant_key)['ai_supported'])
    except ValueError:
        return False


def get_all_methods_meta() -> list:
    """返回所有方法的基本元信息（前端方法选择下拉用）"""
    result = []
    for key in METHOD_REGISTRY:
        cfg = get_method_config(key)
        variants = [
            {
                'key': variant_key,
                'name': variant['name'],
                'signal_count': len(variant['signal_items']),
            }
            for variant_key, variant in (cfg.get('variants') or {}).items()
        ]
        result.append({
            'key': key,
            'name': cfg['name'],
            'description': cfg['description'],
            'ai_supported': cfg['ai_supported'],
            'ai_unavailable_reason': cfg.get('ai_unavailable_reason', ''),
            'config_version': cfg['config_version'],
            'evaluation_strategy': cfg['evaluation_strategy'],
            'default_variant': cfg.get('default_variant', ''),
            'variants': variants,
            'signal_count': len(cfg['signal_items']),
        })
    return result


__all__ = [
    'METHOD_REGISTRY', 'MethodConfigError',
    'ai_supported_method_keys', 'get_all_methods_meta', 'get_method_config',
    'method_supports_ai', 'validate_method_config',
]
