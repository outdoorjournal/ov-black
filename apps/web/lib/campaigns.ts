// Web-side campaign display trim (intake copy). The authoritative campaign
// config — spine templates, facts, mood, the agent's private directive — lives
// server-side in `app.campaigns`. This holds only the cosmetic intake surface
// copy so the immersive first-run screen greets the traveler in the campaign's
// voice: the headline/eyebrow over the chat card and the assistant's seeded
// turn-0 opener. The agent is already campaign-aware via the server directive
// regardless of these lines.
//
// Keep the slugs in sync with `apps/api/app/campaigns/registry.py`.

// Where the campaign CTA stashes "come back to this campaign after sign-in"
// when the traveler isn't authenticated yet. The server action sets it; the
// auth callback consumes it (a same-origin path) and clears it, so an
// unauthenticated CTA click no longer drops the traveler on a bare /basecamp.
export const CAMPAIGN_INTENT_COOKIE = "ov_campaign_intent";

export type CampaignIntakeTrim = {
  /** Small uppercase kicker above the headline (replaces "A new adventure"). */
  eyebrow: string;
  /** The big serif line over the chat card (replaces "Where shall we take you?"). */
  headline: string;
  /** The assistant's first line, baked into turn 0 of the intake session. */
  opener: string;
};

export const CAMPAIGN_INTAKE: Record<string, CampaignIntakeTrim> = {
  olympus: {
    eyebrow: "Mount Olympus by First Light",
    headline: "Let’s shape the ascent.",
    opener:
      "Mount Olympus has been waiting for you. I've started shaping the ascent — " +
      "Litochoro, the refuge, the summit ridge. Before I build it out, two things: " +
      "when would you like to start this epic 14-day adventure, and who's coming with you?",
  },
};

/** The campaign's intake surface copy for a slug, or null if not a known campaign. */
export function campaignIntake(
  slug: string | null | undefined,
): CampaignIntakeTrim | null {
  if (!slug) return null;
  return CAMPAIGN_INTAKE[slug] ?? null;
}
