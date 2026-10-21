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
| Model routing | Optional Groq H0 adapter only; no validated routing policy |
| Durable memory | SQLite event history; no learned factual memory or managed multiworker database |
| Authorization | No external-write authority; no E3 approval mechanism |
| Evolver | Regression cases are written by the human-authorized builder; no automated policy changes |

The code demonstrates bounded checks. It does not yet provide an isolated
security sandbox, semantic fact checking, full program eligibility, autonomous
production operations, or a complete Harness OS. Python adapters and local
configuration remain trusted host code. Source and trace hashes do not protect
against a compromised host. H3 is a build milestone, not an E3 authorization level.

## Next bounded task: H4-001

Connect a proposal-only planner to the H3 gate and build an offline replay matrix.
Use the same contracts with an honest proposer and seeded adversarial proposers.
Show that unsupported PASS claims, missing evidence, source changes, and attempts
to issue new fact receipts cannot change the independently computed outcome.
Persist outcomes, refusal reasons, and model/provider identifiers so later model
comparisons have a common evidence trail. The first matrix needs no paid API.

Require this adapter/replay boundary before expanding provider coverage, building
a dashboard, adding routing, or granting external-write authority.
