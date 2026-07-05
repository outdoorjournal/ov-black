import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  getGraphNodesAsAdvisor,
  getItineraryStatusAsAdvisor,
  seedIdeaItemAsAdvisor,
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

// ADV-10 (advisor, per-card) — the per-card mirror of the whole-plan propose:
// from a card's detail the advisor firms up a single `idea` card to `proposed`
// (hands *that card* over) without freezing the rest of the build. Only that
// node moves — the itinerary stays `draft`. This is the advisor's action on a
// card; the traveler's mirror is "Approve this" (proposed → approved). Driven as
// a QA person would: seed two raw idea cards, open one, propose it, and let the
// API seam backstop the node/itinerary statuses the browser drove.
test("ADV-10: advisor proposes a single card to the traveler (idea → proposed)", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E ADV-10 Client",
    uniqueEmail("propose-card"),
  );
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, building",
    brief: "A few days in Kyoto, still being shaped",
  });
  // Two raw idea cards — the advisor is mid-build; nothing is proposed yet.
  const nodeId = await seedIdeaItemAsAdvisor(itineraryId, {
    title: "Kaiseki dinner",
  });
  await seedIdeaItemAsAdvisor(itineraryId, { title: "Private tea ceremony" });

  // Open that card's detail and propose it — the advisor's per-card hand-over.
  await page.goto(`/itinerary/${itineraryId}/item/${nodeId}`);
  const propose = page.getByTestId("card-detail-propose-node");
  await expect(propose).toBeVisible();
  await propose.click();

  // API seam: only this node flips to proposed; the itinerary stays draft (the
  // advisor is proposing a card, not the whole plan).
  await expect
    .poll(async () =>
      (await getGraphNodesAsAdvisor(itineraryId)).find((n) => n.id === nodeId)
        ?.status,
    )
    .toBe("proposed");
  await expect.poll(async () => getItineraryStatusAsAdvisor(itineraryId)).toBe(
    "draft",
  );

  // Once proposed there's nothing more to hand over here — the action is gone.
  await expect(page.getByTestId("card-detail-propose-node")).toHaveCount(0);
});
