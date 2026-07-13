import { randomUUID } from "node:crypto";
import { plusAddress } from "../support/auth";

import { expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
  createPartyMemberAsAdvisor,
  getClientPartyAsAdvisor,
  getItineraryPartyAsAdvisor,
} from "../support/api";

// ADV-2B — the advisor builds the travel party. Two browser-drivable facets, one
// per test:
//   1. ADD a durable household member (client-detail page) — stamped
//      `created_by_actor = advisor`, the "add new" half + the authorship bit the
//      traveler-side ONB-3 spec can't show.
//   2. ATTACH a remembered member to a SPECIFIC trip (the itinerary dashboard's
//      "Add from household" → "On this trip") — the scenario's core, "select an
//      existing member → the trip roster updates."
//
// Left to the API seam by design (not a browser gap): adding a member by TELLING
// the concierge — the agent `record_party_member` tool is Bedrock-gated
// (semantic), asserted against a real agent, not here. See doc/qa/advisor-plan.md.
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(tag: string): string {
  return plusAddress(`e2e-adv2b-${tag}-${randomUUID()}`);
}

test.describe("ADV-2B: advisor builds the travel party", () => {
  test("adds a durable party member (stamped advisor) to a client", async ({
    page,
  }) => {
    const clientId = await createClientAsAdvisor(
      "E2E ADV-2B Client",
      uniqueEmail("add"),
    );
    const memberName = `E2E Companion ${randomUUID().slice(0, 8)}`;
    const dietary = "Vegetarian, no shellfish";

    await page.goto(`/command-center/clients/${clientId}`);
    await expect(
      page.getByRole("heading", { name: "Travel party" }),
    ).toBeVisible();

    // Open the inline add form (the toggle button unmounts, so the form's own
    // "Add traveler" submit is the only one present once we're filling it in).
    await page.getByRole("button", { name: "Add traveler" }).click();
    await page.getByLabel("Full name").fill(memberName);
    await page.getByLabel("Dietary").fill(dietary);
    await page.getByRole("button", { name: "Add traveler" }).click();

    // The roster carries the member, their dietary summary, and — the net-new
    // assertion over ONB-3 — the "via advisor" provenance stamp.
    const row = page.getByRole("listitem").filter({ hasText: memberName });
    await expect(row).toBeVisible();
    await expect(row.getByText(dietary)).toBeVisible();
    await expect(row.getByText("via advisor")).toBeVisible();

    // State backstop: one durable member resolves for the client, authored by
    // the advisor and carrying the stated constraint.
    const party = await getClientPartyAsAdvisor(clientId);
    const created = party.find((m) => m.full_name === memberName);
    expect(created).toBeTruthy();
    expect(created?.created_by_actor).toBe("advisor");
    expect(created?.dietary).toBe(dietary);
  });

  test("attaches a remembered member to a trip → the trip roster updates", async ({
    page,
  }) => {
    // Precondition (API seam): a client with a durable member, and an itinerary
    // (with a brief, so the dashboard renders) bound to that client.
    const clientId = await createClientAsAdvisor(
      "E2E ADV-2B Trip Client",
      uniqueEmail("attach"),
    );
    const memberName = `E2E Traveler ${randomUUID().slice(0, 8)}`;
    await createPartyMemberAsAdvisor(clientId, { fullName: memberName });
    const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
      title: "Family week",
      brief: "A relaxed week with the whole family",
    });

    // The trip-party panel is its own rail route now ("Party").
    await page.goto(`/itinerary/${itineraryId}/party`);
    await expect(
      page.getByRole("heading", { name: "On this trip" }).first(),
    ).toBeVisible();

    // The member is in the household but not yet on this trip — attach it.
    // (.first() guards the dashboard's responsive desktop/mobile copies.)
    const householdRow = page
      .getByRole("listitem")
      .filter({ hasText: memberName })
      .first();
    await householdRow.getByRole("button", { name: "Attach" }).click();

    // It moves onto the trip: the same member now carries a "Remove" affordance,
    // which only the "On this trip" rows have.
    await expect(
      page
        .getByRole("listitem")
        .filter({ hasText: memberName })
        .filter({ has: page.getByRole("button", { name: "Remove" }) })
        .first(),
    ).toBeVisible();

    // State backstop: the itinerary's party roster now lists the member.
    const party = await getItineraryPartyAsAdvisor(itineraryId);
    expect(party.some((e) => e.member?.full_name === memberName)).toBe(true);
  });
});
