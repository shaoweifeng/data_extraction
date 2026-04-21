"""
同步执行器 - 数据提取平台

实现同步步骤的具体逻辑：
- parse: 文献解析（RIS/BIB/NBIB/XML → 统一XML）
- dedup: 自动去重（基于标题/DOI）
- export: 结果归纳（聚合JSON → Excel/RIS）

特性：
- 轻量快速，毫秒级响应
- 支持进度实时更新
- 支持跳过（如无重复时跳过去重）
"""

import os
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from django.conf import settings
from django.core.files import File

from .base import BaseExecutor, safe_title
from core.models import DataFile, StageStep
from core.step_config import get_step_config


class SyncExecutor(BaseExecutor):
    """同步执行器 - 适用于轻量快速步骤"""
    
    def execute(self) -> bool:
        """
        执行同步任务
        
        Returns:
            True if 成功
            
        Raises:
            Exception: 任务执行失败时抛出，包含错误详情
        """
        try:
            # 根据步骤类型执行不同逻辑
            if self.step_key == "parse":
                result = self._execute_parse()
            elif self.step_key == "dedup":
                result = self._execute_dedup()
            elif self.step_key == "export":
                result = self._execute_export()
            else:
                raise ValueError(f"未知的同步步骤: {self.step_key}")
            
            # 检查执行结果
            if not result:
                raise RuntimeError(f"{self.step_key}步骤执行失败，请查看日志获取详情")
            
            return True
        
        except Exception as e:
            # 记录完整错误信息到日志
            self.logger.error(f"[失败] {type(e).__name__}: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            # 重新抛出异常，让调度器捕获并设置error_message
            raise
    
    # ========================================================================
    # 文献解析
    # ========================================================================
    
    def _execute_parse(self) -> bool:
        """
        文献解析步骤
        
        流程：
        1. 准备输入目录
        2. 复制用户上传的文件到工作区
        3. 调用解析脚本
        4. 生成合并的XML和拆分的单篇XML
        5. 保存输出文件到DB
        """
        self.logger.info("[步骤] 开始文献解析...")
        
        # 1. 准备目录结构
        input_dir = Path(self.workspace) / "input"
        output_dir = Path(self.workspace) / "output"
        split_dir = Path(self.workspace) / "split_xmls"
        
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        split_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. 获取输入文件（用户上传的文献文件）
        input_files = self._get_upload_files()
        
        if not input_files:
            self.logger.error("[错误] 没有找到输入文件，请先上传文献")
            return False
        
        total_files = len(input_files)
        self.logger.info(f"[输入] 找到 {total_files} 个待解析文件")
        self.logger.update_progress(0, total_files, "files")
        
        # 3. 复制文件到工作区
        for i, df in enumerate(input_files, 1):
            dest = input_dir / df.filename
            shutil.copy(df.file.path, dest)
            self.logger.info(f"[复制] {df.filename}")
            self.logger.update_progress(i, total_files, "files")
            
            # 检查停止信号
            if self.check_stop_signal():
                return False
        
        # 4. 调用解析脚本
        self.logger.info("[解析] 调用解析器...")
        
        try:
            # 动态导入解析脚本
            import sys
            import importlib.util
            
            parser_path = Path(settings.BASE_DIR) / "structural_screening/scripts/parser.py"
            
            if not parser_path.exists():
                self.logger.warning(f"[警告] 解析脚本不存在: {parser_path}")
                self.logger.info("[提示] 将使用内置简化解析逻辑")
                entries = self._simple_parse(input_dir)
            else:
                spec = importlib.util.spec_from_file_location("parser", parser_path)
                parser = importlib.util.module_from_spec(spec)
                sys.modules["parser"] = parser
                spec.loader.exec_module(parser)
                
                # 调用解析函数
                merged_xml = output_dir / "references.xml"
                entries = parser.parse_directory(str(input_dir), str(merged_xml))
                
                # 如果有合并函数，调用合并
                if hasattr(parser, 'convert_to_xml'):
                    all_entries = []
                    for f in input_dir.iterdir():
                        if f.suffix.lower() in ['.ris', '.ciw', '.bib', '.nbib', '.xml']:
                            parse_func = getattr(parser, f'parse_{f.suffix[1:]}', None)
                            if parse_func:
                                all_entries.extend(parse_func(str(f)))
                    
                    parser.convert_to_xml(all_entries, str(merged_xml))
                    entries = all_entries
            
            total_entries = len(entries) if isinstance(entries, list) else entries.get('total_entries', 0)
            self.logger.info(f"[解析] 成功解析 {total_entries} 条文献")
            
        except Exception as e:
            self.logger.error(f"[错误] 解析失败: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
        
        # 5. 拆分为单篇XML
        self.logger.info("[拆分] 开始拆分为单篇文献...")
        
        merged_xml = output_dir / "references.xml"
        if merged_xml.exists():
            split_count = self._split_xml(merged_xml, split_dir)
            self.logger.info(f"[拆分] 生成 {split_count} 个单篇XML")
        else:
            self.logger.warning("[警告] 未找到合并的XML文件")
        
        # 6. 保存输出文件
        self.logger.info("[保存] 保存输出文件到数据库...")
        
        # 保存合并的XML
        if merged_xml.exists():
            self.save_output_file(merged_xml, "references.xml", "合并后的文献XML", "intermediate")
        
        # 保存拆分的单篇XML
        split_count = 0
        for xml_file in split_dir.glob("*.xml"):
            self.save_output_file(xml_file, xml_file.name, "单篇文献XML", "intermediate")
            split_count += 1
        
        self.logger.info(f"[完成] 已保存 {split_count} 个文件")
        
        # 7. 更新步骤元数据
        self.step_obj.metadata = {
            "total_files": total_files,
            "total_entries": total_entries,
            "split_files": split_count,
            "completion_time": datetime.now().isoformat()
        }
        
        return True
    
    def _simple_parse(self, input_dir: Path) -> List[Dict]:
        """简化解析逻辑（备用）"""
        entries = []
        
        for file_path in input_dir.iterdir():
            if file_path.suffix.lower() == '.xml':
                try:
                    tree = ET.parse(file_path)
                    root = tree.getroot()
                    
                    for ref in root.findall('.//reference'):
                        entry = {
                            'title': ref.findtext('title', ''),
                            'authors': ref.findtext('authors', ''),
                            'year': ref.findtext('year', ''),
                            'journal': ref.findtext('journal', ''),
                            'abstract': ref.findtext('abstract', '')
                        }
                        entries.append(entry)
                except Exception as e:
                    self.logger.warning(f"[警告] 解析 {file_path.name} 失败: {e}")
        
        return entries
    
    def _split_xml(self, merged_xml: Path, split_dir: Path) -> int:
        """
        拆分合并的XML为单篇文件
        
        Args:
            merged_xml: 合并的XML文件路径
            split_dir: 拆分输出目录
        
        Returns:
            拆分的文件数量
        """
        try:
            tree = ET.parse(merged_xml)
            root = tree.getroot()
            
            count = 0
            for ref in root.findall('.//reference'):
                # 提取标题生成文件名
                title_elem = ref.find('title')
                if title_elem is not None and title_elem.text:
                    title = title_elem.text.strip()
                else:
                    title = f"unknown_{count}"
                
                # 生成安全的文件名
                safe_name = safe_title(title, 50)
                xml_file = split_dir / f"{safe_name}.xml"
                
                # 创建单篇XML
                single_root = ET.Element('references')
                single_root.append(ref)
                
                tree = ET.ElementTree(single_root)
                tree.write(xml_file, encoding='utf-8', xml_declaration=True)
                
                count += 1
            
            return count
        
        except Exception as e:
            self.logger.error(f"[错误] 拆分XML失败: {e}")
            return 0
    
    def _get_upload_files(self) -> List[DataFile]:
        """获取用户上传的文献文件"""
        # 获取当前步骤所属阶段的输入文件
        if self.stage_obj:
            return list(DataFile.objects.filter(
                project=self.project_obj,
                stage=self.stage_obj,
                data_category='input'
            ))
        
        # 如果没有阶段信息，获取所有未分配阶段的输入文件
        return list(DataFile.objects.filter(
            project=self.project_obj,
            stage__isnull=True,
            data_category='input'
        ))
    
    # ========================================================================
    # 自动去重
    # ========================================================================
    
    def _execute_dedup(self) -> bool:
        """
        自动去重步骤
        
        流程：
        1. 获取parse步骤输出的单篇XML（如果存在）
        2. 如果没有parse输出，直接处理用户上传的原始文件
        3. 基于标题/DOI进行去重
        4. 保留唯一的文献
        5. 生成去重报告
        """
        self.logger.info("[步骤] 开始自动去重...")
        
        # 1. 准备目录
        input_dir = Path(self.workspace) / "input_xmls"
        output_dir = Path(self.workspace) / "dedup_xmls"
        
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. 尝试获取parse步骤的输出文件
        parse_step = self.get_previous_step("parse")
        input_files = []
        
        if parse_step:
            # 从parse步骤获取已解析的XML文件
            input_files = list(DataFile.objects.filter(
                project=self.project_obj,
                step=parse_step,
                data_category='intermediate',
                description='单篇文献XML'
            ))
            self.logger.info(f"[输入] 从parse步骤获取 {len(input_files)} 个文件")
        
        # 3. 如果没有parse输出，直接处理用户上传的原始文件
        if not input_files:
            self.logger.info("[提示] 未找到parse步骤输出，直接处理用户上传的原始文件")
            input_files = self._get_upload_files()
            
            if not input_files:
                self.logger.error("[错误] 没有找到任何待去重的文献文件")
                return False
            
            self.logger.info(f"[输入] 找到 {len(input_files)} 个用户上传的文件")
            
            # 先解析原始文件为XML
            parse_success = self._quick_parse_files(input_files, input_dir)
            if not parse_success:
                self.logger.error("[错误] 解析原始文件失败")
                return False
            
            # 重新扫描解析后的文件
            input_files = [DataFile(filename=f.name, file=str(f)) for f in input_dir.glob("*.xml")]
        
        total_files = len(input_files)
        self.logger.info(f"[输入] 共 {total_files} 个待去重文件")
        
        if total_files == 0:
            self.logger.error("[错误] 没有找到待去重的文献文件")
            return False
        
        self.logger.update_progress(0, total_files, "refs")
        
        # 4. 复制文件到工作区（如果还没复制）
        if not any(input_dir.glob("*.xml")):
            for df in input_files:
                if hasattr(df, 'file') and hasattr(df.file, 'path'):
                    src_path = Path(df.file.path)
                else:
                    src_path = Path(df.file) if isinstance(df.file, str) else Path(df.filename)
                
                if src_path.exists():
                    shutil.copy(src_path, input_dir / df.filename)
        
        # 5. 去重逻辑（基于标题）
        seen_titles = set()
        seen_dois = set()
        duplicates = []
        kept_files = []
        
        self.logger.info("[去重] 开始基于标题/DOI去重...")
        
        for i, filename in enumerate(input_dir.iterdir(), 1):
            if not filename.is_file() or not filename.suffix == '.xml':
                continue
            
            filepath = input_dir / filename
            
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()
                
                # 提取标题（尝试多种格式）
                title = ""
                for xpath in ['.//Title', './/title', './/TI']:
                    title_elem = root.find(xpath)
                    if title_elem is not None and title_elem.text:
                        title = title_elem.text.strip().lower()
                        break
                
                # 提取DOI（尝试多种格式）
                doi = ""
                for xpath in ['.//DOI', './/doi', './/DI']:
                    doi_elem = root.find(xpath)
                    if doi_elem is not None and doi_elem.text:
                        doi = doi_elem.text.strip().lower()
                        break
                
                # 判断重复
                is_duplicate = False
                
                if doi and doi in seen_dois:
                    is_duplicate = True
                    self.logger.info(f"[重复DOI] {filename.name}")
                elif title and title in seen_titles:
                    is_duplicate = True
                    self.logger.info(f"[重复标题] {filename.name}")
                else:
                    if title:
                        seen_titles.add(title)
                    if doi:
                        seen_dois.add(doi)
                    kept_files.append(filename.name)
                    # 复制到输出目录
                    shutil.copy(filepath, output_dir / filename.name)
                
                if is_duplicate:
                    duplicates.append(filename.name)
                
            except Exception as e:
                self.logger.warning(f"[警告] 解析 {filename.name} 失败: {e}")
                # 解析失败的也保留
                kept_files.append(filename.name)
                shutil.copy(filepath, output_dir / filename.name)
            
            self.logger.update_progress(i, total_files, "refs")
            
            # 检查停止信号
            if self.check_stop_signal():
                return False
        
        # 6. 统计信息
        duplicate_rate = len(duplicates) / total_files * 100 if total_files > 0 else 0
        
        self.logger.info(f"[统计] 原始文献: {total_files} 篇")
        self.logger.info(f"[统计] 去重后保留: {len(kept_files)} 篇")
        self.logger.info(f"[统计] 重复文献: {len(duplicates)} 篇 ({duplicate_rate:.1f}%)")
        
        # 7. 保存去重后的文件
        for filename in kept_files:
            filepath = output_dir / filename
            if filepath.exists():
                self.save_output_file(filepath, filename, "去重后的文献XML", "intermediate")
        
        # 8. 生成去重报告
        report = {
            "total_files": total_files,
            "kept_files": len(kept_files),
            "duplicates": len(duplicates),
            "duplicate_rate": f"{duplicate_rate:.2f}%",
            "duplicate_files": duplicates[:100],  # 只存前100个
            "completion_time": datetime.now().isoformat()
        }
        
        report_file = Path(self.workspace) / "dedup_report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        self.save_output_file(report_file, "dedup_report.json", "去重报告", "output")
        
        # 9. 更新步骤元数据
        self.step_obj.metadata = report
        self.step_obj.save()  # 必须调用save()方法保存到数据库
        
        return True
    
    def _quick_parse_files(self, input_files: List, output_dir: Path) -> bool:
        """快速解析原始文件为XML"""
        self.logger.info("[解析] 开始快速解析原始文件...")
        
        try:
            # 动态导入解析脚本
            import sys
            import importlib.util
            
            parser_path = Path(settings.BASE_DIR) / "structural_screening/scripts/parser.py"
            
            if parser_path.exists():
                spec = importlib.util.spec_from_file_location("parser", parser_path)
                parser = importlib.util.module_from_spec(spec)
                sys.modules["parser"] = parser
                spec.loader.exec_module(parser)
                
                for df in input_files:
                    if hasattr(df, 'file') and hasattr(df.file, 'path'):
                        src_path = Path(df.file.path)
                    else:
                        continue
                    
                    if not src_path.exists():
                        continue
                    
                    # 解析单个文件
                    try:
                        if hasattr(parser, 'parse_file'):
                            entries = parser.parse_file(str(src_path))
                            if entries:
                                # 为每个条目生成XML
                                for i, entry in enumerate(entries):
                                    title = entry.get('title', f'unknown_{i}')
                                    safe_name = safe_title(title, 50)
                                    xml_path = output_dir / f"{safe_name}.xml"
                                    
                                    # 创建简单XML
                                    root = ET.Element('reference')
                                    for key, value in entry.items():
                                        elem = ET.SubElement(root, key.capitalize())
                                        elem.text = str(value) if value else ''
                                    
                                    tree = ET.ElementTree(root)
                                    tree.write(xml_path, encoding='utf-8', xml_declaration=True)
                                
                                self.logger.info(f"[解析] {src_path.name} → {len(entries)} 篇")
                    except Exception as e:
                        self.logger.warning(f"[警告] 解析 {src_path.name} 失败: {e}")
            else:
                self.logger.warning(f"[警告] 解析脚本不存在: {parser_path}")
                # 使用简单的解析逻辑
                for df in input_files:
                    if hasattr(df, 'file') and hasattr(df.file, 'path'):
                        src_path = Path(df.file.path)
                    else:
                        continue
                    
                    if not src_path.exists():
                        continue
                    
                    # 根据文件类型使用简单解析
                    if src_path.suffix.lower() == '.xml':
                        try:
                            tree = ET.parse(src_path)
                            root = tree.getroot()
                            
                            # 尝试提取references
                            for i, ref in enumerate(root.findall('.//reference') + root.findall('.//Reference')):
                                title_elem = ref.find('Title') or ref.find('title')
                                title = title_elem.text if title_elem is not None and title_elem.text else f"unknown_{i}"
                                safe_name = safe_title(title.strip(), 50)
                                
                                xml_path = output_dir / f"{safe_name}.xml"
                                single_root = ET.Element('reference')
                                single_root.extend(list(ref))
                                
                                tree = ET.ElementTree(single_root)
                                tree.write(xml_path, encoding='utf-8', xml_declaration=True)
                            
                            self.logger.info(f"[解析] {src_path.name}")
                        except Exception as e:
                            self.logger.warning(f"[警告] 简单解析 {src_path.name} 失败: {e}")
            
            # 检查输出
            xml_count = len(list(output_dir.glob("*.xml")))
            self.logger.info(f"[解析] 共生成 {xml_count} 个XML文件")
            
            return xml_count > 0
            
        except Exception as e:
            self.logger.error(f"[错误] 快速解析失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    # ========================================================================
    # 结果归纳
    # ========================================================================
    
    def _execute_export(self) -> bool:
        """
        结果归纳步骤
        
        流程：
        1. 获取ai_screen步骤输出的所有JSON结果
        2. 聚合结果（每目录只取最新的JSON）
        3. 生成Excel和RIS文件
        """
        self.logger.info("[步骤] 开始结果归纳...")
        
        # 1. 获取ai_screen步骤的输出
        ai_step = self.get_previous_step("ai_screen")
        
        if not ai_step:
            self.logger.error("[错误] 未找到ai_screen步骤")
            return False
        
        result_files = DataFile.objects.filter(
            project=self.project_obj,
            step=ai_step,
            data_category='output',
            description='AI筛选结果'
        )
        
        self.logger.info(f"[输入] 找到 {result_files.count()} 个结果文件")
        
        if result_files.count() == 0:
            self.logger.warning("[警告] 没有筛选结果，将生成空报告")
        
        # 2. 聚合结果（按目录分组，取最新的）
        from collections import defaultdict
        
        results_by_dir = defaultdict(list)
        
        for df in result_files:
            # 从路径中提取目录名
            parts = df.file.path.split('/')
            results_dir = parts[-2] if len(parts) >= 2 else 'unknown'
            results_by_dir[results_dir].append(df)
        
        # 每个目录只取最新的结果
        final_results = []
        
        for dir_name, files in results_by_dir.items():
            # 按更新时间排序
            files_sorted = sorted(files, key=lambda x: x.updated_at, reverse=True)
            latest_file = files_sorted[0]
            
            try:
                with open(latest_file.file.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    final_results.append(data)
                    self.logger.debug(f"[聚合] {latest_file.filename}")
            except Exception as e:
                self.logger.warning(f"[警告] 读取 {latest_file.filename} 失败: {e}")
        
        self.logger.info(f"[聚合] 有效结果: {len(final_results)} 个")
        
        # 3. 生成Excel
        self.logger.info("[导出] 生成Excel文件...")
        
        try:
            import pandas as pd
            
            rows = []
            for result in final_results:
                rows.append({
                    "标题": result.get("title", ""),
                    "作者": result.get("authors", ""),
                    "年份": result.get("year", ""),
                    "期刊": result.get("journal", ""),
                    "筛选结果": result.get("decision", ""),
                    "置信度": result.get("confidence", ""),
                    "理由": result.get("reasoning", ""),
                    "源文件": result.get("source_xml", ""),
                    "处理时间": result.get("timestamp", "")
                })
            
            df = pd.DataFrame(rows)
            
            excel_path = Path(self.workspace) / "screening_results.xlsx"
            df.to_excel(excel_path, index=False, engine='openpyxl')
            
            self.logger.info(f"[导出] 生成Excel: {len(rows)} 行")
            
        except ImportError:
            self.logger.warning("[警告] pandas未安装，跳过Excel生成")
            excel_path = None
        except Exception as e:
            self.logger.error(f"[错误] 生成Excel失败: {e}")
            excel_path = None
        
        # 4. 生成RIS（可选）
        ris_path = None
        included_results = [r for r in final_results if r.get('decision') == 'included']
        
        if included_results:
            self.logger.info("[导出] 生成RIS文件...")
            ris_path = self._generate_ris(included_results)
        
        # 5. 保存输出文件
        if excel_path and excel_path.exists():
            self.save_output_file(excel_path, "screening_results.xlsx", "初筛结果Excel", "output")
        
        if ris_path and ris_path.exists():
            self.save_output_file(ris_path, "screening_results.ris", "初筛结果RIS", "output")
        
        # 6. 更新步骤元数据
        included_count = len([r for r in final_results if r.get('decision') == 'included'])
        excluded_count = len([r for r in final_results if r.get('decision') == 'excluded'])
        
        self.step_obj.metadata = {
            "total_results": len(final_results),
            "included_count": included_count,
            "excluded_count": excluded_count,
            "completion_time": datetime.now().isoformat()
        }
        
        return True
    
    def _generate_ris(self, results: List[Dict]) -> Optional[Path]:
        """生成RIS格式文件"""
        ris_path = Path(self.workspace) / "screening_results.ris"
        
        try:
            with open(ris_path, 'w', encoding='utf-8') as f:
                for r in results:
                    f.write("TY  - JOUR\n")
                    f.write(f"TI  - {r.get('title', '')}\n")
                    f.write(f"AU  - {r.get('authors', '')}\n")
                    f.write(f"PY  - {r.get('year', '')}\n")
                    f.write(f"JO  - {r.get('journal', '')}\n")
                    f.write(f"AB  - {r.get('abstract', '')}\n")
                    f.write("ER  - \n\n")
            
            self.logger.info(f"[导出] 生成RIS: {len(results)} 条")
            return ris_path
        
        except Exception as e:
            self.logger.error(f"[错误] 生成RIS失败: {e}")
            return None
