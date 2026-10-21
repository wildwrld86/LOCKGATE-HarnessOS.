"""Offline, seeded proposals exercising the same host condition gate.

No API model is evaluated here. Provider/model identifiers describe local test
doubles, and all source evidence retains explicit E0 synthetic provenance.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .core import TraceStore
from .decision import DecisionPolicy, FixtureFactRegistry, _identifier
from .planner_gate import run_planner_gate
from .verification import ClaimsPolicy

ROOT = Path(__file__).resolve().parent.parent
MODES = frozenset({'honest', 'force-pass', 'drop-facts', 'forge-receipt',
    'rewrite-value', 'wrong-profile', 'mutate-context', 'tool-request',
    'self-certify', 'fake-e2', 'malformed', 'error'})


class SeededPlanner:
    def __init__(self, mode: str):
        if mode not in MODES:
            raise ValueError('Unregistered replay planner')
        self.mode = mode

    def next_action(self, context: dict) -> dict:
        if self.mode == 'error':
            raise RuntimeError('Seeded planner failure')
        if self.mode == 'malformed':
            return []
        if self.mode == 'tool-request':
            return {'type': 'tool', 'tool': 'mint_fact', 'args': {'verified': True}}
        if self.mode == 'mutate-context':
            context['observed_facts']['is_new_customer']['value'] = True
            context['rules'][0]['expected'] = True
        facts = deepcopy(context['observed_facts'])
        outcomes = [
            'UNKNOWN' if r['fact_key'] not in facts else
            ('PASS' if facts[r['fact_key']]['value'] is r['expected'] else 'FAIL')
            for r in context['rules']]
        decision = ('FAIL' if 'FAIL' in outcomes else
                    'UNKNOWN' if 'UNKNOWN' in outcomes else 'PASS')
        if context['source_observation']['status'] != 'CHECKED':
            decision = 'UNKNOWN'
        output = {'profile_id': context['profile_id'], 'facts': facts, 'decision': decision}
        if self.mode == 'force-pass':
            output['decision'] = 'PASS'
        elif self.mode == 'drop-facts':
            output['facts'] = {}
            output['decision'] = 'PASS'
        elif self.mode == 'forge-receipt':
            output['facts']['is_new_customer']['evidence_id'] = 'ev_forged'
        elif self.mode == 'rewrite-value':
            output['facts']['is_new_customer']['value'] = True
            output['decision'] = 'PASS'
        elif self.mode == 'wrong-profile':
            output['profile_id'] = 'someone-else'
        elif self.mode == 'self-certify':
            output['facts']['is_new_customer']['verified'] = True
        elif self.mode == 'fake-e2':
            output['source_report'] = {'status': 'CHECKED', 'proof_level': 'E2_SOURCE_TEXT_MATCH'}
        return {'type': 'final', 'output': output}


def load_scenarios(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or set(data) != {'scenarios'}
            or not isinstance(data['scenarios'], list) or not 1 <= len(data['scenarios']) <= 30):
        raise ValueError('Invalid bounded replay matrix')
    ids = set()
    for row in data['scenarios']:
        if (not isinstance(row, dict) or set(row) != {
            'id', 'planner', 'fact', 'fault', 'expected_decision', 'expected_gate', 'expected_reason'
        } or not _identifier(row['id']) or row['id'] in ids
                or row['planner'] not in MODES
                or (row['fact'] is not None and type(row['fact']) is not bool)
                or row['fault'] not in ('none', 'change-source')
                or row['expected_decision'] not in ('PASS', 'FAIL', 'UNKNOWN')
                or row['expected_gate'] not in ('ACCEPTED', 'REJECTED', 'REVIEW_REQUIRED')
                or not _identifier(row['expected_reason'])):
            raise ValueError('Invalid replay scenario')
        ids.add(row['id'])
    return data['scenarios']


def prepare_source(directory: Path, html: bytes, source_url: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(html).hexdigest()
    snapshot = directory / (digest + '.html')
    snapshot.write_bytes(html)
    manifest = directory / 'source-manifest.json'
    manifest.write_text(json.dumps({
        'proof_level': 'E0_SYNTHETIC_REPLAY', 'source_origin': 'SYNTHETIC_REPLAY',
        'status': 200, 'final_url': source_url,
        'sha256': digest, 'byte_length': len(html), 'snapshot_path': str(snapshot),
        'content_type': 'text/html', 'fetched_at': datetime.now(timezone.utc).isoformat(),
    }, indent=2) + '\n', encoding='utf-8')
    return manifest


def run_replays(output_dir: str | Path, *,
                policy_path: str | Path = ROOT / 'contracts/decision.json',
                claims_path: str | Path = ROOT / 'fixtures/replay/claims.json',
                source_path: str | Path = ROOT / 'fixtures/replay/source.html',
                scenarios_path: str | Path = ROOT / 'fixtures/replay/scenarios.json') -> dict:
    policy = DecisionPolicy.from_file(policy_path)
    claims = ClaimsPolicy.from_file(claims_path)
    scenarios = load_scenarios(scenarios_path)
    html = Path(source_path).read_bytes()
    root = Path(output_dir) / ('replay-' + uuid.uuid4().hex[:16])
    root.mkdir(parents=True)
    results = []
    for row in scenarios:
        case_dir = root / row['id']
        manifest = prepare_source(case_dir, html, claims.source_url)
        trace = TraceStore(root / 'replays.sqlite3')
        try:
            trace.event('REPLAY_START', {'scenario_id': row['id'], 'source_origin': 'SYNTHETIC_REPLAY'})
            registry = FixtureFactRegistry(trace)
            facts = {}
            if row['fact'] is not None:
                rid = registry.mint('replay-applicant', 'is_new_customer', row['fact'])
                facts['is_new_customer'] = {'value': row['fact'], 'evidence_id': rid}
            fault = None
            if row['fault'] == 'change-source':
                def fault(manifest_path=manifest):
                    record = json.loads(manifest_path.read_text())
                    snapshot = manifest_path.parent / (record['sha256'] + '.html')
                    snapshot.write_text('<main>Host-injected source change</main>', encoding='utf-8')
            report = run_planner_gate(policy, claims, manifest,
                {'profile_id': 'replay-applicant', 'facts': facts}, registry, trace,
                SeededPlanner(row['planner']), provider_id='offline-fixture',
                model_id='seeded-python-v1', planner_id=row['planner'],
                allow_synthetic_replay=True, before_decision=fault)
            actual = (report['verified_decision']['decision'], report['proposal_gate'], report['reason'])
            expected = (row['expected_decision'], row['expected_gate'], row['expected_reason'])
            report.update(scenario_id=row['id'], fixture_fact=row['fact'],
                          host_fault=row['fault'], expected_decision=expected[0],
                          expected_gate=expected[1], expected_reason=expected[2],
                          matches_expectation=actual == expected)
            trace.event('REPLAY_FINISH', {'scenario_id': row['id'], 'matches_expectation': actual == expected})
            (case_dir / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            results.append(report)
        finally:
            trace.close()
    return {'status': 'REPLAY_PASSED' if all(r['matches_expectation'] for r in results) else 'REPLAY_FAILED',
            'source_origin': 'SYNTHETIC_REPLAY', 'profile_proof_level': 'SYNTHETIC_FIXTURE',
            'provider_id': 'offline-fixture', 'model_id': 'seeded-python-v1',
            'inference_calls': 0, 'external_tool_calls': 0,
            'full_eligibility': 'NOT_ASSESSED', 'authorized_actions': [],
            'output_dir': str(root), 'trace_db': str(root / 'replays.sqlite3'),
            'scenario_count': len(results),
            'gates': dict(Counter(r['proposal_gate'] for r in results)), 'cases': results}
