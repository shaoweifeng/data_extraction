"""Read-oriented Django Admin views for screening storage and audit records."""

from django.contrib import admin

from core.screening.models import (
    DedupRun,
    ReferenceDuplicateGroup,
    ReferenceDuplicateMember,
    ReferenceImportBatch,
    ReferenceImportFile,
    ReferenceImportIssue,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningReferenceRawMetadata,
    ScreeningResult,
    ScreeningRun,
)


class OperationalRecordAdmin(admin.ModelAdmin):
    """Operational data is mutated by services, not manually through Admin."""

    list_per_page = 50

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.concrete_fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ScreeningCorpus)
class ScreeningCorpusAdmin(OperationalRecordAdmin):
    list_display = [
        'project', 'revision', 'active_reference_count',
        'active_source_file_count', 'updated_at',
    ]
    search_fields = ['project__name', 'project__owner__username']
    list_select_related = ['project']


@admin.register(ReferenceImportBatch)
class ReferenceImportBatchAdmin(OperationalRecordAdmin):
    list_display = [
        'id', 'project', 'operation', 'status', 'base_revision',
        'target_revision', 'accepted_count', 'error_count', 'created_at',
    ]
    list_filter = ['operation', 'status', 'created_at']
    search_fields = ['project__name', 'created_by__username', 'task__celery_task_id']
    list_select_related = ['project', 'created_by', 'task']


@admin.register(ReferenceImportFile)
class ReferenceImportFileAdmin(OperationalRecordAdmin):
    exclude = ['raw_file']
    list_display = [
        'id', 'original_filename', 'source_format', 'parse_status',
        'parsed_count', 'skipped_count', 'warning_count', 'error_count',
    ]
    list_filter = ['source_format', 'parse_status', 'issues_truncated']
    search_fields = ['original_filename', 'sha256', 'import_batch__project__name']
    list_select_related = ['import_batch', 'source_file']

    def get_readonly_fields(self, request, obj=None):
        return tuple(
            field.name for field in self.model._meta.concrete_fields
            if field.name != 'raw_file'
        )


@admin.register(ReferenceImportIssue)
class ReferenceImportIssueAdmin(OperationalRecordAdmin):
    list_display = ['id', 'import_file', 'severity', 'code', 'record_position', 'created_at']
    list_filter = ['severity', 'code', 'created_at']
    search_fields = ['import_file__original_filename', 'source_identifier', 'title_preview', 'message']
    list_select_related = ['import_file']


@admin.register(ScreeningReference)
class ScreeningReferenceAdmin(OperationalRecordAdmin):
    list_display = [
        'id', 'title_preview', 'project', 'source_record_index',
        'introduced_revision', 'removed_revision',
    ]
    list_filter = ['introduced_revision', 'removed_revision']
    search_fields = ['title', 'doi', 'source_identifier', 'project__name']
    list_select_related = ['project', 'import_file']

    @admin.display(description='标题')
    def title_preview(self, obj):
        return obj.title[:100]


@admin.register(ScreeningReferenceRawMetadata)
class ScreeningReferenceRawMetadataAdmin(OperationalRecordAdmin):
    list_display = [
        'id', 'reference', 'import_file', 'source_format',
        'raw_size_bytes', 'parser_version', 'created_at',
    ]
    list_filter = ['source_format', 'parser_version', 'created_at']
    search_fields = ['reference__title', 'import_file__original_filename', 'raw_hash']
    list_select_related = ['reference', 'import_file']


@admin.register(DedupRun)
class DedupRunAdmin(OperationalRecordAdmin):
    list_display = [
        'id', 'project', 'corpus_revision', 'status', 'total_count',
        'duplicate_count', 'group_count', 'created_at',
    ]
    list_filter = ['status', 'rule_version', 'created_at']
    search_fields = ['project__name', 'created_by__username', 'task__celery_task_id']
    list_select_related = ['project', 'created_by', 'task']


@admin.register(ReferenceDuplicateGroup)
class ReferenceDuplicateGroupAdmin(OperationalRecordAdmin):
    list_display = ['id', 'dedup_run', 'sequence', 'match_type', 'member_count', 'title_preview']
    list_filter = ['match_type']
    search_fields = ['display_title', 'match_key_hash', 'dedup_run__project__name']
    list_select_related = ['dedup_run', 'representative_reference']

    @admin.display(description='标题')
    def title_preview(self, obj):
        return obj.display_title[:100]


@admin.register(ReferenceDuplicateMember)
class ReferenceDuplicateMemberAdmin(OperationalRecordAdmin):
    list_display = ['id', 'dedup_run', 'group', 'reference', 'role', 'match_score']
    list_filter = ['role']
    search_fields = ['reference__title', 'match_reason', 'dedup_run__project__name']
    list_select_related = ['dedup_run', 'group', 'reference']


@admin.register(ScreeningRun)
class ScreeningRunAdmin(OperationalRecordAdmin):
    list_display = [
        'id', 'project', 'corpus_revision', 'status', 'processed_count',
        'included_count', 'excluded_count', 'uncertain_count', 'created_at',
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['project__name', 'created_by__username', 'task__celery_task_id']
    list_select_related = ['project', 'created_by', 'task']


@admin.register(ScreeningResult)
class ScreeningResultAdmin(OperationalRecordAdmin):
    list_display = [
        'id', 'screening_run', 'reference', 'status', 'decision',
        'attempt_count', 'updated_at',
    ]
    list_filter = ['status', 'decision', 'updated_at']
    search_fields = ['reference__title', 'reference__doi', 'error_code']
    list_select_related = ['screening_run', 'reference']
