# Production Readiness Audit — OV Black

**Date:** 2026-07-09
**Scope:** `apps/api` (FastAPI backend, agent routes, services), `apps/agent` (concierge runtime), `apps/web` (Next.js), `packages/api-client`, `infra/cdk`, `supabase/migrations`.
**Method:** Five parallel deep-read audits across auth/authorization, agent-token/secrets/redaction, database/scale, frontend/infra, and payments/rate-limiting. Every finding below was read in the actual code and cites `file:line`.

---

## TL;DR

The codebase is, on the whole, **well-engineered** — parameterized SQL everywhere, `Numeric(12,2)` money (never float), server-authoritative charge amounts, a reference-quality row-locked idempotent payment path, an audience-bound HS256 agent token that keeps Dossier/OSINT away from travelers, a single-query recursive graph load, and a 500 handler that leaks nothing. The problems are concentrated in a handful of places: **infrastructure config that only bites under load or in prod**, **a few concurrency races on money paths**, **missing authorization checks on two itinerary routes**, and **the complete absence of rate limiting**.

### Ship-blockers (fix before any production traffic)

| # | Finding | Area | Why it blocks |
|---|---------|------|---------------|
| **B1** | asyncpg + Supabase transaction pooler (`:6543`) with no statement-cache disable | DB | Intermittent prepared-statement errors that only appear under load |
| **B2** | No rate limiting anywhere — incl. the LLM turn loop | Cross-cutting | Unbounded Bedrock spend (cost-DoS) + auth/enumeration abuse |
| **B3** | `POST /itinerary/{id}/assemble` has no ownership check | AuthZ | Any authenticated user can mutate another client's graph (IDOR) |
| **B4** | Double-refund race in booking cancel (no row lock) | Payments | Money leaves twice under concurrent cancel |
| **B5** | `book_node` money gate is an unlocked check-then-act | Payments | Lost race can leave a real duplicate supplier reservation |
| **B6** | Middleware token refresh is dead in production | Web/Auth | Users start 401ing after ~1h; SSE streams break |
| **B7** | Agent context/write token is not DB-bound; replayable for its TTL | Agent | A leaked token = full Dossier/OSINT read + private-fact write |
| **B8** | SSE `card`/unknown frames forwarded to the browser unfiltered | Agent | Redaction of Dossier/OSINT on the primary surface is soft-only |
| **B9** | RLS is not a real backstop — API connects as a superuser | DB | One missing `WHERE` = cross-tenant leak with nothing underneath |

Details, severities, and fixes for all findings follow, grouped by area.

---

## 1. Authentication & Authorization

The auth perimeter is broadly sound: `JWTAuthMiddleware` validates RS256/ES256 Supabase JWTs against JWKS (signature/exp/iat/sub required, algorithm derived from the JWK so no alg-confusion); advisor gating is a DB role lookup that never trusts the JWT `role` claim; most routers scope by `owner_id`/`auth_user_id` and collapse cross-tenant access to 404. The findings are the exceptions.

### HIGH

**A1 (B3) — `POST /itinerary/{id}/assemble` has NO ownership check → cross-tenant graph write**
`apps/api/app/routers/itineraries.py:1584`; service `apps/api/app/services/itineraries.py:1716`.
Every other itinerary mutator calls `_load_itinerary` + `assert_itinerary_writable` first. This route goes straight from `require_user` into the service, which only checks that the itinerary exists and the editor lock. `_check_lock` returns "allow" when `locked_by IS NULL` — the normal state for essentially all itineraries — so a non-advisor with no relationship to the target passes the only barrier. **Exploit:** any authenticated traveler POSTs `/itinerary/{victim_id}/assemble` and wires `follows` edges across the victim's nodes.
**Fix:** add the standard preamble before actor resolution:
```python
itinerary = await _load_itinerary(session, itinerary_id)
if itinerary is None:
    raise HTTPException(status_code=404, detail="not_found")
await assert_itinerary_writable(session, user, itinerary)
```

**A2 — `add_edge` doesn't verify endpoint nodes belong to the itinerary → cross-itinerary edge injection**
`apps/api/app/services/itineraries.py:1485`; route `.../itineraries.py:1635`.
The route gates the itinerary correctly, but `add_edge` inserts an edge with caller-supplied `from_node_id`/`to_node_id` after only an exists+lock check — it never verifies those nodes are in `itinerary_id`. The DB FKs reference `nodes(id)` globally with no same-itinerary constraint. Contrast `add_node`, which *does* validate parent/attachment nodes belong to the itinerary. **Exploit:** a caller who can write to itinerary A creates an edge pointing at nodes in victim itinerary B.
**Fix:** after the exists check, `SELECT id, itinerary_id FROM nodes WHERE id IN (from, to)` and reject unless both exist and both `.itinerary_id == itinerary_id` (mirror `add_node`).

### MEDIUM

**A3 — Node creation accepts caller-supplied `status` with no gate on firmed statuses**
routes `itineraries.py:1044`, `:1084`, `:1155`; service `add_node` writes `status` verbatim at `services/itineraries.py:1172`.
The G1 status gate and money gate defend *transitions of existing* nodes, but `add_node` performs no check on the *initial* status. A traveler (or the agent carrying the client's JWT) can create a node already `approved` — and `booked`/`confirmed` are accepted by the enum — bypassing the propose→approve workflow and potentially confusing the booking money gate.
**Fix:** in `add_node`, clamp create-status by actor kind — non-advisors may only create `idea`/`proposed`/`discarded`; reject firmed states from a USER actor.

**A4 — `POST /itinerary` accepts an arbitrary `client_id` (create-on-behalf-of spoofing)**
`itineraries.py:886`; `CreateItineraryRequest.client_id:123`.
Gated only by `require_user`; body `client_id` passes through with no check that the caller is that client or an advisor. `created_by` is pinned correctly, but the itinerary attaches to the victim's `client_id` and can surface on their roster.
**Fix:** if `client_id` is supplied, require caller == that client's `auth_user_id` or advisor; else 403.

**A5 — Owner can `approve` a still-`draft` itinerary, skipping the advisor propose step**
`itineraries.py:1373`; service accepts `draft` OR `proposed` at `services/itineraries.py:1823`.
The owning traveler can approve a mid-build plan the advisor hasn't proposed, cascading all `proposed` nodes to `approved`.
**Fix:** restrict traveler-initiated approve to `proposed` itineraries; reserve `draft`-approval for advisors. *Confirm intent with product.*

**A6 — Email-claim account-takeover risk: `email_verified` is never checked**
`services/clients.py:250` (email-fallback + backfill at 286-311); JWT email pulled unconditionally at `auth.py:194`. `email_verified` appears nowhere in `app/`.
`resolve_client_for_auth_user` links a Supabase user to a `clients` row (granting full ownership) when the JWT `email` case-insensitively matches a client row with `auth_user_id IS NULL`, with no `email_verified` gate. This is the ownership root for `/me/*` and all traveler itinerary writes. Exploitability depends on whether the Supabase project issues tokens for unverified emails. *(The agent JIT backfill at `services/agent.py:189` is safe — it reads email from `auth.users` server-side.)*
**Fix:** require `claims.get("email_verified") is True` before honoring the email-fallback link; verify Supabase sign-up settings.

### LOW

**A7 — Issuer/audience effectively unverified when `supabase_jwt_issuer` is unset**
`auth.py:168-176` (issuer dropped when empty, `verify_aud: False`); default `supabase_jwt_issuer=""` in `config.py:79`. Signature is still JWKS-pinned, so forged tokens are rejected — but any token validly signed by the same project is accepted regardless of `iss`/`aud`.
**Fix:** make `supabase_jwt_issuer` required in staging/prod (fail boot if empty); set a concrete `aud` with `verify_aud: True`.

**A8 — Approved itineraries readable by ANY authenticated user**
`services/itineraries.py:591` (`assert_itinerary_readable` returns early for any non-`draft` status); routes `GET /itinerary/{id}` (`:912`), `/collection` (`:942`), `/changes` (`:1725`).
Once `approved`, the read gate is satisfied for any logged-in user who knows/guesses the UUID — including the `changes` timeline (actor kinds + status transitions). Documented as intentional; mitigated only by UUID unguessability. For an invitation-only ultra-HNW product this is a real confidentiality concern. *Confirm intent with product.*

---

## 2. Agent Token, Secrets & Redaction

The design is thoughtful — server-pinned `source_kind`, aud/iss binding, short TTL, `repr=False` on secrets, collapsed 401s, no `.env` committed. The gaps are where those guarantees don't reach.

### HIGH

**AG1 (B7) — Agent context/write token is not bound to the DB session; replayable for its whole TTL**
`apps/api/app/services/agent_token.py:92-130`; route trusts `claims.client_id` at `routers/agent_internal.py:170`.
`verify_agent_token` validates signature/aud/iss/exp only. The route then trusts `claims.client_id`/`session_id` with **no DB cross-check** — never verifies the session row exists, is active, or that `session.client_id == claims.client_id`. No `jti`, no revocation list. Within the 15-min TTL the token is a fully replayable bearer credential: anything that captures it once (a proxy log, an AgentCore memory dump, an SSRF against the runtime) can read that client's entire Dossier + OSINT via `GET /agent/context` and forge `agent_inferred`/`traveler_told` facts. Revocation requires rotating the global secret (invalidating every session).
**Fix:** in `require_agent_token`, load the `AgentSession` by `claims.session_id` and assert it exists, is active, and `session.client_id == claims.client_id`. Add a `jti` + ended-session/revocation check; consider binding to `agentcore_session_id`.

**AG2 (B8) — `card`/unknown agent frames forwarded to the browser verbatim, no redaction filter**
`apps/api/app/services/agent.py:1523-1526` (unknown frames forwarded unchanged) and `:1469-1522` (the `card` branch forwards `snapshot` unchanged); frames built in `apps/agent/src/agent/translate.py:145-176` wrap the **entire tool return dict**.
The redaction guarantee on the primary traveler-facing surface (SSE → mood board) is *only* the model's discipline plus each tool's return shape — there is no server-side allowlist/scrubber on the browser-bound path. The team already knows tool outputs can carry Dossier/OSINT (the tool-trace path deliberately carries "name + id + status only", `translate.py:186-193`) — yet card/node frames forward those outputs wholesale. One tool that reflects context into its return (a "why we picked this" rationale sourced from a dossier fact) leaks private tiers, and the redaction sweep test only walks *logs*, not SSE frames.
**Fix:** define an explicit allowlist of browser-safe frame types; project `card`/`node`/`itinerary` payloads through a strict Pydantic model enumerating client-visible fields, drop the rest; do not forward unknown frame types verbatim. Add an SSE-frame redaction sweep mirroring the log sweep.

### MEDIUM

**AG3 — Token minting fails *open* to an empty token on misconfig**
`services/agent.py:1281-1285` and `:1857-1858` (`except AgentTokenError: agent_token = ""`).
If `agent_token_signing_secret` is missing in a real environment, mint raises, the exception is swallowed, and an empty token ships. Verify then 401s every context/write call — so the agent runs "blind" (no Dossier/Profile, records nothing) and degrades silently instead of failing loudly.
**Fix:** when `settings.env != "local"`, treat `not_configured` as fatal at boot/healthcheck. Keep the empty-string degradation for local dev only.

**AG4 — `logger.exception` on the agent turn can serialize payload-referencing tracebacks**
`apps/agent/src/agent/app.py:102-107`.
The catch-all emits a full traceback. The payload in scope holds the assembled system prompt (net worth, Dossier, OSINT), the `agent_token`, and the user JWT. A `pydantic.ValidationError` (or any custom `__str__`) can land the offending input value in the record — exactly the leak the redaction discipline forbids, and the API-side sweep test doesn't cover the agent runtime.
**Fix:** replace with `logger.error("agent.turn.unhandled", extra={"reason": exc.__class__.__name__})` (no traceback) or a scrubbing formatter; extend the redaction sweep to the agent runtime.

**AG5 — Disclosure rules are prompt-only (soft); traveler input is unhardened injection surface**
`app/agent/prompt.py:33-57`, `traveler_context.py:206-234`; traveler text enters unmodified at `apps/agent/src/agent/app.py:96`; stored facts re-injected via `_fact_line` (`traveler_context.py:134-143`).
The only barrier stopping OSINT/Dossier/net-worth disclosure is the natural-language `_DISCLOSURE_RULES` block. Traveler input is passed straight to the model with private context in the same prompt, and — combined with AG2 — there's no output-side scrubber to catch a slip. Separately, a traveler can seed attacker-controlled text into `dossier_facts`/`profile_facts` via the write tools; that text is re-injected unescaped into every future prompt (stored prompt injection).
**Fix:** add an output-side guard (cheap post-turn classifier or sentinel/regex check for net-worth figures + OSINT sentinels before flushing prose); delimit traveler input distinctly from instructions; keep the highest-sensitivity values (net worth, OSINT) out of the model's context, or pass as coarse buckets.

**AG6 — `places_photo_signing_secret` silently falls back to the agent-token secret**
`config.py:434-447` (fallback), `:448-458` (1-year photo-token TTL).
The same HS256 key that authorizes Dossier/OSINT reads also signs public, long-lived, browser-visible photo-proxy tokens — widening exposure of the crown-jewel secret and coupling rotation (you can't rotate the agent secret without invalidating year-long photo tokens).
**Fix:** require a distinct `places_photo_signing_secret` in staging/prod (fail boot if empty); never fall back to the agent-context key outside local dev.

### LOW / INFORMATIONAL

- **AG7** — Stale security comment in `agent_internal.py:4-9` (claims `PUBLIC_PATHS`; actual whitelist is `public_paths`/`public_prefixes` in `main.py:228-246`). Misleading comment invites a future editor to break the whitelist.
- **AG8** — `public_prefixes={"/agent/party-members/"}` (`main.py:246`) is a prefix bypass of the JWT middleware; broader than the one intended route. Every current handler under it does call `require_agent_token`, but prefer an exact-path/route-scoped check.
- **Positive** — `verify_agent_token` pins `algorithms=[_ALGORITHM]` (no alg confusion), enforces aud+iss, maps all failures to a generic 401. All real secrets are `repr=False`. No `.env` tracked in git.

---

## 3. Database, Scale & Data Integrity

Core service code is genuinely well-built: zero string-built SQL, all `text()` uses fully bind-parameterized, no ORM lazy-load N+1 (all joins hand-written and batched), `Numeric(12,2)` money throughout, keyset pagination infra exists. The problems are infra config and a few unlocked hot paths.

### CRITICAL

**D1 (B1) — asyncpg + Supabase transaction pooler (`:6543`) with no statement-cache disable**
`apps/api/app/db.py:22-28`; prod DSN `infra/cdk/lib/secrets-stack.ts:66`.
The engine sets only `pool_size`/`max_overflow`/`pool_pre_ping`. Staging/prod connect through the Supabase **transaction-mode pooler on `:6543`** (pgbouncer). asyncpg uses server-side prepared statements by default; in transaction pooling a connection moves between backends, producing intermittent `prepared statement "__asyncpg_..." does not exist/already exists` errors — hidden at low traffic, surfaced under load. No `statement_cache_size: 0` anywhere.
**Fix:** `create_async_engine(..., connect_args={"statement_cache_size": 0}, prepared_statement_cache_size=0)`, or point prod at the session pooler (`:5432`). Add a pooler smoke test.

**D2 (B9) — RLS is not a real backstop; all isolation is app-layer only**
`config.py:66`; `supabase/migrations/0031_revoke_public_api_grants.sql:11-20`; policies in `0011/0023/0024/0025/0037`.
RLS is enabled and policies exist on nearly every table, but the API connects as `postgres` (a `rolbypassrls` superuser — prod DSN `postgres.<ref>@…`). **RLS and GRANTs are bypassed for 100% of app traffic.** The `for select to authenticated` policies on dossiers/OSINT/net-worth/payments are dead code. A single missing `WHERE owner_id/client_id = …` in any handler leaks cross-tenant data (including Dossier/OSINT) with nothing underneath to catch it. *(0031 itself is sound — it closes the anon/PostgREST surface — but it protects by removing the path, not via RLS.)*
**Fix:** connect the API as a dedicated `NOBYPASSRLS` non-superuser role and make policies load-bearing; **or** formally accept app-layer authz as the sole perimeter, add cross-tenant authz tests, and document it.

**D3 (B5) — `book_node` money gate is an unlocked check-then-act**
`apps/api/app/services/bookings.py:620-626, 698-761`.
`_load_node` (620) and `_booking_for` (625) are plain SELECTs with **no `with_for_update()`**. Two concurrent `POST …/book` both pass the gate. The `bookings_one_per_node` partial unique index (`0028:61`) prevents a duplicate *row*, but the service does **not** catch the resulting `IntegrityError` (loser 500s instead of returning `already_booked`), and for a Bokun supplier node the upstream `reserve()`+`confirm()` (698/706) fire **before** the local insert — a lost race can leave a real duplicate supplier reservation with money committed and no local record.
**Fix:** `SELECT … FOR UPDATE` the node at load and catch `IntegrityError → already_booked`, mirroring the correct `services/payments.py:88` pattern.

### HIGH

**D4 — `itineraries.client_id` has no index**
FK added `0008:26`; no `CREATE INDEX` exists. This is the hottest join in the schema ("itineraries for a client," Command Center, agent context). Sequential scans that worsen linearly with table growth.
**Fix:** `create index concurrently itineraries_client_id_idx on public.itineraries (client_id);`

**D5 — `clients.auth_user_id` has no index; scanned on every client login**
`models/client.py:65`; query `services/clients.py:278`. Only `clients(owner_id)` is indexed. Full scan on the login-resolve fast path for every client-role request.
**Fix:** `create index concurrently clients_auth_user_id_idx on public.clients (auth_user_id) where auth_user_id is not null;`

**D6 — Whole-roster attention scan on every advisor roster page / awareness poll**
`routers/advisor_itineraries.py:157-163`, `awareness.py:106` → `load_advisor_attention`. ~7 aggregate queries across the advisor's **entire** roster regardless of the ≤100 rows on the page, paid on every page and every `/awareness` poll. Cost grows with total roster size.
**Fix:** scope aggregates to the page's itinerary ids, or cache per advisor with a short TTL.

**D7 — Analyze in-flight guard is an unlocked check-then-schedule → doubled LLM cost**
`services/analyze.py:148-207`. SELECT for queued/running then add+commit; `analyses_status_idx` (`0017`) is non-unique. Two concurrent `POST /analyses` both schedule runners.
**Fix:** partial **unique** index on `(itinerary_id) WHERE status IN ('queued','running')` + catch IntegrityError, or `pg_advisory_xact_lock`.

**D8 — Unindexed money-path FKs**
`bookings.offer_id` (`booking.py:103`), `bookings.invoice_line_item_id` (109), `bookings.refund_payment_id` (159), `node_offers.refreshed_from_offer_id` (65) — all FKs with no index. Reconciliation joins seq-scan; slow referenced-row deletes.
**Fix:** add an index on each.

### MEDIUM

- **D9** — Pool is small (5+5=10) with no `pool_timeout`/`pool_recycle` (`db.py`, `config.py:72-73`). Long-lived advisor SSE feeds + background tasks draw on 10 connections; the Supabase pooler also caps tenant connections. Set explicit `pool_timeout`/`pool_recycle` and size against the pooler limit.
- **D10** — Session-open reuse race (`services/agent.py:399-451`) and `_ensure_itinerary_for_client` (865-877): select-then-insert with no lock/partial-unique → duplicate live sessions / itineraries under concurrent `POST /sessions`. *(Turn-index assignment at 828-849 is correctly locked.)*
- **D11** — `party_members.attach_member_to_itinerary` (`services/party_members.py:215-247`): check-then-insert, no lock/unique → duplicate traveler under concurrent attach.
- **D12** — Unbounded list endpoints (no LIMIT): `/me/itineraries` (`me.py:207`), `/me/invoices` (`me.py:231`→`services/invoices.py:598`), `/sessions/{id}/turns` (`agent.py:331`), `list_messages` (`services/messaging.py:353`). N+1 avoided, but full history per request/poll. Add keyset limits (infra exists in `services/pagination.py`).
- **D13** — `GET /agent/context` issues the same `AgentSession.itinerary_id` SELECT 3× per turn (`agent_internal.py:100-158`) plus 2 extra Itinerary lookups — redundant round-trips on the hottest per-turn path.
- **D14** — `list_messages` GET has a write side-effect (`_mark_thread_read` UPDATE+commit) — non-idempotent, non-cacheable read endpoint.
- **D15** — All `CREATE INDEX` are non-`CONCURRENTLY`; new CHECK/FK adds lack `NOT VALID`. On a large prod `node_history` (`0042:19-22`) an index build takes a write-blocking lock. Plan hot-table index/constraint additions accordingly.
- **D16** — `advisor_money` currency band re-runs `_base_stmt()` across all roster invoices on every page (`services/advisor_money.py:203`).
- **D17** — Key-less payments have no DB uniqueness backstop (`0030:21-23` is partial). Relies solely on the app-layer `FOR UPDATE` (which is correct) — acceptable, but no DB belt.
- **D18** — `currency` is free-text everywhere; no DB CHECK that line currency == invoice currency or that invoice total = Σ(lines). Money-gate correctness is app-layer only (consistent with D2).

### LOW

- `Node.deleted_at` soft-delete tombstone unindexed (`itinerary.py:403`); bounded by `(itinerary_id, …)` composites today. `nodes_starts_at_idx` (`0014:124`) is partial `WHERE starts_at IS NOT NULL`, so the wish-list `starts_at IS NULL` query is uncovered.
- `messages.proposed_node_id`/`parent_message_id` FKs unindexed (`messaging.py:150,155`).
- `onboarding.py:62` and `demos.py` use `ORDER BY func.random()` (tiny tables — fine now). `demos.py:157` counts via `.all()` + `len()` instead of `func.count()`.

**Confirmed clean:** no SQL injection (all `text()` bind-parameterized incl. the recursive graph CTE `services/itineraries.py:975-1005`); no ORM lazy-load N+1 (no `relationship()` defs); money is `Numeric(12,2)` everywhere; `pay_invoice` and `open_or_create_human_thread` are reference-quality lock+idempotency+IntegrityError patterns.

---

## 4. Frontend & Infrastructure

Posture is good: `OVB_*` runtime env avoids `NEXT_PUBLIC_` inlining; the web ECS task carries no secrets/IAM grants; secrets flow through Secrets Manager via `EcsSecret.fromSecretsManager` scoped to exact ARNs; ALB terminates TLS with HTTP→HTTPS redirect; the vault S3 bucket is `BLOCK_ALL` + `enforceSSL`; agent SSE content renders via `react-markdown` with no `rehype-raw` (no XSS); dossier/OSINT render only in advisor-scoped `/command-center` server components behind an API that 403s non-advisors.

### HIGH

**F1 (B6) — Middleware token refresh is dead in production**
`apps/web/middleware.ts:24-28`.
The middleware reads `NEXT_PUBLIC_SUPABASE_URL`/`ANON_KEY`, but the app was migrated to **runtime** `OVB_*` vars — the ECS task injects only `OVB_SUPABASE_*` (`infra/cdk/lib/api-stack.ts:398-401`) and the web Dockerfile passes no build args (`apps/web/Dockerfile:11-13`). So in the deployed image both vars are `undefined`, the guard returns early, and `supabase.auth.getUser()` (the refresh trigger, line 49) **never runs**. Access-token cookies are never refreshed server-side; long sessions / SSE turn streams start 401ing after ~1h. Silent in local dev (`.env.local` sets `NEXT_PUBLIC_*`), so it won't surface until prod.
**Fix:** resolve config via `resolvePublicEnv()` from `lib/env.ts` (checks `OVB_*` then `NEXT_PUBLIC_*`) instead of reading `NEXT_PUBLIC_*` directly.

**F2 (B2) — No rate limiting anywhere in the stack** *(also see X1)*
`apps/web/middleware.ts` / `apps/api/app/main.py` / `infra/cdk` — no WAF, no throttle; `routers/auth.py:37-43` `rate_limit_login` is a no-op stub.
No ALB WAFv2 WebACL (grep for `Waf|WebAcl|wafv2` → zero hits), no per-IP throttling, no app-level limiter on any route including the SSE turn loop. `POST /auth/login` can hammer Supabase's admin API (email-send abuse); authenticated abuse of `/sessions/*/turn` drives unbounded Bedrock spend.
**Fix:** implement `rate_limit_login` (per-IP + per-email token bucket); attach an AWS WAFv2 WebACL with rate-based rules to the ALB; add per-actor turn-rate caps on SSE.

### MEDIUM

**F3 — Command Center shell has no server-side *role* gate**
`apps/web/app/command-center/layout.tsx:32-37`, `lib/appHeader.ts:54-68`.
The advisor layout gates only on *authentication* — `getAppHeaderContext` returns non-null for any logged-in user (advisor *or* client). A signed-in traveler can load the entire advisor Command Center shell. Data is protected because every page calls the advisor-scoped API (403/empty), but the route protection is auth-only, not role-based — any page that renders before/without the API call, or reads Supabase directly under RLS, would expose advisor UI to travelers.
**Fix:** redirect in the layout unless `header.role === "advisor"` (send clients to `/basecamp`); keep the API 403s as the authoritative gate.

**F4 — Bedrock AgentCore IAM policy uses `Resource: "*"`**
`infra/cdk/lib/api-stack.ts:201-212`.
The task role grants `bedrock-agentcore:InvokeAgentRuntime` + event actions on `resources: ['*']` (a documented M001 concession). The API task can invoke/read events on any AgentCore runtime in the account; compromise blast-radius is account-wide.
**Fix:** now that the runtime ARN is populated into a secret, scope to `arn:aws:bedrock-agentcore:<region>:<account>:runtime/<id>`.

**F5 — Single Fargate task per service, no autoscaling, no availability floor**
`infra/cdk/lib/api-stack.ts:419-432` (api), `440-453` (web).
Both services run `desiredCount: 1` with no `ScalableTarget`/`scaleOnCpu`. `minHealthyPercent: 50` on a 1-task service can take it to 0 healthy during deploys. No horizontal scale (compounds F2), single-task crash or AZ event = full outage, no CDN in front of the web tier.
**Fix:** `desiredCount ≥ 2` across AZs; `service.autoScaleTaskCount(...).scaleOnCpuUtilization(...)` and/or request-count-per-target; consider CloudFront for the web tier.

### LOW

- **F6** — ECR image tags are mutable (`api-stack.ts:98-141`, no `imageTagMutability: IMMUTABLE`). A pushed `sha-<x>` tag can be overwritten. Set immutability.
- **F7** — Container hardening gaps: no `containerInsights`, no `readonlyRootFilesystem` (`api-stack.ts:157-160`, `262-354`, `378-405`).
- **F8** — Vault CORS falls back to `allowedOrigins: ['*']` when `webOrigin` is empty (`api-stack.ts:227-236`). Shouldn't trigger in a real deploy, but a latent wildcard on the HNW-document bucket — drop the fallback (fail closed).
- **F9** — API CORS is `allow_credentials=True` with `allow_methods/headers=["*"]` (`main.py:275-281`). Origins are correctly scoped to `web_origin`, so safe today; tighten `allow_headers` to the actual set for strictness. Not blocking.

**Confirmed clean:** no secrets in the browser bundle (only Supabase URL/anon key, Mapbox token, API base — all intentionally public); agent token never reaches the browser; no `localStorage`/`sessionStorage` token storage (Supabase SSR uses cookies); SSE parser validates frame shape and renders content as markdown text, not HTML.

---

## 5. Payments, Bookings & Cross-Cutting

Notably well-hardened: money is `Numeric(12,2)`/`Decimal` end-to-end, charge amounts are server-derived, no card data touches the server (Braintree nonce only), the 500 handler returns generic `internal_error` with no stack trace, and file upload is a presigned two-step flow with path-traversal-sanitized S3 keys.

### HIGH

**P1 (B4) — Double-refund race in booking cancel (no row lock)**
`apps/api/app/services/bookings.py:875-1010` (`cancel_booking`).
The pay path row-locks the invoice (`payments.py:88`), but cancel locks nothing. It loads the booking, checks status, then calls `gateway.refund(...)`. Two concurrent `POST …/cancel` both pass the checks and **both issue a gateway refund** — the `bookings_one_per_node` index doesn't help because both requests UPDATE the same existing row. Result: double refund + duplicate supplier-cancel.
**Fix:** `SELECT … FOR UPDATE` the booking (or invoice) row at the top of `cancel_booking`, re-check `cancelled_at is None`/status under the lock before the gateway call. An idempotency key on the refund `Payment` adds defense-in-depth.

**P2 (B2) — No rate limiting; agent-turn LLM cost-DoS** *(same root as F2; see X1)*
`main.py:226-284`, `routers/agent.py:263-317`, `routers/auth.py:37-43`.
`POST /sessions/{id}/turn` streams an expensive Bedrock turn on every call with no per-user/session throttle or in-flight cap — an authenticated traveler can fan out unbounded concurrent turns. Messaging (`POST /threads/{id}/messages`) can also summon Artemis → another LLM turn (`messaging.py:173-184`), equally unthrottled.
**Fix:** real rate limiting keyed on the authenticated `sub`, tightest budget on agent turns and the `@Artemis` bridge; wire the `rate_limit_login` stub.

### MEDIUM

**P3 — Synchronous JWKS fetch blocks the event loop on every request path**
`apps/api/app/auth.py:86-108` (`_refresh`/`get_key`), called from async `dispatch`.
`_refresh()` uses a **synchronous** `httpx.Client(timeout=5.0)` on the event loop, not offloaded to a thread. `get_key` refreshes on stale TTL **or unknown kid** — an attacker sending tokens with random `kid` forces repeated refreshes, each blocking the entire event loop up to 5s. Every other blocking call in the codebase is correctly wrapped in `anyio.to_thread.run_sync`; this one isn't.
**Fix:** use `httpx.AsyncClient` and `await`, or wrap `_refresh` in `anyio.to_thread.run_sync`; don't refresh on unknown-kid (only on stale TTL).

**P4 — No request body size limit**
`apps/api/app/main.py` (no content-length guard).
Field-level caps exist (content ≤ 8000, nonce ≤ 4096), but a request is fully buffered and JSON-parsed before Pydantic rejects it — a multi-hundred-MB body still gets read and parsed (memory/CPU DoS).
**Fix:** middleware rejecting `Content-Length` over a cap (and guarding chunked bodies) with 413 before parsing.

**P5 — Provider HTTP clients never closed on shutdown**
`main.py:208-212` (lifespan `finally` only calls `dispose_engine()`).
Six inventory providers each build an `httpx.AsyncClient` (`_owns_client=True`); teardown never `aclose()`s them. Connection pools/sockets leak on shutdown, impairing graceful termination.
**Fix:** iterate the registry in the lifespan `finally` and `await provider.aclose()`.

### LOW

- **P6** — Refund amount can in principle exceed the original charge: `cancel_booking` refunds `booking.amount` with no assertion `≤ payment.amount` (`bookings.py:970-977`). Relies on Braintree to reject — fragile. Clamp/assert before the gateway call.
- **P7** — No retry/backoff or circuit breaker on external inventory calls. All providers have 5–15s timeouts and are async (good), but the Bokun `reserve/confirm/cancel` money path would benefit from retry.
- **P8** — `resolve_photo_url` (`google_places.py:744`) inherits the 15s client timeout but has no tighter per-call budget on the public photo-proxy path.

**Confirmed clean:** idempotency is real (`pay_invoice` `payments.py:112-260` — fast-path replay + authoritative replay under `FOR UPDATE` + `IntegrityError` on `payments_idempotency_idx`); amount/currency server-authoritative; no card data on the server; money is Decimal; booking state machine gated (only path to `booked` is the money gate, all booking writes `require_advisor`, supplier booking fail-closed); file upload authz-scoped with sanitized S3 keys, no SSRF; 500 handler leaks nothing.

---

## 6. Cross-Cutting Theme

**X1 — There is no rate limiting anywhere in the stack.** This surfaced independently in three audits (F2, P2, and the auth review) and deserves to be treated as one program, not three fixes:
- **Cost-DoS:** unbounded concurrent `/sessions/{id}/turn` and `@Artemis` message bridges → unbounded Bedrock spend. This is the single highest-leverage abuse vector for a product whose per-request cost is a paid LLM call.
- **Auth/enumeration abuse:** `/auth/login` hammering Supabase's admin API (email-send cost); no lockout.
- **Load shedding:** nothing sheds or spreads traffic before it reaches the single Fargate task (F5).

Address with: (1) an AWS WAFv2 WebACL with rate-based rules on the ALB; (2) an app-level limiter (SlowAPI/Redis token bucket) keyed on the authenticated `sub`, tightest on agent turns; (3) horizontal scale + autoscaling (F5).

---

## Recommended Fix Order

1. **B1 / D1** — asyncpg pooler statement cache (silent prod failure under load).
2. **B2 / X1** — rate limiting (WAF + app limiter), tightest on LLM turns.
3. **B3 / A1** — add the ownership gate to `/assemble`; **A2** — node-membership check in `add_edge`.
4. **B4 / P1** and **B5 / D3** — row-lock booking cancel and `book_node`.
5. **B6 / F1** — fix middleware env resolution (prod auth refresh).
6. **B7 / AG1** and **B8 / AG2** — DB-bind the agent token; filter/allowlist SSE frames.
7. **B9 / D2** — decide RLS-backstop vs. documented app-layer-only, add cross-tenant authz tests.
8. **D4 / D5** and the money-path FK indexes (**D8**) — the hot-path indexes.
9. **F5** — `desiredCount ≥ 2` + autoscaling.
10. Everything Medium, then confirm the "intent" items (**A5, A8**) with product.

*Generated by parallel deep-read audits; every finding cites `file:line` for direct verification.*
