import { randomUUID } from "node:crypto";

import { type Page, expect, test } from "@playwright/test";

import { travelerCallbackUrlForEmail } from "../support/auth";
import { findClientByEmail } from "../support/api";

// ONB-1 / ONB-1A / ONB-1B — the advisor's onboarding surface, driven as a QA
// person would: fill the New Client form, watch the roster, nudge a pending
// invite. Runs under the `advisor` project (setup:advisor's captured session).
//
// Every test invents a UNIQUE invitee email (RFC 2606 example.com — passes the
// API's EmailStr, never delivers mail), so repeated runs never collide and the
// roster row we assert on is unambiguous. The invite IS the fixture: the client
// these tests need is the one the browser form creates.

function uniqueEmail(tag: string): string {
  return `e2e-onb-${tag}-${randomUUID()}@example.com`;
}

// Fill + submit the New Client form (assumes we're already on /new-client).
async function submitNewClient(
  page: Page,
  fullName: string,
  email: string,
): Promise<void> {
  await page.getByLabel("Full name").fill(fullName);
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Add client" }).click();
}

// The roster row for a given invitee, matched by their (desktop-visible) email.
function clientRow(page: Page, email: string) {
  return page.getByRole("row").filter({ hasText: email });
}

// ONB-1 — an advisor invites a brand-new email; the roster shows the invitee as
// Pending (welcome sent, not yet signed in). When that traveler then clicks
// their link and lands on basecamp, the same row flips to Active with a
// signed-in date. Browser drives both actions; the API seam confirms the state.
test("ONB-1: advisor invites a new user → Pending, then Active after first sign-in", async ({
  page,
  browser,
  baseURL,
}) => {
  const email = uniqueEmail("invite");

  // A QA person starts from the roster and clicks through to the form.
  await page.goto("/command-center/clients");
  await page.getByRole("link", { name: "New Client" }).click();
  await expect(page).toHaveURL(/\/command-center\/new-client/);

  await submitNewClient(page, "E2E New Invitee", email);

  // The form redirects back to the roster, where the fresh row reads Pending.
  await page.waitForURL(/\/command-center\/clients/);
  await expect(clientRow(page, email).getByText("Pending")).toBeVisible();

  // State backstop: pending, and never accepted.
  await expect
    .poll(async () => (await findClientByEmail(email))?.access_status)
    .toBe("pending");
  expect((await findClientByEmail(email))?.accepted_at ?? null).toBeNull();

  // The invitee clicks their (already-created) link in a separate session and
  // lands on basecamp — first sign-in is what marks them active.
  const travelerContext = await browser.newContext();
  const travelerPage = await travelerContext.newPage();
  const callbackUrl = await travelerCallbackUrlForEmail(
    baseURL ?? "http://localhost:3000",
    email,
  );
  await travelerPage.goto(callbackUrl);
  await travelerPage.waitForURL(/\/basecamp/, { timeout: 30_000 });
  await travelerContext.close();

  // State backstop: the sign-in flipped the client to active with an accepted_at.
  await expect
    .poll(async () => (await findClientByEmail(email))?.access_status)
    .toBe("active");
  expect((await findClientByEmail(email))?.accepted_at ?? null).not.toBeNull();

  // And the advisor, reloading the roster, now sees Active for that same row.
  await page.goto("/command-center/clients");
  await expect(clientRow(page, email).getByText("Active")).toBeVisible();
});

// ONB-1A — inviting an email that already has a client is refused with a plain
// "already exists" message rather than silently creating a duplicate. The first
// invite creates the account (the fixture); the second is the scenario.
test("ONB-1A: inviting an already-registered email tells the advisor it exists", async ({
  page,
}) => {
  const email = uniqueEmail("dup");

  await page.goto("/command-center/new-client");
  await submitNewClient(page, "E2E First Registration", email);
  await page.waitForURL(/\/command-center\/clients/);
  await expect(clientRow(page, email).getByText("Pending")).toBeVisible();

  // Same email again — the API 409 surfaces as an inline advisor message and we
  // stay on the form (no duplicate, no redirect).
  await page.goto("/command-center/new-client");
  await submitNewClient(page, "E2E Duplicate Attempt", email);

  await expect(
    page.getByText("A client with this email already exists."),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/command-center\/new-client/);
});

// ONB-1B — an advisor whose invitee never got the email can re-send the welcome
// link from the roster ("Nudge"), getting a confirmation it went back out. The
// out-of-band code/link recovery (advisor relays a link manually) is the
// SMTP-boundary gap tracked in the scenario doc — not covered here.
test("ONB-1B: advisor can re-send the welcome link to a pending invitee", async ({
  page,
}) => {
  const email = uniqueEmail("nudge");

  await page.goto("/command-center/new-client");
  await submitNewClient(page, "E2E Nudge Target", email);
  await page.waitForURL(/\/command-center\/clients/);

  const row = clientRow(page, email);
  await expect(row.getByText("Pending")).toBeVisible();

  // Nudge is offered only while pending; clicking it re-sends and confirms.
  await row.getByRole("button", { name: "Nudge" }).click();
  await expect(page.getByText("Welcome link re-sent.")).toBeVisible();
});
