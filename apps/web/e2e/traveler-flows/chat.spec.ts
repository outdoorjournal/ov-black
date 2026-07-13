import { expect, test } from "@playwright/test";

import { freshTravelerCallbackUrl } from "../support/auth";
import { enterFreshBuilder } from "../support/builder";
import { withAgentTurnLock } from "../support/agentLock";

// Live concierge chat, driven in the browser. Both surfaces that let a traveler
// talk to the agent — the basecamp onboarding opener (ONB-2) and the itinerary
// builder's concierge (ITB-4) — take a real turn here against the local agent
// backend (apps/agent on :8080). We assert the turn LOOP structurally (the
// composer re-enables once the reply has streamed, no error row) rather than on
// wording, so it holds against the mock or a real tool-using agent. What's
// genuinely non-deterministic — grounded-not-generic replies, profile facts
// recorded — is the semantic bit verified at the API seam by the pillar suite.
//
// Both live turns share ONE local agent. Within this file the traveler-flows
// project (fullyParallel:false) already runs them serially; the turns are also
// wrapped in `withAgentTurnLock` (support/agentLock.ts) so they never contend
// with the advisor concierge turn either — a cross-process file mutex serialises
// every live turn regardless of which Playwright project/worker runs it. This is
// a LOCAL single-process concern only; prod's managed AgentCore fields concurrent
// sessions by design.

// ONB-2 — a never-onboarded traveler converses with the concierge from the
// opener: types a self-disclosure, sends it, and a reply streams back.
test("ONB-2: a traveler converses with the concierge from the opener", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(180_000);

  const { callbackUrl } = await freshTravelerCallbackUrl(baseURL!);
  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  const opener = page.getByPlaceholder("Begin in your own words…");
  await expect(opener).toBeVisible();
  await opener.fill(
    "I love slow mornings, good coffee, and quiet coastal villages.",
  );

  // The shared ConversationPanel keeps its input enabled throughout (so it never
  // loses focus); the robust "a reply came back" signal is the streaming bubble
  // clearing (counting turns is fragile: the seeded opener and the agent's echoed
  // first line can dedupe to one). Real turns take time — give them room. The turn
  // is held under the shared agent lock so it never contends with another live turn.
  await withAgentTurnLock(async () => {
    await opener.press("Enter");

    // The conversation view takes over and records the user's turn verbatim.
    await expect(page.getByTestId("conversation-panel")).toBeVisible();
    await expect(
      page
        .locator('[data-role="user"]', { hasText: "quiet coastal villages" })
        .first(),
    ).toBeVisible();

    // The streaming bubble carries data-streaming="true" until the turn settles.
    await expect(page.locator('[data-streaming="true"]')).toHaveCount(0, {
      timeout: 150_000,
    });
  });

  // The turn must not have fallen back to the D015 error row.
  await expect(page.locator('[data-role="error"]')).toHaveCount(0);
});

// ITB-4 — from an empty builder, the traveler reaches the concierge and it
// takes a turn. The live half of ITB-4 (the empty-state guidance is asserted in
// empty-state.spec); the *grounded* quality of the reply is the API-seam bit.
test("ITB-4: the concierge takes a turn from an empty builder", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(180_000);

  const { id } = await enterFreshBuilder(page, baseURL!, {
    brief: "A quiet week somewhere coastal",
    timing: { kind: "flexible" },
  });
  await page.goto(`/itinerary/${id}/timeline`);
  await expect(
    page.getByRole("heading", { name: "A blank canvas, ready when you are" }),
  ).toBeVisible();

  // The concierge composer sits in the builder aside — an auto-growing textarea.
  // The builder mounts a desktop and a mobile layout (one hidden by responsive
  // CSS), so scope to the visible copy.
  const composer = page.locator(
    'textarea[placeholder="Ask me to propose, assemble, or swap…"]:visible',
  );
  await expect(composer).toBeVisible();
  const message = "Can you suggest a boutique hotel to start?";
  const send = page.locator("button:visible", { hasText: "Send" });

  // The turn runs under the shared agent lock so it never contends with another
  // live turn on the single local agent.
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

    // The thread shows what we sent.
    await expect(page.getByText(message).first()).toBeVisible();

    // The composer re-enables once the reply has streamed in.
    await expect(composer).toBeEnabled({ timeout: 150_000 });
  });

  // It must have reached the concierge (not the local "couldn't reach" fallback).
  await expect(page.getByText(/Couldn.t reach the concierge/)).toHaveCount(0);
});
