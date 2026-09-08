"""Shared parser contracts."""

from typing import Any, Dict, List, TypedDict


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
    reference_type: str
    source_file: str
    source_position: int
    source_type: str


ParserResult = List[Dict[str, Any]]
