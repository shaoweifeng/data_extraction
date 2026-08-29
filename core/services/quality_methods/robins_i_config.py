"""ROBINS-I 配置（预留框架）"""


def get_config() -> dict:
    return {
        'key':          'ROBINS_I',
        'name':         'ROBINS-I',
        'description':  '适用于非随机干预研究的偏倚风险评价工具（Sterne et al., 2016）',
        'ai_supported': False,
        'domains': [
            {'key': 'confounding',   'name': '混杂',       'has_bias_risk': True, 'has_applicability': False, 'order': 1},
            {'key': 'selection',     'name': '研究对象选择', 'has_bias_risk': True, 'has_applicability': False, 'order': 2},
            {'key': 'classification','name': '干预分类',    'has_bias_risk': True, 'has_applicability': False, 'order': 3},
            {'key': 'deviations',    'name': '偏离预期干预', 'has_bias_risk': True, 'has_applicability': False, 'order': 4},
            {'key': 'missing_data',  'name': '数据缺失',    'has_bias_risk': True, 'has_applicability': False, 'order': 5},
            {'key': 'outcome',       'name': '结局测量',    'has_bias_risk': True, 'has_applicability': False, 'order': 6},
            {'key': 'reported',      'name': '选择性报告',  'has_bias_risk': True, 'has_applicability': False, 'order': 7},
        ],
        'signal_items': [],
        'domain_judge_rules': {},
    }
