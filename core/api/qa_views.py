"""
文献质量评价 API

接口列表（前缀 /api/qa/）：
  GET  /refs/                     → 获取项目文献列表
  POST /refs/import/              → 从初筛/复筛导入
  POST /refs/upload/              → 上传全文文件创建文献
  PATCH /refs/<id>/               → 更新单篇文献（方法选择等）
  POST /refs/batch-method/        → 批量设置方法
  GET  /methods/                  → 获取所有可用质量评价方法

  POST /eval/start/               → 启动 AI 质量评价任务
  GET  /eval/progress/            → 查询评价进度

  GET  /signal-items/             → 获取文献信号问题列表
  PATCH /signal-items/<id>/confirm/   → 确认单条信号问题
  POST /signal-items/batch-confirm/   → 一键批量确认

  GET  /domain-results/           → 获取领域汇总结果

  POST /chart/generate/           → 触发图表生成（前端渲染数据）
  GET  /chart/                    → 获取图表信息与数据
  POST /export/excel/             → 生成并下载 Excel
  GET  /export/status/            → 查询导出状态
"""

import io
import base64
import json
import logging
from datetime import datetime, timezone as dt_tz

import matplotlib
matplotlib.use('Agg')   # 非交互后端，避免 GUI 依赖
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone

from core.models import (
    Project, DataFile, QAReference, QASignalItem, QADomainResult, QAChart
)
from core.services.quality_methods import get_method_config, get_all_methods_meta, AI_SUPPORTED_METHODS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────────────────────

def _json_ok(data=None, status=200):
    return JsonResponse({'ok': True, 'data': data or {}}, status=status)


def _json_err(msg, status=400):
    return JsonResponse({'ok': False, 'error': msg}, status=status)


def _get_project(request, project_id):
    """获取项目，校验归属（权限从宽：任何登录用户可访问其参与项目）"""
    try:
        return Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return None


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


def _serialize_signal(item: QASignalItem) -> dict:
    return {
        'id':               item.id,
        'qa_ref_id':        item.qa_ref_id,
        'quality_method':   item.quality_method,
        'domain':           item.domain,
        'result_type':      item.result_type,
        'signal_key':       item.signal_key,
        'signal_question':  item.signal_question,
        'signal_description': item.signal_description,
        'options':          item.options,
        # 单模型
        'ai_judgment':      item.ai_judgment,
        'ai_reason':        item.ai_reason,
        'ai_evidence':      item.ai_evidence,
        'ai_evidence_page': item.ai_evidence_page,
        # 双模型
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


def _recalc_domain_results(qa_ref: QAReference):
    """
    根据已确认的信号问题，重新计算并更新 QADomainResult。
    规则（QUADAS-2 / NOS 通用）：
      - bias_risk: 任意一条 confirmed human_judgment 中有风险倾向 → high；
                   全部 low → low；否则 unclear；未全部确认 → pending
      - applicability: 同上逻辑
    """
    items = list(qa_ref.signal_items.all())
    method_cfg = None
    try:
        method_cfg = get_method_config(qa_ref.quality_method)
    except Exception:
        pass

    # 按 domain 分组
    domains = {}
    for item in items:
        domains.setdefault(item.domain, []).append(item)

    for domain_key, domain_items in domains.items():
        # 找领域名
        domain_name = domain_key
        if method_cfg:
            for d in method_cfg.get('domains', []):
                if d['key'] == domain_key:
                    domain_name = d['name']
                    break

        bias_items  = [i for i in domain_items if i.result_type == 'bias_risk']
        applic_items = [i for i in domain_items if i.result_type == 'applicability']

        def calc_result(signal_list):
            if not signal_list:
                return 'na', True
            confirmed = [i for i in signal_list if i.is_confirmed]
            if len(confirmed) < len(signal_list):
                return 'pending', False
            judgments = [i.human_judgment for i in confirmed]
            # QUADAS-2 bias: 有'否'→high；有'不清楚'→unclear；否则low
            # NOS: 有✗ → high, 有★★ or ★ → 计星，暂用简化逻辑
            if any(j in ('否', '✗') for j in judgments):
                return 'high', True
            if any(j in ('不清楚', '高') for j in judgments):
                return 'unclear', True
            return 'low', True

        bias_result, bias_confirmed = calc_result(bias_items)
        applic_result, applic_confirmed = calc_result(applic_items)

        QADomainResult.objects.update_or_create(
            qa_ref=qa_ref,
            domain=domain_key,
            defaults={
                'domain_name':                 domain_name,
                'bias_risk_result':            bias_result,
                'applicability_result':        applic_result,
                'bias_all_confirmed':          bias_confirmed,
                'applicability_all_confirmed': applic_confirmed,
            },
        )

    # 更新文献级 review_status
    all_items = list(qa_ref.signal_items.all())
    if all_items:
        confirmed_count = sum(1 for i in all_items if i.is_confirmed)
        if confirmed_count == 0:
            new_status = 'not_started'
        elif confirmed_count == len(all_items):
            new_status = 'confirmed'
        else:
            new_status = 'partial'
        QAReference.objects.filter(pk=qa_ref.pk).update(review_status=new_status)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/qa/methods/
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET'])
def methods_list(request):
    """返回所有可用质量评价方法"""
    metas = get_all_methods_meta()
    return _json_ok(metas)


# ─────────────────────────────────────────────────────────────────────────────
# 文献管理
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET'])
def ref_list(request):
    """GET /api/qa/refs/?project_id="""
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)
    refs = QAReference.objects.filter(project=project).select_related('fulltext_file')
    return _json_ok([_serialize_ref(r) for r in refs])


@csrf_exempt
@login_required
@require_http_methods(['POST'])
def ref_import(request):
    """POST /api/qa/refs/import/ — 从初筛/复筛导入已纳入文献"""
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    project_id  = body.get('project_id')
    source_stage = body.get('source_stage', 'SCREEN_1')   # SCREEN_1 or SCREEN_2
    ref_ids     = body.get('ref_ids', [])                  # 空 = 全部已纳入

    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    # 从 ManualReview 中取已纳入的文献（decision=included）
    from core.models import ManualReview
    qs = ManualReview.objects.filter(
        project=project,
        step__stage__stage_key=source_stage,
        decision='included',
    )
    if ref_ids:
        qs = qs.filter(id__in=ref_ids)

    imported = []
    skipped  = 0
    with transaction.atomic():
        for mr in qs:
            # 检查是否已导入过（以 source_ref_id 去重）
            if QAReference.objects.filter(project=project, source_ref_id=mr.id).exists():
                skipped += 1
                continue
            ref = QAReference.objects.create(
                project=project,
                title=mr.source_xml,    # 暂用 source_xml 作为标题，AI评价时再解析
                source_type='screening_import',
                source_ref_id=mr.id,
                fulltext_status='pending',
            )
            imported.append(ref.id)

    return _json_ok({'imported': len(imported), 'skipped': skipped, 'ref_ids': imported})


@csrf_exempt
@login_required
@require_http_methods(['POST'])
def ref_upload(request):
    """POST /api/qa/refs/upload/ — 上传全文 PDF，自动识别文献信息"""
    project_id = request.POST.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    files = request.FILES.getlist('files')
    if not files:
        return _json_err('未上传文件')

    created_refs = []
    for f in files:
        if not f.name.lower().endswith('.pdf'):
            continue
        # 保存文件
        data_file = DataFile.objects.create(
            project=project,
            filename=f.name,
            file=f,
            source='upload',
            data_category='input',
            description='质量评价全文PDF',
            created_by=request.user,
        )
        # 尝试从 PDF 解析基础信息（简化：仅用文件名作为标题）
        title = f.name.replace('.pdf', '').replace('_', ' ')
        ref = QAReference.objects.create(
            project=project,
            title=title,
            source_type='fulltext_upload',
            fulltext_file=data_file,
            fulltext_status='available',
        )
        # 异步触发 PDF 解析提取元数据（非阻塞）
        try:
            from core.tasks import parse_qa_pdf_meta
            parse_qa_pdf_meta.delay(ref.id)
        except Exception:
            pass  # Celery 未就绪时跳过，不影响上传
        created_refs.append(_serialize_ref(ref))

    return _json_ok({'created': len(created_refs), 'refs': created_refs}, status=201)


@csrf_exempt
@login_required
@require_http_methods(['PATCH'])
def ref_update(request, ref_id):
    """PATCH /api/qa/refs/<id>/ — 更新单篇文献（方法选择等）"""
    try:
        ref = QAReference.objects.get(pk=ref_id)
    except QAReference.DoesNotExist:
        return _json_err('文献不存在', 404)

    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    updatable = ['quality_method', 'eval_mode', 'selected_models', 'fulltext_status', 'title', 'first_author', 'year', 'journal']
    changed = False
    for field in updatable:
        if field in body:
            setattr(ref, field, body[field])
            changed = True

    # 绑定全文
    if 'fulltext_file_id' in body:
        try:
            df = DataFile.objects.get(pk=body['fulltext_file_id'], project=ref.project)
            ref.fulltext_file = df
            ref.fulltext_status = 'available'
            changed = True
        except DataFile.DoesNotExist:
            return _json_err('文件不存在或不属于该项目')

    if changed:
        ref.save()

    return _json_ok(_serialize_ref(ref))


@csrf_exempt
@login_required
@require_http_methods(['POST'])
def ref_batch_method(request):
    """POST /api/qa/refs/batch-method/ — 批量设置质量评价方法"""
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    ref_ids       = body.get('ref_ids', [])
    quality_method = body.get('quality_method', '')
    if not ref_ids or not quality_method:
        return _json_err('缺少 ref_ids 或 quality_method')

    updated = QAReference.objects.filter(pk__in=ref_ids).update(quality_method=quality_method)
    return _json_ok({'updated': updated})


# ─────────────────────────────────────────────────────────────────────────────
# AI 评价
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
@require_http_methods(['POST'])
def eval_start(request):
    """POST /api/qa/eval/start/ — 启动 AI 质量评价任务"""
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    project_id   = body.get('project_id')
    ref_ids      = body.get('ref_ids', [])      # 空 = 项目全部已选方法文献
    eval_mode    = body.get('eval_mode', 'single')   # single | dual
    model_ids    = body.get('model_ids', [])     # 选择的模型 ID 列表

    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    # 验证积分
    from core.services.billing_service import get_balance, estimate_credits
    balance = get_balance(request.user)
    # 先估算可评价文献数
    qs = QAReference.objects.filter(project=project)
    if ref_ids:
        qs = qs.filter(pk__in=ref_ids)
    qs = qs.filter(quality_method__in=AI_SUPPORTED_METHODS).exclude(quality_method='')
    evaluable_count = qs.count()

    if evaluable_count == 0:
        return _json_err('没有可评价的文献（请先为文献选择支持 AI 评价的质量评价方法）')

    estimated = estimate_credits(evaluable_count, model_ids)
    if balance < estimated:
        return _json_err(f'积分不足（当前 {balance}，需要约 {estimated}）')

    # 将被评价的 ref 更新为 running
    ref_ids_to_eval = list(qs.values_list('pk', flat=True))
    QAReference.objects.filter(pk__in=ref_ids_to_eval).update(
        ai_eval_status='running',
        eval_mode=eval_mode,
        selected_models=model_ids,
    )

    # 提交 Celery 任务
    try:
        from core.tasks import run_qa_ai_eval
        task = run_qa_ai_eval.delay(
            project_id=project.id,
            ref_ids=ref_ids_to_eval,
            eval_mode=eval_mode,
            model_ids=model_ids,
            user_id=request.user.id,
        )
        task_id = task.id
    except Exception as e:
        logger.warning(f'Celery 提交失败，降级同步执行: {e}')
        task_id = None

    return _json_ok({
        'task_id':        task_id,
        'evaluable_count': evaluable_count,
        'ref_ids':        ref_ids_to_eval,
        'estimated_credits': estimated,
    })


@login_required
@require_http_methods(['GET'])
def eval_progress(request):
    """GET /api/qa/eval/progress/?project_id="""
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    refs = QAReference.objects.filter(project=project)
    total       = refs.count()
    pending     = refs.filter(ai_eval_status='pending').count()
    running     = refs.filter(ai_eval_status='running').count()
    completed   = refs.filter(ai_eval_status='completed').count()
    failed      = refs.filter(ai_eval_status__in=['failed', 'skipped_no_fulltext', 'skipped_no_method']).count()
    abstract_only = refs.filter(ai_eval_status='abstract_only').count()

    # 双模型信号问题一致性统计
    divergent_count = QASignalItem.objects.filter(
        qa_ref__project=project,
        consistency='divergent',
    ).count()

    unconfirmed_count = QASignalItem.objects.filter(
        qa_ref__project=project,
        qa_ref__ai_eval_status__in=['completed', 'abstract_only'],
        is_confirmed=False,
    ).count()

    # 文献级进度列表
    ref_list_data = []
    for ref in refs.select_related('fulltext_file'):
        # 双模型分歧数
        div = QASignalItem.objects.filter(qa_ref=ref, consistency='divergent').count() if ref.eval_mode == 'dual' else 0
        ref_list_data.append({
            'id':             ref.id,
            'title':          ref.title,
            'quality_method': ref.quality_method,
            'eval_mode':      ref.eval_mode,
            'ai_eval_status': ref.ai_eval_status,
            'review_status':  ref.review_status,
            'divergent_count': div,
        })

    return _json_ok({
        'summary': {
            'total':        total,
            'pending':      pending,
            'running':      running,
            'completed':    completed + abstract_only,
            'failed':       failed,
            'abstract_only': abstract_only,
            'divergent_signal_count': divergent_count,
        },
        'refs': ref_list_data,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 信号问题
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET'])
def signal_items_list(request):
    """GET /api/qa/signal-items/?qa_ref_id=&domain=&result_type=&is_confirmed="""
    qa_ref_id = request.GET.get('qa_ref_id')
    if not qa_ref_id:
        return _json_err('缺少 qa_ref_id')
    try:
        ref = QAReference.objects.get(pk=qa_ref_id)
    except QAReference.DoesNotExist:
        return _json_err('文献不存在', 404)

    qs = ref.signal_items.select_related('confirmed_by').all()
    if request.GET.get('domain'):
        qs = qs.filter(domain=request.GET['domain'])
    if request.GET.get('result_type'):
        qs = qs.filter(result_type=request.GET['result_type'])
    if request.GET.get('is_confirmed') == 'false':
        qs = qs.filter(is_confirmed=False)
    elif request.GET.get('is_confirmed') == 'true':
        qs = qs.filter(is_confirmed=True)

    return _json_ok([_serialize_signal(i) for i in qs])


@csrf_exempt
@login_required
@require_http_methods(['PATCH'])
def signal_item_confirm(request, item_id):
    """PATCH /api/qa/signal-items/<id>/confirm/ — 确认单条信号问题"""
    try:
        item = QASignalItem.objects.select_related('qa_ref').get(pk=item_id)
    except QASignalItem.DoesNotExist:
        return _json_err('信号问题不存在', 404)
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    human_judgment = body.get('human_judgment', '').strip()
    if not human_judgment:
        return _json_err('缺少 human_judgment')

    with transaction.atomic():
        # 记录修改
        if item.ai_judgment and human_judgment != item.ai_judgment and not item.is_modified:
            item.is_modified = True
            item.original_ai_judgment = item.ai_judgment
        # 也兼容双模型推荐
        if item.system_recommendation and human_judgment != item.system_recommendation and not item.is_modified:
            item.is_modified = True
            item.original_ai_judgment = item.system_recommendation

        item.human_judgment = human_judgment
        item.is_confirmed  = True
        item.confirmed_by  = request.user
        item.confirmed_at  = timezone.now()
        item.save()

        # 重新聚合领域结果
        _recalc_domain_results(item.qa_ref)

    return _json_ok(_serialize_signal(item))


@csrf_exempt
@login_required
@require_http_methods(['POST'])
def signal_batch_confirm(request):
    """
    POST /api/qa/signal-items/batch-confirm/
    Body: {
      "qa_ref_id": 1,
      "confirm_mode": "adopt_preselected" | "adopt_ai" | "specific_keys",
      "signal_keys": [...],   # confirm_mode=specific_keys 时使用
    }
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    qa_ref_id    = body.get('qa_ref_id')
    confirm_mode = body.get('confirm_mode', 'adopt_preselected')
    signal_keys  = body.get('signal_keys', [])

    if not qa_ref_id:
        return _json_err('缺少 qa_ref_id')
    try:
        ref = QAReference.objects.get(pk=qa_ref_id)
    except QAReference.DoesNotExist:
        return _json_err('文献不存在', 404)

    items = ref.signal_items.all()
    if confirm_mode == 'specific_keys' and signal_keys:
        items = items.filter(signal_key__in=signal_keys)

    confirmed_count = 0
    now = timezone.now()
    with transaction.atomic():
        for item in items:
            if confirm_mode == 'adopt_preselected':
                if not item.pre_selected:
                    continue
                judgment = item.pre_selected
            elif confirm_mode == 'adopt_ai':
                if not item.ai_judgment:
                    continue
                judgment = item.ai_judgment
            else:
                # specific_keys: 使用 pre_selected 或 ai_judgment
                judgment = item.pre_selected or item.ai_judgment
                if not judgment:
                    continue

            if item.ai_judgment and judgment != item.ai_judgment and not item.is_modified:
                item.is_modified = True
                item.original_ai_judgment = item.ai_judgment

            item.human_judgment = judgment
            item.is_confirmed  = True
            item.confirmed_by  = request.user
            item.confirmed_at  = now
            item.save(update_fields=[
                'human_judgment', 'is_confirmed', 'confirmed_by', 'confirmed_at',
                'is_modified', 'original_ai_judgment',
            ])
            confirmed_count += 1

        # 重新聚合
        _recalc_domain_results(ref)

    return _json_ok({'confirmed': confirmed_count})


# ─────────────────────────────────────────────────────────────────────────────
# 领域汇总结果
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET'])
def domain_results(request):
    """GET /api/qa/domain-results/?qa_ref_id="""
    qa_ref_id = request.GET.get('qa_ref_id')
    if not qa_ref_id:
        return _json_err('缺少 qa_ref_id')
    qs = QADomainResult.objects.filter(qa_ref_id=qa_ref_id)
    return _json_ok([_serialize_domain(dr) for dr in qs])


# ─────────────────────────────────────────────────────────────────────────────
# 图表
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
@require_http_methods(['POST'])
def chart_generate(request):
    """
    POST /api/qa/chart/generate/
    返回前端渲染所需的图表数据结构（不生成文件，文件在 export 时生成）
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    project_id     = body.get('project_id')
    quality_method = body.get('quality_method', 'QUADAS2')
    ref_ids        = body.get('ref_ids', [])   # 空 = 全部已确认

    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    qs = QAReference.objects.filter(project=project, quality_method=quality_method)
    if ref_ids:
        qs = qs.filter(pk__in=ref_ids)

    # 获取方法配置
    try:
        method_cfg = get_method_config(quality_method)
    except Exception:
        return _json_err(f'不支持的质量评价方法: {quality_method}')

    domains = method_cfg['domains']
    bias_domains   = [d for d in domains if d['has_bias_risk']]
    applic_domains = [d for d in domains if d['has_applicability']]

    # 构建红绿灯图数据
    traffic_light_data = []
    for ref in qs:
        domain_map = {}
        for dr in ref.domain_results.all():
            domain_map[dr.domain] = dr

        row = {
            'ref_id':     ref.id,
            'title':      ref.title,
            'first_author': ref.first_author,
            'year':       ref.year,
            'review_status': ref.review_status,
            'bias_risk':    {},
            'applicability': {},
        }
        for d in bias_domains:
            dr = domain_map.get(d['key'])
            row['bias_risk'][d['key']] = dr.bias_risk_result if dr else 'pending'
        for d in applic_domains:
            dr = domain_map.get(d['key'])
            row['applicability'][d['key']] = dr.applicability_result if dr else 'pending'
        traffic_light_data.append(row)

    # 构建汇总比例数据
    proportion_data = {}
    for d in bias_domains + applic_domains:
        k = d['key']
        result_type = 'bias_risk' if d['has_bias_risk'] else 'applicability'
        # 统计领域级结果（仅已确认文献）
        confirmed_refs = [r for r in traffic_light_data if r['review_status'] == 'confirmed']
        counts = {'low': 0, 'high': 0, 'unclear': 0, 'pending': 0}
        for r in confirmed_refs:
            val = r['bias_risk'].get(k) or r['applicability'].get(k) or 'pending'
            if val in counts:
                counts[val] += 1
        total = max(1, len(confirmed_refs))
        proportion_data[k] = {
            'domain_name': d['name'],
            'result_type': 'bias_risk' if d['has_bias_risk'] else 'applicability',
            'counts': counts,
            'percentages': {k2: round(v / total * 100, 1) for k2, v in counts.items()},
        }

    # 保存/更新图表记录
    chart, _ = QAChart.objects.update_or_create(
        project=project,
        quality_method=quality_method,
        defaults={
            'chart_types': ['traffic_light', 'proportion', 'detail'],
            'ref_ids':     [r['ref_id'] for r in traffic_light_data],
            'generated_at': timezone.now(),
        },
    )

    # ── 生成图表图片（base64 PNG）────────────────────────────────────────────
    traffic_b64  = _render_traffic_light(traffic_light_data, bias_domains, applic_domains, method_cfg['name'])
    proportion_b64 = _render_proportion(proportion_data, method_cfg['name'])

    return _json_ok({
        'chart_id':          chart.id,
        'quality_method':    quality_method,
        'method_name':       method_cfg['name'],
        'bias_domains':      bias_domains,
        'applic_domains':    applic_domains,
        'traffic_light':     traffic_light_data,
        'proportion':        proportion_data,
        'generated_at':      chart.generated_at.isoformat(),
        'unconfirmed_count': sum(1 for r in traffic_light_data if r['review_status'] != 'confirmed'),
        'traffic_light_image':  traffic_b64,
        'proportion_image':     proportion_b64,
    })


# ── 图表绘制工具函数 ──────────────────────────────────────────────────────────

_RISK_COLORS = {
    'low':     '#059669',
    'high':    '#dc2626',
    'unclear': '#d97706',
    'pending': '#e2e8f0',
    'na':      '#94a3b8',
}
_RISK_MARKERS = {
    'low':     '✓',
    'high':    '✗',
    'unclear': '?',
    'pending': '○',
    'na':      '−',
}


def _fig_to_b64(fig) -> str:
    """将 matplotlib Figure 转为 data URL 格式的 base64 PNG。"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return 'data:image/png;base64,' + base64.b64encode(buf.read()).decode()


# macOS/Linux 中文字体优先顺序
_CJK_FONT_CANDIDATES = [
    'PingFang SC', 'PingFang HK', 'STHeiti', 'Heiti TC',
    'Hiragino Sans GB', 'WenQuanYi Micro Hei', 'SimHei', 'Microsoft YaHei',
]

def _setup_cjk_font():
    """检测并设置第一个可用的 CJK 字体，解决中文乱码。"""
    import matplotlib.font_manager as fm
    available = {f.name for f in fm.fontManager.ttflist}
    for name in _CJK_FONT_CANDIDATES:
        if name in available:
            plt.rcParams['font.family'] = name
            plt.rcParams['axes.unicode_minus'] = False
            return
    # 找不到则保留默认，仅关掉 unicode_minus 警告
    plt.rcParams['axes.unicode_minus'] = False


def _render_traffic_light(traffic_light_data, bias_domains, applic_domains, method_name) -> str:
    """生成交通灯图（Risk of Bias Summary），返回 base64 data URL。"""
    if not traffic_light_data:
        return None
    _setup_cjk_font()

    n_bias   = len(bias_domains)
    n_applic = len(applic_domains)
    all_domains = (
        [(d['key'], d['name'], 'bias')   for d in bias_domains]
      + [(d['key'], d['name'], 'applic') for d in applic_domains]
    )
    n_refs    = len(traffic_light_data)
    n_domains = len(all_domains)

    cell_w, cell_h = 0.9, 0.5
    label_w   = 3.5
    group_h   = 0.28   # 分组标题栏高度
    header_h  = 1.2    # 竖排列头高度
    legend_h  = 0.6
    top_pad   = 0.4
    bot_pad   = 0.2

    fig_w = label_w + n_domains * cell_w + 0.5
    fig_h = max(3.5, top_pad + group_h + 0.06 + header_h + n_refs * cell_h + legend_h + bot_pad)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis('off')

    # ── 主标题 ────────────────────────────────────────────────────────────────
    ax.text(fig_w / 2, fig_h - 0.15,
            f'Risk of Bias Summary — {method_name}',
            ha='center', va='top', fontsize=9, fontweight='bold', color='#1e293b')

    # ── 分组标题栏 ────────────────────────────────────────────────────────────
    group_top = fig_h - top_pad
    group_y   = group_top - group_h
    if n_bias > 0:
        bias_x = label_w
        bias_w = n_bias * cell_w
        ax.add_patch(mpatches.FancyBboxPatch(
            (bias_x, group_y), bias_w, group_h,
            boxstyle='round,pad=0.02', linewidth=0.8,
            facecolor='#eff6ff', edgecolor='#bfdbfe', zorder=1))
        ax.text(bias_x + bias_w / 2, group_y + group_h / 2,
                '偏倚风险  Risk of Bias',
                ha='center', va='center', fontsize=6.5,
                fontweight='bold', color='#1d4ed8', zorder=2)
    if n_applic > 0:
        applic_x = label_w + n_bias * cell_w + (0.06 if n_bias > 0 else 0)
        applic_w = n_applic * cell_w
        ax.add_patch(mpatches.FancyBboxPatch(
            (applic_x, group_y), applic_w, group_h,
            boxstyle='round,pad=0.02', linewidth=0.8,
            facecolor='#f0fdf4', edgecolor='#bbf7d0', zorder=1))
        ax.text(applic_x + applic_w / 2, group_y + group_h / 2,
                '适用性  Applicability',
                ha='center', va='center', fontsize=6.5,
                fontweight='bold', color='#15803d', zorder=2)

    # ── 竖排列头（从分组标题下沿向下悬挂，va='top'）────────────────────────────
    for ci, (dkey, dname, dtype) in enumerate(all_domains):
        x = label_w + ci * cell_w + cell_w / 2
        color = '#1d4ed8' if dtype == 'bias' else '#15803d'
        ax.text(x, group_y - 0.04, dname,
                ha='center', va='top', fontsize=6, color=color, rotation=90)

    # ── 数据行（列头区域下方）─────────────────────────────────────────────────
    data_top_y = group_y - header_h
    for ri, row in enumerate(traffic_light_data):
        y = data_top_y - ri * cell_h
        title = row.get('title') or f"文献 {row['ref_id']}"
        if len(title) > 35:
            title = title[:35] + '…'
        ax.text(label_w - 0.1, y + cell_h / 2, title,
                ha='right', va='center', fontsize=6, color='#475569')
        if ri % 2 == 0:
            rect = mpatches.FancyBboxPatch(
                (label_w, y), n_domains * cell_w, cell_h,
                boxstyle='square,pad=0', linewidth=0, facecolor='#f8fafc', zorder=0)
            ax.add_patch(rect)

        # 偏倚/适用性间竖线
        if n_bias > 0 and n_applic > 0:
            sep_x = label_w + n_bias * cell_w + 0.03
            ax.plot([sep_x, sep_x], [y, y + cell_h],
                    color='#e2e8f0', linewidth=0.8, zorder=1)

        for ci, (dkey, dname, dtype) in enumerate(all_domains):
            x = label_w + ci * cell_w
            result = (row['bias_risk'].get(dkey) if dtype == 'bias'
                      else row['applicability'].get(dkey)) or 'pending'
            color  = _RISK_COLORS.get(result, '#e2e8f0')
            marker = _RISK_MARKERS.get(result, '○')
            circle = plt.Circle(
                (x + cell_w / 2, y + cell_h / 2), radius=0.17,
                color=color, zorder=2)
            ax.add_patch(circle)
            ax.text(x + cell_w / 2, y + cell_h / 2, marker,
                    ha='center', va='center', fontsize=8,
                    color='white', fontweight='bold', zorder=3)

    # ── 图例 ──────────────────────────────────────────────────────────────────
    legend_items = [
        ('low', '低风险'), ('high', '高风险'),
        ('unclear', '不清楚'), ('na', '不适用'), ('pending', '待定'),
    ]
    lx = 0.3
    for key, label in legend_items:
        c = plt.Circle((lx, 0.25), 0.1, color=_RISK_COLORS[key], zorder=2)
        ax.add_patch(c)
        ax.text(lx + 0.18, 0.25, label, va='center', fontsize=6.5, color='#475569')
        lx += 1.2

    plt.tight_layout(pad=0.3)
    return _fig_to_b64(fig)


def _render_proportion(proportion_data, method_name) -> str:
    """生成比例图（Risk of Bias Graph），返回 base64 data URL。"""
    if not proportion_data:
        return None
    _setup_cjk_font()

    items = list(proportion_data.values())
    n = len(items)
    if n == 0:
        return None

    fig_w = 8
    fig_h = max(3.0, n * 0.65 + 1.8)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    y_pos  = np.arange(n)
    labels = [it['domain_name'] for it in items]

    risk_order  = ['low', 'high', 'unclear', 'pending']
    risk_labels_map = {'low': '低风险', 'high': '高风险', 'unclear': '不清楚', 'pending': '待定/不适用'}

    lefts   = np.zeros(n)
    handles = []
    for rk in risk_order:
        vals = np.array([it['percentages'].get(rk, 0) for it in items])
        bars = ax.barh(y_pos, vals, left=lefts, height=0.55,
                       color=_RISK_COLORS[rk], zorder=2)
        lefts += vals
        for bar, v in zip(bars, vals):
            if v >= 8:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2,
                        f'{v:.0f}%', ha='center', va='center',
                        fontsize=6.5, color='white', fontweight='bold')
        handles.append(mpatches.Patch(color=_RISK_COLORS[rk], label=risk_labels_map[rk]))

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel('百分比 (%)', fontsize=8)
    ax.set_title(f'Risk of Bias Graph — {method_name}',
                 fontsize=9, fontweight='bold', pad=8)
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(axis='x', labelsize=7)
    ax.legend(handles=handles, loc='lower right', fontsize=7,
              framealpha=0.9, ncol=len(risk_order))
    ax.grid(axis='x', linestyle='--', alpha=0.3, zorder=0)

    plt.tight_layout(pad=0.5)
    return _fig_to_b64(fig)


@login_required
@require_http_methods(['GET'])
def chart_info(request):
    project_id     = request.GET.get('project_id')
    quality_method = request.GET.get('quality_method', 'QUADAS2')
    if not project_id:
        return _json_err('缺少 project_id')
    try:
        chart = QAChart.objects.get(project_id=project_id, quality_method=quality_method)
    except QAChart.DoesNotExist:
        return _json_ok(None)   # 尚未生成
    return _json_ok({
        'id':             chart.id,
        'quality_method': chart.quality_method,
        'chart_types':    chart.chart_types,
        'ref_ids':        chart.ref_ids,
        'image_url':      chart.image_file.file.url if chart.image_file else None,
        'excel_url':      chart.excel_file.file.url if chart.excel_file else None,
        'generated_at':   chart.generated_at.isoformat() if chart.generated_at else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 导出
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
@require_http_methods(['POST'])
def export_excel(request):
    """POST /api/qa/export/excel/ — 生成并返回 Excel 文件"""
    try:
        body = json.loads(request.body)
    except Exception:
        return _json_err('请求体 JSON 格式错误')

    project_id     = body.get('project_id')
    quality_method = body.get('quality_method', 'QUADAS2')
    include_unconfirmed = body.get('include_unconfirmed', False)

    if not project_id:
        return _json_err('缺少 project_id')
    project = _get_project(request, project_id)
    if not project:
        return _json_err('项目不存在', 404)

    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment
    except ImportError:
        return _json_err('服务端缺少 openpyxl 依赖')

    refs = QAReference.objects.filter(project=project, quality_method=quality_method).prefetch_related('signal_items__confirmed_by', 'domain_results')

    wb = openpyxl.Workbook()

    # ── Sheet 1: 评价明细 ──────────────────────────────────
    ws = wb.active
    ws.title = '评价明细'
    headers = [
        '项目名称', '文献标题', '第一作者', '年份', '质量评价方法', '评价模式',
        '评价领域', '结果类型', '信号问题', '中文释义',
        '模型1判断', '模型1理由', '模型2判断', '模型2理由',
        '一致性状态', '系统推荐', 'AI判断', '判断理由',
        '人工最终判断', '是否人工修改', '确认人', '确认时间', '证据位置',
        '是否已确认',
    ]
    ws.append(headers)

    COLOR_MAP = {'low': 'C8F7C5', 'high': 'FFCDD2', 'unclear': 'FFF9C4', 'pending': 'F5F5F5'}

    for ref in refs:
        for item in ref.signal_items.all():
            if not include_unconfirmed and not item.is_confirmed:
                row_color = 'F5F5F5'
            else:
                row_color = None

            row = [
                project.name,
                ref.title,
                ref.first_author,
                ref.year,
                ref.quality_method,
                ref.get_eval_mode_display() if ref.eval_mode else '',
                item.domain,
                item.result_type,
                item.signal_question,
                item.signal_description,
                item.model1_judgment,
                item.model1_reason,
                item.model2_judgment,
                item.model2_reason,
                item.consistency,
                item.system_recommendation,
                item.ai_judgment,
                item.ai_reason,
                item.human_judgment,
                '是' if item.is_modified else '否',
                item.confirmed_by.username if item.confirmed_by else '',
                item.confirmed_at.strftime('%Y-%m-%d %H:%M') if item.confirmed_at else '',
                item.ai_evidence_page,
                '是' if item.is_confirmed else '否（未确认）',
            ]
            ws.append(row)
            if row_color:
                for cell in ws[ws.max_row]:
                    cell.fill = PatternFill(fill_type='solid', fgColor=row_color)

    # ── Sheet 2: 汇总统计 ──────────────────────────────────
    ws2 = wb.create_sheet('汇总统计')
    ws2.append(['文献标题', '第一作者', '年份', '患者选择_偏倚', '待评价试验_偏倚', '参考标准_偏倚', '流程与时间_偏倚',
                '患者选择_适用', '待评价试验_适用', '参考标准_适用', '整体审阅状态'])
    for ref in refs:
        dr_map = {dr.domain: dr for dr in ref.domain_results.all()}
        ps  = dr_map.get('patient_selection')
        it  = dr_map.get('index_test')
        rs  = dr_map.get('reference_standard')
        ft  = dr_map.get('flow_timing')
        ws2.append([
            ref.title, ref.first_author, ref.year,
            ps.bias_risk_result if ps else '',
            it.bias_risk_result if it else '',
            rs.bias_risk_result if rs else '',
            ft.bias_risk_result if ft else '',
            ps.applicability_result if ps else '',
            it.applicability_result if it else '',
            rs.applicability_result if rs else '',
            ref.review_status,
        ])

    # ── Sheet 3: 证据记录 ──────────────────────────────────
    ws3 = wb.create_sheet('证据记录')
    ws3.append(['文献标题', '信号问题', 'AI判断', '判断理由', '证据原文', '证据位置', '人工修改前', '人工最终判断', '是否修改'])
    for ref in refs:
        for item in ref.signal_items.filter(ai_evidence__gt=''):
            ws3.append([
                ref.title, item.signal_question,
                item.ai_judgment, item.ai_reason,
                item.ai_evidence, item.ai_evidence_page,
                item.original_ai_judgment, item.human_judgment,
                '是' if item.is_modified else '否',
            ])

    # ── Sheet 4: 双模型校验记录 ────────────────────────────
    ws4 = wb.create_sheet('双模型校验记录')
    ws4.append(['文献标题', '信号问题', '模型1 ID', '模型1判断', '模型1理由', '模型2 ID', '模型2判断', '模型2理由', '一致性', '系统推荐', '人工最终判断'])
    for ref in refs.filter(eval_mode='dual'):
        for item in ref.signal_items.all():
            ws4.append([
                ref.title, item.signal_question,
                item.model1_id, item.model1_judgment, item.model1_reason,
                item.model2_id, item.model2_judgment, item.model2_reason,
                item.consistency, item.system_recommendation, item.human_judgment,
            ])

    # 返回文件流
    import io
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f'qa_export_{project.name}_{quality_method}_{datetime.now().strftime("%Y%m%d%H%M%S")}.xlsx'
    resp = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@login_required
@require_http_methods(['GET'])
def export_status(request):
    """GET /api/qa/export/status/?project_id="""
    project_id = request.GET.get('project_id')
    if not project_id:
        return _json_err('缺少 project_id')
    try:
        chart = QAChart.objects.filter(project_id=project_id).order_by('-created_at').first()
    except Exception:
        return _json_ok({'has_chart': False})

    if not chart:
        return _json_ok({'has_chart': False})

    return _json_ok({
        'has_chart':    True,
        'chart_id':     chart.id,
        'image_url':    chart.image_file.file.url if chart.image_file else None,
        'excel_url':    chart.excel_file.file.url if chart.excel_file else None,
        'generated_at': chart.generated_at.isoformat() if chart.generated_at else None,
    })
