# Phase 6 (Fill) — Implementation Handoff

Read this before writing any Phase 6 code. It assumes you've read
[TravelGraph_Analysis.md](../../japan-itin/TravelGraph_Analysis.md) and
[Cards_Style_Guide.md](../apps/agent/src/agent/ai/Cards_Style_Guide.md).

---

## 1. State of the world

**Branch:** `feat/travelgraph-schema-spine` (off `main`).
**Tip commit:** `c342c67` — Phase 4 (card templates + Japan demo + integration stubs).
**Test count:** 376 passing (was 326 on `main`).
**DB:** local Supabase Postgres on `127.0.0.1:54322` with PostGIS + the four TravelGraph migrations applied (`0014` schema spine, `0015` card templates).

### What's done — phases 1-4

| # | Commit | Phase | Files of interest |
|---|---|---|---|
| 1 | `2a800c1` | Schema spine | [`supabase/migrations/0014_travelgraph_schema_spine.sql`](../supabase/migrations/0014_travelgraph_schema_spine.sql), [`apps/api/app/models/itinerary.py`](../apps/api/app/models/itinerary.py), [`apps/api/app/models/party.py`](../apps/api/app/models/party.py) |
| 2 | `ea2d037` | Card attrs | [`apps/api/app/schemas/card_attrs.py`](../apps/api/app/schemas/card_attrs.py), [`apps/api/app/seed_data/japan_itinerary.py`](../apps/api/app/seed_data/japan_itinerary.py) |
| 3 | `0eae4f4` | Linearize | [`apps/api/app/services/timeline.py`](../apps/api/app/services/timeline.py) |
| 4 | `c342c67` | Card templates + Japan demo + integration stubs | [`supabase/migrations/0015_card_templates.sql`](../supabase/migrations/0015_card_templates.sql), [`apps/api/app/services/templates.py`](../apps/api/app/services/templates.py), [`apps/api/app/services/japan_template.py`](../apps/api/app/services/japan_template.py), [`apps/api/app/routers/demos.py`](../apps/api/app/routers/demos.py), [`apps/api/app/routers/integrations/`](../apps/api/app/routers/integrations/) |

### What's NOT done — phases 5 / 6 / 7 / 8

- **Phase 5 — Async Analyze**. **Required before Phase 6.** No `analyses` table, no findings, no endpoints.
- **Phase 6 — Fill**. The subject of this doc.
- **Phase 7 — Status-aware mutation gates** + agent-readable `lock_reason`. The lock check in [`services/itineraries.py`](../apps/api/app/services/itineraries.py) only enforces the editor lock; status-driven gates are TODO.
- **Phase 8 — Meld / Extract** UI ops on the parties model.

### What sits dormant in the schema (Phase 1) but isn't wired

- `nodes.location` / `nodes.route` PostGIS columns exist but **the SQLAlchemy ORM doesn't map them** — no `geoalchemy2` dep yet. Read/write via raw SQL with `ST_X(location)` etc. or add the dep.
- `nodes.is_selected_alt` defaults `true`. Nothing flips it yet — Phase 6 / 8 will care.
- `parties` / `travelers` / `node_parties` tables exist but no service uses them. Linearization respects the "no rows = all parties" default.
- `nodes.attached_to_node_id` + the notes-XOR check work; linearization nests attached notes already.

---

## 2. Conventions already established — follow them

Breaking these in Phase 6 is the fastest way to surface in code review.

### Migrations

- One migration per slice, numbered sequentially: `0016_*.sql` is next.
- Idempotent idiom (`do $$ begin if not exists ... end$$`, `add value if not exists`, `create table if not exists`) — see `0014` and `0011` for reference.
- RLS posture: `enable row level security` + zero policies → service_role only.
- Indexes carry partial WHERE clauses where there's a hot-path filter (e.g. `where role is not null`).

### SQLAlchemy ORM

- All Postgres enum bindings are `create_type=False` — the migration owns DDL (D003).
- Models live under `apps/api/app/models/`; re-exported through `app/models/__init__.py` with `noqa: F401` and a sorted `__all__`.
- Mapped column type annotations use `Mapped[...]`; `nullable` is explicit; `server_default=text("...")` for DB defaults.
- Geometry / `tstzrange` columns: avoid mapping in the ORM until `geoalchemy2` lands. Use raw SQL with explicit casts (see below).

### Async + asyncpg type inference

asyncpg can't infer parameter types when bind values are `None`. Use explicit casts in raw SQL:

```sql
case when cast(:t_from as timestamptz) is null and cast(:t_to as timestamptz) is null
     then null
     else tstzrange(cast(:t_from as timestamptz), cast(:t_to as timestamptz), '[)') end
```

`UUID`, `boolean`, enum casts follow the same pattern. See [`apps/api/app/services/timeline.py`](../apps/api/app/services/timeline.py) for the canonical example.

### Service layer

- Every async service module exposes typed dataclasses for results, never raw dicts. See `ItineraryOutcome` / `ActorContext` / `Card` / `TimelineView`.
- A service function never raises for expected outcomes — it returns a discriminated result the router maps to HTTP. Existing pattern: `Type | ItineraryError`.
- Mutations write history rows in the same session as the change (services/itineraries.py). Templates *don't* — they snapshot via `template_*` columns instead. Phase 6 should write history if it mutates the graph.
- One `await session.commit()` per logical operation; no half-states.

### FastAPI routers

- Router prefixes mirror the entity (`/itinerary`, `/clients`, `/demos`, `/integrations/google-places`). New router under [`apps/api/app/routers/`](../apps/api/app/routers/) and add `app.include_router(...)` in [`apps/api/app/main.py`](../apps/api/app/main.py).
- Auth: `require_user` for any authenticated route; `require_advisor` for advisor-gated. JWT middleware is already wrapping every non-whitelisted path.
- Request models: `ConfigDict(extra="forbid")` so a typo surfaces as 422 instead of a silent ignore.
- Response models: typed `BaseModel` so the OpenAPI schema is precise — the api-client generator depends on that.

### Pydantic schemas

- Discriminated unions over `kind: Literal["..."]` matching the underlying enum value verbatim. See `CardAttributes`.
- All sub-types live in the same module so the union resolution is local; cross-module discriminators get fragile.
- Use `TypeAdapter(...)` once at module top, reuse for every parse.

### Tests

- Pure-Python guards live alongside integration tests in the same file under section banners. The integration tests are skipped if local Supabase isn't running:

```python
def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try: s.connect(("127.0.0.1", 54322))
        except OSError: return False
        return True

integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)
```

- For tests mixing sync `TestClient` with async DB setup/teardown, use the `_run_async(coro_factory)` helper from [`tests/test_japan_template.py`](../apps/api/tests/test_japan_template.py). Each call creates + disposes its own engine inside one `asyncio.run` so cleanup doesn't trip a closed event loop.
- Test fixtures and seed data: production-shaped data lives under `apps/api/app/seed_data/`. Tests import from there. Don't reverse the dependency.
- Always run `supabase db reset` once before claiming a slice is done — proves migrations are idempotent. Then `uv run pytest -q` from `apps/api/`.

### Naming

- Service modules: lowercase, plural noun for CRUD-ish (`itineraries`, `templates`); singular verb for read services (`timeline`).
- Schema modules: noun (`card_attrs`, `clients`, `agent`).
- Migration files: `NNNN_short_kebab.sql`. The slug becomes the implicit topic for the slice.

---

## 3. Phase 5 — async Analyze (PREREQUISITE)

Phase 6 (Fill) consumes Analyze findings. **Build Phase 5 first.** Don't try to inline a synchronous analyzer into Fill — the analysis-doc explicitly resolved this:

> "Analyze is **not** a synchronous service-layer hook. It's an on-demand, long-running, agent-aware operation that can call out to external systems (Google Maps real-time traffic, weather, flight status, currency) without blocking the request path. Its own state machine."

### Phase 5 schema sketch

```sql
-- 0016_async_analyze.sql

create type public.analysis_status as enum (
  'queued','running','completed','failed','cancelled'
);

create type public.analysis_depth as enum ('shallow','standard','deep');

create type public.finding_severity as enum (
  'info','suggest','warn','block'
);

create table public.analyses (
  id              uuid primary key default gen_random_uuid(),
  itinerary_id    uuid not null references public.itineraries (id) on delete cascade,
  status          public.analysis_status not null default 'queued',
  depth           public.analysis_depth not null default 'standard',
  scope           jsonb not null default '{}'::jsonb,
   -- { node_ids?, time_window?: {from, to}, party_id?, branches: 'selected_only'|'all' }
  requested_by    uuid references auth.users (id) on delete set null,
  requested_kind  text not null,  -- 'user' | 'advisor' | 'agent' | 'system'
  started_at      timestamptz,
  completed_at    timestamptz,
  inputs_hash     text,           -- hash of (nodes + edges + party + window) at start
  result          jsonb,          -- structured findings + summary
  summary         text,           -- agent-readable narrative
  external_calls  jsonb not null default '[]'::jsonb,
  error_detail    text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.analysis_findings (
  id              uuid primary key default gen_random_uuid(),
  analysis_id     uuid not null references public.analyses (id) on delete cascade,
  node_id         uuid references public.nodes (id) on delete set null,
   -- null = whole-itinerary finding
  severity        public.finding_severity not null,
  category        text not null,
   -- 'time' | 'location_flux' | 'availability' | 'party' |
   -- 'weather' | 'traffic' | 'cost' | ...
  message         text not null,
  evidence        jsonb not null default '{}'::jsonb,
  suggested_fix   jsonb,          -- shape compatible with Fill's FillProposal
  created_at      timestamptz not null default now()
);

create index analyses_itinerary_idx on public.analyses (itinerary_id);
create index analyses_status_idx    on public.analyses (status)
  where status in ('queued','running');
create index analysis_findings_analysis_idx
  on public.analysis_findings (analysis_id);
create index analysis_findings_node_idx
  on public.analysis_findings (node_id) where node_id is not null;

alter table public.analyses          enable row level security;
alter table public.analysis_findings enable row level security;
```

### Phase 5 endpoints

- `POST /itinerary/{id}/analyze` body `{ depth?: 'shallow'|'standard'|'deep', scope?: {...} }` → returns `{ analysis_id, status }`. Inserts a `queued` row + spawns a background runner.
- `GET /itinerary/{id}/analyses/{analysis_id}` → poll status + result + findings.
- `GET /itinerary/{id}/analyses?limit=20` → list, most recent first.
- `POST /itinerary/{id}/analyses/{analysis_id}/cancel` → best-effort cancel.

### Background-task runner — pick one

The big open decision for Phase 5. Three options, ranked by cost:

1. **FastAPI `BackgroundTasks`** — runs in-process. Fine for dev / staging. Doesn't survive restarts; long-running tasks block the worker. **Pick this for the first cut.**
2. **`asyncio.create_task` + a process-local supervisor** that recovers `running` rows on startup (mark them `failed`). Slightly more robust; same single-process limit.
3. **Real worker** (Celery / ARQ / RQ / Postgres-LISTEN). Production-grade. Over-engineered for now.

Recommendation: option 1, with these guarantees:
- On startup, mark any `running` analyses older than ~10min as `failed` with `error_detail='abandoned_at_restart'`. (lifespan hook in `app.main`.)
- `BackgroundTasks` runner uses its own DB session, not the request's.
- Cap concurrent runs per itinerary at 1 — second `POST /analyze` while one is `running` returns the existing one with 409 (or a clearly-marked queued row).

### Phase 5 depth tiers (from the analysis doc resolved-decisions section)

- **Shallow** (early planning, lots of fuzz): structural checks only — type/role consistency, missing required fields, gross time/location impossibility. **No external API calls.** LLM does interpretation from `result.summary`.
- **Standard** (firmed-up dates, mostly-selected branches): adds tstzrange overlap, location-flux per mode, party constraints, inventory + weather lookups.
- **Deep** (pre-trip, all confirmed): real-time traffic, flight status, currency, every selected node validated against live providers.

Depth is recorded so a `shallow` finding doesn't get treated like a `deep` one.

### Phase 5 finding categories — what to emit

| Category | Trigger | Evidence shape |
|---|---|---|
| `time` | `tstzrange &&` overlap on same party | `{ overlapping_node_id, overlap_minutes }` |
| `location_flux` | `Δkm / Δt > speed_cap[mode]` | `{ from_node_id, to_node_id, distance_km, available_min, mode }` |
| `availability` | node `starts_at` outside venue hours | `{ venue_open_at, venue_close_at }` |
| `party` | age/mobility/allergen mismatch | `{ traveler_id, restriction }` |
| `weather` (deep) | weather forecast vs. activity type | `{ condition, contingency_in_attrs }` |
| `traffic` (deep) | live drive time > buffered offset | `{ live_minutes, scheduled_minutes }` |
| `cost` (deep) | currency conversion drift, etc. | `{ ... }` |

### Phase 5 testing

- Unit: a `shallow` analysis on a contrived itinerary with one overlap produces exactly one `time` finding.
- Integration: real Postgres, full lifecycle queued → running → completed.
- The runner gets its own session and commits as it goes — recovery test asserts a killed runner leaves a `running` row that the lifespan hook reaps to `failed`.

### Phase 5 testing helpers worth writing

- `await_analysis_completion(session, analysis_id, timeout_seconds=10)` for tests that need to wait.
- A "fast-forward" depth knob in tests so `standard` doesn't actually call the integration stubs (or have stubs return immediately).

---

## 4. Phase 6 — Fill design

Fill takes a gap in an itinerary and proposes physically-feasible candidates from inventory, scoped by a party's constraints, anchored in Phase 5's analysis output.

### Inputs

```python
@dataclass(frozen=True, slots=True)
class GapWindow:
    start: datetime  # tz-aware
    end: datetime

async def fill_gap(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    gap: GapWindow,
    party_id: uuid.UUID | None = None,
    analysis_id: uuid.UUID | None = None,
    desired_kinds: list[NodeType] | None = None,
    min_score: float = 0.5,
    max_proposals: int = 8,
) -> list[FillProposal]:
```

- `analysis_id` defaults to **the latest `completed` analysis for this itinerary**. If none exists, return a single `FillProposal` with `feasibility_unknown=True` rather than refusing — the agent can ask the user "want me to run an analysis first?".
- `desired_kinds` lets a caller scope (e.g. "fill this with meals only").
- `party_id` filters inventory by the party's traveler constraints.

### Output

```python
@dataclass(frozen=True, slots=True)
class FillProposal:
    inventory_source: str          # 'ov' | 'mock' | 'google_places' | ...
    inventory_id: str
    title: str
    type: NodeType
    starts_at: datetime
    ends_at: datetime
    location: GeoPoint
    score: float                   # [0, 1]
    fits_in_gap: bool
    drive_time_in_min: int | None
    drive_time_out_min: int | None
    party_ok: bool
    constraint_warnings: list[str]
    rationale: str                 # human-readable why-this-was-suggested
    raw: dict[str, Any]            # provider payload, used for snapshot creation
```

### Algorithm

1. **Resolve bracketing nodes.** Use [`linearize`](../apps/api/app/services/timeline.py) over the `[gap.start - 4h, gap.end + 4h]` window for `party_id` to find the immediately-prior and immediately-next selected cards.
2. **Compute the geo envelope.** Drive time from prior + buffer must leave room for the candidate's duration before next.start. Use `analysis.result.drive_times` if `deep`; fall back to haversine × mode-speed-cap if `shallow`.
3. **Query inventory.** Existing registry at [`apps/api/app/inventory/registry.py`](../apps/api/app/inventory/registry.py). Add a `search_nearby(lat, lng, radius_m, types, time_window) -> list[Candidate]` method to the provider interface; have the OV provider hit the public OV API and the mock provider serve fixture data.
4. **Filter by party.** Pull `travelers.profile_attrs` for `party_id`'s travelers; drop any candidate whose attrs hit a hard restriction (allergen, age, mobility).
5. **Score.** Weighted: gap utilization (closer-to-full ≥ better up to a buffer), distance from bracketing nodes (closer ≥ better), party fit (no warnings ≥ better), energy budget alignment (uses `analysis.result.party_energy_budget`).
6. **Sort + truncate.** Drop below `min_score`. Cap at `max_proposals`.

### Phase 6 endpoint

```
POST /itinerary/{itinerary_id}/fill
```

Body:

```json
{
  "gap": { "start": "...", "end": "..." },
  "party_id": "uuid?",
  "analysis_id": "uuid?",
  "desired_kinds": ["meal", "experience"],
  "min_score": 0.6,
  "max_proposals": 5
}
```

Response: `{ proposals: list[FillProposal], analysis_id: uuid, analysis_age_seconds: int }`.

Auth: `require_user`. Both advisor and the itinerary's owning client should be able to call.

### Phase 6 — physical feasibility envelope

The analysis-doc was emphatic on this: **Fill must NOT suggest physically-impossible options.** Concretely, a Fill candidate is rejected if:

- Drive time from prior node + candidate duration + drive time to next node > gap duration. With a default buffer of `15 min` per transit edge.
- Mode-speed cap applies — driving in metro Tokyo isn't 100km/h. Use a per-mode lookup the analyzer fills in.
- If `analysis.depth >= 'deep'`, the live traffic time replaces the haversine estimate.
- If neither analysis nor live traffic is available, *still emit candidates* but mark `fits_in_gap: false` and `drive_time_in_min: None`. Don't silently lie.

### Phase 6 — when to write to the graph

`POST /fill` is **read-only**. Returning a proposal doesn't mutate anything. Accepting a proposal is a separate route (or just the existing `POST /itinerary/{id}/nodes`). That gives the UI room for "show me 5 options" → "pin #3" without bookkeeping ambiguity.

### Phase 6 — interaction with status gates (Phase 7, not yet built)

Fill should not propose changes that would require demoting a `booked` or `confirmed` neighbor. If gap-bracketing nodes are `booked`/`confirmed` the proposals must respect their fixed times. A demote-and-reposition is out of Fill's scope — that's the agent + advisor's call.

### Phase 6 testing

- Empty gap → empty proposals list (not 404).
- Gap larger than the inventory radius → empty.
- Gap with no analysis → returns proposals with `feasibility_unknown` warnings.
- Gap with a `block`-severity finding from latest analysis (e.g. weather closure) → those candidate types are excluded.
- Party with a tree-nut allergy → meals carrying tree-nut allergen are dropped.
- Drive-time impossibility → candidate excluded (or marked).
- Real-trip Japan integration test: pick a 3h gap on day 3, expect non-empty list of plausible meal/experience candidates.

---

## 5. Open decisions before you code

| Question | Recommended default | Why open |
|---|---|---|
| Background-task runner for Phase 5 | `BackgroundTasks` + lifespan reaper | Easy to reverse if we hit limits |
| Auto-run analysis from Fill if none exists | No — return `feasibility_unknown` proposals | Avoids mystery long-poll |
| Fill cache | None for now | Premature; analysis_id pinning is enough |
| Live traffic provider | Stub at `/integrations/google-places/route` (extend the stub) | Phase 4 only stubbed `places`/`weather`/`flight-status` — `route` is missing and Phase 6 wants drive time |
| Mode-speed caps | Constants in `app/services/fill.py`: walk=5, drive=25 (city) / 80 (highway), train=80, etc. | Easy to tune later |
| Gap buffer minutes | 15 min default per side | UX comfort, can tighten with real data |
| Inventory provider extension shape | `search_nearby(...)` on `InventoryProvider` interface | Keeps the registry pattern; both `ov` and `mock` implement |
| `min_score` default | 0.5 | Coarse for now |

---

## 6. Files you'll add / touch in Phase 6

### New
- `supabase/migrations/0016_async_analyze.sql` (Phase 5 prereq)
- `apps/api/app/models/analysis.py`
- `apps/api/app/services/analyze.py` (Phase 5 prereq)
- `apps/api/app/services/fill.py`
- `apps/api/app/routers/analyze.py` (Phase 5 prereq)
- `apps/api/app/routers/fill.py`
- `apps/api/app/routers/integrations/google_routes.py` (or extend `google_places.py`)
- `apps/api/tests/test_analyze_service.py`
- `apps/api/tests/test_analyze_router.py`
- `apps/api/tests/test_fill_service.py`
- `apps/api/tests/test_fill_router.py`

### Touch
- `apps/api/app/main.py` — `include_router` for the new routers + lifespan reaper for `running` analyses.
- `apps/api/app/models/__init__.py` — re-export new models.
- `apps/api/app/inventory/__init__.py` — extend `InventoryProvider` with `search_nearby`.
- `apps/api/app/inventory/providers/{ov,mock}.py` — implement `search_nearby`.
- `packages/api-client/` — regenerate after the API schema changes (`pnpm -C packages/api-client generate`).

### Don't touch (out of scope for Phase 6)
- Frontend prototypes (rendering Fill proposals is a follow-up).
- Status-gate enforcement (Phase 7).
- Meld / Extract (Phase 8).

---

## 7. First-day checklist

Build top-down so you can iterate against tests:

1. Read the four existing service modules end-to-end ([itineraries](../apps/api/app/services/itineraries.py), [timeline](../apps/api/app/services/timeline.py), [templates](../apps/api/app/services/templates.py), [japan_template](../apps/api/app/services/japan_template.py)). Understand the dataclass-result + `_check_lock` patterns.
2. Read [`Cards_Style_Guide.md §Composition`](../apps/agent/src/agent/ai/Cards_Style_Guide.md) for the alternative-branch rule that Fill must respect.
3. Skim the `analyses` schema sketch above; write the migration; apply + reset.
4. Build Phase 5 schema + the simplest possible runner (synchronous `shallow`, no external calls, no background — just to wire the pipe). Get one failing-then-passing test.
5. Add `BackgroundTasks` + the lifespan reaper. Test: kill the test runner mid-flight and confirm the reaper marks the row `failed`.
6. Build Phase 6 over Phase 5. Start with `feasibility_unknown` proposals (no analysis required) and add real feasibility once the analyzer is producing findings.
7. Real-trip integration test against the Japan instantiation: 3h gap on day 3 → at least 2 non-empty proposals.
8. `supabase db reset && uv run pytest -q` — must be green before declaring done.

---

## 8. Things to verify, not assume

- [ ] The `nodes.location` PostGIS column. Phase 6 wants spatial queries but the ORM doesn't surface it. Either (a) raw SQL with `ST_DWithin`, (b) finally add `geoalchemy2`. Decide before you start filtering inventory.
- [ ] The `inventory/registry.py` interface signature. The `OVProvider` may already have a search-style method I haven't catalogued.
- [ ] Whether `tests/test_japan_template.py::test_demos_japan_happy_path_creates_itinerary` is flaky on cold-start (it does a lot in one test). If yes, split before adding more.
- [ ] Whether `apps/web` already shows Fill-style proposals in any prototype that should be wired up afterward.
- [ ] The Supabase production project's migration history — `0014` and `0015` haven't been applied to staging or prod yet. Phase 5/6 land on top of them, so they all migrate in one window.

---

## 9. Existing seam — integration stubs

Phase 4 stubbed the providers Phase 5/6 will call. Don't re-stub:

- `POST /integrations/google-places/search` → place lookup
- `GET /integrations/google-places/details/{place_id}` → photos, hours
- `GET /integrations/weather/forecast?lat&lng&date` → deterministic stub by lat/lng/date hash
- `GET /integrations/flight-status/{code}?date` → canned for `DL275`/`DL276`

**Missing for Phase 6:** a `routes` / drive-time endpoint. Add it with the same stub pattern:

```
GET /integrations/google-places/route?from_lat=&from_lng=&to_lat=&to_lng=&mode=
```

Returns `{ distance_km, duration_min, mode, polyline? }` shaped like Google Routes. Stub by haversine × mode-speed-cap; live integration is a future slice.

---

## 10. Reference reads, in priority order

1. [TravelGraph_Analysis.md](../../japan-itin/TravelGraph_Analysis.md) §7 (linearize), §8 (analyze), §9 (fill), §11 (status gates), and the §"Resolved design decisions" block.
2. [Cards_Style_Guide.md](../apps/agent/src/agent/ai/Cards_Style_Guide.md) §Status transitions and §Composition.
3. [`apps/api/app/services/timeline.py`](../apps/api/app/services/timeline.py) — the cleanest async-DB service in the codebase; mirror its shape.
4. [`apps/api/tests/test_japan_template.py`](../apps/api/tests/test_japan_template.py) — `_run_async` pattern for any test that mixes sync TestClient + async DB setup.
5. [`supabase/migrations/0014_travelgraph_schema_spine.sql`](../supabase/migrations/0014_travelgraph_schema_spine.sql) — the migration style guide-by-example.
