# Phase 5 (Async Analyze) — Implementation Handoff

Read this before writing any Phase 5 code. Pairs with
[phase6_fill_handoff.md](phase6_fill_handoff.md) — Phase 5 is the
prerequisite that doc points to. Source design lives in
[TravelGraph_Analysis.md](../../japan-itin/TravelGraph_Analysis.md) §8.

---

## 1. State of the world

**Branch:** `feat/travelgraph-schema-spine`.
**Tip commit:** `39741cb` — `seed-japan-demo.sh` script.
**Test count:** 376 passing.
**DB:** local Supabase Postgres on `127.0.0.1:54322` with PostGIS + the four TravelGraph migrations applied (`0014` schema spine, `0015` card templates).

### Done — phases 1-4 (see [phase6_fill_handoff.md §1](phase6_fill_handoff.md#1-state-of-the-world))

Quickly: schema spine, per-type card attrs, server-side linearization,
card templates + Japan demo seeder + integration stubs.

### Not done — phases 5 / 6 / 7 / 8

- **Phase 5 — Async Analyze** ← this doc.
- **Phase 6 — Fill**. Depends on Phase 5.
- **Phase 7 — Status-aware mutation gates** + agent-readable `lock_reason`.
- **Phase 8 — Meld / Extract** UI ops on the parties model.

---

## 2. Conventions to follow

Most are documented in [phase6_fill_handoff.md §2](phase6_fill_handoff.md#2-conventions-already-established--follow-them) — read that first. **Don't re-derive them.**

Phase 5 introduces three new concerns the existing doc doesn't cover:

### 2a. Long-running work in-process

The recommended runner for the first cut is FastAPI `BackgroundTasks`
inside the same uvicorn process. That means:

- The work happens after the HTTP response is sent but in the same
  event loop. **Use a fresh DB session, not the request session** —
  the request's session is closed by the time the task runs.
- Don't hold any Python-level lock across an `await` that touches the
  DB; the request handler returns quickly and the task picks up
  independently.
- Errors raised inside `BackgroundTasks` are *swallowed by FastAPI*.
  The runner must catch its own exceptions and write them to
  `analyses.error_detail` + flip status to `failed`. Re-raising leaks
  the failure into the void.

### 2b. Lifespan hooks

Phase 5 adds an `on_startup` reaper that runs once when uvicorn boots,
inside the existing `app.main:lifespan` async context manager. Pattern:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    ...
    # NEW — Phase 5 reaper
    async with get_sessionmaker()() as s:
        await reap_orphaned_analyses(
            s, max_running_seconds=600
        )
    ...
    yield
    ...
```

Keep it sequential with the rest of startup so failures show up as
"refused to start" — not silent half-running state.

### 2c. Calling integration stubs from a service

Phase 4 wired in [`/integrations/...`](../apps/api/app/routers/integrations/) but they're HTTP routes, not callable as Python. **Two options:**

1. Refactor each stub into `app/integrations/<name>.py` with a service-style
   function the analyzer imports directly, and have the router thinly
   wrap that function. Cleanest.
2. Have the analyzer call its own API via `httpx.AsyncClient` over
   localhost. Cheap but adds a real network hop.

**Pick (1).** Treat the routers as transport over the same module.
Same pattern as `app/services/itineraries.py` ↔ `app/routers/itineraries.py`.

The refactor target: each stub becomes
`app/integrations/<provider>/{client,router}.py` (or similar) where
`router.py` only does request-validation + dispatch. The analyzer
imports `client.search_places(...)` etc. directly.

---

## 3. Phase 5 — design

### 3.1 Schema — migration `0016_async_analyze.sql`

```sql
create type public.analysis_status as enum (
  'queued','running','completed','failed','cancelled'
);

create type public.analysis_depth as enum ('shallow','standard','deep');

create type public.finding_severity as enum (
  'info','suggest','warn','block'
);

create table public.analyses (
  id              uuid primary key default gen_random_uuid(),
  itinerary_id    uuid not null references public.itineraries (id)
                                  on delete cascade,
  status          public.analysis_status not null default 'queued',
  depth           public.analysis_depth not null default 'standard',
  scope           jsonb not null default '{}'::jsonb,
   -- {
   --   node_ids?:    [uuid, ...]  // null = whole itinerary
   --   time_window?: { from: ts, to: ts }
   --   party_id?:    uuid
   --   branches:     'selected_only' | 'all'   // default selected_only
   -- }
  inputs_hash     text,
   -- sha256 of canonicalized {node ids, edge ids, scope, depth} at
   -- run start; lets a re-request find a recent equivalent run.
  requested_by    uuid references auth.users (id) on delete set null,
  requested_kind  text not null,  -- 'user' | 'advisor' | 'agent' | 'system'
  started_at      timestamptz,
  completed_at    timestamptz,
  result          jsonb,
   -- final aggregated result the agent reads:
   -- { summary, top_findings: [...], drive_times?: {...}, ... }
  summary         text,
  external_calls  jsonb not null default '[]'::jsonb,
   -- audit: [{provider, endpoint, status, ms, error?}, ...]
  error_detail    text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.analysis_findings (
  id              uuid primary key default gen_random_uuid(),
  analysis_id     uuid not null references public.analyses (id)
                                  on delete cascade,
  node_id         uuid references public.nodes (id) on delete set null,
   -- null = whole-itinerary finding
  severity        public.finding_severity not null,
  category        text not null,
  message         text not null,
  evidence        jsonb not null default '{}'::jsonb,
  suggested_fix   jsonb,
   -- shape compatible with Phase 6's FillProposal so Fill can pick
   -- one up and present it; null when the finding is informational.
  created_at      timestamptz not null default now()
);

create index analyses_itinerary_idx on public.analyses (itinerary_id);
create index analyses_status_idx
  on public.analyses (status)
  where status in ('queued','running');
create index analyses_inputs_hash_idx
  on public.analyses (itinerary_id, inputs_hash, depth)
  where status = 'completed';
create index analysis_findings_analysis_idx
  on public.analysis_findings (analysis_id);
create index analysis_findings_node_idx
  on public.analysis_findings (node_id) where node_id is not null;
create index analysis_findings_severity_idx
  on public.analysis_findings (analysis_id, severity);

alter table public.analyses          enable row level security;
alter table public.analysis_findings enable row level security;
```

Idempotent idiom — match `0014` / `0015` (`do $$ begin ... end$$` for
the type creations, `if not exists` everywhere).

### 3.2 State machine

```
queued ──► running ──► completed
   │          │
   │          ├──► failed     (runner caught exception)
   │          └──► cancelled  (caller hit /cancel)
   │
   └──► cancelled  (cancelled before runner started)
```

Rules:
- A row spends ≤ a few seconds in `queued` — if `BackgroundTasks` is
  busy it stays longer, but in practice the FastAPI scheduler picks it
  up immediately.
- Only the runner transitions `queued → running` and
  `running → completed | failed`. The cancel endpoint can transition
  any not-yet-terminal status to `cancelled`. Idempotent: cancelling a
  `cancelled` row is a no-op 200.
- Terminal states (`completed`, `failed`, `cancelled`) are immutable.
  The runner checks `status` before each commit; if it's already
  `cancelled` the runner exits the loop, doesn't write anything.
- The `started_at` / `completed_at` columns mirror the transitions;
  they're useful for "how long does a deep run take" SLO tracking.

### 3.3 Endpoints

All under `/itinerary/{itinerary_id}` and require `require_user` (the
existing JWT middleware). Authorization mirrors the `GET /itinerary/{id}`
draft-read gate — advisor, owning client, or the creator can read.

```
POST   /itinerary/{itinerary_id}/analyses
       body: { depth?, scope? }
       → 202 Accepted, { analysis_id, status }

GET    /itinerary/{itinerary_id}/analyses?limit=20
       → 200, list[AnalysisSummary]

GET    /itinerary/{itinerary_id}/analyses/{analysis_id}
       → 200, AnalysisDetail (including findings)

POST   /itinerary/{itinerary_id}/analyses/{analysis_id}/cancel
       → 200, AnalysisDetail (status='cancelled')
```

Notes:
- `POST` returns `202`, not `201` — semantically the resource exists
  immediately but its "real" content is still being computed. The
  client polls or subscribes (subscription is out of scope; long-poll
  via the GET).
- Concurrency: a second `POST` while one is `running` returns the
  existing in-flight row with `200` (not 409). Caller can choose to
  cancel + restart with a different scope.
- Recent-completion lookup: `POST` first checks `analyses_inputs_hash_idx`
  for a `completed` row matching `(itinerary_id, inputs_hash, depth)`
  within the last N minutes (default: 5 for `shallow`, 60 for
  `standard`, 24h for `deep`). If found, return that row's id with a
  `cache_hit: true` flag.

### 3.4 Background runner

Pattern in [`app/services/analyze.py`](#):

```python
async def run_analysis(analysis_id: uuid.UUID) -> None:
    """BackgroundTask entrypoint — opens its own session.

    Wraps every transition in try/except. On uncaught exception flips
    to ``failed`` with the str(exc) tail; never re-raises.
    """
    async with get_sessionmaker()() as session:
        try:
            await _transition_to_running(session, analysis_id)
            await _do_the_work(session, analysis_id)
            await _transition_to_completed(session, analysis_id)
        except asyncio.CancelledError:
            await _transition_to_cancelled(session, analysis_id, "task_cancelled")
            raise
        except Exception as exc:
            logger.exception("analyze.run.failed", extra={"analysis_id": str(analysis_id)})
            await _transition_to_failed(session, analysis_id, str(exc)[:1000])

# Router calls:
@router.post(...)
async def start_analysis(..., background: BackgroundTasks):
    analysis = await create_queued_analysis(session, ...)
    background.add_task(run_analysis, analysis.id)
    return AnalysisCreatedResponse(...)
```

Per-itinerary serialization: before queueing, check for any
`status in ('queued','running')` row for the same `itinerary_id`. If
found, return that row instead of creating a new one. Avoids two
runners racing on the same graph.

### 3.5 Lifespan reaper

```python
async def reap_orphaned_analyses(
    session: AsyncSession,
    *,
    max_running_seconds: int = 600,
) -> int:
    """Mark any 'running' row older than max_running_seconds as 'failed'
    with error_detail='abandoned_at_restart'. Called once at startup.
    """
```

Why 10 minutes default: a deep analysis with several Google Routes
calls can legitimately take a few minutes. 10 min leaves headroom for
slow live providers without leaving genuinely orphaned rows around for
hours. Tunable via env var `ANALYZE_REAPER_MAX_RUNNING_SECONDS`.

### 3.6 Concurrency model

| Concern | Resolution |
|---|---|
| Two simultaneous starts | Pre-insert check → return existing in-flight |
| Crashed runner mid-flight | Lifespan reaper on next boot |
| Cancel mid-run | Runner checks `status` before each commit; exits if cancelled |
| Many parallel itineraries | One BackgroundTask each — uvicorn worker handles N concurrently as long as none blocks the loop |
| One worker, many clients | OK for staging. Production scaling is a future slice (worker pool / Celery) |

---

## 4. Depth tiers — what each one actually does

The analysis-doc resolved that **depth is explicitly chosen, not inferred** — caller passes `depth` to `POST /analyses`. The default is `'standard'`.

### 4.1 `shallow` — structural-only, no external calls

What it does:
- Schema-level checks: missing required CardAttributes fields per
  status (e.g. `confirmed` flight without `flight_code`).
- Type/role consistency: `role IS NOT NULL` rows have the right
  treatment; `attached_to_node_id` non-null only on `type='note'`.
- Time non-linearity: `tstzrange &&` overlap on the same party.
- "Fuzz fingerprint": count how many nodes have `null starts_at`,
  `null location`, and report it as the planning-maturity score in
  `result.summary`. The agent reads this and lowers expectations.

What it does **NOT** do:
- Hit Google Places / weather / flight status / routes.
- Compute drive times.
- Look up inventory.

When to use:
- Early planning (lots of fuzz).
- The graph just changed and the user wants a quick sanity check.
- Cheap CI hook on every commit (free, sub-second).

### 4.2 `standard` — physical-feasibility envelope

Adds, on top of `shallow`:
- Drive-time estimation between consecutive selected nodes via
  haversine × per-mode speed cap. Emits `location_flux` findings.
- Venue availability: pull node-level hours hints from the integration
  stubs (`google_places.details(place_id)` if the node has one),
  cross-check against `starts_at`. Emits `availability` findings.
- Party constraints: walk `node_parties` + `travelers.profile_attrs`
  for hard-restriction matches (allergens, age, mobility). Emits
  `party` findings.
- Weather coarse: stub forecast at each day's location. Adds
  `weather` info-severity findings — never blocks.

Per-mode speed caps (defaults; tunable via env):

| Mode | km/h | Buffer minutes per edge |
|---|---|---|
| walk | 5 | 0 |
| subway | 35 | 5 |
| train | 80 | 10 |
| drive (urban) | 25 | 15 |
| drive (intercity) | 70 | 15 |
| boat | 25 | 10 |
| flight | n/a (use schedule) | 90 |

When to use:
- Default. Most user-initiated analyses run here.
- After firming up a day's plan.

### 4.3 `deep` — live data, real cost

Adds, on top of `standard`:
- Live drive times via the routes endpoint (Phase 4 didn't stub this
  one — see [phase6_fill_handoff.md §9](phase6_fill_handoff.md#9-existing-seam--integration-stubs)).
- Live flight status (the existing `/integrations/flight-status`).
- Currency drift if cost is in `metadata`.

This is the tier that makes the proactive-agent example work:
> "I noticed you're landing at 10pm in Austin, but real-time drive to
> Houston is 3h 40m given current traffic..."

When to use:
- Pre-trip checks within ~24h of `starts_at`.
- Agent-initiated when the user pinned a flight time.

---

## 5. Finding categories — implementation contracts

Every finding row must carry:
- `category` — one of the values below.
- `severity` — `info` / `suggest` / `warn` / `block`.
- `message` — single-sentence, agent-readable.
- `evidence` — structured jsonb the agent can reason over.
- `suggested_fix` (optional) — Fill-shaped payload Phase 6 picks up.

### 5.1 `category` values

| Category | Severity range | Tier | Evidence shape |
|---|---|---|---|
| `time` | `warn` / `block` | shallow+ | `{ overlapping_node_id, overlap_minutes, party_id? }` |
| `location_flux` | `warn` / `block` | standard+ | `{ from_node_id, to_node_id, distance_km, available_min, mode, max_speed_kmh }` |
| `availability` | `warn` / `suggest` | standard+ | `{ venue_open_at, venue_close_at, place_id }` |
| `party` | `warn` / `block` | standard+ | `{ traveler_id, restriction_kind, restriction_value }` |
| `weather` | `info` / `suggest` | standard+ | `{ condition, emoji, summary, contingency_in_attrs }` |
| `traffic` | `warn` | deep | `{ live_minutes, scheduled_minutes, route_polyline }` |
| `cost` | `info` / `warn` | standard+ | `{ source, amount, traveler_currency_amount }` |
| `inventory_stale` | `warn` | standard+ | `{ provider, last_synced_at, current_status }` |
| `missing_required` | `suggest` / `warn` | shallow+ | `{ field_path, status_required_for }` |
| `cyclic` | `block` | shallow+ | `{ cycle_node_ids: [...] }` |

### 5.2 `severity` semantics

- `info` — purely informational. Doesn't gate Fill. Renderer shows
  with no glyph.
- `suggest` — the analyzer thinks the user might want to act. Fill is
  encouraged to consume `suggested_fix`.
- `warn` — there's a problem; the user should know. Renderer shows
  with a warning glyph. Fill can still proceed but its proposals
  inherit the warning.
- `block` — physical impossibility. Fill **must not** present
  candidates that don't resolve this finding.

### 5.3 `result` (top-level, on `analyses.result`)

Shape the agent reads from one row:

```json
{
  "summary": "Mostly firm; 1 location-flux warning on Day 5; weather looks rough Day 8.",
  "stats": {
    "node_count": 36,
    "fuzz_count": 4,           // nodes with null starts_at or location
    "block_count": 0,
    "warn_count": 1,
    "suggest_count": 3
  },
  "by_category": {              // counts, for at-a-glance UI
    "time": 0, "location_flux": 1, "availability": 0, ...
  },
  "drive_times": {              // standard+ tier; helps Fill skip its own queries
    "<from_node_id>:<to_node_id>": { "minutes": 47, "distance_km": 38, "mode": "drive" }
  },
  "party_energy_budget": {     // optional; per-party per-day energy fold
    "<party_id>": { "<yyyy-mm-dd>": { "intrinsic": -3, "modulated": -7 } }
  }
}
```

Keep it **agent-readable** — flat-ish, named keys, ≤ 4kb. The detailed
findings live in `analysis_findings`.

---

## 6. Inputs hash + cache hits

Computing `inputs_hash`:

```python
import hashlib, json

def compute_inputs_hash(
    node_ids: list[str],
    edge_ids: list[str],
    scope: dict,
    depth: str,
) -> str:
    canonical = {
        "nodes": sorted(node_ids),
        "edges": sorted(edge_ids),
        "scope": _canonicalize(scope),
        "depth": depth,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
```

What this catches: re-running the same analysis on the same graph state
returns the cached `completed` row. What it doesn't catch: a node's
`metadata` jsonb edit that doesn't change the id — that's intentional
because metadata edits are common and we don't want to invalidate every
recent run on a typo fix. If the user wants a fresh run they can pass
`force_rerun: true` in the request body.

TTLs (in `analyses_inputs_hash_idx` lookup):
- `shallow`: 5 minutes — cheap to redo, freshness matters.
- `standard`: 60 minutes — significant external-call cost.
- `deep`: 24 hours — but live data goes stale fast, so deep cache hits
  must include freshness gates (e.g. flight status max-age ≤ 30 min).

---

## 7. Agent integration

The agent runs inside Bedrock AgentCore and calls back to the API via
the existing per-session HS256 token (see
[`apps/api/app/agent/`](../apps/api/app/agent/) and
[`apps/api/app/routers/agent_internal.py`](../apps/api/app/routers/agent_internal.py)).
**Phase 5 endpoints are user-facing** — `require_user` JWT only — but
the agent already carries the user's JWT for tools that act on behalf
of the user.

Tool surface to add to the agent's prompt (in
[`apps/api/app/agent/prompt.py`](../apps/api/app/agent/prompt.py)):

- `start_analysis(itinerary_id, depth?)` — POST /analyses, returns id.
- `get_analysis(itinerary_id, analysis_id)` — GET, returns status + findings.
- `list_analyses(itinerary_id, limit?)` — GET, list.
- `cancel_analysis(itinerary_id, analysis_id)` — POST cancel.

When the agent should call `start_analysis`:
- The user just pinned a card (`status: idea → proposed`).
- The user moved a card's time.
- The user added/removed a party member.
- The user explicitly asked "is the trip looking good?" or similar.

The agent's loop:
1. Check `list_analyses` for a recent `completed` analysis.
2. If none recent, call `start_analysis` with depth chosen by trip
   maturity (use `result.stats.fuzz_count` from the most recent shallow
   run as the heuristic; ≥ 30% of nodes fuzzy → `shallow`, else
   `standard`; only `deep` within ~24h of `starts_at`).
3. Poll `get_analysis` (the agent runtime supports this — long-running
   tool calls are fine).
4. Read `result.summary` and `result.stats` into the agent's context;
   selectively pull individual `analysis_findings` rows when the user
   asks "tell me more about that warning".

The system prompt should label findings as **agent-private** — the
agent uses them to reason and proactively flag issues, but the raw
finding text is rarely surfaced verbatim. Findings are like Dossier
entries: ground reasoning, surface as natural conversation.

---

## 8. Graceful degradation under provider failures

Tiers `standard` and `deep` call external providers (today's stubs,
tomorrow's live integrations). Failure modes:

| Failure | Behavior |
|---|---|
| Single provider 404 (e.g. unknown flight code) | Continue; emit `info` finding with `evidence.lookup_missed: true` |
| Single provider 5xx | Retry once with 1s backoff; on second failure, downgrade THAT lookup, emit `info`, continue |
| Whole tier of providers unreachable (e.g. all Places calls fail) | Downgrade analysis to next-lower tier; record `result.degraded_from: 'standard'` and a top-level `info` finding |
| All providers fail at `shallow` | impossible — shallow makes no calls |

The runner records every external call in `analyses.external_calls` so
post-mortems are obvious. Audit shape:

```json
[
  {
    "provider": "google_places", "endpoint": "details/<id>",
    "status": 200, "ms": 142
  },
  {
    "provider": "weather", "endpoint": "forecast", "status": 502,
    "ms": 1031, "error": "bad_gateway"
  }
]
```

---

## 9. Open decisions before you code

| Question | Recommended default | Why open |
|---|---|---|
| Refactor stubs to importable modules first? | Yes, before Phase 5's analyzer code | Avoids a "loopback HTTP" anti-pattern. Add `app/integrations/<provider>.py` with `client` functions; have the existing routers thin-wrap. |
| Concurrency cap per itinerary | 1 in-flight | Avoids racing runners. Second POST returns existing in-flight. |
| Reaper threshold | 10 minutes | Tunable via env. |
| Cache TTL per depth | 5min/60min/24h (with freshness gates on deep) | First-cut numbers; revisit with real usage. |
| Agent depth heuristic | Fuzz ≥ 30% → shallow, else standard, deep only ≤ 24h pre-trip | First-cut; might want stickier policy. |
| Authorization for `GET /analyses` | Same draft-read gate as `GET /itinerary/{id}` | Reuse the function — don't duplicate. |
| Where does `inputs_hash` live during the run | Compute at `running` transition, store in same row | Lets cancel-then-restart find a different hash if scope changed. |
| Force-rerun toggle | `body.force_rerun: bool = false` | Bypass cache when user explicitly wants fresh data. |
| Agent token vs user JWT for analyze endpoints | User JWT (agent has it on its session) | Avoids a second auth path. |

---

## 10. Files you'll add / touch

### New
- `supabase/migrations/0016_async_analyze.sql`
- `apps/api/app/models/analysis.py` — `Analysis`, `AnalysisFinding`, the three new enums.
- `apps/api/app/services/analyze.py` — public surface: `create_queued_analysis`, `run_analysis` (the BackgroundTask entrypoint), `cancel_analysis`, `get_analysis`, `list_analyses`, `reap_orphaned_analyses`.
- `apps/api/app/services/analyze_runners/` — one module per depth: `shallow.py`, `standard.py`, `deep.py`. Each exposes `async def run(session, analysis) -> Result`.
- `apps/api/app/routers/analyze.py` — the four endpoints under `/itinerary/{id}/analyses`.
- `apps/api/app/integrations/__init__.py` + `apps/api/app/integrations/google_places.py` + `apps/api/app/integrations/weather.py` + `apps/api/app/integrations/flight_status.py` — refactored from the existing routers; routers now import these and thin-wrap.
- `apps/api/tests/test_analyze_models.py` — pure-Python guards.
- `apps/api/tests/test_analyze_service.py` — integration: queued → running → completed lifecycle, cancel, reaper, cache hits.
- `apps/api/tests/test_analyze_router.py` — endpoint behavior + auth gates.
- `apps/api/tests/test_analyze_runners_shallow.py` — shallow-tier findings on contrived itineraries.
- `apps/api/tests/test_analyze_runners_standard.py` — standard-tier with stubbed providers.

### Touch
- `apps/api/app/main.py` — `include_router(analyze_router)` + lifespan reaper call.
- `apps/api/app/models/__init__.py` — re-export new models.
- `apps/api/app/routers/integrations/{google_places,weather,flight_status}.py` — import the new client modules; thin-wrap.
- `apps/api/app/agent/prompt.py` — add the four analysis tool descriptions.
- `apps/api/app/agent/` — wire actual tool dispatch for those four (depends on existing tool-call pattern).
- `packages/api-client/` — regenerate (`pnpm -C packages/api-client generate`).

### Don't touch
- The Phase 4 demo endpoint and Japan template builder.
- The frontend prototypes (analysis findings rendering is a follow-up).
- Status-gate enforcement (Phase 7).

---

## 11. First-day checklist

Top-down, build-against-tests:

1. Read [phase6_fill_handoff.md §3](phase6_fill_handoff.md#3-phase-5--async-analyze-prerequisite) — the Phase 5 sketch I wrote earlier; this doc supersedes it but has the same shape.
2. Skim [`apps/api/app/services/timeline.py`](../apps/api/app/services/timeline.py) and [`apps/api/app/services/templates.py`](../apps/api/app/services/templates.py) for the dataclass-result + raw-SQL idiom.
3. Refactor the integration stubs into importable client modules (a pre-step). One small commit. Verify tests stay green.
4. Migration `0016`. Apply. Reset to verify idempotency.
5. Models + re-export. Pure-Python guard test.
6. **Smallest end-to-end slice**: `shallow` runner that only emits `time` + `cyclic` + `missing_required` findings. Synchronous (await directly, no BackgroundTasks yet). One integration test that proves a contrived itinerary produces the expected findings.
7. Move the runner into `BackgroundTasks`. Add the lifespan reaper. Test: kill the test runner mid-flight (use `asyncio.sleep` mock that raises `asyncio.CancelledError`); reaper marks the row `failed`.
8. Add `standard` runner — drive times from haversine, party constraint walk, calls into the new integration client modules.
9. Add `deep` runner — pending the routes-stub addition.
10. Wire the agent prompt + tools.
11. Run a Japan-itinerary integration test: instantiate Japan template via the Phase 4 demo endpoint, run a `standard` analysis, expect 0 `block` findings (the trip is a known-good real itinerary) but ≥ 1 `info` finding (weather day-by-day).
12. `supabase db reset && uv run pytest -q` from `apps/api/`. Must be green.

---

## 12. Verify, don't assume

- [ ] Whether `BackgroundTasks` actually runs after the response in your uvicorn config. There are configs (e.g. middleware that blocks until tasks complete) that change the timing. Add a test that asserts the response returns before the runner starts (use a barrier).
- [ ] Whether `agent_internal` already has tooling for "long-running tool call" — if yes, the agent integration is one config change; if not, an explicit poll loop is needed.
- [ ] How `apps/api/app/db.py:get_sessionmaker()` behaves when called from a `BackgroundTask`. The lru_cache should make it process-wide; verify there's no per-loop binding subtlety with asyncpg.
- [ ] Whether the existing `_check_lock` in [`services/itineraries.py`](../apps/api/app/services/itineraries.py) needs to interact with analyses — it doesn't today (analyses don't mutate the graph), but a future "auto-fix" feature would.
- [ ] The actual Bedrock AgentCore tool-call shape. The recommended tool surface (`start_analysis`, `get_analysis`, …) needs to match whatever the agent runtime expects.

---

## 13. Reference reads, in priority order

1. [TravelGraph_Analysis.md](../../japan-itin/TravelGraph_Analysis.md) §8 (async Analyze). Read the example flow paragraph carefully — that's the thing the schema exists to enable.
2. [phase6_fill_handoff.md](phase6_fill_handoff.md) §3 (Phase 5 sketch) and §9 (existing integration-stub seam). Phase 6 will consume what Phase 5 produces.
3. [`apps/api/app/services/timeline.py`](../apps/api/app/services/timeline.py) — the cleanest service in the codebase; mirror its raw-SQL + dataclass shape.
4. [`apps/api/app/services/templates.py:instantiate_template`](../apps/api/app/services/templates.py) — closest analogue to a multi-step service operation; useful for the runner's transition pattern.
5. [`apps/api/app/main.py:lifespan`](../apps/api/app/main.py) — where the reaper hooks in.
6. [`apps/api/app/routers/integrations/`](../apps/api/app/routers/integrations/) — what to refactor in step (3) of the checklist.
