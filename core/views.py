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
        """删除项目时清理所有相关文件和数据"""
        import shutil
        import os
        from django.conf import settings
        
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
        
        # 获取项目文件夹路径
        project_dir = os.path.join(settings.MEDIA_ROOT, 'projects', f'project_{instance.id}')
        
        # 删除所有关联的文件记录
        try:
            for data_file in instance.files.all():
                if data_file.file and os.path.exists(data_file.file.path):
                    try:
                        os.remove(data_file.file.path)
                    except Exception as e:
                        print(f"删除文件失败: {data_file.file.path}, 错误: {e}")
        except Exception as e:
            print(f"清理文件时出错: {e}")
        
        # 删除整个项目文件夹
        try:
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
                print(f"已删除项目文件夹: {project_dir}")
        except Exception as e:
            print(f"删除项目文件夹失败: {project_dir}, 错误: {e}")
        
        # 最后删除数据库记录
        instance.delete()
    
    @action(detail=True, methods=['get'])
    def stages(self, request, pk=None):
        """获取项目的所有阶段"""
        project = self.get_object()
        stages = project.stages.all().prefetch_related('steps')
        return Response(ProjectStageSerializer(stages, many=True).data)
    
    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """获取项目整体进度"""
        from .monitoring import ProgressMonitor
        
        project = self.get_object()
        monitor = ProgressMonitor(project.id)
        return Response(monitor.get_project_progress())


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
# 文件管理 ViewSet
# ============================================================================

class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    
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
        
        return qs
    
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
        
        serializer.save(created_by=user)
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """
        获取任务的实际日志内容
        
        返回日志文件的最后N行内容，用于调试失败原因
        """
        import os
        from pathlib import Path
        from django.conf import settings
        from django.http import JsonResponse
        
        task = self.get_object()
        
        # 解析日志元信息
        if not task.logs:
            return JsonResponse({
                'log_content': '',
                'error': '没有日志记录'
            })
        
        try:
            log_meta = json.loads(task.logs)
        except (json.JSONDecodeError, TypeError):
            return JsonResponse({
                'log_content': task.logs,  # 如果不是JSON，直接返回原始内容
                'error': '日志格式异常'
            })
        
        # 获取日志文件路径
        log_file_path = log_meta.get('log_file')
        if not log_file_path:
            return JsonResponse({
                'log_content': '',
                'error': '日志文件路径不存在'
            })
        
        # 构建完整路径
        if log_file_path.startswith('/'):
            full_path = Path(log_file_path)
        else:
            full_path = Path(settings.MEDIA_ROOT) / log_file_path
        
        # 读取日志内容（最后100行）
        try:
            if not full_path.exists():
                return JsonResponse({
                    'log_content': '',
                    'error': f'日志文件不存在: {log_file_path}',
                    'log_file': log_file_path
                })
            
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                # 返回最后100行
                last_lines = lines[-100:] if len(lines) > 100 else lines
                log_content = ''.join(last_lines)
            
            return JsonResponse({
                'log_content': log_content,
                'log_file': log_file_path,
                'total_lines': len(lines),
                'returned_lines': len(last_lines)
            })
        except Exception as e:
            return JsonResponse({
                'log_content': '',
                'error': f'读取日志失败: {str(e)}',
                'log_file': log_file_path
            })


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
        """获取任务日志"""
        from .monitoring import LogReader
        
        task = self.get_object()
        reader = LogReader(task.id)
        
        from_line = int(request.query_params.get('from_line', 0))
        max_lines = int(request.query_params.get('max_lines', 100))
        
        return Response(reader.read_logs(from_line, max_lines))
    
    @action(detail=True, methods=['get'])
    def tail(self, request, pk=None):
        """实时获取日志（最后N行）"""
        from .monitoring import LogReader
        
        task = self.get_object()
        reader = LogReader(task.id)
        
        last_n = int(request.query_params.get('n', 50))
        return Response({"lines": reader.tail_logs(last_n)})


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
