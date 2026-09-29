"""Single mapping contract shared by QA charts, spreadsheets and reports."""

from core.quality.domain.methods import get_method_config


QUALITY_RESULTS = ('low', 'high', 'unclear', 'pending', 'na')


def quality_result_schema(quality_method: str) -> dict:
    method = get_method_config(quality_method)
    domains = method['domains']
    return {
        'method': method,
        'bias_domains': [domain for domain in domains if domain['has_bias_risk']],
        'applicability_domains': [domain for domain in domains if domain['has_applicability']],
    }


def normalize_quality_result(value) -> str:
    return value if value in QUALITY_RESULTS else 'pending'


def map_reference_results(reference, schema: dict) -> dict:
    domain_map = {result.domain: result for result in reference.domain_results.all()}
    bias_risk = {}
    applicability = {}
    for domain in schema['bias_domains']:
        result = domain_map.get(domain['key'])
        bias_risk[domain['key']] = normalize_quality_result(
            result.bias_risk_result if result else None,
        )
    for domain in schema['applicability_domains']:
        result = domain_map.get(domain['key'])
        applicability[domain['key']] = normalize_quality_result(
            result.applicability_result if result else None,
        )
    return {'bias_risk': bias_risk, 'applicability': applicability}


def reference_result_row(reference, schema: dict) -> dict:
    mapped = map_reference_results(reference, schema)
    return {
        'ref_id': reference.id,
        'title': reference.title,
        'first_author': reference.first_author,
        'year': reference.year,
        'review_status': reference.review_status,
        **mapped,
    }


def build_proportion_data(rows: list[dict], schema: dict) -> dict:
    confirmed = [row for row in rows if row['review_status'] == 'confirmed']
    output = {}
    for bucket, domains, prefix in (
        ('bias_risk', schema['bias_domains'], ''),
        ('applicability', schema['applicability_domains'], 'app_'),
    ):
        for domain in domains:
            counts = {result: 0 for result in QUALITY_RESULTS}
            for row in confirmed:
                counts[normalize_quality_result(row[bucket].get(domain['key']))] += 1
            total = sum(counts.values())
            output[f"{prefix}{domain['key']}"] = {
                'domain_name': domain['name'],
                'domain_name_en': domain.get('name_en', domain['name']),
                'result_type': bucket,
                'counts': counts,
                'percentages': {
                    result: round(count / total * 100, 1) if total else 0.0
                    for result, count in counts.items()
                },
            }
    return output
