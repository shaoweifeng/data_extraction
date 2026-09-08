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
    review_item,
    review_stats,
    review_complete,
    review_note_append,
    review_notes_list,
)
from .quality.api.reference_views import methods_list, ref_list, ref_import, ref_upload, ref_update, ref_batch_method
from .quality.api.evaluation_views import eval_start, eval_progress
from .quality.api.review_views import signal_items_list, signal_item_confirm, signal_batch_confirm, domain_results
from .quality.api.chart_views import chart_generate, chart_preview, chart_info, chart_settings_get, chart_settings_save
from .quality.api.export_views import export_excel, export_status
from .api.schema_views import openapi_schema

# 注册 ViewSets
router = DefaultRouter()
router.register(r'projects', api.ProjectViewSet, basename='project')
router.register(r'stages', api.ProjectStageViewSet, basename='stage')
router.register(r'steps', api.StageStepViewSet, basename='step')
router.register(r'files', api.DataFileViewSet, basename='file')
router.register(r'tasks', api.TaskViewSet, basename='task')
router.register(r'users', api.UserViewSet, basename='user')
router.register(r'activity-logs', api.ActivityLogViewSet, basename='activity-log')

urlpatterns = [
    # 机器可读 API 契约
    path('schema/', openapi_schema, name='openapi_schema'),
    # 认证 API
    path('auth/register/', api.register, name='register'),
    path('auth/login/', api.login_view, name='login'),
    path('auth/logout/', api.logout_view, name='logout'),
    path('auth/me/', api.current_user, name='current_user'),
    path('ai-models/', api.ai_models_list, name='ai_models_list'),

    # 计费 API
    path('billing/balance/',      billing_balance,      name='billing_balance'),
    path('billing/estimate/',     billing_estimate,     name='billing_estimate'),
    path('billing/redeem/',       billing_redeem,       name='billing_redeem'),
    path('billing/transactions/', billing_transactions, name='billing_transactions'),

    # 人工审阅 API
    path('review/list/',          review_list,    name='review_list'),
    path('review/submit/',        review_submit,  name='review_submit'),
    path('review/item/<path:source_xml>/', review_item, name='review_item'),
    path('review/stats/',         review_stats,   name='review_stats'),
    path('review/complete/',      review_complete, name='review_complete'),
    path('review/note/<path:source_xml>/',  review_note_append,  name='review_note_append'),
    path('review/notes/<path:source_xml>/', review_notes_list,   name='review_notes_list'),

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
    # AI 评价
    path('qa/eval/start/',                     eval_start,            name='qa_eval_start'),
    path('qa/eval/progress/',                  eval_progress,         name='qa_eval_progress'),
    # 信号问题
    path('qa/signal-items/',                   signal_items_list,     name='qa_signal_items_list'),
    path('qa/signal-items/<int:item_id>/confirm/', signal_item_confirm, name='qa_signal_item_confirm'),
    path('qa/signal-items/batch-confirm/',     signal_batch_confirm,  name='qa_signal_batch_confirm'),
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
