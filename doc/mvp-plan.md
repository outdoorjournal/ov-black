# MVP Plan — concierge-to-confirmed loop

> The build plan for [mvp.md](./mvp.md). Structured as milestones → slices. Each slice lists
> **goal · deliverables · touches · acceptance** and is sized to land independently behind tests, in the
> style of M001/S01–S09. (The GSD workflow has been retired; this doc is the forward ledger — see
> `doc/decisions.md` / `doc/requirements.md` / `doc/knowledge.md` for salvaged history.)

---

## 0. Baseline — what's already landed

**M001 (S01–S09) shipped the front half of the loop:** invite + magic link, advisor client/Dossier
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

**TravelGraph phase status:** 1–4 landed · **5 (Analyze) & 6 (Fill) core landed behind tests**
(see §8 progress log — `deep`/live-data tier still deferred) · 7 (status gates) & 8 (Meld/Extract)
design-only.

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
| **F1** ✅ | Land the branch onto a `dev` trunk | Land `feat/travelgraph-schema-spine` onto a long-lived **`dev`** branch (the working trunk) and continue **trunk-based dev** there — *not* onto `main`. Confirm `doc/mvp.md` / `doc/mvp-plan.md` reflect reality (GSD retired, history salvaged to `doc/`); CI green. **Deploying `dev`→`main` (F2) is deferred.** | Migrations through 0017 + the TravelGraph phases + B1–B6 are on `dev`; planning docs match the code. |
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
| **B7 — AI-assisted authoring surface** 🔨 *core landed — see §8* | "Build in minutes" — with AI, from a blank canvas. | Command-Center itinerary editor over the promoted `_components/itinerary-graph` views: add nodes from inventory search (B1–B3), inline node edit + cost (B4), drag/drop, **run-analyze + run-fill actions** (B5/B6) with findings + ranked gap-fill proposals rendered inline, accept a proposal → `proposed` node (via the existing `POST /nodes/from-inventory`), approve. Generated-SDK wrappers for **analyze + fill** (templates deferred to B8). | Advisor builds a 5+ node multi-source itinerary from a blank canvas using inventory search + Fill (no templates), runs Analyze to confirm feasibility, and approves it; client view renders it. |
| **B8 — Templates: snapshot & reuse** ⏸ *deferred — no scheduled date (parked until prioritized)* | Turn a great hand-built itinerary into a reusable starting point. | Direction flips from "instantiate-first" to **"build-then-snapshot"**: `POST /itinerary/{id}/snapshot-template` captures an approved itinerary's nodes/edges into `card_templates`/`template_nodes`/`template_edges` (schema already landed, 0015); a Command-Center **template deck** to instantiate a saved template into a fresh itinerary (reuses the existing `services/templates.py` instantiation); generated-SDK wrappers for the template routes. | Advisor snapshots an approved itinerary to a named template, then instantiates it into a fresh itinerary for another traveler; instantiated nodes land `proposed` carrying template provenance (`template_id`/`template_node_id`/`template_version`). |

### M003 — Traveler details + vault (Pillar 4) — *parallel to M002*
*Goal: the traveler supplies party details and stores reusable documents securely.*

| Slice | Goal | Deliverables / touches | Acceptance |
|---|---|---|---|
| **V1 — Party member model** 🔨 *landed — see §8* | Identity-bearing travelers, **remembered across trips**. | Migration **0019** adds a durable, client-scoped `party_members` (full name, DOB, nationality, dietary/medical/mobility, loyalty, emergency contact, actor provenance) + makes `travelers` the per-trip participation edge (`party_member_id`); service + **collaborative** endpoints for all three actors (advisor `/clients/{id}/party-members`, traveler `/me/party-members`, agent `record_party_member` + `/agent/context`); Fill reads structured member constraints; RLS scoped to client + (advisor or linked traveler). | Traveler record persists per member; advisor + traveler + agent all read/write it; the same member reattaches to a second trip without re-entry; agent references party constraints in Fill. |
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
- **Within M002:** B1/B2/B3 (providers) + B4 (cost) + B5 (Analyze) + B6 (Fill) have **landed** behind tests
  (on `dev`); **B7 (AI-assisted authoring) is next** and consumes them (Fill needs Analyze; authoring needs
  both). **B8 (templates) is deferred to an unscheduled future point** — parked until prioritized, not the
  default next slice after B7. The direction is still build-then-snapshot (snapshot a great hand-built
  itinerary into a template rather than instantiate-from-template first); only the *timing* is open.
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

## 7. Suggested next steps

> The original three are largely done: B1–B6 landed behind tests, D-COST + D-ANALYZE are locked (B4/B5),
> and F1 landed the work onto the `dev` trunk (2026-06-23 — see §8). D-FORK/D-PAY remain to lock before M004/M005.

1. **B7 — AI-assisted authoring surface**: the Command-Center editor that finally surfaces B1–B6 to an
   advisor (inventory search · cost · run-analyze · run-fill · approve). Templates are **not** in scope — that's B8.
2. Then pick the next track: **M003** (traveler details + vault, parallel) or **M004/G1** status gates
   (which M005's money gate needs). Deployment (F2/F3) stays deferred until you choose to cut a release.
3. **B8 — Templates: snapshot & reuse** is **deferred (no scheduled date)** — parked until prioritized.
   When picked up: once an advisor can build a great itinerary, add snapshot-to-template + a deck to
   instantiate saved templates. The backing schema (0015) already landed, so it can resume cold.

---

## 8. Progress log (append-only, newest first)

> Running ledger of what's actually landed against the slices above, so any
> session can resume mid-slice without re-deriving state. Each entry: date ·
> slice · what landed · what's tested · what remains · resume hook.

### 2026-06-25 — M003/V2 Traveler details form — **party roster surfaced to traveler + advisor + the itinerary "who's traveling" attach** (web + api-client)

**Decisions (founder, locked at plan time):** the traveler form lives **under
`/basecamp`** (`/basecamp/party`), the established self-scoped traveler home —
not a new `/account` shell. The per-trip "who's traveling" attach is
**advisor-only on the itinerary view**, so the traveler's itinerary view stays
fully read-only (no write token leaked); travelers manage their roster on the
form, advisors attach saved members to a specific trip.

**What landed (pure web + wrapper slice — no apps/api / migration / SDK-regen
change; V1's backend + the generated ops were already in place):**
- **`packages/api-client` wrappers** for the 11 party routes, discriminated
  `{ok,…}` like the rest, with a shared `_parsePartyMemberDetail` parser and
  `PartyMember*` / `ItineraryParty*` type re-exports: traveler `/me/*`
  (`listMyPartyMembers` + create/update/archive), advisor `/clients/{id}/*`
  (same quartet), and per-trip `listItineraryParty` /
  `attachItineraryPartyMember` / `detachItineraryPartyMember`. `tsc` build clean.
- **Traveler `/basecamp/party`** — RSC (`listMyPartyMembers`, BasecampChrome) +
  `PartyManager` (list/add/edit/archive, driven off props, revalidate-on-mutate)
  + a shared **`PartyMemberForm`** (react-hook-form + zodResolver + useFieldArray
  for loyalty programmes; emergency-contact + dietary/medical/mobility; dark
  craft styling) + self-service server actions. A discreet "Your travel party →"
  link added to the two non-first-touch basecamp variants.
- **Advisor completeness + CRUD** — `ClientPartySection` (reuses the same
  `PartyMemberForm`; "via {actor}" provenance) + advisor server actions, slotted
  as a new **Travel party** panel on the command-center client detail page
  (`listClientPartyMembers` added to its `Promise.all`).
- **Advisor "who's traveling"** — a 4th **Party** tab in the itinerary
  `HorizontalView` aside rendering a self-contained `PartyPanel` (takes the
  store's staff creds like ConciergeChat; lists trip party + household roster,
  attaches/detaches durable members, re-renders from the wrapper result). Kept
  mounted alongside Build/Concierge/Client-thread.

**What's tested:** new `apps/web/tests/party/` group (+11) — `PartyPanel`
(loads trip+roster, picker excludes attached, Attach/Remove call the wrappers),
`PartyManager`/`PartyMemberForm` (empty state, required-name blocks submit,
value→payload mapping incl. loyalty + emergency, edit pre-fill/patch, archive),
`ClientPartySection` (roster + provenance, create with client_id, archive).
**Full web suite 103 passed** (was 92); `apps/web` typecheck + `next lint` +
api-client `tsc` clean. apps/api untouched (V1 still green).

**What remains (resume hooks):** **V3** secure vault (S3+SSE-KMS, presigned,
expiry) — untouched, the last M003 slice. Mobile: the itinerary aside (incl. the
new Party tab) stays desktop-only like Build/Concierge; `/basecamp/party` itself
is responsive. **Traveler-initiated** per-trip attach is deferred by the locked
decision (would need a write token on the traveler itinerary route). Live drive
not exercised here beyond mocked unit tests — `ovb` already covers the V1
backend e2e; Playwright can drive `/basecamp/party` + the Party tab through real
Supabase login once wanted. No `scripts/verify-sV2.sh` (UI slice; vitest is the
coverage).

### 2026-06-25 — M003/V1 Party member model — **durable, household-scoped traveler identity; collaborative across advisor + traveler + agent** (backend)

**Decision (founder):** party details are a three-way collaboration — advisor,
traveler (self-service), and the agent (mid-conversation) all maintain them — and
members must be **remembered across trips**. That reshaped V1: instead of
extending the per-itinerary `travelers` table, we split *identity* from
*participation*.

**What landed:**
- **Migration `0019_party_members.sql`** — new `public.party_members`: durable,
  **client-scoped** identity (full_name, date_of_birth, nationality,
  dietary/medical/mobility, loyalty_programs jsonb, emergency_contact jsonb,
  relationship, is_primary w/ a one-active-primary partial unique index,
  `created_by_actor`/`updated_by_actor` enum `party_member_actor`, `recorded_by`,
  `archived_at` soft-delete). `travelers` becomes the **per-trip edge**
  (`+party_member_id` FK, on delete set null). Defense-in-depth RLS (advisor OR
  linked traveler) on party_members + the previously policy-less
  parties/travelers/node_parties. Applied to local DB.
- **Models/schemas** — `PartyMember` + `PartyMemberActor`; `Traveler.party_member_id`;
  Pydantic create/update/detail + nested LoyaltyProgram/EmergencyContact +
  itinerary-party shapes.
- **Service `party_members.py`** — client-scoped CRUD (soft-archive), cooperative
  one-primary demotion, attach/detach a member to an itinerary's default party
  (idempotent), `list_itinerary_party`. App-level authz (the API runs as the
  owner role; RLS is bypassed there).
- **Endpoints** (`routers/party_members.py`) — advisor `/clients/{id}/party-members`
  (require_advisor + owner scoping), traveler `/me/party-members` (require_user,
  resolved from the JWT), per-trip `/itineraries/{id}/party[/members]` authorized
  by access to the itinerary's client. All collapse to 404 (no existence leak).
- **Agent** — active roster added to `GET /agent/context`; new backend-only
  `POST /agent/party-members` (actor fixed to `agent`, whitelisted in
  PUBLIC_PATHS) + a `record_party_member` Strands tool in the onboarding/planning
  bundles; `get_traveler_context` doc notes party data is SHARED (the agent MAY
  confirm it, unlike Dossier/OSINT).
- **Fill** — `_party_constraints` now also reads the linked member's structured
  `dietary` (folded into the allergen set — matched against declared item
  allergens, so preferences stay inert) + `mobility`, so a constraint saved once
  flows into feasibility on every trip.
- **SDKs** — api-client + ovb CLI regenerated; ovb hand-wrappers for the new routes.

**What's tested:** `apps/api` **565 passed** (ruff + mypy clean) incl. new
`test_party_members_service.py` (CRUD, one-primary, archive, client-scoping,
**reuse-across-two-itineraries**, member→Fill constraints, agent-context roster),
`test_party_members_router.py` (advisor/traveler/cross-tenant-404/role-403/attach),
`test_agent_internal_router.py` (context includes members; record stamps
actor=agent). `scripts/verify-sV1.sh` — **15/15** bullets. ovb e2e
(`test_pillar4_details_vault_e2e.py`) — advisor CRUD+attach, **reuse across two
trips**, traveler self-service all pass against local. web typecheck + 92 vitest
green; api-client builds.

**What remains (resume hooks):** **V2** (traveler/advisor UI: `/account/party`
form + "who's traveling" attach on the itinerary view — api-client `index.ts`
wrappers for the party routes still need adding for the web layer). **V3** secure
vault (S3+SSE-KMS, presigned, expiry) — untouched. Agent runtime tool is wired but
only exercised by mocked unit tests; a live agent turn recording a member is not
yet in the e2e (needs a real/`:8011` agent). NB: running the full `apps/api`
integration suite resets local `auth.users` — rerun `scripts/provision-local-users.sh`
before the e2e (done this session).

### 2026-06-23 — B7 follow-up: audience axis verified end-to-end — **0018 applied; full apps/api green; ovb e2e covers private-vs-shared sessions** (test/tooling only)

**Context:** closes resume hooks #1 of the prior B7-audience entry and the e2e
gap it implied — no app behavior change, only the migration apply + test/CLI
plumbing that proves the private advisor↔AI session is isolated from the shared
client thread over the wire.

**What landed:**
- **Migration 0018 confirmed applied** to the local DB (the `session_audience`
  enum + `agent_sessions.audience` are present and recorded in
  `schema_migrations`). Full `apps/api` pytest is green — **550 passed**, ruff +
  mypy clean.
- **ovb CLI SDK regenerated** (`apps/cli/scripts/generate.sh`) to carry
  `audience` on `OpenSessionRequest`/`OpenSessionResponse` + the
  `SessionAudience` enum (the generated half was stale after the B7 backend
  change). Diff is purely additive.
- **`audience` threaded** through `ovb.sdk.open_session` +
  `ovb.agent.Conversation.open` (+ a `Conversation.audience` field). Defaults to
  `traveler`, so every existing call site is unchanged.
- **New e2e** (`apps/cli/tests/e2e/test_pillar3_build_e2e.py`):
  `test_advisor_private_concierge_isolated_from_client_thread` (advisor opens
  both audiences → distinct, per-`(client_id, audience)`-stable sessions) +
  `test_traveler_cannot_open_advisor_audience` (traveler → 404 existence-hiding;
  self-skips without a linked-traveler profile).

**What's tested:** cli offline 50 passed; ruff + mypy clean. e2e against `local`
— both audience tests pass (the traveler-gating one runs for real against the
provisioned `local-traveler`). e2e against the AWS-free `mock` profile — pillar 2
turn loop green/skip and the audience-isolation test passes (gating self-skips,
no `mock-traveler`). NB: the two pillar-2 *turn-content* tests fail under `local`
only because the local agent on `:8080` wasn't running (`upstream_unavailable`) —
environmental, not a regression; they pass/skip against the `:8011` mock agent.

**What remains (resume hooks):** ConciergeChat web vitest (prior entry's hook #3)
is now **closed** — `apps/web/tests/itineraryGraph/conciergeChat.test.tsx` (+4)
covers lazy session-open, the `audience` prop plumbing into `POST /sessions`,
eager `hydrateHistory` replay with turn→message role mapping, and the
no-context inert composer (web suite **92 passed**, typecheck + lint clean).
Disclosure-rule + mobile (hooks #2/#4) remain deferred design calls.
**Next track is a founder call:** M003 (traveler details + vault) vs M004/G1
(status gates, which M005's money gate needs) — per §7.

### 2026-06-23 — B8 templates **deferred to an unscheduled future point** (doc-only)

**Decision (founder):** B8 (Templates: snapshot & reuse) is **no longer the default next slice after B7**.
It is **parked with no scheduled date** until explicitly prioritized. Direction is unchanged
(build-then-snapshot, not instantiate-first) — only the *timing* is open. After B7, the next track is
**M003** (traveler details + vault) or **M004/G1** (status gates), per §7.

**What changed:** doc-only (`doc/mvp-plan.md`): B8 row marked `⏸ deferred — no scheduled date`; §4
parallelization note rewritten (B8 deferred, not "resequenced to follow B7"); §7 next-steps reordered so
M003/M004 precede B8 and B8 is listed as deferred. No code/schema/test changes — migration 0015 already
landed, so B8 can resume cold whenever it's picked up.

**Resume hook:** to revive B8, restore it as a near-term slice in §4/§7 and start from
`POST /itinerary/{id}/snapshot-template` over the already-landed 0015 schema + `services/templates.py`.

### 2026-06-23 — B7 follow-up: advisor session audience — **private advisor chat vs. shared client thread (behind tests; migration apply pending)**

**Decision (founder):** the advisor needs TWO conversations — a PRIVATE advisor↔AI
session the traveler never sees, AND the ability to join the SHARED client thread (a
separate workflow). B7's "Concierge" tab opened the traveler's (idempotent-per-client)
session — i.e. it posted into the client thread. This adds an `audience` axis so the
two are isolated.

**What landed (backend + apps/web; one migration):**
- **Migration `0018_agent_session_audience.sql`** — Postgres-native `session_audience`
  enum ('traveler','advisor'), `agent_sessions.audience NOT NULL default 'traveler'`
  (existing rows backfill to traveler) + a partial index on `(client_id, audience)
  where ended_at is null` for the reuse lookup. Idempotent (0014–0017 idiom).
  **NOT yet applied** — the sandbox blocked the local `psql` apply (couldn't verify
  local vs. the provisioned remote); apply with `supabase migration up`.
- **Model/schema** — `SessionAudience` + `AgentSession.audience` (PGEnum,
  create_type=False); `OpenSessionRequest.audience` (default traveler) +
  `OpenSessionResponse.audience`.
- **Service `open_or_reuse_session(audience=…)`** — reuse keyed per (client_id,
  audience); **a traveler actor is gated to 'traveler'** (advisor audience →
  FORBIDDEN → 404, existence-hiding). Turn + list-turns refuse a traveler on an
  advisor-audience session (defense-in-depth). Default 'traveler' ⇒ /chat, basecamp,
  and the traveler are unchanged.
- **api-client regenerated** — `audience` on the session request/response +
  `SessionAudience`; tsc build clean.
- **Frontend** — extracted `ConciergeChat(audience)` (its own session + message buffer
  + SSE turn loop; lazy session open; `card_proposed` → `proposeNode` onto the shared
  graph; optional prior-turn hydration). The advisor aside is now **3 tabs: Build ·
  Concierge (private, audience='advisor') · Client thread (shared, audience='traveler',
  hydrated)** — all kept mounted so neither conversation is lost on a tab switch.
  HorizontalView's inline SSE wiring moved into ConciergeChat.

**What's tested:** offline (no DB) — `test_agent_router.py` audience plumb-through +
fixed doubles; `test_agent_service.py` traveler-cannot-open-advisor (FORBIDDEN) +
advisor-opens-advisor. Real-DB (run after the migration) — `test_agent_models.py`
audience default + advisor round-trip. **apps/api offline subset green (35), ruff +
mypy clean; web suite 88 + typecheck + lint clean.**

**What remains (resume hooks):**
1. **Apply 0018 + run the full `apps/api` pytest** — blocked here by the sandbox; the
   real-DB tests (model round-trips, agent integration) need the column present.
2. **Disclosure unchanged** — the private advisor session does NOT yet let the agent
   reveal Dossier/OSINT (kept the existing rules deliberately). Revisit if staff want
   candid internal context there.
3. **ConciergeChat web test** — the component is only indirectly covered; add a vitest
   for lazy-open + audience plumbing + hydration mapping.
4. **Mobile** — the 3-tab aside is desktop-only (like the B7 panel).

### 2026-06-23 — M002/B7 AI-assisted authoring surface — **inventory search · analyze · fill · concierge chat wired into the unified graph view (behind tests)**

**Decision (founder):** B7 lands on the **existing unified `/itinerary/[id]` view** — the
Command-Center editor route was already retired (it redirects there; staff edit on the same
surface travelers see, gated by server-resolved `canEdit`). Both AI-assist modalities ship
together: explicit toolbar actions **and** the agent chat SSE.

**What landed (api-client + apps/web; additive — no backend/migration change, the
B5/B6/inventory routes already existed):**
- **`packages/api-client` wrappers** for the previously-unwrapped routes, discriminated
  `{ok,…}` like the rest: `searchInventory`, `createNodeFromInventory`, `startAnalysis`,
  `listAnalyses`, `getAnalysis`, `cancelAnalysis`, `fillGap`; analyze/fill/from-inventory
  models re-exported (`FindingResponse` / `FillProposalResponse` / `AnalysisStatus` / …).
  **No regen needed** — the generated SDK already carried the operations; `tsc` build clean.
- **`itineraryGraphStore` authoring actions** — `runInventorySearch`, `addNodeFromInventory`,
  `startAnalyze` + `refreshAnalysis` (poll), `runFill`, `acceptFillProposal`,
  `dismissFillProposal`, `clearInventoryResults`/`clearFill` + backing state. Reads gate on
  `canEdit`; the two writes (add / accept) gate on `selectEditable` (lock held) — a traveler
  or unlocked advisor can't mutate. Accept = the same `from-inventory` write Add uses.
- **`AuthoringPanel.tsx`** — the "Build" half of the staff aside: keyword + kind inventory
  search → result rows (title/kind/source/price) with Add; "Analyze" → polled findings list
  (severity/category/message, severity-sorted); "Fill a gap" (from/until datetime → tz-aware
  ISO) → ranked proposals (rationale + fits/tight/unconfirmed) with Accept/Dismiss. Craft-clean
  (no spinners/emoji; plain buttons; serif/sans; `#8b2a1d` only for destructive).
- **`HorizontalView`** — the advisor aside is now a **Build / Concierge** tab switcher
  (`AuthoringPanel` vs `ChatPanel`); travelers still get ChatPanel only (unchanged). The
  `handleChatSubmit` **TODO stub is wired**: lazy `createSessionEndpoint` (idempotent per
  client_id) on first submit → `useAgentStream` turn loop → deltas into store messages,
  `card_proposed` → `proposeNode`, `node_updated` → `applyNodeUpdate`, abort-on-unmount.
  `NodeEditPanel` now shows first-class cost (B4) when the node carries it.

**What's tested:** `apps/web/tests/itineraryGraph/authoring.test.tsx` (+11) — store actions
(search populates / traveler-inert; add appends + lock-gated; analyze→findings; fill→proposals;
accept adds+drops; dismiss no-write) and the panel (sections render; search runs + Add enabled
when locked; locked notice + Add disabled without the lock). **Full web suite 88 passed** (was
77); web `tsc` + api-client `tsc` clean; `next lint` clean.

**What remains (resume hooks):**
1. **Mobile** — the authoring panel is desktop-only (the `md:` aside); `MobileDayList` has no
   authoring affordances yet.
2. **Live drive into a running stack** (search a real provider, analyze/fill the Japan seed,
   chat a real agent turn) — needs F2 staging or a local agent; `ovb` (apps/cli) can drive it.
   Not exercised here beyond mocked unit tests; no `scripts/verify-sB7.sh` yet.
3. **Fill desired-kinds + party** in the UI (store/endpoint accept them; the panel sends
   neither yet) and **richer cost** (sum-of-costs; cost on cards, not just the edit panel).
4. **B8 templates** (snapshot & reuse) is the next M002 slice — deliberately untouched.

### 2026-06-23 — F1 (modified) + M002 resequencing — **landed onto a `dev` trunk; templates moved B7→B8**

**Decision (founder):** F1 lands the branch onto a long-lived **`dev`** branch as the working trunk and we
continue **trunk-based dev** there — NOT onto `main`. There's no git remote yet; deployment (`dev`→`main`,
F2/F3 staging) is deliberately deferred. `main` stays the eventual deploy branch.

**What landed:**
- **`dev` branch created at the `feat/travelgraph-schema-spine` HEAD** (28 commits; `main` is a strict
  ancestor, so `dev` carries all of M001 + migrations through 0017 + TravelGraph phases 1–6 + B1–B6). The
  feature branch is preserved; future work commits to `dev`.
- **B7 rescoped + B8 added.** B7 was "advisor authoring incl. a card-template **deck** (instantiate-first)."
  Founder call: **build a great itinerary with AI assistance first, snapshot it to a template later.** So:
  - **B7 → "AI-assisted authoring surface"**: blank-canvas editor + inventory search (B1–B3) + cost (B4) +
    run-analyze (B5) + run-fill (B6) + approve. **No templates.** SDK wrappers for analyze + fill only.
  - **B8 (new) → "Templates: snapshot & reuse"**: `POST /itinerary/{id}/snapshot-template` captures an
    approved itinerary into `card_templates` (schema already landed, 0015) + a deck to instantiate a saved
    template (reuses `services/templates.py`). Direction flips instantiate-first → build-then-snapshot.

**What's tested:** doc-only change (`doc/mvp-plan.md`: F1 row, B7 row, new B8 row, §4, §7, this entry) — no
code touched, so the last recorded suite state stands (B6: `apps/api` 546 passed, `apps/agent` 34 passed).

**Resume hook:** start **B7** — backend is ready (analyze + fill routers live; inventory search +
`POST /nodes/from-inventory` write live). First step is the generated-SDK wrappers for
`/itinerary/{id}/analyses` + `/itinerary/{id}/fill`, then the Command-Center editor surface. (An `apps/cli`
`ovb` operator CLI now exists — see CLAUDE.md — and can drive these flows e2e.)

### 2026-06-22 — M002/B6 AI Fill — **physically-feasible gap-fill service + endpoint + agent tool landed (behind tests)**

**What landed (all `apps/api` + one `apps/agent` tool; net-new files plus
additive, localized edits to the shared main/standard-runner/planning-prompt
seams — no migration: Fill is read-only over the graph):**
- **Shared drive-time model lifted into `services/analyze_runners/common.py`**
  (`MODE_SPEEDS`, `INTERCITY_KM`, `drive_mode_for_distance`,
  `transit_minutes`). The B5 standard runner now imports them (behavior-
  preserving — same numbers, B5 tests unchanged) so **Fill and Analyze share
  ONE feasibility model** and can never disagree about what's reachable.
- **`services/fill.py`** — `fill_gap(session, *, registry, itinerary_id, gap,
  party_id?, analysis_id?, desired_kinds?, min_score=0.5, max_proposals=8,
  ctx?)` → `FillResult(proposals, analysis_id, analysis_age_seconds)`. Typed
  dataclasses `GapWindow`/`GeoPoint`/`FillProposal`. Algorithm: resolve the
  pinned-or-latest **completed** analysis; collect `block`-finding
  `exclude_node_types`; load bracketing nodes via B5's `load_timeline_nodes`
  (reuses its PostGIS lat/lng decode); bias the inventory `search_inventory`
  fan-out to the bracket midpoint + a gap-derived radius; for each item compute
  the **drive-time envelope** (haversine + shared speed caps for prior→cand and
  cand→next) and `fits_in_gap`; drop meals carrying a **party allergen** (hard),
  flag mobility mismatches (soft); **content-adjacency** — down-rank a meal
  butted up against an adjacent meal in time ("you just ate", via a separate
  `_temporal_neighbors` over the nearest *timed* nodes, located or not) below
  the default `min_score`; score (feasible-close-utilized ≈ 1.0,
  too-tight 0.25, geometry-unknown a neutral 0.5); sort, cut `< min_score`,
  truncate. **Honesty:** where bracket geometry is missing a candidate is
  *marked* `feasibility_unknown` (drive times `None`), never asserted feasible
  (handoff §4).
- **`routers/fill.py`** — `POST /itinerary/{id}/fill` (read-only, 200).
  `extra="forbid"` request; typed `FillResponse`. Reuses
  `assert_itinerary_readable` so Fill applies the **exact same auth** as the
  graph read. **No accept route by design** — a `FillProposal` carries
  `inventory_source`/`inventory_id`, so accepting is the existing
  `POST /nodes/from-inventory` write (proposed node lands with provenance via
  the normal `add_node` path). Wired into `main.py`.
- **Agent tool `apps/agent/.../tools/fill.py`** — `fill_gap(gap_start, gap_end,
  desired_kinds?, party_id?, min_score?, max_proposals?)`, POSTs to the pinned
  itinerary's `/fill`; registered in the **planning** bundle (not onboarding/QA)
  + a one-line mention added to both planning rubrics so the agent reaches for
  it on an empty window. Accept stays `propose_card`/`propose_flight`.

**What's tested (2 new files, +22 tests):**
- `test_fill_service.py` — pure: kind-mapping drops graph-structure types,
  radius bounds, `_party_eval` allergen-hard-block / experience-not-blocked /
  mobility-soft, `_build_proposal` scoring (feasible > too-tight > unknown),
  **meal-after-meal down-rank vs activity-after-meal unaffected**,
  unknown-when-no-anchors. Integration (gated on local Supabase, in-test
  `_FakeProvider`): **Tokyo gap returns feasible meal/experience + excludes a
  ~400 km Osaka candidate (the B6 acceptance)**; far candidate surfaced-but-
  flagged at `min_score=0`; **tree-nut allergen drops the matching meal**;
  **a meal right after a lunch node is suppressed by default + resurfaces
  flagged at `min_score=0`**; **`block` finding `exclude_node_types` excludes
  experiences**; no-located-anchors ⇒ `feasibility_unknown`; empty gap ⇒ no
  proposals.
- `test_fill_router.py` — feasible proposal end-to-end (located+timed seed,
  registry swapped via `dependency_overrides`); feasibility-unknown path;
  `extra="forbid"` 422; 404; 401; draft-read gate 403.
- **Full `apps/api` suite green (546 passed**, was 524 at B5; +22). `apps/agent`
  suite green (34). ruff + `mypy --strict` clean; **api-client regenerated**
  (`/fill` in `sdk.gen`/`types.gen`; `generated/` gitignored) + `tsc` build and
  `apps/web` typecheck clean. `scripts/verify-sB6.sh` runs **13 offline
  acceptance bullets green** + an optional staging live probe (soft-skips
  without `STAGING_API_URL`/JWT/`FILL_ITINERARY_ID`).

**What remains (resume hooks):**
1. **Live drive times (deep tier).** Fill uses haversine + per-mode caps like
   standard Analyze; live Google Routes drive time is the deferred `deep` work
   (D-ANALYZE) — wire it the same place B5's deep tier lands.
2. **Richer party constraints.** Today: meal allergens (hard) + a coarse
   mobility tag (soft). Age/dietary/medical from the V1 party-member model
   (M003) aren't consulted yet — extend `_party_eval` + `_party_constraints`
   once V1 lands.
3. **`block`-finding `exclude_node_types` is a forward contract** — the standard
   runner doesn't emit it yet (no weather/availability findings until the
   integration-stub refactor, B5 resume hook 1). Fill honors it the moment a
   runner produces it.
4. **Web "fill this gap" surface** — the advisor action + proposal render is
   **B7** (advisor authoring); deliberately untouched here. Endpoint + agent
   tool are the B6 surface.
5. **Item-supplied durations.** Visit length is a per-kind default
   (`_DEFAULT_DURATION_MIN`); an item that carries its own duration (e.g. an OV
   experience's `duration_days`) isn't read yet — refine when cards need it.

### 2026-06-21 — M002/B5 Analyze (shallow + standard) — **core async Analyze pipeline landed (behind tests)**

**Decision locked:** D-ANALYZE — build **shallow + standard only**; `deep`
(live external data) deferred. The `deep` enum value stays valid but the runner
**downgrades a `deep` request to `standard`** and records `result.degraded_from`
+ an `info` `degraded` finding (honest, doesn't reject a valid enum).

**What landed (all `apps/api` + one migration; net-new files plus additive,
localized edits to the shared `main`/`config`/itineraries-router seams — disjoint
from the B1–B4 provider/cost surfaces):**
- **Migration `supabase/migrations/0017_async_analyze.sql`** (D003 raw SQL,
  idempotent like 0014–0016; the Phase 5 handoff drafted this as `0016` but that
  number was taken by B4 cost — same schema, renumbered). Three Postgres-native
  ENUMs (`analysis_status` queued/running/completed/failed/cancelled,
  `analysis_depth` shallow/standard/deep, `finding_severity`
  info/suggest/warn/block — D020). `public.analyses` (one run: status state
  machine + `scope` jsonb + `inputs_hash` + agent-readable `result` jsonb +
  `external_calls` audit + `started_at`/`completed_at`) and
  `public.analysis_findings` (append-only, `node_id` ON DELETE SET NULL,
  `evidence` jsonb, Fill-shaped `suggested_fix`). Partial indexes for
  list-by-itinerary, the one-in-flight-per-itinerary check, and the cache-hit
  lookup. RLS enabled (no policies — matches 0014 parties posture; middleware +
  draft-read gate are the live perimeter). **Applied to the local DB; idempotent
  on re-run.**
- **Model** `models/analysis.py`: `Analysis` + `AnalysisFinding` + the three
  enums with `create_type=False` PGEnums (migration owns DDL). Re-exported from
  `app.models`; guard test mirrors `test_itinerary_models.py`.
- **Runner foundation** `services/analyze_runners/common.py`: `Finding` /
  `RunOutput` dataclasses (the runner↔service contract, kept here to avoid a
  cycle), `load_timeline_nodes` (read-only graph load honoring scope
  branches/node_ids/party; decodes PostGIS `location` via
  `ST_Y/ST_X(location::geometry)`) + `load_edges`, `haversine_km`, and
  `build_result` (folds findings → flat agent-readable `result`: summary + stats
  + by_category + `result_extra`).
- **Shallow runner** `analyze_runners/shallow.py` (structural, no external
  calls): `time` overlap (adjacent timed pairs → warn), `cyclic` (DFS
  three-colour over `follows` edges → block), `missing_required` (firmed-up
  approved/booked/confirmed node missing `starts_at`, or bookable type missing
  `cost_amount` (B4) → suggest), and the `fuzz_count` planning-maturity score.
  `collect()` is reused by standard.
- **Standard runner** `analyze_runners/standard.py` (physical-feasibility,
  no live traffic): `location_flux` drive-time check over consecutive timed +
  located pairs — `haversine_km / per-mode speed cap + buffer` vs the scheduled
  gap (per-mode caps from handoff §4.2; `drive` escalates urban→intercity past
  100 km; flight legs skipped — schedule governs). `warn` when too tight,
  `block` on a negative gap. Computed legs surfaced in `result.drive_times` for
  Fill (B6) to reuse. **This is the B5 acceptance: an impossible drive-time gap
  yields a `warn` `location_flux` finding with structured evidence.**
- **Service** `services/analyze.py`: `create_queued_analysis` (in-flight
  serialization → returns existing queued/running row; `inputs_hash` cache-hit
  lookup with per-depth TTL 5min/60min/24h; `force_rerun` bypass),
  `run_analysis` (the `BackgroundTasks` entrypoint — opens its OWN
  `get_sessionmaker()` session, drives queued→running→completed, **swallows its
  own exceptions** to `failed`, re-checks status before the completing commit so
  a mid-run cancel wins), `cancel_analysis` (idempotent, scoped to itinerary),
  `get_analysis`/`list_analyses`, `reap_orphaned_analyses` (startup sweep:
  `running` older than `analyze_reaper_max_running_seconds` → `failed`
  /`abandoned_at_restart`), and pure `compute_inputs_hash`.
- **Router** `routers/analyze.py`: four endpoints under
  `/itinerary/{id}/analyses` (POST→202 + schedules the BackgroundTask only for a
  freshly-queued row; GET list; GET detail+findings; POST cancel). **Refactored
  the draft-read gate out of `routers/itineraries.py` into a shared
  `assert_itinerary_readable`** (behavior-preserving — `get_itinerary_endpoint`
  now calls it) and reused it here, so analyze applies the exact same auth as
  the graph read.
- **Wiring** `main.py` (include router + startup reaper inside `lifespan`,
  sequential so a DB failure refuses boot) + `config.py`
  (`analyze_reaper_max_running_seconds`, default 600).

**What's tested (5 new files, +32 tests):**
- `test_analyze_models.py` — enum `create_type=False` + values-match-migration.
- `test_analyze_runners_shallow.py` — time overlap / cycle / acyclic-clean /
  missing_required (approved vs proposed) / fuzz count.
- `test_analyze_runners_standard.py` — **impossible Tokyo→Osaka drive → `warn`
  `location_flux` with evidence (the acceptance)**; feasible walk → no flux;
  flight leg skipped.
- `test_analyze_service.py` — full queued→completed via `run_analysis`; cancel
  before run is a no-op; cancel idempotent / unknown→None; cache-hit +
  force-rerun; in-flight serialization; reaper fails stale running / spares
  fresh; deep→standard downgrade; list ordering; pure inputs-hash.
- `test_analyze_router.py` — 202; detail completed (BackgroundTask done under
  TestClient); list; cancel-completed idempotent; 404s; 401; draft-gate 403.
- Shared raw-SQL seeding helper `tests/_graph_seed.py` (async inserts +
  `seed_itinerary_sync` for the TestClient tests — seeds `approved` itineraries
  so the draft gate is skipped without needing an `auth.users` row).
- **Full `apps/api` suite green (524 passed**, was 492 at B4; +32). OpenAPI
  emits all four routes; **api-client regenerated** (`generated/` gitignored);
  `apps/web` typecheck + api-client `tsc` clean.

**What remains (resume hooks):**
1. **`standard` availability + weather findings** — need the integration-stub
   refactor (handoff §2c: lift `routers/integrations/{weather,flight_status}.py`
   into importable `app/integrations/<provider>.py` client modules; Google
   Places is already a provider via B1). Today standard does drive-time only;
   `availability`/`weather`/`party`-constraint findings are not yet emitted.
2. **`deep` tier** — live drive times (Google Routes — never stubbed), live
   flight status, currency drift. Deferred per D-ANALYZE; runner downgrades for
   now.
3. **Agent prompt + tools** — `start_analysis` / `get_analysis` / `list_analyses`
   / `cancel_analysis` in `apps/agent` (+ the system-prompt "findings are
   agent-private, like Dossier" framing, handoff §7). Endpoints are user-JWT
   (the agent carries it), so no new auth path.
4. **`scripts/verify-sB5.sh`** offline acceptance harness (mirror sB1/sB3) +
   staging live probe.
5. **Web findings render** — the Command-Center analyze action + findings UI is
   B7 (advisor authoring); deliberately untouched here.

### 2026-06-21 — M002/B4 First-class node cost — **cost columns + provider population + sum landed (behind tests)**

**Decision locked:** D-COST — first-class `nodes.cost_amount` + `cost_currency`,
store native currency (one display currency deferred), optional `cost_kind`
(`per_person`|`total`). Unblocks M005 invoicing + the money gate.

**What landed (all `apps/api` + one migration; net-new files plus additive
edits to the uncontended cost surfaces — disjoint from the B1/B2/B3 provider
work):**
- **Migration `supabase/migrations/0016_node_cost.sql`** (D003 raw SQL,
  idempotent like 0014/0015): new `public.cost_kind` ENUM (`per_person`/`total`,
  D020 Postgres-native), `nodes.cost_amount numeric(12,2)` + `nodes.cost_currency
  text` + `nodes.cost_kind`. CHECK `nodes_cost_amount_currency_together`
  (amount ⇔ currency, mirrors `nodes_provenance_complete`); partial index
  `nodes_cost_idx (itinerary_id, cost_currency) where cost_amount is not null`
  for the M005 per-currency SUM. All nullable — non-bookable/idea nodes carry
  no cost. **Applied to the local Supabase DB.**
- **Model** `models/itinerary.py`: `CostKind` enum + `cost_kind_enum` PGEnum
  (create_type=False) + the three columns on `Node` (cost_amount→`Decimal`).
  Exported `CostKind` from `app.models`; D020 regression guard + a value-match
  assertion extended to cover `cost_kind`.
- **Reads/writes** `services/itineraries.py`: `NodeOut` gains the three cost
  fields; the recursive graph CTE selects them; `_snapshot_node` records them
  in node_history (Decimal→str, enum→value); `add_node`/`update_node` persist
  them (cost in the update whitelist); new `_check_cost` both-or-neither guard
  (→ VALIDATION_ERROR/400, suspenders to the DB CHECK, whose name
  `_integrity_detail` now surfaces).
- **HTTP surface** `routers/itineraries.py`: `NodeResponse` carries
  `cost_amount` (Decimal→JSON string) / `cost_currency` / `cost_kind`;
  `CreateNodeRequest` + `UpdateNodeRequest` accept them (advisor edits land via
  PATCH); two `_node_response_from_*` builders de-duplicate the 5 construction
  sites so cost can't drift between endpoints.
- **Provider population** at the `POST /itinerary/{id}/nodes/from-inventory`
  seam (commit 4266e2a): new uncontended module `services/node_cost.py` with
  `cost_from_inventory_item(item)` — maps `InventoryItem.price` → (amount,
  currency, kind); flights/hotels = `total`, OV-style per-person experiences =
  `per_person`; price-less items (Google-Places meals) → no cost. The endpoint
  threads the derived cost into `add_node`. A Duffel flight's amount is the
  agreed cost at proposal — a **repriceable** quote (D024); the transient offer
  lives in `node_offers` (M005), not here.
- **Sum helper** `services/node_cost.py::sum_node_costs(session, itinerary_id,
  *, statuses=None)` → `{currency: Decimal}` grouped by currency over selected,
  non-discarded priced nodes (optional status filter for the M005 money gate;
  per-person amounts summed at face value — party-size expansion is M005).

**What's tested:**
- `tests/test_node_cost.py` — 16 tests: pure `cost_from_inventory_item`
  (flight/hotel=total, experience=per_person, amount_max fallback, 2dp
  ROUND_HALF_UP, no-price/half-price → None), `_check_cost` matrix, and DB
  integration (add_node persists + graph-read surfaces cost; update edits +
  clears; half-specified cost rejected; `sum_node_costs` per-currency grouping
  with discarded/deselected-alt exclusion + status filter).
- `tests/test_nodes_from_inventory.py` — fixture flight now asserts
  `6420.50 USD total` promoted to cost columns + echoed in the response.
- `tests/test_itineraries.py` — PATCH + POST forward cost to update_node/
  add_node; graph-read serializes cost through. `test_itinerary_models.py` —
  enum guard/value tests extended for `cost_kind`.
- **Full `apps/api` suite green (492 passed).** API client regenerated
  (`CostKind` + cost fields present; `generated/` gitignored); `apps/web`
  typecheck clean.

**What remains (resume hooks):**
1. **Web render of cost** — the cost columns flow to the client surface but no
   card component shows a price line yet (B7 advisor authoring + cards).
2. **M005 wiring** — `sum_node_costs` + `node_offers`/`bookings` (D024 draft in
   §8) feed invoices + the money gate; flight re-price-before-book delta.
3. **`scripts/verify-sB4.sh`** offline acceptance harness (mirror sB1/sB3).

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
