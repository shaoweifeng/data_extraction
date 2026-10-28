"""No Internet traffic: real URL/IP checks and simulated bounded HTTP streams."""
from io import BytesIO
from unittest.mock import Mock, patch
from django.test import SimpleTestCase
from core.fulltext.errors import FulltextError
from core.fulltext.network import (NetworkBudget, checked_url, public_addresses, fetch_to,
    fetch_json, _PinnedHTTP, _PinnedHTTPS)


class FakeResponse(BytesIO):
    def __init__(self, body=b'%PDF-content', *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def budget(**changes):
    return NetworkBudget(**dict({'max_requests': 5, 'max_bytes': 10000, 'timeout': 2,
        'total_seconds': 5, 'max_redirects': 2}, **changes))


class FulltextNetworkTests(SimpleTestCase):
    def test_unsafe_schemes_ports_credentials_and_controls(self):
        for url in ('file:///etc/passwd', 'ftp://example.org/x', 'http://a:b@example.org/',
            'https://example.org:8443/x', 'https://example.org/\nX', 'https://example.org\\@localhost/x',
            'https://[fe80::1%lo0]/x'):
            with self.subTest(url=url), self.assertRaises(FulltextError):
                checked_url(url)

    def test_all_dns_answers_must_be_public_including_ipv4_mapped(self):
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fd00::1', '::ffff:127.0.0.1', '100.64.0.1'):
            answers = [(2, 1, 6, '', ('1.1.1.1', 443)), (2, 1, 6, '', (address, 443))]
            with self.subTest(ip=address), patch('socket.getaddrinfo', return_value=answers), self.assertRaises(FulltextError):
                public_addresses('source.example', 443, 2)
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('1.1.1.1', 443))]):
            self.assertEqual(public_addresses('source.example', 443, 2), ['1.1.1.1'])

    def test_connection_is_pinned_and_tls_uses_original_hostname(self):
        with patch('socket.create_connection') as connect:
            _PinnedHTTP('source.example', '1.1.1.1', 80, 2).connect()
            connect.assert_called_once_with(('1.1.1.1', 80), 2)
        with patch('socket.create_connection') as connect, patch('ssl.create_default_context') as context:
            _PinnedHTTPS('source.example', '1.1.1.1', 443, 2).connect()
            context.return_value.wrap_socket.assert_called_once_with(connect.return_value, server_hostname='source.example')

    def test_redirect_revalidation_blocks_localhost_before_second_connection(self):
        first = FakeResponse(status=302, headers={'Location': 'http://127.0.0.1/private'})
        def open_first(url, **kwargs):
            if '127.0.0.1' in url:
                with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
                    public_addresses('127.0.0.1', 80, 2)
            return Mock(), first
        with patch('core.fulltext.network._open_pinned', side_effect=open_first):
            with self.assertRaisesMessage(FulltextError, '拒绝访问'):
                fetch_to('https://source.example/pdf', BytesIO(), budget=budget(), max_bytes=1000, pdf=True)

    def test_invalid_pdf_and_failed_stream_bytes_are_accounted(self):
        cap = budget()
        with patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(b'<html>Paywall</html>',
                headers={'Content-Type': 'application/pdf'}))):
            with self.assertRaisesMessage(FulltextError, '不是有效 PDF'):
                fetch_to('https://source.example/x', BytesIO(), budget=cap, max_bytes=1000, pdf=True)
        self.assertGreater(cap.received, 0)
        self.assertEqual(cap.requests, 1)

    def test_stream_size_and_declared_size_limits(self):
        for headers, cap in (({}, budget(max_bytes=8)), ({'Content-Length': '1000000'}, budget())):
            with patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(b'%PDF-too-large', headers=headers))):
                with self.assertRaisesMessage(FulltextError, '超过'):
                    fetch_to('https://source.example/pdf', BytesIO(), budget=cap, max_bytes=10, pdf=True)

    def test_compression_and_non_json_responses_are_rejected(self):
        with patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(headers={'Content-Encoding': 'gzip'}))):
            with self.assertRaisesMessage(FulltextError, '压缩'):
                fetch_to('https://source.example/pdf', BytesIO(), budget=budget(), max_bytes=1000, pdf=True)
        with patch('core.fulltext.network._open_pinned', return_value=(Mock(), FakeResponse(b'<html>'))):
            with self.assertRaisesMessage(FulltextError, '元数据格式无效'):
                fetch_json('https://source.example/api', budget=budget(), max_bytes=1000)

    def test_redirect_budget_and_cancellation(self):
        with patch('core.fulltext.network._open_pinned', side_effect=lambda *a, **k: (Mock(), FakeResponse(
                status=302, headers={'Location': '/another'}))):
            with self.assertRaisesMessage(FulltextError, '重定向'):
                fetch_to('https://source.example/pdf', BytesIO(), budget=budget(max_redirects=1), max_bytes=1000)
        def cancelled(_):
            raise FulltextError('lookup_cancelled', 'stopped')
        with self.assertRaisesMessage(FulltextError, 'stopped'):
            fetch_to('https://source.example/pdf', BytesIO(), budget=budget(checkpoint=cancelled), max_bytes=1000)
