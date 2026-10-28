"""Validate the finite shared-fulltext resource boundaries on startup."""
import os
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def validate_settings():
    for name in ('RESCREEN_EXPORT_MAX_BYTES', 'RESCREEN_EXPORT_RETENTION_DAYS', 'RESCREEN_EXPORT_RATE_PER_MINUTE',
                 'RESCREEN_EXPORT_SOFT_TIME_LIMIT', 'RESCREEN_EXPORT_HARD_TIME_LIMIT'):
        if getattr(settings, name) <= 0:
            raise ImproperlyConfigured(f'{name} 必须为正数。')
    if settings.RESCREEN_EXPORT_HARD_TIME_LIMIT <= settings.RESCREEN_EXPORT_SOFT_TIME_LIMIT:
        raise ImproperlyConfigured('复筛导出硬超时必须大于软超时。')
    from core.rescreening.storage import PrivateRescreenExportStorage
    export_root = os.path.realpath(PrivateRescreenExportStorage().location)
    media_root = os.path.realpath(settings.MEDIA_ROOT)
    if os.path.commonpath([export_root, media_root]) == media_root:
        raise ImproperlyConfigured('RESCREEN_EXPORT_UPLOAD_ROOT 不能位于公开 MEDIA_ROOT 内。')
    for name in ('FULLTEXT_MAX_PENDING_PER_USER', 'FULLTEXT_MAX_ASSETS_PER_PROJECT',
            'FULLTEXT_UPLOAD_RATE_PER_MINUTE', 'FULLTEXT_LOOKUP_MAX_REFERENCES',
            'FULLTEXT_LOOKUP_MAX_REQUESTS', 'FULLTEXT_LOOKUP_MAX_BYTES', 'FULLTEXT_LOOKUP_DAILY_BYTES',
            'FULLTEXT_LOOKUP_RATE_PER_MINUTE', 'FULLTEXT_LOOKUP_TIMEOUT', 'FULLTEXT_LOOKUP_DOWNLOAD_SECONDS',
            'FULLTEXT_LOOKUP_MAX_JSON_BYTES', 'FULLTEXT_LOOKUP_MAX_CANDIDATES',
            'FULLTEXT_LOOKUP_SOFT_TIME_LIMIT', 'FULLTEXT_LOOKUP_HARD_TIME_LIMIT'):
        if getattr(settings, name) <= 0:
            raise ImproperlyConfigured(f'{name} 必须为正数。')
    from core.rescreening.services.ai_protocol import limits_snapshot
    from core.rescreening.errors import RescreenError
    try:
        limits_snapshot()
    except RescreenError as exc:
        raise ImproperlyConfigured(str(exc)) from exc
    if (settings.RESCREEN_AI_SOFT_TIME_LIMIT <= 0 or settings.RESCREEN_AI_HARD_TIME_LIMIT <= settings.RESCREEN_AI_SOFT_TIME_LIMIT
            or settings.RESCREEN_AI_RATE_PER_MINUTE <= 0 or settings.RESCREEN_AI_MAX_ACTIVE_PER_USER <= 0):
        raise ImproperlyConfigured('复筛 AI 超时或启动限额无效。')
    if settings.FULLTEXT_LOOKUP_MAX_REDIRECTS < 0 or settings.FULLTEXT_LOOKUP_HARD_TIME_LIMIT <= settings.FULLTEXT_LOOKUP_SOFT_TIME_LIMIT:
        raise ImproperlyConfigured('全文重定向次数必须非负，硬超时必须大于软超时。')
    root, public = os.path.realpath(settings.FULLTEXT_UPLOAD_ROOT), os.path.realpath(settings.MEDIA_ROOT)
    if os.path.commonpath([root, public]) == public:
        raise ImproperlyConfigured('FULLTEXT_UPLOAD_ROOT 不能位于公开 MEDIA_ROOT 内。')
