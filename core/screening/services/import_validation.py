"""Security and resource validation for raw reference-file uploads."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from core.screening.services.import_errors import ScreeningImportError
from core.screening.services.import_limits import ImportLimits


FORMAT_BY_EXTENSION = {
    '.ris': 'ris',
    '.bib': 'bibtex',
    '.bibtex': 'bibtex',
    '.nbib': 'nbib',
    '.medline': 'nbib',
    '.ciw': 'ciw',
    '.enw': 'enw',
    '.txt': 'enw',
    '.xml': 'xml',
    '.doc': 'docx',
    '.docx': 'docx',
}


@dataclass(frozen=True)
class ValidatedUpload:
    uploaded_file: object
    original_filename: str
    source_format: str
    size: int
    sha256: str


def _rewind(uploaded) -> None:
    try:
        uploaded.seek(0)
    except (AttributeError, OSError):
        raise ScreeningImportError('invalid_file', '上传文件无法读取或定位。')


def _read_prefix(uploaded, size=65536) -> bytes:
    _rewind(uploaded)
    prefix = uploaded.read(size)
    _rewind(uploaded)
    return prefix


def _decode_text(prefix: bytes, filename: str) -> str:
    for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
        try:
            return prefix.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ScreeningImportError(
        'unsupported_encoding', f'{filename} 无法使用 UTF-8、UTF-16 或 GB18030 解码。'
    )


def _validate_zip_container(uploaded, filename: str, limits: ImportLimits) -> None:
    _rewind(uploaded)
    try:
        if not zipfile.is_zipfile(uploaded):
            raise ScreeningImportError(
                'file_signature_mismatch', f'{filename} 不是可读取的 DOCX/OOXML 文件。'
            )
        _rewind(uploaded)
        with zipfile.ZipFile(uploaded) as archive:
            members = archive.infolist()
            if len(members) > limits.max_docx_entries:
                raise ScreeningImportError(
                    'archive_too_many_entries',
                    f'{filename} 的压缩包成员超过 {limits.max_docx_entries} 个。',
                )
            total_uncompressed = 0
            names = set()
            for member in members:
                normalized = member.filename.replace('\\', '/')
                path = PurePosixPath(normalized)
                if path.is_absolute() or '..' in path.parts or '\x00' in normalized:
                    raise ScreeningImportError('unsafe_archive_path', f'{filename} 包含不安全路径。')
                if normalized in names:
                    raise ScreeningImportError('duplicate_archive_path', f'{filename} 包含重复路径。')
                names.add(normalized)
                if member.flag_bits & 0x1:
                    raise ScreeningImportError('encrypted_archive', f'{filename} 是加密压缩文件。')
                total_uncompressed += member.file_size
                if total_uncompressed > limits.max_docx_uncompressed_bytes:
                    raise ScreeningImportError(
                        'archive_uncompressed_too_large',
                        f'{filename} 解压后超过允许大小。',
                    )
            if 'word/document.xml' not in names:
                raise ScreeningImportError(
                    'file_signature_mismatch', f'{filename} 缺少 DOCX 主文档结构。'
                )
    except zipfile.BadZipFile as exc:
        raise ScreeningImportError('invalid_archive', f'{filename} 压缩结构损坏。') from exc
    finally:
        _rewind(uploaded)


def _validate_content(uploaded, filename: str, source_format: str, limits: ImportLimits) -> None:
    prefix = _read_prefix(uploaded)
    if not prefix:
        raise ScreeningImportError('empty_file', f'{filename} 是空文件。')
    if source_format == 'docx':
        _validate_zip_container(uploaded, filename, limits)
        return
    if b'\x00' in prefix and not prefix.startswith((b'\xff\xfe', b'\xfe\xff')):
        raise ScreeningImportError('binary_content', f'{filename} 包含与文本索引不符的二进制内容。')

    text = _decode_text(prefix, filename).lstrip('\ufeff\r\n\t ')
    lower = text.lower()
    if source_format == 'xml':
        if not text.startswith('<'):
            raise ScreeningImportError('file_signature_mismatch', f'{filename} 不是 XML 内容。')
        if '<!doctype' in lower or '<!entity' in lower:
            raise ScreeningImportError('unsafe_xml', f'{filename} 包含禁止的 DTD 或实体声明。')
    elif source_format == 'ris' and not re.search(r'(?im)^ty\s{1,2}-\s*', text):
        raise ScreeningImportError('file_signature_mismatch', f'{filename} 未检测到 RIS 记录。')
    elif source_format == 'bibtex' and not re.search(r'(?im)^\s*@[a-z]+\s*[\{(]', text):
        raise ScreeningImportError('file_signature_mismatch', f'{filename} 未检测到 BibTeX 记录。')
    elif source_format == 'nbib' and not re.search(r'(?im)^pmid\s*-\s*', text):
        raise ScreeningImportError('file_signature_mismatch', f'{filename} 未检测到 NBIB/Medline 记录。')
    elif source_format == 'ciw' and not re.search(r'(?im)^pt\s+', text):
        raise ScreeningImportError('file_signature_mismatch', f'{filename} 未检测到 CIW 记录。')
    elif source_format == 'enw' and not re.search(r'(?im)^%0\s+', text):
        raise ScreeningImportError('file_signature_mismatch', f'{filename} 未检测到 ENW/TXT 记录。')


def _sha256(uploaded) -> str:
    digest = hashlib.sha256()
    _rewind(uploaded)
    for chunk in uploaded.chunks():
        digest.update(chunk)
    _rewind(uploaded)
    return digest.hexdigest()


def validate_uploads(files: Iterable, limits: ImportLimits) -> list[ValidatedUpload]:
    files = list(files)
    if not files:
        raise ScreeningImportError('no_files', '请至少上传一个索引文件。')
    if len(files) > limits.max_files:
        raise ScreeningImportError(
            'too_many_files', f'单次最多上传 {limits.max_files} 个文件。',
            details={'limit': limits.max_files, 'actual': len(files)},
        )

    validated = []
    total_bytes = 0
    names = set()
    hashes = set()
    for uploaded in files:
        original = str(getattr(uploaded, 'name', '') or '')
        if (
            not original or len(original) > 255 or '\x00' in original
            or '/' in original or '\\' in original
        ):
            raise ScreeningImportError('unsafe_filename', '文件名为空、过长或包含路径字符。')
        if original.casefold() in names:
            raise ScreeningImportError('duplicate_filename', f'本次上传包含重名文件：{original}')
        names.add(original.casefold())

        extension = Path(original).suffix.lower()
        source_format = FORMAT_BY_EXTENSION.get(extension)
        if source_format is None:
            raise ScreeningImportError(
                'unsupported_format', f'{original} 的格式不受支持。',
                details={'extension': extension},
            )
        size = int(getattr(uploaded, 'size', 0) or 0)
        if size <= 0:
            raise ScreeningImportError('empty_file', f'{original} 是空文件。')
        if size > limits.max_file_bytes:
            raise ScreeningImportError(
                'file_too_large', f'{original} 超过单文件大小限制。', http_status=413,
                details={'limit': limits.max_file_bytes, 'actual': size},
            )
        total_bytes += size
        if total_bytes > limits.max_total_bytes:
            raise ScreeningImportError(
                'request_too_large', '本次上传文件总大小超过限制。', http_status=413,
                details={'limit': limits.max_total_bytes, 'actual': total_bytes},
            )

        _validate_content(uploaded, original, source_format, limits)
        digest = _sha256(uploaded)
        if digest in hashes:
            raise ScreeningImportError('duplicate_file', f'本次上传包含内容重复的文件：{original}', http_status=409)
        hashes.add(digest)
        validated.append(ValidatedUpload(uploaded, original, source_format, size, digest))
    return validated
