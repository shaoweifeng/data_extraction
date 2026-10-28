"""Authorized callers use single-range, private PDF streaming (including HEAD)."""
import re
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header


def pdf_response(request, asset):
    try:
        size = asset.raw_file.size
        handle = asset.raw_file.open('rb')
    except (OSError, ValueError):
        return HttpResponse(status=404)
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Type': 'application/pdf',
        'Content-Disposition': content_disposition_header(False, asset.original_filename)}
    if getattr(asset, 'sha256', ''):
        headers['ETag'] = f'"{asset.sha256}"'
    range_header = request.headers.get('Range', '')
    if range_header and request.headers.get('If-Range') not in (None, headers.get('ETag')):
        range_header = ''
    if range_header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header) if len(range_header) <= 100 else None
        start, end = 0, size-1
        if match and any(match.groups()):
            first, last = match.groups()
            if first:
                start, end = int(first), min(int(last), size-1) if last else size-1
            else:
                start = max(0, size-int(last))
        else:
            start, end = size, -1
        if not 0 <= start <= end < size:
            handle.close()
            return HttpResponse(status=416, headers={**headers, 'Content-Range': f'bytes */{size}'})
        headers.update({'Content-Range': f'bytes {start}-{end}/{size}', 'Content-Length': str(end-start+1)})
        if request.method == 'HEAD':
            handle.close()
            return HttpResponse(status=206, headers=headers)
        handle.seek(start)
        def body():
            remaining = end-start+1
            try:
                while remaining:
                    value = handle.read(min(64*1024, remaining))
                    if not value:
                        break
                    remaining -= len(value)
                    yield value
            finally:
                handle.close()
        response = StreamingHttpResponse(body(), status=206, headers=headers)
        response._resource_closers.append(handle.close)
        return response
    headers['Content-Length'] = str(size)
    if request.method == 'HEAD':
        handle.close()
        return HttpResponse(headers=headers)
    return FileResponse(handle, headers=headers)
