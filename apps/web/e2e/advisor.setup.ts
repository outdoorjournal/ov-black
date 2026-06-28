import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test as setup } from "@playwright/test";

import { ADVISOR_STORAGE_STATE, advisorCallbackUrl } from "./support/auth";

// Establishes an advisor session once, up front, and saves the cookies so the
// `authenticated` project can reuse them. This *is* the login flow: we visit
// the real /auth/callback route, which runs verifyOtp server-side and sets the
// Supabase session cookies — identical to a user clicking their email link.
setup("authenticate as advisor", async ({ page, baseURL }) => {
  const base = baseURL ?? "http://localhost:3000";

  const callbackUrl = await advisorCallbackUrl(base);
  await page.goto(callbackUrl);

  // Advisors are redirected to /command-center on success. A failed verify
  // would bounce to /?auth_error=… instead, so this assertion is the login
  // check. (The atelier heading is rendered even if downstream API reads fail.)
  await page.waitForURL(/\/command-center/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "The atelier" })).toBeVisible();

  mkdirSync(path.dirname(ADVISOR_STORAGE_STATE), { recursive: true });
  await page.context().storageState({ path: ADVISOR_STORAGE_STATE });
});
