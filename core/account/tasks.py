import logging
from urllib.parse import urlencode

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from .models import AccountEmailChangeRequest, AccountVerificationToken, VerificationPurpose

logger = logging.getLogger(__name__)


def _activation_url(raw_token: str) -> str:
    base_url = getattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    # Fragment is not sent in HTTP requests, so the raw token stays out of access logs.
    return f'{base_url}/verify-email#{urlencode({"token": raw_token})}'


def _account_action_url(path: str, raw_token: str) -> str:
    base_url = getattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    return f'{base_url}/{path.lstrip("/")}#{urlencode({"token": raw_token})}'


def _send_template_email(*, subject, template_name, context, recipient):
    text_body = render_to_string(f'account/emails/{template_name}.txt', context)
    html_body = render_to_string(f'account/emails/{template_name}.html', context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(html_body, 'text/html')
    message.send(fail_silently=False)


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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, token_id: int, raw_token: str):
    try:
        token = AccountVerificationToken.objects.select_related('account_email').get(
            pk=token_id,
            purpose=VerificationPurpose.PASSWORD_RESET,
        )
    except AccountVerificationToken.DoesNotExist:
        return {'status': 'missing'}
    if token.used_at or token.revoked_at or token.expires_at <= timezone.now():
        return {'status': 'inactive'}

    AccountVerificationToken.objects.filter(pk=token.pk).update(
        send_attempts=F('send_attempts') + 1,
    )
    reset_url = _account_action_url('reset-password', raw_token)
    context = {
        'platform_name': getattr(settings, 'ACCOUNT_EMAIL_SENDER_NAME', '循证智筛'),
        'reset_url': reset_url,
        'ttl_minutes': getattr(settings, 'PASSWORD_RESET_TTL_MINUTES', 30),
    }
    try:
        _send_template_email(
            subject=f'[{context["platform_name"]}] 重置您的密码',
            template_name='password_reset',
            context=context,
            recipient=token.account_email.email,
        )
    except Exception as exc:
        AccountVerificationToken.objects.filter(pk=token.pk).update(last_error=str(exc)[:255])
        logger.warning('[账户邮件] 密码重置邮件发送失败 token_id=%s', token.pk)
        raise self.retry(exc=exc) from exc

    AccountVerificationToken.objects.filter(pk=token.pk).update(
        sent_at=timezone.now(), last_error='',
    )
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
        logger.info('[账户邮件][本地调试] 密码重置链接: %s', reset_url)
    return {'status': 'sent'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_changed_notice(self, user_id: int):
    from .models import AccountEmail
    identity = AccountEmail.objects.filter(
        user_id=user_id, verified_at__isnull=False,
    ).first()
    if not identity:
        return {'status': 'missing'}
    context = {'platform_name': getattr(settings, 'ACCOUNT_EMAIL_SENDER_NAME', '循证智筛')}
    try:
        _send_template_email(
            subject=f'[{context["platform_name"]}] 您的密码已修改',
            template_name='password_changed',
            context=context,
            recipient=identity.email,
        )
    except Exception as exc:
        logger.warning('[账户邮件] 密码修改通知发送失败 user_id=%s', user_id)
        raise self.retry(exc=exc) from exc
    return {'status': 'sent'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_change_confirmation(self, request_id: int, raw_token: str):
    try:
        request = AccountEmailChangeRequest.objects.get(pk=request_id)
    except AccountEmailChangeRequest.DoesNotExist:
        return {'status': 'missing'}
    if request.used_at or request.revoked_at or request.expires_at <= timezone.now():
        return {'status': 'inactive'}

    AccountEmailChangeRequest.objects.filter(pk=request.pk).update(
        send_attempts=F('send_attempts') + 1,
    )
    confirmation_url = _account_action_url('verify-email-change', raw_token)
    context = {
        'platform_name': getattr(settings, 'ACCOUNT_EMAIL_SENDER_NAME', '循证智筛'),
        'confirmation_url': confirmation_url,
        'ttl_hours': getattr(settings, 'EMAIL_CHANGE_TOKEN_TTL_HOURS', 24),
    }
    try:
        _send_template_email(
            subject=f'[{context["platform_name"]}] 验证您的新邮箱',
            template_name='email_change_confirmation',
            context=context,
            recipient=request.new_email,
        )
    except Exception as exc:
        AccountEmailChangeRequest.objects.filter(pk=request.pk).update(last_error=str(exc)[:255])
        logger.warning('[账户邮件] 邮箱变更验证发送失败 request_id=%s', request.pk)
        raise self.retry(exc=exc) from exc
    AccountEmailChangeRequest.objects.filter(pk=request.pk).update(
        sent_at=timezone.now(), last_error='',
    )
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
        logger.info('[账户邮件][本地调试] 邮箱变更链接: %s', confirmation_url)
    return {'status': 'sent'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_changed_notice(self, user_id: int, old_email: str, new_email: str):
    context = {
        'platform_name': getattr(settings, 'ACCOUNT_EMAIL_SENDER_NAME', '循证智筛'),
        'new_email': new_email,
    }
    try:
        _send_template_email(
            subject=f'[{context["platform_name"]}] 您的登录邮箱已变更',
            template_name='email_changed',
            context=context,
            recipient=old_email,
        )
    except Exception as exc:
        logger.warning('[账户邮件] 旧邮箱变更通知失败 user_id=%s', user_id)
        raise self.retry(exc=exc) from exc
    return {'status': 'sent'}


def _queue(task, *args) -> bool:
    try:
        task.delay(*args)
        return True
    except Exception:
        logger.exception('[账户邮件] 邮件任务投递失败 task=%s', task.name)
        return False


def queue_password_reset_email(token_id: int, raw_token: str) -> bool:
    return _queue(send_password_reset_email, token_id, raw_token)


def queue_password_changed_notice(user_id: int) -> bool:
    return _queue(send_password_changed_notice, user_id)


def queue_email_change_confirmation(request_id: int, raw_token: str) -> bool:
    return _queue(send_email_change_confirmation, request_id, raw_token)


def queue_email_changed_notice(user_id: int, old_email: str, new_email: str) -> bool:
    return _queue(send_email_changed_notice, user_id, old_email, new_email)
