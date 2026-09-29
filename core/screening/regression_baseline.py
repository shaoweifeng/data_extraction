"""Build a deterministic regression baseline from real screening/QA samples."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable

from core.screening.parsers import parse_file
from core.screening.parsers.diagnostics import build_parse_report


BASELINE_SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_title(value: Any) -> str:
    """Match the title normalization used by the v1.5.0 deduplication handler."""
    return ''.join(char.lower() for char in str(value or '') if char.isalnum())


def _screening_file_baseline(path: Path) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    parser_error = None
    try:
        entries = list(parse_file(str(path)))
    except Exception as exc:  # the error itself is part of the regression contract
        entries = []
        parser_error = exc

    report = build_parse_report(str(path), entries, parser_error=parser_error)
    issue_codes = Counter(issue['code'] for issue in report['issues'])
    populated_fields: Counter[str] = Counter()
    for entry in entries:
        populated_fields.update(
            key for key, value in entry.items()
            if not key.startswith('_') and value not in ('', None, [], {})
        )

    return ({
        'filename': path.name,
        'bytes': path.stat().st_size,
        'sha256': _sha256(path),
        'status': report['status'],
        'detected_entries': report['detected_entries'],
        'parsed_entries': report['parsed_entries'],
        'skipped_entries': report['skipped_entries'],
        'missing_abstract_entries': report['missing_abstract_entries'],
        'error_count': report['error_count'],
        'warning_count': report['warning_count'],
        'issue_codes': dict(sorted(issue_codes.items())),
        'populated_fields': dict(sorted(populated_fields.items())),
        'parser_error': str(parser_error) if parser_error else '',
    }, entries)


def _quality_file_baseline(path: Path) -> Dict[str, Any]:
    with path.open('rb') as source:
        signature = source.read(8).hex()
    return {
        'filename': path.name,
        'bytes': path.stat().st_size,
        'sha256': _sha256(path),
        'extension': path.suffix.lower(),
        'signature': signature,
    }


def _files(directory: Path) -> Iterable[Path]:
    return sorted((path for path in directory.iterdir() if path.is_file()), key=lambda path: path.name)


def build_regression_baseline(sample_root: Path) -> Dict[str, Any]:
    """Parse the supplied sample corpus and return stable, JSON-serializable metrics."""
    screening_dir = sample_root / 'Screen_input'
    quality_dir = sample_root / 'QA_input'
    if not screening_dir.is_dir() or not quality_dir.is_dir():
        raise FileNotFoundError(
            f'回归样本目录不完整，期望存在 {screening_dir} 和 {quality_dir}'
        )

    screening = []
    all_entries: list[Dict[str, Any]] = []
    for path in _files(screening_dir):
        file_baseline, entries = _screening_file_baseline(path)
        screening.append(file_baseline)
        all_entries.extend(entries)

    quality_assessment = [_quality_file_baseline(path) for path in _files(quality_dir)]

    title_groups: defaultdict[str, int] = defaultdict(int)
    untitled_entries = 0
    for entry in all_entries:
        normalized = _normalized_title(entry.get('title'))
        if normalized:
            title_groups[normalized] += 1
        else:
            untitled_entries += 1
    duplicate_sizes = [size for size in title_groups.values() if size > 1]

    return {
        'schema_version': BASELINE_SCHEMA_VERSION,
        'aggregate': {
            'screening_file_count': len(screening),
            'qa_file_count': len(quality_assessment),
            'parsed_entries': len(all_entries),
            'untitled_entries': untitled_entries,
            'normalized_title_groups': len(title_groups),
            'duplicate_groups': len(duplicate_sizes),
            'duplicate_entries': sum(size - 1 for size in duplicate_sizes),
            'kept_entries': untitled_entries + len(title_groups),
        },
        'screening': screening,
        'quality_assessment': quality_assessment,
    }
