import json

from django.core.management.base import BaseCommand, CommandError

from core.operations.services import (
    get_system_state,
    pause_long_running_tasks,
    resume_maintenance_tasks,
)


class Command(BaseCommand):
    help = '协作式暂停或恢复因维护中断的长任务'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['pause', 'resume'])
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        if options['action'] == 'pause':
            if get_system_state(fresh=True)['mode'] == 'normal':
                raise CommandError('请先将系统切换到 draining 或 maintenance')
            result = pause_long_running_tasks()
        else:
            result = resume_maintenance_tasks()
        output = json.dumps(result, ensure_ascii=False, indent=2)
        self.stdout.write(output)
        if result['failed']:
            raise CommandError(f"{len(result['failed'])} 个任务处理失败")
