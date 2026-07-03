import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { ADVISOR_STORAGE_STATE, freshTravelerCallbackUrl } from "../support/auth";
import { findClientByEmail } from "../support/api";

// ONB-3 — a traveler maintains their own preferences and the advisor sees the
// change. The traveler-facing surface that exists today is the travel-party
// roster (/basecamp/party): a traveler adds a companion with a dietary need, and
// that same record shows up on the advisor's client-detail page. Browser drives
// both sides; the API lookup only resolves the client id for the advisor's URL.
//
// (A general "edit my travel style / constraints" profile editor does not exist
// yet — that slice of ONB-3 stays aspirational; see doc/qa/onboarding.md.)
test("ONB-3: a traveler's party edit is visible to their advisor", async ({
  page,
  browser,
  baseURL,
}) => {
  const { email, callbackUrl } = await freshTravelerCallbackUrl(baseURL!);
  const memberName = `E2E Companion ${randomUUID().slice(0, 8)}`;
  const dietary = "Severe shellfish allergy";

  // Traveler self-serves their household from basecamp.
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);
  await page.goto("/basecamp/party");
  await expect(
    page.getByRole("heading", { name: "Your travel party" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Add a traveler" }).click();
  await page.getByLabel("Full name").fill(memberName);
  await page.getByLabel("Dietary").fill(dietary);
  await page.getByRole("button", { name: "Add traveler" }).click();

  // The roster now shows the member and their dietary summary.
  await expect(page.getByText(memberName)).toBeVisible();
  await expect(page.getByText(dietary)).toBeVisible();

  // The advisor, in their own session, sees the same member on the client's
  // detail page — the "traveler self-edits, advisor sees it" invariant.
  const client = await findClientByEmail(email);
  expect(client?.id).toBeTruthy();

  const advisorCtx = await browser.newContext({
    storageState: ADVISOR_STORAGE_STATE,
  });
  const advisorPage = await advisorCtx.newPage();
  await advisorPage.goto(`/command-center/clients/${client!.id}`);
  await expect(advisorPage.getByText(memberName)).toBeVisible();
  await advisorCtx.close();
});
