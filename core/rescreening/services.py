"""文献复筛业务服务。"""

from django.db import transaction

from core.models import RescreenReference
from core.screening.services.final_results import iter_resolved_screening_records
from core.screening.services.import_limits import ImportLimits
from core.screening.services.screening_run_service import current_completed_screening_run


def _safe_int(value):
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _authors_to_list(authors):
    if isinstance(authors, list):
        return [str(item).strip() for item in authors if str(item).strip()]
    if not authors:
        return []
    raw = str(authors).replace('；', ';')
    parts = []
    for chunk in raw.split(';'):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _first_author(result):
    authors = _authors_to_list(result.get('authors') or result.get('Authors'))
    if authors:
        return authors[0][:200]
    value = result.get('first_author') or result.get('First Author') or ''
    return str(value)[:200]


@transaction.atomic
def import_from_screening(project, source_stage='SCREEN_1', ref_ids=None):
    """从当前已完成初筛运行的最终纳入结果增量导入复筛题录。

    不清空既有复筛列表；同一初筛文献（source_ref_id）已导入过时跳过，
    便于再次导入时只追加新增文献。
    """
    if source_stage != 'SCREEN_1':
        return []

    screening_run = current_completed_screening_run(project.id)
    if screening_run is None:
        return []

    existing_source_ref_ids = set(
        RescreenReference.objects.filter(
            project=project,
            source_type='screening_import',
            source_ref_id__isnull=False,
        ).values_list('source_ref_id', flat=True)
    )
    ref_id_filter = {int(item) for item in (ref_ids or [])}
    imported = []
    batch_size = max(1, ImportLimits.from_settings().db_batch_size)

    for resolved in iter_resolved_screening_records(screening_run, batch_size=batch_size):
        if resolved.final_decision != 'included':
            continue
        reference = resolved.reference
        if ref_id_filter and reference.id not in ref_id_filter:
            continue
        if reference.id in existing_source_ref_ids:
            continue

        authors = _authors_to_list(reference.authors)
        ref = RescreenReference.objects.create(
            project=project,
            title=(reference.title or f'文献 {reference.id}')[:500],
            first_author=(authors[0] if authors else '')[:200],
            authors=authors,
            year=_safe_int(reference.publication_year),
            journal=(reference.journal or '')[:300],
            abstract=reference.abstract or '',
            doi=(reference.doi or '')[:200],
            pmid=(reference.pmid or '')[:100],
            source_type='screening_import',
            source_ref_id=reference.id,
            source_xml=(reference.source_record_key or reference.source_identifier or f'screening_ref:{reference.id}')[:500],
            fulltext_status='unbound',
        )
        imported.append(ref.id)
        existing_source_ref_ids.add(reference.id)
    return imported


@transaction.atomic
def batch_include_consistent(project, user, ref_ids=None):
    """一键纳入 AI 一致纳入文献。"""
    qs = RescreenReference.objects.filter(
        project=project,
        human_decision='',
        ai_status='completed',
        ai_decision='included',
        consensus_status='consistent',
    )
    if ref_ids:
        qs = qs.filter(pk__in=list(dict.fromkeys(ref_ids)))
    updated = 0
    for ref in qs:
        ref.human_decision = 'included'
        ref.exclusion_reason = ''
        ref.reviewed_by = user
        from django.utils import timezone
        ref.reviewed_at = timezone.now()
        ref.save(update_fields=['human_decision', 'exclusion_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])
        updated += 1
    return updated


def extract_pdf_meta_from_file(data_file):
    """从 PDF 中尽力提取基础题录信息，复用质量评价上传后的元数据识别思路。

    返回字段均为可选；失败时返回空 dict，不影响上传/绑定主流程。
    """
    if not data_file or not data_file.file:
        return {}
    try:
        file_path = data_file.file.path
    except Exception:
        return {}

    title = ''
    author = ''
    abstract_hint = ''
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        meta = doc.metadata or {}
        title = (meta.get('title') or '').strip()
        author = (meta.get('author') or '').strip()
        abstract_hint = doc[0].get_text()[:800].strip() if len(doc) > 0 else ''
        doc.close()
    except Exception:
        try:
            import PyPDF2
            with open(file_path, 'rb') as fh:
                reader = PyPDF2.PdfReader(fh)
                info = reader.metadata or {}
                title = str(info.get('/Title') or '').strip()
                author = str(info.get('/Author') or '').strip()
                abstract_hint = (reader.pages[0].extract_text() or '')[:800].strip() if reader.pages else ''
        except Exception:
            return {}

    payload = {}
    if title:
        payload['title'] = title[:500]
    if author:
        first_author = author.replace(',', ';').replace('，', ';').split(';')[0].strip()
        if first_author:
            payload['first_author'] = first_author[:200]
            payload['authors'] = _authors_to_list(author) or [first_author[:200]]
    if abstract_hint:
        payload['abstract'] = abstract_hint
    return payload


def apply_pdf_meta_to_rescreen_ref(ref):
    """将 PDF 元数据补充到复筛文献；只填空或文件名占位字段。"""
    meta = extract_pdf_meta_from_file(ref.fulltext_file)
    if not meta:
        return ref

    updates = []
    filename_title = ''
    if ref.fulltext_file:
        filename_title = ref.fulltext_file.filename.rsplit('.', 1)[0].replace('_', ' ')

    if meta.get('title') and (not ref.title or ref.title == filename_title):
        ref.title = meta['title']
        updates.append('title')
    if meta.get('first_author') and not ref.first_author:
        ref.first_author = meta['first_author']
        updates.append('first_author')
    if meta.get('authors') and not ref.authors:
        ref.authors = meta['authors']
        updates.append('authors')
    if meta.get('abstract') and not ref.abstract:
        ref.abstract = meta['abstract']
        updates.append('abstract')

    if updates:
        ref.save(update_fields=updates + ['updated_at'])
    return ref


def normalize_identifier(value):
    return str(value or '').strip().lower().replace('https://doi.org/', '').replace('http://doi.org/', '')


def normalize_title(value):
    import re
    text = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff]+', '', str(value or '').lower())
    return text[:300]


def build_fulltext_lookup_url(ref):
    """为人工兜底提供在线查找入口；不改变绑定状态。"""
    from urllib.parse import quote, quote_plus

    doi = normalize_identifier(ref.doi)
    if doi:
        return f"https://doi.org/{quote(doi, safe='/')}"
    if ref.pmid:
        return f'https://pubmed.ncbi.nlm.nih.gov/{quote_plus(str(ref.pmid).strip())}/'
    query = ' '.join(part for part in [ref.title, str(ref.year or '')] if part).strip()
    if query:
        return f'https://scholar.google.com/scholar?q={quote_plus(query)}'
    return ''


def _pdf_ref_match_score(target, pdf_ref):
    """返回 0-100 的本项目已上传 PDF 与题录匹配分。"""
    from difflib import SequenceMatcher

    target_doi = normalize_identifier(target.doi)
    pdf_doi = normalize_identifier(pdf_ref.doi)
    if target_doi and pdf_doi and target_doi == pdf_doi:
        return 100

    target_title = normalize_title(target.title)
    pdf_title = normalize_title(pdf_ref.title)
    if not target_title or not pdf_title:
        return 0
    if target_title == pdf_title:
        return 95
    if len(target_title) > 20 and (target_title in pdf_title or pdf_title in target_title):
        return 90
    ratio = SequenceMatcher(None, target_title, pdf_title).ratio()
    score = int(ratio * 100)
    if score >= 84 and target.year and pdf_ref.year and target.year != pdf_ref.year:
        score -= 10
    return score


def auto_bind_fulltexts(project, ref_ids=None, user=None):
    """自动查找并绑定全文。

    复用项目内 PDF，并接入 Europe PMC / Unpaywall 等合法开放全文来源；
    不实现 Sci-Hub 等非合规下载。
    """
    from core.rescreening.fulltext_resolvers import auto_bind_fulltexts_with_resolvers

    return auto_bind_fulltexts_with_resolvers(project, ref_ids=ref_ids, user=user)
