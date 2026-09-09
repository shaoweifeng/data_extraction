"""
结果归纳步骤 Handler

负责：
- 获取 ai_screen 步骤输出的 JSON 结果
- 合并人工审阅（ManualReview）覆写 —— 人工决定 > AI 共识
- 按 export_type（all/included/excluded）过滤
- 生成 Excel 和 RIS 文件
- 保存产物到 DataFile

多模型说明：
- 文件命名：使用所有参与模型的简称拼接，单模型保留原来的模型名
- exclusion_reason_id / exclusion_reason：
    1. 人工审阅过 → 使用 ManualReview.reason（纯文本，reason_id 置空）
    2. AI 共识排除 → 使用 number_exclusion_reason / exclusion_reason（JSON 里的合并结果）
- manual_override：ManualReview.is_override=True 时填 'yes'，否则 'no'
- extracted_fields：从 JSON 的 extracted_fields 读取（ai_screen_handler 在多模型时已合并）
"""

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import logging
logger = logging.getLogger(__name__)

from core.models import DataFile
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.screening.services.decision_service import ScreeningDecisionService
from core.artifacts.types import ArtifactType

@register("export")
class ExportHandler(BaseStepHandler):
    """结果归纳步骤 Handler（Celery 异步执行）"""

    execution_mode = "async"

    def execute(self) -> bool:
        """
        导出流程：
        1. 获取 ai_screen 输出的 JSON 结果
        2. 按 export_type 过滤
        3. 生成 Excel
        4. 生成 RIS（仅 included 条目）
        5. 保存产物
        """
        self.logger.info("[步骤] 开始结果归纳...")
        export_type = self.config.get("export_type", "all")
        self.logger.info(f"[导出] 导出类型: {export_type}")

        # 1. 获取 ai_screen 步骤输出
        ai_step = self.executor.get_previous_step("ai_screen")
        if not ai_step:
            self.logger.error("[错误] 未找到 ai_screen 步骤")
            return False

        result_files = DataFile.objects.filter(
            project=self.project_obj,
            step=ai_step,
            data_category='output',
            metadata__artifact_type=ArtifactType.SCREENING_RESULT_JSON,
        )
        result_file_count = result_files.count()
        self.logger.info(f"[输入] 找到 {result_file_count} 个结果文件")
        if result_file_count == 0:
            self.logger.warning("[警告] 没有筛选结果，将生成空报告")

        # 每批只保留少量结果、人工审阅和 XML 字段，避免 2.5 万篇文献常驻内存。
        criteria_list = self._load_criteria_list()
        self.logger.info(f"[导出] 纳排标准条数: {len(criteria_list)}")

        model_suffix = self._get_model_suffix()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stats = {
            'total': 0,
            'included': 0,
            'excluded': 0,
            'manual_overrides': 0,
            'exported': 0,
        }
        prepared_results = self._iter_prepared_results(
            result_files, export_type, stats, total_count=result_file_count,
        )

        # Excel 使用 openpyxl write-only 模式逐行写；同一遍遍历中同步追加 RIS，
        # 避免为了生成第二种格式重新扫描数据库和结果文件。
        from core.screening.exporters.ris import ScreeningRisExporter
        ris_exporter = ScreeningRisExporter(self)
        ris_path = self.workspace / f"screening_results_included_{model_suffix}_{ts}.ris"
        ris_output = None
        ris_count = 0
        if export_type != 'excluded':
            ris_output = open(ris_path, 'w', encoding='utf-8')

        def append_ris(result, xml_fields, final_decision):
            nonlocal ris_count
            include_conflict = (
                final_decision == 'conflict'
                and self.config.get('include_conflicts_in_ris') is True
            )
            if ris_output is not None and (final_decision == 'included' or include_conflict):
                ris_exporter._write_record(ris_output, result, xml_fields)
                ris_count += 1

        try:
            excel_path = self._generate_excel(
                prepared_results,
                export_type,
                model_suffix,
                ts,
                {},
                criteria_list,
                on_record=append_ris,
            )
        finally:
            if ris_output is not None:
                ris_output.close()

        if excel_path is None:
            if ris_path.exists():
                ris_path.unlink()
            return False

        if ris_count == 0:
            if ris_path.exists():
                ris_path.unlink()
            ris_path = None
        else:
            self.logger.info(f"[导出] 生成 RIS: {ris_count} 条")

        self.logger.info(f"[聚合] 有效结果: {stats['total']} 个")
        self.logger.info(f"[过滤] {export_type} → {stats['exported']} 条")

        # 6. 保存产物
        if excel_path and excel_path.exists():
            self.save_output_file(
                excel_path, excel_path.name, "初筛结果Excel", "output",
                ArtifactType.SCREENING_EXPORT_XLSX,
            )
        if ris_path and ris_path.exists():
            self.save_output_file(
                ris_path, ris_path.name, "初筛结果RIS", "output",
                ArtifactType.SCREENING_EXPORT_RIS,
            )

        # 7. 更新步骤元数据
        self.step_obj.metadata = {
            "total_results": stats['total'],
            "included_count": stats['included'],
            "excluded_count": stats['excluded'],
            "manual_override_count": stats['manual_overrides'],
            "completion_time": datetime.now().isoformat(),
        }
        return True

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _get_model_suffix(self) -> str:
        """
        读取本次 ai_screen 任务使用的模型列表，返回文件名后缀。
        - 单模型 → 模型显示名称（如 deepseek-chat）
        - 多模型 → 各模型名简写拼接（如 ds-chat+gpt4o），超过 40 字符则用 "Nmodels"
        - 兜底   → 'default'
        """
        # 优先从 export 任务自带 config 中读
        model_ids: List[str] = self.config.get("ai_models") or []
        if not model_ids:
            single = self.config.get("ai_model", "")
            if single:
                model_ids = [single]

        # 其次从最近的 ai_screen 任务配置读取
        if not model_ids:
            from core.models import Task
            ai_task = Task.objects.filter(
                project=self.project_obj,
                task_type='ai_screen',
            ).order_by('-created_at').first()
            if ai_task and ai_task.config:
                model_ids = ai_task.config.get("ai_models") or []
                if not model_ids:
                    single = ai_task.config.get("ai_model", "")
                    if single:
                        model_ids = [single]

        if not model_ids:
            return "default"

        # 将 model_id 转换为显示名
        try:
            from core.services.ai_models_config import get_models_for_frontend_flat
            id_to_name = {m["id"]: m["name"] for m in get_models_for_frontend_flat()}
        except Exception:
            id_to_name = {}

        display_names = []
        for mid in model_ids:
            name = id_to_name.get(mid, mid)
            # 简化：去掉常见冗余前缀/后缀
            short = (name.replace("deepseek-", "ds-")
                        .replace("gpt-", "gpt")
                        .replace("-preview", "")
                        .replace(" ", "_"))
            display_names.append(short)

        if len(display_names) == 1:
            return display_names[0]

        joined = "+".join(display_names)
        if len(joined) > 40:
            joined = f"{len(display_names)}models"
        return joined

    def _iter_prepared_results(self, result_files, export_type: str,
                               stats: Dict, batch_size: int = 200,
                               total_count: Optional[int] = None):
        """按主键翻页读取并补齐一批导出记录，内存占用受 batch_size 限制。"""
        from core.models import ManualReview
        from core.screening.selectors import load_ai_result_file, load_xml_fields_bulk

        last_pk = 0
        while True:
            if self.check_stop_signal():
                raise RuntimeError('用户已停止导出任务')
            batch = list(
                result_files.filter(pk__gt=last_pk)
                .order_by('pk')
                .only('pk', 'file', 'filename', 'metadata')[:batch_size]
            )
            if not batch:
                return
            last_pk = batch[-1].pk

            loaded = []
            for data_file in batch:
                result = load_ai_result_file(data_file)
                result.setdefault(
                    'source_xml',
                    (data_file.metadata or {}).get('source_xml', ''),
                )
                loaded.append(result)

            sources = [result.get('source_xml', '') for result in loaded]
            manual_reviews = {
                review.source_xml: review
                for review in ManualReview.objects.filter(
                    project=self.project_obj,
                    source_xml__in=[source for source in sources if source],
                ).only('source_xml', 'decision', 'reason', 'is_override')
            }
            xml_fields_by_source = load_xml_fields_bulk(sources, self.project_id)

            for result in loaded:
                source_xml = result.get('source_xml', '')
                manual_review = manual_reviews.get(source_xml)
                final_decision = ScreeningDecisionService.resolve(result, manual_review)
                is_included = final_decision == 'included'

                if final_decision == 'pending':
                    raise RuntimeError(
                        f'仍有待定文献，不能导出：{source_xml or "未知文献"}'
                    )
                if (
                    final_decision == 'conflict'
                    and self.config.get('allow_unresolved_conflicts') is not True
                ):
                    raise RuntimeError(
                        '仍有 AI 分歧文献未经人工裁定；如需继续，请勾选“允许豁免分歧文献”'
                    )

                stats['total'] += 1
                stats['included' if is_included else 'excluded'] += 1
                if manual_review and manual_review.is_override:
                    stats['manual_overrides'] += 1

                should_export = (
                    export_type == 'all'
                    or (export_type == 'included' and is_included)
                    or (export_type == 'excluded' and not is_included)
                )
                prepared = dict(result)
                prepared['_export_manual_review'] = manual_review
                prepared['_export_final_decision'] = final_decision
                prepared['_export_xml_fields'] = xml_fields_by_source.get(source_xml, {})
                prepared['_export_include_excel'] = should_export
                if should_export:
                    stats['exported'] += 1
                yield prepared

            if total_count:
                self.logger.update_progress(stats['total'], total_count, 'refs')

    def _generate_excel(self, results, export_type: str,
                        model_suffix: str, ts: str, manual_reviews: Dict,
                        criteria_list: List[str] = None,
                        on_record=None) -> Optional[Path]:
        from core.screening.exporters.excel import ScreeningExcelExporter
        return ScreeningExcelExporter(self)._generate_excel(
            results, export_type, model_suffix, ts, manual_reviews, criteria_list,
            on_record,
        )

    def _generate_ris(self, results: List[Dict], model_suffix: str, ts: str) -> Optional[Path]:
        from core.screening.exporters.ris import ScreeningRisExporter
        return ScreeningRisExporter(self)._generate_ris(results, model_suffix, ts)

    def _load_criteria_list(self) -> List[str]:
        """从 criteria 步骤元数据中加载纳排标准列表（按序），供导出时反查编号。"""
        try:
            from core.models import StageStep
            criteria_step = StageStep.objects.filter(
                stage__project_id=self.project_id,
                stage__stage_key='SCREEN_1',
                step_key='criteria',
            ).first()
            if criteria_step and criteria_step.metadata:
                criteria = criteria_step.metadata.get('criteria', [])
                if criteria:
                    return [str(c) for c in criteria]
        except Exception as e:
            logger.warning(f"[导出] 加载纳排标准失败: {e}")
        return []

    def _load_extraction_field_names(self) -> List[str]:
        try:
            from core.models import StageStep
            fe_step = StageStep.objects.filter(
                stage__project_id=self.project_id,
                stage__stage_key='SCREEN_1',
                step_key='field_extraction',
            ).first()
            if fe_step and fe_step.metadata and fe_step.metadata.get('fields'):
                return [f['name'] for f in fe_step.metadata['fields']]
        except Exception as e:
            logger.warning(f"[导出] 加载提取字段失败: {e}")
        return []

    def _load_xml_fields(self, xml_path: str) -> Dict:
        """兼容单条导出调用；生产导出使用批量版本避免逐条查询。"""
        from core.screening.selectors import load_xml_fields
        return load_xml_fields(xml_path, self.project_id)
