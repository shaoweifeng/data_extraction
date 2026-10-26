from django.db import migrations


def seed(apps, schema_editor):
    Product = apps.get_model('core', 'AddonProduct')
    Version = apps.get_model('core', 'AddonProductVersion')
    rows = [
        ('CREDIT_10K', '10,000 积分包', 'CREDIT', 99, 10000, 0, 12, True, True),
        ('CREDIT_50K', '50,000 积分包', 'CREDIT', 399, 50000, 0, 12, True, True),
        ('CREDIT_100K', '100,000 积分包', 'CREDIT', 699, 100000, 0, 12, True, True),
        ('TRIAL_5K', '追加体验积分', 'TRIAL', 99, 5000, 0, 12, False, True),
        ('SLOTS_4', '4 并发升级', 'CONCURRENCY', 49, 0, 4, 1, True, False),
        ('SLOTS_8', '8 并发升级', 'CONCURRENCY', 99, 0, 8, 1, True, True),
        ('SLOTS_16', '16 并发升级', 'CONCURRENCY', 199, 0, 16, 1, True, True),
    ]
    for order, (code, name, kind, price, credits, slots, months, subscription, active) in enumerate(rows):
        product, _ = Product.objects.get_or_create(code=code, defaults={
            'name': name, 'kind': kind, 'is_active': active, 'sort_order': order,
        })
        Version.objects.get_or_create(version=f'{code.lower()}-2026-10-26', defaults={
            'product': product, 'kind': kind, 'status': 'published',
            'reference_price_cny': price, 'credits': credits, 'target_slots': slots,
            'valid_months': months, 'requires_subscription': subscription,
        })


class Migration(migrations.Migration):
    dependencies = [('core', '0048_addonproduct_alter_rechargecode_code_type_and_more')]
    # Keep issued versions on rollback; never delete commercial history.
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
