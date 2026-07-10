# The Journal — traveler itinerary experience redesign

Design proposal for the immersive vertical itinerary view sketched in [thoughts.md](thoughts.md#L49-L90).
Working name: **the Journal** (the itinerary as a travel journal you scroll through, on paper, with
watermark imagery — consistent with the existing light-editorial design direction).

We're going to use the Japan seed itinerary to visually explore / test, but also some sparser itineraries (e.g., a 2-day city trip, a 2-week multi-country trip) to make sure the layout and interaction patterns scale.

## The one-sentence pitch

When a traveler opens their itinerary, they land on a single page: an edit-in-place hero, and below it
a vertical journey — a spine of beautiful cards that reads like a story of the trip — with a right rail
that reacts to whatever moment they're looking at.

## What already exists (foundation audit)

This is not a from-scratch build. The survey of the codebase found:

| Need | Already built | Where |
|---|---|---|
| Vertical timeline with spine, duration bars, ambient backdrop, scroll anchoring | Prototype, working | `apps/web/app/prototype/itinerary-graph-vertical/` |
| Card spec: 13 node types × icon × accent/tint color, 5 statuses with non-color a11y cues, 3 widths (compact/glance/zoom) | Complete | `app/_components/itinerary-graph/shared/cards/tokens.ts`, `CardShell.tsx`, sandbox at `/prototype/cards` |
| View-agnostic data: timing resolution, tz inference, `start_synthesized` for unscheduled, `night_bar`, `alt_group`, `ambient_image`, `lane` metadata | Complete | `adapter/toItineraryTimeline.ts`, `model/types.ts` (`VerticalNodeMeta`) |
| Active-node state | Minimal but right | `focusedNodeId` in `itineraryGraphStore` |
| Detail surface for a node | Exists as a route | `/itinerary/[id]/item/[nodeId]` |
| Day-jump UI | Mobile `DayStrip`; axis day dividers | `views/mobile/DayStrip.tsx` |
| Drag/insert plumbing | @dnd-kit + framer-motion throughout | horizontal view, collection rail |
| Hero + brief | Dashboard hero renders it; editing goes through the `ItineraryIntake` overlay | `_shell/DashboardView.tsx:177-233` |

The genuinely new work: the **narrative layout engine**, the **scroll-active system**, the
**right rail**, **edit-in-place on the hero**, **virtual/elision nodes**, **fork-in-the-spine rendering
for alternatives**, and **cinema mode**.

## Core decision 1: the Journal is narrative, not metric

The vertical prototype (like the horizontal canvas) is *time-proportional* — `pxPerMinute`, zoom
presets. The Journal should explicitly **not** be. It lays out event-proportionally: cards stacked
with editorial rhythm, and *gap length expressed in buckets, not pixels*:

- **short gap** (< ~2h): plain spine segment
- **long gap** (an afternoon, "free time"): a **virtual node** — small circle, no card, a quiet caption
  ("A free afternoon in Kyoto"), derived from the gap or from existing `free_time`/`waiting` nodes
- **night**: the spine itself changes — darkens, moon glyph, `night_bar` metadata already models this;
  sleep/wake are virtual nodes bracketing it
- **elision** (multi-day empty span): a collapsed marker — "Days 12–18 · At sea" — expandable, with a
  jump affordance

This means two views with two jobs, both reading the same graph:

- **Journal** — the traveler's default. Reading, reacting, approving, light editing. Narrative layout.
- **Studio** (today's timeline canvas) — the advisor's working surface. Metric layout, lanes, zoom,
  authoring panel. Unchanged.

Consistent with the collection/wishlist precedent: the Journal is *a view over the graph*, never a
parallel store. Virtual nodes are derived client-side in a `toJournal()` layer on top of
`toItineraryTimeline` output; nothing virtual is ever persisted.

## Core decision 2: the Journal *is* the dashboard

`/itinerary/[id]` currently redirects to `/dashboard` (hero + next-action + approvals + money + party
modules). The redesign: the dashboard page becomes **hero + Journal**. The existing modules don't die —
they relocate:

- **Next action + approve-all + balance** → the right rail's *resting state* (what you see before any
  node is active). These are exactly the "trip at a glance" content the rail needs when idle.
- **Money / invoices ledger, travel party, advisor vault** → a quiet **footer section** after the end
  of the journey ("The practical part"), and deep links from the rail. Invoices should not interrupt
  the story mid-scroll.

No new route needed. The traveler's click from the Home tile lands directly on beauty (thoughts.md
scenario step 5–6 solved).

## The layout

```
┌────────────────────────────────────────────────────────────┐
│  HERO  (full-bleed mood image, edit-in-place)              │
│   MAR 14 — 11 NIGHTS ✎        title ✎        brief ✎       │
├──────────────────────────────────────┬─────────────────────┤
│  JOURNAL (scrolls)                   │  RIGHT RAIL (fixed) │
│                                      │                     │
│  ── Day 1 · Friday, March 14 ──      │  reacts to the      │
│   │                                  │  active node:       │
│  (✈)──[ Flight card        ]         │   · zoom-detail     │
│   │                                  │   · photos, place   │
│   │  ~ a quiet afternoon ~           │   · actions:        │
│   │                                  │     approve, move,  │
│  (◻)──[ Hotel card         ]         │     see options,    │
│   ┆  🌙 night                        │     ask Artemis     │
│  ── Day 2 ──                         │                     │
│   ├─(◉)──[ Experience A ]            │  idle state:        │
│   └─(◆)──[ …or this      ]  ← fork   │   next action,      │
│   │                                  │   approve-all,      │
│  (⌂)──[ Destination card   ]         │   balance           │
│   ▼  (scroll shadow + jump)          │                     │
├──────────────────────────────────────┴─────────────────────┤
│  day rail (floating): ●○○○○○○  "Day 1 of 11"  [jump]       │
└────────────────────────────────────────────────────────────┘
```

### The spine

A continuous line on the left of the card column. Node circles sit on it, filled with the type's
accent color and icon **from the existing `tokens.ts` mapping** — the circle is a miniature of the
card's identity. Status renders as the circle's ring using the existing status tokens (pending soft,
approved check, booked lock, confirmed double ring), so status reads at spine-glance without opening
a card. **Problem state**: red ring + an adjacent non-color glyph (⚠ badge outside the circle) +
one-line caption under the card; activating it puts the explanation and a "get help" action (chat
pre-seeded with the node) in the right rail.

### Graph-ness: forks in the spine

`alternative_to` edges / `alt_group` render as the spine literally splitting into two (or three) short
parallel rails, cards side by side (desktop) or stacked with an "or —" connector (mobile), rejoining
after the group. Choosing one is the existing approval action; the unchosen alternative collapses to a
ghost chip ("you also considered…", tap to restore). `grouped_with` renders as a bracket spanning the
group. This is the honest, subtle way to say "this is a graph" without a node-and-wire editor.

### Comparing versions: diff mode

The fork/trunk model (D030) needs a visualization: *my version vs. the official trip*. Two pairings
cover every real case — traveler's fork vs trunk, and advisor's working fork vs trunk (the advisor
reviewing a traveler's fork during reconcile is still the second shape with a different fork id).
**Never three-way** — and the backend agrees: `diff_fork` (G3, `apps/api/app/services/fork.py`) is
inherently pairwise, diffing a fork against its own baseline. It already returns everything the UI
needs: changes bucketed into `added / removed / changed / moved`, before/after snapshots, changed
field names, and a stable `change_id` that `reconcile_fork` consumes with per-change accept/discard
decisions. Diff mode is a rendering problem, not a data problem.

**Unified diff on one spine, not side-by-side columns.** Two parallel scrolling timelines are heavy on
desktop and impossible on mobile; a unified sequence reads like tracked changes in a manuscript, which
is exactly the Journal's register:

- The sequence is the union of both graphs, ordered by the fork's timing where a node exists there.
- **added** — the card renders vivid with a "new in this version" stitch on its spine segment.
- **removed** — a ghost card (trunk-only): dashed circle, muted, "not in your version".
- **changed** — a change dot on the circle; the right rail shows a field-level before/after.
- **moved** — a chip on the card; the rail shows old vs new time. (No ghost-at-old-position arrows —
  tried mentally, too much ink.)
- Where the versions agree, the spine is just the spine. Divergence density is visible at a scroll.

One vocabulary caution: **alternatives split the spine; versions do not.** The fork-in-the-spine
visual means "choose one of these experiences." Version divergence uses stitches/ghosts/dots so the
two ideas can't be confused. A slim dashed *second thread* alongside the spine may run through
diverged regions as a region cue, but the spine itself never forks for version diffs.

**Entry and actions:**
- Traveler: the "Your version" chip near the hero gains a *Compare with the trip* toggle. In diff
  mode the rail's idle state summarizes the divergence ("4 additions, 1 change") with *request
  reconcile* as the CTA.
- Advisor: the reconcile review opens the same view against the traveler's fork; activating a diffed
  node puts **accept / keep original** in the rail, wired to the existing per-`change_id` decisions
  (`accept_all` stays as the fast path). Refusals (`refused_booked` — G1 immutable) render as a lock
  explanation, not an error.
- Diff mode is a toggle over the Journal DOM, not a separate route.

### Scroll-active system

- IntersectionObserver against a **center band** (~viewport 35–55%). The card most inside the band is
  scroll-active.
- Explicit click **pins** the active node (`focusSource: 'click'` added next to `focusedNodeId` in the
  store). A pin releases when the user scrolls the pinned card fully out of the band — scroll resumes
  control. This is the "balance" rule from thoughts.md, made deterministic.
- The active node drives: right rail content, spine emphasis (circle scales slightly, connector
  brightens), and the ambient layer.

### Ambient layer

Behind the paper: the active node's `ambient_image` (already in `VerticalNodeMeta`; fall back to mood
tint from `MOOD_ACCENTS`) as a very low-opacity watermark/watercolor wash, crossfading between
neighbors as activation changes (300–600ms, framer-motion). Lottie is a **later garnish**: at most one
subtle loop per node *type* (plane drift, steam off a meal), lazy-loaded, and everything respects
`prefers-reduced-motion` (crossfades become instant swaps, no lottie, no autoscroll).

### Scale: 2 days to 2 months

- **Sticky day header** while scrolling within a day ("Day 4 · Tuesday · Kyoto").
- **Day rail**: a slim floating minimap (dots or micro-labels per day, current highlighted, click to
  jump — the Journal's equivalent of `DayStrip`, which mobile reuses directly).
- **Elision nodes** compress empty spans (see above).
- **Windowed rendering**: `content-visibility: auto` on card wrappers first (cheap, likely
  sufficient); true virtualization only if a 60-day trip proves it necessary. Ambient images lazy-load
  at activation-distance.
- **More-below cues**: bottom scroll shadow + "↓ 6 more days" jump pill when the tail is off-screen.

### Notes: the margin channel

Notes are the one write that works **everywhere, including the official trunk** — by design
(`selectCanLeaveNote`), a note is feedback for staff, not a graph edit, so it bypasses the fork and
approve gates entirely. The store already has the three shapes the Journal needs: `addAttachedNote`
(hangs off a host node — "why are we doing this at 1:30?"), `addFreeStandingNote` (dropped on a day —
"a dinner between these?"), and `addCollectionNote` (timeless, into the wish list). Notes are always
removable, even on a booked host.

The journal metaphor gives notes their natural home — **the margin**:

- An **attached note** renders as a margin annotation beside its host card (the existing note tokens:
  yellow tint, ✎ glyph, handwritten register), not as a full node on the spine. Affordance: a quiet ✎
  in the card's margin on hover/long-press, plus a *Leave a note* action in the right rail whenever a
  node is active.
- A **free-standing day note** is a small note card sitting on the spine in that day's flow (it *is* a
  node). Affordance: the `+`-on-the-line always offers *Note* — on the trunk it's the **only** thing
  the line offers a traveler, which makes the feedback channel discoverable exactly where the urge
  strikes ("something should go here → say so").
- The traveler's **own notes are editable in place**: tap → the text becomes a textarea, save on blur;
  delete is always available (mirrors the backend's notes-always-removable rule).

### Editing in the Journal (light, not Studio)

What the traveler can do depends on which version they're reading, and the Journal makes that legible
rather than burying it in disabled buttons:

- **On the official trip**: the only pencils are note pencils (margin ✎, `+`→Note). A content gesture
  (drag, insert-experience) offers the existing lazy-fork path — "make this yours?" — via the 409
  `fork_required` flow and the working-copy toggle.
- **On "Your version"** (a draft fork — `selectTravelerEditable`): full light editing.
  - **Insert**: the `+` on the line opens a picker that leads with the **Collection** (placing
    wish-list items is the #1 traveler edit), then "describe it to Artemis", then note, then blank
    card. Existing add-node + placement flows.
  - **Move**: drag the card along the spine; drop slots are the gaps (dnd-kit, as horizontal view
    does today). No freeform time-pixel math — a drop between A and B assigns a sensible slot time.
  - **Edit a card**: the right rail's detail becomes editable for the fields a traveler owns (title,
    note/body, time slot); deeper edits route to "ask Artemis".
- **Everything else** (durations, lanes, bulk ops) stays in Studio.
- The "Your version" chip near the hero is the mode indicator when `viewerOpenForkId` is set. Role
  (not derived flags) decides which actions render.

### Hero edit-in-place (kills the "edit brief" overlay for edits)

Each hero text element becomes its own inline editor, styled identically to its display state:

- **Title**: click → input, save on blur/Enter.
- **Brief**: click → auto-growing textarea over the image.
- **Timing**: click → popover with the existing timing-kind/date controls (the one case that needs
  real UI; a popover, not a page takeover).

Persistence is the same API the intake uses, then `router.refresh()` (the established pattern — brief
is a server prop). `ItineraryIntake` survives only as the **first-run** experience when the brief gate
fires; it's never the edit path again. No thin bar under the hero.

### Cinema mode

A mode flag on the same DOM, not a new view: chrome (rail, day rail, header) fades out, ambient goes
full-bleed instead of watermark, and a scroll driver eases from node to node with a dwell at each
(requestAnimationFrame, ~4s/node, pause on any input, Esc/tap exits). Entry: a small "Play" affordance
on the hero. This is the demo-day money shot and it's cheap once the Journal exists.

### Mobile

Same screen, responsive (per the established architecture preference — no parallel routes):
- Journal column goes full-width; spine slims.
- Right rail becomes the existing bottom-sheet pattern (`ConciergeSheet` interaction) or deep-links to
  `/item/[nodeId]` for full detail.
- Day rail = `DayStrip` reused.
- This can eventually *replace* `MobileItineraryLayout`'s day-feed as the traveler default, since the
  Journal is inherently a vertical mobile-first shape.

## What this changes in code (shape, not a plan yet)

- `app/_components/itinerary-graph/views/journal/` — new view family: `JournalView`, `Spine`,
  `JournalNode` (wraps existing `CardShell`/`CardBody`), `VirtualNode`, `ForkGroup`, `DayHeader`,
  `DayRail`, `RightRail`, `AmbientLayer`, `CinemaDriver`; later `DiffOverlay` consuming the G3 diff
  response (union sequencing + per-node change annotations).
- `views/journal/toJournal.ts` — derives the narrative sequence (day groups, virtual nodes, elisions,
  alt groups) from `ItineraryTimeline`. Pure function, unit-testable with vitest.
- Store: add `focusSource`, `journalActiveNodeId` (or reuse `focusedNodeId` + source); no schema/API
  changes — **zero backend work** in phase 1.
- `DashboardView` → hero (edit-in-place) + `JournalView` + practical footer; the money/party modules
  move rather than vanish.
- Prototype at `/prototype/itinerary-graph-vertical` stays as the metric-layout sandbox; the Journal
  borrows its ambient/measure code but is a distinct layout engine.

## Phasing

1. **Journal core** — `toJournal()` derivation, spine + cards + day headers, scroll-active + right
   rail (detail + idle state), lands as the dashboard below the existing hero. Read-only. This alone
   fixes the bland landing.
2. **Hero edit-in-place + margin notes** — title/brief/timing inline editors (intake demoted to
   first-run); attached + day notes with in-place editing (store actions already exist — this is the
   cheapest write and works on the trunk, so the feedback loop opens early).
3. **Interaction depth** — insert on the line (Collection-first picker), drag-to-move, editable rail
   detail on the traveler's fork, alternatives fork rendering, problem states wired to Analyze
   findings, approve from the rail.
4. **Diff mode** — unified version diff over the Journal (fork vs trunk), traveler compare toggle,
   advisor reconcile review with per-change accept/keep. Backend already done (G3 `diff_fork` /
   `reconcile_fork`).
5. **Atmosphere & scale** — ambient crossfades, lottie garnish, elision nodes, day rail, windowed
   rendering, cinema mode.

## Open questions

- **Advisor default**: does an advisor opening `/itinerary/[id]` also land on the Journal (with Studio
  one click away), or straight into Studio? Leaning: same landing, role-gated actions — one mental
  model of "the trip", Studio as the workbench you enter deliberately. ANSWER: yes. Land on the Journal, Studio is one click away. The Journal is the trip, Studio is the workbench.
- **Problem source of truth**: node "problems" need a home (Analyze findings mapped to node ids vs. a
  `metadata.problem` bag). Phase 3 decision.
  Answer: Defer this until after. Likely, we'll run an analysis pass via some trigger and this will populate the problems.
- **Chat placement**: does the concierge live in the right rail below the node detail, or stay a
  separate surface with "Ask Artemis about this" deep-seeding it? Leaning: rail hosts a compact
  composer that expands, so the reaction loop (look at node → ask about it) never leaves the page.
  Answer: Stays in the same place on the left rail.
