import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test as setup } from "@playwright/test";

import { TRAVELER_STORAGE_STATE, travelerCallbackUrl } from "./support/auth";

// Establishes a traveler (client) session and saves the cookies for the
// `traveler` project. Like the advisor setup this drives the real
// /auth/callback, but a client only reaches /basecamp when their auth user is
// linked to a clients row — travelerCallbackUrl() provisions that link first.
setup("authenticate as traveler", async ({ page, baseURL }) => {
  const base = baseURL ?? "http://localhost:3000";

  const callbackUrl = await travelerCallbackUrl(base);
  await page.goto(callbackUrl);

  // A linked client redirects to /basecamp; an unlinked one bounces to
  // /?auth_error=no_client — so reaching /basecamp is the login + linkage check.
  await page.waitForURL(/\/basecamp/, { timeout: 30_000 });
  await expect(page.getByText("Outdoor Voyage").first()).toBeVisible();

  mkdirSync(path.dirname(TRAVELER_STORAGE_STATE), { recursive: true });
  await page.context().storageState({ path: TRAVELER_STORAGE_STATE });
});
