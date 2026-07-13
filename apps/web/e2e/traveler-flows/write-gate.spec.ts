import { expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import { reachFreshIntake } from "../support/builder";

// ITB-5 (browser slice) — the same relationship gate that guards brief *writes*
// also guards *visibility*: a non-entitled viewer can't even open the draft. The
// owner reaches the intake; a stranger gets a 404 (the draft's existence stays
// hidden — S08's notFound()), so there's no intake to attempt a write on. The
// write-side 403 itself (owner 200 vs. stranger 403 on PATCH) has no browser
// surface for a stranger and stays covered at the API seam.
test("ITB-5: a stranger cannot open another traveler's draft itinerary", async ({
  page,
  browser,
  baseURL,
}) => {
  // Owner A starts a draft and reaches its intake (the helper leaves the page on
  // the intake and asserts the "Where shall we take you?" headline).
  const { id } = await reachFreshIntake(page, baseURL!);

  // Stranger B (a different linked traveler, no relationship to A's itinerary)
  // hits the same URL in their own session and is refused.
  const strangerCtx = await browser.newContext();
  const strangerPage = await strangerCtx.newPage();
  const stranger = await freshTravelerCallbackUrl(baseURL!);
  await strangerPage.goto(stranger.callbackUrl);
  await expect(strangerPage).toHaveURL(/\/basecamp/);

  const resp = await strangerPage.goto(`/itinerary/${id}`);
  expect(resp?.status()).toBe(404);
  await expect(
    strangerPage.getByRole("heading", { name: "Where shall we take you?" }),
  ).toHaveCount(0);

  await strangerCtx.close();
});
