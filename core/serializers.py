"""
数据提取平台 - 序列化器

优化要点：
1. 添加计算字段（progress_percentage, duration, is_async等）
2. 避免N+1查询（使用 select_related/prefetch_related）
3. 解析日志元信息
4. 保持嵌套序列化的简洁性
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from django.db.models import Avg
from django.utils import timezone

from core.workflow.domain.statuses import ProjectStageStatus, StageStepStatus
import json
from datetime import datetime

from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    Project, ProjectStage, StageStep, DataFile, DataFileVersion, Task, ActivityLog
)


# ============================================================================
# 用户相关 Serializers
# ============================================================================

class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    concurrency_limit = serializers.SerializerMethodField()
    quota_projects    = serializers.SerializerMethodField()
    quota_storage_mb  = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ['id', 'username', 'email', 'role', 'quota_projects', 'quota_storage_mb',
                  'is_approved', 'is_banned', 'concurrency_limit', 'is_admin',
                  'approved_at', 'created_at']
        read_only_fields = ['approved_at', 'created_at']

    def _is_admin(self, obj):
        return obj.role == 'admin' or obj.user.is_superuser

    def get_concurrency_limit(self, obj):
        """admin/superuser 返回后台实际档位（AI_SCREEN_ADMIN_CONCURRENCY），普通用户返回字段值"""
        if self._is_admin(obj):
            from django.conf import settings
            return getattr(settings, 'AI_SCREEN_ADMIN_CONCURRENCY', 16)
        return obj.concurrency_limit

    def get_quota_projects(self, obj):
        """admin/superuser 项目配额，与实际限制一致（当前无硬性限制，返回原始值）"""
        return obj.quota_projects

    def get_quota_storage_mb(self, obj):
        """admin/superuser 存储配额，与实际限制一致（当前无硬性限制，返回原始值）"""
        return obj.quota_storage_mb


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'code', 'name', 'category', 'description', 'is_system']


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_superuser', 'date_joined', 'profile', 'permissions']
        read_only_fields = ['date_joined']

    def get_permissions(self, obj):
        """返回用户的权限列表"""
        if obj.is_superuser:
            return ['*']

        from django.db.models import Q
        perms = UserPermission.objects.filter(
            user=obj
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).values_list('permission__code', flat=True)

        return list(perms)


# ============================================================================
# 任务相关 Serializers
# ============================================================================

class TaskSerializer(serializers.ModelSerializer):
    """
    任务序列化器

    新增字段：
    - progress_percentage: 百分比形式进度（0-100）
    - duration: 运行时长（秒）
    - is_async: 是否异步任务
    - log_metadata: 解析后的日志元信息
    """
    progress_percentage = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    is_async = serializers.SerializerMethodField()
    log_metadata = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = ['id', 'project', 'task_type', 'celery_task_id', 'status', 'progress',
                  'progress_percentage', 'duration', 'is_async',
                  'result', 'logs', 'log_metadata', 'error_message', 'config',
                  'started_at', 'completed_at', 'created_at', 'updated_at', 'created_by']
        read_only_fields = ['status', 'celery_task_id', 'started_at', 'completed_at',
                            'created_at', 'updated_at']

    def get_progress_percentage(self, obj):
        """转换为百分比"""
        return round(obj.progress * 100, 2)

    def get_duration(self, obj):
        """计算运行时长（秒）"""
        if obj.started_at:
            if obj.completed_at:
                delta = obj.completed_at - obj.started_at
            else:
                delta = timezone.now() - obj.started_at
            return delta.total_seconds()
        return None

    def get_is_async(self, obj):
        """判断是否异步任务"""
        from .step_config import is_async_step
        return is_async_step(obj.task_type)

    def get_log_metadata(self, obj):
        """解析日志元信息"""
        if not obj.logs:
            return None

        try:
            return json.loads(obj.logs)
        except (json.JSONDecodeError, TypeError):
            return None


class TaskBriefSerializer(serializers.ModelSerializer):
    """任务简要信息（用于嵌套显示）"""
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = ['id', 'task_type', 'status', 'progress_percentage', 'created_at']

    def get_progress_percentage(self, obj):
        return round(obj.progress * 100, 2)


# ============================================================================
# 步骤相关 Serializers
# ============================================================================

class StageStepSerializer(serializers.ModelSerializer):
    """
    步骤序列化器

    新增字段：
    - progress_percentage: 从独立JSON文件读取的进度
    - duration: 运行时长（秒）
    - latest_task: 最近一次任务
    """
    progress_percentage = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    latest_task = serializers.SerializerMethodField()

    class Meta:
        model = StageStep
        fields = ['id', 'step_key', 'name', 'order', 'status', 'can_skip',
                  'progress_percentage', 'duration', 'latest_task',
                  'started_at', 'completed_at', 'metadata', 'created_at', 'updated_at']
        read_only_fields = ['status', 'started_at', 'completed_at', 'created_at', 'updated_at']

    def get_progress_percentage(self, obj):
        """从独立JSON文件读取进度"""
        # 尝试从metadata读取
        if obj.metadata and 'progress' in obj.metadata:
            return obj.metadata['progress']

        # 状态映射
        status_map = {
            StageStepStatus.COMPLETED: 100.0,
            StageStepStatus.SKIPPED: 100.0,
            StageStepStatus.PENDING: 0.0,
            StageStepStatus.IN_PROGRESS: 50.0,
            StageStepStatus.STOPPED: 0.0,
            StageStepStatus.FAILED: 0.0,
        }
        return status_map.get(obj.status, 0.0)

    def get_duration(self, obj):
        """计算运行时长（秒）"""
        if obj.started_at:
            if obj.completed_at:
                delta = obj.completed_at - obj.started_at
            else:
                delta = timezone.now() - obj.started_at
            return delta.total_seconds()
        return None

    def get_latest_task(self, obj):
        """获取最近一次任务"""
        task = Task.objects.filter(
            project=obj.stage.project,
            task_type=obj.step_key
        ).order_by('-created_at').first()

        return TaskBriefSerializer(task).data if task else None


class StageStepBriefSerializer(serializers.ModelSerializer):
    """步骤简要信息（用于嵌套显示）"""
    class Meta:
        model = StageStep
        fields = ['id', 'step_key', 'name', 'status', 'order', 'can_skip', 'metadata']


# ============================================================================
# 阶段相关 Serializers
# ============================================================================

class ProjectStageSerializer(serializers.ModelSerializer):
    """
    阶段序列化器

    新增字段：
    - progress_percentage: 聚合子步骤进度
    - duration: 运行时长（秒）
    - steps: 嵌套的步骤列表
    """
    steps = StageStepBriefSerializer(many=True, read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()

    class Meta:
        model = ProjectStage
        fields = ['id', 'stage_key', 'name', 'order', 'status',
                  'progress_percentage', 'duration',
                  'started_at', 'completed_at', 'metadata', 'steps',
                  'created_at', 'updated_at']
        read_only_fields = ['status', 'started_at', 'completed_at', 'created_at', 'updated_at']

    def get_progress_percentage(self, obj):
        """聚合子步骤进度"""
        steps = obj.steps.all()
        if not steps:
            # 状态映射
            status_map = {
                ProjectStageStatus.COMPLETED: 100.0,
                ProjectStageStatus.SKIPPED: 100.0,
                ProjectStageStatus.PENDING: 0.0,
                ProjectStageStatus.IN_PROGRESS: 50.0,
                ProjectStageStatus.STOPPED: 0.0,
                ProjectStageStatus.FAILED: 0.0,
            }
            return status_map.get(obj.status, 0.0)

        # 计算平均进度
        total = 0
        count = 0
        for step in steps:
            if step.status == StageStepStatus.COMPLETED:
                total += 100
            elif step.status == StageStepStatus.SKIPPED:
                total += 100
            elif step.status in (StageStepStatus.PENDING, StageStepStatus.STOPPED, StageStepStatus.FAILED):
                total += 0
            elif step.metadata and 'progress' in step.metadata:
                total += step.metadata['progress']
            else:
                total += 50  # in_progress 默认50%
            count += 1

        return round(total / count, 2) if count > 0 else 0.0

    def get_duration(self, obj):
        """计算运行时长（秒）"""
        if obj.started_at:
            if obj.completed_at:
                delta = obj.completed_at - obj.started_at
            else:
                delta = timezone.now() - obj.started_at
            return delta.total_seconds()
        return None


class ProjectStageBriefSerializer(serializers.ModelSerializer):
    """阶段简要信息（用于嵌套显示）"""
    class Meta:
        model = ProjectStage
        fields = ['id', 'stage_key', 'name', 'status', 'order']


# ============================================================================
# 文件相关 Serializers
# ============================================================================

class DataFileVersionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = DataFileVersion
        fields = ['id', 'version', 'file_path', 'file_size', 'change_summary',
                  'metadata', 'created_by', 'created_by_username', 'created_at']
        read_only_fields = ['created_at']


class DataFileSerializer(serializers.ModelSerializer):
    versions_count = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    stage_name = serializers.CharField(source='stage.name', read_only=True)
    step_name = serializers.CharField(source='step.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = DataFile
        fields = ['id', 'project', 'stage', 'step', 'stage_name', 'step_name',
                  'filename', 'file', 'file_url',
                  'file_size', 'file_type', 'data_category', 'source', 'description',
                  'metadata', 'versions_count', 'created_by', 'created_by_username',
                  'created_at', 'updated_at']
        read_only_fields = ['file_size', 'file_type', 'created_at', 'updated_at']

    def get_versions_count(self, obj):
        return len(obj.versions.all())

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
        return None


class DataFileBriefSerializer(serializers.ModelSerializer):
    """文件简要信息（用于嵌套显示）"""
    class Meta:
        model = DataFile
        fields = ['id', 'filename', 'file_size', 'data_category', 'created_at']


# ============================================================================
# 项目相关 Serializers
# ============================================================================

class ProjectSerializer(serializers.ModelSerializer):
    """
    项目序列化器

    新增字段：
    - owner_username: 所有者用户名
    - progress_percentage: 整体进度
    - duration: 运行时长（秒）
    - stages_count: 阶段数
    - files_count: 文件数
    - stages: 嵌套的阶段列表
    """
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    stages = ProjectStageBriefSerializer(many=True, read_only=True)
    stages_count = serializers.SerializerMethodField()
    files_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'slug', 'description', 'owner', 'owner_username',
                  'status', 'progress_percentage', 'duration',
                  'metadata', 'stages', 'stages_count', 'files_count',
                  'created_at', 'updated_at']
        read_only_fields = ['owner', 'slug', 'created_at', 'updated_at']

    def get_progress_percentage(self, obj):
        """聚合所有阶段的进度"""
        stages = obj.stages.all()
        if not stages:
            return 0.0

        total = 0
        for stage in stages:
            status_map = {
                'completed': 100.0,
                'skipped': 100.0,
                'pending': 0.0,
                'in_progress': 50.0
            }
            total += status_map.get(stage.status, 0.0)

        return round(total / len(stages), 2)

    def get_duration(self, obj):
        """计算运行时长（秒）"""
        # 从第一个阶段的开始时间到最后一个阶段的完成时间
        first_stage = obj.stages.filter(started_at__isnull=False).order_by('started_at').first()
        last_stage = obj.stages.filter(completed_at__isnull=False).order_by('-completed_at').first()

        if first_stage:
            start = first_stage.started_at
            end = last_stage.completed_at if last_stage else timezone.now()
            return (end - start).total_seconds()
        return None

    def get_stages_count(self, obj):
        return obj.stages.count()

    def get_files_count(self, obj):
        return obj.files.count()


class ProjectBriefSerializer(serializers.ModelSerializer):
    """项目简要信息（用于列表显示）"""
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    stages_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'slug', 'owner_username', 'status', 'progress_percentage',
                  'stages_count', 'created_at', 'updated_at']

    def get_progress_percentage(self, obj):
        stages = obj.stages.all()
        if not stages:
            return 0.0

        completed = len([s for s in stages if s.status in ['completed', 'skipped']])
        return round(completed / len(stages) * 100, 2)

    def get_stages_count(self, obj):
        return obj.stages.count()


# ============================================================================
# 操作日志 Serializers
# ============================================================================

class ActivityLogSerializer(serializers.ModelSerializer):
    operation_type_display = serializers.CharField(source='get_operation_type_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ['id', 'project', 'operation_type', 'operation_type_display',
                  'operation_detail', 'created_by_name', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by else ''


# ============================================================================
# 操作日志 Serializers
# ============================================================================

class ActivityLogSerializer(serializers.ModelSerializer):
    operation_type_display = serializers.CharField(source='get_operation_type_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ['id', 'project', 'operation_type', 'operation_type_display',
                  'operation_detail', 'created_by_name', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by else ''


# ============================================================================
# 统计汇总 Serializers
# ============================================================================

class ProjectProgressSerializer(serializers.Serializer):
    """项目进度汇总（用于前端进度条显示）"""
    project_id = serializers.IntegerField()
    stages = serializers.DictField()
    overall_percentage = serializers.FloatField()
    elapsed_time = serializers.FloatField(allow_null=True)
    estimated_remaining = serializers.FloatField(allow_null=True)
