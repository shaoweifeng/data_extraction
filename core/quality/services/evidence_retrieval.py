"""Deterministic, local evidence retrieval over one QA full-text asset."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from copy import deepcopy
from typing import Iterable

from django.conf import settings

from core.quality.domain.methods import get_method_config


RETRIEVAL_VERSION = 'qa-evidence-lexical-v1'
_WORD_RE = re.compile(r'[a-z0-9][a-z0-9_-]{2,}', re.I)
_CJK_RE = re.compile(r'[\u3400-\u9fff]+')
_WHITESPACE_RE = re.compile(r'\s+')
_STOPWORDS = frozenset({
    'and', 'are', 'for', 'from', 'have', 'into', 'not', 'that', 'the', 'their',
    'this', 'was', 'were', 'with', '是否', '判断', '研究', '患者', '结果', '问题',
    '信息', '进行', '存在', '评价',
})
_REQUIRED_CHUNK_FIELDS = {
    'chunk_id', 'page_start', 'page_end', 'section', 'sha256', 'text',
}


class EvidenceRetrievalError(ValueError):
    """Raised when evidence cannot be read safely from the requested reference."""


def _normalize(value: str) -> str:
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return _WHITESPACE_RE.sub(' ', value).strip()


def _terms(value: str) -> set[str]:
    normalized = _normalize(value)
    terms = {
        word for word in _WORD_RE.findall(normalized)
        if word not in _STOPWORDS
    }
    for sequence in _CJK_RE.findall(normalized):
        if sequence in _STOPWORDS:
            continue
        for width in (2, 3, 4):
            if len(sequence) < width:
                continue
            terms.update(
                sequence[index:index + width]
                for index in range(len(sequence) - width + 1)
                if sequence[index:index + width] not in _STOPWORDS
            )
    return terms


def _english_lexemes(value: str) -> set[str]:
    return {
        word.casefold() for word in _WORD_RE.findall(_normalize(value))
        if word.casefold() not in _STOPWORDS
    }


def _lexeme_matches(query_word: str, text_words: set[str]) -> bool:
    if query_word in text_words:
        return True
    # Covers deterministic morphology such as enrollment/enrolled and sample/sampling
    # without admitting short, noisy prefix matches.
    for text_word in text_words:
        if len(query_word) < 5 or len(text_word) < 5:
            continue
        common = 0
        for left, right in zip(query_word, text_word):
            if left != right:
                break
            common += 1
        if common >= 5:
            return True
    return False


def _phrase_hits(text: str, queries: Iterable[str]) -> tuple[float, list[str]]:
    score = 0.0
    matched = []
    text_words = _english_lexemes(text)
    for query in queries:
        phrase = _normalize(query)
        if not phrase:
            continue
        count = min(text.count(phrase), 3)
        query_words = _english_lexemes(phrase)
        lexical_match = bool(query_words) and all(
            _lexeme_matches(word, text_words) for word in query_words
        )
        if not count and lexical_match:
            count = 1
        if count:
            matched.append(str(query))
            # Longer phrases are more specific, while repeated hits have a bounded benefit.
            score += 10.0 + min(6.0, math.log2(len(phrase) + 1) * 1.5) + (count - 1) * 2.0
    return score, matched


def _question_overlap(text: str, question_terms: set[str]) -> tuple[float, list[str]]:
    matched = sorted(term for term in question_terms if term in text)
    return min(12.0, len(matched) * 1.5), matched[:20]


def _section_score(section: str, preferred_sections: list[str]) -> float:
    try:
        index = preferred_sections.index(section)
    except ValueError:
        return 0.0
    return max(2.0, 7.0 - index * 1.5)


def _candidate(chunk: dict, index: int, signal: dict, *, fallback: bool) -> dict | None:
    text = _normalize(chunk.get('text', ''))
    retrieval = signal['retrieval']
    query_score, matched_queries = _phrase_hits(text, retrieval['queries'])
    question_text = f"{signal['signal_question']} {signal.get('signal_description', '')}"
    overlap_score, matched_terms = _question_overlap(text, _terms(question_text))
    section_score = _section_score(chunk.get('section', ''), retrieval['preferred_sections'])

    if not fallback and query_score <= 0:
        return None
    if fallback and overlap_score <= 0:
        return None
    score = query_score + overlap_score + section_score
    return {
        'chunk': chunk,
        'index': index,
        'score': round(score, 4),
        'matched_queries': matched_queries,
        'matched_terms': matched_terms,
        'section_bonus': round(section_score, 4),
        'fallback': fallback,
        'neighbor_of': '',
    }


def retrieve_for_signal(chunks: list[dict], signal: dict, *, max_chunks: int) -> list[dict]:
    """Return stable Top-N evidence for one signal question."""
    configured_max = signal['retrieval']['max_chunks']
    limit = max(1, min(max_chunks, configured_max))
    direct = [
        item for index, chunk in enumerate(chunks)
        if (item := _candidate(chunk, index, signal, fallback=False)) is not None
    ]
    used_fallback = False
    if not direct:
        used_fallback = True
        direct = [
            item for index, chunk in enumerate(chunks)
            if (item := _candidate(chunk, index, signal, fallback=True)) is not None
        ]
    direct.sort(key=lambda item: (-item['score'], item['index'], item['chunk']['chunk_id']))
    if not direct:
        return []

    primary_count = min(len(direct), max(1, (limit + 1) // 2))
    selected = direct[:primary_count]
    selected_ids = {item['chunk']['chunk_id'] for item in selected}
    # Adjacent context is useful for sentences split across deterministic chunks.
    for source in list(selected):
        if len(selected) >= limit:
            break
        for neighbor_index in (source['index'] - 1, source['index'] + 1):
            if neighbor_index < 0 or neighbor_index >= len(chunks):
                continue
            chunk = chunks[neighbor_index]
            if chunk['chunk_id'] in selected_ids:
                continue
            selected.append({
                'chunk': chunk,
                'index': neighbor_index,
                'score': round(source['score'] * 0.35, 4),
                'matched_queries': [],
                'matched_terms': [],
                'section_bonus': 0.0,
                'fallback': used_fallback,
                'neighbor_of': source['chunk']['chunk_id'],
            })
            selected_ids.add(chunk['chunk_id'])
            if len(selected) >= limit:
                break
    if len(selected) < limit:
        for candidate in direct[primary_count:]:
            if candidate['chunk']['chunk_id'] in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate['chunk']['chunk_id'])
            if len(selected) >= limit:
                break
    selected.sort(key=lambda item: (-item['score'], item['index'], item['chunk']['chunk_id']))
    return selected


def _public_candidate(item: dict, signal_key: str) -> dict:
    chunk = item['chunk']
    return {
        'chunk_id': chunk['chunk_id'],
        'page_start': chunk['page_start'],
        'page_end': chunk['page_end'],
        'section': chunk['section'],
        'sha256': chunk['sha256'],
        'char_count': chunk.get('char_count', len(chunk['text'])),
        'text': chunk['text'],
        'score': item['score'],
        'matched_queries': item['matched_queries'],
        'matched_terms': item['matched_terms'],
        'section_bonus': item['section_bonus'],
        'fallback': item['fallback'],
        'neighbor_of': item['neighbor_of'],
        'selected_for': [signal_key],
        'score_by_signal': {signal_key: item['score']},
    }


def _merge_domain_candidates(signal_results: dict[str, list[dict]], *, char_budget: int) -> list[dict]:
    merged: dict[str, dict] = {}
    # First preserve one best hit per signal where possible, then rank all remaining hits.
    priority = []
    remainder = []
    for signal_key, items in signal_results.items():
        if items:
            priority.append((signal_key, items[0]))
            remainder.extend((signal_key, item) for item in items[1:])
    remainder.sort(key=lambda pair: (-pair[1]['score'], pair[1]['index'], pair[1]['chunk']['chunk_id']))

    used_chars = 0
    for signal_key, item in priority + remainder:
        chunk_id = item['chunk']['chunk_id']
        if chunk_id in merged:
            existing = merged[chunk_id]
            if signal_key not in existing['selected_for']:
                existing['selected_for'].append(signal_key)
            existing['score_by_signal'][signal_key] = item['score']
            existing['score'] = max(existing['score'], item['score'])
            existing['matched_queries'] = sorted(set(existing['matched_queries'] + item['matched_queries']))
            existing['matched_terms'] = sorted(set(existing['matched_terms'] + item['matched_terms']))[:20]
            continue
        candidate = _public_candidate(item, signal_key)
        chunk_chars = len(candidate['text'])
        if used_chars + chunk_chars > char_budget:
            continue
        merged[chunk_id] = candidate
        used_chars += chunk_chars

    output = list(merged.values())
    output.sort(key=lambda item: (-item['score'], item['page_start'], item['chunk_id']))
    return output


def build_method_evidence_packages(
    chunks: list[dict],
    method_config: dict,
    reference_info: dict,
    *,
    max_chars_per_domain: int,
    max_chunks_per_signal: int,
) -> list[dict]:
    """Build one bounded, deduplicated evidence package per configured domain."""
    signals_by_domain: dict[str, list[dict]] = defaultdict(list)
    for signal in method_config['signal_items']:
        signals_by_domain[signal['domain']].append(signal)

    domain_names = {domain['key']: domain['name'] for domain in method_config['domains']}
    packages = []
    for domain_key, signals in signals_by_domain.items():
        signal_results = {
            signal['signal_key']: retrieve_for_signal(
                chunks, signal, max_chunks=max_chunks_per_signal,
            )
            for signal in signals
        }
        selected = _merge_domain_candidates(signal_results, char_budget=max_chars_per_domain)
        coverage = {
            signal['signal_key']: [
                item['chunk']['chunk_id'] for item in signal_results[signal['signal_key']]
                if item['chunk']['chunk_id'] in {chunk['chunk_id'] for chunk in selected}
            ]
            for signal in signals
        }
        package = {
            'retrieval_version': RETRIEVAL_VERSION,
            'method_key': method_config['key'],
            'method_config_version': method_config['config_version'],
            'method_variant': method_config.get('variant_key', ''),
            'domain': domain_key,
            'domain_name': domain_names[domain_key],
            'reference': deepcopy(reference_info),
            'signal_items': [deepcopy(signal) for signal in signals],
            'selected_chunks': selected,
            'signal_coverage': coverage,
            'char_count': sum(len(item['text']) for item in selected),
            'char_budget': max_chars_per_domain,
        }
        snapshot = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        package['snapshot_sha256'] = hashlib.sha256(snapshot.encode('utf-8')).hexdigest()
        packages.append(package)
    return packages


def load_verified_chunks(asset) -> list[dict]:
    if not asset.chunk_index_file or not asset.chunk_index_file.name:
        raise EvidenceRetrievalError('全文分块尚未生成。')
    asset.chunk_index_file.open('rb')
    try:
        max_bytes = max(1_000_000, settings.QA_PDF_TEXT_MAX_CHARS * 6)
        payload = asset.chunk_index_file.read(max_bytes + 1)
    finally:
        asset.chunk_index_file.close()
    if len(payload) > max_bytes:
        raise EvidenceRetrievalError('全文分块文件异常过大，请重新生成分块。')
    if hashlib.sha256(payload).hexdigest() != asset.chunk_index_sha256:
        raise EvidenceRetrievalError('全文分块文件校验失败，请重新生成分块。')
    try:
        chunks = [json.loads(line) for line in payload.decode('utf-8').splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRetrievalError('全文分块文件无法解析，请重新生成分块。') from exc
    if len(chunks) != asset.chunk_count:
        raise EvidenceRetrievalError('全文分块数量不一致，请重新生成分块。')
    chunk_ids = set()
    for chunk in chunks:
        if not isinstance(chunk, dict) or not _REQUIRED_CHUNK_FIELDS.issubset(chunk):
            raise EvidenceRetrievalError('全文分块结构无效，请重新生成分块。')
        if chunk['chunk_id'] in chunk_ids:
            raise EvidenceRetrievalError('全文分块 ID 重复，请重新生成分块。')
        chunk_ids.add(chunk['chunk_id'])
        if not (
            isinstance(chunk['page_start'], int)
            and isinstance(chunk['page_end'], int)
            and 1 <= chunk['page_start'] <= chunk['page_end']
        ):
            raise EvidenceRetrievalError('全文分块页码无效，请重新生成分块。')
        text = chunk['text']
        if not isinstance(text, str) or hashlib.sha256(text.encode('utf-8')).hexdigest() != chunk['sha256']:
            raise EvidenceRetrievalError('全文分块正文校验失败，请重新生成分块。')
    return chunks


# Backward-compatible private alias for stage-4 tests and internal callers.
_load_verified_chunks = load_verified_chunks


def build_reference_evidence_packages(reference) -> list[dict]:
    """Load and retrieve evidence strictly inside one reference and project boundary."""
    try:
        asset = reference.fulltext_asset
    except Exception as exc:
        raise EvidenceRetrievalError('文献没有可用的全文资产。') from exc
    if asset.qa_reference_id != reference.id or asset.project_id != reference.project_id:
        raise EvidenceRetrievalError('全文资产与文献或项目不匹配。')
    if asset.status != 'ready' or asset.extraction_status != 'completed':
        raise EvidenceRetrievalError('全文资产尚未完成处理。')
    method = get_method_config(
        reference.quality_method,
        reference.quality_method_variant or None,
    )
    if not method['ai_supported']:
        raise EvidenceRetrievalError(method.get('ai_unavailable_reason') or '该方法暂不支持 AI 评价。')
    chunks = load_verified_chunks(asset)
    abstract = reference.abstract or ''
    abstract_limit = settings.QA_AI_MAX_CONTENT_CHARS
    reference_info = {
        'id': reference.id,
        'project_id': reference.project_id,
        'title': reference.title,
        'first_author': reference.first_author,
        'year': reference.year,
        'journal': reference.journal,
        'doi': reference.doi,
        'abstract': abstract[:abstract_limit],
        'abstract_truncated': len(abstract) > abstract_limit,
        'asset_id': asset.id,
        'chunk_index_sha256': asset.chunk_index_sha256,
        'chunking_version': asset.chunking_version,
    }
    return build_method_evidence_packages(
        chunks,
        method,
        reference_info,
        max_chars_per_domain=settings.QA_EVIDENCE_MAX_CHARS_PER_DOMAIN,
        max_chunks_per_signal=settings.QA_EVIDENCE_MAX_CHUNKS_PER_SIGNAL,
    )
