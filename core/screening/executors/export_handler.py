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

import json
import xml.etree.ElementTree as ET
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


from core.screening.exporters.common import _lookup_criteria_id


@register("export")
class ExportHandler(BaseStepHandler):
    """结果归纳步骤 Handler（同步执行）"""

    execution_mode = "sync"

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
        self.logger.info(f"[输入] 找到 {result_files.count()} 个结果文件")
        if result_files.count() == 0:
            self.logger.warning("[警告] 没有筛选结果，将生成空报告")

        # 2. 读取并过滤
        final_results = []
        for df in result_files:
            try:
                with open(df.file.path, 'r', encoding='utf-8') as f:
                    final_results.append(json.load(f))
            except Exception as e:
                self.logger.warning(f"[警告] 读取 {df.filename} 失败: {e}")

        self.logger.info(f"[聚合] 有效结果: {len(final_results)} 个")

        # 3. 加载人工审阅覆写记录（source_xml → ManualReview）
        from core.models import ManualReview
        manual_reviews = {
            mr.source_xml: mr
            for mr in ManualReview.objects.filter(project=self.project_obj)
        }
        self.logger.info(f"[人工审阅] 覆写记录: {len(manual_reviews)} 条")

        # 加载 criteria 列表，用于人工审阅时反查排除标准编号
        criteria_list = self._load_criteria_list()
        self.logger.info(f"[导出] 纳排标准条数: {len(criteria_list)}")

        def _final_decision(r: Dict) -> str:
            """通过共享领域规则返回最终决定。"""
            source_xml = r.get('source_xml', '')
            return ScreeningDecisionService.resolve(r, manual_reviews.get(source_xml))

        def _is_included(r: Dict) -> bool:
            return _final_decision(r) == 'included'

        if export_type == "included":
            filtered = [r for r in final_results if _is_included(r)]
        elif export_type == "excluded":
            filtered = [r for r in final_results if not _is_included(r)]
        else:
            filtered = final_results
        self.logger.info(f"[过滤] {export_type} → {len(filtered)} 条")

        model_suffix = self._get_model_suffix()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 5. 生成 Excel（将 manual_reviews + criteria_list 显式传入，避免闭包问题）
        excel_path = self._generate_excel(filtered, export_type, model_suffix, ts, manual_reviews, criteria_list)

        # 5. 生成 RIS（只含 included）
        included = [r for r in filtered if _is_included(r)]
        ris_path = self._generate_ris(included, model_suffix, ts) if included else None

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
        included_count = len([r for r in final_results if _is_included(r)])
        self.step_obj.metadata = {
            "total_results": len(final_results),
            "included_count": included_count,
            "excluded_count": len(final_results) - included_count,
            "manual_override_count": sum(1 for mr in manual_reviews.values() if mr.is_override),
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

    def _generate_excel(self, results: List[Dict], export_type: str,
                        model_suffix: str, ts: str, manual_reviews: Dict,
                        criteria_list: List[str] = None) -> Optional[Path]:
        from core.screening.exporters.excel import ScreeningExcelExporter
        return ScreeningExcelExporter(self)._generate_excel(
            results, export_type, model_suffix, ts, manual_reviews, criteria_list,
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

    def _itext(self, elem) -> str:
        """提取 XML 元素的全部文本。"""
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def _load_xml_fields(self, xml_path: str) -> Dict:
        """从源 XML 文件中读取完整文献元数据（带多级目录模糊查找）。"""
        if not xml_path:
            return {}
        try:
            p = Path(xml_path)
            actual_path: Optional[Path] = p if p.exists() else None
            project_ws = self.workspace.parent  # export_*/parent = project_*

            if actual_path is None:
                xml_name = p.name
                name_prefix = xml_name.rsplit('_', 1)[0] if '_' in xml_name else xml_name
                if not hasattr(self, '_xml_path_index'):
                    self._xml_path_index = self._build_xml_path_index(project_ws)
                actual_path = self._xml_path_index.get(xml_name)
                if actual_path is None:
                    actual_path = next(
                        (path for name, path in self._xml_path_index.items() if name_prefix in name),
                        None,
                    )

            if actual_path is None:
                self.logger.debug(f"[XML] 未找到文件: {xml_path}")
                return {}

            root = ET.parse(actual_path).getroot()
            ref = root
            if root.tag not in ("Reference", "reference"):
                ref = root.find(".//Reference") or root.find(".//reference") or root
            return {
                "ReferenceType": self._itext(ref.find("ReferenceType")),
                "Title":         self._itext(ref.find("Title")),
                "Author":        self._itext(ref.find("Authors")) or self._itext(ref.find("Author")),
                "Year":          self._itext(ref.find("Year")),
                "Journal":       self._itext(ref.find("Journal")),
                "Volume":        self._itext(ref.find("Volume")),
                "Issue":         self._itext(ref.find("Issue")),
                "Page":          self._itext(ref.find("Page")),
                "Date":          self._itext(ref.find("Date")),
                "Doi":           self._itext(ref.find("Doi")) or self._itext(ref.find("DOI")),
                "PMCID":         self._itext(ref.find("PMCID")),
                "Abstract":      self._itext(ref.find("Abstract")),
                "URL":           self._itext(ref.find("Url")) or self._itext(ref.find("URL")),
                "Address":       self._itext(ref.find("Address")),
            }
        except Exception as e:
            self.logger.warning(f"[警告] 加载 XML 字段失败 {xml_path}: {e}")
            return {}

    def _build_xml_path_index(self, project_ws: Path) -> Dict[str, Path]:
        """Scan prior-step XML directories once per export, rather than once per row."""
        index: Dict[str, Path] = {}
        locations = (
            ('dedup_*', ('dedup_xmls',)),
            ('parse_*', ('split_xmls', 'parsed_xmls', 'output')),
        )
        for workspace_glob, sub_dirs in locations:
            for base_dir in sorted(project_ws.glob(workspace_glob), reverse=True):
                for sub_dir in sub_dirs:
                    directory = base_dir / sub_dir
                    if not directory.exists():
                        continue
                    for path in directory.glob('*.xml'):
                        index.setdefault(path.name, path)
        return index
