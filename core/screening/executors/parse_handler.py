"""
文献解析步骤 Handler

负责：
- 复制上传文件到工作区
- 调用 screening 领域解析器生成条目
- 生成单篇 XML 索引文件
- 保存产物到 DataFile
"""

import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List

from core.models import DataFile
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.executors.base import safe_title
from core.artifacts.types import ArtifactType
from core.screening import parsers as _parser


@register("parse")
class ParseHandler(BaseStepHandler):
    """文献解析步骤 Handler（同步执行）"""

    execution_mode = "async"

    def execute(self) -> bool:
        """
        文献解析流程：
        1. 准备目录结构
        2. 复制上传文件到工作区
        3. 调用解析脚本
        4. 生成单篇 XML 索引
        5. 保存产物到 DataFile
        """
        self.logger.info("[步骤] 开始文献解析...")

        # 1. 准备目录结构
        input_dir = self.workspace / "input"
        output_dir = self.workspace / "output"
        split_dir = self.workspace / "split_xmls"
        for d in [input_dir, output_dir, split_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 2. 获取输入文件
        input_files = self._get_upload_files()
        if not input_files:
            self.logger.error("[错误] 没有找到输入文件，请先上传文献")
            return False

        total_files = len(input_files)
        self.logger.info(f"[输入] 找到 {total_files} 个待解析文件")
        self.logger.update_progress(0, total_files, "files")

        for i, df in enumerate(input_files, 1):
            dest = input_dir / df.filename
            shutil.copy(df.file.path, dest)
            self.logger.info(f"[复制] {df.filename}")
            self.logger.update_progress(i, total_files, "files")
            if self.check_stop_signal():
                return False

        # 3. 调用解析脚本
        self.logger.info("[解析] 调用解析器...")
        total_entries, merged_xml = self._run_parser(input_dir, output_dir, split_dir)
        if total_entries is None:
            return False

        self.logger.info(f"[解析] 成功解析 {total_entries} 条文献")
        split_count = total_entries
        self.logger.info(f"[拆分] 生成 {split_count} 个单篇XML")

        # 5. 保存产物
        self.logger.info("[保存] 保存输出文件到数据库...")
        self._clear_old_intermediate()
        saved_count = self._save_outputs(merged_xml, split_dir)
        self.logger.info(f"[完成] 已保存 {saved_count} 个文件")

        # 6. 写最终统计到 Task.config
        self._update_parse_progress("done", 99, 100,
                                    f"解析完成，共 {split_count} 篇文献，等待收尾...")
        self._write_final_stats(total_entries, split_count, total_files)
        return True

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _get_upload_files(self) -> List[DataFile]:
        """获取用户上传的文献文件（input 类别）。"""
        if self.stage_obj:
            return list(DataFile.objects.filter(
                project=self.project_obj,
                stage=self.stage_obj,
                data_category='input',
            ))
        return list(DataFile.objects.filter(
            project=self.project_obj,
            stage__isnull=True,
            data_category='input',
        ))

    def _run_parser(self, input_dir: Path, output_dir: Path, split_dir: Path):
        """单遍解析并同时生成合并 XML 和单篇 XML。"""
        merged_xml = output_dir / "references.xml"

        def write_split(entry, position):
            title = entry.get('title') or f'unknown_{position}'
            xml_file = split_dir / f"{position:05d}_{safe_title(title, 40)}.xml"
            root = ET.Element('reference')
            field_map = [
                ('title', 'Title'), ('authors', 'Authors'), ('year', 'Year'),
                ('journal', 'Journal'), ('volume', 'Volume'), ('issue', 'Issue'),
                ('page', 'Page'), ('date', 'Date'), ('reference_type', 'ReferenceType'),
                ('pmcid', 'PMCID'), ('address', 'Address'), ('abstract', 'Abstract'),
                ('doi', 'Doi'), ('url', 'Url'),
            ]
            for field_key, xml_tag in field_map:
                value = entry.get(field_key)
                if value:
                    elem = ET.SubElement(root, xml_tag)
                    elem.text = '; '.join(str(item) for item in value if item) if isinstance(value, list) else str(value)
            ET.SubElement(root, 'SourceFile').text = str(entry.get('source_file', 'unknown'))
            ET.SubElement(root, 'SourcePosition').text = str(entry.get('source_position', position))
            ET.ElementTree(root).write(xml_file, encoding='utf-8', xml_declaration=True)
            if position % 50 == 0:
                self._update_parse_progress(
                    "splitting", 40, 100, f"[2/3] 已解析并生成 {position} 个单篇索引",
                )

        try:
            count = _parser.write_xml_stream(
                _parser.iter_directory(str(input_dir)),
                str(merged_xml),
                on_entry=write_split,
            )
            if count == 0:
                merged_xml.unlink(missing_ok=True)
        except Exception as e:
            self.logger.error(f"[错误] 解析失败: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None, None

        return count, merged_xml

    def _clear_old_intermediate(self) -> None:
        """清除本步骤旧的 intermediate DataFile 记录，避免重复运行时累加。
        同时清除项目级的人工审阅和 AI 筛选结果（重新上传意味着文献集完全更换）。
        """
        old_qs = DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            data_category='intermediate',
        )
        old_count = old_qs.count()
        if old_count > 0:
            old_qs.delete()
            self.logger.info(f"[清理] 已清除 {old_count} 条旧的 intermediate 记录")

        # 重新解析意味着文献集完全更换，后续所有流程数据均无效，一并清除
        from core.models import ManualReview
        mr_count, _ = ManualReview.objects.filter(project=self.project_obj).delete()
        if mr_count > 0:
            self.logger.info(f"[清理] 已清除 {mr_count} 条人工审阅记录")

        # 清除 AI 筛选结果（ai_screen 步骤的 output DataFile）
        from core.models import StageStep
        ai_screen_steps = StageStep.objects.filter(
            stage__project=self.project_obj,
            step_key='ai_screen',
        )
        for step in ai_screen_steps:
            ai_qs = DataFile.objects.filter(
                project=self.project_obj,
                step=step,
                data_category='output',
                metadata__artifact_type=ArtifactType.SCREENING_RESULT_JSON,
            )
            ai_cnt, _ = ai_qs.delete()
            if ai_cnt > 0:
                self.logger.info(f"[清理] 已清除 {ai_cnt} 条 AI 筛选结果")

    def _save_outputs(self, merged_xml: Path, split_dir: Path) -> int:
        """保存合并 XML 和单篇 XML 到 DataFile，返回保存数量。"""
        from core.models import Task as _Task

        xml_files = list(split_dir.glob("*.xml"))
        total = len(xml_files) + (1 if merged_xml.exists() else 0)
        saved = 0
        INTERVAL = max(1, len(xml_files) // 20)

        if merged_xml.exists():
            self.save_output_file(
                merged_xml, "references.xml", "合并后的文献XML", "intermediate",
                ArtifactType.SCREENING_PARSED_REFERENCES_XML,
            )
            saved += 1

        for j, xml_file in enumerate(xml_files, 1):
            self.save_output_file(
                xml_file, xml_file.name, "单篇文献XML", "intermediate",
                ArtifactType.SCREENING_PARSED_REFERENCE_XML,
            )
            saved += 1
            if j % INTERVAL == 0 or j == len(xml_files):
                self._update_parse_progress(
                    "saving",
                    70 + int(saved / total * 29), 100,
                    f"[3/3] 保存到数据库 {saved}/{total}",
                )
        return saved

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

    def _write_final_stats(self, total_entries: int, split_count: int, total_files: int) -> None:
        """将最终统计回写到 Task.config 和 StageStep.metadata。"""
        from core.models import Task as _Task
        row = _Task.objects.filter(id=self.executor.task_id).values('config').first()
        cfg = (row['config'] if row and row['config'] else {})
        cfg.update({
            "total_entries": total_entries,
            "split_files": split_count,
            "parse_progress": {
                "phase": "done", "current": 99, "total": 100,
                "message": f"解析完成，共 {split_count} 篇文献，等待收尾...",
            },
        })
        _Task.objects.filter(id=self.executor.task_id).update(config=cfg)

        self.step_obj.metadata = {
            "total_files": total_files,
            "total_entries": total_entries,
            "split_files": split_count,
            "completion_time": datetime.now().isoformat(),
        }
