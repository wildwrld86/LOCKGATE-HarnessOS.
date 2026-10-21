# Optional model evaluation

H5 connects one Groq proposal to the same independent H4 gate. Offline replay
remains the default. The initial remote case uses only synthetic source and
applicant fixtures, so it evaluates proposal behavior without claiming real
applicant eligibility or live source verification.

## Run entirely on GitHub

1. Add a repository **Actions secret** named `GROQ_API_KEY` using your own key.
   Enter the key in GitHub's secret field; do not put it in files, issues, or chat.
2. Open **Actions → Lockgate contract and regression checks → Run workflow**.
3. Select `groq` for `evaluation_provider`, an allowlisted model your account can
   access, and one synthetic profile. Start with `demo-new`.
4. Inspect **Optional bounded Groq evaluation** and download its
   `lockgate-optional-model-evaluation` artifact. Other jobs still run their
   normal offline and live-source checks.

Pushes and PRs cannot trigger the optional Groq job. The manual default is
`offline`. A missing key/model produces `NOT_CONFIGURED` without dispatch.
Model availability and access are provider-controlled; an HTTP error is recorded
as a failed attempt and is never retried automatically.

## CLI

```bash
python -m lockgate.model_cli
python -m lockgate.model_cli --provider groq --model openai/gpt-oss-20b --case demo-new
```

For the second command, configure `GROQ_API_KEY` privately in the environment;
`GROQ_MODEL` may supply the model instead of `--model`. Each command instance
permits one remote proposal at most. A new explicit invocation reserves a new
attempt; there is no persistent account-wide spending or call ledger yet.

## Trusted limits

| Limit | Default | Enforcement |
|---|---:|---|
| Calls per adapter/remote command | 1 | Attempt reserved before worker starts; failures consume it |
| Worker wall time | 20 seconds | Parent kills/reaps worker, including stalled DNS, TLS, or reads |
| Requested completion tokens | 1,024 | API `max_completion_tokens`; reported overruns rejected |
| Encoded request | 32 KiB | Checked before worker dispatch and again before HTTP |
| HTTP response body | 64 KiB | Read with a bounded size; oversized bodies rejected |
| Proposal JSON | 16 KiB | Worker and independent H4 gate validate it |
| Redirects, proxies, tools, retries | 0 | Fixed endpoint, explicit transport configuration, response checks |

The trusted policy can lower limits; its parser rejects more than one call,
wall times above 30 seconds, or completion caps above 2,048 tokens. The model
cannot edit that policy. API keys travel in the child environment and the HTTPS
authorization header, never in command arguments or recorded payloads. The
worker inherits no unrelated environment secrets. Python host code and adapters
remain trusted; the worker is a lifetime boundary, not a general security sandbox.

Local cancellation does not guarantee provider-side cancellation or prevent a
charge for an already accepted request. Usage is `null` when not reported,
`request_attempted` can be `null` after a killed worker, and `cost_usd` is always
`null` until a separate pricing/accounting method exists. No dollar budget is
claimed. Use provider-side account controls for that purpose.

## What to review

The JSON/SQLite artifact records the model's proposed decision, the host's
independent decision, the proposal gate/refusal, model/provider IDs, source and
policy hashes, budget/latency, safe transport status, and usage when available.
It omits keys, full prompts, raw response bodies, and provider error text.

`ACCEPTED` validates a scoped decision report. `FAIL` can be a correct accepted
report. `UNKNOWN` requires review. A transport error, truncation, schema failure,
or tool response rejects the proposal. None grants application or write authority.

Current validation is mocked protocol tests plus a real subprocess kill test;
no credentialed API call has been validated yet. Inspect the first manual
artifact before drawing conclusions about a model or adding routing.

## API references checked during implementation

- https://console.groq.com/docs/api-reference
- https://console.groq.com/docs/structured-outputs
- https://console.groq.com/docs/models
