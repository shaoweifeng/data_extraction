"""Database-backed automatic deduplication step."""

import json

from core.artifacts.types import ArtifactType
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.models import DataFile
from core.screening.models import DedupRun
from core.screening.services.dedup_service import (
    DeduplicationCancelled,
    build_dedup_run,
    cancel_dedup_run,
    complete_dedup_run,
    create_dedup_run,
    fail_dedup_run,
)


def phase_percentage(completed: int, total: int, start_pct: int, end_pct: int) -> int:
    """Map progress within one phase onto its overall task percentage range."""
    ratio = completed / total if total else 1
    return min(end_pct, start_pct + int(ratio * (end_pct - start_pct)))


@register('dedup')
class DedupHandler(BaseStepHandler):
    """Deduplicate the current corpus revision without reading parsed XML files."""

    def execute(self) -> bool:
        self.logger.info('[步骤] 开始数据库化自动去重...')
        run = None
        try:
            run = create_dedup_run(
                project=self.project_obj,
                task=self.task_obj,
                created_by=self.task_obj.created_by,
            )
            self.logger.info(
                f'[输入] 文献集修订 r{run.corpus_revision}，共 {run.total_count} 篇文献'
            )
            self._report_progress(0, run.total_count, 0, 70, '[去重] 正在扫描数据库文献')
            run = build_dedup_run(
                run.id,
                should_cancel=self.check_stop_signal,
                on_progress=lambda completed, total: self._report_progress(
                    completed, total, 0, 70, f'[去重] 已比较 {completed}/{total} 篇文献',
                ),
            )

            self.logger.info(
                f'[统计] 原始: {run.total_count} 篇  保留: {run.kept_count} 篇  '
                f'重复: {run.duplicate_count} 篇  重复组: {run.group_count}'
            )
            report = self._save_compact_report(run)
            run = complete_dedup_run(run.id)
            self._clear_superseded_outputs(run.id)

            report['completion_time'] = run.finished_at.isoformat()
            self.step_obj.metadata = report
            self.step_obj.save(update_fields=['metadata'])
            self._report_progress(1, 1, 99, 100, '[完成] 数据库去重结果已发布')
            return True
        except DeduplicationCancelled:
            if run is not None:
                cancel_dedup_run(run.id)
                self._delete_run_outputs(run.id)
            self.logger.warning('[停止] 数据库去重已取消，未发布本次结果')
            return False
        except Exception as exc:
            if run is not None:
                fail_dedup_run(run.id)
                self._delete_run_outputs(run.id)
            self.logger.error(f'[错误] 数据库去重失败: {exc}')
            return False

    def _report_progress(
        self,
        completed: int,
        total: int,
        start_pct: int,
        end_pct: int,
        message: str,
    ) -> None:
        percentage = phase_percentage(completed, total, start_pct, end_pct)
        self.logger.update_progress(percentage, 100, 'percent')
        self.logger.info(message)

    def _save_compact_report(self, run: DedupRun) -> dict:
        duplicate_rate = run.duplicate_count / run.total_count * 100 if run.total_count else 0
        report = {
            'dedup_run_id': run.id,
            'corpus_revision': run.corpus_revision,
            'rule_version': run.rule_version,
            'total_files': run.total_count,
            'kept_files': run.kept_count,
            'duplicates': run.duplicate_count,
            'duplicate_rate': f'{duplicate_rate:.2f}%',
            'duplicate_groups': run.group_count,
        }
        report_path = self.workspace / f'dedup_report_{run.id}.json'
        with open(report_path, 'w', encoding='utf-8') as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        self.save_output_file(
            report_path,
            report_path.name,
            '数据库去重摘要报告',
            'output',
            ArtifactType.SCREENING_DEDUP_REPORT_JSON,
            metadata={'dedup_run_id': run.id, 'corpus_revision': run.corpus_revision},
        )
        return report

    def _delete_run_outputs(self, run_id: int) -> None:
        DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            metadata__dedup_run_id=run_id,
        ).delete()

    def _clear_superseded_outputs(self, run_id: int) -> None:
        old_outputs = DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            metadata__artifact_type=ArtifactType.SCREENING_DEDUP_REPORT_JSON,
        ).exclude(metadata__dedup_run_id=run_id)
        old_count, _ = old_outputs.delete()
        if old_count:
            self.logger.info(f'[清理] 已清除 {old_count} 份旧去重报告')
