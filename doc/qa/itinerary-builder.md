# Itinerary Builder — QA Scenarios

Area code: **ITB**. See [README.md](./README.md) for the scenario format, status
legend, and how these map to e2e tests.

The itinerary is a **builder**, not just a viewer, and the same surface serves an
advisor building on a client's behalf and a traveler starting their own. Before a
timeline exists, the builder captures the trip's **first-class brief + timing**:
the free-text goal ("sailing in Greece with my family") and *when* — from exact
dates through a fuzzy-but-bounded window (~a week in summer) to fully flexible,
plus free-text constraints the dates can't hold ("not August", "back by a
Sunday"). From there the concierge (agent) fills the graph out.

> **Data model (0033):** brief `text`; `timing_kind` ∈ {exact, window, flexible};
> `date_start`/`date_end` `date`; `duration_nights` `int`; `timing_note` `text`.
> Read `timing_kind` to interpret the dates: *exact* → the dates are the trip;
> *window* → the dates bound an acceptable window and `duration_nights` is the
> target length inside it; *flexible* → no dates yet, see `timing_note`.

## Coverage at a glance

| Scenario | Title | Status | Automated by (layer) |
| --- | --- | --- | --- |
| [ITB-1](#itb-1--first-run-intake-captures-brief--timing) | First-run intake captures brief + timing | ✅ Automated | intake gate → save → reveal → reload (web) + API contract (pytest) |
| [ITB-1A](#itb-1a--exact-dates) | Exact dates | ✅ Automated | exact-mode intake → persisted range (web) + API |
| [ITB-1B](#itb-1b--fuzzy-window--target-duration) | Fuzzy window + target duration | ✅ Automated | window-mode intake → bounds + duration (web) + API |
| [ITB-1C](#itb-1c--flexible-with-a-constraints-note) | Flexible with a constraints note | ✅ Automated | flexible-mode intake → note, no dates (web) + API |
| [ITB-2](#itb-2--revising-the-brief--timing-later) | Revising the brief + timing later (partial edit) | ✅ Automated | mode-switch clears dates in intake (web) + partial-edit API contract; post-save editor absent |
| [ITB-3](#itb-3--timing-validation) | Timing validation (reversed range, bad duration) | ✅ Automated | reversed range refused in intake (web) + API contract + DB CHECK |
| [ITB-4](#itb-4--empty-itinerary-guides-you-to-the-concierge) | Empty itinerary guides you to the concierge | ✅ Automated | empty-state + **live concierge turn** (web); grounded reply agent-gated |
| [ITB-5](#itb-5--only-the-owner-creator-or-advisor-may-set-the-brief) | Only owner/creator/advisor may set the brief | 🟡 Partial | stranger 404 on a draft = visibility gate (web) + write gate (`test_itinerary_writable.py`); write-403 has no browser surface |
| [ITB-6](#itb-6--timeline-stays-hidden-until-timing-is-concrete) | Timeline stays hidden until timing is concrete | ✅ Automated | vague brief hides the dated timeline (web) |
| [ITB-6A](#itb-6a--exact-dates-may-show-the-timeline) | Exact dates may show the timeline | ✅ Automated | exact dates bring the timeline back (web) |

---

## ITB-1 · First-run intake captures brief + timing

- **Status:** ✅ Automated
- **Personas:** Traveler (self-serve) or Advisor (on a client's behalf) — same surface
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** An itinerary exists with no `brief` yet (freshly created, or the
  lazy "Concierge draft" auto-created on the agent's first card).
- **Automated by:**
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_forwards_brief_and_timing` — create accepts + echoes brief + timing.
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_persists_brief_and_timing` — the fields persist and round-trip through the response serializer.
  - `apps/web/e2e/traveler-flows/intake.spec.ts` → *"ITB-1: first-run intake gates the timeline, saves, and doesn't re-block on reload"* — a fresh traveler starts a trip, the intake **gates** the empty timeline (save disabled until a brief is written), saving **reveals** the builder in place, and on reload the intake no longer blocks (brief persisted first-class; API-seam backstop confirms it).

**Given** an itinerary with an empty `brief`,

**When**
1. the viewer opens `/itinerary/[id]`;
2. the builder presents the first-run intake instead of an empty timeline;
3. the viewer writes the goal ("Sailing in Greece with my family") and picks a
   timing mode;
4. the viewer saves.

**Then**
- the itinerary's `brief` is persisted as first-class data (not buried in the title);
- `timing_kind` is set to the chosen mode and the matching timing fields are stored;
- on reload the intake no longer blocks — the timeline builder is shown with the
  brief surfaced as trip context.

**Notes**
- The three timing modes are [ITB-1A](#itb-1a--exact-dates) / [ITB-1B](#itb-1b--fuzzy-window--target-duration) / [ITB-1C](#itb-1c--flexible-with-a-constraints-note).
- Advisor vs. traveler is the **same** intake — editability of the graph still
  follows role/ownership downstream, but articulating the brief is open to whoever
  owns the itinerary (see [ITB-5](#itb-5--only-the-owner-creator-or-advisor-may-set-the-brief)).

---

## ITB-1A · Exact dates

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** In the first-run intake ([ITB-1](#itb-1--first-run-intake-captures-brief--timing)) or editing timing later.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/intake.spec.ts` → *"ITB-1A: exact dates persist as the trip range"* — picks *Exact dates*, enters start/end, saves; the persisted itinerary (API backstop) has `timing_kind == exact` and the entered range.
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_forwards_fields_and_returns_200`

**Given** the viewer knows the exact trip dates ("March 18–25, 2027"),

**When**
1. they choose the *exact* timing mode;
2. they enter a start and end date.

**Then**
- `timing_kind == exact`;
- `date_start`/`date_end` hold the entered range;
- the stored range is the trip itself (no separate window).

---

## ITB-1B · Fuzzy window + target duration

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** As ITB-1.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/intake.spec.ts` → *"ITB-1B: a rough window keeps bounds plus a target duration"* — picks *A rough window*, sets the bounds + nights, saves; the persisted itinerary (API backstop) has `timing_kind == window`, the window bounds, and `duration_nights`.
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_forwards_brief_and_timing` (window + `duration_nights` round-trip)
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_persists_brief_and_timing`

**Given** the viewer wants "generally summer, about a week" rather than fixed dates,

**When**
1. they choose the *window* timing mode;
2. they set the window bounds (e.g. Jun 1 – Aug 31, 2027);
3. they set a target duration (~7 nights).

**Then**
- `timing_kind == window`;
- `date_start`/`date_end` hold the **window bounds**, not a committed trip;
- `duration_nights` holds the target length inside that window;
- the value is machine-usable — a concrete range can later be resolved from the
  window + duration when the trip firms up.

---

## ITB-1C · Flexible with a constraints note

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** As ITB-1.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/intake.spec.ts` → *"ITB-1C: flexible keeps the constraints note and no dates"* — picks *Flexible* (the date inputs disappear), writes a constraints note, saves; the persisted itinerary (API backstop) has `timing_kind == flexible`, null dates, and the note verbatim.
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_forwards_brief_and_timing` (`timing_note` round-trip)

**Given** the viewer has no dates yet, only constraints,

**When**
1. they choose the *flexible* timing mode;
2. they write a free-text note: "can't go in August; must be back by a Sunday".

**Then**
- `timing_kind == flexible`;
- `date_start`/`date_end` are null;
- `timing_note` holds the constraints verbatim, riding alongside any structured
  fields (the note is allowed in every mode, not just flexible).

---

## ITB-2 · Revising the brief + timing later (partial edit)

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** An itinerary with a brief + timing already set.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/intake.spec.ts` → *"ITB-2: switching to flexible clears the dates"* — the browser slice: picking exact dates then switching to *Flexible* makes the date inputs disappear and persists them as null. (The **post-save** partial edit of a stored itinerary has **no UI yet** — that half stays API-only, below.)
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_details_partial_then_clear` — set brief only leaves timing untouched; commit to exact dates; then clear `date_start` via explicit null while `date_end` + brief stay put.
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_forwards_fields_and_returns_200` — only sent fields are forwarded.
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_explicit_null_clears_date` — an explicit null reaches the service (clears), an omitted field does not.
  - `apps/api/tests/test_itineraries.py::test_update_request_exclude_unset_distinguishes_omitted_from_null` — the Pydantic contract the partial edit depends on.

**Given** an itinerary with an exact-dates trip,

**When**
1. the viewer edits the brief text only;
2. later, the viewer switches to *flexible*, clearing the dates.

**Then**
- editing the brief leaves the timing fields untouched (omitted ≠ cleared);
- switching to flexible clears `date_start`/`date_end` (explicit null clears);
- fields the edit never mentioned keep their stored values.

---

## ITB-3 · Timing validation

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** API seam (pytest) + DB constraint
- **Preconditions:** An itinerary exists.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/intake.spec.ts` → *"ITB-3: a reversed date range is refused in the intake"* — the browser slice: an end-before-start range shows the inline error and keeps **Start building** disabled (no save). The zero/oversized-duration and unknown-field rejections have no intake surface and stay API/DB-only, below.
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_details_rejects_reversed_range` — `date_end < date_start` → `VALIDATION_ERROR` (clean 400, not a 500).
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_rejects_zero_duration` — `duration_nights` must be ≥ 1 (422).
  - `apps/api/tests/test_itineraries.py::test_update_itinerary_rejects_unknown_field` — a misspelled field is a 422, not a silent no-op.
  - DB CHECK `itineraries_date_order_chk` + `itineraries_duration_positive_chk` (migration 0033) as belt-and-suspenders.

**Given** the intake or a later edit,

**When** the viewer submits an end date before the start date, a non-positive
duration, or an unknown field,

**Then**
- a reversed range is refused with a `date_end_before_start` validation error;
- `duration_nights ≤ 0` (or `> 365`) is refused;
- an unrecognized field is refused rather than silently ignored.

---

## ITB-4 · Empty itinerary guides you to the concierge

- **Status:** ✅ Automated (guidance + live turn; grounded reply agent-gated)
- **Personas:** Traveler (self-serve) or Advisor
- **Surface:** Web UI (Playwright) + agent (SSE)
- **Preconditions:** An itinerary with a brief set but **no** graph nodes yet.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/empty-state.spec.ts` → *"ITB-4: an empty timeline guides the traveler to the concierge"* — with a brief saved and no nodes, the builder shows the empty-state ("A blank canvas, ready when you are") pointing at the concierge, not a bare canvas.
  - `apps/web/e2e/traveler-flows/chat.spec.ts` → *"ITB-4: the concierge takes a turn from an empty builder"* — the traveler sends a message from the builder aside and a **live concierge reply** streams back (turn loop asserted structurally: composer re-enables, no "couldn't reach" fallback).
  - `apps/api/tests/test_traveler_context.py::test_assemble_includes_trip_brief_after_client_before_dossier` + the `format_trip_brief` cases — the brief + timing render into the system prompt, ahead of the private tiers.
  - `apps/api/tests/test_agent_internal_router.py::test_get_context_surfaces_trip_brief` — the brief flows through the `GET /agent/context` payload the AgentCore tool reads.
  - The reply being **grounded** in the saved brief (not generic) needs a real tool-using agent — asserted at the API seam above, never on wording in the browser.

**Given** a saved brief but an empty timeline,

**When** the builder renders,

**Then**
- an empty-state explains that the concierge builds the itinerary out, with a clear
  way to start a turn (not a bare empty canvas) — **shipped** ([BuilderEmptyState](../../apps/web/app/_components/itinerary-graph/shared/BuilderEmptyState.tsx));
- the brief + timing are seeded into the concierge's context so its first
  suggestions are grounded in the stated goal and window — **shipped** (in-API prompt
  assembly + `GET /agent/context` payload); asserted structurally at the API seam,
  live grounding Bedrock-gated.

**Notes**
- This is the bridge from [ITB-1](#itb-1--first-run-intake-captures-brief--timing) into the existing concierge turn loop + `card_proposed` graph writes.

---

## ITB-5 · Only the owner, creator, or advisor may set the brief

- **Status:** 🟡 Partial
- **Personas:** Traveler (owner) vs. an unrelated authenticated user
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** An itinerary owned by a specific client.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/write-gate.spec.ts` → *"ITB-5: a stranger cannot open another traveler's draft itinerary"* — the browser-observable half: the owner reaches the intake, while an unrelated traveler opening the same URL gets a **404** (the S08 visibility gate hides the draft's existence), so there's no intake to attempt a write on.
  - `apps/api/tests/test_itinerary_writable.py` — the shared owner/creator/advisor write gate that `PATCH /itinerary/{id}` reuses (owner/creator/advisor admitted, stranger 403).

**Given** an itinerary owned by client A,

**When** a stranger (client B, no relationship) tries to set its brief,

**Then**
- the write is refused with `403 forbidden` — the same relationship gate as node
  writes (`assert_itinerary_writable`);
- the owning traveler, the creator, and any advisor are admitted.

**Notes**
- The brief is deliberately owner-writable so a traveler can articulate the goal on
  a draft they started; graph editability still follows role/ownership downstream.
- **Browser surface is the *visibility* gate, not the write 403.** A stranger can't reach the
  intake at all (the draft `notFound()`s for a non-entitled viewer), so the browser proves
  "a stranger can't open someone else's trip"; the write-side `403` on `PATCH` has no stranger
  screen and stays at the API seam.

---

## ITB-6 · Timeline stays hidden until timing is concrete

- **Status:** ✅ Automated
- **Personas:** Traveler (self-serve) or Advisor
- **Surface:** Web UI (Playwright)
- **Preconditions:** A saved brief with **vague** timing (window or flexible) and an empty board (no nodes/proposals).
- **Automated by:** `apps/web/e2e/traveler-flows/timeline-visibility.spec.ts` → *"ITB-6: a vague brief (no dates yet) hides the dated timeline"*.

**Given** a brief whose timing is a rough window or fully flexible — no committed dates — and nothing on the board yet,

**When** the builder renders,

**Then**
- **no dated timeline is shown** — the day-axis / day-strip scaffold is absent (`itinerary-graph-header[data-timeline-visible="false"]`);
- only the concierge empty-state ("A blank canvas…") stands in, because a dated grid around "today" is meaningless when we don't yet know *when*.

**Notes**
- Root cause the scenario guards against: the timeline adapter synthesizes a "today" day for an itinerary with zero dated nodes, so without this gate the builder drew a fabricated grid. The gate — `nodes.length > 0 || pendingProposals.length > 0 || timing_kind === "exact"` — lives in both the horizontal and mobile views.
- Anything already on the board (a node or a pending proposal) brings the timeline back regardless of timing — there's something to place.

---

## ITB-6A · Exact dates may show the timeline

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** Web UI (Playwright)
- **Preconditions:** A saved brief with **exact** timing (concrete dates).
- **Automated by:** `apps/web/e2e/traveler-flows/timeline-visibility.spec.ts` → *"ITB-6A: exact dates bring the timeline back"*.

**Given** a brief whose timing is *exact* — you know the days,

**When** the builder renders (on the next load, which picks up the persisted timing),

**Then**
- the dated timeline **may** show (`itinerary-graph-header[data-timeline-visible="true"]`) — knowing *when* is enough to lay out the days, even before anything is scheduled.

**Notes**
- The pairing with [ITB-6](#itb-6--timeline-stays-hidden-until-timing-is-concrete): vague timing hides the timeline (a hard rule), exact timing permits it (the "you *could* show me" case).
- The in-place reveal right after saving the intake still holds the pre-save prop (timing was unset when the page first rendered), so the timeline appears on the next SSR/reload — the persisted-state behavior the test asserts.
