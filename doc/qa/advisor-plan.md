# Advisor Experience — codebase analysis & coverage plan

> Companion to [advisor.md](./advisor.md) (the **scenario spec**, ADV-1…ADV-11). This
> doc is the **engineering** side: what the codebase already delivers for each advisor
> workflow, the product gaps that block a scenario being asserted as written, and a
> prioritised plan for closing coverage — in the [mvp-plan.md](../mvp-plan.md) house
> style (goal · gap · plan · tests). Unlike the scenario spec, this is a working plan,
> not an invariant contract.
>
> **Bottom line (handoff):** ~two-thirds of the advisor loop is already **green at the
> API seam** via the pillar suite (P1–P6). The outstanding work is (a) **advisor-project
> Playwright** specs that drive the real screens, and (b) **six product gaps** — most
> small and isolated — before the remaining scenarios are true. Nothing here is a
> rewrite; it's finishing UI + a few tools on top of a built spine.

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
| 1 | Create client w/o inviting | **partial** | `POST /clients` → `create_client_with_dossier` (`apps/api/app/routers/clients.py`); P1 | create + welcome are **atomic** — no silent-create / invite-later |
| 2 | Itinerary shell (brief+timing) | **built** | `POST /itinerary` (`routers/itineraries.py`), timing 0033; ITB-1/1B/1C | advisor-project browser run of the intake |
| 2A | AI cover image | **gap** | `cover_image` only from provider photos / OG scrape / manual paste | **no image generation/curation anywhere** |
| 2B | Travel party (existing/new) | **built** | `party_members` routes + agent `record_/update_party_member` (`agent/tools/traveler.py`); P4 | advisor-project browser run |
| 2C | Advisor≠traveler agent access | **built** | audience isolation (`open_or_reuse_session`); `agent/tools/__init__.py` mode bundles; P3 + `test_modes` | — (optional visibility browser test) |
| 3 | Build by conversation | **partial** | search→propose→approve (P3, full-loop); `propose_card` | advisor browser turn; live grounding agent-gated |
| 4 | Hand-author a node | **partial** | `POST /nodes`, `/from-inventory` (P3), `/from-link` OG preview | **no card-editor UI component** |
| 5 | Duffel flights | **partial** | `inventory/providers/duffel.py`; `search_inventory`+`propose_flight`; P3 flight lane | **no flight-picker UI**; live creds-gated |
| 6 | Analyze w/ the agent | **partial** | `routers/analyze.py` (P3 analyze+fill) | **no agent tool** to run Analyze / read findings; UI trigger unconfirmed |
| 7 | Send + message (email+chat) | **partial** | `routers/messaging.py` `/threads`; `HumanThread.tsx`; `test_agent_summon.py` | **no e2e**; email 🔍; "send" as first-class action undecided |
| 8 | Traveler requests changes | **partial** | `request_reconcile` (P5); human thread + @Artemis | conversational-request e2e; @Artemis thin |
| 9 | Advisor changes, locked nodes | **built** | status×actor gate, `demote_before_edit`, reconcile (P5) | — (optional lock-affordance browser test) |
| 10 | Bulk-approve + see price | **partial** | itinerary approve (P3), client-sees (full-loop), `cost_totals` (P3) | **no bulk node-approve action**; **no surfaced total** |
| 11 | Invoice + Braintree pay | **built** | `routers/invoices.py`, `payments/braintree_gateway.py`; P6 + M005 + full-loop | pre-filled **test-card UI**; auto-invoice-from-nodes (optional) |

**Orientation (surfaces):** `command-center/*` = advisor-only (roster, new client, client
detail; `require_advisor`). `basecamp/*` = traveler self-serve (`/me/*`). `itinerary/[id]/*`
= **shared** advisor+traveler, role-gated server-side. The agent runs the same session for
both, split by `audience` (`traveler` shared vs `advisor` private) and `actor_kind` stamped
server-side.

## §2. Product gaps (decision precedes test)

Six gaps block a scenario being asserted *as written*. Each is small and isolated; the
first four each unlock one ADV scenario, the last two are demo-polish.

### G-INVITE-LATER — silent client create (ADV-1)
- **Goal:** an advisor can create a client and build for them **without** notifying them.
- **Today:** `create_client_with_dossier` always mints the Supabase identity + emails a
  welcome link; `access_status` starts `pending`. No opt-out.
- **Plan:** add `notify: bool = true` to `POST /clients` (or split a `POST
  /clients/{id}/invite`); when false, create the client + Dossier but defer the auth-row
  mint + email. Roster gains a "Send invite" action on not-yet-invited rows. Keep the
  atomic path the default so ONB-1/P1 stay green.
- **Size:** S. **Touches:** `services/clients.py`, `routers/clients.py`, command-center roster.
- **Test to add:** API — create with `notify=false` mints **no** auth row / sends **no**
  welcome (assert the enqueue count is 0), then explicit invite flips to `pending` + sends.

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

### G-NODE-EDITOR — advisor card editor UI (ADV-4)
- **Goal:** a card-like editor: choose type, paste a link (auto-preview), fill fields incl. price.
- **Today:** **all three write paths exist** — `POST /nodes` (blank/typed/priced),
  `/nodes/from-inventory` (P3-tested), `/nodes/from-link` (OG preview via
  `services/link_preview.py`), all through the shared `add_node` lock/queue/history spine.
  There is **no** `NodeEditor`/`CardEditor` component (`app/prototype/cards` is an unwired
  visual ref).
- **Plan:** build the editor modal against the existing endpoints — type select, a
  paste-link field that calls `/from-link` for the preview, and a cost pair (amount +
  currency + kind). Pure frontend; no API work.
- **Size:** M. **Touches:** `app/_components/itinerary-graph/…` (new editor), wire into the board.
- **Test to add:** browser — type+link+price → card appears; API backstop on type,
  `actor_kind=advisor`, cost pair, resolved link snapshot.

### G-ANALYZE-AGENT — Analyze as a conversational step (ADV-6)
- **Goal:** the advisor can ask the concierge to analyze the plan and hear what's wrong.
- **Today:** the Analyze/Fill **engine** is built + P3-tested, but only reachable by the
  advisor calling `POST /itinerary/{id}/analyses` directly; the agent has **no** tool for it.
- **Plan:** add `run_analysis` + `get_analysis_findings` tools (planning/advisor mode) that
  wrap the existing endpoints, plus an Analyze button on the advisor board.
- **Size:** S–M. **Touches:** `agent/tools/` (new tools + registry), advisor board button.
- **Test to add:** agent-mode unit that the tool bundle includes Analyze in advisor/planning;
  API path already covered by P3.

### G-APPROVE-TOTAL — bulk approve + surfaced price (ADV-10)
- **Goal:** the traveler approves once, remaining `proposed` nodes → `approved`, and sees a total.
- **Today:** approval is itinerary-status-level or per-node (`update_node_status`); no cascade.
  `cost_totals` proves the per-currency total is **derivable** but nothing surfaces it.
- **Plan — decide first:** does itinerary-approve **cascade** remaining `proposed` nodes to
  `approved`, or is there a distinct bulk endpoint? Recommend a cascade on the approve path
  (one mental model). Add a `totals: {currency: amount}` field to the graph/itinerary read so
  the UI can show the price.
- **Size:** M. **Touches:** approve service (cascade), graph serializer (totals), traveler UI.
- **Test to add:** API — approve → every `proposed` node is `approved`; graph read carries
  the per-currency total. Browser — traveler sees the price + one-action approve.

### G-TESTCARD — pre-filled sandbox card in the pay UI (ADV-11)
- **Goal:** demo payment without typing card numbers.
- **Today:** the payment **contract** is fully green (P6/M005/full-loop); `fake-valid-nonce`
  works. Just no UI affordance to pre-fill the sandbox card.
- **Plan:** a dev/demo-only "pay with test card" affordance in the Drop-in that submits the
  sandbox nonce. Guard it behind an env flag so it never ships to prod.
- **Size:** S. **Touches:** `app/invoices/[id]` pay form.
- **Test to add:** browser — the pre-filled path drives a pay to `paid` (gateway-unwired 🔍).

**Also flagged, not gating:** **G-SEND** (is "send the itinerary" a first-class action that
flips visibility + fires email, or just the first advisor message on an approved trip? —
settles ADV-7's shape) and **G-FLIGHT-UI** (a dedicated advisor flight-picker screen vs.
picking via the concierge — ADV-5 is drivable conversationally without it). Both are product
calls, not blockers.

## §3. Coverage plan (waves)

Ordered by leverage: prove what's built in the browser first (cheap, high-signal), then the
scenarios that need a small product gap closed, then the boundary-limited ones.

**Wave 1 — advisor-project browser specs over already-built spine (no product work).**
New specs under `apps/web/e2e/advisor/` (an advisor Playwright project already exists —
`command-center.spec.ts`, `onboarding-invite.spec.ts`):
- **ADV-2** — own a client → new itinerary → brief + rough window → saved (reuses the ITB intake).
- **ADV-2B** — attach a remembered party member + add one via the concierge → trip roster updates.
- **ADV-3** — drive a concierge build turn from the advisor aside (loop asserted structurally).
- **ADV-9** (optional) — a booked node shows non-editable; an attempted edit surfaces the crafted reason.
- **ADV-2C** (optional) — the advisor's private aside is absent from the traveler's itinerary view.

These lean on P1/P3/P4/P5 as the API-seam backstop and add the *experience* proof the
headless pillars can't give.

**Wave 2 — close a small gap, then assert the scenario.** One product slice each, then its test:
- **G-INVITE-LATER → ADV-1**, **G-NODE-EDITOR → ADV-4**, **G-ANALYZE-AGENT → ADV-6**,
  **G-APPROVE-TOTAL → ADV-10**, **G-TESTCARD → ADV-11 browser**.
- **G-COVER → ADV-2A** is the largest; sequence it after the decision in §2.

**Wave 3 — messaging + boundary-limited.**
- **ADV-7 / ADV-8** — first add an e2e for the human thread (advisor posts → traveler's
  thread shows it, both browser; API backstop on the message row + collapsing 404), since
  messaging (M006/PS7) has unit but no e2e coverage. Email delivery stays 🔍.
- Wire an advisor **messaging pillar** into `apps/cli/tests/e2e/` if we want the human thread
  in the API-seam spine alongside P1–P6.

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
