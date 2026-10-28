"""Sequential lookup/download runner with bounded budgets and stop checkpoints."""
from tempfile import TemporaryFile
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone
from core.fulltext.errors import FulltextError
from core.fulltext.matching import local_candidates, match_asset
from core.fulltext.network import NetworkBudget, fetch_to
from core.fulltext.resolvers import europe_pmc, unpaywall
from core.fulltext.services import create_assets
from core.fulltext.processing import process_asset
from core.models import Project
from core.rescreening.models import FulltextLookupJob, FulltextCandidate, RescreenReference
from core.rescreening.services.fulltext_binding import bind_fulltext


def _download(candidate, item, job, budget, checkpoint):
    if candidate.license not in job.settings_snapshot['allowed_licenses']:
        candidate.error_code = 'license_not_allowed'
        candidate.save(update_fields=['error_code'])
        return
    with TemporaryFile() as temporary:
        response = fetch_to(candidate.url, temporary, budget=budget,
            max_bytes=settings.QA_FULLTEXT_MAX_FILE_BYTES, pdf=True)
        temporary.seek(0)
        uploaded = UploadedFile(temporary, name=f'fulltext-{item.reference_id}.pdf',
            size=response['size'], content_type='application/pdf')
        checkpoint(budget)
        assets, _ = create_assets(project=job.project, user=job.created_by, files=[uploaded], schedule=False,
            provenance={'source': candidate.source, 'url': response['url'], 'license': candidate.license,
                        'lookup_job_id': job.pk, 'candidate_id': candidate.pk})
        asset = assets[0]
        if asset.status == 'pending':
            asset = process_asset(asset.pk, check_stop=lambda: _stopped(job))
        checkpoint(budget)
        if asset.status != 'ready':
            raise FulltextError('download_validation_failed', '下载的 PDF 未通过安全处理。')
        candidate.asset, candidate.status = asset, 'downloaded'
        candidate.confidence = match_asset(item.bibliography_snapshot, asset)
        candidate.save(update_fields=['asset', 'status', 'confidence'])


def _stopped(job):
    return not FulltextLookupJob.objects.filter(pk=job.pk, task_id=job.task_id, status='running').exists()


def process_lookup(job_id, *, expected_task_id=None, check_stop=None, progress=None):
    with transaction.atomic():
        job = FulltextLookupJob.objects.select_for_update().select_related('project', 'created_by').get(pk=job_id)
        if expected_task_id is not None and job.task_id != expected_task_id:
            raise FulltextError('stale_task', '查找任务已被替代。', status=409)
        if job.status != 'pending':
            return job
        job.status = 'running'
        job.save(update_fields=['status', 'updated_at'])
    snapshot = job.settings_snapshot

    def checkpoint(budget):
        FulltextLookupJob.objects.filter(pk=job.pk, task_id=job.task_id).update(
            request_count=budget.requests, received_bytes=budget.received, updated_at=timezone.now())
        if _stopped(job) or (check_stop and check_stop()):
            raise FulltextError('lookup_cancelled', '全文查找任务已停止。', status=409)

    budget = NetworkBudget(**{key: snapshot[key] for key in (
        'max_requests', 'max_bytes', 'timeout', 'total_seconds', 'max_redirects')}, checkpoint=checkpoint)
    def advance(total):
        job.processed_count += 1
        FulltextLookupJob.objects.filter(pk=job.pk, status='running').update(processed_count=job.processed_count)
        if progress:
            progress(job.processed_count, total)
    try:
        total = job.items.count()
        for item in job.items.select_related('reference__project', 'selected_candidate').order_by('pk').iterator(chunk_size=50):
            checkpoint(budget)
            ref = item.reference
            if ref.input_version != item.input_version or ref.removed_revision is not None:
                item.status, item.error_code = 'failed', 'input_changed'
                item.save(update_fields=['status', 'error_code'])
                advance(total)
                continue
            item.status = 'processing'
            item.save(update_fields=['status'])
            candidates = []
            try:
                if job.mode == 'download':
                    candidates = [item.selected_candidate]
                else:
                    for asset in local_candidates(job.project_id, item.bibliography_snapshot, limit=snapshot['max_candidates']):
                        candidates.append(FulltextCandidate.objects.create(item=item, asset=asset,
                            source='local', confidence=match_asset(item.bibliography_snapshot, asset), title=asset.original_filename))
                    if job.mode == 'online' and not candidates:
                        if not settings.FULLTEXT_LOOKUP_ENABLED:
                            raise FulltextError('lookup_disabled', '外部全文查找已关闭。')
                        for name, resolver, extra in (('europe_pmc', europe_pmc, {}),
                                ('unpaywall', unpaywall, {'email': settings.FULLTEXT_UNPAYWALL_EMAIL})):
                            checkpoint(budget)
                            remaining = snapshot['max_candidates']-len(candidates)
                            if remaining <= 0:
                                break
                            try:
                                found, note = resolver(item.bibliography_snapshot, budget=budget,
                                    max_json_bytes=snapshot['max_json_bytes'], limit=remaining, **extra)
                                if note:
                                    item.resolver_notes[name] = note
                                seen = {candidate.url for candidate in candidates}
                                for candidate_data in found[:remaining]:
                                    if candidate_data['url'] not in seen:
                                        candidates.append(FulltextCandidate.objects.create(item=item, **candidate_data))
                                        seen.add(candidate_data['url'])
                            except FulltextError as exc:
                                if exc.code in ('lookup_cancelled', 'request_budget_exceeded', 'download_budget_exceeded'):
                                    raise
                                item.resolver_notes[name] = exc.code
                for candidate in candidates:
                    if snapshot['download'] and candidate.url and not candidate.asset_id:
                        if not settings.FULLTEXT_LOOKUP_ENABLED:
                            raise FulltextError('lookup_disabled', '外部全文下载已关闭。')
                        try:
                            _download(candidate, item, job, budget, checkpoint)
                        except FulltextError as exc:
                            if exc.code in ('lookup_cancelled', 'request_budget_exceeded', 'download_budget_exceeded'):
                                raise
                            candidate.status, candidate.error_code = 'failed', exc.code
                            candidate.save(update_fields=['status', 'error_code'])
                strong = [candidate for candidate in candidates if candidate.asset_id and candidate.confidence == 'identifier']
                if snapshot['auto_bind'] and len(strong) == 1 and len(candidates) == 1 and not ref.current_binding_id:
                    checkpoint(budget)
                    bind_fulltext(reference=ref, asset=strong[0].asset, user=job.created_by,
                        expected_version=item.input_version, source=strong[0].source,
                        provenance={'candidate_id': strong[0].pk, 'license': strong[0].license}, lookup_job_id=job.pk)
                    strong[0].status = 'bound'
                    strong[0].save(update_fields=['status'])
                    item.status = 'bound'
                else:
                    item.status = ('failed' if all(candidate.status == 'failed' for candidate in candidates) else 'found') if candidates else 'not_found'
                    if item.status == 'failed':
                        item.error_code = candidates[0].error_code
            except FulltextError as exc:
                if exc.code in ('lookup_cancelled', 'request_budget_exceeded', 'download_budget_exceeded'):
                    raise
                item.status, item.error_code = 'failed', exc.code
            item.save(update_fields=['status', 'error_code', 'resolver_notes'])
            advance(total)
        checkpoint(budget)
        FulltextLookupJob.objects.filter(pk=job.pk, status='running').update(status='completed', finished_at=timezone.now())
    except BaseException as exc:
        code = getattr(exc, 'code', 'lookup_failed')
        cancelled = code == 'lookup_cancelled'
        FulltextLookupJob.objects.filter(pk=job.pk, task_id=job.task_id).update(
            status='cancelled' if cancelled else 'failed', error_code=code, finished_at=timezone.now())
        job.items.filter(status__in=('pending', 'processing')).update(status='cancelled' if cancelled else 'failed', error_code=code)
        raise
    job.refresh_from_db()
    return job
