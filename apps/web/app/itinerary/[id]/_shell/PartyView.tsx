"use client";

// The Travel Party destination — "who's coming" as its own routed surface on the
// left rail (a page, not just the hero's popover). Advisors get the full
// attach/detach panel (rehomed here from the hero popover); a traveler sees the
// roster on this trip with a way through to keep their household current.

import { useCallback, useEffect, useState } from "react";
import type { Route } from "next";
import Link from "next/link";

import {
  createApiClient,
  listItineraryParty,
  type ItineraryPartyEntry,
} from "@ov-black/api-client";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { PartyPanel } from "@/app/_components/itinerary-graph/views/horizontal/PartyPanel";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

export function PartyView() {
  const role = itineraryGraphStore.useStore((s) => s.role);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const { timeline } = useTimelineData();

  const isAdvisor = role === "advisor";
  const clientId = timeline.itinerary.client_id ?? null;

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6 sm:py-10">
        <header className="mb-6">
          <p className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
            Travel party
          </p>
          <h1 className="mt-1 font-serif text-3xl text-ink">Who’s coming</h1>
          <p className="mt-2 font-sans text-[13px] text-ink/55">
            {isAdvisor
              ? "Attach travelers from the client’s household onto this trip."
              : "Everyone on this adventure. Keep your household current and we’ll bring them along."}
          </p>
        </header>

        {isAdvisor ? (
          <div className="overflow-hidden rounded-lg border border-ink/10 bg-paper shadow-sm">
            <PartyPanel
              clientId={clientId}
              itineraryId={itineraryId}
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
            />
          </div>
        ) : (
          <TravelerParty
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
          />
        )}
      </div>
    </div>
  );
}

// Traveler read view — who is on this trip, plus a way to keep the durable
// household roster current (the same roster advisors attach from).
function TravelerParty({
  itineraryId,
  apiBaseUrl,
  accessToken,
}: {
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
}) {
  const [members, setMembers] = useState<ItineraryPartyEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    if (!apiBaseUrl || !accessToken) {
      setLoaded(true);
      return;
    }
    const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
    const result = await listItineraryParty(api, itineraryId);
    if (result.ok) setMembers(result.party.members);
    setLoaded(true);
  }, [itineraryId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-lg tracking-tight text-ink">
          On this trip
        </h2>
        {!loaded ? (
          <p className="font-sans text-sm text-ink/50">Loading…</p>
        ) : members.length === 0 ? (
          <p className="font-serif text-[13px] italic text-ink/45">
            Just you so far.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
            {members.map((m) => (
              <li key={m.traveler_id} className="py-2.5">
                <span className="font-sans text-sm text-ink/90">
                  {m.member?.full_name ?? m.name}
                  {m.member?.is_primary ? (
                    <span className="ml-2 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
                      Primary
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link
        href={"/basecamp/party" as Route}
        className="self-start font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
      >
        Manage your household →
      </Link>
    </div>
  );
}
