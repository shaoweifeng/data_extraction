"""Bounded HTTP with per-hop public-IP validation and DNS-pinned TLS connections.

Never follows proxies, cookies, authentication, JavaScript or automatic redirects.
The original hostname remains the TLS SNI/certificate and HTTP Host identity.
"""
import http.client
import ipaddress
import json
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from core.fulltext.errors import FulltextError

_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='fulltext-dns')


def checked_url(url):
    if not isinstance(url, str) or len(url) > 2000 or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise FulltextError('unsafe_url', '全文地址无效。')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').encode('idna').decode('ascii').rstrip('.').lower()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except (ValueError, UnicodeError):
        raise FulltextError('unsafe_url', '全文地址无效。')
    if parsed.scheme not in ('http', 'https') or not host or parsed.username is not None or parsed.password is not None:
        raise FulltextError('unsafe_url', '仅支持不带认证信息的 HTTP(S) 地址。')
    if port != (443 if parsed.scheme == 'https' else 80) or '\\' in url or '%' in host:
        raise FulltextError('unsafe_url', '不允许此网络地址或端口。')
    authority = f'[{host}]' if ':' in host else host
    return urlunsplit((parsed.scheme, authority, parsed.path or '/', parsed.query, ''))


def public_addresses(host, port, timeout):
    future = _DNS_POOL.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    try:
        rows = future.result(timeout=timeout)
    except (FutureTimeout, OSError):
        future.cancel()
        raise FulltextError('dns_failed', '全文来源域名解析失败或超时。')
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses:
        raise FulltextError('dns_failed', '全文来源域名没有可用地址。')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        mapped = getattr(ip, 'ipv4_mapped', None)
        if not ip.is_global or (mapped and not mapped.is_global):
            raise FulltextError('unsafe_address', '拒绝访问本机、私网或保留网络地址。')
    return addresses[:4]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, hostname, address, port, timeout):
        super().__init__(hostname, port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _PinnedHTTPS(_PinnedHTTP):
    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _open_pinned(url, *, timeout, deadline=None, budget=None):
    parsed = urlsplit(checked_url(url))
    port = 443 if parsed.scheme == 'https' else 80
    addresses = public_addresses(parsed.hostname, port, timeout)
    connection = None
    for index, address in enumerate(addresses):
        if index and budget:
            budget.check()
            budget.requests += 1
        remaining = (deadline-time.monotonic()) if deadline is not None else timeout
        if remaining <= 0:
            raise FulltextError('network_timeout', '全文获取超过总超时。')
        connection = (_PinnedHTTPS if parsed.scheme == 'https' else _PinnedHTTP)(
            parsed.hostname, address, port, min(timeout, remaining))
        try:
            connection.request('GET', urlunsplit(('', '', parsed.path, parsed.query, '')),
                headers={'User-Agent': 'MetaFlow-Fulltext/1.0', 'Accept-Encoding': 'identity',
                         'Accept': 'application/json, application/pdf, application/octet-stream;q=0.8'})
            return connection, connection.getresponse()
        except (OSError, http.client.HTTPException):
            connection.close()
    raise FulltextError('network_failed', '全文来源连接失败。')


@dataclass
class NetworkBudget:
    max_requests: int
    max_bytes: int
    timeout: int
    total_seconds: int
    max_redirects: int
    requests: int = 0
    received: int = 0
    checkpoint: object = None

    def check(self):
        if self.checkpoint:
            self.checkpoint(self)
        if self.requests >= self.max_requests:
            raise FulltextError('request_budget_exceeded', '全文查找请求预算已用完。')
        if self.received >= self.max_bytes:
            raise FulltextError('download_budget_exceeded', '全文查找下载预算已用完。')


def fetch_to(url, target, *, budget, max_bytes, pdf=False):
    """Write at most max_bytes (and remaining task bytes) to a caller-owned temporary file."""
    url = checked_url(url)
    deadline = time.monotonic() + budget.total_seconds
    received = 0
    try:
        for hop in range(budget.max_redirects + 1):
            budget.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FulltextError('network_timeout', '全文获取超过总超时。')
            budget.requests += 1
            connection, response = _open_pinned(url, timeout=min(budget.timeout, remaining), deadline=deadline, budget=budget)
            try:
                if response.status in (301, 302, 303, 307, 308):
                    if hop == budget.max_redirects or not response.getheader('Location'):
                        raise FulltextError('too_many_redirects', '全文来源重定向次数过多。')
                    url = checked_url(urljoin(url, response.getheader('Location')))
                    continue
                if response.status != 200:
                    raise FulltextError('http_error', f'全文来源返回 HTTP {response.status}。')
                if response.getheader('Content-Encoding', 'identity').lower() not in ('identity', ''):
                    raise FulltextError('encoded_response', '拒绝压缩的全文网络响应。')
                declared = response.getheader('Content-Length')
                if declared:
                    try:
                        size = int(declared)
                    except ValueError:
                        raise FulltextError('invalid_response_size', '全文响应大小无效。')
                    if size < 0 or size > min(max_bytes, budget.max_bytes-budget.received):
                        raise FulltextError('response_too_large', '全文响应超过大小预算。')
                mime = response.getheader('Content-Type', '').split(';')[0].strip().lower()
                if pdf and mime not in ('application/pdf', 'application/octet-stream', 'binary/octet-stream', ''):
                    raise FulltextError('not_pdf', '全文链接未返回 PDF 文件。')
                header = b''
                while True:
                    if budget.checkpoint:
                        budget.checkpoint(budget)
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise FulltextError('network_timeout', '全文获取超过总超时。')
                    if connection.sock:
                        connection.sock.settimeout(min(budget.timeout, remaining))
                    # Read one extra byte to detect streaming bodies that exceed the limit.
                    allowance = min(max_bytes-received, budget.max_bytes-budget.received)
                    try:
                        chunk = response.read(min(64*1024, max(1, allowance+1)))
                    except http.client.IncompleteRead as exc:
                        received += len(exc.partial)
                        budget.received += len(exc.partial)
                        raise FulltextError('incomplete_response', '全文下载中断，已接收的部分仍计入网络预算。') from exc
                    if not chunk:
                        break
                    received += len(chunk)
                    budget.received += len(chunk)
                    if received > max_bytes or budget.received > budget.max_bytes:
                        raise FulltextError('response_too_large', '全文响应超过大小预算。')
                    if len(header) < 5:
                        header += chunk[:5-len(header)]
                    if pdf and len(header) >= 5 and header != b'%PDF-':
                        raise FulltextError('not_pdf', '全文响应不是有效 PDF。')
                    target.write(chunk)
                if pdf and header != b'%PDF-':
                    raise FulltextError('not_pdf', '全文响应不是有效 PDF。')
                if declared is not None and received != int(declared):
                    raise FulltextError('incomplete_response', '全文下载不完整。')
                if not received:
                    raise FulltextError('empty_response', '全文来源返回空响应。')
                return {'url': url, 'size': received, 'content_type': mime}
            finally:
                response.close()
                connection.close()
        raise FulltextError('too_many_redirects', '全文来源重定向次数过多。')
    except (OSError, http.client.HTTPException) as exc:
        raise FulltextError('network_failed', '全文来源连接或读取失败。') from exc
    finally:
        if budget.checkpoint:
            budget.checkpoint(budget)


def fetch_json(url, *, budget, max_bytes):
    from io import BytesIO
    output = BytesIO()
    fetch_to(url, output, budget=budget, max_bytes=max_bytes)
    try:
        payload = json.loads(output.getvalue())
    except (ValueError, UnicodeError):
        raise FulltextError('invalid_metadata', '开放来源返回的元数据格式无效。')
    if not isinstance(payload, dict):
        raise FulltextError('invalid_metadata', '开放来源返回的元数据格式无效。')
    return payload
