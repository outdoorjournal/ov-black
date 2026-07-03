import { type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import { getItineraryAsAdvisor } from "../support/api";

// ITB-1 family — the itinerary builder's first-run intake, driven as a QA person
// would: a fresh traveler starts a trip from basecamp, lands on the intake gate,
// writes the brief, picks a timing mode, and saves into the builder. The browser
// asserts the *experience* (gate blocks → builder reveals); the API seam confirms
// the *state* (the exact brief + timing that was persisted).
//
// Each test provisions its own throwaway traveler + itinerary, so a run never
// pollutes the shared `traveler` persona (a saved itinerary flips its basecamp
// variant). Local-only — freshTraveler provisioning needs the local Supabase.

const HEADING = "Where shall we take you?"; // traveler-audience intake heading
const REVEALED = "A blank canvas, ready when you are"; // builder empty-state

// Fresh traveler → basecamp → "Start a new itinerary" → the intake gate.
// Returns the new itinerary id (parsed from the builder URL).
async function openFreshIntake(page: Page, baseURL: string): Promise<string> {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  await page.getByRole("button", { name: "Start a new itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/, { timeout: 30_000 });
  const id = page.url().split("/itinerary/")[1]!.split(/[?#]/)[0]!;

  // The intake gate stands in front of the (empty) timeline.
  await expect(page.getByRole("heading", { name: HEADING })).toBeVisible();
  return id;
}

function pickMode(page: Page, mode: "exact" | "window" | "flexible") {
  const label =
    mode === "exact"
      ? "Exact dates"
      : mode === "window"
        ? "A rough window"
        : "Flexible";
  return page.getByRole("button", { name: label }).click();
}

// ITB-1 — the intake blocks the timeline until a brief is written; saving
// reveals the builder in place; and on reload the intake no longer blocks (the
// brief is now persisted first-class, so the builder is shown directly).
test("ITB-1: first-run intake gates the timeline, saves, and doesn't re-block on reload", async ({
  page,
  baseURL,
}) => {
  const id = await openFreshIntake(page, baseURL!);
  const brief = "Sailing in Greece with my family";

  // Save is inert until the brief is written — the timeline stays gated.
  await expect(page.getByRole("button", { name: "Start building" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: REVEALED })).toHaveCount(0);

  await page.getByLabel("The trip, in a sentence").fill(brief);
  await pickMode(page, "window");
  await page.getByLabel("No earlier than").fill("2027-06-01");
  await page.getByLabel("No later than").fill("2027-08-31");
  await page.getByLabel("About how many nights").fill("7");

  await page.getByRole("button", { name: "Start building" }).click();

  // The intake gives way to the builder — the empty-state proves we crossed over.
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();
  await expect(page.getByRole("heading", { name: HEADING })).toHaveCount(0);

  // Reload: the brief is persisted, so the gate is gone and the builder renders.
  await page.goto(`/itinerary/${id}`);
  await expect(page.getByRole("heading", { name: HEADING })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();

  // State backstop: the brief landed as first-class data (not buried in a title).
  const it = await getItineraryAsAdvisor(id);
  expect(it.brief).toBe(brief);
});

// ITB-1A — exact dates: the entered range IS the trip.
test("ITB-1A: exact dates persist as the trip range", async ({ page, baseURL }) => {
  const id = await openFreshIntake(page, baseURL!);

  await page.getByLabel("The trip, in a sentence").fill("A week in Kyoto");
  await pickMode(page, "exact");
  await page.getByLabel("Start").fill("2027-03-18");
  await page.getByLabel("End").fill("2027-03-25");
  await page.getByRole("button", { name: "Start building" }).click();
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();

  const it = await getItineraryAsAdvisor(id);
  expect(it.timing_kind).toBe("exact");
  expect(it.date_start).toBe("2027-03-18");
  expect(it.date_end).toBe("2027-03-25");
});

// ITB-1B — fuzzy window: the dates bound a window, duration is the target length
// inside it (both machine-usable, not a committed trip).
test("ITB-1B: a rough window keeps bounds plus a target duration", async ({
  page,
  baseURL,
}) => {
  const id = await openFreshIntake(page, baseURL!);

  await page.getByLabel("The trip, in a sentence").fill("Generally summer, about a week");
  await pickMode(page, "window");
  await page.getByLabel("No earlier than").fill("2027-06-01");
  await page.getByLabel("No later than").fill("2027-08-31");
  await page.getByLabel("About how many nights").fill("7");
  await page.getByRole("button", { name: "Start building" }).click();
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();

  const it = await getItineraryAsAdvisor(id);
  expect(it.timing_kind).toBe("window");
  expect(it.date_start).toBe("2027-06-01");
  expect(it.date_end).toBe("2027-08-31");
  expect(it.duration_nights).toBe(7);
});

// ITB-1C — flexible: no dates yet, only a free-text constraints note that rides
// alongside (the note is allowed in every mode, but this is its home).
test("ITB-1C: flexible keeps the constraints note and no dates", async ({
  page,
  baseURL,
}) => {
  const id = await openFreshIntake(page, baseURL!);
  const note = "can't go in August; must be back by a Sunday";

  await page.getByLabel("The trip, in a sentence").fill("Somewhere warm, eventually");
  await pickMode(page, "flexible");
  // Flexible hides the date inputs entirely.
  await expect(page.getByLabel("Start")).toHaveCount(0);
  await page.getByLabel(/Anything to work around/).fill(note);
  await page.getByRole("button", { name: "Start building" }).click();
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();

  const it = await getItineraryAsAdvisor(id);
  expect(it.timing_kind).toBe("flexible");
  expect(it.date_start ?? null).toBeNull();
  expect(it.date_end ?? null).toBeNull();
  expect(it.timing_note).toBe(note);
});

// ITB-2 (browser slice) — switching modes mid-intake clears what the new mode
// doesn't own: pick exact dates, then switch to flexible, and the dates both
// disappear from the form and are persisted as null. (The post-save partial
// edit of a persisted itinerary has no UI yet — that half stays API-only.)
test("ITB-2: switching to flexible clears the dates", async ({ page, baseURL }) => {
  const id = await openFreshIntake(page, baseURL!);

  await page.getByLabel("The trip, in a sentence").fill("Plans in flux");
  await pickMode(page, "exact");
  await page.getByLabel("Start").fill("2027-03-18");
  await page.getByLabel("End").fill("2027-03-25");

  // Switch to flexible — the date inputs unmount.
  await pickMode(page, "flexible");
  await expect(page.getByLabel("Start")).toHaveCount(0);
  await expect(page.getByLabel("End")).toHaveCount(0);

  await page.getByRole("button", { name: "Start building" }).click();
  await expect(page.getByRole("heading", { name: REVEALED })).toBeVisible();

  const it = await getItineraryAsAdvisor(id);
  expect(it.timing_kind).toBe("flexible");
  expect(it.date_start ?? null).toBeNull();
  expect(it.date_end ?? null).toBeNull();
});

// ITB-3 (browser slice) — a reversed range is caught in the intake before it can
// be saved: the inline error shows and the save button stays disabled. (The
// zero/oversized-duration and unknown-field rejections have no intake surface —
// they stay API/DB-CHECK-only.)
test("ITB-3: a reversed date range is refused in the intake", async ({
  page,
  baseURL,
}) => {
  await openFreshIntake(page, baseURL!);

  await page.getByLabel("The trip, in a sentence").fill("Backwards in time");
  await pickMode(page, "exact");
  await page.getByLabel("Start").fill("2027-03-25");
  await page.getByLabel("End").fill("2027-03-18");

  await expect(page.getByText(/The end can.t be before the start/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Start building" })).toBeDisabled();
});
