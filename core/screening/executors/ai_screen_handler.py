"""Database-backed AI screening step handler."""

from datetime import datetime
from typing import Dict, List

from core.ai import AIQuotaService, is_unlimited_ai_user
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.models import Task
from core.screening.services.screening_run_service import (
    complete_screening_run,
    next_result_batch,
    pause_screening_run,
    persist_result_batch,
    prepare_screening_run,
    reference_entry,
)


@register('ai_screen')
class AIScreenHandler(BaseStepHandler):
    """Run AI screening against the published database corpus."""

    execution_mode = 'async'

    def execute(self) -> bool:
        self.logger.info('[步骤] 开始 AI 初筛（数据库模式）...')
        criteria = self._get_criteria()
        model_ids = self._model_ids()
        run = None

        try:
            run, created = prepare_screening_run(
                project=self.project_obj,
                task=self.task_obj,
                criteria=criteria,
                model_ids=model_ids,
                config=self.config,
            )
            remaining_count = max(0, run.total_count - run.processed_count)
            self.logger.info(
                f'[数据] 文献集修订 r{run.corpus_revision}，共 {run.total_count} 篇，'
                f'待处理 {remaining_count} 篇'
            )
            self.logger.info(f'[标准] 纳排标准: {len(criteria)} 条')
            self._preflight_quota(remaining_count, model_ids)

            concurrency = self._concurrency()
            self.logger._progress_sync_interval = concurrency
            self.logger.info(f'[并发] 本次使用 {concurrency} 线程并发')
            self._report_progress(run.processed_count, run.total_count)

            while True:
                if self.check_stop_signal():
                    self.logger.warning('[停止] 用户请求停止任务')
                    pause_screening_run(run.id)
                    self.save_checkpoint({
                        'screening_run_id': run.id,
                        'progress': {
                            'current': run.processed_count,
                            'total': run.total_count,
                        },
                    })
                    return False

                rows = next_result_batch(run, concurrency)
                if not rows:
                    break
                batch = [reference_entry(row.reference) for row in rows]
                self.logger.info(
                    f'[批次] 处理 {run.processed_count + 1}-'
                    f'{min(run.processed_count + len(rows), run.total_count)}/'
                    f'{run.total_count} 篇（并发 {concurrency} 线程）'
                )
                results = self._process_batch(batch, criteria, concurrency)
                persist_result_batch(rows, results)
                run.refresh_from_db()
                self._report_progress(run.processed_count, run.total_count)
                self.save_checkpoint({
                    'screening_run_id': run.id,
                    'progress': {
                        'current': run.processed_count,
                        'total': run.total_count,
                    },
                })

            run, settlement = complete_screening_run(
                run.id,
                task=self.task_obj,
                model_ids=model_ids,
            )
            self.executor.clear_checkpoint()
            conflict_count = run.results.filter(consensus='conflict').count()
            self.step_obj.metadata = {
                'stats_version': 3,
                'screening_run_id': run.id,
                'corpus_revision': run.corpus_revision,
                'dedup_run_id': run.dedup_run_id,
                'total_refs': run.total_count,
                'processed_refs': run.processed_count,
                'included_refs': run.included_count,
                'excluded_refs': run.excluded_count,
                'uncertain_refs': run.uncertain_count + run.failed_count,
                'conflict_refs': conflict_count,
                'pending_refs': max(
                    0,
                    run.uncertain_count - conflict_count + run.failed_count,
                ),
                'error_refs': run.failed_count,
                'input_tokens': run.input_tokens,
                'output_tokens': run.output_tokens,
                'credits_consumed': settlement.get('credits_consumed', 0),
                'start_time': run.started_at.isoformat() if run.started_at else None,
                'end_time': run.finished_at.isoformat() if run.finished_at else None,
                'criteria_count': len(criteria),
            }
            self.logger.info(
                f'[完成] AI 初筛完成：纳入 {run.included_count}，排除 '
                f'{run.excluded_count}，待定 {run.uncertain_count}，失败 {run.failed_count}'
            )
            return True
        except Exception:
            if run is not None:
                # Keep the same run resumable for Celery retry / worker restart.
                pause_screening_run(run.id)
            raise

    def _model_ids(self) -> List[str]:
        model_ids = list(self.config.get('ai_models') or [])
        if not model_ids:
            single = self.config.get('ai_model') or ''
            if single:
                model_ids = [single]
        return model_ids

    def _preflight_quota(self, reference_count: int, model_ids: List[str]) -> None:
        user = self.task_obj.created_by if self.task_obj else None
        if not user or reference_count <= 0:
            return
        if is_unlimited_ai_user(user):
            self.logger.info('[计费] 管理员账户，跳过余额预检')
            return
        estimated = AIQuotaService.preflight(user, reference_count, model_ids)
        self.logger.info(f'[计费] 余额预检通过，预估消耗 {estimated} credits')

    def _concurrency(self) -> int:
        if 'concurrency' in self.config:
            return max(1, int(self.config['concurrency']))
        from core.services.concurrency_service import get_user_concurrency

        user = self.task_obj.created_by if self.task_obj else None
        return max(1, int(get_user_concurrency(user)))

    def _report_progress(self, current: int, total: int) -> None:
        self._send_heartbeat(current, total)
        self.logger.update_progress(current, total, 'refs')

    def _send_heartbeat(self, current: int, total: int) -> None:
        try:
            row = Task.objects.filter(id=self.executor.task_id).values('config').first()
            config = dict(row['config'] if row and row['config'] else {})
            config['screen_progress'] = {
                'heartbeat': datetime.now().isoformat(),
                'processed_refs': current,
                'total_refs': total,
                'status_message': f'正在处理第 {current}/{total} 篇文献',
            }
            Task.objects.filter(id=self.executor.task_id).update(config=config)
        except Exception as exc:
            self.logger.warning(f'[心跳] 更新失败: {exc}')

    def _get_criteria(self) -> List[str]:
        criteria = self.config.get('criteria') or []
        if criteria:
            return list(criteria)
        criteria_step = self.executor.get_previous_step('criteria')
        if criteria_step and criteria_step.metadata:
            criteria = criteria_step.metadata.get('criteria') or []
            if criteria:
                return list(criteria)
        if self.stage_obj and self.stage_obj.metadata:
            raw = self.stage_obj.metadata.get('screening_criteria', '')
            if raw:
                return [line.strip() for line in raw.splitlines() if line.strip()]
        self.logger.warning('[标准] 未找到纳排标准，使用默认值')
        return ['排除非英文文献', '排除综述和Meta分析', '排除动物实验研究', '排除病例报告']

    def _process_batch(
        self,
        batch: List[Dict],
        criteria: List[str],
        concurrency: int = 16,
    ) -> List[Dict]:
        try:
            results = self._call_multi_model_api(batch, criteria, concurrency=concurrency)
        except Exception as exc:
            self.logger.warning(f'[API] 批次调用失败，将按单篇失败策略重试: {exc}')
            results = [{'error': str(exc), 'consensus': 'pending'} for _ in batch]

        for index, result in enumerate(results):
            result['timestamp'] = datetime.now().isoformat()
            result['reference_id'] = batch[index].get('reference_id')
        return results

    def _call_multi_model_api(
        self,
        batch: List[Dict],
        criteria: List[str],
        concurrency: int = 16,
    ) -> List[Dict]:
        from core.screening.services.model_runner import ScreeningModelRunner

        return ScreeningModelRunner(self)._call_multi_model_api(batch, criteria, concurrency)

    def _mock_api_call(self, batch: List[Dict], criteria: List[str]) -> List[Dict]:
        from core.screening.services.model_runner import ScreeningModelRunner

        return ScreeningModelRunner(self)._mock_api_call(batch, criteria)

    def _get_prompt_template(self) -> str:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder

        return ScreeningPromptBuilder(self)._get_prompt_template()

    def _append_extraction_block(self, base_prompt: str) -> str:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder

        return ScreeningPromptBuilder(self)._append_extraction_block(base_prompt)

    def _get_extraction_fields(self) -> List[Dict]:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder

        return ScreeningPromptBuilder(self)._get_extraction_fields()

    def _mock_extracted_fields(self) -> Dict:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder

        return ScreeningPromptBuilder(self)._mock_extracted_fields()
