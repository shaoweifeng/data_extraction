"""Compatibility exports; deterministic chunking is shared with fulltext rescreening."""
from core.fulltext.chunks import (  # noqa: F401
    CHUNKING_VERSION, EVIDENCE_SPAN_MAX_CHARS, EVIDENCE_SPAN_MIN_BOUNDARY_CHARS,
    PageText, build_chunks, serialize_chunks, estimate_tokens, detect_section,
)
