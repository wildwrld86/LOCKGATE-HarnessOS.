"""One bounded run joining E1/E2, synthetic fact receipts, decisions and trace."""
import argparse
import json
from pathlib import Path

from .core import TraceStore
from .decision import DecisionPolicy, FixtureFactRegistry, evaluate_conditions
from .verification import ClaimsPolicy

ROOT = Path(__file__).resolve().parent.parent


def run_fixture_matrix(summary_path: str | Path, policy_path: str | Path,
                       claims_path: str | Path, fixtures_path: str | Path,
                       db_path: str | Path) -> dict:
    policy = DecisionPolicy.from_file(policy_path)
    claims = ClaimsPolicy.from_file(claims_path)
    summary = json.loads(Path(summary_path).read_text(encoding='utf-8'))
    if (not isinstance(summary, dict) or not isinstance(summary.get('manifest_path'), str)):
        raise ValueError('Retrieval summary needs a manifest path')
    fixtures = json.loads(Path(fixtures_path).read_text(encoding='utf-8'))
    if (not isinstance(fixtures, dict) or set(fixtures) != {'source_type', 'profiles'}
            or fixtures['source_type'] != 'synthetic_fixture'
            or not isinstance(fixtures['profiles'], list)
            or not 1 <= len(fixtures['profiles']) <= 10):
        raise ValueError('Only bounded synthetic fixture matrices are supported')
    cases = []
    seen_profiles = set()
    for profile in fixtures['profiles']:
        if (not isinstance(profile, dict) or set(profile) != {
            'profile_id', 'facts', 'expected_decision'
        } or not isinstance(profile['facts'], dict)
                or not isinstance(profile['profile_id'], str)
                or profile['profile_id'] in seen_profiles
                or profile['expected_decision'] not in ('PASS', 'FAIL', 'UNKNOWN')):
            raise ValueError('Invalid profile fixture')
        seen_profiles.add(profile['profile_id'])
        trace = TraceStore(db_path)
        try:
            trace.event('PROFILE_FIXTURE_START', {'source_type': 'synthetic_fixture'})
            registry = FixtureFactRegistry(trace)
            facts = {}
            for key, value in profile['facts'].items():
                rid = registry.mint(profile['profile_id'], key, value)
                facts[key] = {'value': value, 'evidence_id': rid}
            report = evaluate_conditions(policy, claims, summary['manifest_path'],
                        {'profile_id': profile['profile_id'], 'facts': facts}, registry, trace)
            report['expected_decision'] = profile['expected_decision']
            cases.append(report)
        finally:
            trace.close()
    passed = all(c['decision'] == c['expected_decision']
                 and c['source_proof_level'] == 'E2_SOURCE_TEXT_MATCH' for c in cases)
    return {'status': 'DEMO_PASSED' if passed else 'DEMO_FAILED',
            'profile_proof_level': 'SYNTHETIC_FIXTURE',
            'full_eligibility': 'NOT_ASSESSED', 'authorized_actions': [], 'cases': cases}


def main() -> int:
    parser = argparse.ArgumentParser(description='LOCKGATE H3 synthetic condition matrix')
    parser.add_argument('--retrieval-summary', required=True)
    parser.add_argument('--policy', default=str(ROOT / 'contracts/decision.json'))
    parser.add_argument('--claims', default=str(ROOT / 'contracts/claims.json'))
    parser.add_argument('--fixtures', default=str(ROOT / 'fixtures/profiles.json'))
    parser.add_argument('--db', default='runtime/decisions.sqlite3')
    args = parser.parse_args()
    try:
        report = run_fixture_matrix(args.retrieval_summary, args.policy, args.claims,
                                    args.fixtures, args.db)
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({'status': 'HALTED', 'error_type': type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'DEMO_PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
