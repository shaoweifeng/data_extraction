"""Incremental SCREEN_2 → QA handoff. Existing evaluations are never rebuilt or overwritten."""
from itertools import islice
from django.contrib.auth import get_user_model
from django.db import transaction
from core.models import ActivityLog, Project, QAReference, Task
from core.rescreening.errors import RescreenError
from core.rescreening.models import QASourceBibliographySnapshot
from core.rescreening.services.ai_runs import _permission
from core.rescreening.services.imports import _require_idle
from core.rescreening.services.exports import fingerprint, snapshot_rows
from core.rescreening.services.source import digest
from core.rescreening.services.workspace import reference_query
from core.quality.services.reference_service import _safe_int, _first_author
from core.screening.services.import_limits import ImportLimits
from core.workflow.services.task_launcher import ACTIVE_EXECUTION_STATUSES


def _signature(ref):
    return digest([ref.pk, ref.input_version, ref.current_review_id, ref.current_review.version if ref.current_review_id else 0,
                   ref.suggestion_id, ref.suggestion_revision])


def preview(project):
    before = fingerprint(project)
    refs = reference_query(project).select_related('current_review').only('pk', 'input_version',
        'current_review__id', 'current_review__version', 'current_review__decision').order_by('pk').iterator(chunk_size=500)
    counts = {'included': 0, 'new': 0, 'existing': 0, 'changed': 0, 'no_longer_included': 0}
    differences = []
    # Incremental digest of QA identity/snapshot state, not a whole-corpus list.
    import hashlib
    state = hashlib.sha256()
    while rows := list(islice(refs, 500)):
        old = {r.source_rescreen_reference_id: r for r in QAReference.objects.filter(project=project,
            source_rescreen_reference_id__in=[r.pk for r in rows]).select_related('rescreen_source_snapshot')}
        for ref in rows:
            included = ref.review_valid and ref.current_review.decision == 'included'
            saved = old.get(ref.pk)
            signature = _signature(ref)
            state.update(digest([ref.pk, signature, bool(included)]).encode())
            counts['included'] += included
            if included and saved is None:
                counts['new'] += 1
            elif saved:
                source = getattr(saved, 'rescreen_source_snapshot', None)
                saved_signature = source.provenance.get('handoff_signature') if source else None
                state.update(digest([saved.pk, ref.pk, saved_signature]).encode())
                if included:
                    counts['existing'] += 1
                if not included or saved_signature != signature:
                    counts['changed' if included else 'no_longer_included'] += 1
                    if len(differences) < 100:
                        differences.append({'reference_id': ref.pk, 'qa_reference_id': saved.pk, 'title': saved.title,
                            'kind': 'changed' if included else 'no_longer_included', 'ai_status': saved.ai_eval_status})
    # Removed source references are also retained, not silently deleted from QA.
    removed = QAReference.objects.filter(project=project, source_rescreen_reference__isnull=False,
        source_rescreen_reference__removed_revision__isnull=False)
    counts['no_longer_included'] += removed.count()
    for saved in removed.order_by('pk').values('id', 'title', 'source_rescreen_reference_id').iterator(chunk_size=500):
        state.update(digest(saved).encode())
        if len(differences) < 100:
            differences.append({'reference_id': saved['source_rescreen_reference_id'], 'qa_reference_id': saved['id'],
                                'title': saved['title'], 'kind': 'removed'})
    source_fingerprint = fingerprint(project)
    if before != source_fingerprint:
        raise RescreenError('qa_source_changed', '复筛在预览期间变化，请重新预览。', status=409)
    return {'fingerprint': source_fingerprint, 'confirmation_token': digest([source_fingerprint, state.hexdigest(), counts]),
            'counts': counts, 'differences': differences,
            'differences_truncated': counts['changed']+counts['no_longer_included'] > len(differences),
            'policy': 'append_only_preserve_existing'}


def handoff(*, project, user, confirmation_token, acknowledge_differences=False):
    _permission(project, user)
    if not isinstance(acknowledge_differences, bool):
        raise RescreenError('invalid_confirmation', 'acknowledge_differences 必须是 JSON 布尔值。')
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=project.owner_id)
        Project.objects.select_for_update().get(pk=project.pk)
        _require_idle(project)
        if Task.objects.filter(project=project, task_type__startswith='qa_', status__in=ACTIVE_EXECUTION_STATUSES).exists():
            raise RescreenError('qa_busy', '质量评价已有活动任务，请稍后导入。', status=409)
        current = preview(project)
        if current['confirmation_token'] != confirmation_token:
            raise RescreenError('qa_source_changed', '复筛或 QA 来源已变化，请重新预览。', status=409)
        counts = current['counts']
        if (counts['changed'] or counts['no_longer_included']) and acknowledge_differences is not True:
            raise RescreenError('qa_differences_required', '请确认来源差异；已有 QA 及评价成果将保留不变。', status=409)
        limits = ImportLimits.from_settings()
        if QAReference.objects.filter(project=project).count()+counts['new'] > limits.max_references:
            raise RescreenError('too_many_references', '导入后 QA 文献数超过上限。', status=413)
        imported, no_fulltext, buffer = 0, 0, []

        def flush(rows):
            nonlocal imported, no_fulltext
            existing = set(QAReference.objects.filter(project=project,
                source_rescreen_reference_id__in=[ref.pk for ref,p in rows]).values_list('source_rescreen_reference_id', flat=True))
            pending, snapshots = [], {}
            for ref, payload in rows:
                if payload['decision'] != 'included' or ref.pk in existing:
                    continue
                b = payload['bibliography']
                asset = ref.current_binding.asset if ref.current_binding_id and ref.current_binding.asset.status == 'ready' else None
                pending.append(QAReference(project=project, title=b['title'][:500], abstract=b['abstract'],
                    first_author=_first_author(b['authors']), year=_safe_int(b['publication_year']),
                    journal=b['journal'][:300], doi=b['doi'][:200], source_type='screening_import',
                    source_reference_id=ref.source_reference_id, source_screening_run_id=ref.source_screening_run_id,
                    source_screening_decision='included', source_rescreen_reference=ref,
                    source_rescreen_run_item_id=ref.suggestion_id, source_rescreen_review=ref.current_review,
                    shared_fulltext_asset=asset, fulltext_status='available' if asset else 'pending'))
                snapshots[ref.pk] = dict(bibliography=b, raw_metadata=payload['raw_metadata'],
                    provenance={**payload['provenance'], 'handoff_signature': _signature(ref),
                        'source_fingerprint': current['fingerprint'], 'source_reference_id': ref.pk,
                        'input_version': ref.input_version, 'review': payload['review'],
                        'criteria_revision_id': payload['criteria_revision_id'], 'criteria': payload['criteria'],
                        'fulltext': payload['fulltext'],
                        'model_results': payload['model_results'], 'asset_sha256': asset.sha256 if asset else ''})
                imported += 1
                no_fulltext += not bool(asset)
            QAReference.objects.bulk_create(pending, batch_size=200)
            ids = QAReference.objects.filter(project=project, source_rescreen_reference_id__in=snapshots).values_list('pk', 'source_rescreen_reference_id')
            QASourceBibliographySnapshot.objects.bulk_create([
                QASourceBibliographySnapshot(qa_reference_id=pk, **snapshots[source]) for pk, source in ids], batch_size=100)
        for ref, payload in snapshot_rows(project, 'included'):
            buffer.append((ref, payload))
            if len(buffer) >= 500:
                flush(buffer)
                buffer.clear()
        flush(buffer)
        ActivityLog.objects.create(project=project, created_by=user, operation_type='rescreen_to_qa',
            operation_detail={'imported': imported, 'preserved': counts['existing'], 'differences_acknowledged': acknowledge_differences,
                              'fingerprint': current['fingerprint']})
        return {'imported': imported, 'preserved': counts['existing'], 'no_fulltext': no_fulltext,
                'differences_preserved': counts['changed']+counts['no_longer_included'], 'source_stage': 'SCREEN_2'}
