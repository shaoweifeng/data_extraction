"""Public reference parsing API for the screening domain."""

from .bibtex import parse_bib
from .ciw import parse_ciw
from .docx import parse_docx
from .enw import parse_enw
from .nbib import parse_nbib
from .registry import iter_file, parse_file, register_parser, supported_extensions
from .ris import parse_ris
from .validation import ReferenceRecordValidationError, validate_reference_record
from .xml import parse_xml


register_parser(('.ris',), parse_ris)
register_parser(('.ciw',), parse_ciw)
register_parser(('.bib', '.bibtex'), parse_bib)
register_parser(('.nbib', '.medline'), parse_nbib)
register_parser(('.xml',), parse_xml)
register_parser(('.enw', '.txt'), parse_enw)
register_parser(('.doc', '.docx'), parse_docx)

__all__ = [
    'iter_file', 'parse_bib', 'parse_ciw', 'parse_docx',
    'parse_enw', 'parse_file', 'parse_nbib', 'parse_ris', 'parse_xml',
    'ReferenceRecordValidationError', 'register_parser', 'supported_extensions',
    'validate_reference_record',
]
