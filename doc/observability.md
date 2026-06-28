# Observability runbook (apps/api)

How to tell what went wrong when you're driving the live stack. The API emits
**structured logs**, **CloudWatch EMF metrics**, and **log-based spans**, all
correlated by a per-request `request_id`. The design is dependency-free and
**OpenTelemetry-ready** — the metric/span emitters sit behind a seam
(`emit_metric`, `set_span_recorder`) so swapping in OTel later doesn't touch call
sites. Code lives in [apps/api/app/observability](../apps/api/app/observability/).

## The one thing to grab: `request_id`

Every response carries an `X-Request-Id` header (minted per request, or echoed
if the caller sent one). Every log line emitted while handling that request
carries the same `request_id`. So the debugging loop is:

1. Reproduce the bad behavior in the UI / `ovb` / curl.
2. Read `X-Request-Id` off the response (the global 500 handler also puts it in
   the JSON body: `{"detail":"internal_error","request_id":"…"}`).
3. Filter logs by that id.

```bash
# local (text format): every line for one request
uv run uvicorn app.main:app --reload 2>&1 | grep <request_id>
```

```sql
-- staging/prod (CloudWatch Logs Insights, JSON format)
fields ts, level, logger, event, route, status, duration_ms, @message
| filter request_id = "<request_id>"
| sort ts asc
```

## Log format

`LOG_FORMAT=auto` (default): **text** when `ENV=local` (readable console),
**json** otherwise. Force with `LOG_FORMAT=json|text`.

Every JSON line has: `ts, level, logger, event, service, env`, the bound context
(`request_id, method, path, route`), and any per-call `extra` fields flattened to
top-level keys. Example access line:

```json
{"ts":"…","level":"INFO","logger":"ov_black.request","event":"http.request",
 "request_id":"…","method":"POST","path":"/invoices/abc/pay",
 "route":"/invoices/{invoice_id}/pay","status":200,"duration_ms":143.2}
```

Useful event names to filter on: `http.request` (access log, one per request),
`http.request.error` (unhandled 500 + traceback), `db.slow_query`,
`invoice.payment`, `agent.turn.complete`, `inventory.provider.search`, `span`.

## Metrics (CloudWatch EMF)

`emit_metric()` writes EMF log lines that CloudWatch auto-extracts into metrics —
**no PutMetricData, no agent, no infra**. Namespace `OVBlack/API` (override with
`METRICS_NAMESPACE`); `Service` + `Env` dimensions are added automatically. Mute
with `METRICS_ENABLED=false`. What's emitted today:

| Metric | Unit | Dimensions | Meaning |
|---|---|---|---|
| `http.request.latency` | ms | Route, Method | per-request latency |
| `http.request.count` | count | Route, Method, Status | request/error volume |
| `db.slow_query` | count | Op | queries over `DB_SLOW_QUERY_MS` |
| `span.duration` / `span.count` | ms / count | Span, Ok | any `metric=True` span |
| `agent.turn.latency` / `agent.turn.first_token` | ms | Outcome | R015 2 s SLO |
| `agent.turn.count` | count | Outcome, Retried | turn volume + retries |
| `payment.count` | count | Gateway, Status | succeeded/failed charges |
| `payment.gateway_error` / `payment.token_error` | count | Gateway | infra failures |

## Spans

`async with span("name", metric=True, **attrs)` (or `span_sync`) times a block,
logs a `span` line with `duration_ms`, and (when `metric=True`) emits the
`span.*` metrics above. Instrumented boundaries: each inventory provider call in
the search fan-out, and both payment gateway calls. To find a slow upstream in
one request: filter `event = "span"` by `request_id` and sort by `duration_ms`.

## Slow queries

A SQLAlchemy listener logs `db.slow_query` (statement text only — never bound
params) for anything over `DB_SLOW_QUERY_MS` (default 500). This is the cheap
path to N+1 / missing-index hunts: when a request feels slow, its `db.slow_query`
lines name the statement and the duration, correlated by `request_id`.

## Settings (env vars)

| Var | Default | Notes |
|---|---|---|
| `LOG_FORMAT` | `auto` | `auto`→text local / json cloud; or force |
| `LOG_LEVEL` | `INFO` | root level |
| `METRICS_ENABLED` | `true` | EMF emission on/off |
| `METRICS_NAMESPACE` | `OVBlack/API` | CloudWatch namespace |
| `REQUEST_LOG_ENABLED` | `true` | per-request access line |
| `DB_SLOW_QUERY_MS` | `500` | slow-query threshold |
| `SERVICE_NAME` | `ov-black-api` | stamped on logs + metric dims |

## Redaction discipline (unchanged, still enforced)

Net worth, Dossier, OSINT, the agent token, the user JWT, the payment nonce /
processor txn id / card last-four / raw processor payload **must never** appear
in a log record. The structured formatter only serializes what call sites pass —
the discipline is at the call site, and the sweep tests in
`tests/test_traveler_context.py` / `tests/test_payments.py` enforce it. The
`ov_black.metrics` logger never carries secrets (ids + numbers only).

## Payment flow hardening (M005 I2/I3)

Bundled with the instrumentation because these were both perf and correctness
risks in the active payment path:

- **Event loop no longer blocks**: the synchronous Braintree SDK call was being
  awaited inline (stalling all concurrent requests for the whole charge); it now
  runs in a worker thread, bounded by `BRAINTREE_TIMEOUT_SECONDS` (default 8 s).
- **No double-charge**: `SELECT … FOR UPDATE` row-locks the invoice for the
  charge so two concurrent pays serialize (the loser sees `paid` and is refused),
  and an optional `Idempotency-Key` header (unique per `invoice_id`, migration
  `0025`) makes a retried pay replay the prior outcome instead of charging again.
- **Error vs decline**: a gateway *error* (timeout/network — outcome unknown)
  records **no** payment and returns `payment_gateway_unavailable` (safe to retry
  with the same key); a settled *decline* still records a `failed` row.
- Only the read-only client-token call is auto-retried; the charge never is.

### Known follow-ups (not yet done)

- `packages/api-client` not regenerated for the new optional `Idempotency-Key`
  header / new error detail strings — additive, so the web build is unaffected;
  regenerate (`pnpm -C packages/api-client generate`) when the web pay UI wires
  the header.
- No async settlement **webhook** yet — if the process dies after Braintree
  settles but before our commit, reconciliation needs a pull (I3 money-gate).
