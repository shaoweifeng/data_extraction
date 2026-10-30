"""Persistent settings, bounded query state and versioned human review for SCREEN_2."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery, BooleanField, Case, When, Value
from core.models import ActivityLog, Project
from core.rescreening.errors import RescreenError
from core.rescreening.models import (RescreenCorpus, RescreenSettings, RescreenCriteriaRevision,
    RescreenReference, RescreenRunItem, RescreenReview, RescreenReviewEvent)
from core.rescreening.services.ai_protocol import PROMPT, normalize_criteria, limits_snapshot
from core.rescreening.services.ai_runs import _permission, ACTIVE_RUN_STATUSES
from core.rescreening.services.imports import _require_idle
from core.services.access_policy import ProjectAccessPolicy
from core.services.ai_models_config import get_model_config


def configuration(project, user=None):
    corpus = RescreenCorpus.objects.filter(project=project).first()
    config = RescreenSettings.objects.filter(corpus=corpus).first() if corpus else None
    criteria = corpus.criteria_versions.order_by('-revision').first() if corpus else None
    data = {'version': config.version if config else 0, 'criteria_revision_id': criteria.pk if criteria else None,
            'criteria': criteria.criteria if criteria else [], 'model_ids': config.model_ids if config else []}
    if user and ProjectAccessPolicy.can_configure_screening_prompt(user):
        data['custom_prompt'] = config.custom_prompt if config else ''
        data['protocol_prompt'] = PROMPT
    return data


def prompt_configuration(project):
    config = RescreenSettings.objects.filter(corpus__project=project).first()
    return ((config.custom_prompt + '\n\n' if config and config.custom_prompt else '') + PROMPT,
            config.version if config else 0)


def save_configuration(*, project, user, expected_version, criteria, model_ids, custom_prompt=None):
    _permission(project, user)
    rows = normalize_criteria(criteria, limits_snapshot())
    if (not isinstance(model_ids, list) or len(model_ids) > 6
            or any(not isinstance(value, str) or not get_model_config(value) for value in model_ids)):
        raise RescreenError('invalid_models', '无效的模型列表。')
    model_ids = list(dict.fromkeys(get_model_config(value)['id'] for value in model_ids))
    if custom_prompt is not None:
        if not ProjectAccessPolicy.can_configure_screening_prompt(user):
            raise RescreenError('permission_denied', '无权修改 Prompt。', status=403)
        if not isinstance(custom_prompt, str) or len(custom_prompt) > 5000:
            raise RescreenError('invalid_prompt', '补充提示不能超过 5000 字符。')
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        Project.objects.select_for_update().get(pk=project.pk)
        _require_idle(project)
        corpus, _ = RescreenCorpus.objects.get_or_create(project=project)
        config, _ = RescreenSettings.objects.get_or_create(corpus=corpus)
        if config.version != expected_version:
            raise RescreenError('settings_conflict', '设置已在其他页面修改，请刷新后再保存。', status=409)
        last = corpus.criteria_versions.order_by('-revision').first()
        criteria_changed = not last or last.criteria != rows
        effective_prompt = custom_prompt.strip() if custom_prompt is not None else config.custom_prompt
        if not criteria_changed and config.model_ids == model_ids and config.custom_prompt == effective_prompt:
            return configuration(project, user)
        if criteria_changed:
            RescreenCriteriaRevision.objects.create(corpus=corpus, revision=last.revision+1 if last else 1,
                                                    criteria=rows, created_by=user)
        config.version += 1
        config.model_ids, config.updated_by = model_ids, user
        if custom_prompt is not None:
            config.custom_prompt = custom_prompt.strip()
        config.save()
        ActivityLog.objects.create(project=project, created_by=user, operation_type='rescreen_settings_saved',
                                   operation_detail={'version': config.version, 'criteria_count': len(rows)})
    return configuration(project, user)


def reference_query(project):
    """All filters and counters use SQL, never a browser's current-page array."""
    corpus = RescreenCorpus.objects.filter(project=project).first()
    criteria = corpus.criteria_versions.order_by('-revision').first() if corpus else None
    latest = RescreenRunItem.objects.filter(reference_id=OuterRef('pk'), input_version=OuterRef('input_version'),
        run__criteria_revision=criteria).order_by('-run_id')
    queryset = RescreenReference.objects.active().filter(project=project).annotate(
        source_type=F('import_batch__source_type'),
        suggestion_id=Subquery(latest.values('pk')[:1]),
        suggestion_revision=Subquery(latest.values('result_revision')[:1]),
        suggestion_status=Subquery(latest.values('status')[:1]),
        suggestion_decision=Subquery(latest.values('consensus')[:1]),
    )
    matches = Q(current_review__input_version=F('input_version'), current_review__criteria_revision=criteria)
    matches &= (Q(current_review__run_item_id=F('suggestion_id'),
                  current_review__suggestion_revision=F('suggestion_revision'))
                | Q(current_review__run_item__isnull=True, suggestion_id__isnull=True))
    matches &= ~Q(current_review__decision='not_retrieved', current_binding__asset__status='ready')
    return queryset.annotate(review_valid=Case(When(matches & Q(current_review__isnull=False), then=Value(True)),
        default=Value(False), output_field=BooleanField()))


def reference_payload(ref):
    asset = ref.current_binding.asset if ref.current_binding_id else None
    ready = bool(asset and asset.status == 'ready' and asset.extraction_status == 'completed' and not asset.extraction_truncated)
    review = ref.current_review
    return {'id': ref.pk, 'title': ref.title, 'authors': ref.authors, 'publication_year': ref.publication_year,
            'doi': ref.doi, 'journal': ref.journal, 'input_version': ref.input_version,
            'source_type': ref.source_type,
            'asset_id': asset.pk if asset else None, 'fulltext_status': asset.status if asset else 'missing',
            'ai_ready': ready, 'suggestion_id': ref.suggestion_id, 'suggestion_revision': ref.suggestion_revision or 0,
            'suggestion_status': ref.suggestion_status, 'suggestion': ref.suggestion_decision,
            'review_version': review.version if review else 0, 'review_valid': ref.review_valid,
            'decision': review.decision if review and ref.review_valid else None,
            'needs_reconfirmation': bool(review and not ref.review_valid)}


def workspace_state(project, user):
    corpus = RescreenCorpus.objects.filter(project=project).first()
    refs = reference_query(project)
    ready = Q(current_binding__asset__status='ready', current_binding__asset__extraction_status='completed',
              current_binding__asset__extraction_truncated=False)
    counts = refs.aggregate(total=Count('pk'), ready=Count('pk', filter=ready),
        bound=Count('pk', filter=Q(current_binding__asset__status='ready')),
        missing=Count('pk', filter=Q(current_binding__isnull=True)),
        fulltext_failed=Count('pk', filter=Q(current_binding__asset__status__in=('failed', 'rejected'))),
        pending=Count('pk', filter=Q(review_valid=True, current_review__decision='pending')),
        conflict=Count('pk', filter=Q(suggestion_decision='conflict')),
        included=Count('pk', filter=Q(review_valid=True, current_review__decision='included')),
        excluded=Count('pk', filter=Q(review_valid=True, current_review__decision='excluded')),
        not_retrieved=Count('pk', filter=Q(review_valid=True, current_review__decision='not_retrieved')),
        needs_reconfirmation=Count('pk', filter=Q(review_valid=False, current_review__isnull=False)))
    counts['finalized'] = sum(counts[key] for key in ('included', 'excluded', 'not_retrieved'))
    counts['remaining'] = counts['total'] - counts['finalized']
    config = configuration(project, user)
    active_runs = corpus.runs.filter(status__in=ACTIVE_RUN_STATUSES).order_by('-pk').first() if corpus else None
    latest = corpus.runs.order_by('-pk').first() if corpus else None
    active_import = project.rescreen_imports.filter(status__in=('uploaded', 'importing', 'cancelling', 'ready')).exists()
    active_lookup = project.fulltext_lookup_jobs.filter(status__in=('pending', 'running', 'cancelling')).exists()
    processing_assets = project.shared_fulltext_assets.exclude(status__in=('ready', 'rejected', 'failed')).exists()
    busy = bool(active_runs or active_import or active_lookup)
    from core.rescreening.services.exports import fingerprint, current_final_export
    from core.rescreening.models import RescreenExport
    current_fingerprint = fingerprint(project)
    completed_export = current_final_export(project, current_fingerprint)
    export_busy = RescreenExport.objects.filter(project=project, status__in=('pending', 'running', 'cancelling')).exists()
    return {'revision': corpus.revision if corpus else 0, 'counts': counts, 'configuration': config,
        'fingerprint': current_fingerprint, 'export_completed_id': completed_export.pk if completed_export else None,
        'export_completion_kind': 'skipped' if completed_export and completed_export.format == 'skip' else 'generated' if completed_export else None,
        'export_busy': export_busy,
        'busy': busy, 'poll_required': busy or processing_assets or export_busy, 'current_run_id': corpus.current_run_id if corpus else None,
        'latest_run_id': latest.pk if latest else None, 'active_run_id': active_runs.pk if active_runs else None,
        'can_start': bool(counts['ready'] and config['criteria'] and not busy),
        'steps': [{'index': 1, 'enabled': True, 'completed': bool(counts['total'] and not active_import)},
                  {'index': 2, 'enabled': bool(counts['total']), 'completed': bool(counts['total'] and counts['ready']+counts['not_retrieved'] == counts['total'])},
                  {'index': 3, 'enabled': bool(counts['total']), 'completed': bool(config['criteria'])},
                  {'index': 4, 'enabled': bool(counts['total'] and config['criteria']),
                   'completed': bool(latest and latest.status == 'completed' and latest.input_revision == corpus.revision
                                     and latest.criteria_revision_id == config['criteria_revision_id']
                                     and latest.config_snapshot.get('settings_version', 0) == config['version'])},
                  {'index': 5, 'enabled': bool(counts['total']), 'completed': bool(counts['total'] and not counts['remaining'])},
                  {'index': 6, 'enabled': bool(counts['total']), 'completed': bool(completed_export and counts['total'] and not counts['remaining'])}],
        'capabilities': {'diagnostics': ProjectAccessPolicy.can_view_research_diagnostics(user),
                         'prompt': ProjectAccessPolicy.can_configure_screening_prompt(user),
                         'online_lookup': settings.FULLTEXT_LOOKUP_ENABLED,
                         'max_lookup': settings.FULLTEXT_LOOKUP_MAX_REFERENCES,
                         'max_run': settings.RESCREEN_MAX_RUN_REFERENCES}}


def save_review(*, project, user, reference_id, input_version, expected_version, criteria_revision_id,
                suggestion_id, suggestion_revision, decision, reason='', note=''):
    _permission(project, user)
    if decision not in ('included', 'excluded', 'pending', 'not_retrieved'):
        raise RescreenError('invalid_decision', '无效的人工决定。')
    if not isinstance(reason, str) or len(reason) > 2000 or not isinstance(note, str) or len(note) > 4000:
        raise RescreenError('invalid_review', '排除理由或备注超过长度限制。')
    if decision == 'excluded' and not reason.strip():
        raise RescreenError('reason_required', '排除时必须填写理由。')
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        Project.objects.select_for_update().get(pk=project.pk)
        _require_idle(project)
        ref = RescreenReference.objects.active().select_for_update().get(pk=reference_id, project=project)
        criteria = ref.corpus.criteria_versions.order_by('-revision').first()
        actual_criteria = criteria.pk if criteria else None
        current = reference_query(project).get(pk=ref.pk)
        if (ref.input_version != input_version or actual_criteria != criteria_revision_id
                or current.suggestion_id != suggestion_id or (current.suggestion_revision or 0) != suggestion_revision):
            raise RescreenError('review_input_conflict', '文献、标准或 AI 建议已变化，请刷新后再确认。', status=409)
        old = RescreenReview.objects.filter(reference=ref, input_version=input_version).first()
        if (old.version if old else 0) != expected_version:
            raise RescreenError('review_conflict', '审核已在另一页面更新，请刷新后再保存。', status=409)
        if (decision == 'not_retrieved' and ref.current_binding_id
                and ref.current_binding.asset.status not in ('failed', 'rejected')):
            raise RescreenError('fulltext_exists', '已存在可读全文或全文正在处理，不能标记全文未获取。')
        review = old or RescreenReview(reference=ref, input_version=input_version, version=0)
        review.version += 1
        review.decision, review.exclusion_reason, review.note = decision, reason.strip(), note.strip()
        review.run_item_id, review.suggestion_revision = suggestion_id, suggestion_revision
        review.criteria_revision, review.reviewed_by = criteria, user
        review.save()
        payload = {'decision': decision, 'exclusion_reason': review.exclusion_reason, 'note': review.note,
                   'input_version': input_version, 'criteria_revision_id': actual_criteria,
                   'run_item_id': suggestion_id, 'suggestion_revision': suggestion_revision}
        RescreenReviewEvent.objects.create(review=review, version=review.version, payload=payload, created_by=user)
        ref.current_review = review
        ref.save(update_fields=['current_review', 'updated_at'])
        ActivityLog.objects.create(project=project, created_by=user, operation_type='rescreen_review_saved',
            operation_detail={'reference_id': ref.pk, 'review_version': review.version, 'decision': decision})
        return review
