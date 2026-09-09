"""
人工审阅 API

接口列表：
  GET  /api/review/list/    → 分页返回文献列表（含 abstract，从 XML 读）
  POST /api/review/submit/  → 批量提交/更新人工决定
  PATCH /api/review/item/<source_xml>/ → 单条即时更新（source_xml URL 编码）
  GET  /api/review/stats/   → 统计（total/reviewed/pending/included/excluded）
  POST /api/review/complete/ → 标记 review 步骤为 completed
  POST /api/review/note/<source_xml>/  → 追加备注（append）
  GET  /api/review/notes/<source_xml>/ → 查询历史备注列表
"""

import json
import logging
from datetime import datetime, timezone
from urllib.parse import unquote

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required

from core.models import StageStep, ManualReview
from core.services.access_policy import ProjectAccessPolicy
from core.screening.api.serializers import (
    ReviewCompleteInputSerializer,
    ReviewNoteInputSerializer,
    ReviewSubmitInputSerializer,
    ReviewUpdateInputSerializer,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _get_project(user, project_id):
    return ProjectAccessPolicy.get_project(user, project_id)


def _get_step(user, project_id, step_id):
    """获取 review 步骤对象，校验归属。"""
    return StageStep.objects.filter(
        id=step_id,
        stage__project_id=project_id,
        stage__project__in=ProjectAccessPolicy.visible_projects(user),
        step_key='review',
    ).first()


def _validated_json(request, serializer_class):
    try:
        body = json.loads(request.body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, JsonResponse({'error': '请求体非法 JSON'}, status=400)
    serializer = serializer_class(data=body)
    if not serializer.is_valid():
        return None, JsonResponse({'error': serializer.errors}, status=400)
    return serializer.validated_data, None


from core.screening.selectors import (
    load_ai_results,
    load_ai_result_file,
    load_xml_fields_bulk,
)
from core.screening.services.review_query import (
    aggregate_review_stats,
    final_decision_filter,
    review_result_queryset,
)


def _indexed_results_available(queryset):
    """Only use the fast path when result metadata contains its lookup key."""
    return queryset is not None and queryset.filter(
        metadata__source_xml__isnull=False,
    ).exists()


def _indexed_review_list(project_id, queryset, decision, q, page, page_size):
    """Filter and paginate in SQL, then open only the current page's files."""
    queryset = queryset.filter(final_decision_filter(decision))
    if q:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(metadata__title__icontains=q)
            | Q(filename__icontains=q.replace(' ', '_'))
        )

    queryset = queryset.order_by('ai_excluded_priority', 'id')
    total = queryset.count()
    start = (page - 1) * page_size
    data_files = list(queryset[start:start + page_size])
    result_pairs = [(data_file, load_ai_result_file(data_file)) for data_file in data_files]

    source_xmls = [
        result.get('source_xml') or (data_file.metadata or {}).get('source_xml', '')
        for data_file, result in result_pairs
    ]
    reviews = {
        review.source_xml: review
        for review in ManualReview.objects.filter(
            project_id=project_id,
            source_xml__in=[source for source in source_xmls if source],
        )
    }

    items = []
    for data_file, result in result_pairs:
        metadata = data_file.metadata or {}
        source_xml = result.get('source_xml') or metadata.get('source_xml', '')
        ai_decision = result.get('decision', '') or (
            'included' if result.get('include_or_not', '').lower() == 'yes'
            else ('excluded' if result.get('include_or_not', '').lower() == 'no' else '')
        )
        review = reviews.get(source_xml)
        items.append({
            'source_xml': source_xml,
            'title': result.get('title', '') or result.get('Title', '') or metadata.get('title', ''),
            'authors': result.get('authors', '') or metadata.get('authors', ''),
            'year': result.get('year', '') or metadata.get('year', ''),
            'journal': result.get('journal', '') or metadata.get('journal', ''),
            'doi': result.get('doi', '') or metadata.get('doi', ''),
            'url': result.get('url', '') or metadata.get('url', ''),
            'ai_decision': ai_decision,
            'ai_reason': result.get('exclusion_reason', '') or metadata.get('ai_reason', ''),
            'consensus': result.get('consensus', ai_decision),
            'multi_model_results': result.get('multi_model_results', []),
            'human_decision': review.decision if review else None,
            'human_reason': review.reason if review else '',
            'is_override': review.is_override if review else False,
            'reviewed_at': review.reviewed_at.isoformat() if review else None,
            'has_notes': bool(review and review.notes),
        })

    xml_fields = load_xml_fields_bulk(
        [item['source_xml'] for item in items], project_id,
    )
    for item in items:
        xml_data = xml_fields.get(item['source_xml'], {})
        item['abstract'] = xml_data.get('abstract', '')
        if not item.get('url'):
            item['url'] = xml_data.get('url', '')

    return JsonResponse({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': items,
    })
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
    if not project_id or not step_id:
        return JsonResponse({'error': '缺少 project 或 step 参数'}, status=400)
    step = _get_step(request.user, project_id, step_id)
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)
    try:
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(max(1, int(request.GET.get('page_size', 50))), 200)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'page 和 page_size 必须是正整数'}, status=400)

    indexed_results = review_result_queryset(project_id)
    if _indexed_results_available(indexed_results):
        return _indexed_review_list(
            project_id, indexed_results, decision, q, page, page_size,
        )

    # 加载 AI 结果
    all_results = load_ai_results(project_id)

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
        has_notes      = bool(mr and mr.notes)

        # Tab 过滤（按「最终决定」口径：人工有则用人工，否则用AI；conflict = 有歧义且未人工定夺）
        # 计算本条文献的最终决定
        consensus_val = r.get('consensus', ai_decision)
        if human_decision is not None:
            final_dec = human_decision          # 人工已审 → 以人工为准
        elif consensus_val == 'conflict':
            final_dec = 'conflict'              # 未审且有歧义
        elif ai_decision in ('included', 'excluded'):
            final_dec = ai_decision             # 未审且 AI 有明确结论
        else:
            final_dec = 'pending'               # 未审且 AI 无明确结论

        if decision == 'unreviewed' and human_decision is not None:
            continue
        elif decision in ('included', 'excluded', 'pending', 'conflict') and final_dec != decision:
            continue

        # 标题搜索
        if q and q.lower() not in title.lower():
            continue

        items.append({
            'source_xml':          source_xml,
            'title':               title,
            'authors':             r.get('authors', ''),
            'year':                r.get('year', ''),
            'journal':             r.get('journal', ''),
            'doi':                 r.get('doi', ''),
            'url':                 r.get('url', ''),
            'ai_decision':         ai_decision,
            'ai_reason':           ai_reason,
            'consensus':           r.get('consensus', ai_decision),  # 多模型共识结论
            'multi_model_results': r.get('multi_model_results', []), # 各模型子结果
            'human_decision':      human_decision,
            'human_reason':        human_reason,
            'is_override':         is_override,
            'reviewed_at':         reviewed_at,
            'has_notes':           has_notes,
        })

    # 排序：AI excluded 优先（方便人工找被误排的文献）
    items.sort(key=lambda x: (0 if x['ai_decision'] == 'excluded' else 1))

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start: start + page_size]

    # 按需加载 abstract 和 url（仅当前页，避免全量 IO）
    xml_fields = load_xml_fields_bulk(
        [item['source_xml'] for item in page_items], project_id,
    )
    for item in page_items:
        xml_data = xml_fields.get(item['source_xml'], {})
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
@require_http_methods(["POST"])
def review_submit(request):
    data, error = _validated_json(request, ReviewSubmitInputSerializer)
    if error:
        return error
    step = _get_step(request.user, data['project'], data['step'])
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)

    from core.screening.services.review_service import submit_reviews

    created, updated = submit_reviews(
        data['project'], step, data['reviews'], request.user
    )
    return JsonResponse({'created': created, 'updated': updated})


@login_required
@require_http_methods(["PATCH"])
def review_item(request, source_xml):
    source_xml = unquote(source_xml)
    data, error = _validated_json(request, ReviewUpdateInputSerializer)
    if error:
        return error
    step = _get_step(request.user, data['project'], data['step'])
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)

    from core.screening.services.review_service import update_review

    review, created = update_review(
        data['project'], step, source_xml, data['decision'], data['reason'], request.user
    )
    return JsonResponse({
        'created': created,
        'source_xml': source_xml,
        'decision': review.decision,
        'is_override': review.is_override,
        'reviewed_at': review.reviewed_at.isoformat(),
    })


@login_required
@require_http_methods(["GET"])
def review_stats(request):
    project_id = request.GET.get('project')
    if not project_id:
        return JsonResponse({'error': '缺少 project 参数'}, status=400)
    if not _get_project(request.user, project_id):
        return JsonResponse({'error': '无权访问该项目或项目不存在'}, status=404)

    indexed_results = review_result_queryset(project_id)
    if _indexed_results_available(indexed_results):
        return JsonResponse(aggregate_review_stats(indexed_results))

    all_results = load_ai_results(project_id)
    total = len(all_results)

    result_source_xmls = {
        r.get('source_xml', '') for r in all_results if r.get('source_xml')
    }
    # 只统计本次 AI 结果中的人工记录，避免历史/备注占位记录使未审数变成负数。
    reviews = ManualReview.objects.filter(
        project_id=project_id,
        source_xml__in=result_source_xmls,
    )
    reviewed_xml_set = set(reviews.values_list('source_xml', flat=True))
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
    # ai_excluded：仅统计明确排除且无歧义的文献（歧义文献单独计入 conflict）
    ai_conflict = sum(
        1 for r in all_results
        if r.get('consensus') == 'conflict'
    )
    ai_excluded = sum(
        1 for r in all_results
        if ((r.get('decision') == 'excluded') or (r.get('include_or_not', '').lower() == 'no'))
        and r.get('consensus') != 'conflict'
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

    # 分歧数： consensus = conflict 且未人工定夺
    conflict_count = sum(
        1 for r in all_results
        if r.get('consensus') == 'conflict' and
           r.get('source_xml', '') not in reviewed_xml_set
    )

    # ── 最终决定口径统计（用于左侧 Tab 计数，保证各分类之和 = total）──
    # 规则：人工有则用人工，无则用AI；conflict = 有歧义且未人工定夺
    tab_included = 0
    tab_excluded = 0
    tab_pending  = 0
    tab_conflict = 0
    reviewed_xml_map = {
        mr.source_xml: mr.decision
        for mr in reviews
    }
    for r in all_results:
        xml = r.get('source_xml', '')
        ai_dec = r.get('decision', '') or ('included' if r.get('include_or_not', '').lower() == 'yes' else
                                           'excluded' if r.get('include_or_not', '').lower() == 'no' else '')
        consensus = r.get('consensus', ai_dec)
        if xml in reviewed_xml_map:
            human_dec = reviewed_xml_map[xml]
            if human_dec == 'included':  tab_included += 1
            elif human_dec == 'excluded': tab_excluded += 1
            else:                         tab_pending  += 1
        elif consensus == 'conflict':
            tab_conflict += 1
        elif ai_dec == 'included':
            tab_included += 1
        elif ai_dec == 'excluded':
            tab_excluded += 1
        else:
            tab_pending += 1

    # 最终筛选结果 = 人工审阅结果 + 未审文献的 AI 结果
    final_included = included  # 人工标记纳入
    final_excluded = excluded  # 人工标记排除
    final_conflict_pending = 0  # 未被人工定夺的分歧文献 + 人工标记待定
    for r in all_results:
        xml = r.get('source_xml', '')
        if xml in reviewed_xml_set:
            continue  # 已人工审阅，已计入上面
        ai_dec = r.get('decision', '') or ('included' if r.get('include_or_not', '').lower() == 'yes' else
                                           'excluded' if r.get('include_or_not', '').lower() == 'no' else '')
        consensus = r.get('consensus', ai_dec)
        if ai_dec == 'included' and consensus != 'conflict':
            final_included += 1
        elif ai_dec == 'excluded' and consensus != 'conflict':
            final_excluded += 1
        else:
            # 未审的分歧文献或无明确结论的文献
            final_conflict_pending += 1

    # 人工标记待定也归入 final_conflict_pending（分歧+待定合并展示）
    final_conflict_pending += pending

    return JsonResponse({
        'total':       total,
        'reviewed':    reviewed,
        'unreviewed':  total - reviewed,
        'included':    included,    # 人工审阅标记纳入
        'excluded':    excluded,    # 人工审阅标记排除
        'pending':     pending,
        'conflict':    conflict_count,
        'overridden':  overridden,
        'ai_included': ai_included,
        'ai_excluded': ai_excluded,  # 不含歧义文献
        'ai_conflict': ai_conflict,  # 歧义（模型结论分歧）文献数
        # ── 最终决定口径（Tab 计数用，加起来 = total）──
        'tab_included': tab_included,
        'tab_excluded': tab_excluded,
        'tab_pending':  tab_pending,
        'tab_conflict': tab_conflict,
        'final_included': final_included,       # 最终纳入（人工覆写 + 未审的AI结论）
        'final_excluded': final_excluded,       # 最终排除
        'final_conflict_pending': final_conflict_pending,  # 分歧+待定（未解决）
        # 准确率相关
        'ai_accuracy':            ai_accuracy,
        'ai_correct_in_reviewed': ai_correct_in_reviewed,
        'ai_wrong_in_reviewed':   ai_wrong_in_reviewed,
        'decisive_reviewed':      decisive_reviewed_count,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/review/complete/  → 标记 review 步骤 completed
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def review_complete(request):
    data, error = _validated_json(request, ReviewCompleteInputSerializer)
    if error:
        return error
    project_id = data['project']
    step_id = data['step']
    step = _get_step(request.user, project_id, step_id)
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)

    from datetime import datetime
    reviews = ManualReview.objects.filter(project_id=project_id)
    stats = {
        'total':      len(load_ai_results(project_id)),
        'reviewed':   reviews.count(),
        'included':   reviews.filter(decision='included').count(),
        'excluded':   reviews.filter(decision='excluded').count(),
        'pending':    reviews.filter(decision='pending').count(),
        'completed_at': datetime.now().isoformat(),
    }

    from core.workflow.domain.statuses import StageStepStatus
    from core.workflow.services.lifecycle import transition_step

    transition_step(
        step,
        StageStepStatus.COMPLETED,
        updates={'metadata': {**(step.metadata or {}), **stats}},
    )

    return JsonResponse({'ok': True, 'stats': stats})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/review/note/<path:source_xml>/  → 追加备注
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def review_note_append(request, source_xml):
    """
    向指定文献追加一条备注。
    请求体：{"project": <id>, "step": <id>, "content": "备注内容"}
    备注以 JSON 数组形式保存在 ManualReview.notes 字段，每条追加不覆盖历史。
    若该文献尚无 ManualReview 记录则先创建（decision 用 pending 占位）。
    """
    source_xml = unquote(source_xml)
    data, error = _validated_json(request, ReviewNoteInputSerializer)
    if error:
        return error
    project_id = data['project']
    step_id = data['step']
    content = data['content']
    step = _get_step(request.user, project_id, step_id)
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)

    # 新备注条目
    note_entry = {
        'content':    content,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'user':       request.user.username,
    }

    # 查找或创建 ManualReview 记录（notes append 不依赖 decision 字段）
    try:
        mr = ManualReview.objects.get(project_id=project_id, source_xml=source_xml)
        notes = list(mr.notes or [])
        notes.append(note_entry)
        mr.notes = notes
        mr.save(update_fields=['notes'])
        created = False
    except ManualReview.DoesNotExist:
        # 先查 AI 决定作为占位
        ai_decision, ai_reason = '', ''
        for r in load_ai_results(project_id):
            if r.get('source_xml') == source_xml:
                ai_decision = r.get('decision') or ('included' if r.get('include_or_not', '').lower() == 'yes' else 'excluded')
                ai_reason   = r.get('exclusion_reason', '')
                break
        mr = ManualReview.objects.create(
            project_id=project_id,
            source_xml=source_xml,
            step=step,
            ai_decision=ai_decision,
            ai_reason=ai_reason,
            decision='pending',
            reason='',
            is_override=False,
            reviewer=request.user,
            notes=[note_entry],
        )
        created = True

    return JsonResponse({
        'ok':      True,
        'created': created,
        'note':    note_entry,
        'total':   len(mr.notes),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/review/notes/<path:source_xml>/  → 查询历史备注
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def review_notes_list(request, source_xml):
    """返回指定文献的所有历史备注（按时间倒序）。"""
    source_xml = unquote(source_xml)
    project_id = request.GET.get('project')
    if not project_id:
        return JsonResponse({'error': '缺少 project 参数'}, status=400)
    if not _get_project(request.user, project_id):
        return JsonResponse({'error': '无权访问该项目或项目不存在'}, status=404)

    try:
        mr = ManualReview.objects.get(project_id=project_id, source_xml=source_xml)
        notes = list(mr.notes or [])
    except ManualReview.DoesNotExist:
        notes = []

    # 倒序返回（最新在前）
    notes_desc = list(reversed(notes))
    return JsonResponse({'notes': notes_desc, 'total': len(notes_desc)})
