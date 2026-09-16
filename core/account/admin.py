from django.contrib import admin

from .models import AccountEmail, AccountEmailChangeRequest, AccountVerificationToken


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
