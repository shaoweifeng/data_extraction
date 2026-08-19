"""
人工审阅 API

接口列表：
  GET  /api/review/list/    → 分页返回文献列表（含 abstract，从 XML 读）
  POST /api/review/submit/  → 批量提交/更新人工决定
  PATCH /api/review/item/<source_xml>/ → 单条即时更新（source_xml URL 编码）
  GET  /api/review/stats/   → 统计（total/reviewed/pending/included/excluded）
  POST /api/review/complete/ → 标记 review 步骤为 completed
"""

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction

from core.models import DataFile, StageStep, ManualReview

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _get_step(project_id, step_id):
    """获取 review 步骤对象，校验归属。"""
    return StageStep.objects.filter(
        id=step_id,
        stage__project_id=project_id,
        step_key='review',
    ).first()


def _load_xml_fields(source_xml: str, project_id) -> dict:
    """
    从原始 XML 文件中读取 abstract、url、doi 等字段，一次读取，避免重复 IO。

    背景：AI 筛选结果 JSON 中的 source_xml 存的是文件名（如 00006_xxx_d698f2b6.xml），
    而实际 XML 文件在 intermediate/ 目录下的随机后缀不同（如 00006_xxx_Q7QCqN2.xml）。
    因此不能精确匹配文件名，需用数字编号前缀（如 "00006_"）模糊匹配。
    """
    if not source_xml:
        return {}
    try:
        import re
        from django.conf import settings as django_settings

        def _parse_fields(path: Path) -> dict:
            root = ET.parse(path).getroot()
            ref = root
            if root.tag not in ("Reference", "reference"):
                ref = root.find(".//Reference") or root.find(".//reference") or root
            def _t(tag):
                el = ref.find(tag)
                return ''.join(el.itertext()).strip() if el is not None else ''
            return {
                'abstract': _t('Abstract'),
                'url':      _t('Url') or _t('URL') or _t('url'),
                'doi':      _t('Doi') or _t('DOI'),
            }

        # 1. 直接尝试绝对路径（_load_refs_from_xml 降级路径存的是绝对路径）
        p = Path(source_xml)
        if p.exists():
            return _parse_fields(p)

        # 2. 提取编号前缀（如 "00006_"）进行模糊匹配
        xml_name = p.name
        num_prefix_match = re.match(r'^(\d+_)', xml_name)

        project_dir = Path(django_settings.MEDIA_ROOT) / 'projects' / f'project_{project_id}'

        if num_prefix_match and project_dir.exists():
            num_prefix = num_prefix_match.group(1)
            for candidate in project_dir.rglob(num_prefix + '*.xml'):
                if candidate.is_file():
                    return _parse_fields(candidate)

        # 3. 无数字前缀则精确文件名查找（兜底）
        if project_dir.exists():
            for candidate in project_dir.rglob(xml_name):
                if candidate.is_file():
                    return _parse_fields(candidate)

        logger.debug(f"[review] 未找到 XML 文件: {source_xml} (project_id={project_id}, project_dir={project_dir})")
        return {}
    except Exception as e:
        logger.debug(f"[review] 读取 XML 字段失败 {source_xml}: {e}")
        return {}


def _ai_result_files(project_id, ai_step):
    """返回 ai_screen 输出的所有结果文件列表（DataFile QuerySet）。"""
    return DataFile.objects.filter(
        project_id=project_id,
        step=ai_step,
        data_category='output',
        description='AI筛选结果',
    )


def _load_ai_results(project_id):
    """
    加载文献列表。优先从 ai_screen 结果 JSON 读取；
    若 ai_screen 未执行，则从去重后 XML 文件中读取基础信息（title/source_xml），
    使人工审阅步骤可独立于 AI 初筛运作。
    """
    from core.models import StageStep
    ai_step = StageStep.objects.filter(
        stage__project_id=project_id,
        step_key='ai_screen',
    ).order_by('-id').first()

    if ai_step:
        result_files = _ai_result_files(project_id, ai_step)
        if result_files.exists():
            results = []
            for df in result_files:
                try:
                    with open(df.file.path, 'r', encoding='utf-8') as f:
                        results.append(json.load(f))
                except Exception as e:
                    logger.warning(f"[review] 读取结果文件失败 {df.filename}: {e}")
            if results:
                return results

    # ── 降级：从去重后 XML 文件读取基础信息 ──
    return _load_refs_from_xml(project_id)


def _load_refs_from_xml(project_id):
    """
    AI 初筛未完成时，从 dedup 步骤输出的 XML 文件中读取文献基础信息，
    以支持人工审阅独立运作。
    返回结构与 AI 结果 JSON 兼容（decision/include_or_not 留空）。
    """
    import xml.etree.ElementTree as ET
    from core.models import DataFile, StageStep

    dedup_step = StageStep.objects.filter(
        stage__project_id=project_id,
        step_key='dedup',
    ).order_by('-id').first()

    xml_files = DataFile.objects.filter(
        project_id=project_id,
        data_category='output',
    )
    if dedup_step:
        xml_files = xml_files.filter(step=dedup_step)

    results = []
    for df in xml_files:
        if not df.file or not df.filename.endswith('.xml'):
            continue
        try:
            root = ET.parse(df.file.path).getroot()
            ref = root
            if root.tag not in ("Reference", "reference"):
                ref = root.find(".//Reference") or root.find(".//reference") or root

            def _t(tag):
                el = ref.find(tag)
                return ''.join(el.itertext()).strip() if el is not None else ''

            results.append({
                'source_xml':      df.file.path,
                'title':           _t('Title'),
                'authors':         _t('Authors') or _t('Author'),
                'year':            _t('Year'),
                'journal':         _t('Journal'),
                'doi':             _t('Doi') or _t('DOI'),
                'url':             _t('URL') or _t('Url') or _t('url'),
                'decision':        '',        # 无 AI 判断
                'include_or_not':  '',
                'exclusion_reason': '',
            })
        except Exception as e:
            logger.debug(f"[review] 解析 XML 失败 {df.filename}: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/review/list/?project=&step=&decision=&q=&page=&page_size=
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def review_list(request):
    project_id = request.GET.get('project')
    step_id    = request.GET.get('step')
    decision   = request.GET.get('decision', '')   # '' = 全部
    q          = request.GET.get('q', '').strip()
    page       = int(request.GET.get('page', 1))
    page_size  = min(int(request.GET.get('page_size', 50)), 200)

    if not project_id or not step_id:
        return JsonResponse({'error': '缺少 project 或 step 参数'}, status=400)

    # 加载 AI 结果
    all_results = _load_ai_results(project_id)

    # 查出该项目所有 ManualReview 记录（dict: source_xml → review）
    reviews = {
        mr.source_xml: mr
        for mr in ManualReview.objects.filter(project_id=project_id)
    }

    # 组装展示列表
    items = []
    for r in all_results:
        source_xml  = r.get('source_xml', '')
        ai_decision = r.get('decision', '') or (
            'included' if r.get('include_or_not', '').lower() == 'yes'
            else ('excluded' if r.get('include_or_not', '').lower() == 'no' else '')
        )
        ai_reason   = r.get('exclusion_reason', '')
        title       = r.get('title', '') or r.get('Title', '')

        mr = reviews.get(source_xml)
        human_decision = mr.decision if mr else None   # None = 未审阅
        human_reason   = mr.reason   if mr else ''
        is_override    = mr.is_override if mr else False
        reviewed_at    = mr.reviewed_at.isoformat() if mr else None

        # Tab 过滤
        if decision == 'unreviewed' and human_decision is not None:
            continue
        elif decision in ('included', 'excluded', 'pending') and human_decision != decision:
            continue

        # 标题搜索
        if q and q.lower() not in title.lower():
            continue

        items.append({
            'source_xml':     source_xml,
            'title':          title,
            'authors':        r.get('authors', ''),
            'year':           r.get('year', ''),
            'journal':        r.get('journal', ''),
            'doi':            r.get('doi', ''),
            'url':            r.get('url', ''),
            'ai_decision':    ai_decision,
            'ai_reason':      ai_reason,
            'human_decision': human_decision,
            'human_reason':   human_reason,
            'is_override':    is_override,
            'reviewed_at':    reviewed_at,
        })

    # 排序：AI excluded 优先（方便人工找被误排的文献）
    items.sort(key=lambda x: (0 if x['ai_decision'] == 'excluded' else 1))

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start: start + page_size]

    # 按需加载 abstract 和 url（仅当前页，避免全量 IO）
    for item in page_items:
        xml_data = _load_xml_fields(item['source_xml'], project_id)
        item['abstract'] = xml_data.get('abstract', '')
        # url 优先用 JSON 里的值，为空则从 XML 补充
        if not item.get('url'):
            item['url'] = xml_data.get('url', '')

    return JsonResponse({
        'total':    total,
        'page':     page,
        'page_size': page_size,
        'results':  page_items,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/review/submit/  → 批量提交
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def review_submit(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '请求体非法 JSON'}, status=400)

    project_id = data.get('project')
    step_id    = data.get('step')
    reviews    = data.get('reviews', [])

    if not project_id or not step_id or not reviews:
        return JsonResponse({'error': '缺少必要参数'}, status=400)

    step = _get_step(project_id, step_id)
    if not step:
        return JsonResponse({'error': '未找到 review 步骤'}, status=404)

    # 预加载 AI 原始决定
    ai_map = {}
    for r in _load_ai_results(project_id):
        sx = r.get('source_xml', '')
        if sx:
            raw_decision = r.get('decision', '') or (
                'included' if r.get('include_or_not', '').lower() == 'yes'
                else ('excluded' if r.get('include_or_not', '').lower() == 'no' else '')
            )
            ai_map[sx] = {
                'decision': raw_decision,
                'reason':   r.get('exclusion_reason', ''),
            }

    created, updated = 0, 0
    with transaction.atomic():
        for item in reviews:
            source_xml = item.get('source_xml', '')
            decision   = item.get('decision', '')
            reason     = item.get('reason', '')
            if not source_xml or not decision:
                continue

            ai_info    = ai_map.get(source_xml, {})
            is_override = ai_info.get('decision', '') != decision

            mr, new = ManualReview.objects.update_or_create(
                project_id=project_id,
                source_xml=source_xml,
                defaults={
                    'step':        step,
                    'ai_decision': ai_info.get('decision', ''),
                    'ai_reason':   ai_info.get('reason', ''),
                    'decision':    decision,
                    'reason':      reason,
                    'is_override': is_override,
                    'reviewer':    request.user,
                },
            )
            if new:
                created += 1
            else:
                updated += 1

    return JsonResponse({'created': created, 'updated': updated})


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/review/item/<path:source_xml>/  → 单条即时更新
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@csrf_exempt
@require_http_methods(["PATCH"])
def review_item(request, source_xml):
    source_xml = unquote(source_xml)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '请求体非法 JSON'}, status=400)

    project_id = data.get('project')
    step_id    = data.get('step')
    decision   = data.get('decision', '')
    reason     = data.get('reason', '')

    if not project_id or not step_id or not decision:
        return JsonResponse({'error': '缺少必要参数'}, status=400)

    step = _get_step(project_id, step_id)
    if not step:
        return JsonResponse({'error': '未找到 review 步骤'}, status=404)

    # 查 AI 原始决定
    ai_decision, ai_reason = '', ''
    for r in _load_ai_results(project_id):
        if r.get('source_xml') == source_xml:
            ai_decision = r.get('decision') or ('included' if r.get('include_or_not', '').lower() == 'yes' else 'excluded')
            ai_reason   = r.get('exclusion_reason', '')
            break

    is_override = bool(ai_decision) and ai_decision != decision

    mr, created = ManualReview.objects.update_or_create(
        project_id=project_id,
        source_xml=source_xml,
        defaults={
            'step':        step,
            'ai_decision': ai_decision,
            'ai_reason':   ai_reason,
            'decision':    decision,
            'reason':      reason,
            'is_override': is_override,
            'reviewer':    request.user,
        },
    )

    return JsonResponse({
        'created':     created,
        'source_xml':  source_xml,
        'decision':    mr.decision,
        'is_override': mr.is_override,
        'reviewed_at': mr.reviewed_at.isoformat(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/review/stats/?project=&step=
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def review_stats(request):
    project_id = request.GET.get('project')
    if not project_id:
        return JsonResponse({'error': '缺少 project 参数'}, status=400)

    all_results = _load_ai_results(project_id)
    total = len(all_results)

    reviews = ManualReview.objects.filter(project_id=project_id)
    reviewed   = reviews.count()
    included   = reviews.filter(decision='included').count()
    excluded   = reviews.filter(decision='excluded').count()
    pending    = reviews.filter(decision='pending').count()
    overridden = reviews.filter(is_override=True).count()

    # AI 原始统计（无 AI 结果时为 0）
    ai_included = sum(
        1 for r in all_results
        if (r.get('decision') == 'included') or (r.get('include_or_not', '').lower() == 'yes')
    )
    ai_excluded = sum(
        1 for r in all_results
        if (r.get('decision') == 'excluded') or (r.get('include_or_not', '').lower() == 'no')
    )

    # AI 准确率：以人工审阅结果为标准
    # - 参与人工审阅的文献中，人工决定与 AI 一致的条数（pending 不计入）
    # - 未参与人工审阅的文献默认 AI 正确
    reviewed_decisive = reviews.filter(decision__in=['included', 'excluded'])
    ai_correct_in_reviewed = reviewed_decisive.filter(is_override=False).count()
    ai_wrong_in_reviewed   = reviewed_decisive.filter(is_override=True).count()
    decisive_reviewed_count = reviewed_decisive.count()
    unreviewed_count = total - reviewed

    # 准确率分子 = AI在已审中正确数 + 未审文献数（默认正确）
    # 准确率分母 = 总文献数（pending 不参与准确率计算，故分母用 total - pending_count）
    pending_count = pending
    accuracy_denominator = total - pending_count
    accuracy_numerator   = ai_correct_in_reviewed + unreviewed_count
    ai_accuracy = round(accuracy_numerator / accuracy_denominator * 100, 1) if accuracy_denominator > 0 else None

    return JsonResponse({
        'total':       total,
        'reviewed':    reviewed,
        'unreviewed':  total - reviewed,
        'included':    included,
        'excluded':    excluded,
        'pending':     pending,
        'overridden':  overridden,
        'ai_included': ai_included,
        'ai_excluded': ai_excluded,
        # 准确率相关
        'ai_accuracy':            ai_accuracy,         # 百分比浮点，如 87.5
        'ai_correct_in_reviewed': ai_correct_in_reviewed,
        'ai_wrong_in_reviewed':   ai_wrong_in_reviewed,
        'decisive_reviewed':      decisive_reviewed_count,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/review/complete/  → 标记 review 步骤 completed
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def review_complete(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '请求体非法 JSON'}, status=400)

    project_id = data.get('project')
    step_id    = data.get('step')

    if not project_id or not step_id:
        return JsonResponse({'error': '缺少必要参数'}, status=400)

    step = _get_step(project_id, step_id)
    if not step:
        return JsonResponse({'error': '未找到 review 步骤'}, status=404)

    from datetime import datetime
    reviews = ManualReview.objects.filter(project_id=project_id)
    stats = {
        'total':      len(_load_ai_results(project_id)),
        'reviewed':   reviews.count(),
        'included':   reviews.filter(decision='included').count(),
        'excluded':   reviews.filter(decision='excluded').count(),
        'pending':    reviews.filter(decision='pending').count(),
        'completed_at': datetime.now().isoformat(),
    }

    step.status = 'completed'
    step.metadata = {**(step.metadata or {}), **stats}
    step.save(update_fields=['status', 'metadata'])

    return JsonResponse({'ok': True, 'stats': stats})
