# LOCKGATE // Team coordination

Read this file before substantial changes. Claim bounded work before editing,
preserve other contributors' claims and notes, and leave a handoff when done.
Never commit secrets or private traces. Policy changes need human review.

## Claims

- H0-001 — ChatGPT — completed: import and verify H0, isolate planner observation
  copies from authoritative evidence, add a regression, and publish the baseline.
  Scope: starter files, tests, CI, and project documentation.
- H1-001 — ChatGPT — completed: implement read-only official-page retrieval with
  host and redirect controls, pinned public IP connections, bounded response,
  hashed snapshots, independent tests, and one real page smoke run.
  Scope: retrieval module, CLI/config, tests, CI, docs; no H0 policy loosening.
- H2-001 — ChatGPT — completed: independently check trusted exact source-text
  claims against a fresh E1 snapshot; report unknown and contradiction states,
  retain text citation offsets and hashes, and deny E2 completion otherwise.
  Scope: verifier, trusted claim contract, tests, CI, and documentation.
- H3-001 — ChatGPT — implemented; live CI pending: add a generic three-valued decision gate with
  source checks recomputed from E1, host-issued fact receipts, synthetic profiles,
  scoped outcomes, and a SQLite decision trace. Join these in a bounded CLI/CI run.
  Scope: decision module, fixtures/contracts, tests, workflow and docs.

## Notes

- 2026-10-20: User authorized H0 initialization in `wildwrld86/LOCKGATE-HarnessOS.`.
  Existing repository contained only its introductory README. No other claims or
  agent instructions were present in its tree.
- 2026-10-20 H0 handoff: Original six regressions passed. Added a seventh to block
  planner mutation of observed source data, and pass observation deep copies to
  the planner. All seven pass locally. CI runs the same suite and uploads a demo
  summary plus SQLite trace; no API credentials are needed. Live Groq inference
  and internet opportunity verification remain untested and unimplemented,
  respectively. The Python planner adapter is trusted host code, not a sandbox.
- 2026-10-20 H1 handoff: Added trusted-host CLI for one official page, exact
  hostname and redirect policy, public-IP DNS validation, pinned TLS connection,
  size/time checks, SHA-256 snapshot and E1-only manifest. The planner has no
  network authority. Fifteen local tests pass, including injected private DNS,
  hostile redirects, forged evidence and oversized bodies. Local external DNS
  was unavailable; the live official-page smoke job was checked in CI.
  DNS lookup itself has no portable Python stdlib timeout, and this stage picks
  only one vetted address. No eligibility claims are extracted or verified.
- Live smoke attempts against the Google pre-funded page were rejected at both
  1 MiB and 2 MiB. The policy cap remains 2 MiB; smoke source changed to the
  official AWS Free Tier credit FAQ. No rejected page became an E1 receipt.
- The AWS FAQ URL redirected to a different hostname and was denied by the
  exact-host policy. The smoke source is now a direct AWS Billing documentation
  page on the already permitted `docs.aws.amazon.com` host.
- Live GitHub Actions run 39515538508 succeeded for both jobs. The E1 artifact
  contains a 20,739-byte source snapshot and manifest with matching SHA-256
  `779c708ffc32f201ed24aa1fa0e2b1cd2c89f95e745fbe1515451039d6b61fc1`.
  No redirect was followed. The snapshot demonstrates retrieval only; no
  applicant eligibility or source truth has been independently checked.
- 2026-10-20 H2 handoff: Added exact-source-text host contract, independent
  verifier, freshness and hash checks, visible text/citation offsets, explicit
  contradiction and unknown statuses, and a failing CI gate unless all claims
  are supported. Twenty-two deterministic tests pass. A previous live E1
  artifact also passed both configured quotes locally. Fresh GitHub Actions
  run 39516195231 passed both jobs. Its E2 artifact's two quote offsets and
  hashes were independently recomputed against the saved visible text and
  source snapshot (SHA-256 `779c708ffc32f201ed24aa1fa0e2b1cd2c89f95e745fbe1515451039d6b61fc1`).
  This is exact text support only, not semantic or applicant verification.
- Direction review: LOCKGATE remains a reusable execution/accountability layer.
  Credit programs are the proving case. H3 checks one stated condition using
  synthetic applicant facts; a passing condition cannot become a full program
  eligibility claim. Routing, approvals, Evolver, and real identity evidence
  remain future work. Reuse the source verifier and trace store already present.
- H3 handoff: Thirty local tests pass. The three-case fixture matrix also ran
  against the prior AWS E1 artifact and returned PASS / FAIL / UNKNOWN as
  expected. Source checks are recomputed instead of trusting saved E2 JSON.
  Fact receipts are scoped to run/profile/key/value/age. Decision outputs retain
  source citations, policy hashes, explicit synthetic provenance, no authorized
  actions, and `full_eligibility: NOT_ASSESSED`. Fresh CI must confirm the
  retrieval-to-decision chain. See `ROADMAP.md` for the broad assessment.
- Next unclaimed task H4-001: proposal-only planner adapter and an offline
  replay matrix using the same condition gate. Prefer this integration and
  adversarial evaluation before expanding credit-specific features.
