import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...models import AccountSecurityEvent, AccountVerificationToken, AccountEmailChangeRequest


class Command(BaseCommand):
    help = '汇总近期账户攻击与邮件错误，可供 cron/监控系统告警。'

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=15)
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--fail-on-alert', action='store_true')

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(minutes=options['minutes'])
        failures = AccountSecurityEvent.objects.filter(
            created_at__gte=since,
            outcome__in=['failure', 'denied', 'banned'],
        ).count()
        mail_errors = (
            AccountVerificationToken.objects.filter(
                created_at__gte=since,
            ).exclude(last_error='').count()
            + AccountEmailChangeRequest.objects.filter(
                created_at__gte=since,
            ).exclude(last_error='').count()
        )
        threshold = getattr(settings, 'ACCOUNT_SECURITY_ALERT_FAILURE_THRESHOLD', 50)
        mail_threshold = getattr(settings, 'ACCOUNT_SECURITY_ALERT_MAIL_THRESHOLD', 5)
        alert = failures >= threshold or mail_errors >= mail_threshold
        result = {
            'window_minutes': options['minutes'],
            'authentication_failures': failures,
            'mail_errors': mail_errors,
            'alert': alert,
        }
        self.stdout.write(json.dumps(result, ensure_ascii=False) if options['json'] else str(result))
        if alert and options['fail_on_alert']:
            raise CommandError('账户安全指标超过告警阈值')
