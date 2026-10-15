from django.db import migrations


PRICING_VERSION = 'credit-v2-draft-2026-10-13'
RATE_KEY = 'credit-v2-draft:deepseek-v4-flash:all'


def use_observed_provider_model(apps, schema_editor):
    ModelBillingRate = apps.get_model('core', 'ModelBillingRate')
    ModelBillingRate.objects.filter(
        version=PRICING_VERSION,
        rate_key=RATE_KEY,
        status='draft',
        provider_model='deepseek-v4-flash',
    ).update(provider_model='deepseek-flash')


def restore_configured_provider_model(apps, schema_editor):
    ModelBillingRate = apps.get_model('core', 'ModelBillingRate')
    ModelBillingRate.objects.filter(
        version=PRICING_VERSION,
        rate_key=RATE_KEY,
        status='draft',
        provider_model='deepseek-flash',
    ).update(provider_model='deepseek-v4-flash')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0037_plancatalog_rechargecode_batch_no_and_more'),
    ]

    operations = [
        migrations.RunPython(
            use_observed_provider_model,
            restore_configured_provider_model,
        ),
    ]
