import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lockgate.verification import (
    ClaimsPolicy, SourceClaim, VerificationDenied, check_snapshot,
)


URL = 'https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html'
CLAIM = SourceClaim('initial-credit',
                    'New customers receive USD $100 in credits.',
                    ('New customers receive no credits.',))
POLICY = ClaimsPolicy(URL, 3600, (CLAIM,))


class VerificationTest(unittest.TestCase):
    def fixture(self, directory, html):
        body = html.encode('utf-8')
        digest = hashlib.sha256(body).hexdigest()
        snapshot = Path(directory) / (digest + '.html')
        snapshot.write_bytes(body)
        manifest = Path(directory) / 'receipt.json'
        record = {'proof_level': 'E1_RETRIEVED_ONLY', 'status': 200,
                  'final_url': URL, 'sha256': digest, 'byte_length': len(body),
                  'fetched_at': datetime.now(timezone.utc).isoformat(),
                  'snapshot_path': str(snapshot), 'content_type': 'text/html'}
        manifest.write_text(json.dumps(record))
        return manifest, snapshot, record

    def test_checked_quote_has_recomputable_text_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, _ = self.fixture(directory,
                '<head><title>New customers receive no credits.</title></head>'
                '<script>New customers receive no credits.</script>'
                '<main>New customers receive <b>USD $100</b> in credits.</main>')
            report = check_snapshot(manifest, POLICY)
            self.assertEqual(report['status'], 'CHECKED')
            self.assertEqual(report['proof_level'], 'E2_SOURCE_TEXT_MATCH')
            citation = report['claims'][0]['support_citations'][0]
            text = Path(report['visible_text_path']).read_text()
            self.assertEqual(text[citation['text_start']:citation['text_end']],
                             CLAIM.source_text)
            self.assertEqual(citation['quote_sha256'],
                             hashlib.sha256(CLAIM.source_text.encode()).hexdigest())
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),
                             report['visible_text_sha256'])
            self.assertEqual(json.loads(Path(report['report_path']).read_text())['status'],
                             'CHECKED')

    def test_contradiction_and_conflict_block_e2(self):
        for html, verdict in (
            ('<p>New customers receive no credits.</p>', 'CONTRADICTED'),
            ('<p>New customers receive USD $100 in credits. '
             'New customers receive no credits.</p>', 'CONFLICT'),
        ):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as directory:
                manifest, _, _ = self.fixture(directory, html)
                report = check_snapshot(manifest, POLICY)
                self.assertEqual(report['status'], 'REVIEW_REQUIRED')
                self.assertEqual(report['proof_level'], 'E1_RETRIEVED_ONLY')
                self.assertEqual(report['claims'][0]['verdict'], verdict)

    def test_unknown_and_script_only_quote_block_e2(self):
        for html in ('<p>Different text.</p>',
                     '<script>New customers receive USD $100 in credits.</script>'):
            with self.subTest(html=html), tempfile.TemporaryDirectory() as directory:
                manifest, _, _ = self.fixture(directory, html)
                report = check_snapshot(manifest, POLICY)
                self.assertEqual(report['claims'][0]['verdict'], 'UNKNOWN')
                self.assertEqual(report['status'], 'REVIEW_REQUIRED')

    def test_tampered_snapshot_or_wrong_source_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, snapshot, record = self.fixture(directory, '<p>Example</p>')
            snapshot.write_text('<p>Tampered</p>')
            with self.assertRaisesRegex(VerificationDenied, 'SNAPSHOT_BYTES_MISMATCH'):
                check_snapshot(manifest, POLICY)
            snapshot.write_text('<p>Example</p>')
            record['final_url'] = 'https://example.org/other'
            manifest.write_text(json.dumps(record))
            with self.assertRaisesRegex(VerificationDenied, 'SOURCE_OR_PROOF_MISMATCH'):
                check_snapshot(manifest, POLICY)

    def test_stale_snapshot_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, record = self.fixture(directory, '<p>Example</p>')
            record['fetched_at'] = (datetime.now(timezone.utc) -
                                    timedelta(hours=2)).isoformat()
            manifest.write_text(json.dumps(record))
            with self.assertRaisesRegex(VerificationDenied, 'STALE_OR_FUTURE_SNAPSHOT'):
                check_snapshot(manifest, POLICY)

    def test_malformed_manifest_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, record = self.fixture(directory, '<p>Example</p>')
            record['snapshot_path'] = None
            manifest.write_text(json.dumps(record))
            with self.assertRaisesRegex(VerificationDenied, 'INVALID_E1_MANIFEST'):
                check_snapshot(manifest, POLICY)

    def test_rejects_untrusted_claim_contract_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'claims.json'
            path.write_text(json.dumps({'source_url': URL, 'max_age_seconds': 3600,
                'claims': [{'id': 'x', 'source_text': 'A short supported quote.',
                            'contradiction_texts': [], 'allowed_tool': 'send_email'}]}))
            with self.assertRaises(ValueError):
                ClaimsPolicy.from_file(path)


if __name__ == '__main__':
    unittest.main()
