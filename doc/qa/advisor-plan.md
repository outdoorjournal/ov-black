# Advisor Experience — codebase analysis & coverage plan

> Companion to [advisor.md](./advisor.md) (the **scenario spec**, ADV-1…ADV-11). This
> doc is the **engineering** side: what the codebase already delivers for each advisor
> workflow, the product gaps that block a scenario being asserted as written, and a
> prioritised plan for closing coverage — in the [mvp-plan.md](../mvp-plan.md) house
> style (goal · gap · plan · tests). Unlike the scenario spec, this is a working plan,
> not an invariant contract.
>
> **Bottom line (handoff):** ~two-thirds of the advisor loop is already **green at the
> API seam** via the pillar suite (P1–P6). Wave 1 (advisor-project Playwright over the
> built spine) is shipped, and of the original **six product gaps**, **G-INVITE-LATER**
> (ADV-1), **G-NODE-EDITOR** (ADV-4, the card composer), **G-APPROVE-TOTAL** (ADV-10,
> now a full `draft → proposed → approved` state machine — advisor proposes, traveler
> approves node-by-node or all-at-once, with surfaced totals), **G-ANALYZE-AGENT**
> (ADV-6, Analyze as a conversational step — a board **Analyze** button plus `run_analysis`
> / `get_analysis_findings` agent tools over the built engine) and **G-BILLING-COCKPIT**
> (ADV-11 — the advisor's invoice issue/manage flow: a per-currency reconciliation glance
> that surfaces the **uninvoiced remainder**, coverage-aware charging + "Bill all uninvoiced",
> a guided **supplemental** for the delta after issue, per-card coverage, plus the demo
> test-card pay affordance) are **closed**. Outstanding: **G-COVER** (ADV-2A) plus the deferred
> **advisor-private Collection** slice. Nothing here is a rewrite; it's finishing UI + a few
> tools on top of a built spine.

## §0. Method

Two parallel sweeps fed this: a read of the **pillar e2e suite**
(`apps/cli/tests/e2e/test_pillar{1..6}_*_e2e.py`, `test_full_loop_e2e.py`,
`test_m005_invoicing_e2e.py`) for what's proven over the wire, and a **capability map**
of `apps/api` / `apps/web` / `apps/agent` for what's implemented behind those tests.
Statuses below are **built** (code + API test), **partial** (API path built, UI or agent
seam missing), or **gap** (no code path — a product decision precedes the test).

## §1. Capability map (what exists today)

| # | Workflow (ADV-#) | Status | Where it lives | The gap |
| --- | --- | --- | --- | --- |
| 1 | Create client w/o inviting | **built** | `POST /clients` `notify` flag → `create_client_with_dossier`; roster "Send invite" (`resend-welcome`); P1; `onboarding-invite.spec.ts` (ADV-1) | ✅ silent-create + invite-later shipped (G-INVITE-LATER closed) |
| 2 | Itinerary shell (brief+timing) | **built** | `POST /itinerary` (`routers/itineraries.py`), timing 0033; ITB-1/1B/1C; `itinerary-intake.spec.ts` | ✅ advisor browser intake **and** "New itinerary for this client" affordance shipped (G-ITIN-FOR-CLIENT closed) |
| 2A | AI cover image | **gap** | `cover_image` only from provider photos / OG scrape / manual paste | **no image generation/curation anywhere** |
| 2B | Travel party (existing/new) | **built** | `party_members` routes + agent `record_/update_party_member`; dashboard `PartyPanel` trip-attach; P4; `travel-party.spec.ts` | ✅ advisor browser (add + trip-attach) shipped; concierge-add agent-gated |
| 2C | Advisor≠traveler agent access | **built** | audience isolation (`open_or_reuse_session`); `agent/tools/__init__.py` mode bundles; P3 + `test_modes` | — (optional visibility browser test) |
| 3 | Build by conversation | **partial** | search→propose→approve (P3, full-loop); `propose_card`; `concierge.spec.ts` | ✅ advisor browser turn-loop shipped; live grounding still agent-gated |
| 4 | Hand-author a node | **built** | `POST /nodes`, `/from-inventory` (P3), `/from-link` OG preview; summonable `CardComposer` (Studio / Collection / timeline-slot) + live preview; `authorNode`; `node-editor.spec.ts` (ADV-4) | ✅ composer shipped (G-NODE-EDITOR closed): typed+priced, paste-link, create-at-slot scheduling; advisor-private Collection + link-card pricing are follow-ups |
| 5 | Duffel flights | **partial** | `inventory/providers/duffel.py`; `search_inventory`+`propose_flight`; P3 flight lane | **no flight-picker UI**; live creds-gated |
| 6 | Analyze w/ the agent | **built** | `routers/analyze.py` (P3 analyze+fill); board **Analyze** button (`itinerary-graph-tool-analyze` → `AnalyzeSection` modal); `run_analysis`+`get_analysis_findings` planning-mode tools; `test_analyze_tools`/`test_modes` | ✅ Analyze is now a conversational step (G-ANALYZE-AGENT closed); live turn Bedrock-gated per §4 |
| 7 | Send + message (email+chat) | **partial** | `routers/messaging.py` `/threads`; `HumanThread.tsx`; `test_agent_summon.py` | **no e2e**; email 🔍; "send" as first-class action undecided |
| 8 | Traveler requests changes | **partial** | `request_reconcile` (P5); human thread + @Artemis | conversational-request e2e; @Artemis thin |
| 9 | Advisor changes, locked nodes | **built** | status×actor gate, `demote_before_edit`, reconcile (P5) | — (optional lock-affordance browser test) |
| 10 | Propose + approve + see price | **built** | `draft→proposed→approved` (migration `0039`): advisor `POST …/propose` + `…/reopen`; traveler-writable `…/approve` cascades + per-node derive; per-currency `totals`; DashboardView Approval section + StaffToolbar + card-detail approve; `test_itinerary_lock`/`test_itineraries` + `approve.spec.ts` (advisor + traveler-flows) | ✅ propose→approve state machine shipped (G-APPROVE-TOTAL closed): advisor proposes, traveler approves node-by-node or all-at-once, totals surfaced |
| 11 | Invoice + Braintree pay | **built** | `routers/invoices.py`, `payments/braintree_gateway.py`; P6 + M005 + full-loop; **billing cockpit** (`InvoicePanel` reconciliation strip + coverage-aware charging + supplemental via `reconcileBilling`), per-card coverage (`MoneyFacet`), env-gated test-card pay; `dashboardModel`/`invoicePanel`/`payInvoiceView` tests + `e2e/advisor/invoicing.spec.ts` | ✅ advisor issue/manage flow + demo pay shipped (G-BILLING-COCKPIT closed); live pay gateway-gated 🔍 |

**Orientation (surfaces):** `command-center/*` = advisor-only (roster, new client, client
detail; `require_advisor`). `basecamp/*` = traveler self-serve (`/me/*`). `itinerary/[id]/*`
= **shared** advisor+traveler, role-gated server-side. The agent runs the same session for
both, split by `audience` (`traveler` shared vs `advisor` private) and `actor_kind` stamped
server-side.

## §2. Product gaps (decision precedes test)

Originally six gaps blocked a scenario being asserted *as written*; **G-INVITE-LATER,
G-NODE-EDITOR, G-APPROVE-TOTAL, G-ANALYZE-AGENT, and G-BILLING-COCKPIT (née G-TESTCARD) are
now closed** (G-APPROVE-TOTAL as a full `draft → proposed → approved` state machine — see
below). That leaves **G-COVER** as the last product gap (plus the deferred advisor-private
Collection slice).

### ✅ Closed: G-INVITE-LATER — silent client create (ADV-1)
- **Shipped:** `POST /clients` now carries `notify: bool = true`. When false the create
  persists the client + Dossier but mints **no** Supabase auth row and sends **no** welcome
  email — a new `clients.invited_at` (migration `0038`) stays NULL, so `access_status`
  derives a third state, **`uninvited`** (→ `pending` once invited → `active` once signed
  in). The invite-later action reuses `POST /clients/{id}/resend-welcome`, which now stamps
  `invited_at` on first send (flipping `uninvited` → `pending`); a re-send is idempotent.
  The atomic path stays the default, so ONB-1/P1 are un-regressed.
- **Browser:** the New Client form gained a "Send a welcome email now" checkbox (on by
  default; uncheck = silent create); the roster's `InviteActions` shows **Send invite** on
  `uninvited` rows and **Nudge** on `pending`, and all three `InvitePill`s render the
  `uninvited` state.
- **Tested:** API — `test_clients_service.py` (notify=false mints no auth row, one commit,
  `invited_at` NULL) + `test_resend_welcome.py` (first-invite stamps `invited_at`; re-send
  writes nothing) + `test_clients_router.py` (`uninvited` renders). Browser —
  `onboarding-invite.spec.ts` ADV-1 drives silent create → **Uninvited** → **Send invite**
  → **Pending**, backstopped at the API seam (`invited_at` null → set).

### G-COVER — AI (or curated) cover image (ADV-2A)
- **Goal:** a cover image lands on an itinerary from its brief, ~80% hands-off, refinable.
- **Today:** nothing. `cover_image` is provider photos / `og:image` / manual URL only.
- **Plan — decide first:** (a) **curated picker** — query a stock source (Unsplash-style,
  keyed off the brief), advisor picks; matches the editorial imagery-forward design
  direction, no generative model, cheaper/safer; or (b) **generative** `propose_cover_image`
  agent tool. Recommend (a) for the MVP demo. Either way, persist onto a new
  `itineraries.cover_image` field and render as the hero.
- **Size:** M. **Touches:** a cover service, `itineraries` model/migration, itinerary header UI.
- **Test to add:** the assertable outcome is choice-independent — after the action, the
  itinerary carries a `cover_image` derived from the brief; browser shows the hero.

### ✅ Closed: G-NODE-EDITOR — advisor card composer UI (ADV-4)
- **Shipped:** a summonable **`CardComposer`** overlay (store-driven, opened via a new
  `ComposerControl` context from the shell) with two shapes mapped 1:1 to the existing write
  paths via a new `itineraryGraphStore.authorNode` action: **Details** (type + name + price
  amount/currency/`per_person|total`) → `POST /nodes` (status `proposed`), and **Link**
  (paste a URL) → `POST /nodes/from-link` (server-fetched OG preview, degrading to the bare
  URL). Writes gate on the edit lock (`selectEditable`). A **live card preview** (the real
  `CardShell`+`CardBody`) updates as the advisor edits. Pure frontend — no API change (only
  re-exported `CostKind`).
- **Three entry points** (per the placement discussion): the Studio "Add a card" button and
  the Collection add affordance → compose into the (shared) Collection; an **empty timeline
  slot** click → the composer pre-set to that day + minute (Outlook-style), landing the card
  **scheduled** there (`authorNode`'s `schedule` → `starts_at` + 1h default). The create-slot
  layer sits under the cards (empty space only) and is advisor-lock-gated.
- **Deferred (product decision):** an **advisor-only** Collection needs a node
  `audience`/visibility column + filtering it from every traveler-facing read (graph API,
  Collection, agent context). Phase 1 ships shared-Collection + scheduled; advisor-private next.
- **v1 boundary:** price applies to the **Details** shape only (the `updateNode` wrapper's
  patch type carries no cost, so pricing a link card is deferred).
- **Tested:** `apps/web/e2e/advisor/node-editor.spec.ts` (ADV-4) — three composer flows
  (typed+priced via Studio with a live-preview assertion → Collection; pasted link via the
  Collection affordance → `web` node; empty timeline-slot click → **scheduled** node with
  `starts_at`), each API-seam-backstopped. `actor_kind=advisor` is Pillar 3's job.

### ✅ Closed: G-ANALYZE-AGENT — Analyze as a conversational step (ADV-6)
- **Goal:** the advisor can ask the concierge to analyze the plan and hear what's wrong.
- **Shipped (two halves, both now green):**
  - **Board button:** the horizontal board's **Analyze** tool button
    (`itinerary-graph-tool-analyze`) opens an `AuthoringModal` hosting `AnalyzeSection` —
    it runs the analysis, polls until terminal, and lists findings by severity. (Landed in the
    authoring-harmonization commit alongside the unified **Add** composer.)
  - **Agent tools:** `run_analysis` (queues `POST …/analyses` with depth + `force_rerun`) and
    `get_analysis_findings` (reads a run — defaulting to the latest — and returns
    `{status, summary, findings}`, dropping the noisy `result`/`external_calls`) in
    [`agent/tools/analyze.py`](../../apps/agent/src/agent/tools/analyze.py), registered in the
    **planning** bundle and taught in both planning rubrics (advisor + client) so "check this
    plan for conflicts" actually fires the tools. Both are read-only over the graph, gated by
    the same itinerary-read authorization as `get_itinerary`.
- **Tested:** agent — `test_analyze_tools.py` (request shape, latest-run default, empty-history,
  unpinned guard) + `test_modes.py` (the planning bundle includes both tools; onboarding/Q&A
  don't). API path already covered by P3.
- **Boundary:** the *live conversational turn* (a real agent invoking the tool and narrating
  findings) is Bedrock-gated and asserted against a real agent, never on browser wording — same
  posture as ADV-3 / §4.

### ✅ Closed: G-APPROVE-TOTAL — propose → approve + surfaced price (ADV-10)
- **Goal:** the advisor presents a finished plan; the traveler approves it (node-by-node or all
  at once), remaining `proposed` nodes → `approved`, and sees a total.
- **Decision (made, with the user):** the itinerary carries a small **`draft` → `proposed` →
  `approved`** state machine. The advisor's finalize gesture is **"propose"** (named to avoid the
  existing editor-lock + node status-lock meanings of "lock"); the whole itinerary then follows
  the same `proposed → approved` arc as its nodes. Itinerary-level `approved` is **derived** from
  the nodes ("stateless" rollup), not a separate gesture.
- **Shipped:**
  - **State + migration:** `ItineraryStatus` gained `proposed` (migration `0039`, + `proposed_by`/
    `proposed_at`). Two advisor-only endpoints — `POST …/propose` (draft→proposed, freezes the
    build) and `POST …/reopen` (proposed→draft, the escape hatch).
  - **Approval is the traveler's:** `POST …/approve` relaxed from advisor-only to **writability-
    gated** (owner/creator/advisor); accepts a draft **or** proposed itinerary and cascades
    remaining `proposed` nodes → `approved`. Per-node approve (`update_node`) **derives** the
    itinerary to `approved` once the last `proposed` node clears. The advisor keeps approve-all
    (pending-client / full-loop stays green).
  - **Price:** `GET /itinerary/{id}` surfaces `totals: {currency: amount}` via `sum_node_costs`;
    threaded through the `getItinerary` wrapper → store → UI.
  - **UI:** a DashboardView **Approval** section (advisor Propose/Reopen · traveler "Approve all" ·
    per-currency total · approved state), the timeline **StaffToolbar** Propose/Reopen, and a
    per-node **"Approve this"** on the card-detail route + timeline expanded card. `selectEditable`
    now freezes the build on `proposed` (soft freeze, reversible via Reopen).
- **Tested:** API — `test_itinerary_lock` (propose/reopen/approve-from-proposed/per-node derive/
  cascade) + `test_itinerary_lock_routes` (owner-approves 200 / non-writer 403 / propose+reopen
  routes) + `test_itineraries` totals. Web — `store.test.tsx` (the propose/reopen/approve gates +
  totals threading) + browser `e2e/advisor/approve.spec.ts` (advisor proposes/reopens) and
  `e2e/traveler-flows/approve.spec.ts` (traveler approve-all + card-by-card → derived approved).
- **Follow-ups (scoped out, non-blocking):** (1) the **soft freeze** on `proposed` is UX-level —
  `selectEditable` steps the advisor's build affordances back (reversible via Reopen), *not* a hard
  API write-lock (a hard lock would also block the traveler's approval writes, which share the
  `update_node` path). (2) The legacy **command-center `DraftItineraryEditor`** keeps its direct
  "Approve" (draft→approved) as the advisor's approve-on-behalf shortcut — its S08 acceptance tests
  are untouched; aligning it to "Propose" is a tidy-up, not a gate. (3) `/me/itineraries` still lists
  `draft + proposed + approved`; if a `proposed` plan should read differently in the traveler's
  basecamp listing, that's a small copy tweak.

### ✅ Closed: G-BILLING-COCKPIT — advisor invoice issue/manage + demo pay (ADV-11)
- **Reframe (with the user):** "add a pre-filled test card" (the old **G-TESTCARD**) was the
  wrong end — payment presupposes an *issued* invoice, and the advisor had no coherent way to
  **get there** or see what an invoice covered. The panel's mechanics existed (`InvoicePanel`:
  create/charge/adjust/void/issue) but the advisor was flying blind on the three real worries:
  *what does this invoice cover · what changed since I issued · how do I see it without losing
  my mind*. So the slice grew into the billing cockpit; the test-card button rides along.
- **Shipped:**
  - **Reconciliation glance** — a pure `reconcileBilling` in [`dashboardModel.ts`](../../apps/web/app/itinerary/[id]/_shell/dashboardModel.ts)
    joins the two numbers the dashboard never reconciled: **trip total** (the graph `totals`)
    vs **invoiced / paid / outstanding** (the `rollupInvoices` ledger), and adds the missing
    **uninvoiced remainder** (amount + item count). Rendered as the `invoice-reconcile` strip
    atop `InvoicePanel`, grouped by currency.
  - **Coverage-aware charging** — coverage is derived from each `charge` line's `node_id`
    (reversed lines fall back to uninvoiced); the charge picker only offers genuinely-uninvoiced
    nodes (no silent double-billing — the API had **no** guard), and **"Bill all uninvoiced"**
    seeds the first/balance invoice in one click.
  - **Guided supplemental** — once an invoice is issued, chargeable nodes that no invoice covers
    surface an `invoice-supplemental` prompt → a pre-seeded **Supplemental** draft over exactly
    the delta.
  - **Per-card coverage** — the card-detail `MoneyFacet` distinguishes *priced-but-not-yet-
    invoiced* (an advisor to-do) from costless, and deep-links a charged node to its invoice.
  - **Pinned to the itinerary (its own Rail destination)** — **Invoices** is a first-class left-
    Rail noun (`/itinerary/[id]/invoices` → `InvoicesView`; advisor-only, same role gate as
    Studio), a proper full-page CRUD surface for managing several invoices + their lines — better
    than a summoned modal. Still available on the dashboard's "Trip management → Invoices" tab.
    (Post-harmonization the timeline aside was dropped, orphaning invoicing on the itinerary page;
    this restores it as a dedicated destination.)
  - **Decoupled from the graph edit-lock** — invoicing now gates on advisor **role**
    (`canManage`), not `selectEditable`. The invoice API is advisor-only and admits writes
    "regardless of itinerary status" (financial data), so requiring the draft-only *build* lock
    was wrong — it blocked invoicing an **approved** trip and made a dedicated route unusable
    (unheld lock → read-only). Travelers who reach the surface see invoices read-only.
  - **Demo pay** — an env-gated (`OVB_DEMO_TEST_CARD` / `NEXT_PUBLIC_DEMO_TEST_CARD` →
    `demoTestCard()`) "pay with test card" button in `PayInvoiceView`. The env var holds the
    sandbox card (e.g. the Braintree Visa `4111111111111111`); the button shows it masked
    (`····1111`) and submits the sandbox `fake-valid-nonce` directly (a raw PAN isn't a nonce),
    settling via the local Fake gateway. Off by default (gitignored `.env.local`); never prod.
- **Design note (deviation):** a **%-of-trip deposit** shortcut was dropped — a deposit
  *adjustment* and node-coverage billing are incompatible money models (a 30% deposit *plus*
  later billing all nodes = 130% invoiced). One coherent model — invoices partition the trip's
  nodes — is what keeps the reconciliation honest; a real "deposit" is charging a subset of
  nodes. (A money-split deposit that tracks its own remainder is a possible follow-up.)
- **Tested:** unit — `dashboardModel.test.ts` (`reconcileBilling`/`coverageByNode`/`isChargeable`:
  remainder math, reversed-line fallthrough, supplemental gating), `invoicePanel.test.tsx` (strip,
  bill-all seeds+charges, supplemental seeds the delta), `payInvoiceView.test.tsx` (test-card off
  by default; on → sandbox nonce → paid, no drop-in tokenizer). Browser —
  `e2e/advisor/invoicing.spec.ts` (seed → approve nodes → open **Invoices** from the left Rail
  (its own route, no edit lock) → reconcile glance → bill-all → issue, API-seam-backstopped; then
  the demo **pay with test card** → paid receipt) — **green against the live stack, demo pay
  included** (with `NEXT_PUBLIC_DEMO_TEST_CARD` set + the local Fake gateway).
- **Boundary:** the live Braintree drop-in tokenizer / real settlement stays gateway-gated per §4 — the
  browser drives the *demo* nonce path; the drop-in tokenizer is never exercised headless.

**Also flagged, not gating:** **G-SEND** (is "send the itinerary" a first-class action that
flips visibility + fires email, or just the first advisor message on an approved trip? —
settles ADV-7's shape); and **G-FLIGHT-UI** (a dedicated advisor flight-picker screen vs.
picking via the concierge — ADV-5 is drivable conversationally without it). Both are product
calls, not blockers.

**✅ Closed: G-ITIN-FOR-CLIENT** — the command-center client detail page's Itineraries panel
now carries a **"New itinerary"** action (`NewItineraryButton` →
`startItineraryForClientAction`) that creates a `client_id`-bound itinerary via the existing
`POST /itinerary` and drops the advisor into its first-run intake — the advisor-side
counterpart to the traveler's `startNewItinerary`. `itinerary-intake.spec.ts` now drives the
whole flow (create + intake) in the browser and seeds only the client, so the binding is the
affordance under test rather than seeded state.

## §3. Coverage plan (waves)

Ordered by leverage: prove what's built in the browser first (cheap, high-signal), then the
scenarios that need a small product gap closed, then the boundary-limited ones.

**Wave 1 — advisor-project browser specs over already-built spine (no product work).**
Specs live under `apps/web/e2e/advisor/` (an advisor Playwright project already exists —
`command-center.spec.ts`, `onboarding-invite.spec.ts`). Seed helpers for the advisor path
(create a client, create a client-bound itinerary, seed/read party) are in
`e2e/support/api.ts`. **Status: the three core specs are shipped and green locally.**
- ✅ **ADV-2** — `itinerary-intake.spec.ts`: own a client → **New itinerary for this client**
  → brief + rough window → saved. Fully browser-driven now that **G-ITIN-FOR-CLIENT** is
  closed: seeds only the client, clicks the client page's "New itinerary" affordance, drives
  the advisor-audience intake, and backstops brief + window + the client binding the browser
  action created.
- ✅ **ADV-2B** — `travel-party.spec.ts` (two facets): advisor **adds** a durable member on
  the client page (stamped advisor) **and attaches** a remembered member to the trip via the
  dashboard's "Add from household" → "On this trip". (Correction to the map: a per-trip attach
  UI **does** exist — the itinerary dashboard's `PartyPanel`. Concierge-add stays agent-gated.)
- ✅ **ADV-3** — `concierge.spec.ts`: a real build turn from the advisor's **private**
  "Concierge" tab; the turn loop asserted structurally (live agent required — run live-agent
  specs isolated / `--workers=1` so they don't contend with the traveler chat turns).
- **ADV-9** (optional, not yet written) — a booked node shows non-editable; an attempted edit surfaces the crafted reason.
- **ADV-2C** (optional, not yet written) — the advisor's private aside is absent from the traveler's itinerary view.

These lean on P1/P3/P4/P5 as the API-seam backstop and add the *experience* proof the
headless pillars can't give. **Two map corrections surfaced while automating** (both folded
into §1/§2): the advisor itinerary "home" is the **`DashboardView`** (trip title, money,
trip-party, trip-management — not the traveler's "blank canvas" timeline), and it carries the
per-trip party-attach UI ADV-2B needed.

**Wave 2 — close a small gap, then assert the scenario.** One product slice each, then its test:
- ✅ **G-INVITE-LATER → ADV-1** — shipped (see §2): `notify` opt-out + `uninvited` state +
  roster "Send invite"; `onboarding-invite.spec.ts` ADV-1 drives it in the browser.
- ✅ **G-NODE-EDITOR → ADV-4** — shipped (see §2): summonable `CardComposer` (Studio /
  Collection / empty timeline-slot) + live preview + create-at-slot scheduling, via
  `authorNode`; `node-editor.spec.ts` drives all three flows in the browser.
- ✅ **G-APPROVE-TOTAL → ADV-10** — shipped (see §2): `draft → proposed → approved` state
  machine (advisor Propose/Reopen, traveler Approve-all + per-node derive, surfaced `totals`);
  `approve.spec.ts` drives both the advisor and traveler halves in the browser.
- ✅ **G-ANALYZE-AGENT → ADV-6** — shipped (see §2): board **Analyze** button + `run_analysis`
  / `get_analysis_findings` planning-mode tools; `test_analyze_tools` + `test_modes` cover the
  tool shape + bundle; the live conversational turn stays Bedrock-gated per §4.
- ✅ **G-BILLING-COCKPIT → ADV-11** — shipped (see §2): reconciliation glance + coverage-aware
  charging + supplemental + per-card coverage + env-gated demo pay; `dashboardModel`/`invoicePanel`/
  `payInvoiceView` unit + `e2e/advisor/invoicing.spec.ts`; live drop-in settlement stays §4-gated.
- **G-COVER → ADV-2A** is the last product gap; sequence it after the decision in §2.

**Wave 3 — messaging + boundary-limited.**
- **ADV-7 / ADV-8** — first add an e2e for the human thread (advisor posts → traveler's
  thread shows it, both browser; API backstop on the message row + collapsing 404), since
  messaging (M006/PS7) has unit but no e2e coverage. Email delivery stays 🔍.
- Wire an advisor **messaging pillar** into `apps/cli/tests/e2e/` if we want the human thread
  in the API-seam spine alongside P1–P6.

### Next up (recommended order for the next hand)

> **Superseded 2026-07-07 by §6 (Course forward)** — a full implementation sweep found the
> felt gaps live outside the ADV-1…11 ledger: the booking last-mile is gated unreachable,
> cards are write-once, the agent is money-blind, and there is no advisor awareness layer.
> §6 is the current ordering; the two items below fold into its parked list.

With G-INVITE-LATER, G-NODE-EDITOR, G-APPROVE-TOTAL, G-ANALYZE-AGENT and G-BILLING-COCKPIT
closed, **one product gap + one deferred slice remain**. Suggested sequence by leverage-per-effort:

1. **G-COVER → ADV-2A** (M, decision-gated) — decide curated-picker vs. generative first
   (§2 recommends the curated Unsplash-style picker), then `itineraries.cover_image` +
   service + hero UI. The last product gap.
2. **Advisor-private Collection** (deferred from G-NODE-EDITOR) — a node `audience`/visibility
   column filtered out of every traveler-facing read (graph API, Collection, agent context).
   Bigger (touches every read path); do it when an advisor-only scratch space is actually needed.

Two small ADV-11 follow-ups noted in §2 (non-blocking): (a) a **money-split deposit** that
tracks its own remainder (the %-deposit shortcut was dropped as incompatible with node-coverage
billing); (b) driving the **live drop-in** settlement once a sandbox harness exists (the browser
spec covers only the demo nonce path today).

A follow-up worth noting for ADV-6: a **live-agent conversational spec** (the advisor asks the
concierge to check the plan → the agent fires `run_analysis`/`get_analysis_findings` → findings
narrated) belongs alongside ADV-3's `concierge.spec.ts` (run isolated / `--workers=1`), asserted
at the API seam not on wording — the tool wiring is now in place for it.

Optional thin browser adds noted inline: **ADV-9** (locked-node affordance), **ADV-2C** (private
aside absent from the traveler view). Boundary-limited items (email, live Duffel, gateway) stay
🔍 per §4 — cover the dispatch/enqueue, never the far side.

## §4. Honest skips — gates we don't own

Mirror the pillar suite's discipline: skip with a reason, never false-green.
- **SMTP / mailbox (🔍):** welcome email (ADV-1), send notification (ADV-7). No HTTP seam
  until the F2 mailbox harness; cover only the *dispatch/enqueue*, never inbox receipt.
- **Live Duffel (🔍):** the flight lane self-skips + records itself dark without
  `DUFFEL_API_KEY` (ADV-5). Real offers are F2 live-vendor.
- **Payment gateway (🔍):** `payments_unconfigured` self-skips the pay steps where no gateway
  is wired; the Fake gateway + `fake-valid-nonce` keep it green locally (ADV-11).
- **Agent semantics (⚠️ Bedrock-gated):** grounded-not-generic build (ADV-3), the concierge
  actually recording a party member (ADV-2B). Asserted at the API seam against a real agent,
  never on wording in the browser.

## §5. Definition of done (advisor area)

- Every ADV scenario has an accurate **Status** + **Automated by** and appears in the
  [advisor.md](./advisor.md) coverage table and the [README](./README.md) areas table.
- Wave 1 advisor-project specs exist and pass locally against the running stack.
- Each §2 gap is either **shipped** (its scenario flips 🟡→✅) or **explicitly deferred** with
  the product decision recorded here — no scenario left claiming ✅ it can't exercise.
- The pillar suite stays green (the atomic-create default, money gate, and audience isolation
  are not regressed by any gap work).

## §6. Course forward (2026-07-07) — beyond the ADV ledger

> A full sweep of the implementation (web shell, agent tools/prompts/context, api-client
> surface) against the *felt* advisor experience. The ADV-1…11 ledger above is accurate for
> what it tracks; these are the gaps it doesn't. Four themes, ordered into waves by leverage.

### The findings

1. **The loop's last mile is unreachable in the browser (bug).** `BookingPanel` has every
   action (Book, choose-slot, override, confirmation-#, cancel) but the Dashboard passes it
   `editable={selectEditable}`, and `selectEditable` requires `lockStatus === "locked-by-me"
   && status === "draft"` — while `bookableNodes` only lists **approved** nodes. On a
   proposed/approved trip (the only bookable ones) the buttons never render. Identical to the
   edit-lock coupling ADV-11 fixed for invoices; bookings were missed. Today booking only
   works via `ovb`/API.
2. **Cards are write-once.** After the composer, an advisor can edit only title + `source_id`
   inline (plus schedule/status). No cost edit (so a link card can never be priced), no
   description, no location, no supplier-confirmation field for manually-booked items (the
   [advisor.md](./advisor.md) "Reminders for later" note). Soft delete (0040, notes-only) has
   no restore; the undo toast reverses placement only. Mood/cover fixed at intake (G-COVER).
3. **No advisor awareness layer.** Nothing surfaces traveler activity — a reconcile request
   is only visible inside that fork's Studio; approvals, payments, and thread messages require
   walking into each trip. The client page has no cross-trip invoice/booking roster (a known
   resume hook) and no "since you last looked."
4. **The agent reads the graph but can't do half the advisor's job.** No node field-edit tool
   (title/cost/description); zero money awareness (can't answer "what's uninvoiced," can't
   explain a money-gate refusal, can't warn an offer is expiring); no per-turn graph digest
   (must burn `get_itinerary` to learn statuses/totals/the ADV-10 state — and the rubric never
   teaches the propose flow); no proactivity and no escalation channel (can't post to the
   human thread).

### The waves

**Wave A — close the loop in the browser** *(small, first)* — **✅ shipped 2026-07-07**
- ✅ **ADV-12 — Booking decoupled from the edit lock** (S): shipped — `BookingPanel` now
  takes `canManage` (role-derived, the same gate as `InvoicePanel`) instead of
  `selectEditable` at both mounts (Dashboard `AdvisorManagement`, prototype aside), so
  Book / slot-book / confirm-# / cancel render on the proposed/approved trips that are
  actually bookable. Read-only copy is now "Booking is managed by your advisor."
  Tested: `bookingPanel.test.tsx` (role gate). *Follow-up:* extend
  `e2e/advisor/invoicing.spec.ts` with the book → confirm beat against the live stack.
- ✅ **ADV-15 — Invoice ↔ inventory legibility** (M, founder-flagged 2026-07-07: "invoicing
  is still largely unusable — I cannot intuitively SEE how the invoices relate to the
  inventory"): shipped, two halves. (a) **Card-aware invoices** — a node-tagged charge line
  renders a shared `NodeIdentity` (type glyph + title deep-linking to
  `/itinerary/[id]/item/[nodeId]` + a "Wed, Sep 24" when-stamp) instead of ledger prose,
  with a graceful fallback to the description when the node isn't in the graph; a new
  **"Not yet billed" tray** under the reconcile strip lists every uncovered card as
  identifiable inventory with its remaining balance ("$200 of $1,200" when part-billed).
  (b) **Billing state on the inventory** — a pure `billingChipsByNode` in `dashboardModel`
  (unbilled / partial / billed / paid, party-expanded, coverage-derived) feeds a store
  `refreshBilling` action (advisor-only, self-contained ledger+graph fetch) loaded on
  Timeline mount; every timeline/mobile card wears the chip in its type-label row (a new
  `CardShell.headerExtra` slot). A cost edit re-derives the chips. Tested:
  `dashboardModel.test.ts` (chip truth table incl. per-person expansion),
  `invoicePanel.test.tsx` (tray, line identity, fallback, traveler-hidden),
  `nodeCardBadge.test.tsx` (chip render). *Boundary:* chips load on timeline mount — a
  billing change made elsewhere shows on next visit, not live.
- ✅ **ADV-13 — Editable cards** (M): shipped as the card-detail **Edit facet** (facet (g),
  advisors holding the lock, non-note cards): **description** (`metadata.description` —
  already rendered in every zoom body), **price** (the first-class cost trio; clearing the
  amount clears all three — this also finally lets a pasted-link card be priced), and the
  **confirmation # / PNR** (`metadata.confirmation_number` — already rendered as the
  booked/confirmed footer serial; closes the "manually booked off-inventory" reminder at
  the bottom of [advisor.md](./advisor.md)). Store: a new `updateCardDetails` action —
  client-side metadata **merge** (the server replaces the object wholesale), both-or-
  neither cost semantics, optimistic + revert, adopts the server's canonical node, and
  re-derives billing chips after a price change. `UpdateNodePatch` in the api-client
  gained the cost trio (the generated body already carried them; no regen). Tested:
  `cardDetail.test.tsx` (patch shape incl. metadata-merge survival of schedule/location
  keys, cost-clear, role gate), `store.test.tsx` (inert for travelers / no-creds).
  *Boundaries:* title edit stays in the ScheduleFacet (already existed); a **firmed**
  card (approved/booked/confirmed) still refuses field edits server-side (G1
  `demote_before_edit`) — the facet gates on the same `selectEditable` as every other
  edit affordance, so the demote-first dance is unchanged; type/location editing deferred.

**Wave B — agent eval harness** *(deliberately before agent behavior work)* — **✅ shipped 2026-07-07**
- ✅ **EVAL-1 — tool observability + scenario runner** (M): shipped, both halves, and
  **run over the REAL agent** (per the founder: the mock lane carries no eval value —
  deterministic-on-mock was dropped; every eval drives live Bedrock turns).
  - **`tool_trace` SSE frame** — emitted by the *agent's* `EventTranslator` (the
    `toolUseId → name` map lives in `apps/agent/src/agent/translate.py`, not the API — the
    API forwards unknown frames verbatim), one frame per tool **call** and **result**
    (name + toolUseId + Strands status ONLY; never inputs/outputs — Dossier/OSINT
    redaction discipline). Debug-gated on a new `EMIT_TOOL_TRACE` agent setting (off by
    default; the mprocs agent pane, `scripts/restart-agent.sh`, and the gitignored
    `apps/agent/.env` set it locally). Structurally invisible to real browsers: the web's
    `KNOWN_FRAME_TYPES` filter drops the unknown type. `ovb` types it (`ToolTraceFrame`),
    `TurnResult` accumulates `tool_trace`/`tools_called`, and `ovb chat` renders fires
    inline (`⚙ search_inventory`) + `tools_called` under `--json`.
  - **Scenario runner** — declarative `ovb.evals` (`EvalScenario`/`TurnSpec`): turn script
    + expected tools (set-subset or ordered subsequence, plus `forbid_tools`) + a
    `GraphDiff` spec (`min_nodes_added`/`statuses_to`/`no_change`, snapshotted around every
    turn) + expected frames (`card_proposed`) + prose markers (fenced shortcodes like
    ` ```ov-timeline `) + an optional **LLM-judge rubric** (Bedrock Converse; skips
    honestly without boto3/creds). Surfaced two ways over the same runner: **`ovb agent
    eval scenarios.json --client-id … [--judge]`** (JSON scenario files, rich/`--json`
    report, exit 1 on failure) and the **`live_agent` pytest marker**
    (`tests/e2e/test_agent_eval_e2e.py` — run isolated, ADV-3 posture; self-skips on
    `upstream_unavailable` or a trace-less agent with the restart hint, never false-green).
  - **Verified live 2026-07-07:** both e2e evals green against real Bedrock (analyze-
    conversational: `run_analysis` fires, graph untouched; grounded-build:
    `search_inventory → propose_card` in order, `card_proposed` frame, +1 node on the
    graph), and the CLI face + judge lane green end-to-end (judge passed the rubric with a
    plan-grounded reason). Unit: `apps/agent/tests/test_translate.py` (trace gating,
    redaction shape, read-only tools trace) + `apps/cli/tests/test_evals.py` (parsing,
    every check, report aggregation) + sse/agent trace tests.
  - **Boundary:** evals score invariants (tools/frames/diff), never wording — the rubric
    judge is the only semantic check and it's opt-in per turn.

**Wave C — agent parity** *(measured by the Wave B harness)* — **✅ shipped 2026-07-08**

> Each AGT item is now a first-class QA scenario in the new
> [agent-parity.md](./agent-parity.md) area (code **AGT**) — a different *kind*
> of doc/qa spec: no screen, asserted via the Wave B eval harness (tools fired /
> frames / graph diff over the real agent), with the deterministic halves pinned
> by unit tests. Coverage + Given/When/Then live there; this is the build log.

- ✅ **AGT-1 — `update_node_details` field-edit tool** (S): shipped (named
  `update_node_details`, not `update_node`, to keep clear water from
  `update_node_status`). ADV-13's field set — title · description
  (`metadata.description`, read-merge-write so `start_time`/`snapshot`
  survive the wholesale metadata PATCH) · the cost trio (both-or-neither
  guarded tool-side; finally prices a pasted-link card conversationally) ·
  `metadata.confirmation_number` (the "manually booked off-inventory"
  reminder). Planning-bundle only; maps to the existing `node_updated` frame
  so an open board re-renders; docstring teaches the `locked` /
  `status_locked` / `demote_before_edit` outcomes (demote-first only on
  advisor confirmation). Taught in both planning rubrics.
- ✅ **AGT-2 — graph digest in the turn context** (S/M): shipped as a per-turn
  **"Live plan state"** block — computed by a new
  `app/services/graph_digest.py` (itinerary status *with its ADV-10 meaning*,
  node counts by status + locked note, per-currency totals + party size,
  invoiced/outstanding + the uninvoiced remainder, pending reconcile request,
  latest analysis block/warn counts) and **injected into the system prompt
  every turn** by `assemble_traveler_context` (founder call 2026-07-08:
  append per turn rather than have the agent fetch — the prompt is rebuilt
  each turn so it never stacks). Mirrored as `AgentContext.graph_digest` on
  `GET /agent/context`. Both planning rubrics + pinned Q&A teach "trust it
  over memory; `get_itinerary` only for the cards themselves", and the
  advisor rubric now teaches the `draft → proposed → approved` flow (the
  propose gesture stays the advisor's — no propose tool).
- ✅ **AGT-3 — read-only money tools** (M): shipped. Server-side seams first:
  `GET /itinerary/{id}/billing` (a new `app/services/billing_summary.py` —
  `derive_billing_state`, the server port of the ADV-11 cockpit's
  `reconcileBilling`: coverage net of reversals, per_person × party,
  issued/paid rollup, per-node uninvoiced remainder) and
  `GET /itinerary/{id}/booking-state` (`bookings.booking_state`: per
  approved/booked/confirmed node the billed/paid/owed split, booking +
  supplier ref + confirmed_at, latest offer + expiry/expired). Both under the
  invoice read gate (advisor/owner/creator) so either audience's JWT works.
  Agent tools `get_billing_state` / `get_booking_state` in planning **and**
  Q&A ("am I paid up?" is Q&A); narrate + nudge, never mutate — the tools are
  GETs, so the human-in-the-loop boundary stays structural. The reads also
  let the agent explain a money-gate refusal.
- ✅ **AGT-4 — escalation + proactivity** (M): shipped. A backend-only
  `POST /agent/thread-message` (agent-token auth; JWT-middleware
  whitelisted) posts **one `author_kind='artemis'` message** — attribution
  pinned server-side — onto the *same* human thread ADV-7/8 use
  (`post_agent_thread_message` reuses the get-or-create via a
  `_get_or_create_scope_thread` extraction; foreign-itinerary pins refused;
  failures collapse to 404). Agent tool `post_thread_message` (planning +
  Q&A) with disclosure + one-per-request rules in the docstring. Proactivity
  is the prompt-level **opening-of-turn convention**: the rubrics tell the
  agent to open with material changes the live plan state shows (pending
  merge, blocking finding, money newly outstanding) — judged, not gated.
- **Tested:** agent — `test_wave_c_tools.py` (patch shapes, metadata merge,
  cost-pair + unpinned guards, route paths), `test_modes.py` (bundle
  membership + rubric teaching), `test_translate.py` (`update_node_details`
  → `node_updated`). API — `test_billing_summary.py` (the cockpit-math
  mirror), `test_graph_digest.py` (render truth table),
  `test_traveler_context.py` (digest placement), `test_agent_internal_router.py`
  (digest field + thread-message auth matrix), `test_messaging.py`
  integration (artemis lands on the humans' thread; foreign pin refused).
  Evals — four new scenarios in `test_agent_eval_e2e.py` (field-edit fires
  the editor + frame; digest answers state with `get_itinerary` **forbidden**;
  money question fires `get_billing_state`, mutations forbidden, graph
  untouched; escalation fires the tool + an artemis row lands at the API
  seam). Clients regenerated (`packages/api-client` + the `ovb` SDK, which
  gained typed `get_billing_state`/`get_booking_state`/`open_thread`/
  `list_thread_messages`).
- **Verified live 2026-07-08:** all six evals (the four Wave C + the two
  Wave B) green against real Bedrock. Two harness learnings folded back in:
  (a) the Japan demo's cards are mostly firmed, so the field-edit eval seeds
  its own `proposed` card (the G1 refusal it first hit is P5's subject, not
  the editor's); (b) a forbid-only eval turn can't distinguish "no tools
  called" from a traceless agent, so `_check_tools` hard-fails on an empty
  trace only when tools are *expected*, and the digest eval runs a
  tool-firing turn first to prove the trace channel live.

**Wave D — awareness layer**
- **ADV-14 — needs-attention feed** (M/L): derive from what exists (`reconcile_requested_at`,
  node_history approvals, payments, unread thread messages) — no new table initially. Surface
  as command-center roster badges + a per-client "since you last looked" strip; a real
  notifications model only if that earns it.

**Parked, consciously:** G-COVER (decision-gated), G-SEND (product call), restore-UI for soft
deletes (bundle with ADV-13 if wanted), advisor-private Collection, money-split deposit.
