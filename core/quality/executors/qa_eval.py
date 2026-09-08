"""
文献质量评价 AI 评价引擎

使用方式：
    handler = QAEvalHandler(project_id, ref_ids, eval_mode, model_ids, user_id)
    handler.execute()

设计原则：
- 复用 get_provider() 与 OpenAICompatibleProvider，不重复造轮子
- 独立于 BaseStepHandler/Executor 体系（QA 评价不走原有的 Task/Stage/Step 流程）
- 每篇文献独立评价，失败不影响其他文献
- 无全文但有摘要 → 用摘要评价（标记 abstract_only）
- 无全文无摘要 → 跳过（标记 skipped_no_fulltext）
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from django.utils import timezone
from core.ai import (
    AIQuotaService,
    AIUsageContext,
    AIUsageSettlementService,
    TokenUsageAccumulator,
    is_unlimited_ai_user,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PDF 元数据提取（轻量版，用于上传后自动解析）
# ─────────────────────────────────────────────────────────────────────────────

def extract_pdf_meta(ref_id: int):
    """
    简单解析 PDF 的元数据（标题、作者、年份、摘要首段）。
    仅作尽力提取，失败时静默跳过。
    """
    from core.models import QAReference
    try:
        ref = QAReference.objects.select_related('fulltext_file').get(pk=ref_id)
        if not ref.fulltext_file:
            return
        file_path = ref.fulltext_file.file.path
        if not os.path.exists(file_path):
            return

        # 优先用 PyMuPDF，可处理 AES 加密 PDF
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            meta = doc.metadata or {}
            title = (meta.get('title') or '').strip()
            author = (meta.get('author') or '').strip()
            abstract_hint = doc[0].get_text()[:600].strip() if len(doc) > 0 else ''
            doc.close()
        except Exception:
            # 降级到 PyPDF2
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    info = reader.metadata or {}
                    title = info.get('/Title', '').strip()
                    author = info.get('/Author', '').strip()
                    abstract_hint = (reader.pages[0].extract_text() or '')[:600].strip() if reader.pages else ''
            except Exception as e:
                logger.debug(f'PDF meta parse fallback: {e}')
                title = author = abstract_hint = ''

        updates = {}
        if title and not ref.title.endswith('.pdf'):
            updates['title'] = title
        if author and not ref.first_author:
            updates['first_author'] = author.split(';')[0].split(',')[0][:100]
        if abstract_hint and not ref.abstract:
            updates['abstract'] = abstract_hint
        if updates:
            QAReference.objects.filter(pk=ref_id).update(**updates)
    except Exception as e:
        logger.warning(f'extract_pdf_meta ref_id={ref_id}: {e}')


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 构建
# ─────────────────────────────────────────────────────────────────────────────

def _build_qa_prompt(ref_info: dict, signal_items: list, method_name: str) -> str:
    """
    构建质量评价 prompt。
    输出格式为 JSON 数组，每项对应一条信号问题。
    """
    questions_text = []
    for i, item in enumerate(signal_items):
        options_str = '、'.join(item['options'])
        questions_text.append(
            f"{i+1}. [{item['signal_key']}] {item['signal_question']}\n"
            f"   释义：{item['signal_description']}\n"
            f"   可选答案：{options_str}"
        )

    prompt = f"""你是一名系统综述领域的方法学专家，请对以下文献进行 {method_name} 质量评价。

## 文献信息
- 标题：{ref_info.get('title', '（未知）')}
- 第一作者：{ref_info.get('first_author', '（未知）')}
- 年份：{ref_info.get('year', '（未知）')}
- 来源：{'全文' if ref_info.get('has_fulltext') else '摘要（仅供参考，信息可能不完整）'}

## 文献内容
{ref_info.get('content', '（无内容）')}

## 待评价信号问题
{chr(10).join(questions_text)}

## 输出要求
请严格按以下 JSON 格式输出，不要输出任何其他内容：
```json
[
  {{
    "signal_key": "信号问题key",
    "judgment": "答案（必须是可选答案之一）",
    "reason": "判断依据（1-3句话，引用文献原文关键信息）",
    "evidence": "原文关键证据摘录（30-100字）",
    "evidence_page": "页码或章节位置（如：第2页，方法学部分）"
  }}
]
```

注意：
1. judgment 必须从可选答案中选择，不能自创答案
2. reason 要简洁明确，引用文献关键信息
3. 若文献内容不足以判断，选择"不清楚"并说明原因
4. 仅输出 JSON 数组，不要输出 ```json 标记以外的任何文字"""

    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# 单篇文献 AI 评价
# ─────────────────────────────────────────────────────────────────────────────

def _call_model_for_ref(model_id: str, prompt: str, signal_items: list) -> tuple:
    """
    调用单个模型对一篇文献的信号问题进行评价。
    返回：(results, token_usage)
      results:     [{'signal_key': ..., 'judgment': ..., 'reason': ..., 'evidence': ..., 'evidence_page': ...}, ...]
                   失败时返回空列表
      token_usage: {'prompt': int, 'completion': int, 'total': int} 或 None
    """
    from core.ai.providers import get_provider, provider_is_configured

    if not provider_is_configured(model_id):
        logger.warning(f'[QA] 模型 {model_id} 未配置 API Key，跳过')
        return [], None

    try:
        provider = get_provider(model_id)
        response_text, token_usage = provider.generate_text(prompt)
        if not response_text:
            logger.warning(f'[QA] 模型 {model_id} 返回空内容')
            return [], token_usage
    except Exception as e:
        logger.warning(f'[QA] 模型 {model_id} 调用失败: {e}')
        return [], None

    # 解析 JSON
    try:
        # 提取 JSON 数组（处理推理模型思维链、多余文本等情况）
        text = response_text.strip()

        # 策略1：优先从 ```json ... ``` 代码块中提取
        import re as _re
        code_block = _re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', text)
        if code_block:
            json_str = code_block.group(1)
        else:
            # 策略2：从最后一个 ] 向前找匹配的 [（取最末尾的完整数组，跳过思维链中的片段）
            end = text.rfind(']')
            if end == -1:
                raise ValueError('响应中未找到 JSON 数组')
            # 向前扫描，找括号平衡的起始 [
            depth = 0
            start = -1
            for i in range(end, -1, -1):
                if text[i] == ']':
                    depth += 1
                elif text[i] == '[':
                    depth -= 1
                    if depth == 0:
                        start = i
                        break
            if start == -1:
                raise ValueError('响应中未找到 JSON 数组')
            json_str = text[start:end+1]

        parsed = json.loads(json_str)
        if not isinstance(parsed, list):
            raise ValueError('JSON 不是数组')
        # 过滤有效条目
        valid = []
        valid_keys = {item['signal_key'] for item in signal_items}
        for item in parsed:
            if isinstance(item, dict) and item.get('signal_key') in valid_keys:
                valid.append({
                    'signal_key':    item.get('signal_key', ''),
                    'judgment':      item.get('judgment', '不清楚'),
                    'reason':        item.get('reason', ''),
                    'evidence':      item.get('evidence', ''),
                    'evidence_page': item.get('evidence_page', ''),
                })
        return valid, token_usage
    except Exception as e:
        logger.warning(f'[QA] 模型 {model_id} 响应解析失败: {e}，原始: {response_text[:300]}')
        return [], token_usage


def _determine_consistency(model_results: list) -> tuple:
    """
    根据 N 个模型的结果计算一致性状态和系统推荐值。
    返回 (consistency, system_recommendation)

    规则：
    - 0 个有效结果  → 'failed', ''
    - 1 个有效结果  → 'single', 该结果
    - N≥2 全部一致  → 'consistent', 共同值
    - N≥3 多数一致  → 'majority', 多数值
    - 完全分歧      → 'divergent', 保守值
    - 部分失败      → 'partial', 成功的那个
    """
    valid = [r for r in model_results if r.get('judgment')]
    if not valid:
        return 'failed', ''
    if len(valid) == 1:
        status = 'single' if len(model_results) == 1 else 'partial'
        return status, valid[0]['judgment']

    judgments = [r['judgment'] for r in valid]
    # 统计各判断出现次数
    from collections import Counter
    counts = Counter(judgments)
    most_common_val, most_common_cnt = counts.most_common(1)[0]

    if most_common_cnt == len(valid):
        # 全部一致
        return 'consistent', most_common_val
    if most_common_cnt > len(valid) / 2:
        # 多数一致（严格过半）
        return 'majority', most_common_val

    # 分歧：取保守值（倾向否/高风险/不清楚）
    conservative_priority = ['否', '高', '不清楚', '是', '低']
    for safe in conservative_priority:
        if safe in judgments:
            return 'divergent', safe
    return 'divergent', judgments[0]


# ─────────────────────────────────────────────────────────────────────────────
# QAEvalHandler
# ─────────────────────────────────────────────────────────────────────────────

class QAEvalHandler:
    """
    QA AI 评价主引擎

    与 BaseStepHandler 独立，直接操作 QAReference / QASignalItem / QADomainResult。
    """

    def __init__(
        self,
        project_id: int,
        ref_ids: List[int],
        eval_mode: str,            # 兼容旧参数，实际由 model_ids 长度决定
        model_ids: List[str],      # 选择的模型 ID 列表（1 个=单模型，2+ 个=多模型校验）
        user_id: Optional[int] = None,
    ):
        self.project_id = project_id
        self.ref_ids    = ref_ids
        self.model_ids  = model_ids if model_ids else ['deepseek-v4-pro']
        self.user_id    = user_id
        # eval_mode 由模型数量决定，不依赖前端传入
        self.eval_mode  = 'single' if len(self.model_ids) <= 1 else 'multi'

    def execute(self):
        from core.models import QAReference
        from core.quality.domain.methods import get_method_config, AI_SUPPORTED_METHODS

        refs = list(QAReference.objects.filter(
            pk__in=self.ref_ids,
            quality_method__in=AI_SUPPORTED_METHODS,
        ).select_related('fulltext_file'))

        logger.info(f'[QA] 开始评价 project_id={self.project_id}，共 {len(refs)} 篇，模式={self.eval_mode}，模型={self.model_ids}')

        # ── 余额预检（旁路，不足时拒绝启动）─────────────────────────────────
        if self.user_id:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.filter(pk=self.user_id).first()
                if user:
                    estimated = AIQuotaService.preflight(user, len(refs), self.model_ids)
                    if is_unlimited_ai_user(user):
                        logger.info('[QA][计费] 管理员账户，跳过余额预检')
                    else:
                        logger.info(f'[QA][计费] 余额预检通过，预估消耗 {estimated} credits')
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f'[QA][计费] 余额预检异常（非致命）: {e}')

        # ── token 累计器 ──────────────────────────────────────────────────────
        token_stats = TokenUsageAccumulator()

        # 串行评价（每篇文献独立，失败不影响其他）
        for ref in refs:
            try:
                ref_token = self._eval_one_ref(ref)
                token_stats.add(ref_token)
            except Exception as e:
                logger.exception(f'[QA] 文献 {ref.id} 评价失败: {e}')
                QAReference.objects.filter(pk=ref.id).update(ai_eval_status='failed')

        logger.info(f'[QA] 评价完成 project_id={self.project_id}')

        # ── 结算：按实际 token 扣费 ───────────────────────────────────────────
        self._settle_credits(token_stats)

    def _settle_credits(self, token_stats):
        """Delegate QA usage accounting to the shared AI settlement service."""
        if not self.user_id:
            return {}
        try:
            from django.contrib.auth import get_user_model
            from core.models import Project

            user = get_user_model().objects.filter(pk=self.user_id).first()
            project = Project.objects.filter(pk=self.project_id).first()
            context = AIUsageContext(
                feature='AI质量评价',
                user=user,
                project=project,
                task=getattr(self, 'task_obj', None),
                model_ids=self.model_ids,
            )
            stats = AIUsageSettlementService.settle(context, token_stats)
            if stats.get('total_tokens'):
                logger.info(
                    f"[QA][计费] 已统一结算 {stats['total_tokens']} tokens，"
                    f"{stats['credits_consumed']} credits"
                )
            return stats
        except ValueError as exc:
            logger.warning(f'[QA][计费] 扣费失败: {exc}')
        except Exception as exc:
            logger.warning(f'[QA][计费] 结算失败（非致命）: {exc}')
        return {}

    def _eval_one_ref(self, ref) -> Optional[dict]:
        """
        评价单篇文献，返回本篇累计的 token_usage dict，或 None（跳过/失败）。
        """
        from core.models import QAReference, QASignalItem
        from core.quality.domain.methods import get_method_config

        method_key = ref.quality_method
        try:
            method_cfg = get_method_config(method_key)
        except Exception:
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='skipped_no_method')
            return None

        signal_items_cfg = method_cfg.get('signal_items', [])
        if not signal_items_cfg:
            # 方法未配置信号问题（如 ROB2）
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='skipped_no_method')
            return None

        # 获取内容
        content, has_fulltext = self._get_ref_content(ref)
        if not content:
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='skipped_no_fulltext')
            logger.info(f'[QA] 文献 {ref.id} 无全文和摘要，跳过')
            return None

        ai_status = 'completed' if has_fulltext else 'abstract_only'
        ref_info = {
            'title':       ref.title,
            'first_author': ref.first_author,
            'year':        ref.year,
            'has_fulltext': has_fulltext,
            'content':     content,
        }

        # 构建 prompt
        prompt = _build_qa_prompt(ref_info, signal_items_cfg, method_cfg['name'])

        # ── N 模型评价（统一逻辑：1 个=单模型，2+=多模型校验）────────────────
        logger.info(f'[QA] 文献 {ref.id} 使用 {len(self.model_ids)} 个模型: {self.model_ids}')

        # 本篇 token 累计
        ref_token_stats = {'prompt': 0, 'completion': 0, 'total': 0}

        def _add_token(usage):
            if usage:
                ref_token_stats['prompt']     += usage.get('prompt', 0)
                ref_token_stats['completion'] += usage.get('completion', 0)
                ref_token_stats['total']      += usage.get('total', 0)

        # 并发调用所有模型（最多同时 4 个，避免占用过多连接）
        all_model_raw = {}   # model_id -> List[dict]
        if len(self.model_ids) == 1:
            results, usage = _call_model_for_ref(
                self.model_ids[0], prompt, signal_items_cfg)
            all_model_raw[self.model_ids[0]] = results
            _add_token(usage)
        else:
            max_workers = min(len(self.model_ids), 4)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_call_model_for_ref, mid, prompt, signal_items_cfg): mid
                    for mid in self.model_ids
                }
                for fut in as_completed(futures):
                    mid = futures[fut]
                    try:
                        results, usage = fut.result()
                        all_model_raw[mid] = results
                        _add_token(usage)
                    except Exception as e:
                        logger.warning(f'[QA] 模型 {mid} 并发调用异常: {e}')
                        all_model_raw[mid] = []

        # 先删除已有条目（重新生成场景）
        QASignalItem.objects.filter(qa_ref=ref).delete()

        # 检查是否所有模型都返回空结果（超时/API 失败等）
        all_empty = all(len(v) == 0 for v in all_model_raw.values())
        if all_empty:
            logger.warning(f'[QA] 文献 {ref.id} 所有模型均无有效返回，标记为 failed')
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='failed')
            return None

        # 获取模型名称映射
        from core.services.ai_models_config import get_model_config
        model_name_map = {}
        for mid in self.model_ids:
            cfg = get_model_config(mid)
            model_name_map[mid] = cfg['name'] if cfg else mid

        for cfg_item in signal_items_cfg:
            sk = cfg_item['signal_key']

            # 构建 model_results 列表
            model_results = []
            for mid in self.model_ids:
                raw_list = all_model_raw.get(mid, [])
                raw_map  = {r['signal_key']: r for r in raw_list}
                r = raw_map.get(sk, {})
                model_results.append({
                    'model_id':     mid,
                    'model_name':   model_name_map.get(mid, mid),
                    'judgment':     r.get('judgment', ''),
                    'reason':       r.get('reason', ''),
                    'evidence':     r.get('evidence', ''),
                    'evidence_page':r.get('evidence_page', ''),
                })

            # 计算一致性和推荐值
            consistency, recommendation = _determine_consistency(model_results)

            # 汇总字段：取推荐值；理由/证据取第一个有效模型的
            first_valid = next((m for m in model_results if m.get('judgment')), {})
            ai_judgment  = recommendation
            ai_reason    = first_valid.get('reason', '')
            ai_evidence  = first_valid.get('evidence', '')
            ai_evidence_page = first_valid.get('evidence_page', '')

            # 向后兼容双模型字段（取前两个模型）
            m1 = model_results[0] if len(model_results) > 0 else {}
            m2 = model_results[1] if len(model_results) > 1 else {}

            QASignalItem.objects.create(
                qa_ref=ref,
                quality_method=method_key,
                domain=cfg_item['domain'],
                result_type=cfg_item['result_type'],
                signal_key=sk,
                signal_question=cfg_item['signal_question'],
                signal_description=cfg_item['signal_description'],
                options=cfg_item['options'],
                # 汇总字段
                ai_judgment=ai_judgment,
                ai_reason=ai_reason,
                ai_evidence=ai_evidence,
                ai_evidence_page=ai_evidence_page,
                # N 模型原始结果
                model_results=model_results,
                # 向后兼容双模型字段
                model1_id=m1.get('model_id', ''),
                model1_judgment=m1.get('judgment', ''),
                model1_reason=m1.get('reason', ''),
                model2_id=m2.get('model_id', ''),
                model2_judgment=m2.get('judgment', ''),
                model2_reason=m2.get('reason', ''),
                consistency=consistency,
                system_recommendation=recommendation,
                pre_selected=recommendation,
            )

        # 更新文献状态
        QAReference.objects.filter(pk=ref.id).update(ai_eval_status=ai_status)

        # 初始化领域结果（全部 pending，等待人工确认后重算）
        from core.quality.services.domain_results import recalculate_domain_results
        ref.refresh_from_db()
        recalculate_domain_results(ref)

        logger.info(
            f'[QA] 文献 {ref.id} 评价完成，状态={ai_status}，'
            f'创建 {len(signal_items_cfg)} 条信号问题，'
            f'tokens={ref_token_stats["total"]}'
        )
        return ref_token_stats if ref_token_stats['total'] > 0 else None

    def _get_ref_content(self, ref) -> tuple:
        """
        获取文献内容用于 AI 评价。
        返回 (content_text, has_fulltext)
        - has_fulltext=True:  成功读取全文 PDF
        - has_fulltext=False: 仅使用摘要
        - content=None:       无内容，需跳过
        """
        # 优先读取全文 PDF
        if ref.fulltext_file:
            try:
                file_path = ref.fulltext_file.file.path
                if os.path.exists(file_path):
                    text = self._extract_pdf_text(file_path)
                    if text and len(text.strip()) > 100:
                        # 截取前 8000 字符（避免超出 context 限制）
                        return text[:8000], True
            except Exception as e:
                logger.warning(f'[QA] 文献 {ref.id} 全文读取失败: {e}')

        # 降级：使用摘要
        if ref.abstract and len(ref.abstract.strip()) > 50:
            logger.info(f'[QA] 文献 {ref.id} 使用摘要评价（无全文）')
            return ref.abstract, False

        return None, False

    @staticmethod
    def _extract_pdf_text(file_path: str) -> str:
        """提取 PDF 文本（优先 PyMuPDF，备用 PyPDF2，再备用 pdfminer）。
        PyMuPDF 可正确处理 AES 加密 PDF 及复杂字体嵌入，推荐首选。
        """
        # ── 优先：PyMuPDF（fitz）────────────────────────────────────────────
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            pages_text = []
            for page in doc[:20]:  # 最多读前 20 页
                t = page.get_text()
                if t and t.strip():
                    pages_text.append(t)
            doc.close()
            result = '\n'.join(pages_text)
            if result.strip():
                return result
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f'PyMuPDF 失败: {e}')

        # ── 备用：PyPDF2 ────────────────────────────────────────────────────
        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                pages_text = []
                for page in reader.pages[:20]:
                    t = page.extract_text()
                    if t:
                        pages_text.append(t)
                return '\n'.join(pages_text)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f'PyPDF2 失败: {e}')

        # ── 最终备用：pdfminer ───────────────────────────────────────────────
        try:
            from pdfminer.high_level import extract_text
            return extract_text(file_path)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f'pdfminer 失败: {e}')

        return ''


# ─────────────────────────────────────────────────────────────────────────────
# QAEvalStepHandler — 接入 BaseStepHandler / TaskScheduler 体系
# ─────────────────────────────────────────────────────────────────────────────

from core.executors.registry import register
from core.executors.step_handler import BaseStepHandler


@register("qa_eval")
class QAEvalStepHandler(BaseStepHandler):
    """
    AI 质量评价步骤 Handler（异步执行，接入统一 Task/ActivityLog 体系）

    executor.config 中预期字段：
        ref_ids    : list[int]  待评价文献 ID（空 = 全部）
        model_ids  : list[str]  选择的模型 ID 列表（1 个=单模型，2+=多模型校验）
        eval_mode  : str        已废弃（由 model_ids 长度自动推断），保留向后兼容
    """

    execution_mode = "async"

    def execute(self) -> bool:
        from core.models import QAReference
        from core.quality.domain.methods import AI_SUPPORTED_METHODS

        cfg        = self.executor.config or {}
        ref_ids    = cfg.get('ref_ids', [])
        model_ids  = cfg.get('model_ids', [])
        user_id    = self.task_obj.created_by_id if self.task_obj else None

        # eval_mode 由模型数量推断
        eval_mode = 'single' if len(model_ids) <= 1 else 'multi'

        # 确定待评价文献
        qs = QAReference.objects.filter(
            project_id=self.project_id,
            quality_method__in=AI_SUPPORTED_METHODS,
        ).exclude(quality_method='')
        if ref_ids:
            qs = qs.filter(pk__in=ref_ids)

        ref_ids_to_eval = list(qs.values_list('pk', flat=True))
        total = len(ref_ids_to_eval)

        if total == 0:
            self.logger.warning('[QA] 没有可评价的文献，跳过')
            return True

        user = self.task_obj.created_by if self.task_obj else None
        if user:
            estimated = AIQuotaService.preflight(user, total, model_ids)
            if is_unlimited_ai_user(user):
                self.logger.info('[QA][计费] 管理员账户，跳过余额预检')
            else:
                self.logger.info(f'[QA][计费] Worker 余额预检通过，预估 {estimated} credits')

        self.logger.info(f'[QA] 开始评价 {total} 篇，模式={eval_mode}，模型={model_ids}')
        self.logger.update_progress(0, total, '篇')

        # 将文献状态置为 running
        QAReference.objects.filter(pk__in=ref_ids_to_eval).update(
            ai_eval_status='running',
            eval_mode=eval_mode,
            selected_models=model_ids,
        )

        # 调用评价引擎（逐篇评价，内部已处理异常）
        engine = QAEvalHandler(
            project_id=self.project_id,
            ref_ids=ref_ids_to_eval,
            eval_mode=eval_mode,
            model_ids=model_ids,
            user_id=user_id,
        )
        # 透传 task_obj，供结算时写入 TokenUsageLog
        engine.task_obj = self.task_obj

        # ── token 累计器 ──────────────────────────────────────────────────────
        token_stats = TokenUsageAccumulator()

        # 逐篇评价，同时更新进度到 Task
        completed = 0
        refs = list(QAReference.objects.filter(
            pk__in=ref_ids_to_eval,
            quality_method__in=AI_SUPPORTED_METHODS,
        ).select_related('fulltext_file'))

        for ref in refs:
            if self.executor.check_stop_signal():
                self.logger.warning('[QA] 检测到停止信号，中断评价')
                break
            try:
                ref_token = engine._eval_one_ref(ref)
                token_stats.add(ref_token)
            except Exception as e:
                logger.exception(f'[QA] 文献 {ref.id} 评价失败: {e}')
                QAReference.objects.filter(pk=ref.id).update(ai_eval_status='failed')
            completed += 1
            self.logger.update_progress(completed, total, '篇')

        self.logger.info(
            f'[QA] 评价完成，共处理 {completed}/{total} 篇，'
            f'总 tokens={token_stats.total_tokens}'
        )

        # 按实际 token 结算
        engine._settle_credits(token_stats)
        return True
