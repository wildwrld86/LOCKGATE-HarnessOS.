# LOCKGATE // Harness OS — H0

**A tiny, model-agnostic harness: the model proposes; deterministic code enforces.**

Designed as a first, cloud-first building block for LEVERAGE//SEEKER, SI COLONY, and Grok Bot Desk. Does **not** modify or connect to those repositories. No external Python dependencies. Python 3.11+.

## What works now

- Explicit JSON contract: tool allowlist, output acceptance fields, bounded step budget, repeated-action stop rule, short-lived evidence requirements.
- Intent proposals from a deterministic demo planner **or** an optional Groq model; neither directly executes tools.
- Read-only tools over synthetic local fixture data; Python policy checks every tool call.
- Evidence receipts are minted only by successful read tool execution and bound to the current run.
- Deterministic output verifier: matching fields must agree with **one** witnessed source record; forged receipts fail.
- Planner observations are deep copies, so changing them cannot rewrite the harness's witnessed evidence.
- SQLite event traces; tests exercise wrong tool, skipped proof, loops, mismatched fields, unbounded step budget.
- GitHub Actions CI and downloadable demo traces.

## Try it

```bash
python -m unittest discover -s tests -v
python -m lockgate.cli --mode demo
python -m lockgate.cli --mode wrong-tool  # exits 2 by design
python -m lockgate.cli --mode skip-proof # exits 2 by design
python -m lockgate.cli --mode loop       # exits 2 by design
```

Optional Groq API integration:

```bash
export GROQ_API_KEY='your-private-key'
export GROQ_MODEL='a-current-model-id-your-account-supports'
python -m lockgate.cli --mode groq
```

Never commit secrets. In GitHub Actions use repository secrets for protected values if you later add an authenticated run.

## Test matrix

| Scenario | Expected | Enforced by |
|---|---|---|
| Model reads fixture, cites receipt and matching source fields | ACCEPTED | Output and evidence gate |
| Model asks to `send_email` | HALTED | Registered tool + contract allowlist |
| Model fabricates evidence ID / skips read | HALTED | Receipt registry + loop/step limit |
| Model repeats the same useless call | HALTED | Repeated-action budget |
| Model cites a record but changes URL | HALTED | Same-source exact-field comparison |
| Contract allows millions of steps | Configuration rejected | Contract validation |
| Planner edits an observed source and submits it with a real receipt | HALTED | Observation copy + authoritative evidence gate |

## Run it on GitHub

Every push and pull request runs `.github/workflows/verify.yml` using Python 3.11.
Open **Actions → Lockgate contract and regression checks** to see the seven tests
and the demo run. A successful run includes a **lockgate-demo-trace** artifact
containing the JSON summary and SQLite audit log, retained for seven days.
No API key is required. Groq inference is optional and is not exercised by CI.
Read `TEAM.md` before contributing.

## Trust limits / explicit non-features

**This prototype does not verify an opportunity on the internet.** The fixture data is fabricated and the proof level is `synthetic_fixture_grounding_only`. 'ACCEPTED' means the result was supported by read-only *test evidence*, not that the underlying claim is objectively correct.

A production implementation must add independent live-source verification, safe network egress rules, content extraction, source freshness thresholds, appropriate authorization and human review for side effects, safe secret management, persistent backups, quotas and money limits, and tests for prompt injection. The API model may still make logical mistakes; a deterministic gate only protects what the code actually checks.

The Python planner adapter runs inside the host process and must be trusted code.
Observation copies prevent accidental or context-based evidence mutation; they
do not sandbox arbitrary Python. Only the remote model's JSON proposals are
treated as untrusted input. Free-text recommendations are not fact-checked by
the exact-field gate.

`TraceStore` records non-sensitive metadata only by convention. Audit the event schema before using real customer, financial, or private data. This code is a proof of concept, not a hardened security boundary or a production SaaS.

## Upgrade sequence

1. Build `fetch_official_page` with hostname allowlist, redirect validation, DNS/IP egress controls, TLS checks, and reproducible citations. Treat fetched pages as data, not instructions.
2. Add a second independent `verify_finding` stage that checks eligibility/deadline against independently retrieved primary sources, not model self-report.
3. Add consent-based write actions behind approval tokens issued by the host, with explicit scopes and expiry.
4. Export signed evidence receipts to a durable store (SQLite locally; managed database if required), record hashes + source snapshots subject to privacy policies.
5. Add provider routing and quantitative tests: accepted grounded outputs, unjustified claims rejected, cost per verified finding, stall rate, time-to-review.
6. Add guarded 'Evolver': propose tests/rules via PR, run regression suite, require human approval before any policy change.

## Why not just use a framework?

Frameworks such as OpenAI Agents SDK and LangGraph can already provide orchestration, tracing, persistence, and review primitives. LOCKGATE is intended to be a small **portable enforcement contract** over whichever model/framework eventually runs the work. Do not reimplement every available feature when an existing runtime fits.
