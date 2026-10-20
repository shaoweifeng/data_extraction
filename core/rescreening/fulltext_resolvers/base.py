"""全文查找器基础对象。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_TIMEOUT = int(os.getenv('FULLTEXT_DOWNLOAD_TIMEOUT', '20'))
DEFAULT_MAX_BYTES = int(os.getenv('FULLTEXT_DOWNLOAD_MAX_BYTES', str(50 * 1024 * 1024)))
USER_AGENT = os.getenv(
    'FULLTEXT_DOWNLOAD_USER_AGENT',
    'DataExtractionRescreening/1.0 (+https://example.local; open-access-pdf-resolver)',
)


@dataclass
class ResolveResult:
    """单个 resolver 的输出。"""

    found: bool
    resolver: str
    status: str
    message: str = ''
    source: str = ''
    source_url: str = ''
    license: str = ''
    filename: str = ''
    content: bytes | None = None
    data_file: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def attempt_payload(self) -> dict[str, Any]:
        payload = {
            'resolver': self.resolver,
            'status': self.status,
            'found': self.found,
            'message': self.message,
            'source': self.source,
            'source_url': self.source_url,
            'license': self.license,
        }
        if self.extra:
            payload['extra'] = self.extra
        return {key: value for key, value in payload.items() if value not in ('', None, {}, [])}


class FulltextResolver:
    """全文查找器接口。"""

    name = 'base'

    def resolve(self, ref) -> ResolveResult:  # pragma: no cover - interface
        raise NotImplementedError


def sanitize_filename(value: str, fallback: str = 'fulltext.pdf') -> str:
    raw = (value or fallback).strip() or fallback
    raw = re.sub(r'[\\/:*?"<>|\s]+', '_', raw).strip('._')
    if not raw.lower().endswith('.pdf'):
        raw += '.pdf'
    return raw[:180] or fallback


def ref_display_filename(ref, suffix: str = '') -> str:
    seed = ref.doi or ref.title or f'rescreen-ref-{ref.id}'
    if suffix:
        seed = f'{seed}_{suffix}'
    return sanitize_filename(seed)


def download_pdf(url: str, *, timeout: int = DEFAULT_TIMEOUT, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """下载并校验 PDF。只接受 PDF 响应，避免把网页 landing page 当成全文。"""
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.1',
    }
    response = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
    response.raise_for_status()

    content_type = (response.headers.get('content-type') or '').lower()
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=1024 * 64):
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            raise ValueError(f'PDF 文件超过大小限制 {max_bytes} bytes')
        chunks.append(chunk)
    content = b''.join(chunks)
    head = content[:20].lstrip()
    if not head.startswith(b'%PDF'):
        # 部分服务器 content-type 不准，但真实 PDF 基本应以 %PDF 开头。
        raise ValueError(f'下载结果不是 PDF（content-type={content_type or "unknown"}）')
    return content
