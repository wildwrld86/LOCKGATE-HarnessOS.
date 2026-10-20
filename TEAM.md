# LOCKGATE // Team coordination

Read this file before substantial changes. Claim bounded work before editing,
preserve other contributors' claims and notes, and leave a handoff when done.
Never commit secrets or private traces. Policy changes need human review.

## Claims

- H0-001 — ChatGPT — completed: import and verify H0, isolate planner observation
  copies from authoritative evidence, add a regression, and publish the baseline.
  Scope: starter files, tests, CI, and project documentation.

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
- Next unclaimed task H1-001: design and implement one read-only official-page
  fetcher with strict allowed hosts, validated redirects and resolved public IPs,
  bounded response size/time, snapshot hashes, and explicit retrieved-only proof.
  Test denied hosts, redirects, private addresses, and oversized responses before
  using a real cloud-credit page. Retrieval alone must not imply eligibility.
