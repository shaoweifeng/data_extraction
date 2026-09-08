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
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set

from core.models import DataFile
from core.artifacts.types import ArtifactType
from core.ai import AIQuotaService, TokenUsageAccumulator, is_unlimited_ai_user
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler


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
        # 多模型支持：读 ai_models 列表，单模型时降级为 ai_model
        model_ids = self.config.get('ai_models') or []
        if not model_ids:
            single = self.config.get('ai_model') or ''
            if single:
                model_ids = [single]
        if user:
            if is_unlimited_ai_user(user):
                self.logger.info("[计费] 管理员账户，跳过余额预检")
            else:
                try:
                    estimated = AIQuotaService.preflight(user, total_refs, model_ids)
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
                metadata__artifact_type=ArtifactType.SCREENING_RESULT_JSON,
            )
            old_count = old_qs.count()
            if old_count > 0:
                old_qs.delete()
                self.logger.info(f"[清理] 已清除 {old_count} 条历史筛选结果")
            # 同步清理该项目的人工审阅记录，避免重跑后残留旧数据
            from core.models import ManualReview
            mr_count, _ = ManualReview.objects.filter(project=self.project_obj).delete()
            if mr_count > 0:
                self.logger.info(f"[清理] 已清除 {mr_count} 条历史人工审阅记录")
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
        token_stats = TokenUsageAccumulator()
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
                token_stats.add(usage)

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
        from core.screening.services.input_selector import ScreeningInputSelector
        return ScreeningInputSelector(self)._get_input_files()

    def _get_criteria(self) -> List[str]:
        from core.screening.services.input_selector import ScreeningInputSelector
        return ScreeningInputSelector(self)._get_criteria()

    # ── 批处理 ───────────────────────────────────────────────────────────

    def _process_batch(self, batch: List[Dict], criteria: List[str],
                       results_dir: Path, concurrency: int = 16) -> List[Dict]:
        try:
            results = self._call_multi_model_api(batch, criteria, concurrency=concurrency)
        except Exception as e:
            self.logger.warning(f"[API] 调用失败: {e}，使用模拟结果")
            results = self._mock_api_call(batch, criteria)

        for i, result in enumerate(results):
            result["timestamp"] = datetime.now().isoformat()
            result["source_xml"] = batch[i].get("source_xml", "unknown")
        return results

    def _call_multi_model_api(self, batch: List[Dict], criteria: List[str], concurrency: int = 16) -> List[Dict]:
        from core.screening.services.model_runner import ScreeningModelRunner
        return ScreeningModelRunner(self)._call_multi_model_api(batch, criteria, concurrency)

    def _mock_api_call(self, batch: List[Dict], criteria: List[str]) -> List[Dict]:
        from core.screening.services.model_runner import ScreeningModelRunner
        return ScreeningModelRunner(self)._mock_api_call(batch, criteria)

    # ── 结果保存 ─────────────────────────────────────────────────────────

    def _save_result(self, entry: Dict, result: Dict, results_dir: Path):
        from core.screening.services.result_repository import ScreeningResultRepository
        return ScreeningResultRepository(self)._save_result(entry, result, results_dir)

    def _save_batch_results_to_db(self, batch: List[Dict], results: List[Dict]):
        from core.screening.services.result_repository import ScreeningResultRepository
        return ScreeningResultRepository(self)._save_batch_results_to_db(batch, results)

    def _save_all_results(self, results_dir: Path):
        from core.screening.services.result_repository import ScreeningResultRepository
        return ScreeningResultRepository(self)._save_all_results(results_dir)

    # ── Prompt / 字段提取 ────────────────────────────────────────────────

    def _get_prompt_template(self) -> str:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder
        return ScreeningPromptBuilder(self)._get_prompt_template()

    def _append_extraction_block(self, base_prompt: str) -> str:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder
        return ScreeningPromptBuilder(self)._append_extraction_block(base_prompt)

    def _get_extraction_fields(self) -> List[Dict]:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder
        return ScreeningPromptBuilder(self)._get_extraction_fields()

    def _mock_extracted_fields(self) -> Dict:
        from core.screening.services.prompt_builder import ScreeningPromptBuilder
        return ScreeningPromptBuilder(self)._mock_extracted_fields()

    # ── Token 统计（阶段二）───────────────────────────────────────────────

    def _save_token_stats(self, token_stats: Dict):
        from core.screening.services.usage_settlement import UsageSettlementService
        return UsageSettlementService(self)._save_token_stats(token_stats)

    # ── 工具方法 ─────────────────────────────────────────────────────────

    def _parse_xml_entry(self, xml_path: str) -> Dict:
        from core.screening.services.input_selector import ScreeningInputSelector
        return ScreeningInputSelector(self)._parse_xml_entry(xml_path)
