"""Web of Science CIW reference parser."""

import os
from typing import Dict, List


def _normalize_record(rec: Dict[str, List[str]], source_file: str, position: int) -> Dict:
    """Normalize one CIW record without retaining the whole source file."""
    clean = lambda value: (value or "").strip()

    title = " ".join(rec.get("TI", [])).strip()
    if not title:
        return {}

    authors = [a for a in rec.get("AU", []) if a] or [a for a in rec.get("AF", []) if a]
    journal = " ".join(rec.get("SO", [])).strip()
    year = clean(rec.get("PY", [""])[0]) if rec.get("PY") else ""
    reference_type = clean(rec.get("PT", [""])[0]) if rec.get("PT") else ""
    volume = clean(rec.get("VL", [""])[0]) if rec.get("VL") else ""
    issue = clean(rec.get("IS", [""])[0]) if rec.get("IS") else ""
    bp = clean(rec.get("BP", [""])[0]) if rec.get("BP") else ""
    ep = clean(rec.get("EP", [""])[0]) if rec.get("EP") else ""
    page = f"{bp}-{ep}" if bp and ep else (bp or ep)
    date = clean(rec.get("PD", [""])[0]) if rec.get("PD") else ""
    address = "; ".join(a for a in rec.get("C1", []) if a).strip()
    doi = clean(rec.get("DI", [""])[0]).rstrip(".").rstrip(";").strip() if rec.get("DI") else ""
    abstract = " ".join(rec.get("AB", [])).strip()
    pmid = clean(rec.get("PM", [""])[0]) if rec.get("PM") else ""
    ut = clean(rec.get("UT", [""])[0]) if rec.get("UT") else ""
    ur = clean(rec.get("UR", [""])[0]) if rec.get("UR") else ""

    if ur.lower().startswith(("http://", "https://")):
        url = ur
    elif doi:
        url = f"https://doi.org/{doi}"
    elif pmid.isdigit():
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    elif ut:
        url = f"https://www.webofscience.com/wos/woscc/full-record/{ut}"
    else:
        url = ""

    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "reference_type": reference_type,
        "volume": volume,
        "issue": issue,
        "page": page,
        "date": date,
        "address": address,
        "doi": doi,
        "abstract": abstract,
        "pmcid": "",
        "url": url,
        "source_file": source_file,
        "source_position": position,
        "record_number": ut,
        "source_type": "CIW",
    }


def parse_ciw(file_path: str) -> List[Dict]:
    """
    解析 CIW 格式文献（Web of Science 导出格式）

    CIW 格式特点：
    - 字段标签：TI, AU, AF, SO, PY, PT, VL, IS, BP, EP, PD, C1, DI, AB, PM, UT, UR, ER
    - 多值字段：AU, AF, C1（每行一个值）
    - 续行：以两个空格开头
    - 记录分隔：ER

    Args:
        file_path: CIW 文件路径

    Returns:
        标准化的文献字典列表
    """
    def clean(s):
        return (s or "").strip()

    def add_to_field(d, key, value):
        if key not in d:
            d[key] = []
        d[key].append(value)

    parsed_entries = []
    current = {}
    current_tag = None
    record_position = 0
    source_file = os.path.basename(file_path)

    def flush_record():
        nonlocal current, current_tag, record_position
        if current:
            record_position += 1
            normalized = _normalize_record(current, source_file, record_position)
            if normalized:
                parsed_entries.append(normalized)
        current = {}
        current_tag = None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue

            # 记录结束
            if line.strip() == "ER":
                flush_record()
                continue

            # 续行（以两个空格开头）
            if line.startswith("  ") and current_tag:
                add_to_field(current, current_tag, clean(line))
                continue

            # 新字段（格式：XX value，XX是两个字符的标签）
            if len(line) >= 3 and line[2] == " ":
                tag = line[:2]
                value = clean(line[3:])
                current_tag = tag
                if value:
                    add_to_field(current, tag, value)
                continue

    flush_record()

    return parsed_entries
