# Planner Shell — navigation & information architecture

> **Status: DRAFT / exploring.** A design doc for reframing the traveler+advisor planner from
> "a timeline with a chat bolted on" into a **planning workspace**: a proper side-nav that scales to
> the surfaces we keep needing to add, handles multi-party chat (Artemis + Advisor + travel party),
> and is mobile-friendly. Narrative + target architecture + a phased build plan. The **Open questions**
> section (§10) is where unresolved decisions live — answer by number.
>
> Companion to [mvp.md](../mvp.md) / [mvp-plan.md](../mvp-plan.md). Holds to the craft line (R014):
> no emoji, no spinners, serif concierge prose. Nothing here is committed until §10 is resolved and the
> relevant decisions are appended to [decisions.md](../decisions.md).
>
> **→ Executable plan: [planner-shell-plan.md](./planner-shell-plan.md) (M006)** — the slice-by-slice build
> ledger derived from this doc. All open questions except **Q13** (held) are decided there by default; this doc
> stays the *rationale*.

---

## 1. Why now — the "eight-tab" tell

The planner is one route today — [`itinerary/[id]/page.tsx`](../../apps/web/app/itinerary/[id]/page.tsx)
— with a single overloaded right column. For an advisor,
[`HorizontalView.tsx:797-939`](../../apps/web/app/_components/itinerary-graph/views/horizontal/HorizontalView.tsx#L797)
crams **eight tabs** into a 440px strip:

`Build · Diff · Concierge · Client thread · Party · Vault · Invoices · Booking`

That strip is the pressure we're feeling. It isn't one navigation problem — it's **three kinds of thing
fused into one control**:

| Today's tab | What it actually is | Where it belongs |
| --- | --- | --- |
| Concierge, Client thread | **people** you talk to | the persistent concierge (people axis) |
| Party, Vault, Invoices, Booking | trip-management **surfaces** | the Dashboard view (places axis) |
| Build, Diff | advisor **authoring** tools | an advisor-only inspector |

So the three "thoughts" that kicked this off aren't three features to bolt on — they're the natural
decomposition of that one strip. And the architecture is already staged for the split:

- The store is deliberately **view-agnostic domain state** with a literal note —
  *"when a second view lands, extract per-view UI state into a view-local store"*
  ([`itineraryGraphStore.tsx:1-24`](../../apps/web/app/_components/itinerary-graph/store/itineraryGraphStore.tsx#L1)).
- The store **Provider is owned one level up** in
  [`ItineraryGraphView.tsx:74`](../../apps/web/app/_components/itinerary-graph/ItineraryGraphView.tsx#L74),
  so multiple views can already share one graph instance.
- There are already **two real chat threads** — `ConciergeChat audience="advisor"` (private advisor↔AI)
  and `audience="traveler"` (shared client thread) — plus a `PartyPanel`. The multi-party chat is
  half-built; it's just buried in tabs.

**This is an unbundling, not a rewrite.**

---

## 2. First principles — two orthogonal nav axes

Everything on the wishlist sorts onto two axes that must **not** be merged:

- **Places** — *which view am I in?* → Dashboard · Timeline · Collection · Card · (future) Cinematic
- **People** — *who am I talking to?* → Artemis · Advisor · travel party

The IA smell to avoid: one rail mixing places (Home, Calendar) with people (Artemis, Mom). Keep them
visually and spatially distinct. "Old people know how to use iMessage" → the people axis is modeled on
iMessage (faces you switch between), the places axis on an app's primary nav (a noun per destination).

Supporting principles:

- **Responsive, one component tree.** Same store, same routes; layout collapses by breakpoint. No parallel
  view trees or `/mobile` routes (per [feedback_frontend_architecture]).
- **Role is the source of truth**, not derived `canEdit` flags threaded around
  (per [feedback_frontend_architecture]); the store already derives capability from `role`.
- **The graph stays the single spine.** Collection, Timeline, Dashboard, and Card are all *views over the
  same nodes/edges* — never parallel stores (per [project_collection_wishlist]).
- **The concierge is the soul, not a tab.** It's persistent and adjacent, collapsible for real-estate,
  never hidden behind a nav click.
- **Destinations vs layers.** Not every surface is a routed destination. Dashboard / Timeline / Card are
  mutually-exclusive **destinations** (deep-linkable URLs). The **Collection** and **place-mode** are
  *layers*: the Collection can float *over* the timeline (or any surface), and a held card floats across
  whatever's underneath — transient UI state, not a URL you can land on cold (see §7, §8).
- **Surfaces are shared; role changes affordances *within*, never access.** Travelers click cards, open card
  routes, and ask Artemis too — deep-linking and agent access are **role-agnostic**. What differs by role is
  what you can *do* on a surface (edit / schedule / pay), not whether you can reach it.

---

## 3. Target shell

### Desktop (left-aligned nav + concierge, planning space right)

```
┌─────────────────── AppHeader (wordmark · breadcrumb · avatar) ──────────────────┐
├──────┬──────────────────────────┬───────────────────────────────────────────────┤
│ RAIL │  CONCIERGE  (persistent) │              PLANNING SPACE                    │
│      │                          │                                               │
│  ⌂   │ (Artemis)(Advisor)( + )  │   ┌ Dashboard · Timeline · Collection ┐       │
│ Home │ ───── who you talk to    │                                               │
│  ▦   │                          │   whichever view the RAIL selected            │
│ Time │  ▸ the selected thread   │   fills this region. Opening a card           │
│  ✦   │                          │   takes it over full-bleed (‹ back).          │
│ Coll │ ┌ Re: 6am Tsukiji  ✕ ┐   │                                               │
│  ⚙   │ └────────────────────┘   │                                               │
│ adv  │ [ ask Artemis…       ]   │                                               │
└──────┴──────────────────────────┴───────────────────────────────────────────────┘
   places            people                     the one big canvas
```

- **Rail** (~72px, icon+label): the **places** switcher. Home · Timeline · Collection · (future Cinematic);
  advisor-only authoring destination gated below a divider. App-level items (back to Basecamp / Command
  Center, avatar) anchor the bottom. Reuses the existing [`AppHeader`](../../apps/web/app/_components/app-header/AppHeader.tsx)
  above for wordmark/breadcrumb/avatar.
- **Concierge column** (~360–400px, collapsible): persistent chat. **People** circles across the top;
  the selected thread below; a **context chip** when scoped to a card; composer at the bottom.
- **Planning space** (flex-1): the selected view fills it. A card takes it over full-bleed with a back
  affordance (not a modal).

The spatial metaphor: your concierge sits beside you; the plan is the big table in front of you.

### Mobile (bottom tabs, one full-screen view at a time)

```
┌───────────── AppHeader (compact) ─────────────┐
│                                               │
│           active view (full screen)           │
│      Home | Timeline | Collection | Chat      │
│                                               │
├───────────────────────────────────────────────┤
│   ⌂ Home    ▦ Timeline   ✦ Collection   ✎ Chat │  ← bottom tab bar
└───────────────────────────────────────────────┘
```

- Bottom tab bar carries the **places** axis; each view is full-screen on the shared store (the responsive
  collapse the codebase already does — no separate tree).
- The **Chat** tab hosts the **people** circles at the top and the roomy thread below.
- Keep the existing peek-sheet concierge
  ([`ConciergeSheet.tsx`](../../apps/web/app/_components/itinerary-graph/views/mobile/ConciergeSheet.tsx))
  over the Timeline for quick asks; the Chat tab is the full version with people-switching.
- Card detail stays a full-screen sheet (exists in
  [`MobileItineraryLayout.tsx:241`](../../apps/web/app/_components/itinerary-graph/views/mobile/MobileItineraryLayout.tsx#L241)).

---

## 4. Places axis — the planning-space views

Promote the mutually-exclusive **destinations** from component-local `useState` to **routes** under a nested
layout that holds the rail + concierge, so the concierge doesn't unmount on navigation and *anyone* can
deep-link to an exact surface — an advisor sending a traveler "look at this card," or a traveler bookmarking
their own. Deep-linking and card/agent access are **role-agnostic** (§2). Transient **layers** — the
Collection drawer, a held card mid-placement — are UI state, not routes (§8).

| Route | View | Built from today | Notes |
| --- | --- | --- | --- |
| `/itinerary/[id]` | **Dashboard** (dashboard-lite, 1b) | Party + Vault + Invoices + Booking panels, brief/splash | Guided *next best action*; the **per-trip** home (Basecamp stays the cross-trip home — Q4) |
| `/itinerary/[id]/timeline` | **Timeline** | `HorizontalCanvas` / mobile pager | Only meaningful once things are dated |
| `/itinerary/[id]/collection` | **Collection** (dreaming, 1c) | `CollectionRail variant="board"` | Destination **and** a summonable overlay layer — floats over other surfaces in place-mode (§7) |
| `/itinerary/[id]/item/[nodeId]` | **Card detail** (3) | `NodeZoomCard` + `NotesPanel`, promoted out of the modal | Full-bleed; deep-linkable |
| _(advisor)_ authoring inspector | **Studio** | `AuthoringPanel` (Build) + `DiffPanel` | Advisor-only; not in the traveler's world |
| _(future)_ `/itinerary/[id]/cinematic` | **Cinematic** | — | Day-by-day walkthrough w/ weather, narration |

**Dashboard (1b)** is the **per-trip** landing and the "you're not lost" anchor: brief + splash image
(editable), travel party (+ future invite), advisor notifications, one guided next action, and the **money
roll-up** — total owed, issued invoices, what-to-pay, pay actions at trip level. The roll-up only; the itemized
per-inventory charge/booking/payment lives on the **card** (§6f), and a what-to-pay row deep-links to it.
The account-level `/basecamp` **stays** (Q4) — the cross-trip home where you pick a trip and hold
basecamp-scoped chat; its invoices are this same roll-up viewed across trips. Both roles see the Dashboard;
affordances differ by `role`.

---

## 5. Chat — scope, audience, kind

"Who you talk to" is only one of chat's axes. There are three, and **two are already in the schema**:

**Scope — where a conversation is pinned.** `agent_sessions.itinerary_id`
([0009](../../supabase/migrations/0009_agent_sessions_itinerary_pin.sql)):

- **Basecamp** (account, cross-trip) = `itinerary_id IS NULL` — onboarding, dreaming, Q&A across all trips.
- **Itinerary** (pinned) = `itinerary_id` set — building/discussing one specific trip.

**Audience — visibility.** `session_audience`
([0018](../../supabase/migrations/0018_agent_session_audience.sql)):

- **traveler** — the client-facing thread (traveler + any advisor who joins).
- **advisor** — a private advisor↔AI workspace the traveler never sees (Dossier/OSINT reasoning). A traveler
  cannot even open it (FORBIDDEN→404). Maps to today's `ConciergeChat audience="advisor"` vs `"traveler"`.

**Kind — general chat vs AI session.** *Decided (Q9/Q10):*

- **General chat** — a continuous **human** channel (you ↔ Advisor ↔ party), **human by default** (Artemis is
  *summonable*, not always-on — see *Harmonizing Artemis into the human channel* below), iMessage-style; one per
  scope. **Net-new**: today the advisor only reaches the traveler *through* the shared AI thread
  (`audience="traveler"`), so the human channel is fused with Artemis and must be separated out. (The sibling
  **voyage-site** app has human GROUP/ORGANIZATION messaging — message list, reactions, participants — as prior
  art to mine.)
- **AI sessions** — a **list** of discrete, resumable Artemis conversations per scope (ChatGPT-like: browse,
  resume, start, archive). Basecamp has its list; each itinerary has its list. This un-collapses today's single
  re-pinned session; the turn loop already runs per session, so it's mostly reuse-key + titles + list UI.

**The real gap is multiplicity.** `open_or_reuse_session` keeps exactly **one live session per
`(client_id, audience)`** and *re-pins* it to whatever itinerary you opened from
([`services/agent.py:375-387`](../../apps/api/app/services/agent.py#L375)) — so today a client has at most one
traveler + one advisor session, and switching trips silently re-pins the same row. 0009 anticipated "parallel
sessions against different itineraries," but the reuse key never took `itinerary_id`. So "AI chat **sessions**"
(plural, scoped, resumable) is the new capability: reuse must key on scope, or the singleton gives way to a
session **list** (Q10).

**Two shells, one persistent concierge.** The concierge column (§3) lives at BOTH a **Basecamp shell**
(cross-trip home — pick a trip, dream, basecamp-scoped chat) and the **Itinerary shell** (this trip). The
concierge follows you; its session list filters to the current scope, with basecamp always reachable. This
also **resolves Q4**: Basecamp (account home) and the trip Dashboard (§4) are different *levels*, not
competitors — Basecamp must exist because basecamp-scoped chat needs a home.

**People circles (iMessage).** Faces across the top of the concierge; tap to switch. Two behaviors behind them:

- **Advisor / party** circles → the **general (human) chat** for the current scope.
- **Artemis** circle → the **AI session list** for the current scope (active session + history + "＋ new").
  Artemis reads like a person you tap, but behind it is a list of topics, not one endless thread.

Name and face the AI — **Artemis** (the mobile sheet still says the generic "Concierge",
[`ConciergeSheet.tsx:140`](../../apps/web/app/_components/itinerary-graph/views/mobile/ConciergeSheet.tsx#L140)).
The set is **role-dependent** (privacy): a traveler sees `Artemis · Advisor · [party]`; an advisor's Artemis
list includes the private-workspace sessions (`audience="advisor"`), which must **never** appear in a shared
general thread.

**Context-aware, single surface.** Opening a card doesn't spawn a second chat — "Ask Artemis about this"
**focuses the persistent concierge with a context chip** ("Re: 6am Tsukiji ✕") so replies are scoped.
One thread, not twelve boxes (see §6d).

### Harmonizing Artemis into the human channel (@-mention & triggers)

"General chat = human, no AI" is the **default, not a wall.** We still want to summon Artemis into a human
thread — @-mention her, or fire other triggers — without collapsing the two concepts back together. The
reconciliation: **one thread substrate; Artemis is a participant — *standing* in AI sessions, *summoned* in
human chats.** The two "kinds" (§5) are really two participant configurations of the same thread:

| | Participants | Artemis |
| --- | --- | --- |
| **AI session** | you (or advisor) + Artemis | **standing member** — persistent memory; that's the point |
| **General chat** | you ↔ advisor ↔ party | **summoned guest** — reads context when called; doesn't silently sit in |

**One bridge, many triggers.** Every trigger is the same event: it invokes a **thread-scoped agent turn** whose
reply is posted back as an **Artemis-authored message**, with any card proposals flowing to the single graph
spine (Q12). Build the bridge once; wire many sources into it:

- **@-mention** — `@Artemis <q>` in any human thread → scoped turn → Artemis message in-thread. The canonical
  explicit trigger.
- **Ask-about-this** — long-press a message (or a card, §6d) → "Ask Artemis" with it as context. Same pattern
  as the card context-chip.
- **Advisor delegation / reclaim** — advisor hands a thread to Artemis ("@Artemis take this") and can take it
  back; the AI acts on the advisor's behalf, explicitly labelled.
- **Proactive rules (opt-in, advisor-configured)** — answer a factual question if no advisor replies within N
  minutes; price/deadline alerts; auto-translate a multilingual party. Rules fire the same bridge.
- **Escalation (reverse)** — Artemis in an AI session loops a human in ("I've asked your advisor") by posting
  into the general chat. Human↔AI handoff runs both directions.

**Non-negotiable rules** (mostly OV-specific privacy):

1. **Disclosure follows the thread's *audience*, not the summoner.** Artemis in a client-visible thread is
   client-safe — never surfaces Dossier / OSINT / net worth — **even when an advisor @-mentions her**. The
   advisor-private disclosure context is used *only* in advisor-private threads. The redaction sweep
   ([`test_traveler_context.py`](../../apps/api/tests/test_traveler_context.py)) must cover Artemis messages in
   human threads too — more eyes (the party) now see them.
2. **Attribution is explicit.** An Artemis message is visibly the AI, never mistaken for the advisor; "on
   behalf of your advisor" delegation is labelled. Trust depends on nobody confusing who spoke.
3. **Summoned ≠ surveilling.** In a human thread Artemis reads what she needs to answer *when called*; she is
   not a standing listener on the party's chatter unless a rule explicitly opts in (cost + privacy + it's a
   human space).
4. **Scope binds the turn.** The summoned turn inherits the thread's scope (itinerary | basecamp), so context
   is right and proposals pin correctly.

**Implementation fork (Q13):** (a) **unify the substrate** — one `threads` / `messages` / `participants` store,
with an `agent_session` as the per-thread AI execution engine behind Artemis's messages (mixed threads,
"advisor joins an AI session", and @-mention all fall out for free; more upfront rework; voyage-site is the
prior art); or (b) **bridge two stores** — keep `agent_sessions` / `agent_turns` for AI sessions, add a human
messages store, and a mention→turn→insert-message bridge (less rework, some content duplication; a stepping
stone to (a)). *Lean: (a) as the target; (b) acceptable as an interim.*

---

## 6. Card detail surface (3)

Today card detail is a centered `max-w-4xl` **modal**
([`HorizontalView.tsx:949-1000`](../../apps/web/app/_components/itinerary-graph/views/horizontal/HorizontalView.tsx#L949))
— too cramped for the wishlist. Promote it to a **full planning-space takeover** (`/item/[nodeId]`) with
room for:

- **(a) Actions** — open in Google Maps, driving/walking directions. (`location` is already on node metadata;
  `MapFlyer`/`MapStrip` exist.)
- **(b) Type-specific UI** — the per-type experiences already designed (subway stops, flight segments, hotel
  rooms). The prototype card set under
  [`prototype/cards/`](../../apps/web/app/prototype/cards/) is the source material.
- **(c) Notes** — **already built** as graph nodes (`addAttachedNote`, `attached_to_node_id`), visible to
  advisor + party via `NotesPanel`.
- **(d) Talk about this card** — focuses the persistent concierge with a context chip (see §5), rather than
  embedding a second chat.
- **(e) Manual scheduling** — reschedule/adjust via the same store actions (`moveNode`, `editNodeField`,
  `unscheduleNode`) the timeline uses.
- **(f) Money — the per-inventory line.** This is where you see *this item's* cost, booking status
  (reserved / confirmed / cancelled via Bokun), and what's owed vs paid — and take the pay/deposit action
  scoped to it. The data model already supports this: `invoice_line_items.node_id → nodes(id)`
  ([`0023_invoices.sql:93`](../../supabase/migrations/0023_invoices.sql#L93)) and
  `bookings.invoice_line_item_id → invoice_line_items`
  ([`0025_bookings.sql:71`](../../supabase/migrations/0025_bookings.sql#L71)), so a card is the natural home
  for its own charge/booking/payment. The Dashboard (§4) shows only the **roll-up**; drilling into a
  specific charge lands *here*.

**Money lives in two places, parent↔child.** Dashboard = the ledger roll-up (Σ lines, total owed,
what-to-pay, pay actions at trip level). Card detail = the per-inventory line (this item's charge + booking +
payment). They link both ways: a "what to pay" row on the Dashboard deep-links to the card's money facet, and
each card's charge rolls up into the Dashboard total. Basecamp's invoices are the same roll-up viewed
cross-trip — the itemized view a traveler needs "per inventory" is the card.

---

## 7. Collection → Timeline "place mode" (1c)

Drag-hold as the **only** affordance is an accessibility trap (sustained mouse-button hold is hard for older
travelers). Make **pick-then-place** the primary path; keep drag as a power-user enhancement.

> Tap **Schedule** on a Collection card → the card lifts into a floating "holding" chip → Collection slides
> out, Timeline slides in → valid slots pulse → tap a slot to drop → toast "Added to Tue 2pm · Undo."
> Escape cancels; the card floats home.

Two taps (like moving a chess piece on a touchscreen) instead of a sustained drag. Mechanically it **reuses**
`moveNode` / `unscheduleNode` and the existing drag-ghost layout machinery — a new *interaction* over the
same store actions, plus a small "held item" UI-state slice. Placed items correctly **stay** in the
Collection (the store already models the timeline as an additional surface, not a move —
[`collectionItemsOf`](../../apps/web/app/_components/itinerary-graph/store/itineraryGraphStore.tsx#L357)).

**Place-mode is a cross-surface overlay, not a route.** The held card floats over whatever's underneath, and
the Collection can slide *in or out over* the current surface — it's a **layer**, not only the `/collection`
destination (§2, §8). So it's driven by a transient `heldItem` UI slice, not a URL: refreshing mid-placement
returns you to the underlying destination with nothing held, rather than to a broken "holding a card" page.

---

## 8. Architecture changes

1. **Routes + nested layout.** New `itinerary/[id]/layout.tsx` renders the rail + persistent concierge and
   hosts the store Provider; child routes (`(dashboard) / timeline / collection / item/[nodeId]`) render into
   the planning space. **The one real refactor** is lifting the Provider from inside `ItineraryBuilderScreen`
   up into the layout so the store — and the concierge — survive view navigation. Clean, because the Provider
   is already isolated one level up.
2. **Store: split domain vs per-view UI.** Follow the store's own TODO — extract horizontal-view UI state
   (`pxPerMinute`, zoom) into a view-local store; keep `itineraryGraphStore` pure domain. Add small shared UI
   slices: `activeThread` (people axis) and `heldItem` (place mode). **URL vs state split:** routed
   **destinations** (Dashboard / Timeline / Card) live in the URL; **layers & transient modes** (the Collection
   drawer's open/closed, a held card mid-placement, the concierge context-chip) are UI state — the Collection
   drawer *may* encode open/closed as a URL param for shareability (open Q6), but place-mode is never a landable
   URL.
3. **Decompose the eight-tab aside** per the §1 table: chat tabs → concierge column; Party/Vault/Invoices/
   Booking → Dashboard sections; Build/Diff → advisor Studio.
4. **Card modal → route.** Move `NodeZoomCard` + `NotesPanel` into the `/item/[nodeId]` view; keep the modal
   only as the mobile full-screen sheet.

---

## 9. Phased build plan

> **The authoritative, execution-ready version is [planner-shell-plan.md](./planner-shell-plan.md) (M006)** —
> dependency-ordered, with per-slice data-model / touches / tests / deps. The summaries below are the overview;
> edit the plan doc, not this list, when sequencing changes.

Each slice sized to land independently behind tests, in the mvp-plan.md house style
(**goal · deliverables · touches · acceptance**). Order front-loads the shell so later surfaces have a home.

**PS1 — Shell skeleton (routes + layout + store lift).**
· *goal:* the three-region desktop shell and mobile tab bar exist and switch views, concierge persists across
nav. · *deliverables:* `itinerary/[id]/layout.tsx` with rail + concierge + Provider; child routes for
Timeline & Collection wrapping today's views unchanged; bottom tab bar < md. · *touches:* `itinerary/[id]/*`,
`ItineraryGraphView`, `HorizontalView` (strip its aside), `itineraryGraphStore` (Provider lift). ·
*acceptance:* switching views keeps one store instance + an open chat mounted; existing itinerary tests green;
deep-link to `/timeline` and `/collection` works.

**PS2 — Concierge shell + Artemis session list.** · *goal:* the concierge column hosts a scoped Artemis
**session list** (browse / resume / start / archive), un-collapsing today's single re-pinned session. ·
*deliverables:* `ConciergeColumn`, session-list UI, session titles, people-circle switcher, context-chip
scaffold; reuse key moves off `(client_id, audience)` to honor scope; session list/create/archive endpoints. ·
*touches:* `ConciergeChat`, [`services/agent.py`](../../apps/api/app/services/agent.py) (reuse/list),
`agent_sessions` (title column), new `ConciergeColumn`, mobile Chat tab. · *acceptance:* many named Artemis
sessions per scope; switching trips no longer re-pins; each session resumes its own history; advisor's private
sessions never leak into a shared thread.

**PS2b — General (human) chat channel.** · *goal:* a pure human channel (traveler ↔ advisor ↔ party),
separate from Artemis, scoped to basecamp or an itinerary. · *deliverables:* messages backend (thread +
participants + scope), the general-chat surface behind the Advisor/party circles. · *touches:* new messaging
tables/service, `ConciergeColumn`. · *note:* net-new backend — mine the sibling voyage-site app's human
GROUP/ORGANIZATION messaging (message list, reactions, participants) as prior art. · *acceptance:* advisor↔
traveler exchange a message with no agent turn; itinerary general chat shows that trip's party; basecamp
general chat is the account-level advisor relationship.

**PS2c — Artemis-in-human-chat bridge (@-mention & triggers).** · *goal:* summon Artemis into a general
(human) thread. · *deliverables:* mention parse + pluggable trigger sources → thread-scoped agent turn →
Artemis-authored message; **disclosure-by-thread-audience** enforcement + redaction-sweep coverage; proposals
to the graph; explicit AI attribution. · *touches:* messaging store, [`services/agent.py`](../../apps/api/app/services/agent.py),
[`test_traveler_context.py`](../../apps/api/tests/test_traveler_context.py). · *depends:* Q13 substrate choice. ·
*acceptance:* `@Artemis` in a client-visible thread answers client-safe *even when an advisor summons her*;
message attributed to Artemis; a proposed card lands on the single graph.

**PS3 — Dashboard view (dashboard-lite).** · *goal:* `/itinerary/[id]` lands on a guided dashboard. ·
*deliverables:* brief/splash, party, invoices/what-to-pay, advisor notifications, next-best-action; folds in
Party/Vault/Invoices/Booking panels. · *touches:* new `DashboardView`, existing panels, `/basecamp` reconciliation.
· *acceptance:* both roles land here; next-action reflects real state (needs brief → capture; unpaid invoice → pay).

**PS4 — Card detail as a route.** · *goal:* clicking a card opens `/item/[nodeId]` full-bleed. · *deliverables:*
card view w/ actions (maps/directions), notes, "ask Artemis about this" → context chip, manual scheduling; type-
specific UI wired from the prototype card set. · *touches:* `NodeZoomCard`, `NotesPanel`, prototype cards, concierge
context chip. · *acceptance:* deep-linkable; "ask about this" scopes the concierge; note visible to party.

**PS5 — Place mode.** · *goal:* pick-then-place scheduling alongside drag. · *deliverables:* Schedule action,
holding chip, slot-target highlight, cancel/undo; `heldItem` slice. · *touches:* `CollectionRail`, timeline canvas,
store. · *acceptance:* no-drag placement lands a card on a slot; Escape cancels; item stays in Collection; keyboard-
and touch-accessible.

**PS6 — Advisor Studio + polish.** · *goal:* Build/Diff move out of the traveler shell. · *deliverables:* advisor-only
Studio destination; concierge collapse; responsive pass. · *acceptance:* travelers never see authoring; advisor
authoring unchanged in behavior.

_(Future: Cinematic view; proactive Artemis trigger rules (§5); travel-party invite.)_

---

## 10. Open questions & decisions to lock

Answer by number. My current lean is in **bold**. **Status:** all decided (default) in
[planner-shell-plan.md §1](./planner-shell-plan.md) except **Q13** (held) — veto any default before its slice.

1. ~~Chat model — 1:1 threads vs a group "Trip" thread?~~ **Largely resolved by Q9–Q12 + harmonization:** the
   itinerary **general chat is already multi-party** (you ↔ advisor ↔ that trip's party, Q11), and Artemis joins
   it by **summon** (§5 harmonization), not as a standing member; **AI sessions** stay 1:1 (you ↔ Artemis).
   Residual: do AI sessions ever need to be shareable/multi-party, or always 1:1?
2. **Card "ask about this."** **DECIDED (default, M006):** context-chip into the persistent concierge — not a
   card-embedded chat tab.
3. **Card detail surface.** **DECIDED (default, M006):** full-bleed takeover with back (desktop) / full-screen
   sheet (mobile). Not split, not over-canvas.
4. ~~Dashboard vs Basecamp.~~ **RESOLVED (via §5):** keep BOTH — Basecamp is the account/cross-trip home (and
   the home for basecamp-scoped chat); Dashboard is the per-trip home. Different levels, not competitors.
5. **Concierge default state.** **DECIDED (default, M006):** open by default ≥ ~1100px, collapsible;
   auto-collapsed below.
6. **Places axis in URL vs state.** ~~Routes per view vs store state?~~ **Refined:** routed **destinations**
   (Dashboard / Timeline / Card) in the URL for deep-linking + back button; **layers / transient modes**
   (Collection drawer, held card, concierge context) as UI state (§8). Caveats logged: deep-linking + card/agent
   access are **role-agnostic** (travelers click cards & ask Artemis too), and the **Collection is a layer** that
   floats over other surfaces in place-mode, not only a destination. Still open: does the Collection drawer's
   open/closed state belong in the URL (shareable) or stay purely local?
7. **Rail contents & order.** **DECIDED (default, M006):** Home · Timeline · Collection · ─ · Studio
   (advisor-only, below a divider). Party + notifications live **in the Dashboard**, not the rail.
8. **Scope & sequencing.** **DECIDED (default, M006):** a new milestone **M006**, landing incrementally; **PS1**
   (shell skeleton, non-breaking) is the first cut. Critical path PS1 → PS2 → PS4.
9. ~~What is "general chat"?~~ **RESOLVED:** a **human** channel (you ↔ advisor ↔ party), **human by default** —
   Artemis is *summonable* into it, not a standing member (§5 harmonization). Net-new (§5, PS2b).
10. ~~AI session multiplicity.~~ **RESOLVED:** a **session list** — many named, resumable Artemis conversations
    per scope; reuse must honor scope, not collapse to `(client_id, audience)` (§5, PS2).
11. ~~General-chat participants & scope.~~ **RESOLVED:** basecamp general chat is just **you ↔ advisor** (or an
    AI session) — no party at the basecamp level; party is strictly per-itinerary. Itinerary general chat =
    you ↔ advisor ↔ that trip's party.
12. ~~Sessions → graph.~~ **RESOLVED:** **single spine** — Artemis sessions are peers; all propose onto the one
    itinerary graph. No distinguished "building" session.
13. **Chat substrate (harmonization).** Unify on one thread/message store with `agent_session` as the per-thread
    AI engine (**lean**), or keep two stores bridged by a mention→turn→message adapter? Gates PS2 / PS2b / PS2c.
    See §5 *Harmonizing Artemis into the human channel*.

### PS0 resolution — Q13 (recommendation, pending sign-off)

**Recommendation: UNIFY** — one `threads` / `messages` / `thread_participants` store, with
`agent_sessions` **retained as the per-thread AI *engine*** (not the message store). Draft migration:
[`scratchpad/00NN_messaging_threads.draft.sql`](../../) (throwaway — real one lands in PS7). This is Q13's
lean (a); the spike hardens it into a concrete schema and settles *how* `agent_sessions` relates.

*What the two priors told us.* Today's `agent_sessions`/`agent_turns` (0004/0009/0018) carry scope
(`itinerary_id`), an `audience` enum (`traveler|advisor`), an open/ended lifecycle + reuse key
`(client_id, audience, ended_at IS NULL)`, AgentCore coupling (`agentcore_session_id`), and **zero RLS**
(authz is service-layer). The sibling **voyage-site** models *human* messaging conversation-centrically —
`messages(author_id nullable, is_asked_from_ai, parent_message_id, soft-delete, edit-chain)`,
`message_reactions`, `conversation_seen` — but with **implicit** participation (via authorship/seen + org
membership) and **no agent lifecycle at all**. So voyage-site is prior art for the message *shape*, not the
session model: we take its message columns and make **participation explicit**, because OV's disclosure rules
must know exactly who can see a thread.

*The unified shape.*
- `threads(id, client_id, itinerary_id?, kind∈{ai_session,human}, audience, title, created_at, archived_at)`
  — the container. `audience` (the disclosure boundary) lives **on the thread**, which is what makes the PS8
  invariant fall out. The open-AI-thread unique index keys on **scope** `(client, itinerary, audience)`,
  un-collapsing today's single re-pinned session (this *is* PS2's reuse-key fix, re-expressed).
- `messages(id, thread_id, author_kind∈{traveler,advisor,artemis,system}, author_id?, content,
  proposed_node_id?, parent_message_id?, created_at, edited_at?, removed_at?)` — the canonical, human-visible
  transcript for **both** human turns and Artemis turns; `author_kind='artemis'` is the explicit AI
  attribution (rule 2). A proposal flows to the one graph via `proposed_node_id` (Q12).
- `thread_participants(thread_id, actor_kind, actor_id, …)` — explicit membership. AI session = {the human} +
  Artemis (standing); human channel = party + advisor, Artemis **absent** (summoned per PS8, not standing —
  rule 3).
- `agent_sessions += thread_id`. An AI-session thread has exactly one bound `agent_session` (the engine); a
  human thread has none until a summon opens a **thread-scoped** turn whose reply is inserted as an
  `author_kind='artemis'` message. **`agent_turns` stays the raw model-IO ledger** (latency/retries/model);
  `messages` is the spine — so we keep the ops telemetry without duplicating the user-visible content.

*Why unify over bridge.* Every harmonization behaviour (§5) — mixed threads, "advisor joins an AI session,"
@-mention, and **disclosure-by-thread-audience** — is a free consequence of "one message store + audience on
the thread." The bridge's cost is precisely the drift the redaction sweep would then have to cover in *two*
places (agent_turns **and** the human store). Unify pays more upfront in PS7 (the migration + writing a thread
on session-open) but makes **PS8 trivial**: a summon is just a thread-scoped turn that inserts one message,
and the PS8 disclosure sweep is a single assertion over `messages.content` on any `audience='traveler'`
thread — regardless of who summoned.

*Interim allowance (keeps the plan's sequencing).* The migration is **additive + back-compatible**, so **PS2**
can still ship first (add `title`/`archived_at` + scope-aware reuse on `agent_sessions` as written), and
**PS7** introduces `threads` and backfills each open `agent_session` into a `kind='ai_session'` thread with
its turns replayed into `messages`. No rework is thrown away; PS2's session becomes "a thread of kind
`ai_session`."

*Status:* Q13 is the one held decision (§8, and plan §8). This is the PS0 output for sign-off — **confirm
before PS7**; on milestone green-light it graduates to a `doc/decisions.md` D0xx.

### Your thoughts & questions (capture here)

- **Invoices are per-inventory, not just trip-level.** Basecamp shows the roll-up, but the traveler needs to
  see a charge/booking/payment against the specific item — so money gets a **card facet** (§6f) with a
  parent↔child link to the Dashboard roll-up (§4). Schema already supports it (`invoice_line_items.node_id`).
  _Incorporated._
- **Chat = human general channel + scoped Artemis session list.** _Resolved Q9_ (general chat is a **human**
  channel, no AI — net-new) and _Q10_ (AI = a **scoped session list**). Scope (`itinerary_id`, [0009]) and
  audience (traveler/advisor, [0018]) already exist; the gaps are **multiplicity** (reuse collapses to one live
  session per `(client_id, audience)` and re-pins,
  [`services/agent.py:375`](../../apps/api/app/services/agent.py#L375)) and a **net-new human channel**.
  Reshaped §5; split the build into **PS2** (Artemis session list — un-collapse existing infra) and **PS2b**
  (new human channel — mine voyage-site prior art). Side effect: resolves Q4 (Basecamp exists as a cross-trip
  shell). New follow-ons: **Q11** (general-chat participants/scope), **Q12** (multiple sessions → one graph).
- **Harmonize AI into human chat via @-mention / triggers.** _Resolved Q11_ (basecamp = you ↔ advisor only;
  party is per-itinerary) and _Q12_ (single spine; sessions are peers). Added the harmonization model to §5:
  one thread substrate; Artemis *standing* in AI sessions, *summoned* in human chats; one trigger→turn→message
  bridge; **disclosure follows the thread's audience, not the summoner.** New fork **Q13** (unify vs bridge
  substrate); new slice PS2c.
- **Routing caveats (Q6).** URL routing is great for deep-linking, but (1) travelers click cards and ask
  Artemis too — routes + agent access are **role-agnostic**, affordances-within differ by role; and (2) the
  **Collection is a layer**, not just a destination — place-mode floats it (and a held card) *over* other
  surfaces, so that's transient `heldItem` state, not a route. Refined Q6; threaded through §2 (destinations vs
  layers), §4, §7, §8. _Incorporated._
- _(next — drop notes against the numbers above or add new items)_

---

## 11. What's already there (reuse map)

Grounding that this is an unbundling: the pieces exist, they're just fused.

- **View-agnostic store + isolated Provider** — ready for multiple views
  ([`itineraryGraphStore.tsx`](../../apps/web/app/_components/itinerary-graph/store/itineraryGraphStore.tsx),
  [`ItineraryGraphView.tsx`](../../apps/web/app/_components/itinerary-graph/ItineraryGraphView.tsx)).
- **Two chat threads + PartyPanel** — the people axis, latent
  ([`ConciergeChat`](../../apps/web/app/_components/itinerary-graph/views/horizontal/ConciergeChat.tsx),
  `PartyPanel`).
- **Collection board/rail variants** — the Collection view, sized two ways
  ([`CollectionRail`](../../apps/web/app/_components/itinerary-graph/collection/CollectionRail.tsx)).
- **Notes as graph nodes** — card notes visible to party, already wired
  ([`NotesPanel`](../../apps/web/app/_components/itinerary-graph/shared/NotesPanel.tsx), `addAttachedNote`).
- **Per-node invoicing already in the schema** — `invoice_line_items.node_id` + `bookings.invoice_line_item_id`,
  so the card's money facet (§6f) is a new *view*, not a new data model
  ([`0023_invoices.sql`](../../supabase/migrations/0023_invoices.sql),
  [`0025_bookings.sql`](../../supabase/migrations/0025_bookings.sql)).
- **Drag-ghost + move/unschedule actions** — place mode reuses these
  ([`HorizontalView`](../../apps/web/app/_components/itinerary-graph/views/horizontal/HorizontalView.tsx),
  `moveNode`/`unscheduleNode`).
- **Responsive one-tree pattern** — desktop/mobile off the same store, toggled by `display`
  ([`ItineraryGraphView.tsx:88-104`](../../apps/web/app/_components/itinerary-graph/ItineraryGraphView.tsx#L88)).
- **Prototype card set** — type-specific card UIs for the detail surface
  ([`prototype/cards/`](../../apps/web/app/prototype/cards/)).
