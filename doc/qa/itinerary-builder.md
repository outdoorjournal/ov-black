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
| [ITB-1](#itb-1--first-run-intake-captures-brief--timing) | First-run intake captures brief + timing | 🟡 Partial | API contract (pytest); builder first-run UI planned (web) |
| [ITB-1A](#itb-1a--exact-dates) | Exact dates | 🟡 Partial | API contract (pytest); intake date-mode UI planned |
| [ITB-1B](#itb-1b--fuzzy-window--target-duration) | Fuzzy window + target duration | 🟡 Partial | API contract (pytest); intake window-mode UI planned |
| [ITB-1C](#itb-1c--flexible-with-a-constraints-note) | Flexible with a constraints note | 🟡 Partial | API contract (pytest); intake flexible-mode UI planned |
| [ITB-2](#itb-2--revising-the-brief--timing-later) | Revising the brief + timing later (partial edit) | ✅ Automated | API contract (pytest) — partial semantics + clear-via-null |
| [ITB-3](#itb-3--timing-validation) | Timing validation (reversed range, bad duration) | ✅ Automated | API contract (pytest) + DB CHECK |
| [ITB-4](#itb-4--empty-itinerary-guides-you-to-the-concierge) | Empty itinerary guides you to the concierge | 🟡 Partial | Empty-state UI (web, planned) + concierge brief-seed (`test_traveler_context.py` / `test_agent_internal_router.py`); live grounding Bedrock-gated |
| [ITB-5](#itb-5--only-the-owner-creator-or-advisor-may-set-the-brief) | Only owner/creator/advisor may set the brief | 🟡 Partial | `test_itinerary_writable.py` covers the write gate; brief route parity planned |

---

## ITB-1 · First-run intake captures brief + timing

- **Status:** 🟡 Partial
- **Personas:** Traveler (self-serve) or Advisor (on a client's behalf) — same surface
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** An itinerary exists with no `brief` yet (freshly created, or the
  lazy "Concierge draft" auto-created on the agent's first card).
- **Automated by:**
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_forwards_brief_and_timing` — create accepts + echoes brief + timing.
  - `apps/api/tests/test_itineraries.py::test_create_itinerary_persists_brief_and_timing` — the fields persist and round-trip through the response serializer.
  - Builder first-run **UI** (intake shown when `brief` is empty, timeline revealed after save) — _planned (web)_.

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

- **Status:** 🟡 Partial
- **Personas:** Traveler or Advisor
- **Surface:** API seam (pytest) + Web UI (Playwright, planned)
- **Preconditions:** In the first-run intake ([ITB-1](#itb-1--first-run-intake-captures-brief--timing)) or editing timing later.
- **Automated by:** `apps/api/tests/test_itineraries.py::test_update_itinerary_forwards_fields_and_returns_200`

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

- **Status:** 🟡 Partial
- **Personas:** Traveler or Advisor
- **Surface:** API seam (pytest) + Web UI (Playwright, planned)
- **Preconditions:** As ITB-1.
- **Automated by:**
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

- **Status:** 🟡 Partial
- **Personas:** Traveler or Advisor
- **Surface:** API seam (pytest) + Web UI (Playwright, planned)
- **Preconditions:** As ITB-1.
- **Automated by:** `apps/api/tests/test_itineraries.py::test_create_itinerary_forwards_brief_and_timing` (`timing_note` round-trip)

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
- **Surface:** API seam (pytest)
- **Preconditions:** An itinerary with a brief + timing already set.
- **Automated by:**
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

- **Status:** 🟡 Partial
- **Personas:** Traveler (self-serve) or Advisor
- **Surface:** Web UI (Playwright) + agent (SSE)
- **Preconditions:** An itinerary with a brief set but **no** graph nodes yet.
- **Automated by:**
  - `apps/api/tests/test_traveler_context.py::test_assemble_includes_trip_brief_after_client_before_dossier` + the `format_trip_brief` cases — the brief + timing render into the system prompt, ahead of the private tiers.
  - `apps/api/tests/test_agent_internal_router.py::test_get_context_surfaces_trip_brief` — the brief flows through the `GET /agent/context` payload the AgentCore tool reads.
  - Builder empty-state **UI** (guidance over an empty canvas) — _planned (web)_.
  - "Grounded first reply" self-skips against the mock; only exercised against Bedrock (F3 UAT).

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
- **Surface:** API seam (pytest)
- **Preconditions:** An itinerary owned by a specific client.
- **Automated by:** `apps/api/tests/test_itinerary_writable.py` covers the shared
  owner/creator/advisor write gate that `PATCH /itinerary/{id}` reuses; a brief-route
  parity test (owner 200 vs. stranger 403) is _planned_.

**Given** an itinerary owned by client A,

**When** a stranger (client B, no relationship) tries to set its brief,

**Then**
- the write is refused with `403 forbidden` — the same relationship gate as node
  writes (`assert_itinerary_writable`);
- the owning traveler, the creator, and any advisor are admitted.

**Notes**
- The brief is deliberately owner-writable so a traveler can articulate the goal on
  a draft they started; graph editability still follows role/ownership downstream.
