import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  getItineraryStatusAsAdvisor,
  seedPricedItemAsAdvisor,
} from "../support/api";

// ADV-10 (advisor half) — the advisor *proposes* the finished plan to the
// traveler (draft → proposed), the step that hands it over for approval. Driven
// as a QA person would: seed a client + a brief'd itinerary with a couple of
// priced cards, land on the dashboard, and use the Approval section to propose —
// then reopen. The per-currency total is shown here too (the money the advisor is
// sending over). The API seam backstops the status transitions the browser drove.
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(tag: string): string {
  return `e2e-adv10-${tag}-${randomUUID()}@example.com`;
}

test("ADV-10: advisor proposes the plan to the traveler (and can reopen it)", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E ADV-10 Client",
    uniqueEmail("propose"),
  );
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, priced",
    brief: "A few days in Kyoto with a couple of firm, priced evenings",
  });
  await seedPricedItemAsAdvisor(itineraryId, {
    title: "Kaiseki dinner",
    amount: "800",
    currency: "USD",
    kind: "total",
  });
  await seedPricedItemAsAdvisor(itineraryId, {
    title: "Private tea ceremony",
    amount: "450",
    currency: "USD",
    kind: "total",
  });

  await page.goto(`/itinerary/${itineraryId}/dashboard`);

  // The plan's per-currency total is shown to the advisor too (the money going over).
  await expect(
    page.locator('[data-testid="dashboard-trip-total-row"][data-currency="USD"]'),
  ).toContainText("1250");

  // Propose it — the advisor's finish-and-hand-over action.
  const propose = page.getByTestId("dashboard-propose");
  await expect(propose).toBeVisible();
  await propose.click();

  // The section flips to the proposed/awaiting state (Reopen now offered).
  await expect(page.getByTestId("dashboard-reopen")).toBeVisible();
  await expect(page.getByTestId("dashboard-propose")).toHaveCount(0);
  await expect.poll(async () => getItineraryStatusAsAdvisor(itineraryId)).toBe(
    "proposed",
  );

  // Reopen resumes building (proposed → draft), the escape hatch.
  await page.getByTestId("dashboard-reopen").click();
  await expect(page.getByTestId("dashboard-propose")).toBeVisible();
  await expect.poll(async () => getItineraryStatusAsAdvisor(itineraryId)).toBe(
    "draft",
  );
});
