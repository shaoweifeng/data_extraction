"""Report QA evidence rollout health over a bounded observation window."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum
from django.utils import timezone

from core.models import QAReference, Task
from core.models_billing import TokenUsageLog


class Command(BaseCommand):
    help = 'Report QA evaluation task/ref/token health for rollout monitoring.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--max-task-failure-rate', type=float, default=0.10)
        parser.add_argument('--fail-on-threshold', action='store_true')

    def handle(self, *args, **options):
        if options['days'] < 1 or options['days'] > 90:
            raise CommandError('--days 必须在 1 到 90 之间。')
        since = timezone.now() - timedelta(days=options['days'])
        tasks = Task.objects.filter(task_type='qa_eval', created_at__gte=since)
        task_total = tasks.count()
        task_failed = tasks.filter(status='failed').count()
        failure_rate = task_failed / task_total if task_total else 0
        refs = QAReference.objects.filter(updated_at__gte=since)
        usage = TokenUsageLog.objects.filter(
            created_at__gte=since, task__task_type='qa_eval',
        ).aggregate(
            tokens=Sum('total_tokens'), charged=Sum('credits_consumed'),
            shadow=Sum('shadow_credits'), cost=Sum('estimated_cost_cny'),
        )
        lines = [
            f'观察窗口: {options["days"]} 天（自 {since.isoformat()}）',
            f'QA任务: total={task_total} failed={task_failed} failure_rate={failure_rate:.2%}',
            '文献状态: ' + ', '.join(
                f'{row["ai_eval_status"]}={row["count"]}'
                for row in refs.values('ai_eval_status').order_by('ai_eval_status').annotate(count=Count('pk'))
            ),
            f'Token/计费: tokens={usage["tokens"] or 0} old_credits={usage["charged"] or 0} '
            f'shadow_credits={usage["shadow"] or 0} estimated_cny={usage["cost"] or 0}',
        ]
        self.stdout.write('\n'.join(lines))
        if options['fail_on_threshold'] and failure_rate > options['max_task_failure_rate']:
            raise CommandError('QA 任务失败率超过阈值，禁止继续扩大灰度。')
