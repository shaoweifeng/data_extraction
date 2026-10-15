"""Offline replay of stored AI usage against one immutable rate version."""

from django.core.management.base import BaseCommand, CommandError

from core.ai.pricing import calculate_versioned_pricing
from core.models_billing import TokenUsageLog


class Command(BaseCommand):
    help = '只读回放 TokenUsageLog 的新版加权计费，不修改余额或流水'

    def add_arguments(self, parser):
        parser.add_argument('--usage-log-id', type=int, action='append', dest='usage_log_ids')
        parser.add_argument('--pricing-version', required=True)
        parser.add_argument('--allow-draft', action='store_true')

    def handle(self, *args, **options):
        ids = options.get('usage_log_ids') or []
        if not ids:
            raise CommandError('至少提供一个 --usage-log-id')
        logs = {
            row.pk: row for row in TokenUsageLog.objects.filter(pk__in=ids).order_by('pk')
        }
        missing = sorted(set(ids) - set(logs))
        if missing:
            raise CommandError(f'TokenUsageLog 不存在: {missing}')

        total_old = 0
        total_new = 0
        total_cost = 0
        total_priced_calls = 0
        total_unknown_calls = 0
        has_unresolved = False
        for usage_log_id in ids:
            row = logs[usage_log_id]
            result = calculate_versioned_pricing(
                row.usage_breakdown,
                pricing_version=options['pricing_version'],
                allow_draft=options['allow_draft'],
            )
            unknown = result['unknown_calls']
            credits = result['task_credits']
            total_old += row.credits_consumed
            if credits is not None:
                total_new += credits
            else:
                has_unresolved = True
            total_cost += result['estimated_cost_cny']
            total_priced_calls += len(result['priced_calls'])
            total_unknown_calls += len(unknown)
            self.stdout.write(
                f'usage_log={row.pk} old={row.credits_consumed} '
                f'new={credits} cost_cny={result["estimated_cost_cny"]} '
                f'calls={len(result["priced_calls"])} unknown={len(unknown)}'
            )
            if unknown:
                self.stdout.write(self.style.WARNING(f'  未匹配费率: {unknown}'))

        total_new_display = 'None' if has_unresolved else str(total_new)
        summary = (
            f'合计 logs={len(ids)} old={total_old} new={total_new_display} '
            f'cost_cny={total_cost} calls={total_priced_calls} unknown={total_unknown_calls}'
        )
        if has_unresolved:
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
