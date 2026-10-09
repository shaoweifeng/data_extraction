"""Authorized, bounded context lookup for persisted QA evidence citations."""

from __future__ import annotations

from core.quality.services.evidence_retrieval import (
    EvidenceRetrievalError,
    load_verified_chunks,
)


MAX_CONTEXT_CHARS_PER_CHUNK = 2400
MAX_CONTEXT_RADIUS = 1


def _cited_results(signal_item) -> list[dict]:
    return [
        result for result in (signal_item.model_results or [])
        if isinstance(result, dict) and result.get('evidence_chunk_id')
    ]


def get_signal_evidence_context(
    signal_item,
    *,
    chunk_id: str,
    model_id: str = '',
    radius: int = MAX_CONTEXT_RADIUS,
) -> dict:
    """Return a cited chunk and bounded neighbors; arbitrary full-text browsing is forbidden."""
    cited = _cited_results(signal_item)
    matching_citations = [
        result for result in cited
        if result.get('evidence_chunk_id') == chunk_id
        and (not model_id or result.get('model_id') == model_id)
    ]
    if not matching_citations:
        raise EvidenceRetrievalError('该证据块不属于当前评价结果。')

    try:
        asset = signal_item.qa_ref.fulltext_asset
    except Exception as exc:
        raise EvidenceRetrievalError('该文献的全文证据已不可用。') from exc
    if asset.project_id != signal_item.qa_ref.project_id:
        raise EvidenceRetrievalError('全文资产与项目不匹配。')

    chunks = load_verified_chunks(asset)
    index_by_id = {chunk['chunk_id']: index for index, chunk in enumerate(chunks)}
    if chunk_id not in index_by_id:
        raise EvidenceRetrievalError('引用的证据块已失效，请重新评价。')

    radius = max(0, min(int(radius), MAX_CONTEXT_RADIUS))
    center = index_by_id[chunk_id]
    start = max(0, center - radius)
    end = min(len(chunks), center + radius + 1)
    context = []
    for chunk in chunks[start:end]:
        text = chunk['text']
        context.append({
            'chunk_id': chunk['chunk_id'],
            'page_start': chunk['page_start'],
            'page_end': chunk['page_end'],
            'section': chunk['section'],
            'text': text[:MAX_CONTEXT_CHARS_PER_CHUNK],
            'text_truncated': len(text) > MAX_CONTEXT_CHARS_PER_CHUNK,
            'is_cited': chunk['chunk_id'] == chunk_id,
        })
    citation = matching_citations[0]
    return {
        'signal_item_id': signal_item.id,
        'model_id': citation.get('model_id', ''),
        'cited_chunk_id': chunk_id,
        'citation_page': citation.get('evidence_page', ''),
        'chunks': context,
    }
