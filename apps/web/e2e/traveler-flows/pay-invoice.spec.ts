import { type FrameLocator, type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import {
  approveNodeAsAdvisor,
  createFinalInvoiceAsAdvisor,
  createItineraryForClientAsAdvisor,
  findClientByEmail,
  getInvoiceAsAdvisor,
  issueInvoiceAsAdvisor,
  seedPricedItemAsAdvisor,
  setClientBillingAsAdvisor,
} from "../support/api";

// M005/I2 — a traveler pays an issued invoice end-to-end against the REAL
// Braintree sandbox, driven exactly as the traveler would:
//   - the advisor prices + bills a trip on the traveler's client and issues it,
//   - the traveler opens the pay page, sees the line-item breakdown (why it's
//     owed) and a billing form PRE-FILLED from their client record,
//   - they type the sandbox test card into Braintree Hosted Fields and pay,
//   - the charge settles at the sandbox: status flips to `paid` and the payment
//     (last-4, processor txn) is recorded.
//
// Gated on OVB_BRAINTREE_E2E because Hosted Fields need a real sandbox client
// token — with no creds the API falls back to the FakeGateway (whose token the
// Braintree JS won't accept), so this can't run in CI. Run locally with the
// sandbox creds in apps/api/.env:
//   OVB_BRAINTREE_E2E=1 pnpm -C apps/web test:e2e -- --project=traveler-flows pay-invoice
//
// Braintree's official sandbox test Visa — tokenizes to a real nonce and settles.
const TEST_CARD = "4111111111111111";
const TEST_EXPIRY = "1230"; // MM/YY, comfortably in the future
const TEST_CVV = "123";

/** Type into a Braintree Hosted Field (each is a cross-origin iframe with one
 *  input). `pressSequentially` respects the field's input masking; `fill` does not. */
async function typeHostedField(page: Page, fieldName: string, value: string): Promise<void> {
  const frame: FrameLocator = page.frameLocator(`iframe[name="braintree-hosted-field-${fieldName}"]`);
  // Each iframe also carries hidden browser-autofill helper inputs; the real
  // field is the one Braintree tags with data-braintree-name.
  const input = frame.locator(`input[data-braintree-name="${fieldName}"]`);
  await input.click();
  await input.pressSequentially(value, { delay: 20 });
}

test("TRV-PAY: a traveler pays an issued invoice via Braintree Hosted Fields", async ({
  page,
  baseURL,
}) => {
  test.skip(
    !process.env.OVB_BRAINTREE_E2E,
    "needs Braintree sandbox creds — set OVB_BRAINTREE_E2E=1 with keys in apps/api/.env",
  );
  test.setTimeout(120_000); // real Braintree network + Hosted Fields load

  // 1. Fresh traveler signs in (landing on basecamp backfills client ownership).
  const { email, callbackUrl } = await freshTravelerCallbackUrl(baseURL!);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  const client = await findClientByEmail(email);
  if (!client) throw new Error(`no linked client for ${email}`);

  // 2. Seed the traveler's billing identity — the pay form pre-fills from this.
  await setClientBillingAsAdvisor(client.id, {
    address: "1 Analytical Way",
    city: "London",
    region: "LDN",
    postal_code: "EC1A 1AA",
    country_code: "GB",
  });

  // 3. Advisor prices two nodes and bills them (native USD → no FX quote).
  const itineraryId = await createItineraryForClientAsAdvisor(client.id, {
    title: "Kyoto, billable",
    brief: "A couple of firm, priced evenings in Kyoto",
  });
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

  const invoiceId = await createFinalInvoiceAsAdvisor(itineraryId);
  await issueInvoiceAsAdvisor(invoiceId);

  // 4. Traveler opens the pay page.
  await page.goto(`/invoices/${invoiceId}`);
  await expect(page.getByTestId("pay-invoice")).toBeVisible();

  // Why they're paying: the breakdown lists both charges and the total.
  await expect(page.getByTestId("pay-breakdown")).toBeVisible();
  await expect(page.getByTestId("pay-line")).toHaveCount(2);
  await expect(page.getByTestId("pay-line").filter({ hasText: "Kaiseki dinner" })).toBeVisible();
  await expect(page.getByTestId("pay-total")).toContainText("1,250");
  await expect(page.getByTestId("pay-trip")).toContainText("Kyoto, billable");

  // The billing form is pre-filled from the client record.
  await expect(page.getByTestId("billing-name")).toHaveValue("E2E Linked Traveler");
  await expect(page.getByTestId("billing-address")).toHaveValue("1 Analytical Way");
  await expect(page.getByTestId("billing-city")).toHaveValue("London");
  await expect(page.getByTestId("billing-country")).toHaveValue("GB");

  // 5. Enter the sandbox card into the real Braintree Hosted Fields and pay.
  await expect(page.locator('iframe[name="braintree-hosted-field-number"]')).toBeVisible({
    timeout: 30_000,
  });
  await typeHostedField(page, "number", TEST_CARD);
  await typeHostedField(page, "expirationDate", TEST_EXPIRY);
  await typeHostedField(page, "cvv", TEST_CVV);

  const payButton = page.getByTestId("pay-submit");
  await expect(payButton).toBeEnabled();
  await payButton.click();

  // 6. The charge settles at the sandbox: the receipt appears with the card's last-4.
  await expect(page.getByTestId("pay-receipt")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("pay-receipt")).toContainText("····1111");

  // API backstop: the invoice really flipped to paid with a succeeded payment.
  await expect
    .poll(async () => (await getInvoiceAsAdvisor(invoiceId)).status, { timeout: 15_000 })
    .toBe("paid");
  const settled = await getInvoiceAsAdvisor(invoiceId);
  const succeeded = settled.payments.filter((p) => p.status === "succeeded");
  expect(succeeded).toHaveLength(1);
  expect(succeeded[0]?.last_four).toBe("1111");
});
