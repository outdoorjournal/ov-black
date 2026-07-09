// "The Slate" (Wave F): the working set — the most recently touched trips as
// a dense strip under the queue, each row a straight line into the studio.

import type { Route } from "next";
import Link from "next/link";

import type { AdvisorItinerarySummary } from "@ov-black/api-client";

import { StatusPill, relativeDay } from "../panels";

export function PipelineStrip({ trips }: { trips: AdvisorItinerarySummary[] }) {
  return (
    <section
      aria-label="The slate"
      className="flex flex-col gap-3 rounded-md border border-paper/10 bg-paper/5 p-4 sm:p-5"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
          The slate
        </p>
        <Link
          href={"/command-center/trips" as Route}
          className="font-sans text-[10px] uppercase tracking-label text-paper/50 transition-colors hover:text-paper"
        >
          All trips →
        </Link>
      </div>

      {trips.length === 0 ? (
        <p className="py-2 font-serif text-lg text-paper/60">
          No itineraries yet — they appear as soon as a client&rsquo;s first
          session is opened.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-paper/8">
          {trips.map((trip) => (
            <li key={trip.id}>
              <Link
                href={`/itinerary/${trip.id}`}
                className="flex items-center gap-3 rounded-sm px-1 py-2 transition-colors focus-visible:bg-paper/5 focus-visible:outline-none hover:bg-paper/5"
              >
                {trip.needs_attention ? (
                  <span
                    aria-label="Needs attention"
                    className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
                  />
                ) : (
                  <span aria-hidden className="inline-block h-1.5 w-1.5 shrink-0" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-serif text-base tracking-tight text-paper">
                    {trip.title || "Untitled draft"}
                  </span>
                  <span className="block truncate font-sans text-[11px] text-paper/45">
                    {trip.client.full_name}
                  </span>
                </span>
                <StatusPill status={trip.status} />
                <span className="hidden shrink-0 whitespace-nowrap font-mono text-[10px] text-paper/40 sm:inline">
                  {relativeDay(trip.last_activity_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
