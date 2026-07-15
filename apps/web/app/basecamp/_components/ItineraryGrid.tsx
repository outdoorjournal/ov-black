"use client";

// The "all your itineraries" surface for /basecamp variant (d).
//
// Imagery-forward tiles — the trip's own hero image when it has one (matching
// the dashboard hero), else pulled from the trip's most evocative node
// (destination → hotel → experience → meal), the serif title and timeframe
// resting on a scrim at the foot of the image, a status chip up top. When a
// trip has no cover yet the hero falls back to a stable per-trip gradient so
// the grid never shows a floating, image-less card. Each links to the existing
// /itinerary/{id} detail view. The self-serve "start a new itinerary"
// affordance lives in the section header (travelers create their own trips).

import Link from "next/link";

import type { ItineraryTimingKind, MyItinerarySummary } from "@ov-black/api-client";

import { placePhotoUrl } from "@/app/_components/itinerary-graph/model/placePhoto";

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

// Muted, editorial placeholder gradients — a stable pick per trip so an
// image-less tile still reads as a considered object, not an empty frame.
const PLACEHOLDER_GRADIENTS = [
  "linear-gradient(150deg, #2f3a34 0%, #55655c 55%, #cdbfa6 100%)", // pine → sand
  "linear-gradient(150deg, #3a3340 0%, #6a5f74 55%, #d3c4b4 100%)", // plum → linen
  "linear-gradient(150deg, #2c3a45 0%, #566d78 55%, #c9c1ad 100%)", // slate → stone
  "linear-gradient(150deg, #45362c 0%, #7a5f49 55%, #d8c6a8 100%)", // umber → wheat
  "linear-gradient(150deg, #2f4038 0%, #5c7061 55%, #c6c8b0 100%)", // moss → sage
];

function placeholderFor(id: string): string {
  let sum = 0;
  for (let i = 0; i < id.length; i += 1) sum += id.charCodeAt(i);
  return PLACEHOLDER_GRADIENTS[sum % PLACEHOLDER_GRADIENTS.length]!;
}

// The trip's timeframe for the tile subtitle: a real date range once one
// exists, else the target length for a still-flexible trip, else a gentle
// "dates to be set" so the row is never empty.
function timeframeLabel(it: MyItinerarySummary): string {
  if (it.date_start && it.date_end) {
    const start = new Date(`${it.date_start}T00:00:00Z`);
    const end = new Date(`${it.date_end}T00:00:00Z`);
    if (!Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime())) {
      const sameYear = start.getUTCFullYear() === end.getUTCFullYear();
      const sameMonth = sameYear && start.getUTCMonth() === end.getUTCMonth();
      if (sameMonth) {
        const month = start.toLocaleDateString(undefined, { month: "long", timeZone: "UTC" });
        return `${month} ${start.getUTCDate()}–${end.getUTCDate()}, ${start.getUTCFullYear()}`;
      }
      const left = start.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
      const right = end.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      });
      return `${left} – ${right}`;
    }
  }
  if (it.duration_nights && it.duration_nights > 0) {
    const nights = `${it.duration_nights} ${it.duration_nights === 1 ? "night" : "nights"}`;
    return isFlexible(it.timing_kind) ? `${nights} · dates flexible` : nights;
  }
  return "Dates to be set";
}

function isFlexible(kind: ItineraryTimingKind | null | undefined): boolean {
  return kind === "flexible" || kind === "window";
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
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {itineraries.map((it) => (
          <ItineraryCard key={it.id} itinerary={it} />
        ))}
      </div>
    </section>
  );
}

function ItineraryCard({ itinerary }: { itinerary: MyItinerarySummary }) {
  // The trip's own hero image (0054) wins — the SAME image the dashboard hero
  // shows — so the tile and the detail page agree. Trips without an explicit
  // hero (ordinary advisor trips) fall back to their most evocative node cover.
  const cover =
    itinerary.hero_image ??
    placePhotoUrl(itinerary.cover_photo_token ?? undefined) ??
    itinerary.cover_image ??
    undefined;

  return (
    <Link
      href={`/itinerary/${itinerary.id}`}
      className="group relative flex aspect-[4/5] flex-col justify-end overflow-hidden rounded-lg border border-ink/10 text-paper shadow-sheet transition-all duration-200 hover:-translate-y-1 hover:shadow-sheet-lg sm:aspect-[5/6]"
      style={{ backgroundImage: placeholderFor(itinerary.id), backgroundSize: "cover" }}
    >
      {/* The hero photo, layered over the gradient. On a load error it hides
          itself so the gradient shows through rather than a broken frame. */}
      {cover ? (
        // eslint-disable-next-line @next/next/no-img-element -- proxied/remote URL; next/image loaders unneeded, degrades to the gradient on error.
        <img
          src={cover}
          alt=""
          className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : null}

      {/* Legibility scrim — deep at the foot where the type sits, clear up top. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to top, rgba(10,10,10,0.82) 0%, rgba(10,10,10,0.35) 38%, rgba(10,10,10,0) 68%)",
        }}
      />

      {/* Status chip, top-left. */}
      <span className="absolute left-4 top-4 z-10 rounded-full bg-paper/90 px-2.5 py-1 font-sans text-[10px] uppercase tracking-label text-ink/80 backdrop-blur-sm">
        {statusLabel(itinerary)}
      </span>

      <div className="relative z-10 flex flex-col gap-1.5 p-5">
        <h3 className="font-serif text-2xl leading-tight tracking-tight text-paper sm:text-[1.7rem]">
          {itinerary.title || "Your itinerary"}
        </h3>
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11px] uppercase tracking-label text-paper/75">
            {timeframeLabel(itinerary)}
          </span>
          <span className="shrink-0 border-b border-transparent text-[11px] uppercase tracking-label text-paper/85 transition-colors group-hover:border-brand group-hover:text-brand">
            Open →
          </span>
        </div>
      </div>
    </Link>
  );
}
