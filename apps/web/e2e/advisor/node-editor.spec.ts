import { randomUUID } from "node:crypto";

import { type Page, expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  getGraphNodesAsAdvisor,
} from "../support/api";

// ADV-4 / G-NODE-EDITOR — the advisor hand-authors a bespoke card the inventory
// providers don't carry, using the Studio "Add a card" editor. The three server
// write paths (/nodes, /nodes/from-inventory, /nodes/from-link) are proven at the
// API seam by Pillar 3; what only the browser can show is the editor experience:
// choose a type, name it, price it (or paste a link) → a card lands on the board.
//
// Flow: seed a client + a brief'd itinerary (past the intake gate), acquire the
// edit lock on the Timeline, then cross to Studio via the rail — a client-side
// nav that keeps the same store instance, so the lock carries. The authored node
// is unscheduled + proposed, so it surfaces in the Collection. The API seam
// backstops the persisted type + cost pair. (`actor_kind = advisor` isn't on the
// node read — Pillar 3 asserts provenance on the shared add_node path.)
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(tag: string): string {
  return `e2e-adv4-${tag}-${randomUUID()}@example.com`;
}

// Acquire the edit lock on the Timeline, then open Studio (Build tab) with the
// lock carried across the sibling-route nav.
async function lockAndOpenStudio(page: Page, itineraryId: string): Promise<void> {
  await page.goto(`/itinerary/${itineraryId}/timeline`);
  const edit = page
    .locator('[data-testid="itinerary-graph-edit"]:visible')
    .first();
  await expect(edit).toBeVisible();
  await edit.click();
  // The lock is mine once Release enables.
  await expect(
    page.locator('[data-testid="itinerary-graph-release"]:visible').first(),
  ).toBeEnabled();

  await page.locator('[data-testid="rail-studio"]').click();
  await expect(page).toHaveURL(new RegExp(`/itinerary/${itineraryId}/studio`));
  await expect(
    page.locator('[data-testid="itinerary-graph-add-card"]'),
  ).toBeVisible();
}

test("ADV-4: advisor hand-authors a typed + priced card in the editor", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E ADV-4 Client",
    uniqueEmail("typed"),
  );
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, bespoke",
    brief: "A few days in Kyoto with hand-picked meals",
  });
  const title = `Kaiseki dinner ${randomUUID().slice(0, 8)}`;

  await lockAndOpenStudio(page, itineraryId);

  // Open the editor — Details mode is the default (typed + priced).
  await page.locator('[data-testid="add-card-toggle"]').click();
  await page.locator('[data-testid="add-card-type"]').selectOption("meal");
  await page.locator('[data-testid="add-card-title"]').fill(title);
  await page.locator('[data-testid="add-card-amount"]').fill("450");
  await page.locator('[data-testid="add-card-currency"]').selectOption("USD");
  await page
    .locator('[data-testid="add-card-kind"]')
    .selectOption("per_person");
  await page.locator('[data-testid="add-card-submit"]').click();

  // The card lands on the board: an unscheduled proposed node shows in the
  // Collection (same store instance across the rail nav).
  await page.locator('[data-testid="rail-collection"]').click();
  await expect(
    page.locator('[data-testid="collection-card"]').filter({ hasText: title }),
  ).toBeVisible();

  // API backstop: the node persisted with the chosen type + cost pair.
  await expect
    .poll(async () => {
      const nodes = await getGraphNodesAsAdvisor(itineraryId);
      return nodes.some((n) => n.title === title);
    })
    .toBe(true);
  const node = (await getGraphNodesAsAdvisor(itineraryId)).find(
    (n) => n.title === title,
  );
  expect(node?.type).toBe("meal");
  expect(node?.status).toBe("proposed");
  expect(Number(node?.cost_amount)).toBe(450);
  expect(node?.cost_currency).toBe("USD");
  expect(node?.cost_kind).toBe("per_person");
});

test("ADV-4: advisor saves a pasted link as a card via the editor", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E ADV-4 Link Client",
    uniqueEmail("link"),
  );
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, bespoke",
    brief: "A few days in Kyoto with hand-picked places",
  });
  // A stable, dependency-free URL: even if the OpenGraph fetch fails, from-link
  // degrades to the bare URL as the title, so the node is deterministic.
  const url = `https://example.com/spot-${randomUUID().slice(0, 8)}`;

  await lockAndOpenStudio(page, itineraryId);

  await page.locator('[data-testid="add-card-toggle"]').click();
  await page.locator('[data-testid="add-card-mode-link"]').click();
  await page.locator('[data-testid="add-card-type"]').selectOption("experience");
  await page.locator('[data-testid="add-card-link"]').fill(url);
  await page.locator('[data-testid="add-card-submit"]').click();

  // The pasted link persisted as a `web`-sourced node carrying the URL.
  await expect
    .poll(async () => {
      const nodes = await getGraphNodesAsAdvisor(itineraryId);
      return nodes.some((n) => n.source === "web" && n.source_id === url);
    })
    .toBe(true);
  const node = (await getGraphNodesAsAdvisor(itineraryId)).find(
    (n) => n.source_id === url,
  );
  expect(node?.type).toBe("experience");
  expect(node?.status).toBe("proposed");
});
