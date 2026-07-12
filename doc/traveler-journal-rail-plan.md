# Traveler Journal — Rail & Layout Redesign

Plan of record for the `feat/traveler-journal` right-rail + layout rework. Design
was settled in conversation; this is the build spec. Diff mode is **parked** for
separate re-examination and intentionally not folded into the affordance model.

## Progress log (handoff)

- **Phase 1 — done.** `JournalView.tsx`: dropped `mx-auto max-w-6xl` from the
  container (was centering the whole rig) and capped the Journal column at
  `lg:max-w-[680px]`. Spine now rides the left; freed width trails right for the
  rail / future `2xl` inline detail. Cards were already `max-w-[420px]`, so the
  cap governs the margin channel, not card width. Journal test suites green (47),
  web typecheck clean. *Visual confirmation on a wide viewport still pending —
  batch it with the Phase 2c UI review.*
- **Phase 2a — done.** New pure resolver
  `views/journal/affordances.ts` → `resolveNodeAffordances(s, node, {hasProblem})`
  returning `{approve, reschedule, edit, notes, ask, locked}` as string unions.
  Composes the existing selectors (`s.canEdit` = advisor, `selectCanSchedule` =
  real editable fork, `selectCanApprove`/`selectCanLeaveNote`/`isSchedulePinned`).
  13 matrix tests in `tests/itineraryGraph/journalAffordances.test.ts`, all green;
  web typecheck clean.
  - **Refinement vs the plan's matrix:** "advisor editable" = the working-copy
    fork (`selectCanSchedule`), not "any advisor on the trunk" — the UI routes
    advisor authoring through forks, so advisor-on-trunk resolves to `none`
    (edit in your workspace), matching the existing `RailEditPanel` gate.
- **2b — dropped (see decision below).**
- **Phase 2c — done.** Rewrote `RightRail`'s active state into the three zones,
  driven by the 2a resolver (`resolveNodeAffordances` computed from live store
  state, `hasProblem` fed from the active finding):
  - **Zone 1** `RailIdentity` — the NodeZoomCard duplicate is GONE; replaced by a
    compact accent(mood)·type·time·title header + `RailAsk` (settled/booked chip
    or the advisor re-approval hint) + Approve + "Open full →".
  - **Zone 2** — `RailEditPanel` / readonly-legibility / new `RailPrice` (headline
    figure; breakdown expando deferred) / Notes (`RailNoteAction`, already an
    expando). Diff-change stays here.
  - **Zone 3** — enrichment: part-of-journey + problem; map slot left as a
    documented TODO (coords-gated, second-class).
  - Idle gains a restrained atmosphere wash (`journal-rail-atmosphere`);
    image-backed treatment deferred.
  - All existing rail sub-components + testids preserved. Web typecheck clean;
    all rail test files green (journalNotes/Diff/Phase3/Phase5 + affordances).
  - **Follow-ups noted:** notes→real advisor↔traveler thread (needs the data
    check), Price breakdown expando (billing wiring), the Zone-3 map, atmosphere
    image source, and fuller convergence (route every gate through the resolver;
    2c drives the ask via the resolver but keeps the proven action-component
    gates). Advisor·approved "edit in your workspace" hint not yet added.
- **Phase 3 — done (structure; browser pass pending).** Added the `@modal`
  parallel slot under `(shell)`: `@modal/default.tsx` (null), the intercept
  `@modal/(.)item/[nodeId]/page.tsx`, and `_shell/CardDetailModal.tsx` (a
  dismissible overlay reusing `CardDetailView`; Escape / backdrop / ✕ →
  `router.back()`, body-scroll lock). The shell layout now takes a `modal` slot
  and renders it inside `ItineraryShell` (so the modal shares the store +
  concierge). `next build` registers both `/itinerary/[id]/(.)item/[nodeId]`
  (intercept) and `/itinerary/[id]/item/[nodeId]` (hard-nav full page); typecheck
  clean. **Pending:** a browser pass to confirm soft-nav → overlay, hard-nav →
  full page, and dismiss; plus visual polish (CardDetailView is a full-bleed
  takeover — its own back-chrome may want hiding inside the modal frame).
- **Phase 4 — not started.**

> ⚠ **Pre-existing, unrelated test failure** (not from this work): the full web
> suite has one red — `store.test.tsx > selectCanApprove > advisor may
> approve-all …` expects `true` but the selector returns `false`
> (`if (s.canEdit) return false`). Both files are untouched by every commit in
> this branch's rail work. Left as-is; flag for whoever owns `selectCanApprove`.

### Phase 2b — DROPPED (decided)

Decision: **do not build the in-place trunk demote-edit.** Advisor-edits-approved
→ re-approval is delivered by the existing fork + reconcile flow; advisor·approved
in the rail resolves to "edit in your working copy." The resolver keeps its
`advisor-demote` / `reapproval-warning` branch as tested, defensive forward-compat
(fork demotion means production data won't present advisor·editable·approved, so
it stays dormant — cheap to keep, ready if in-place editing is ever wanted).

### (History) Open question on Phase 2b — surfaced while building 2a

The "advisor edits an approved card → traveler re-approves" capability **already
exists via fork + reconcile**: forking demotes `approved → pending`
([fork.py:8/71](../apps/api/app/services/fork.py)) so an advisor never edits an
"approved" node — they edit a pending one in their working copy — and reconcile
demotes the trunk node + applies the change
([fork.py:701–726](../apps/api/app/services/fork.py)), after which the traveler
re-approves. So **2b (a direct, in-place atomic demote-edit on the trunk) is only
needed if advisors should edit approved cards from the rail WITHOUT switching to
their working copy.** Pending a decision: build 2b (enables in-place), or drop it
(rely on the existing fork/reconcile flow) and treat advisor·approved in the rail
as "edit in your workspace." The resolver already carries the `advisor-demote`
branch, dormant until this is decided.

## Problem

Two independent faults in [`JournalView`](../apps/web/app/_components/itinerary-graph/views/journal/JournalView.tsx):

1. **Centered, not left-anchored.** The three-column rig is `mx-auto … max-w-6xl`
   (JournalView.tsx:327) — on a wide screen it floats in a 1152px box with dead
   gutters on both sides; the spine reads as "middle with waste on the left."
2. **The active rail is a bigger copy of the focused card.** [`RightRail`](../apps/web/app/_components/itinerary-graph/views/journal/RightRail.tsx)
   leads with `NodeZoomCard` (RightRail.tsx:158) — same card, zoomed, no new
   information. The valuable verbs (approve, note, edit) trail beneath it.

## Principles

- **Stable things in stable places; richness that appears sometimes is a
  second-class citizen.** Zone *slots* are fixed and never reorder. A slot
  renders its live control **or a legible substitute** — never a grayed-out
  button. Motion the **user** triggers (expanding a section) is fine; motion the
  **data** triggers (a map appearing) must never move the stable anchors.
- **Role is the source of truth, not derived `canEdit` flags.** The affordance
  resolver is a store selector reading role/state/fork at the point of use, not a
  boolean drilled down as a prop.
- **Same screen, responsive** — never parallel routes/views.

## Responsive tiers

| Tier | Width | Behavior |
|---|---|---|
| Small | `< lg` (<1024) | No rail. Tap a card → full detail (as an intercepting modal). |
| Medium | `lg`–`2xl` (~1024–1536, incl. 1280 mdpi) | Card **selects** → drives the cockpit rail. A second gesture opens full detail. |
| Very large | `2xl`+ (~1536+) | Full detail inline on the right, permanent. No modal, no second click. |

## The rail is a cockpit, not a viewer

Fixed zones, fixed order; each renders-or-collapses:

- **Zone 1 — Identity + the ask** (stable top). Per-vertical color + icon
  (`getVerticalMeta`, not brand orange) · title · time. Carries the **primary
  contextual action**: Approve when pending, "needs attention" when there's a
  problem (detail lives in Zone 3). "Open full →" is a quiet handle on the header
  (opens the intercepting modal).
- **Zone 2 — Expandable detail sections** (stable headers, user-controlled
  depth). **Notes** (advisor↔traveler thread, composer at the tail — absorbs the
  old "Leave a note" verb) and **Price** (summary → breakdown on expand). Also
  hosts the **reschedule** control (day + time) when the affordance resolves live.
- **Zone 3 — Enrichment** (second-class, blooms below, may be empty). Static map
  (coords-gated — often absent, and that's fine), problem explanation + get-help,
  part-of-journey.
- **Backdrop — Atmosphere** behind the idle (nothing-selected) state only.

Idle rail shares Zone 1/2 geometry so focusing a card feels like the frame
filling, not a panel swap.

## Affordance resolver (the 3-axis matrix)

One pure selector — `resolveNodeAffordances(state, node)` → the intent set the
zones render from. Axes: **role × node-state × fork-context**.

### The lock model (core)

A node is content-locked by three pins; the resolver checks which apply:

| Pin | reschedule | edit | Applies |
|---|---|---|---|
| **booked / confirmed** (G1) | 🔒 | 🔒 | everyone, hard |
| **schedule-pinned** (flight) | 🔒 "set by airline" | ✓ *(other fields)* | everyone |
| **approved** | 🔒 / ✓† | 🔒 / ✓† | **hard for traveler**, **soft† for advisor** |

† An advisor edit of an approved node is live, but **demotes the node back to
`pending`** in the same transaction → the traveler re-approves. Zone 1 warns:
"Editing will ask [traveler] to re-approve." (See backend change below.)

### Traveler

| Context · State | approve | reschedule | edit | Zone-1 ask |
|---|---|---|---|---|
| trunk · **pending** | ✓ | →fork | →fork | **Approve** |
| trunk · **approved** | — | 🔒 | 🔒 | Approved ✓ |
| own fork · **pending** | — | ✓ | ✓ | *(edit)* |
| own fork · **approved** | — | 🔒 | 🔒 | Approved ✓ |
| any · **booked/confirmed** | — | 🔒 | 🔒 | 🔒 Booked |

`notes` = ✓ →advisor in every row. In a fork a traveler may move anything **not**
pinned by booked / schedule / approved.

### Advisor

| Context · State | reschedule | edit | Zone-1 ask |
|---|---|---|---|
| trunk *or* fork · **pending** | ✓ | ✓ | *(status)* |
| trunk *or* fork · **approved** | ✓† | ✓† | *"edits → re-approval"* |
| any · **booked/confirmed** | 🔒 | 🔒 | 🔒 Booked |

`approve` never appears for advisors; `notes` = ✓ internal. Advisor writes on the
trunk are allowed (only non-advisor trunk writes 409), so trunk ≈ fork for
editing — the trunk/fork difference for advisors is reconcile/publish (diff mode,
parked).

### Modifiers (applied after the cell resolves)

- **schedule-pinned** (flights): live `reschedule` → read-only "set by the
  airline" (`isSchedulePinned`).
- **draft-preview** (traveler viewing "mine" before a fork exists): edits render
  live; the **first** mutation lazy-forks (`forkAndMove`).
- **no write creds**: `notes` absent, everything read-only.
- **problem present**: Zone-1 ask becomes/adds "needs attention"; explanation +
  get-help in Zone 3.

### discarded

Not surfaced in the rail (filtered from the reading) — no row.

## Backend rule change (option b) — DROPPED

> **Not building this** (decided after 2a). The fork+reconcile path already
> delivers advisor-edits-approved → re-approval. Kept below for context.

Today the G1 status gate lumps `approved` with `booked/confirmed`
([`_FIRMED_STATUSES`](../apps/api/app/services/itineraries.py), itineraries.py:590)
and refuses an advisor edit of any firmed node with `demote_before_edit`
([`_check_status_gate`](../apps/api/app/services/itineraries.py), itineraries.py:616–653).
The auto-demote-then-edit we want already exists **but only inside reconcile**
([fork.py:701–726](../apps/api/app/services/fork.py)).

**Change:** split `approved` out of the blanket advisor refusal — an advisor edit
of an `approved` node **demotes it to `pending` and applies the edit in one
transaction** (mirror the reconcile precedent at fork.py:718). `booked/confirmed`
stay hard-refused (their demotion is money-gated through `services.bookings`).
This avoids the "un-approved with no edit" partial-failure window a two-call
client orchestration would open.

## Full detail as "modal, not route"

Next 15 intercepting + parallel routes: a `@modal` slot + `(.)item/[nodeId]`
intercept over the existing `/itinerary/{id}/item/{nodeId}` page. Navigating from
the Journal renders a dismissible overlay (back/Escape closes); a hard nav to the
URL renders the real full page. The existing deep link
([JournalView.tsx:308](../apps/web/app/_components/itinerary-graph/views/journal/JournalView.tsx))
is unchanged — it just starts feeling like a modal. Small-screen tap and
medium-screen "Open full" become the same gesture.

## Phased build (each phase shippable alone)

### Phase 1 — Left-anchor + spine width
- `JournalView.tsx:327`: drop `mx-auto … max-w-6xl`; pin the container left with a
  page pad; cap the **spine column** at a reading measure (~640–680px) so it
  doesn't stretch; let the right region absorb the freed width. DayRail stays
  leftmost.
- **Acceptance:** on a wide viewport the spine rides the left; no dead center
  gutter. Existing Journal tests stay green.

### Phase 2 — Rail cockpit

**2a — Affordance resolver.** New pure module (e.g.
`views/journal/affordances.ts`) exporting `resolveNodeAffordances(state, node)`
returning `{ approve, reschedule, edit, notes, ask, locked }` as small string
unions (e.g. `reschedule: 'live' | 'fork-offer' | 'pinned-airline' |
'locked-booked' | 'locked-approved' | 'none'`). Consolidates the scattered
`selectCanApprove` / `selectEditable` / `selectTravelerEditable` / `onTrunk` /
status checks. **Exhaustive unit tests** over the matrix (every role × state ×
fork cell + the modifiers).

**2b — DROPPED.** See the decision above — the fork+reconcile flow already
covers advisor-edits-approved → re-approval, so no backend change.

**2c — Render zones from the resolver.** Rewrite `RightRail` active state: drop the
`NodeZoomCard` lead; build Zone 1 (identity + ask, vertical color/icon, Approve /
re-approval warning), Zone 2 (Notes + Price expandos, reschedule slot), Zone 3
(map / problem / part-of-journey), atmosphere backdrop on idle. Fold the existing
approve/note/edit/problem pieces into the zone frame. Idle shares Z1/Z2 geometry.
- **Acceptance:** the medium/mdpi rail carries stable identity + Approve that
  never moves card-to-card; enrichment blooms below without disturbing the
  anchors; the matrix behaviors match 2a.

### Phase 3 — Intercepting-route modal
- Add the `@modal` parallel slot + `(.)item/[nodeId]` intercept; the modal renders
  the full-detail component, dismiss on back/Escape/overlay-click. Small-screen
  tap and "Open full" route through it.
- **Acceptance:** from the Journal it's an overlay; a hard nav to the URL is the
  full page; back dismisses.

### Phase 4 — `2xl` inline-detail tier
- At `2xl`+, render full detail inline in the fluid right region permanently — no
  modal, no second click; selection *is* the open.
- **Acceptance:** at ≥1536 the full detail is always present; the second-click
  path is suppressed.

## Deferred / open

- **Diff mode** — re-examined separately; the resolver is built so diff mode can
  layer on as an orthogonal *mode* over the same zones, not a fourth matrix axis.
- **Notes thread model** — confirm attached notes carry `actor_kind` + timestamp
  well enough to render an advisor↔traveler chain, or whether that's a small
  model gap (Zone 2 Notes expando depends on it).
- **Atmosphere source** — pick the idle-backdrop image convention (Unsplash mood
  per the design-direction memory?).
