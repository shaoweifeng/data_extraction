
import os
import sys
import json

# Add the directory containing parser.py to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "structural_screening/01_reference_parsing")))

try:
    from parser import parse_ris, parse_bib
except ImportError:
    # Try importing from local directory if running from there
    sys.path.append(os.path.abspath("structural_screening/01_reference_parsing"))
    from parser import parse_ris, parse_bib

def test_ris_parsing():
    ris_file = "media/projects/project_5/SCREEN_1/citation-export-2.ris"
    if not os.path.exists(ris_file):
        print(f"File not found: {ris_file}")
        return

    print(f"\nTesting RIS parsing for {ris_file}...")
    entries = parse_ris(ris_file)
    print(f"Parsed {len(entries)} entries.")
    
    found_urls = 0
    for i, entry in enumerate(entries[:5]): # Check first 5
        print(f"Entry {i+1}:")
        print(f"  Title: {entry.get('title')[:50]}...")
        print(f"  URL: {entry.get('url')}")
        if entry.get('url'):
            found_urls += 1
            
    print(f"Total entries with URL: {sum(1 for e in entries if e.get('url'))}/{len(entries)}")

def test_bib_parsing():
    bib_file = "media/projects/project_5/SCREEN_1/citation-export.bib"
    if not os.path.exists(bib_file):
        print(f"File not found: {bib_file}")
        return

    print(f"\nTesting BibTeX parsing for {bib_file}...")
    entries = parse_bib(bib_file)
    print(f"Parsed {len(entries)} entries.")
    
    found_urls = 0
    for i, entry in enumerate(entries[:5]):
        print(f"Entry {i+1}:")
        print(f"  Title: {entry.get('title')[:50]}...")
        print(f"  URL: {entry.get('url')}")
        if entry.get('url'):
            found_urls += 1
            
    print(f"Total entries with URL: {sum(1 for e in entries if e.get('url'))}/{len(entries)}")

if __name__ == "__main__":
    test_ris_parsing()
    test_bib_parsing()
