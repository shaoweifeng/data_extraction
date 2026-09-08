"""质量评价 API 的共享 HTTP 适配辅助。"""

import json

from django.http import JsonResponse

from core.models import QAReference, QASignalItem, QADomainResult
from core.services.access_policy import ProjectAccessPolicy


def _json_ok(data=None, status=200):
    return JsonResponse({'ok': True, 'data': {} if data is None else data}, status=status)


def _json_err(msg, status=400):
    return JsonResponse({'ok': False, 'error': msg}, status=status)


def _get_project(request, project_id):
    """获取当前用户可访问的项目。"""
    return ProjectAccessPolicy.get_project(request.user, project_id)


def _visible_qa_refs(request):
    return QAReference.objects.filter(
        project__in=ProjectAccessPolicy.visible_projects(request.user)
    )


def _get_qa_ref(request, ref_id):
    return _visible_qa_refs(request).filter(pk=ref_id).first()


def _get_signal_item(request, item_id):
    return QASignalItem.objects.select_related('qa_ref', 'qa_ref__project').filter(
        qa_ref__project__in=ProjectAccessPolicy.visible_projects(request.user),
        pk=item_id,
    ).first()


def _validated_json(request, serializer_class):
    try:
        body = json.loads(request.body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, _json_err('请求体 JSON 格式错误')
    serializer = serializer_class(data=body)
    if not serializer.is_valid():
        return None, _json_err(_format_validation_errors(serializer.errors))
    return serializer.validated_data, None


def _format_validation_errors(errors):
    """将 DRF 的字段错误树统一转成可直接展示的字符串。"""
    messages = []

    def collect(value, path=''):
        if isinstance(value, dict):
            for key, detail in value.items():
                next_path = path if key == 'non_field_errors' else '.'.join(filter(None, [path, str(key)]))
                collect(detail, next_path)
        elif isinstance(value, (list, tuple)):
            for detail in value:
                collect(detail, path)
        else:
            text = str(value)
            messages.append(f'{path}: {text}' if path else text)

    collect(errors)
    return '；'.join(messages) or '请求参数错误'


def _serialize_ref(ref: QAReference) -> dict:
    return {
        'id':             ref.id,
        'title':          ref.title,
        'first_author':   ref.first_author,
        'year':           ref.year,
        'journal':        ref.journal,
        'abstract':       ref.abstract,
        'doi':            ref.doi,
        'source_type':    ref.source_type,
        'fulltext_status':ref.fulltext_status,
        'fulltext_file_id': ref.fulltext_file_id,
        'fulltext_url':   ref.fulltext_file.file.url if ref.fulltext_file else None,
        'quality_method': ref.quality_method,
        'eval_mode':      ref.eval_mode,
        'selected_models':ref.selected_models,
        'ai_eval_status': ref.ai_eval_status,
        'review_status':  ref.review_status,
        'created_at':     ref.created_at.isoformat(),
        'updated_at':     ref.updated_at.isoformat(),
    }


def _safe_int(val):
    """将字符串安全转换为 int，失败返回 None。"""
    try:
        return int(val) if val else None
    except (ValueError, TypeError):
        return None


def _safe_list(val) -> list:
    """确保 options 字段始终返回 list，兼容历史数据中意外存成字符串的情况。"""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            return [val] if val else []
    return []


_DOMAIN_NAME_MAP = {
    'patient_selection':  '患者选择',
    'index_test':         '待评价试验',
    'reference_standard': '参考标准',
    'flow_timing':        '流程与时间',
    'bias_risk':          '偏倚风险',
    'applicability':      '适用性',
}

def _serialize_signal(item: QASignalItem) -> dict:
    return {
        'id':               item.id,
        'qa_ref_id':        item.qa_ref_id,
        'quality_method':   item.quality_method,
        'domain':           item.domain,
        'domain_name':      _DOMAIN_NAME_MAP.get(item.domain, item.domain),
        'result_type':      item.result_type,
        'signal_key':       item.signal_key,
        'signal_question':  item.signal_question,
        'signal_description': item.signal_description,
        'options':          _safe_list(item.options),
        # 汇总字段
        'ai_judgment':      item.ai_judgment,
        'ai_reason':        item.ai_reason,
        'ai_evidence':      item.ai_evidence,
        'ai_evidence_page': item.ai_evidence_page,
        # N 模型原始结果列表
        'model_results':    item.model_results or [],
        # 向后兼容双模型字段
        'model1_id':        item.model1_id,
        'model1_judgment':  item.model1_judgment,
        'model1_reason':    item.model1_reason,
        'model2_id':        item.model2_id,
        'model2_judgment':  item.model2_judgment,
        'model2_reason':    item.model2_reason,
        'consistency':      item.consistency,
        'system_recommendation': item.system_recommendation,
        'pre_selected':     item.pre_selected,
        # 人工确认
        'human_judgment':   item.human_judgment,
        'is_modified':      item.is_modified,
        'original_ai_judgment': item.original_ai_judgment,
        'is_confirmed':     item.is_confirmed,
        'confirmed_by':     item.confirmed_by.username if item.confirmed_by else None,
        'confirmed_at':     item.confirmed_at.isoformat() if item.confirmed_at else None,
    }


def _serialize_domain(dr: QADomainResult) -> dict:
    return {
        'id':                          dr.id,
        'qa_ref_id':                   dr.qa_ref_id,
        'domain':                      dr.domain,
        'domain_name':                 dr.domain_name,
        'bias_risk_result':            dr.bias_risk_result,
        'applicability_result':        dr.applicability_result,
        'bias_all_confirmed':          dr.bias_all_confirmed,
        'applicability_all_confirmed': dr.applicability_all_confirmed,
    }


from core.quality.services.domain_results import (
    recalculate_domain_results as _recalc_domain_results,
)
# ─────────────────────────────────────────────────────────────────────────────
# GET /api/qa/methods/
# ─────────────────────────────────────────────────────────────────────────────
