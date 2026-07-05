import { type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import {
  discardNodeAsAdvisor,
  getCollectionAsAdvisor,
  seedCollectionItemAsAdvisor,
} from "../support/api";

// COL family — the Collection (wish list): the pile of unscheduled "maybes" a
// traveler accumulates before a timeline exists. Driven as a QA person would —
// a fresh traveler starts a trip, lands in the builder, and works the Collection
// rail. The browser asserts the *experience* (the wish list renders, regroups,
// accepts adds); the API seam confirms the *state* (what actually persisted).
//
// The browser can only add the FIRST item via the concierge (agent-gated), so
// each spec seeds a starter item at the API seam (advisor — entitled to write
// any itinerary), then drives the rail's own affordances in the browser. Cards
// render in BOTH the desktop and mobile layouts (one hidden by responsive CSS),
// so every locator is scoped to `:visible`. Local-only (freshTraveler needs the
// local Supabase). See doc/qa/collection.md.

const HEADING = "Where shall we take you?"; // traveler-audience intake heading
const REVEALED = "A blank canvas, ready when you are"; // builder empty-state

// Fresh traveler → basecamp → new itinerary → intake → builder. `flexible`
// keeps the timeline off, so the Collection is the dominant surface once items
// exist. Returns the new itinerary id.
async function startFlexibleTrip(page: Page, baseURL: string, brief: string): Promise<string> {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  await page.getByRole("button", { name: "Start a new itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/, { timeout: 30_000 });
  const id = page.url().split("/itinerary/")[1]!.split(/[?#]/)[0]!;

  await expect(page.getByRole("heading", { name: HEADING })).toBeVisible();
  await page.getByLabel("The trip, in a sentence").fill(brief);
  await page.getByRole("button", { name: "Flexible" }).click();
  await page.getByRole("button", { name: "Start building" }).click();
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();
  return id;
}

const visibleCards = (page: Page) =>
  page.locator('[data-testid="collection-card"]:visible');

// COL-1 — with a brief but nothing scheduled, the Collection is the dominant
// surface, and it lists exactly the unscheduled, non-discarded nodes.
test("COL-1: the Collection is the dominant pre-timeline surface", async ({
  page,
  baseURL,
}) => {
  const id = await startFlexibleTrip(page, baseURL!, "A slow week somewhere green");
  await seedCollectionItemAsAdvisor(id, { type: "meal", title: "Kaiseki dinner" });
  await seedCollectionItemAsAdvisor(id, { type: "experience", title: "Sunrise hike" });
  const gone = await seedCollectionItemAsAdvisor(id, {
    type: "hotel",
    title: "Overbooked ryokan",
  });
  await discardNodeAsAdvisor(id, gone);

  // The store hydrates from the server, so pick up the seeded nodes on reload.
  await page.reload();

  await expect(
    page.locator('[data-testid="collection-rail"][data-variant="board"]:visible'),
  ).toBeVisible();
  await expect(visibleCards(page)).toHaveCount(2);
  await expect(visibleCards(page).filter({ hasText: "Kaiseki dinner" })).toHaveCount(1);
  await expect(visibleCards(page).filter({ hasText: "Sunrise hike" })).toHaveCount(1);
  // The discarded item is excluded from the wish list.
  await expect(visibleCards(page).filter({ hasText: "Overbooked ryokan" })).toHaveCount(0);
});

// COL-2 — switching the group-by axis re-lanes the SAME cards; nothing is lost.
test("COL-2: switching the grouping axis re-lanes the same items", async ({
  page,
  baseURL,
}) => {
  const id = await startFlexibleTrip(page, baseURL!, "Eat and wander");
  await seedCollectionItemAsAdvisor(id, { type: "meal", title: "Omakase counter" });
  await seedCollectionItemAsAdvisor(id, { type: "experience", title: "Pottery studio" });
  await page.reload();

  // By type: a meal lane and a do lane.
  await expect(
    page.locator('[data-testid="collection-lane"][data-lane="eat"]:visible'),
  ).toBeVisible();
  await expect(
    page.locator('[data-testid="collection-lane"][data-lane="do"]:visible'),
  ).toBeVisible();

  // By cost: neither carries a price, so they collapse into one "No price" lane —
  // but both cards are still present.
  await page.locator('[data-testid="collection-groupby-cost"]:visible').click();
  await expect(
    page.locator('[data-testid="collection-lane"][data-lane="cnone"]:visible'),
  ).toBeVisible();
  await expect(page.locator('[data-testid="collection-lane"]:visible')).toHaveCount(1);
  await expect(visibleCards(page)).toHaveCount(2);
});

// COL-3 — the traveler jots a note straight into the wish list; it persists as a
// timeless note (no time, no host) and never touches a timeline.
test("COL-3: a traveler jots a note into the wish list", async ({ page, baseURL }) => {
  const id = await startFlexibleTrip(page, baseURL!, "Notes to self");
  await seedCollectionItemAsAdvisor(id, { type: "experience", title: "Starter idea" });
  await page.reload();

  const note = "wants a sushi counter, not a table";
  const field = page.locator('[data-testid="collection-add-note"]:visible');
  await field.fill(note);
  await field.press("Enter");

  await expect(visibleCards(page).filter({ hasText: "sushi counter" })).toHaveCount(1);

  // State backstop: a timeless note landed in the Collection (unscheduled).
  await expect
    .poll(async () => (await getCollectionAsAdvisor(id)).map((n) => n.title))
    .toContain(note);
  const saved = (await getCollectionAsAdvisor(id)).find((n) => n.title === note);
  expect(saved?.type).toBe("note");
  expect(saved?.starts_at ?? null).toBeNull();
});

// COL-4 — the traveler pastes a link; it persists as an unscheduled `web` node.
// OpenGraph enrichment is best-effort, so we assert the provenance, not wording.
test("COL-4: a traveler saves a pasted link", async ({ page, baseURL }) => {
  const id = await startFlexibleTrip(page, baseURL!, "Reading list");
  await seedCollectionItemAsAdvisor(id, { type: "experience", title: "Starter idea" });
  await page.reload();

  const field = page.locator('[data-testid="collection-add-link"]:visible');
  await field.fill("https://example.com/kaiseki-guide");
  await field.press("Enter");

  // The link fetch is a server round-trip (≤5s), so wait on the API seam.
  await expect
    .poll(async () => (await getCollectionAsAdvisor(id)).some((n) => n.source === "web"), {
      timeout: 15_000,
    })
    .toBe(true);
  const web = (await getCollectionAsAdvisor(id)).find((n) => n.source === "web");
  expect(web?.source_id).toContain("example.com");
  expect(web?.starts_at ?? null).toBeNull();

  // And a second card lands on the board (starter + the saved link). This rides
  // the browser's OWN from-link round-trip — the backend's OpenGraph fetch can
  // take up to its 5s timeout — so give it room beyond the default 5s window.
  await expect(visibleCards(page)).toHaveCount(2, { timeout: 15_000 });
});

// COL-5 — dragging a collection card onto a day gives it a real time and lays
// it out on the timeline. Once placed it drops out of the wish list by default
// (revealed again behind the "Scheduled" toggle); dragging it back off the
// timeline clears the time and returns it to the wish list.
//
// Marked fixme: the schedule/un-schedule DATA outcome is fully covered at the
// unit/integration layer —
//   apps/api/tests/test_notes.py::test_metadata_patch_schedules_then_unschedules_non_note
//   apps/api/tests/test_notes.py::test_unschedule_note_returns_to_collection
//   apps/web/tests/itineraryGraph/collectionRail.test.tsx (placed node hidden by default)
// — but the BROWSER drag rides dnd-kit's PointerSensor, which isn't reliably
// automatable through Playwright's synthetic pointer here (the day droppable is
// absolutely-positioned with pointer-events gated on an in-flight drag). Kept as
// a documented gap rather than a flaky green (see doc/qa/collection.md · COL-5).
test.fixme(
  "COL-5: dragging a collection card onto a day schedules it",
  async () => {
    // Intentionally unimplemented — see the note above.
  },
);
