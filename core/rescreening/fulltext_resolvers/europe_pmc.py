"""Europe PMC / PMC 开放全文查找。"""

from urllib.parse import quote_plus

import requests

from .base import FulltextResolver, ResolveResult, download_pdf, ref_display_filename


class EuropePmcResolver(FulltextResolver):
    """通过 Europe PMC 官方接口查找开放全文 PDF。"""

    name = 'europe_pmc'
    endpoint = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'

    def _query(self, ref):
        if ref.pmid:
            return f'EXT_ID:{ref.pmid} AND SRC:MED'
        if ref.doi:
            doi = str(ref.doi).replace('"', '')
            return f'DOI:"{doi}"'
        title = (ref.title or '').replace('"', '').strip()
        if title:
            return f'TITLE:"{title}"'
        return ''

    def _candidate_pdf_urls(self, result):
        items = (((result or {}).get('fullTextUrlList') or {}).get('fullTextUrl') or [])
        for item in items:
            document_style = (item.get('documentStyle') or '').lower()
            availability = (item.get('availability') or item.get('availabilityCode') or '').lower()
            url = item.get('url') or ''
            if url and ('pdf' in document_style or url.lower().endswith('.pdf')):
                if not availability or 'open' in availability or availability in {'f', 'oa'}:
                    yield url
        pmcid = (result or {}).get('pmcid') or ''
        if pmcid:
            yield f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/'

    def resolve(self, ref):
        query = self._query(ref)
        if not query:
            return ResolveResult(False, self.name, 'skipped', '缺少 DOI/PMID/标题，跳过 Europe PMC')

        params = {'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': 1}
        try:
            response = requests.get(self.endpoint, params=params, timeout=15, headers={'User-Agent': 'DataExtractionRescreening/1.0'})
            response.raise_for_status()
            payload = response.json() or {}
        except Exception as exc:
            return ResolveResult(False, self.name, 'error', f'Europe PMC 查询失败: {exc}', source_url=f'{self.endpoint}?query={quote_plus(query)}')

        results = (((payload.get('resultList') or {}).get('result')) or [])
        if not results:
            return ResolveResult(False, self.name, 'not_found', 'Europe PMC 未找到记录', source_url=f'{self.endpoint}?query={quote_plus(query)}')

        result = results[0]
        for pdf_url in self._candidate_pdf_urls(result):
            try:
                content = download_pdf(pdf_url)
            except Exception:
                continue
            return ResolveResult(
                found=True,
                resolver=self.name,
                status='downloaded',
                message='通过 Europe PMC/PMC 找到开放全文 PDF',
                source='europe_pmc',
                source_url=pdf_url,
                license=result.get('license') or '',
                filename=ref_display_filename(ref, 'europe_pmc'),
                content=content,
                extra={
                    'pmid': result.get('pmid') or '',
                    'pmcid': result.get('pmcid') or '',
                    'doi': result.get('doi') or '',
                },
            )
        return ResolveResult(False, self.name, 'not_found', 'Europe PMC 记录未提供可下载开放 PDF', source_url=f'{self.endpoint}?query={quote_plus(query)}')
