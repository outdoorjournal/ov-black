import { randomUUID } from "node:crypto";
import { plusAddress } from "../support/auth";

import { expect, test } from "@playwright/test";

import { createClientAsAdvisor, getItineraryAsAdvisor } from "../support/api";
import { setHeroBrief, setHeroTiming } from "../support/builder";

// ADV-2 — the advisor stands up an itinerary shell for a client: spin up a trip
// bound to them from the command center, then give it a free-text brief plus
// rough timing. The immersive first-run conversation is the traveler's front
// door only — advisors are dropped straight onto the trip dashboard, where the
// structured brief + timing live on the hero (the same controls the traveler
// gets). This is the advisor-project browser proof that an advisor drives the
// whole flow — creation AND briefing — on a client's behalf.
//
// Fully browser-driven (G-ITIN-FOR-CLIENT closed): the command-center client
// page carries a "New itinerary" action that creates a client-bound itinerary
// and drops the advisor into it, so the ONLY seed is the precondition an advisor
// genuinely starts from — a client they own. The binding is confirmed at the
// API seam.
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(): string {
  return plusAddress(`e2e-adv2-${randomUUID()}`);
}

test("ADV-2: advisor stands up an itinerary shell (brief + rough window) for a client", async ({
  page,
}) => {
  // Precondition (API seam): a client the advisor owns. Everything else —
  // creating the itinerary and binding it to this client — is driven in the
  // browser, so the binding is the affordance under test, not seeded state.
  const clientId = await createClientAsAdvisor("E2E ADV-2 Client", uniqueEmail());

  const brief = "7 days in Italy, anniversary, slow and food-forward";

  // The advisor opens this client's command-center page; its Trips section
  // lists their itineraries (none yet) and carries the "New itinerary"
  // affordance.
  await page.goto(`/command-center/clients/${clientId}`);
  await expect(page.getByRole("heading", { name: "Trips" })).toBeVisible();
  await expect(page.getByText("No trips yet.")).toBeVisible();

  // Spin up an itinerary FOR THIS CLIENT: the action creates a client-bound
  // shell and drops the advisor onto its dashboard (no immersive intake).
  await page.getByRole("button", { name: "New itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}/);
  const itineraryId = page.url().match(/\/itinerary\/([0-9a-f-]{36})/)?.[1];
  if (!itineraryId) {
    throw new Error(`expected an itinerary URL, got ${page.url()}`);
  }
  await expect(page.getByTestId("dashboard")).toBeVisible();

  // Give the shell its brief + a rough WINDOW (bounds + a target length, not
  // committed dates) on the hero.
  await setHeroBrief(page, brief);
  await setHeroTiming(page, {
    kind: "window",
    dateStart: "2027-09-15",
    dateEnd: "2027-09-30",
    nights: 7,
  });

  // Reload: the brief is persisted first-class, so the hero renders it directly
  // — the shell is real, not just in-memory form state.
  await page.goto(`/itinerary/${itineraryId}/dashboard`);
  await expect(page.getByTestId("dashboard")).toBeVisible();
  await expect(page.getByTestId("hero-brief")).toContainText(brief);

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
