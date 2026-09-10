from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import FeedbackAttachment, FeedbackDailyQuota, UserFeedback


class FeedbackAttachmentInline(admin.TabularInline):
    model = FeedbackAttachment
    extra = 0
    can_delete = False
    fields = ('preview', 'original_name', 'mime_type', 'file_size', 'width', 'height', 'sha256', 'created_at')
    readonly_fields = fields

    @admin.display(description='预览')
    def preview(self, obj):
        if not obj.pk:
            return '-'
        url = reverse('feedback:attachment', args=[obj.pk])
        return format_html('<a href="{}" target="_blank"><img src="{}" width="120" loading="lazy"></a>', url, url)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UserFeedback)
class UserFeedbackAdmin(admin.ModelAdmin):
    list_display = ('display_code', 'category', 'reporter_username', 'status', 'page_path', 'attachment_count', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('display_code', 'reporter_username', 'content')
    list_select_related = ('user', 'project', 'resolved_by')
    raw_id_fields = ('user', 'project', 'resolved_by')
    readonly_fields = (
        'display_code', 'user', 'reporter_user_id', 'reporter_username', 'category', 'content',
        'project', 'page_path', 'route_name', 'client_request_id', 'context', 'resolved_by',
        'resolved_at', 'created_at', 'updated_at',
    )
    fields = (
        'display_code', 'status', 'admin_note', 'user', 'reporter_user_id', 'reporter_username',
        'category', 'content', 'project', 'page_path', 'route_name', 'client_request_id', 'context',
        'resolved_by', 'resolved_at', 'created_at', 'updated_at',
    )
    inlines = (FeedbackAttachmentInline,)
    actions = ('mark_reviewing', 'mark_resolved', 'mark_rejected')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_attachment_count=Count('attachments'))

    @admin.display(description='图片数', ordering='_attachment_count')
    def attachment_count(self, obj):
        return obj._attachment_count

    def save_model(self, request, obj, form, change):
        if obj.status in ('resolved', 'rejected'):
            obj.resolved_by = request.user
            obj.resolved_at = obj.resolved_at or timezone.now()
        elif obj.status in ('new', 'reviewing'):
            obj.resolved_by = None
            obj.resolved_at = None
        super().save_model(request, obj, form, change)

    def _set_status(self, request, queryset, value):
        updates = {'status': value, 'updated_at': timezone.now()}
        if value in ('resolved', 'rejected'):
            updates.update(resolved_by=request.user, resolved_at=timezone.now())
        else:
            updates.update(resolved_by=None, resolved_at=None)
        queryset.update(**updates)

    @admin.action(description='标记为处理中')
    def mark_reviewing(self, request, queryset):
        self._set_status(request, queryset, 'reviewing')

    @admin.action(description='标记为已解决')
    def mark_resolved(self, request, queryset):
        self._set_status(request, queryset, 'resolved')

    @admin.action(description='标记为无效')
    def mark_rejected(self, request, queryset):
        self._set_status(request, queryset, 'rejected')


@admin.register(FeedbackDailyQuota)
class FeedbackDailyQuotaAdmin(admin.ModelAdmin):
    list_display = ('user', 'quota_date', 'used_count', 'updated_at')
    list_filter = ('quota_date',)
    search_fields = ('user__username',)
    readonly_fields = ('user', 'quota_date', 'used_count', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
