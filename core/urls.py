from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api
from .api.billing_views import (
    balance as billing_balance,
    estimate as billing_estimate,
    redeem as billing_redeem,
    transactions as billing_transactions,
)
from .screening.api.review_views import (
    review_list,
    review_submit,
    review_stats,
    review_complete,
    review_reference_item,
    review_reference_notes,
)
from .screening.api.dedup_views import dedup_group_members, dedup_groups
from .quality.api.reference_views import (
    fulltext_download, fulltext_retry, methods_list, ref_list, ref_import, ref_upload, ref_update,
    ref_batch_method,
)
from .quality.api.evaluation_views import eval_start, eval_progress
from .quality.api.review_views import (
    domain_results, evaluation_audit, project_batch_confirm, signal_batch_confirm,
    signal_evidence_context, signal_item_confirm, signal_items_list,
)
from .quality.api.chart_views import chart_generate, chart_preview, chart_info, chart_settings_get, chart_settings_save
from .quality.api.export_views import export_excel, export_status
from .api.schema_views import openapi_schema
from .operations.api_views import (
    health_live, health_ready, operations_announcement, operations_pause_tasks,
    operations_resume_tasks, operations_state, operations_status, presence_heartbeat,
    system_status,
)

# 注册 ViewSets
router = DefaultRouter()
router.register(r'projects', api.ProjectViewSet, basename='project')
router.register(r'stages', api.ProjectStageViewSet, basename='stage')
router.register(r'steps', api.StageStepViewSet, basename='step')
router.register(r'files', api.DataFileViewSet, basename='file')
router.register(r'tasks', api.TaskViewSet, basename='task')
router.register(r'users', api.UserViewSet, basename='user')
router.register(r'activity-logs', api.ActivityLogViewSet, basename='activity-log')
router.register(r'screening-imports', api.ScreeningImportViewSet, basename='screening-import')

urlpatterns = [
    path('health/live/', health_live, name='health_live'),
    path('health/ready/', health_ready, name='health_ready'),
    path('system/status/', system_status, name='system_status'),
    path('presence/heartbeat/', presence_heartbeat, name='presence_heartbeat'),
    path('operations/status/', operations_status, name='operations_status'),
    path('operations/state/', operations_state, name='operations_state'),
    path('operations/announcement/', operations_announcement, name='operations_announcement'),
    path('operations/tasks/pause/', operations_pause_tasks, name='operations_pause_tasks'),
    path('operations/tasks/resume/', operations_resume_tasks, name='operations_resume_tasks'),
    # 机器可读 API 契约
    path('schema/', openapi_schema, name='openapi_schema'),
    # 认证 API；注册领域由 core.account 独立维护
    path('auth/', include('core.account.urls')),
    path('auth/logout/', api.logout_view, name='logout'),
    path('auth/me/', api.current_user, name='current_user'),
    path('ai-models/', api.ai_models_list, name='ai_models_list'),

    # 计费 API
    path('billing/balance/',      billing_balance,      name='billing_balance'),
    path('billing/estimate/',     billing_estimate,     name='billing_estimate'),
    path('billing/redeem/',       billing_redeem,       name='billing_redeem'),
    path('billing/transactions/', billing_transactions, name='billing_transactions'),

    # 用户反馈
    path('feedback/', include('core.feedback.urls')),

    # 外部系统图片接收（独立 Bearer API Key，不使用网页登录会话）
    path('external/images/', include('core.external_images.urls')),

    # 人工审阅 API
    path('review/list/',          review_list,    name='review_list'),
    path('review/submit/',        review_submit,  name='review_submit'),
    path('review/stats/',         review_stats,   name='review_stats'),
    path('review/complete/',      review_complete, name='review_complete'),
    path(
        'review/runs/<int:run_id>/references/<int:reference_id>/',
        review_reference_item,
        name='review_reference_item',
    ),
    path(
        'review/runs/<int:run_id>/references/<int:reference_id>/notes/',
        review_reference_notes,
        name='review_reference_notes',
    ),

    # 数据库化去重详情（组与成员均有固定上限的服务端分页）
    path(
        'projects/<int:project_id>/dedup-runs/<int:run_id>/groups/',
        dedup_groups,
        name='dedup_groups',
    ),
    path(
        'projects/<int:project_id>/dedup-runs/<int:run_id>/groups/<int:group_id>/members/',
        dedup_group_members,
        name='dedup_group_members',
    ),

    # RESTful API
    path('', include(router.urls)),

    # ── 文献质量评价 API ───────────────────────────────────────────────
    path('qa/methods/',                        methods_list,          name='qa_methods_list'),
    # 文献
    path('qa/refs/',                           ref_list,              name='qa_ref_list'),
    path('qa/refs/import/',                    ref_import,            name='qa_ref_import'),
    path('qa/refs/upload/',                    ref_upload,            name='qa_ref_upload'),
    path('qa/refs/batch-method/',              ref_batch_method,      name='qa_ref_batch_method'),
    path('qa/refs/<int:ref_id>/',              ref_update,            name='qa_ref_update'),
    path('qa/fulltext-assets/<int:asset_id>/download/', fulltext_download, name='qa_fulltext_download'),
    path('qa/fulltext-assets/<int:asset_id>/retry/', fulltext_retry, name='qa_fulltext_retry'),
    # AI 评价
    path('qa/eval/start/',                     eval_start,            name='qa_eval_start'),
    path('qa/eval/progress/',                  eval_progress,         name='qa_eval_progress'),
    # 信号问题
    path('qa/signal-items/',                   signal_items_list,     name='qa_signal_items_list'),
    path('qa/signal-items/<int:item_id>/confirm/', signal_item_confirm, name='qa_signal_item_confirm'),
    path('qa/signal-items/<int:item_id>/evidence-context/', signal_evidence_context, name='qa_signal_evidence_context'),
    path('qa/signal-items/batch-confirm/',     signal_batch_confirm,  name='qa_signal_batch_confirm'),
    path('qa/review/batch-confirm/',           project_batch_confirm, name='qa_project_batch_confirm'),
    path('qa/eval/audit/',                     evaluation_audit,      name='qa_evaluation_audit'),
    # 领域结果
    path('qa/domain-results/',                 domain_results,        name='qa_domain_results'),
    # 图表
    path('qa/chart/',                          chart_info,            name='qa_chart_info'),
    path('qa/chart/preview/',                  chart_preview,         name='qa_chart_preview'),
    path('qa/chart/generate/',                 chart_generate,        name='qa_chart_generate'),
    path('qa/chart/settings/',                 chart_settings_get,    name='qa_chart_settings_get'),
    path('qa/chart/settings/save/',            chart_settings_save,   name='qa_chart_settings_save'),
    # 导出
    path('qa/export/excel/',                   export_excel,          name='qa_export_excel'),
    path('qa/export/status/',                  export_status,         name='qa_export_status'),
]
