"""Read-only E1 retrieval. A snapshot proves retrieval, never claim truth.

Only trusted host code may construct RetrievalPolicy or call this module. The
planner is not given this tool in H1. Connections use resolved public socket
addresses while TLS hostname verification and SNI use the permitted hostname.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit


class RetrievalDenied(ValueError):
    """Request, redirect, address, or response violates the trusted policy."""


@dataclass(frozen=True)
class RetrievalPolicy:
    allowed_hosts: frozenset[str]
    max_redirects: int = 3
    max_bytes: int = 1_048_576
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.allowed_hosts or any(
            not h or h != h.lower() or h.endswith('.') or
            any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in h)
            for h in self.allowed_hosts
        ):
            raise ValueError('allowed_hosts must contain exact lowercase DNS names')
        if not 0 <= self.max_redirects <= 5:
            raise ValueError('max_redirects must be 0..5')
        if not 1 <= self.max_bytes <= 2_097_152:
            raise ValueError('max_bytes must be 1..2097152')
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError('timeout_seconds must be positive and at most 30')

    @classmethod
    def from_file(cls, path: str | Path) -> 'RetrievalPolicy':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if set(data) != {'allowed_hosts', 'max_redirects', 'max_bytes', 'timeout_seconds'}:
            raise ValueError('Unexpected or missing retrieval policy fields')
        hosts = data['allowed_hosts']
        if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
            raise ValueError('allowed_hosts must be a list of exact hostnames')
        return cls(frozenset(hosts), data['max_redirects'], data['max_bytes'],
                   data['timeout_seconds'])


def _validated_url(url: str, policy: RetrievalPolicy) -> tuple[str, str, str]:
    if not isinstance(url, str) or len(url) > 2048 or any(
        ord(c) < 33 or ord(c) > 126 or c == '\\' for c in url
    ):
        raise RetrievalDenied('INVALID_URL')
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise RetrievalDenied('INVALID_URL') from exc
    if (parts.scheme != 'https' or not host or host not in policy.allowed_hosts
            or port not in (None, 443) or parts.username or parts.password
            or parts.query or parts.fragment or parts.netloc != host):
        raise RetrievalDenied('URL_NOT_ALLOWED')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise RetrievalDenied('IP_HOST_NOT_ALLOWED')
    path = parts.path or '/'
    return urlunsplit(('https', host, path, '', '')), host, path


def _resolve_public(host: str) -> list[tuple[int, tuple]]:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM,
                                     proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise RetrievalDenied('DNS_FAILURE') from exc
    if not answers:
        raise RetrievalDenied('DNS_EMPTY')
    addresses: list[tuple[int, tuple]] = []
    for family, socktype, proto, _, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM:
            raise RetrievalDenied('DNS_UNEXPECTED_ADDRESS')
        addr = ipaddress.ip_address(sockaddr[0])
        if not addr.is_global:
            raise RetrievalDenied('DNS_NON_PUBLIC_ADDRESS')
        # All answers must be safe, even if we connect using only the first.
        addresses.append((family, sockaddr))
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: tuple[int, tuple], timeout: float):
        super().__init__(host, port=443, timeout=timeout,
                         context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        family, sockaddr = self._address
        raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            raw.settimeout(self.timeout)
            raw.connect(sockaddr)  # No hostname resolution on the connection path.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _request(host: str, path: str, address: tuple[int, tuple],
             policy: RetrievalPolicy, deadline: float) -> tuple[int, dict[str, str], bytes]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RetrievalDenied('TIME_BUDGET_EXHAUSTED')
    conn = _PinnedHTTPSConnection(host, address, min(policy.timeout_seconds, remaining))
    try:
        conn.request('GET', path, headers={
            'User-Agent': 'LOCKGATE-H1/0.1 (read-only source snapshot)',
            'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity',
            'Connection': 'close',
        })
        if conn.sock is not None:
            conn.sock.settimeout(max(0.001, min(policy.timeout_seconds,
                                                 deadline - time.monotonic())))
        response = conn.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        if response.status in (301, 302, 303, 307, 308):
            return response.status, headers, b''
        if response.status != 200:
            raise RetrievalDenied('HTTP_STATUS_' + str(response.status))
        content_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type not in ('text/html', 'text/plain'):
            raise RetrievalDenied('UNSUPPORTED_CONTENT_TYPE')
        if headers.get('content-encoding', 'identity').lower() != 'identity':
            raise RetrievalDenied('COMPRESSED_RESPONSE_DENIED')
        try:
            declared_length = int(headers.get('content-length', '0'))
        except ValueError as exc:
            raise RetrievalDenied('INVALID_CONTENT_LENGTH') from exc
        if declared_length < 0:
            raise RetrievalDenied('INVALID_CONTENT_LENGTH')
        if declared_length > policy.max_bytes:
            raise RetrievalDenied('RESPONSE_TOO_LARGE')
        chunks = []
        total = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RetrievalDenied('TIME_BUDGET_EXHAUSTED')
            if conn.sock is not None:
                conn.sock.settimeout(min(policy.timeout_seconds, remaining))
            block = response.read(min(65536, policy.max_bytes - total + 1))
            total += len(block)
            if total > policy.max_bytes:
                raise RetrievalDenied('RESPONSE_TOO_LARGE')
            if not block:
                break
            chunks.append(block)
        return response.status, headers, b''.join(chunks)
    finally:
        conn.close()


def fetch_official_page(url: str, policy: RetrievalPolicy, output_dir: str | Path) -> dict:
    """Fetch one allowed page and atomically persist its exact response bytes.

    This cannot prove that text is true, current after fetch, or applicable to a
    particular applicant. DNS resolution is outside the elapsed-time budget
    because stdlib getaddrinfo offers no portable timeout.
    """
    initial_url, _, _ = _validated_url(url, policy)
    current_url = initial_url
    redirects: list[str] = []
    deadline = time.monotonic() + policy.timeout_seconds
    for hop in range(policy.max_redirects + 1):
        current_url, host, path = _validated_url(current_url, policy)
        addresses = _resolve_public(host)  # Revalidate every redirect target.
        family, sockaddr = addresses[0]
        try:
            status, headers, body = _request(host, path, (family, sockaddr), policy, deadline)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise RetrievalDenied('NETWORK_FAILURE') from exc
        if status in (301, 302, 303, 307, 308):
            location = headers.get('location')
            if not location or hop >= policy.max_redirects:
                raise RetrievalDenied('REDIRECT_LIMIT_OR_MISSING_LOCATION')
            target, _, _ = _validated_url(urljoin(current_url, location), policy)
            if target == current_url or target in redirects:
                raise RetrievalDenied('REDIRECT_LOOP')
            redirects.append(current_url)
            current_url = target
            continue
        digest = hashlib.sha256(body).hexdigest()
        base = Path(output_dir)
        base.mkdir(parents=True, exist_ok=True)
        snapshot = base / (digest + '.html')
        # Persist bytes before publishing the manifest; no partial trusted result.
        if not snapshot.exists():
            fd, temporary = tempfile.mkstemp(dir=base, prefix='.snapshot-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(body)
                os.replace(temporary, snapshot)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        elif hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
            raise RetrievalDenied('EXISTING_SNAPSHOT_MISMATCH')
        result = {
            'run_id': uuid.uuid4().hex[:16],
            'proof_level': 'E1_RETRIEVED_ONLY',
            'requested_url': initial_url,
            'final_url': current_url,
            'redirects': redirects,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'status': status,
            'content_type': headers['content-type'],
            'resolved_ip': sockaddr[0],
            'byte_length': len(body),
            'sha256': digest,
            'snapshot_path': str(snapshot),
        }
        manifest = base / (result['run_id'] + '.json')
        fd, temporary = tempfile.mkstemp(dir=base, prefix='.manifest-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(result, stream, indent=2)
                stream.write('\n')
            os.replace(temporary, manifest)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        result['manifest_path'] = str(manifest)
        return result
    raise RetrievalDenied('REDIRECT_LIMIT')
