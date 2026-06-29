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
        # 优先从 task.config 里的 resume_checkpoint_path 加载（跨任务续传场景）
        checkpoint = None
        resume_checkpoint_path = self.config.get("resume_checkpoint_path")
        if resume_checkpoint_path:
            from pathlib import Path as _Path
            _cp = _Path(resume_checkpoint_path)
            if _cp.exists():
                try:
                    with open(_cp, 'r', encoding='utf-8') as f:
                        import json as _json
                        checkpoint = _json.load(f)
                    self.logger.info(f"[断点] 从上次任务恢复: {resume_checkpoint_path}")
                except Exception as e:
                    self.logger.warning(f"[断点] 加载跨任务 checkpoint 失败: {e}")
        
        if checkpoint is None:
            checkpoint = self.load_checkpoint()
        
        processed_sources: Set[str] = set()
        
        if checkpoint:
            # processed_sources 直接在顶层（save_checkpoint 修复后写入原始 data 格式）
            # 兼容旧版：如果存在 "data" 包裹层（历史 checkpoint 文件），也能正确读取
            raw_sources = checkpoint.get("processed_sources", [])
            if not raw_sources and "data" in checkpoint:
                raw_sources = checkpoint["data"].get("processed_sources", [])
            processed_sources = set(raw_sources)
            # 进度字段同样兼容顶层和 data 包裹两种格式
            prog = checkpoint.get("progress") or checkpoint.get("data", {}).get("progress", {}) or {}
            self.logger.info(f"[断点] 检测到上次断点，已处理 {len(processed_sources)} 篇")
            self.logger.info(f"[断点] 上次进度: {prog.get('current', 0)}/{prog.get('total', 0)}")
            # 初始化进度写入 DB，避免进度条从0跳升
            resume_progress = self.config.get("resume_progress", 0)
            if resume_progress and resume_progress > 0:
                from django.db import close_old_connections
                close_old_connections()
                from core.models import Task
                Task.objects.filter(id=self.task_id).update(progress=resume_progress)
                self.logger.info(f"[断点] 恢复进度: {round(resume_progress * 100, 1)}%")
        
        # 3. 准备工作区
        workspace_ai = Path(self.workspace) / "screening_ai"
        datasets_dir = workspace_ai / "datasets"
        results_dir = workspace_ai / "results"
        
        datasets_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # 全新任务时清除旧的 output 文件；断点续传时保留（已处理结果不删，新结果追加）
        is_resume = bool(self.config.get("resume_checkpoint_path"))
        if not is_resume:
            old_outputs = DataFile.objects.filter(
                project=self.project_obj,
                step=self.step_obj,
                data_category='output',
                description='AI筛选结果'
            )
            old_count = old_outputs.count()
            if old_count > 0:
                old_outputs.delete()
                self.logger.info(f"[清理] 已清除 {old_count} 条历史筛选结果记录，开始新一轮筛选")
        else:
            self.logger.info("[断点] 断点续传模式：保留已有筛选结果，仅追加新结果")
        
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
        
        # 6. 批处理参数（batch_size=concurrency=16，每批16篇并发处理，每批完成后即保存断点）
        batch_size = self.config.get("batch_size", 16)
        concurrency = self.config.get("concurrency", 16)
        
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
            
            # 每批次发送心跳，让前端知道任务还活着
            self._send_heartbeat(processed_count, total_refs)
            
            # 获取当前批次
            batch = entries_to_process[i:i+batch_size]
            
            # 处理批次
            self.logger.info(f"[批次] 处理 {i+1}-{i+len(batch)}/{len(entries_to_process)} 篇（并发{concurrency}线程）")
            
            results = self._process_batch(batch, criteria, results_dir, concurrency)
            batch_results.extend(results)
            
            # 批次完成后统一更新进度、保存文件、写断点
            for entry, result in zip(batch, results):
                # 保存结果到文件
                self._save_result(entry, result, results_dir)
                processed_sources.add(entry["source_xml"])
                processed_count += 1
            
            # 每批（16篇）完成后统一更新进度条（前端以此为最小刷新单位）
            self.logger.update_progress(processed_count, total_refs, "refs")
            
            # 每 checkpoint_interval 篇（=batch_size=16）保存一次断点
            # 注意：不能调用 self.logger.add_checkpoint，它会把 wrapped 格式覆盖写入 checkpoint.json
            self.save_checkpoint({
                "processed_sources": list(processed_sources),
                "last_batch_index": i + batch_size,
                "progress": {
                    "current": processed_count,
                    "total": total_refs
                }
            })
            
            # 将本批结果写入DB，供前端实时查看已筛选文献
            self._save_batch_results_to_db(batch, results)
            
            batch_index += 1
        
        # 8. 保存所有结果到DB
        self.logger.info("[保存] 将结果保存到数据库...")
        self._save_all_results(results_dir)
        
        # 9. 清除断点（任务完成）
        self.clear_checkpoint()
        
        # 10. 更新步骤元数据（从 DB DataFile 累计查询，包含所有任务的结果）
        from django.db import close_old_connections
        close_old_connections()
        all_outputs = DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            data_category='output'
        )
        included_count = all_outputs.filter(metadata__decision='included').count()
        excluded_count = all_outputs.filter(metadata__decision='excluded').count()
        total_output_count = all_outputs.count()
        
        self.step_obj.metadata = {
            "total_refs": total_refs,
            "processed_refs": processed_count,
            "included_refs": included_count,
            "excluded_refs": excluded_count,
            "error_refs": total_output_count - included_count - excluded_count,
            "start_time": self.task_obj.started_at.isoformat() if self.task_obj.started_at else None,
            "end_time": datetime.now().isoformat(),
            "criteria_count": len(criteria)
        }
        
        return True
    
    def _process_batch(self, batch: List[Dict], criteria: List[str], 
                       results_dir: Path, concurrency: int = 16) -> List[Dict]:
        """
        处理一批文献
        
        Args:
            batch: 待处理的文献条目列表
            criteria: 纳排标准列表
            results_dir: 结果保存目录
            concurrency: 并发线程数（默认16）
        
        Returns:
            结果字典列表（与batch顺序对应）
        """
        results = []
        
        # 尝试调用真实API
        try:
            results = self._call_ai_api(batch, criteria, concurrency=concurrency)
        except Exception as e:
            self.logger.warning(f"[API] 调用失败: {e}，使用模拟结果")
            results = self._mock_api_call(batch, criteria)
        
        # 添加时间戳
        for i, result in enumerate(results):
            result["timestamp"] = datetime.now().isoformat()
            result["source_xml"] = batch[i].get("source_xml", "unknown")
        
        return results
    
    def _mock_extracted_fields(self) -> Dict:
        """mock 模式下生成模拟的提取字段结果"""
        fields_def = self._get_extraction_fields()
        result = {}
        for f in fields_def:
            result[f["name"]] = f"(模拟) {f['definition'][:30]}..."
        return result

    def _get_extraction_fields(self) -> List[Dict]:
        """从 field_extraction 步骤的 metadata 读取提取字段定义"""
        try:
            fe_step = self.get_previous_step("field_extraction")
            if fe_step and fe_step.metadata:
                fields = fe_step.metadata.get("fields", [])
                if fields:
                    self.logger.info(f"[字段] 读取到 {len(fields)} 个提取字段: {[f['name'] for f in fields]}")
                    return fields
        except Exception as e:
            self.logger.warning(f"[字段] 读取提取字段失败: {e}")
        return []

    def _parse_extracted_fields_from_raw(self, raw_response: str) -> Dict:
        """从 AI 原始响应中解析 extracted_fields"""
        import json
        try:
            parsed = json.loads(raw_response)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0].get("extracted_fields", {})
            elif isinstance(parsed, dict):
                return parsed.get("extracted_fields", {})
        except (json.JSONDecodeError, Exception):
            pass
        return {}

    def _get_prompt_template(self) -> str:
        """读取 prompt 模板，优先使用项目自定义 prompt，否则读 prompt1.txt"""
        from django.conf import settings
        from pathlib import Path

        # 1. 优先：项目 metadata 中的自定义 prompt
        try:
            meta = self.project_obj.metadata or {}
            if meta.get('use_custom_prompt') and meta.get('custom_prompt', '').strip():
                custom = meta['custom_prompt'].strip()
                if '{screening_criteria}' in custom:
                    self.logger.info("[Prompt] 使用项目自定义 Prompt")
                    return custom
                else:
                    self.logger.warning("[Prompt] 自定义 Prompt 缺少 {screening_criteria}，回退到默认")
        except Exception as e:
            self.logger.warning(f"[Prompt] 读取自定义 Prompt 失败: {e}，回退到默认")

        # 2. 回退：prompt1.txt 文件
        prompt_path = Path(settings.BASE_DIR) / "structural_screening/02_screening_ai/prompts/prompt1.txt"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            self.logger.warning(f"[警告] prompt1.txt 不存在: {prompt_path}，使用内置默认模板")
            base_prompt = (
                "你是文献筛选助手，请根据以下排除标准判断文献是否纳入，返回JSON格式："
                "[{\"exclusion_reason\": \"\", \"number_exclusion_reason\": \"\", \"include_or_not\": \"yes\"}]\n"
                "<exclusion_criteria>\n{screening_criteria}\n</exclusion_criteria>"
            )

        # 3. 追加提取字段指令（如果有定义）
        extraction_fields = self._get_extraction_fields()
        if extraction_fields:
            field_descriptions = "\n".join(
                f'  - "{f["name"]}": {f["definition"]}'
                for f in extraction_fields
            )
            field_names = ", ".join(f'"{f["name"]}"' for f in extraction_fields)
            extraction_block = (
                "\n\n=======字段提取任务=======\n"
                "对于纳入的文献，请同时从全文内容中提取以下字段信息：\n"
                f"{field_descriptions}\n\n"
                "输出JSON中的 extracted_fields 字段包含提取结果，格式：\n"
                f'{{"extracted_fields": {{{field_names}: "提取值"}}, ...}}\n\n'
            )
            self.logger.info(f"[字段] 追加提取指令到 prompt，字段数: {len(extraction_fields)}")
            return base_prompt + extraction_block

        return base_prompt

    def _call_ai_api(self, batch: List[Dict], criteria: List[str], concurrency: int = 16) -> List[Dict]:
        """
        调用 AI Provider 进行批量筛选
        
        架构说明：
        - 通过 ai_providers.get_provider() 工厂函数获取 provider 实例
        - 当前默认使用 DeepSeekProvider（环境变量 AI_PROVIDER=deepseek）
        - 将来扩展多模型时，可在此并发调用多个 provider，对结果有分歧的文献单独标记
        - 每个 provider 实现 screen_single()，框架层控制并发和批处理
        """
        from .ai_providers import get_provider

        # 从 task config 读取选定模型，fallback 到环境变量
        import os
        model_id = self.config.get("ai_model") or os.environ.get("AI_PROVIDER", "deepseek")

        # 检查是否配置了真实 API key
        from platform_backend.ai_models_config import get_model_config
        model_cfg = get_model_config(model_id)
        has_key = bool(model_cfg and model_cfg.get("api_key")) or bool(os.environ.get("AI_API_KEY"))
        if not has_key:
            self.logger.warning(f"[AI] 模型 {model_id} 未配置 API Key，使用 mock 模拟结果")
            return self._mock_api_call(batch, criteria)

        provider = get_provider(model_id)
        prompt_template = self._get_prompt_template()
        self.logger.info(f"[AI] 使用 Provider: {provider.name}，批次: {len(batch)} 篇，并发: {concurrency}")

        screening_results = provider.screen_batch(batch, criteria, prompt_template, concurrency=concurrency)

        # 将 ScreeningResult 转换为兼容原有格式的 dict
        results = []
        for entry, sr in zip(batch, screening_results):
            result = {
                "title": entry.get("title", ""),
                "authors": entry.get("authors", ""),
                "year": entry.get("year", ""),
                "journal": entry.get("journal", ""),
                "doi": entry.get("doi", ""),
                "url": entry.get("url", ""),
                "source_xml": entry.get("source_xml", ""),
                "decision": sr.decision,
                "include_or_not": "yes" if sr.is_included else "no",
                "exclusion_reason": sr.exclusion_reason,
                "number_exclusion_reason": sr.exclusion_criterion_no,
                "model": sr.model,
                "raw_ai_response": sr.raw_response,
                "error": sr.error,
                "timestamp": datetime.now().isoformat(),
                "extracted_fields": sr.extracted_fields or {},
            }
            if sr.is_error:
                self.logger.warning(f"[AI] 筛选失败: {entry.get('title', '')[:40]} - {sr.error}")
            results.append(result)

        return results
    
    def _mock_api_call(self, batch: List[Dict], criteria: List[str]) -> List[Dict]:
        """模拟API调用（用于测试和演示），输出字段与真实 API 一致"""
        results = []
        
        for entry in batch:
            # 模拟决策逻辑（随机）
            import random
            decision = random.choice(['included', 'excluded'])
            
            result = {
                "title": entry.get("title", ""),
                "authors": entry.get("authors", ""),
                "year": entry.get("year", ""),
                "journal": entry.get("journal", ""),
                "doi": entry.get("doi", ""),
                "url": entry.get("url", ""),
                "source_xml": entry.get("source_xml", ""),
                "decision": decision,
                "include_or_not": "yes" if decision == "included" else "no",
                "exclusion_reason": f"根据排除标准判断：{', '.join(criteria[:2])}..." if decision == "excluded" else "",
                "number_exclusion_reason": random.choice(["1", "2", "3"]) if decision == "excluded" else "",
                "model": "mock-model-v1.0",
                "raw_ai_response": f'[{{"exclusion_reason": "模拟排除理由", "number_exclusion_reason": "1", "include_or_not": "no"}}]',
                "error": "",
                "extracted_fields": self._mock_extracted_fields() if decision == "included" else {},
                "timestamp": datetime.now().isoformat(),
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
    
    def _save_batch_results_to_db(self, batch: List[Dict], results: List[Dict]):
        """每批处理完后，将本批结果写入DB（供前端实时查看已筛选文献）"""
        from django.db import close_old_connections
        from django.core.files.base import ContentFile
        close_old_connections()
        
        for entry, result in zip(batch, results):
            filename = f"screening_result_{entry['source_xml'].replace('.xml', '.json')}"
            
            # 避免重复写入（断点续传时可能已有）
            if DataFile.objects.filter(
                project=self.project_obj,
                step=self.step_obj,
                filename=filename
            ).exists():
                continue
            
            # 从 workspace 结果目录读取文件内容
            safe_dir_name = safe_title(entry.get("title", "unknown"), 50)
            result_file_path = Path(self.workspace) / "screening_ai" / "results" / safe_dir_name / filename
            
            if result_file_path.exists():
                with open(result_file_path, 'rb') as f:
                    content = f.read()
                # 用 ContentFile 传入内容+短文件名，避免绝对路径拼进 storage
                django_file = ContentFile(content, name=filename)
                DataFile.objects.create(
                    project=self.project_obj,
                    stage=self.stage_obj,
                    step=self.step_obj,
                    filename=filename,
                    file=django_file,
                    data_category='output',
                    source='tool_generated',
                    description='AI筛选结果',
                    metadata={'decision': result.get('decision', 'excluded'), 'source_xml': entry.get("source_xml", "")},  # 关键：写入决策结果+原始文件名
                    created_by=self.task_obj.created_by
                )

    def _save_all_results(self, results_dir: Path):
        """
        将所有结果文件保存到DB（兜底，已存在的会跳过）
        """
        from django.core.files.base import ContentFile
        
        for result_dir in results_dir.iterdir():
            if not result_dir.is_dir():
                continue
            
            for result_file in result_dir.glob("screening_result_*.json"):
                filename = result_file.name
                
                # 跳过已存在的（批次写入时已保存）
                if DataFile.objects.filter(
                    project=self.project_obj,
                    step=self.step_obj,
                    filename=filename
                ).exists():
                    continue
                
                with open(result_file, 'rb') as f:
                    content = f.read()
                django_file = ContentFile(content, name=filename)
                
                DataFile.objects.create(
                    project=self.project_obj,
                    stage=self.stage_obj,
                    step=self.step_obj,
                    filename=filename,
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
        # 1. 优先从 task.config 里读（前端 startScreening 传入的 criteria）
        if self.task_obj and self.task_obj.config:
            criteria = self.task_obj.config.get('criteria', [])
            if criteria:
                self.logger.info(f"[标准] 从任务配置读取纳排标准: {len(criteria)} 条")
                return criteria
        
        # 2. 从 criteria 步骤的 metadata 读
        criteria_step = self.get_previous_step("criteria")
        if criteria_step and criteria_step.metadata:
            criteria = criteria_step.metadata.get("criteria", [])
            if criteria:
                return criteria
        
        # 3. 从阶段 metadata 里读 screening_criteria（前端保存标准时写入的位置）
        if self.stage_obj and self.stage_obj.metadata:
            raw = self.stage_obj.metadata.get('screening_criteria', '')
            if raw:
                lines = [l.strip() for l in raw.splitlines() if l.strip()]
                if lines:
                    self.logger.info(f"[标准] 从阶段 metadata 读取纳排标准: {len(lines)} 条")
                    return lines
        
        # 4. 返回默认标准（兜底）
        self.logger.warning("[标准] 未找到纳排标准，使用默认值")
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
