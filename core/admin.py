from django import forms
from django.conf import settings
from django.contrib import admin
from .models import (
    UserProfile, Permission, UserPermission, RoleTemplate,
    RoleTemplatePermission, Project, ProjectStage, StageStep,
    DataFile, DataFileVersion, Task, ManualReview, QAEvaluationRun,
    QAFulltextAsset, QAModelSignalResult, QAReviewContext, ServiceContactSetting,
    SystemOperationState,
)
from .models_billing import (
    CreditAccount, CreditTransaction, TokenUsageLog, RechargeCode,
    PlanCatalog, PlanPriceVersion, UserPlanEntitlement, PlanBillingPeriod,
    CreditGrantBatch, CreditAllocation, ModelBillingRate, ModelUsageDetail,
    CreditReservation, CreditReservationAllocation,
    AddonProduct, AddonProductVersion, UserConcurrencyGrant,
)


class UserProfileAdminForm(forms.ModelForm):
    """Validate user quotas and concurrency edited through Django Admin."""

    quota_projects = forms.IntegerField(
        label='旧版项目配额',
        min_value=-1,
        help_text='仅兼容旧逻辑；新版实际上限由套餐或“项目配额覆盖”决定。',
    )
    quota_storage_mb_override = forms.IntegerField(
        label='存储配额覆盖(MB)',
        min_value=-1,
        required=False,
        help_text='留空时跟随当前套餐；-1 表示不限。计入索引、PDF、派生文本、导出产物和反馈图片。',
    )

    concurrency_limit = forms.IntegerField(
        label='旧版 AI 筛选并发数',
        min_value=1,
    )
    quota_projects_override = forms.IntegerField(
        label='项目配额覆盖', required=False, min_value=-1,
        help_text='留空时使用当前套餐或免费默认值；-1 表示不限额。',
    )
    ai_call_slots_override = forms.IntegerField(
        label='AI 调用槽位覆盖', required=False, min_value=1,
        help_text='留空时使用当前套餐或免费默认值。该值是用户跨任务共享的总槽位。',
    )

    class Meta:
        model = UserProfile
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        max_concurrency = settings.AI_SCREEN_MAX_GLOBAL_THREADS
        field = self.fields['concurrency_limit']
        field.widget.attrs['max'] = max_concurrency
        field.help_text = (
            '仅供关闭新版套餐开关时兼容旧逻辑；新版请使用“AI 调用槽位覆盖”。'
        )
        self.fields['ai_call_slots_override'].widget.attrs['max'] = max_concurrency

    def clean_concurrency_limit(self):
        value = self.cleaned_data['concurrency_limit']
        max_concurrency = settings.AI_SCREEN_MAX_GLOBAL_THREADS
        if value > max_concurrency:
            raise forms.ValidationError(f'并发数不能超过全局上限 {max_concurrency}')
        return value

    def clean_ai_call_slots_override(self):
        value = self.cleaned_data.get('ai_call_slots_override')
        if value is not None and value > settings.AI_SCREEN_MAX_GLOBAL_THREADS:
            raise forms.ValidationError(
                f'槽位覆盖不能超过全局上限 {settings.AI_SCREEN_MAX_GLOBAL_THREADS}'
            )
        return value


class BillingAuditAdmin(admin.ModelAdmin):
    """计费审计表只允许查看，禁止人工改写历史快照。"""

    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionError('计费审计模型不允许从 Admin 修改历史快照')


class BillingVersionAdmin(admin.ModelAdmin):
    """Draft versions are editable; published pricing snapshots are immutable."""

    actions = ['publish_selected_versions']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != 'draft':
            return tuple(field.name for field in self.model._meta.fields)
        return ('status', 'created_at')

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            current = self.model.objects.only('status').get(pk=obj.pk)
            if current.status != 'draft':
                raise PermissionError('已发布或停用的计费版本不可修改')
        obj.status = 'draft'
        super().save_model(request, obj, form, change)

    @admin.action(description='发布所选草稿版本')
    def publish_selected_versions(self, request, queryset):
        from django.contrib import messages
        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        from django.template.response import TemplateResponse

        drafts = queryset.filter(status='draft')
        if request.POST.get('confirm_publish') == 'yes':
            targets = self.get_publish_queryset(drafts)
            published_objects = list(targets)
            count = targets.update(status='published')
            for obj in published_objects:
                obj.status = 'published'
                self.log_change(request, obj, '通过计费版本发布操作设为已发布')
            self.message_user(request, f'已发布 {count} 条版本记录。', messages.SUCCESS)
            return None
        context = {
            **self.admin_site.each_context(request),
            'title': '确认发布计费版本',
            'opts': self.model._meta,
            'queryset': drafts,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
            'action_name': 'publish_selected_versions',
        }
        return TemplateResponse(request, 'admin/billing_publish_confirm.html', context)

    def get_publish_queryset(self, queryset):
        return queryset


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    form = UserProfileAdminForm
    list_display = [
        'user', 'role', 'current_plan', 'effective_ai_call_slots',
        'effective_project_limit', 'storage_quota_display',
        'is_approved', 'approved_at', 'created_at',
    ]
    list_filter = ['role', 'is_approved']
    search_fields = ['user__username', 'user__email']
    list_select_related = ['user']
    readonly_fields = [
        'current_plan', 'effective_ai_call_slots', 'effective_project_limit',
        'storage_usage_display', 'quota_projects', 'concurrency_limit',
        'quota_storage_mb',
        'created_at', 'updated_at',
    ]
    
    fieldsets = (
        ('用户信息', {
            'fields': ('user', 'role')
        }),
        ('当前生效权益', {
            'fields': (
                'current_plan', 'effective_ai_call_slots', 'effective_project_limit',
                'storage_usage_display',
            )
        }),
        ('管理员覆盖与存储限制', {
            'fields': (
                'quota_projects_override', 'ai_call_slots_override',
                'quota_storage_mb_override',
            )
        }),
        ('旧版兼容字段', {
            'fields': ('quota_projects', 'concurrency_limit', 'quota_storage_mb'),
            'classes': ('collapse',),
            'description': '新版套餐开启后不参与实际权益计算。',
        }),
        ('审核状态', {
            'fields': ('is_approved', 'approved_at', 'approved_by')
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def _entitlements(self, obj):
        cached = getattr(obj, '_admin_entitlements_cache', None)
        if cached is None:
            from core.services.entitlement_service import resolve_user_entitlements

            cached = resolve_user_entitlements(obj.user, sync=False)
            obj._admin_entitlements_cache = cached
        return cached

    @admin.display(description='当前套餐')
    def current_plan(self, obj):
        if not obj or not obj.pk:
            return '-'
        value = self._entitlements(obj)
        return f'{value.plan_name} ({value.plan_code})'

    @admin.display(description='实际 AI 调用槽位', ordering='ai_call_slots_override')
    def effective_ai_call_slots(self, obj):
        return self._entitlements(obj).ai_call_slots if obj and obj.pk else '-'

    @admin.display(description='实际项目上限', ordering='quota_projects_override')
    def effective_project_limit(self, obj):
        if not obj or not obj.pk:
            return '-'
        value = self._entitlements(obj).project_limit
        return '不限' if value < 0 else value

    @admin.display(description='存储上限')
    def storage_quota_display(self, obj):
        if not obj or not obj.pk:
            return '-'
        value = self._entitlements(obj).storage_limit_mb
        return '不限' if value < 0 else f'{value} MB'

    @admin.display(description='存储用量 / 上限')
    def storage_usage_display(self, obj):
        if not obj or not obj.pk:
            return '-'
        from core.services.storage_quota_service import storage_quota_snapshot

        snapshot = storage_quota_snapshot(obj.user)
        limit = '不限' if snapshot.limit_mb is None else f'{snapshot.limit_mb} MB'
        return f'{snapshot.used_mb:.1f} MB / {limit}'


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


@admin.register(SystemOperationState)
class SystemOperationStateAdmin(admin.ModelAdmin):
    list_display = [
        'mode', 'message', 'announcement_enabled', 'announcement_message',
        'scheduled_at', 'updated_by', 'updated_at',
    ]
    readonly_fields = ['updated_by', 'updated_at']

    def has_add_permission(self, request):
        return not SystemOperationState.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


class ServiceContactSettingAdminForm(forms.ModelForm):
    class Meta:
        model = ServiceContactSetting
        fields = '__all__'

    def clean_wechat_qr(self):
        uploaded = self.cleaned_data.get('wechat_qr')
        if not uploaded or not hasattr(uploaded, 'temporary_file_path') and not getattr(uploaded, 'content_type', None):
            return uploaded

        from core.service_contact.validators import validate_service_contact_qr
        from core.services.image_validation import ImageValidationError

        try:
            return validate_service_contact_qr(uploaded).content
        except ImageValidationError as exc:
            raise forms.ValidationError(str(exc)) from exc


@admin.register(ServiceContactSetting)
class ServiceContactSettingAdmin(admin.ModelAdmin):
    form = ServiceContactSettingAdminForm
    list_display = [
        'display_name', 'enabled', 'wechat_id', 'contact_email',
        'service_hours', 'updated_by', 'updated_at',
    ]
    readonly_fields = ['updated_by', 'updated_at']
    fieldsets = (
        ('入口状态', {'fields': ('enabled', 'description')}),
        ('联系方式', {
            'fields': ('display_name', 'wechat_id', 'wechat_qr', 'contact_email', 'service_hours'),
        }),
        ('安全提示', {'fields': ('security_notice',)}),
        ('审计信息', {'fields': ('updated_by', 'updated_at'), 'classes': ('collapse',)}),
    )

    def has_add_permission(self, request):
        return not ServiceContactSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        old_qr_name = ''
        if change:
            old_qr_name = (
                ServiceContactSetting.objects.filter(pk=obj.pk)
                .values_list('wechat_qr', flat=True)
                .first() or ''
            )
        obj.updated_by = request.user
        obj.full_clean(exclude=['wechat_qr'])
        super().save_model(request, obj, form, change)
        new_qr_name = obj.wechat_qr.name if obj.wechat_qr else ''
        if old_qr_name and old_qr_name != new_qr_name:
            obj.wechat_qr.storage.delete(old_qr_name)


# ============================================================================
# 计费相关 Admin（阶段二/六）
# ============================================================================

class CreditTransactionInline(admin.TabularInline):
    model = CreditTransaction
    extra = 0
    readonly_fields = [
        'txn_type', 'amount', 'balance_after', 'idempotency_key',
        'note', 'created_at', 'created_by',
    ]
    ordering = ['-created_at']
    can_delete = False
    max_num = 20


@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display  = [
        'user', 'balance', 'total_granted', 'total_consumed',
        'ledger_difference', 'updated_at',
    ]
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['total_granted', 'total_consumed', 'created_at', 'updated_at']
    inlines = [CreditTransactionInline]

    fieldsets = (
        ('账户', {'fields': ('user', 'balance', 'total_granted', 'total_consumed')}),
        ('时间戳', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='账本差额')
    def ledger_difference(self, obj):
        from core.services.credit_ledger_service import account_reconciliation

        return account_reconciliation(obj)['difference']


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display  = [
        'account', 'txn_type', 'amount', 'balance_after',
        'idempotency_key', 'note', 'created_at', 'created_by',
    ]
    list_filter   = ['txn_type', 'created_at']
    search_fields = ['account__user__username', 'idempotency_key', 'note']
    readonly_fields = ['idempotency_key', 'created_at']
    raw_id_fields = ['account', 'task', 'created_by']


@admin.register(TokenUsageLog)
class TokenUsageLogAdmin(admin.ModelAdmin):
    list_display = [
        'task', 'project', 'user', 'model', 'total_tokens', 'credits_consumed',
        'shadow_credits', 'estimated_cost_cny', 'pricing_version', 'created_at',
    ]
    list_filter = ['pricing_version', 'created_at']
    search_fields = ['user__username', 'project__name', 'model']
    readonly_fields = [field.name for field in TokenUsageLog._meta.fields]
    raw_id_fields = ['task', 'project', 'user', 'transaction']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RechargeCode)
class RechargeCodeAdmin(admin.ModelAdmin):
    list_display  = [
        'code', 'code_type', 'plan_price_version', 'addon_version', 'credits', 'valid_months',
        'batch_no', 'created_by', 'is_used', 'used_by_display', 'used_at',
        'expires_at', 'note', 'created_at',
    ]
    list_filter   = ['code_type', 'is_used', 'plan_price_version__plan', 'created_at']
    search_fields = ['code', 'note', 'used_by__username']
    readonly_fields = ['created_by', 'is_used', 'used_by', 'used_at', 'created_at']

    @admin.display(description='使用者', ordering='used_by__username')
    def used_by_display(self, obj):
        if obj.used_by_id and obj.used_by:
            return obj.used_by.username
        if obj.is_used:
            return '已使用（原用户已删除）'
        return '-'

    fieldsets = (
        ('兑换码信息', {
            'fields': (
                'code', 'code_type', 'credits', 'plan_price_version', 'addon_version',
                'valid_months', 'batch_no', 'note', 'expires_at',
            ),
            'description': '积分码填写 credits；套餐码选择套餐版本；加购码选择商品版本且 credits 填 0。商品权益及有效期均由版本决定。',
        }),
        ('使用状态（只读）', {
            'fields': ('is_used', 'used_by', 'used_at'),
            'classes': ('collapse',),
        }),
        ('时间戳', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

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
        import secrets
        from django.core.exceptions import PermissionDenied
        from django.db import transaction
        from django.shortcuts import render
        from django.contrib import messages
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime
        from core.services.recharge_code_service import (
            create_secure_recharge_code,
            normalize_recharge_code_prefix,
        )

        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == 'POST':
            try:
                count   = max(1, min(500, int(request.POST.get('count', 10))))
                code_type = request.POST.get('code_type', 'CREDIT').upper()
                if code_type not in {'CREDIT', 'PLAN', 'ADDON'}:
                    raise ValueError('不支持的兑换码类型')
                credits = max(0 if code_type == 'PLAN' else 1, int(request.POST.get('credits', 100)))
                if code_type in {'PLAN', 'ADDON'}:
                    credits = 0
                prefix = normalize_recharge_code_prefix(request.POST.get('prefix') or code_type)
                note    = request.POST.get('note', '').strip()
                expires = request.POST.get('expires_at', '').strip() or None
                batch_no = request.POST.get('batch_no', '').strip()[:64]
                if not batch_no:
                    batch_no = f"ADMIN-{timezone.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3).upper()}"
                valid_months = max(1, min(36, int(request.POST.get('valid_months', 1))))
                plan_version = None
                addon_version = None
                if code_type == 'ADDON':
                    addon_version = AddonProductVersion.objects.get(
                        pk=int(request.POST.get('addon_version')), status='published', product__is_active=True,
                    )
                if code_type == 'PLAN':
                    from core.models_billing import PlanPriceVersion
                    plan_version = PlanPriceVersion.objects.get(
                        pk=int(request.POST.get('plan_price_version')),
                        status='published',
                    )

                expires_at = None
                if expires:
                    expires_at = parse_datetime(expires + ':00') if len(expires) == 16 else parse_datetime(expires)
                    if expires_at is None:
                        raise ValueError('过期时间格式无效')
                    if timezone.is_naive(expires_at):
                        expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
                    if expires_at <= timezone.now():
                        raise ValueError('过期时间必须晚于当前时间')

                created = []
                with transaction.atomic():
                    for _ in range(count):
                        obj = create_secure_recharge_code(
                            prefix=prefix,
                            code_type=code_type,
                            credits=credits,
                            plan_price_version=plan_version,
                            addon_version=addon_version,
                            valid_months=valid_months,
                            batch_no=batch_no,
                            note=note,
                            expires_at=expires_at,
                            created_by=request.user,
                        )
                        self.log_addition(
                            request,
                            obj,
                            f'后台批量生成；发行批次 {batch_no}',
                        )
                        created.append(obj.code)

                label = (
                    f'{plan_version.plan.name} × {valid_months}个月'
                    if plan_version else f'{credits} credits/张'
                )
                if addon_version:
                    label = str(addon_version)
                messages.success(request, f'成功生成 {len(created)} 张兑换码（{label}）')
                return render(request, 'admin/rechargecode_batch_result.html', {
                    'title': '批量生成兑换码',
                    'codes': created,
                    'codes_text': '\n'.join(created),
                    'credits': credits,
                    'summary': label,
                    'batch_no': batch_no,
                    'opts': self.model._meta,
                })
            except Exception as e:
                messages.error(request, f'生成失败：{e}')

        from core.models_billing import PlanPriceVersion
        return render(request, 'admin/rechargecode_batch_generate.html', {
            'title': '批量生成兑换码',
            'opts': self.model._meta,
            'addon_versions': AddonProductVersion.objects.filter(status='published', product__is_active=True).select_related('product'),
            'plan_versions': PlanPriceVersion.objects.filter(
                status='published', plan__is_active=True,
            ).select_related('plan').order_by('monthly_price_cny'),
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
        'project', 'screening_run', 'reference', 'ai_decision', 'decision',
        'is_override', 'reviewer', 'reviewed_at'
    ]
    list_filter   = ['decision', 'ai_decision', 'is_override', 'project']
    search_fields = ['reference__title', 'reason', 'ai_reason', 'project__name', 'reviewer__username']
    readonly_fields = [
        'screening_run', 'ai_decision', 'ai_reason', 'is_override',
        'reviewed_at', 'created_at',
    ]

    fieldsets = (
        ('文献信息', {
            'fields': ('project', 'step', 'screening_run', 'reference'),
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

@admin.register(QAFulltextAsset)
class QAFulltextAssetAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'project', 'qa_reference', 'status', 'scan_status',
        'extraction_status', 'page_count', 'extracted_page_count',
        'extraction_truncated', 'chunk_count', 'size_bytes', 'created_at',
    ]
    list_filter = [
        'status', 'scan_status', 'extraction_status', 'extraction_truncated', 'created_at',
    ]
    search_fields = ['original_filename', 'sha256', 'qa_reference__title', 'project__name']
    readonly_fields = [
        'project', 'qa_reference', 'raw_file', 'extracted_text_file', 'chunk_index_file',
        'original_filename', 'sha256', 'size_bytes', 'mime_type', 'page_count',
        'scan_status', 'extraction_status', 'extracted_text_sha256',
        'extracted_text_chars', 'extraction_version', 'extracted_page_count',
        'extraction_truncated', 'truncated_at_page', 'chunk_index_sha256',
        'chunk_count', 'chunking_version', 'error_code', 'error_message', 'validated_at',
        'scanned_at', 'extracted_at', 'created_at', 'updated_at',
    ]
    raw_id_fields = ['project', 'qa_reference']

    def has_add_permission(self, request):
        return False


@admin.register(QAReviewContext)
class QAReviewContextAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'project', 'quality_method', 'method_variant', 'updated_by', 'updated_at',
    ]
    list_filter = ['quality_method', 'method_variant', 'updated_at']
    search_fields = [
        'project__name', 'target_population', 'index_test', 'target_condition',
        'reference_standard', 'review_objective',
    ]
    raw_id_fields = ['project', 'created_by', 'updated_by']
    readonly_fields = ['context_version', 'created_at', 'updated_at']


@admin.register(QAEvaluationRun)
class QAEvaluationRunAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'run_uuid', 'project', 'status', 'requested_count', 'validated_count',
        'failed_count', 'created_by', 'created_at',
    ]
    list_filter = ['status', 'protocol_version', 'retrieval_version', 'created_at']
    search_fields = ['run_uuid', 'idempotency_key', 'project__name']
    raw_id_fields = ['project', 'task', 'created_by']
    readonly_fields = [field.name for field in QAEvaluationRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QAModelSignalResult)
class QAModelSignalResultAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'evaluation_run', 'qa_reference', 'signal_key', 'model_id', 'status',
        'attempt_count', 'updated_at',
    ]
    list_filter = ['status', 'model_id', 'prompt_version', 'created_at']
    search_fields = [
        'qa_reference__title', 'signal_key', 'model_id', 'error_code', 'error_message',
    ]
    raw_id_fields = ['evaluation_run', 'qa_reference']
    readonly_fields = [field.name for field in QAModelSignalResult._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlanCatalog)
class PlanCatalogAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    readonly_fields = ['created_at', 'updated_at']

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AddonProduct)
class AddonProductAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'kind', 'is_active', 'sort_order']
    list_filter = ['kind', 'is_active']

    def get_readonly_fields(self, request, obj=None):
        return ('code', 'kind') if obj and obj.versions.exists() else ()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AddonProductVersion)
class AddonProductVersionAdmin(BillingVersionAdmin):
    list_display = ['product', 'version', 'status', 'reference_price_cny', 'reference_cost',
                    'credits', 'target_slots', 'valid_months', 'requires_subscription']
    list_filter = ['kind', 'status']
    actions = ['publish_selected_versions', 'revoke_selected_versions']

    @admin.display(description='模型参考成本（不含平台成本）')
    def reference_cost(self, obj):
        from decimal import Decimal
        return f'¥{obj.credits * Decimal("0.00216"):.2f}' if obj.credits else '容量成本待测'

    def get_publish_queryset(self, queryset):
        for obj in queryset:
            obj.full_clean()
        return queryset

    @admin.action(description='撤销所选商品版本（未使用码将不可兑换）')
    def revoke_selected_versions(self, request, queryset):
        for obj in queryset.filter(status='published'):
            obj.status = 'revoked'
            obj.save(update_fields=['status'])
            self.log_change(request, obj, '撤销商品版本；已生效权益不受影响')


@admin.register(UserConcurrencyGrant)
class UserConcurrencyGrantAdmin(BillingAuditAdmin):
    list_display = ['user', 'version', 'starts_at', 'expires_at', 'cancelled']
    raw_id_fields = ['user', 'source_code']


@admin.register(PlanPriceVersion)
class PlanPriceVersionAdmin(BillingVersionAdmin):
    list_display = [
        'plan', 'version', 'status', 'monthly_price_cny', 'included_credits',
        'ai_call_slots', 'project_limit', 'storage_limit_mb',
    ]
    list_filter = ['status', 'plan']
    search_fields = ['plan__code', 'plan__name', 'version']


@admin.register(UserPlanEntitlement)
class UserPlanEntitlementAuditAdmin(BillingAuditAdmin):
    list_display = ['user', 'price_version', 'status', 'starts_at', 'expires_at']
    list_filter = ['status', 'price_version__plan']
    raw_id_fields = ['user', 'source_recharge_code']


@admin.register(PlanBillingPeriod)
class PlanBillingPeriodAuditAdmin(BillingAuditAdmin):
    list_display = ['entitlement', 'period_start', 'period_end', 'grant_status', 'grant_batch']
    list_filter = ['grant_status']


@admin.register(CreditGrantBatch)
class CreditGrantBatchAuditAdmin(BillingAuditAdmin):
    list_display = [
        'batch_key', 'account', 'batch_type', 'granted_amount', 'remaining_amount',
        'reserved_amount', 'expires_at',
    ]
    list_filter = ['batch_type', 'expires_at']


@admin.register(CreditAllocation)
class CreditAllocationAuditAdmin(BillingAuditAdmin):
    list_display = ['transaction', 'batch', 'allocation_type', 'amount', 'created_at']
    list_filter = ['allocation_type']


@admin.register(ModelBillingRate)
class ModelBillingRateAdmin(BillingVersionAdmin):
    list_display = [
        'rate_key', 'version', 'status', 'provider', 'model_id', 'region',
        'service_tier', 'input_cny_per_million', 'output_cny_per_million',
        'cache_read_cny_per_million', 'context_min_tokens', 'context_max_tokens',
    ]
    list_filter = ['status', 'version', 'provider', 'region', 'service_tier']
    search_fields = ['rate_key', 'model_id', 'provider_model']

    def get_publish_queryset(self, queryset):
        versions = list(queryset.values_list('version', flat=True).distinct())
        if not versions:
            return self.model.objects.none()
        return self.model.objects.filter(
            version__in=versions,
            status='draft',
        )


@admin.register(ModelUsageDetail)
class ModelUsageDetailAuditAdmin(BillingAuditAdmin):
    list_display = [
        'usage_log', 'call_index', 'provider', 'model_id', 'input_tokens',
        'output_tokens', 'cache_read_tokens', 'raw_credits', 'estimated_cost_cny',
        'rate', 'attempt_reason', 'charge_bearer',
    ]
    list_filter = ['provider', 'model_id', 'attempt_reason', 'charge_bearer']
    search_fields = ['provider_request_id', 'model_id', 'user__username']


@admin.register(CreditReservation)
class CreditReservationAuditAdmin(BillingAuditAdmin):
    list_display = [
        'idempotency_key', 'account', 'task', 'status', 'pricing_version',
        'estimated_credits', 'reserved_credits', 'actual_credits',
        'settled_credits', 'platform_covered_credits',
    ]
    list_filter = ['status', 'pricing_version']


@admin.register(CreditReservationAllocation)
class CreditReservationAllocationAuditAdmin(BillingAuditAdmin):
    list_display = [
        'reservation', 'batch', 'reserved_amount', 'consumed_amount',
        'additional_consumed_amount', 'released_amount',
    ]


# 初筛数据库化模型按领域拆分，Admin 自动发现仍从 core.admin 进入。
from core.screening import admin as _screening_admin  # noqa: E402,F401
