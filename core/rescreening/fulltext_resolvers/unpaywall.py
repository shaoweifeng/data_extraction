"""Unpaywall 开放获取 PDF 查找。"""

import os
from urllib.parse import quote

import requests

from .base import FulltextResolver, ResolveResult, download_pdf, ref_display_filename


class UnpaywallResolver(FulltextResolver):
    """通过 Unpaywall API 查找合法 OA PDF。需要配置 UNPAYWALL_EMAIL。"""

    name = 'unpaywall'

    def __init__(self, email=None):
        self.email = email or os.getenv('UNPAYWALL_EMAIL', '').strip()

    def resolve(self, ref):
        doi = (ref.doi or '').strip()
        if not doi:
            return ResolveResult(False, self.name, 'skipped', '缺少 DOI，跳过 Unpaywall')
        if not self.email:
            return ResolveResult(False, self.name, 'skipped', '未配置 UNPAYWALL_EMAIL，跳过 Unpaywall')

        api_url = f'https://api.unpaywall.org/v2/{quote(doi, safe="")}?email={quote(self.email, safe="@.")}'
        try:
            response = requests.get(api_url, timeout=15, headers={'User-Agent': 'DataExtractionRescreening/1.0'})
            response.raise_for_status()
            payload = response.json() or {}
        except Exception as exc:
            return ResolveResult(False, self.name, 'error', f'Unpaywall 查询失败: {exc}', source_url=api_url)

        locations = []
        best = payload.get('best_oa_location') or {}
        if best:
            locations.append(best)
        locations.extend(payload.get('oa_locations') or [])

        for location in locations:
            pdf_url = location.get('url_for_pdf') or ''
            if not pdf_url:
                continue
            try:
                content = download_pdf(pdf_url)
            except Exception as exc:
                continue
            return ResolveResult(
                found=True,
                resolver=self.name,
                status='downloaded',
                message='通过 Unpaywall 找到开放获取 PDF',
                source='unpaywall',
                source_url=pdf_url,
                license=location.get('license') or payload.get('license') or '',
                filename=ref_display_filename(ref, 'unpaywall'),
                content=content,
                extra={
                    'oa_status': payload.get('oa_status') or '',
                    'host_type': location.get('host_type') or '',
                    'landing_page_url': location.get('url') or '',
                },
            )
        return ResolveResult(False, self.name, 'not_found', 'Unpaywall 未返回可下载 PDF', source_url=api_url)
