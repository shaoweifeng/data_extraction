from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...models import AccountSecurityEvent
from core.models import RegistrationLog


class Command(BaseCommand):
    help = '预览或删除超过留存期限的账户安全事件；默认只预览。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--older-than-days', type=int,
            default=getattr(settings, 'ACCOUNT_SECURITY_EVENT_RETENTION_DAYS', 180),
        )
        parser.add_argument('--delete', action='store_true')

    def handle(self, *args, **options):
        days = options['older_than_days']
        if days <= 0:
            raise CommandError('--older-than-days 必须大于 0')
        cutoff = timezone.now() - timedelta(days=days)
        queryset = AccountSecurityEvent.objects.filter(created_at__lt=cutoff)
        legacy_queryset = RegistrationLog.objects.filter(created_at__lt=cutoff)
        count = queryset.count()
        legacy_count = legacy_queryset.count()
        if not options['delete']:
            self.stdout.write(
                f'将清理 {count} 条脱敏账户安全事件和 {legacy_count} 条历史注册日志'
                f'（截止 {cutoff.isoformat()}）；未执行删除。'
            )
            return
        deleted, _ = queryset.delete()
        legacy_deleted, _ = legacy_queryset.delete()
        self.stdout.write(self.style.SUCCESS(
            f'已删除 {deleted} 条账户安全事件和 {legacy_deleted} 条历史注册日志。'
        ))
