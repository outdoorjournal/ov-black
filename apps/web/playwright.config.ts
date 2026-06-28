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
    // Each setup logs one persona in and saves its session under e2e/.auth/.
    // setup:traveler reuses the advisor (to create the linked client), so it
    // must run after setup:advisor — otherwise both mint magic links for the
    // same advisor user concurrently and invalidate each other's token.
    { name: "setup:advisor", testMatch: /advisor\.setup\.ts$/ },
    {
      name: "setup:traveler",
      testMatch: /traveler\.setup\.ts$/,
      dependencies: ["setup:advisor"],
    },

    // Unauthenticated surface — the sign-in / invite landing page.
    {
      name: "public",
      testDir: "./e2e/public",
      use: { ...devices["Desktop Chrome"] },
    },

    // Advisor surface — reuses the session captured by setup:advisor.
    {
      name: "advisor",
      testDir: "./e2e/advisor",
      dependencies: ["setup:advisor"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/advisor.json",
      },
    },

    // Traveler (client) surface — reuses the session captured by setup:traveler.
    {
      name: "traveler",
      testDir: "./e2e/traveler",
      dependencies: ["setup:traveler"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/traveler.json",
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
