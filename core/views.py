from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q
from functools import wraps

from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    Project, ProjectStage, StageStep, DataFile, DataFileVersion, Task
)
from .serializers import (
    UserSerializer, UserProfileSerializer, PermissionSerializer,
    ProjectSerializer, ProjectStageSerializer, StageStepSerializer,
    DataFileSerializer, DataFileVersionSerializer, TaskSerializer
)


# ============================================================================
# 权限检查装饰器
# ============================================================================

def require_permission(permission_code):
    """
    权限检查装饰器
    Usage: @require_permission('project.create')
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            user = request.user
            
            # 超级管理员跳过检查
            if user.is_superuser:
                return func(self, request, *args, **kwargs)
            
            # 检查用户是否拥有该权限
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()
            
            if not has_perm:
                return Response(
                    {"error": f"缺少权限：{permission_code}"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            return func(self, request, *args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# 认证 API（无需 ViewSet）
# ============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """用户注册"""
    username = request.data.get('username')
    password = request.data.get('password')
    email = request.data.get('email', '')
    
    if not username or not password:
        return Response(
            {"error": "用户名和密码不能为空"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if User.objects.filter(username=username).exists():
        return Response(
            {"error": "用户名已存在"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # 创建用户（Profile 会通过 signal 自动创建）
    user = User.objects.create_user(username=username, password=password, email=email)
    
    return Response({
        "message": "注册成功，请等待管理员审核",
        "user": UserSerializer(user).data
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """用户登录"""
    username = request.data.get('username')
    password = request.data.get('password')
    
    user = authenticate(request, username=username, password=password)
    
    if user is not None:
        # 检查是否已审核通过
        if hasattr(user, 'profile') and not user.profile.is_approved and not user.is_superuser:
            return Response({
                "error": "账号尚未通过审核，请联系管理员"
            }, status=status.HTTP_403_FORBIDDEN)
        
        login(request, user)
        return Response({
            "message": "登录成功",
            "user": UserSerializer(user).data
        })
    else:
        return Response(
            {"error": "用户名或密码错误"},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """用户注销"""
    logout(request)
    return Response({"message": "已注销"})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    """获取当前登录用户信息"""
    return Response(UserSerializer(request.user).data)


# ============================================================================
# 项目管理 ViewSet
# ============================================================================

# 系统预定义阶段
STAGE_DEFINITIONS = [
    {
        "stage_key": "SEARCH",
        "name": "文献检索",
        "order": 10,
        "steps": []
    },
    {
        "stage_key": "SCREEN_1",
        "name": "文献初筛",
        "order": 20,
        "steps": [
            {"step_key": "parse", "name": "文献解析", "order": 10, "can_skip": False},
            {"step_key": "dedup", "name": "自动去重", "order": 20, "can_skip": True},
            {"step_key": "criteria", "name": "纳排标准", "order": 30, "can_skip": False},
            {"step_key": "ai_screen", "name": "AI初筛", "order": 40, "can_skip": False},
            {"step_key": "export", "name": "结果归纳", "order": 50, "can_skip": False}
        ]
    },
    {
        "stage_key": "SCREEN_2",
        "name": "文献复筛",
        "order": 30,
        "steps": []
    },
    {
        "stage_key": "QUALITY",
        "name": "文献质量评价",
        "order": 40,
        "steps": []
    },
    {
        "stage_key": "EXTRACT",
        "name": "数据提取",
        "order": 50,
        "steps": []
    },
    {
        "stage_key": "META",
        "name": "Meta分析",
        "order": 60,
        "steps": []
    }
]


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """返回用户有权访问的项目"""
        return Project.objects.for_user(self.request.user)
    
    def perform_create(self, serializer):
        """创建项目时自动初始化阶段和步骤"""
        # 手动检查权限（不使用装饰器，因为 perform_create 的参数不同）
        user = self.request.user
        permission_code = 'project.create'
        
        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()
            
            if not has_perm:
                raise PermissionError(f"缺少权限：{permission_code}")
        
        # 检查配额
        if not user.is_superuser and hasattr(user, 'profile'):
            quota = user.profile.quota_projects
            if quota >= 0:  # -1 表示无限
                current_count = Project.objects.filter(owner=user).count()
                if current_count >= quota:
                    raise PermissionError(f"已达项目配额上限({quota}个)")
        
        # 创建项目
        project = serializer.save(owner=user)
        
        # 自动创建 6 个阶段
        for stage_def in STAGE_DEFINITIONS:
            stage = ProjectStage.objects.create(
                project=project,
                stage_key=stage_def["stage_key"],
                name=stage_def["name"],
                order=stage_def["order"],
                status="pending"
            )
            
            # 为有子步骤的阶段创建步骤
            for step_def in stage_def.get("steps", []):
                StageStep.objects.create(
                    stage=stage,
                    step_key=step_def["step_key"],
                    name=step_def["name"],
                    order=step_def["order"],
                    can_skip=step_def["can_skip"],
                    status="pending"
                )
    
    @action(detail=True, methods=['get'])
    def stages(self, request, pk=None):
        """获取项目的所有阶段"""
        project = self.get_object()
        stages = project.stages.all().prefetch_related('steps')
        return Response(ProjectStageSerializer(stages, many=True).data)


# ============================================================================
# 阶段管理 ViewSet
# ============================================================================

class ProjectStageViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectStageSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return ProjectStage.objects.all()
        return ProjectStage.objects.filter(project__owner=user)
    
    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        """跳过整个阶段"""
        stage = self.get_object()
        stage.status = 'skipped'
        stage.completed_at = timezone.now()
        stage.save()
        return Response(ProjectStageSerializer(stage).data)


# ============================================================================
# 步骤管理 ViewSet
# ============================================================================

class StageStepViewSet(viewsets.ModelViewSet):
    serializer_class = StageStepSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return StageStep.objects.all()
        return StageStep.objects.filter(stage__project__owner=user)
    
    @action(detail=True, methods=['post'])
    @require_permission('stage.skip')
    def skip(self, request, pk=None):
        """跳过步骤"""
        step = self.get_object()
        if not step.can_skip:
            return Response(
                {"error": "该步骤不允许跳过"},
                status=status.HTTP_400_BAD_REQUEST
            )
        step.status = 'skipped'
        step.completed_at = timezone.now()
        step.save()
        return Response(StageStepSerializer(step).data)
    
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """开始步骤"""
        step = self.get_object()
        step.status = 'in_progress'
        step.started_at = timezone.now()
        step.save()
        return Response(StageStepSerializer(step).data)
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """完成步骤"""
        step = self.get_object()
        step.status = 'completed'
        step.completed_at = timezone.now()
        step.save()
        return Response(StageStepSerializer(step).data)
    
    @action(detail=True, methods=['patch'])
    def update_metadata(self, request, pk=None):
        """更新步骤元数据（如保存纳排标准）"""
        step = self.get_object()
        metadata = request.data.get('metadata', {})
        step.metadata.update(metadata)
        step.save()
        return Response(StageStepSerializer(step).data)


# ============================================================================
# 文件管理 ViewSet
# ============================================================================

class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return DataFile.objects.all()
        return DataFile.objects.filter(project__owner=user)
    
    def perform_create(self, serializer):
        """创建文件时自动关联当前用户"""
        # 手动检查权限（不使用装饰器，因为 perform_create 的参数不同）
        user = self.request.user
        permission_code = 'file.upload'
        
        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()
            
            if not has_perm:
                raise PermissionError(f"缺少权限：{permission_code}")
        
        serializer.save(created_by=user)
    
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """获取文件的所有版本"""
        data_file = self.get_object()
        versions = data_file.versions.all()
        return Response(DataFileVersionSerializer(versions, many=True).data)


# ============================================================================
# 任务管理 ViewSet
# ============================================================================

class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Task.objects.all()
        return Task.objects.filter(project__owner=user)
    
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止任务"""
        task = self.get_object()
        if task.status == 'running' and task.celery_task_id:
            from celery import current_app
            current_app.control.revoke(task.celery_task_id, terminate=True)
            task.status = 'stopped'
            task.completed_at = timezone.now()
            task.save()
        return Response(TaskSerializer(task).data)


# ============================================================================
# 用户管理 ViewSet（管理员专用）
# ============================================================================

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    @require_permission('user.view_all')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    @require_permission('user.approve')
    def approve(self, request, pk=None):
        """审核通过用户"""
        user = self.get_object()
        profile = user.profile
        
        profile.is_approved = True
        profile.approved_at = timezone.now()
        profile.approved_by = request.user
        profile.save()
        
        # 应用"标准研究者"角色模板
        try:
            template = RoleTemplate.objects.get(name='标准研究者')
            for rtp in template.template_permissions.all():
                UserPermission.objects.get_or_create(
                    user=user,
                    permission=rtp.permission,
                    defaults={
                        'granted_by': request.user,
                        'granted_at': timezone.now()
                    }
                )
        except RoleTemplate.DoesNotExist:
            pass
        
        return Response({
            "message": "用户已审核通过并授予基础权限",
            "user": UserSerializer(user).data
        })
