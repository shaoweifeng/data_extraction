"""
文献解析步骤 Handler

负责：
- 复制上传文件到工作区
- 调用 screening 领域解析器逐条生成标准化记录
- 批量写入数据库并保存文件级解析诊断
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from django.core.exceptions import ObjectDoesNotExist

from core.models import DataFile
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.artifacts.types import ArtifactType
from core.screening import parsers as _parser
from core.screening.parsers.diagnostics import ParseReportCollector


@register("parse")
class ParseHandler(BaseStepHandler):
    """文献解析步骤 Handler（同步执行）"""

    execution_mode = "async"

    def execute(self) -> bool:
        """
        文献解析流程：
        1. 准备目录结构
        2. 复制上传文件到工作区
        3. 逐条解析并批量写入数据库
        4. 保存解析诊断报告
        """
        self.logger.info("[步骤] 开始文献解析...")
        batch_id = self._import_batch_id()
        if batch_id:
            from core.screening.services.import_service import claim_import_batch

            claim_import_batch(batch_id, self.task_obj.id)
            self._clear_batch_outputs()

        # 1. 准备目录结构
        input_dir = self.workspace / "input"
        for d in [input_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 2. 获取输入文件
        input_files = self._get_upload_files()
        if not input_files:
            self.logger.error("[错误] 没有找到输入文件，请先上传文献")
            self._fail_import_batch()
            return False

        total_files = len(input_files)
        self.logger.info(f"[输入] 找到 {total_files} 个待解析文件")
        self.logger.update_progress(0, total_files, "files")

        self._input_source_ids = {
            data_file.filename: getattr(data_file, 'id', None)
            for data_file in input_files
        }
        for i, df in enumerate(input_files, 1):
            dest = input_dir / df.filename
            source_path = self._source_path(df)
            shutil.copy(source_path, dest)
            self.logger.info(f"[复制] {df.filename}")
            self.logger.update_progress(i, total_files, "files")
            if self.check_stop_signal():
                self._cancel_import_batch()
                return False

        # 3. 调用解析脚本
        self.logger.info("[解析] 调用解析器...")
        total_entries = self._run_parser(input_dir)
        if total_entries is None:
            self._fail_import_batch()
            return False

        parse_reports = getattr(self, '_parse_reports', [])
        parse_summary = self._aggregate_parse_reports(parse_reports)

        self.logger.info(f"[解析] 成功解析 {total_entries} 条文献")
        if parse_summary['skipped_entries']:
            self.logger.warning(
                f"[解析警告] 检测到 {parse_summary['detected_entries']} 条，"
                f"成功 {parse_summary['parsed_entries']} 条，"
                f"异常跳过 {parse_summary['skipped_entries']} 条"
            )
        if parse_summary['missing_abstract_entries']:
            self.logger.warning(
                f"[质量提示] {parse_summary['missing_abstract_entries']} 条文献缺少摘要"
            )
        split_count = total_entries

        # 5. 保存产物
        self.logger.info("[保存] 保存输出文件到数据库...")
        try:
            self._save_parse_reports(input_files, parse_reports)
        except Exception:
            if batch_id:
                self._fail_import_batch()
                self._clear_batch_outputs(preserve_parse_reports=True)
            raise
        self.logger.info("[完成] 标准化文献已写入数据库，解析诊断已保存")

        if total_entries == 0:
            failure_message = '未解析到可用文献，请查看解析诊断报告并确认文件格式'
            self.logger.error(f"[错误] {failure_message}")
            self._update_parse_progress('failed', 100, 100, failure_message)
            self._write_final_stats(
                total_entries,
                split_count,
                total_files,
                parse_summary,
                progress_phase='failed',
                progress_message=failure_message,
            )
            if batch_id:
                from core.screening.services.import_service import persist_import_reports

                persist_import_reports(batch_id, parse_reports)
                self._clear_batch_outputs(preserve_parse_reports=True)
                self._fail_import_batch()
            return False

        if batch_id:
            from core.screening.services.import_errors import ScreeningImportError
            from core.screening.services.import_service import complete_import_batch

            try:
                complete_import_batch(batch_id, parse_reports)
            except ScreeningImportError as exc:
                self.logger.error(f"[导入失败] {exc.message}")
                self._fail_import_batch()
                self._clear_batch_outputs(preserve_parse_reports=True)
                self._update_parse_progress('failed', 100, 100, exc.message)
                return False

        # 6. 写最终统计到 Task.config
        self._update_parse_progress("done", 99, 100,
                                    f"解析完成，共 {split_count} 篇文献，等待收尾...")
        self._write_final_stats(total_entries, split_count, total_files, parse_summary)
        return True

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _get_upload_files(self) -> List[DataFile]:
        """获取用户上传的文献文件（input 类别）。"""
        config = getattr(self, 'config', {}) or {}
        file_ids = config.get('file_ids') or []
        batch_id = config.get('import_batch_id')
        if self.stage_obj:
            queryset = DataFile.objects.filter(
                project=self.project_obj,
                stage=self.stage_obj,
                data_category='input',
            )
        else:
            queryset = DataFile.objects.filter(
                project=self.project_obj,
                stage__isnull=True,
                data_category='input',
            )
        if file_ids:
            queryset = queryset.filter(id__in=file_ids)
        if batch_id:
            queryset = queryset.filter(reference_import_file__import_batch_id=batch_id)
        files = list(queryset.order_by('id'))
        if file_ids and {item.id for item in files} != {int(value) for value in file_ids}:
            from core.screening.services.import_errors import ScreeningImportError

            raise ScreeningImportError(
                'invalid_import_files', '任务中的文件不存在、已移除或不属于当前项目。',
                http_status=409,
            )
        return files

    @staticmethod
    def _source_path(data_file: DataFile) -> str:
        try:
            private_file = data_file.reference_import_file.raw_file
            if private_file:
                return private_file.path
        except (AttributeError, ObjectDoesNotExist):
            pass
        return data_file.file.path

    def _import_batch_id(self):
        return (getattr(self, 'config', {}) or {}).get('import_batch_id')

    def _fail_import_batch(self):
        batch_id = self._import_batch_id()
        if batch_id:
            from core.screening.services.import_service import fail_import_batch

            fail_import_batch(batch_id)

    def _cancel_import_batch(self):
        batch_id = self._import_batch_id()
        if batch_id:
            from core.screening.services.import_service import cancel_import_batch

            cancel_import_batch(batch_id)

    def _clear_batch_outputs(self, *, preserve_parse_reports=False):
        batch_id = self._import_batch_id()
        if batch_id:
            outputs = DataFile.objects.filter(
                project=self.project_obj,
                step=self.step_obj,
                metadata__import_batch_id=batch_id,
            ).exclude(data_category='input')
            if preserve_parse_reports:
                outputs = outputs.exclude(
                    metadata__artifact_type=ArtifactType.SCREENING_PARSE_REPORT_JSON,
                )
            outputs.delete()

    def _run_parser(self, input_dir: Path):
        """单遍解析并将标准化记录批量写入数据库。"""
        self._parse_reports = []
        batch_id = self._import_batch_id()
        reference_writer = None
        existing_reference_count = 0
        if batch_id:
            from core.screening.services.reference_persistence import ScreeningReferenceBulkWriter

            reference_writer = ScreeningReferenceBulkWriter(
                batch_id,
                on_flush=lambda _batch_count, written_count: self._update_parse_progress(
                    'persisting', 55, 100,
                    f'[数据库] 已暂存 {written_count} 条标准化文献',
                ),
            )
            existing_reference_count = reference_writer.batch.corpus.active_reference_count

        def iter_entries_with_reports():
            emitted = 0
            from core.screening.services.import_errors import ScreeningImportError
            from core.screening.services.import_limits import (
                ImportLimits,
                validate_projected_reference_count,
            )

            limits = ImportLimits.from_settings()
            for file_path in sorted(input_dir.iterdir()):
                if not file_path.is_file():
                    continue
                collector = ParseReportCollector(
                    str(file_path), max_issues=limits.max_reported_errors,
                )
                parser_error = None
                try:
                    for entry in _parser.iter_file(str(file_path)):
                        try:
                            _parser.validate_reference_record(entry, limits)
                        except _parser.ReferenceRecordValidationError as exc:
                            collector.reject_record(
                                exc.code,
                                exc.message,
                                position=entry.get('source_position'),
                                identifier=str(
                                    entry.get('source_identifier')
                                    or entry.get('record_number')
                                    or ''
                                ),
                                title=str(entry.get('title') or '')[:500],
                                suggestion='请修正异常字段后重新导出，平台不会静默截断内容。',
                            )
                            continue

                        emitted += 1
                        if (
                            reference_writer
                            and emitted % limits.processing_batch_size == 0
                            and self.check_stop_signal()
                        ):
                            self._cancel_import_batch()
                            raise ScreeningImportError(
                                'import_cancelled', '文献导入已由用户取消。', http_status=409,
                            )
                        projected_total = validate_projected_reference_count(
                            existing_reference_count, emitted, limits,
                        )
                        if (
                            projected_total >= limits.warning_references
                            and (
                                emitted == 1
                                or projected_total - 1 < limits.warning_references
                            )
                        ):
                            self.logger.warning(
                                f"[容量提示] 项目文献总数已达到 {projected_total} 篇"
                            )
                        collector.observe(entry)
                        entry['_source_file_id'] = getattr(
                            self, '_input_source_ids', {},
                        ).get(file_path.name)
                        if reference_writer:
                            reference_writer.add(entry)
                        yield entry
                except ScreeningImportError:
                    self._parse_reports.append(collector.finalize())
                    raise
                except Exception as exc:
                    parser_error = exc
                    self.logger.warning(f"[警告] 解析失败 {file_path.name}: {exc}")
                report = collector.finalize(parser_error=parser_error)
                self._parse_reports.append(report)

                if parser_error is not None:
                    self.logger.warning(
                        f"[解析诊断] {file_path.name} 已接受 {collector.parsed_entries} 条后终止"
                    )

        try:
            count = 0
            for count, _entry in enumerate(iter_entries_with_reports(), 1):
                if count % 100 == 0:
                    self._update_parse_progress(
                        "persisting", 40, 100, f"[数据库] 已解析 {count} 条文献",
                    )
            if reference_writer:
                stored_count = reference_writer.finalize()
                if stored_count != count:
                    from core.screening.services.import_errors import ScreeningImportError

                    raise ScreeningImportError(
                        'reference_count_mismatch',
                        '解析输出数与数据库暂存文献数不一致。',
                        details={'parsed': count, 'stored': stored_count},
                    )
        except Exception as e:
            self.logger.error(f"[错误] 解析失败: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

        return count

    @staticmethod
    def _aggregate_parse_reports(reports):
        summary = {
            'status': 'success',
            'total_files': len(reports),
            'detected_entries': 0,
            'parsed_entries': 0,
            'skipped_entries': 0,
            'missing_abstract_entries': 0,
            'error_count': 0,
            'warning_count': 0,
        }
        for report in reports:
            for key in (
                'detected_entries', 'parsed_entries', 'skipped_entries',
                'missing_abstract_entries', 'error_count', 'warning_count',
            ):
                summary[key] += int(report.get(key) or 0)

        statuses = {report.get('status') for report in reports}
        if statuses and statuses <= {'failed'}:
            summary['status'] = 'failed'
        elif 'failed' in statuses or 'partial' in statuses:
            summary['status'] = 'partial'
        elif 'warning' in statuses:
            summary['status'] = 'warning'
        return summary

    def _save_parse_reports(self, input_files: List[DataFile], reports) -> None:
        """Persist compact summaries on inputs and full diagnostics as artifacts."""
        files_by_name = {}
        for data_file in input_files:
            files_by_name.setdefault(data_file.filename, []).append(data_file)

        report_dir = self.workspace / 'parse_reports'
        report_dir.mkdir(parents=True, exist_ok=True)
        parsed_at = datetime.now().isoformat()

        for report_index, report in enumerate(reports, 1):
            matches = files_by_name.get(report.get('filename'), [])
            source_file = matches.pop(0) if matches else None
            report['parsed_at'] = parsed_at
            report['source_file_id'] = source_file.id if source_file else None

            summary = {key: value for key, value in report.items() if key != 'issues'}
            if source_file:
                metadata = dict(source_file.metadata or {})
                metadata['parse_summary'] = summary
                source_file.metadata = metadata
                source_file.save(update_fields=['metadata', 'updated_at'])

            report_name = f"parse_report_{source_file.id if source_file else report_index}.json"
            report_path = report_dir / report_name
            with open(report_path, 'w', encoding='utf-8') as output:
                json.dump(report, output, ensure_ascii=False, indent=2)
            self.save_output_file(
                report_path,
                report_name,
                '文献解析诊断报告',
                'output',
                ArtifactType.SCREENING_PARSE_REPORT_JSON,
                metadata={
                    'source_file_id': source_file.id if source_file else None,
                    'import_batch_id': self._import_batch_id(),
                },
            )

    def _update_parse_progress(self, phase: str, current: int, total: int, message: str) -> None:
        """更新 Task.config 中的 parse_progress 字段（供前端轮询）。"""
        from core.models import Task as _Task
        row = _Task.objects.filter(id=self.executor.task_id).values('config').first()
        cfg = (row['config'] if row and row['config'] else {})
        cfg['parse_progress'] = {
            "phase": phase, "current": current,
            "total": total, "message": message,
        }
        _Task.objects.filter(id=self.executor.task_id).update(config=cfg)

    def _write_final_stats(
        self, total_entries: int, split_count: int, total_files: int,
        parse_summary=None,
        progress_phase='done', progress_message=None,
    ) -> None:
        """将最终统计回写到 Task.config 和 StageStep.metadata。"""
        from core.models import Task as _Task
        row = _Task.objects.filter(id=self.executor.task_id).values('config').first()
        cfg = (row['config'] if row and row['config'] else {})
        progress_message = progress_message or f"解析完成，共 {split_count} 篇文献，等待收尾..."
        cfg.update({
            "total_entries": total_entries,
            "split_files": split_count,
            "parse_summary": parse_summary or {},
            "parse_progress": {
                "phase": progress_phase,
                "current": 99 if progress_phase == 'done' else 100,
                "total": 100,
                "message": progress_message,
            },
        })
        _Task.objects.filter(id=self.executor.task_id).update(config=cfg)

        self.step_obj.metadata = {
            "total_files": total_files,
            "total_entries": total_entries,
            "split_files": split_count,
            "parse_summary": parse_summary or {},
            "completion_time": datetime.now().isoformat(),
        }
