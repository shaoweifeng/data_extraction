"""Provider execution and multi-model consensus for AI screening."""

import time
from datetime import datetime
from typing import Dict, List


class ScreeningModelRunner:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _call_multi_model_api(self, batch: List[Dict], criteria: List[str], concurrency: int = 16) -> List[Dict]:
            """
            支持单/多模型筛选。
            单模型时行为与废弃的 _call_ai_api 完全一致。
            多模型时依次调用各模型，汇总结果并计算 consensus。
            """
            import os
            from core.ai.providers import get_provider, provider_is_configured
            from core.services.consensus_service import resolve_consensus, build_summary_reason, get_model_display_name

            # 读取多模型列表，向后兼容单模型配置
            model_ids = self.config.get('ai_models') or []
            if not model_ids:
                single = self.config.get('ai_model') or os.environ.get('AI_PROVIDER', 'deepseek')
                model_ids = [single]

            prompt_template = self._get_prompt_template()

            # key: 条目索引 -> [{模型结果}, ...]
            per_entry_model_results: List[List[dict]] = [[] for _ in batch]

            for model_id in model_ids:
                if not provider_is_configured(model_id):
                    self.logger.warning(f"[AI] 模型 {model_id} 未配置 API Key，跳过该模型")
                    continue

                provider = get_provider(model_id)
                model_display = get_model_display_name(model_id)
                self.logger.info(f"[AI] 模型 {model_display} 开始筛选，批次: {len(batch)} 篇，并发: {concurrency}")
                try:
                    screening_results = provider.screen_batch(batch, criteria, prompt_template, concurrency=concurrency)
                except Exception as e:
                    self.logger.warning(f"[AI] 模型 {model_display} 调用失败: {e}")
                    continue

                for idx, (entry, sr) in enumerate(zip(batch, screening_results)):
                    per_entry_model_results[idx].append({
                        'model_id':        model_id,
                        'model_name':      model_display,
                        'decision':        sr.decision,
                        'reason':          sr.exclusion_reason or '',
                        'reason_id':       sr.exclusion_criterion_no or '',  # 排除标准编号
                        'tokens':          sr.token_usage or {},
                        'error':           sr.error or '',
                        'extracted_fields': sr.extracted_fields or {},       # 自定义提取字段
                    })
                    # 计费统计：累加到 token_stats（通过返回对象透传）
                    if sr.token_usage:
                        pass  # token_usage 随 result 返回，在 execute() 里汇总

            # 所有模型均无 API Key 时退化为 mock
            if all(len(r) == 0 for r in per_entry_model_results):
                self.logger.warning("[AI] 所有模型均无效，使用 mock")
                return self._mock_api_call(batch, criteria)

            # 构建最终返回结果（与旧接口兼容）
            results = []
            for idx, (entry, model_results) in enumerate(zip(batch, per_entry_model_results)):
                consensus = resolve_consensus(model_results)
                summary_reason = build_summary_reason(model_results)

                # 计费：各模型 token 累加
                total_token_usage = {
                    'prompt': sum(r['tokens'].get('prompt', 0) for r in model_results),
                    'completion': sum(r['tokens'].get('completion', 0) for r in model_results),
                    'total': sum(r['tokens'].get('total', 0) for r in model_results),
                }

                # 主模型（单模型时第一个就是它；多模型取 consensus 一致的第一个，否则第一个）
                primary = model_results[0] if model_results else {}
                # 导出用排除理由：取与共识一致的第一个模型的 reason（简洁文本），
                # 而非 summary_reason（多模型拼接摘要，仅供审阅界面展示用）
                if consensus == 'excluded':
                    # 优先取与 consensus 结论一致的第一个模型的理由
                    consensus_reason = next(
                        (r.get('reason', '') for r in model_results if r.get('decision') == 'excluded'),
                        primary.get('reason', '')
                    )
                else:
                    consensus_reason = primary.get('reason', '')

                # 合并 extracted_fields：优先用 included 模型的结果，其次取第一个非空的
                merged_extracted: Dict = {}
                for mr in model_results:
                    ef = mr.get('extracted_fields') or {}
                    if ef and not merged_extracted:
                        merged_extracted = dict(ef)
                    elif ef:
                        # 用后续模型补充空字段
                        for k, v in ef.items():
                            if not merged_extracted.get(k) and v:
                                merged_extracted[k] = v
                # exclusion_reason_id：共识排除时取主模型；多模型冲突时取所有非空编号的第一个
                primary_reason_id = primary.get('reason_id', '')
                if not primary_reason_id:
                    for mr in model_results:
                        if mr.get('reason_id'):
                            primary_reason_id = mr['reason_id']
                            break

                results.append({
                    'title':    entry.get('title', ''),
                    'authors':  entry.get('authors', ''),
                    'year':     entry.get('year', ''),
                    'journal':  entry.get('journal', ''),
                    'doi':      entry.get('doi', ''),
                    'url':      entry.get('url', ''),
                    'source_xml': entry.get('source_xml', ''),
                    # 展示对外的主字段（单模型时直接用主模型结果，多模型时用 consensus）
                    'decision':  consensus,
                    'include_or_not': 'yes' if consensus == 'included' else 'no',
                    # 导出排除理由：用与共识一致的主模型简洁理由（非多模型拼接摘要）
                    'exclusion_reason': consensus_reason,
                    # 多模型摘要：供审阅界面展示，不写入导出列
                    'ai_summary_reason': summary_reason,
                    'number_exclusion_reason': primary_reason_id,
                    'model':    ', '.join(r['model_id'] for r in model_results),
                    'raw_ai_response': '',
                    'error':    primary.get('error', ''),
                    'extracted_fields': merged_extracted,
                    'timestamp': datetime.now().isoformat(),
                    'token_usage': total_token_usage if total_token_usage['total'] > 0 else None,
                    # 多模型扩展字段
                    'multi_model_results': model_results,
                    'consensus': consensus,
                })
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
