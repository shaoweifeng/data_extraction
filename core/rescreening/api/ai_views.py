"""Authenticated, bounded run APIs; prompts and usage audits are role-restricted."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.rescreening.api.common import boundary, integer, paginated, project_for
from core.rescreening.api.import_views import _key, _accepting_work
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenRun, RescreenRunItem
from core.rescreening.services.ai_runs import prepare, start_run, retry_run, run_stats, finish_task
from core.services.access_policy import ProjectAccessPolicy


def _run(request, run_id):
    run = RescreenRun.objects.select_related('corpus__project', 'criteria_revision', 'task').get(pk=run_id)
    ProjectAccessPolicy.require_project(request.user, run.corpus.project_id)
    return run


def _payload(run, user):
    data = {key: getattr(run, key) for key in ('id', 'task_id', 'status', 'input_revision',
        'model_ids', 'total_count', 'processed_count', 'created_at', 'finished_at')}
    data.update(project_id=run.corpus.project_id, criteria_revision=run.criteria_revision.revision,
        counts=run_stats(run), needs_unknown_ack=run.status in ('failed', 'partial', 'paused', 'cancelled')
        and run.items.filter(model_results__calls__status__in=('calling', 'unknown')).exists())
    if ProjectAccessPolicy.can_view_research_diagnostics(user):
        data.update(error_code=run.error_code, prompt_version=run.prompt_version, pricing_version=run.pricing_version)
    return data


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def estimate(request):
    project = project_for(request)
    from core.rescreening.services.ai_runs import _permission
    _permission(project, request.user)
    prepared = prepare(project, request.data.get('ids'), request.data.get('criteria'), request.data.get('model_ids'))
    return Response({'ok': True, 'data': {**prepared['estimate'], 'input_revision': prepared['corpus'].revision}})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def start(request):
    _accepting_work()
    run = start_run(project=project_for(request), user=request.user, ids=request.data.get('ids'),
        criteria=request.data.get('criteria'), model_ids=request.data.get('model_ids'),
        expected_revision=integer(request.data.get('expected_revision'), 'expected_revision', minimum=0),
        expected_settings_version=integer(request.data['expected_settings_version'], 'expected_settings_version', minimum=0)
            if request.data.get('expected_settings_version') is not None else None,
        idempotency_key=_key(request))
    return Response({'ok': True, 'data': _payload(run, request.user)}, status=202)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def runs(request):
    queryset = RescreenRun.objects.filter(corpus__project=project_for(request)).select_related('corpus', 'criteria_revision')
    return Response({'ok': True, 'data': paginated(queryset.order_by('-pk'), request, lambda row: _payload(row, request.user))})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def detail(request, run_id):
    run = _run(request, run_id)
    return Response({'ok': True, 'data': {**_payload(run, request.user), 'criteria': run.criteria_revision.criteria}})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def items(request, run_id):
    run = _run(request, run_id)
    queryset = run.items.select_related('reference').order_by('pk')
    status = request.query_params.get('status')
    if status:
        queryset = queryset.filter(status=status)
    q = request.query_params.get('q', '').strip()
    if len(q) > 200:
        raise RescreenError('invalid_query', '搜索文本过长。')
    if q:
        queryset = queryset.filter(reference__title__icontains=q)
    return Response({'ok': True, 'data': paginated(queryset, request, lambda row: {
        'id': row.pk, 'reference_id': row.reference_id, 'title': row.bibliography_snapshot.get('title', ''),
        'input_version': row.input_version, 'status': row.status, 'consensus': row.consensus,
    })})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def item_detail(request, item_id):
    item = RescreenRunItem.objects.select_related('run__corpus').get(pk=item_id)
    ProjectAccessPolicy.require_project(request.user, item.run.corpus.project_id)
    diagnostics = ProjectAccessPolicy.can_view_research_diagnostics(request.user)
    models = []
    for result in item.model_results.order_by('pk'):
        row = {key: getattr(result, key) for key in ('id', 'model_id', 'status', 'decision', 'reason', 'evidence', 'criteria_results')}
        if diagnostics:
            row.update(error_code=result.error_code, error_message=result.error_message, usage=result.usage)
        elif result.status == 'failed':
            row['error'] = '模型评价未完成，请重试或联系管理员。'
        models.append(row)
    package = item.evidence_package
    coverage = {key: package.get(key) for key in ('strategy', 'source_complete', 'total_spans', 'selected_spans')}
    return Response({'ok': True, 'data': {'id': item.pk, 'run_id': item.run_id, 'reference_id': item.reference_id,
        'pdf_url': f'/api/fulltext/assets/{item.asset_id}/download/' if item.asset_id else None,
        'bibliography': item.bibliography_snapshot, 'status': item.status, 'consensus': item.consensus,
        'coverage': coverage, 'models': models}})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def cancel(request, run_id):
    run = _run(request, run_id)
    from core.rescreening.services.ai_runs import _permission
    _permission(run.corpus.project, request.user)
    from core.scheduler import TaskScheduler
    if run.task_id:
        TaskScheduler(run.corpus.project_id).stop_task(run.task_id)
    run.refresh_from_db()
    return Response({'ok': True, 'data': _payload(run, request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def retry(request, run_id):
    _accepting_work()
    _run(request, run_id)
    ack = request.data.get('acknowledge_unknown', False)
    if not isinstance(ack, bool):
        raise RescreenError('invalid_parameter', 'acknowledge_unknown 必须为布尔值。')
    run = retry_run(run_id=run_id, user=request.user, acknowledge_unknown=ack)
    return Response({'ok': True, 'data': _payload(run, request.user)}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@boundary
def settle(request, run_id):
    run = _run(request, run_id)
    if run.status != 'settlement_pending' or run.task.status in ('pending', 'running', 'queuing', 'stopping'):
        raise RescreenError('not_recoverable', '只有已结束任务的计费故障可以重试结算。', status=409)
    finish_task(run.task)
    run.refresh_from_db()
    return Response({'ok': True, 'data': _payload(run, request.user)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@boundary
def prompt(request):
    project_for(request)
    if not ProjectAccessPolicy.can_view_research_diagnostics(request.user):
        raise RescreenError('permission_denied', '无权查看 Prompt 配置。', status=403)
    from core.rescreening.services.ai_protocol import PROMPT, PROTOCOL_VERSION
    return Response({'ok': True, 'data': {'prompt': PROMPT, 'version': PROTOCOL_VERSION}})
