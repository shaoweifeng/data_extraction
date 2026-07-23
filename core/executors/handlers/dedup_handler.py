"""
自动去重步骤 Handler

负责：
- 获取 parse 步骤输出的单篇 XML 文件
- 基于标题规范化去重（保留首次出现）
- 生成去重报告（dedup_report.json）
- 保存去重后的产物到 DataFile
"""

import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from core.models import DataFile
from core.executors.registry import register
from core.executors.handlers.base_handler import BaseStepHandler


@register("dedup")
class DedupHandler(BaseStepHandler):
    """自动去重步骤 Handler（同步执行）"""

    execution_mode = "sync"

    def execute(self) -> bool:
        """
        去重流程：
        1. 准备目录
        2. 获取 parse 输出的单篇 XML
        3. 基于标题去重，生成保留列表
        4. 生成去重报告
        5. 保存产物到 DataFile
        """
        self.logger.info("[步骤] 开始自动去重...")

        input_dir = self.workspace / "input_xmls"
        output_dir = self.workspace / "dedup_xmls"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 获取 parse 步骤输出
        parse_step = self.executor.get_previous_step("parse")
        input_files: List = []
        if parse_step:
            input_files = list(DataFile.objects.filter(
                project=self.project_obj,
                step=parse_step,
                data_category='intermediate',
                description='单篇文献XML',
            ))
            self.logger.info(f"[输入] 从 parse 步骤获取 {len(input_files)} 个文件")

        if not input_files:
            self.logger.error("[错误] 未找到文献解析步骤的输出文件")
            self.logger.error("[提示] 请先完成步骤1（文献解析）再运行去重")
            return False

        total_files = len(input_files)
        self.logger.update_progress(0, total_files, "refs")

        # 复制文件到工作区
        if not any(input_dir.glob("*.xml")):
            for df in input_files:
                src = Path(df.file.path) if hasattr(df.file, 'path') else Path(df.file)
                if src.exists():
                    shutil.copy(src, input_dir / df.filename)

        # 去重主逻辑
        groups: Dict[str, List] = {}
        ordered_keys: List[str] = []
        kept_files: List[str] = []

        self.logger.info("[去重] 开始基于标题去重...")

        for i, filepath in enumerate(input_dir.iterdir(), 1):
            if not filepath.is_file() or filepath.suffix != '.xml':
                continue

            try:
                meta = self._extract_xml_meta(filepath)
                norm_title = "".join(c.lower() for c in meta['title'] if c.isalnum())

                if not norm_title:
                    self.logger.warning(f"[警告] {filepath.name} 缺少标题，直接保留")
                    kept_files.append(filepath.name)
                    shutil.copy(filepath, output_dir / filepath.name)
                else:
                    if norm_title not in groups:
                        groups[norm_title] = []
                        ordered_keys.append(norm_title)
                    meta['filename'] = filepath.name
                    groups[norm_title].append(meta)

            except Exception as e:
                self.logger.warning(f"[警告] 解析 {filepath.name} 失败: {e}")
                kept_files.append(filepath.name)
                shutil.copy(filepath, output_dir / filepath.name)

            self.logger.update_progress(i, total_files, "refs")
            if self.check_stop_signal():
                return False

        # 按序处理分组，保留首次出现
        duplicates = []
        for norm_title in ordered_keys:
            items = groups[norm_title]
            if len(items) <= 1:
                kept_files.append(items[0]['filename'])
                shutil.copy(input_dir / items[0]['filename'], output_dir / items[0]['filename'])
                continue

            kept = items[0]
            removed = items[1:]
            kept_files.append(kept['filename'])
            shutil.copy(input_dir / kept['filename'], output_dir / kept['filename'])
            duplicates.append({
                "norm_title": norm_title,
                "title": kept.get('title', ''),
                "kept": {k: kept.get(k, '') for k in ('filename', 'source_file', 'source_position', 'year', 'journal', 'doi', 'url')},
                "duplicates": [{k: d.get(k, '') for k in ('filename', 'source_file', 'source_position', 'year', 'journal', 'doi', 'url')} for d in removed],
            })

        duplicate_count = sum(len(d['duplicates']) for d in duplicates)
        dup_rate = duplicate_count / total_files * 100 if total_files > 0 else 0

        self.logger.info(f"[统计] 原始: {total_files} 篇  保留: {len(kept_files)} 篇  重复: {duplicate_count} 篇 ({dup_rate:.1f}%)")

        # 清旧记录，保存新产物
        self._clear_old_intermediate()
        for fname in kept_files:
            fp = output_dir / fname
            if fp.exists():
                self.save_output_file(fp, fname, "去重后的文献XML", "intermediate")

        # 保存去重报告
        report = {
            "total_files": total_files,
            "kept_files": len(kept_files),
            "duplicates": duplicate_count,
            "duplicate_rate": f"{dup_rate:.2f}%",
            "duplicate_groups": len(duplicates),
            "duplicate_details": duplicates[:100],
            "completion_time": datetime.now().isoformat(),
        }
        report_file = self.workspace / "dedup_report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        self.save_output_file(report_file, "dedup_report.json", "去重报告", "output")

        self.step_obj.metadata = report
        self.step_obj.save()
        return True

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _extract_xml_meta(self, filepath: Path) -> Dict:
        """从单篇 XML 中提取标题、年份、来源等元数据。"""
        tree = ET.parse(filepath)
        root = tree.getroot()

        def _find(xpaths):
            for xp in xpaths:
                elem = root.find(xp)
                if elem is not None and elem.text:
                    return elem.text.strip()
            return ""

        return {
            'title':           _find(['.//Title', './/title', './/TI']),
            'year':            _find(['.//Year', './/year', './/YR']),
            'journal':         _find(['.//Journal', './/journal', './/SO']),
            'doi':             _find(['.//Doi', './/DOI', './/doi', './/DI']),
            'url':             _find(['.//Url', './/URL', './/url', './/UR']),
            'source_file':     _find(['.//SourceFile', './/Source_file', './/source_file']),
            'source_position': _find(['.//SourcePosition', './/Source_position', './/source_position']),
        }

    def _clear_old_intermediate(self) -> None:
        old_qs = DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            data_category='intermediate',
        )
        old_count = old_qs.count()
        if old_count > 0:
            old_qs.delete()
            self.logger.info(f"[清理] 已清除 {old_count} 条旧的 intermediate 记录")
