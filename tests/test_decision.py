import hashlib
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from lockgate.core import TraceStore
from lockgate.decision import (DecisionPolicy, DecisionRule, FixtureFactRegistry,
                                evaluate_conditions)
from lockgate.verification import ClaimsPolicy, SourceClaim


URL = 'https://example.org/condition'
QUOTE = 'New customers can receive a synthetic test benefit.'
CLAIMS = ClaimsPolicy(URL, 3600, (SourceClaim('new-customer-text', QUOTE,
                            ('New customers cannot receive the test benefit.',)),))
POLICY = DecisionPolicy('condition-demo', 'Only the synthetic new-customer condition.',
                       60, (DecisionRule('new-customer', 'is_new_customer', True,
                                         'new-customer-text'),))


class DecisionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.trace = TraceStore(self.base / 'trace.sqlite3')
        self.registry = FixtureFactRegistry(self.trace)
        body = ('<main>' + QUOTE + '</main>').encode()
        digest = hashlib.sha256(body).hexdigest()
        self.snapshot = self.base / (digest + '.html')
        self.snapshot.write_bytes(body)
        self.manifest = self.base / 'manifest.json'
        self.record = {'proof_level': 'E1_RETRIEVED_ONLY', 'status': 200,
            'final_url': URL, 'sha256': digest, 'byte_length': len(body),
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'snapshot_path': str(self.snapshot), 'content_type': 'text/html'}
        self.save_manifest()

    def tearDown(self):
        self.trace.close()
        self.directory.cleanup()

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.record))

    def evaluate(self, facts, *, profile_id='demo', policy=POLICY):
        return evaluate_conditions(policy, CLAIMS, self.manifest,
                  {'profile_id': profile_id, 'facts': facts}, self.registry, self.trace)

    def fact(self, value, profile_id='demo', key='is_new_customer'):
        return {'value': value, 'evidence_id': self.registry.mint(profile_id, key, value)}

    def test_known_pass_and_fail_are_scoped_and_recorded(self):
        for value, expected in ((True, 'PASS'), (False, 'FAIL')):
            with self.subTest(value=value):
                report = self.evaluate({'is_new_customer': self.fact(value)})
                self.assertEqual(report['decision'], expected)
                self.assertEqual(report['full_eligibility'], 'NOT_ASSESSED')
                self.assertEqual(report['authorized_actions'], [])
                self.assertEqual(report['profile_proof_level'], 'SYNTHETIC_FIXTURE')
                self.assertTrue(report['conditions'][0]['source_citations'])
        kinds = [r[0] for r in self.trace.db.execute(
                 'SELECT kind FROM events WHERE run_id=? ORDER BY seq', (self.trace.run_id,))]
        self.assertIn('FACT_RECEIPT', kinds)
        self.assertIn('SOURCE_RECHECK', kinds)
        self.assertIn('CONDITION_GATE', kinds)
        self.assertEqual(kinds[-1], 'DECISION_FINISH')

    def test_missing_untyped_and_self_certified_facts_never_pass(self):
        for facts in ({}, {'is_new_customer': None},
                      {'is_new_customer': {'value': True, 'verified': True}},
                      {'is_new_customer': {'value': 'true', 'evidence_id': 'fake'}},
                      {'is_new_customer': {'value': 1, 'evidence_id': 'fake'}}):
            with self.subTest(facts=facts):
                self.assertEqual(self.evaluate(facts)['decision'], 'UNKNOWN')

    def test_forged_wrong_profile_wrong_field_and_modified_value_are_unknown(self):
        mismatches = [
            {'value': True, 'evidence_id': 'ev_forged'},
            self.fact(True, profile_id='someone-else'),
            self.fact(True, key='unrelated_fact'),
            {**self.fact(False), 'value': True},
        ]
        for fact in mismatches:
            with self.subTest(fact=fact):
                self.assertEqual(self.evaluate({'is_new_customer': fact})['decision'], 'UNKNOWN')

    def test_fact_receipt_cannot_cross_run_or_expire_into_pass(self):
        fact = self.fact(True)
        with patch('lockgate.decision.time.time', return_value=time.time() + 61):
            report = self.evaluate({'is_new_customer': fact})
        self.assertEqual(report['decision'], 'UNKNOWN')
        self.assertEqual(report['conditions'][0]['reason'], 'STALE_FACT_RECEIPT')
        other_trace = TraceStore(self.base / 'trace.sqlite3')
        try:
            with self.assertRaisesRegex(ValueError, 'different run'):
                evaluate_conditions(POLICY, CLAIMS, self.manifest,
                    {'profile_id': 'demo', 'facts': {'is_new_customer': fact}},
                    self.registry, other_trace)
            other_registry = FixtureFactRegistry(other_trace)
            report = evaluate_conditions(POLICY, CLAIMS, self.manifest,
                    {'profile_id': 'demo', 'facts': {'is_new_customer': fact}},
                    other_registry, other_trace)
            self.assertEqual(report['decision'], 'UNKNOWN')
        finally:
            other_trace.close()

    def test_forged_checked_report_cannot_override_tampered_source(self):
        fact = self.fact(True)
        self.snapshot.write_text('<main>Changed terms</main>')
        (self.base / (self.record['sha256'] + '.e2.json')).write_text(
            json.dumps({'status': 'CHECKED', 'proof_level': 'E2_SOURCE_TEXT_MATCH'}))
        report = self.evaluate({'is_new_customer': fact})
        self.assertEqual(report['decision'], 'UNKNOWN')
        self.assertIn('SOURCE_RECHECK_FAILED', report['conditions'][0]['reason'])

    def test_stale_wrong_url_and_unsupported_source_block_positive_decision(self):
        fact = self.fact(True)
        self.record['fetched_at'] = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        self.save_manifest()
        self.assertEqual(self.evaluate({'is_new_customer': fact})['decision'], 'UNKNOWN')
        self.record['fetched_at'] = datetime.now(timezone.utc).isoformat()
        self.record['final_url'] = 'https://example.org/wrong-source'
        self.save_manifest()
        self.assertEqual(self.evaluate({'is_new_customer': fact})['decision'], 'UNKNOWN')
        self.record['final_url'] = URL
        body = b'<main>Unrelated content</main>'
        digest = hashlib.sha256(body).hexdigest()
        self.snapshot = self.base / (digest + '.html')
        self.snapshot.write_bytes(body)
        self.record.update(sha256=digest, byte_length=len(body), snapshot_path=str(self.snapshot))
        self.save_manifest()
        self.assertEqual(self.evaluate({'is_new_customer': fact})['decision'], 'UNKNOWN')

    def test_empty_contract_and_unconfigured_source_rule_are_rejected(self):
        with self.assertRaises(ValueError):
            DecisionPolicy('empty', 'Empty policies cannot authorize anything.', 60, ())
        with self.assertRaises(ValueError):
            DecisionRule('bad', 'fact', 1, 'new-customer-text')
        bad = DecisionPolicy('bad', 'An unconfigured source cannot justify a rule.', 60,
                             (DecisionRule('bad', 'fact', True, 'absent-claim'),))
        with self.assertRaisesRegex(ValueError, 'unconfigured source claim'):
            self.evaluate({}, policy=bad)

    def test_false_dominates_unknown_only_with_checked_source(self):
        policy = DecisionPolicy('two-facts', 'Two independently required boolean conditions.', 60,
            (DecisionRule('first', 'first', True, 'new-customer-text'),
             DecisionRule('second', 'second', True, 'new-customer-text')))
        report = self.evaluate({'first': self.fact(False, key='first')}, policy=policy)
        self.assertEqual(report['decision'], 'FAIL')
        self.assertEqual([r['result'] for r in report['conditions']], ['FAIL', 'UNKNOWN'])


if __name__ == '__main__':
    unittest.main()
