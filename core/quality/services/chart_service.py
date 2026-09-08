"""QA 图表生成用例，不依赖 HTTP 或 Celery。"""

from django.utils import timezone

from core.models import QAChart
from core.quality.renderers.matplotlib_charts import render_proportion, render_traffic_light
from core.quality.services.chart_data import build_chart_data


def generate_chart_payload(
    project,
    quality_method,
    ref_ids=None,
    study_labels=None,
    orientation='horizontal',
    lang='zh',
):
    """构建领域数据并使用 Python/Matplotlib 渲染两张 PNG data URL。"""
    traffic, proportion, bias_domains, applic_domains, method_cfg = build_chart_data(
        project, quality_method, ref_ids or None
    )
    chart = QAChart.objects.filter(
        project=project, quality_method=quality_method
    ).order_by('-created_at').first()
    if chart is None:
        chart = QAChart(project=project, quality_method=quality_method)
    chart.chart_types = ['traffic_light', 'proportion', 'detail']
    chart.ref_ids = [row['ref_id'] for row in traffic]
    chart.generated_at = timezone.now()
    chart.save()
    traffic_image = render_traffic_light(
        traffic,
        bias_domains,
        applic_domains,
        method_cfg['name'],
        quality_method=quality_method,
        study_labels=study_labels or {},
        orientation=orientation,
        lang=lang,
    )
    proportion_image = render_proportion(
        proportion,
        method_cfg['name'],
        quality_method=quality_method,
        traffic_light_data=traffic,
        bias_domains=bias_domains,
        applic_domains=applic_domains,
        study_labels=study_labels or {},
        lang=lang,
    )
    return {
        'chart': chart,
        'quality_method': quality_method,
        'method_name': method_cfg['name'],
        'bias_domains': bias_domains,
        'applic_domains': applic_domains,
        'traffic_light': traffic,
        'proportion': proportion,
        'generated_at': chart.generated_at.isoformat(),
        'unconfirmed_count': sum(1 for row in traffic if row['review_status'] != 'confirmed'),
        'traffic_light_image': traffic_image,
        'proportion_image': proportion_image,
    }
