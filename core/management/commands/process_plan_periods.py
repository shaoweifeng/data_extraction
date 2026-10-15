from django.core.management.base import BaseCommand

from core.services.entitlement_service import process_due_plan_periods


class Command(BaseCommand):
    help = '推进套餐状态并幂等发放当前到期账期积分'

    def handle(self, *args, **options):
        result = process_due_plan_periods()
        self.stdout.write(self.style.SUCCESS(
            f'套餐周期处理完成：users_processed={result["users_processed"]}'
        ))
