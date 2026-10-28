"""Common streaming PDF signature/hash check; callers keep their own upload semantics."""
import hashlib
from core.fulltext.errors import FulltextError


def hash_and_check(uploaded_file):
    digest, header = hashlib.sha256(), b''
    for chunk in uploaded_file.chunks():
        if len(header) < 5:
            header += chunk[:5-len(header)]
        digest.update(chunk)
    uploaded_file.seek(0)
    if header != b'%PDF-':
        raise FulltextError('invalid_pdf_signature', '文件内容不是有效的 PDF。')
    return digest.hexdigest()
