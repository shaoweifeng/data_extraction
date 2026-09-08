"""Input selection and source-record loading for AI screening."""

import xml.etree.ElementTree as ET
from typing import Dict, List

from core.models import DataFile
from core.artifacts.types import ArtifactType


class ScreeningInputSelector:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _get_input_files(self) -> List[DataFile]:
        """优先 dedup 输出，其次 parse 输出。"""
        dedup_step = self.executor.get_previous_step("dedup")
        if dedup_step:
            qs = DataFile.objects.filter(
                project=self.project_obj, step=dedup_step,
                data_category='intermediate',
                metadata__artifact_type=ArtifactType.SCREENING_DEDUP_REFERENCE_XML,
            )
            if qs.exists():
                self.logger.info(f"[数据] 使用去重后的文件: {qs.count()} 个")
                return list(qs)

        parse_step = self.executor.get_previous_step("parse")
        if parse_step:
            qs = DataFile.objects.filter(
                project=self.project_obj, step=parse_step,
                data_category='intermediate',
                metadata__artifact_type=ArtifactType.SCREENING_PARSED_REFERENCE_XML,
            )
            if qs.exists():
                self.logger.info(f"[数据] 使用解析后的文件: {qs.count()} 个")
                return list(qs)
        return []

    def _get_criteria(self) -> List[str]:
        """纳排标准读取优先级：task.config > criteria步骤 > stage.metadata > 默认。"""
        if self.task_obj and self.task_obj.config:
            criteria = self.task_obj.config.get('criteria', [])
            if criteria:
                self.logger.info(f"[标准] 从任务配置读取: {len(criteria)} 条")
                return criteria

        criteria_step = self.executor.get_previous_step("criteria")
        if criteria_step and criteria_step.metadata:
            criteria = criteria_step.metadata.get("criteria", [])
            if criteria:
                return criteria

        if self.stage_obj and self.stage_obj.metadata:
            raw = self.stage_obj.metadata.get('screening_criteria', '')
            if raw:
                lines = [l.strip() for l in raw.splitlines() if l.strip()]
                if lines:
                    self.logger.info(f"[标准] 从阶段 metadata 读取: {len(lines)} 条")
                    return lines

        self.logger.warning("[标准] 未找到纳排标准，使用默认值")
        return ["排除非英文文献", "排除综述和Meta分析", "排除动物实验研究", "排除病例报告"]

    def _parse_xml_entry(self, xml_path: str) -> Dict:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            def get_text(tag):
                elem = root.find(f'.//{tag}')
                return elem.text.strip() if elem is not None and elem.text else ""

            return {
                "title": get_text("Title"),
                "authors": get_text("Authors"),
                "year": get_text("Year"),
                "journal": get_text("Journal"),
                "abstract": get_text("Abstract"),
                "doi": get_text("DOI"),
                "url": get_text("URL") or get_text("Url") or get_text("url"),
            }
        except Exception as e:
            self.logger.warning(f"[警告] 解析XML失败 {xml_path}: {e}")
            return {"title": "", "authors": "", "year": "", "journal": "", "abstract": ""}
