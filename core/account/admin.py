from django.contrib import admin

from .models import AccountEmail


@admin.register(AccountEmail)
class AccountEmailAdmin(admin.ModelAdmin):
    list_display = ['email', 'user', 'verified_at', 'created_at']
    list_filter = ['verified_at', 'created_at']
    search_fields = ['email', 'normalized_email', 'user__username']
    readonly_fields = ['normalized_email', 'verified_at', 'created_at', 'updated_at']
    raw_id_fields = ['user']
