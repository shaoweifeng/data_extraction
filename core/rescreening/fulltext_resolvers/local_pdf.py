"""项目内已上传 PDF 匹配。"""

from difflib import SequenceMatcher
import re

from core.models import RescreenReference

from .base import FulltextResolver, ResolveResult


def _normalize_identifier(value):
    return str(value or '').strip().lower().replace('https://doi.org/', '').replace('http://doi.org/', '')


def _normalize_title(value):
    text = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff]+', '', str(value or '').lower())
    return text[:300]


def _pdf_ref_match_score(target, pdf_ref):
    target_doi = _normalize_identifier(target.doi)
    pdf_doi = _normalize_identifier(pdf_ref.doi)
    if target_doi and pdf_doi and target_doi == pdf_doi:
        return 100

    target_title = _normalize_title(target.title)
    pdf_title = _normalize_title(pdf_ref.title)
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


class LocalPdfResolver(FulltextResolver):
    """优先复用项目里用户已经上传过的 PDF。"""

    name = 'local_pdf'

    def __init__(self, project, candidates=None, threshold=88):
        self.project = project
        self.threshold = threshold
        self.candidates = candidates

    def _candidates(self):
        if self.candidates is not None:
            return self.candidates
        return list(RescreenReference.objects.filter(
            project=self.project,
            source_type='pdf_upload',
            fulltext_status='bound',
            fulltext_file__isnull=False,
        ).select_related('fulltext_file'))

    def resolve(self, ref):
        best_ref = None
        best_score = 0
        for pdf_ref in self._candidates():
            if pdf_ref.id == ref.id:
                continue
            score = _pdf_ref_match_score(ref, pdf_ref)
            if score > best_score:
                best_score = score
                best_ref = pdf_ref
        if best_ref and best_score >= self.threshold:
            return ResolveResult(
                found=True,
                resolver=self.name,
                status='matched',
                message=f'匹配项目内已上传 PDF，匹配分 {best_score}',
                source='local_upload',
                source_url='',
                license='',
                filename=best_ref.fulltext_file.filename if best_ref.fulltext_file else '',
                data_file=best_ref.fulltext_file,
                extra={'matched_ref_id': best_ref.id, 'score': best_score},
            )
        return ResolveResult(
            found=False,
            resolver=self.name,
            status='not_found',
            message='项目内未找到可自动匹配的 PDF',
            extra={'best_score': best_score},
        )
