import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from lockgate.core import TraceStore
from lockgate.decision import DecisionPolicy, FixtureFactRegistry
from lockgate.planner_gate import MAX_PROPOSAL_BYTES, run_planner_gate
from lockgate.replay import ROOT, SeededPlanner, prepare_source, run_replays
from lockgate.verification import ClaimsPolicy, VerificationDenied, check_snapshot


class PlannerGateTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.policy = DecisionPolicy.from_file(ROOT / 'contracts/decision.json')
        self.claims = ClaimsPolicy.from_file(ROOT / 'fixtures/replay/claims.json')
        self.source = (ROOT / 'fixtures/replay/source.html').read_bytes()
        self.manifest = prepare_source(self.base, self.source, self.claims.source_url)
        self.trace = TraceStore(self.base / 'trace.sqlite3')
        self.registry = FixtureFactRegistry(self.trace)

    def tearDown(self):
        self.trace.close()
        self.directory.cleanup()

    def task(self, value):
        rid = self.registry.mint('demo', 'is_new_customer', value)
        return {'profile_id': 'demo', 'facts': {
            'is_new_customer': {'value': value, 'evidence_id': rid}}}

    def run_gate(self, planner, task, **kwargs):
        return run_planner_gate(self.policy, self.claims, self.manifest, task,
                self.registry, self.trace, planner, provider_id='offline-fixture',
                model_id='seeded-python-v1', planner_id='test-adapter',
                **kwargs)

    def test_full_offline_matrix_and_audit_traces(self):
        report = run_replays(self.base / 'matrix')
        self.assertEqual(report['status'], 'REPLAY_PASSED')
        self.assertEqual(report['scenario_count'], 15)
        self.assertEqual(report['gates'], {'ACCEPTED': 2, 'REJECTED': 11, 'REVIEW_REQUIRED': 2})
        self.assertEqual(report['inference_calls'], 0)
        with sqlite3.connect(report['trace_db']) as db:
            for case in report['cases']:
                self.assertEqual(case['full_eligibility'], 'NOT_ASSESSED')
                self.assertEqual(case['authorized_actions'], [])
                self.assertEqual(case['completion_allowed'], case['proposal_gate'] == 'ACCEPTED')
                self.assertNotEqual(case['verified_decision']['source_proof_level'], 'E2_SOURCE_TEXT_MATCH')
                events = [(k, json.loads(v)) for k, v in db.execute(
                    'SELECT kind,data_json FROM events WHERE run_id=? ORDER BY seq', (case['run_id'],))]
                self.assertEqual(events[0][0], 'REPLAY_START')
                self.assertEqual(events[-1][0], 'REPLAY_FINISH')
                self.assertEqual(sum(k == 'PLANNER_START' for k, _ in events), 1)
                gate = next(v for k, v in events if k == 'PLANNER_GATE')
                self.assertEqual(gate['gate'], case['proposal_gate'])
                self.assertEqual(gate['reason'], case['reason'])

    def test_synthetic_source_is_rejected_by_default_and_never_promoted(self):
        with self.assertRaises(VerificationDenied):
            check_snapshot(self.manifest, self.claims)
        task = self.task(True)
        denied = self.run_gate(SeededPlanner('honest'), task)
        self.assertEqual(denied['proposal_gate'], 'REVIEW_REQUIRED')
        self.assertEqual(denied['verified_decision']['decision'], 'UNKNOWN')
        checked = self.run_gate(SeededPlanner('honest'), task, allow_synthetic_replay=True)
        self.assertEqual(checked['proposal_gate'], 'ACCEPTED')
        self.assertEqual(checked['verified_decision']['source_proof_level'], 'E0_SYNTHETIC_TEXT_MATCH')
        self.assertEqual(checked['verified_decision']['source_origin'], 'SYNTHETIC_REPLAY')

    def test_planner_cannot_hide_host_known_adverse_fact(self):
        report = self.run_gate(SeededPlanner('drop-facts'), self.task(False),
                               allow_synthetic_replay=True)
        self.assertEqual(report['verified_decision']['decision'], 'FAIL')
        self.assertEqual(report['proposal_gate'], 'REJECTED')
        self.assertEqual(report['reason'], 'FACT_SET_MISMATCH')

    def test_observation_mutation_does_not_rewrite_task_or_contract(self):
        task = self.task(False)
        original = deepcopy(task)
        report = self.run_gate(SeededPlanner('mutate-context'), task,
                               allow_synthetic_replay=True)
        self.assertEqual(task, original)
        self.assertIs(self.policy.rules[0].expected, True)
        self.assertEqual(report['verified_decision']['decision'], 'FAIL')
        self.assertEqual(report['proposal_gate'], 'REJECTED')

    def test_source_is_rechecked_after_proposal(self):
        class ChangeObservation(SeededPlanner):
            def next_action(self, context):
                context['source_observation']['status'] = 'CHECKED'
                context['source_observation']['proof_level'] = 'E2_SOURCE_TEXT_MATCH'
                return super().next_action(context)

        def host_source_change():
            record = json.loads(self.manifest.read_text())
            (self.base / (record['sha256'] + '.html')).write_text('Changed after planning')

        report = self.run_gate(ChangeObservation('honest'), self.task(True),
                    allow_synthetic_replay=True, before_decision=host_source_change)
        self.assertEqual(report['proposed_decision'], 'PASS')
        self.assertEqual(report['verified_decision']['decision'], 'UNKNOWN')
        self.assertEqual(report['proposal_gate'], 'REVIEW_REQUIRED')
        self.assertEqual(report['reason'], 'SOURCE_NOT_CHECKED')

    def test_oversized_and_non_json_responses_fail_closed_once(self):
        class ResponsePlanner:
            def __init__(self, response):
                self.response = response
                self.calls = 0

            def next_action(self, context):
                self.calls += 1
                return self.response

        for response, reason in (('x' * (MAX_PROPOSAL_BYTES + 1), 'PROPOSAL_TOO_LARGE'),
                                 ({'invalid': float('nan')}, 'INVALID_JSON_PROPOSAL'),
                                 ({'invalid': {1, 2}}, 'INVALID_JSON_PROPOSAL')):
            with self.subTest(reason=reason):
                planner = ResponsePlanner(response)
                report = self.run_gate(planner, self.task(True), allow_synthetic_replay=True)
                self.assertEqual(planner.calls, 1)
                self.assertEqual(report['proposal_gate'], 'REJECTED')
                self.assertEqual(report['reason'], reason)
                self.assertEqual(report['verified_decision']['decision'], 'PASS')

    def test_wrong_replay_expectation_fails_the_matrix(self):
        scenarios = json.loads((ROOT / 'fixtures/replay/scenarios.json').read_text())
        scenarios['scenarios'] = [scenarios['scenarios'][0]]
        scenarios['scenarios'][0]['expected_decision'] = 'FAIL'
        path = self.base / 'wrong-expectation.json'
        path.write_text(json.dumps(scenarios))
        report = run_replays(self.base / 'wrong-matrix', scenarios_path=path)
        self.assertEqual(report['status'], 'REPLAY_FAILED')
        self.assertEqual(report['cases'][0]['verified_decision']['decision'], 'PASS')


if __name__ == '__main__':
    unittest.main()
