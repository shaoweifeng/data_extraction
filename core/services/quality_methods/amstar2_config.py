"""AMSTAR 2 配置（预留框架）"""


def get_config() -> dict:
    return {
        'key':          'AMSTAR2',
        'name':         'AMSTAR 2',
        'description':  '适用于系统综述/Meta分析的方法学质量评价（Shea et al., 2017）',
        'ai_supported': False,
        'domains': [
            {'key': 'amstar2', 'name': 'AMSTAR 2 条目', 'has_bias_risk': True, 'has_applicability': False, 'order': 1},
        ],
        'signal_items': [],
        'domain_judge_rules': {},
    }
