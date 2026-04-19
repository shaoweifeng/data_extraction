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
    
    def perform_destroy(self, instance):
        """删除项目时清理所有相关文件和数据"""
        import shutil
        import os
        from django.conf import settings
        
        # 检查权限
        user = self.request.user
        permission_code = 'project.delete'
        
        if not user.is_superuser:
            has_perm = UserPermission.objects.filter(
                user=user,
                permission__code=permission_code
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists()
            
            if not has_perm:
                raise PermissionError(f"缺少权限：{permission_code}")
        
        # 检查是否是项目所有者
        if instance.owner != user and not user.is_superuser:
            raise PermissionError("无权删除该项目")
        
        # 获取项目文件夹路径
        project_dir = os.path.join(settings.MEDIA_ROOT, 'projects', f'project_{instance.id}')
        
        # 删除所有关联的文件记录（级联删除会自动处理）
        # 但我们需要手动删除物理文件
        
        # 方式1：遍历所有 DataFile，删除物理文件
        try:
            for data_file in instance.files.all():
                if data_file.file and os.path.exists(data_file.file.path):
                    try:
                        os.remove(data_file.file.path)
                    except Exception as e:
                        print(f"删除文件失败: {data_file.file.path}, 错误: {e}")
        except Exception as e:
            print(f"清理文件时出错: {e}")
        
        # 方式2：删除整个项目文件夹（更彻底）
        try:
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
                print(f"已删除项目文件夹: {project_dir}")
        except Exception as e:
            print(f"删除项目文件夹失败: {project_dir}, 错误: {e}")
        
        # 最后删除数据库记录（级联删除会自动处理所有关联记录）
        instance.delete()
    
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
    def process_references(self, request, pk=None):
        """
        解析并去重文献索引文件（同步执行，参考 xxc/develop 分支）
        
        步骤：
        1. 获取该阶段的所有输入文件（.ris, .bib, .nbib, .xml, .ciw）
        2. 调用 parser.process_directory 解析并去重
        3. 保存合并后的 references.xml 和去重报告
        4. 返回去重报告给前端
        """
        stage = self.get_object()
        project = stage.project
        
        # 检查权限
        if project.owner != request.user and not request.user.is_superuser:
            return Response({"error": "无权操作该项目"}, status=status.HTTP_403_FORBIDDEN)
        
        # 创建工作区
        import tempfile
        import shutil
        import os
        
        work_dir = tempfile.mkdtemp(prefix=f'project_{project.id}_dedup_')
        input_dir = os.path.join(work_dir, 'input')
        output_dir = os.path.join(work_dir, 'output')
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # 1. 复制所有输入文件到工作区
            input_files = DataFile.objects.filter(
                project=project,
                data_category='input'
            )
            
            file_count = 0
            for data_file in input_files:
                if data_file.file and os.path.exists(data_file.file.path):
                    # 复制文件到输入目录
                    dest_path = os.path.join(input_dir, data_file.filename)
                    shutil.copy2(data_file.file.path, dest_path)
                    file_count += 1
            
            if file_count == 0:
                return Response({"error": "未找到任何输入文件，请先上传文献索引"}, status=status.HTTP_400_BAD_REQUEST)
            
            # 2. 调用 parser.process_directory
            from structural_screening.reference_parsing.parser import process_directory
            
            merged_xml_path = os.path.join(output_dir, 'references.xml')
            result = process_directory(input_dir, merged_xml_path, return_report=True)
            
            # 解析返回值：return_report=True 时返回 (final_entries, report)
            if isinstance(result, tuple):
                final_entries, report = result
            else:
                final_entries = result
                report = {'total_entries_found': len(final_entries), 'duplicates_removed': 0}
            
            # 3. 保存结果文件
            # 保存合并后的 references.xml
            if os.path.exists(merged_xml_path):
                with open(merged_xml_path, 'rb') as f:
                    from django.core.files import File
                    data_file = DataFile.objects.create(
                        project=project,
                        stage=stage,
                        filename='references.xml',
                        file=File(f, name='references.xml'),
                        data_category='output',
                        description='合并后的文献 XML',
                        metadata={'source': 'dedup', 'entries': len(final_entries)}
                    )
            
            # 保存去重报告
            import json
            report_path = os.path.join(output_dir, 'dedup_report.json')
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            with open(report_path, 'rb') as f:
                from django.core.files import File
                report_file = DataFile.objects.create(
                    project=project,
                    stage=stage,
                    filename='dedup_report.json',
                    file=File(f, name='dedup_report.json'),
                    data_category='output',
                    description='去重报告',
                    metadata={'source': 'dedup'}
                )
            
            # 更新阶段状态
            stage.status = 'completed'
            stage.completed_at = timezone.now()
            stage.metadata.update({
                'total_entries_found': report.get('total_entries_found', 0),
                'duplicates_removed': report.get('duplicates_removed', 0),
                'final_unique_entries': report.get('final_unique_entries', len(final_entries))
            })
            stage.save()
            
            return Response({
                'message': '去重完成',
                'total_entries': len(final_entries),
                'dedup_report': report
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({
                'error': f'处理失败: {str(e)}',
                'traceback': traceback.format_exc()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(work_dir)
            except:
                pass
    
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
    
    def perform_create(self, serializer):
        """创建任务时自动调度 Celery 任务"""
        task_obj = serializer.save()
        
        # 根据任务类型调度对应的 Celery 任务
        from .tasks import (
            run_reference_parsing_pipeline,
            run_deduplication_pipeline,
            run_ai_screening_pipeline,
            run_result_aggregation
        )
        
        task_type = task_obj.task_type
        project_id = task_obj.project.id
        config = task_obj.config or {}
        
        celery_task = None
        
        if task_type == 'reference_parsing':
            file_ids = config.get('file_ids')
            celery_task = run_reference_parsing_pipeline.delay(project_id, file_ids)
        elif task_type == 'deduplication':
            celery_task = run_deduplication_pipeline.delay(project_id)
        elif task_type == 'ai_screening':
            criteria = config.get('criteria')
            celery_task = run_ai_screening_pipeline.delay(project_id, criteria)
        elif task_type == 'result_aggregation':
            celery_task = run_result_aggregation.delay(project_id)
        
        # 更新任务的 celery_task_id
        if celery_task:
            task_obj.celery_task_id = celery_task.id
            task_obj.save()
    
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
