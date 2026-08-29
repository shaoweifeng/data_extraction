"""
NOS（Newcastle-Ottawa Scale）信号问题配置
适用于队列研究（cohort）和病例对照研究（case_control）
初版：提供基本框架和核心条目，完整列表待用户提供后补充
"""

_DOMAINS_COHORT = [
    {'key': 'selection',     'name': '选择（Selection）',     'has_bias_risk': True, 'has_applicability': False, 'order': 1},
    {'key': 'comparability', 'name': '可比性（Comparability）','has_bias_risk': True, 'has_applicability': False, 'order': 2},
    {'key': 'outcome',       'name': '结局（Outcome）',        'has_bias_risk': True, 'has_applicability': False, 'order': 3},
]

_DOMAINS_CASE_CONTROL = [
    {'key': 'selection',     'name': '选择（Selection）',     'has_bias_risk': True, 'has_applicability': False, 'order': 1},
    {'key': 'comparability', 'name': '可比性（Comparability）','has_bias_risk': True, 'has_applicability': False, 'order': 2},
    {'key': 'exposure',      'name': '暴露（Exposure）',       'has_bias_risk': True, 'has_applicability': False, 'order': 3},
]

# NOS 评分制：每项 1 星（部分项最多 2 星），满分 9 星
# 这里将选项统一为：★（得分）/ ✗（不得分），前端可映射为中文

_SIGNAL_ITEMS_COHORT = [
    # ── 选择（Selection）────────────────────────────────────────
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_repr_exposed',
        'signal_question': '暴露队列的代表性',
        'signal_description': '暴露队列是否真正代表社区中的平均暴露人群，或至少有某些独立的外部确认。',
        'options': ['★ 真正代表社区平均暴露人群', '★ 有一定代表性（如患者群体）', '✗ 选定的群体（如护士、志愿者）', '✗ 无描述'],
        'order': 1,
    },
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_repr_unexposed',
        'signal_question': '非暴露队列的选取',
        'signal_description': '非暴露队列是否来自与暴露队列相同的社区。',
        'options': ['★ 来自同一社区', '★ 来自同一来源', '✗ 无描述'],
        'order': 2,
    },
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_ascertainment',
        'signal_question': '暴露的确定方式',
        'signal_description': '暴露是否通过安全记录（如外科记录）、结构化访谈或仅靠书面自我报告确定。',
        'options': ['★ 安全记录（如外科记录）', '★ 结构化访谈', '✗ 书面自我报告', '✗ 无描述'],
        'order': 3,
    },
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_outcome_absent',
        'signal_question': '研究开始时结局指标尚未出现',
        'signal_description': '是否证实研究开始时感兴趣的结局指标尚未出现。',
        'options': ['★ 是', '✗ 否'],
        'order': 4,
    },
    # ── 可比性（Comparability）──────────────────────────────────
    {
        'domain':      'comparability',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_compare',
        'signal_question': '基于设计或分析的队列可比性',
        'signal_description': '研究是否在设计或分析中控制了最重要的混杂因素，以及是否控制了其他混杂因素。',
        'options': ['★★ 控制了最重要因素且控制了其他因素', '★ 仅控制了最重要因素', '✗ 未控制混杂因素'],
        'order': 5,
    },
    # ── 结局（Outcome）──────────────────────────────────────────
    {
        'domain':      'outcome',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_outcome_assess',
        'signal_question': '结局指标评估',
        'signal_description': '结局是否通过独立盲法评估、记录关联或自我报告确定。',
        'options': ['★ 独立盲法评估', '★ 记录关联', '✗ 自我报告', '✗ 无描述'],
        'order': 6,
    },
    {
        'domain':      'outcome',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_followup_length',
        'signal_question': '随访时间是否足够长',
        'signal_description': '随访时间是否足够长，以便结局指标出现。',
        'options': ['★ 是', '✗ 否'],
        'order': 7,
    },
    {
        'domain':      'outcome',
        'result_type': 'bias_risk',
        'signal_key':  'cohort_followup_complete',
        'signal_question': '随访完整性',
        'signal_description': '随访是否足够完整，或失访是否有合理描述。',
        'options': ['★ 随访完整', '★ 失访率<20%且有描述', '✗ 失访率>20%', '✗ 无描述'],
        'order': 8,
    },
]

_SIGNAL_ITEMS_CASE_CONTROL = [
    # ── 选择（Selection）────────────────────────────────────────
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cc_case_def',
        'signal_question': '病例定义是否充分',
        'signal_description': '病例是否有独立验证，或仅依赖自我报告或档案记录。',
        'options': ['★ 有独立验证', '★ 仅依赖档案记录', '✗ 无描述'],
        'order': 1,
    },
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cc_repr',
        'signal_question': '病例的代表性',
        'signal_description': '是否为某一疾病系列中连续的代表性病例。',
        'options': ['★ 连续代表性系列', '★ 潜在代表性但非连续', '✗ 非代表性', '✗ 无描述'],
        'order': 2,
    },
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cc_control_selection',
        'signal_question': '对照的选取',
        'signal_description': '对照是否来自与病例相同的社区，且无所研究的疾病。',
        'options': ['★ 来自社区且无该疾病', '★ 来自医院且无该疾病', '✗ 无描述'],
        'order': 3,
    },
    {
        'domain':      'selection',
        'result_type': 'bias_risk',
        'signal_key':  'cc_control_nonexposed',
        'signal_question': '对照的定义',
        'signal_description': '对照是否经过验证无所研究的疾病。',
        'options': ['★ 有验证', '✗ 无验证'],
        'order': 4,
    },
    # ── 可比性（Comparability）──────────────────────────────────
    {
        'domain':      'comparability',
        'result_type': 'bias_risk',
        'signal_key':  'cc_compare',
        'signal_question': '基于设计或分析的病例-对照可比性',
        'signal_description': '研究是否控制了最重要的混杂因素及其他混杂因素。',
        'options': ['★★ 控制了最重要因素且控制了其他因素', '★ 仅控制了最重要因素', '✗ 未控制混杂因素'],
        'order': 5,
    },
    # ── 暴露（Exposure）─────────────────────────────────────────
    {
        'domain':      'exposure',
        'result_type': 'bias_risk',
        'signal_key':  'cc_exposure_ascertain',
        'signal_question': '暴露的确定方式',
        'signal_description': '暴露是否通过安全记录、结构化访谈（盲法）、访谈（无盲法）或书面自我报告确定。',
        'options': ['★ 安全记录', '★ 结构化访谈（盲法）', '✗ 访谈（无盲法）', '✗ 书面自我报告', '✗ 无描述'],
        'order': 6,
    },
    {
        'domain':      'exposure',
        'result_type': 'bias_risk',
        'signal_key':  'cc_nonresponse',
        'signal_question': '病例和对照的无应答率相同',
        'signal_description': '病例组和对照组的无应答率是否相同，或是否描述了无应答者。',
        'options': ['★ 两组应答率相同', '★ 描述了无应答者', '✗ 未描述'],
        'order': 7,
    },
]


def get_config() -> dict:
    return {
        'key':          'NOS',
        'name':         'NOS',
        'description':  'Newcastle-Ottawa Scale，适用于队列研究和病例对照研究（Wells et al.）',
        'ai_supported': True,
        'domains':      _DOMAINS_COHORT,           # 默认使用队列研究领域
        'domains_cohort':       _DOMAINS_COHORT,
        'domains_case_control': _DOMAINS_CASE_CONTROL,
        'signal_items': _SIGNAL_ITEMS_COHORT,      # 默认队列研究
        'signal_items_cohort':       _SIGNAL_ITEMS_COHORT,
        'signal_items_case_control': _SIGNAL_ITEMS_CASE_CONTROL,
        'domain_judge_rules': {
            'bias_risk': {
                'low':     '★ 评分 ≥ 7（满分9星），方法学质量较高',
                'high':    '★ 评分 ≤ 4，存在明显方法学缺陷',
                'unclear': '★ 评分 5-6，质量中等',
            },
        },
    }
