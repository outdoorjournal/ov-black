# M006 — Planner Shell (executable plan)

> The build ledger for the planner-shell redesign. Companion to
> [planner-shell.md](./planner-shell.md) (the design **rationale** — read that for *why*). This doc is the
> **executable** *what/how*: locked decisions, a dependency-ordered slice plan, and per-slice
> **goal · deliverables · data model · touches · tests · acceptance · depends · size**, in the
> [mvp-plan.md](../mvp-plan.md) house style. Holds the craft line (R014): no emoji, no spinners, serif
> concierge prose.
>
> **Status (handoff):** **PS0–PS4 are landed on `dev`; PS5 is implemented + verified (commit pending)** —
> see §0 below for exactly what's done, what was deferred within those slices, verification, and what's next.
> Q13 is **resolved (UNIFY, endorsed)**; Q3 (card takeover → PS4), Q4 (keep both homes → PS3), and Q6
> (place-mode is state, not a URL → PS5) shipped as their defaults. On milestone green-light the §1 decisions
> graduate to `doc/decisions.md` (D0xx) and this slots into `mvp-plan.md` as M006.

---

## 0. Status — handoff ledger

**Landed on `dev`:** PS0/PS1/PS2 in `a61c1dc` (docs) · `98f50bc` (PS2 agent + client) · `07146b3` (PS1 shell +
PS2 UI); **PS4 in `59bed60`** (card detail + charges read); **PS3 in `ce28581`** (Dashboard view + rail Home);
**PS5 in this commit** (place-mode: `heldItem`/`lastPlacement` store slice + Collection Schedule affordance +
timeline tap targets + shell holding-chip/undo-toast + unit tests + this ledger — **no backend**). Next up: **PS6**.

| Slice | State | Notes |
| --- | --- | --- |
| **PS0** | **done** | Q13 resolved → **UNIFY** (endorsed by the human call). Recommendation memo appended to [planner-shell.md §10](./planner-shell.md); draft migration in `scratchpad/00NN_messaging_threads.draft.sql` (throwaway — real one lands in PS7). Graduates to a D0xx on green-light. |
| **PS1** | **done** | Two-axis shell: `itinerary/[id]/layout.tsx` (Provider lift), routed `timeline` / `collection` / advisor-only `studio` (+ index→`/timeline` redirect), `_shell/*` (ItineraryShell · Rail · ConciergeColumn · MobileTabBar · the three planning-space views), and `TimelineDataContext`. |
| **PS2** | **done** | Scoped Artemis session list: migration `0036`, scope-aware reuse (no re-pin) + `force_new` + `list`/`patch` + auto-title, endpoints, api-client wrappers (`listSessions`/`patchSession`), `SessionThread` + `ConciergeColumn` UI, `ConciergeChat` `sessionId`/`onSessionOpened`. |
| **PS4** | **done** | Card detail as a route: `item/[nodeId]/page.tsx` + `CardDetailView` (full-bleed takeover; back affordance) with the six facets — (a) Maps/directions, (b) the data-driven `NodeZoomCard` (not the prototype fixtures), (c) `NotesPanel`, (d) "Ask Artemis about this" → concierge **context chip** (new `askContext` store slice + `ConciergeControl` context), (e) reschedule/unschedule/title via the store's `moveNode`/`unscheduleNode`/`editNodeField`, (f) money — new **`GET /itinerary/{id}/nodes/{node_id}/charges`** (billed/paid/owed + booking) + `getNodeCharges` wrapper. Card clicks everywhere route via a shared `useOpenNode` (timeline/mobile/collection); the old in-place modal stays as the fallback for non-shell hosts. |
| **PS5** | **done** | Place mode (pick-then-place, a11y path over drag): store slice `heldItem` + `lastPlacement` with `holdItem`/`placeHeldItem`/`clearHeldItem`/`undoPlacement` (`placeHeldItem` reuses `moveNode`; gated `selectCanSchedule` = editable ∨ traveler-fork, so a draft-mine traveler keeps drag→lazy-fork). **Schedule** button on `CollectionCard` → `holdItem`; `HorizontalCanvas` renders pulsing per-day **tap targets** when holding, mapping the tapped `clientY` → minute via the drag path's `mapYToMinute`; a shell-level **`PlaceModeLayer`** floats the holding chip + undo toast, handles Esc, and slides to the timeline when you pick from elsewhere (the held state survives the nav because the store is shell-hosted). `CollectionRail` gained a `variant="overlay"`. **No backend.** |
| **PS3** | **done** | Per-trip Dashboard: `dashboard/page.tsx` + `DashboardView` (index now redirects here; rail/tab **Home** entry + `DashboardIcon`). Sections — **hero** (mood-splash via `MOODS[timeline.mood]` + title/brief/timing; edit reuses `ItineraryIntake` prefilled → `router.refresh()`), one derived **next best action** (`deriveNextAction`, pure), the **money roll-up** (`listInvoices` → `rollupInvoices` owed-per-currency/issued/paid; per-invoice **pay** → existing `/invoices/[id]`; charge lines with `node_id` deep-link **down** to the PS4 card money facet), and **travel party** (advisor → `PartyPanel`; traveler → read-only `listItineraryParty` glance + link to `/basecamp/party`). Advisor-only **Trip management** tabs (Vault · Invoices · Booking) **rehomed out of Studio** — `StudioPlanningSpace` is now Build/Diff only. **No backend** (client-side roll-up over existing reads). |

**Verified (incl. PS5):** web — **43 files / 264 vitest pass** (+`placeMode.test.tsx`: hold/place/undo store
slice · Schedule affordance gating · PlaceModeLayer chip/Esc/toast/undo + slide-to-timeline), **typecheck + lint
clean**; the timeline/collection/dashboard route segments **compile on the live dev server** (307 → auth
redirect). Place mode is web-only — no api change. **Prior (PS3):** web — **42 files / 254 vitest pass** (+`dashboardModel.test.ts`: roll-up nets
payments/excludes draft+void · next-action priority · timing format; +`dashboard.test.tsx`: hero+edit gate ·
money owed/pay-link/line-deep-link · next-action · role split), **typecheck + lint clean**; the new
`dashboard`/`timeline` route segments **compile on the live dev server** (307 → auth redirect, no 500). PS3 is
**web-only** — no api/api-client change, so the api suite is unchanged from PS4 (863 pytest, mypy + ruff clean).
A full authenticated **browser UAT** of the hero splash + roll-up visuals is the remaining craft-line sign-off.
**Prior (PS4):** api — 863 pytest pass (the 2 `test_me` onboarding failures below are pre-existing); web
`cardDetail.test.tsx` (facets · money read · booking status · missing-node · ask→chip).
**e2e (Playwright, against the live mproc stack):** new `e2e/traveler-flows/card-detail.spec.ts` —
**CARD-1** (deep-link → facets), **CARD-2** (timeline card click → route; needed a `data-testid="timeline-card"`
hook on the canvas card + a `force` click, since the card is framer-motion-animated), **CARD-3** (ask-about-this
→ Re: chip → a **real live agent turn** on the itinerary path) — **all green**. Every other traveler-flows spec
(COL-1..4, ITB-6/6A, empty-state ITB-4, chat ITB-4) **passes in isolation** — the PS1/PS2 shell is structurally
sound. **Pre-existing red (NOT PS4):** `chat.spec ONB-2` (the *basecamp onboarding* opener turn) fails
consistently with the D015 "concierge stepping away" fallback — an onboarding-agent-path issue, separate from
the itinerary agent path (which is green via ITB-4 + CARD-3). Fix ONB-2 as its own cleanup before M006 done.

**Deferred *within* PS1/PS2 — carry into the noted slice (not lost, but not done):**
- Zoom/`pxPerMinute` still lives in `itineraryGraphStore` (extract to a view-local store — PS1's own TODO;
  cleanliness only, no bug since only the timeline reads it).
- The mobile **peek-sheet** concierge was dropped on the routed timeline in favor of the **Chat tab**
  (`showConciergeSheet={false}`); the design wanted to keep the sheet — **revisit in PS6**.
- Concierge **collapse** is basic (in-flow ≥1100px, summonable overlay below via Rail button / Chat tab); full
  Q5 polish → **PS6**.
- ~~**Context-chip** is a scaffold~~ — **done in PS4** (`askContext` store slice → the `Re: …` chip in
  `ConciergeColumn`, consumed as a turn prefix in `ConciergeChat`).
- ~~The transitional advisor **Studio** route (`/studio`) holds Party/Vault/Invoices/Booking **and** Build/Diff~~
  — **done in PS3**: Party/Vault/Invoices/Booking rehomed into the Dashboard; `StudioPlanningSpace` is now
  Build/Diff only. **PS6** still finalizes Build/Diff and removes the leftover in-canvas aside (behind
  `showConciergeAside`/`showConciergeSheet` on `HorizontalView`/`MobileItineraryLayout`, kept for the prototype).
- **Scroll-to-node from chat** is not wired in the relocated ConciergeColumn (chat is no longer canvas-adjacent);
  re-add via a store signal if wanted.
- The **people-circle** "Advisor" circle is a disabled placeholder (the human channel is **PS7**).

**Deferred *within* PS4 — carry into the noted slice (not lost, but not done):**
- The money facet (f) is **read-only** — it shows this item's charge/paid/owed + booking + invoice status, but
  the actual **pay/deposit action** is **PS3** (the Dashboard money roll-up owns the pay affordance; the card's
  "what to pay" rolls up there and the roll-up deep-links back). The read (`getNodeCharges`) already returns
  `invoice_id`, so a pay button here is a small follow-up once the client pay flow has a home.
- Facet (b) uses the existing **data-driven `NodeZoomCard`**, not the `prototype/cards/*` fixtures (those are
  hardcoded design mocks). The plan named the prototype as *source material*; `NodeZoomCard` already renders the
  per-type detail from node metadata, so wiring it was the right unbundling — no new adapter needed.
- The scheduling facet (e) gates on holding the lock (`selectEditable`) or a real fork (`selectTravelerEditable`);
  a **draft-mine** traveler (previewing Official with no fork yet) still reschedules via the timeline drag
  (which lazily forks) — the card facet stays read-only for them. Fine for PS4; revisit if the card should be
  able to trigger the lazy fork too.
- Card taps route to the **same** full-bleed detail on every breakpoint (deep-linkable on mobile); the old
  in-place desktop modal + mobile sheet remain **only** as the `onOpenNode`-absent fallback (the prototype / any
  standalone host). Removing them for good rides with the aside teardown in **PS6**.

**Deferred *within* PS3 — carry into the noted slice (not lost, but not done):**
- The money roll-up **pay** action is a link to the **existing** `/invoices/[id]` `PayInvoiceView` (traveler pays,
  advisor reviews) rather than a new inline pay flow — reuse, not scope creep. Closes the PS4↔PS3 loop: the card
  money facet rolls **up** into the Dashboard total, and each issued invoice's charge lines (those with `node_id`)
  deep-link **down** to that card's facet.
- The Dashboard money roll-up shows **issued/paid** only; **draft** invoices are advisor scaffolding surfaced in
  the rehomed **Invoices** management tab (advisor assembles there), never counted as "owed."
- The traveler **travel-party** section is a **read-only** glance (`listItineraryParty`, which is `require_user`)
  + a link to self-service `/basecamp/party`; household attach/detach stays the advisor `PartyPanel`. A first-class
  in-Dashboard traveler party editor (and the **advisor notifications** feed named in §4) are follow-ups — the
  current "notices" surface is implicit (the next-action derives from pending proposals + unpaid invoices).
- Brief **edit** reuses the full-screen `ItineraryIntake` inline (prefilled) rather than an inline field editor;
  fine, and it already PATCHes `/itinerary/{id}` + `router.refresh()`es the server-prop brief.
- **Live browser UAT** (hero splash render, roll-up visuals, mobile Home tab) not yet run — a `next dev` was
  holding `.next`, so `next build` was skipped to avoid the known prerender-collision; typecheck + full vitest +
  a live route-compile probe stood in. Run the UAT before M006 "done."

**Deferred *within* PS5 — carry into the noted slice (not lost, but not done):**
- **Place mode is desktop-only** (tap targets live on the ≥md `HorizontalCanvas`). PS6 resolved the mobile edge:
  the **Schedule** button is now `hidden md:block` so a phone never holds a card with nowhere to drop it —
  mobile scheduling flows through the **PS4 card-detail schedule facet** (which sets day/time and works on a
  phone). A *native* mobile place UI (the pager is a card feed with no time axis, so "tap a minute" needs a
  discrete-slot design) is a proper design-later item, not this slice.
- **`CollectionRail variant="overlay"`** exists (styling + non-droppable) but no host **summons** it yet — the
  pick-then-place flow instead relies on the store surviving route nav (pick on `/collection` → `PlaceModeLayer`
  slides to `/timeline`, held state intact) and the xl rail-beside-timeline. A floating "Collection" drawer
  summon on the timeline is a small **PS6** follow-up.
- **Draft-mine travelers** get no Schedule button (`selectCanSchedule` excludes them); they reschedule via drag,
  which lazily forks (`forkAndMove`) — exact parity with the PS4 card scheduling facet. Wiring place-mode to
  trigger the lazy fork too is a later nicety.
- The tap places at a snapped **15-min** minute-of-day from the tapped y; there's no live insertion-line preview
  under the pointer before the tap (the drag path has its ghost). A hover preview is polish, not blocking.

**Heads-up — pre-existing failures, NOT from this work (don't chase):**
`apps/api/tests/test_me.py::test_evaluate_onboarding_rule` and `::test_onboarding_session_reports_onboarding_complete`
fail on `dev` independently — `evaluate_onboarding` is `profile_fact_count >= 2` but those tests still assert
`>= 1`. `app/routers/me.py` is untouched here. Fix the stale tests (or the rule) as a separate cleanup.

**Local-dev notes for the next agent:**
- Migration `0036` is **already applied to the local Supabase** (`:54322`). Integration tests are
  `@integration` (skip when the DB is down; CI has no Postgres, so they never run there — write DB-behavior
  tests this way).
- After any apps/api schema change: `pnpm -C packages/api-client generate` (boots the API itself), then add the
  discriminated wrapper in `packages/api-client/src/index.ts`. `src/generated/` + `dist/` are **gitignored**
  (regenerated), so only `src/index.ts` is committed.
- A running web `next dev` holds `.next`; a concurrent `next build` will `MODULE_NOT_FOUND` in the prerender
  worker *after* "Compiled successfully" — that's the collision, not a real build failure.

**Next:** PS1 → PS2 → PS4 → PS3 → PS5 are done. The front is now **PS6** (advisor Studio finalize + concierge
collapse + a11y sweep — PS3's panel rehome is already done, so PS6 now only needs to finish Build/Diff, remove
the leftover in-canvas aside, and land the Q5 collapse). **PS7/PS8** (human channel + @-mention bridge) are
unblocked by Q13=unify but remain the late second track. Cleanup still owed regardless: the pre-existing
`chat.spec ONB-2` (basecamp onboarding opener) + the two stale `test_me` onboarding assertions; and place-mode's
**mobile tap targets** + the **overlay-drawer summon** (see PS5 deferrals) are follow-ups.

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
| Q13 | Chat substrate | **RESOLVED (PS0): UNIFY** — one `threads`/`messages`/`thread_participants` store, `agent_session` as the per-thread AI engine (endorsed). Additive/back-compatible: PS2 ships first, PS7 introduces threads + backfills. | PS7, PS8 |

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
> **DONE** (see §0). Outcome: **UNIFY**. Memo in [planner-shell.md §10](./planner-shell.md); draft migration in scratchpad.
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
> **DONE** (commit `07146b3`, see §0). Rail order shipped as **Timeline · Collection · ─ · Studio** (Home/Dashboard joins in PS3). Deferred: zoom→view-local store, mobile peek-sheet, full Q5 collapse. The in-canvas aside is retained behind `showConciergeAside`/`showConciergeSheet` for the prototype (removed in PS6).
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
> **DONE** (commits `98f50bc` + `07146b3`, see §0). Migration `0036` applied to local DB. Reuse index shipped as a **plain** partial index on `(client_id, audience, itinerary_id, started_at desc) WHERE ended_at IS NULL AND archived_at IS NULL` (not unique — multiple live sessions per scope). Context-chip is scaffolded (empty), wired in PS4; the people-circle "Advisor" is a PS7 placeholder.
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
> **DONE** (commit pending, see §0). Index redirects to `dashboard/`; rail/tab **Home** entry added. `DashboardView`
> composes hero (mood-splash + editable brief via `ItineraryIntake`) · one `deriveNextAction` · money roll-up
> (`rollupInvoices`, per-currency owed, pay → `/invoices/[id]`, charge-line deep-links to the PS4 card facet) ·
> travel party (advisor `PartyPanel` / traveler read-only glance). Vault/Invoices/Booking **rehomed** into an
> advisor-only Trip-management tab strip; `StudioPlanningSpace` trimmed to Build/Diff. Pure helpers in
> `_shell/dashboardModel.ts` are unit-tested. Deferred: real pay flow reuses the existing `/invoices/[id]` page;
> advisor-notifications feed + traveler party editor → follow-ups; live UAT pending.
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
> **DONE** (commit pending, see §0). Route is `itinerary/[id]/item/[nodeId]` (nested under the shell so the
> concierge + store persist beside the takeover). Facet (b) reused the data-driven `NodeZoomCard` (the
> `prototype/cards/*` are hardcoded fixtures); money facet added `GET …/nodes/{id}/charges` (no schema change);
> the ask-chip is a new `askContext` store slice + a tiny `ConciergeControl` context (the shell hosts the store
> Provider, so the overlay-open control can't live in the store). Deferred: the money **pay action** (→ PS3),
> draft-mine card-triggered fork (→ drag path for now), modal/sheet teardown (→ PS6).
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
> **DONE** (commit pending, see §0). Store slice `heldItem`/`lastPlacement` (+ `holdItem`/`placeHeldItem`/
> `clearHeldItem`/`undoPlacement`, gated `selectCanSchedule`); `placeHeldItem` reuses `moveNode`. **Schedule** on
> `CollectionCard`; pulsing per-day **tap targets** in `HorizontalCanvas` mapping tapped `clientY` → minute via
> the drag path's `mapYToMinute`; shell-level **`PlaceModeLayer`** = holding chip + undo toast + Esc + slide-to-
> timeline (held state survives the nav — the store is shell-hosted, so place-mode is a real cross-surface
> **layer**, not a route). `CollectionRail` gained `variant="overlay"`. Deferred: mobile tap targets, the
> overlay-drawer summon, draft-mine lazy-fork on tap, a pointer insertion preview (all → PS6/follow-ups).
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

| Migration | Slice | Change |
| --- | --- | --- |
| **0036** ✱ | PS2 | **done** — `agent_sessions` += `title text`, `archived_at timestamptz`; open-session partial index replaced with a scope-aware one (`client_id, audience, itinerary_id, started_at desc`) over live rows |
| **none** ✱ | PS4 | **done** — `GET /itinerary/{id}/nodes/{node_id}/charges` (no schema change): sums `invoice_line_items.node_id` across non-void invoices (billed/paid/owed) + attaches the live `bookings` row |
| **none** | PS3 | **done** — no backend: the Dashboard money roll-up is a **client-side** `rollupInvoices` over the existing `listInvoices` read; next-action is a client-side derivation; pay reuses the existing `/invoices/[id]` page |
| **none** | PS5 | **done** — no backend: place mode is a transient `heldItem`/`lastPlacement` **UI slice** over the existing `moveNode`/`unscheduleNode`; not a route (refresh mid-place returns clean) |
| next avail. | PS7 | `threads` / `messages` / `thread_participants` (+ RLS) — shape in **PS0/Q13 = UNIFY**; see `scratchpad/00NN_messaging_threads.draft.sql` |

✱ Next free migration number after this is **0037**. Every schema change re-runs
`pnpm -C packages/api-client generate` and adds a wrapper in `packages/api-client/src/index.ts` (generated
output is gitignored — not committed).

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

- ~~**Q13 (PS0 output).**~~ **RESOLVED — UNIFY** (endorsed). No longer blocks; PS7 builds on it.
- **Default vetoes now mostly resolved by shipping:** Q3 (card takeover → **PS4**), Q4 (keep both homes → **PS3**),
  Q6 (place-mode is transient **state**, never a landable URL → **PS5**; the Collection *drawer's* open/closed is
  likewise local state), Q5 (collapse threshold) + Q7 (rail order — Home · Timeline · Collection · ─ · Studio,
  Home now live) defaulted in PS1/PS3. Changing any now is a small follow-up, not a veto. The only still-open
  human call is the **green-light** below.
- **Green-light.** On approval, the §1 decisions graduate to `doc/decisions.md` (D0xx) and this registers in
  `mvp-plan.md` as **M006**.
