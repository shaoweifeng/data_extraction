from django.urls import path
from . import api

urlpatterns = [
    path('assets/', api.assets),
    path('assets/upload/', api.upload),
    path('assets/<int:asset_id>/', api.detail),
    path('assets/<int:asset_id>/download/', api.download),
    path('assets/<int:asset_id>/retry/', api.retry),
    path('assets/<int:asset_id>/rebuild/', api.rebuild),
]
