from django.db import migrations


SOURCE_VERSION = 'credit-v2-draft-2026-10-13'
PUBLISHED_VERSION = 'credit-v2-2026-10-14'


def publish_model_billing_rates(apps, schema_editor):
    ModelBillingRate = apps.get_model('core', 'ModelBillingRate')
    source_rates = ModelBillingRate.objects.filter(
        version=SOURCE_VERSION,
    ).order_by('rate_key')

    for source in source_rates:
        suffix = source.rate_key.removeprefix('credit-v2-draft:')
        ModelBillingRate.objects.get_or_create(
            rate_key=f'credit-v2-2026-10-14:{suffix}',
            defaults={
                'version': PUBLISHED_VERSION,
                'status': 'published',
                'provider': source.provider,
                'region': source.region,
                'service_tier': source.service_tier,
                'model_id': source.model_id,
                'provider_model': source.provider_model,
                'context_min_tokens': source.context_min_tokens,
                'context_max_tokens': source.context_max_tokens,
                'currency': source.currency,
                'fx_cny_per_unit': source.fx_cny_per_unit,
                'input_cny_per_million': source.input_cny_per_million,
                'output_cny_per_million': source.output_cny_per_million,
                'cache_read_cny_per_million': source.cache_read_cny_per_million,
                'cache_write_cny_per_million': source.cache_write_cny_per_million,
                'effective_from': source.effective_from,
                'effective_until': source.effective_until,
                'source_url': source.source_url,
                'notes': f'首版正式费率；发布自 {SOURCE_VERSION}。',
            },
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0040_publish_personal_plan_v1')]
    operations = [
        migrations.RunPython(
            publish_model_billing_rates,
            migrations.RunPython.noop,
        ),
    ]
