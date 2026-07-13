import { expect, test } from "@playwright/test";

import {
  createItineraryForClientAsAdvisor,
  findClientByEmail,
} from "../support/api";
import { freshTravelerCallbackUrl } from "../support/auth";
import { enterFreshBuilder } from "../support/builder";

// ITB-4 — once a brief is set but the timeline still has no nodes, the builder
// shows a guiding empty-state (not a bare canvas): it explains the concierge
// builds the trip out and points at where the conversation lives.
test("ITB-4: an empty timeline guides the traveler to the concierge", async ({
  page,
  baseURL,
}) => {
  // A brief unblocks the timeline; with no nodes yet, the empty-state stands in.
  const { id } = await enterFreshBuilder(page, baseURL!, {
    brief: "A blank slate for now",
    timing: { kind: "flexible" },
  });
  await page.goto(`/itinerary/${id}/timeline`);

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

// The teaser half: an ADVISOR-crafted trunk with nothing published yet shows
// the anticipation state, not the self-serve builder prompt — the advisor
// builds privately in their workspace and this official view stays quiet
// until they publish.
test("an advisor-crafted trip with nothing published shows the teaser", async ({
  page,
  baseURL,
}) => {
  const { email, callbackUrl } = await freshTravelerCallbackUrl(baseURL!);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  const client = await findClientByEmail(email);
  if (!client) throw new Error(`no linked client for ${email}`);
  const trunkId = await createItineraryForClientAsAdvisor(client.id, {
    title: "Kyoto, being crafted",
    brief: "A week in Kyoto — composed by the advisor, not yet published",
  });

  await page.goto(`/itinerary/${trunkId}/timeline`);

  await expect(
    page.getByRole("heading", { name: "Your advisor is crafting something" }),
  ).toBeVisible();
  // The self-serve builder prompt must NOT show on an advisor-crafted trip.
  await expect(
    page.getByRole("heading", { name: "A blank canvas, ready when you are" }),
  ).toHaveCount(0);
});
