import logging
from urllib.parse import urlencode

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from .models import AccountVerificationToken

logger = logging.getLogger(__name__)


def _activation_url(raw_token: str) -> str:
    base_url = getattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    # Fragment is not sent in HTTP requests, so the raw token stays out of access logs.
    return f'{base_url}/verify-email#{urlencode({"token": raw_token})}'


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_email(self, token_id: int, raw_token: str):
    try:
        token = AccountVerificationToken.objects.select_related('account_email').get(pk=token_id)
    except AccountVerificationToken.DoesNotExist:
        return {'status': 'missing'}
    if token.used_at or token.revoked_at or token.expires_at <= timezone.now():
        return {'status': 'inactive'}

    AccountVerificationToken.objects.filter(pk=token.pk).update(
        send_attempts=F('send_attempts') + 1,
    )
    context = {
        'platform_name': getattr(settings, 'ACCOUNT_EMAIL_SENDER_NAME', '循证智筛'),
        'activation_url': _activation_url(raw_token),
        'ttl_hours': getattr(settings, 'EMAIL_VERIFICATION_TTL_HOURS', 24),
    }
    subject = f'[{context["platform_name"]}] 验证您的邮箱'
    text_body = render_to_string('account/emails/verify_email.txt', context)
    html_body = render_to_string('account/emails/verify_email.html', context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[token.account_email.email],
    )
    message.attach_alternative(html_body, 'text/html')
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        AccountVerificationToken.objects.filter(pk=token.pk).update(
            last_error=str(exc)[:255],
        )
        logger.warning('[账户邮件] 验证邮件发送失败 token_id=%s', token.pk)
        raise self.retry(exc=exc) from exc

    AccountVerificationToken.objects.filter(pk=token.pk).update(
        sent_at=timezone.now(),
        last_error='',
    )
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
        # The Celery worker can absorb Django's console backend stdout. Emit the
        # local-only activation URL through the configured logger so developers
        # can always complete the verification flow from celery.log/platform.log.
        logger.info('[账户邮件][本地调试] 验证链接: %s', context['activation_url'])
    return {'status': 'sent'}


def queue_verification_email(token_id: int, raw_token: str) -> bool:
    try:
        send_verification_email.delay(token_id, raw_token)
        return True
    except Exception:
        logger.exception('[账户邮件] 验证邮件任务投递失败 token_id=%s', token_id)
        return False
