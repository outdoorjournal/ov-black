// API-seam backstops for the browser e2e suite.
//
// These specs are browser-first — a QA person drives every action through the
// UI. But some outcomes are STATE, not experience: the exact timing fields an
// intake persisted, or a client another actor should now be able to see. Rather
// than scrape those out of the DOM (brittle) or open a second UI (slow), we read
// them back at the API seam with an advisor token — the reliable "and it really
// saved / the advisor really sees it" assertion behind the browser check.
//
// Advisor-scoped on purpose: an advisor is entitled to GET any itinerary and to
// list every client, so one privileged reader can verify outcomes a traveler
// produced. Local-only, like the rest of the harness's provisioning.

import { getApiBaseUrl, mintAdvisorAccessToken } from "./auth";

async function advisorFetch(path: string): Promise<Response> {
  const token = mintAdvisorAccessToken();
  return fetch(`${getApiBaseUrl()}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export interface ClientRow {
  id: string;
  full_name?: string | null;
  email?: string | null;
  access_status?: "pending" | "active" | null;
  accepted_at?: string | null;
}

/** The advisor's view of a client, matched by email (the invite link key). */
export async function findClientByEmail(
  email: string,
): Promise<ClientRow | undefined> {
  const resp = await advisorFetch("/clients");
  if (!resp.ok) {
    throw new Error(`GET /clients failed (${resp.status})`);
  }
  const clients = (await resp.json()) as ClientRow[];
  return clients.find(
    (c) => (c.email ?? "").toLowerCase() === email.toLowerCase(),
  );
}

export interface ItineraryTiming {
  brief?: string | null;
  timing_kind?: "exact" | "window" | "flexible" | null;
  date_start?: string | null;
  date_end?: string | null;
  duration_nights?: number | null;
  timing_note?: string | null;
}

/**
 * The persisted itinerary as an advisor sees it. GET /itinerary/{id} returns
 * `{ itinerary, nodes, edges }`; we return the itinerary record so a test can
 * assert the brief + timing the browser intake wrote.
 */
export async function getItineraryAsAdvisor(id: string): Promise<ItineraryTiming> {
  const resp = await advisorFetch(`/itinerary/${id}`);
  if (!resp.ok) {
    throw new Error(`GET /itinerary/${id} failed (${resp.status})`);
  }
  const data = (await resp.json()) as { itinerary?: ItineraryTiming };
  const itinerary = data.itinerary ?? (data as ItineraryTiming);
  return itinerary;
}
