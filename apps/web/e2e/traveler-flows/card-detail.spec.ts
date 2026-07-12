import { type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import { seedScheduledItemAsAdvisor } from "../support/api";

// CARD family (M006/PS4) — card detail as a route. Driven as a QA person would:
// a fresh traveler starts a trip, we seed a scheduled card at the API seam
// (advisor — entitled to write any itinerary), then the browser proves the two
// halves of the slice:
//   - a card is deep-linkable — /itinerary/[id]/item/[nodeId] resolves to the
//     full-bleed detail with its facets (role-agnostic; a traveler opens it),
//   - opening a card scopes the concierge SILENTLY — the next turn carries the
//     viewed card as a hidden `viewing_node_id` (no chip, no text prefix) — a
//     real turn against the local agent.
// The builder mounts a desktop + a mobile layout (one hidden by responsive CSS),
// so timeline locators are scoped to `:visible`. Local-only (freshTraveler needs
// the local Supabase; the live turn needs apps/agent on :8080).

const CARD_TITLE = "Tea ceremony at dawn";

// Fresh traveler → basecamp → new itinerary → intake → builder, then seed one
// scheduled card at the seam. Returns the itinerary + node ids.
async function startTripWithCard(
  page: Page,
  baseURL: string,
): Promise<{ id: string; nodeId: string }> {
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  await page.getByRole("button", { name: "Start a new itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/, { timeout: 30_000 });
  const id = page.url().split("/itinerary/")[1]!.split(/[?#]/)[0]!;

  await page.getByLabel("The trip, in a sentence").fill("A quiet week in Kyoto");
  await page.getByRole("button", { name: "Flexible" }).click();
  await page.getByRole("button", { name: "Start building" }).click();

  // A scheduled card gives the timeline something to render + something to open.
  const nodeId = await seedScheduledItemAsAdvisor(id, {
    type: "experience",
    title: CARD_TITLE,
    startsAt: "2026-08-15T06:00:00+09:00",
  });
  return { id, nodeId };
}

// CARD-1 — a card is deep-linkable: the traveler opens /item/[nodeId] straight
// on and lands on the full-bleed detail with its facets (a traveler, not staff,
// so this is the role-agnostic path).
test("CARD-1: a card detail is deep-linkable to its facets", async ({ page, baseURL }) => {
  const { id, nodeId } = await startTripWithCard(page, baseURL!);

  await page.goto(`/itinerary/${id}/item/${nodeId}`);

  const detail = page.getByTestId("card-detail");
  await expect(detail).toBeVisible();
  await expect(detail).toHaveAttribute("data-node-id", nodeId);
  await expect(page.getByRole("heading", { level: 1, name: CARD_TITLE })).toBeVisible();

  // The facet a traveler always gets: money (actions/schedule are conditional
  // on a location / holding the lock).
  await expect(page.getByTestId("card-detail-money")).toBeVisible();
  // The money read resolved (loading state cleared) — nothing billed yet here.
  await expect(page.getByTestId("card-detail-money-empty")).toBeVisible();

  // The back affordance returns to the timeline.
  await page.getByTestId("card-detail-back").click();
  await expect(page).toHaveURL(new RegExp(`/itinerary/${id}/timeline`));
});

// CARD-2 — clicking a card on the timeline routes to its detail (the primary
// interaction, replacing the old in-place modal).
test("CARD-2: clicking a timeline card opens its detail route", async ({ page, baseURL }) => {
  const { id, nodeId } = await startTripWithCard(page, baseURL!);

  await page.goto(`/itinerary/${id}/timeline`);
  // The card is framer-motion-animated + absolutely positioned on the canvas, so
  // Playwright's stability wait never settles — force the click; we're only
  // asserting the click handler routes.
  const card = page
    .locator(`[data-testid="timeline-card"][data-node-id="${nodeId}"]:visible`)
    .first();
  await expect(card).toBeVisible();
  await card.click({ force: true });

  await expect(page).toHaveURL(new RegExp(`/itinerary/${id}/item/${nodeId}`));
  await expect(page.getByTestId("card-detail")).toBeVisible();
});

// CARD-3 — opening a card scopes the concierge SILENTLY: no chip, the turn text
// is sent verbatim (no "Regarding …" prefix), and the POST carries the viewed
// card as a hidden `viewing_node_id` (a real turn end-to-end against the agent).
test("CARD-3: opening a card scopes the concierge silently and takes the turn", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(180_000);
  const { id, nodeId } = await startTripWithCard(page, baseURL!);

  await page.goto(`/itinerary/${id}/item/${nodeId}`);
  await expect(page.getByTestId("card-detail")).toBeVisible();

  // No manual scope UI exists anymore — the card rides along silently.
  await expect(page.getByTestId("concierge-context-chip")).toHaveCount(0);

  const composer = page.locator(
    'input[placeholder="Ask me to propose, assemble, or swap…"]:visible',
  );
  await expect(composer).toBeEnabled();
  await composer.fill("what time should we arrive?");

  // Capture the turn POST: its body must carry the viewed card verbatim, with
  // no text prefix, so the agent silently knows what's on screen.
  const turnRequest = page.waitForRequest(
    (req) => req.method() === "POST" && /\/sessions\/[0-9a-f-]+\/turn$/.test(req.url()),
  );
  await page.locator("button:visible", { hasText: "Send" }).click();

  const body = (await turnRequest).postDataJSON() as {
    content: string;
    viewing_node_id?: string;
  };
  expect(body.content).toBe("what time should we arrive?");
  expect(body.viewing_node_id).toBe(nodeId);

  // The message bubble shows the typed text unchanged — no "Regarding …" scope.
  await expect(composer).toHaveValue("");
  await expect(page.getByText("what time should we arrive?").first()).toBeVisible();
  await expect(page.getByText(/Regarding/)).toHaveCount(0);

  // The turn runs end-to-end against the live agent: the composer re-enables once
  // the reply has streamed, and it never hit the "couldn't reach" fallback.
  await expect(composer).toBeEnabled({ timeout: 150_000 });
  await expect(page.getByText(/Couldn.t reach the concierge/)).toHaveCount(0);
});
