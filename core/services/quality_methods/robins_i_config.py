"""ROBINS-I 配置（预留框架）"""


def get_config() -> dict:
    return {
        'key':          'ROBINS_I',
        'name':         'ROBINS-I',
        'description':  '适用于非随机干预研究的偏倚风险评价工具（Sterne et al., 2016）',
        'ai_supported': False,
        'domains': [
            {'key': 'confounding',   'name': '混杂',       'name_en': 'Confounding',                'has_bias_risk': True, 'has_applicability': False, 'order': 1},
            {'key': 'selection',     'name': '研究对象选择', 'name_en': 'Selection of Participants',   'has_bias_risk': True, 'has_applicability': False, 'order': 2},
            {'key': 'classification','name': '干预分类',    'name_en': 'Classification of Interventions', 'has_bias_risk': True, 'has_applicability': False, 'order': 3},
            {'key': 'deviations',    'name': '偏离预期干预', 'name_en': 'Deviations from Interventions', 'has_bias_risk': True, 'has_applicability': False, 'order': 4},
            {'key': 'missing_data',  'name': '数据缺失',    'name_en': 'Missing Data',               'has_bias_risk': True, 'has_applicability': False, 'order': 5},
            {'key': 'outcome',       'name': '结局测量',    'name_en': 'Measurement of Outcomes',    'has_bias_risk': True, 'has_applicability': False, 'order': 6},
            {'key': 'reported',      'name': '选择性报告',  'name_en': 'Selection of Reported Results', 'has_bias_risk': True, 'has_applicability': False, 'order': 7},
        ],
        'signal_items': [],
        'domain_judge_rules': {},
    }
