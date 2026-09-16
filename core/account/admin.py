from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse

from core.models import UserProfile
from core.models_billing import CreditAccount

from .models import (
    AccountAdminAuditEvent,
    AccountEmail,
    AccountEmailChangeRequest,
    AccountSecurityEvent,
    AccountVerificationToken,
    AgreementAcceptance,
)
from .services.security_audit import record_admin_event

User = get_user_model()


class AccountEmailInline(admin.StackedInline):
    model = AccountEmail
    extra = 0
    can_delete = False
    readonly_fields = ('email', 'normalized_email', 'verified_at', 'created_at', 'updated_at')

    def has_add_permission(self, request, obj=None):
        return False


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    fk_name = 'user'
    extra = 0
    can_delete = False
    fields = ('role', 'is_banned', 'quota_projects', 'quota_storage_mb', 'concurrency_limit')


class CreditAccountInline(admin.StackedInline):
    model = CreditAccount
    extra = 0
    can_delete = False
    readonly_fields = ('balance', 'total_granted', 'total_consumed', 'created_at', 'updated_at')

    def has_add_permission(self, request, obj=None):
        return False


class AgreementAcceptanceInline(admin.TabularInline):
    model = AgreementAcceptance
    extra = 0
    can_delete = False
    fields = ('document_type', 'version', 'content_sha256', 'accepted_at')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


admin.site.unregister(User)


@admin.register(User)
class PlatformUserAdmin(DjangoUserAdmin):
    inlines = (AccountEmailInline, UserProfileInline, CreditAccountInline, AgreementAcceptanceInline)
    list_select_related = ('profile', 'account_email', 'credit_account')
    list_display = DjangoUserAdmin.list_display + ('account_role', 'trusted_email_status', 'credit_balance')
    actions = ('ban_accounts', 'unban_accounts')

    @admin.display(description='平台角色')
    def account_role(self, obj):
        return getattr(getattr(obj, 'profile', None), 'get_role_display', lambda: '-')()

    @admin.display(description='可信邮箱')
    def trusted_email_status(self, obj):
        identity = getattr(obj, 'account_email', None)
        return '已验证' if identity and identity.verified_at else '未验证/未绑定'

    @admin.display(description='积分余额')
    def credit_balance(self, obj):
        return getattr(getattr(obj, 'credit_account', None), 'balance', '-')

    def save_model(self, request, obj, form, change):
        before = {}
        if change:
            previous = User.objects.get(pk=obj.pk)
            before = {field: getattr(previous, field) for field in form.changed_data}
        super().save_model(request, obj, form, change)
        if change and form.changed_data:
            record_admin_event(
                request=request,
                action='user_change',
                target_user=obj,
                reason='Django Admin 修改用户',
                before=before,
                after={field: getattr(obj, field) for field in form.changed_data},
            )

    def save_formset(self, request, form, formset, change):
        changed = [
            (
                item.instance,
                list(item.changed_data),
                {field: item.initial.get(field) for field in item.changed_data},
            )
            for item in formset.forms if item.changed_data and item.instance.pk
        ]
        super().save_formset(request, form, formset, change)
        for instance, fields, before in changed:
            if isinstance(instance, UserProfile):
                record_admin_event(
                    request=request,
                    action='profile_change',
                    target_user=instance.user,
                    reason='Django Admin 修改角色、封禁状态或配额',
                    before=before,
                    after={field: getattr(instance, field) for field in fields},
                )

    def delete_model(self, request, obj):
        record_admin_event(
            request=request, action='user_delete', target_user=obj,
            reason='Django Admin 删除用户', before={'is_active': obj.is_active},
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            record_admin_event(
                request=request, action='user_delete', target_user=obj,
                reason='Django Admin 批量删除用户', before={'is_active': obj.is_active},
            )
        super().delete_queryset(request, queryset)

    def _account_state_action(self, request, queryset, *, banned, action_name, audit_action):
        if request.POST.get('confirmed') == 'yes':
            reason = request.POST.get('reason', '').strip()
            if not reason:
                self.message_user(request, '必须填写操作原因。', level=messages.ERROR)
                return None
            for user in queryset.select_related('profile'):
                before = {'is_banned': user.profile.is_banned}
                user.profile.is_banned = banned
                user.profile.save(update_fields=['is_banned', 'updated_at'])
                record_admin_event(
                    request=request, action=audit_action, target_user=user, reason=reason,
                    before=before, after={'is_banned': banned},
                )
            self.message_user(request, f'已处理 {queryset.count()} 个账户。')
            return None
        return TemplateResponse(request, 'admin/account/confirm_user_action.html', {
            **self.admin_site.each_context(request),
            'title': '确认敏感账户操作',
            'users': queryset,
            'action_name': action_name,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
        })

    @admin.action(description='封禁所选账户（需要原因）')
    def ban_accounts(self, request, queryset):
        return self._account_state_action(
            request, queryset, banned=True,
            action_name='ban_accounts', audit_action='account_ban',
        )

    @admin.action(description='解除所选账户封禁（需要原因）')
    def unban_accounts(self, request, queryset):
        return self._account_state_action(
            request, queryset, banned=False,
            action_name='unban_accounts', audit_action='account_unban',
        )


@admin.register(AccountEmail)
class AccountEmailAdmin(admin.ModelAdmin):
    list_display = ['email', 'user', 'verified_at', 'created_at']
    list_filter = ['verified_at', 'created_at']
    search_fields = ['email', 'normalized_email', 'user__username']
    readonly_fields = ['normalized_email', 'verified_at', 'created_at', 'updated_at']
    raw_id_fields = ['user']


@admin.register(AccountVerificationToken)
class AccountVerificationTokenAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'purpose', 'expires_at', 'used_at', 'revoked_at',
        'sent_at', 'send_attempts', 'created_at',
    ]
    list_filter = ['purpose', 'used_at', 'revoked_at', 'created_at']
    search_fields = ['user__username', 'account_email__email']
    readonly_fields = [
        'user', 'account_email', 'purpose', 'token_digest', 'expires_at',
        'used_at', 'revoked_at', 'sent_at', 'send_attempts', 'last_error', 'created_at',
    ]
    raw_id_fields = ['user', 'account_email']


@admin.register(AccountEmailChangeRequest)
class AccountEmailChangeRequestAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'new_email', 'expires_at', 'used_at', 'revoked_at',
        'sent_at', 'send_attempts', 'created_at',
    ]
    list_filter = ['used_at', 'revoked_at', 'created_at']
    search_fields = ['user__username', 'new_email', 'normalized_new_email']
    readonly_fields = [
        'user', 'new_email', 'normalized_new_email', 'token_digest', 'expires_at',
        'used_at', 'revoked_at', 'sent_at', 'send_attempts', 'last_error', 'created_at',
    ]
    raw_id_fields = ['user']


@admin.register(AgreementAcceptance)
class AgreementAcceptanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'document_type', 'version', 'accepted_at')
    list_filter = ('document_type', 'version', 'accepted_at')
    search_fields = ('user__username',)
    readonly_fields = [field.name for field in AgreementAcceptance._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        route_name = getattr(getattr(request, 'resolver_match', None), 'url_name', '')
        return obj is not None and route_name in {'auth_user_delete', 'auth_user_changelist'}


@admin.register(AccountSecurityEvent)
class AccountSecurityEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'outcome', 'user', 'ip_masked', 'created_at')
    list_filter = ('event_type', 'outcome', 'created_at')
    search_fields = ('user__username', 'identifier_hash', 'ip_hash')
    readonly_fields = [field.name for field in AccountSecurityEvent._meta.fields]
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccountAdminAuditEvent)
class AccountAdminAuditEventAdmin(admin.ModelAdmin):
    list_display = ('action', 'actor', 'target_username_snapshot', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('actor__username', 'target_username_snapshot')
    readonly_fields = [field.name for field in AccountAdminAuditEvent._meta.fields]
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
