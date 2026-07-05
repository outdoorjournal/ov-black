# Advisor Experience — QA Scenarios

Area code: **ADV**. See [README.md](./README.md) for the scenario format, status
legend, and how these map to e2e tests. The build/coverage plan that pairs with
this file is [advisor-plan.md](./advisor-plan.md).

The advisor's day: create a client, stand up an itinerary shell, build it out with
the concierge (with more tools + a private workspace the traveler never sees),
hand-author the odd node, price it, send it over, absorb change requests, and take
payment. The itinerary graph is the single spine underneath all of it — an advisor
mutation and a traveler mutation are the same write path with a different
`actor_kind` and a different set of gates.

> **"P#" below = the CLI/pytest pillar suite** (`apps/cli/tests/e2e/test_pillarN_*_e2e.py`),
> which already exercises most of this loop at the API seam (invite → dream → build
> → detail → fork/reconcile → invoice/book). These scenarios **cite that coverage
> rather than duplicate it**; net-new tests should target the **gaps** each **Notes**
> block names — mostly advisor-facing *UI* that the headless pillars can't drive,
> a few genuine product gaps (AI cover image, deferred invite, bulk-approve), and
> the email/SMTP + live-vendor + payment-gateway boundaries.

## Coverage at a glance

| Scenario | Title | Status | Automated by (layer) |
| --- | --- | --- | --- |
| [ADV-1](#adv-1--advisor-creates-a-client-without-inviting-them-yet) | Create a client without inviting them yet | 🟡 Partial | build-before-sign-in via P1/full-loop (API); *silent create* (invite-later) is a product gap |
| [ADV-2](#adv-2--advisor-stands-up-the-itinerary-shell-brief--rough-timing) | Stand up the itinerary shell (brief + rough timing) | ✅ Automated | `POST /itinerary` brief+timing (API, ITB-1/1B); advisor-driven browser flow to write |
| [ADV-2A](#adv-2a--ai-proposes-and-refines-the-cover-image) | AI proposes & refines the cover image | 🚧 Planned | — (no AI image generation exists; cover is provider/OG/manual only) |
| [ADV-2B](#adv-2b--build-the-travel-party-existing-or-new-with-the-agent) | Build the travel party (existing or new, with the agent) | ✅ Automated | P4 party CRUD + cross-trip reuse + agent `record_party_member` (API); advisor browser to write |
| [ADV-2C](#adv-2c--the-advisors-agent-workspace-has-different-tools--access) | The advisor's agent workspace has different tools + access | ✅ Automated | P3 advisor/traveler audience isolation + `test_modes` tool bundles (API/agent) |
| [ADV-3](#adv-3--advisor-builds-the-itinerary-by-conversation-on-the-travelers-behalf) | Build the itinerary by conversation, on the traveler's behalf | 🟡 Partial | P3 search→propose→approve + full-loop build (API); live grounded turn agent-gated; advisor browser to write |
| [ADV-4](#adv-4--advisor-hand-authors-a-node-in-a-card-like-editor) | Hand-author a node in a Card-like editor (type, links, price) | 🟡 Partial | `POST /nodes` + `/from-inventory` (P3) + `/from-link` OG preview (API); **card-editor UI missing** |
| [ADV-5](#adv-5--advisor-picks-flights-via-duffel) | Pick flights via Duffel | 🟡 Partial | Duffel provider + `search_inventory(flight)` + `propose_flight` (API, P3 flight lane); **flight-picker UI missing**; live creds-gated |
| [ADV-6](#adv-6--advisor-works-with-the-agent-to-analyze-the-itinerary) | Work with the agent to Analyze the itinerary | 🟡 Partial | Analyze/Fill engine (P3); **no agent tool to run Analyze conversationally**; UI trigger to confirm |
| [ADV-7](#adv-7--advisor-sends-the-itinerary-to-the-traveler-with-a-message) | Send the itinerary to the traveler with a message | 🟡 Partial | human thread `POST /threads/{id}/messages` + `HumanThread` UI; **email delivery 🔍 SMTP**; no e2e pillar yet |
| [ADV-8](#adv-8--traveler-reviews-and-chats-with-the-advisor-requesting-changes) | Traveler reviews & chats with the advisor, requesting changes | 🟡 Partial | P5 `request_reconcile` fork loop + human thread (API); @Artemis summon newer, thin coverage |
| [ADV-9](#adv-9--advisor-makes-changes-via-the-agent-respecting-locked-nodes) | Make changes via the agent, respecting locked nodes | ✅ Automated | P5 booked-node immutability + status×actor gate + reconcile (API) |
| [ADV-10](#adv-10--traveler-approves-the-itinerary-at-once-and-sees-the-price) | Traveler approves the itinerary at once, sees the price | 🟡 Partial | itinerary-level approve (P3) + client-sees-approved (full-loop) + cost rollup computable (P3); **bulk node-approve + surfaced total missing** |
| [ADV-11](#adv-11--advisor-invoices-the-trip-traveler-pays-via-braintree) | Advisor invoices the trip; traveler pays via Braintree | ✅ Automated | P6 assemble/pay/money-gate + M005 discount/void + full-loop (API); pre-filled test-card **UI affordance** to add; gateway-unwired 🔍 |

---

## ADV-1 · Advisor creates a client without inviting them yet

- **Status:** 🟡 Partial — the "build before the traveler is in" half works; the "don't
  notify yet" half is a product gap (create currently always emails a sign-in link).
- **Personas:** Advisor
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor is signed in. The target person has no account yet.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar1_invite_e2e.py::test_advisor_adds_client_and_welcome_is_sent` — client + Dossier created atomically, `access_status == "pending"`, `accepted_at is None` (the advisor owns the client before any sign-in).
  - `apps/cli/tests/e2e/test_full_loop_e2e.py::test_loop_invite_to_approved` — the advisor builds, analyzes, fills, and **approves** an itinerary for a still-`pending` client, proving the whole build can precede the traveler engaging.
  - Silent-create (create with **no** welcome sent) — **no test; no code path.**

**Given** an advisor who wants a workspace for a not-yet-contacted client,

**When**
1. the advisor creates the client record (name, contact);
2. the advisor starts building an itinerary against that client **before** the client
   is invited.

**Then**
- the client exists and is owned by the advisor, in a pre-engagement state (`pending`,
  `accepted_at is None`);
- the advisor can create/edit/approve an itinerary for that client while they are still
  `pending` — nothing about the build requires the traveler to have signed in;
- **(target, not yet true)** creating the client does **not** send an invitation:
  no Supabase auth row is minted and no welcome email goes out until the advisor takes
  an explicit, separate "invite" action.

**Notes / gaps**
- ⛔ **Product gap — create and invite are atomic today.** `POST /clients`
  (`apps/api/app/routers/clients.py`, `create_client_with_dossier`) always mints the
  auth identity and sends the welcome sign-in link; there is no "draft client / invite
  later" toggle. The scenario's third `Then` bullet fails as written. Closing it is a
  small, isolated slice: a `notify=false` create path (or a distinct `POST
  /clients/{id}/invite`) plus a "Send invite" affordance on the roster. Tracked in
  [advisor-plan.md](./advisor-plan.md) as **G-INVITE-LATER**.
- ✅ **The build-before-engagement half is real and covered** — `pending` clients are
  fully buildable (full-loop), so an advisor can absolutely "make the itinerary first";
  they just can't currently do it *quietly*.
- Re-sending to a client who never got the mail is [ONB-1B](./onboarding.md#onb-1b--invitee-never-receives-the-email); the deliberate invite itself is [ONB-1](./onboarding.md#onb-1--advisor-invites-a-new-user).

---

## ADV-2 · Advisor stands up the itinerary shell (brief + rough timing)

- **Status:** ✅ Automated (API + shared intake); advisor-driven browser flow still to write.
- **Personas:** Advisor (on a client's behalf)
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** Advisor owns a client (ADV-1). No itinerary yet, or a fresh empty one.
- **Automated by:**
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_forwards_brief_and_timing` — `POST /itinerary` accepts + echoes `brief` + timing.
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_persists_brief_and_timing` — brief + timing round-trip through the serializer.
  - The intake experience is the **same surface** as the traveler's, already specced +
    browser-tested under [ITB-1](./itinerary-builder.md#itb-1--first-run-intake-captures-brief--timing)
    (brief), [ITB-1B](./itinerary-builder.md#itb-1b--fuzzy-window--target-duration) (rough
    window + duration), [ITB-1C](./itinerary-builder.md#itb-1c--flexible-with-a-constraints-note) (flexible note).
  - Advisor-project browser run of the intake (`apps/web/e2e/advisor/…`) — **to write.**

**Given** an advisor with a client but no plan yet,

**When**
1. the advisor creates an itinerary for the client with a title;
2. the advisor writes the free-text brief ("7 days in Italy, anniversary, slow and
   food-forward");
3. the advisor sets rough timing — a *window* ("late September, ~7 nights") rather than
   exact dates.

**Then**
- the itinerary is owned by the advisor and linked to the client;
- `brief` persists as first-class data (not buried in the title);
- `timing_kind == window` with the window bounds in `date_start`/`date_end` and the
  target length in `duration_nights` — machine-usable, so a concrete range resolves later;
- the dated timeline stays hidden until timing is concrete or something is on the board
  ([ITB-6](./itinerary-builder.md#itb-6--timeline-stays-hidden-until-timing-is-concrete)).

**Notes / gaps**
- The three timing modes and their validation are fully specced under ITB; ADV-2 exists
  to assert the **advisor** drives the same intake on a client's behalf (personas differ,
  surface does not — see the ITB-1 note).
- 🔎 The browser half is currently traveler-project only; the advisor-project spec that
  drives the intake as an advisor (own a client → new itinerary → brief + window → saved)
  is the net-new test here.

---

## ADV-2A · AI proposes and refines the cover image

- **Status:** 🚧 Planned — **no AI image generation exists.**
- **Personas:** Advisor ↔ Agent
- **Surface:** Web UI (Playwright) + agent
- **Preconditions:** An itinerary with a brief (ADV-2).
- **Automated by:** — (no code path)

**Given** an itinerary with a brief but no cover image,

**When**
1. the advisor asks the concierge (or a one-click action) to propose a cover image;
2. the advisor accepts it, or nudges it ("warmer, more coastline") and re-rolls.

**Then**
- a cover image is generated/selected from the brief and set on the itinerary ~80% of the
  time with no further input;
- the advisor can refine it conversationally and the itinerary's cover updates;
- the chosen image renders as the itinerary hero across advisor and traveler surfaces.

**Notes / gaps**
- ⛔ **This feature does not exist.** There is no image-generation call anywhere (no
  DALL·E / SD / Bedrock image model). `cover_image` is only ever populated from an
  inventory provider's photos (`services/card_mapping.py`), an OpenGraph `og:image`
  scrape when a link is pasted (`services/link_preview.py`), or a manually pasted URL.
  Cards fall back to a curated `ambient_image` per category.
- **Two build options** (see [advisor-plan.md](./advisor-plan.md) **G-COVER**): (a) a
  *curated* picker — search a stock/Unsplash-style source keyed off the brief and let the
  advisor pick, which matches the "editorial, imagery-forward" design direction and needs
  no generative model; or (b) a true generative `propose_cover_image` agent tool. Decide
  before writing the test — the assertable outcome (a `cover_image` lands on the
  itinerary from the brief) is the same either way, so the scenario is stable across the
  choice, but nothing is drivable until one ships.
- Until then this is 🚧, not 🔍 — it's unbuilt, not merely un-automatable.

---

## ADV-2B · Build the travel party (existing or new, with the agent)

- **Status:** ✅ Automated (API); advisor-project browser run to write.
- **Personas:** Advisor ↔ Agent (with traveler self-service overlap)
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor owns a client with (maybe) an existing party roster.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar4_details_vault_e2e.py::test_advisor_party_member_crud_and_attach_to_trip` — advisor creates a durable member (`created_by_actor == "advisor"`), edits a constraint, attaches it to the trip; the per-trip row resolves back to the member.
  - `apps/cli/tests/e2e/test_pillar4_details_vault_e2e.py::test_party_member_is_remembered_across_trips` — the same saved member attaches to a second itinerary without re-entry ("select from existing").
  - Agent path (efficient add via conversation): `record_party_member` / `update_party_member`
    tools (`apps/agent/src/agent/tools/traveler.py`), available in onboarding + planning
    modes — the "use AI to do this efficiently" affordance.
  - Traveler self-service overlap is [ONB-3](./onboarding.md#onb-3--user-adjusts-preferences-after-onboarding).

**Given** an advisor assembling the travelling party for a trip,

**When**
1. the advisor **selects** existing party members (durable, remembered across trips) and
   attaches them to this itinerary; **and/or**
2. the advisor tells the concierge who's coming ("add her mother, vegetarian, no early
   mornings") and the agent records the new member;
3. per-member detail (dietary, mobility, DOB) is captured.

**Then**
- attached members resolve to durable per-client records — a returning traveller is
  referenced, not recreated;
- an agent-recorded member is stamped with the right `created_by_actor` and carries the
  stated constraints;
- the itinerary's party roster lists exactly the attached members, visible to both the
  advisor and (their own) the traveler.

**Notes / gaps**
- ✅ Both "select existing" and "agent adds new" are covered at the API seam (P4 + the
  traveler tools). The net-new test is the **advisor browser** flow: open a client, attach
  a remembered member + add one via the concierge, see the trip roster update.
- The vault/passport half of P4 is out of scope for the advisor party scenario (it's
  traveler-driven, [ONB-3](./onboarding.md#onb-3--user-adjusts-preferences-after-onboarding)).

---

## ADV-2C · The advisor's agent workspace has different tools + access

- **Status:** ✅ Automated (session isolation + tool bundles at the API/agent seam).
- **Personas:** Advisor vs. Traveler (same client, same graph)
- **Surface:** API seam (CLI/pytest) + agent unit
- **Preconditions:** A client with both a shared (traveler) thread and a private (advisor) workspace.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_advisor_private_concierge_isolated_from_client_thread` — opening `audience="advisor"` and `audience="traveler"` for one client yields two distinct, per-audience-stable sessions; the private workspace never crosses into the shared thread.
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_traveler_cannot_open_advisor_audience` — a traveler asking for the advisor audience is refused with existence-hiding (404, not 403).
  - `apps/agent/tests/test_modes.py` — the planning prompt differs for advisor vs. client, and the tool bundle is mode-appropriate (onboarding/planning/qa expose different tool sets).

**Given** an advisor and a traveler both able to talk to the concierge about the same client,

**When**
1. the advisor opens their **private** advisor workspace (`audience="advisor"`);
2. the traveler opens their **shared** thread (`audience="traveler"`);
3. the traveler tries to open the advisor workspace.

**Then**
- the two are distinct, isolated sessions keyed per `(client_id, audience)` — the
  advisor's private reasoning never appears in the traveler's thread;
- re-opening the same audience returns the same session (idempotent); opening the other
  does not;
- the traveler is refused the advisor audience with a **404** (we don't even confirm it
  could exist);
- the advisor's planning persona speaks to a peer and its tool bundle can execute writes
  the traveler's cannot (moves, drops, status changes), with `actor_kind` stamped
  server-side on every mutation for the audit trail.

**Notes / gaps**
- ✅ Session isolation, the 404 hide, and the differentiated prompts/tools are all covered.
  The "different **access rules**" (advisor can execute a mutation a traveler can't on the
  same node) is asserted structurally by the status×actor gate in [ADV-9](#adv-9--advisor-makes-changes-via-the-agent-respecting-locked-nodes) / P5.
- 🔎 Optional browser add: show the advisor's private aside is not visible in the traveler's
  itinerary view — a thin visibility test, since the isolation itself is API-proven.

---

## ADV-3 · Advisor builds the itinerary by conversation, on the traveler's behalf

- **Status:** 🟡 Partial — build spine ✅ at API seam; the live *grounded* turn is agent-gated; advisor browser flow to write.
- **Personas:** Advisor ↔ Agent
- **Surface:** Web UI (Playwright) + agent (SSE) + API seam
- **Preconditions:** An itinerary shell with a brief (ADV-2).
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_search_inventory_returns_normalized_items` — search dispatches across live provider lanes with provenance (self-skips dark lanes).
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_proposing_an_inventory_node_carries_provenance_and_cost` — a searched item becomes a `proposed` node with source + cost (`POST /nodes/from-inventory`).
  - `apps/cli/tests/e2e/test_full_loop_e2e.py::test_loop_invite_to_approved` — the advisor drives dream → build (drop card, analyze, fill) → approve as one narrative.
  - `apps/cli/tests/e2e/test_smoke_e2e.py::test_chat_turn_persists_and_keeps_graph_sound` — an advisor turn persists and the graph stays sound (invariant, not wording).
  - A live, *grounded-in-the-brief* build turn needs a real tool-using agent — asserted at the API seam / real Bedrock, never on wording. Advisor-project browser turn — **to write.**

**Given** an advisor at the concierge aside of an itinerary with a stated brief,

**When**
1. the advisor asks the concierge to build ("give us three days around Florence, food-led");
2. the agent searches inventory and proposes cards;
3. the advisor accepts/adjusts proposals into the graph.

**Then**
- each turn persists and the graph stays structurally sound (no orphaned nodes/edges);
- proposed inventory nodes carry `source` + `source_id` provenance and, when priced,
  first-class cost;
- the concierge's suggestions are grounded in the brief (asserted at the API seam via the
  trip-brief-in-context tests, not on prose in the browser).

**Notes / gaps**
- ✅ The build **data spine** (search → propose → graph integrity → cost) is thoroughly
  covered by P3 + full-loop. The **turn loop** itself (composer re-enables, reply streams,
  no error row) is the browser assertion to add under the advisor project, mirroring the
  traveler `chat.spec.ts`.
- ⚠️ *Semantic* build quality (the right cards for the brief) is Bedrock-gated and lives at
  the API seam / F3 craft-feel UAT — out of scope for a wording-free browser test.

---

## ADV-4 · Advisor hand-authors a node in a Card-like editor

- **Status:** 🟡 Partial — the write paths (blank, from-inventory, from-link) exist and are
  API-tested; the **card-editor UI is missing.**
- **Personas:** Advisor
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** An itinerary the advisor can write to.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_proposing_an_inventory_node_carries_provenance_and_cost` — the `from-inventory` write path (provenance + cost).
  - `apps/api/tests/…` node-create coverage for `POST /itinerary/{id}/nodes` (blank, typed, priced) and `POST /itinerary/{id}/nodes/from-link` (paste a URL → OpenGraph title/image/description → a node) — both go through the same `add_node` write path (lock/queue + history).
  - The **editor UI** that lets an advisor choose a type, paste a link, and fill price — **no component; no test.**

**Given** an advisor who wants to place a bespoke node the inventory providers don't carry,

**When**
1. the advisor opens a new-node editor that looks like a card;
2. the advisor chooses the node **type** (destination / hotel / experience / meal / note / …);
3. the advisor pastes a link (which pre-fills a title/image/description via preview);
4. the advisor fills the remaining fields, including **price** (amount + currency + kind).

**Then**
- a node is created on the graph with the chosen type and `status = proposed`, authored by
  the advisor (`actor_kind = advisor`);
- a pasted link resolves to a title + cover image + description via the OpenGraph preview,
  degrading gracefully to the bare URL when the fetch fails;
- `cost_amount` + `cost_currency` are stored together (both-or-neither) with the chosen
  `cost_kind` (per-person / total), feeding the cost rollup and later invoicing.

**Notes / gaps**
- 🔎 **The gap is purely UI.** All three server write paths (`/nodes`, `/nodes/from-inventory`,
  `/nodes/from-link`) are built and share the `add_node` lock/queue/history spine; there is
  **no** `NodeEditor`/`CardEditor` component in `apps/web` (a `prototype/cards` visual
  reference exists but is unwired). Building the editor is the work; the API is ready.
  Tracked as **G-NODE-EDITOR** in [advisor-plan.md](./advisor-plan.md).
- Once the editor ships, the browser test drives type-select + paste-link + price → a card
  appears on the board; an API-seam backstop confirms type, `actor_kind`, cost pair, and
  the resolved link snapshot.

---

## ADV-5 · Advisor picks flights via Duffel

- **Status:** 🟡 Partial — Duffel search + propose work at the API seam; **no advisor
  flight-picker UI**; live offers are creds-gated.
- **Personas:** Advisor ↔ Agent
- **Surface:** Web UI (Playwright) + API seam (pytest) + live vendor
- **Preconditions:** An itinerary with a rough route/timing; Duffel provider enabled.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_search_inventory_returns_normalized_items` — the `flight` lane (LAX→HND) returns normalized offers with provenance **when Duffel is live**; self-skips (records the dark lane) when its key isn't configured.
  - Duffel provider two-step offer flow (`apps/api/app/inventory/providers/duffel.py`); agent tools `search_inventory(kinds=['flight'])` + `propose_flight(source='duffel', source_id=<offer>)` (`apps/agent/src/agent/tools/proposals.py`), which re-fetches the offer before it lands (time-boxed quote + segment detail).
  - Advisor flight-picker **UI** (search form → ranked offers → pick → node) — **to write once built.**

**Given** an advisor placing air travel on an itinerary,

**When**
1. the advisor searches Duffel by origin/destination/date (via the concierge or a picker);
2. the advisor picks an offer;
3. the offer is added to the itinerary.

**Then**
- offers come back ranked (by total amount) and normalized, each addressable by
  `source = duffel` + `source_id`;
- proposing an offer re-fetches the live quote and lands a `flight` node carrying the
  segment detail (cabin/seat/times) and first-class cost;
- the graph stays sound and the flight's cost feeds the rollup + invoicing.

**Notes / gaps**
- 🔍 **Live Duffel is credentials-gated** — the flight lane self-skips (and records itself
  dark) where `DUFFEL_API_KEY` isn't set, so CI/local stays green without secrets; real
  offers are an F2 live-vendor concern.
- 🔎 **No dedicated advisor flight-picker screen.** Today flights go on via the concierge
  (`propose_flight`) or a direct API call; a search-form → offer-list → pick UI is the
  net-new surface (**G-FLIGHT-UI**). The scenario is drivable *conversationally* now, as a
  screen later.

---

## ADV-6 · Advisor works with the agent to Analyze the itinerary

- **Status:** 🟡 Partial — the Analyze/Fill engine is built + API-tested; **the agent has no
  tool to run Analyze or read findings**, so it isn't yet a *conversational* step.
- **Personas:** Advisor ↔ Agent
- **Surface:** API seam (pytest) + agent
- **Preconditions:** A built itinerary with timed/located nodes.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_standard_analyze_completes_with_findings` — a standard Analyze reaches `completed` and yields a structured findings list.
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_fill_proposes_feasible_options_for_a_gap` — Fill returns ranked, physically-feasible (or explicitly `feasibility_unknown`) options for an open window.
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_analyze_flags_an_impossible_drive` — **skipped** scaffold: needs a PATCH to inject timed/geo nodes; the flux finding itself is covered by the backend B5 suite.
  - Agent-driven Analyze (`run_analysis` / `get_findings` tools) — **no tool; no test.**

**Given** an advisor with a fleshed-but-imperfect itinerary,

**When**
1. the advisor asks the concierge to analyze the plan for issues, **or** triggers Analyze
   directly;
2. Analyze runs feasibility checks (overlaps, impossible drive-times, missing fields);
3. the advisor asks the agent to Fill an open gap.

**Then**
- Analyze terminates cleanly (`completed`) and returns findings with severity + category +
  evidence + suggested fix;
- an impossible drive-time between consecutive located nodes surfaces as a `warn` flux
  finding (backend-proven; over-the-wire injection is the skipped scaffold);
- Fill returns ranked options that either fit the gap or are marked `feasibility_unknown`
  — never asserted-feasible without geometry.

**Notes / gaps**
- ✅ The Analyze **engine** and Fill are solid at the API seam.
- 🔎 **"Works *with the agent*" is the gap.** There is no agent tool to kick off Analyze or
  read its findings, and no confirmed UI trigger button — the advisor runs it via the API
  today. Add a `run_analysis` + `get_analysis_findings` tool (planning/advisor mode) so the
  concierge can "check this for me and tell me what's wrong," plus an Analyze button on the
  advisor board. Tracked as **G-ANALYZE-AGENT** in [advisor-plan.md](./advisor-plan.md).

---

## ADV-7 · Advisor sends the itinerary to the traveler with a message

- **Status:** 🟡 Partial — the human chat thread is built (the "chat window is working" half);
  email delivery is the 🔍 SMTP boundary; no e2e pillar covers messaging yet.
- **Personas:** Advisor → Traveler
- **Surface:** Web UI (Playwright) + API seam (pytest) + email (🔍)
- **Preconditions:** A built itinerary the advisor is ready to share; a linked traveler.
- **Automated by:**
  - `apps/api/tests/test_agent_summon.py` + messaging router tests — `POST /threads`
    (get-or-create the human thread) and `POST /threads/{id}/messages` (post a message;
    `@Artemis` mention summons the concierge into the thread).
  - `HumanThread.tsx` (`apps/web/app/itinerary/[id]/_shell/`) — poll-based advisor↔traveler
    chat, get-or-creates the thread, renders both parties' messages.
  - E2E pillar for messaging — **none yet** (messaging is M006/PS7, newer than the pillar
    suite); advisor→traveler send is **to write** at both seams.
  - Emailed notification delivery — 🔍, same SMTP boundary as [ONB-1](./onboarding.md#onb-1--advisor-invites-a-new-user).

**Given** an advisor with a finished draft and a linked traveler,

**When**
1. the advisor posts a message to the traveler on the itinerary's human thread ("Hey
   [name]! Here's your 7-day Italy trip — take a look and tell me…");
2. the traveler is notified by email;
3. the traveler opens the itinerary and reads the message in the chat window.

**Then**
- the message persists on the itinerary-scoped human thread with `author_kind = advisor`,
  authorized to the owning advisor + the client (every access failure collapses to 404);
- the traveler's `HumanThread` polls and shows the new message without a reload;
- an email notification is dispatched to the traveler (delivery itself is 🔍 — not
  automatable over HTTP).

**Notes / gaps**
- ✅ The chat window is the drivable surface and works; the net-new e2e is advisor posts →
  traveler's thread shows it (browser both sides, like `preferences.spec.ts`), plus an
  API-seam backstop on the message row + collapsing authorization.
- 🔍 **Email delivery can't cross the HTTP seam** — mark the email bullet 🔍 and cover only
  the dispatch call (that a notification was *enqueued*), never inbox receipt, until the F2
  mailbox harness exists.
- 🔎 **Is there a distinct "Send" action, or is it just a message?** Whether "send the
  itinerary" is a first-class action (that also flips visibility / fires the email) or
  simply the first advisor message on an approved trip is an open product call — settle it
  before writing (see **G-SEND** in [advisor-plan.md](./advisor-plan.md)). Approval-driven
  visibility is separately covered by [ADV-10](#adv-10--traveler-approves-the-itinerary-at-once-and-sees-the-price) / full-loop.

---

## ADV-8 · Traveler reviews and chats with the advisor, requesting changes

- **Status:** 🟡 Partial — both change-request paths exist (human thread + fork/request);
  the @Artemis-in-thread bridge is newer with thin coverage.
- **Personas:** Traveler → Advisor
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** An approved (shared) itinerary the traveler can see.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar5_fork_reconcile_e2e.py::test_traveler_requests_and_advisor_reconciles` — the traveler forks their own itinerary, reworks the alternative, and **requests** a merge (`request_reconcile`), but cannot execute it (403); the advisor sees the request and reconciles.
  - `apps/cli/tests/e2e/test_full_loop_e2e.py::test_loop_detail_to_confirmed_continuation` — the same request→reconcile beat inside the full loop with two real JWTs.
  - Human-thread change request (free-text "can we do Rome instead of Milan?") — messaging
    router + `HumanThread.tsx`; @Artemis summon `test_agent_summon.py`. E2E **to write**.

**Given** a traveler looking at their shared itinerary,

**When**
1. the traveler messages the advisor asking for a change ("can we swap the Milan day for
   more time in Rome?"); **and/or**
2. the traveler forks the plan, reworks the alternative, and requests it be merged.

**Then**
- a free-text request lands on the human thread and the advisor sees it (poll-based, no
  reload);
- a forked change is captured with lineage and a `reconcile_requested_at` marker; the
  traveler **cannot** self-merge (403 — reconciliation is advisor-only);
- the advisor has an actionable request (a thread message and/or a pending fork) to respond
  to in [ADV-9](#adv-9--advisor-makes-changes-via-the-agent-respecting-locked-nodes).

**Notes / gaps**
- ✅ The **fork + request_reconcile** path is well-covered by P5 + full-loop (the structured
  "ask for an alternate" flow).
- 🔎 The **conversational** change request (just message the advisor, optionally `@Artemis`)
  is the thinner side — messaging has unit coverage but no e2e; the browser test (traveler
  posts a request → advisor's thread shows it) pairs with [ADV-7](#adv-7--advisor-sends-the-itinerary-to-the-traveler-with-a-message).

---

## ADV-9 · Advisor makes changes via the agent, respecting locked nodes

- **Status:** ✅ Automated — the status×actor gate and booked-node immutability are fully
  covered at the API seam.
- **Personas:** Advisor ↔ Agent
- **Surface:** API seam (CLI/pytest); advisor browser optional
- **Preconditions:** An approved itinerary with at least one booked/confirmed (locked) node.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar5_fork_reconcile_e2e.py::test_booked_node_is_immutable_to_traveler_and_agent` — a booked node advertises `lock_reason = status_locked`; a traveler/agent edit is refused 409 (`status_locked`); even the advisor must **demote before editing** (409 `demote_before_edit`), after which a field edit succeeds.
  - `apps/cli/tests/e2e/test_pillar5_fork_reconcile_e2e.py::test_direct_booked_flip_is_refused_use_booking_flow` — a direct flip to `booked` is a clean 409 `use_booking_flow` (booking is the money gate's job, never a bare status write).
  - `apps/cli/tests/e2e/test_pillar5_fork_reconcile_e2e.py::test_advisor_diffs_and_reconciles_a_fork` — the advisor accepts a subset of fork changes after an Analyze check while the carried booking is never mutated.

**Given** an advisor absorbing requested changes on an itinerary that already has locked-in
(booked/confirmed) nodes,

**When**
1. the advisor asks the concierge to make the change (move/swap/re-time nodes);
2. the change would touch a booked/confirmed node;
3. the advisor deliberately reworks a still-editable node instead, or demotes a locked one
   first.

**Then**
- editable nodes (idea/proposed/approved) change freely and carry `actor_kind = advisor`;
- a booked/confirmed node is immutable to the agent's non-advisor write path — refused
  409 `status_locked` — and even the advisor gets `demote_before_edit` until they demote;
- booking is reached only through the money gate — a direct `status = booked` write is
  refused `use_booking_flow`;
- reconciling accepted fork changes folds them into the live plan while carried bookings
  stay untouched (invariant-checked).

**Notes / gaps**
- ✅ This is the best-covered advisor scenario — the whole status×actor contract, the
  demotion dance, and reconcile-preserves-bookings all land in P5.
- 🔎 Optional browser add: the advisor board shows a locked node as non-editable (a lock
  affordance), and an attempted edit surfaces the crafted explanation rather than silently
  failing — a thin UI test over the API-proven gate.

---

## ADV-10 · Traveler approves the itinerary at once, and sees the price

- **Status:** 🟡 Partial — itinerary-level approval + client visibility + cost rollup are
  covered; a **single bulk "approve the remaining nodes" action and a surfaced total** are missing.
- **Personas:** Traveler
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** A shared itinerary with several `proposed` nodes and per-node costs.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_advisor_approves_built_itinerary` — approval flips the itinerary `status → approved` (the gate that makes it client-visible).
  - `apps/cli/tests/e2e/test_full_loop_e2e.py::test_loop_client_sees_approved_itinerary` — the traveler sees the approved itinerary on their own surface (`GET /me/itineraries`, `status == approved`).
  - `apps/cli/tests/e2e/test_pillar3_build_e2e.py::test_cost_rolls_up_per_currency` — Σ node cost per currency is computable (the price the traveler should see; `ovb.invariants.cost_totals`).
  - Per-node approval tool `update_node_status` (`apps/agent/src/agent/tools/mutations.py`).
  - A one-action **bulk approve** of remaining `proposed` nodes, and a **surfaced total** in
    the graph/UI — **no endpoint, no UI, no test.**

**Given** a traveler happy with the whole plan,

**When**
1. the traveler approves the itinerary in one action;
2. the remaining `proposed` nodes move to `approved`;
3. the traveler views the trip's total price.

**Then**
- the itinerary is `approved` and visible on the traveler's own surface;
- **(target)** every still-`proposed` node flips to `approved` in that single action (no
  node left behind);
- **(target)** the traveler sees a clear per-currency total (Σ of node costs), computed
  from the same first-class cost the invoicing later charges.

**Notes / gaps**
- ✅ Itinerary-level approval, client visibility, and the fact that a per-currency total is
  **computable** all hold. The data for "see the price" exists.
- 🔎 **Two gaps** (both **G-APPROVE-TOTAL** in [advisor-plan.md](./advisor-plan.md)): (1)
  there's no single "approve all remaining proposed nodes" action — approval is per-node via
  `update_node_status`, or itinerary-status only; the "all at once → nodes approved" invariant
  needs either a cascade on itinerary-approve or a bulk endpoint. (2) No endpoint/graph field
  surfaces the aggregate total, so the traveler-visible price is unbuilt UI even though
  `cost_totals` proves it's derivable. Decide whether approval **cascades** to nodes before
  writing the assertion.

---

## ADV-11 · Advisor invoices the trip; traveler pays via Braintree

- **Status:** ✅ Automated at the API seam (assemble → issue → pay → money gate → confirm →
  reconcile); the only add is a **pre-filled test-card affordance** in the pay UI.
- **Personas:** Advisor → Traveler
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest) + payment gateway
- **Preconditions:** An approved itinerary with priced, bookable nodes; a payment gateway
  wired (Braintree sandbox or the local Fake gateway).
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar6_invoice_book_e2e.py::test_advisor_assembles_invoices_over_booked_nodes` — an invoice over an approved node: `total = Σ lines`, each line references its node.
  - `apps/cli/tests/e2e/test_pillar6_invoice_book_e2e.py::test_traveler_pays_invoice_via_braintree_sandbox` — an issued invoice paid with `fake-valid-nonce` flips to `paid` with a `succeeded` payment carrying a gateway reference.
  - `apps/cli/tests/e2e/test_pillar6_invoice_book_e2e.py::test_money_gate_blocks_unpaid_booking_and_reconciles` — unpaid node → 409 `node_not_paid`; once a covering paid line exists it books, a confirmation → `confirmed`, and Σ(paid lines) ⇔ Σ(booked node costs) balances.
  - `apps/cli/tests/e2e/test_m005_invoicing_e2e.py::test_advisor_invoices_and_collects_payment` — assemble + a signed discount line + void→reversal netting, then issue + pay.
  - `apps/cli/tests/e2e/test_full_loop_e2e.py::test_loop_detail_to_confirmed_continuation` — the traveler pays their **own** invoice inside the full loop.
  - The **pre-populated example card** in the Braintree Drop-in — no UI affordance yet.

**Given** an advisor ready to collect payment on an approved trip,

**When**
1. the advisor creates an invoice and adds a charge line per bookable node (charge = node
   cost), optionally layering a discount;
2. the advisor issues the invoice;
3. the traveler pays it, using the pre-populated Braintree sandbox test card.

**Then**
- the invoice total equals Σ of its line items, and each charge line references the node it
  pays for;
- issuing then paying with a tokenized nonce flips the invoice to `paid` with exactly one
  `succeeded` payment and a recorded gateway reference;
- the money gate then permits booking the covered node (an unpaid node is refused 409
  `node_not_paid`), a supplier confirmation advances it to `confirmed`, and reconciliation
  balances (Σ paid lines ⇔ Σ booked node costs).

**Notes / gaps**
- 🔍 **Gateway-unwired self-skips** — where no Braintree keys are set the local Fake gateway
  stands in (`fake-valid-nonce` works for both), and against a target with **no** gateway
  the pay step skips (`payments_unconfigured`) rather than false-failing.
- 🔎 **The "pre-populated for now, to make it easy" ask is UI-only.** The Drop-in accepts the
  test nonce; add a dev/demo affordance that pre-fills the sandbox card (or a one-click "pay
  with test card" button) so a demo flows without typing card numbers (**G-TESTCARD**). The
  payment *contract* is fully green already.
- 🔎 **Auto-populate an invoice from approved nodes** — today the advisor adds lines by hand;
  an "invoice all approved bookables" convenience is optional follow-on, not a gate.

---

## Where these land in the suite

Most of ADV is already **green at the API seam** through the pillar suite; the net-new work
is (a) advisor-**project** Playwright specs (`apps/web/e2e/advisor/…`) that drive the real
screens, and (b) a handful of genuine **product gaps** before some scenarios can be asserted
as written. Both are enumerated, prioritised, and cost-noted in the companion
[advisor-plan.md](./advisor-plan.md).
