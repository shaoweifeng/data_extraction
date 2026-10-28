"""Page-aware extraction shared by QA and full-text rescreening; protocol unchanged."""
from core.fulltext.chunks import PageText

EXTRACTION_VERSION = 'qa-text-v2-pages'
PAGE_MARKER_TEMPLATE = '<<<QA_PAGE:{page_number}>>>\n'

def extract_page_text(document, *, max_chars, check_stop=None):
    """Extract every page until the total rendered-text character budget is reached."""
    pages = []
    rendered = []
    rendered_chars = 0
    inspected_pages = 0
    truncated = False
    truncated_at_page = None

    for page_index in range(len(document)):
        if check_stop:
            check_stop()
        page_number = page_index + 1
        inspected_pages = page_number
        raw_text = (document[page_index].get_text() or '').replace('\r\n', '\n').replace('\r', '\n')
        text = raw_text.strip()
        if not text:
            continue

        marker = PAGE_MARKER_TEMPLATE.format(page_number=page_number)
        prefix = marker if not rendered else f'\n\n{marker}'
        remaining = max_chars - rendered_chars
        if remaining <= len(prefix):
            truncated = True
            truncated_at_page = page_number
            break

        available = remaining - len(prefix)
        selected = text[:available]
        rendered.append(prefix + selected)
        rendered_chars += len(prefix) + len(selected)
        pages.append(PageText(page_number=page_number, text=selected))

        if len(selected) < len(text):
            truncated = True
            truncated_at_page = page_number
            break
        if rendered_chars >= max_chars and page_number < len(document):
            truncated = True
            truncated_at_page = page_number + 1
            break

    return {
        'text': ''.join(rendered),
        'pages': pages,
        'extracted_page_count': inspected_pages,
        'truncated': truncated,
        'truncated_at_page': truncated_at_page,
    }
