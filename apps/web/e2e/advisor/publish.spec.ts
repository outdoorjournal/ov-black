import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  forkItineraryAsAdvisor,
  getGraphNodesAsAdvisor,
  getItineraryStatusAsAdvisor,
  seedPricedItemAsAdvisor,
} from "../support/api";

// The publish half of the trunk + working-copy model: the advisor builds in
// their private fork and PUBLISHES — an accept-all reconcile that folds the
// workspace into the official trunk, where the cards land `pending` for the
// traveler's review. Driven as a QA person would: seed a trunk + an advisor
// fork with priced cards over the API, land on the fork in the browser, and
// publish from the version switcher. The API seam backstops what the browser
// drove: trunk gains the content and buckets `with_traveler`.
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(tag: string): string {
  return `e2e-publish-${tag}-${randomUUID()}@example.com`;
}

test("advisor publishes their workspace into the official trunk", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E Publish Client",
    uniqueEmail("flow"),
  );
  const trunkId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, crafted",
    brief: "A few days in Kyoto, composed privately then published",
  });
  // The workspace: an advisor fork carrying the build. The trunk stays empty
  // (private until publish).
  const forkId = await forkItineraryAsAdvisor(trunkId);
  await seedPricedItemAsAdvisor(forkId, {
    title: "Kaiseki dinner",
    amount: "800",
    currency: "USD",
    kind: "total",
  });
  expect(await getGraphNodesAsAdvisor(trunkId)).toHaveLength(0);

  await page.goto(`/itinerary/${forkId}`);

  // The switcher shows the advisor is on their workspace, with Publish live.
  await expect(page.getByTestId("version-mine")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const publish = page.getByTestId("publish-mine");
  await expect(publish).toBeVisible();
  await publish.click();

  // Publishing navigates back to the official trunk.
  await page.waitForURL(`**/itinerary/${trunkId}**`);

  // API seam: the trunk now carries the card, pending, and reads with_traveler.
  await expect
    .poll(async () => (await getGraphNodesAsAdvisor(trunkId)).length)
    .toBeGreaterThan(0);
  const nodes = await getGraphNodesAsAdvisor(trunkId);
  expect(nodes.map((n) => n.title)).toContain("Kaiseki dinner");
  await expect
    .poll(async () => getItineraryStatusAsAdvisor(trunkId))
    .toBe("with_traveler");
});
