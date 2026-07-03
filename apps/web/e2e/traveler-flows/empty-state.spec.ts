import { expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";

// ITB-4 — once a brief is set but the timeline still has no nodes, the builder
// shows a guiding empty-state (not a bare canvas): it explains the concierge
// builds the trip out and points at where the conversation lives.
test("ITB-4: an empty timeline guides the traveler to the concierge", async ({
  page,
  baseURL,
}) => {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL!);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  await page.getByRole("button", { name: "Start a new itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/, { timeout: 30_000 });

  // A brief unblocks the timeline; with no nodes yet, the empty-state stands in.
  await page.getByLabel("The trip, in a sentence").fill("A blank slate for now");
  await page.getByRole("button", { name: "Flexible" }).click();
  await page.getByRole("button", { name: "Start building" }).click();

  // The builder mounts both a desktop and a mobile empty-state (one hidden by
  // responsive CSS), so text lives in the DOM twice. getByRole filters to the
  // visible (a11y-tree) copy; for the plain paragraph we scope to `:visible`.
  await expect(
    page.getByRole("heading", { name: "A blank canvas, ready when you are" }),
  ).toBeVisible();
  await expect(
    page.locator("p:visible", { hasText: "Tell the concierge what you have in mind" }),
  ).toBeVisible();
  // The desktop pointer text is unique to the visible (aside) layout.
  await expect(page.getByText("Start in the Concierge panel →")).toBeVisible();

  // NOTE: that the saved brief actually *seeds the concierge's context* (grounded
  // first suggestions) is Bedrock-gated — the mock agent records nothing — so
  // that bullet is asserted at the API seam by the pillar suite, not in-browser.
  // See doc/qa/itinerary-builder.md · ITB-4.
});
