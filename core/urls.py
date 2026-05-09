from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# 注册 ViewSets
router = DefaultRouter()
router.register(r'projects', views.ProjectViewSet, basename='project')
router.register(r'stages', views.ProjectStageViewSet, basename='stage')
router.register(r'steps', views.StageStepViewSet, basename='step')
router.register(r'files', views.DataFileViewSet, basename='file')
router.register(r'tasks', views.TaskViewSet, basename='task')
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'activity-logs', views.ActivityLogViewSet, basename='activity-log')

urlpatterns = [
    # 认证 API
    path('auth/register/', views.register, name='register'),
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/me/', views.current_user, name='current_user'),
    path('ai-models/', views.ai_models_list, name='ai_models_list'),
    
    # RESTful API
    path('', include(router.urls)),
]
