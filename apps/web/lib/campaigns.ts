// Web-side campaign display trim (openers). The authoritative campaign config —
// spine templates, facts, mood, the agent's private directive — lives server-side
// in `app.campaigns`. This holds only the cosmetic intake opener so the immersive
// first-run conversation greets the traveler in the campaign's voice. The agent
// is already campaign-aware via the server directive regardless of this line.
//
// Keep the slugs in sync with `apps/api/app/campaigns/registry.py`.

export const CAMPAIGN_OPENERS: Record<string, string> = {
  olympus:
    "Mount Olympus has been waiting for you. I've started shaping the ascent — " +
    "Litochoro, the refuge, the summit ridge. Before I build it out, two things: " +
    "how many days do you have for the mountain, and who's coming with you?",
};

/** The campaign opener for a slug, or null if not a known campaign. */
export function campaignOpener(slug: string | null | undefined): string | null {
  if (!slug) return null;
  return CAMPAIGN_OPENERS[slug] ?? null;
}
