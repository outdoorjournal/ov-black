import { expect, test } from "@playwright/test";

import { plusAddress } from "../support/auth";

// Unauthenticated landing page. Needs only the web server running; the
// submit-confirmation test additionally exercises the API's POST /auth/login.
test.describe("sign-in landing page", () => {
  test("renders the member email sign-in", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Sign in", exact: true }),
    ).toBeVisible();
    await expect(page.locator("#sign-in-email")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Send sign-in link" }),
    ).toBeVisible();

    // Email is the only front door now — no invite-code entry.
    await expect(
      page.getByRole("heading", { name: "Claim your invitation" }),
    ).toHaveCount(0);
  });

  test("submitting an email shows the inbox confirmation", async ({ page }) => {
    await page.goto("/");

    // A plus-addressed mailbox with no account: passes the API's email
    // validation and resolves to "no account" (→ 204), so no mail is sent and
    // the "sent"/"no account" responses are indistinguishable by design.
    await page.locator("#sign-in-email").fill(plusAddress("e2e-smoke"));

    // The submit button is gated on the controlled input's React state, so it
    // only enables once the page has hydrated and registered the value. Wait
    // for that rather than racing a cold dev-server compile.
    const submit = page.getByRole("button", { name: "Send sign-in link" });
    await expect(submit).toBeEnabled();
    await submit.click();

    // The API collapses "sent" and "no account" into one response, so the UI
    // always confirms — proving the form wired through to the backend.
    await expect(page.getByRole("status")).toContainText("Check your inbox");
  });
});
