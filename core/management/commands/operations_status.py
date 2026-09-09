import json

from django.core.management.base import BaseCommand

from core.operations.services import get_operations_snapshot


class Command(BaseCommand):
    help = '输出在线用户、活动任务和 Celery 状态'

    def add_arguments(self, parser):
        parser.add_argument('--no-celery', action='store_true')
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        snapshot = get_operations_snapshot(inspect_celery=not options['no_celery'])
        if options['json']:
            self.stdout.write(json.dumps(snapshot, ensure_ascii=False, indent=2))
            return
        self.stdout.write(f"系统状态: {snapshot['state']['mode']}")
        self.stdout.write(
            f"在线用户: {snapshot['presence']['online_users']}，"
            f"活跃标签页: {snapshot['presence']['active_tabs']}，"
            f"活动任务: {snapshot['active_task_count']}"
        )
        celery = snapshot['celery']
        if celery.get('available') is not None:
            self.stdout.write(
                f"Celery worker: {celery.get('workers', 0)}，active: {celery.get('active', 0)}，"
                f"reserved: {celery.get('reserved', 0)}，scheduled: {celery.get('scheduled', 0)}"
            )
        self.stdout.write(f"可以安全停机: {'是' if snapshot['safe_to_stop'] else '否'}")
