import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { createClientAsAdvisor, getItineraryAsAdvisor } from "../support/api";

// ADV-2 — the advisor stands up an itinerary shell for a client: pick the
// client, spin up a trip bound to them, then fill a free-text brief plus rough
// timing through the SAME first-run intake the traveler uses but under the
// ADVISOR audience (personas differ, surface does not). This is the
// advisor-project browser proof the headless pillars + traveler intake specs
// (ITB-1/1B) can't give: that an advisor drives the whole flow — creation AND
// intake — on a client's behalf.
//
// Fully browser-driven (G-ITIN-FOR-CLIENT closed): the command-center client
// page now carries a "New itinerary" action that creates a client-bound
// itinerary and drops the advisor into its intake, so the ONLY seed is the
// precondition an advisor genuinely starts from — a client they own. The client
// binding is created by the browser action under test, then confirmed back at
// the API seam.
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(): string {
  return `e2e-adv2-${randomUUID()}@example.com`;
}

// The intake heading is audience-aware: advisors see "What are we planning?"
// where the traveler sees "Where shall we take you?" — so its presence proves we
// are driving the intake AS an advisor, not merely reusing the traveler flow.
const ADVISOR_INTAKE_HEADING = "What are we planning?";

test("ADV-2: advisor stands up an itinerary shell (brief + rough window) for a client", async ({
  page,
}) => {
  // Precondition (API seam): a client the advisor owns. Everything else —
  // creating the itinerary and binding it to this client — is driven in the
  // browser, so the binding is the affordance under test, not seeded state.
  const clientId = await createClientAsAdvisor("E2E ADV-2 Client", uniqueEmail());

  const brief = "7 days in Italy, anniversary, slow and food-forward";

  // The advisor opens this client's command-center page; it lists their
  // itineraries (none yet) and carries the "New itinerary" affordance.
  await page.goto(`/command-center/clients/${clientId}`);
  await expect(
    page.getByRole("heading", { name: "Itineraries" }),
  ).toBeVisible();
  await expect(page.getByText("No itineraries yet.")).toBeVisible();

  // Spin up an itinerary FOR THIS CLIENT: the action creates a client-bound
  // shell and redirects the advisor into its first-run intake.
  await page.getByRole("button", { name: "New itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/);
  const itineraryId = page.url().match(/\/itinerary\/([0-9a-f-]{36})/)?.[1];
  if (!itineraryId) {
    throw new Error(`expected an itinerary URL, got ${page.url()}`);
  }

  // Because they're an advisor the intake wears the advisor heading, standing in
  // front of the still-empty shell (the dashboard is gated until the brief lands).
  await expect(
    page.getByRole("heading", { name: ADVISOR_INTAKE_HEADING }),
  ).toBeVisible();
  await expect(page.getByTestId("dashboard")).toHaveCount(0);

  // Save is inert until the brief is written — the shell needs its sentence.
  await expect(
    page.getByRole("button", { name: "Start building" }),
  ).toBeDisabled();

  await page.getByLabel("The trip, in a sentence").fill(brief);
  // Rough timing: a WINDOW (bounds + a target length), not committed dates.
  await page.getByRole("button", { name: "A rough window" }).click();
  await page.getByLabel("No earlier than").fill("2027-09-15");
  await page.getByLabel("No later than").fill("2027-09-30");
  await page.getByLabel("About how many nights").fill("7");

  await page.getByRole("button", { name: "Start building" }).click();

  // The intake gives way to the itinerary shell — the advisor lands on the trip
  // dashboard and the intake gate is gone.
  await expect(page.getByTestId("dashboard")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: ADVISOR_INTAKE_HEADING }),
  ).toHaveCount(0);

  // Reload: the brief is persisted first-class, so the gate stays gone and the
  // shell renders directly — the shell is real, not just in-memory form state.
  await page.goto(`/itinerary/${itineraryId}`);
  await expect(
    page.getByRole("heading", { name: ADVISOR_INTAKE_HEADING }),
  ).toHaveCount(0);
  await expect(page.getByTestId("dashboard")).toBeVisible();

  // State backstop: the brief landed as first-class data (not buried in the
  // title), timing is a machine-usable window (bounds + target nights), and the
  // itinerary the browser created stayed bound to the client it was started for.
  const it = await getItineraryAsAdvisor(itineraryId);
  expect(it.brief).toBe(brief);
  expect(it.timing_kind).toBe("window");
  expect(it.date_start).toBe("2027-09-15");
  expect(it.date_end).toBe("2027-09-30");
  expect(it.duration_nights).toBe(7);
  expect(it.client_id).toBe(clientId);
});
