import hashlib
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from ..models import LegalDocumentType


LEGAL_ROOT = Path(__file__).resolve().parent.parent / 'legal'


@dataclass(frozen=True)
class LegalDocument:
    document_type: str
    title: str
    version: str
    effective_date: str
    content: str
    content_sha256: str


DOCUMENTS = {
    LegalDocumentType.TERMS: ('循证智筛服务协议', 'service-terms-2026-09-16.txt'),
    LegalDocumentType.PRIVACY: ('循证智筛隐私政策', 'privacy-policy-2026-09-16.txt'),
}


def get_current_legal_document(document_type: str) -> LegalDocument:
    if document_type not in DOCUMENTS:
        raise KeyError(document_type)
    title, filename = DOCUMENTS[document_type]
    version = getattr(settings, 'ACCOUNT_LEGAL_VERSION', '2026-09-16')
    content = (LEGAL_ROOT / filename).read_text(encoding='utf-8').format(
        operator_name=getattr(settings, 'LEGAL_OPERATOR_NAME', '待配置的平台运营主体'),
        contact_email=getattr(settings, 'LEGAL_CONTACT_EMAIL', '待配置'),
        contact_address=getattr(settings, 'LEGAL_CONTACT_ADDRESS', '待配置'),
        security_retention_days=getattr(settings, 'ACCOUNT_SECURITY_EVENT_RETENTION_DAYS', 180),
    )
    return LegalDocument(
        document_type=document_type,
        title=title,
        version=version,
        effective_date='2026-09-16',
        content=content,
        content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(),
    )


def current_legal_documents():
    return [get_current_legal_document(kind) for kind in LegalDocumentType.values]
