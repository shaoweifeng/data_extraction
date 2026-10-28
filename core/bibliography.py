"""Pure, lossless normalized bibliography mapping shared by screening stages."""

import re


BIBLIOGRAPHY_FIELDS = (
    'title', 'abstract', 'authors', 'journal', 'publication_year', 'publication_date',
    'doi', 'pmid', 'pmcid', 'isbn', 'issn', 'url', 'publication_type', 'volume',
    'issue', 'pages', 'keywords', 'language', 'publisher', 'database',
    'organization', 'address', 'source_identifier',
)


def text(value):
    return str(value or '').strip()


def string_list(value):
    if not value:
        return []
    values = value if isinstance(value, (list, tuple)) else re.split(r'[;\n]', str(value))
    return [str(item).strip() for item in values if str(item).strip()]


def bibliography_fields(record):
    """Map parser keys, retaining strings, lists, long titles and full abstracts."""
    identifier = text(record.get('source_identifier') or record.get('record_number'))
    pmid = text(record.get('pmid'))
    if not pmid:
        match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', text(record.get('url')))
        pmid = identifier if text(record.get('source_type')).upper() == 'NBIB' and identifier.isdigit() else (match.group(1) if match else '')
    result = {key: text(record.get(key)) for key in (
        'title', 'abstract', 'journal', 'doi', 'pmcid', 'isbn', 'issn', 'url',
        'volume', 'issue', 'language', 'publisher', 'database', 'organization', 'address',
    )}
    result.update(
        authors=string_list(record.get('authors')), keywords=string_list(record.get('keywords')),
        publication_year=text(record.get('year')), publication_date=text(record.get('date')),
        publication_type=text(record.get('reference_type') or record.get('type')),
        pages=text(record.get('page')), pmid=pmid, source_identifier=identifier,
    )
    return result


def bibliography_snapshot(reference):
    return {field: getattr(reference, field) for field in BIBLIOGRAPHY_FIELDS}


def parser_record(snapshot):
    """Translate a database snapshot back to the shared validator/export keys."""
    result = dict(snapshot)
    for target, source in (('year', 'publication_year'), ('date', 'publication_date'),
                           ('reference_type', 'publication_type'), ('page', 'pages')):
        result[target] = snapshot.get(source, '')
    return result
