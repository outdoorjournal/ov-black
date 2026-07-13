// Shared traveler → builder entry, for the traveler-flows specs that only need
// to *reach* the itinerary builder (Collection, card detail, empty-state,
// write-gate) before driving the surface under test.
//
// The self-serve front door was redesigned (feat/traveler-journal):
//
//   - Basecamp is onboarding-first. A brand-new traveler lands on the seeded
//     first-prompt opener, NOT the atelier — the "Start a new itinerary" CTA
//     only appears once they're a returning, onboarded traveler
//     (has_prior_session + onboarding_complete). We reproduce that precondition
//     by seeding two profile facts (the evaluate_onboarding bar) and dismissing
//     the opener, then click the real CTA.
//   - The first-run intake is now a conversation with Artemis, not a form. The
//     structured brief + timing controls moved into the builder's DashboardHero
//     (hero-brief / hero-timing popover). So we skip the conversation ("Skip for
//     now ›") into the dashboard and set brief/timing there when a spec needs
//     them — deterministic, no live agent.
//
// Fork-first (D030): a traveler's self-serve build runs on THEIR fork, so the
// dashboard URL we land on carries the fork id. That is the traveler's working
// copy — advisor seeds against it are visible to the traveler — so we return it
// as the itinerary id these specs seed and assert against.

import { type Page, expect } from "@playwright/test";

import { freshTravelerCallbackUrl } from "./auth";
import { findClientByEmail, seedProfileFactsAsAdvisor } from "./api";

const INTAKE_HEADING = "Where shall we take you?"; // conversational intake headline

export type TimingSeed = {
  kind: "exact" | "window" | "flexible";
  dateStart?: string; // YYYY-MM-DD
  dateEnd?: string; // YYYY-MM-DD
  nights?: number; // window mode only
};

/**
 * Provision a fresh, *onboarded* traveler, authenticate them, and walk the real
 * self-serve flow up to the immersive Artemis intake: dismiss the onboarding
 * opener, then click "Start a new itinerary". Leaves the page ON the intake
 * ("Where shall we take you?"). Returns the trunk itinerary id (from the /new
 * URL) and the traveler's linked client.
 */
export async function reachFreshIntake(
  page: Page,
  baseURL: string,
): Promise<{ id: string; clientId: string; email: string }> {
  const { email, callbackUrl } = await freshTravelerCallbackUrl(baseURL);
  const client = await findClientByEmail(email);
  if (!client) throw new Error(`no linked client for fresh traveler ${email}`);
  // Two profile facts satisfy evaluate_onboarding, so dismissing the opener
  // reveals the atelier empty-state (with its CTA) rather than the "finish your
  // introduction" reminder.
  await seedProfileFactsAsAdvisor(client.id, 2);

  await page.goto(callbackUrl);
  await expect(page).toHaveURL(/\/basecamp/);

  // Onboarding-first: dismiss the seeded opener; the atelier + CTA render in
  // its place (onboarding already satisfied above).
  await page.getByRole("button", { name: "Not now" }).click();
  await page.getByRole("button", { name: "Start a new itinerary" }).click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}\/new/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: INTAKE_HEADING })).toBeVisible();
  const id = page.url().split("/itinerary/")[1]!.split("/")[0]!;

  return { id, clientId: client.id, email };
}

/**
 * Provision a fresh, *onboarded* traveler and walk the real self-serve flow into
 * their trip dashboard: reach the Artemis intake, then skip it. Optionally set
 * the brief + timing on the DashboardHero. Returns the working-copy (fork)
 * itinerary id and the traveler's linked client.
 */
export async function enterFreshBuilder(
  page: Page,
  baseURL: string,
  opts: { brief?: string; timing?: TimingSeed } = {},
): Promise<{ id: string; clientId: string; email: string }> {
  const { clientId, email } = await reachFreshIntake(page, baseURL);

  // Skip the immersive intake into the dashboard (Desktop Chrome ≥ lg, so the
  // desktop "Skip for now ›" shows).
  await page.getByTestId("intake-open-journal").click();
  await page.waitForURL(/\/itinerary\/[0-9a-f-]{36}\/dashboard/, { timeout: 30_000 });
  const id = page.url().split("/itinerary/")[1]!.split("/")[0]!;

  if (opts.brief !== undefined) await setHeroBrief(page, opts.brief);
  if (opts.timing !== undefined) await setHeroTiming(page, opts.timing);

  return { id, clientId, email };
}

/** Set the trip brief via the DashboardHero inline editor (blur commits). */
export async function setHeroBrief(page: Page, brief: string): Promise<void> {
  await page.getByTestId("hero-brief").click();
  const input = page.getByTestId("hero-brief-input");
  await input.fill(brief);
  await input.blur();
}

/** Set the trip timing via the DashboardHero popover (TimingFields + Save). */
export async function setHeroTiming(page: Page, timing: TimingSeed): Promise<void> {
  await page.getByTestId("hero-timing").click();
  await expect(page.getByTestId("hero-timing-popover")).toBeVisible();
  await page.getByTestId(`timing-mode-${timing.kind}`).click();
  if (timing.kind !== "flexible") {
    if (timing.dateStart) await page.getByTestId("timing-date-start").fill(timing.dateStart);
    if (timing.dateEnd) await page.getByTestId("timing-date-end").fill(timing.dateEnd);
    if (timing.kind === "window" && timing.nights != null) {
      await page.getByTestId("timing-nights").fill(String(timing.nights));
    }
  }
  await page.getByTestId("hero-timing-save").click();
  await expect(page.getByTestId("hero-timing-popover")).toHaveCount(0);
}
