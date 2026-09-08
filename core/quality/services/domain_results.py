"""QA 信号问题到领域结果的聚合服务。"""

from core.models import QADomainResult, QAReference
from core.quality.domain.methods import get_method_config


def recalculate_domain_results(qa_ref: QAReference):
    """
    根据已确认的信号问题，重新计算并更新 QADomainResult。
    规则（QUADAS-2 / NOS 通用）：
      - bias_risk: 任意一条 confirmed human_judgment 中有风险倾向 → high；
                   全部 low → low；否则 unclear；未全部确认 → pending
      - applicability: 同上逻辑
    """
    items = list(qa_ref.signal_items.all())
    method_cfg = None
    try:
        method_cfg = get_method_config(qa_ref.quality_method)
    except Exception:
        pass

    # 按 domain 分组
    domains = {}
    for item in items:
        domains.setdefault(item.domain, []).append(item)

    for domain_key, domain_items in domains.items():
        # 找领域名
        domain_name = domain_key
        if method_cfg:
            for d in method_cfg.get('domains', []):
                if d['key'] == domain_key:
                    domain_name = d['name']
                    break

        bias_items  = [i for i in domain_items if i.result_type == 'bias_risk']
        applic_items = [i for i in domain_items if i.result_type == 'applicability']

        def calc_bias(signal_list):
            """
            偏倚风险判断（支持多种评价方法）：
            QUADAS-2：选项为 是/否/不清楚/不适用
              - '否' → high；'不清楚' → unclear；'是'/'不适用' → low
            NOS：选项为以 ★/✗ 开头的完整字符串
              - 含 '✗' 开头 → high；★ → low
            """
            if not signal_list:
                return 'na', True
            confirmed = [i for i in signal_list if i.is_confirmed]
            if len(confirmed) < len(signal_list):
                return 'pending', False
            judgments = [i.human_judgment for i in confirmed]
            # 检查高风险：精确值'否' 或 以'✗'开头的 NOS 选项
            if any(j == '否' or j.startswith('✗') for j in judgments):
                return 'high', True
            # 检查不清楚
            if any(j == '不清楚' for j in judgments):
                return 'unclear', True
            return 'low', True

        def calc_applicability(signal_list):
            """
            适用性：选项为 低/高/不清楚（QUADAS-2）
            有'高' → high；有'不清楚' → unclear；否则 low
            """
            if not signal_list:
                return 'na', True
            confirmed = [i for i in signal_list if i.is_confirmed]
            if len(confirmed) < len(signal_list):
                return 'pending', False
            judgments = [i.human_judgment for i in confirmed]
            if any(j == '高' for j in judgments):
                return 'high', True
            if any(j == '不清楚' for j in judgments):
                return 'unclear', True
            return 'low', True

        bias_result, bias_confirmed = calc_bias(bias_items)
        applic_result, applic_confirmed = calc_applicability(applic_items)

        QADomainResult.objects.update_or_create(
            qa_ref=qa_ref,
            domain=domain_key,
            defaults={
                'domain_name':                 domain_name,
                'bias_risk_result':            bias_result,
                'applicability_result':        applic_result,
                'bias_all_confirmed':          bias_confirmed,
                'applicability_all_confirmed': applic_confirmed,
            },
        )

    # 更新文献级 review_status
    all_items = list(qa_ref.signal_items.all())
    if all_items:
        confirmed_count = sum(1 for i in all_items if i.is_confirmed)
        if confirmed_count == 0:
            new_status = 'not_started'
        elif confirmed_count == len(all_items):
            new_status = 'confirmed'
        else:
            new_status = 'partial'
        QAReference.objects.filter(pk=qa_ref.pk).update(review_status=new_status)
