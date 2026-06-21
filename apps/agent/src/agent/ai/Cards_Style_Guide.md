# Cards — Style Guide

How to compose, populate, and escalate itinerary cards. Pairs with:

- Visual reference: [`apps/web/app/prototype/cards/page.tsx`](../../../../../apps/web/app/prototype/cards/page.tsx) — every type in glance and zoom, status escalation, accessibility notes.
- Tokens (colors, icons, status): [`apps/web/app/prototype/cards/_lib/tokens.ts`](../../../../../apps/web/app/prototype/cards/_lib/tokens.ts)
- Conceptual root: [`Itinerary_Planning_System.md`](./Itinerary_Planning_System.md) — the original travel-graph notebook.
- Graph schema: [`supabase/migrations/0002_itinerary_graph.sql`](../../../../../supabase/migrations/0002_itinerary_graph.sql)

If the visual rules in this doc disagree with the prototype, the prototype is canonical — update this doc.

---

## Principles

1. **A card is glanceable.** Phone-sized. Body 11px+, captions only with letterspacing for legibility. Touch target = whole card body, ≥ 44px.
2. **Zoom is for commitment.** Glance answers "what is this?"; zoom answers "what do I need to know to walk into it?". Reserve heavy detail for the zoom view.
3. **Color + cue, never color alone.** Type, status, energy, allergens — every color signal is paired with an icon, label, glyph, or texture so the system reads identically to color-blind users.
4. **Status weight is real.** A Confirmed card visibly weighs more than a Booked one — heavier paper, deeper shadow, ink-on-paper footer band. The escalation tells the traveler "this is hard to move now."
5. **Every type earns its keep.** Each card type has a *signature detail* — the one thing it exists to deliver that a generic card doesn't. If you can't surface the signature detail, the card type is wrong for this moment.
6. **Don't render absent fields with em-dashes.** If the gate isn't assigned yet, the gate row doesn't appear. Empty rows look like missing data, not pending data.

---

## Per type

For each type: when to use it, required fields, optional fields, fields to *omit when absent*, and the signature detail. Field shapes follow `NodeMeta` in the prototype's `_lib/types.ts`.

### `destination`

- **When:** regional anchor used as `parent_subgraph_id` for everything in that place. Usually rendered as a header strip, not a timeline leaf card.
- **Required:** title (region), location (lat/lng or geocoded), date window
- **Optional:** regional map, language hint, climate, signature image
- **Signature:** regional map with contained nodes pinned.

### `flight`

- **When:** any commercial or chartered air leg. Multi-leg → one card per segment under a subgraph parent (see Composition).
- **Required:** `iata_from`, `iata_to`, `depart_at` (with TZ), `arrive_at` (with TZ), `flight_code` (or "Charter")
- **Optional:** cabin, seat, terminal, gate, lounge near gate, scenic side, jet-lag protocol, time-zone delta
- **Omit when absent:** gate (don't show "—" — wait until assigned), seat (until ticketed)
- **Signature:** explicit time-zone delta (e.g. `+13h`) + lounge proximity to the gate, not just "access yes/no".

### `subway`

- **When:** one metro leg where line color and station signage matter — i.e., a foreign-language transit system the traveler will navigate themselves.
- **Required:** from station, to station, line(s), duration, fare/pass note
- **Optional:** stop count, transfer dots colored by connecting line, step-free note, signage gloss block
- **Omit when absent:** signage gloss when traveler's primary language matches the local language.
- **Signature:** the line drawn in its **official agency color**, transfer dots in each connecting line's official color, and platform signage shown in native script + romanization + traveler-language gloss.

### `train`

- **When:** intercity, Shinkansen, scenic rail. One card per train, even with intermediate stops.
- **Required:** from, to, train name/number, depart, arrive, platform · car · seat
- **Optional:** stop sequence with arr/dep times, scenery callouts (specific minute, specific side), pass eligibility, food-on-board notes
- **Omit when absent:** stop sequence at glance level — zoom only.
- **Signature:** window briefing — scenery flagged at a specific minute on a specific side ("Mt. Fuji, north window, from 12:55").

### `drive`

- **When:** private transfer or chartered car between fixed points.
- **Required:** from, to, ETA, vehicle (make + capacity), driver name
- **Optional:** driver photo, languages spoken, plate (in local format with native script when applicable), bag capacity, route preview, contact link, prior-trip continuity note
- **Omit when absent:** driver photo if not on file — use initials placeholder, never stock silhouettes.
- **Signature:** driver continuity. If the same driver has served the traveler before, surface it.

### `walk`

- **When:** the traveler walks ≥ 300m between two graph nodes. Below 300m, fold into the upstream node's zoom — not its own card.
- **Required:** from, to, distance, time
- **Optional:** surface notes (cobblestones, stairs, no shade), POIs along the way, route polyline
- **Omit when absent:** route polyline when distance < 500m — over-instrumented for short walks.
- **Signature:** surface warning. "Cobblestone last 100m" is a small call-out that prevents a real bad moment.

### `boat`

- **When:** ferry, water taxi, charter on water.
- **Required:** dock from, dock to, departure window, duration
- **Optional:** motion-sickness rating, bring-with reminders (sunscreen, layers), schedule frequency
- **Signature:** motion-sickness rating, with antidote suggestion if rated > moderate.

### `hotel`

- **When:** any sleeping accommodation — hotel, ryokan, private villa, yacht. One card per consecutive stay, not per night.
- **Required:** name, location, check-in window, check-out window, room type, nights
- **Optional:** hero image, neighborhood blurb, walking distances to upcoming itinerary nodes from your door, profile prefs honored, confirmation #, in-room amenities
- **Omit when absent:** nights count if 1 (just show dates).
- **Signature:** "from your door" walking distances to the next 3 itinerary nodes — connects the hotel to the day around it.

### `experience`

- **When:** any guided or structured activity, tour, or curated moment.
- **Required:** title, location, duration, category
- **Optional:** hero image, narrative paragraph, energy meter, difficulty, best-window strip, gear list, weather contingency, allergen list, age limits, language support
- **Omit when absent:** weather contingency for 100% indoor experiences.
- **Signature:** energy meter + 24-hour best-window strip together.

### `meal`

- **When:** a fixed-time food node — reservation, scheduled tasting, provisioned picnic. NOT casual eating during free time.
- **Required:** title, location, seating time, duration, cuisine class
- **Optional:** dish image, dress code, dietary flags from profile, etiquette tiles, pre-meal phrases (foreign-language country only), reservation #, cancellation policy
- **Omit when absent:** phrases card when traveler's language matches local.
- **Signature:** pre-meal phrases. Travelers screenshot this card on the way to dinner.

### `free_time`

- **When:** an open block ≥ 90 min the agent could optionally fill. Below 90 min → roll into adjacent waiting or the upstream node.
- **Required:** title, time window, location
- **Optional:** weather, sunset/sunrise, energy advice (rest vs. explore — derived from prior-day fatigue), suggestion grid
- **Omit when absent:** suggestion grid if the traveler has opted into "no fills" for this trip.
- **Signature:** energy advice tied to actual prior-day load + sunset awareness.

### `waiting`

- **When:** forced buffer between two fixed nodes — pre-flight, layover, lobby wait. Distinct from `free_time`: not optional, and the next node is fixed.
- **Required:** location, duration, "what's next" pointer
- **Optional:** lounge info, "use this time to" list, restroom and quiet zones, soft progress bar
- **Omit when absent:** progress bar when duration < 30 min.
- **Signature:** "use this time to" — concrete actionable list, not generic time-killers.

### `note`

- **When:** any author-attached annotation. Advisor → trip, agent → card, traveler → card.
- **Required:** body, author (name + role), timestamp, attached-to (which node or trip)
- **Optional:** tags, replies thread, visibility (private / team / shared with traveler)
- **Omit when absent:** avatars — name + role only.
- **Signature:** yellow paper substrate. Signals "a human wrote this," not "the system inferred this." Default visibility: team-internal. Travelers see notes only when explicitly shared.

---

## Status transitions

| Status | Who creates | Who advances | Reversible by |
| --- | --- | --- | --- |
| `idea` | agent (inferred from convo) | agent, advisor, traveler | anyone |
| `proposed` | agent or advisor | traveler (approve / discard) | anyone |
| `approved` | traveler | advisor (book) | traveler → proposed |
| `booked` | advisor or operator | system (on payment + confirmation) | advisor only |
| `confirmed` | system (event-driven) | — | only via cancellation flow, not from this surface |
| `discarded` | anyone | — | restorable to prior status |

Rules:

- Once a card is `booked`, it shows a **serial** in the footer band.
- Once a card is `confirmed`, the **substrate changes** (heavier paper, thicker border, deeper shadow) AND the footer band inverts to ink-on-paper with the serial + confirmation date. The visual escalation is the traveler's signal that moving this card now costs real money.
- The agent must not silently re-propose an `approved` or higher card. If a constraint forces a change, demote with a visible note.
- `discarded` cards remain on the graph for audit and restore — they don't vanish.

---

## Composition

- **A card is the leaf-level unit.** A subgraph is a parent that holds related leaves (`parent_subgraph_id`).
- **Multi-leg flight:** one `flight` card per segment, all under a subgraph parent with a single travel-spine title (`DTW → HND → ITM`). Layovers ≥ 90 min get a `waiting` card; layovers < 90 min are absorbed into the next leg's pre-flight detail.
- **Multi-day experience** (e.g., a 3-day trek): default to **one** experience card with `duration_days = 3` and per-day chips. Promote to a subgraph of three connected cards only if the days diverge meaningfully (different lodging, different guide, different difficulty).
- **Alternatives:** use the `alternative_to` edge type. Only one branch is active at a time; others render dimmed and greyed in the timeline.
- **Optional / parallel sub-step** (the doc's bento example — branch off, rejoin): subgraph branch that rejoins the main path. Don't render as a separate card on glance; reveal it inside the parent card's zoom.

---

## Localization & signage gloss

- Always reproduce signage **as the traveler will see it** in the local script (出口, 銀座, etc.), then gloss.
- Three-line stack — native script primary, romanization, traveler-language gloss — applies only when foreign script differs from traveler's language. If they match, single line in the traveler's language.
- Currency: native symbol + amount; add traveler-currency conversion when amount exceeds ~$50 equivalent, or always show conversion in zoom.
- Subway and train line names use the **agency's official color** (e.g., Tokyo Metro Ginza Line = #f39700) — preserves wayfinding intuition the traveler builds in-country.

---

## Image policy

- **Required** for `experience`, `hotel`, `meal` zoom views. Optional for glance. Required for `flight` only when premium cabin is the value prop.
- **Fallback:** type-tinted gradient with a small "photo" mark in a corner. **Never** use stock-photo silhouettes or "image not available" text.
- **Source:** operator-provided or licensed. No web-scraped images.
- **Aspect ratio:** 16:9 for hero, 1:1 for thumbnail.

---

## Visual rules — pointers, not duplication

These live in code so they can be enforced at runtime. The MD points; it does not redescribe.

- **Status treatment:** hybrid substrate + manifest band. Canonical implementation in [`StatusAlternatives.tsx`](../../../../../apps/web/app/prototype/cards/_components/StatusAlternatives.tsx) — see `HybridCard` and `HYBRID_CFG`. Substrate escalates paper weight; footer band carries serial + date and removes the corner-overlap problem.
- **Type tokens:** [`tokens.ts`](../../../../../apps/web/app/prototype/cards/_lib/tokens.ts) — accent and tint colors, icon component, three-letter mnemonic. Accents are tested ≥ 4.5:1 for text and ≥ 3:1 for non-text indicators on `#f7f4ee` paper.
- **Body / caption sizes:** body ≥ 11px (glance) / 12px (zoom). Captions 10px allowed only with ≥ 0.18em letterspacing.
- **Touch targets:** ≥ 44×44px. The card body is the primary tap.
- **Motion:** hover lift and status flash respect `prefers-reduced-motion`.

---

## How to change this guide

- **Visual rules** (color, shadow, status escalation, layout) — change the prototype first, then update the relevant pointer here.
- **Per-type rules** (which fields appear, signature detail, when to use the type) — update this MD first; then the prototype is the new reference.
- **Status transitions** — propose the change in [doc/decisions.md](../../../../../doc/decisions.md) before updating this MD; transitions touch the API + agent + UI together.
