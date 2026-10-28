from django.urls import path
from .api import import_views as imports, reference_views as references
from .api import fulltext_views as fulltext
from .api import ai_views as ai
from .api import workspace_views as workspace
from .api import export_views as exports
from .api import qa_views

urlpatterns = [
    path('qa-handoff/', qa_views.handoff),
    path('exports/', exports.exports),
    path('exports/skip/', exports.skip),
    path('exports/<int:export_id>/cancel/', exports.cancel),
    path('exports/<int:export_id>/purge/', exports.purge),
    path('exports/<int:export_id>/download/', exports.download),
    path('workspace/', workspace.state),
    path('configuration/', workspace.configuration),
    path('workspace/references/', workspace.references),
    path('references/<int:reference_id>/review/', workspace.review),
    path('references/<int:reference_id>/review/history/', workspace.history),
    path('ai/estimate/', ai.estimate),
    path('ai/start/', ai.start),
    path('ai/runs/', ai.runs),
    path('ai/runs/<int:run_id>/', ai.detail),
    path('ai/runs/<int:run_id>/items/', ai.items),
    path('ai/runs/<int:run_id>/cancel/', ai.cancel),
    path('ai/runs/<int:run_id>/retry/', ai.retry),
    path('ai/runs/<int:run_id>/settle/', ai.settle),
    path('ai/items/<int:item_id>/', ai.item_detail),
    path('ai/prompt/', ai.prompt),
    path('references/<int:reference_id>/fulltext/', fulltext.binding),
    path('lookups/', fulltext.jobs),
    path('lookups/start/', fulltext.start),
    path('lookups/<int:job_id>/', fulltext.job_detail),
    path('lookups/<int:job_id>/items/', fulltext.items),
    path('lookups/<int:job_id>/cancel/', fulltext.cancel),
    path('lookups/<int:job_id>/retry/', fulltext.retry),
    path('candidates/<int:candidate_id>/confirm/', fulltext.confirm),
    path('imports/', imports.batches),
    path('imports/preview/', imports.preview),
    path('imports/upload/', imports.upload),
    path('imports/from-screening/', imports.from_screening),
    path('imports/<int:batch_id>/', imports.detail),
    path('imports/<int:batch_id>/retry/', imports.retry),
    path('imports/<int:batch_id>/cancel/', imports.cancel),
    path('imports/files/<int:file_id>/download/', imports.download),
    path('references/', references.references),
    path('references/remove/', references.remove),
    path('references/<int:reference_id>/', references.detail),
    path('references/<int:reference_id>/raw/', references.raw),
    path('stats/', references.stats),
]
