import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
import bibtexparser
import rispy

def parse_ris(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        entries = rispy.load(f)
    
    parsed_entries = []
    for entry in entries:
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
            'type': 'RIS'
        })
    return parsed_entries

def parse_bib(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        library = bibtexparser.load(f)
    
    parsed_entries = []
    for entry in library.entries:
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
    for entry in entries:
        parsed_entries.append({
            'title': entry.get('title'),
            'authors': entry.get('authors', []),
            'journal': entry.get('journal'),
            'year': entry.get('year'),
            'abstract': entry.get('abstract'),
            'doi': entry.get('doi'),
            'url': entry.get('url'),
            'source_file': os.path.basename(file_path),
            'type': 'NBIB'
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
        
    for i, entry in enumerate(entries):
        title = entry.get('title', f'Unknown_Title_{i}')
        # Sanitize title for filename
        safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_title = safe_title[:100] # Limit length
        if not safe_title:
            safe_title = f"entry_{i}"
            
        filename = f"{safe_title}.xml"
        file_path = os.path.join(output_dir, filename)
        
        # Create a single entry list for conversion
        convert_to_xml([entry], file_path)

def process_directory(input_dir, output_file):
    all_entries = []
    for filename in os.listdir(input_dir):
        file_path = os.path.join(input_dir, filename)
        if filename.lower().endswith('.ris'):
            all_entries.extend(parse_ris(file_path))
        elif filename.lower().endswith('.bib'):
            all_entries.extend(parse_bib(file_path))
        elif filename.lower().endswith('.nbib'):
            all_entries.extend(parse_nbib(file_path))
            
    # Deduplication based on Title (Case insensitive)
    unique_entries = {}
    duplicates_count = 0
    
    for entry in all_entries:
        title = entry.get('title', '')
        if not title:
            continue
            
        # Normalize title: lowercase and remove punctuation/spaces for comparison
        norm_title = "".join(c.lower() for c in title if c.isalnum())
        
        if norm_title not in unique_entries:
            unique_entries[norm_title] = entry
        else:
            duplicates_count += 1
            
    final_entries = list(unique_entries.values())
    print(f"Total entries found: {len(all_entries)}")
    print(f"Duplicates removed: {duplicates_count}")
    print(f"Final unique entries: {len(final_entries)}")
    
    convert_to_xml(final_entries, output_file)
    
    # New step: Split into individual XML files
    # Assuming output_file is like ".../references.xml", we want to output to the same directory
    output_dir = os.path.dirname(output_file)
    split_xml_to_single_files(final_entries, output_dir)
    
    return final_entries

if __name__ == "__main__":
    # Test run
    process_directory("archive", "3/references.xml")
