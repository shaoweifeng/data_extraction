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

def _call_model_for_ref(model_id: str, prompt: str, signal_items: list) -> List[dict]:
    """
    调用单个模型对一篇文献的信号问题进行评价。
    返回：[{'signal_key': ..., 'judgment': ..., 'reason': ..., 'evidence': ..., 'evidence_page': ...}, ...]
    若失败返回空列表。
    """
    from core.executors.ai_providers import get_provider
    from core.services.ai_models_config import get_model_config

    model_cfg = get_model_config(model_id)
    has_key = bool(model_cfg and model_cfg.get('api_key')) or bool(os.environ.get('AI_API_KEY'))
    if not has_key:
        logger.warning(f'[QA] 模型 {model_id} 未配置 API Key，跳过')
        return []

    try:
        provider = get_provider(model_id)
        # 使用底层 _call_api(full_prompt) -> (content, token_usage)
        response_text, _ = provider._call_api(prompt)
        if not response_text:
            logger.warning(f'[QA] 模型 {model_id} 返回空内容')
            return []
    except Exception as e:
        logger.warning(f'[QA] 模型 {model_id} 调用失败: {e}')
        return []

    # 解析 JSON
    try:
        # 提取 JSON 数组（处理模型可能输出多余文本）
        text = response_text.strip()
        # 找到 [ 和 ] 的最外层
        start = text.find('[')
        end   = text.rfind(']')
        if start == -1 or end == -1:
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
        return valid
    except Exception as e:
        logger.warning(f'[QA] 模型 {model_id} 响应解析失败: {e}，原始: {response_text[:300]}')
        return []


def _determine_consistency(r1: dict, r2: dict) -> tuple:
    """
    比较双模型结果，返回 (consistency, system_recommendation)
    """
    if not r1 and not r2:
        return 'failed', ''
    if not r1:
        return 'partial', r2.get('judgment', '')
    if not r2:
        return 'partial', r1.get('judgment', '')
    if r1['judgment'] == r2['judgment']:
        return 'consistent', r1['judgment']
    else:
        # 分歧：推荐更"保守"的判断（倾向于 unclear/否/高风险）
        conservative_priority = ['否', '高', '不清楚', '是', '低']
        j1, j2 = r1['judgment'], r2['judgment']
        for safe_answer in conservative_priority:
            if j1 == safe_answer:
                return 'divergent', j1
            if j2 == safe_answer:
                return 'divergent', j2
        return 'divergent', j1  # fallback 取第一个


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
        eval_mode: str,            # 'single' | 'dual'
        model_ids: List[str],      # 选择的模型 ID 列表
        user_id: Optional[int] = None,
    ):
        self.project_id = project_id
        self.ref_ids    = ref_ids
        self.eval_mode  = eval_mode
        self.model_ids  = model_ids
        self.user_id    = user_id

    def execute(self):
        from core.models import QAReference
        from core.services.quality_methods import get_method_config, AI_SUPPORTED_METHODS

        refs = list(QAReference.objects.filter(
            pk__in=self.ref_ids,
            quality_method__in=AI_SUPPORTED_METHODS,
        ).select_related('fulltext_file'))

        logger.info(f'[QA] 开始评价 project_id={self.project_id}，共 {len(refs)} 篇，模式={self.eval_mode}，模型={self.model_ids}')

        # 串行评价（每篇文献独立，失败不影响其他）
        # 若需并发可改为 ThreadPoolExecutor，暂时串行保证稳定性
        for ref in refs:
            try:
                self._eval_one_ref(ref)
            except Exception as e:
                logger.exception(f'[QA] 文献 {ref.id} 评价失败: {e}')
                QAReference.objects.filter(pk=ref.id).update(ai_eval_status='failed')

        logger.info(f'[QA] 评价完成 project_id={self.project_id}')

        # 扣积分
        if self.user_id:
            try:
                from core.services.billing_service import deduct_credits, estimate_credits
                credits = estimate_credits(len(refs), self.model_ids)
                deduct_credits(self.user_id, credits, reason='质量评价 AI 评价')
            except Exception as e:
                logger.warning(f'[QA] 扣积分失败（非致命）: {e}')

    def _eval_one_ref(self, ref):
        from core.models import QAReference, QASignalItem
        from core.services.quality_methods import get_method_config
        from core.api.qa_views import _recalc_domain_results

        method_key = ref.quality_method
        try:
            method_cfg = get_method_config(method_key)
        except Exception:
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='skipped_no_method')
            return

        signal_items_cfg = method_cfg.get('signal_items', [])
        if not signal_items_cfg:
            # 方法未配置信号问题（如 ROB2）
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='skipped_no_method')
            return

        # 获取内容
        content, has_fulltext = self._get_ref_content(ref)
        if not content:
            QAReference.objects.filter(pk=ref.id).update(ai_eval_status='skipped_no_fulltext')
            logger.info(f'[QA] 文献 {ref.id} 无全文和摘要，跳过')
            return

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

        # ── 单模型评价 ──────────────────────────────────────────
        if self.eval_mode == 'single':
            model_id = self.model_ids[0] if self.model_ids else 'deepseek'
            model_results = _call_model_for_ref(model_id, prompt, signal_items_cfg)
            result_map = {r['signal_key']: r for r in model_results}

            # 先删除已有条目（重新生成场景）
            QASignalItem.objects.filter(qa_ref=ref).delete()

            for cfg_item in signal_items_cfg:
                r = result_map.get(cfg_item['signal_key'], {})
                judgment = r.get('judgment', '')
                QASignalItem.objects.create(
                    qa_ref=ref,
                    quality_method=method_key,
                    domain=cfg_item['domain'],
                    result_type=cfg_item['result_type'],
                    signal_key=cfg_item['signal_key'],
                    signal_question=cfg_item['signal_question'],
                    signal_description=cfg_item['signal_description'],
                    options=cfg_item['options'],
                    ai_judgment=judgment,
                    ai_reason=r.get('reason', ''),
                    ai_evidence=r.get('evidence', ''),
                    ai_evidence_page=r.get('evidence_page', ''),
                    consistency='single',
                    system_recommendation=judgment,
                    pre_selected=judgment,
                )

        # ── 双模型校验 ──────────────────────────────────────────
        else:
            model1_id = self.model_ids[0] if len(self.model_ids) > 0 else 'deepseek'
            model2_id = self.model_ids[1] if len(self.model_ids) > 1 else model1_id

            logger.info(f'[QA] 文献 {ref.id} 双模型: model1={model1_id}, model2={model2_id}')
            results1 = _call_model_for_ref(model1_id, prompt, signal_items_cfg)
            results2 = _call_model_for_ref(model2_id, prompt, signal_items_cfg)
            map1 = {r['signal_key']: r for r in results1}
            map2 = {r['signal_key']: r for r in results2}

            QASignalItem.objects.filter(qa_ref=ref).delete()

            for cfg_item in signal_items_cfg:
                sk = cfg_item['signal_key']
                r1 = map1.get(sk, {})
                r2 = map2.get(sk, {})
                consistency, recommendation = _determine_consistency(r1, r2)

                QASignalItem.objects.create(
                    qa_ref=ref,
                    quality_method=method_key,
                    domain=cfg_item['domain'],
                    result_type=cfg_item['result_type'],
                    signal_key=sk,
                    signal_question=cfg_item['signal_question'],
                    signal_description=cfg_item['signal_description'],
                    options=cfg_item['options'],
                    # 双模型字段
                    model1_id=model1_id,
                    model1_judgment=r1.get('judgment', ''),
                    model1_reason=r1.get('reason', ''),
                    model2_id=model2_id,
                    model2_judgment=r2.get('judgment', ''),
                    model2_reason=r2.get('reason', ''),
                    consistency=consistency,
                    system_recommendation=recommendation,
                    pre_selected=recommendation,
                    # 兼容单模型字段（用 model1 结果填充，便于界面显示）
                    ai_judgment=r1.get('judgment', '') or r2.get('judgment', ''),
                    ai_reason=r1.get('reason', '') or r2.get('reason', ''),
                    ai_evidence=r1.get('evidence', '') or r2.get('evidence', ''),
                    ai_evidence_page=r1.get('evidence_page', '') or r2.get('evidence_page', ''),
                )

        # 更新文献状态
        QAReference.objects.filter(pk=ref.id).update(ai_eval_status=ai_status)

        # 初始化领域结果（全部 pending，等待人工确认后重算）
        from core.api.qa_views import _recalc_domain_results
        ref.refresh_from_db()
        _recalc_domain_results(ref)

        logger.info(f'[QA] 文献 {ref.id} 评价完成，状态={ai_status}，创建 {len(signal_items_cfg)} 条信号问题')

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
