from django.contrib import admin
from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    RoleTemplatePermission, Project, ProjectStage, StageStep,
    DataFile, DataFileVersion, Task, ManualReview
)
from .models_billing import CreditAccount, CreditTransaction, TokenUsageLog, RechargeCode


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


# ============================================================================
# 计费相关 Admin（阶段二/六）
# ============================================================================

class CreditTransactionInline(admin.TabularInline):
    model = CreditTransaction
    extra = 0
    readonly_fields = ['txn_type', 'amount', 'balance_after', 'note', 'created_at', 'created_by']
    ordering = ['-created_at']
    can_delete = False
    max_num = 20


@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display  = ['user', 'balance', 'total_granted', 'total_consumed', 'updated_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['total_granted', 'total_consumed', 'created_at', 'updated_at']
    inlines = [CreditTransactionInline]

    fieldsets = (
        ('账户', {'fields': ('user', 'balance', 'total_granted', 'total_consumed')}),
        ('时间戳', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display  = ['account', 'txn_type', 'amount', 'balance_after', 'note', 'created_at', 'created_by']
    list_filter   = ['txn_type', 'created_at']
    search_fields = ['account__user__username', 'note']
    readonly_fields = ['created_at']
    raw_id_fields = ['account', 'task', 'created_by']


@admin.register(RechargeCode)
class RechargeCodeAdmin(admin.ModelAdmin):
    list_display  = ['code', 'credits', 'is_used', 'used_by', 'used_at', 'expires_at', 'note', 'created_at']
    list_filter   = ['is_used', 'created_at']
    search_fields = ['code', 'note', 'used_by__username']
    readonly_fields = ['is_used', 'used_by', 'used_at', 'created_at']

    fieldsets = (
        ('兑换码信息', {
            'fields': ('code', 'credits', 'note', 'expires_at'),
            'description': '码格式建议：FREE-XXXX-XXXX，credits 为面值（正整数）',
        }),
        ('使用状态（只读）', {
            'fields': ('is_used', 'used_by', 'used_at'),
            'classes': ('collapse',),
        }),
        ('时间戳', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        # 已使用的码：全部只读，防止误修改
        if obj and obj.is_used:
            return [f.name for f in self.model._meta.fields]
        return self.readonly_fields

    # ── 批量生成兑换码 ──────────────────────────────────────────
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom = [
            path('batch-generate/', self.admin_site.admin_view(self.batch_generate_view), name='rechargecode_batch_generate'),
        ]
        return custom + urls

    def batch_generate_view(self, request):
        import random, string
        from django.shortcuts import render
        from django.contrib import messages
        from core.models_billing import RechargeCode

        def _gen(prefix):
            chars = string.ascii_uppercase + string.digits
            return f"{prefix}-{''.join(random.choices(chars,k=4))}-{''.join(random.choices(chars,k=4))}"

        if request.method == 'POST':
            try:
                count   = max(1, min(500, int(request.POST.get('count', 10))))
                credits = max(1, int(request.POST.get('credits', 100)))
                prefix  = (request.POST.get('prefix') or 'FREE').strip().upper()[:10]
                note    = request.POST.get('note', '').strip()
                expires = request.POST.get('expires_at', '').strip() or None

                created = []
                for _ in range(count):
                    for _retry in range(10):
                        code = _gen(prefix)
                        if not RechargeCode.objects.filter(code=code).exists():
                            break
                    obj = RechargeCode(code=code, credits=credits, note=note)
                    if expires:
                        from django.utils.dateparse import parse_datetime
                        obj.expires_at = parse_datetime(expires + ':00') if len(expires) == 16 else parse_datetime(expires)
                    obj.save()
                    created.append(code)

                messages.success(request, f'成功生成 {len(created)} 张兑换码（{credits} credits/张）')
                return render(request, 'admin/rechargecode_batch_result.html', {
                    'title': '批量生成兑换码',
                    'codes': created,
                    'codes_text': '\n'.join(created),
                    'credits': credits,
                    'opts': self.model._meta,
                })
            except Exception as e:
                messages.error(request, f'生成失败：{e}')

        return render(request, 'admin/rechargecode_batch_generate.html', {
            'title': '批量生成兑换码',
            'opts': self.model._meta,
        })

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['batch_generate_url'] = 'batch-generate/'
        return super().changelist_view(request, extra_context=extra_context)


# ─────────────────────────────────────────────────────────────────────────────
# 人工审阅
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(ManualReview)
class ManualReviewAdmin(admin.ModelAdmin):
    list_display  = [
        'project', 'source_xml_short', 'ai_decision', 'decision',
        'is_override', 'reviewer', 'reviewed_at'
    ]
    list_filter   = ['decision', 'ai_decision', 'is_override', 'project']
    search_fields = ['source_xml', 'reason', 'ai_reason', 'project__name', 'reviewer__username']
    readonly_fields = ['ai_decision', 'ai_reason', 'is_override', 'reviewed_at', 'created_at']

    fieldsets = (
        ('文献信息', {
            'fields': ('project', 'step', 'source_xml'),
        }),
        ('AI 判断（只读）', {
            'fields': ('ai_decision', 'ai_reason'),
            'classes': ('collapse',),
        }),
        ('人工决定', {
            'fields': ('decision', 'reason', 'reviewer', 'is_override'),
        }),
        ('时间戳', {
            'fields': ('reviewed_at', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='XML 文件名')
    def source_xml_short(self, obj):
        name = obj.source_xml.split('/')[-1]
        return name[:60] + '…' if len(name) > 60 else name
