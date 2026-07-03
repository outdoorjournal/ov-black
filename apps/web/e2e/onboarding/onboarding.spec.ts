import { expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";

// Onboarding lifecycle (ONB-2 / ONB-2A). Each test provisions its OWN throwaway
// traveler and self-authenticates via the real magic-link callback, so these
// mutating flows never touch the shared `traveler` persona. Kept in one file +
// the `onboarding` project's fullyParallel:false so they share a worker (and the
// per-worker advisor-token cache is minted once — see support/auth.ts).

// ONB-2 — a brand-new, never-onboarded traveler lands on the first-prompt
// onboarding experience (the seeded opener + composer), not the returning-user
// shell. This is the mock-safe half of ONB-2; the positive completion path
// (engage → profile facts → no reminder) needs a real tool-using agent and is
// covered at the API seam by Pillar 2. See doc/qa/onboarding.md.
test("ONB-2: a never-onboarded traveler lands on the onboarding opener", async ({
  page,
  baseURL,
}) => {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL!);

  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  // The first-prompt composer proves the new-user (first_prompt) variant.
  await expect(page.getByPlaceholder("Begin in your own words…")).toBeVisible();

  // The skip affordance is present pre-engage — the entry point ONB-2A drives.
  await expect(page.getByRole("button", { name: "Not now" })).toBeVisible();

  // Not the returning-user reminder — this is a fresh arrival, nothing skipped.
  await expect(
    page.getByRole("heading", { name: "Tell us how you travel" }),
  ).toHaveCount(0);
});

// ONB-2A — a traveler who skips onboarding before telling us anything gets a
// gentle "finish your introduction" reminder on basecamp (the nudge), rather
// than the welcoming empty-itineraries state. Mechanics: dismissing writes a
// marker session (has_prior_session → true) and, with no profile facts, the
// server re-renders post_first_touch into the reminder. See
// app/routers/onboarding.py (dismiss) + app/routers/me.py (has_profile_facts).
test("ONB-2A: skipping onboarding surfaces the finish-your-introduction reminder", async ({
  page,
  baseURL,
}) => {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL!);

  await page.goto(callbackUrl);
  await expect(page.getByPlaceholder("Begin in your own words…")).toBeVisible();

  // Skip without engaging.
  await page.getByRole("button", { name: "Not now" }).click();

  // The nudge appears — router.refresh re-renders post_first_touch, and with no
  // profile facts the reminder shows instead of the welcoming empty state.
  await expect(
    page.getByRole("heading", { name: "Tell us how you travel" }),
  ).toBeVisible();

  // And they are not re-prompted: the opener is gone.
  await expect(
    page.getByPlaceholder("Begin in your own words…"),
  ).toHaveCount(0);
});
