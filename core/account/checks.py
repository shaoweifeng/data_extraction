import ipaddress

from django.conf import settings
from django.core import checks


@checks.register(checks.Tags.security)
def check_account_security_settings(app_configs, **kwargs):
    messages = []
    min_length = getattr(settings, 'ACCOUNT_PASSWORD_MIN_LENGTH', 8)
    max_length = getattr(settings, 'ACCOUNT_PASSWORD_MAX_LENGTH', 128)
    if min_length < 8 or max_length < min_length:
        messages.append(checks.Error(
            '账户密码长度配置无效，最小长度不得低于 8 且不得超过最大长度。',
            id='account.E001',
        ))

    rate_limit_enabled = getattr(settings, 'ACCOUNT_RATE_LIMIT_ENABLED', False)
    registration_v2_enabled = getattr(settings, 'ACCOUNT_REGISTRATION_V2_ENABLED', False)
    if rate_limit_enabled and not getattr(settings, 'RATE_LIMIT_REDIS_URL', ''):
        messages.append(checks.Error(
            'ACCOUNT_RATE_LIMIT_ENABLED=True 时必须配置 RATE_LIMIT_REDIS_URL。',
            id='account.E002',
        ))
    if registration_v2_enabled and not rate_limit_enabled:
        messages.append(checks.Warning(
            '新注册链路已开启，但账户安全限流尚未开启。',
            hint='生产环境请配置 RATE_LIMIT_REDIS_URL 并启用 ACCOUNT_RATE_LIMIT_ENABLED。',
            id='account.W001',
        ))
    if registration_v2_enabled and getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', False):
        messages.append(checks.Error(
            '阶段 2 邮箱激活尚未实现，不能同时开启新注册和强制邮箱验证。',
            id='account.E003',
        ))

    for value in getattr(settings, 'TRUSTED_PROXY_IPS', []):
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            messages.append(checks.Error(
                f'TRUSTED_PROXY_IPS 包含无效地址：{value}',
                id='account.E004',
            ))
    return messages
