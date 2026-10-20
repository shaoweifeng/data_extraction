"""OpenAlex 开放获取 PDF 查找。"""

from urllib.parse import quote_plus

import requests

from .base import FulltextResolver, ResolveResult, download_pdf, ref_display_filename


class OpenAlexResolver(FulltextResolver):
    """通过 OpenAlex works API 查找开放获取 PDF URL。"""

    name = 'openalex'
    endpoint = 'https://api.openalex.org/works'

    def _params(self, ref):
        if ref.doi:
            doi = str(ref.doi).strip()
            if not doi.lower().startswith('http'):
                doi = f'https://doi.org/{doi}'
            return {'filter': f'doi:{doi}', 'per-page': 1}
        if ref.title:
            return {'search': ref.title, 'per-page': 1}
        return {}

    def _candidate_pdf_urls(self, work):
        primary = (work or {}).get('primary_location') or {}
        if primary.get('pdf_url'):
            yield primary['pdf_url']
        for location in (work or {}).get('locations') or []:
            if location.get('pdf_url'):
                yield location['pdf_url']
        oa_url = ((work or {}).get('open_access') or {}).get('oa_url') or ''
        if oa_url and oa_url.lower().endswith('.pdf'):
            yield oa_url

    def resolve(self, ref):
        params = self._params(ref)
        if not params:
            return ResolveResult(False, self.name, 'skipped', '缺少 DOI/标题，跳过 OpenAlex')
        try:
            response = requests.get(self.endpoint, params=params, timeout=15, headers={'User-Agent': 'DataExtractionRescreening/1.0'})
            response.raise_for_status()
            payload = response.json() or {}
        except Exception as exc:
            query = params.get('filter') or params.get('search') or ''
            return ResolveResult(False, self.name, 'error', f'OpenAlex 查询失败: {exc}', source_url=f'{self.endpoint}?q={quote_plus(query)}')

        results = payload.get('results') or []
        if not results:
            return ResolveResult(False, self.name, 'not_found', 'OpenAlex 未找到记录')
        work = results[0]
        for pdf_url in self._candidate_pdf_urls(work):
            try:
                content = download_pdf(pdf_url)
            except Exception:
                continue
            return ResolveResult(
                found=True,
                resolver=self.name,
                status='downloaded',
                message='通过 OpenAlex 找到开放获取 PDF',
                source='openalex',
                source_url=pdf_url,
                license=((work.get('primary_location') or {}).get('license') or ''),
                filename=ref_display_filename(ref, 'openalex'),
                content=content,
                extra={
                    'openalex_id': work.get('id') or '',
                    'doi': work.get('doi') or '',
                    'oa_status': ((work.get('open_access') or {}).get('oa_status') or ''),
                },
            )
        return ResolveResult(False, self.name, 'not_found', 'OpenAlex 记录未提供可下载开放 PDF')
