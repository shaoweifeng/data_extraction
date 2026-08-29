"""
QUADAS-2 信号问题完整配置
共11条信号问题，4个领域，风险偏倚 + 适用性担忧
"""

_DOMAINS = [
    {
        'key':        'patient_selection',
        'name':       '患者选择',
        'has_bias_risk':     True,
        'has_applicability': True,
        'order':      1,
    },
    {
        'key':        'index_test',
        'name':       '待评价试验',
        'has_bias_risk':     True,
        'has_applicability': True,
        'order':      2,
    },
    {
        'key':        'reference_standard',
        'name':       '参考标准',
        'has_bias_risk':     True,
        'has_applicability': True,
        'order':      3,
    },
    {
        'key':        'flow_timing',
        'name':       '流程与时间',
        'has_bias_risk':     True,
        'has_applicability': False,  # 流程与时间无适用性担忧
        'order':      4,
    },
]

_SIGNAL_ITEMS = [
    # ── 患者选择（patient_selection） ─────────────────────────────
    {
        'domain':      'patient_selection',
        'result_type': 'bias_risk',
        'signal_key':  'ps_consecutive',
        'signal_question': '是否纳入了连续或随机样本？',
        'signal_description': '判断研究对象是否为连续入组或随机抽样，避免选择性纳入患者。',
        'options': ['是', '否', '不清楚'],
        'order': 1,
    },
    {
        'domain':      'patient_selection',
        'result_type': 'bias_risk',
        'signal_key':  'ps_avoid_cc',
        'signal_question': '是否避免病例-对照设计？',
        'signal_description': '判断研究是否避免只选取典型病例和健康对照，减少夸大诊断准确性的风险。',
        'options': ['是', '否', '不清楚'],
        'order': 2,
    },
    {
        'domain':      'patient_selection',
        'result_type': 'bias_risk',
        'signal_key':  'ps_avoid_exclusion',
        'signal_question': '是否避免不恰当排除？',
        'signal_description': '判断研究是否存在不合理排除患者，从而影响样本代表性。',
        'options': ['是', '否', '不清楚'],
        'order': 3,
    },
    {
        'domain':      'patient_selection',
        'result_type': 'applicability',
        'signal_key':  'ps_applicability',
        'signal_question': '纳入患者是否与研究问题匹配？',
        'signal_description': '判断研究对象的疾病阶段、就诊场景、既往检测和目标人群是否符合本综述问题。',
        'options': ['低', '高', '不清楚'],
        'order': 4,
    },
    # ── 待评价试验（index_test） ──────────────────────────────────
    {
        'domain':      'index_test',
        'result_type': 'bias_risk',
        'signal_key':  'it_blinded',
        'signal_question': '待评价试验结果解释时是否未知参考标准结果？',
        'signal_description': '判断解释待评价试验结果时是否进行了盲法，避免受到参考标准结果影响。',
        'options': ['是', '否', '不清楚'],
        'order': 5,
    },
    {
        'domain':      'index_test',
        'result_type': 'bias_risk',
        'signal_key':  'it_threshold_preset',
        'signal_question': '如使用阈值，阈值是否预先设定？',
        'signal_description': '判断诊断阈值是否在研究前确定，避免根据结果事后选择最佳阈值。',
        'options': ['是', '否', '不清楚', '不适用'],
        'order': 6,
    },
    {
        'domain':      'index_test',
        'result_type': 'applicability',
        'signal_key':  'it_applicability',
        'signal_question': '待评价试验的执行或解释是否与研究问题匹配？',
        'signal_description': '判断试验方法、设备、操作者、阈值和解释方式是否符合本综述关注的实际应用场景。',
        'options': ['低', '高', '不清楚'],
        'order': 7,
    },
    # ── 参考标准（reference_standard） ───────────────────────────
    {
        'domain':      'reference_standard',
        'result_type': 'bias_risk',
        'signal_key':  'rs_classify_correctly',
        'signal_question': '参考标准是否能正确区分目标疾病状态？',
        'signal_description': '判断参考标准是否足够准确，能够正确识别是否存在目标疾病。',
        'options': ['是', '否', '不清楚'],
        'order': 8,
    },
    {
        'domain':      'reference_standard',
        'result_type': 'bias_risk',
        'signal_key':  'rs_blinded',
        'signal_question': '参考标准结果解释时是否未知待评价试验结果？',
        'signal_description': '判断解释参考标准时是否进行了盲法，避免受到待评价试验结果影响。',
        'options': ['是', '否', '不清楚'],
        'order': 9,
    },
    {
        'domain':      'reference_standard',
        'result_type': 'applicability',
        'signal_key':  'rs_applicability',
        'signal_question': '参考标准定义的目标疾病是否与研究问题匹配？',
        'signal_description': '判断参考标准所定义的疾病状态是否与本综述关注的目标疾病一致。',
        'options': ['低', '高', '不清楚'],
        'order': 10,
    },
    # ── 流程与时间（flow_timing） ─────────────────────────────────
    {
        'domain':      'flow_timing',
        'result_type': 'bias_risk',
        'signal_key':  'ft_interval_appropriate',
        'signal_question': '待评价试验与参考标准之间的时间间隔是否合适？',
        'signal_description': '判断两种检测之间是否间隔过长，导致疾病状态可能发生变化。',
        'options': ['是', '否', '不清楚'],
        'order': 11,
    },
    {
        'domain':      'flow_timing',
        'result_type': 'bias_risk',
        'signal_key':  'ft_all_received_rs',
        'signal_question': '是否所有患者都接受了参考标准？',
        'signal_description': '判断是否所有入组患者都接受了参考标准验证，避免部分验证偏倚。',
        'options': ['是', '否', '不清楚'],
        'order': 12,
    },
    {
        'domain':      'flow_timing',
        'result_type': 'bias_risk',
        'signal_key':  'ft_same_rs',
        'signal_question': '是否所有患者都接受了相同参考标准？',
        'signal_description': '判断不同患者是否接受一致的参考标准，避免差异验证偏倚。',
        'options': ['是', '否', '不清楚'],
        'order': 13,
    },
    {
        'domain':      'flow_timing',
        'result_type': 'bias_risk',
        'signal_key':  'ft_all_analyzed',
        'signal_question': '是否所有患者都纳入分析？',
        'signal_description': '判断是否存在未解释的脱落或排除，避免分析不完整引入偏倚。',
        'options': ['是', '否', '不清楚'],
        'order': 14,
    },
]

# 领域最终判断规则说明（供 AI prompt 使用）
_DOMAIN_JUDGE_RULES = {
    'bias_risk': {
        'low':     '该领域所有或大多数信号问题结果支持不存在明显偏倚',
        'high':    '一个或多个关键信号问题提示可能存在明显偏倚（如答案为"否"）',
        'unclear': '信息不足或存在不清楚的信号问题，无法判断',
    },
    'applicability': {
        'low':     '与本综述研究问题匹配，无明显担忧',
        'high':    '与本综述研究问题存在明显不匹配',
        'unclear': '信息不足，无法判断是否匹配',
    },
}


def get_config() -> dict:
    return {
        'key':          'QUADAS2',
        'name':         'QUADAS-2',
        'description':  '适用于诊断准确性研究的质量评价工具（Whiting et al., 2011）',
        'ai_supported': True,
        'domains':      _DOMAINS,
        'signal_items': _SIGNAL_ITEMS,
        'domain_judge_rules': _DOMAIN_JUDGE_RULES,
    }
