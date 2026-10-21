"""One proposal, no tools: compare untrusted JSON to a host-owned decision.

The Python adapter remains trusted host code. This boundary protects JSON
proposals; it does not sandbox arbitrary Python or time out malicious adapters.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .core import Planner, TraceStore
from .decision import DecisionPolicy, FixtureFactRegistry, evaluate_conditions, _identifier
from .verification import ClaimsPolicy, check_snapshot
from .model_budget import model_identifier

MAX_PROPOSAL_BYTES = 16384


def run_planner_gate(policy: DecisionPolicy, claims: ClaimsPolicy,
                     manifest_path: str | Path, task: dict,
                     registry: FixtureFactRegistry, trace: TraceStore,
                     planner: Planner, *, provider_id: str, model_id: str,
                     planner_id: str, allow_synthetic_replay: bool = False,
                     before_decision: Callable[[], None] | None = None) -> dict:
    if not all(_identifier(x) for x in (provider_id, planner_id)) or not model_identifier(model_id):
        raise ValueError('Invalid host planner identity')
    canonical_task = deepcopy(task)
    precheck = {'status': 'NOT_CHECKED'}
    try:
        checked = check_snapshot(manifest_path, claims,
                                 allow_synthetic_replay=allow_synthetic_replay)
        precheck = {key: checked[key] for key in (
            'status', 'proof_level', 'source_origin', 'source_sha256')}
    except (ValueError, OSError, TypeError):
        pass
    context = {
        'task_id': policy.task_id, 'scope': policy.scope,
        'profile_id': canonical_task['profile_id'],
        'observed_facts': deepcopy(canonical_task['facts']),
        'rules': [asdict(r) for r in policy.rules],
        'source_observation': precheck,
        'allowed_actions': ['final'], 'max_proposals': 1,
    }
    identity = {'provider_id': provider_id, 'model_id': model_id, 'planner_id': planner_id}
    trace.event('PLANNER_START', {**identity, 'max_proposals': 1})
    action = None
    error = None
    try:
        proposal = planner.next_action(deepcopy(context))
    except Exception as exc:
        error = 'PLANNER_ERROR'
        trace.event('PLANNER_ERROR', {'error_type': type(exc).__name__})
    else:
        try:
            encoded = json.dumps(proposal, allow_nan=False).encode('utf-8')
            if len(encoded) > MAX_PROPOSAL_BYTES:
                error = 'PROPOSAL_TOO_LARGE'
            else:
                action = json.loads(encoded)  # Detach all adapter-owned references.
        except (ValueError, TypeError, RecursionError):
            error = 'INVALID_JSON_PROPOSAL'
    trace.event('PLANNER_PROPOSAL', {'received': action is not None, 'error': error})
    if before_decision is not None:
        # A trusted replay fault, never an action the planner may request.
        before_decision()
        trace.event('HOST_FAULT_INJECTION', {'stage': 'BEFORE_DECISION'})
    # Independent baseline uses host facts, not facts selected by the planner.
    verified = evaluate_conditions(policy, claims, manifest_path, canonical_task,
                                   registry, trace,
                                   allow_synthetic_replay=allow_synthetic_replay)
    proposed_decision = None
    output = None
    if error is None:
        if not isinstance(action, dict) or set(action) != {'type', 'output'}:
            error = ('UNAUTHORIZED_ACTION' if isinstance(action, dict)
                     and action.get('type') == 'tool' else 'INVALID_ACTION_SCHEMA')
        elif action['type'] != 'final':
            error = 'UNAUTHORIZED_ACTION'
        elif (not isinstance(action['output'], dict) or set(action['output']) != {
            'profile_id', 'facts', 'decision'
        }):
            error = 'INVALID_FINAL_SCHEMA'
        else:
            output = action['output']
            if type(output['decision']) is not str or output['decision'] not in ('PASS', 'FAIL', 'UNKNOWN'):
                error = 'INVALID_FINAL_SCHEMA'
            else:
                proposed_decision = output['decision']
                if output['profile_id'] != canonical_task['profile_id']:
                    error = 'PROFILE_MISMATCH'
                elif (not isinstance(output['facts'], dict)
                      or set(output['facts']) != set(canonical_task['facts'])):
                    error = 'FACT_SET_MISMATCH'
                else:
                    for key, submitted in output['facts'].items():
                        if (not isinstance(submitted, dict) or set(submitted) != {'value', 'evidence_id'}
                                or type(submitted['value']) is not bool
                                or not isinstance(submitted['evidence_id'], str)):
                            error = 'INVALID_FACT_SCHEMA'
                            break
                        reason = registry.inspect(submitted['evidence_id'], output['profile_id'],
                                                  key, submitted['value'], policy.max_fact_age_seconds)
                        if reason != 'WITNESSED_SYNTHETIC_FACT':
                            error = reason
                            break
                        if submitted != canonical_task['facts'][key]:
                            error = 'FACT_NOT_IN_TASK'
                            break
    if error is not None:
        gate, reason = 'REJECTED', error
    elif verified['source_proof_level'] not in ('E2_SOURCE_TEXT_MATCH', 'E0_SYNTHETIC_TEXT_MATCH'):
        gate, reason = 'REVIEW_REQUIRED', 'SOURCE_NOT_CHECKED'
    elif verified['decision'] == 'UNKNOWN':
        gate, reason = 'REVIEW_REQUIRED', 'INCOMPLETE_FACTS'
    elif proposed_decision != verified['decision']:
        gate, reason = 'REJECTED', 'DECISION_MISMATCH'
    else:
        gate, reason = 'ACCEPTED', 'MATCHES_INDEPENDENT_DECISION'
    trace.event('PLANNER_GATE', {'gate': gate, 'reason': reason,
                'proposed_decision': proposed_decision, 'verified_decision': verified['decision']})
    return {'run_id': trace.run_id, **identity,
            'proposal_gate': gate, 'reason': reason,
            'proposed_decision': proposed_decision, 'verified_decision': verified,
            'completion_allowed': gate == 'ACCEPTED',
            'acceptance_scope': 'SCOPED_DECISION_REPORT_ONLY',
            'full_eligibility': 'NOT_ASSESSED', 'authorized_actions': []}
