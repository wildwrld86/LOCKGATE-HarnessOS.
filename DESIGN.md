# LOCKGATE // DESIGN

## Thesis

Do not ask a probabilistic model to act as its own permission system, evidence authority, memory store, or completion judge. Treat it as a bounded proposer operating in a deterministic environment. Differentiate *instruction*, *observation*, *proof*, and *authority*.

## The minimal loop

```text
USER GOAL -> CONTRACT (trusted host configuration)
                 |
              PLANNER <--- observations (untrusted records, bounded context)
                 |
       action JSON: tool or final
                 |
       VALIDATE ACTION / STEP / REPEAT BUDGET
            /                  \
          TOOL                 FINAL
           |                     |
    ALLOWLIST CHECK         OUTPUT GATE
           |                     |
    HOST EXECUTES            RECEIPT VALID?
           |                     |
    MINT EVIDENCE ---------> ACCEPT or REJECT
           |
    APPEND TRACE, LOOP or STOP
```

## Security principles

- The planner does not get OS, network, database, repository, messaging, or payment credentials.
- Trust the contract only when it comes from an authorized user/admin process. An LLM cannot change the contract.
- Reject tool names not registered by code even if the model hallucinates them or the JSON contract mentions them.
- Deny side effects by default. Introduce capability-scoped host-side approvals before any email, purchase, repo write, or invoice action.
- Never interpret source text as operational instructions. Prompt-injection defense ultimately requires bounded capabilities, not just prompt wording.
- Verification of evidence *existence* is weaker than checking the truth of evidence. Only claim checks that the program actually implements.
- A verifier should not rely on model self-attestation. Independently inspect authoritative source evidence where feasible.
- Keep decision traces append-only; do not casually store user data, credentials, private documents or full reasoning prompts in public artifacts.
- Every run has a cost, tool, loop, and elapsed-time budget; the first demo implements step + repetition budgets, not cost or elapsed time.

## Evidence maturity levels

| Level | Definition | Available in H0? |
|---|---|---|
| E0 synthetic | A fixture observed through an allowed tool and referenced by a valid receipt | Yes |
| E1 retrieved | A live page fetched through controlled egress and snapshotted | No |
| E2 checked | A deterministic or independent verification step comparing claims to current primary sources | No |
| E3 authorized | Sensitive external write, identity proof, or human approval as required | No |

Output gating should encode a task-specific minimum. H0 only demonstrates E0; it cannot support a production claim of eligibility or grant availability.

## Proposed Leverage Seeker task contract (v1)

```json
{
  "task_id": "LS-OPPORTUNITY-2026-001",
  "objective": "Determine whether an infrastructure credit is worth human review",
  "inputs": ["provider_url", "applicant_profile"],
  "tools": ["fetch_official_page", "extract_terms", "verify_source"],
  "require": ["primary_source_url", "eligibility", "expiry_or_unknown", "evidence_hash"],
  "max_steps": 12,
  "max_cost_usd": 0.05,
  "side_effects": "none",
  "on_uncertainty": "human_review",
  "on_verification_failure": "not_verified"
}
```

This JSON is a design proposal, **not** supported by the demo runtime; H0 uses `contracts/demo.json`.

## Failure-to-harness upgrades

1. Capture a minimal, privacy-safe failure trace.
2. Name the failure category: unauthorized tool, unsupported claim, stalled loop, stale evidence, policy conflict, time or budget overrun.
3. Convert the trace into an adversarial regression case.
4. Propose the smallest deterministic check that would have prevented it.
5. Run regression suite and collect false-rejection rate; human-review the change.
6. Merge an approved policy version. Rerun held-out cases.
7. Measure whether validated outcomes improved, not simply whether the model complied.

The *Evolver* must never silently weaken policy or auto-approve its own security changes. At most it proposes reviewed changes.

## Success metrics

- Accepted outputs with independent primary-source support / all accepted outputs
- Unsupported or forged outputs blocked / all seeded attacks
- Legitimate tasks incorrectly blocked / all legitimate test cases
- Human review minutes per verified candidate
- Model/API dollars per reviewed candidate
- Duplicate/repeated actions per run
- Percentage of failures that become regression tests

## Next smallest production vertical

For LEVERAGE//SEEKER, begin with exactly one official-source opportunity category (e.g. cloud provider credits), and focus on *whether the source, terms, and eligibility claims can be independently checked*. Avoid customer-facing actions and automatic applications until read-only verification is reliable.
