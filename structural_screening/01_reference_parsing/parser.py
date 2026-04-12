import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import bibtexparser
import rispy

def parse_ris(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        entries = rispy.load(f)
    
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
        
        parsed_entries.append({
            'title': entry.get('title') or entry.get('primary_title'),
            'authors': entry.get('authors', []),
            'journal': entry.get('journal_name') or entry.get('secondary_title'),
            'year': entry.get('year'),
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
        
        parsed_entries.append({
            'title': entry.get('title'),
            'authors': [a.strip() for a in authors if a.strip()],
            'journal': entry.get('journal'),
            'year': entry.get('year'),
            'abstract': entry.get('abstract'),
            'doi': entry.get('doi'),
            'url': url,
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'type': 'BIB'
        })
    return parsed_entries

def parse_nbib(file_path):
    # NBIB format is similar to RIS but with specific keys. 
    # Using a simple parser since standard libraries might not cover all NBIB nuances perfectly.
    # However, rispy often handles Medline/NBIB formats if they follow the tag-value structure.
    # Let's try manual parsing for Medline format which NBIB usually is.
    
    entries = []
    current_entry = {}
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    current_key = None
    current_value = []
    
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
            
        if line[:4] == '    ' and current_key: # Continuation line
            current_value.append(line.strip())
        else:
            # Save previous key
            if current_key:
                val = ' '.join(current_value)
                if current_key in current_entry:
                    if isinstance(current_entry[current_key], list):
                        current_entry[current_key].append(val)
                    else:
                        current_entry[current_key] = [current_entry[current_key], val]
                else:
                    current_entry[current_key] = val
            
            # New key
            if '-' in line[:5]: # Standard Medline tag format "TI  - "
                parts = line.split('-', 1)
                key = parts[0].strip()
                val = parts[1].strip() if len(parts) > 1 else ""
                current_key = key
                current_value = [val] if val else []
            else:
                current_key = None # Reset if format unrecognized
                
    # Add last entry
    if current_entry:
        entries.append(current_entry)
        
    # NBIB/Medline file usually contains multiple records separated by blank lines or implicit start.
    # The above simple logic merges everything into one entry if separators aren't clear.
    # Let's use a more robust approach: Split by "PMID-" or "TI  -" as start markers?
    # Better yet, let's write a dedicated simple parser based on "PMID-" or "PT  -" start.
    
    # Re-implementation for multi-record NBIB
    entries = []
    current_entry = {}
    
    for line in lines:
        line = line.rstrip()
        if not line: continue
        
        # Check for start of new record (usually PMID or just implicit if previous ended)
        # But Medline format usually has tags at start of line.
        
        if line.startswith('PMID-'):
            if current_entry:
                # Construct URL from PMID if not present
                if 'url' not in current_entry and 'pmid' in current_entry:
                    current_entry['url'] = f"https://pubmed.ncbi.nlm.nih.gov/{current_entry['pmid']}"
                entries.append(current_entry)
                current_entry = {}
            
            # Extract PMID
            parts = line.split('-', 1)
            if len(parts) > 1:
                current_entry['pmid'] = parts[1].strip()
        
        if '-' in line[:5]:
            parts = line.split('-', 1)
            key = parts[0].strip()
            val = parts[1].strip() if len(parts) > 1 else ""
            
            # Store current key for continuation lines
            current_key = key
            
            if key == 'FAU' or key == 'AU': # Authors
                if 'authors' not in current_entry:
                    current_entry['authors'] = []
                current_entry['authors'].append(val)
            elif key == 'TI':
                current_entry['title'] = val
            elif key == 'AB':
                current_entry['abstract'] = val
            elif key == 'DP': # Date of Publication
                current_entry['year'] = val.split()[0] # Extract year roughly
            elif key == 'JT': # Journal Title
                current_entry['journal'] = val
            elif key == 'UR' or key == 'URL': # URL
                current_entry['url'] = val
            elif key == 'PMID': # Alternative PMID tag
                current_entry['pmid'] = val
            elif key == 'LID' and '[doi]' in val:
                current_entry['doi'] = val.replace('[doi]', '').strip()
            else:
                # Reset key if we don't care about this field to avoid appending continuation lines to wrong field
                if key not in ['AB', 'TI']: 
                    current_key = None
                
        elif line.startswith('      ') and current_key: # Continuation line (6 spaces indentation common in nbib)
            val = line.strip()
            if current_key == 'AB':
                if 'abstract' in current_entry:
                    current_entry['abstract'] += " " + val
                else:
                    current_entry['abstract'] = val
            elif current_key == 'TI':
                if 'title' in current_entry:
                    current_entry['title'] += " " + val
                else:
                    current_entry['title'] = val
            
    if current_entry:
        # Construct URL from PMID if not present (for the last entry)
        if 'url' not in current_entry and 'pmid' in current_entry:
            current_entry['url'] = f"https://pubmed.ncbi.nlm.nih.gov/{current_entry['pmid']}"
        entries.append(current_entry)
        
    parsed_entries = []
    for i, entry in enumerate(entries, start=1):
        parsed_entries.append({
            'title': entry.get('title'),
            'authors': entry.get('authors', []),
            'journal': entry.get('journal'),
            'year': entry.get('year'),
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
