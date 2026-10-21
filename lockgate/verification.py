"""E2 source-text checks on an E1 snapshot, independent of model proposals.

The checked claims and the source URL come from trusted host configuration.
Exact visible text support is narrower than semantic or applicant verification.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


class VerificationDenied(ValueError):
    """The snapshot, policy, or manifest cannot be trusted for this check."""


def _normalized(value: str) -> str:
    return ' '.join(value.split())


class _VisibleText(HTMLParser):
    IGNORED = frozenset({'head', 'script', 'style', 'noscript', 'template', 'svg'})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.IGNORED:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.IGNORED and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        return _normalized(' '.join(self.parts))


@dataclass(frozen=True)
class SourceClaim:
    id: str
    source_text: str
    contradiction_texts: tuple[str, ...]


@dataclass(frozen=True)
class ClaimsPolicy:
    source_url: str
    max_age_seconds: int
    claims: tuple[SourceClaim, ...]

    @classmethod
    def from_file(cls, path: str | Path) -> 'ClaimsPolicy':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if set(data) != {'source_url', 'max_age_seconds', 'claims'}:
            raise ValueError('Invalid claims policy fields')
        from .retrieval import RetrievalPolicy, _validated_url
        url = data['source_url']
        if not isinstance(url, str):
            raise ValueError('Invalid source URL')
        host = urlsplit(url).hostname
        if not host:
            raise ValueError('Invalid source URL')
        _validated_url(url, RetrievalPolicy(frozenset({host})))
        age = data['max_age_seconds']
        if type(age) is not int or not 1 <= age <= 86400:
            raise ValueError('max_age_seconds must be 1..86400')
        rows = data['claims']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
            raise ValueError('claims must contain 1..10 items')
        claims = []
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                'id', 'source_text', 'contradiction_texts'
            }:
                raise ValueError('Invalid claim fields')
            cid, quote, opposites = (row['id'], row['source_text'],
                                      row['contradiction_texts'])
            if (not isinstance(cid, str) or not re.fullmatch('[a-z0-9-]{1,80}', cid)
                    or cid in ids or not isinstance(quote, str)
                    or quote != _normalized(quote) or not 10 <= len(quote) <= 500
                    or not isinstance(opposites, list) or len(opposites) > 5
                    or any(not isinstance(x, str) or x != _normalized(x)
                           or not 10 <= len(x) <= 500 for x in opposites)):
                raise ValueError('Invalid or duplicate claim')
            ids.add(cid)
            claims.append(SourceClaim(cid, quote, tuple(opposites)))
        return cls(url, age, tuple(claims))


def _occurrences(text: str, quote: str) -> list[dict]:
    matches = []
    start = 0
    while len(matches) <= 10:
        i = text.find(quote, start)
        if i < 0:
            break
        matches.append({'text_start': i, 'text_end': i + len(quote),
                        'quote_sha256': hashlib.sha256(quote.encode('utf-8')).hexdigest()})
        start = i + len(quote)
    return matches


def check_snapshot(manifest_path: str | Path, policy: ClaimsPolicy,
                   *, now: datetime | None = None,
                   allow_synthetic_replay: bool = False) -> dict:
    """Check trusted quotes against visible text of a fresh, hashed E1 page."""
    path = Path(manifest_path)
    record = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(record, dict):
        raise VerificationDenied('INVALID_E1_MANIFEST')
    synthetic = record.get('proof_level') == 'E0_SYNTHETIC_REPLAY'
    digest = record.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise VerificationDenied('INVALID_SNAPSHOT_HASH')
    snapshot = path.parent / (digest + '.html')
    snapshot_path = record.get('snapshot_path')
    content_type = record.get('content_type')
    if (not isinstance(snapshot_path, str)
            or not isinstance(content_type, str)
            or content_type.split(';', 1)[0].strip().lower()
               not in ('text/html', 'text/plain')):
        raise VerificationDenied('INVALID_E1_MANIFEST')
    if ((record.get('proof_level') != 'E1_RETRIEVED_ONLY'
         and not (synthetic and allow_synthetic_replay))
            or record.get('status') != 200
            or record.get('final_url') != policy.source_url
            or Path(snapshot_path).name != snapshot.name):
        raise VerificationDenied('SOURCE_OR_PROOF_MISMATCH')
    try:
        fetched = datetime.fromisoformat(record['fetched_at'])
        age = ((now or datetime.now(timezone.utc)) - fetched).total_seconds()
    except (KeyError, ValueError, TypeError) as exc:
        raise VerificationDenied('INVALID_FETCH_TIME') from exc
    if fetched.tzinfo is None or age < -60 or age > policy.max_age_seconds:
        raise VerificationDenied('STALE_OR_FUTURE_SNAPSHOT')
    body = snapshot.read_bytes()
    if (type(record.get('byte_length')) is not int
            or len(body) != record['byte_length']
            or hashlib.sha256(body).hexdigest() != digest):
        raise VerificationDenied('SNAPSHOT_BYTES_MISMATCH')
    try:
        raw = body.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise VerificationDenied('INVALID_UTF8_SOURCE') from exc
    parser = _VisibleText()
    parser.feed(raw)
    visible = parser.text()
    visible_hash = hashlib.sha256(visible.encode('utf-8')).hexdigest()
    outcomes = []
    for claim in policy.claims:
        support = _occurrences(visible, claim.source_text)
        opposite = [{'quote': quote, 'citations': _occurrences(visible, quote)}
                    for quote in claim.contradiction_texts]
        opposed = any(x['citations'] for x in opposite)
        if len(support) > 10 or any(len(x['citations']) > 10 for x in opposite):
            verdict = 'UNKNOWN_TOO_MANY_MATCHES'
        elif support and opposed:
            verdict = 'CONFLICT'
        elif opposed:
            verdict = 'CONTRADICTED'
        elif support:
            verdict = 'SUPPORTED_EXACT_TEXT'
        else:
            verdict = 'UNKNOWN'
        outcomes.append({'id': claim.id, 'source_text': claim.source_text,
                         'verdict': verdict, 'support_citations': support,
                         'contradiction_citations': [x for x in opposite if x['citations']]})
    checked = all(x['verdict'] == 'SUPPORTED_EXACT_TEXT' for x in outcomes)
    text_path = path.parent / (digest + '.visible.txt')
    text_path.write_text(visible, encoding='utf-8')
    report = {
        'status': 'CHECKED' if checked else 'REVIEW_REQUIRED',
        'proof_level': (('E0_SYNTHETIC_TEXT_MATCH' if checked else 'E0_SYNTHETIC_REPLAY')
                        if synthetic else
                        ('E2_SOURCE_TEXT_MATCH' if checked else 'E1_RETRIEVED_ONLY')),
        'source_origin': 'SYNTHETIC_REPLAY' if synthetic else 'LIVE_RETRIEVAL',
        'source_url': policy.source_url,
        'source_sha256': digest,
        'visible_text_sha256': visible_hash,
        'visible_text_path': str(text_path),
        'source_fetched_at': record['fetched_at'],
        'claims': outcomes,
    }
    report_path = path.parent / (digest + ('.text-check.json' if synthetic else '.e2.json'))
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    report['report_path'] = str(report_path)
    return report
