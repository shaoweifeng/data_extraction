import ipaddress
from urllib.parse import urlparse

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
    verification_enabled = getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', False)
    if verification_enabled and not registration_v2_enabled:
        messages.append(checks.Error(
            '启用邮箱验证必须同时启用 ACCOUNT_REGISTRATION_V2_ENABLED。',
            id='account.E007',
        ))
    public_base_url = getattr(settings, 'PUBLIC_BASE_URL', '')
    parsed_base_url = urlparse(public_base_url)
    if verification_enabled and (
        parsed_base_url.scheme not in {'http', 'https'} or not parsed_base_url.netloc
    ):
        messages.append(checks.Error(
            '启用邮箱验证时 PUBLIC_BASE_URL 必须是完整的 HTTP(S) 地址。',
            id='account.E003',
        ))
    if getattr(settings, 'EMAIL_USE_TLS', False) and getattr(settings, 'EMAIL_USE_SSL', False):
        messages.append(checks.Error(
            'EMAIL_USE_TLS 与 EMAIL_USE_SSL 不能同时启用。',
            id='account.E005',
        ))
    email_backend = getattr(settings, 'EMAIL_BACKEND', '')
    if (
        getattr(settings, 'APP_ENV', 'development') == 'production'
        and email_backend in {
            'django.core.mail.backends.console.EmailBackend',
            'django.core.mail.backends.locmem.EmailBackend',
        }
    ):
        messages.append(checks.Error(
            '生产环境启用邮箱验证时不能使用 console 或 locmem 邮件后端。',
            id='account.E008',
        ))
    positive_settings = (
        'ACCOUNT_PENDING_RETENTION_DAYS',
        'EMAIL_VERIFICATION_TTL_HOURS',
        'EMAIL_RESEND_INTERVAL_SECONDS',
        'EMAIL_DAILY_SEND_LIMIT',
        'EMAIL_TOKEN_FAILURE_LIMIT',
        'PASSWORD_RESET_TTL_MINUTES',
        'PASSWORD_RESET_RESEND_INTERVAL_SECONDS',
        'PASSWORD_RESET_DAILY_SEND_LIMIT',
        'PASSWORD_RESET_IP_LIMIT',
        'EMAIL_CHANGE_TOKEN_TTL_HOURS',
        'EMAIL_CHANGE_RESEND_INTERVAL_SECONDS',
        'EMAIL_CHANGE_DAILY_SEND_LIMIT',
        'EMAIL_CHANGE_IP_LIMIT',
        'ACCOUNT_SECURITY_CHANGE_WINDOW_SECONDS',
        'ACCOUNT_SECURITY_CHANGE_USER_LIMIT',
        'ACCOUNT_SECURITY_CHANGE_IP_LIMIT',
        'ACCOUNT_SECURITY_EVENT_RETENTION_DAYS',
        'ACCOUNT_SECURITY_ALERT_FAILURE_THRESHOLD',
        'ACCOUNT_SECURITY_ALERT_MAIL_THRESHOLD',
    )
    invalid_positive_settings = [
        name for name in positive_settings if getattr(settings, name, 0) <= 0
    ]
    if invalid_positive_settings:
        messages.append(checks.Error(
            f'{", ".join(invalid_positive_settings)} 必须大于 0。',
            id='account.E006',
        ))

    if getattr(settings, 'APP_ENV', 'development') == 'production':
        if getattr(settings, 'REGISTRATION_ENABLED', True) and not registration_v2_enabled:
            messages.append(checks.Error(
                '生产开放注册必须启用 ACCOUNT_REGISTRATION_V2_ENABLED。', id='account.E012',
            ))
        if getattr(settings, 'REGISTRATION_ENABLED', True) and not verification_enabled:
            messages.append(checks.Error(
                '生产开放注册必须启用 REQUIRE_EMAIL_VERIFICATION。', id='account.E013',
            ))
        if parsed_base_url.scheme != 'https':
            messages.append(checks.Error(
                '生产环境 PUBLIC_BASE_URL 必须使用 HTTPS。', id='account.E014',
            ))
        for name in ('LEGAL_OPERATOR_NAME', 'LEGAL_CONTACT_EMAIL', 'LEGAL_CONTACT_ADDRESS'):
            value = getattr(settings, name, '')
            if not value or '待配置' in value or '请替换' in value:
                messages.append(checks.Error(
                    f'生产环境必须配置真实的 {name}。',
                    id='account.E009',
                ))
        if not getattr(settings, 'SESSION_COOKIE_SECURE', False) or not getattr(
            settings, 'CSRF_COOKIE_SECURE', False,
        ):
            messages.append(checks.Error(
                '生产环境必须启用 Secure Session/CSRF Cookie。', id='account.E010',
            ))
        if getattr(settings, 'SECURE_HSTS_SECONDS', 0) <= 0:
            messages.append(checks.Error(
                '生产环境必须配置 SECURE_HSTS_SECONDS。', id='account.E011',
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
