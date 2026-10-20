"""全文自动查找绑定管道。"""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from core.models import DataFile, RescreenReference

from .base import ResolveResult, sanitize_filename
from .europe_pmc import EuropePmcResolver
from .local_pdf import LocalPdfResolver
from .openalex import OpenAlexResolver
from .unpaywall import UnpaywallResolver


def default_resolvers(project):
    """合法来源 resolver 顺序：本地复用 → 官方/开放获取来源。"""
    pdf_refs = list(RescreenReference.objects.filter(
        project=project,
        source_type='pdf_upload',
        fulltext_status='bound',
        fulltext_file__isnull=False,
    ).select_related('fulltext_file'))
    return [
        LocalPdfResolver(project, candidates=pdf_refs),
        EuropePmcResolver(),
        UnpaywallResolver(),
        OpenAlexResolver(),
    ]


def _create_downloaded_data_file(project, ref, result: ResolveResult, user=None):
    filename = sanitize_filename(result.filename or ref.doi or ref.title or f'rescreen-ref-{ref.id}.pdf')
    data_file = DataFile(
        project=project,
        filename=filename,
        source='imported',
        data_category='input',
        description=f'文献复筛自动查找全文：{result.resolver}',
        metadata={
            'resolver': result.resolver,
            'source': result.source,
            'source_url': result.source_url,
            'license': result.license,
            'reference_id': ref.id,
            'reference_title': ref.title,
        },
        created_by=user,
    )
    data_file.file.save(filename, ContentFile(result.content or b''), save=True)
    return data_file


def _append_attempts(ref, attempts):
    existing = ref.fulltext_attempts if isinstance(ref.fulltext_attempts, list) else []
    stamped = []
    now = timezone.now().isoformat()
    for attempt in attempts:
        stamped.append({'checked_at': now, **attempt})
    # 保留最近 30 条，避免 JSON 字段无限增长。
    return (existing + stamped)[-30:]


@transaction.atomic
def _bind_ref(ref, result: ResolveResult, attempts, user=None):
    if result.data_file is not None:
        data_file = result.data_file
    else:
        data_file = _create_downloaded_data_file(ref.project, ref, result, user=user)

    ref.fulltext_file = data_file
    ref.fulltext_status = 'bound'
    ref.fulltext_error = ''
    ref.fulltext_source = result.source or result.resolver
    ref.fulltext_source_url = result.source_url or ''
    ref.fulltext_license = result.license or ''
    ref.fulltext_resolver = result.resolver
    ref.fulltext_checked_at = timezone.now()
    ref.fulltext_attempts = _append_attempts(ref, attempts)
    ref.save(update_fields=[
        'fulltext_file',
        'fulltext_status',
        'fulltext_error',
        'fulltext_source',
        'fulltext_source_url',
        'fulltext_license',
        'fulltext_resolver',
        'fulltext_checked_at',
        'fulltext_attempts',
        'updated_at',
    ])
    return data_file


@transaction.atomic
def _mark_unresolved(ref, attempts):
    last_message = ''
    for attempt in reversed(attempts):
        if attempt.get('message'):
            last_message = attempt['message']
            break
    ref.fulltext_status = 'bind_failed'
    ref.fulltext_error = last_message or '未找到可自动绑定的开放全文 PDF，请人工上传全文'
    ref.fulltext_checked_at = timezone.now()
    ref.fulltext_attempts = _append_attempts(ref, attempts)
    ref.save(update_fields=['fulltext_status', 'fulltext_error', 'fulltext_checked_at', 'fulltext_attempts', 'updated_at'])


def auto_bind_fulltexts_with_resolvers(project, ref_ids=None, user=None, resolvers=None):
    """自动查找并绑定全文。\n\n只使用合法开放来源：项目内已上传 PDF、Europe PMC/PMC、Unpaywall。\n找到 PDF 后直接绑定；未找到则标记 bind_failed，用户可上传/更改。\n"""
    targets = RescreenReference.objects.filter(
        project=project,
        fulltext_status__in=['unbound', 'bind_failed'],
    ).select_related('fulltext_file')
    if ref_ids:
        targets = targets.filter(pk__in=list(dict.fromkeys(ref_ids)))
    target_list = list(targets)
    resolver_list = list(resolvers) if resolvers is not None else default_resolvers(project)

    bound_ids = []
    failed_ids = []
    all_attempts = []

    for ref in target_list:
        attempts = []
        bound = False
        for resolver in resolver_list:
            try:
                result = resolver.resolve(ref)
            except Exception as exc:  # resolver 失败不能中断整批文献。
                result = ResolveResult(False, getattr(resolver, 'name', resolver.__class__.__name__), 'error', str(exc))
            attempt = result.attempt_payload()
            attempts.append(attempt)
            all_attempts.append({'ref_id': ref.id, **attempt})
            if result.found:
                _bind_ref(ref, result, attempts, user=user)
                bound_ids.append(ref.id)
                bound = True
                break
        if not bound:
            _mark_unresolved(ref, attempts)
            failed_ids.append(ref.id)

    return {
        'searched': len(target_list),
        'bound': len(bound_ids),
        'failed': len(failed_ids),
        'bound_ids': bound_ids,
        'unbound_ids': failed_ids,
        'attempts': all_attempts,
    }
