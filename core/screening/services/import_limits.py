"""Single source of truth for screening import resource limits."""

from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from core.screening.services.import_errors import ScreeningImportError


@dataclass(frozen=True)
class ImportLimits:
    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    warning_references: int
    max_references: int
    max_title_chars: int
    max_abstract_chars: int
    max_authors: int
    max_record_text_chars: int
    max_raw_metadata_bytes: int
    max_docx_entries: int
    max_docx_uncompressed_bytes: int
    max_reported_errors: int
    allow_partial: bool
    db_batch_size: int
    processing_batch_size: int
    max_concurrent_per_user: int
    max_concurrent_per_project: int
    rate_limit_window_seconds: int
    rate_limit_requests: int
    failed_retention_days: int

    @classmethod
    def from_settings(cls) -> 'ImportLimits':
        limits = cls(
            max_files=settings.SCREENING_IMPORT_MAX_FILES,
            max_file_bytes=settings.SCREENING_IMPORT_MAX_FILE_BYTES,
            max_total_bytes=settings.SCREENING_IMPORT_MAX_TOTAL_BYTES,
            warning_references=settings.SCREENING_IMPORT_WARNING_REFERENCES,
            max_references=settings.SCREENING_IMPORT_MAX_REFERENCES,
            max_title_chars=settings.SCREENING_IMPORT_MAX_TITLE_CHARS,
            max_abstract_chars=settings.SCREENING_IMPORT_MAX_ABSTRACT_CHARS,
            max_authors=settings.SCREENING_IMPORT_MAX_AUTHORS,
            max_record_text_chars=settings.SCREENING_IMPORT_MAX_RECORD_TEXT_CHARS,
            max_raw_metadata_bytes=settings.SCREENING_IMPORT_MAX_RAW_METADATA_BYTES,
            max_docx_entries=settings.SCREENING_IMPORT_MAX_DOCX_ENTRIES,
            max_docx_uncompressed_bytes=settings.SCREENING_IMPORT_MAX_DOCX_UNCOMPRESSED_BYTES,
            max_reported_errors=settings.SCREENING_IMPORT_MAX_REPORTED_ERRORS,
            allow_partial=settings.SCREENING_IMPORT_ALLOW_PARTIAL,
            db_batch_size=settings.SCREENING_IMPORT_DB_BATCH_SIZE,
            processing_batch_size=settings.SCREENING_PROCESSING_BATCH_SIZE,
            max_concurrent_per_user=settings.SCREENING_IMPORT_MAX_CONCURRENT_PER_USER,
            max_concurrent_per_project=settings.SCREENING_IMPORT_MAX_CONCURRENT_PER_PROJECT,
            rate_limit_window_seconds=settings.SCREENING_IMPORT_RATE_LIMIT_WINDOW_SECONDS,
            rate_limit_requests=settings.SCREENING_IMPORT_RATE_LIMIT_REQUESTS,
            failed_retention_days=settings.SCREENING_IMPORT_FAILED_RETENTION_DAYS,
        )
        limits.validate()
        return limits

    def validate(self) -> None:
        values = asdict(self)
        for name, value in values.items():
            if name == 'allow_partial':
                continue
            if not isinstance(value, int) or value <= 0:
                raise ImproperlyConfigured(f'{name} 必须是正整数，当前值为 {value!r}')
        if self.max_file_bytes > self.max_total_bytes:
            raise ImproperlyConfigured('SCREENING_IMPORT_MAX_FILE_BYTES 不能大于总大小上限')
        if self.warning_references > self.max_references:
            raise ImproperlyConfigured('SCREENING_IMPORT_WARNING_REFERENCES 不能大于篇数上限')
        if self.max_reported_errors > self.max_references:
            raise ImproperlyConfigured('SCREENING_IMPORT_MAX_REPORTED_ERRORS 不能大于篇数上限')
        if self.db_batch_size > self.max_references:
            raise ImproperlyConfigured('SCREENING_IMPORT_DB_BATCH_SIZE 不能大于篇数上限')

    def snapshot(self) -> dict:
        return asdict(self)


def validate_import_settings() -> None:
    ImportLimits.from_settings()


def validate_projected_reference_count(
    existing_count: int,
    incoming_count: int,
    limits: ImportLimits,
) -> int:
    """Validate the published + incoming boundary from one shared contract."""
    projected = int(existing_count) + int(incoming_count)
    if projected > limits.max_references:
        raise ScreeningImportError(
            'too_many_references',
            f'项目文献总数将超过 {limits.max_references} 篇上限。',
            details={
                'limit': limits.max_references,
                'current': int(existing_count),
                'incoming': int(incoming_count),
            },
        )
    return projected
