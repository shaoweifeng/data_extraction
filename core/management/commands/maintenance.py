import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from core.operations.services import get_system_state, set_system_state


class Command(BaseCommand):
    help = '查看或切换平台运行状态（normal/draining/maintenance）'

    def add_arguments(self, parser):
        parser.add_argument('mode', choices=['status', 'normal', 'draining', 'maintenance'])
        parser.add_argument('--message', default='')
        parser.add_argument('--scheduled-at', default='')
        parser.add_argument('--username', default='')
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        mode = options['mode']
        if mode == 'status':
            result = get_system_state(fresh=True)
        else:
            scheduled_at = None
            if options['scheduled_at']:
                scheduled_at = parse_datetime(options['scheduled_at'])
                if scheduled_at is None:
                    raise CommandError('--scheduled-at 必须是 ISO 8601 时间')
            user = None
            if options['username']:
                user = get_user_model().objects.filter(username=options['username']).first()
                if user is None:
                    raise CommandError('指定的管理员用户不存在')
            result = set_system_state(
                mode,
                message=options['message'],
                scheduled_at=scheduled_at,
                user=user,
            )
        if options['json']:
            self.stdout.write(json.dumps(result, ensure_ascii=False))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"系统状态: {result['mode']} {result.get('message', '')}".rstrip()
            ))
