"""QA chart data assembled through the shared result-mapping contract."""

from core.models import QAReference
from core.quality.services.result_mapping import (
    build_proportion_data,
    quality_result_schema,
    reference_result_row,
)


def build_chart_data(project, quality_method, ref_ids=None):
    schema = quality_result_schema(quality_method)
    queryset = QAReference.objects.filter(
        project=project,
        quality_method=quality_method,
    ).prefetch_related('domain_results')
    if ref_ids:
        queryset = queryset.filter(pk__in=ref_ids)
    rows = [reference_result_row(reference, schema) for reference in queryset]
    proportions = build_proportion_data(rows, schema)
    return (
        rows,
        proportions,
        schema['bias_domains'],
        schema['applicability_domains'],
        schema['method'],
    )
