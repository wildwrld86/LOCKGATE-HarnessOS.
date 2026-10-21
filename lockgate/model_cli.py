"""Offline by default; --provider groq requests one credentialed proposal."""
import argparse
import json
import os
import uuid
from pathlib import Path

from .core import TraceStore
from .decision import DecisionPolicy, FixtureFactRegistry
from .model_budget import ModelBudget
from .model_provider import BoundedGroqPlanner
from .planner_gate import run_planner_gate
from .replay import ROOT, prepare_source, run_replays
from .verification import ClaimsPolicy


def run_remote_case(output_dir: str | Path, model: str, api_key: str,
                    profile_id: str, budget: ModelBudget) -> dict:
    planner = BoundedGroqPlanner(model, api_key, budget)
    policy = DecisionPolicy.from_file(ROOT / 'contracts/decision.json')
    claims = ClaimsPolicy.from_file(ROOT / 'fixtures/replay/claims.json')
    profiles = json.loads((ROOT / 'fixtures/profiles.json').read_text())['profiles']
    profile = next((p for p in profiles if p['profile_id'] == profile_id), None)
    if profile is None:
        raise ValueError('Unregistered synthetic profile')
    directory = Path(output_dir) / ('model-evaluation-' + uuid.uuid4().hex[:16])
    manifest = prepare_source(directory, (ROOT / 'fixtures/replay/source.html').read_bytes(),
                              claims.source_url)
    trace = TraceStore(directory / 'trace.sqlite3')
    try:
        trace.event('MODEL_EVALUATION_START', {'provider_id': 'groq', 'model_id': model,
                                            'source_origin': 'SYNTHETIC_REPLAY'})
        registry = FixtureFactRegistry(trace)
        facts = {key: {'value': value, 'evidence_id': registry.mint(profile_id, key, value)}
                 for key, value in profile['facts'].items()}
        report = run_planner_gate(policy, claims, manifest,
                {'profile_id': profile_id, 'facts': facts}, registry, trace, planner,
                provider_id='groq', model_id=model, planner_id='bounded-groq-v1',
                allow_synthetic_replay=True)
        report['provider_run'] = planner.telemetry()
        report['status'] = ('EVALUATED' if report['provider_run']['status'] == 'OK'
                            else 'PROVIDER_FAILED')
        report['evaluation_source'] = 'SYNTHETIC_REPLAY'
        report['trace_db'] = str(directory / 'trace.sqlite3')
        report['report_path'] = str(directory / 'result.json')
        trace.event('MODEL_USAGE', report['provider_run'])
        trace.event('MODEL_EVALUATION_FINISH', {'status': report['status'],
                                              'proposal_gate': report['proposal_gate']})
        (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        trace.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='LOCKGATE bounded model evaluation')
    parser.add_argument('--provider', choices=('offline', 'groq'), default='offline')
    parser.add_argument('--model')
    parser.add_argument('--case', choices=('demo-new', 'demo-returning', 'demo-unknown'), default='demo-new')
    parser.add_argument('--budget', default=str(ROOT / 'contracts/model.json'))
    parser.add_argument('--output-dir', default='runtime/model-evaluation')
    args = parser.parse_args()
    try:
        if args.provider == 'offline':
            report = run_replays(args.output_dir)
            ok = report['status'] == 'REPLAY_PASSED'
        else:
            model = args.model or os.environ.get('GROQ_MODEL', '')
            key = os.environ.get('GROQ_API_KEY', '')
            if not model or not key.strip():
                print(json.dumps({'status': 'NOT_CONFIGURED',
                                  'required': ['GROQ_API_KEY', '--model or GROQ_MODEL']}))
                return 2
            report = run_remote_case(args.output_dir, model, key, args.case,
                                     ModelBudget.from_file(args.budget))
            ok = report['completion_allowed']
    except (ValueError, OSError, TypeError):
        print(json.dumps({'status': 'HALTED', 'reason': 'INVALID_CONFIGURATION'}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
