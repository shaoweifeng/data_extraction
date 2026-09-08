"""QA 图表所需的只读领域数据。"""

from core.models import QAReference
from core.quality.domain.methods import get_method_config


def build_chart_data(project, quality_method, ref_ids=None):
    """
    计算图表所需的数据结构（不渲染图片）。
    返回 (traffic_light_data, proportion_data, bias_domains, applic_domains, method_cfg)
    """
    method_cfg = get_method_config(quality_method)
    domains        = method_cfg['domains']
    bias_domains   = [d for d in domains if d['has_bias_risk']]
    applic_domains = [d for d in domains if d['has_applicability']]

    qs = QAReference.objects.filter(
        project=project, quality_method=quality_method
    ).prefetch_related('domain_results')
    if ref_ids:
        qs = qs.filter(pk__in=ref_ids)

    traffic_light_data = []
    for ref in qs:
        domain_map = {dr.domain: dr for dr in ref.domain_results.all()}
        row = {
            'ref_id': ref.id, 'title': ref.title,
            'first_author': ref.first_author, 'year': ref.year,
            'review_status': ref.review_status,
            'bias_risk': {}, 'applicability': {},
        }
        for d in bias_domains:
            dr = domain_map.get(d['key'])
            row['bias_risk'][d['key']] = dr.bias_risk_result if dr else 'pending'
        for d in applic_domains:
            dr = domain_map.get(d['key'])
            row['applicability'][d['key']] = dr.applicability_result if dr else 'pending'
        traffic_light_data.append(row)

    proportion_data = {}

    def _add_proportion(domain, result_type):
        k = domain['key']
        output_key = k if result_type == 'bias_risk' else f'app_{k}'
        result_bucket = 'bias_risk' if result_type == 'bias_risk' else 'applicability'
        confirmed_refs = [r for r in traffic_light_data if r['review_status'] == 'confirmed']
        counts = {'low': 0, 'high': 0, 'unclear': 0, 'pending': 0}
        for r in confirmed_refs:
            val = r[result_bucket].get(k) or 'pending'
            if val in counts:
                counts[val] += 1
        total = max(1, len(confirmed_refs))
        proportion_data[output_key] = {
            'domain_name':    domain['name'],
            'domain_name_en': domain.get('name_en', domain['name']),
            'result_type': result_type,
            'counts': counts,
            'percentages': {k2: round(v / total * 100, 1) for k2, v in counts.items()},
        }

    for d in bias_domains:
        _add_proportion(d, 'bias_risk')
    for d in applic_domains:
        _add_proportion(d, 'applicability')

    return traffic_light_data, proportion_data, bias_domains, applic_domains, method_cfg
