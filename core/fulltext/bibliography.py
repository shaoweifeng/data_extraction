"""Conservative, local-only bibliography hints corroborated by the first page.

This is deliberately not a general PDF citation parser. Missing/ambiguous fields
stay empty; producer names, filesystem names and PDF timestamps are not citations.
"""
import re
import unicodedata

VERSION = 'pdf-bibliography-v1'


def normalized(value):
    return unicodedata.normalize('NFKC', str(value or '')).replace('．', '.')


def compact(value):
    return re.sub(r'\s+', '', normalized(value)).casefold()


def extract_bibliography(metadata, first_page):
    text = normalized(first_page)[:20000]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields, sources = {}, {}

    def add(key, value, method, evidence):
        if value:
            fields[key] = value
            sources[key] = {'method': method, 'page': 1, 'evidence': evidence[:500]}

    # Affiliation numbers identify a Chinese author row before the abstract.
    header = re.split(r'(?:[\[【]?摘要[\]】]?\s*[:：]?|\bAbstract\b)', text, maxsplit=1, flags=re.I)[0][:2500]
    names = re.findall(r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})\s*[1-9]\d?(?=\s|[,，(（]|$)', header)
    names = list(dict.fromkeys(names))
    if 2 <= len(names) <= 30:
        add('authors', names, 'first_page_affiliation_author_row', header[-500:])
    else:
        author = normalized(metadata.get('author')).strip()
        denied = re.search(r'cnki|administrator|microsoft|adobe|elsevier|springer|reader|unknown|'
                           r'university|hospital|department|institute|publisher|office|pdf|作者|管理员|知网|出版社', author, re.I)
        # Only accept author properties appearing verbatim in the article header.
        # A single name can be a partial author list; retain that fact in provenance.
        if (2 <= len(author) <= 300 and not denied and len(author.split()) >= 2
                and compact(author) in compact(text[:6000])):
            values = [name.strip() for name in re.split(r'[;；]', author) if name.strip()]
            add('authors', values, 'pdf_author_property_corroborated_partial_list', author)

    # Publication headers, not study dates, references or copyright timestamps.
    for index, line in enumerate(lines):
        match = re.fullmatch(r'([\u4e00-\u9fff·]{2,40}(?:杂志|学报|期刊))\s*((?:19|20)\d{2})\s*年.*第\s*\d+\s*卷.*', line)
        if match:
            add('journal', match[1], 'publication_header', line)
            add('publication_year', match[2], 'publication_header', line)
            break
        if (index < 15 and re.fullmatch(r'[\u4e00-\u9fff·]{2,40}(?:杂志|学报|期刊)', line)
                and index > 0 and index + 1 < len(lines)
                and re.fullmatch(r'((?:19|20)\d{2})\s*年', lines[index-1])
                and re.search(r'\d+\s*卷\s*\d+\s*期', lines[index+1])):
            add('journal', line, 'publication_header', '\n'.join(lines[index-1:index+2]))
            add('publication_year', re.search(r'\d{4}', lines[index-1])[0], 'publication_header', lines[index-1])
            break

    # Some publisher PDFs include the actual journal in Subject. Require a
    # matching first-page journal name and a labelled cite-this-article year.
    subject = normalized(metadata.get('subject')).strip()
    journal = subject.split(',')[0].strip()
    if ('journal' not in fields and 5 <= len(journal) <= 150
            and re.search(r'journal|microbiology|medicine|lancet|nature', journal, re.I)
            and compact(journal) in compact(text[:6000])):
        add('journal', journal, 'pdf_subject_corroborated', subject)
        citation = re.search(r'please\s+cite\s+this\s+article.{0,900}?\.\s*\(((?:19|20)\d{2})\)\s*,',
                             re.sub(r'\s+', ' ', text[:1500]), re.I)
        if citation:
            add('publication_year', citation[1], 'first_page_citation', citation[0])

    return {'version': VERSION, 'fields': fields, 'sources': sources}


def bibliography_from_asset(asset):
    """Bounded read of the existing extraction; never reread/scan the PDF body."""
    if not asset.extracted_text_file:
        return extract_bibliography(asset.metadata, '')
    with asset.extracted_text_file.open('rb') as handle:
        text = handle.read(160000).decode('utf-8', errors='replace')
    marker = re.match(r'\s*<<<QA_PAGE:1>>>\n', text)
    first = re.split(r'<<<QA_PAGE:\d+>>>', text[marker.end():], maxsplit=1)[0] if marker else ''
    return extract_bibliography(asset.metadata, first)
