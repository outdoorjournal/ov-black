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

**What remains to call B2 fully "done" (resume hooks):**
1. **Flight node → `FlightCardAttrs`.** Map a proposed Duffel `FlightItem` to the
   `flight` card (use `summarize_offer` for iata_from/to, flight_code, cabin,
   depart/arrive) so "flight node renders with cabin/seat/times" holds. Touches
   the proposal path (`propose_card`) / card-attrs — coordinate with whoever
   owns the itinerary-graph files (timezone work in flight). **See the flight-
   offer-lifecycle design note below — the flight card/node must carry the
   offer's `expires_at` + `priced_at`, not just static fields.**
2. **Verify script** `scripts/verify-sB2.sh` against staging (matches M001 discipline).

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
</content>
