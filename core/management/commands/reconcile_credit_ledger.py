from django.core.management.base import BaseCommand, CommandError

from core.models_billing import CreditAccount
from core.services.credit_ledger_service import account_reconciliation


class Command(BaseCommand):
    help = '只读核对积分账户余额与有效批次可用余额'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, action='append', dest='user_ids')
        parser.add_argument('--fail-on-difference', action='store_true')

    def handle(self, *args, **options):
        accounts = CreditAccount.objects.select_related('user').order_by('pk')
        if options.get('user_ids'):
            accounts = accounts.filter(user_id__in=options['user_ids'])

        differences = []
        total_balance = 0
        total_available = 0
        total_reserved = 0
        for account in accounts:
            row = account_reconciliation(account)
            total_balance += row['balance']
            total_available += row['batch_available']
            total_reserved += row['reserved']
            if row['difference']:
                differences.append(row)
                self.stdout.write(self.style.WARNING(
                    f'user={account.user_id} username={account.user.username} '
                    f'balance={row["balance"]} batches={row["batch_available"]} '
                    f'difference={row["difference"]} reserved={row["reserved"]}'
                ))

        summary = (
            f'accounts={accounts.count()} balance={total_balance} '
            f'batch_available={total_available} reserved={total_reserved} '
            f'differences={len(differences)}'
        )
        if differences:
            self.stdout.write(self.style.WARNING(summary))
            if options['fail_on_difference']:
                raise CommandError('积分账本核对存在差异')
        else:
            self.stdout.write(self.style.SUCCESS(summary))
