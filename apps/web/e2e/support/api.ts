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

async function advisorFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = mintAdvisorAccessToken();
  return fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
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

// ── Collection (wish list) seam ──────────────────────────────────────────────
// A collection item is any node with no scheduled time. The browser can only
// add the FIRST item via the concierge (agent-gated) — so a self-serve spec
// seeds a starter item at the API seam (advisor, entitled to write any
// itinerary), then drives the rail's own add/group/schedule affordances in the
// browser. These helpers seed and read that state.

export interface GraphNode {
  id: string;
  type: string;
  status: string;
  title: string;
  source?: string | null;
  source_id?: string | null;
  starts_at?: string | null;
  metadata?: Record<string, unknown>;
}

/** Seed an unscheduled item onto an itinerary (advisor write). Returns its id. */
export async function seedCollectionItemAsAdvisor(
  itineraryId: string,
  body: { type?: string; title: string; source?: string; source_id?: string },
): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/nodes`, {
    method: "POST",
    body: JSON.stringify({
      type: body.type ?? "note",
      status: "proposed",
      title: body.title,
      ...(body.source ? { source: body.source, source_id: body.source_id } : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`seed node failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as GraphNode).id;
}

/** Seed a SCHEDULED item (carries a start_time), so the timeline is present. */
export async function seedScheduledItemAsAdvisor(
  itineraryId: string,
  body: { type?: string; title: string; startsAt: string },
): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/nodes`, {
    method: "POST",
    body: JSON.stringify({
      type: body.type ?? "experience",
      status: "proposed",
      title: body.title,
      starts_at: body.startsAt,
      duration_minutes: 60,
    }),
  });
  if (!resp.ok) {
    throw new Error(`seed scheduled node failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as GraphNode).id;
}

/** Mark a node discarded (advisor), to prove the Collection filter excludes it. */
export async function discardNodeAsAdvisor(
  itineraryId: string,
  nodeId: string,
): Promise<void> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/nodes/${nodeId}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "discarded" }),
  });
  if (!resp.ok) {
    throw new Error(`discard node failed (${resp.status}): ${await resp.text()}`);
  }
}

/** The itinerary's Collection (unscheduled, non-discarded nodes) as advisor. */
export async function getCollectionAsAdvisor(itineraryId: string): Promise<GraphNode[]> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/collection`);
  if (!resp.ok) {
    throw new Error(`GET collection failed (${resp.status})`);
  }
  return ((await resp.json()) as { items: GraphNode[] }).items;
}

/** Every node on the itinerary (advisor), for asserting a node's scheduled state. */
export async function getGraphNodesAsAdvisor(itineraryId: string): Promise<GraphNode[]> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}`);
  if (!resp.ok) {
    throw new Error(`GET /itinerary/${itineraryId} failed (${resp.status})`);
  }
  return ((await resp.json()) as { nodes: GraphNode[] }).nodes;
}
