"""QA Excel 导出 HTTP 适配层。"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods

from core.models import QAChart
from core.quality.api.common import _get_project, _json_err, _json_ok, _validated_json
from core.quality.api.serializers import QAExportInputSerializer


@login_required
@require_http_methods(['POST'])
def export_excel(request):
    """POST /api/qa/export/excel/ — 生成并返回 Excel 文件。"""
    body, error = _validated_json(request, QAExportInputSerializer)
    if error:
        return error
    project = _get_project(request, body['project_id'])
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)

    from core.models import ActivityLog
    from core.quality.exporters.excel import export_qa_excel

    filename, content = export_qa_excel(
        project,
        body['quality_method'],
        body['include_unconfirmed'],
    )
    response = HttpResponse(
        content,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    ActivityLog.objects.create(
        project=project,
        operation_type='qa_export_excel',
        operation_detail={
            'quality_method': body['quality_method'],
            'include_unconfirmed': body['include_unconfirmed'],
            'filename': filename,
        },
        created_by=request.user,
    )
    return response


@login_required
@require_http_methods(['GET'])
def export_status(request):
    """GET /api/qa/export/status/?project_id="""
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('无权访问该项目或项目不存在', 404)
    chart = QAChart.objects.filter(project=project).order_by('-created_at').first()

    if not chart:
        return _json_ok({'has_chart': False})

    return _json_ok({
        'has_chart':    True,
        'chart_id':     chart.id,
        'image_url':    chart.image_file.file.url if chart.image_file else None,
        'excel_url':    chart.excel_file.file.url if chart.excel_file else None,
        'generated_at': chart.generated_at.isoformat() if chart.generated_at else None,
    })
