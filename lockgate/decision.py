"""A bounded boolean condition gate with independently rechecked source text.

Policies and fact adapters are trusted host code. Proposals only reference facts;
they cannot issue receipts, certify themselves, or supply an accepted E2 report.
H3 fact receipts are deliberately synthetic and confer no operational authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from .core import TraceStore, canonical_json
from .verification import ClaimsPolicy, check_snapshot


def _identifier(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value) is not None


@dataclass(frozen=True)
class DecisionRule:
    id: str
    fact_key: str
    expected: bool
    source_claim_id: str

    def __post_init__(self) -> None:
        if (not all(_identifier(x) for x in (self.id, self.fact_key, self.source_claim_id))
                or type(self.expected) is not bool):
            raise ValueError('Invalid decision rule')


@dataclass(frozen=True)
class DecisionPolicy:
    task_id: str
    scope: str
    max_fact_age_seconds: int
    rules: tuple[DecisionRule, ...]

    def __post_init__(self) -> None:
        if (not _identifier(self.task_id) or not isinstance(self.scope, str)
                or not 10 <= len(self.scope) <= 500
                or type(self.max_fact_age_seconds) is not int
                or not 1 <= self.max_fact_age_seconds <= 86400
                or not isinstance(self.rules, tuple) or not 1 <= len(self.rules) <= 10
                or not all(isinstance(x, DecisionRule) for x in self.rules)
                or len({x.id for x in self.rules}) != len(self.rules)):
            raise ValueError('Invalid decision policy')

    @classmethod
    def from_file(cls, path: str | Path) -> 'DecisionPolicy':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) != {
            'task_id', 'scope', 'max_fact_age_seconds', 'rules'
        } or not isinstance(data['rules'], list):
            raise ValueError('Invalid decision policy fields')
        rules = []
        for row in data['rules']:
            if not isinstance(row, dict) or set(row) != {
                'id', 'fact_key', 'expected', 'source_claim_id'
            }:
                raise ValueError('Invalid decision rule fields')
            rules.append(DecisionRule(**row))
        return cls(data['task_id'], data['scope'], data['max_fact_age_seconds'], tuple(rules))


@dataclass(frozen=True)
class _FixtureFact:
    profile_id: str
    key: str
    value: bool
    issued_at: float


class FixtureFactRegistry:
    """Host-only adapter for synthetic facts; not an identity verifier."""
    def __init__(self, trace: TraceStore):
        self.trace = trace
        self.run_id = trace.run_id
        self._facts: dict[str, _FixtureFact] = {}

    def mint(self, profile_id: str, key: str, value: bool) -> str:
        if not _identifier(profile_id) or not _identifier(key) or type(value) is not bool:
            raise ValueError('Fixture facts need a profile, key, and boolean value')
        rid = self.trace.receipt(profile_id + ':' + key, {
            'profile_id': profile_id, 'key': key, 'value': value,
            'source_type': 'synthetic_fixture',
        })
        self._facts[rid] = _FixtureFact(profile_id, key, value, time.time())
        self.trace.event('FACT_RECEIPT', {'receipt_id': rid, 'source_type': 'synthetic_fixture'})
        return rid

    def inspect(self, evidence_id: str, profile_id: str, key: str,
                value: bool, max_age: int) -> str:
        fact = self._facts.get(evidence_id)
        if fact is None:
            return 'UNKNOWN_FACT_RECEIPT'
        if fact.profile_id != profile_id or fact.key != key or fact.value is not value:
            return 'FACT_RECEIPT_MISMATCH'
        age = time.time() - fact.issued_at
        if age < 0 or age > max_age:
            return 'STALE_FACT_RECEIPT'
        return 'WITNESSED_SYNTHETIC_FACT'


def evaluate_conditions(policy: DecisionPolicy, claims_policy: ClaimsPolicy,
                        manifest_path: str | Path, proposal: dict,
                        registry: FixtureFactRegistry, trace: TraceStore) -> dict:
    """Recompute source checks and decide a conjunction of explicit boolean rules.

    FAIL dominates UNKNOWN for a conjunction of independently supported rules.
    Any source failure blocks the entire decision with UNKNOWN. A PASS is only
    a match to this small contract and its synthetic facts, never full eligibility.
    """
    if (not isinstance(proposal, dict) or set(proposal) != {'profile_id', 'facts'}
            or not _identifier(proposal['profile_id']) or not isinstance(proposal['facts'], dict)
            or set(proposal['facts']) - {x.fact_key for x in policy.rules}):
        raise ValueError('Invalid condition proposal')
    if registry.run_id != trace.run_id:
        raise ValueError('Fact registry belongs to a different run')
    known_claim_ids = {x.id for x in claims_policy.claims}
    if any(x.source_claim_id not in known_claim_ids for x in policy.rules):
        raise ValueError('Decision rule references an unconfigured source claim')
    profile_id = proposal['profile_id']
    policy_hash = hashlib.sha256(canonical_json(asdict(policy)).encode()).hexdigest()
    claims_hash = hashlib.sha256(canonical_json(asdict(claims_policy)).encode()).hexdigest()
    trace.event('DECISION_START', {'task_id': policy.task_id,
                'decision_policy_sha256': policy_hash, 'claims_policy_sha256': claims_hash})
    source = None
    source_error = None
    try:
        # Never accept a model's or caller's saved "CHECKED" JSON as authority.
        source = check_snapshot(manifest_path, claims_policy)
        if source['status'] != 'CHECKED':
            source_error = 'SOURCE_CLAIMS_NOT_CHECKED'
    except (ValueError, OSError, TypeError) as exc:
        source_error = 'SOURCE_RECHECK_FAILED:' + type(exc).__name__
    trace.event('SOURCE_RECHECK', {
        'checked': source_error is None,
        'source_sha256': source['source_sha256'] if source else None,
        'error': source_error,
    })
    source_claims = {x['id']: x for x in source['claims']} if source else {}
    outcomes = []
    for rule in policy.rules:
        result = 'UNKNOWN'
        reason = source_error or 'MISSING_FACT'
        rid = None
        if source_error is None and rule.fact_key in proposal['facts']:
            submitted = proposal['facts'][rule.fact_key]
            if (not isinstance(submitted, dict) or set(submitted) != {'value', 'evidence_id'}
                    or type(submitted['value']) is not bool
                    or not isinstance(submitted['evidence_id'], str)):
                reason = 'INVALID_FACT_PROPOSAL'
            else:
                rid = submitted['evidence_id']
                reason = registry.inspect(rid, profile_id, rule.fact_key, submitted['value'],
                                          policy.max_fact_age_seconds)
                if reason == 'WITNESSED_SYNTHETIC_FACT':
                    result = 'PASS' if submitted['value'] is rule.expected else 'FAIL'
                    reason = 'EXPECTED_VALUE_MATCH' if result == 'PASS' else 'EXPECTED_VALUE_MISMATCH'
        item = {'rule_id': rule.id, 'result': result, 'reason': reason,
                'fact_receipt_id': rid,
                'source_claim_id': rule.source_claim_id,
                'source_citations': deepcopy(source_claims.get(rule.source_claim_id, {})
                                            .get('support_citations', []))}
        outcomes.append(item)
        trace.event('CONDITION_GATE', {'rule_id': rule.id, 'result': result, 'reason': reason})
    results = {x['result'] for x in outcomes}
    decision = 'FAIL' if 'FAIL' in results else ('UNKNOWN' if 'UNKNOWN' in results else 'PASS')
    report = {
        'run_id': trace.run_id, 'task_id': policy.task_id, 'profile_id': profile_id,
        'decision': decision, 'scope': policy.scope,
        'profile_proof_level': 'SYNTHETIC_FIXTURE',
        'source_proof_level': source['proof_level'] if source else 'NOT_CHECKED',
        'source_url': claims_policy.source_url,
        'source_sha256': source['source_sha256'] if source else None,
        'source_fetched_at': source['source_fetched_at'] if source else None,
        'visible_text_sha256': source['visible_text_sha256'] if source else None,
        'decision_policy_sha256': policy_hash, 'claims_policy_sha256': claims_hash,
        'full_eligibility': 'NOT_ASSESSED', 'authorized_actions': [],
        'conditions': outcomes,
    }
    trace.event('DECISION_FINISH', {'decision': decision, 'full_eligibility': 'NOT_ASSESSED'})
    return report
