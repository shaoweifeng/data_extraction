"""
AI 初筛步骤 Handler

负责：
- 获取去重/解析后的 XML 文件
- 加载断点（跨任务续传支持）
- 批量并发调用 AI API 筛选文献
- 每批写入 DB 供前端实时查看
- 保存断点、清除断点、更新步骤元数据
"""

import json
import shutil
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set

from django.conf import settings

from core.models import DataFile
from core.executors.registry import register
from core.executors.handlers.base_handler import BaseStepHandler
from core.executors.base import safe_title


@register("ai_screen")
class AIScreenHandler(BaseStepHandler):
    """AI 初筛步骤 Handler（异步执行，Celery 线程池）"""

    execution_mode = "async"

    def execute(self) -> bool:
        """
        AI 初筛主流程：
        1. 获取输入文件 + 纳排标准
        2. 加载断点
        3. 批量并发调用 AI API
        4. 保存断点、保存结果到 DB
        """
        self.logger.info("[步骤] 开始AI初筛...")

        input_files = self._get_input_files()
        criteria = self._get_criteria()
        total_refs = len(input_files)

        self.logger.info(f"[数据] 待筛选文献: {total_refs} 篇")
        self.logger.info(f"[标准] 纳排标准: {len(criteria)} 条")

        if total_refs == 0:
            self.logger.error("[错误] 没有找到待筛选文献")
            return False

        # ── 阶段三：余额预检 ──────────────────────────────────────────────
        # superuser / admin 角色享受无限额度，跳过余额检查
        user = self.task_obj.created_by if self.task_obj else None
        if user:
            profile = getattr(user, 'profile', None)
            is_unlimited = user.is_superuser or (profile and profile.role == 'admin')
            if is_unlimited:
                self.logger.info("[计费] 管理员账户，跳过余额预检")
            else:
                try:
                    from core.services.billing_service import estimate_credits, check_balance_sufficient, get_balance
                    estimated = estimate_credits(total_refs)
                    if not check_balance_sufficient(user, estimated):
                        balance = get_balance(user)
                        self.logger.error(
                            f"[计费] 余额不足：预估需要 {estimated} credits，"
                            f"当前余额 {balance} credits，拒绝启动"
                        )
                        raise ValueError(f"余额不足（预估需 {estimated} credits，当前余额 {balance} credits）")
                    self.logger.info(f"[计费] 余额预检通过，预估消耗 {estimated} credits")
                except ValueError:
                    raise
                except Exception as e:
                    self.logger.warning(f"[计費] 余额预检异常（跳过）: {e}")

        # 加载断点
        checkpoint, is_resume = self._load_checkpoint_with_resume()
        processed_sources: Set[str] = set()
        if checkpoint:
            raw = checkpoint.get("processed_sources", [])
            if not raw and "data" in checkpoint:
                raw = checkpoint["data"].get("processed_sources", [])
            processed_sources = set(raw)
            prog = checkpoint.get("progress") or checkpoint.get("data", {}).get("progress", {}) or {}
            self.logger.info(f"[断点] 已处理 {len(processed_sources)} 篇，上次进度 {prog.get('current', 0)}/{prog.get('total', 0)}")
            resume_progress = self.config.get("resume_progress", 0)
            if resume_progress:
                from django.db import close_old_connections
                from core.models import Task
                close_old_connections()
                Task.objects.filter(id=self.executor.task_id).update(progress=resume_progress)
                self.logger.info(f"[断点] 恢复进度: {round(resume_progress * 100, 1)}%")

        # 准备工作区
        workspace_ai = self.workspace / "screening_ai"
        datasets_dir = workspace_ai / "datasets"
        results_dir = workspace_ai / "results"
        datasets_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        # 全新任务清旧结果；续传保留
        if not is_resume:
            old_qs = DataFile.objects.filter(
                project=self.project_obj,
                step=self.step_obj,
                data_category='output',
                description='AI筛选结果',
            )
            old_count = old_qs.count()
            if old_count > 0:
                old_qs.delete()
                self.logger.info(f"[清理] 已清除 {old_count} 条历史筛选结果")
        else:
            self.logger.info("[断点] 续传模式：保留已有结果，追加新结果")

        # 收集待处理条目（跳过已处理）
        entries_to_process = []
        for df in input_files:
            if df.filename in processed_sources:
                continue
            entry = self._parse_xml_entry(df.file.path)
            entry["source_xml"] = df.filename
            entry["datafile_id"] = df.id
            entries_to_process.append(entry)
        self.logger.info(f"[筛选] 待处理: {len(entries_to_process)} 篇")

        if not entries_to_process:
            self.logger.info("[完成] 所有文献已处理完成")
            return True

        batch_size = self.config.get("batch_size", 16)
        # 阶段四：从用户档位读并发线程数（config 中可显式覆盖）
        if 'concurrency' in self.config:
            concurrency = int(self.config['concurrency'])
        else:
            from core.services.concurrency_service import get_user_concurrency
            user = self.task_obj.created_by if self.task_obj else None
            concurrency = get_user_concurrency(user)
        # batch_size 对齐并发数：每批正好铺满所有线程，进度更新粒度 = 并发数
        # 例：2并发 → 每2篇上报一次；16并发 → 每16篇上报一次（原行为）
        batch_size = concurrency
        # 同步 logger 的进度写库间隔，确保 Task.progress 以并发数为粒度更新
        self.logger._progress_sync_interval = concurrency
        self.logger.info(f"[并发] 本次使用 {concurrency} 线程并发，batch_size={batch_size}")
        processed_count = len(processed_sources)
        # 阶段二：全程累加 token 统计（key: prompt/completion/total/ref_count）
        token_stats = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
            'ref_count': 0,      # 实际调用过 AI API 的篇数（mock 不计）
        }
        # 进入循环前先上报一次起点篇数（续传时 processed_count 已是断点值）
        self._send_heartbeat(processed_count, total_refs)
        self.logger.update_progress(processed_count, total_refs, "refs")

        for i in range(0, len(entries_to_process), batch_size):
            if self.check_stop_signal():
                self.logger.warning("[停止] 用户请求停止任务")
                self.save_checkpoint({
                    "processed_sources": list(processed_sources),
                    "last_batch_index": i,
                    "progress": {"current": processed_count, "total": total_refs},
                })
                return False

            batch = entries_to_process[i:i + batch_size]
            self.logger.info(f"[批次] 处理 {i + 1}-{i + len(batch)}/{len(entries_to_process)} 篇（并发{concurrency}线程）")

            results = self._process_batch(batch, criteria, results_dir, concurrency)

            for entry, result in zip(batch, results):
                self._save_result(entry, result, results_dir)
                processed_sources.add(entry["source_xml"])
                processed_count += 1
                # 累加 token 统计
                usage = result.get('token_usage')
                if usage:
                    token_stats['prompt_tokens']     += usage.get('prompt', 0)
                    token_stats['completion_tokens'] += usage.get('completion', 0)
                    token_stats['total_tokens']      += usage.get('total', 0)
                    token_stats['ref_count']         += 1

            # 篇数递增后立即上报心跳（放在批次结尾，确保最后一批也能上报最新篇数）
            self._send_heartbeat(processed_count, total_refs)
            self.logger.update_progress(processed_count, total_refs, "refs")
            self.save_checkpoint({
                "processed_sources": list(processed_sources),
                "last_batch_index": i + batch_size,
                "progress": {"current": processed_count, "total": total_refs},
            })
            self._save_batch_results_to_db(batch, results)

        # 收尾
        self.logger.info("[保存] 将结果保存到数据库...")
        self._save_all_results(results_dir)
        self.executor.clear_checkpoint()

        # 阶段二：将 token 统计写入 Task.result，并写 TokenUsageLog
        self._save_token_stats(token_stats)

        from django.db import close_old_connections
        close_old_connections()
        all_outputs = DataFile.objects.filter(
            project=self.project_obj,
            step=self.step_obj,
            data_category='output',
        )
        included_count = all_outputs.filter(metadata__decision='included').count()
        excluded_count = all_outputs.filter(metadata__decision='excluded').count()
        total_out = all_outputs.count()

        self.step_obj.metadata = {
            "total_refs": total_refs,
            "processed_refs": processed_count,
            "included_refs": included_count,
            "excluded_refs": excluded_count,
            "error_refs": total_out - included_count - excluded_count,
            "start_time": self.task_obj.started_at.isoformat() if self.task_obj.started_at else None,
            "end_time": datetime.now().isoformat(),
            "criteria_count": len(criteria),
        }
        return True

    # ── 断点 ─────────────────────────────────────────────────────────────

    def _load_checkpoint_with_resume(self):
        """加载断点。返回 (checkpoint_dict, is_resume)。"""
        is_resume = bool(self.config.get("resume_checkpoint_path"))
        resume_path = self.config.get("resume_checkpoint_path")
        checkpoint = None

        if resume_path:
            p = Path(resume_path)
            if p.exists():
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        candidate = json.load(f)
                    if self._is_compatible_checkpoint(candidate):
                        checkpoint = candidate
                        self.logger.info(f"[断点] 从上次任务恢复: {resume_path}")
                except Exception as e:
                    self.logger.warning(f"[断点] 加载跨任务 checkpoint 失败: {e}")

        if is_resume and checkpoint is None:
            candidate = self.load_checkpoint()
            if candidate and self._is_compatible_checkpoint(candidate):
                checkpoint = candidate

        return checkpoint, is_resume

    def _is_compatible_checkpoint(self, checkpoint: Dict) -> bool:
        """校验 checkpoint 是否属于当前项目/步骤。"""
        meta = checkpoint.get("_checkpoint_meta") or {}
        if not meta:
            return True
        if meta.get("project_id") != self.project_id:
            self.logger.warning(f"[断点] 忽略其他项目的 checkpoint: project_id={meta.get('project_id')}")
            return False
        if meta.get("step_key") != self.executor.step_key:
            self.logger.warning(f"[断点] 忽略其他步骤的 checkpoint: step_key={meta.get('step_key')}")
            return False
        return True

    # ── 心跳 ─────────────────────────────────────────────────────────────

    def _send_heartbeat(self, current: int, total: int):
        """将筛选进度写入 Task.config.screen_progress（供前端轮询）。

        注意：Task 模型没有 metadata 字段，进度统一存放在 config 里
        （与 parse 步骤的 config.parse_progress 保持一致）。
        """
        try:
            from django.db import close_old_connections
            from core.models import Task
            close_old_connections()
            # 读取现有 config 再合并，避免覆盖 criteria / ai_model 等配置
            row = Task.objects.filter(id=self.executor.task_id).values('config').first()
            cfg = (row['config'] if row and row['config'] else {})
            cfg['screen_progress'] = {
                'heartbeat': datetime.now().isoformat(),
                'processed_refs': current,
                'total_refs': total,
                'status_message': f'正在处理第 {current}/{total} 篇文献',
            }
            Task.objects.filter(id=self.executor.task_id).update(config=cfg)
        except Exception as e:
            self.logger.warning(f"[心跳] 更新失败: {e}")

    # ── 数据获取 ─────────────────────────────────────────────────────────

    def _get_input_files(self) -> List[DataFile]:
        """优先 dedup 输出，其次 parse 输出。"""
        dedup_step = self.executor.get_previous_step("dedup")
        if dedup_step:
            qs = DataFile.objects.filter(
                project=self.project_obj, step=dedup_step,
                data_category='intermediate', description='去重后的文献XML',
            )
            if qs.exists():
                self.logger.info(f"[数据] 使用去重后的文件: {qs.count()} 个")
                return list(qs)

        parse_step = self.executor.get_previous_step("parse")
        if parse_step:
            qs = DataFile.objects.filter(
                project=self.project_obj, step=parse_step,
                data_category='intermediate', description='单篇文献XML',
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

    # ── 批处理 ───────────────────────────────────────────────────────────

    def _process_batch(self, batch: List[Dict], criteria: List[str],
                       results_dir: Path, concurrency: int = 16) -> List[Dict]:
        try:
            results = self._call_ai_api(batch, criteria, concurrency=concurrency)
        except Exception as e:
            self.logger.warning(f"[API] 调用失败: {e}，使用模拟结果")
            results = self._mock_api_call(batch, criteria)

        for i, result in enumerate(results):
            result["timestamp"] = datetime.now().isoformat()
            result["source_xml"] = batch[i].get("source_xml", "unknown")
        return results

    def _call_ai_api(self, batch: List[Dict], criteria: List[str], concurrency: int = 16) -> List[Dict]:
        import os
        from core.executors.ai_providers import get_provider

        model_id = self.config.get("ai_model") or os.environ.get("AI_PROVIDER", "deepseek")
        from core.services.ai_models_config import get_model_config
        model_cfg = get_model_config(model_id)
        has_key = bool(model_cfg and model_cfg.get("api_key")) or bool(os.environ.get("AI_API_KEY"))
        if not has_key:
            self.logger.warning(f"[AI] 模型 {model_id} 未配置 API Key，使用 mock")
            return self._mock_api_call(batch, criteria)

        provider = get_provider(model_id)
        prompt_template = self._get_prompt_template()
        self.logger.info(f"[AI] Provider: {provider.name}，批次: {len(batch)} 篇，并发: {concurrency}")
        screening_results = provider.screen_batch(batch, criteria, prompt_template, concurrency=concurrency)

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
                "token_usage": sr.token_usage,   # 阶段二：透传到 handler 层汇总
            }
            if sr.is_error:
                self.logger.warning(f"[AI] 筛选失败: {entry.get('title', '')[:40]} - {sr.error}")
            results.append(result)
        return results

    def _mock_api_call(self, batch: List[Dict], criteria: List[str]) -> List[Dict]:
        import random
        results = []
        for entry in batch:
            decision = random.choice(['included', 'excluded'])
            results.append({
                "title": entry.get("title", ""),
                "authors": entry.get("authors", ""),
                "year": entry.get("year", ""),
                "journal": entry.get("journal", ""),
                "doi": entry.get("doi", ""),
                "url": entry.get("url", ""),
                "source_xml": entry.get("source_xml", ""),
                "decision": decision,
                "include_or_not": "yes" if decision == "included" else "no",
                "exclusion_reason": f"根据排除标准: {', '.join(criteria[:2])}..." if decision == "excluded" else "",
                "number_exclusion_reason": random.choice(["1", "2", "3"]) if decision == "excluded" else "",
                "model": "mock-model-v1.0",
                "raw_ai_response": '[{"exclusion_reason": "模拟排除理由", "number_exclusion_reason": "1", "include_or_not": "no"}]',
                "error": "",
                "extracted_fields": self._mock_extracted_fields() if decision == "included" else {},
                "timestamp": datetime.now().isoformat(),
            })
            time.sleep(0.3)
        return results

    # ── 结果保存 ─────────────────────────────────────────────────────────

    def _save_result(self, entry: Dict, result: Dict, results_dir: Path):
        safe_dir = safe_title(entry.get("title", "unknown"), 50)
        result_dir = results_dir / safe_dir
        result_dir.mkdir(exist_ok=True)
        result_file = result_dir / f"screening_result_{entry['source_xml'].replace('.xml', '.json')}"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    def _save_batch_results_to_db(self, batch: List[Dict], results: List[Dict]):
        from django.db import close_old_connections
        from django.core.files.base import ContentFile
        close_old_connections()

        for entry, result in zip(batch, results):
            filename = f"screening_result_{entry['source_xml'].replace('.xml', '.json')}"
            if DataFile.objects.filter(project=self.project_obj, step=self.step_obj, filename=filename).exists():
                continue
            safe_dir = safe_title(entry.get("title", "unknown"), 50)
            result_file_path = self.workspace / "screening_ai" / "results" / safe_dir / filename
            if result_file_path.exists():
                with open(result_file_path, 'rb') as f:
                    content = f.read()
                DataFile.objects.create(
                    project=self.project_obj, stage=self.stage_obj, step=self.step_obj,
                    filename=filename, file=ContentFile(content, name=filename),
                    data_category='output', source='tool_generated',
                    description='AI筛选结果',
                    metadata={'decision': result.get('decision', 'excluded'), 'source_xml': entry.get("source_xml", "")},
                    created_by=self.task_obj.created_by,
                )

    def _save_all_results(self, results_dir: Path):
        from django.core.files.base import ContentFile
        for result_dir in results_dir.iterdir():
            if not result_dir.is_dir():
                continue
            for result_file in result_dir.glob("screening_result_*.json"):
                filename = result_file.name
                if DataFile.objects.filter(project=self.project_obj, step=self.step_obj, filename=filename).exists():
                    continue
                with open(result_file, 'rb') as f:
                    content = f.read()
                DataFile.objects.create(
                    project=self.project_obj, stage=self.stage_obj, step=self.step_obj,
                    filename=filename, file=ContentFile(content, name=filename),
                    data_category='output', source='tool_generated',
                    description='AI筛选结果',
                    created_by=self.task_obj.created_by,
                )

    # ── Prompt / 字段提取 ────────────────────────────────────────────────

    def _get_prompt_template(self) -> str:
        """读取 prompt 模板（自定义 > prompt1.txt > 内置默认），追加字段提取指令。"""
        try:
            meta = self.project_obj.metadata or {}
            if meta.get('use_custom_prompt') and meta.get('custom_prompt', '').strip():
                custom = meta['custom_prompt'].strip()
                if '{screening_criteria}' in custom:
                    self.logger.info("[Prompt] 使用项目自定义 Prompt")
                    return self._append_extraction_block(custom)
                self.logger.warning("[Prompt] 自定义 Prompt 缺少 {screening_criteria}，回退默认")
        except Exception as e:
            self.logger.warning(f"[Prompt] 读取自定义 Prompt 失败: {e}")

        prompt_path = Path(settings.BASE_DIR) / "core/resources/prompts/prompt1.txt"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            self.logger.warning(f"[警告] prompt1.txt 不存在，使用内置默认")
            base_prompt = (
                '你是文献筛选助手，请根据以下排除标准判断文献是否纳入，返回JSON格式：'
                '[{"exclusion_reason": "", "number_exclusion_reason": "", "include_or_not": "yes"}]\n'
                '<exclusion_criteria>\n{screening_criteria}\n</exclusion_criteria>'
            )
        return self._append_extraction_block(base_prompt)

    def _append_extraction_block(self, base_prompt: str) -> str:
        fields = self._get_extraction_fields()
        if not fields:
            return base_prompt
        field_descriptions = "\n".join(f'  - "{f["name"]}": {f["definition"]}' for f in fields)
        field_names = ", ".join(f'"{f["name"]}"' for f in fields)
        block = (
            "\n\n=======字段提取任务=======\n"
            "对于纳入的文献，请同时从全文内容中提取以下字段信息：\n"
            f"{field_descriptions}\n\n"
            "输出JSON中的 extracted_fields 字段包含提取结果，格式：\n"
            f'{{"extracted_fields": {{{field_names}: "提取值"}}, ...}}\n\n'
        )
        self.logger.info(f"[字段] 追加提取指令，字段数: {len(fields)}")
        return base_prompt + block

    def _get_extraction_fields(self) -> List[Dict]:
        try:
            fe_step = self.executor.get_previous_step("field_extraction")
            if fe_step and fe_step.metadata:
                fields = fe_step.metadata.get("fields", [])
                if fields:
                    self.logger.info(f"[字段] 读取到 {len(fields)} 个提取字段")
                    return fields
        except Exception as e:
            self.logger.warning(f"[字段] 读取提取字段失败: {e}")
        return []

    def _mock_extracted_fields(self) -> Dict:
        return {f["name"]: f"(模拟) {f['definition'][:30]}..." for f in self._get_extraction_fields()}

    # ── Token 统计（阶段二）───────────────────────────────────────────────

    def _save_token_stats(self, token_stats: Dict):
        """
        将 token 用量统计写入 Task.result['token_stats']，
        并在 TokenUsageLog 中写一条任务级汇总记录（旁路，异常不影响筛选结果）。
        """
        if token_stats.get('total_tokens', 0) == 0:
            return

        from django.conf import settings as dj_settings
        ratio = getattr(dj_settings, 'BILLING_CREDIT_TOKEN_RATIO', 1000)
        credits_estimate = max(1, token_stats['total_tokens'] // ratio)
        token_stats['credits_estimate'] = credits_estimate
        token_stats['credit_token_ratio'] = ratio

        # 1. 写入 Task.result
        try:
            from django.db import close_old_connections
            from core.models import Task
            close_old_connections()
            row = Task.objects.filter(id=self.executor.task_id).values('result').first()
            result_data = (row['result'] if row and row['result'] else {}) or {}
            result_data['token_stats'] = token_stats
            Task.objects.filter(id=self.executor.task_id).update(result=result_data)
            self.logger.info(
                f"[Token] 本次任务共消耗 {token_stats['total_tokens']} tokens"
                f"（{token_stats['ref_count']} 篇，≈{credits_estimate} credits）"
            )
        except Exception as e:
            self.logger.warning(f"[Token] 写入 Task.result 失败: {e}")

        # 2. 旁路写 TokenUsageLog（不阻断主流程）
        try:
            from django.db import close_old_connections
            from core.models_billing import TokenUsageLog
            close_old_connections()
            user = self.task_obj.created_by if self.task_obj else None
            model_name = self.config.get("ai_model", "unknown")
            if user:
                TokenUsageLog.objects.create(
                    task_id=self.executor.task_id,
                    user=user,
                    model=model_name,
                    prompt_tokens=token_stats.get('prompt_tokens', 0),
                    completion_tokens=token_stats.get('completion_tokens', 0),
                    total_tokens=token_stats.get('total_tokens', 0),
                    credits_consumed=credits_estimate,
                    ref_count=token_stats.get('ref_count', 0),
                )
        except Exception as e:
            self.logger.warning(f"[Token] 写入 TokenUsageLog 失败: {e}")

        # 3. 阶段三：按实际 token 用量扣费（旁路，异常不影响主流程）
        # superuser / admin 角色无限额度，不扣费
        try:
            from core.models import Task
            from core.services.billing_service import consume_credits
            user = self.task_obj.created_by if self.task_obj else None
            if user and credits_estimate > 0:
                profile = getattr(user, 'profile', None)
                is_unlimited = user.is_superuser or (profile and profile.role == 'admin')
                if is_unlimited:
                    self.logger.info(f"[计费] 管理员账户，跳过扣费（实际用量 {credits_estimate} credits）")
                    # 写一条 amount=0 的审计流水，方便管理员在个人中心查看用量
                    from core.services.billing_service import log_admin_usage
                    task_obj = Task.objects.select_related('project').filter(id=self.executor.task_id).first()
                    project_name = task_obj.project.name if task_obj and task_obj.project else '未知项目'
                    model_name   = self.config.get('ai_model', '未知模型')
                    admin_note = f"AI筛选(免费) · {project_name} · 模型:{model_name}（{token_stats.get('ref_count', 0)}篇/{token_stats.get('total_tokens', 0)} tokens，等值{credits_estimate} credits）"
                    log_admin_usage(user, credits_estimate, task=task_obj, note=admin_note)
                else:
                    task_obj = Task.objects.select_related('project').filter(id=self.executor.task_id).first()
                    project_name = task_obj.project.name if task_obj and task_obj.project else '未知项目'
                    model_name   = self.config.get('ai_model', '未知模型')
                    note = f"AI筛选 · {project_name} · 模型:{model_name}（{token_stats.get('ref_count', 0)}篇/{token_stats.get('total_tokens', 0)} tokens）"
                    consume_credits(user, credits_estimate, task=task_obj, note=note)
                    self.logger.info(f"[计费] 已扣除 {credits_estimate} credits（实际用量）")
        except ValueError as e:
            self.logger.warning(f"[计费] 扣费失败: {e}")
        except Exception as e:
            self.logger.warning(f"[计费] 扣费异常（不影响筛选结果）: {e}")

    # ── 工具方法 ─────────────────────────────────────────────────────────

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
            }
        except Exception as e:
            self.logger.warning(f"[警告] 解析XML失败 {xml_path}: {e}")
            return {"title": "", "authors": "", "year": "", "journal": "", "abstract": ""}
