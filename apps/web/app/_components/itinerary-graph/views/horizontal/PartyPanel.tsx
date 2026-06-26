"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type ItineraryPartyEntry,
  type PartyMemberDetail,
  attachItineraryPartyMember,
  createApiClient,
  detachItineraryPartyMember,
  listClientPartyMembers,
  listItineraryParty,
} from "@ov-black/api-client";

// Advisor "who's traveling" surface — the itinerary-aside Party tab.
//
// Self-contained, like ConciergeChat: it takes the staff credentials the store
// already holds (travelers never receive them, so this panel is implicitly
// advisor-only) and calls the party wrappers directly rather than threading
// through itineraryGraphStore. Lists who's on the trip + the client's household
// roster, and attaches/detaches durable members onto this itinerary's party.

const ERROR_COPY: Record<string, string> = {
  client_not_found: "This client could not be found.",
  itinerary_not_found: "This itinerary could not be found.",
  party_member_not_found: "That traveler is no longer available.",
  advisor_only: "This action is advisor-only.",
  network_error: "Could not reach the server. Try again in a moment.",
};

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

export function PartyPanel({
  clientId,
  itineraryId,
  apiBaseUrl,
  accessToken,
}: {
  clientId: string | null;
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
}) {
  const [onTrip, setOnTrip] = useState<ItineraryPartyEntry[]>([]);
  const [roster, setRoster] = useState<PartyMemberDetail[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const api =
    apiBaseUrl && accessToken
      ? createApiClient({ baseUrl: apiBaseUrl, accessToken })
      : null;

  const refresh = useCallback(async () => {
    if (!api || !clientId) return;
    const [party, members] = await Promise.all([
      listItineraryParty(api, itineraryId),
      listClientPartyMembers(api, clientId),
    ]);
    if (party.ok) setOnTrip(party.party.members);
    if (members.ok) setRoster(members.members);
    if (!party.ok) setError(copy(party.detail));
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itineraryId, clientId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const attachedMemberIds = new Set(
    onTrip
      .map((e) => e.party_member_id)
      .filter((id): id is string => Boolean(id)),
  );
  const available = roster.filter((m) => !attachedMemberIds.has(m.id));

  const attach = (memberId: string) => {
    if (!api) return;
    setError(null);
    setPending(true);
    void (async () => {
      const result = await attachItineraryPartyMember(api, itineraryId, {
        party_member_id: memberId,
      });
      if (result.ok) setOnTrip(result.party.members);
      else setError(copy(result.detail));
      setPending(false);
    })();
  };

  const detach = (memberId: string) => {
    if (!api) return;
    setError(null);
    setPending(true);
    void (async () => {
      const result = await detachItineraryPartyMember(
        api,
        itineraryId,
        memberId,
      );
      if (result.ok) setOnTrip(result.party.members);
      else setError(copy(result.detail));
      setPending(false);
    })();
  };

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto bg-paper px-4 py-4 text-ink">
      <section className="flex flex-col gap-2">
        <h3 className="font-serif text-lg tracking-tight text-ink">
          On this trip
        </h3>
        {!loaded ? (
          <p className="font-sans text-sm text-ink/50">Loading…</p>
        ) : onTrip.length === 0 ? (
          <p className="font-sans text-sm italic text-ink/50">
            No one attached yet. Add travelers from the household below.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
            {onTrip.map((entry) => (
              <li
                key={entry.traveler_id}
                className="group flex items-center gap-3 py-2.5"
              >
                <span className="min-w-0 flex-1 truncate font-sans text-sm text-ink/90">
                  {entry.member?.full_name ?? entry.name}
                  {entry.member?.is_primary ? (
                    <span className="ml-2 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
                      Primary
                    </span>
                  ) : null}
                </span>
                {entry.party_member_id ? (
                  <button
                    type="button"
                    onClick={() => detach(entry.party_member_id as string)}
                    disabled={pending}
                    className="shrink-0 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/50 transition-colors hover:text-[#8b2a1d] disabled:opacity-40"
                  >
                    Remove
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-serif text-lg tracking-tight text-ink">
          Add from household
        </h3>
        {loaded && available.length === 0 ? (
          <p className="font-sans text-sm italic text-ink/50">
            {roster.length === 0
              ? "No saved travelers yet."
              : "Everyone in the household is already on this trip."}
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
            {available.map((m) => (
              <li key={m.id} className="flex items-center gap-3 py-2.5">
                <span className="min-w-0 flex-1 truncate font-sans text-sm text-ink/90">
                  {m.full_name}
                  {m.relationship_to_primary ? (
                    <span className="ml-2 font-sans text-xs text-ink/50">
                      {m.relationship_to_primary}
                    </span>
                  ) : null}
                </span>
                <button
                  type="button"
                  onClick={() => attach(m.id)}
                  disabled={pending}
                  className="shrink-0 rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
                >
                  Attach
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {error ? (
        <p role="alert" className="font-sans text-xs font-medium text-[#8b2a1d]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
