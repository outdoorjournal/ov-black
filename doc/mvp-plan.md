# MVP Plan — concierge-to-confirmed loop

> The build plan for [mvp.md](./mvp.md). Structured as milestones → slices. Each slice lists
> **goal · deliverables · touches · acceptance** and is sized to land independently behind tests, in the
> style of M001/S01–S09. (The GSD workflow has been retired; this doc is the forward ledger — see
> `doc/decisions.md` / `doc/requirements.md` / `doc/knowledge.md` for salvaged history.)

---

## 0. Baseline — what's already landed

**M001 (S01–S09) shipped the front half of the loop:** invite + magic link, advisor client/Voodoo-Doll
authoring, AgentCore turn loop, client chat with atmospheric morph, mood-board cards from OV inventory,
draft assembly + advisor approval gate + lock/queue, and the client final-itinerary view.

**The `feat/travelgraph-schema-spine` branch added (landed in code, but never reflected in the project's status docs — the drift that prompted retiring GSD):**
- Migrations 0007–0013: invite lifecycle, `itineraries.client_id` FK fix (0008), agent-session itinerary
  pin (0009), onboarding openers (0010), three-tier context Dossier/Profile/OSINT (0011), client contacts (0013).
- **Migration 0014 — TravelGraph schema spine:** first-class `starts_at tstzrange`, PostGIS `location`/`route`,
  `node_role` axis (destination/terminus), split transit types (subway/train/drive/walk/boat) + `waiting`,
  `parties`/`travelers`/`node_parties`, `is_selected_alt`, dual-mode notes (`attached_to_node_id` + XOR).
- **Migration 0015 — card templates:** `card_templates` / `template_nodes` / `template_edges` + node snapshot
  columns (`template_id`/`template_node_id`/`template_version`).
- Services: `timeline.py` (linearization), `templates.py` + `japan_template.py` (template instantiation),
  `card_attrs.py` (per-type discriminated Pydantic metadata), `seed_data/japan_itinerary.py`.
- New `apps/agent` workspace — the real Strands/AgentCore agent (modes, tools: `update_node_status`,
  `record_profile_fact`, `record_dossier_inference`, `get_traveler_context`, `set_mood`, translate).
- Integration routers (**all stubs**): `google_places.py`, `weather.py`, `flight_status.py`.
- Production graph UI promoted from prototypes under `apps/web/app/_components/itinerary-graph/`
  (horizontal/vertical canvas, cards, map strip, time axis).
- Design docs: `TravelGraph_Analysis.md` (the 8-phase plan), `Cards_Style_Guide.md`,
  `phase5_analyze_handoff.md`, `phase6_fill_handoff.md`.

**TravelGraph phase status:** 1–4 landed · **5 (Analyze) & 6 (Fill) documented, not implemented** ·
7 (status gates) & 8 (Meld/Extract) design-only.

**First task before anything else:** land this branch. Its 9 migrations and TravelGraph phases never
made it into the project's status docs — the stale GSD state files were the trigger for retiring that
workflow. Forward state now lives in `doc/mvp.md` / `doc/mvp-plan.md`, with decisions, requirements, and
engineering lessons salvaged to `doc/decisions.md`, `doc/requirements.md`, `doc/knowledge.md`.

---

## 1. Strategy

1. **Finish M001 first (Foundation gate).** No new milestone is "done" until it runs in real staging
   against real vendors with a craft-feel sign-off (R021). M001's owed staging deploy + UAT is the
   prerequisite that makes every later milestone testable.
2. **Build the spine bottom-up.** Node cost → status gates → invoices is a hard dependency chain. Do them
   in order; everything money- or booking-related sits on top.
3. **Two independent tracks can run in parallel** once Foundation lands: the **inventory/build track**
   (M002) and the **vault/details track** (M003) don't depend on each other.
4. **Reuse the existing seams.** New inventory providers are adapters behind the existing registry — no
   agent-prompt changes (R009/D006). New status/money logic extends `services/itineraries.py`'s existing
   `_check_lock` / `update_node` / `acquire_lock` patterns. New surfaces follow the RSC-auth + generated-SDK
   discriminated-result conventions M001 established.
5. **Hold the craft line everywhere client-facing** (R014): no emoji, no spinners/progress bars, serif
   agent prose, honest crafted failure messages.

---

## 2. Milestone map & dependencies

```
        ┌───────────────────────────────────────────────┐
        │ M001 CLOSEOUT (Foundation gate)                │  ← prerequisite for real-vendor testing
        │  branch land · staging deploy · agent runtime  │
        │  · GSD state refresh · founder craft UAT       │
        └───────────────┬───────────────────┬───────────┘
                        │                   │
         ┌──────────────▼─────────┐   ┌─────▼──────────────────┐
         │ M002 BUILD FAST        │   │ M003 DETAILS + VAULT   │   (parallel)
         │ providers · cost ·     │   │ party members ·        │
         │ Analyze · Fill ·       │   │ traveler form ·        │
         │ advisor authoring      │   │ secure vault           │
         └──────────────┬─────────┘   └────────────────────────┘
                        │ (node cost + Analyze)
         ┌──────────────▼─────────┐
         │ M004 FORK + GATES      │   needs: status gates, Analyze
         │ status mutation gates ·│
         │ fork/version · diff ·  │
         │ reconcile              │
         └──────────────┬─────────┘
                        │ (cost + gates)
         ┌──────────────▼─────────┐
         │ M005 INVOICE + BOOK    │   needs: cost (M002) + gates (M004)
         │ invoices · Braintree · │
         │ money gate · booking   │
         └────────────────────────┘
```

**Critical path:** Foundation → M002 (cost + Analyze) → M004 (gates) → M005 (money). M003 is parallel.

---

## 3. Milestones & slices

### M001 — Closeout / Foundation gate
*Goal: the existing loop runs in real staging against real vendors, and the project's source-of-truth
state files reflect the branch.*

| Slice | Goal | Deliverables / touches | Acceptance |
|---|---|---|---|
| **F1** | Land the branch | Merge `feat/travelgraph-schema-spine`; confirm `doc/mvp.md` / `doc/mvp-plan.md` reflect reality (GSD retired, history salvaged to `doc/`); CI green on `main`. | Migrations through 0015 + the TravelGraph phases are on `main`; planning docs match the code. |
| **F2** | Real staging deploy | Populate CDK context (real `vpcId`/subnets), real Secrets (Supabase, Bedrock, vendor keys), provision the AgentCore runtime + put its ARN in the Secret, configure SMTP. | `scripts/verify-s0*.sh` pass against `STAGING_API_URL`; magic-link email arrives. |
| **F3** | Founder craft-feel UAT | Run M001's owed UATs (S03 authoring, S05 opener, S06 morph, S07 cards, S08 advisor surface, S09 final view) against real Bedrock + OV. | R021 sign-off recorded; any craft slips fixed. |

### M002 — Build fast: multi-source inventory + AI authoring (Pillar 3)
*Goal: staff (with AI) assemble delightful itineraries from four live sources, in minutes.*

| Slice | Goal | Deliverables / touches | Acceptance |
|---|---|---|---|
| **B1 — Google Places live** | Replace the stub with the live API. | Wire `routers/integrations/google_places.py` to live Text Search + Details (key in Secrets); add a **Places inventory adapter** so `search_inventory(kinds=['meal','experience'])` dispatches to it; normalize to `InventoryItem`. | Agent proposes a real restaurant card by name+geo; provenance `source='google_places'`; stub path removed. |
| **B2 — Duffel flights provider** 🔨 *adapter landed — see §8* | Flight search as an inventory adapter. | New `inventory/providers/duffel.py` (offer search → `InventoryItem` flight variant); map to the `flight` card type + `FlightCardAttrs`; register via `INVENTORY_PROVIDERS_ENABLED`. Reference `voyage-site` `src/utils/duffel-client.ts` patterns. | `search_inventory(kinds=['flight'])` returns live Duffel offers; a flight node renders with cabin/seat/times. |
| **B3 — Ratehawk hotels provider** | Hotel search as an inventory adapter. | New `inventory/providers/ratehawk.py` (availability + rates → `InventoryItem` hotel variant); map to `hotel` card + `HotelCardAttrs`. (No `voyage-site` reference — net-new; build adapter + fixture like OV.) | `search_inventory(kinds=['hotel'])` returns live Ratehawk rates; hotel node renders room/nights/check-in. |
| **B4 — First-class node cost** | Make cost real (unblocks M005). | Migration: `nodes.cost_amount numeric`, `nodes.cost_currency text`, optional `cost_kind` (per_person/total); populate from each provider adapter; surface in `card_attrs` + linearization; advisor can edit. **Deprecate free-text `metadata.price` for bookables.** | A bookable node has numeric cost+currency from the provider; advisor surface shows/edits it; sum-of-costs computable. |
| **B5 — Analyze (shallow + standard)** | Feasibility backbone for Fill + reconcile. | Migration: `analyses` + `analysis_findings` (per `TravelGraph_Analysis` §8 / `phase5_analyze_handoff.md`); `services/analyze.py` async state machine; endpoints `POST /itinerary/{id}/analyze`, `GET .../analyses[/{id}]`, cancel. Shallow = structural; standard = `tstzrange` overlap + geo-flux by mode (uses 0014 PostGIS) + weather stub. **No deep/real-time yet.** | Running standard analyze on the Japan seed flags an impossible drive-time gap as a `warn` finding with evidence. |
| **B6 — AI Fill** | Physically-feasible gap-filling. | `services/fill.py` consuming the latest completed analysis (`phase6_fill_handoff.md`); `fill_gap(itinerary_id, gap, party_id, analysis_id)` → ranked `FillProposal`s filtered by geo-radius + drive-time + party constraints; agent tool + advisor "fill this gap" action; accepted proposals become `proposed` nodes. | Advisor selects a gap; Fill returns ranked feasible options with rationale; accepting one adds a `proposed` node with provenance. |
| **B7 — Advisor authoring surface** | "Build in minutes." | Command-Center itinerary editor: card-template **deck** (instantiate from `card_templates`), drag/drop using the promoted `_components/itinerary-graph` views, inline node edit, run-analyze + run-fill actions, approve. Generated-SDK wrappers for templates/analyze/fill. | Advisor builds a 5+ node multi-source itinerary from templates + Fill and approves it; client view renders it. |

### M003 — Traveler details + vault (Pillar 4) — *parallel to M002*
*Goal: the traveler supplies party details and stores reusable documents securely.*

| Slice | Goal | Deliverables / touches | Acceptance |
|---|---|---|---|
| **V1 — Party member model** | Identity-bearing travelers. | Migration extending `travelers` (0014): full name, DOB, nationality, dietary/medical/mobility, loyalty numbers, emergency contact, party↔client link; service + endpoints; RLS scoped to client + assigned advisor. | Traveler record persists per member; advisor reads it; agent can reference party constraints in Fill. |
| **V2 — Traveler details form** | Client-facing entry. | `/account/party` (or in-trip) RSC + form (react-hook-form + zodResolver, craft-clean) to add/edit party members; "who's traveling" attaches members to an itinerary's `node_parties`/party. | Traveler fills missing details; data flows to V1; advisor sees completeness. |
| **V3 — Secure vault** | Encrypted, expiry-tracked, reusable docs. | Migration `client_documents` (type, S3 key, expiry, owner, encryption ref); S3 bucket (SSE-KMS) via CDK; presigned upload/download endpoints scoped to client + advisor; expiry flagging (passport < 6mo). `/account/vault` upload UI; **documents reusable across trips** (attach existing doc to a new itinerary). | Traveler uploads a passport; advisor views it; expiry warns; same doc attaches to a second trip without re-upload. |

### M004 — Status gates, fork & reconcile (Pillar 5)
*Goal: AI forking + staff reconcile, with booked inventory immutable. (TravelGraph Phase 7 + fork.)*

| Slice | Goal | Deliverables / touches | Acceptance |
|---|---|---|---|
| **G1 — Status-aware mutation gates** | Booked/finalized immutability. | `_check_status_gate` in `services/itineraries.py` (per `TravelGraph_Analysis` §11): `approved` editable only by advisor-after-demote; `booked`/`confirmed` immutable except advisor demotion/cancellation (writes visible `node_history`). Agent `update_node_status` inherits the gate; refusals return a crafted reason. Per-node `lock_reason` exposed so the agent can explain. | A `booked` node refuses traveler/agent edits with a crafted message; advisor demotion works + is logged; tests cover every status × actor cell. |
| **G2 — Itinerary fork (versioned clone)** | Branch an itinerary (D-FORK). | Migration: `itineraries.forked_from_id`, `fork_status`, `nodes.forked_from_node_id` lineage. `services/fork.py::fork_itinerary` deep-copies nodes/edges: pre-booked → editable, `booked`/`confirmed` → carried **locked**. Agent tool + traveler-initiated fork. | Traveler forks an approved itinerary; the fork is independently editable; booked nodes are present but locked; lineage links each forked node to its origin. |
| **G3 — Diff + reconcile surface** | Staff fold changes back in. | `services/fork.py::diff_fork` (added/removed/changed/moved via lineage pairing); Command-Center **diff view** (side-by-side baseline vs. fork); per-change **accept/discard** that mutates the live graph, gated by an Analyze feasibility check before accept. | Advisor opens a fork's diff, runs analyze, accepts a subset into the live plan and discards the rest; live itinerary reflects only accepted changes; booked nodes can't be changed via reconcile. |

### M005 — Invoicing & booking (Pillar 6 + the money gate)
*Goal: invoices total booked inventory; pay-before-book; advisor books to confirmed.*

| Slice | Goal | Deliverables / touches | Acceptance |
|---|---|---|---|
| **I1 — Invoices + line items** | One itinerary → N invoices. | Migration `invoices` (itinerary_id, label, status draft/issued/paid/void, currency, due_at, totals) + `invoice_line_items` (invoice_id, **node_id** nullable, description, amount, currency). `services/invoices.py`: create/issue, line-item from node cost (B4), `total = Σ line items`. Advisor surface to assemble invoices from approved bookable nodes. | Advisor creates a deposit + a balance invoice over a set of approved nodes; each total = Σ its lines; line items reference the nodes. |
| **I2 — Braintree payment** | Traveler pays (D-PAY). | Braintree gateway (Secrets) per `voyage-site` `brainTreeGateway.ts`; client-token endpoint + drop-in payment on a client `/invoices` view; webhook/confirm marks invoice `paid`, records payment. Sandbox for the MVP. | Traveler pays an issued invoice in Braintree sandbox; invoice flips to `paid`; payment + invoice history visible. |
| **I3 — Money gate + booking workflow** | Pay-before-book → confirmed. | Service gate: `approved → booked` requires a covering **paid** invoice line (advisor override to *issued*, logged — D-PAY). Advisor "record booking" flow attaches supplier confirmation # → `booked`, then `confirmed`. **Reconciliation check**: Σ(paid lines for nodes) ⇔ Σ(booked node costs), surfaced + tested. | A node can't be booked until paid; advisor books a paid node + records confirmation → `confirmed`; reconciliation invariant holds and is asserted in tests + a verify script. |

---

## 4. Parallelization & sizing

- **After Foundation:** run M002 and M003 concurrently (different subsystems, no shared schema churn).
- **Within M002:** B1/B2/B3 (the three providers) are independent and parallelizable; B4 (cost) can land
  alongside them; B5→B6→B7 are sequential (Fill needs Analyze; authoring needs both).
- **M004 needs** G1 (gates) before G2/G3, and benefits from B5 (Analyze) for reconcile feasibility.
- **M005 needs** B4 (cost) and G1 (gates) — start it only after those land.
- Each slice ships behind tests with a `scripts/verify-sNN.sh` smoke harness, matching M001 discipline.

---

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Ratehawk has no reference impl** (unlike Duffel/Braintree in `voyage-site`). | Build it as a clean adapter behind the registry with a committed live-capture fixture (mirror the OV adapter). Spike credentials early. |
| **Money-gate correctness** (booked-but-unpaid, double-billing). | Single source of truth = invoice tables; assert the reconciliation invariant in tests + a verify script; advisor override is explicit + logged. |
| **Fork divergence + reconcile complexity.** | Lineage column (`forked_from_node_id`) makes diff deterministic; gate accepts through the same service mutation path as M001's lock/queue (no parallel write path — cf. D022). |
| **PostGIS / geo feasibility accuracy in Analyze.** | Start with haversine + per-mode speed caps (no live traffic) for standard depth; defer real-time to post-MVP deep mode. |
| **Vault security for HNW clients.** | SSE-KMS + presigned, access-scoped URLs + RLS; never log document content/keys (extend the existing redaction discipline); legal review of OSINT/doc retention. |
| **Vendor rate limits / flakiness** (Duffel, Ratehawk, Places). | Provider abstraction already isolates this; apply R018 silent-retry + crafted-failure; agent treats "no results" as a conversational pivot. |
| **Planning-doc drift** (GSD already drifted 9 migrations behind before it was retired). | Keep `doc/mvp-plan.md` updated per slice — it's now the single forward ledger. |

---

## 6. Decisions to lock before/within the relevant milestone

Carried from [mvp.md](./mvp.md) §6 — confirm these as they come up (recommendations in **bold**):

- **D-FORK** (before M004/G2): **versioned-clone fork** with lineage + diff/reconcile; `alternative_to` stays for local swaps.
- **D-PAY** (before M005/I2): **Braintree**; gate `booked` on **paid**, advisor override to *issued* (logged).
- **D-COST** (before M002/B4): **first-class `nodes.cost_amount` + `cost_currency`**; minimal multi-currency (store native, one display currency).
- **D-VAULT** (before M003/V3): **S3 + SSE-KMS** + presigned, access-scoped; expiry in Postgres; client-side encryption deferred.
- **D-ANALYZE** (before M002/B5): **shallow + standard only**; defer deep/real-time external calls.
- **D-BOOK** (before M005; informs M002/B4 + M004/G1): booking state = two structured tables — **`node_offers`** (transient, time-boxed supplier quotes with `expires_at` + refresh lineage) + **`bookings`** (committed record: order/PNR, charged amount, links to offer + invoice line). Flight offers **re-priced before `approved → booked`**; money gate reconciles the re-priced amount + surfaces a delta. Recorded as **D024**; draft schema in §8 below.

---

## 7. Suggested first three steps

1. **F1** — land the branch so `main` matches the planning docs.
2. Lock **D-COST**, **D-FORK**, **D-PAY** (they gate the spine).
3. Start **M002/B1 + B2 + B3** (providers, parallel) and **M002/B4** (node cost) — the highest-leverage,
   most-independent work, and the foundation everything money-related sits on.

---

## 8. Progress log (append-only, newest first)

> Running ledger of what's actually landed against the slices above, so any
> session can resume mid-slice without re-deriving state. Each entry: date ·
> slice · what landed · what's tested · what remains · resume hook.

### 2026-06-21 — M002/B1 Google Places live — **provider + live router landed (behind tests)**

**What landed (all in `apps/api`, net-new files plus additive, localized edits
to the shared config/main seams — deliberately disjoint from B2's Duffel and
B3's Ratehawk work, and from the in-flight itinerary-graph timezone files):**
- `app/inventory/providers/google_places.py` — `GooglePlacesProvider(InventoryProvider)`,
  `source="google_places"`. Targets the **Places API (New)** (`places.googleapis.com/v1`):
  single-POST `POST /v1/places:searchText` (`{textQuery, includedType?,
  maxResultCount, locationBias?}` → `{places:[…]}`) and `GET /v1/places/{id}`.
  Auth via the `X-Goog-Api-Key` header; the response is shaped by a shared
  `X-Goog-FieldMask` (search masks fields under `places.`, detail unprefixed —
  built from one `_FIELDS` list so they can't drift). Pure helpers:
  per-field wire accessors (`display_name_of` … `photos_of`), `classify_kind`
  (dining type / `*_restaurant` suffix → `meal`, else `experience`),
  `summarize_place`, and `normalize_place` (→ `MealItem` | `ExperienceItem`,
  full place kept in `raw`). The accessors are **exported and reused by the
  integration router** so router + provider read one wire shape.
- **Two honesty calls (documented in the module docstring):**
  (1) **price** — Places quotes only a coarse `priceLevel` enum, never a
  bookable amount, so items carry `price=None` and the level rides in `tags`
  as a `$`-symbol (meals/experiences aren't first-class bookable cost — that's
  B4 flights/hotels); (2) **photos** — a Places (New) photo is a resource
  *name*, not a URL, and resolving it needs a keyed `…/media` fetch, so
  `photos` is left `[]` (refs preserved in `raw`) to keep the API key
  server-side. A keyed backend photo-proxy is the follow-up.
- Error posture mirrors the other providers: `search()` / `text_search()`
  degrade to `[]` + a warning on every failure (no key, missing query, timeout,
  non-2xx, malformed); `place_details()` / `get_detail()` → `None` on 404,
  raise `ProviderUpstreamError` otherwise. Text Search **requires** a
  `textQuery` — a keyword-less call returns `[]` (a no-query browse legitimately
  has no Places hits). Key never logged (`repr=False` on the settings field).
- `app/config.py` — `google_places_base_url` (`https://places.googleapis.com`),
  `google_places_api_key` (`repr=False`). Keyless ⇒ registered but every search
  returns `[]` (degrade, don't crash boot). `INVENTORY_PROVIDERS_ENABLED`
  docstring updated to list `google_places` (still defaults to `ov,mock`, so
  off until opted in).
- `app/main.py` — registers `GooglePlacesProvider` when `google_places` ∈
  `INVENTORY_PROVIDERS_ENABLED`.
- **`app/routers/integrations/google_places.py` rewired stub → live.** The
  canned `_CATALOGUE` is gone; `/search` + `/details/{id}` now delegate to the
  provider's public `text_search` / `place_details` (one shared HTTP layer) and
  map the raw place into the **unchanged** `PlaceSummary` / `PlaceDetail`
  response contract (so the generated client surface is identical — only the
  route `summary=` strings changed). Provider injected via a
  `get_google_places_provider` FastAPI dependency so tests swap a
  `MockTransport`-backed provider. `/details` returns 404 (absent) / 502
  (upstream broken).

**What's tested:**
- `tests/fixtures/google_places_searchtext.json` (3-place Tokyo/Kyoto Text
  Search: Sushi Saito = meal, Fushimi Inari + Aman Tokyo = experiences) +
  `google_places_details.json` (single Fushimi Inari detail).
- `tests/test_inventory_google_places_provider.py` — 27 tests: pure classify /
  normalize / summarize, search request-shape (textQuery, includedType
  narrowing per single kind, location-bias circle, maxResultCount clamp), kind
  filtering, every degrade path, get_detail happy/404/empty/500/conn-error/
  no-creds, key redaction.
- `tests/test_integrations.py` — Google Places section rewritten from the stub
  to the live router (mock-transport): result mapping, location-bias
  passthrough, blank-query no-op, detail full-record, 404, 502, auth gate.
- **Full `apps/api` suite green (473 passed) + `apps/agent` suite green (34).**
  `app.main` imports clean with `google_places` enabled. `scripts/verify-sB1.sh`
  runs the acceptance bullets + a static "stub removed" guard offline, with an
  optional staging live probe (soft-skips without creds).

**Follow-up landed same day (the two cross-file hooks, after B2/B3 finished):**
- **Meal → `MealCardAttrs` card mapping.** `services/card_mapping.py` now maps a
  Places `MealItem` → typed `MealCardAttrs` (cuisine class from the place's
  primary type, coarse `priceLevel` → a `$`-symbol, geo anchor, snapshot chip
  strip); `inventory_item_to_card_metadata` routes `MealItem` to it, so a
  restaurant proposed via `POST /{id}/nodes/from-inventory` renders as a typed
  `meal` card. A Places *experience* (attraction) deliberately stays on the
  shared snapshot path — `parse_card_attrs` re-inflates it into an
  `ExperienceCardAttrs` on read, identical to an OV experience. +3 tests in
  `tests/test_card_mapping.py`.
- **Location-bias plumbing.** `/search-inventory` (route) + the agent
  `search_inventory` tool gained optional `near_lat`/`near_lng`/`radius_m`
  params, forwarded into `filters` (distinct from Ratehawk's hotel-geo
  `latitude`/`longitude`); the provider already consumed them. +2 route tests
  in `tests/test_search_inventory.py`.

**What remains to call B1 fully "done" (resume hooks):**
1. **Live validation (real key).** No Google Places key in `voyage-site` or the
   ov-black env (net-new, like B3) — spike a key, run the provider against the
   real API, and **re-record both fixtures** from a live call (the committed
   ones are recorded-*shape*, hand-built from real places). Then enable
   `google_places` in the staging `INVENTORY_PROVIDERS_ENABLED` + add the
   `GOOGLE_PLACES_API_KEY` secret (F2) and run `verify-sB1.sh`'s live probe.
2. **Photo proxy (genuinely a small follow-up slice, not a quick win).** A
   Places (New) photo is a resource *name* needing a keyed `…/media` fetch — but
   an `<img src>` can't carry the Supabase JWT, so a naive proxy endpoint would
   401 (or, if public, leak the key to abuse). It needs a **signed short-lived
   URL** scheme (token in the query string) before `photos` can be populated
   from the refs preserved in `raw`. Cards render imageless until then.

### 2026-06-21 — M002/B3 Ratehawk hotels provider — **adapter layer landed (behind tests)**

**What landed (all in `apps/api`, deliberately disjoint from B2's in-flight
Duffel card-mapping / timezone work — net-new files plus additive, localized
edits to the shared config/main/router/agent-tool seams):**
- `app/inventory/providers/ratehawk.py` — `RatehawkProvider(InventoryProvider)`,
  `source="ratehawk"`. Single-POST ETG (Emerging Travel Group / Worldota) B2B
  v3 SERP flow: `POST /search/serp/region/` (when `region_id` present) or
  `POST /search/serp/geo/` (when `latitude`+`longitude` present). Pure helpers
  `normalize_ratehawk_hotel` (hotel → `HotelItem`, full hotel incl. every rate
  kept in `raw`) and `summarize_hotel` (headline facts: name, star_rating,
  geo, room_name/type, bedding, nights, board, amount/currency,
  free_cancellation_before, book_hash — exported for the later card mapping).
  Each hotel headlines off its **cheapest rate** (min display `show_amount`).
  Error posture mirrors `OVProvider`/`DuffelProvider`: `search()` degrades to
  `[]` + a warning on any failure (no creds, missing params, timeout, non-2xx,
  malformed) **and on a non-`ok` ETG envelope** (status≠ok / populated error —
  ETG returns HTTP 200 for business errors); `get_detail()` → `None` when the
  hotel is absent, raises `ProviderUpstreamError` on transport/HTTP errors.
  Auth via HTTP **Basic** (`key_id`:`api_key`); key never logged.
- `app/config.py` — `ratehawk_base_url` (`https://api.worldota.net/api/b2b/v3`),
  `ratehawk_key_id`, `ratehawk_api_key` (`repr=False`). Missing either half ⇒
  registered but every search returns `[]` (degrade, don't crash boot).
- `app/main.py` — registers `RatehawkProvider` when `ratehawk` ∈
  `INVENTORY_PROVIDERS_ENABLED` (still defaults to `ov,mock`, so off until opted in).
- `tests/fixtures/ratehawk_hotels.json` — recorded-shape Lake Como region SERP
  (2 five-star hotels, multi-rate). **Fixture honesty:** the real ETG SERP
  carries only `id`/`hid`/`rates` per hotel; name/geo/star/images come from a
  separate static store. The fixture inlines that static content under
  `static_vm` so the full name→geo→price mapping is exercised offline (and
  `get_detail` reuses the same extractor via `/hotel/info/`).
- `tests/test_inventory_ratehawk_provider.py` — 22 tests (pure
  normalize/summarize incl. cheapest-rate + static-less fallbacks, region +
  geo search, guests/children, all guard paths, envelope-error,
  get_detail happy/not-found/500/conn-error/no-creds, key redaction).

**Hotel search params** ride in the registry `filters` dict (not `keyword`):
`region_id` **or** (`latitude`+`longitude`), plus `checkin`+`checkout`
(required), and optional `adults`, `children` (ages), `residency`, `currency`,
`language`, `radius`, `limit`.

**Plumbing landed (same day, additive to B2's edits):**
- `app/routers/inventory.py` — `GET /search-inventory` now accepts hotel params
  (`region_id`, `latitude`, `longitude`, `checkin`, `checkout`, `residency`,
  `currency`; `adults` is shared with flights) and forwards non-empty ones into
  `filters`. OV/mock ignore unknown keys. +3 router tests (region passthrough,
  geo passthrough, omitted-when-unset).
- `apps/agent/src/agent/tools/inventory.py` — agent `search_inventory` tool
  widened with the same hotel params + hotel-search guidance in the docstring.

**Card mapping landed (same session, creds-independent — closes the "hotel node
renders room/nights/check-in" acceptance bullet):**
- `app/services/card_mapping.py` — `hotel_item_to_card_attrs(item, *, check_in,
  check_out)` maps a `HotelItem` → typed `HotelCardAttrs` (name, room_type,
  bedding, nights, geo, `night_bar`, seed-shaped `CardSnapshot`) via
  `summarize_hotel`; `inventory_item_to_card_metadata` now dispatches
  `HotelItem` → typed (alongside B2's `FlightItem`). `check_in`/`check_out` are
  the *search-request* dates (NOT in the ETG per-hotel response), threaded by
  the caller; when both present `nights` is recomputed from the stay length.
  Like B2's flight mapping, this is **tested but not yet wired into the live
  `propose_card` path** — that wiring (threading search dates through to the
  node) is shared follow-up with B2.
- `tests/test_card_mapping.py` — +4 hotel tests (room/nights/geo, date→nights
  override, metadata shape, sparse/static-less hotel).
- `scripts/verify-sB3.sh` — 11 offline acceptance bullets (region + geo search,
  cheapest-rate, source provenance, hotel-node room/nights/check-in, router
  passthrough, no-creds + non-ok-envelope degrade, key redaction, registry
  wiring) + an optional staging live probe that soft-skips without creds
  (mirrors `verify-sB1.sh`). Runs green offline: **11 passed, 0 failed**.

**Tested:** full `apps/api` suite **464 passed**; full `apps/agent` suite
**34 passed**; `app.main` imports clean with `ov,mock,duffel,ratehawk` enabled.
(No live ETG validation — no sandbox credentials available; see resume hook 1.)

**What remains to call B3 fully "done" (resume hooks):**
1. **Credential spike + live re-capture (the only creds-blocked item).** Get ETG
   sandbox creds, confirm the real SERP/`hotel/info/` field shapes, wire the
   **static-content join** the fixture currently inlines as `static_vm` (content
   dump vs. per-hotel `/hotel/info/`), re-record `ratehawk_hotels.json` from a
   live call, enable `ratehawk` in the staging `INVENTORY_PROVIDERS_ENABLED` +
   add `RATEHAWK_KEY_ID`/`RATEHAWK_API_KEY` secrets (F2), and run
   `verify-sB3.sh`'s live probe. (mvp-plan §5: "Ratehawk has no reference impl —
   spike credentials early".)
2. **Wire the typed mapping into `propose_card`** (shared with B2's flight
   mapping): thread the originating search dates so a proposed hotel node stamps
   `check_in`/`check_out`. Touches the proposal path / itinerary-graph files.

   *Done this session:* ~~Hotel `HotelItem` → `HotelCardAttrs` mapping~~ and
   ~~`scripts/verify-sB3.sh`~~ — both landed above.

### 2026-06-21 — M002/B2 Duffel flights provider — **adapter layer landed (behind tests)**

**What landed (all in `apps/api`, deliberately disjoint from the in-flight
timezone work in `services/itineraries.py` / `services/japan_template.py` /
`apps/web/.../itinerary-graph/` — do not touch those here):**
- `app/inventory/providers/duffel.py` — `DuffelProvider(InventoryProvider)`,
  `source="duffel"`. Two-step Duffel flow: `POST /air/offer_requests`
  (`return_offers=false`) → `GET /air/offers?offer_request_id=…&sort=total_amount`.
  Pure helpers `normalize_duffel_offer` (offer → `FlightItem`, full offer kept
  in `raw`) and `summarize_offer` (headline facts: iata_from/to, flight_code,
  carrier, cabin, depart/arrive, stops — exported for the later card mapping).
  Error posture mirrors `OVProvider`: `search()` degrades to `[]` + a warning
  on any failure (no creds, missing route params, timeout, non-2xx, malformed);
  `get_detail()` → `None` on 404, raises `ProviderUpstreamError` otherwise.
  Auth via `Authorization: Bearer`, `Duffel-Version` header; key never logged.
- `app/config.py` — `duffel_base_url` (`https://api.duffel.com`), `duffel_api_key`
  (`repr=False`), `duffel_api_version` (`v2`). Keyless ⇒ registered but every
  search returns `[]` (degrade, don't crash boot).
- `app/main.py` — registers `DuffelProvider` when `duffel` ∈
  `INVENTORY_PROVIDERS_ENABLED` (still defaults to `ov,mock`, so off until opted in).
- `tests/fixtures/duffel_offers.json` — recorded-shape LAX→HND offer-list (2 offers).
- `tests/test_inventory_duffel_provider.py` — 17 tests (pure normalize/summarize,
  two-step search incl. round-trip slice + passenger count, all guard paths,
  get_detail happy/404/500/conn-error, api-key redaction). **73 passed** across
  the full inventory suite; `app.main` imports clean with duffel enabled.

**Flight search params** ride in the registry `filters` dict (not `keyword`):
`origin`, `destination`, `departure_date` (required trio), plus optional
`return_date`, `cabin_class`, `adults`, `limit`.

**Plumbing landed (same day):**
- `app/routers/inventory.py` — `GET /search-inventory` now accepts flight params
  (`origin`, `destination`, `departure_date`, `return_date`, `cabin_class`,
  `adults`) and forwards non-empty ones into `filters`. OV/mock ignore unknown
  keys. +2 router tests (passthrough + omitted-when-unset); 36 passing.
- `apps/agent/src/agent/tools/inventory.py` — agent `search_inventory` tool
  widened with the same flight params + flight-search guidance in the docstring.
  Agent suite: 34 passing.
- API client regenerated (`pnpm -C packages/api-client generate`) — note
  `packages/api-client/src/generated/` is **gitignored** (CI regenerates; not
  committed). `apps/web` typecheck clean.

**Live validation (sandbox):** ran the adapter against the real Duffel API with
the `duffel_test_*` token from `~/work/voyage-site/.env.local`. `search` returned
3 real LHR→JFK business offers, normalized correctly (title, EUR price, carrier/
cabin/nonstop tags, flight_code + times via `summarize_offer`, origin-airport
geo). Confirms field names match the fixture and `Duffel-Version: v2`. (Live
results came back in EUR — multi-currency display deferred per D-COST.)

**UPDATE (later same day) — render + wiring landed; B2 acceptance met.**
Both acceptance clauses now hold end-to-end (behind tests):
- **Render clause** (`a1bfcb0`): `services/card_mapping.py`
  `flight_item_to_card_attrs` (FlightItem → `FlightCardAttrs` via `summarize_offer`
  + airport geometry) and a generic `inventory_item_to_card_metadata`; the flight
  Node card (`NodeCard` FlightBody + `ExpandedCard` FlightFace) renders route +
  cities + cabin chip + seat + depart→arrive wall-clock (each end its own offset),
  with lifecycle status carried by `CardShell`. `NodeMeta` gains
  cabin/seat/depart_at/arrive_at. 5 api mapping tests + 3 web render tests.
- **Wiring clause** (`4266e2a`): `POST /itinerary/{id}/nodes/from-inventory`
  fetches the item via the registry (Duffel re-fetch = offer refresh, D024),
  derives typed card metadata, maps kind→NodeType, and creates the node through
  the normal `add_node` write path; agent tool `propose_flight(source, source_id)`
  registered in the planning set. 4 router tests. Multi-kind for free (hotels via
  the shared `card_mapping`, co-developed with B3).

**Still owed (small):**
1. **Flight card → offer-freshness status.** The card is the surface to show the
   time-boxed quote ("fare held until …" / repriced) per the design note + D024.
   Needs `node_offers` (M005) threaded into the card (`expires_at`/`priced_at`);
   today the card shows cabin/seat/times + lifecycle status only.
2. **Client regen for the new endpoint** — deferred to the B1/B3 batch
   (`generated/` is gitignored; the agent path uses raw HTTP, so nothing is blocked).
3. **Verify script** `scripts/verify-sB2.sh` against staging (after F2).

### 2026-06-21 — Design note (founder): flight offers are time-boxed & repriceable

> Captured to shape **B4** (cost), **M004/G1** (status gates), and **M005**
> (invoice + money gate). Do not lose this — it changes the money-gate design.

Flights differ fundamentally from experiences/hotels: a Duffel **offer is a
price HELD for a fixed window** (`expires_at`, typically ~20–30 min), not a
stable listing price. The quote metadata is attached in a *pre-booking* state,
is expected to **go stale**, and **changes when refreshed**. Implications:

- **Two distinct price-bearing states.** A flight node carries OFFER metadata
  (`offer_id`, `priced_at`, `expires_at`, `amount`, `currency`) that is
  explicitly transient — separate from a final, committed BOOKED price. The
  adapter now surfaces `total_amount`/`total_currency`/`expires_at` in
  `summarize_offer` so this freshness is first-class, not buried in `raw`.
- **Booking is a separate supplier step, not just a status flip.** Duffel
  booking is `POST /air/orders` (optionally a *hold* order + `POST /air/payments`
  before the hold expires) — not editing node status. Before `approved → booked`
  the offer must be **re-priced/refreshed**; the new amount may differ from what
  an invoice was issued at.
- **This stresses the M005 money-gate invariant** (Σ paid invoice lines ⇔ Σ
  booked node costs): for flights the cost is **not stable** between invoice
  issue and payment/booking. M005 needs a re-price/refresh step that surfaces a
  **price delta** for advisor/traveler confirmation before committing, and the
  invoice line must reconcile against the *re-priced / held-fare* amount, not the
  original search quote.
- **Booked nodes need STRUCTURED booking metadata** (not the current free-text
  `metadata.snapshot`): supplier order id / PNR, payment + transaction refs,
  charged amount + currency, `booked_at`, actor, and change/cancel terms —
  linking node ↔ invoice line ↔ payment ↔ supplier order. Design this typed
  "booking record" in B4/M005 and lock it booked-immutable in G1.

#### Draft schema — `node_offers` + `bookings` (decision **D024** / **D-BOOK**)

> **DRAFT — not yet migrated.** Belongs to M005 (needs B4 cost + G1 gates first);
> recorded now so the design isn't lost. Conventions follow D003 (Supabase CLI
> owns raw-SQL DDL; SQLAlchemy is query-layer only), D005 (relational + append-
> only, not JSONB blobs), and D020 (Postgres-native `ENUM` for new enums). Two
> tables sit beside the existing `nodes` (status enum `idea→proposed→approved→
> booked→confirmed` is unchanged — it stays the lifecycle axis; money/booking
> detail lives here). `invoice_line_items` is defined by M005/I1.

```sql
-- ── node_offers: the transient, time-boxed supplier QUOTE (pre-booking) ─────
-- A flight (and any repriceable supplier item) is quoted, not listed: price +
-- availability are HELD only until expires_at. Attached while the node is
-- pre-booking; expected to go stale; re-fetched/re-priced before booking — and
-- the amount can change. Each refresh inserts a new row (refreshed_from_id),
-- so the offer history is auditable; the lone 'active' row is the live quote.
create type public.offer_status as enum (
    'active',      -- within its hold window; usable to book
    'expired',     -- past expires_at; must be refreshed before booking
    'superseded',  -- replaced by a newer refresh of the same logical offer
    'booked'       -- converted into a booking (terminal)
);

create table public.node_offers (
    id                uuid primary key default gen_random_uuid(),
    node_id           uuid not null references public.nodes (id) on delete cascade,
    itinerary_id      uuid not null references public.itineraries (id) on delete cascade,
    source            text not null,                 -- 'duffel', 'ratehawk', ...
    source_offer_id   text not null,                 -- e.g. Duffel off_...
    status            public.offer_status not null default 'active',
    amount            numeric(12,2) not null,        -- held quote; native currency (D-COST)
    currency          text not null,                 -- ISO 4217
    priced_at         timestamptz not null default now(),
    expires_at        timestamptz,                   -- null = no explicit hold window
    refreshed_from_id uuid references public.node_offers (id) on delete set null,
    raw               jsonb not null default '{}'::jsonb,  -- supplier payload for re-price/book
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
-- At most one live quote per node.
create unique index node_offers_one_active
    on public.node_offers (node_id) where status = 'active';

-- ── bookings: the committed BOOKING record (the money-committed state) ───────
-- Created when a node goes approved -> booked with the supplier. Single
-- structured home for "everything about the booking": supplier order/PNR, the
-- amount ACTUALLY charged (may differ from the search quote after a re-price),
-- who/when, change-cancel terms, and links to the offer it booked from + the
-- covering invoice line. Booked/confirmed nodes are immutable (G1); this is
-- their backing data.
create type public.booking_status as enum (
    'pending',    -- order placed with supplier, awaiting confirmation/ticketing
    'confirmed',  -- supplier confirmed (PNR/ticket issued)  -> node 'confirmed'
    'cancelled',  -- cancelled via advisor demotion/cancellation flow
    'failed'      -- supplier order failed (price changed / sold out)
);

create table public.bookings (
    id                   uuid primary key default gen_random_uuid(),
    node_id              uuid not null references public.nodes (id) on delete restrict,
    itinerary_id         uuid not null references public.itineraries (id) on delete cascade,
    booked_from_offer_id uuid references public.node_offers (id) on delete set null,
    status               public.booking_status not null default 'pending',
    source               text not null,                 -- 'duffel', ...
    supplier_order_id    text,                           -- Duffel ord_...
    confirmation_code    text,                           -- PNR / record locator
    charged_amount       numeric(12,2),                  -- reconciles vs invoice line (M005)
    charged_currency     text,
    invoice_line_item_id uuid references public.invoice_line_items (id) on delete set null,
    terms                jsonb not null default '{}'::jsonb,  -- change/cancel terms
    raw                  jsonb not null default '{}'::jsonb,  -- supplier confirmation payload
    booked_by            uuid references auth.users (id) on delete set null,
    booked_at            timestamptz not null default now(),
    cancelled_at         timestamptz,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);
-- A node has at most one live booking (a cancelled/failed one frees it).
create unique index bookings_one_live_per_node
    on public.bookings (node_id) where status in ('pending', 'confirmed');
```

**How it ties together (for M005):**
- **Status mapping:** a live `bookings` row (`pending`/`confirmed`) ⇒ node `booked`;
  `bookings.status='confirmed'` ⇒ node `confirmed`. Node status stays the axis the
  graph/UI read; `bookings` is the detail + audit.
- **Transactions** live on the M005 invoice/payment side (Braintree per D-PAY);
  `bookings.invoice_line_item_id` is the link, so the booking record references the
  money movement rather than duplicating it.
- **Re-price step (flights):** before `approved → booked`, refresh the offer
  (`node_offers` new row); compare the latest `active` amount to the invoice line
  amount; if it differs, surface the **delta** for advisor/traveler confirmation,
  then book against the held amount. `charged_amount` records what was actually taken.
- **Money-gate invariant (restated):** Σ(`charged_amount` of live bookings) ⇔
  Σ(paid invoice lines) — reconciled against the re-priced amount, not the search quote.
</content>
