from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_qareference_quality_method_variant'),
    ]

    operations = [
        migrations.AddField(
            model_name='tokenusagelog',
            name='usage_breakdown',
            field=models.JSONField(blank=True, default=dict, verbose_name='分模型用量'),
        ),
        migrations.AddField(
            model_name='tokenusagelog',
            name='pricing_version',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='影子计费版本'),
        ),
        migrations.AddField(
            model_name='tokenusagelog',
            name='shadow_credits',
            field=models.IntegerField(blank=True, null=True, verbose_name='影子积分'),
        ),
        migrations.AddField(
            model_name='tokenusagelog',
            name='estimated_cost_cny',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True, verbose_name='估算成本（元）'),
        ),
    ]
