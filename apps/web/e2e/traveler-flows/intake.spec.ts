import { type Page, expect, test } from "@playwright/test";

import { enterFreshBuilder } from "../support/builder";
import { getItineraryAsAdvisor } from "../support/api";

// ITB-1 family — capturing the trip's brief + timing as first-class, structured
// data. The immersive first-run intake is a conversation now; the STRUCTURED
// controls it used to carry (a brief line + a timing picker) moved into the
// builder's DashboardHero — the editable "hero-brief" field and the "hero-timing"
// popover (the shared TimingFields). So these drive the hero as a QA person
// would, and confirm the exact brief + timing that persisted at the API seam.
//
// Each test provisions its own throwaway traveler + itinerary, so a run never
// pollutes the shared `traveler` persona. Local-only — freshTraveler
// provisioning needs the local Supabase.

// Set the trip brief via the hero's inline editor (blur commits).
async function setBrief(page: Page, brief: string): Promise<void> {
  await page.getByTestId("hero-brief").click();
  const input = page.getByTestId("hero-brief-input");
  await input.fill(brief);
  await input.blur();
  await expect(page.getByTestId("hero-brief")).toContainText(brief);
}

// Open the hero's timing popover (the structured When? controls + note + Save).
async function openTiming(page: Page): Promise<void> {
  await page.getByTestId("hero-timing").click();
  await expect(page.getByTestId("hero-timing-popover")).toBeVisible();
}

function pickMode(page: Page, mode: "exact" | "window" | "flexible") {
  return page.getByTestId(`timing-mode-${mode}`).click();
}

function saveTiming(page: Page) {
  return page.getByTestId("hero-timing-save").click();
}

// ITB-1 — the hero captures a brief + a rough window as first-class data, and
// they survive a reload (persisted, not buried in a title).
test("ITB-1: the hero captures the brief + timing and persists across reload", async ({
  page,
  baseURL,
}) => {
  const { id } = await enterFreshBuilder(page, baseURL!);
  const brief = "Sailing in Greece with my family";

  await setBrief(page, brief);
  await openTiming(page);
  await pickMode(page, "window");
  await page.getByTestId("timing-date-start").fill("2027-06-01");
  await page.getByTestId("timing-date-end").fill("2027-08-31");
  await page.getByTestId("timing-nights").fill("7");
  await saveTiming(page);
  await expect(page.getByTestId("hero-timing-popover")).toHaveCount(0);

  // Reload: the brief is persisted first-class, so the hero renders it directly.
  await page.goto(`/itinerary/${id}/dashboard`);
  await expect(page.getByTestId("hero-brief")).toContainText(brief);

  // State backstop: the brief landed as first-class data (not buried in a title).
  const it = await getItineraryAsAdvisor(id);
  expect(it.brief).toBe(brief);
  expect(it.timing_kind).toBe("window");
});

// ITB-1A — exact dates: the entered range IS the trip.
test("ITB-1A: exact dates persist as the trip range", async ({ page, baseURL }) => {
  const { id } = await enterFreshBuilder(page, baseURL!);

  await setBrief(page, "A week in Kyoto");
  await openTiming(page);
  await pickMode(page, "exact");
  await page.getByTestId("timing-date-start").fill("2027-03-18");
  await page.getByTestId("timing-date-end").fill("2027-03-25");
  await saveTiming(page);
  await expect(page.getByTestId("hero-timing-popover")).toHaveCount(0);

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
  const { id } = await enterFreshBuilder(page, baseURL!);

  await setBrief(page, "Generally summer, about a week");
  await openTiming(page);
  await pickMode(page, "window");
  await page.getByTestId("timing-date-start").fill("2027-06-01");
  await page.getByTestId("timing-date-end").fill("2027-08-31");
  await page.getByTestId("timing-nights").fill("7");
  await saveTiming(page);
  await expect(page.getByTestId("hero-timing-popover")).toHaveCount(0);

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
  const { id } = await enterFreshBuilder(page, baseURL!);
  const note = "can't go in August; must be back by a Sunday";

  await setBrief(page, "Somewhere warm, eventually");
  await openTiming(page);
  await pickMode(page, "flexible");
  // Flexible hides the date inputs entirely.
  await expect(page.getByTestId("timing-date-start")).toHaveCount(0);
  await page.getByTestId("hero-timing-note").fill(note);
  await saveTiming(page);
  await expect(page.getByTestId("hero-timing-popover")).toHaveCount(0);

  const it = await getItineraryAsAdvisor(id);
  expect(it.timing_kind).toBe("flexible");
  expect(it.date_start ?? null).toBeNull();
  expect(it.date_end ?? null).toBeNull();
  expect(it.timing_note).toBe(note);
});

// ITB-2 (browser slice) — switching modes clears what the new mode doesn't own:
// pick exact dates, then switch to flexible, and the dates both disappear from
// the popover and are persisted as null.
test("ITB-2: switching to flexible clears the dates", async ({ page, baseURL }) => {
  const { id } = await enterFreshBuilder(page, baseURL!);

  await setBrief(page, "Plans in flux");
  await openTiming(page);
  await pickMode(page, "exact");
  await page.getByTestId("timing-date-start").fill("2027-03-18");
  await page.getByTestId("timing-date-end").fill("2027-03-25");

  // Switch to flexible — the date inputs unmount.
  await pickMode(page, "flexible");
  await expect(page.getByTestId("timing-date-start")).toHaveCount(0);
  await expect(page.getByTestId("timing-date-end")).toHaveCount(0);

  await saveTiming(page);
  await expect(page.getByTestId("hero-timing-popover")).toHaveCount(0);

  const it = await getItineraryAsAdvisor(id);
  expect(it.timing_kind).toBe("flexible");
  expect(it.date_start ?? null).toBeNull();
  expect(it.date_end ?? null).toBeNull();
});

// ITB-3 (browser slice) — a reversed range is caught before it can be saved: the
// inline error shows and the Save button stays disabled. (The
// zero/oversized-duration and unknown-field rejections have no UI surface — they
// stay API/DB-CHECK-only.)
test("ITB-3: a reversed date range is refused in the hero", async ({
  page,
  baseURL,
}) => {
  await enterFreshBuilder(page, baseURL!);

  await openTiming(page);
  await pickMode(page, "exact");
  await page.getByTestId("timing-date-start").fill("2027-03-25");
  await page.getByTestId("timing-date-end").fill("2027-03-18");

  await expect(page.getByText(/The end can.t be before the start/)).toBeVisible();
  await expect(page.getByTestId("hero-timing-save")).toBeDisabled();
});
