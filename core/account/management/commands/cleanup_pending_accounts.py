from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

User = get_user_model()


def pending_account_candidates():
    cutoff = timezone.now() - timedelta(
        days=getattr(settings, 'ACCOUNT_PENDING_RETENTION_DAYS', 7),
    )
    return User.objects.filter(
        is_active=False,
        is_staff=False,
        is_superuser=False,
        date_joined__lt=cutoff,
        account_email__isnull=False,
        account_email__verified_at__isnull=True,
        account_verification_tokens__purpose='email_activation',
        profile__role='user',
        profile__is_banned=False,
        profile__approved_by__isnull=True,
    ).filter(
        Q(credit_account__isnull=True)
        | Q(
            credit_account__balance=0,
            credit_account__total_granted=0,
            credit_account__total_consumed=0,
            credit_account__transactions__isnull=True,
        ),
        owned_projects__isnull=True,
        token_logs__isnull=True,
    ).distinct().order_by('pk')


class Command(BaseCommand):
    help = '清理超过保留期且没有业务数据的未激活账户；默认只预览'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true', help='实际删除符合条件的账户')
        parser.add_argument('--limit', type=int, default=500, help='单次最多处理数量，默认 500')

    def handle(self, *args, **options):
        limit = options['limit']
        if limit <= 0 or limit > 5000:
            raise CommandError('--limit 必须在 1～5000 之间')

        user_ids = list(pending_account_candidates().values_list('pk', flat=True)[:limit])
        self.stdout.write(f'符合安全清理条件的待激活账户: {len(user_ids)}')
        if not options['delete']:
            self.stdout.write('当前为预览模式；确认后使用 --delete 执行清理')
            return

        with transaction.atomic():
            locked_ids = list(
                pending_account_candidates().select_for_update()
                .filter(pk__in=user_ids).values_list('pk', flat=True)
            )
            deleted, _ = User.objects.filter(pk__in=locked_ids).delete()
        self.stdout.write(self.style.SUCCESS(
            f'已清理 {len(locked_ids)} 个待激活账户（级联删除对象总数 {deleted}）',
        ))
