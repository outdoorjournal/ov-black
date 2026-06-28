import { defineConfig, devices } from "@playwright/test";

// One suite, two targets. Point it at a local dev server (the default) or a
// deployed environment by setting PLAYWRIGHT_BASE_URL:
//
//   pnpm -C apps/web test:e2e                          # local  (http://localhost:3000)
//   PLAYWRIGHT_BASE_URL=https://staging.example pnpm -C apps/web test:e2e
//
// The auth model is identical in both: we mint a single-use magic-link token
// against whichever Supabase project backs the target, then drive the real
// /auth/callback route to establish a cookie session (see e2e/support/auth.ts).
const baseURL = process.env["PLAYWRIGHT_BASE_URL"] ?? "http://localhost:3000";
const isLocal = /localhost|127\.0\.0\.1/.test(baseURL);
const isCI = !!process.env["CI"];

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  timeout: 60_000,
  reporter: isCI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    // Logs a member in once and writes the session to e2e/.auth/advisor.json.
    { name: "setup", testMatch: /auth\.setup\.ts$/ },

    // Unauthenticated surface — the sign-in / invite landing page.
    {
      name: "public",
      testDir: "./e2e/public",
      use: { ...devices["Desktop Chrome"] },
    },

    // Authenticated surface — reuses the session captured by `setup`.
    {
      name: "authenticated",
      testDir: "./e2e/authenticated",
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/advisor.json",
      },
    },
  ],
  // Locally, boot (or reuse) the Next dev server. Against a remote target we
  // assume the app is already deployed, so we start nothing.
  ...(isLocal
    ? {
        webServer: {
          command: "pnpm dev",
          url: baseURL,
          reuseExistingServer: true,
          timeout: 120_000,
        },
      }
    : {}),
});
