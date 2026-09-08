"""Public reference parsing API for the screening domain."""

import os
from typing import Dict, List

from .bibtex import parse_bib
from .ciw import parse_ciw
from .docx import parse_docx
from .enw import parse_enw
from .nbib import parse_nbib
from .output import convert_to_xml, split_to_single_files, write_xml_stream
from .registry import parse_file, register_parser, supported_extensions
from .ris import parse_ris
from .xml import parse_xml


register_parser(('.ris',), parse_ris)
register_parser(('.ciw',), parse_ciw)
register_parser(('.bib', '.bibtex'), parse_bib)
register_parser(('.nbib', '.medline'), parse_nbib)
register_parser(('.xml',), parse_xml)
register_parser(('.enw', '.txt'), parse_enw)
register_parser(('.doc', '.docx'), parse_docx)


def iter_directory(dir_path: str):
    """Yield records file by file so callers need not retain the whole import."""
    supported = set(supported_extensions())
    for filename in sorted(os.listdir(dir_path)):
        file_path = os.path.join(dir_path, filename)
        if not os.path.isfile(file_path):
            continue
        if os.path.splitext(filename)[1].lower() not in supported:
            continue
        try:
            yield from parse_file(file_path)
        except Exception as exc:
            print(f'[警告] 解析失败 {filename}: {exc}')


def parse_directory(dir_path: str) -> List[Dict]:
    """Compatibility API returning all parsed records."""
    return list(iter_directory(dir_path))


__all__ = [
    'convert_to_xml', 'iter_directory', 'parse_bib', 'parse_ciw', 'parse_directory', 'parse_docx',
    'parse_enw', 'parse_file', 'parse_nbib', 'parse_ris', 'parse_xml',
    'register_parser', 'split_to_single_files', 'supported_extensions', 'write_xml_stream',
]
