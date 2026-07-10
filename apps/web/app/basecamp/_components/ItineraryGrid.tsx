// The "all your itineraries" surface for /basecamp variant (d).
//
// Cormorant-titled cards on cream tiles, each linking to the existing
// /itinerary/{id} detail view. The self-serve "start a new itinerary" affordance
// lives in this section header (travelers create their own trips; the card grid
// is its natural home, not the masthead).

import Link from "next/link";

import type { MyItinerarySummary } from "@ov-black/api-client";

import { Eyebrow } from "@/components/ui/eyebrow";

import { StartItineraryButton } from "./StartItineraryButton";

export type ItineraryGridProps = {
  itineraries: MyItinerarySummary[];
};

// Human copy for the derived trunk lifecycle (traveler-facing).
const STATUS_LABEL: Record<MyItinerarySummary["status"], string> = {
  in_studio: "In the studio",
  with_traveler: "Awaiting your review",
  approved: "Approved",
};

// A solo trip lives in the traveler's own working copy until staff ever
// publish, so an "in the studio" trunk with their open fork reads as theirs —
// not as something an advisor is crafting.
function statusLabel(it: MyItinerarySummary): string {
  if (it.status === "in_studio" && it.has_open_fork) return "Your working version";
  return STATUS_LABEL[it.status] ?? it.status;
}

export function ItineraryGrid({ itineraries }: ItineraryGridProps) {
  return (
    <section className="flex min-h-[60vh] flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-3">
          <h2 className="font-serif text-4xl leading-[1.1] tracking-tight text-ink sm:text-5xl">
            Your itineraries
          </h2>
        </div>
        <StartItineraryButton />
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
      className="group flex min-h-[200px] flex-col justify-between rounded-sm border border-ink/5 bg-card p-7 text-ink shadow-sheet transition-all hover:-translate-y-0.5 hover:border-ink/10 hover:shadow-sheet-lg"
    >
      <div className="flex flex-col gap-2">
        <p className="text-[10px] uppercase tracking-label text-ink/55">
          {statusLabel(itinerary)}
        </p>
        <h3 className="font-serif text-3xl leading-tight tracking-tight text-ink">
          {itinerary.title || "Your itinerary"}
        </h3>
      </div>
      <div className="mt-6 flex items-center justify-between text-[10px] uppercase tracking-label text-ink/50">
        <span>{dateLabel ?? "—"}</span>
        <span className="border-b border-transparent text-ink/70 transition-colors group-hover:border-brand group-hover:text-brand">
          Open →
        </span>
      </div>
    </Link>
  );
}
