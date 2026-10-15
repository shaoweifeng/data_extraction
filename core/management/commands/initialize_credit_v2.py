"""One-time internal cutover from the disposable legacy credit ledger."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.ai.quota import is_unlimited_ai_user
from core.models_billing import (
    CreditAccount, CreditAllocation, CreditGrantBatch, CreditReservation,
    CreditTransaction, RechargeCode, UserPlanEntitlement,
)
from core.services.credit_ledger_service import grant_batch_credits


CONFIRMATION = 'RESET-CREDIT-V2'


class Command(BaseCommand):
    help = '测试期一次性清理旧积分账本，并为普通有效账户初始化 V2 欢迎积分'

    def add_arguments(self, parser):
        parser.add_argument(
            '--initial-credits',
            type=int,
            default=getattr(settings, 'BILLING_FREE_CREDITS_ON_REGISTER', 200),
        )
        parser.add_argument('--confirm', default='')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--include-inactive', action='store_true')

    def handle(self, *args, **options):
        amount = options['initial_credits']
        if amount < 0:
            raise CommandError('--initial-credits 不能为负数')

        users = get_user_model().objects.select_related('profile').order_by('pk')
        if not options['include_inactive']:
            users = users.filter(is_active=True)
        user_rows = list(users)
        grant_users = [user for user in user_rows if not is_unlimited_ai_user(user)]
        unused_codes = RechargeCode.objects.filter(is_used=False).count()
        summary = (
            f'将清理 transactions={CreditTransaction.objects.count()}、'
            f'batches={CreditGrantBatch.objects.count()}、'
            f'reservations={CreditReservation.objects.count()}；'
            f'初始化普通账户={len(grant_users)}，每户={amount}；'
            f'作废未使用旧兑换码={unused_codes}'
        )
        self.stdout.write(summary)
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('dry-run：未修改任何数据'))
            return
        if options['confirm'] != CONFIRMATION:
            raise CommandError(f'这是不可逆测试数据重置，请显式传入 --confirm {CONFIRMATION}')
        if CreditGrantBatch.objects.exists():
            raise CommandError('检测到 V2 积分批次，拒绝重复初始化')

        now = timezone.now()
        with transaction.atomic():
            for user in user_rows:
                CreditAccount.objects.get_or_create(
                    user=user,
                    defaults={'balance': 0, 'total_granted': 0, 'total_consumed': 0},
                )
            CreditReservation.objects.all().delete()
            CreditAllocation.objects.all().delete()
            CreditGrantBatch.objects.all().delete()
            CreditTransaction.objects.filter(
                reverses_transaction__isnull=False,
            ).update(reverses_transaction=None)
            CreditTransaction.objects.all().delete()
            CreditAccount.objects.all().update(
                balance=0,
                total_granted=0,
                total_consumed=0,
                updated_at=now,
            )
            UserPlanEntitlement.objects.exclude(status='cancelled').update(
                status='cancelled',
                updated_at=now,
            )
            RechargeCode.objects.filter(is_used=False).update(expires_at=now)

            for user in grant_users:
                if amount == 0:
                    continue
                grant_batch_credits(
                    user,
                    amount,
                    batch_type='WELCOME',
                    batch_key=f'credit-v2-initial:{user.pk}',
                    note='V2 积分账本初始化',
                    txn_type='grant',
                )

        self.stdout.write(self.style.SUCCESS(
            f'V2 积分账本初始化完成：普通账户 {len(grant_users)} 个，每户 {amount} 积分；'
            '管理员账户保持 0 积分且继续免扣费。'
        ))
