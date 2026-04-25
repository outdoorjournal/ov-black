# TravelGraph — Gap Analysis vs. Current `ov-black` Schema

Source notes: [Itinerary_Planning_System.md](./Itinerary_Planning_System.md)
Codebase analyzed: `~/personal/ov-black` (commit `d940297`, 2026-04-25)

---

## Side-by-side: notes vs. what's in the DB

| Notes concept | Current state | Gap |
|---|---|---|
| Vertex types: Activity, Travel, Waiting, Lodging, Eating, Terminus | `node_type`: destination, flight, hotel, experience, meal, transit, free_time, note | **Mostly mappable** but `waiting` and `terminus` are missing. `destination` and `note` are layout-flavored, not semantic. |
| Mandatory: start/end time (ranges), location (lat/lng/alt), type | All three live in `metadata jsonb` (verticalStore reads `metadata.start_time`, `metadata.duration_minutes`, `metadata.location`) | **No first-class temporal/spatial columns.** Can't enforce, can't index, can't do range/overlap queries. |
| Other attributes: money, energy ±, restrictions, items, phrases, pictures | Ad-hoc in `metadata jsonb` | No documented sub-schema; can't aggregate ("daily energy budget"). |
| Intrinsic vs. layered attributes | Only `source`/`source_id` (provenance pointer) | **No template registry.** Every node is fully instantiated; nothing intrinsic stored once and reused. |
| Linking, Melding, Extracting, Analyzing, Filling | `assemble_initial_draft` (linking only); `parent_subgraph_id` (self-FK for nesting) | **Meld, Extract, Analyze, Fill don't exist.** No party model, no validations engine, no inventory in-fill. |
| Per-party timelines | `itineraries.client_id` only | **No parties/travelers concept** at all. |
| Branching vertices | `edge_type='alternative_to'` | Exists, but **no "selected alternative" flag**, so linearization can't tell which branch is active. |
| Reusable subgraphs / card library | `parent_subgraph_id` is itinerary-scoped (NOT NULL `itinerary_id`) | **Subgraphs are not portable.** No `card_templates` table, no copy-into-itinerary op. |
| Card linearization (per-party walk between T1/T2) | Frontend re-implements per-prototype (vertical/horizontal) | **No server-side linearization service.** Each surface re-derives ordering. |
| Card deck ops (Duplicate, Edit, Archive) | None — cards are render-only | No store of named subgraphs to manage. |
| Mobile day view, prep video, fatigue tracker | None | All blocked on missing temporal/spatial columns + linearization service. |

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
- PostGIS `geography` lets the Map view do spatial queries without parsing JSON.
- Keep `metadata jsonb` for the long tail (phrases, items, energy ±) but spec a documented sub-schema.

### 2. Reconcile the vertex taxonomy

Add `waiting` and `terminus` to `node_type`. Optionally fold `destination` into `lodging` + `terminus` (a destination is really an arrival event = a Terminus or a Lodging start).

### 3. Introduce a template / card-library layer

Today every node is bespoke. Add:

```sql
card_templates       (id, name, description, intrinsic_attrs jsonb, region_id)
template_subgraph    (template_id, node_id, parent_id, type, ...)
template_edges       (...)

nodes.template_id    uuid references card_templates(id)
```

- Operators' "deck" = `card_templates`.
- Instantiating a template = copy template_subgraph rows into `nodes`/`edges` with `template_id` set.
- Layered attributes (travelers, dates) live on `nodes`; intrinsic ones on `card_templates`.

### 4. Add a parties/travelers model

The whole **Meld/Overlay** and **Extract** story collapses without it.

```sql
parties           (id, itinerary_id, label, member_count, attrs jsonb)
node_parties      (node_id, party_id)        -- many-to-many
```

- Default: every node belongs to a synthetic "all" party.
- Meld = UI op surfacing where two parties share the same node id vs. diverge.
- Extract = `select … where node_parties.party_id = $1`.

### 5. Mark the active branch among alternatives

Either `nodes.is_selected_alt boolean` or `edges.priority int` on `alternative_to` edges. Without this, the timeline renderer has no principled way to pick "the timeline" — it has to render every alternative.

### 6. Build a server-side linearization service

A new `app/services/timeline.py`:

```python
def linearize(itinerary_id, party_id, t_from, t_to) -> list[Card]
```

Walks `follows` (and selected `alternative_to`), filters by party, returns ordered cards. Every analysis the notes mention (packing list, vocabulary, exertion, map polyline) is a fold over this list. **Both prototypes today derive ordering client-side**, which means each surface drifts.

### 7. Build an Analyze pass

Run after every graph mutation; emit a `validations` table the UI surfaces:

- time non-linearity (range overlap on same party)
- location flux (Δkm / Δt > threshold given mode)
- availability (node `starts_at` vs. inventory `open_at`)
- party incompatibility (age/physical restrictions on members)

This is **continuous validation**, not a one-shot. Best run as a service-layer hook after `add_node` / `add_edge` commits, producing rows with severity + dismissable.

### 8. Build a Fill operation

Wire to the existing inventory registry (`apps/api/app/inventory/registry.py`). Given gaps between two `nodes.starts_at`, query providers for transit/lodging that fits the geo+time window.

---

## Holes in the notes & opportunities

### 1. "Possible ranges" should be the default, not the exception

Early planning is fuzzy ("Tuesday afternoon-ish"); firmness comes later. `tstzrange` collapsing to a point as planning matures is cleaner than min/max columns and makes overlap detection trivial. Worth committing to ranges from day one.

### 2. Selection of alternatives is under-specified

The notes say "Two possibilities present in this situation" but never say what makes one the "current plan." Without a `selected` flag, your fatigue tracker has to either pick arbitrarily or count both — neither is right. Decide: branch selection per-itinerary, per-party, or per-traveler?

### 3. Inventory sync is mentioned but the failure modes aren't

What if the Shinkansen 716 card got rescheduled by JR after the user pinned it? Need: `synced_at`, `provider_etag`, drift detection, and a status like `inventory_stale` distinct from `idea/proposed/approved`.

### 4. Energy budget is more meaningful per-traveler than per-node

A 6-mile hike is +2 for a 30-y-o trail runner and -5 for a grandparent. Storing energy ± on the node (intrinsic) and modulating by traveler profile (layered) makes the fatigue tracker actually useful.

### 5. Intrinsic data has three tiers, not two

Region-level (vocabulary, signs, currency) → Template-level (this Shinkansen leg's phrases) → Instance-level (these travelers, this date). Worth building all three from the start; a `regions` table is cheap.

### 6. Cards in a "deck" need versioning

When an operator edits a saved subgraph, do prior instantiations follow? Probably not — itineraries should snapshot. So: `card_templates` is mutable but instantiation copies. Keep a `template_version` snapshot on the instantiated node so "card has been updated since you used it" is detectable.

### 7. The Meld diagram skips the hard part — semantic merge

"Zippered together" is fine when both parties' nodes share an id (they did the same thing). But what if Party-1 is at the spa while Party-2 is hiking? That's not zippering, that's parallel tracks. Worth deciding up front whether Meld produces one merged graph or two parallel timelines with shared sync points.

### 8. `destination` and `note` clutter the vertex taxonomy

Your notes have a clean 6-type taxonomy. Current schema has 8, including two that aren't really physical states. I'd drop `destination` (it's just the terminus of a Travel) and either drop `note` or make it a non-temporal annotation type that doesn't appear in linearization.

### 9. The card library is the moat, but the schema treats it as nice-to-have

"Operators are effectively curating a library/deck" is the **business** of the platform — so reusable subgraphs should be the most-baked part of the schema, not a JSONB convention. Today they're absent.

### 10. No place for "walked-it" proof-of-experience attributes

Pictures, videos, stamps, sketches — your notes list them as attributes but the schema has no `media` table. Worth a `node_media (node_id, kind, url, taken_at, by_user_id)` so the Mobile day view's "what to bring" footer can flip to "what we did" post-trip.

---

## Suggested phasing

1. **Schema spine** — add `starts_at tstzrange`, `location`, `route`; add `waiting`/`terminus` to `node_type`; add `parties` + `node_parties`; add `nodes.is_selected_alt`.
2. **Linearization service** + retire client-side ordering in both prototypes.
3. **Card templates** — separate registry, instantiation op, version snapshot on instances.
4. **Analyze hooks** — `validations` table, run on every graph commit.
5. **Fill** — wire to inventory providers.
6. **Meld/Extract** — UI ops on top of the parties model.

Steps 1–2 unblock the largest set of features (fatigue tracker, day-prep video, map view, today's vocabulary) for the smallest schema cost.
