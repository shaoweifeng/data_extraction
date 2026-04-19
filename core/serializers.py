from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    Project, ProjectStage, StageStep, DataFile, DataFileVersion, Task
)


# ============================================================================
# 用户相关 Serializers
# ============================================================================

class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = UserProfile
        fields = ['id', 'username', 'email', 'role', 'quota_projects', 'quota_storage_mb',
                  'is_approved', 'approved_at', 'created_at']
        read_only_fields = ['approved_at', 'created_at']


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'code', 'name', 'category', 'description', 'is_system']


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_superuser', 'date_joined', 'profile']
        read_only_fields = ['date_joined']


# ============================================================================
# 项目相关 Serializers
# ============================================================================

class StageStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = StageStep
        fields = ['id', 'step_key', 'name', 'order', 'status', 'can_skip',
                  'started_at', 'completed_at', 'metadata', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ProjectStageSerializer(serializers.ModelSerializer):
    steps = StageStepSerializer(many=True, read_only=True)
    
    class Meta:
        model = ProjectStage
        fields = ['id', 'stage_key', 'name', 'order', 'status',
                  'started_at', 'completed_at', 'metadata', 'steps',
                  'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class DataFileSerializer(serializers.ModelSerializer):
    versions_count = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = DataFile
        fields = ['id', 'project', 'stage', 'step', 'filename', 'file', 'file_url', 
                  'file_size', 'file_type', 'data_category', 'source', 'description', 
                  'metadata', 'versions_count', 'created_at', 'updated_at']
        read_only_fields = ['file_size', 'file_type', 'created_at', 'updated_at']
    
    def get_versions_count(self, obj):
        return obj.versions.count()
    
    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
        return None


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ['id', 'project', 'task_type', 'celery_task_id', 'status', 'progress',
                  'result', 'logs', 'error_message', 'config',
                  'started_at', 'completed_at', 'created_at', 'updated_at']
        read_only_fields = ['celery_task_id', 'created_at', 'updated_at']


class ProjectSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    stages = ProjectStageSerializer(many=True, read_only=True)
    stages_count = serializers.SerializerMethodField()
    files_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Project
        fields = ['id', 'name', 'slug', 'description', 'owner', 'owner_username',
                  'status', 'metadata', 'stages', 'stages_count', 'files_count',
                  'created_at', 'updated_at']
        read_only_fields = ['owner', 'slug', 'created_at', 'updated_at']
    
    def get_stages_count(self, obj):
        return obj.stages.count()
    
    def get_files_count(self, obj):
        return obj.files.count()


# ============================================================================
# 文件版本 Serializer
# ============================================================================

class DataFileVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataFileVersion
        fields = ['id', 'version', 'file_path', 'file_size', 'change_summary',
                  'metadata', 'created_by', 'created_at']
        read_only_fields = ['created_at']
