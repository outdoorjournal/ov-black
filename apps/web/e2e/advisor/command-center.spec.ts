import { randomUUID } from "node:crypto";
import { plusAddress } from "../support/auth";

import { expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  findAnySessionWithTurns,
} from "../support/api";

// Wave F — the Command Center as mission control. Runs with the advisor
// session captured by advisor.setup.ts (storageState). The five beats of the
// redesign: the Ops dashboard shell, roster URL-state search, the ⌘K palette,
// the client workspace sub-nav, and the read-only session replay.

function uniqueEmail(tag: string): string {
  return plusAddress(`e2e-ccf-${tag}-${randomUUID()}`);
}

test("advisor reaches Mission Control with an active session", async ({
  page,
}) => {
  await page.goto("/command-center");

  await expect(page).toHaveURL(/\/command-center/);
  await expect(
    page.getByRole("heading", { name: "Mission Control" }),
  ).toBeVisible();

  // The dashboard shell: attention queue + activity feed regions render.
  await expect(page.getByRole("region", { name: "Needs attention" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Activity" })).toBeVisible();

  // The public sign-in CTA must be absent — its presence would mean we were
  // bounced back to / by the auth gate.
  await expect(
    page.getByRole("button", { name: "Send sign-in link" }),
  ).toHaveCount(0);
});

test("clients roster search drives URL state and filters rows", async ({
  page,
}) => {
  // The searched-for row is our own fixture, so the assertion is unambiguous.
  const email = uniqueEmail("roster");
  await createClientAsAdvisor("E2E Roster Search", email);

  await page.goto("/command-center/clients");
  await page.getByPlaceholder("Search name or email…").fill(email);

  // The toolbar debounces into router.replace — the query lands in the URL
  // (shareable, refresh-safe) and the roster narrows to the match.
  await expect(page).toHaveURL(/\?(.*&)?q=/);
  await expect(page.getByRole("row").filter({ hasText: email })).toBeVisible();
});

test("⌘K palette searches and navigates to a client", async ({ page }) => {
  const email = uniqueEmail("palette");
  const fullName = `E2E Palette ${randomUUID().slice(0, 8)}`;
  const clientId = await createClientAsAdvisor(fullName, email);

  await page.goto("/command-center");

  // Open via the global hotkey (the masthead trigger is the pointer path).
  await page.keyboard.press("ControlOrMeta+k");
  const paletteInput = page.getByPlaceholder(
    "Search clients, trips, or jump anywhere…",
  );
  await expect(paletteInput).toBeVisible();

  // Async roster search (150ms debounce) surfaces the client group.
  await paletteInput.fill(fullName);
  const option = page.getByRole("option", { name: new RegExp(fullName) });
  await expect(option).toBeVisible();
  await option.click();

  await expect(page).toHaveURL(new RegExp(`/command-center/clients/${clientId}`));
  await expect(page.getByRole("heading", { name: fullName })).toBeVisible();
});

test("client workspace sub-nav anchors between sections", async ({ page }) => {
  const email = uniqueEmail("subnav");
  const clientId = await createClientAsAdvisor("E2E SubNav Client", email);

  await page.goto(`/command-center/clients/${clientId}`);

  const subNav = page.getByRole("navigation", { name: "Client sections" });
  await expect(subNav).toBeVisible();

  await subNav.getByRole("link", { name: "Facts" }).click();
  await expect(page).toHaveURL(new RegExp(`#facts$`));
  await expect(page.getByRole("heading", { name: "Facts" })).toBeVisible();
});

test("session replay renders the transcript with telemetry chips", async ({
  page,
}) => {
  // Replay is a read-only surface; borrow any conversation the local stack
  // already holds rather than driving a live agent turn here.
  const found = await findAnySessionWithTurns();
  test.skip(!found, "no session with turns on this stack — run a chat first");
  if (!found) return;

  await page.goto(
    `/command-center/clients/${found.clientId}/sessions/${found.sessionId}`,
  );

  // The telemetry strip and at least one transcript turn render.
  await expect(page.getByTestId("replay-telemetry")).toBeVisible();
  expect(await page.getByTestId("replay-turn").count()).toBeGreaterThan(0);

  // Read-only: the replay page has no composer.
  await expect(page.locator("textarea, input[type=text]")).toHaveCount(0);
});
