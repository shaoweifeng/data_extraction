from django.contrib import admin

from .models import RescreenCorpus, RescreenImportBatch, RescreenImportFile, RescreenReference, RescreenReferenceRawMetadata


class RescreenAuditAdmin(admin.ModelAdmin):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields if field.name not in (self.exclude or ()))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Allow the superuser's parent cascade, never direct deletion of audit rows.
        return request.user.is_superuser and request.path.startswith(('/admin/auth/user/', '/admin/core/project/'))


@admin.register(RescreenCorpus)
class CorpusAdmin(RescreenAuditAdmin):
    list_display = ['project', 'revision', 'active_reference_count', 'updated_at']


@admin.register(RescreenImportBatch)
class ImportAdmin(RescreenAuditAdmin):
    list_display = ['id', 'project', 'source_type', 'status', 'accepted_count', 'rejected_count', 'error_code', 'task']
    list_filter = ['status', 'source_type']


@admin.register(RescreenImportFile)
class SourceFileAdmin(RescreenAuditAdmin):
    exclude = ['raw_file']  # FileField's default readonly renderer calls the forbidden public .url.
    list_display = ['id', 'batch', 'original_filename', 'size_bytes', 'sha256']


@admin.register(RescreenReference)
class ReferenceAdmin(RescreenAuditAdmin):
    list_display = ['id', 'project', 'title', 'publication_year', 'doi', 'introduced_revision', 'removed_revision']
    search_fields = ['title', 'doi', 'source_key']


@admin.register(RescreenReferenceRawMetadata)
class RawMetadataAdmin(RescreenAuditAdmin):
    list_display = ['reference', 'input_version', 'source_format', 'raw_size_bytes']


from core.fulltext.models import FulltextAsset
from core.rescreening.models import FulltextLookupJob, FulltextLookupItem, FulltextCandidate
from core.rescreening.models import RescreenRun, RescreenRunItem, RescreenModelResult, RescreenCall
from core.rescreening.models import RescreenSettings, RescreenReview, RescreenReviewEvent
from core.rescreening.models import RescreenExport, RescreenExportItem


@admin.register(RescreenExport)
class ExportAdmin(RescreenAuditAdmin):
    exclude = ['output']
    list_display = ['id', 'project', 'format', 'scope', 'mode', 'status', 'total_count', 'output_size', 'created_at']


@admin.register(RescreenExportItem)
class ExportItemAdmin(RescreenAuditAdmin):
    list_display = ['id', 'export', 'reference_id_snapshot', 'asset_id']


@admin.register(FulltextAsset)
class FulltextAssetAdmin(RescreenAuditAdmin):
    exclude = ['raw_file', 'extracted_text_file', 'chunk_index_file']
    list_display = ['id', 'project', 'original_filename', 'status', 'page_count', 'chunk_count', 'error_code']
    list_filter = ['status', 'scan_status', 'extraction_status']
    search_fields = ['original_filename', 'sha256', 'primary_doi']


@admin.register(FulltextLookupJob)
class LookupJobAdmin(RescreenAuditAdmin):
    list_display = ['id', 'project', 'mode', 'status', 'processed_count', 'received_bytes', 'error_code']


@admin.register(FulltextLookupItem)
class LookupItemAdmin(RescreenAuditAdmin):
    list_display = ['id', 'job', 'reference_id', 'status', 'error_code']


@admin.register(FulltextCandidate)
class CandidateAdmin(RescreenAuditAdmin):
    list_display = ['id', 'item', 'source', 'asset', 'confidence', 'license', 'status']


@admin.register(RescreenRun)
class RunAdmin(RescreenAuditAdmin):
    list_display = ['id', 'corpus', 'status', 'input_revision', 'total_count', 'processed_count', 'task', 'pricing_version']
    list_filter = ['status', 'pricing_version']


@admin.register(RescreenRunItem)
class RunItemAdmin(RescreenAuditAdmin):
    list_display = ['id', 'run', 'reference_id', 'status', 'consensus', 'input_version']


@admin.register(RescreenModelResult)
class ModelResultAdmin(RescreenAuditAdmin):
    list_display = ['id', 'item', 'model_id', 'status', 'decision', 'error_code']


@admin.register(RescreenCall)
class CallAdmin(RescreenAuditAdmin):
    list_display = ['id', 'result', 'task', 'attempt', 'status', 'error_code', 'created_at']


@admin.register(RescreenSettings)
class SettingsAdmin(RescreenAuditAdmin):
    list_display = ['corpus', 'version', 'updated_by', 'updated_at']


@admin.register(RescreenReview)
class ReviewAdmin(RescreenAuditAdmin):
    list_display = ['reference_id', 'input_version', 'decision', 'version', 'reviewed_by', 'updated_at']


@admin.register(RescreenReviewEvent)
class ReviewEventAdmin(RescreenAuditAdmin):
    list_display = ['review_id', 'version', 'created_by', 'created_at']
