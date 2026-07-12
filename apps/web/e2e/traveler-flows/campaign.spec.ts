import { type Page, expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import { withAgentTurnLock } from "../support/agentLock";
import { getGraphNodesAsAdvisor } from "../support/api";

// CMP-1 — the inbound Olympus campaign, driven end-to-end as a traveler would:
// article CTA → /campaign/olympus landing → "Begin your ascent" → campaign-aware
// intake → the dashboard auto-kickoff that BUILDS the spine on screen. This is a
// live-agent flow (apps/agent on :8080), so it's held under the shared agent lock
// and given real room to stream. It guards two regressions we hit by hand:
//
//   #1 The agent must NOT leak its internal planning — tool names, self-talk,
//      tool failures — into the traveler-visible chat. With extended thinking on
//      (agent config `thinking_budget_tokens`) that reasoning lives in a hidden
//      channel; here we assert none of it reaches the conversation transcript.
//
//   #2 The dashboard day-grid must reflect the spine the kickoff builds WITHOUT a
//      manual reload. The cards land in the client store, but the dated day
//      scaffold is a server prop — ConciergeChat.onDone now runs router.refresh()
//      after the reveal burst so the scaffold re-derives from the fresh graph.
//      The test NEVER calls page.reload() before asserting the cards, so a green
//      run proves the soft refresh wired the spine onto the journal.
//
// Wording is non-deterministic, so we assert structurally: the intake hands off
// to the dashboard, the transcript is free of machine tokens, and the built spine
// is both visible in the journal and present at the API seam.

// Snake_case tool identifiers + planning tells that must never surface to the
// traveler. These are the exact leaks the bug produced; a match means the model's
// scratchpad reached the reply again.
const LEAK_TOKENS = [
  "add_trip_traveler",
  "remove_trip_traveler",
  "record_party_member",
  "update_party_member",
  "complete_intake",
  "update_trip_timing",
  "update_trip_details",
  "assemble_campaign_spine",
  "record_profile_fact",
  "record_dossier_inference",
  "save_link_to_collection",
  "set_mood",
  "add_transfer",
  "propose_flight",
  // Planning self-talk seen leaking alongside the tool names.
  "the timing window call failed",
  "independent operations",
];

// Assert the whole visible conversation transcript is free of machine tokens.
async function expectNoAgentLeak(page: Page): Promise<void> {
  const transcript = (
    await page.getByTestId("conversation-panel").innerText()
  ).toLowerCase();
  for (const token of LEAK_TOKENS) {
    expect(
      transcript.includes(token.toLowerCase()),
      `traveler-visible transcript leaked "${token}"`,
    ).toBe(false);
  }
}

test("CMP-1: the Olympus campaign builds its spine live, without leaking agent internals", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(300_000);

  // A throwaway traveler, so the campaign seed + kickoff run against clean state.
  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL!);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  // The campaign article CTA lands here; "Begin your ascent" seeds the shell
  // itinerary and drops the traveler into the campaign-aware intake.
  await page.goto(`${baseURL}/campaign/olympus`);
  await page.getByRole("button", { name: "Begin your ascent" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}\/new\?campaign=olympus/, {
    timeout: 30_000,
  });

  // The opener greets in the campaign's voice (proves the intake is campaign-aware).
  await expect(page.getByText(/Mount Olympus has been waiting for you/)).toBeVisible();

  const composer = page.getByPlaceholder("Tell Artemis what you're dreaming of…");
  await expect(composer).toBeVisible();

  // One comprehensive answer so intake can complete in a single turn: days, party,
  // an anchoring window, and the go-ahead. The whole live stretch — the intake
  // turn AND the dashboard's auto-kickoff — runs under the shared agent lock so it
  // never contends with another live turn on the single local agent.
  await withAgentTurnLock(async () => {
    await composer.fill(
      "Seven days, first week of September 2026. I'll climb solo while my wife " +
        "Anna and our kids relax by the coast. Go ahead and build it out.",
    );
    await page.getByRole("button", { name: "Send" }).click();

    // Intake may resolve in one turn or ask one clarifying question. Either way,
    // completing it hands off to the dashboard; nudge once if it's still on the
    // intake after the first reply settles.
    const landed = await page
      .waitForURL(/\/itinerary\/[0-9a-f-]{36}\/dashboard/, { timeout: 150_000 })
      .then(() => true)
      .catch(() => false);
    if (!landed) {
      await expect(composer).toBeEnabled({ timeout: 150_000 });
      await composer.fill("That's everything — please build it out now.");
      await page.getByRole("button", { name: "Send" }).click();
      await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}\/dashboard/, {
        timeout: 150_000,
      });
    }

    // On the dashboard the kickoff builds the spine. The journal renders each
    // scheduled card as an <article>; wait for the burst to land (NO reload) — a
    // populated grid is the #2 fix. Litochoro anchors nearly every leg of the
    // Olympus spine, so it's a wording-stable signal the cards are on the board.
    await expect(page.locator("main article").first()).toBeVisible({
      timeout: 150_000,
    });
    await expect(
      page.getByText(/Litochoro/).first(),
    ).toBeVisible({ timeout: 150_000 });
  });

  // #1 — nothing machine-facing reached the traveler across the whole transcript.
  await expectNoAgentLeak(page);

  // #2 backstop at the API seam: the spine really was built on this fork (the
  // dashboard URL carries the traveler's working fork id).
  const forkId = page.url().split("/itinerary/")[1]!.split("/")[0]!;
  const nodes = await getGraphNodesAsAdvisor(forkId);
  expect(nodes.length).toBeGreaterThan(5);
});
