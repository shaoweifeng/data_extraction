import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import bibtexparser
import rispy

def parse_ris(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        entries = rispy.load(f)
    
    def first_value(d, keys):
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (int, float)):
                return str(v)
        return None

    parsed_entries = []
    for i, entry in enumerate(entries, start=1):
        # Robust URL extraction
        url = entry.get('url')
        if not url:
            # Try 'urls' list (take first)
            urls = entry.get('urls')
            if urls and isinstance(urls, list) and len(urls) > 0:
                url = urls[0]
            # Try 'UR' key directly if rispy preserved it
            if not url:
                url = entry.get('UR')
            # Try 'L1' (File Link) or 'L2'
            if not url:
                url = entry.get('L1')
        
        reference_type = first_value(entry, ['type_of_reference', 'type', 'TY'])
        volume = first_value(entry, ['volume', 'VL'])
        issue = first_value(entry, ['number', 'issue', 'IS'])
        pages = first_value(entry, ['pages'])
        start_page = first_value(entry, ['start_page', 'sp', 'SP'])
        end_page = first_value(entry, ['end_page', 'ep', 'EP'])
        page = pages
        if not page:
            if start_page and end_page:
                page = f"{start_page}-{end_page}"
            elif start_page:
                page = start_page
            elif end_page:
                page = end_page

        date = first_value(entry, ['date', 'publication_date', 'DA', 'Y1'])
        pmcid = first_value(entry, ['pmcid', 'PMCID'])
        address = first_value(entry, ['address', 'AD'])

        parsed_entries.append({
            'title': entry.get('title') or entry.get('primary_title'),
            'authors': entry.get('authors', []),
            'journal': entry.get('journal_name') or entry.get('secondary_title'),
            'year': entry.get('year'),
            'reference_type': reference_type,
            'volume': volume,
            'issue': issue,
            'page': page,
            'date': date,
            'pmcid': pmcid,
            'address': address,
            'abstract': entry.get('abstract'),
            'doi': entry.get('doi'),
            'url': url,
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'type': 'RIS'
        })
    return parsed_entries

def parse_bib(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        library = bibtexparser.load(f)
    
    parsed_entries = []
    for i, entry in enumerate(library.entries, start=1):
        # BibTeX authors are often strings, need parsing if possible, but keeping simple for now
        authors = entry.get('author', '').replace('\n', ' ').split(' and ')
        
        # Robust URL extraction
        url = entry.get('url') or entry.get('link') or entry.get('URL')

        reference_type = entry.get('ENTRYTYPE') or entry.get('entrytype') or entry.get('type')
        volume = entry.get('volume')
        issue = entry.get('number') or entry.get('issue')
        page = entry.get('pages')
        year = entry.get('year')
        month = entry.get('month')
        date = None
        if month and year:
            date = f"{month} {year}"
        elif year:
            date = str(year)
        doi = entry.get('doi')
        pmcid = entry.get('pmcid') or entry.get('PMCID')
        address = entry.get('address')
        
        parsed_entries.append({
            'title': entry.get('title'),
            'authors': [a.strip() for a in authors if a.strip()],
            'journal': entry.get('journal'),
            'year': entry.get('year'),
            'reference_type': reference_type,
            'volume': volume,
            'issue': issue,
            'page': page,
            'date': date,
            'pmcid': pmcid,
            'address': address,
            'abstract': entry.get('abstract'),
            'doi': doi,
            'url': url,
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'type': 'BIB'
        })
    return parsed_entries

def parse_nbib(file_path):
    """
    解析 PubMed NBIB/Medline 格式文件。

    Medline 格式规则：
    - 每条记录以 PMID- 开头
    - 每个字段格式：TAG - value（tag 为 2-4 个字母，后跟空格和连字符）
    - 多行续行：以至少 6 个空格缩进，属于上一个 tag 的内容
    - 记录间以空行分隔（也可能紧接着下一条 PMID-）

    修复要点：
    1. 使用正则精确匹配 tag 行（避免把续行或 PMID- 误识别为 tag）
    2. 第二个 if 改为 elif，防止 PMID- 行被重复处理
    3. 续行对所有字段生效，不只是 TI/AB
    4. AD（机构地址）支持多行追加
    """
    import re

    TAG_RE = re.compile(r'^([A-Z]{2,6})\s*-\s*(.*)')

    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    entries = []
    current_entry = {}
    current_key = None  # 当前正在处理的字段 key，用于续行追加

    def _finalize_entry(entry):
        """入库前补全 URL，并删除内部标记字段"""
        if 'url' not in entry and 'pmid' in entry:
            entry['url'] = f"https://pubmed.ncbi.nlm.nih.gov/{entry['pmid']}"
        entry.pop('_has_fau', None)  # 删除内部标记，不输出到结果
        return entry

    def _append_continuation(entry, key, val):
        """把续行内容追加到对应字段"""
        if key == 'authors':
            # 作者列表不续行追加，忽略
            pass
        elif key in ('title', 'abstract', 'address', 'journal', 'date',
                     'volume', 'issue', 'page', 'pmcid', 'doi'):
            if key in entry and entry[key]:
                entry[key] += ' ' + val
            else:
                entry[key] = val

    for line in lines:
        line = line.rstrip('\r\n')

        # ── 空行：有些文件用空行分隔记录（但多数靠 PMID- 分隔，此处仅做保险）
        if not line.strip():
            continue

        # ── 续行检测：以 6 个及以上空格开头，且不是新的 tag 行
        if line.startswith('      ') and current_key:
            val = line.strip()
            if val:
                _append_continuation(current_entry, current_key, val)
            continue

        # ── 记录起始行：PMID- 开头（Medline 每条记录必须有 PMID）
        if line.startswith('PMID-'):
            if current_entry:
                entries.append(_finalize_entry(current_entry))
                current_entry = {}
            pmid_val = line[5:].strip().lstrip('-').strip()
            current_entry['pmid'] = pmid_val
            current_key = None  # PMID 本身不需要续行
            continue

        # ── 普通 tag 行
        m = TAG_RE.match(line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()

            # 将 Medline tag 映射到内部字段，同时记录 current_key 供续行使用
            # FAU = 作者全名（如 "Smith, John A"），AU = 作者缩写（如 "Smith JA"）
            # 同一条记录里 FAU 和 AU 是同一批人的两种写法，优先取 FAU，避免重复
            if key == 'FAU':
                current_entry.setdefault('authors', [])
                current_entry['authors'].append(val)
                current_entry['_has_fau'] = True
                current_key = 'authors'
            elif key == 'AU':
                # 只有当该记录没有 FAU 时才收集 AU（避免同一人重复）
                if not current_entry.get('_has_fau'):
                    current_entry.setdefault('authors', [])
                    current_entry['authors'].append(val)
                current_key = 'authors'
            elif key == 'TI':                       # 标题
                current_entry['title'] = val
                current_key = 'title'
            elif key == 'AB':                       # 摘要
                current_entry['abstract'] = val
                current_key = 'abstract'
            elif key == 'DP':                       # 发表日期，如 "2023 Jan"
                current_entry['date'] = val
                year_part = val.split()[0] if val else ''
                current_entry['year'] = year_part if re.match(r'\d{4}', year_part) else ''
                current_key = 'date'
            elif key in ('JT', 'TA'):               # 期刊全称 / 缩写（优先 JT）
                if 'journal' not in current_entry or key == 'JT':
                    current_entry['journal'] = val
                current_key = 'journal'
            elif key in ('UR', 'URL'):              # URL
                current_entry['url'] = val
                current_key = None
            elif key in ('PMCID', 'PMC'):           # PMC ID
                current_entry['pmcid'] = val
                current_key = 'pmcid'
            elif key == 'LID':                      # Location ID，可能包含 DOI
                if '[doi]' in val.lower():
                    current_entry['doi'] = val.lower().replace('[doi]', '').strip()
                    current_key = 'doi'
                else:
                    current_key = None
            elif key == 'AID':                      # Article ID，可能包含 DOI
                if '[doi]' in val.lower() and 'doi' not in current_entry:
                    current_entry['doi'] = val.lower().replace('[doi]', '').strip()
                    current_key = 'doi'
                else:
                    current_key = None
            elif key == 'VI':                       # 卷号
                current_entry['volume'] = val
                current_key = 'volume'
            elif key == 'IP':                       # 期号
                current_entry['issue'] = val
                current_key = 'issue'
            elif key == 'PG':                       # 页码
                current_entry['page'] = val
                current_key = 'page'
            elif key == 'AD':                       # 作者机构地址（可多行，多机构用分号拼接）
                if 'address' in current_entry and current_entry['address']:
                    current_entry['address'] += '; ' + val
                else:
                    current_entry['address'] = val
                current_key = 'address'
            elif key == 'PT':                       # 文献类型
                current_entry.setdefault('reference_type', val)
                current_key = None
            elif key == 'MH':                       # MeSH 词（可多值，存为列表备用）
                current_entry.setdefault('mesh_terms', [])
                current_entry['mesh_terms'].append(val)
                current_key = None
            else:
                # 未知字段：不追加续行，避免污染已有字段
                current_key = None
        # 其他格式不符合的行（如 "ER  "）直接跳过
        else:
            current_key = None

    # 收尾：保存最后一条记录
    if current_entry:
        entries.append(_finalize_entry(current_entry))

    parsed_entries = []
    for i, entry in enumerate(entries, start=1):
        parsed_entries.append({
            'title': entry.get('title'),
            'authors': entry.get('authors', []),
            'journal': entry.get('journal'),
            'year': entry.get('year'),
            'reference_type': entry.get('reference_type'),
            'volume': entry.get('volume'),
            'issue': entry.get('issue'),
            'page': entry.get('page'),
            'date': entry.get('date'),
            'pmcid': entry.get('pmcid'),
            'address': entry.get('address'),
            'abstract': entry.get('abstract'),
            'doi': entry.get('doi'),
            'url': entry.get('url'),
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'type': 'NBIB'
        })
    return parsed_entries

def parse_xml(file_path):
    def itext(elem):
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def first_text(parent, paths):
        for p in paths:
            e = parent.find(p)
            t = itext(e)
            if t:
                return t
        return ""

    tree = ET.parse(file_path)
    root = tree.getroot()

    records_node = root.find("./records")
    if root.tag == "xml" and records_node is not None:
        parsed_entries = []
        for i, rec in enumerate(records_node.findall("./record"), start=1):
            title = first_text(rec, ["./titles/title"])
            journal = first_text(rec, ["./titles/secondary-title", "./periodical/full-title"])
            year_raw = first_text(rec, ["./dates/year", "./pub-dates/year", "./dates/pub-dates/year"])
            year_match = re.search(r"\b(19|20)\d{2}\b", year_raw)
            year = year_match.group(0) if year_match else (year_raw[:4] if year_raw else "")
            reference_type = ""
            rt = rec.find("./ref-type")
            if rt is not None:
                reference_type = rt.get("name") or ""
            volume = first_text(rec, ["./volume"])
            issue = first_text(rec, ["./number"])
            page = first_text(rec, ["./pages"])
            date = first_text(rec, ["./dates/pub-dates/date", "./pub-dates/date", "./dates/date"])
            if year and date and year not in date:
                date = f"{date} {year}"
            address = first_text(rec, ["./auth-address"])
            pmcid = first_text(rec, ["./custom2"])

            authors = []
            for a in rec.findall("./contributors/authors/author"):
                t = itext(a)
                if t:
                    authors.append(t)

            abstract = first_text(rec, ["./abstract"])

            doi_raw = first_text(rec, ["./doi", "./electronic-resource-num"])
            doi_raw = doi_raw.replace("doi:", "").replace("DOI:", "").strip()
            doi = doi_raw.split()[0] if doi_raw else ""
            doi = doi.strip().rstrip(".").rstrip(";").strip()

            accession = first_text(rec, ["./accession-num"])
            accession = accession.strip()

            wos_id = ""
            if accession.upper().startswith("WOS:"):
                wos_id = accession
            else:
                m = re.search(r"\bWOS:\w+\b", accession)
                if m:
                    wos_id = m.group(0)

            url = ""
            if accession.isdigit():
                url = f"https://pubmed.ncbi.nlm.nih.gov/{accession}/"
            elif doi:
                url = f"https://doi.org/{doi}"
            elif wos_id:
                url = f"https://www.webofscience.com/wos/woscc/full-record/{wos_id}"

            parsed_entries.append({
                'title': title,
                'authors': authors,
                'journal': journal,
                'year': year,
                'reference_type': reference_type,
                'volume': volume,
                'issue': issue,
                'page': page,
                'date': date,
                'pmcid': pmcid,
                'address': address,
                'abstract': abstract,
                'doi': doi,
                'url': url,
                'source_file': os.path.basename(file_path),
                'source_position': i,
                'record_number': first_text(rec, ["./rec-number"]),
                'type': 'XML'
            })
        return parsed_entries

    parsed_entries = []
    for i, ref in enumerate(root.findall(".//Reference"), start=1):
        title = first_text(ref, ["Title"])
        authors = []
        for a in ref.findall("./Authors/Author"):
            t = itext(a)
            if t:
                authors.append(t)
        journal = first_text(ref, ["Journal"])
        year = first_text(ref, ["Year"])
        abstract = first_text(ref, ["Abstract"])
        doi = first_text(ref, ["DOI"])
        url = first_text(ref, ["URL"])
        parsed_entries.append({
            'title': title,
            'authors': authors,
            'journal': journal,
            'year': year,
            'abstract': abstract,
            'doi': doi,
            'url': url,
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'type': 'XML'
        })
    return parsed_entries

def parse_ciw(file_path):
    def clean(s):
        return (s or "").strip()

    def add_to_field(d, key, value):
        if key not in d:
            d[key] = []
        d[key].append(value)

    records = []
    current = {}
    current_tag = None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue

            if line.strip() == "ER":
                if current:
                    records.append(current)
                current = {}
                current_tag = None
                continue

            if line.startswith("  ") and current_tag:
                add_to_field(current, current_tag, clean(line))
                continue

            if len(line) >= 3 and line[2] == " ":
                tag = line[:2]
                value = clean(line[3:])
                current_tag = tag
                if value:
                    add_to_field(current, tag, value)
                continue

    if current:
        records.append(current)

    parsed_entries = []
    for i, rec in enumerate(records, start=1):
        title = " ".join(rec.get("TI", [])).strip()
        if not title:
            continue

        authors = [a for a in rec.get("AU", []) if a] or [a for a in rec.get("AF", []) if a]
        journal = " ".join(rec.get("SO", [])).strip()
        year = ""
        if rec.get("PY"):
            year = clean(rec.get("PY", [""])[0])
        reference_type = clean(rec.get("PT", [""])[0]) if rec.get("PT") else ""
        volume = clean(rec.get("VL", [""])[0]) if rec.get("VL") else ""
        issue = clean(rec.get("IS", [""])[0]) if rec.get("IS") else ""
        bp = clean(rec.get("BP", [""])[0]) if rec.get("BP") else ""
        ep = clean(rec.get("EP", [""])[0]) if rec.get("EP") else ""
        page = ""
        if bp and ep:
            page = f"{bp}-{ep}"
        elif bp:
            page = bp
        elif ep:
            page = ep
        date = clean(rec.get("PD", [""])[0]) if rec.get("PD") else ""
        address = "; ".join([a for a in rec.get("C1", []) if a]).strip()
        doi = ""
        if rec.get("DI"):
            doi = clean(rec.get("DI", [""])[0]).rstrip(".").rstrip(";").strip()
        abstract = " ".join(rec.get("AB", [])).strip()
        pmid = clean(rec.get("PM", [""])[0]) if rec.get("PM") else ""
        ut = clean(rec.get("UT", [""])[0]) if rec.get("UT") else ""
        ur = ""
        if rec.get("UR"):
            ur = clean(rec.get("UR", [""])[0])

        url = ""
        if ur.lower().startswith("http://") or ur.lower().startswith("https://"):
            url = ur
        elif doi:
            url = f"https://doi.org/{doi}"
        elif pmid.isdigit():
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        elif ut:
            url = f"https://www.webofscience.com/wos/woscc/full-record/{ut}"

        parsed_entries.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "year": year,
            "reference_type": reference_type,
            "volume": volume,
            "issue": issue,
            "page": page,
            "date": date,
            "pmcid": "",
            "address": address,
            "abstract": abstract,
            "doi": doi,
            "url": url,
            "source_file": os.path.basename(file_path),
            "source_position": i,
            "record_number": ut,
            "type": "CIW"
        })

    return parsed_entries

def convert_to_xml(entries, output_path):
    root = ET.Element("References")
    
    for entry in entries:
        ref_node = ET.SubElement(root, "Reference")
        
        # Helper to create sub-elements safely
        def add_field(parent, tag, value):
            if value:
                elem = ET.SubElement(parent, tag)
                elem.text = str(value)
            # Force add URL tag even if empty, as requested
            elif tag == "URL":
                elem = ET.SubElement(parent, tag)
                elem.text = ""
                
        add_field(ref_node, "Title", entry.get('title'))
        
        authors_node = ET.SubElement(ref_node, "Authors")
        for author in entry.get('authors', []):
            add_field(authors_node, "Author", author)
            
        add_field(ref_node, "Journal", entry.get('journal'))
        add_field(ref_node, "Year", entry.get('year'))
        add_field(ref_node, "ReferenceType", entry.get('reference_type'))
        add_field(ref_node, "Volume", entry.get('volume'))
        add_field(ref_node, "Issue", entry.get('issue'))
        add_field(ref_node, "Page", entry.get('page'))
        add_field(ref_node, "Date", entry.get('date'))
        add_field(ref_node, "PMCID", entry.get('pmcid'))
        add_field(ref_node, "Address", entry.get('address'))
        add_field(ref_node, "Abstract", entry.get('abstract'))
        add_field(ref_node, "DOI", entry.get('doi'))
        add_field(ref_node, "URL", entry.get('url'))
        add_field(ref_node, "SourceFile", entry.get('source_file'))
        add_field(ref_node, "Type", entry.get('type'))

    # Pretty print
    xmlstr = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xmlstr)

def split_xml_to_single_files(entries, output_dir):
    """
    Split the parsed entries into individual XML files in the output directory.
    Each file will be named based on the entry's title (sanitized).
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    used_filenames = set()
    for i, entry in enumerate(entries):
        title = entry.get('title', f'Unknown_Title_{i}')
        # Sanitize title for filename
        safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_title = safe_title[:100] # Limit length
        if not safe_title:
            safe_title = f"entry_{i}"

        filename = f"{safe_title}.xml"
        if filename in used_filenames:
            filename = f"{safe_title}_{i+1}.xml"
            n = 2
            while filename in used_filenames:
                filename = f"{safe_title}_{i+1}_{n}.xml"
                n += 1
        used_filenames.add(filename)
        file_path = os.path.join(output_dir, filename)
        
        # Create a single entry list for conversion
        convert_to_xml([entry], file_path)

def process_directory(input_dir, output_file, return_report=False):
    all_entries = []
    for filename in os.listdir(input_dir):
        file_path = os.path.join(input_dir, filename)
        if filename.lower().endswith('.ris'):
            all_entries.extend(parse_ris(file_path))
        elif filename.lower().endswith('.bib'):
            all_entries.extend(parse_bib(file_path))
        elif filename.lower().endswith('.nbib'):
            all_entries.extend(parse_nbib(file_path))
        elif filename.lower().endswith('.xml'):
            all_entries.extend(parse_xml(file_path))
        elif filename.lower().endswith('.ciw'):
            all_entries.extend(parse_ciw(file_path))
            
    # Deduplication based on Title (Case insensitive)
    groups = {}
    ordered_keys = []
    for entry in all_entries:
        title = entry.get('title', '') or ''
        norm_title = "".join(c.lower() for c in title if c.isalnum())
        if not norm_title:
            continue
        if norm_title not in groups:
            groups[norm_title] = []
            ordered_keys.append(norm_title)
        groups[norm_title].append(entry)

    final_entries = [groups[k][0] for k in ordered_keys if groups.get(k)]
    duplicates_count = sum(max(0, len(v) - 1) for v in groups.values())
    duplicate_groups_count = sum(1 for v in groups.values() if len(v) > 1)

    print(f"Total entries found: {len(all_entries)}")
    print(f"Duplicates removed: {duplicates_count}")
    print(f"Final unique entries: {len(final_entries)}")

    convert_to_xml(final_entries, output_file)
    
    # New step: Split into individual XML files
    # Assuming output_file is like ".../references.xml", we want to output to the same directory
    output_dir = os.path.dirname(output_file)
    split_xml_to_single_files(final_entries, output_dir)

    if not return_report:
        return final_entries

    duplicates = []
    for k in ordered_keys:
        items = groups.get(k) or []
        if len(items) <= 1:
            continue
        kept = items[0]
        removed = items[1:]
        duplicates.append({
            "norm_title": k,
            "title": kept.get("title") or "",
            "kept": {
                "source_file": kept.get("source_file"),
                "source_position": kept.get("source_position"),
                "record_number": kept.get("record_number"),
                "year": kept.get("year"),
                "journal": kept.get("journal"),
                "doi": kept.get("doi"),
                "url": kept.get("url"),
            },
            "duplicates": [
                {
                    "source_file": d.get("source_file"),
                    "source_position": d.get("source_position"),
                    "record_number": d.get("record_number"),
                    "year": d.get("year"),
                    "journal": d.get("journal"),
                    "doi": d.get("doi"),
                    "url": d.get("url"),
                }
                for d in removed
            ],
        })

    report = {
        "total_entries_found": len(all_entries),
        "duplicate_groups": duplicate_groups_count,
        "duplicates_removed": duplicates_count,
        "final_unique_entries": len(final_entries),
        "duplicates": duplicates,
    }

    return final_entries, report

if __name__ == "__main__":
    # Test run
    process_directory("archive", "3/references.xml")
