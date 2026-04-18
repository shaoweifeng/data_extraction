from django.contrib import admin
from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    RoleTemplatePermission, Project, ProjectStage, StageStep,
    DataFile, DataFileVersion, Task
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'quota_projects', 'quota_storage_mb', 
                   'is_approved', 'approved_at', 'created_at']
    list_filter = ['role', 'is_approved']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('用户信息', {
            'fields': ('user', 'role')
        }),
        ('配额设置', {
            'fields': ('quota_projects', 'quota_storage_mb')
        }),
        ('审核状态', {
            'fields': ('is_approved', 'approved_at', 'approved_by')
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'category', 'is_system', 'created_at']
    list_filter = ['category', 'is_system']
    search_fields = ['code', 'name', 'description']
    readonly_fields = ['created_at']


@admin.register(UserPermission)
class UserPermissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'permission', 'granted_by', 'granted_at', 'expires_at']
    list_filter = ['permission__category']
    search_fields = ['user__username', 'permission__code']
    readonly_fields = ['granted_at']
    
    fieldsets = (
        ('权限信息', {
            'fields': ('user', 'permission')
        }),
        ('授予信息', {
            'fields': ('granted_by', 'granted_at', 'expires_at')
        }),
    )


class RoleTemplatePermissionInline(admin.TabularInline):
    model = RoleTemplatePermission
    extra = 1


@admin.register(RoleTemplate)
class RoleTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'is_system', 'created_at']
    list_filter = ['is_system']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    inlines = [RoleTemplatePermissionInline]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'owner', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'description', 'owner__username']
    readonly_fields = ['slug', 'created_at', 'updated_at']
    raw_id_fields = ['owner']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'slug', 'description', 'owner')
        }),
        ('状态', {
            'fields': ('status',)
        }),
        ('元数据', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ProjectStage)
class ProjectStageAdmin(admin.ModelAdmin):
    list_display = ['project', 'stage_key', 'name', 'order', 'status', 
                   'started_at', 'completed_at']
    list_filter = ['stage_key', 'status']
    search_fields = ['project__name', 'name']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['project']
    
    fieldsets = (
        ('阶段信息', {
            'fields': ('project', 'stage_key', 'name', 'order')
        }),
        ('状态', {
            'fields': ('status', 'started_at', 'completed_at')
        }),
        ('元数据', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(StageStep)
class StageStepAdmin(admin.ModelAdmin):
    list_display = ['stage', 'step_key', 'name', 'order', 'status', 
                   'can_skip', 'started_at', 'completed_at']
    list_filter = ['status', 'can_skip']
    search_fields = ['stage__project__name', 'name']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['stage']
    
    fieldsets = (
        ('步骤信息', {
            'fields': ('stage', 'step_key', 'name', 'order', 'can_skip')
        }),
        ('状态', {
            'fields': ('status', 'started_at', 'completed_at')
        }),
        ('元数据', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class DataFileVersionInline(admin.TabularInline):
    model = DataFileVersion
    extra = 0
    readonly_fields = ['version', 'created_at', 'created_by']


@admin.register(DataFile)
class DataFileAdmin(admin.ModelAdmin):
    list_display = ['filename', 'project', 'data_category', 'source', 
                   'file_size', 'created_at']
    list_filter = ['data_category', 'source', 'created_at']
    search_fields = ['filename', 'project__name', 'description']
    readonly_fields = ['file_size', 'file_type', 'created_at', 'updated_at']
    raw_id_fields = ['project', 'stage', 'step', 'created_by']
    inlines = [DataFileVersionInline]
    
    fieldsets = (
        ('文件信息', {
            'fields': ('project', 'filename', 'file', 'file_size', 'file_type')
        }),
        ('关联信息', {
            'fields': ('stage', 'step', 'created_by')
        }),
        ('分类信息', {
            'fields': ('data_category', 'source', 'description')
        }),
        ('元数据', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DataFileVersion)
class DataFileVersionAdmin(admin.ModelAdmin):
    list_display = ['data_file', 'version', 'change_summary', 'created_by', 'created_at']
    list_filter = ['created_at']
    search_fields = ['data_file__filename', 'change_summary']
    readonly_fields = ['created_at']
    raw_id_fields = ['data_file', 'created_by']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['project', 'task_type', 'status', 'progress', 
                   'started_at', 'completed_at', 'created_at']
    list_filter = ['task_type', 'status', 'created_at']
    search_fields = ['project__name', 'celery_task_id']
    readonly_fields = ['celery_task_id', 'created_at', 'updated_at']
    raw_id_fields = ['project', 'stage', 'step']
    
    fieldsets = (
        ('任务信息', {
            'fields': ('project', 'stage', 'step', 'task_type', 'celery_task_id')
        }),
        ('状态', {
            'fields': ('status', 'progress', 'started_at', 'completed_at')
        }),
        ('结果', {
            'fields': ('result', 'logs', 'error_message'),
            'classes': ('collapse',)
        }),
        ('配置', {
            'fields': ('config',),
            'classes': ('collapse',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
