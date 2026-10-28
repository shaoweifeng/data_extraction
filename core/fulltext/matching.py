"""Bounded, project-local matching; ambiguous identifiers never auto-bind."""
import hashlib
from pathlib import Path
from django.db.models import Q
from core.fulltext.models import FulltextAsset
from core.screening.services.reference_persistence import normalize_doi, normalize_title


def match_asset(reference, asset):
    doi = normalize_doi(reference.get('doi'))
    pmid = str(reference.get('pmid') or '')
    dois = {normalize_doi(value) for value in asset.metadata.get('dois', [])}
    pmids = set(asset.metadata.get('pmids', []))
    if (doi and dois and doi not in dois) or (pmid and pmids and pmid not in pmids):
        return 'conflict'
    if (doi and dois == {doi}) or (pmid and pmids == {pmid}):
        return 'identifier'
    expected = normalize_title(reference.get('title'))
    if expected and expected == normalize_title(Path(asset.original_filename).stem):
        return 'title'
    return 'candidate'


def local_candidates(project_id, reference, *, limit):
    doi, pmid = normalize_doi(reference.get('doi')), str(reference.get('pmid') or '')
    title = normalize_title(reference.get('title'))
    condition = Q(pk__in=[])
    if doi:
        condition |= Q(primary_doi=doi)
    if pmid:
        condition |= Q(primary_pmid=pmid)
    if title:
        condition |= Q(normalized_title_hash=hashlib.sha256(title.encode()).hexdigest())
    return list(FulltextAsset.objects.filter(project_id=project_id, status='ready').filter(condition).order_by('pk')[:limit])
