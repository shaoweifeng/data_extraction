"""XML reference parser."""

import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List


def _itext(elem):
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _local_name(tag: str) -> str:
    """Return an XML tag name without its optional namespace."""
    return tag.rsplit("}", 1)[-1].lower()


def _first_descendant_text(parent, names):
    wanted = {name.lower() for name in names}
    for elem in parent.iter():
        if _local_name(elem.tag) in wanted:
            text = _itext(elem)
            if text:
                return text
    return ""


def _first_text(parent, paths):
    for path in paths:
        text = _itext(parent.find(path))
        if text:
            return text
    return ""


def _normalize_endnote_record(rec, source_file: str, position: int) -> Dict:
    title = _first_text(rec, ["./titles/title"])
    journal = _first_text(rec, ["./titles/secondary-title", "./periodical/full-title"])
    year_raw = _first_text(rec, ["./dates/year", "./pub-dates/year", "./dates/pub-dates/year"])
    year_match = re.search(r"\b(19|20)\d{2}\b", year_raw)
    year = year_match.group(0) if year_match else (year_raw[:4] if year_raw else "")
    ref_type = rec.find("./ref-type")
    reference_type = (ref_type.get("name") or "") if ref_type is not None else ""
    date = _first_text(rec, ["./dates/pub-dates/date", "./pub-dates/date", "./dates/date"])
    if year and date and year not in date:
        date = f"{date} {year}"

    authors = [text for author in rec.findall("./contributors/authors/author") if (text := _itext(author))]
    doi_raw = _first_text(rec, ["./doi", "./electronic-resource-num"])
    doi_raw = doi_raw.replace("doi:", "").replace("DOI:", "").strip()
    doi = (doi_raw.split()[0] if doi_raw else "").strip().rstrip(".").rstrip(";").strip()
    accession = _first_text(rec, ["./accession-num"]).strip()
    wos_match = re.search(r"\bWOS:\w+\b", accession)
    wos_id = accession if accession.upper().startswith("WOS:") else (wos_match.group(0) if wos_match else "")

    if accession.isdigit():
        url = f"https://pubmed.ncbi.nlm.nih.gov/{accession}/"
    elif doi:
        url = f"https://doi.org/{doi}"
    elif wos_id:
        url = f"https://www.webofscience.com/wos/woscc/full-record/{wos_id}"
    else:
        url = ""

    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "reference_type": reference_type,
        "volume": _first_text(rec, ["./volume"]),
        "issue": _first_text(rec, ["./number"]),
        "page": _first_text(rec, ["./pages"]),
        "date": date,
        "pmcid": _first_text(rec, ["./custom2"]),
        "address": _first_text(rec, ["./auth-address"]),
        "abstract": _first_text(rec, ["./abstract"]),
        "doi": doi,
        "url": url,
        "source_file": source_file,
        "source_position": position,
        "record_number": _first_text(rec, ["./rec-number"]),
        "type": "XML",
    }


def _normalize_internal_reference(ref, source_file: str, position: int) -> Dict:
    authors = [text for author in ref.findall("./Authors/Author") if (text := _itext(author))]
    if not authors:
        authors_text = _first_text(ref, ["Authors"])
        authors = [item.strip() for item in authors_text.split(";") if item.strip()]
    return {
        "title": _first_text(ref, ["Title"]),
        "authors": authors,
        "journal": _first_text(ref, ["Journal"]),
        "year": _first_text(ref, ["Year"]),
        "abstract": _first_text(ref, ["Abstract"]),
        "doi": _first_text(ref, ["DOI", "Doi", "doi"]),
        "url": _first_text(ref, ["URL", "Url", "url"]),
        "address": _first_text(ref, ["Address"]),
        "source_file": source_file,
        "source_position": position,
        "type": "XML",
    }


def _normalize_embase_item(item, source_file: str, position: int) -> Dict:
    """Normalize one Elsevier/Embase ``bibdataset/item`` record."""
    doi = _first_descendant_text(item, ["doi"])

    source_identifier = ""
    for elem in item.iter():
        if _local_name(elem.tag) == "itemid" and (elem.get("idtype") or "").upper() == "PUI":
            source_identifier = _itext(elem)
            break

    # Embase repeats authors in multiple author-group elements for affiliations.
    # Sequence number is the stable identity and also restores the publication order.
    authors_by_sequence = {}
    authors_without_sequence = []
    seen_unsequenced = set()
    for author in (elem for elem in item.iter() if _local_name(elem.tag) == "author"):
        name = _first_descendant_text(author, ["indexed-name"])
        if not name:
            surname = _first_descendant_text(author, ["surname"])
            given_name = _first_descendant_text(author, ["given-name"])
            name = " ".join(part for part in (surname, given_name) if part).strip()
        if not name:
            continue
        sequence = (author.get("seq") or "").strip()
        if sequence:
            authors_by_sequence.setdefault(sequence, name)
        elif name.casefold() not in seen_unsequenced:
            authors_without_sequence.append(name)
            seen_unsequenced.add(name.casefold())

    def _sequence_sort_key(value):
        return (0, int(value)) if value.isdigit() else (1, value)

    authors = [
        authors_by_sequence[key]
        for key in sorted(authors_by_sequence, key=_sequence_sort_key)
    ]
    authors.extend(authors_without_sequence)

    publication_year = next(
        (elem for elem in item.iter() if _local_name(elem.tag) == "publicationyear"),
        None,
    )
    year = (publication_year.get("first") or "").strip() if publication_year is not None else ""
    if not year:
        publication_date = next(
            (elem for elem in item.iter() if _local_name(elem.tag) == "publicationdate"),
            None,
        )
        year = _first_descendant_text(publication_date, ["year"]) if publication_date is not None else ""

    publication_date = next(
        (elem for elem in item.iter() if _local_name(elem.tag) == "publicationdate"),
        None,
    )
    date_parts = []
    if publication_date is not None:
        for name in ("year", "month", "day"):
            value = _first_descendant_text(publication_date, [name])
            if value:
                date_parts.append(value.zfill(2) if name != "year" else value)

    abstract_parts = []
    abstracts = next(
        (elem for elem in item.iter() if _local_name(elem.tag) == "abstracts"),
        None,
    )
    if abstracts is not None:
        abstract_parts = [
            text for elem in abstracts.iter()
            if _local_name(elem.tag) == "para" and (text := _itext(elem))
        ]

    volume_issue = next(
        (elem for elem in item.iter() if _local_name(elem.tag) == "voliss"),
        None,
    )
    citation_type = next(
        (elem for elem in item.iter() if _local_name(elem.tag) == "citation-type"),
        None,
    )
    organizations = []
    seen_organizations = set()
    for elem in item.iter():
        if _local_name(elem.tag) != "organization":
            continue
        organization = _itext(elem)
        if organization and organization.casefold() not in seen_organizations:
            organizations.append(organization)
            seen_organizations.add(organization.casefold())

    fulltext_url = (item.get("fulltexturl") or "").strip()
    return {
        "title": _first_descendant_text(item, ["titletext"]),
        "authors": authors,
        "journal": _first_descendant_text(item, ["sourcetitle"]),
        "year": year,
        "reference_type": (citation_type.get("code") or "") if citation_type is not None else "",
        "volume": (volume_issue.get("volume") or "") if volume_issue is not None else "",
        "issue": (volume_issue.get("issue") or "") if volume_issue is not None else "",
        "page": _first_descendant_text(item, ["pagerange", "article-number"]),
        "date": "-".join(date_parts),
        "address": "; ".join(organizations),
        "abstract": "\n".join(abstract_parts),
        "doi": doi,
        "url": fulltext_url or (f"https://doi.org/{doi}" if doi else ""),
        "source_file": source_file,
        "source_position": position,
        "source_identifier": source_identifier or doi,
        "source_type": "EMBASE_XML",
        "type": "XML",
    }


def parse_xml(file_path: str) -> List[Dict]:
    """Parse EndNote, Elsevier/Embase, or internal XML record by record."""
    parsed_entries = []
    source_file = os.path.basename(file_path)
    root_tag = None

    for event, elem in ET.iterparse(file_path, events=("start", "end")):
        if root_tag is None and event == "start":
            root_tag = _local_name(elem.tag)
            continue
        if event != "end":
            continue

        tag = _local_name(elem.tag)
        if root_tag == "xml" and tag == "record":
            parsed_entries.append(_normalize_endnote_record(elem, source_file, len(parsed_entries) + 1))
            elem.clear()
        elif root_tag == "bibdataset" and tag == "item":
            parsed_entries.append(_normalize_embase_item(elem, source_file, len(parsed_entries) + 1))
            elem.clear()
        elif root_tag != "xml" and tag == "reference":
            parsed_entries.append(_normalize_internal_reference(elem, source_file, len(parsed_entries) + 1))
            elem.clear()

    return parsed_entries
