// The "all your itineraries" surface for /basecamp variant (d).
//
// Cormorant-titled cards on cream tiles, each linking to the existing
// /itinerary/{id} detail view. No "new itinerary" affordance — advisors
// create itineraries; clients read them and converse with the agent
// alongside.

import Link from "next/link";

import type { MyItinerarySummary } from "@ov-black/api-client";

export type ItineraryGridProps = {
  itineraries: MyItinerarySummary[];
};

export function ItineraryGrid({ itineraries }: ItineraryGridProps) {
  return (
    <section className="flex min-h-[60vh] flex-col gap-8">
      <header className="flex flex-col gap-2">
        <p className="text-[10px] uppercase tracking-[0.4em] text-paper/55">
          Your atelier
        </p>
        <h2 className="font-serif text-4xl leading-[1.1] tracking-tight text-paper sm:text-5xl">
          Your itineraries
        </h2>
      </header>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {itineraries.map((it) => (
          <ItineraryCard key={it.id} itinerary={it} />
        ))}
      </div>
    </section>
  );
}

function ItineraryCard({ itinerary }: { itinerary: MyItinerarySummary }) {
  const date = new Date(itinerary.updated_at);
  const dateLabel = Number.isNaN(date.getTime())
    ? null
    : date.toLocaleDateString(undefined, {
        month: "long",
        day: "numeric",
        year: "numeric",
      });
  return (
    <Link
      href={`/itinerary/${itinerary.id}`}
      className="group flex min-h-[200px] flex-col justify-between rounded-sm bg-paper p-7 text-ink shadow-[0_30px_80px_-20px_rgba(0,0,0,0.5)] transition-shadow hover:shadow-[0_40px_100px_-20px_rgba(0,0,0,0.7)]"
    >
      <div className="flex flex-col gap-2">
        <p className="text-[10px] uppercase tracking-[0.3em] text-ink/55">
          {itinerary.status}
        </p>
        <h3 className="font-serif text-3xl leading-tight tracking-tight text-ink">
          {itinerary.title || "Your itinerary"}
        </h3>
      </div>
      <div className="mt-6 flex items-center justify-between text-[10px] uppercase tracking-[0.3em] text-ink/50">
        <span>{dateLabel ?? "—"}</span>
        <span className="border-b border-transparent group-hover:border-ink/40">
          Open →
        </span>
      </div>
    </Link>
  );
}
