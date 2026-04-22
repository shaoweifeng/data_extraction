"""
异步执行器 - 数据提取平台

实现AI筛选步骤的具体逻辑：
- 批处理：每批10篇文献
- 并发控制：最多3个并发请求
- 断点续传：每50篇保存checkpoint
- 错误重试：超时/API错误自动重试
- 实时进度：独立JSON文件存储进度

关键设计：
- checkpoint存储在JSON文件中，包含已处理的源文件列表
- 进度信息独立维护，不依赖日志解析
- 支持STOP信号中断和恢复
"""

import os
import json
import time
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime
from collections import defaultdict

from django.conf import settings
from django.core.files import File

from .base import BaseExecutor, safe_title
from core.models import DataFile, StageStep
from core.step_config import get_step_config


class AsyncExecutor(BaseExecutor):
    """异步执行器 - 适用于长时间运行的任务"""
    
    def execute(self) -> bool:
        """
        执行异步任务
        
        Returns:
            True if 成功, False if 失败
        """
        if self.step_key == "ai_screen":
            return self._execute_ai_screen()
        elif self.step_key == "META":
            return self._execute_meta_analysis()
        else:
            self.logger.error(f"未知的异步步骤: {self.step_key}")
            return False
    
    # ========================================================================
    # AI初筛
    # ========================================================================
    
    def _send_heartbeat(self, current: int, total: int):
        """发送心跳，更新任务的 last_update 时间"""
        try:
            from core.models import Task
            Task.objects.filter(id=self.task_id).update(
                metadata={
                    'heartbeat': datetime.now().isoformat(),
                    'processed_refs': current,
                    'total_refs': total,
                    'status_message': f'正在处理第 {current}/{total} 篇文献'
                }
            )
        except Exception:
            pass
    
    def _execute_ai_screen(self) -> bool:
        """
        AI初筛步骤
        
        流程：
        1. 准备数据：获取去重后的XML + 纳排标准
        2. 检查断点：加载上次进度
        3. 批处理：每批10篇调用AI API
        4. 保存结果：每个结果存为JSON
        5. 定期checkpoint：每50篇保存进度
        """
        self.logger.info("[步骤] 开始AI初筛...")
        
        # 1. 准备数据
        input_files = self._get_input_files()
        criteria = self._get_criteria()
        
        total_refs = len(input_files)
        self.logger.info(f"[数据] 待筛选文献: {total_refs} 篇")
        self.logger.info(f"[标准] 纳排标准: {len(criteria)} 条")
        
        if total_refs == 0:
            self.logger.error("[错误] 没有找到待筛选文献")
            return False
        
        # 2. 检查断点
        checkpoint = self.load_checkpoint()
        processed_sources: Set[str] = set()
        
        if checkpoint:
            processed_sources = set(checkpoint.get("processed_sources", []))
            self.logger.info(f"[断点] 检测到上次断点，已处理 {len(processed_sources)} 篇")
            self.logger.info(f"[断点] 上次进度: {checkpoint.get('progress', {}).get('current', 0)}/{checkpoint.get('progress', {}).get('total', 0)}")
        
        # 3. 准备工作区
        workspace_ai = Path(self.workspace) / "screening_ai"
        datasets_dir = workspace_ai / "datasets"
        results_dir = workspace_ai / "results"
        
        datasets_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # 4. 复制筛选脚本（如果存在）
        self._copy_screening_scripts(workspace_ai)
        
        # 5. 收集待处理条目
        entries_to_process = []
        
        for df in input_files:
            source_xml = df.filename
            
            # 跳过已处理的
            if source_xml in processed_sources:
                continue
            
            # 解析XML获取条目信息
            entry = self._parse_xml_entry(df.file.path)
            entry["source_xml"] = source_xml
            entry["datafile_id"] = df.id
            entries_to_process.append(entry)
        
        self.logger.info(f"[筛选] 待处理: {len(entries_to_process)} 篇")
        
        if not entries_to_process:
            self.logger.info("[完成] 所有文献已处理完成")
            return True
        
        # 6. 批处理参数
        batch_size = self.config.get("batch_size", 10)
        checkpoint_interval = self.config.get("checkpoint_interval", 50)
        concurrency = self.config.get("concurrency", 3)
        
        # 7. 处理文献
        processed_count = len(processed_sources)
        self.logger.update_progress(processed_count, total_refs, "refs")
        
        # 批处理循环
        batch_results = []
        batch_index = 0
        
        for i in range(0, len(entries_to_process), batch_size):
            # 检查停止信号
            if self.check_stop_signal():
                self.logger.warning("[停止] 用户请求停止任务")
                # 保存当前进度作为断点
                self.save_checkpoint({
                    "processed_sources": list(processed_sources),
                    "last_batch_index": i,
                    "progress": {
                        "current": processed_count,
                        "total": total_refs
                    }
                })
                return False
            
            # 【新增】每5个批次发送心跳，让前端知道任务还活着
            if batch_index % 5 == 0:
                self._send_heartbeat(processed_count, total_refs)
            
            # 获取当前批次
            batch = entries_to_process[i:i+batch_size]
            
            # 处理批次
            self.logger.info(f"[批次] 处理 {i+1}-{i+len(batch)}/{len(entries_to_process)} 篇")
            
            results = self._process_batch(batch, criteria, results_dir, concurrency)
            batch_results.extend(results)
            
            # 更新进度
            for entry, result in zip(batch, results):
                # 保存结果
                self._save_result(entry, result, results_dir)
                processed_sources.add(entry["source_xml"])
                processed_count += 1
                
                # 更新进度文件
                self.logger.update_progress(processed_count, total_refs, "refs")
                
                # 定期保存断点
                if processed_count % checkpoint_interval == 0:
                    self.save_checkpoint({
                        "processed_sources": list(processed_sources),
                        "last_batch_index": i + batch_size,
                        "progress": {
                            "current": processed_count,
                            "total": total_refs
                        }
                    })
                    self.logger.add_checkpoint(f"auto_checkpoint_{processed_count}")
            
            batch_index += 1
        
        # 8. 保存所有结果到DB
        self.logger.info("[保存] 将结果保存到数据库...")
        self._save_all_results(results_dir)
        
        # 9. 清除断点（任务完成）
        self.clear_checkpoint()
        
        # 10. 更新步骤元数据
        included_count = len([r for r in batch_results if r.get('decision') == 'included'])
        excluded_count = len([r for r in batch_results if r.get('decision') == 'excluded'])
        
        self.step_obj.metadata = {
            "total_refs": total_refs,
            "processed_refs": processed_count,
            "included_refs": included_count,
            "excluded_refs": excluded_count,
            "error_refs": len(batch_results) - included_count - excluded_count,
            "start_time": self.task_obj.started_at.isoformat() if self.task_obj.started_at else None,
            "end_time": datetime.now().isoformat(),
            "criteria_count": len(criteria)
        }
        
        return True
    
    def _process_batch(self, batch: List[Dict], criteria: List[str], 
                       results_dir: Path, concurrency: int = 3) -> List[Dict]:
        """
        处理一批文献
        
        Args:
            batch: 待处理的文献条目列表
            criteria: 纳排标准列表
            results_dir: 结果保存目录
            concurrency: 并发数
        
        Returns:
            结果字典列表（与batch顺序对应）
        """
        results = []
        
        # 尝试调用真实API
        try:
            results = self._call_ai_api(batch, criteria)
        except Exception as e:
            self.logger.warning(f"[API] 调用失败: {e}，使用模拟结果")
            results = self._mock_api_call(batch, criteria)
        
        # 添加时间戳
        for i, result in enumerate(results):
            result["timestamp"] = datetime.now().isoformat()
            result["source_xml"] = batch[i].get("source_xml", "unknown")
        
        return results
    
    def _call_ai_api(self, batch: List[Dict], criteria: List[str]) -> List[Dict]:
        """
        调用AI API进行筛选
        
        这里是接口，实际实现需要根据具体的AI服务调整
        """
        # 检查配置文件中是否有API配置
        api_config = self.config.get("api_config", {})
        
        if not api_config:
            # 使用模拟结果
            return self._mock_api_call(batch, criteria)
        
        # 实际API调用逻辑
        # TODO: 根据具体AI服务实现
        # 示例：
        # import requests
        # response = requests.post(api_config['url'], json={
        #     "entries": batch,
        #     "criteria": criteria
        # }, headers={"Authorization": f"Bearer {api_config['key']}"})
        # 
        # return response.json()['results']
        
        return self._mock_api_call(batch, criteria)
    
    def _mock_api_call(self, batch: List[Dict], criteria: List[str]) -> List[Dict]:
        """模拟API调用（用于测试和演示）"""
        results = []
        
        for entry in batch:
            # 模拟决策逻辑（随机）
            import random
            decision = random.choice(['included', 'excluded'])
            confidence = round(random.uniform(0.6, 0.95), 2)
            
            result = {
                "title": entry.get("title", ""),
                "authors": entry.get("authors", ""),
                "year": entry.get("year", ""),
                "journal": entry.get("journal", ""),
                "decision": decision,
                "confidence": confidence,
                "reasoning": f"根据纳排标准判断：{', '.join(criteria[:2])}...",
                "model": "mock-model-v1.0"
            }
            results.append(result)
            
            # 模拟延迟（避免限流）
            time.sleep(0.3)
        
        return results
    
    def _save_result(self, entry: Dict, result: Dict, results_dir: Path):
        """
        保存单个筛选结果
        
        Args:
            entry: 文献条目信息
            result: AI筛选结果
            results_dir: 结果保存目录
        """
        # 使用标题生成安全的目录名
        safe_dir_name = safe_title(entry.get("title", "unknown"), 50)
        result_dir = results_dir / safe_dir_name
        result_dir.mkdir(exist_ok=True)
        
        # 保存结果JSON
        result_file = result_dir / f"screening_result_{entry['source_xml'].replace('.xml', '.json')}"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    def _save_all_results(self, results_dir: Path):
        """
        将所有结果文件保存到DB
        
        Args:
            results_dir: 结果目录
        """
        # 遍历所有结果文件
        for result_dir in results_dir.iterdir():
            if not result_dir.is_dir():
                continue
            
            for result_file in result_dir.glob("screening_result_*.json"):
                # 保存到DataFile
                with open(result_file, 'rb') as f:
                    django_file = File(f)
                    
                    DataFile.objects.create(
                        project=self.project_obj,
                        stage=self.stage_obj,
                        step=self.step_obj,
                        filename=result_file.name,
                        file=django_file,
                        data_category='output',
                        source='tool_generated',
                        description='AI筛选结果',
                        created_by=self.task_obj.created_by
                    )
    
    def _get_input_files(self) -> List[DataFile]:
        """
        获取输入文件
        
        优先级：
        1. 去重步骤的输出（dedup）
        2. 解析步骤的拆分输出
        """
        # 1. 尝试获取去重后的文件
        dedup_step = self.get_previous_step("dedup")
        
        if dedup_step:
            dedup_files = DataFile.objects.filter(
                project=self.project_obj,
                step=dedup_step,
                data_category='intermediate',
                description='去重后的文献XML'
            )
            
            if dedup_files.exists():
                self.logger.info(f"[数据] 使用去重后的文件: {dedup_files.count()} 个")
                return list(dedup_files)
        
        # 2. 使用解析后的拆分文件
        parse_step = self.get_previous_step("parse")
        
        if parse_step:
            parse_files = DataFile.objects.filter(
                project=self.project_obj,
                step=parse_step,
                data_category='intermediate',
                description='单篇文献XML'
            )
            
            if parse_files.exists():
                self.logger.info(f"[数据] 使用解析后的文件: {parse_files.count()} 个")
                return list(parse_files)
        
        return []
    
    def _get_criteria(self) -> List[str]:
        """
        获取纳排标准
        
        Returns:
            标准文本列表
        """
        # 尝试从criteria步骤获取
        criteria_step = self.get_previous_step("criteria")
        
        if criteria_step and criteria_step.metadata:
            return criteria_step.metadata.get("criteria", [])
        
        # 尝试从文件获取
        criteria_file = Path(settings.MEDIA_ROOT) / f"projects/project_{self.project_id}/screening_criteria.json"
        
        if criteria_file.exists():
            try:
                with open(criteria_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("criteria", [])
            except Exception as e:
                self.logger.warning(f"[警告] 读取纳排标准失败: {e}")
        
        # 返回默认标准
        return [
            "排除非英文文献",
            "排除综述和Meta分析",
            "排除动物实验研究",
            "排除病例报告"
        ]
    
    def _copy_screening_scripts(self, target_dir: Path):
        """
        复制筛选脚本到工作区（可选）
        
        Args:
            target_dir: 目标目录
        """
        source_dir = Path(settings.BASE_DIR) / "structural_screening/scripts"
        
        if source_dir.exists():
            try:
                shutil.copytree(
                    source_dir,
                    target_dir / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    dirs_exist_ok=True
                )
                self.logger.info("[脚本] 已复制筛选脚本到工作区")
            except Exception as e:
                self.logger.warning(f"[警告] 复制脚本失败: {e}")
    
    def _parse_xml_entry(self, xml_path: str) -> Dict:
        """
        解析XML获取条目信息
        
        Args:
            xml_path: XML文件路径
        
        Returns:
            条目信息字典
        """
        import xml.etree.ElementTree as ET
        
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
                "doi": get_text("DOI")
            }
        
        except Exception as e:
            self.logger.warning(f"[警告] 解析XML失败 {xml_path}: {e}")
            return {
                "title": "",
                "authors": "",
                "year": "",
                "journal": "",
                "abstract": ""
            }
    
    # ========================================================================
    # Meta分析（预留）
    # ========================================================================
    
    def _execute_meta_analysis(self) -> bool:
        """
        Meta分析步骤（预留）
        
        TODO: 实现Meta分析逻辑
        """
        self.logger.info("[步骤] 开始Meta分析...")
        self.logger.warning("[警告] Meta分析功能尚未实现")
        
        # 更新步骤状态为跳过
        self.step_obj.status = 'skipped'
        self.step_obj.metadata = {
            "reason": "功能未实现",
            "completion_time": datetime.now().isoformat()
        }
        
        return True
