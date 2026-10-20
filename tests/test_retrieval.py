import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lockgate.retrieval import (
    RetrievalDenied, RetrievalPolicy, _PinnedHTTPSConnection, _request,
    _resolve_public, _validated_url, fetch_official_page,
)


POLICY = RetrievalPolicy(frozenset({'cloud.google.com'}), timeout_seconds=5,
                         max_bytes=20)
PUBLIC = [(socket.AF_INET, ('8.8.8.8', 443))]


class RetrievalTest(unittest.TestCase):
    def test_rejects_untrusted_url_variants(self):
        for url in (
            'http://cloud.google.com/startup',
            'https://evil.example/startup',
            'https://cloud.google.com.evil.example/startup',
            'https://cloud.google.com:8443/startup',
            'https://user@cloud.google.com/startup',
            'https://cloud.google.com/startup?token=secret',
            'https://cloud.google.com/startup#section',
            'https://cloud.google.com\\@evil.example/startup',
        ):
            with self.subTest(url=url), self.assertRaises(RetrievalDenied):
                _validated_url(url, POLICY)

    def test_dns_rejects_private_and_mixed_answers(self):
        for ips in (('127.0.0.1',), ('169.254.169.254',),
                    ('8.8.8.8', '10.1.2.3'), ('::1',)):
            answers = [(socket.AF_INET6 if ':' in ip else socket.AF_INET,
                        socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
                        (ip, 443)) for ip in ips]
            with self.subTest(ips=ips), patch('socket.getaddrinfo', return_value=answers):
                with self.assertRaisesRegex(RetrievalDenied, 'DNS_NON_PUBLIC_ADDRESS'):
                    _resolve_public('cloud.google.com')

    def test_redirect_dns_is_checked_again(self):
        with patch('lockgate.retrieval._resolve_public', side_effect=[
                PUBLIC, RetrievalDenied('DNS_NON_PUBLIC_ADDRESS')]) as resolve, \
                patch('lockgate.retrieval._request', return_value=(302, {
                    'location': '/startup/pre-funded'}, b'')) as request:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RetrievalDenied, 'DNS_NON_PUBLIC_ADDRESS'):
                    fetch_official_page('https://cloud.google.com/startup',
                                        POLICY, directory)
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(request.call_count, 1)

    def test_connection_pins_address_and_verifies_dns_name(self):
        with patch('lockgate.retrieval.socket.socket') as make_socket, \
                patch('lockgate.retrieval.ssl.create_default_context') as make_context:
            raw = make_socket.return_value
            tls = make_context.return_value.wrap_socket.return_value
            connection = _PinnedHTTPSConnection('cloud.google.com', PUBLIC[0], 5)
            connection.connect()
            raw.connect.assert_called_once_with(('8.8.8.8', 443))
            make_context.return_value.wrap_socket.assert_called_once_with(
                raw, server_hostname='cloud.google.com')
            self.assertIs(connection.sock, tls)

    def test_denies_cross_host_redirect_before_resolving_it(self):
        with patch('lockgate.retrieval._resolve_public', return_value=PUBLIC) as resolve, \
                patch('lockgate.retrieval._request', return_value=(302, {
                    'location': 'https://evil.example/private'}, b'')):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RetrievalDenied, 'URL_NOT_ALLOWED'):
                    fetch_official_page('https://cloud.google.com/startup/pre-funded',
                                        POLICY, directory)
            self.assertEqual(resolve.call_count, 1)

    def test_same_host_redirect_and_snapshot_provenance(self):
        replies = [(302, {'location': '/startup/pre-funded'}, b''),
                   (200, {'content-type': 'text/html; charset=utf-8'}, b'<h1>Credit</h1>')]
        with patch('lockgate.retrieval._resolve_public', return_value=PUBLIC), \
                patch('lockgate.retrieval._request', side_effect=replies):
            with tempfile.TemporaryDirectory() as directory:
                result = fetch_official_page('https://cloud.google.com/startup',
                                             POLICY, directory)
                self.assertEqual(result['proof_level'], 'E1_RETRIEVED_ONLY')
                self.assertEqual(result['redirects'], ['https://cloud.google.com/startup'])
                self.assertEqual(result['final_url'],
                                 'https://cloud.google.com/startup/pre-funded')
                self.assertEqual(result['resolved_ip'], '8.8.8.8')
                self.assertEqual(result['sha256'], hashlib.sha256(b'<h1>Credit</h1>').hexdigest())
                self.assertEqual(Path(result['snapshot_path']).read_bytes(), b'<h1>Credit</h1>')
                manifest = json.loads(Path(result['manifest_path']).read_text())
                self.assertEqual(manifest['sha256'], result['sha256'])
                self.assertNotIn('manifest_path', manifest)

    def test_denies_oversize_response_even_without_content_length(self):
        class FakeResponse:
            status = 200

            def getheaders(self):
                return [('Content-Type', 'text/html')]

            def read(self, limit):
                return b'x' * (POLICY.max_bytes + 1)

        with patch('lockgate.retrieval._PinnedHTTPSConnection') as factory:
            factory.return_value.getresponse.return_value = FakeResponse()
            with self.assertRaisesRegex(RetrievalDenied, 'RESPONSE_TOO_LARGE'):
                _request('cloud.google.com', '/startup', PUBLIC[0], POLICY,
                         __import__('time').monotonic() + 5)
            factory.return_value.close.assert_called_once()

    def test_denies_oversize_advertised_content_length(self):
        class FakeResponse:
            status = 200

            def getheaders(self):
                return [('Content-Type', 'text/html'), ('Content-Length', '999999')]

            def read(self, limit):
                self.fail('Body must not be read')

        with patch('lockgate.retrieval._PinnedHTTPSConnection') as factory:
            factory.return_value.getresponse.return_value = FakeResponse()
            with self.assertRaisesRegex(RetrievalDenied, 'RESPONSE_TOO_LARGE'):
                _request('cloud.google.com', '/startup', PUBLIC[0], POLICY,
                         __import__('time').monotonic() + 5)


if __name__ == '__main__':
    unittest.main()
