# LOCKGATE // Harness OS — H0

**A tiny, model-agnostic harness: the model proposes; deterministic code enforces.**

Designed as a first, cloud-first building block for LEVERAGE//SEEKER, SI COLONY, and Grok Bot Desk. Does **not** modify or connect to those repositories. No external Python dependencies. Python 3.11+.

## What works now

- Explicit JSON contract: tool allowlist, output acceptance fields, bounded step budget, repeated-action stop rule, short-lived evidence requirements.
- Intent proposals from deterministic demo planners, with a separate bounded Groq adapter for the H4 condition gate; planners receive no execution authority.
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

Optional Groq evaluation (one proposal using synthetic source/profile data):

```bash
python -m lockgate.model_cli --provider groq --model openai/gpt-oss-20b
```

Set `GROQ_API_KEY` privately in the environment first. The cloud workflow uses a
repository secret and an explicit manual Groq selection. See `MODEL_EVALUATION.md`.
The legacy H0 `--mode groq` path has been removed; H0 is an offline demonstration.

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
Open **Actions → Lockgate contract and regression checks** to see the tests
and the demo run. A successful run includes a **lockgate-demo-trace** artifact
containing the JSON summary and SQLite audit log, retained for seven days.
No API key is required for push/PR checks. Groq inference runs only when explicitly
selected through the manual workflow; regular CI uses mocked provider responses.
Read `TEAM.md` before contributing.

## H1: one official-page snapshot

Run the trusted-host fetcher with no API key:

```bash
python -m lockgate.retrieval_cli
```

The initial policy in `contracts/retrieval.json` allows only the
`docs.aws.amazon.com` hostname; the default requested page is
`https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html`.
The first Google startup-program page exceeded the bounded response cap, so
the smoke test uses an official AWS plan and credit page as its E1 source. Its
configured hostname is an exact match; it rejects HTTP, other hosts, ports,
credentials, URL queries, fragments, non-public DNS answers, unexpected content
types, compression, oversized responses, and redirect loops. TLS still verifies
the allowed hostname although the connection uses a vetted resolved address.
The response bytes are stored under `runtime/snapshots/` with SHA-256 naming and
a separate JSON manifest containing the final URL, redirect chain, resolved IP,
timestamp, response type, and hash. CI attempts one read-only live retrieval on
push and publishes the `lockgate-evidence-chain` artifact. The deterministic tests
do not depend on that external page.
The response cap is 2 MiB; larger pages are rejected rather than truncated.

## H2: exact source-text checks

The trusted host contract `contracts/claims.json` defines two exact excerpts
about AWS account credits. After H1 writes `retrieval-summary.json`, run:

```bash
python -m lockgate.verification_cli --retrieval-summary retrieval-summary.json
```

H2 first checks the E1 source URL, timestamp, byte count, and SHA-256. It then
extracts visible HTML text without executing scripts, normalizes whitespace,
and looks for each configured excerpt and explicit contradiction excerpt. Its
report records the source hash, visible-text hash, quote hash, and character
offsets into the saved `.visible.txt` file. The CLI succeeds only if **every**
trusted excerpt is present and none of its configured contradictions is present;
unknown, contradicted, or conflicting claims return exit code 2 and require
review. The live GitHub Actions job applies this gate after retrieval and
includes the E2 report and text in its downloadable artifact.

**E2_SOURCE_TEXT_MATCH proves only that these exact words appear in the
approved source snapshot.** It does not infer the eligibility of a particular
founder, detect every possible contradiction, establish that provider terms
remain unchanged, or validate an arbitrary model-written paraphrase. An
untrusted planner cannot edit the host claim contract or promote E1 to E2;
the H0 synthetic demo remains a separate E0 workflow. The report and hashes
are an audit trail, not a cryptographic signature against a compromised host.

## H3: scoped decisions with witnessed facts

```bash
python -m lockgate.decision_cli --retrieval-summary retrieval-summary.json
```

This bounded host command joins the existing source verifier, host-issued fact
receipts, a generic boolean condition gate, and SQLite tracing. It rechecks E1
bytes and current E2 claims on every decision. A saved JSON report saying
`CHECKED` is not accepted as proof. The trusted `contracts/decision.json` lists
the required facts, expected values, scope, and source claim IDs. The planner's
proposal may only reference receipts created by the host in that run.

The included fixture matrix demonstrates:

| Synthetic applicant fact | Condition result |
|---|---|
| Witnessed `is_new_customer: true` | PASS |
| Witnessed `is_new_customer: false` | FAIL |
| Missing, forged, expired, mismatched, or self-certified fact | UNKNOWN |

A failed source check makes the decision UNKNOWN. For multiple checked rules,
all must pass for PASS; a definite failed rule yields FAIL even if another fact
is missing. Receipts are bound to the run, profile, fact key, value, and age.
The demo command exits zero only when its expected PASS/FAIL/UNKNOWN matrix
matches and its source checks passed. That exit status reports a successful
test run; it grants no applicant approval or action permission.

Every result retains source citations, source/policy hashes, a run ID, and a
SQLite event trace. `profile_proof_level` is always `SYNTHETIC_FIXTURE`,
`full_eligibility` is always `NOT_ASSESSED`, and `authorized_actions` is empty.
H3 evaluates one configured condition, not the provider's full eligibility
terms. Real applicant facts still need an independently trusted adapter and a
defined verification procedure. Keep personal profiles out of public fixtures
and downloadable CI artifacts.

See `ROADMAP.md` for the implementation boundary and next task.

## H4: proposal-only planner and offline replay

```bash
python -m lockgate.replay_cli
```

The planner gets a separate copy of bounded observations and can submit one
JSON `final` proposal. It receives no tool capabilities, registry handle, file
paths, or database handle. The host independently computes the decision from
its own task facts after planning, then checks the proposal's profile, fact
receipts, and claimed decision. Dropping an adverse fact cannot change that
host decision. Requests to mint receipts or call tools are rejected.

The offline matrix exercises 15 scenarios: honest PASS/FAIL/UNKNOWN, unsupported
PASS, withheld evidence, forged receipts, changed values, wrong profiles,
mutated observations, unauthorized tools, self-certification, fabricated source
checks, source changes, malformed output, and planner exceptions. Its expected
result is two accepted scoped reports, eleven rejected proposals, and two
review outcomes. Acceptance of a faithful FAIL report does not approve an
applicant. UNKNOWN requires review.

Every replay preserves scenario/provider/model identifiers, refusal reasons,
independent outcomes, policy/source hashes, and SQLite events. The provider is
`offline-fixture` and the model identifier is `seeded-python-v1`: these are local
test doubles, not a measured API model. No API inference or external tool call
is used by this matrix. CI uploads the `lockgate-offline-replay` artifact.

Replay source manifests are explicitly `E0_SYNTHETIC_REPLAY` and successful
text checks stay `E0_SYNTHETIC_TEXT_MATCH`. Trusted replay code must enable that
mode explicitly; normal source verification rejects such manifests. Synthetic
source checks never become live E1/E2 evidence. Python adapters remain trusted
code and are not isolated or independently timed out by this boundary. Proposal
responses are limited to 16 KiB of JSON and a single call.

To exercise the same planner gate with a live H1 snapshot and synthetic profiles:

```bash
python -m lockgate.decision_cli --retrieval-summary retrieval-summary.json --planner-mode seeded-honest
```

CI runs that path too. Both paths retain `full_eligibility: NOT_ASSESSED` and
an empty `authorized_actions` list.

## H5: optional bounded model evaluation

`python -m lockgate.model_cli` defaults to offline replay. Its explicit
`--provider groq` path sends one proposal request to a fixed HTTPS endpoint with
the trusted model allowlist and budget in `contracts/model.json`. A dedicated
worker process has a parent-enforced deadline, one reserved attempt, provider
completion-token cap, request/response byte limits, and independent JSON/output
checks. Requests have no tools, redirects, proxies, or automatic retries.

The existing H4 gate independently decides the outcome. Reports retain actual
provider/model IDs, latency, reported usage when available, the budget hash, and
safe failure codes. Cost remains unknown (`null`); local timeout cannot cancel
provider-side work or establish a dollar spending cap. All applicant/source
data in this first remote evaluation is synthetic and stays E0.

The adapter is validated with mocked responses and an actual stalled-process
kill test. A credentialed provider run has not yet been performed. The cloud
steps and exact limits are in `MODEL_EVALUATION.md`.

**E1_RETRIEVED_ONLY means the page was fetched.** Its contents are untrusted
data, and this stage makes no eligibility, deadline, availability, or applicant
claim. It is separate from the H0 planner and cannot authorize new tools.
Network connect/read time and response size are bounded, but DNS lookup has no
portable timeout in the Python standard library; address-level connection
failures can also prevent this first single-address prototype from reaching a
healthy alternate address. Treat live CI failures as retrieval failures, not as
evidence that a credit has disappeared.

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
