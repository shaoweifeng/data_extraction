from django.db import migrations


VERSION = 'credit-v2-2026-10-14-r2'


def publish_verified_rates(apps, schema_editor):
    ModelBillingRate = apps.get_model('core', 'ModelBillingRate')
    qwen_source = 'https://help.aliyun.com/zh/model-studio/model-pricing'
    deepseek_source = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
    doubao_source = 'https://www.volcengine.com/docs/82379/1554682'
    rates = (
        # key suffix, provider, region, platform model, provider model, min, max,
        # input, output, cache read, cache write, source, note
        ('qwen3-7-flash:0-32768', 'qwen', 'cn-beijing',
         'qwen3-7-flash', 'qwen3.7-flash', 0, 32768,
         '0.200000', '0.800000', '0.040000', '0.250000', qwen_source,
         '华北2北京原价；缓存写入按显式缓存创建价。'),
        ('qwen3-7-flash:32769-262144', 'qwen', 'cn-beijing',
         'qwen3-7-flash', 'qwen3.7-flash', 32769, 262144,
         '0.600000', '2.400000', '0.120000', '0.750000', qwen_source,
         '华北2北京原价；缓存写入按显式缓存创建价。'),
        ('qwen3-7-flash:262145-1048576', 'qwen', 'cn-beijing',
         'qwen3-7-flash', 'qwen3.7-flash', 262145, 1048576,
         '1.200000', '4.800000', '0.240000', '1.500000', qwen_source,
         '华北2北京原价；缓存写入按显式缓存创建价。'),
        ('qwen3-7-plus:0-262144', 'qwen', 'cn-beijing',
         'qwen3-7-plus', 'qwen3.7-plus', 0, 262144,
         '2.000000', '8.000000', '0.400000', '2.500000', qwen_source,
         '华北2北京原价；补齐上下文阶梯与缓存价格。'),
        ('qwen3-7-plus:262145-1048576', 'qwen', 'cn-beijing',
         'qwen3-7-plus', 'qwen3.7-plus', 262145, 1048576,
         '6.000000', '24.000000', '1.200000', '7.500000', qwen_source,
         '华北2北京原价；补齐上下文阶梯与缓存价格。'),
        ('qwen3-7-max:all', 'qwen', 'cn-beijing',
         'qwen3-7-max', 'qwen3.7-max', 0, 0,
         '12.000000', '36.000000', '2.400000', '15.000000', qwen_source,
         '华北2北京原价；缓存价格已核验。'),
        ('deepseek-v4-flash:all', 'deepseek', 'global',
         'deepseek-v4-flash', 'deepseek-flash', 0, 0,
         '2.000000', '8.000000', '0.040000', '2.000000', deepseek_source,
         'DeepSeek V4.1 Flash 高峰价；旧平台ID保留用于兼容。'),
        ('deepseek-v4-pro:all', 'deepseek', 'global',
         'deepseek-v4-pro', 'deepseek-v4-pro', 0, 0,
         '9.000000', '27.000000', '0.300000', '9.000000', deepseek_source,
         'DeepSeek V4 Pro 高峰价；用于保守预估和稳定结算。'),
        ('doubao-seed-2-1-turbo:all', 'doubao', 'cn-beijing',
         'doubao-seed-2-1-turbo', 'doubao-seed-2-1-turbo-260628', 0, 0,
         '3.000000', '15.000000', '3.000000', '3.000000', doubao_source,
         '方舟按量实时推理公开原价；当前调用未启用缓存。'),
    )
    for row in rates:
        (suffix, provider, region, model_id, provider_model, context_min,
         context_max, input_price, output_price, cache_read, cache_write,
         source_url, notes) = row
        ModelBillingRate.objects.get_or_create(
            rate_key=f'{VERSION}:{suffix}',
            defaults={
                'version': VERSION,
                'status': 'published',
                'provider': provider,
                'region': region,
                'service_tier': 'standard',
                'model_id': model_id,
                'provider_model': provider_model,
                'context_min_tokens': context_min,
                'context_max_tokens': context_max,
                'currency': 'CNY',
                'fx_cny_per_unit': '1.000000',
                'input_cny_per_million': input_price,
                'output_cny_per_million': output_price,
                'cache_read_cny_per_million': cache_read,
                'cache_write_cny_per_million': cache_write,
                'source_url': source_url,
                'notes': notes,
            },
        )


def remove_verified_rates(apps, schema_editor):
    apps.get_model('core', 'ModelBillingRate').objects.filter(version=VERSION).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0041_publish_model_billing_rates_v2')]
    operations = [
        migrations.RunPython(publish_verified_rates, remove_verified_rates),
    ]
