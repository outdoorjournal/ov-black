// Inbound-campaign landing — /campaign/[slug].
//
// The CTA in a campaign article (e.g. a Mt Olympus piece on one of the Outside
// properties) links here with a known slug. The traveler is already signed in,
// so this is a one-click front door: a full-bleed hero in the campaign's mood,
// and a "Begin" button that seeds the behind-the-scenes shell itinerary and
// drops them into the immersive, campaign-aware intake. The heavy lifting is in
// the `startCampaign` server action; this page is presentation + the trigger.

import { notFound } from "next/navigation";

import { MOODS, type MoodId } from "@/lib/atmos/moods";

import { startCampaign } from "@/app/_actions/start-campaign";

export const dynamic = "force-dynamic";

// Display trim only (the real campaign config — spine, facts, mood — lives
// server-side in app.campaigns). Keep the slugs in sync with that registry.
const CAMPAIGN_DISPLAY: Record<
  string,
  { title: string; kicker: string; blurb: string; mood: MoodId; cta: string }
> = {
  olympus: {
    kicker: "The mountain of the gods",
    title: "Mount Olympus, by first light",
    blurb:
      "A guided ascent of the mythic peak — Litochoro to the Mytikas summit, with the Aegean at your back. We'll shape the details together.",
    mood: "olympus",
    cta: "Begin your ascent",
  },
};

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function CampaignLandingPage({ params }: PageProps) {
  const { id } = await params;
  const display = CAMPAIGN_DISPLAY[id];
  if (!display) notFound();

  const mood = MOODS[display.mood];
  const start = startCampaign.bind(null, id);

  return (
    <main
      className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-6 text-center"
      style={{ backgroundColor: mood.palette.bg, color: mood.palette.fg }}
    >
      {/* Full-bleed hero + legibility veil, matching the cinematic backdrop. */}
      <div
        aria-hidden
        className="absolute inset-0 bg-cover bg-center opacity-60"
        style={{ backgroundImage: `url(${mood.imageUrl})` }}
      />
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.35), rgba(0,0,0,0.15) 40%, rgba(0,0,0,0.65))",
        }}
      />

      <div className="relative z-10 flex max-w-2xl flex-col items-center gap-6">
        <p className="text-sm uppercase tracking-[0.3em] opacity-80">
          {display.kicker}
        </p>
        <h1 className="font-serif text-5xl leading-tight sm:text-6xl">
          {display.title}
        </h1>
        <p className="max-w-xl text-lg leading-relaxed opacity-90">
          {display.blurb}
        </p>
        <form action={start}>
          <button
            type="submit"
            className="mt-2 rounded-full px-8 py-3 text-base font-medium shadow-lg transition-transform hover:scale-[1.02]"
            style={{
              backgroundColor: mood.palette.accent,
              color: mood.palette.bg,
            }}
          >
            {display.cta}
          </button>
        </form>
      </div>
    </main>
  );
}
