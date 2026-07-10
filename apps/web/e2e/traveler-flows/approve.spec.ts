import { type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import {
  createItineraryForClientAsAdvisor,
  findClientByEmail,
  getGraphNodesAsAdvisor,
  getItineraryStatusAsAdvisor,
  seedPricedItemAsAdvisor,
} from "../support/api";

// ADV-10 — the traveler approves a plan the advisor has *proposed*, and sees its
// price. Driven as a QA person would: the advisor builds + prices a plan for the
// traveler's client and proposes it at the seam (advisor — entitled to write it;
// this is the ADV-10 shape — the advisor builds, the traveler approves), then the
// browser proves the two traveler paths to `approved`:
//   - "Approve all" on the dashboard flips the whole plan in one action, and the
//     per-currency total the traveler is approving is shown alongside;
//   - card-by-card "Approve this" firms up one card at a time, and clearing the
//     LAST proposed card derives the itinerary itself to approved.
// The API seam backstops the itinerary status + node statuses the browser drove.
// Local-only (freshTraveler needs the local Supabase).

// A fresh traveler, signed in (loading basecamp JIT-backfills their client
// ownership), with the advisor having priced + proposed an itinerary onto their
// client. Returns the itinerary id — the traveler navigates straight to it.
async function seedProposedPricedTripForTraveler(
  page: Page,
  baseURL: string,
): Promise<{ id: string }> {
  const { email, callbackUrl } = await freshTravelerCallbackUrl(baseURL);
  // Sign the traveler in; landing on basecamp backfills clients.auth_user_id so
  // the traveler owns their linked client (and can later read + approve the plan).
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  // Advisor builds the plan on the traveler's linked client: brief + two priced
  // proposed cards (→ a USD total), then proposes it (draft → proposed).
  const client = await findClientByEmail(email);
  if (!client) throw new Error(`no linked client for ${email}`);
  const id = await createItineraryForClientAsAdvisor(client.id, {
    title: "Kyoto, priced",
    brief: "A week in Kyoto with a couple of firm, priced evenings",
  });
  await seedPricedItemAsAdvisor(id, {
    title: "Kaiseki dinner",
    amount: "800",
    currency: "USD",
    kind: "total",
  });
  await seedPricedItemAsAdvisor(id, {
    title: "Private tea ceremony",
    amount: "450",
    currency: "USD",
    kind: "total",
  });
  // TODO(wave4): the whole-itinerary propose endpoint is gone (trunk + forks
  // model). Seeded pending cards already surface to the traveler; the proper
  // publish-flow rework lands next wave.
  return { id };
}

// ADV-10a — one-action "Approve all" + the shown per-currency total.
test("ADV-10: the traveler approves the whole plan at once and sees the price", async ({
  page,
  baseURL,
}) => {
  const { id } = await seedProposedPricedTripForTraveler(page, baseURL!);

  await page.goto(`/itinerary/${id}/dashboard`);

  // The plan's per-currency total is shown — what the traveler is approving.
  const total = page.getByTestId("dashboard-trip-total");
  await expect(total).toBeVisible();
  await expect(
    page.locator('[data-testid="dashboard-trip-total-row"][data-currency="USD"]'),
  ).toContainText("1250");

  // One action approves the whole plan.
  const approveAll = page.getByTestId("dashboard-approve-all");
  await expect(approveAll).toBeVisible();
  await approveAll.click();

  // The section reflects the approved plan (optimistic), and the total still shows.
  await expect(page.getByTestId("dashboard-approve-all")).toHaveCount(0);
  await expect(total).toBeVisible();

  // API backstop: the itinerary is approved and every proposed node cascaded.
  await expect.poll(async () => getItineraryStatusAsAdvisor(id)).toBe("approved");
  const nodes = await getGraphNodesAsAdvisor(id);
  expect(nodes.length).toBeGreaterThan(0);
  expect(nodes.every((n) => n.status === "approved")).toBe(true);
});

// ADV-10b — node-by-node: approving each proposed card one at a time reaches the
// same approved end state (the last card derives the itinerary to approved).
test("ADV-10: the traveler approves card-by-card and the plan derives to approved", async ({
  page,
  baseURL,
}) => {
  const { id } = await seedProposedPricedTripForTraveler(page, baseURL!);

  const pending = (await getGraphNodesAsAdvisor(id)).filter(
    (n) => n.status === "pending",
  );
  expect(pending.length).toBe(2);

  // Approve each card from its detail route; after the first the plan is still
  // with the traveler, after the last it derives to approved.
  for (let i = 0; i < pending.length; i++) {
    const node = pending[i]!;
    await page.goto(`/itinerary/${id}/item/${node.id}`);
    const approve = page.getByTestId("card-detail-approve-node");
    await expect(approve).toBeVisible();
    await approve.click();
    await expect
      .poll(async () =>
        (await getGraphNodesAsAdvisor(id)).find((n) => n.id === node.id)?.status,
      )
      .toBe("approved");
    await expect
      .poll(async () => getItineraryStatusAsAdvisor(id))
      .toBe(i === pending.length - 1 ? "approved" : "with_traveler");
  }
});
