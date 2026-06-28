import { expect, test } from "@playwright/test";

// Runs with the traveler session captured by traveler.setup.ts. Confirms the
// client session persists into /basecamp rather than bouncing to the public
// landing or a no-client error.
test("traveler reaches basecamp with an active session", async ({ page }) => {
  await page.goto("/basecamp");

  await expect(page).toHaveURL(/\/basecamp/);

  // The first-prompt composer proves an authenticated basecamp rendered for a
  // linked client — not the login page or a no-client 404.
  await expect(
    page.getByPlaceholder("Begin in your own words…"),
  ).toBeVisible();

  // The public sign-in CTA must be absent — its presence would mean the auth
  // gate bounced us back to /.
  await expect(
    page.getByRole("button", { name: "Send sign-in link" }),
  ).toHaveCount(0);
});
