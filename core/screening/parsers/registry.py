"""Extension-based parser registry used by screening imports."""

import os
from typing import Callable, Dict, Iterable, Iterator, List

from .common import ReferenceRecord


Parser = Callable[[str], Iterable[ReferenceRecord]]
_PARSERS: Dict[str, Parser] = {}


def _normalize_extension(extension: str) -> str:
    normalized = extension.lower().strip()
    if not normalized.startswith('.'):
        normalized = f'.{normalized}'
    return normalized


def register_parser(extensions: Iterable[str], parser: Parser) -> None:
    """Register one parser for one or more file extensions."""
    for extension in extensions:
        normalized = _normalize_extension(extension)
        if normalized in _PARSERS and _PARSERS[normalized] is not parser:
            raise ValueError(f'解析器扩展名重复注册: {normalized}')
        _PARSERS[normalized] = parser


def get_parser(file_path: str) -> Parser:
    extension = os.path.splitext(file_path)[1].lower()
    try:
        return _PARSERS[extension]
    except KeyError as exc:
        raise ValueError(f'不支持的文件格式: {extension}') from exc


def supported_extensions() -> List[str]:
    return sorted(_PARSERS)


def iter_file(file_path: str) -> Iterator[ReferenceRecord]:
    """Stream normalized records from one source file."""
    yield from get_parser(file_path)(file_path)


def parse_file(file_path: str) -> List[ReferenceRecord]:
    """Compatibility boundary for callers that still require a materialized list."""
    return list(iter_file(file_path))
