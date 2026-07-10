import { randomUUID } from "node:crypto";

import { type Page, expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  getGraphNodesAsAdvisor,
  seedScheduledItemAsAdvisor,
} from "../support/api";

// ADV-4 / G-NODE-EDITOR — the advisor hand-authors a bespoke card the inventory
// providers don't carry, using the summonable "card composer". The three server
// write paths (/nodes, /nodes/from-inventory, /nodes/from-link) are proven at the
// API seam by Pillar 3; what only the browser can show is the composer
// experience: choose a type, name it, price it (or paste a link) — with a LIVE
// card preview — and place it either in the Collection or, from a timeline slot,
// scheduled at that time.
//
// Flow: seed a client + a brief'd itinerary (past the intake gate), acquire the
// edit lock on the Timeline, then summon the composer. The API seam backstops
// the persisted type + cost pair (and starts_at for the scheduled path).
// (`actor_kind = advisor` isn't on the node read — Pillar 3 asserts provenance.)
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(tag: string): string {
  return `e2e-adv4-${tag}-${randomUUID()}@example.com`;
}

// Acquire the edit lock on the Timeline (the composer's writes gate on it).
async function acquireLock(page: Page, itineraryId: string): Promise<void> {
  await page.goto(`/itinerary/${itineraryId}/timeline`);
  const edit = page
    .locator('[data-testid="itinerary-graph-edit"]:visible')
    .first();
  await expect(edit).toBeVisible();
  await edit.click();
  await expect(
    page.locator('[data-testid="itinerary-graph-release"]:visible').first(),
  ).toBeEnabled();
}

test("ADV-4: advisor composes a typed + priced card (with live preview) into the Collection", async ({
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

  await acquireLock(page, itineraryId);
  // Summon the unified Add composer straight from the Timeline toolbar — the
  // authoring tools live here now, not on a separate Studio route.
  await page
    .locator('[data-testid="itinerary-graph-add-card"]:visible')
    .first()
    .click();
  await expect(page.locator('[data-testid="card-composer"]')).toBeVisible();

  // Details is the default. Fill type + name + price.
  await page.locator('[data-testid="composer-type"]').selectOption("meal");
  await page.locator('[data-testid="composer-title"]').fill(title);
  await page.locator('[data-testid="composer-amount"]').fill("450");
  await page.locator('[data-testid="composer-currency"]').selectOption("USD");
  await page.locator('[data-testid="composer-kind"]').selectOption("per_person");

  // The live preview reflects the in-progress card — the name and the price.
  const preview = page.locator('[data-testid="composer-preview"]');
  await expect(preview).toContainText(title);
  await expect(
    page.locator('[data-testid="composer-preview-price"]'),
  ).toContainText("450");

  await page.locator('[data-testid="composer-submit"]').click();
  await expect(page.locator('[data-testid="card-composer"]')).toBeHidden();

  // Lands in the Collection (unscheduled proposed node). Wait for the route to
  // settle before asserting — mid-transition the outgoing timeline (which shows
  // the collection-dominant board when nothing is scheduled) and the incoming
  // Collection route are briefly both mounted.
  await page.locator('[data-testid="rail-collection"]').click();
  await page.waitForURL(`**/itinerary/${itineraryId}/collection`);
  await expect(
    page.locator('[data-testid="collection-card"]').filter({ hasText: title }),
  ).toBeVisible();

  // API backstop: type + cost pair, unscheduled.
  await expect
    .poll(async () =>
      (await getGraphNodesAsAdvisor(itineraryId)).some((n) => n.title === title),
    )
    .toBe(true);
  const node = (await getGraphNodesAsAdvisor(itineraryId)).find(
    (n) => n.title === title,
  );
  expect(node?.type).toBe("meal");
  expect(node?.status).toBe("pending");
  expect(node?.starts_at ?? null).toBeNull();
  expect(Number(node?.cost_amount)).toBe(450);
  expect(node?.cost_currency).toBe("USD");
  expect(node?.cost_kind).toBe("per_person");
});

test("ADV-4: advisor composes a pasted link into the Collection", async ({
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
  const url = `https://example.com/spot-${randomUUID().slice(0, 8)}`;

  await acquireLock(page, itineraryId);
  // Summon from the Collection add affordance this time.
  await page.locator('[data-testid="rail-collection"]').click();
  await page.locator('[data-testid="collection-add-card"]').click();
  await expect(page.locator('[data-testid="card-composer"]')).toBeVisible();

  await page.locator('[data-testid="composer-mode-link"]').click();
  await page
    .locator('[data-testid="composer-type"]')
    .selectOption("experience");
  await page.locator('[data-testid="composer-link"]').fill(url);
  await page.locator('[data-testid="composer-submit"]').click();

  // The pasted link persisted as a `web`-sourced node carrying the URL.
  await expect
    .poll(async () =>
      (await getGraphNodesAsAdvisor(itineraryId)).some(
        (n) => n.source === "web" && n.source_id === url,
      ),
    )
    .toBe(true);
  const node = (await getGraphNodesAsAdvisor(itineraryId)).find(
    (n) => n.source_id === url,
  );
  expect(node?.type).toBe("experience");
  expect(node?.status).toBe("pending");
});

test("ADV-4: advisor clicks an empty timeline slot to schedule a new card", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E ADV-4 Schedule Client",
    uniqueEmail("sched"),
  );
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, bespoke",
    brief: "A few days in Kyoto with a firm evening",
    // Declare the window the cards live in: days_anchor stamps from
    // date_start (Wave E), so Day 1 = Aug 1 and the first empty slot the
    // test clicks is on the seeded card's day — not the day the test ran.
    timing: { kind: "window", dateStart: "2026-08-01", dateEnd: "2026-08-05" },
  });
  // Seed a scheduled node so the timeline renders a day column to click into.
  await seedScheduledItemAsAdvisor(itineraryId, {
    title: "Evening anchor",
    startsAt: "2026-08-01T18:00:00Z",
  });
  const title = `Morning temple ${randomUUID().slice(0, 8)}`;

  await acquireLock(page, itineraryId);

  // Click empty column space near the top (morning) — the create-slot layer maps
  // it to a day + minute and opens the composer pre-set to that slot.
  const slot = page.locator('[data-testid="create-slot"]').first();
  await expect(slot).toBeVisible();
  await slot.click({ position: { x: 30, y: 48 } });

  const composer = page.locator('[data-testid="card-composer"]');
  await expect(composer).toBeVisible();
  // The slot seeds an EDITABLE datetime, not a static chip — pre-filled to the
  // clicked day so the advisor can nudge the time before adding.
  const scheduleInput = page.locator('[data-testid="composer-schedule-input"]');
  await expect(scheduleInput).toBeVisible();
  await expect(scheduleInput).toHaveValue(/^2026-08-01T\d{2}:\d{2}$/);
  // Adjust the time to a firm morning before adding (stays on 2026-08-01).
  await scheduleInput.fill("2026-08-01T07:15");

  await page.locator('[data-testid="composer-type"]').selectOption("experience");
  await page.locator('[data-testid="composer-title"]').fill(title);
  await page.locator('[data-testid="composer-submit"]').click();
  await expect(composer).toBeHidden();

  // API backstop: the node persisted SCHEDULED (starts_at set), on 2026-08-01.
  await expect
    .poll(async () =>
      (await getGraphNodesAsAdvisor(itineraryId)).some((n) => n.title === title),
    )
    .toBe(true);
  const node = (await getGraphNodesAsAdvisor(itineraryId)).find(
    (n) => n.title === title,
  );
  expect(node?.type).toBe("experience");
  expect(node?.status).toBe("pending");
  expect(node?.starts_at ?? null).not.toBeNull();
  expect(node?.starts_at ?? "").toContain("2026-08-01");
});
