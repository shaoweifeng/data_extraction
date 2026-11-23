"""Open-access metadata only; URLs are candidates, not a license or identity guarantee."""
import re
from urllib.parse import urlencode, quote
from core.fulltext.errors import FulltextError
from core.fulltext.network import checked_url, fetch_json
from core.screening.services.reference_persistence import normalize_doi


# Fixed product lookup order; captured in each job for reproducibility.
LOOKUP_SOURCES = ('europe_pmc', 'unpaywall', 'semantic_scholar', 'crossref')


def normalized_license(value):
    value = str(value or '').lower().strip().replace('_', '-')
    value = {'ccby': 'cc-by', 'ccbysa': 'cc-by-sa', 'ccbync': 'cc-by-nc', 'cc0': 'cc0'}.get(value, value)
    match = re.search(r'creativecommons\.org/licenses/([a-z-]+)/', value)
    if match:
        return 'cc-' + match.group(1)
    if 'creativecommons.org/publicdomain/zero/' in value:
        return 'cc0'
    return re.sub(r'-\d+(?:\.\d+)*$', '', value)


def _candidate(*, source, url, title='', doi='', pmid='', license='', provenance=None):
    return dict(source=source, url=checked_url(url), title=str(title or '')[:2000],
        doi=normalize_doi(doi)[:255], pmid=str(pmid or '')[:64], license=normalized_license(license)[:100],
        confidence='identifier', provenance=provenance or {})


def europe_pmc(reference, *, budget, max_json_bytes, limit):
    doi = normalize_doi(reference.get('doi'))
    pmid = str(reference.get('pmid') or '')
    pmcid = str(reference.get('pmcid') or '')
    if re.fullmatch(r'10\.\d{4,9}/[^\s"<>]+', doi):
        query = f'DOI:"{doi}" AND OPEN_ACCESS:Y'
    elif pmid.isdigit():
        query = f'EXT_ID:{pmid} AND SRC:MED AND OPEN_ACCESS:Y'
    elif re.fullmatch(r'PMC\d+', pmcid, flags=re.I):
        query = f'PMCID:{pmcid} AND OPEN_ACCESS:Y'
    else:
        return [], 'identifier_missing'
    url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urlencode(
        {'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': min(limit, 10)})
    payload = fetch_json(url, budget=budget, max_bytes=max_json_bytes)
    candidates = []
    result_list = payload.get('resultList')
    if not isinstance(result_list, dict) or not isinstance(result_list.get('result'), list):
        raise FulltextError('invalid_metadata', '开放来源返回的结果列表无效。')
    for result in result_list['result'][:limit]:
        if not isinstance(result, dict):
            continue
        if result.get('isOpenAccess') != 'Y':
            continue
        result_doi = normalize_doi(result.get('doi'))
        result_pmid = str(result.get('id') or '') if result.get('source') == 'MED' else ''
        if doi and result_doi != doi:
            continue
        if not doi and pmid and result_pmid != pmid:
            continue
        links = result.get('fullTextUrlList')
        links = links.get('fullTextUrl', []) if isinstance(links, dict) else []
        for link in (links if isinstance(links, list) else [])[:limit]:
            if not isinstance(link, dict):
                continue
            if str(link.get('documentStyle', '')).lower() != 'pdf' or link.get('availabilityCode') != 'OA':
                continue
            try:
                candidates.append(_candidate(source='europe_pmc', url=link.get('url'),
                    title=result.get('title'), doi=result_doi, pmid=result_pmid,
                    license=link.get('license') or result.get('license'),
                    provenance={'pmcid': result.get('pmcid'), 'availability_code': 'OA'}))
            except FulltextError:
                continue
    return candidates[:limit], ''


def unpaywall(reference, *, budget, max_json_bytes, limit, email):
    if not email:
        return [], 'email_not_configured'
    doi = normalize_doi(reference.get('doi'))
    if not re.fullmatch(r'10\.\d{4,9}/[^\s"<>]+', doi):
        return [], 'doi_missing'
    payload = fetch_json('https://api.unpaywall.org/v2/' + quote(doi, safe='') + '?' + urlencode({'email': email}),
                         budget=budget, max_bytes=max_json_bytes)
    if not payload.get('is_oa') or normalize_doi(payload.get('doi')) != doi:
        return [], 'not_open_access'
    locations = payload.get('oa_locations')
    locations = [payload.get('best_oa_location')] + (locations if isinstance(locations, list) else [])[:limit]
    found, seen = [], set()
    for location in locations:
        if not isinstance(location, dict) or not location.get('url_for_pdf') or location['url_for_pdf'] in seen:
            continue
        seen.add(location['url_for_pdf'])
        try:
            found.append(_candidate(source='unpaywall', url=location['url_for_pdf'], title=payload.get('title'),
                doi=doi, license=location.get('license'), provenance={'host_type': location.get('host_type'),
                    'version': location.get('version'), 'evidence': str(location.get('evidence') or '')[:200]}))
        except FulltextError:
            continue
    return found[:limit], ''


def semantic_scholar(reference, *, budget, max_json_bytes, limit):
    """Exact identifiers only; OA metadata without an explicit license stays link-only."""
    doi = normalize_doi(reference.get('doi'))
    pmid = str(reference.get('pmid') or '')
    if re.fullmatch(r'10\.\d{4,9}/[^\s"<>]+', doi):
        identifier = 'DOI:' + doi
    elif pmid.isdigit():
        identifier = 'PMID:' + pmid
    else:
        return [], 'identifier_missing'
    payload = fetch_json('https://api.semanticscholar.org/graph/v1/paper/' + quote(identifier, safe='') +
        '?fields=title,externalIds,isOpenAccess,openAccessPdf', budget=budget, max_bytes=max_json_bytes)
    identifiers = payload.get('externalIds') or {}
    if not isinstance(identifiers, dict):
        raise FulltextError('invalid_metadata', '来源标识符格式无效。')
    if (doi and normalize_doi(identifiers.get('DOI')) != doi) or (
            not doi and str(identifiers.get('PubMed') or '') != pmid):
        return [], 'identifier_mismatch'
    pdf = payload.get('openAccessPdf')
    if not payload.get('isOpenAccess') or not isinstance(pdf, dict) or not pdf.get('url'):
        return [], 'not_open_access'
    return [_candidate(source='semantic_scholar', url=pdf['url'], title=payload.get('title'),
        doi=identifiers.get('DOI'), pmid=identifiers.get('PubMed'), license=pdf.get('license'),
        provenance={'paper_id': payload.get('paperId'), 'external_ids': identifiers,
                    'access_status': pdf.get('status'), 'resolver_version': 1})], ''


def crossref(reference, *, budget, max_json_bytes, limit):
    doi = normalize_doi(reference.get('doi'))
    if not re.fullmatch(r'10\.\d{4,9}/[^\s"<>]+', doi):
        return [], 'doi_missing'
    payload = fetch_json('https://api.crossref.org/works/' + quote(doi, safe=''),
        budget=budget, max_bytes=max_json_bytes)
    record = payload.get('message')
    if not isinstance(record, dict) or normalize_doi(record.get('DOI')) != doi:
        return [], 'identifier_mismatch'
    titles = record.get('title') or []
    # Crossref license declarations may apply to a different content version:
    # retain them for provenance, never treat a TDM link as download permission.
    licenses = record.get('license') or []
    found = []
    links = record.get('link') or []
    for link in (links if isinstance(links, list) else [])[:limit]:
        if not isinstance(link, dict) or link.get('content-type') != 'application/pdf':
            continue
        try:
            found.append(_candidate(source='crossref', url=link.get('URL'), doi=doi,
                title=titles[0] if isinstance(titles, list) and titles else '',
                provenance={'content_version': link.get('content-version'),
                    'intended_application': link.get('intended-application'),
                    'license_declarations': licenses[:10] if isinstance(licenses, list) else [],
                    'resolver_version': 1}))
        except FulltextError:
            continue
    return found[:limit], '' if found else 'no_pdf_link'
