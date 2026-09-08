"""Extension-based parser registry used by screening imports."""

import os
from typing import Callable, Dict, Iterable, List

from .common import ParserResult


Parser = Callable[[str], ParserResult]
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


def parse_file(file_path: str) -> ParserResult:
    return get_parser(file_path)(file_path)
