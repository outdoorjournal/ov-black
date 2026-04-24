# Itinerary Visualization — Option 1

A design exploration responding to [itinerary-visualization.md](./itinerary-visualization.md). This doc captures the *thinking*, not just the implementation. The running prototype lives at [apps/web/app/prototype/itinerary-graph/](../../../../../apps/web/app/prototype/itinerary-graph/) and renders at `/prototype/itinerary-graph`.

---

## How I read the brief

Three things stood out as non-obvious constraints that ruled out whole categories of solutions before I wrote any code.

**1. "Timeline, really."** The brief calls the thing a graph but then clarifies it's a timeline. That's a design-defining clarification. A freeform 2D graph (a la Miro / react-flow) has a very different information hierarchy than a timeline: a graph says "relationships matter"; a timeline says "sequence matters." Travel itineraries are fundamentally sequential — days go in order, you can't be in two places at once — so the timeline interpretation is correct. This immediately rules out generic graph libraries that optimize for freeform 2D layout.

**2. "Skeuomorphic, tactile, elegant."** These three words don't coexist easily. "Skeuomorphic" in 2025 usually means chunky iOS 6 buttons with glossy gradients. "Tactile" means physical-feeling. "Elegant" means restrained. The brief's reference to "a physical travel journal... a table filled with handwritten notes and sketches" resolves the tension: the target is **craft paper**, not plastic. Think Moleskine + fountain pen, not iOS 6 leather stitching. That points to: warm paper tones, layered soft shadows, subtle noise texture, a rotated "tape" accent on cards, serif display type — all things a component library gives you poorly. Bespoke craft over drop-in.

**3. "Alongside a conversation with AI."** The graph isn't the main event — it's co-equal with chat. That's a layout constraint (split screen, and a hard one on mobile) and a motion constraint (when the AI proposes something, it has to appear in *both* surfaces coherently). The brief's AI section asks explicitly how proposals, accept/reject, and questions work in-graph — so the AI integration isn't an afterthought. It's a first-class interaction target.

---

## Scope decisions (and why)

Before architecting anything, I asked four scope questions and took the recommended path on each. The reasoning matters more than the choices:

| Axis | Choice | Why |
|---|---|---|
| **Data** | Static TS fixtures matching `NodeResponse`/`EdgeResponse` | This is a *design* exploration, not a wiring exercise. The data model already exists and is expressive. Faking data against the real types means the prototype is wire-compatible later without rework. Avoiding auth + API calls cuts the dev-loop time by 10x. |
| **Stack** | `dnd-kit` + `framer-motion` + hand-rolled SVG | React-flow would have given me a graph in 100 LOC, but its aesthetic is "tech diagram." Fighting it into "craft paper" would be more work than starting clean. `dnd-kit` handles the thorny pointer/touch/keyboard drag primitives; `framer-motion` handles the tactile micro-animations; the layout and edge math are simple enough to write by hand. |
| **Location** | Unauthed route at `/prototype/itinerary-graph` | Prototype is a sandbox, not a product surface. Stakeholders evaluating it shouldn't need to log in. The existing middleware doesn't gate routes so this is free. |
| **AI demo** | Scripted mock replay using real `SseFrame` types | The agent runtime exists, but wiring a prototype through `/sessions` means boot a whole stack. Using the real `SseFrame` union for scripted scenarios proves the shape is right *and* runs without infrastructure. The same code consumes real frames later. |

The underlying heuristic in all four: **minimize the cost of being wrong**. A prototype's job is to make design decisions cheap to revise. Static fixtures + a design-controlled stack + no auth + scripted AI is the configuration with the shortest iteration loop.

---

## Design philosophy

The prototype holds to four principles:

### 1. The card is the atom

The brief is explicit: cards are the canonical unit. So I treated the Card component as the foundational design decision, not the graph. Everything else — the layout, the edges, the AI affordances — is in service of making cards feel right. Every node type (flight, hotel, experience, meal, transit, free_time, note, destination) has its own visual face, but they share a single shell. That shell carries the skeuomorphic weight: paper background with inline SVG noise, layered soft shadow, inset top highlight, rotated tape accent. Per-type bodies only need to handle the *content* difference (airport codes vs. photo vs. lined paper) — the "objectness" comes from the shell.

Status (idea → proposed → approved → booked → confirmed → discarded) is a modifier on the shell, not on the body. `proposed` adds the tape + a slow pulse. `approved` stamps a corner. `discarded` desaturates. This keeps the per-type code focused on the content and means we can introduce new statuses in one place.

### 2. The graph is the timeline is the schedule

The layout algorithm is day-column × type-order, not a freeform 2D placement. Each day is a vertical column. Within a day, cards stack in a fixed type priority (flights up top, destinations and experiences in the dominant middle, notes at the bottom). This maps directly to how people mentally organize trips — by day, with a natural within-day order (morning flight, check in, afternoon activity, evening meal). It's not a DAG visualization; it's a schedule you can manipulate.

`alternative_to` edges get a special treatment: sibling options stack offset-diagonally from their canonical primary (`-8px x`, `+44px y` per alt), and an SVG bracket with the label "or" connects them. This is how I render "choose one of three Amalfi day trips" without cluttering the main column. It preserves the sequence reading — there's clearly *one* day 3 slot, with options stacked onto it.

`parent_subgraph_id` collapses to a single "folder" card at the top level (e.g., the 4-day Patagonia W-circuit becomes one card in the top timeline). Clicking opens `NodeDetailSheet` which mounts a mini `TimelineCanvas` on the child set. This is how we keep a 10-day trip with an embedded 4-day trek from overwhelming the main view — and it makes the nesting explicit rather than implicit.

### 3. Edges are not all the same

Different edge types carry different semantic weight, and the rendering reflects that:

- `follows` is the spine. Solid line, arrowhead, moderate opacity. If you squint, you see this path left-to-right across the whole trip.
- `alternative_to` is a choice. Dashed, "or" label. Visually softer so it doesn't compete with the spine.
- `connected_by` marks transit. Thin with a glyph at the midpoint. The plane/train handles continuity information inline.
- `requires` is a constraint. Red-tinted with a diamond marker. Visually alarming because breaking a requirement breaks the trip.
- `grouped_with` is not a line at all — it's a translucent rounded rectangle drawn *behind* the grouped cards. A multi-night hotel stay reads as "these cards are one thing" without a distracting line connecting them.

### 4. Mobile is its own design

The brief's mobile section proposes a specific gesture: "swipe out of the timeline, scroll to where they want to go, then swipe it back in." I took this seriously and didn't retrofit desktop drag-drop to mobile. Mobile has its own component (`MobileTimeline`) with its own mental model: cards are physical objects you pluck out, hold in a floating tray, scroll to a destination, and drop. The pluck animation uses `framer-motion`'s `useAnimate` to sequence the lift; the parked card lives in a fixed-position floating tray with a `-2deg` rotation (like picking up a real card off a table); every remaining day slot becomes a tappable drop zone while held. No horizontal scrolling, no zoom, no pan. The sequence is preserved because everything is vertical.

---

## Architecture

The file layout follows the underlying conceptual split: **state is separate from presentation, data is separate from both**. The cleanliness matters for a prototype because the iteration happens in the presentation layer.

```
apps/web/app/prototype/itinerary-graph/
  page.tsx                       Route entry; loads fixtures; renders shell
  _lib/types.ts                  Type re-exports + local metadata shape + constants
  _state/
    layout.ts                    Pure function: (nodes, edges) → Positioned[]
    useTimelineState.ts          Reducer wrapping all graph mutations
    mockStream.ts                Scripted async scenarios that dispatch actions
  _fixtures/
    builders.ts                  makeNode / makeEdge / makeItinerary helpers
    tuscany.ts / amalfi-nested.ts / tokyo-kyoto.ts / patagonia.ts
    index.ts                     Exports getSampleTimelines()
  _components/
    PrototypeShell.tsx           Top-level layout, owns state, routes callbacks
    TimelineCanvas.tsx           Desktop: DndContext + positioned cards
    MobileTimeline.tsx           Mobile: pluck/park/land gesture flow
    EdgeLayer.tsx                SVG overlay with per-type styling
    Card.tsx                     Skeuomorphic shell + 8 per-type faces inlined
    GhostCard.tsx                Proposal-mode card with Accept/Dismiss affordances
    ConversationPanel.tsx        Right-rail chat with inline proposals
    AIDemoController.tsx         Three buttons: propose / assemble / modify
    ViewportToggle.tsx           Desktop / Mobile pill switch
    TimelineSwitcher.tsx         Tabs for the four sample itineraries
    NodeDetailSheet.tsx          Expandable detail drawer with nested subgraphs
```

### The reducer is the truth

All graph state lives in one reducer (`useTimelineState`). Actions are typed: `MOVE_NODE`, `PROPOSE_NODE`, `ACCEPT_PROPOSAL`, `ASSEMBLE_DRAFT`, `APPEND_DELTA`, etc. The canvas and the chat panel both read the same state and dispatch the same actions — that's how a single AI proposal renders coherently in both surfaces. The conversation isn't a sibling of the graph; they're two views of one reducer.

A specific consequence: clicking Accept on a ghost card in the graph vs. clicking Accept on the inline proposal in the chat panel dispatches the same action (`ACCEPT_PROPOSAL`). Both surfaces update consistently because both read the same `pendingProposals` array.

### The layout algorithm is pure

`computeLayout(nodes, edges)` takes the current graph and returns a `Map<nodeId, Positioned>` plus bounding width/height. It's a pure function — no refs, no DOM measurement, no side effects. That lets the layout drive both the card positions and the SVG edge paths in a single render pass, and it makes the whole thing debuggable by console-logging the layout result. Re-layout on every change is fine at this scale (tens of nodes, not thousands).

### The mock AI is a real protocol

`mockStream.ts` doesn't mock by returning fake component state. It dispatches the same reducer actions that would fire from a real SSE stream — `PROPOSE_NODE` with a real-shaped `AgentNode`, `ASSEMBLE_DRAFT` with a list of new edges, `APPEND_DELTA` with token text. The difference between the prototype and a real agent run is only where the frames come from; the consumer side is identical. This is the cheapest way to prove the interaction design *and* validate the frame shapes.

---

## Visual language

Palette, type, and motion all derive from existing OV Black design tokens so the prototype doesn't feel disconnected from the rest of the product:

- **Paper (#f7f4ee) and ink (#0a0a0a)** are the canvas. Everything sits on paper.
- **Mood accents** (amber, glacial, tidal, onyx, ember, verdant, alpine) color the tape, the activity chips, and the flash pulse — one mood per sample itinerary, chosen to match the destination's feel (Tuscany is amber; Patagonia is glacial; Amalfi is tidal; Tokyo→Kyoto is onyx).
- **Cormorant Garamond** for display (card titles, detail headings). **Inter** for UI (buttons, chips, metadata). The serif does the heavy lifting on "elegant"; the sans does the heavy lifting on "readable."
- **Motion** uses `framer-motion`'s `layout` prop liberally, so reorders animate smoothly without manual choreography. Drag pickups lift the card via shadow-intensity change, not via scale — a scaled card looks cartoonish; a deeper shadow looks like the card floated up a quarter inch.
- **Micro-details that do a lot of work**: inline SVG noise filter at ~6% opacity on every card (otherwise paper looks like flat beige); a `rotate(-3deg)` tape strip that crosses the card's top-left corner; a 1px inset top highlight that sells the "paper layered on paper" feel; uppercase type labels at `0.22em` letter-spacing because the brief is elegant and elegant things have room to breathe.

---

## Interaction design

### Desktop

Drag a card to change its day. `dnd-kit`'s `PointerSensor` has a 6px activation distance so a tap opens the detail sheet instead of triggering a drag — a common source of "why does my click not work?" complaints. The day columns are `useDroppable` rails that light up dashed when any drag is active and solid when you're over one. On drop, `MOVE_NODE` dispatches with the target day's `day_index`.

Edges redraw in real time because the layout is recomputed every render. Memoizing path strings is a trivial future perf win (cache by `fromId::toId::fromXY::toXY`); at the current scale it's not needed.

Click a card → `NodeDetailSheet` slides in from the right with full metadata, activities, and — critically — a nested `TimelineCanvas` for subgraph parents. The Patagonia fixture shows this: clicking the "Torres del Paine W Circuit" card opens a mini timeline of the 4 sub-days.

### Mobile

The viewport toggle in the header flips the main area between desktop canvas and mobile stack. The mobile mode uses the pluck/park/land gesture flow from the brief:

1. Drag a card horizontally past a 110px threshold.
2. On release, the card animates out to the side and "parks" in a floating tray at bottom-right of the viewport, rotated `-2deg`, scaled to 88%.
3. The card's original slot collapses (`layout` handles the reflow automatically).
4. Every day header now has a "Drop here" button. Tap one to land the card in that day.
5. Or tap "Cancel" in the tray to return the card.

This preserves sequence while letting the user navigate a long list to find the right insertion point — which was the whole point of the brief's gesture.

### The AI demo

Three scripted scenarios cover the brief's AI questions:

1. **"Propose cards"** — the assistant streams a reply character-by-character, then drops three ghost cards into the graph at their proposed slots. Each ghost has Accept / Dismiss both on the card in the graph and inline in the chat. Accepting either one dispatches `ACCEPT_PROPOSAL`, the card transitions from ghost (dashed border, sparkle) to solid with a mood-accented flash, and edges update accordingly.
2. **"Assemble draft"** — the assistant creates new `follows` edges between adjacent same-day nodes and across days. The edges animate in via SVG `stroke-dashoffset`, so you see the spine stitch together left-to-right. The chat posts "Draft assembled — N new connections."
3. **"Modify hotel"** — the assistant picks the first hotel in the current itinerary and swaps its title/metadata. The target card flashes its tape accent (via `motion` animation on `boxShadow`) to draw the eye without being jarring. The chat narrates what changed.

Freeform chat input works too — typed messages match against keywords (`propose`, `assemble`, `swap`) and fall back to a help-ish reply. The user can type "swap the hotel" and get the modify scenario. This isn't an LLM — it's a keyword router — but the interaction shape is faithful to what real chat-driven modification will look like.

---

## Trade-offs and alternatives considered

**Why not React Flow?** I considered it seriously because it would have cut implementation time significantly. I rejected it because:
1. Its default aesthetic fights the brief. Re-skinning would take most of the time I'd save.
2. Its pan/zoom gestures conflict with the mobile swipe design.
3. Its node positioning is freeform 2D, but the brief wants timeline semantics. Forcing timeline layout onto a freeform library is fighting the tool.

A pure-CSS implementation was also tempting but would have meant reinventing drag-drop for pointer + touch + keyboard. `dnd-kit` is small, accessible, and battle-tested. Not worth hand-rolling.

**Why a single Card file with inlined per-type faces, not a `CardFace/` folder?** The original plan had separate files. I consolidated because each face is small (10-30 lines), they share the same signature, and splitting them across files actively hurts readability when you're trying to tune the visual language. A prototype benefits from colocation; a production component library might not. If we graduate this to production, splitting is trivial.

**Why absolute positioning for desktop instead of flex?** Absolute positioning made edge-drawing tractable (`EdgeLayer` reads positions directly from the layout result) and made alt-sibling fans easy (`-8px / +44px` offsets from the primary). Flex would have required DOM measurement via refs to get positions for SVG paths, which introduces timing complexity with animations. Absolute was the cleaner fit.

**Why a reducer instead of Zustand?** Zustand would be fine. The existing codebase uses `useReducer` for similar state (see `ChatShell.tsx`), and keeping convention consistent felt worth more than a slightly nicer API. No global state is warranted — the prototype is a single page.

**Why static fixtures instead of generating data at runtime?** The four fixtures are hand-authored because a generator would give you bland, uniform data. The whole point of multiple samples is to *stress-test the design with variety*: Tuscany has a single alt branch; Amalfi has three parallel branches; Patagonia has a nested subgraph; Tokyo→Kyoto has dense same-day stacking plus a `connected_by` edge. Generated data wouldn't exercise the design meaningfully.

---

## What I didn't do (and why)

- **Reorder within a day on desktop.** `dnd-kit`'s `SortableContext` fights absolute positioning, and the cross-day drag is the more valuable interaction. Within-day reorder is solvable with a second gesture (e.g., drag a card over another within the same column) — I didn't ship it because it wasn't required to validate the design.
- **Real SSE wiring.** The mock fires real `SseFrame`-shaped actions. Replacing `mockStream.ts` with a real `useAgentStream` reader is a half-day's work when the time comes. Deferring this was explicitly scoped out.
- **Persistence.** State resets on page reload. This is a design sandbox; the real surface would `PATCH` the API.
- **Accessibility polish.** `dnd-kit` gives us keyboard dragging for free, and buttons are keyboard-accessible. I did not audit contrast, focus rings, or screen-reader descriptions at the level production would require.
- **iOS Safari gesture testing on device.** I implemented the `touch-action` rules the brief needs, but you really have to test swipe mechanics on glass. Desktop touch simulation is close but not enough.
- **Edge perf.** With ~15 nodes per sample, recomputing edge paths every render is fine. At 100+ nodes you'd memoize. I'm not pre-optimizing.

---

## Evaluating against the brief

Mapping the explicit asks to what shipped:

| Brief ask | Status |
|---|---|
| Graph visualization (as timeline) | ✅ Day-column × type-order layout |
| Cards with title / description / metadata (dates, locations, costs) | ✅ Card shell + 8 per-type faces + metadata chips |
| Skeuomorphic feel (shadows, textures, 3D) | ✅ Paper noise, layered shadow, tape accent, inset highlight |
| Interactive (click to expand, drag to rearrange) | ✅ Detail sheet on click; drag to change day |
| Balance graph + conversation real estate | ✅ Split with 360px conversation rail; collapses on mobile |
| Adapt to mobile (linear timeline, swipe) | ✅ Dedicated `MobileTimeline` with pluck/park/land |
| Multiple sample timelines | ✅ Four samples with deliberately varied structure |
| Switch between desktop / mobile views | ✅ `ViewportToggle` |
| AI suggestions (what they look like) | ✅ Ghost cards with dashed border + sparkle, in graph + chat |
| Accept / reject proposals | ✅ Paired buttons in both surfaces, one dispatch path |
| Ask AI to make changes | ✅ Chat input + keyword routing to scripted scenarios |
| Ask AI questions about the itinerary | ⚠️ Freeform text has a fallback reply but no scripted Q&A scenario. Worth adding. |

---

## Open questions worth the next conversation

1. **Does the aesthetic read as "paper" to real users?** I can't evaluate my own skeuomorphism. We need someone outside the team to look at it cold and describe what they see.
2. **Does `alternative_to` fanning actually make sense at a glance?** The `-8/+44` offset feels right on the Amalfi sample with three alts, but with 5+ it would stack ugly. What's the escape hatch — paginate? Open a picker?
3. **How does the conversation panel feel on mobile?** The current design collapses it entirely. Probably wrong — the AI is co-equal with the graph per the brief. A bottom sheet or swipe-up tray might be the right answer.
4. **Is day-as-column right for really long trips?** A 21-day trip is 21 columns, which is a lot of horizontal scroll. Alternatives: paginate by week; collapse days with low content; add a "fold" affordance.
5. **When the AI proposes multiple cards across multiple days, should they land one-at-a-time (as implemented) or all at once?** The staggered feel is nice for demo; it might feel slow when there are 10 proposals.

These are the things I'd want to test next, in roughly that order.
