"""Shared parser contracts."""

from typing import Any, Dict, Iterable, List, TypedDict


# v1.5.0 后数据库化改造的解析字段契约。解析器可以不提供某个可选字段，
# 但不应在没有同步更新契约和回归基线的情况下返回新的顶层字段。
REFERENCE_RECORD_FIELDS = frozenset({
    'title', 'authors', 'journal', 'year', 'volume', 'issue', 'page', 'date',
    'doi', 'pmcid', 'abstract', 'url', 'address', 'keywords', 'database',
    'publisher', 'organization', 'reference_type', 'type', 'record_number',
    'source_file', 'source_position', 'source_identifier', 'source_type',
    '_raw_metadata',
})


class ReferenceRecord(TypedDict, total=False):
    """Normalized record returned by every screening reference parser."""

    title: str
    authors: List[str]
    journal: str
    year: str
    volume: str
    issue: str
    page: str
    date: str
    doi: str
    pmcid: str
    abstract: str
    url: str
    address: str
    keywords: str
    database: str
    publisher: str
    organization: str
    reference_type: str
    type: str
    record_number: str
    source_file: str
    source_position: int
    source_identifier: str
    source_type: str
    _raw_metadata: Dict[str, Any]


ParserResult = List[Dict[str, Any]]
ReferenceRecordStream = Iterable[ReferenceRecord]
