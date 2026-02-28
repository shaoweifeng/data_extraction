from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProjectViewSet, DocumentViewSet, ExtractionTaskViewSet, StageViewSet, StageDataViewSet

router = DefaultRouter()
router.register(r'projects', ProjectViewSet)
router.register(r'documents', DocumentViewSet)
router.register(r'tasks', ExtractionTaskViewSet)
router.register(r'stages', StageViewSet)
router.register(r'stage-data', StageDataViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
