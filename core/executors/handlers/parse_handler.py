"""
文献解析步骤 Handler

负责：
- 复制上传文件到工作区
- 调用解析器（core.executors.parsers.parser）生成条目
- 生成单篇 XML 索引文件
- 保存产物到 DataFile
"""

import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from core.models import DataFile
from core.executors.registry import register
from core.executors.handlers.base_handler import BaseStepHandler
from core.executors.base import safe_title
from core.executors.parsers import parser as _parser


@register("parse")
class ParseHandler(BaseStepHandler):
    """文献解析步骤 Handler（同步执行）"""

    execution_mode = "sync"

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
        entries, merged_xml = self._run_parser(input_dir, output_dir)
        if entries is None:
            return False

        total_entries = len(entries) if isinstance(entries, list) else entries.get('total_entries', 0)
        self.logger.info(f"[解析] 成功解析 {total_entries} 条文献")

        # 4. 生成单篇 XML 索引
        self._update_parse_progress("splitting", 10, 100, f"[2/3] 解析完成 {total_entries} 条，准备生成单篇索引...")
        all_entries = entries if isinstance(entries, list) else []
        split_count = self._generate_split_xmls(all_entries, split_dir)
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

    def _run_parser(self, input_dir: Path, output_dir: Path):
        """调用解析器，返回 (entries, merged_xml_path)。失败返回 (None, None)。"""
        merged_xml = output_dir / "references.xml"

        try:
            entries = _parser.parse_directory(str(input_dir))
            if entries:
                _parser.convert_to_xml(entries, str(merged_xml))
        except Exception as e:
            self.logger.error(f"[错误] 解析失败: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None, None

        return entries, merged_xml

    def _generate_split_xmls(self, all_entries: List[Dict], split_dir: Path) -> int:
        """为每条条目生成单篇 XML 文件，返回生成数量。"""
        FIELD_MAP = [
            ('title', 'Title'), ('authors', 'Authors'), ('year', 'Year'),
            ('journal', 'Journal'), ('volume', 'Volume'), ('issue', 'Issue'),
            ('page', 'Page'), ('date', 'Date'), ('reference_type', 'ReferenceType'),
            ('pmcid', 'PMCID'), ('address', 'Address'), ('abstract', 'Abstract'),
            ('doi', 'Doi'), ('url', 'Url'),
        ]
        total = len(all_entries)
        INTERVAL = max(1, total // 20)
        count = 0

        for i, entry in enumerate(all_entries, 1):
            title = entry.get('title', f'unknown_{i}')
            safe_name = safe_title(title, 40)
            xml_file = split_dir / f"{i:05d}_{safe_name}.xml"

            root = ET.Element('reference')
            for field_key, xml_tag in FIELD_MAP:
                value = entry.get(field_key)
                if value:
                    elem = ET.SubElement(root, xml_tag)
                    elem.text = '; '.join(str(v) for v in value if v) if isinstance(value, list) else str(value)

            source_file = entry.get('source_file', 'unknown')
            ET.SubElement(root, 'SourceFile').text = str(source_file)
            ET.SubElement(root, 'SourcePosition').text = str(entry.get('source_position', i))

            ET.ElementTree(root).write(xml_file, encoding='utf-8', xml_declaration=True)
            count += 1

            if i % INTERVAL == 0 or i == total:
                self._update_parse_progress(
                    "splitting",
                    10 + int(i / total * 60), 100,
                    f"[2/3] 生成单篇索引 {i}/{total}",
                )
        return count

    def _clear_old_intermediate(self) -> None:
        """清除本步骤旧的 intermediate DataFile 记录，避免重复运行时累加。"""
        old_qs = DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            data_category='intermediate',
        )
        old_count = old_qs.count()
        if old_count > 0:
            old_qs.delete()
            self.logger.info(f"[清理] 已清除 {old_count} 条旧的 intermediate 记录")

    def _save_outputs(self, merged_xml: Path, split_dir: Path) -> int:
        """保存合并 XML 和单篇 XML 到 DataFile，返回保存数量。"""
        from core.models import Task as _Task

        xml_files = list(split_dir.glob("*.xml"))
        total = len(xml_files) + (1 if merged_xml.exists() else 0)
        saved = 0
        INTERVAL = max(1, len(xml_files) // 20)

        if merged_xml.exists():
            self.save_output_file(merged_xml, "references.xml", "合并后的文献XML", "intermediate")
            saved += 1

        for j, xml_file in enumerate(xml_files, 1):
            self.save_output_file(xml_file, xml_file.name, "单篇文献XML", "intermediate")
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
