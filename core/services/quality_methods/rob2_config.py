"""
RoB 2 信号问题配置（预留框架）
适用于随机对照试验（Sterne et al., 2019）
当前状态：AI评价暂不支持，信号问题配置占位，待补充完整
"""


def get_config() -> dict:
    return {
        'key':          'ROB2',
        'name':         'RoB 2',
        'description':  '适用于随机对照试验（RCT）的偏倚风险评价工具（Sterne et al., 2019）',
        'ai_supported': False,  # 暂不支持AI评价，前端显示提示
        'domains': [
            {'key': 'randomization',   'name': '随机化过程',           'has_bias_risk': True, 'has_applicability': False, 'order': 1},
            {'key': 'deviations',      'name': '偏离预期干预',          'has_bias_risk': True, 'has_applicability': False, 'order': 2},
            {'key': 'missing_data',    'name': '结局数据缺失',          'has_bias_risk': True, 'has_applicability': False, 'order': 3},
            {'key': 'outcome_measure', 'name': '结局测量',              'has_bias_risk': True, 'has_applicability': False, 'order': 4},
            {'key': 'reported_result', 'name': '选择性报告结果',        'has_bias_risk': True, 'has_applicability': False, 'order': 5},
        ],
        'signal_items': [],  # 待补充
        'domain_judge_rules': {},
    }
