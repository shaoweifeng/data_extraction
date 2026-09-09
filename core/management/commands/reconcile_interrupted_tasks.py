import json

from django.core.management.base import BaseCommand

from core.operations.services import reconcile_interrupted_tasks


class Command(BaseCommand):
    help = '检查并修复在所有 Worker 停止后仍标记为运行中的孤儿任务'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        result = reconcile_interrupted_tasks(apply=options['apply'])
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
