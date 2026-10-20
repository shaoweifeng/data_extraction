"""AI 全文复筛 Handler。

设计目标：
- 复用统一 StepExecutor / TaskScheduler / AI Provider / 多模型共识能力；
- 输入从初筛的 Title + Abstract 改为复筛的 PDF 全文文本；
- AI 只产出建议结论，人工审阅仍是最终结论。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from core.ai import (
    AIQuotaService,
    AIUsageContext,
    AIUsageSettlementService,
    TokenUsageAccumulator,
    is_unlimited_ai_user,
)
from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler
from core.models import RescreenCriteria, RescreenReference, Task
from core.services.consensus_service import (
    build_summary_reason,
    get_model_display_name,
    resolve_consensus,
)


MAX_FULLTEXT_CHARS = 32000
MAX_PDF_PAGES = 40


@register('rescreen_ai')
class RescreenAIHandler(BaseStepHandler):
    """AI 全文复筛步骤 Handler（异步）。"""

    execution_mode = 'async'

    def execute(self) -> bool:
        refs = self._get_target_refs()
        total = len(refs)
        if total == 0:
            self.logger.warning('[复筛] 没有可进入 AI 全文复筛的已绑定文献')
            self.logger.update_progress(0, 0, '篇')
            return True

        criteria = self._get_criteria()
        if not criteria:
            self.logger.error('[复筛] 未配置纳排标准，无法启动 AI 全文复筛')
            RescreenReference.objects.filter(pk__in=[ref.id for ref in refs]).update(ai_status='failed')
            return False

        model_ids = self._get_model_ids()
        self._preflight_quota(total, model_ids)

        self.logger.info(f'[复筛] 开始 AI 全文复筛：{total} 篇，模型={model_ids}')
        self.logger.update_progress(0, total, '篇')
        RescreenReference.objects.filter(pk__in=[ref.id for ref in refs]).update(ai_status='running')

        token_stats = TokenUsageAccumulator()
        completed = 0
        failed = 0

        for index, ref in enumerate(refs, start=1):
            if self.executor.check_stop_signal():
                remaining_ids = [item.id for item in refs[index - 1:]]
                RescreenReference.objects.filter(pk__in=remaining_ids, ai_status='running').update(ai_status='queued')
                self.logger.warning('[复筛] 检测到停止信号，已中断 AI 全文复筛')
                break

            try:
                ref_usage = self._process_one_ref(ref, criteria, model_ids)
                token_stats.add(ref_usage)
                completed += 1
            except Exception as exc:  # 单篇失败不影响后续文献
                failed += 1
                self.logger.warning(f'[复筛] 文献 {ref.id} AI 复筛失败: {exc}')
                RescreenReference.objects.filter(pk=ref.id).update(
                    ai_status='failed',
                    ai_decision='pending',
                    ai_reason=f'AI 复筛失败：{exc}',
                    consensus_status='pending',
                    updated_at=timezone.now(),
                )

            self.logger.update_progress(index, total, '篇')
            Task.objects.filter(id=self.executor.task_id).update(progress=index / total)

        self._settle_usage(token_stats, model_ids)
        self.task_obj.result = {
            **(self.task_obj.result or {}),
            'total': total,
            'completed': completed,
            'failed': failed,
            'token_stats': token_stats.as_dict(),
        }
        self.task_obj.save(update_fields=['result', 'updated_at'])
        self.logger.info(f'[复筛] AI 全文复筛结束：completed={completed}, failed={failed}')
        return completed > 0 or failed == 0

    def _get_target_refs(self) -> List[RescreenReference]:
        ref_ids = self.config.get('ref_ids') or []
        qs = RescreenReference.objects.filter(
            project_id=self.project_id,
            fulltext_status='bound',
            fulltext_file__isnull=False,
        ).select_related('fulltext_file')
        if ref_ids:
            qs = qs.filter(pk__in=list(dict.fromkeys(ref_ids)))
        return list(qs.order_by('id'))

    def _get_criteria(self) -> List[str]:
        obj = RescreenCriteria.objects.filter(project_id=self.project_id).first()
        return [str(item).strip() for item in (obj.criteria_list if obj else []) if str(item).strip()]

    def _get_model_ids(self) -> List[str]:
        model_ids = self.config.get('ai_models') or self.config.get('model_ids') or []
        if not model_ids:
            single = self.config.get('ai_model') or os.environ.get('AI_PROVIDER', 'deepseek')
            model_ids = [single]
        return [str(model).strip() for model in model_ids if str(model).strip()]

    def _preflight_quota(self, total_refs: int, model_ids: List[str]) -> None:
        user = self.task_obj.created_by if self.task_obj else None
        if not user:
            return
        if is_unlimited_ai_user(user):
            self.logger.info('[复筛][计费] 管理员账户，跳过余额预检')
            return
        try:
            estimated = AIQuotaService.preflight(user, total_refs, model_ids)
            self.logger.info(f'[复筛][计费] 余额预检通过，预估消耗 {estimated} credits')
        except ValueError:
            raise
        except Exception as exc:
            self.logger.warning(f'[复筛][计费] 余额预检异常（跳过）: {exc}')

    def _process_one_ref(self, ref: RescreenReference, criteria: List[str], model_ids: List[str]) -> Optional[Dict]:
        content, page_texts = self._get_fulltext_content(ref)
        if not content:
            RescreenReference.objects.filter(pk=ref.id).update(
                ai_status='failed',
                ai_decision='pending',
                ai_reason='全文解析失败或 PDF 文本过短，请更换可复制文本的 PDF 后重试。',
                consensus_status='pending',
                updated_at=timezone.now(),
            )
            return None

        prompt = self._build_prompt(ref, content, criteria)
        model_results: List[dict] = []
        ref_tokens = TokenUsageAccumulator()

        for model_id in model_ids:
            result, usage = self._call_model(model_id, prompt)
            if usage:
                ref_tokens.add(usage)
            if result:
                model_results.append(result)

        if not model_results:
            self.logger.warning(f'[复筛] 文献 {ref.id} 所有模型不可用，使用 mock 结果')
            model_results.append(self._mock_model_result(ref, page_texts, criteria))

        consensus = resolve_consensus(model_results)
        decision = consensus if consensus in ('included', 'excluded') else 'pending'
        consensus_status = self._map_consensus_status(consensus, model_results)
        reason = build_summary_reason(model_results)
        evidence = self._pick_evidence(model_results)

        RescreenReference.objects.filter(pk=ref.id).update(
            ai_status='completed',
            ai_decision=decision,
            ai_reason=reason,
            ai_evidence=evidence,
            consensus_status=consensus_status,
            multi_model_results=model_results,
            updated_at=timezone.now(),
        )
        return ref_tokens.as_dict() if ref_tokens.total_tokens > 0 else None

    def _call_model(self, model_id: str, prompt: str) -> Tuple[Optional[dict], Optional[Dict]]:
        from core.ai.providers import get_provider, provider_is_configured

        model_display = get_model_display_name(model_id)
        if not provider_is_configured(model_id):
            self.logger.warning(f'[复筛][AI] 模型 {model_display} 未配置 API Key，跳过')
            return None, None

        try:
            provider = get_provider(
                model_id,
                thinking_enabled=self.config.get('enable_thinking') is True,
            )
            response_text, token_usage = provider.generate_text(prompt)
            if not response_text:
                return {
                    'model_id': model_id,
                    'model_name': model_display,
                    'decision': 'pending',
                    'reason': '模型返回为空',
                    'reason_id': '',
                    'evidence': [],
                    'tokens': token_usage or {},
                    'error': 'empty_response',
                }, token_usage
            parsed = self._parse_model_response(response_text)
            return {
                'model_id': model_id,
                'model_name': model_display,
                'decision': parsed['decision'],
                'reason': parsed.get('reason', ''),
                'reason_id': parsed.get('reason_id', ''),
                'evidence': parsed.get('evidence', []),
                'tokens': token_usage or {},
                'error': '',
                'raw_ai_response': response_text,
            }, token_usage
        except Exception as exc:
            self.logger.warning(f'[复筛][AI] 模型 {model_display} 调用失败: {exc}')
            return {
                'model_id': model_id,
                'model_name': model_display,
                'decision': 'pending',
                'reason': f'模型调用失败：{exc}',
                'reason_id': '',
                'evidence': [],
                'tokens': {},
                'error': str(exc),
            }, None

    def _get_fulltext_content(self, ref: RescreenReference) -> Tuple[str, List[dict]]:
        if not ref.fulltext_file or not ref.fulltext_file.file:
            return '', []
        file_path = ref.fulltext_file.file.path
        if not os.path.exists(file_path):
            return '', []

        page_texts = self._extract_pdf_pages(file_path)
        if not page_texts:
            return '', []
        chunks = []
        used_pages = []
        for item in page_texts:
            text = item.get('text', '').strip()
            if not text:
                continue
            chunks.append(f"[第{item['page']}页]\n{text}")
            used_pages.append(item)
            if sum(len(chunk) for chunk in chunks) >= MAX_FULLTEXT_CHARS:
                break
        content = '\n\n'.join(chunks)[:MAX_FULLTEXT_CHARS]
        return content, used_pages

    @staticmethod
    def _extract_pdf_pages(file_path: str) -> List[dict]:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            pages = []
            for page_no, page in enumerate(doc[:MAX_PDF_PAGES], start=1):
                text = page.get_text() or ''
                if text.strip():
                    pages.append({'page': page_no, 'text': text})
            doc.close()
            if pages:
                return pages
        except ImportError:
            pass
        except Exception:
            pass

        try:
            import PyPDF2
            with open(file_path, 'rb') as fh:
                reader = PyPDF2.PdfReader(fh)
                pages = []
                for index, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
                    text = page.extract_text() or ''
                    if text.strip():
                        pages.append({'page': index, 'text': text})
                return pages
        except ImportError:
            pass
        except Exception:
            pass
        return []

    @staticmethod
    def _build_prompt(ref: RescreenReference, content: str, criteria: List[str]) -> str:
        criteria_text = '\n'.join(f'{index + 1}. {item}' for index, item in enumerate(criteria))
        authors = '；'.join(ref.authors or [])
        return f"""你是一名系统综述 / Meta 分析文献复筛专家。请基于 PDF 全文判断该研究是否符合复筛纳排标准。

## 文献信息
- 标题：{ref.title}
- 作者：{authors or '未知'}
- 年份：{ref.year or '未知'}
- 期刊：{ref.journal or '未知'}
- DOI：{ref.doi or '未知'}

## 复筛纳排标准
{criteria_text}

## PDF 全文内容（已按页码拼接，可能只截取前若干页）
{content}

## 输出要求
请只输出 JSON 对象，不要输出 Markdown、解释文字或代码块。格式如下：
{{
  "include_or_not": "yes 或 no；yes=建议纳入，no=建议排除",
  "exclusion_reason": "建议排除时填写违反的具体标准和理由；建议纳入时留空或简述满足理由",
  "number_exclusion_reason": "建议排除时填写对应标准编号；建议纳入时留空",
  "evidence": [
    {{"page": 1, "text": "支持该判断的全文关键证据原文摘录"}}
  ]
}}

判断原则：
1. 必须依据全文证据，不能只凭标题或摘要猜测；
2. 如果证据不足以明确纳入，请输出 no，并在 exclusion_reason 中说明“全文证据不足/无法确认”；
3. evidence 最多返回 3 条，每条 text 控制在 20-120 字。
"""

    @staticmethod
    def _parse_model_response(response_text: str) -> dict:
        cleaned = response_text.strip()
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]
        if cleaned.startswith('```'):
            cleaned = cleaned[3:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start == -1 or end == -1 or end <= start:
                raise
            parsed = json.loads(cleaned[start:end + 1])

        include_or_not = str(parsed.get('include_or_not', 'no')).strip().lower()
        decision = 'included' if include_or_not in ('yes', 'include', 'included', '纳入') else 'excluded'
        evidence = parsed.get('evidence') or []
        if not isinstance(evidence, list):
            evidence = []
        normalized_evidence = []
        for item in evidence[:3]:
            if not isinstance(item, dict):
                continue
            normalized_evidence.append({
                'page': item.get('page') or item.get('evidence_page') or '',
                'text': str(item.get('text') or item.get('evidence') or '').strip()[:300],
            })
        return {
            'decision': decision,
            'reason': str(parsed.get('exclusion_reason') or parsed.get('reason') or '').strip(),
            'reason_id': str(parsed.get('number_exclusion_reason') or parsed.get('reason_id') or '').strip(),
            'evidence': normalized_evidence,
        }

    @staticmethod
    def _map_consensus_status(consensus: str, model_results: List[dict]) -> str:
        valid_count = len([item for item in model_results if item.get('decision') in ('included', 'excluded')])
        if consensus == 'conflict':
            return 'divergent'
        if consensus in ('included', 'excluded'):
            return 'single' if valid_count <= 1 else 'consistent'
        return 'pending'

    @staticmethod
    def _pick_evidence(model_results: List[dict]) -> List[dict]:
        for result in model_results:
            evidence = result.get('evidence') or []
            if evidence:
                return evidence[:3]
        return []

    @staticmethod
    def _mock_model_result(ref: RescreenReference, page_texts: List[dict], criteria: List[str]) -> dict:
        first_page = page_texts[0] if page_texts else {'page': '', 'text': ref.abstract or ref.title}
        snippet = (first_page.get('text') or '')[:100].replace('\n', ' ')
        return {
            'model_id': 'mock-model-v1.0',
            'model_name': 'Mock Model',
            'decision': 'included',
            'reason': '模拟结果：全文可解析，默认建议纳入；真实环境配置模型 API Key 后将返回真实复筛结论。',
            'reason_id': '',
            'evidence': [{'page': first_page.get('page') or 1, 'text': snippet}],
            'tokens': {},
            'error': '',
        }

    def _settle_usage(self, token_stats: TokenUsageAccumulator, model_ids: List[str]) -> dict:
        if token_stats.total_tokens <= 0:
            return {}
        context = AIUsageContext(
            feature='AI全文复筛',
            user=self.task_obj.created_by if self.task_obj else None,
            project=self.project_obj,
            task=self.task_obj,
            model_ids=model_ids,
        )
        try:
            stats = AIUsageSettlementService.settle(context, token_stats)
            self.logger.info(
                f"[复筛][计费] 已结算 {stats.get('total_tokens', 0)} tokens，"
                f"≈{stats.get('credits_consumed', 0)} credits"
            )
            return stats
        except ValueError as exc:
            self.logger.warning(f'[复筛][计费] 扣费失败: {exc}')
        except Exception as exc:
            self.logger.warning(f'[复筛][计费] 结算失败（非致命）: {exc}')
        return {}
