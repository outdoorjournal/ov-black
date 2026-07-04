# Collection (Wish List) — QA Scenarios

Area code: **COL**. See [README.md](./README.md) for the scenario format, status
legend, and how these map to e2e tests.

Before a trip has a scheduled timeline, the traveler and concierge accumulate a
pile of **maybes** — places to eat, places to stay, things to do, ways to fly
in, and stray notes. In the graph a wish-list item is simply an **unscheduled
node** (no `starts_at`); the Collection is the view over exactly those nodes,
and it's the *dominant* surface until something is placed on a timeline.
Scheduling an item = giving it a time (drag it onto a day); un-scheduling clears
the time and returns it to the wish list.

> **Data model:** the Collection is the mood board — **every non-discarded
> node** shows in it. *Placing* an item on the timeline (giving it a real
> `start_time`) does **not** remove it from the Collection; the timeline is an
> additional surface, not a move out. Only `status = discarded` drops a node
> from the wish list. The backend `GET /itinerary/{id}/collection` returns the
> **unscheduled** subset (`starts_at` NULL, non-discarded) — the agent's pool of
> "still-unplaced maybes" and the test backstop for "did this save persist
> unscheduled". Saving is type-agnostic: an inventory item (`from-inventory`), a
> pasted web link (`from-link`, `source="web"`), or a timeless note
> (`type=note`, no anchor — legal since migration `0035`). Grouping (Type / Cost
> / Proximity) is derived client-side from existing node fields; it never
> mutates the graph.

> **Seeding note (harness):** the browser can only add the *first* item through
> the concierge (agent-gated, non-deterministic). So a self-serve spec seeds one
> starter item at the API seam (advisor, entitled to write any itinerary) to
> bring the rail up, then drives the rail's own add / group / schedule
> affordances in the browser — "seed the state, drive the experience".

## Coverage at a glance

| Scenario | Title | Status | Automated by (layer) |
| --- | --- | --- | --- |
| [COL-1](#col-1--the-collection-is-the-pre-timeline-home) | The Collection is the pre-timeline home | ✅ Automated | dominant board renders unscheduled, non-discarded nodes (web) + `GET /collection` contract (pytest) |
| [COL-2](#col-2--grouping-axis-re-lanes-the-same-items) | Grouping axis re-lanes the same items | ✅ Automated | Type→Cost→Proximity re-lanes, no card lost (web) + `groupCollection` unit (vitest) |
| [COL-3](#col-3--traveler-jots-a-note-into-the-wish-list) | Traveler jots a note into the wish list | ✅ Automated | in-browser note add → card + timeless note persisted (web + API seam) |
| [COL-4](#col-4--traveler-saves-a-pasted-link) | Traveler saves a pasted link | ✅ Automated | in-browser link add → card + `source="web"` unscheduled node (web + API seam) |
| [COL-5](#col-5--schedule-a-collection-item-keeping-it-in-the-collection) | Schedule a collection item (keeping it in the Collection) | 🟡 Partial | schedule/un-schedule sets/clears `start_time` via `move_node`/`update_node` (pytest + vitest); item stays in the wish list; browser drag flagged in Notes |

---

## COL-1 · The Collection is the pre-timeline home

- **Status:** ✅ Automated
- **Personas:** Traveler (self-serve) or Advisor — same surface
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** An itinerary with a brief, nothing scheduled, and ≥1 unscheduled item.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/collection.spec.ts` → *"COL-1: the Collection is the dominant pre-timeline surface"*.
  - `apps/api/tests/test_collection.py::test_collection_returns_only_unscheduled_non_discarded` — the `GET /collection` filter (unscheduled, non-discarded).

**Given** a brief-set itinerary with unscheduled items and nothing on a timeline,

**When** the builder renders,

**Then**
- the Collection is the **dominant** surface, not an empty dated grid (`collection-rail[data-variant="board"]`);
- every non-discarded node shows as a card;
- a discarded node does **not** appear in the Collection.

**Notes**
- Once something is scheduled the Collection condenses to a side rail beside the timeline, but placed items **stay** in it — see [COL-5](#col-5--schedule-a-collection-item-keeping-it-in-the-collection).

---

## COL-2 · Grouping axis re-lanes the same items

- **Status:** ✅ Automated
- **Personas:** Traveler or Advisor
- **Surface:** Web UI (Playwright) + unit (vitest)
- **Preconditions:** A Collection holding items of more than one type.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/collection.spec.ts` → *"COL-2: switching the grouping axis re-lanes the same items"*.
  - `apps/web/tests/itineraryGraph/collectionGrouping.test.ts` — the pure `groupCollection` axes (type folds to traveler lanes; cost tiers with "No price" last; proximity clusters with "No location" last).

**Given** a Collection with a meal and an experience saved,

**When** the viewer switches the group-by axis from *Type* to *Cost* to *Proximity*,

**Then**
- by **type**, the cards sit under named lanes (e.g. *Places to eat*, *Things to do*);
- by **cost**, price-less items collapse into a single *No price* lane;
- the same cards are present under every axis — regrouping never drops an item.

---

## COL-3 · Traveler jots a note into the wish list

- **Status:** ✅ Automated
- **Personas:** Traveler (self-serve)
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** The Collection rail is visible (≥1 item already saved).
- **Automated by:**
  - `apps/web/e2e/traveler-flows/collection.spec.ts` → *"COL-3: a traveler jots a note into the wish list"*.
  - `apps/api/tests/test_notes.py::test_note_without_any_anchor_is_collection_note` — a timeless, unattached note is legal (migration `0035`).

**Given** the Collection rail is showing,

**When** the traveler types a note into the rail's note field and presses Enter,

**Then**
- a new card appears in the Collection;
- the note persists as a **timeless** note node — `type=note`, no `start_time`, no host anchor (API seam confirms it's in `GET /collection`);
- it never lands on a timeline.

---

## COL-4 · Traveler saves a pasted link

- **Status:** ✅ Automated
- **Personas:** Traveler (self-serve)
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** The Collection rail is visible.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/collection.spec.ts` → *"COL-4: a traveler saves a pasted link"*.
  - `apps/api/tests/test_collection.py::test_from_link_creates_unscheduled_web_note` — the `from-link` write shape (`source="web"`, unscheduled).
  - `apps/api/tests/test_link_preview.py` — the OpenGraph fetch + graceful fallback.

**Given** the Collection rail is showing,

**When** the traveler pastes a URL into the rail's link field and presses Enter,

**Then**
- a new card appears in the Collection;
- the node persists with `source="web"`, `source_id` = the URL, and no `start_time` (API seam);
- the card's richness (OpenGraph title/image) is **best-effort** — a failed or slow fetch degrades to the URL — so it's asserted structurally (`source="web"`), never on fetched wording.

---

## COL-5 · Schedule a collection item (keeping it in the Collection)

- **Status:** 🟡 Partial
- **Personas:** Traveler (own version) or Advisor (with the edit lock)
- **Surface:** Web UI (Playwright, drag) + API seam / unit
- **Preconditions:** The Collection rail holds a card with no real time yet.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/collection.spec.ts` → *"COL-5: dragging a collection card onto a day schedules it"* — the browser drag, when the harness can drive dnd-kit reliably.
  - `apps/api/tests/test_notes.py::test_metadata_patch_schedules_then_unschedules_non_note` — the schedule (start_time → `starts_at` column) then un-schedule (cleared) round-trip.
  - `apps/api/tests/test_notes.py::test_unschedule_note_returns_to_collection` — a timed note dragged back becomes a timeless node again.
  - `apps/web/tests/itineraryGraph/collectionRail.test.tsx` → *"keeps placed nodes and drops only discarded ones"* — a scheduled node stays in the rail.

**Given** a Collection card that isn't placed on a day yet,

**When** the viewer drags the card onto a day column,

**Then**
- the item gains a real `start_time` and now **also** lays out on that day's timeline;
- it **stays** in the Collection — placing is an additional surface, not a move out (only discarding removes it);
- the `starts_at` column is set to match;
- dragging the placed card back off the timeline **clears** its `start_time` (it leaves the timeline) while remaining in the Collection.

**Notes**
- This reflects the product rule that **a placed item is not removed from the Collection** — the wish list is the whole mood board, and scheduling just adds a timeline placement. `collectionItemsOf` therefore excludes only discarded nodes; `scheduledCount` (which still distinguishes a *real* placement from the adapter's synthesized auto-layout) drives whether the board is dominant or condenses to a side rail.
- The scheduling *mechanic* is the existing `move_node` metadata patch (the same one the timeline uses) plus the `update_node` fix that clears the `starts_at` column on un-schedule — both covered at the unit/integration layer above. The **browser drag** rides dnd-kit's `PointerSensor`; it isn't reliably automatable under Playwright here, so this stays 🟡 with the drag skipped and the data outcome resting on the pytest/vitest coverage (an honest skip, not a false green).
