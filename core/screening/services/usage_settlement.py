"""Screening adapter for the shared AI usage settlement service."""

from core.ai import AIUsageContext, AIUsageSettlementService


class UsageSettlementService:
    """Compatibility adapter retained for the existing screening handler API."""

    def __init__(self, handler):
        self.handler = handler

    def _save_token_stats(self, token_stats):
        task = self.handler.task_obj
        user = task.created_by if task else None
        model_ids = self.handler.config.get('ai_models') or []
        if not model_ids:
            model_ids = [self.handler.config.get('ai_model') or 'unknown']
        context = AIUsageContext(
            feature='AI筛选',
            user=user,
            project=self.handler.project_obj,
            task=task,
            model_ids=model_ids,
        )
        try:
            stats = AIUsageSettlementService.settle(context, token_stats)
            if stats.get('total_tokens'):
                self.handler.logger.info(
                    f"[Token] 本次任务共消耗 {stats['total_tokens']} tokens"
                    f"（{stats.get('ref_count', 0)} 篇，≈{stats['credits_consumed']} credits）"
                )
            return stats
        except ValueError as exc:
            self.handler.logger.warning(f'[计费] 扣费失败: {exc}')
        except Exception as exc:
            self.handler.logger.warning(f'[计费] 结算异常（不影响筛选结果）: {exc}')
        return {}
