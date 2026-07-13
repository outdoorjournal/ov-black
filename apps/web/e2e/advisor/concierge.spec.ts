import { randomUUID } from "node:crypto";
import { plusAddress } from "../support/auth";

import { expect, test } from "@playwright/test";

import {
  createClientAsAdvisor,
  createItineraryForClientAsAdvisor,
} from "../support/api";
import { withAgentTurnLock } from "../support/agentLock";

// ADV-3 — the advisor drives a build turn from their PRIVATE concierge aside.
// The build data-spine (search → propose → graph integrity → cost) is proven
// headless by Pillar 3 + the full loop; what only the browser can show is the
// turn LOOP in the advisor's private workspace: the composer takes a message,
// the reply streams, the composer re-enables, no error row — asserted
// STRUCTURALLY (never on wording), so it holds against the mock or a real
// tool-using agent. The advisor's private aside (audience="advisor") is the
// distinguishing surface: it's the concierge tab the traveler never sees.
//
// Live agent: like the traveler chat.spec turns, this drives a REAL turn against
// the local agent (apps/agent on :8080). That single local process handles one
// turn at a time, so the turn is wrapped in `withAgentTurnLock` — a cross-process
// file mutex every live-agent spec shares — which serialises it with the traveler
// chat turns no matter how Playwright schedules the projects. This is a LOCAL
// test-infra concern only: prod runs on managed AgentCore, which fields concurrent
// sessions by design. (`scripts/restart-agent.sh` gives a clean agent first; the
// API seam / Bedrock own the agent's *semantic* output.) If the agent is
// unreachable the turn falls back to the D015 error row, which this test asserts.
//
// Runs under the `advisor` project (setup:advisor's captured session).

function uniqueEmail(): string {
  return plusAddress(`e2e-adv3-${randomUUID()}`);
}

test("ADV-3: advisor drives a concierge build turn from the private aside", async ({
  page,
}) => {
  test.setTimeout(180_000);

  // Precondition (API seam): a client + an itinerary that already carries a
  // brief, so we land straight in the builder (past the intake gate) with the
  // concierge present. Binding to a client is what lets the concierge open a
  // session at all (it keys sessions by client + audience).
  const clientId = await createClientAsAdvisor("E2E ADV-3 Client", uniqueEmail());
  const itineraryId = await createItineraryForClientAsAdvisor(clientId, {
    title: "Florence, food-led",
    brief: "Three days around Florence, food-led, slow mornings",
  });

  await page.goto(`/itinerary/${itineraryId}`);

  // The concierge is an in-flow column at desktop width; for an advisor its
  // Artemis channel IS the private "Concierge" workspace (no audience tabs — the
  // client-facing conversation lives on the human "Client" circle). Prove it's
  // the private aside via the intro copy the traveler never sees.
  await expect(
    page.getByText(/Private workspace — just you and the concierge/).first(),
  ).toBeVisible();

  // Drive a build turn from the private composer. The turn itself is wrapped in
  // the shared agent lock so it never contends with a traveler chat turn on the
  // single local agent (see support/agentLock.ts).
  const composer = page.locator(
    'textarea[placeholder="Ask me to propose, assemble, or swap…"]:visible',
  );
  await expect(composer).toBeVisible();
  const message = "Give us three days around Florence, food-led.";
  const send = page.locator("button:visible", { hasText: "Send" });

  await withAgentTurnLock(async () => {
    // The concierge re-disables the composer in bursts while it opens a session,
    // so a fill or click can be dropped — retry the whole submit (fill + Send)
    // until the composer clears, which only happens once a turn actually fired.
    await expect(async () => {
      await composer.fill(message);
      await expect(composer).toHaveValue(message);
      await send.click({ timeout: 4000 });
      await expect(composer).toHaveValue("");
    }).toPass({ timeout: 40_000 });

    // The private thread shows what we sent.
    await expect(page.getByText(message).first()).toBeVisible();

    // The turn runs end-to-end: the composer re-enables once the reply has
    // streamed in.
    await expect(composer).toBeEnabled({ timeout: 150_000 });
  });

  // It must have reached the concierge — not the local "couldn't reach"
  // fallback, and no D015 error row.
  await expect(page.getByText(/Couldn.t reach the concierge/)).toHaveCount(0);
  await expect(page.locator('[data-role="error"]')).toHaveCount(0);
});
