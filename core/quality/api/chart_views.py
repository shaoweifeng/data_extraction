"""QA 图表预览、异步生成和设置 HTTP 适配层。"""

import logging

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from core.artifacts.types import ArtifactType
from core.models import DataFile, QAChart, QAChartSettings, QAReference, Task
from core.quality.api.common import _get_project, _json_err, _json_ok, _validated_json
from core.quality.api.serializers import (
    QAChartGenerateInputSerializer, QAChartRequestSerializer, QAChartSettingsInputSerializer,
)


logger = logging.getLogger(__name__)


from core.quality.services.chart_data import build_chart_data as _build_chart_data
@login_required
@require_http_methods(['POST'])
def chart_preview(request):
    """
    POST /api/qa/chart/preview/
    快速返回前端渲染所需的数据结构，不生成 PNG 图片。
    用于页面加载时的实时预览，用户编辑文献名后点「生成图片」才真正渲染 PNG。
    """
    body, error = _validated_json(request, QAChartRequestSerializer)
    if error:
        return error
    project_id = body['project_id']
    quality_method = body['quality_method']
    ref_ids = list(dict.fromkeys(body['ref_ids']))
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    if ref_ids and QAReference.objects.filter(project=project, pk__in=ref_ids).count() != len(ref_ids):
        return _json_err('部分文献不存在或不属于该项目', 404)

    try:
        tl, prop, bias_d, applic_d, method_cfg = _build_chart_data(project, quality_method, ref_ids or None)
    except Exception as e:
        return _json_err(f'数据构建失败: {e}')

    return _json_ok({
        'quality_method':    quality_method,
        'method_name':       method_cfg['name'],
        'bias_domains':      bias_d,
        'applic_domains':    applic_d,
        'traffic_light':     tl,
        'proportion':        prop,
        'generated_at':      None,
        'unconfirmed_count': sum(1 for r in tl if r['review_status'] != 'confirmed'),
    })


@login_required
@require_http_methods(['POST'])
def chart_generate(request):
    """POST /api/qa/chart/generate/ — 创建统一的异步 QA 图表任务。"""
    body, error = _validated_json(request, QAChartGenerateInputSerializer)
    if error:
        return error

    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    ref_ids = list(dict.fromkeys(body['ref_ids']))
    if ref_ids and QAReference.objects.filter(project=project, pk__in=ref_ids).count() != len(ref_ids):
        return _json_err('部分文献不存在或不属于该项目', 404)

    from core.scheduler import TaskScheduler

    try:
        task = TaskScheduler(project.id).start_step(
            'qa_chart',
            request.user.id,
            quality_method=body['quality_method'],
            ref_ids=ref_ids,
            study_labels=body['study_labels'],
            orientation=body['orientation'],
            lang=body['lang'],
        )
    except Exception as exc:
        logger.exception('创建 QA 图表任务失败')
        return _json_err(f'图表任务创建失败: {exc}', 500)

    return _json_ok({'task_id': task.id, 'status': task.status}, status=202)


@login_required
@require_http_methods(['GET'])
def chart_settings_get(request):
    """GET /api/qa/chart/settings/?project_id=&quality_method="""
    project_id     = request.GET.get('project_id')
    quality_method = request.GET.get('quality_method', '')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    obj = QAChartSettings.objects.filter(project=project, quality_method=quality_method).first()
    return _json_ok({
        'study_labels': obj.study_labels if obj else {},
        'updated_at':   obj.updated_at.isoformat() if obj else None,
    })


@login_required
@require_http_methods(['PATCH'])
def chart_settings_save(request):
    """PATCH /api/qa/chart/settings/ — 保存/合并 study_labels"""
    body, error = _validated_json(request, QAChartSettingsInputSerializer)
    if error:
        return error
    project_id = body['project_id']
    quality_method = body['quality_method']
    study_labels = body['study_labels']

    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    obj, created = QAChartSettings.objects.get_or_create(
        project=project,
        quality_method=quality_method,
        defaults={'study_labels': study_labels},
    )
    if not created:
        # 合并：只更新前端传来的 key，不覆盖未传的 key
        merged = {**obj.study_labels, **study_labels}
        obj.study_labels = merged
        obj.save(update_fields=['study_labels', 'updated_at'])

    return _json_ok({
        'study_labels': obj.study_labels,
        'updated_at':   obj.updated_at.isoformat(),
    })


@login_required
@require_http_methods(['GET'])
def chart_info(request):
    project_id     = request.GET.get('project_id')
    quality_method = request.GET.get('quality_method', 'QUADAS2')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    chart = QAChart.objects.filter(
        project=project, quality_method=quality_method
    ).order_by('-created_at').first()
    if chart is None:
        return _json_ok(None)   # 尚未生成
    artifacts = DataFile.objects.filter(
        project=project,
        step__step_key='qa_chart',
        metadata__quality_method=quality_method,
    ).order_by('-created_at')
    traffic_file = artifacts.filter(metadata__artifact_type=ArtifactType.QA_TRAFFIC_LIGHT_PNG).first()
    proportion_file = artifacts.filter(metadata__artifact_type=ArtifactType.QA_PROPORTION_PNG).first()
    latest_task = Task.objects.filter(
        project=project, task_type='qa_chart'
    ).order_by('-created_at').first()
    return _json_ok({
        'id':             chart.id,
        'quality_method': chart.quality_method,
        'chart_types':    chart.chart_types,
        'ref_ids':        chart.ref_ids,
        'image_url':      traffic_file.file.url if traffic_file else None,
        'traffic_light_image': traffic_file.file.url if traffic_file else None,
        'proportion_image': proportion_file.file.url if proportion_file else None,
        'excel_url':      chart.excel_file.file.url if chart.excel_file else None,
        'generated_at':   chart.generated_at.isoformat() if chart.generated_at else None,
        'task_id':        latest_task.id if latest_task else None,
        'task_status':    latest_task.status if latest_task else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 导出
# ─────────────────────────────────────────────────────────────────────────────
