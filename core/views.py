"""
数据提取平台 - API视图

核心变更：
- 使用 TaskScheduler 统一调度任务
- 使用 step_config.py 管理配置
- 保留认证API和权限装饰器
"""

from rest_framework import viewsets, status, serializers as drf_serializers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import PermissionDenied
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q
from functools import wraps
import json

from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    Project, ProjectStage, StageStep, DataFile, DataFileVersion, Task, ActivityLog
)
from .serializers import (
    UserSerializer, UserProfileSerializer, PermissionSerializer,
    ProjectSerializer, ProjectStageSerializer, StageStepSerializer,
    DataFileSerializer, DataFileVersionSerializer, TaskSerializer, ActivityLogSerializer
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ai_models_list(request):
    """返回可用的 AI 模型列表（不含 api_key）"""
    from platform_backend.ai_models_config import get_models_for_frontend
    return Response(get_models_for_frontend())


# ============================================================================
# 项目管理 ViewSet
# ============================================================================

class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """返回用户有权访问的项目"""
        return Project.objects.for_user(self.request.user)
    
    def perform_create(self, serializer):
        """创建项目时自动初始化阶段和步骤"""
        from .step_config import get_stage_definition
        
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
                raise PermissionDenied(f"缺少权限：{permission_code}")
        
        # 检查配额
        if not user.is_superuser and hasattr(user, 'profile'):
            quota = user.profile.quota_projects
            if quota >= 0:  # -1 表示无限
                current_count = Project.objects.filter(owner=user).count()
                if current_count >= quota:
                    raise PermissionDenied(f"已达项目配额上限({quota}个)")
        
        # 创建项目
        project = serializer.save(owner=user)
        
        # 自动创建 6 个阶段（使用 step_config 配置）
        stage_keys = ['SEARCH', 'SCREEN_1', 'SCREEN_2', 'QUALITY', 'EXTRACT', 'META']
        
        for stage_key in stage_keys:
            stage_def = get_stage_definition(stage_key)
            
            stage = ProjectStage.objects.create(
                project=project,
                stage_key=stage_key,
                name=stage_def.get("name", stage_key),
                order=stage_def.get("order", 100),
                status="pending"
            )
            
            # 为有子步骤的阶段创建步骤
            for step_def in stage_def.get("steps", []):
                StageStep.objects.create(
                    stage=stage,
                    step_key=step_def["step_key"],
                    name=step_def.get("name", step_def["step_key"]),
                    order=step_def.get("order", 100),
                    can_skip=step_def.get("can_skip", True),
                    status="pending"
                )
    
    def perform_destroy(self, instance):
        """删除项目时：归档到历史表 + 清理所有文件 + 删除数据库记录"""
        import shutil
        import os
        from django.conf import settings
        from django.db import connection

        user = self.request.user
        permission_code = 'project.delete_own'

        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()

            if not has_perm:
                raise PermissionDenied(f"缺少权限：{permission_code}")

        # 检查是否是项目所有者
        if instance.owner != user and not user.is_superuser:
            raise PermissionDenied("无权删除该项目")

        # 1. 归档 plat_project 记录到 plat_project_history
        try:
            import json
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO plat_project_history
                        (id, name, slug, description, owner_id, status, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name=VALUES(name), slug=VALUES(slug), description=VALUES(description),
                        status=VALUES(status), metadata=VALUES(metadata), updated_at=VALUES(updated_at)
                    """,
                    [
                        instance.id,
                        instance.name,
                        instance.slug,
                        instance.description,
                        instance.owner_id,
                        'deleted',
                        json.dumps(instance.metadata) if instance.metadata else '{}',
                        instance.created_at,
                        instance.updated_at,
                    ]
                )
        except Exception as e:
            print(f"归档项目到历史表失败: {e}")

        # 2. 清理 MEDIA_ROOT 下的项目文件（逐个删除，防止 signal 重复触发）
        try:
            for data_file in instance.files.all():
                if data_file.file:
                    try:
                        path = data_file.file.path
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception as e:
                        print(f"删除文件失败: {e}")
        except Exception as e:
            print(f"清理文件时出错: {e}")

        # 删除整个 MEDIA_ROOT/projects/project_{id}/ 目录（兜底）
        media_project_dir = os.path.join(settings.MEDIA_ROOT, 'projects', f'project_{instance.id}')
        try:
            if os.path.exists(media_project_dir):
                shutil.rmtree(media_project_dir)
        except Exception as e:
            print(f"删除 media 目录失败: {e}")

        # 3. 清理 workspaces/project_{id}/ 目录（任务运行目录）
        workspace_dir = os.path.join(settings.BASE_DIR, 'workspaces', f'project_{instance.id}')
        try:
            if os.path.exists(workspace_dir):
                shutil.rmtree(workspace_dir)
        except Exception as e:
            print(f"删除 workspace 目录失败: {e}")

        # 4. 删除数据库记录（级联删除 Task/StageStep/DataFile/ActivityLog 等）
        instance.delete()
    
    @action(detail=True, methods=['get'])
    def stages(self, request, pk=None):
        """获取项目的所有阶段"""
        project = self.get_object()
        stages = project.stages.all().prefetch_related('steps')
        return Response(ProjectStageSerializer(stages, many=True).data)

    @action(detail=True, methods=['post'])
    def clear_ai_screen_results(self, request, pk=None):
        """清除项目 ai_screen 步骤的所有 output 文件记录（启动/放弃任务时调用）"""
        from core.models import StageStep, ProjectStage, DataFile
        project = self.get_object()

        # 找到 ai_screen 步骤
        ai_step = StageStep.objects.filter(
            stage__project=project,
            step_key='ai_screen'
        ).first()

        if ai_step:
            deleted_count, _ = DataFile.objects.filter(
                project=project,
                step=ai_step,
                data_category='output'
            ).delete()
            # 记录操作日志
            ActivityLog.objects.create(
                project=project,
                operation_type='task_abandon',
                operation_detail={'task_type': 'AI初筛', 'action': 'clear_results', 'deleted_count': deleted_count},
                created_by=request.user
            )
            return Response({'message': f'已清除 {deleted_count} 条筛选结果记录'})

        return Response({'message': '未找到 ai_screen 步骤，无需清除'})
    
    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """获取项目整体进度"""
        from .monitoring import ProgressMonitor
        
        project = self.get_object()
        monitor = ProgressMonitor(project.id)
        return Response(monitor.get_project_progress())

    @action(detail=True, methods=['get'])
    def get_prompt(self, request, pk=None):
        """获取项目的自定义 Prompt（返回 custom_prompt、use_custom 标志和 default_prompt）"""
        from pathlib import Path
        from django.conf import settings

        project = self.get_object()
        custom_prompt = (project.metadata or {}).get('custom_prompt', '')
        use_custom = (project.metadata or {}).get('use_custom_prompt', False)

        # 读取默认 prompt1.txt 内容一并返回
        prompt_path = Path(settings.BASE_DIR) / "structural_screening/02_screening_ai/prompts/prompt1.txt"
        default_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ''

        return Response({
            'custom_prompt': custom_prompt,
            'use_custom_prompt': use_custom,
            'default_prompt': default_prompt,
        })

    @action(detail=True, methods=['post'])
    def save_prompt(self, request, pk=None):
        """保存自定义 Prompt，同时记录操作日志"""
        project = self.get_object()
        custom_prompt = request.data.get('custom_prompt', '').strip()
        use_custom = request.data.get('use_custom_prompt', True)

        # 校验：必须包含占位符
        if use_custom and '{screening_criteria}' not in custom_prompt:
            return Response(
                {'error': 'Prompt 必须包含 {screening_criteria} 占位符'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 持久化到 project.metadata
        project.metadata = project.metadata or {}
        project.metadata['custom_prompt'] = custom_prompt
        project.metadata['use_custom_prompt'] = use_custom
        project.save(update_fields=['metadata'])

        # 操作日志
        ActivityLog.objects.create(
            project=project,
            operation_type='prompt_set',
            operation_detail={
                'use_custom': use_custom,
                'prompt_length': len(custom_prompt),
                'prompt_preview': custom_prompt[:100] if custom_prompt else '',
            },
            created_by=request.user
        )

        return Response({'message': '已保存', 'use_custom_prompt': use_custom})

    @action(detail=True, methods=['post'])
    def reset_prompt(self, request, pk=None):
        """重置为默认 Prompt，并记录操作日志"""
        project = self.get_object()
        project.metadata = project.metadata or {}
        project.metadata['custom_prompt'] = ''
        project.metadata['use_custom_prompt'] = False
        project.save(update_fields=['metadata'])

        ActivityLog.objects.create(
            project=project,
            operation_type='prompt_reset',
            operation_detail={},
            created_by=request.user
        )

        return Response({'message': '已重置为默认 Prompt'})


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
    @require_permission('stage.start')
    def start(self, request, pk=None):
        """
        启动阶段（使用 TaskScheduler）
        
        Request Body:
            - config: 阶段配置（可选）
        """
        from .scheduler import TaskScheduler
        
        stage = self.get_object()
        project = stage.project
        
        # 检查权限
        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)
        
        # 获取配置
        config = request.data.get('config', {})
        
        # 调用调度器
        scheduler = TaskScheduler(project.id)
        
        try:
            task = scheduler.start_stage(stage.stage_key, request.user.id, **config)
            return Response({
                "message": f"阶段 {stage.name} 已启动",
                "task": TaskSerializer(task).data
            })
        except Exception as e:
            return Response({
                "error": f"启动失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止阶段"""
        from .scheduler import TaskScheduler
        
        stage = self.get_object()
        project = stage.project
        
        # 检查权限
        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)
        
        # 获取正在运行的任务
        running_task = Task.objects.filter(
            project=project,
            task_type=stage.stage_key,
            status='running'
        ).first()
        
        if not running_task:
            return Response({"error": "没有正在运行的任务"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 调用调度器停止
        scheduler = TaskScheduler(project.id)
        success = scheduler.stop_task(running_task.id)
        
        if success:
            stage.status = 'stopped'
            stage.save()
            return Response({"message": "阶段已停止"})
        else:
            return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        """跳过整个阶段"""
        stage = self.get_object()
        
        # 检查是否允许跳过
        from .step_config import get_step_config
        config = get_step_config(stage.stage_key)
        
        if not config.get("can_skip", False):
            return Response(
                {"error": "该阶段不允许跳过"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        stage.status = 'skipped'
        stage.completed_at = timezone.now()
        stage.save()
        
        # 同时跳过所有子步骤
        stage.steps.update(status='skipped', completed_at=timezone.now())
        
        return Response(ProjectStageSerializer(stage).data)
    
    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """获取阶段进度"""
        from .monitoring import ProgressMonitor
        
        stage = self.get_object()
        monitor = ProgressMonitor(stage.project.id)
        return Response(monitor.get_stage_progress(stage.stage_key))


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
    @require_permission('step.start')
    def start(self, request, pk=None):
        """
        启动步骤（使用 TaskScheduler）
        
        Request Body:
            - config: 步骤配置（可选，如纳排标准）
        """
        from .scheduler import TaskScheduler
        
        step = self.get_object()
        stage = step.stage
        project = stage.project
        
        # 检查权限
        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)
        
        # 检查步骤状态
        if step.status == 'in_progress':
            return Response({"error": "步骤正在运行中"}, status=status.HTTP_400_BAD_REQUEST)
        
        if step.status == 'completed':
            return Response({"error": "步骤已完成，请勿重复执行"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取配置
        config = request.data.get('config', {})
        
        # 保存纳排标准（如果是 criteria 步骤）
        if step.step_key == 'criteria' and 'criteria' in config:
            step.metadata = step.metadata or {}
            step.metadata['criteria'] = config['criteria']
            step.save()
        
        # 调用调度器
        scheduler = TaskScheduler(project.id)
        
        try:
            task = scheduler.start_step(step.step_key, request.user.id, **config)
            
            # 更新步骤状态
            step.status = 'in_progress'
            step.started_at = timezone.now()
            step.save()
            
            return Response({
                "message": f"步骤 {step.name} 已启动",
                "task": TaskSerializer(task).data
            })
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                "error": f"启动失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止步骤"""
        from .scheduler import TaskScheduler
        
        step = self.get_object()
        stage = step.stage
        project = stage.project
        
        # 检查权限
        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)
        
        # 检查步骤状态
        if step.status != 'in_progress':
            return Response({"error": "步骤未在运行"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取正在运行的任务
        running_task = Task.objects.filter(
            project=project,
            task_type=step.step_key,
            status='running'
        ).first()
        
        if not running_task:
            # 可能是同步任务已执行完
            step.status = 'stopped'
            step.save()
            return Response({"message": "步骤已停止"})
        
        # 调用调度器停止
        scheduler = TaskScheduler(project.id)
        success = scheduler.stop_task(running_task.id)
        
        if success:
            step.status = 'stopped'
            step.completed_at = timezone.now()
            step.save()
            return Response({"message": "步骤已停止"})
        else:
            return Response({"error": "停止失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    @require_permission('step.skip')
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
    def complete(self, request, pk=None):
        """手动完成步骤"""
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

        # 纳排标准变更时，记录操作日志
        if step.step_key == 'criteria' and 'criteria' in metadata:
            old_criteria = set((step.metadata or {}).get('criteria', []))
            new_criteria = set(metadata['criteria'])
            project = step.stage.project
            for c in (new_criteria - old_criteria):
                ActivityLog.objects.create(
                    project=project,
                    operation_type='criteria_add',
                    operation_detail={'criteria': c},
                    created_by=request.user
                )
            for c in (old_criteria - new_criteria):
                ActivityLog.objects.create(
                    project=project,
                    operation_type='criteria_delete',
                    operation_detail={'criteria': c},
                    created_by=request.user
                )

        step.metadata = step.metadata or {}
        step.metadata.update(metadata)
        step.save()
        return Response(StageStepSerializer(step).data)
    
    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """获取步骤进度"""
        from .monitoring import ProgressMonitor
        
        step = self.get_object()
        stage = step.stage
        monitor = ProgressMonitor(stage.project.id)
        return Response(monitor.get_step_progress(step.step_key))
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """获取步骤日志"""
        from .monitoring import LogReader
        
        step = self.get_object()
        stage = step.stage
        project = stage.project
        
        # 获取最新的任务
        latest_task = Task.objects.filter(
            project=project,
            task_type=step.step_key
        ).order_by('-created_at').first()
        
        if not latest_task:
            return Response({"lines": [], "total": 0})
        
        # 读取日志
        reader = LogReader(latest_task.id)
        from_line = int(request.query_params.get('from_line', 0))
        max_lines = int(request.query_params.get('max_lines', 100))
        
        return Response(reader.read_logs(from_line, max_lines))


# ============================================================================
# 操作日志 ViewSet
# ============================================================================

class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """操作日志（只读）"""
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            qs = ActivityLog.objects.all()
        else:
            qs = ActivityLog.objects.filter(project__owner=user)

        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


# ============================================================================
# 文件管理 ViewSet
# ============================================================================

class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None  # 默认禁用分页，由前端控制
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            qs = DataFile.objects.all()
        else:
            qs = DataFile.objects.filter(project__owner=user)
        
        qp = self.request.query_params
        project_id = qp.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        
        stage_id = qp.get('stage')
        if stage_id:
            qs = qs.filter(stage_id=stage_id)
        
        step_id = qp.get('step')
        if step_id:
            qs = qs.filter(step_id=step_id)
        
        data_category = qp.get('data_category')
        if data_category:
            qs = qs.filter(data_category=data_category)
        
        return qs.select_related('stage', 'step', 'created_by').prefetch_related('versions')
    
    def perform_create(self, serializer):
        """创建文件时自动关联当前用户"""
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
                raise PermissionDenied(f"缺少权限：{permission_code}")
        
        # 自动提取文件名
        uploaded_file = self.request.FILES.get('file')
        if uploaded_file and not serializer.validated_data.get('filename'):
            serializer.validated_data['filename'] = uploaded_file.name
        
        # 自动关联 stage 和 step
        project = serializer.validated_data.get('project')
        if project:
            project_id = project.id
            data_category = serializer.validated_data.get('data_category', 'input')
            
            # 如果是 input 类型且没有指定 stage，自动关联到 SCREEN_1 阶段的 parse 步骤
            if data_category == 'input' and not serializer.validated_data.get('stage'):
                try:
                    screen1_stage = ProjectStage.objects.get(project_id=project_id, stage_key='SCREEN_1')
                    serializer.validated_data['stage'] = screen1_stage
                    
                    # 自动关联到 parse 步骤
                    try:
                        parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
                        serializer.validated_data['step'] = parse_step
                    except StageStep.DoesNotExist:
                        pass
                except ProjectStage.DoesNotExist:
                    pass
        
        # 自动计算文件大小
        if uploaded_file and not serializer.validated_data.get('file_size'):
            serializer.validated_data['file_size'] = uploaded_file.size
        
        # 自动检测文件类型
        if uploaded_file and not serializer.validated_data.get('file_type'):
            import mimetypes
            file_type, _ = mimetypes.guess_type(uploaded_file.name)
            if file_type:
                serializer.validated_data['file_type'] = file_type
        
        # 在 save 之前记录 filename 和 project（save 后 validated_data 可能被清空）
        _filename = (uploaded_file.name if uploaded_file
                     else serializer.validated_data.get('filename', ''))
        _project = serializer.validated_data.get('project')

        serializer.save(created_by=user)

        # 记录操作日志
        if _project:
            ActivityLog.objects.create(
                project=_project,
                operation_type='file_add',
                operation_detail={'filename': _filename},
                created_by=user
            )

    def perform_destroy(self, instance):
        """删除文件时记录操作日志，并级联清理失效的中间数据"""
        from core.models import StageStep, ProjectStage

        # 级联清理：删除 input 文件时，parse/dedup 步骤的 intermediate 数据也失效了
        if instance.data_category == 'input' and instance.project:
            project = instance.project
            # 清理 parse 步骤的 intermediate（解析结果依赖原始输入）
            parse_step = StageStep.objects.filter(
                stage__project=project, step_key='parse'
            ).first()
            if parse_step:
                old_intermediate = DataFile.objects.filter(
                    project=project, step=parse_step, data_category='intermediate'
                )
                count = old_intermediate.count()
                if count > 0:
                    old_intermediate.delete()

            # 清理 dedup 步骤的 intermediate（去重结果依赖解析结果）
            dedup_step = StageStep.objects.filter(
                stage__project=project, step_key='dedup'
            ).first()
            if dedup_step:
                old_intermediate = DataFile.objects.filter(
                    project=project, step=dedup_step, data_category='intermediate'
                )
                count = old_intermediate.count()
                if count > 0:
                    old_intermediate.delete()

            # 重置 parse 和 dedup 步骤状态（从 completed → pending）
            for step_key in ['parse', 'dedup']:
                step = StageStep.objects.filter(
                    stage__project=project, step_key=step_key
                ).first()
                if step and step.status in ('completed', 'in_progress', 'failed'):
                    step.status = 'pending'
                    step.metadata = {}
                    step.save()

        # 记录操作日志
        ActivityLog.objects.create(
            project=instance.project,
            operation_type='file_delete',
            operation_detail={'filename': instance.filename},
            created_by=self.request.user
        )
        instance.delete()

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """
        获取任务的实际日志内容
        
        优先从 log_file 字段读取日志文件，fallback 到 logs 字段
        """
        from pathlib import Path
        from django.http import JsonResponse
        
        task = self.get_object()
        
        # 优先使用 log_file 字段（绝对路径）
        log_file_path = task.log_file if task.log_file else None
        
        # fallback：尝试从 logs 字段解析出 log_file 路径（兼容旧格式）
        if not log_file_path and task.logs:
            try:
                log_meta = json.loads(task.logs)
                log_file_path = log_meta.get('log_file')
            except (json.JSONDecodeError, TypeError):
                # logs 是纯文本，直接返回
                return JsonResponse({'log_content': task.logs})
        
        # 有日志文件路径，读取文件内容
        if log_file_path:
            full_path = Path(log_file_path)
            try:
                if not full_path.exists():
                    return JsonResponse({
                        'log_content': task.logs or '',
                        'error': f'日志文件不存在: {log_file_path}'
                    })
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                last_lines = lines[-200:] if len(lines) > 200 else lines
                return JsonResponse({
                    'log_content': ''.join(last_lines),
                    'log_file': log_file_path,
                    'total_lines': len(lines),
                    'returned_lines': len(last_lines)
                })
            except Exception as e:
                return JsonResponse({
                    'log_content': task.logs or '',
                    'error': f'读取日志失败: {str(e)}'
                })
        
        # 兜底：直接返回 logs 字段
        return JsonResponse({'log_content': task.logs or ''})


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        # 基础查询集：用户只能看到自己有权限的任务
        if user.is_superuser:
            queryset = Task.objects.all()
        else:
            queryset = Task.objects.filter(project__owner=user)
        
        # ✅ 根据请求参数过滤项目
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        return queryset
    
    def perform_create(self, serializer):
        """
        兼容前端 POST /api/tasks/ 调用
        
        前端调用示例：
        - task_type: 'reference_parsing' → 触发 parse 步骤
        - task_type: 'deduplication' → 触发 dedup 步骤
        - task_type: 'ai_screening' → 触发 ai_screen 步骤
        - task_type: 'result_aggregation' → 触发 export 步骤
        """
        from .scheduler import TaskScheduler
        from .step_config import get_step_config
        
        user = self.request.user
        
        # 超级用户和管理员跳过权限检查
        if not user.is_superuser and not user.is_staff:
            # 检查用户是否有 task.start 权限
            permission_code = 'task.start'
            from django.db.models import Q
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()
            
            if not has_perm:
                # 返回 400 而不是 403，避免前端触发登录框
                raise serializers.ValidationError(f"缺少权限：{permission_code}，请联系管理员")
        
        # 映射前端 task_type 到 step_key
        task_type_map = {
            'reference_parsing': 'parse',
            'deduplication': 'dedup',
            'ai_screening': 'ai_screen',
            'result_aggregation': 'export'
        }
        
        task_type = serializer.validated_data.get('task_type', '')
        step_key = task_type_map.get(task_type, task_type)
        config = serializer.validated_data.get('config', {})
        
        # 获取项目ID
        project_id = serializer.validated_data.get('project').id if 'project' in serializer.validated_data else None
        
        if not project_id:
            raise serializers.ValidationError("缺少项目ID")
        
        # 使用调度器启动任务
        scheduler = TaskScheduler(project_id)
        
        try:
            task = scheduler.start_step(step_key, user.id, **config)
            # 更新serializer实例以返回正确的数据
            serializer.instance = task
            
            # 记录操作日志（使用细化的任务类型）
            op_type = f'task_start_{step_key}'
            task_type_display = {
                'parse': '文献解析', 'dedup': '文献去重',
                'ai_screen': 'AI初筛', 'export': '结果归纳'
            }.get(step_key, step_key)
            ActivityLog.objects.create(
                project_id=project_id,
                operation_type=op_type,
                operation_detail={'task_type': task_type_display, 'task_id': task.id},
                created_by=user
            )
        except ValueError as e:
            raise drf_serializers.ValidationError(str(e))
        except Exception as e:
            raise drf_serializers.ValidationError(f"启动失败: {str(e)}")
    
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止任务"""
        from .scheduler import TaskScheduler
        
        task = self.get_object()
        
        if task.status not in ['running', 'pending']:
            return Response(
                {"error": "任务未在运行"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        scheduler = TaskScheduler(task.project.id)
        success = scheduler.stop_task(task.id)
        
        if success:
            task_type_display = {
                'parse': '文献解析', 'dedup': '文献去重',
                'ai_screen': 'AI初筛', 'export': '结果归纳'
            }.get(task.task_type, task.task_type)
            ActivityLog.objects.create(
                project=task.project,
                operation_type='task_stop',
                operation_detail={'task_type': task_type_display, 'task_id': task.id},
                created_by=request.user
            )
            return Response({"message": "任务已停止"})
        else:
            return Response(
                {"error": "停止失败"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """恢复任务（断点续传）"""
        from .scheduler import TaskScheduler
        
        task = self.get_object()
        
        if task.status != 'stopped':
            return Response(
                {"error": "只能恢复已停止的任务"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        scheduler = TaskScheduler(task.project.id)
        
        try:
            new_task = scheduler.resume_task(task.id)
            task_type_display = {
                'parse': '文献解析', 'dedup': '文献去重',
                'ai_screen': 'AI初筛', 'export': '结果归纳'
            }.get(task.task_type, task.task_type)
            ActivityLog.objects.create(
                project=task.project,
                operation_type='task_resume',
                operation_detail={'task_type': task_type_display, 'task_id': new_task.id},
                created_by=request.user
            )
            return Response({
                "message": "任务已恢复",
                "task": TaskSerializer(new_task).data
            })
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """获取任务进度"""
        from .monitoring import get_task_progress
        
        task = self.get_object()
        return Response(get_task_progress(task.id))
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """获取任务日志 - 直接读 log_file 字段指向的文件"""
        from pathlib import Path
        
        task = self.get_object()
        log_file_path = task.log_file
        
        if log_file_path and Path(log_file_path).exists():
            try:
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                last_lines = lines[-200:] if len(lines) > 200 else lines
                return Response({
                    'log_content': ''.join(last_lines),
                    'total_lines': len(lines),
                    'returned_lines': len(last_lines)
                })
            except Exception as e:
                return Response({'log_content': f'读取日志失败: {e}'})
        
        # fallback: 返回 logs 字段（纯文本）
        return Response({'log_content': task.logs or '任务正在初始化，日志即将生成...'})
    
    @action(detail=True, methods=['get'])
    def tail(self, request, pk=None):
        """实时获取日志（最后N行）"""
        from .monitoring import LogReader
        
        task = self.get_object()
        reader = LogReader(task.id)
        
        last_n = int(request.query_params.get('n', 50))
        lines = reader.tail_logs(last_n)
        
        # 兼容前端：返回合并后的日志字符串
        return Response({
            "lines": lines,
            "log_content": '\n'.join(lines) if lines else '暂无日志'
        })


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
