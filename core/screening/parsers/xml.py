"""XML reference parser."""

import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List


def _itext(elem):
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


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
        "source_file": source_file,
        "source_position": position,
        "type": "XML",
    }


def parse_xml(file_path: str) -> List[Dict]:
    """Parse EndNote or internal reference XML while releasing completed records."""
    parsed_entries = []
    source_file = os.path.basename(file_path)
    root_tag = None

    for event, elem in ET.iterparse(file_path, events=("start", "end")):
        if root_tag is None and event == "start":
            root_tag = elem.tag.lower()
            continue
        if event != "end":
            continue

        tag = elem.tag.lower()
        if root_tag == "xml" and tag == "record":
            parsed_entries.append(_normalize_endnote_record(elem, source_file, len(parsed_entries) + 1))
            elem.clear()
        elif root_tag != "xml" and tag == "reference":
            parsed_entries.append(_normalize_internal_reference(elem, source_file, len(parsed_entries) + 1))
            elem.clear()

    return parsed_entries
