# TravelGraph — Gap Analysis vs. Current `ov-black` Schema

Source notes: [Itinerary_Planning_System.md](./Itinerary_Planning_System.md)
Card design canon: `ov-black/apps/agent/src/agent/ai/Cards_Style_Guide.md` and `apps/web/app/prototype/cards/`
Codebase analyzed: `~/personal/ov-black` (commit `d940297`, 2026-04-25)

---

## Side-by-side: notes vs. what's in the DB

| Notes / design concept | Current state | Gap |
|---|---|---|
| Vertex types: Activity, Travel, Waiting, Lodging, Eating + Terminus/Destination as **graph-structural markers** for subgraph endpoints/anchors | `node_type`: destination, flight, hotel, experience, meal, transit, free_time, note | **Missing**: `waiting`, `terminus`. **Conflated**: Cards prototype distinguishes `subway` / `train` / `drive` / `walk` / `boat` as separate types because each has a unique signature detail; today they all collapse to `transit`. |
| Mandatory: start/end time (ranges), location (lat/lng/alt), type | All three live in `metadata jsonb` (verticalStore reads `metadata.start_time`, `metadata.duration_minutes`, `metadata.location`) | **No first-class temporal/spatial columns.** Can't enforce, can't index, can't do range/overlap queries. |
| Per-type rich attributes (jet-lag protocol, walking-from-door minutes, signage gloss, line color, dietary file, energy meter, best-window strip, surface warnings, motion-sickness rating, "what's next" pointer, …) — see Cards Style Guide | Loose `metadata jsonb` with no per-type schema | **No discriminated per-type schema.** Every renderer guesses. The cards prototype is the schema target — the DB has to capture enough to feed every signature detail. |
| Intrinsic vs. layered attributes | Only `source`/`source_id` (provenance pointer) | **No template registry.** Every node is fully instantiated; nothing intrinsic stored once and reused. |
| Linking, Melding, Extracting, Analyzing, Filling | `assemble_initial_draft` (linking only); `parent_subgraph_id` (self-FK for nesting) | **Meld, Extract, Analyze, Fill don't exist.** No party model, no validations engine, no inventory in-fill. |
| Per-party timelines | `itineraries.client_id` only | **No parties/travelers concept** at all. |
| Branching vertices | `edge_type='alternative_to'` | Exists, but **no "selected alternative" flag**, so linearization can't tell which branch is active. |
| Reusable subgraphs / card library | `parent_subgraph_id` is itinerary-scoped (NOT NULL `itinerary_id`) | **Subgraphs are not portable.** No `card_templates` table, no copy-into-itinerary op. |
| Card linearization (per-party walk between T1/T2) | Frontend re-implements per-prototype (vertical/horizontal) | **No server-side linearization service.** Each surface re-derives ordering. |
| Card deck ops (Duplicate, Edit, Archive) | None — cards are render-only | No store of named subgraphs to manage. |
| Notes as both attached and free-standing | `node_type='note'` exists but no `attached_to_node_id`; participates in the timeline like any other node | **Dual-mode notes don't exist.** A free-standing note has its own time anchor; an attached note rides on a host node and inherits its anchor. |
| Status-aware locking (booked/approved are constrained, not freely editable) | Only an `itineraries.locked_by` editor-session lock — no per-node status gate | **No status mutation gates.** A `booked` node can be re-titled by anyone holding the editor lock. |
| Mobile day view, prep video, fatigue tracker | None | Blocked on missing temporal/spatial columns + linearization service. |

---

## What needs to change

### 1. Promote start/end/location to first-class columns

Migration `0002_itinerary_graph.sql` puts these in `metadata jsonb`. Move them out:

```sql
nodes.starts_at  tstzrange  -- range, not point — your "possible ranges?" note
nodes.location   geography(Point, 4326)
nodes.route      geography(LineString, 4326)  -- for trails / Shinkansen leg
nodes.altitude_m integer
```

- `tstzrange` makes overlap detection (`&&`) free for the Analyze pass.
- PostGIS `geography` lets the Map view do spatial queries without parsing JSON, and powers physical-feasibility checks for Fill (haversine + speed cap by mode).
- Keep `metadata jsonb` for the long tail (phrases, items, energy ±) but spec a documented per-type sub-schema (see §3).

### 2. Reconcile the vertex taxonomy

Per your reframe: **Terminus is a subgraph-end marker, Destination is a subgraph-anchor — both are graph-structural, not physical states.** Treat them as a separate axis from physical type.

Proposed taxonomy:

```
node_type (physical-state):
  flight, subway, train, drive, walk, boat,   -- transit modes (split per Card Style Guide)
  hotel, experience, meal, free_time, waiting -- presence states
  note                                         -- annotation (dual-mode, see §10)

node_role (graph-structural, nullable):
  null         -- ordinary node
  'destination' -- subgraph anchor / region container; renders as header strip
  'terminus'    -- subgraph end marker; renders as a join, not as a card
```

This way the timeline renderer can ignore `node_role IS NOT NULL` for linearization and treat them as graph-structural metadata. Subway/train/drive/walk/boat get split because **each card's signature detail differs** (line-color signage gloss vs. window briefing vs. driver continuity vs. surface warning vs. motion-sickness rating). Collapsing them to `transit` loses information the UI needs.

### 3. Per-type structured attributes — schema target = the cards prototype

Every card type in `Cards_Style_Guide.md` has required + optional + omit-when-absent fields. The schema must capture **at least** the union so every signature detail can render. Approach: **discriminated JSONB** — `metadata` validated against a per-`node_type` Pydantic model at the API and service boundary, with the DB CHECK guarding presence of the type discriminator.

Required-field summary, distilled from the prototype:

| Type | Must capture |
|---|---|
| `flight` | iata_from, iata_to, depart_at (TZ), arrive_at (TZ), flight_code, cabin, seat, terminal, gate, lounge_proximity, scenic_side, jet_lag_protocol_text, tz_delta, aircraft, wifi, miles |
| `subway` | from_station, to_station, lines[]: { name, agency_color }, transfers[]: { station, line_color }, duration, fare_or_pass_note, signage_gloss[]: { native, romanization, traveler_lang } |
| `train` | from, to, train_name, train_number, depart_at, arrive_at, platform, car, seat, stops[]: { station, arr, dep }, scenery_callouts[]: { minute, side, what }, pass_eligibility, food_on_board |
| `drive` | from, to, eta, vehicle: { make, capacity, plate, plate_native_script }, driver: { name, photo_url, languages[] }, bag_capacity, route_polyline, contact_link, prior_trip_continuity_flag |
| `walk` | from, to, distance_m, time_min, surface_notes[], pois_along[], route_polyline (optional <500m) |
| `boat` | dock_from, dock_to, depart_window, duration, motion_sickness_rating, bring_with[], schedule_frequency |
| `hotel` | name, location, check_in_window (range), check_out_window (range), room_type, nights, hero_image, neighborhood_blurb, walking_to_next_nodes[]: { node_id, mins, mode }, profile_prefs_honored[], confirmation_number, in_room_amenities[], bedding |
| `experience` | title, location, duration_min, category, hero_image, narrative, energy_required (1-5), energy_after, difficulty, best_window: { start_h, end_h }, gear_list[], weather_contingency, allergens[], age_min, language_support |
| `meal` | title, location, seating_at, duration_min, cuisine_class, dish_image, dress_code, dietary_flags_from_profile[], etiquette[], pre_meal_phrases[]: { native, romanization, gloss }, reservation_number, cancellation_policy |
| `free_time` | title, time_window, location, weather, sunset, sunrise, energy_advice (derived), suggestion_grid[] |
| `waiting` | location, duration_min, whats_next_node_id, lounge_info, use_this_time_to[], facilities[], soft_progress_bar (≥30 min) |
| `note` | body, author: { user_id, name, role }, attached_to_node_id (nullable, see §10), tags[], replies[], visibility |

This is the schema's **functional spec** — the prototype is the visual canon, the style guide is the rulebook, and the DB has to keep up.

### 4. Card-template / library layer — visual canon = `prototype/cards/`

The card prototype already shows what the deck UI must support: a glance + zoom for every type, with status escalation. Translate to schema:

```sql
card_templates       (id, name, description, region_id, intrinsic_attrs jsonb, version, owner_advisor_id)
template_subgraph    (template_id, node_id, parent_id, type, intrinsic_attrs jsonb, ...)
template_edges       (template_id, from_node_id, to_node_id, type, ...)

nodes.template_id        uuid references card_templates(id)
nodes.template_version   int                      -- snapshot at instantiation
```

- Operators' "deck" = `card_templates`; operations Duplicate / Edit / Archive map to standard CRUD.
- Instantiating a template = copy template_subgraph rows into `nodes`/`edges` with `template_id` and `template_version` set on each new node.
- Layered attributes (travelers, dates) live on `nodes`; intrinsic ones (jet-lag protocol, etiquette, signage gloss) live on `card_templates.intrinsic_attrs`.
- Smart Suggestions / Sort / Group / Filter operate over the template registry.

### 5. Add a parties/travelers model

```sql
parties           (id, itinerary_id, label, member_count, attrs jsonb)
node_parties      (node_id, party_id)        -- many-to-many
travelers         (id, party_id, name, age, profile_attrs jsonb)
```

- Default: every node belongs to a synthetic "all" party.
- Meld = UI op surfacing where two parties share the same node id vs. diverge.
- Extract = `select … where node_parties.party_id = $1`.
- Per-traveler `profile_attrs` (fitness, dietary, allergies, age) modulates intrinsic energy ± and feeds the proactive agent suggestions in §8.

### 6. Mark the active branch among alternatives (without hiding the others)

Add `nodes.is_selected_alt boolean` (default `true` for non-alternative nodes). The renderer **continues to show all branches** — alternatives are part of the UX, dimmed/grouped per the Cards Style Guide §Composition — but downstream consumers (Analyze, Fill, fatigue / packing folds, agent reasoning) treat the **selected** branch as "the plan." Without the flag those folds would either pick arbitrarily or double-count.

The flag flips when the traveler/advisor commits to a branch; analyses are scoped by it but the timeline keeps rendering siblings.

### 7. Build a server-side linearization service

A new `app/services/timeline.py`:

```python
def linearize(itinerary_id, party_id, t_from, t_to) -> list[Card]
```

Walks `follows` (and selected `alternative_to`), filters by party, returns ordered cards. Every analysis the notes mention (packing list, vocabulary, exertion, map polyline) is a fold over this list. **Both prototypes today derive ordering client-side**, which means each surface drifts. Linearization also enforces status-aware visibility and feeds the agent's situational awareness.

### 8. Async on-demand Analyze service

**Reframe**: Analyze is **not** a synchronous service-layer hook. It's an on-demand, long-running, agent-aware operation that can call out to external systems (Google Maps real-time traffic, weather, flight status, currency) without blocking the request path. Its own state machine.

```sql
analyses (
  id              uuid pk,
  itinerary_id    uuid fk,
  status          analysis_status,     -- queued | running | completed | failed | cancelled
  requested_by    uuid,                -- user / advisor / agent
  started_at      timestamptz,
  completed_at    timestamptz,
  inputs          jsonb,               -- snapshot of itinerary nodes/edges hash + scope
  result          jsonb,               -- structured findings
  summary         text,                -- agent-readable narrative
  external_calls  jsonb                -- audit of which APIs were touched
);

analysis_findings (
  id              uuid pk,
  analysis_id     uuid fk,
  node_id         uuid,                -- nullable; null = whole-itinerary finding
  severity        text,                -- info | suggest | warn | block
  category        text,                -- time | location_flux | availability | party | weather | traffic | cost
  message         text,
  evidence        jsonb,               -- e.g. { drive_minutes_realtime: 198, distance_km: 250 }
  suggested_fix   jsonb                -- optional: a Fill proposal payload
);
```

**Endpoints**:

- `POST /itinerary/{id}/analyze` — start; returns `{ analysis_id, status }`.
- `GET /itinerary/{id}/analyses/{analysis_id}` — poll status + result.
- `GET /itinerary/{id}/analyses` — list (most recent first).
- `POST /itinerary/{id}/analyses/{analysis_id}/cancel` — best-effort cancel.

**Why on-demand + async**:

- You don't yet know whether to run on every commit or by hand — async lets you defer that decision.
- External APIs (Google Maps, weather) take seconds and have rate limits — wrong fit for the request path.
- The agent treats analyses as **first-class context**: it can list pending/recent analyses, kick off a new one when the graph changes meaningfully, and reason over `result + summary` to answer questions and proactively flag issues.
- Example flow the schema needs to enable:
  > "I noticed you're landing at 10pm in Austin, but real-time drive to Houston is 3h 40m given current traffic. You'll have the kids — I suggest a hotel in Austin tonight. Since it's late, a no-pool hotel saves money — the kids will be too tired to swim."
  This requires `analysis_findings` rows with `evidence.drive_minutes_realtime`, party context (kids), and a `suggested_fix` that Fill can pick up.

**Graduated thoroughness — avoid combinatoric explosion**:

The analyzer must know when **not** to be thorough. An itinerary that's 80% fuzzy ranges and unselected alternatives shouldn't trigger a deep search across every (range × alternative × party) combination. Approach:

```
analyses.depth   text  -- 'shallow' | 'standard' | 'deep'
analyses.scope   jsonb -- { node_ids, time_window, party_id, branches: 'selected_only' | 'all' }
```

- **Shallow** (early planning, lots of fuzz): structural checks only — type/role consistency, missing required fields, grossly impossible time/location pairs. Defer real-time API calls. The LLM does the heavy lifting interpretively from `result.summary`.
- **Standard** (firmed-up dates, mostly selected branches): adds `tstzrange` overlap, location-flux per mode, party constraints. Touches inventory + weather. Runs over selected branch only by default.
- **Deep** (pre-trip, all confirmed): real-time traffic, flight status, currency, every selected node validated against live provider data.

Selection of depth is explicit — the agent or advisor picks it when starting the analysis. The schema records what depth ran so a `shallow` finding doesn't get treated like a `deep` one. This also keeps cost/latency predictable.

### 9. Build a Fill operation tied to Analyze output

Fill must be **anchored in physical reality** — not just "find a hotel near here." A high-quality Fill consumes the latest `completed` analysis and refuses suggestions that violate its feasibility envelope.

```python
def fill_gap(itinerary_id, gap: TimeRange, party_id, analysis_id) -> list[FillProposal]:
    """Suggest only options that are physically possible given the analysis."""
```

Constraints:

- Drive-time + distance + buffer must fit `gap.duration` per real-time data in `analysis.result`.
- Inventory provider hits filter by geo-radius from gap endpoints (`location` column from §1).
- Party constraints (age, allergies, mobility from §5) filter inventory before scoring.
- Returns ranked `FillProposal` objects that include rationale ("fits in 2h gap, 18 min drive, kid-friendly menu").

The advisor / traveler approves; approved proposals become `proposed` nodes in the graph.

### 10. Notes as dual-mode — attached or free-standing

Per your feedback, a note can be either:

- **Attached**: `attached_to_node_id` non-null. No own time anchor; rides the host node's `starts_at`. Renders inline with that card.
- **Free-standing**: `attached_to_node_id` null. Has its own `starts_at` (range or point). Renders as a stand-alone item in the timeline at that moment.

Schema:

```sql
nodes.attached_to_node_id uuid references nodes(id) on delete cascade
-- check constraint: applies only when type='note'
constraint notes_anchored_or_attached check (
  type <> 'note'
  or (attached_to_node_id is null) <> (starts_at is null)
)
```

The XOR keeps free-standing notes anchored in time and keeps attached notes from drifting away from their host.

### 11. Status-aware mutation gates

Today only `itineraries.locked_by` (editor-session lock) gates writes — there's no per-node status gate. Per your rules:

| Status | Traveler can edit? | Agent can edit? | Advisor can edit? |
|---|---|---|---|
| `idea`, `proposed` | yes | yes | yes |
| `approved` | **no — must be demoted to `proposed` first** | no | yes (demote first, then edit) |
| `booked` | **no** | no | yes (demote, with visible note per Style Guide §Status transitions) |
| `confirmed` | no — only via cancellation flow | no | only via cancellation flow |
| `discarded` | restorable to prior status | restorable | restorable |

Implementation: extend `_check_lock` (or add `_check_status_gate`) in [`apps/api/app/services/itineraries.py`](https://github.com/.../apps/api/app/services/itineraries.py) so:

- Updates to `approved`+ nodes by non-advisors return `LOCKED`/`FORBIDDEN` with a specific outcome (`STATUS_LOCKED`).
- Advisor demotion writes a `node_history` row with `actor_kind=advisor` and a flag the UI can render as the "visible note" the Style Guide requires.
- The agent's tool surface inherits this — `update_node` from an agent context refuses `approved`+ silently and emits a finding the agent can surface conversationally ("That hotel is already booked; I'd need an advisor to move it").

---

## Resolved design decisions

(Items here started as open questions; each carries the decision now made.)

### 1. Time ranges are the default, not the exception ✅

`tstzrange` from day one. Points are a degenerate range; firmness arrives by collapse, not by column swap.

### 2. Analysis must avoid combinatoric explosion in fuzzy phases ✅

Captured in §8 as **graduated thoroughness** (`shallow` / `standard` / `deep`). In early planning the LLM does the interpretive work directly; the analyzer stays out of expensive cross-product searches over fuzzy ranges and unselected alternatives. Depth is chosen explicitly when an analysis is started and recorded with the result so callers can weight the findings appropriately.

### 3. Inventory sync — fetch behind the scenes for the traveler ✅

Add `synced_at`, `provider_etag`, drift-detect flag, and a `inventory_stale` lock_reason distinct from `idea/proposed/approved`. Stale inventory triggers a `standard`-depth Analyze re-run. Eventually the agent fetches proactively; the schema needs to support that without a redesign.

### 4. Energy budget is per-traveler, not per-node ✅

Energy ± on the template/node is the **intrinsic** value; the per-traveler modifier lives on `travelers.profile_attrs` (fitness, age, mobility). The fatigue tracker folds intrinsic × modifier across the linearized timeline.

### 5. Three tiers of intrinsic data ✅

Region (`regions.vocabulary`, currency, signage script) → Template (per-card phrases, etiquette, line colors) → Instance (this party, this date). The signage-gloss and metro-line-color rules from the Cards Style Guide naturally fall into the Region tier.

### 6. Card-template versioning by snapshot ✅

`card_templates` is mutable; instantiation copies. `nodes.template_version` snapshots the version at instantiation. A "template updated since you used it" detector triggers an Analyze re-run — never a silent rewrite of an instantiated node.

### 7. Meld produces one merged graph **and** shared sync points ✅

Hybrid: a single merged graph is the source of truth, and per-party timelines are projections (§5 `node_parties`). Where two parties' projections share a node id → they're together; where they don't → parallel tracks with **explicit sync nodes** (terminus/destination roles from §2 are a natural fit) marking where the parties rejoin. The renderer shows shared cards once; divergent cards appear in each party's column.

### 8. Vertex taxonomy follows the Cards prototype ✅

Subway / train / drive / walk / boat are distinct types because each has a unique signature detail. The schema follows `prototype/cards/` and `Cards_Style_Guide.md` rather than collapsing to `transit`. Captured in §2 and §3.

### 9. Terminus + Destination are graph-structural ✅

Both live on the `node_role` axis from §2 — separate from physical type, skipped by linearization, rendered as headers / sync points rather than cards.

### 10. The card library is the moat ✅

Reusable templates are core schema, not a JSONB convention. The cards prototype is the visible 80% of the moat; §4 is the missing back-end half.

### 11. Status-locking is visible to the agent ✅

Per-node `lock_reason` (computed: `status_locked_by_status`, `editor_locked_by_advisor`, `inventory_stale`, `cancellation_window_closed`, …) so the agent can say "That meal is confirmed and the 48-hour cancellation window has closed" instead of "I can't change that."

### 12. "Walked-it" media — deferred 🕒

Captured intent (pictures, videos, stamps, sketches → `node_media` table) but not in the first build. Added to a backlog rather than the spine.

---

## Suggested phasing

1. **Schema spine** — `starts_at tstzrange`, `location`, `route`; `node_role` axis (terminus/destination); split transit modes (subway/train/drive/walk/boat); add `waiting`; add `parties` + `travelers` + `node_parties`; `nodes.is_selected_alt`; dual-mode `nodes.attached_to_node_id` for notes; status-gate columns / `lock_reason`.
2. **Per-type discriminated metadata** — Pydantic models for every node_type, validated at the service boundary; backfill what the cards prototype consumes.
3. **Linearization service** + retire client-side ordering in both prototypes.
4. **Card templates** — separate registry, instantiation op, version snapshot on instances; wire the operator deck UI to it.
5. **Async Analyze service** — `analyses` + `analysis_findings` + the four endpoints; no auto-trigger yet (manual button + agent-initiated).
6. **Fill** — anchored in latest analysis; physically-feasible only.
7. **Status-aware gates + agent visibility** — per §11; ensures booked/approved respect the right actors.
8. **Meld/Extract** — UI ops on top of the parties model.

Steps 1-3 unblock the largest set of features (fatigue tracker, day-prep video, map view, today's vocabulary, faithful card render) for the smallest schema cost. Step 5 is the unlock for the proactive-agent behavior — no analysis = no proactive insight.