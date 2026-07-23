from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api

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
    # 认证 API
    path('auth/register/', api.register, name='register'),
    path('auth/login/', api.login_view, name='login'),
    path('auth/logout/', api.logout_view, name='logout'),
    path('auth/me/', api.current_user, name='current_user'),
    path('ai-models/', api.ai_models_list, name='ai_models_list'),
    
    # RESTful API
    path('', include(router.urls)),
]
