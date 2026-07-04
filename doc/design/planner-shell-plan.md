# M006 — Planner Shell (executable plan)

> The build ledger for the planner-shell redesign. Companion to
> [planner-shell.md](./planner-shell.md) (the design **rationale** — read that for *why*). This doc is the
> **executable** *what/how*: locked decisions, a dependency-ordered slice plan, and per-slice
> **goal · deliverables · data model · touches · tests · acceptance · depends · size**, in the
> [mvp-plan.md](../mvp-plan.md) house style. Holds the craft line (R014): no emoji, no spinners, serif
> concierge prose.
>
> **One decision is still held — Q13** (chat substrate). It gates only the two human-channel slices (PS7/PS8);
> a spike (**PS0**) resolves it before they start, and everything else proceeds without it. On milestone
> green-light the §1 decisions graduate to `doc/decisions.md` (D0xx) and this slots into `mvp-plan.md` as M006.

---

## 1. Locked decisions (defaults — flag any to revisit)

Resolved in [planner-shell.md §10](./planner-shell.md); defaults chosen here to make the plan executable.
Veto any before we start the affected slice.

| # | Decision | Call | Affects |
| --- | --- | --- | --- |
| Q1 | Chat model | General chat is **multi-party** (advisor + trip party); **AI sessions stay 1:1** (you ↔ Artemis). Multi-party AI only via *summon* into a human thread. | PS2, PS7, PS8 |
| Q2 | "Ask about this" | **Context-chip** into the persistent concierge — not a card-embedded chat. | PS4 |
| Q3 | Card detail surface | **Full-bleed takeover** on desktop (back affordance); full-screen sheet on mobile. Not split, not over-canvas. | PS4 |
| Q4 | Dashboard vs Basecamp | **Keep both** — Basecamp = account/cross-trip home; Dashboard = per-trip home. | PS3 |
| Q5 | Concierge default | **Open by default** ≥ ~1100px, collapsible; auto-collapsed below. | PS1, PS6 |
| Q6 | Places URL vs state | **Destinations routed** (Dashboard/Timeline/Card); **layers/modes are state** (Collection drawer, held card). Collection drawer open/closed = **local state**, not URL. | PS1, PS5 |
| Q7 | Rail order | **Home · Timeline · Collection · ─ · Studio** (advisor-only, below a divider). Party + notifications live **in the Dashboard**, not the rail. | PS1, PS3, PS6 |
| Q8 | Scope & sequencing | **New milestone M006**, lands **incrementally**; PS1 first and non-breaking. | all |
| Q9 | "General chat" | **Human channel**, human-by-default, Artemis summonable. | PS7 |
| Q10 | AI multiplicity | **Session list** (many, scoped, resumable). | PS2 |
| Q11 | General-chat scope | Basecamp = you ↔ advisor; itinerary = you ↔ advisor ↔ that trip's party. | PS7 |
| Q12 | Sessions → graph | **Single spine** — sessions are peers writing one graph. | PS2, PS8 |
| **Q13** | **Chat substrate** | **HELD** — unify (one thread/message store, `agent_session` as per-thread engine) vs bridge two stores. **PS0 decides.** | PS7, PS8 |

---

## 2. Milestone goal & non-goals

**Goal.** Replace the overloaded eight-tab aside with a two-axis planner shell — **places** (routed
destinations: Dashboard · Timeline · Collection · Card · advisor Studio) on a left rail, **people** (a
persistent concierge: general human chat + scoped Artemis session list) beside it, planning space filling the
rest — responsive to a mobile bottom-tab collapse, role-agnostic (travelers click cards & ask Artemis too),
built as an **unbundling** of existing pieces on the single graph spine.

**Non-goals (this milestone).** Cinematic view; proactive Artemis trigger *rules* beyond @-mention (PS8 ships
the bridge + @-mention only); travel-party *invite* flows; any change to the itinerary domain/graph semantics;
Tailwind v4 migration (separate track).

---

## 3. Dependency graph

```
PS0 spike (Q13) ─────────────────────────────────────┐  (doc only; parallel to PS1)
                                                      │
PS1 shell ─┬─ PS2 Artemis session list ─┬─ PS4 card detail (ask-chip needs PS2)
           │                            │
           ├─ PS3 Dashboard ────────────┴─ (money facet ↔ PS4)
           ├─ PS5 place mode
           └─ PS6 Studio + polish (needs PS3 rehome)
                                                      │
              PS7 general human chat ◄── PS0 (Q13) + PS2 ── PS8 Artemis-in-chat bridge ◄── PS7
```

Critical path: **PS1 → PS2 → PS4**. PS3/PS5 parallelize off PS1. PS7/PS8 are a second track gated on PS0 + PS2
and can run late without blocking the traveler-facing shell.

---

## 4. Slices

### PS0 — Messaging substrate spike (resolves Q13)
- **goal:** decide unify-vs-bridge for the human channel and commit a concrete schema, so PS7/PS8 are unblocked.
- **deliverables:** a short decision memo appended to [planner-shell.md](./planner-shell.md) Q13 + a D0xx entry;
  a *draft* migration sketching `threads` / `messages` / `thread_participants` under the chosen model, and how
  `agent_sessions` relates (unify: `agent_session.thread_id`; bridge: separate stores + adapter).
- **data model:** draft only (no apply).
- **touches:** docs; a throwaway migration draft under `scratchpad`.
- **tests:** none (spike).
- **acceptance:** Q13 resolved with a schema a reviewer signs off; PS7 can start.
- **depends:** — · **size:** S · **parallel to PS1.**

### PS1 — Shell skeleton (routes + nested layout + Provider lift)
- **goal:** the three-region desktop shell and mobile tab bar exist; the concierge persists across view
  navigation; today's Timeline & Collection render **unchanged** inside routed destinations.
- **deliverables:**
  - `apps/web/app/itinerary/[id]/layout.tsx` — `AppHeader` + `Rail` + `ConciergeColumn` (placeholder wrapping
    today's `ConciergeChat`) + `{children}`; **hosts the store Provider** (lifted out of `ItineraryGraphView`).
  - Routed children under `itinerary/[id]/`: `timeline/page.tsx`, `collection/page.tsx`, and index `page.tsx`
    → redirect to `timeline` (Dashboard replaces the index in PS3).
  - `ItineraryGraphView` / `HorizontalView` become pure **planning-space** consumers: the chat aside and the
    eight-tab strip are removed from the canvas and re-slotted into the shell. **Transitional bridge:** the
    advisor panels not yet rehomed (Party/Vault/Invoices/Booking/Build/Diff) move behind a temporary
    advisor-only **Studio** rail entry so nothing is lost before PS3/PS6.
  - `_shell/Rail.tsx`, `_shell/ConciergeColumn.tsx`, `_shell/MobileTabBar.tsx`; responsive collapse (Q5).
  - `needsBrief` intake gate relocates to the layout/index (still first-run).
  - Extract horizontal-view UI state (`pxPerMinute`, zoom) into a view-local store; keep `itineraryGraphStore`
    pure domain (the store's own TODO).
- **data model:** none.
- **touches:** `itinerary/[id]/page.tsx`, new `layout.tsx` + route dirs, `ItineraryGraphView.tsx`,
  `HorizontalView.tsx`, `ItineraryBuilderScreen.tsx`, `itineraryGraphStore.tsx`, new `_shell/*`,
  `MobileItineraryLayout.tsx`.
- **tests:** existing `apps/web/tests/itineraryGraph/*` stay green; new — layout renders rail+concierge+view;
  deep-link `/timeline` & `/collection`; **store identity preserved across nav** (one instance, chat stays
  mounted); `apps/web/e2e/traveler-flows/*` smoke green.
- **acceptance:** switching views keeps one store + an open chat mounted; deep-links resolve; zero behavior
  regression on Timeline/Collection.
- **depends:** — · **size:** L (the foundational refactor).

### PS2 — Artemis session list (un-collapse sessions)
- **goal:** many named, scoped, resumable Artemis sessions per scope; switching trips no longer re-pins the one
  session; the concierge column shows the list.
- **deliverables:**
  - **Backend:** migration `agent_sessions` += `title text`, `archived_at timestamptz null`; rework
    `open_or_reuse_session` so reuse honors **scope** (stop collapsing to `(client_id, audience)`), plus an
    explicit "new session" path; endpoints `GET /sessions` (list by scope+audience), `POST /sessions` (create),
    `PATCH /sessions/{id}` (title/archive); auto-title from the first user message.
  - Regenerate `packages/api-client` (+ commit `src/generated/`).
  - **Frontend:** `ConciergeColumn` session-list UI (list · resume · ＋new · rename · archive); people-circle
    switcher (Artemis vs Advisor/party placeholder); context-chip scaffold; unify the mobile `ConciergeSheet`
    onto the same list.
- **data model:** `agent_sessions.title`, `agent_sessions.archived_at`; revisit the open-session index.
- **touches:** migration 00NN, `apps/api/app/services/agent.py`, `routers/agent.py`, `models/agent.py`,
  `packages/api-client`, `_shell/ConciergeColumn.tsx`, `ConciergeChat.tsx`, `ConciergeSheet.tsx`.
- **tests:** pytest — list returns scope-filtered sessions; a new session does **not** re-pin an existing one;
  open itinerary A then B → two distinct sessions (regression on the re-pin bug); traveler cannot list
  `audience="advisor"` sessions (FORBIDDEN→404 preserved). web — session-list UI, resume keeps history.
- **acceptance:** many Artemis sessions per scope; no re-pin; advisor-private sessions never surface to a
  traveler.
- **depends:** PS1 · **size:** M–L.

### PS3 — Dashboard view (per-trip home)
- **goal:** `/itinerary/[id]` lands on a guided per-trip dashboard; folds Party/Vault/Invoices/Booking in.
- **deliverables:** `DashboardView` — brief + splash (editable), travel party, advisor notifications, one
  guided **next best action**, and the **money roll-up** (total owed · issued invoices · what-to-pay · pay
  actions); a what-to-pay row deep-links to the card money facet (PS4). Reuse `PartyPanel` / `VaultPanel` /
  `InvoicePanel` / `BookingPanel` and **share** with the existing `basecamp/*` party/vault/invoice components
  where possible.
- **data model:** none (roll-up reads existing invoices; add a `next_action` derivation, client-side or a small
  read).
- **touches:** new `(dashboard)` index route + `DashboardView`, the four panels, `basecamp/_components/*`
  (shared), Rail (Home → Dashboard).
- **tests:** web — sections render per role; next-action reflects real state (needs brief → capture; unpaid
  invoice → pay); roll-up total = Σ lines. pytest if a roll-up/next-action endpoint is added.
- **acceptance:** both roles land here; next-action correct; retires the transitional Studio home for those four
  panels.
- **depends:** PS1 (links to PS4) · **size:** M.

### PS4 — Card detail as a route
- **goal:** clicking a card opens `/item/[nodeId]` — full-bleed takeover (desktop) / sheet (mobile) — with all
  six facets. Role-agnostic (travelers open + ask too).
- **deliverables:** `CardDetailView` wrapping `NodeZoomCard` + facet sections: **(a)** actions (Maps/directions),
  **(b)** type-specific UI wired from `prototype/cards/*`, **(c)** notes (`NotesPanel`), **(d)** "Ask Artemis
  about this" → concierge **context-chip** (PS2), **(e)** manual scheduling (`moveNode`/`editNodeField`/
  `unscheduleNode`), **(f)** money — the per-inventory line (charge · Bokun booking status · owed/paid · pay
  action). Back affordance; mobile keeps the existing sheet.
- **data model:** none new if a per-node charges read exists; else add `GET /itinerary/{id}/nodes/{nodeId}/charges`
  (reads `invoice_line_items.node_id` + `bookings`).
- **touches:** new `item/[nodeId]/page.tsx` + `CardDetailView`, `NodeZoomCard`, `NotesPanel`,
  `prototype/cards/*`, `ConciergeColumn` (context-chip), maybe a charges endpoint + client regen.
- **tests:** web — route renders facets; ask-about-this focuses the concierge with the chip; note persists +
  visible; money facet shows this item's line/booking. pytest for any new read. e2e — traveler opens a card
  deep-link and asks Artemis.
- **acceptance:** deep-linkable; role-agnostic; money facet = the per-inventory line that rolls up to PS3.
- **depends:** PS1; ask-chip needs PS2; money aligns with PS3 · **size:** M–L.

### PS5 — Place mode (pick-then-place + Collection as a layer)
- **goal:** non-drag scheduling as the primary path (drag kept); the Collection floats over other surfaces; a
  held card floats across whatever's underneath.
- **deliverables:** `heldItem` store slice; a **Schedule** affordance on `CollectionCard`; a floating holding
  chip; slot-target highlighting on the timeline; tap-to-place (reuses `moveNode`); cancel (Esc) + undo toast;
  a `CollectionRail variant="overlay"` (drawer over any surface). Place-mode is transient state — refresh
  mid-place returns to the underlying destination with nothing held (not a landable URL).
- **data model:** none.
- **touches:** `itineraryGraphStore.tsx` (heldItem + actions over `moveNode`/`unscheduleNode`),
  `collection/CollectionRail.tsx` (overlay variant + Schedule button), timeline canvas (slot highlight + tap
  target), new `HoldingChip`, toast/undo.
- **tests:** web — pick→place lands a card on a slot with no drag; Esc cancels; item stays in Collection;
  keyboard- and touch-accessible; refresh mid-place is clean.
- **acceptance:** as design; accessible; drag path still works.
- **depends:** PS1 · **size:** M.

### PS6 — Advisor Studio + shell polish
- **goal:** Build/Diff move to an advisor-only **Studio** destination; retire the transitional aside; finalize
  concierge collapse (Q5) + a responsive/a11y sweep.
- **deliverables:** `StudioView` (`AuthoringPanel` + `DiffPanel`), advisor-only rail entry below the divider;
  remove the PS1 transitional panel home; concierge collapse behavior; responsive pass.
- **data model:** none.
- **touches:** `HorizontalView.tsx` (remove leftover aside), `_shell/Rail.tsx` (advisor gating),
  `AuthoringPanel.tsx`, `DiffPanel.tsx`, `ConciergeColumn.tsx`.
- **tests:** web — travelers never see Studio; advisor authoring behavior unchanged; concierge collapses/expands.
- **acceptance:** authoring parity; traveler shell carries no advisor tooling.
- **depends:** PS1, PS3 · **size:** M.

### PS7 — General (human) chat channel  ·  *gated on PS0 (Q13)*
- **goal:** a pure human channel (traveler ↔ advisor ↔ party), scoped, with **no agent turn**.
- **deliverables:** the messaging backend per the PS0 decision (`threads` / `messages` / `thread_participants`
  + service + endpoints + RLS); the general-chat surface behind the Advisor/party circles; itinerary general =
  that trip's party, basecamp general = you ↔ advisor; **unify** `basecamp/_components/RightRailChat` +
  `basecampChatStore` under `ConciergeColumn`.
- **data model:** new messaging tables (shape from PS0).
- **touches:** migration 00NN, new messaging service + router, `packages/api-client`, `ConciergeColumn`,
  `basecamp/_components/*`.
- **tests:** pytest — send/receive a human message; scope; RLS (party sees the itinerary thread; a non-member
  gets 403); web — general-chat UI; e2e — advisor↔traveler exchange.
- **acceptance:** advisor↔traveler message with no agent turn; itinerary chat shows the party; basecamp chat is
  the account relationship.
- **depends:** PS0, PS2 · **size:** L.

### PS8 — Artemis-in-human-chat bridge (@-mention)  ·  *gated on PS7*
- **goal:** summon Artemis into a human thread; one bridge, @-mention as the first trigger.
- **deliverables:** mention parse → **thread-scoped agent turn** → Artemis-authored message; **disclosure follows
  the thread's audience, not the summoner** (client-safe in client-visible threads even when an advisor
  summons); redaction-sweep coverage for Artemis messages in human threads; proposals flow to the single graph;
  explicit AI attribution. (Proactive rules / delegation deferred.)
- **data model:** none beyond PS7.
- **touches:** messaging service, `apps/api/app/services/agent.py` (thread-scoped turn),
  `apps/api/tests/test_traveler_context.py` (redaction), `ConciergeColumn` (mention UI + Artemis message
  rendering).
- **tests:** pytest — `@Artemis` in a client-visible thread answers **client-safe even when an advisor
  summons** (disclosure invariant); redaction sweep covers Artemis human-thread messages; a proposed card lands
  on the graph. web — mention UI + attribution.
- **acceptance:** the disclosure invariant is test-enforced; attribution unambiguous; proposal lands on the spine.
- **depends:** PS7 · **size:** L.

---

## 5. New data model (cumulative)

| Migration (next avail.) | Slice | Change |
| --- | --- | --- |
| 00NN | PS2 | `agent_sessions` += `title text`, `archived_at timestamptz`; revisit the open-session partial index so reuse can honor scope |
| 00NN | PS4 | *(only if missing)* per-node charges read — no schema change, reads `invoice_line_items` + `bookings` |
| 00NN | PS7 | `threads` / `messages` / `thread_participants` (+ RLS) — shape decided in **PS0/Q13** |

Every schema change re-runs `pnpm -C packages/api-client generate` and commits `src/generated/`.

---

## 6. Test & verification strategy

- **web:** Vitest + jsdom under `apps/web/tests/itineraryGraph/*` for shell/store/views; keep existing suites
  green as the regression net through the PS1 refactor.
- **api:** Pytest (`asyncio_mode=auto`) for session-list, messaging, and the **disclosure invariant** (PS8);
  ruff + mypy strict must stay green.
- **e2e:** `apps/web/e2e/traveler-flows/*` — extend for deep-link-to-card, place-mode, and an @-mention flow;
  `ovb` scenario smoke for the session-list API.
- **live:** per-slice `scripts/verify-sNN.sh`-style smoke against staging where a slice touches the backend;
  craft-line sign-off (R014/R021) before a slice is "done."

## 7. Definition of done (M006)

The eight-tab aside is gone; the two axes (places/people) are clean and role-agnostic; mobile reaches parity via
the bottom-tab collapse; the Collection works as both destination and place-mode layer; Artemis is a scoped
session list and is summonable into human chat under the disclosure invariant; all existing suites green + the
new coverage above; craft line held; staging UAT passed.

## 8. Still needs a human call

- **Q13 (PS0 output).** The one held decision — unify vs bridge. PS0 produces the recommendation; confirm
  before PS7.
- **Default vetoes.** Q3 (takeover), Q5 (collapse threshold), Q7 (rail order) were decided by default in §1 —
  say the word to change any before its slice.
- **Green-light.** On approval, the §1 decisions graduate to `doc/decisions.md` (D0xx) and this registers in
  `mvp-plan.md` as **M006**.
