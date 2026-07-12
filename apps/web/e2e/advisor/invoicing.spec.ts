import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  approveNodeAsAdvisor,
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  listInvoicesAsAdvisor,
  seedPricedItemAsAdvisor,
} from "../support/api";

// ADV-11 (advisor half) — the billing COCKPIT. Before payment can happen the
// advisor has to get to an issued invoice, and know what it covers. Driven as a
// QA person would: seed a client + itinerary with two approved, priced cards, open
// the Invoices destination from the left Rail (its own CRUD surface pinned to the
// itinerary), and use the reconciliation glance + "Bill all uninvoiced" + Issue to
// stand up the first invoice. The API seam backstops what the actions persisted.
//
// No edit lock: invoicing gates on advisor ROLE, not the graph build-lock — it's
// advisor-only server-side and works on any itinerary status. Nodes are approved
// individually so the trip carries a per-currency total to reconcile against.
//
// The traveler pay half uses the env-gated "pay with test card" affordance
// (sandbox nonce via the Fake gateway locally): driven when OVB_/NEXT_PUBLIC_
// DEMO_TEST_CARD is set, else skipped (gateway boundary per advisor-plan.md §4).
// The button→nonce→paid path is also unit-tested (payInvoiceView.test.tsx).
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(tag: string): string {
  return `e2e-adv11-${tag}-${randomUUID()}@example.com`;
}

test("ADV-11: advisor stands up the first invoice from the billing cockpit", async ({
  page,
}) => {
  const clientId = await createClientAsAdvisor(
    "E2E ADV-11 Client",
    uniqueEmail("invoice"),
  );
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Kyoto, billable",
    brief: "A few firm, priced days in Kyoto",
  });

  // Two approved, priced cards → the trip carries a USD total of 1,250 and two
  // chargeable-but-uninvoiced nodes.
  const nodeA = await seedPricedItemAsAdvisor(itineraryId, {
    title: "Kaiseki dinner",
    amount: "800",
    currency: "USD",
    kind: "total",
  });
  const nodeB = await seedPricedItemAsAdvisor(itineraryId, {
    title: "Private tea ceremony",
    amount: "450",
    currency: "USD",
    kind: "total",
  });
  await approveNodeAsAdvisor(itineraryId, nodeA);
  await approveNodeAsAdvisor(itineraryId, nodeB);

  // Reach the Invoices destination from the left Rail — its own CRUD surface
  // pinned to this itinerary. No edit lock needed: invoicing gates on advisor role,
  // not the graph build-lock (it must work on any itinerary status).
  await page.goto(`/itinerary/${itineraryId}/dashboard`);
  await page.getByTestId("rail-finances").click();
  await expect(page.getByTestId("finances-view")).toBeVisible();

  // The reconciliation glance renders, grouped by currency, with the uninvoiced
  // remainder — the "am I done billing?" truth. Everything is still uninvoiced.
  await expect(page.getByTestId("invoice-reconcile")).toBeVisible();
  await expect(
    page.locator('[data-testid="invoice-reconcile-row"][data-currency="USD"]'),
  ).toBeVisible();
  await expect(page.getByTestId("reconcile-trip-total")).toBeVisible();

  // One click bills every uncovered node — the fast path to the first invoice.
  const billAll = page.getByTestId("invoice-bill-all");
  await expect(billAll).toContainText("(2)");
  await billAll.click();

  // The draft now carries both charges; issue it.
  const issue = page.getByTestId("invoice-issue");
  await expect(issue).toBeVisible();
  await issue.click();

  // With everything invoiced, the "bill all" shortcut and supplemental prompt are
  // both gone (nothing left uncovered).
  await expect(page.getByTestId("invoice-bill-all")).toHaveCount(0);
  await expect(page.getByTestId("invoice-supplemental")).toHaveCount(0);

  // API-seam backstop: exactly one issued invoice for the full 1,250.
  await expect
    .poll(async () => {
      const invoices = await listInvoicesAsAdvisor(itineraryId);
      return invoices.map((i) => `${i.status}:${i.total}:${i.currency}`);
    })
    .toEqual(["issued:1250.00:USD"]);

  // Traveler pay — demo/dev only (env-gated). Drive it when the flag is on;
  // otherwise the gateway boundary (§4) is covered at the unit layer.
  const invoices = await listInvoicesAsAdvisor(itineraryId);
  const invoiceId = invoices[0]?.id;
  if (invoiceId) {
    await page.goto(`/invoices/${invoiceId}`);
    // Wait for the pay section to actually render (the invoice loads async) before
    // deciding whether the demo test-card button is present — else we race the load.
    await expect(page.getByTestId("pay-submit")).toBeVisible();
    const testCard = page.getByTestId("pay-test-card");
    if (await testCard.count()) {
      await testCard.click();
      await expect(page.getByTestId("pay-receipt")).toBeVisible();
    } else {
      test.info().annotations.push({
        type: "skip",
        description:
          "pay-with-test-card off (DEMO_TEST_CARD unset) — pay is gateway-gated per §4",
      });
    }
  }
});
