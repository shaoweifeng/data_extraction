"""Database-backed manual screening review API."""

import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.models import ActivityLog, ManualReview, StageStep
from core.screening.api.serializers import (
    ReviewCompleteInputSerializer,
    ReviewNoteInputSerializer,
    ReviewSubmitInputSerializer,
    ReviewUpdateInputSerializer,
)
from core.screening.models import ScreeningResult, ScreeningRun
from core.screening.services.review_query import (
    aggregate_review_stats,
    final_decision_filter,
    review_result_queryset,
)
from core.screening.services.screening_run_service import screening_run_is_current
from core.services.access_policy import ProjectAccessPolicy


def _get_project(user, project_id):
    return ProjectAccessPolicy.get_project(user, project_id)


def _get_step(user, project_id, step_id):
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


def _review_service_error(exc):
    status = 409 if exc.code == 'screening_run_stale' else 404
    return JsonResponse({'error': {'code': exc.code, 'message': exc.message}}, status=status)


@login_required
@require_http_methods(['GET'])
def review_list(request):
    project_id = request.GET.get('project')
    step_id = request.GET.get('step')
    if not project_id or not step_id:
        return JsonResponse({'error': '缺少 project 或 step 参数'}, status=400)
    if not _get_step(request.user, project_id, step_id):
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)
    try:
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(200, max(1, int(request.GET.get('page_size', 50))))
        run_id = int(request.GET['run']) if request.GET.get('run') else None
    except (TypeError, ValueError):
        return JsonResponse({'error': '分页参数或 run 参数非法'}, status=400)

    queryset = review_result_queryset(project_id, run_id=run_id)
    if queryset is None:
        if run_id is not None:
            return JsonResponse({'error': '未找到指定的 AI 初筛运行'}, status=404)
        return JsonResponse({
            'total': 0, 'page': page, 'page_size': page_size, 'results': [],
            'storage_mode': 'database', 'screening_run_id': None,
            'corpus_revision': None, 'is_current': True,
        })

    run = queryset._screening_run
    is_current = queryset._screening_is_current
    decision = request.GET.get('decision', '')
    queryset = queryset.filter(final_decision_filter(decision))
    query = request.GET.get('q', '').strip()
    if query:
        queryset = queryset.filter(Q(reference__title__icontains=query))
    queryset = queryset.order_by('ai_excluded_priority', 'id')
    total = queryset.count()
    start = (page - 1) * page_size
    rows = list(queryset[start:start + page_size])
    reviews = {
        review.reference_id: review
        for review in ManualReview.objects.filter(
            project_id=project_id,
            screening_run=run,
            reference_id__in=[row.reference_id for row in rows],
        )
    }
    results = []
    for row in rows:
        reference = row.reference
        review = reviews.get(reference.id)
        results.append({
            'reference_id': reference.id,
            'title': reference.title,
            'year': reference.publication_year,
            'journal': reference.journal,
            'ai_decision': row.decision,
            'consensus': row.consensus or row.decision,
            'human_decision': review.decision if review else None,
            'human_reason': review.reason if review else '',
            'is_override': review.is_override if review else False,
            'reviewed_at': review.reviewed_at.isoformat() if review else None,
            'has_notes': bool(review and review.notes),
        })
    return JsonResponse({
        'total': total, 'page': page, 'page_size': page_size, 'results': results,
        'storage_mode': 'database', 'screening_run_id': run.id,
        'corpus_revision': run.corpus_revision,
        'is_current': is_current,
    })


@login_required
@require_http_methods(['GET', 'PATCH'])
def review_reference_item(request, run_id, reference_id):
    if request.method == 'PATCH':
        data, error = _validated_json(request, ReviewUpdateInputSerializer)
        if error:
            return error
        step = _get_step(request.user, data['project'], data['step'])
        if not step:
            return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)
        from core.screening.services.review_service import ReviewRunError, update_review_by_reference
        try:
            review, created = update_review_by_reference(
                data['project'], step, run_id, reference_id,
                data['decision'], data['reason'], request.user,
            )
        except ReviewRunError as exc:
            return _review_service_error(exc)
        return JsonResponse({
            'created': created, 'screening_run_id': run_id,
            'reference_id': reference_id, 'decision': review.decision,
            'is_override': review.is_override,
            'reviewed_at': review.reviewed_at.isoformat(),
        })

    project_id = request.GET.get('project')
    if not project_id or not _get_project(request.user, project_id):
        return JsonResponse({'error': '无权访问该项目或项目不存在'}, status=404)
    result = ScreeningResult.objects.select_related(
        'screening_run__corpus', 'screening_run__dedup_run', 'reference',
    ).filter(
        screening_run_id=run_id, screening_run__project_id=project_id,
        screening_run__status=ScreeningRun.Status.COMPLETED,
        reference_id=reference_id,
    ).first()
    if result is None:
        return JsonResponse({'error': '未找到该文献的初筛结果'}, status=404)
    review = ManualReview.objects.filter(
        screening_run_id=run_id, reference_id=reference_id,
    ).first()
    reference = result.reference
    return JsonResponse({
        'screening_run_id': run_id,
        'corpus_revision': result.screening_run.corpus_revision,
        'is_current': screening_run_is_current(result.screening_run),
        'reference_id': reference.id,
        'title': reference.title,
        'authors': '; '.join(reference.authors or []),
        'year': reference.publication_year,
        'journal': reference.journal,
        'doi': reference.doi,
        'url': reference.url,
        'abstract': reference.abstract,
        'ai_decision': result.decision,
        'ai_reason': result.reason,
        'consensus': result.consensus or result.decision,
        'multi_model_results': result.model_results,
        'extracted_fields': result.extracted_fields,
        'error': result.error_message,
        'human_decision': review.decision if review else None,
        'human_reason': review.reason if review else '',
        'is_override': review.is_override if review else False,
        'reviewed_at': review.reviewed_at.isoformat() if review else None,
        'has_notes': bool(review and review.notes),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def review_reference_notes(request, run_id, reference_id):
    from core.screening.services.review_service import ReviewRunError, append_note, review_notes
    if request.method == 'POST':
        data, error = _validated_json(request, ReviewNoteInputSerializer)
        if error:
            return error
        step = _get_step(request.user, data['project'], data['step'])
        if not step:
            return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)
        try:
            review, note, created = append_note(
                data['project'], step, run_id, reference_id, data['content'], request.user,
            )
        except ReviewRunError as exc:
            return _review_service_error(exc)
        return JsonResponse({'ok': True, 'created': created, 'note': note, 'total': len(review.notes)})
    project_id = request.GET.get('project')
    if not project_id or not _get_project(request.user, project_id):
        return JsonResponse({'error': '无权访问该项目或项目不存在'}, status=404)
    try:
        notes = review_notes(project_id, run_id, reference_id)
    except ReviewRunError as exc:
        return _review_service_error(exc)
    return JsonResponse({'notes': notes, 'total': len(notes)})


@login_required
@require_http_methods(['POST'])
def review_submit(request):
    data, error = _validated_json(request, ReviewSubmitInputSerializer)
    if error:
        return error
    step = _get_step(request.user, data['project'], data['step'])
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)
    from core.screening.services.review_service import ReviewRunError, submit_reviews
    try:
        created, updated = submit_reviews(
            data['project'], step, data['screening_run'], data['reviews'], request.user,
        )
    except ReviewRunError as exc:
        return _review_service_error(exc)
    return JsonResponse({'created': created, 'updated': updated})


@login_required
@require_http_methods(['GET'])
def review_stats(request):
    project_id = request.GET.get('project')
    if not project_id or not _get_project(request.user, project_id):
        return JsonResponse({'error': '无权访问该项目或项目不存在'}, status=404)
    try:
        run_id = int(request.GET['run']) if request.GET.get('run') else None
    except (TypeError, ValueError):
        return JsonResponse({'error': 'run 必须是正整数'}, status=400)
    queryset = review_result_queryset(project_id, run_id=run_id)
    if queryset is None:
        if run_id is not None:
            return JsonResponse({'error': '未找到指定的 AI 初筛运行'}, status=404)
        return JsonResponse({'total': 0, 'reviewed': 0, 'unreviewed': 0})
    stats = aggregate_review_stats(queryset)
    run = queryset._screening_run
    stats.update({
        'storage_mode': 'database', 'screening_run_id': run.id,
        'corpus_revision': run.corpus_revision,
        'is_current': queryset._screening_is_current,
    })
    return JsonResponse(stats)


@login_required
@require_http_methods(['POST'])
def review_complete(request):
    data, error = _validated_json(request, ReviewCompleteInputSerializer)
    if error:
        return error
    step = _get_step(request.user, data['project'], data['step'])
    if not step:
        return JsonResponse({'error': '无权访问该项目或未找到 review 步骤'}, status=404)
    run = ScreeningRun.objects.select_related('corpus', 'dedup_run').filter(
        pk=data['screening_run'], project_id=data['project'],
        status=ScreeningRun.Status.COMPLETED,
    ).first()
    if run is None:
        return JsonResponse({'error': '未找到指定的 AI 初筛运行'}, status=404)
    if not screening_run_is_current(run):
        return JsonResponse({'error': {
            'code': 'screening_run_stale',
            'message': '该结果属于历史文献版本，不能标记完成。',
        }}, status=409)
    reviews = ManualReview.objects.filter(screening_run=run)
    stats = {
        'total': run.total_count, 'reviewed': reviews.count(),
        'included': reviews.filter(decision='included').count(),
        'excluded': reviews.filter(decision='excluded').count(),
        'pending': reviews.filter(decision='pending').count(),
        'screening_run_id': run.id, 'corpus_revision': run.corpus_revision,
        'completed_at': datetime.now().isoformat(),
    }
    from core.workflow.domain.statuses import StageStepStatus
    from core.workflow.services.lifecycle import transition_step
    transition_step(
        step, StageStepStatus.COMPLETED,
        updates={'metadata': {**(step.metadata or {}), **stats}},
    )
    ActivityLog.objects.create(
        project_id=data['project'], operation_type='review_complete',
        operation_detail={
            'screening_run_id': run.id, 'corpus_revision': run.corpus_revision,
            'stats': stats,
        },
        created_by=request.user,
    )
    return JsonResponse({'ok': True, 'stats': stats})
