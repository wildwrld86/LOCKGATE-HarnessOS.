# LOCKGATE // Build direction

## Directive

Keep model proposals separate from authority. Trusted code owns permissions,
evidence issuance, acceptance, stopping, and the audit trail. Cloud credits are
the first proving case; provider-specific facts belong in contracts and fixtures.
Use Python standard-library tools and cloud CI without inference costs first.

## Current assessment

| Capability | Implemented boundary |
|---|---|
| H0 execution contract | Registered tools, output receipts, step/repeat budgets, SQLite trace; E0 fixtures |
| H1 source retrieval | Controlled HTTPS, public IPs, snapshots, byte hashes; E1 retrieval only |
| H2 source text check | Trusted exact quotes, configured contradictions, freshness and citations; E2 text support only |
| H3 condition decision | Recomputed source checks + host-issued synthetic fact receipts + PASS/FAIL/UNKNOWN + common trace store |
| H4 planner proposal gate | One bounded JSON proposal, host-owned independent outcome, no tool capabilities; 15 offline seeded scenarios and honest planner on live evidence |
| H5 bounded provider | Optional Groq adapter with one attempt, parent worker deadline, token/byte limits and safe telemetry; credentialed API validation pending |
| Model routing | No routing policy or measured model comparisons yet |
| Durable memory | SQLite event history; no learned factual memory or managed multiworker database |
| Authorization | No external-write authority; no E3 approval mechanism |
| Evolver | Regression cases are written by the human-authorized builder; no automated policy changes |

The code demonstrates bounded checks. It does not yet provide an isolated
security sandbox, semantic fact checking, full program eligibility, autonomous
production operations, or a complete Harness OS. Python adapters and local
configuration remain trusted host code. Source and trace hashes do not protect
against a compromised host. H3 is a build milestone, not an E3 authorization level.

## H4 evaluation boundary

The first replay matrix uses local honest/adversarial proposers with shared
contracts. It records refusal reasons, independent outcomes, and provider/model
identifiers. Its source fixtures remain E0; only the separate live retrieval
path can produce E1/E2. These results describe seeded checks, not real model
accuracy, a hardened security sandbox, or a general defense against injection.

## H5 validation boundary

The Groq adapter has mocked protocol coverage and an actual stalled-process
kill test. It uses an explicit manual cloud path and the same independent gate.
Source/applicant evidence in the first remote evaluation remains synthetic E0.
No real-model result has been validated yet, and no dollar spending cap is
claimed. The older unbounded H0 remote mode has been removed.

## Next concrete validation: H6-001

Configure the private Groq Actions secret and manually evaluate one `demo-new`
proposal. Inspect provider status, usage, latency, refusal reasons and host
outcome. If the provider call fails, turn that specific failure into a bounded
regression or transport fix. Repeat with the returning/unknown synthetic cases
only after inspecting the first run. Use actual evidence to select the next
build step; defer routing and additional architecture until measured runs exist.

Keep the resulting protocol portable before expanding provider coverage,
building a dashboard, or granting external-write authority.
