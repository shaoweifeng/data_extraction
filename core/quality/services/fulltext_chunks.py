"""Deterministic, page-aware chunking for quality-evaluation full text."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable, Sequence


CHUNKING_VERSION = 'qa-chunks-v2-spans'
EVIDENCE_SPAN_MAX_CHARS = 400
EVIDENCE_SPAN_MIN_BOUNDARY_CHARS = 80


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class _TextUnit:
    page_number: int
    section: str
    text: str
    estimated_tokens: int
    evidence_spans: tuple[dict, ...]


_SECTION_PATTERNS = (
    ('abstract', re.compile(r'^(abstract|摘要)$', re.I)),
    ('introduction', re.compile(r'^(introduction|background|引言|背景)$', re.I)),
    ('methods', re.compile(
        r'^(materials?\s+and\s+methods?|methods?|methodology|patients?\s+and\s+methods?|'
        r'study\s+design|研究方法|材料与方法|对象与方法|方法)$', re.I,
    )),
    ('participants', re.compile(
        r'^(participants?|patients?|study\s+population|subjects?|研究对象|患者|受试者)$', re.I,
    )),
    ('results', re.compile(r'^(results?|findings?|结果)$', re.I)),
    ('discussion', re.compile(r'^(discussion|讨论)$', re.I)),
    ('conclusion', re.compile(r'^(conclusions?|结论)$', re.I)),
    ('references', re.compile(r'^(references?|bibliography|参考文献)$', re.I)),
    ('appendix', re.compile(r'^(appendix|supplementary\s+materials?|附录|补充材料)$', re.I)),
)


def estimate_tokens(text: str) -> int:
    """Return a stable local estimate without requiring a provider tokenizer."""
    if not text:
        return 0
    cjk = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]', text))
    non_cjk = max(0, len(text) - cjk)
    return max(1, cjk + (non_cjk + 3) // 4)


def _normalize_text(text: str) -> str:
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n')]
    return '\n'.join(lines).strip()


def detect_section(line: str) -> str | None:
    candidate = re.sub(r'^\s*(?:\d+(?:\.\d+)*[.)]?\s*)', '', line or '').strip()
    candidate = candidate.rstrip(':：.').strip()
    if not candidate or len(candidate) > 80:
        return None
    for section, pattern in _SECTION_PATTERNS:
        if pattern.fullmatch(candidate):
            return section
    return None


def _cut_to_token_budget(text: str, budget: int) -> tuple[str, str]:
    """Split text at a readable boundary while staying within an estimated budget."""
    if estimate_tokens(text) <= budget:
        return text, ''
    low, high = 1, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    cut = low
    floor = max(1, cut // 2)
    boundary = max(
        text.rfind('\n', floor, cut),
        text.rfind('。', floor, cut),
        text.rfind('.', floor, cut),
        text.rfind('；', floor, cut),
        text.rfind(';', floor, cut),
        text.rfind(' ', floor, cut),
    )
    if boundary >= floor:
        cut = boundary + 1
    return text[:cut].strip(), text[cut:].strip()


def _split_evidence_text(
    text: str,
    *,
    max_chars: int = EVIDENCE_SPAN_MAX_CHARS,
    min_boundary_chars: int = EVIDENCE_SPAN_MIN_BOUNDARY_CHARS,
) -> list[str]:
    """Split exact normalized text into short, deterministic citation spans."""
    if max_chars <= 0:
        raise ValueError('max_chars must be positive')
    if min_boundary_chars < 0 or min_boundary_chars >= max_chars:
        raise ValueError('min_boundary_chars must be non-negative and below max_chars')

    remaining = (text or '').strip()
    spans = []
    while remaining:
        if len(remaining) <= max_chars:
            spans.append(remaining)
            break

        window = remaining[:max_chars]
        boundary = -1
        for marker in ('\n', '。', '！', '？', '.', '!', '?', '；', ';'):
            position = window.rfind(marker, min_boundary_chars)
            if position >= 0:
                boundary = max(boundary, position + 1)
        if boundary < min_boundary_chars:
            whitespace = window.rfind(' ', min_boundary_chars)
            if whitespace >= min_boundary_chars:
                boundary = whitespace
        if boundary < min_boundary_chars:
            boundary = max_chars

        piece = remaining[:boundary].strip()
        if piece:
            spans.append(piece)
        remaining = remaining[boundary:].strip()
    return spans


def _make_evidence_spans(
    *,
    page_number: int,
    section: str,
    text: str,
    first_ordinal: int,
) -> tuple[tuple[dict, ...], int]:
    spans = []
    ordinal = first_ordinal
    for piece in _split_evidence_text(text):
        digest = hashlib.sha256(piece.encode('utf-8')).hexdigest()
        spans.append({
            'span_id': f'p{page_number:04d}-s{ordinal:04d}-{digest[:8]}',
            'page_number': page_number,
            'section': section,
            'char_count': len(piece),
            'sha256': digest,
            'text': piece,
        })
        ordinal += 1
    return tuple(spans), ordinal


def _page_units(pages: Sequence[PageText], target_tokens: int) -> list[_TextUnit]:
    units: list[_TextUnit] = []
    current_section = 'unknown'
    for page in pages:
        span_ordinal = 1
        normalized = _normalize_text(page.text)
        if not normalized:
            continue
        paragraphs = []
        for block in (item.strip() for item in re.split(r'\n\s*\n+', normalized)):
            if not block:
                continue
            buffer = []
            for line in block.split('\n'):
                if detect_section(line):
                    if buffer:
                        paragraphs.append('\n'.join(buffer).strip())
                        buffer = []
                    paragraphs.append(line.strip())
                else:
                    buffer.append(line)
            if buffer:
                paragraphs.append('\n'.join(buffer).strip())
        for paragraph in paragraphs:
            first_line = paragraph.split('\n', 1)[0]
            detected = detect_section(first_line)
            if detected:
                current_section = detected
            remaining = paragraph
            while remaining:
                piece, remaining = _cut_to_token_budget(remaining, target_tokens)
                if not piece:
                    break
                evidence_spans, span_ordinal = _make_evidence_spans(
                    page_number=page.page_number,
                    section=current_section,
                    text=piece,
                    first_ordinal=span_ordinal,
                )
                units.append(_TextUnit(
                    page_number=page.page_number,
                    section=current_section,
                    text=piece,
                    estimated_tokens=estimate_tokens(piece),
                    evidence_spans=evidence_spans,
                ))
    return units


def build_chunks(
    pages: Sequence[PageText],
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> list[dict]:
    """Create stable chunks with page ranges, section labels and bounded overlap."""
    if target_tokens <= 0:
        raise ValueError('target_tokens must be positive')
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError('overlap_tokens must be non-negative and below target_tokens')

    units = _page_units(pages, target_tokens)
    chunks: list[dict] = []
    current: list[_TextUnit] = []
    current_tokens = 0

    def emit() -> None:
        if not current:
            return
        text = '\n\n'.join(unit.text for unit in current).strip()
        index = len(chunks) + 1
        page_start = min(unit.page_number for unit in current)
        page_end = max(unit.page_number for unit in current)
        section = current[0].section if all(
            unit.section == current[0].section for unit in current
        ) else 'mixed'
        evidence_spans = []
        seen_span_ids = set()
        for unit in current:
            for span in unit.evidence_spans:
                if span['span_id'] in seen_span_ids:
                    continue
                seen_span_ids.add(span['span_id'])
                evidence_spans.append(span)
        chunks.append({
            'chunk_id': f'p{page_start:04d}-p{page_end:04d}-c{index:04d}',
            'page_start': page_start,
            'page_end': page_end,
            'section': section,
            'estimated_tokens': estimate_tokens(text),
            'char_count': len(text),
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'text': text,
            'evidence_spans': evidence_spans,
        })

    for unit in units:
        section_changed = current and unit.section != current[-1].section
        exceeds_target = current and current_tokens + unit.estimated_tokens > target_tokens
        if section_changed or exceeds_target:
            emit()
            overlap: list[_TextUnit] = []
            overlap_size = 0
            if not section_changed and overlap_tokens:
                for previous in reversed(current):
                    if overlap_size + previous.estimated_tokens > overlap_tokens:
                        break
                    overlap.insert(0, previous)
                    overlap_size += previous.estimated_tokens
            current = overlap
            current_tokens = overlap_size
        current.append(unit)
        current_tokens += unit.estimated_tokens
    emit()
    return chunks


def serialize_chunks(chunks: Iterable[dict]) -> bytes:
    lines = [
        json.dumps(chunk, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        for chunk in chunks
    ]
    return (('\n'.join(lines) + '\n') if lines else '').encode('utf-8')


def load_chunks(field_file) -> list[dict]:
    if not field_file or not field_file.name:
        return []
    field_file.open('rb')
    try:
        return [
            json.loads(line)
            for line in field_file.read().decode('utf-8').splitlines()
            if line.strip()
        ]
    finally:
        field_file.close()
