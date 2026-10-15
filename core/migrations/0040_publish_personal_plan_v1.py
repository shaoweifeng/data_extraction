from django.db import migrations


def publish_personal_plans(apps, schema_editor):
    PlanCatalog = apps.get_model('core', 'PlanCatalog')
    PlanPriceVersion = apps.get_model('core', 'PlanPriceVersion')
    plans = (
        ('LITE', 'Lite', '个人轻量使用', '399.00', 20000, 4, 5),
        ('PLUS', 'Plus', '个人进阶使用', '599.00', 50000, 8, 10),
        ('PRO', 'Pro', '个人高强度使用', '899.00', 120000, 16, 20),
    )
    for code, name, description, price, credits, slots, projects in plans:
        plan, _ = PlanCatalog.objects.update_or_create(
            code=code,
            defaults={'name': name, 'description': description, 'is_active': True},
        )
        PlanPriceVersion.objects.get_or_create(
            plan=plan,
            version='personal-v1-2026-10-13',
            defaults={
                'status': 'published',
                'monthly_price_cny': price,
                'valid_months': 1,
                'included_credits': credits,
                'ai_call_slots': slots,
                'project_limit': projects,
            },
        )


def unpublish_personal_plans(apps, schema_editor):
    apps.get_model('core', 'PlanPriceVersion').objects.filter(
        version='personal-v1-2026-10-13',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0039_credit_ledger_reservations')]
    operations = [migrations.RunPython(publish_personal_plans, unpublish_personal_plans)]
