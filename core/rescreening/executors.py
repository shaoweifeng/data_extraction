"""Rescreen import adapter for the existing task lifecycle (no AI calls)."""
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.rescreening.services.processing import process_import


@register('rescreen_export')
class RescreenExportHandler(BaseStepHandler):
    execution_mode = 'async'

    def execute(self):
        from core.rescreening.models import RescreenExport
        from core.rescreening.services.exports import process_export
        job_id = self.config['rescreen_export_id']
        RescreenExport.objects.get(pk=job_id, project_id=self.project_id, task_id=self.task_obj.pk)
        job = process_export(job_id, expected_task_id=self.task_obj.pk, check_stop=self.check_stop_signal,
            progress=lambda current, total: self.logger.update_progress(current, total, 'refs'))
        return job.status == 'completed'


@register('rescreen_import')
class RescreenImportHandler(BaseStepHandler):
    execution_mode = 'async'

    def execute(self):
        batch_id = self.config['rescreen_import_batch_id']
        # Never accept another project's batch through a manipulated task config.
        from core.rescreening.models import RescreenImportBatch
        RescreenImportBatch.objects.get(pk=batch_id, project_id=self.project_id, task_id=self.task_obj.pk)
        batch = process_import(batch_id, stop_checker=self.check_stop_signal, expected_task_id=self.task_obj.pk)
        self.logger.info(f'[复筛导入] 已发布 {batch.accepted_count} 篇文献')
        self.logger.update_progress(batch.accepted_count, batch.accepted_count, 'refs')
        return True


@register('rescreen_pdf')
class RescreenPDFHandler(BaseStepHandler):
    execution_mode = 'async'

    def execute(self):
        from core.fulltext.models import FulltextAsset
        from core.fulltext.processing import process_asset
        asset_id = self.config['fulltext_asset_id']
        FulltextAsset.objects.get(pk=asset_id, project_id=self.project_id, processing_task=self.task_obj)
        asset = process_asset(asset_id, expected_task_id=self.task_obj.pk, check_stop=self.check_stop_signal)
        if asset.status != 'ready':
            return False
        self.logger.update_progress(1, 1, 'files')
        return True


@register('rescreen_fetch')
class RescreenFetchHandler(BaseStepHandler):
    execution_mode = 'async'

    def execute(self):
        from core.rescreening.models import FulltextLookupJob
        from core.rescreening.services.fulltext_fetch import process_lookup
        job_id = self.config['fulltext_lookup_job_id']
        FulltextLookupJob.objects.get(pk=job_id, project_id=self.project_id, task_id=self.task_obj.pk)
        job = process_lookup(job_id, expected_task_id=self.task_obj.pk, check_stop=self.check_stop_signal,
            progress=lambda current, total: self.logger.update_progress(current, total, 'refs'))
        return job.status == 'completed'


@register('rescreen_ai')
class RescreenAIHandler(BaseStepHandler):
    execution_mode = 'async'

    def execute(self):
        from core.rescreening.models import RescreenRun
        from core.rescreening.services.ai_execution import process_run
        run_id = self.config['rescreen_run_id']
        RescreenRun.objects.get(pk=run_id, corpus__project_id=self.project_id, task_id=self.task_obj.pk)
        run = process_run(run_id, expected_task_id=self.task_obj.pk, check_stop=self.check_stop_signal,
            progress=lambda current, total: self.logger.update_progress(current, total, 'refs'))
        if run.status == 'paused':
            # Distinguish resource-pause from a technical failure in Task too.
            from core.workflow.services.lifecycle import transition_task
            from core.workflow.domain.statuses import TaskStatus
            self.task_obj.refresh_from_db()
            if self.task_obj.status == TaskStatus.RUNNING:
                transition_task(self.task_obj, TaskStatus.STOPPING, expected_from={TaskStatus.RUNNING})
        return run.status in ('completed', 'partial')
