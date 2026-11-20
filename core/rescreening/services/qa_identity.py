"""Stable project-local identities retained when a rescreen corpus is reset."""
from types import SimpleNamespace
from core.models import QAReference
from core.rescreening.errors import RescreenError
from core.screening.services.reference_persistence import normalize_doi


def source_identities(ref, *, bibliography=None, asset_sha=None):
    identities = []
    if ref.source_reference_id:
        identities.append(f'screening:{ref.source_reference_id}')
    if ref.import_file_id:
        identities.append(f'file:{ref.import_file.sha256}:{ref.source_record_index}')
    if asset_sha is None:
        asset_sha = ref.current_binding.asset.sha256 if ref.current_binding_id else ''
    if asset_sha:
        identities.append(f'pdf:{asset_sha}')
    doi = normalize_doi(bibliography.get('doi') if bibliography is not None else ref.doi)
    if doi:
        identities.append(f'doi:{doi}')
    return identities


def preserved_sources(project):
    result = {}
    rows = QAReference.objects.filter(project=project, source_rescreen_reference__isnull=True,
        rescreen_source_snapshot__provenance__source_reset=True).values('id', 'title', 'ai_eval_status',
        'rescreen_source_snapshot__provenance__handoff_identities')
    for row in rows.iterator(chunk_size=500):
        saved = SimpleNamespace(pk=row['id'], title=row['title'], ai_eval_status=row['ai_eval_status'])
        for key in row['rescreen_source_snapshot__provenance__handoff_identities'] or []:
            result.setdefault(key, {})[saved.pk] = saved
    return result


def match_preserved(ref, sources):
    if not sources:
        return None
    matches = {}
    for key in source_identities(ref):
        matches.update(sources.get(key, {}))
    if len(matches) > 1:
        raise RescreenError('qa_source_ambiguous', '当前文献匹配到多篇已有质量评价文献，请先核对质量评价列表。', status=409)
    return next(iter(matches.values()), None)
