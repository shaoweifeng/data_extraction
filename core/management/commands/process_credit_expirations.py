from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models_billing import CreditGrantBatch, CreditReservation
from core.services.credit_ledger_service import (
    expire_due_batches, release_reservation,
)


class Command(BaseCommand):
    help = '释放已超时预占并处理到期积分批次；默认只预览，传 --apply 才修改'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        now = timezone.now()
        reservation_ids = list(CreditReservation.objects.filter(
            status='reserved',
            expires_at__isnull=False,
            expires_at__lte=now,
        ).values_list('pk', flat=True))
        account_ids = list(CreditGrantBatch.objects.filter(
            expires_at__isnull=False,
            expires_at__lte=now,
            remaining_amount__gt=0,
        ).values_list('account_id', flat=True).distinct())
        self.stdout.write(
            f'待处理：超时预占={len(reservation_ids)}，存在到期批次的账户={len(account_ids)}'
        )
        if not options['apply']:
            self.stdout.write(self.style.WARNING('预览模式：传 --apply 后才会修改'))
            return

        released = 0
        for reservation in CreditReservation.objects.filter(pk__in=reservation_ids):
            released += release_reservation(
                reservation,
                status='expired',
                reason='预占超过有效期',
            )
        expired = 0
        for user_id in CreditGrantBatch.objects.filter(
            account_id__in=account_ids,
        ).values_list('account__user_id', flat=True).distinct():
            from django.contrib.auth import get_user_model

            user = get_user_model().objects.get(pk=user_id)
            expired += expire_due_batches(user, now=now)
        self.stdout.write(self.style.SUCCESS(
            f'处理完成：恢复可用预占={released}，到期扣减={expired}'
        ))
