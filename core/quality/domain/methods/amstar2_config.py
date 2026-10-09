"""AMSTAR 2 配置（预留框架）"""


def get_config() -> dict:
    return {
        'key':          'AMSTAR2',
        'name':         'AMSTAR 2',
        'description':  '适用于系统综述/Meta分析的方法学质量评价（Shea et al., 2017）',
        'config_version': '0.1',
        'ai_supported': False,
        'ai_unavailable_reason': '尚未配置完整的 AMSTAR 2 条目和关键条目汇总规则',
        'evaluation_strategy': 'domain_batches',
        'aggregation_policy': 'quadas2_v1',
        'domains': [
            {'key': 'amstar2', 'name': 'AMSTAR 2 条目', 'name_en': 'AMSTAR 2 Items', 'has_bias_risk': True, 'has_applicability': False, 'order': 1},
        ],
        'signal_items': [],
        'domain_judge_rules': {},
    }
