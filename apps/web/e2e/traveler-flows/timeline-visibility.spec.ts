import { type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";

// ITB-6 / ITB-6A — the builder shouldn't show a *dated* timeline before it knows
// *when*. With a vague brief (window/flexible) and an empty board, a date grid is
// meaningless (it would be synthesized around "today"), so only the concierge
// empty-state shows. Exact dates — or anything already on the board — bring the
// timeline back. Driven as a QA person would: start a trip, pick a timing mode,
// and look at whether the timeline scaffold is there.

async function startIntake(page: Page, baseURL: string): Promise<string> {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);
  await page.getByRole("button", { name: "Start a new itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/, { timeout: 30_000 });
  await expect(
    page.getByRole("heading", { name: "Where shall we take you?" }),
  ).toBeVisible();
  return page.url().split("/itinerary/")[1]!.split(/[?#]/)[0]!;
}

const header = (page: Page) => page.getByTestId("itinerary-graph-header");

// ITB-6 — a vague brief keeps the dated timeline hidden.
test("ITB-6: a vague brief (no dates yet) hides the dated timeline", async ({
  page,
  baseURL,
}) => {
  await startIntake(page, baseURL!);
  await page.getByLabel("The trip, in a sentence").fill("Somewhere warm, sometime");
  await page.getByRole("button", { name: "Flexible" }).click();
  await page.getByRole("button", { name: "Start building" }).click();

  // Only the concierge guidance — no dated grid behind it.
  await expect(
    page.getByRole("heading", { name: "A blank canvas, ready when you are" }),
  ).toBeVisible();
  await expect(header(page)).toHaveAttribute("data-timeline-visible", "false");
});

// ITB-6A — knowing the exact dates is enough to (optionally) show the timeline.
test("ITB-6A: exact dates bring the timeline back", async ({ page, baseURL }) => {
  const id = await startIntake(page, baseURL!);
  await page.getByLabel("The trip, in a sentence").fill("A week in Lisbon");
  await page.getByRole("button", { name: "Exact dates" }).click();
  await page.getByLabel("Start").fill("2027-05-10");
  await page.getByLabel("End").fill("2027-05-17");
  await page.getByRole("button", { name: "Start building" }).click();
  await expect(
    page.getByRole("heading", { name: "A blank canvas, ready when you are" }),
  ).toBeVisible();

  // Reload so SSR rebuilds the timeline from the now-persisted exact timing (the
  // in-place reveal still holds the pre-save prop, when timing was unset).
  await page.goto(`/itinerary/${id}`);
  await expect(header(page)).toHaveAttribute("data-timeline-visible", "true");
});
