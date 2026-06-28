import { expect, test } from "@playwright/test";

// Runs with the advisor session captured by auth.setup.ts (the `authenticated`
// project injects storageState). Confirms the session actually persists into a
// protected route rather than redirecting back to the public landing page.
test("advisor reaches the Command Center with an active session", async ({
  page,
}) => {
  await page.goto("/command-center");

  await expect(page).toHaveURL(/\/command-center/);
  await expect(page.getByRole("heading", { name: "The atelier" })).toBeVisible();

  // The public sign-in CTA must be absent — its presence would mean we were
  // bounced back to / by the auth gate.
  await expect(
    page.getByRole("button", { name: "Send sign-in link" }),
  ).toHaveCount(0);
});
