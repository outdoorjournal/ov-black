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
  access_status?: "uninvited" | "pending" | "active" | null;
  invited_at?: string | null;
  accepted_at?: string | null;
}

/** The advisor's view of a client, matched by email (the invite link key). */
export async function findClientByEmail(
  email: string,
): Promise<ClientRow | undefined> {
  // Wave F: GET /clients is a searchable envelope — `?q=` matches email, so
  // the lookup no longer scans an unbounded roster.
  const resp = await advisorFetch(`/clients?q=${encodeURIComponent(email)}`);
  if (!resp.ok) {
    throw new Error(`GET /clients failed (${resp.status})`);
  }
  const { clients } = (await resp.json()) as { clients: ClientRow[] };
  return clients.find(
    (c) => (c.email ?? "").toLowerCase() === email.toLowerCase(),
  );
}

/**
 * Any existing session that already has turns, for the read-only replay spec.
 * Replay is a pure read surface — driving a fresh agent turn just to render it
 * would drag the whole agent stack into this spec — so it borrows whatever
 * conversation history the local stack already carries and skips when there is
 * none (fresh DB).
 */
export async function findAnySessionWithTurns(): Promise<
  { clientId: string; sessionId: string } | undefined
> {
  const resp = await advisorFetch("/clients?limit=50");
  if (!resp.ok) {
    throw new Error(`GET /clients failed (${resp.status})`);
  }
  const { clients } = (await resp.json()) as { clients: ClientRow[] };
  for (const client of clients) {
    const sessionsResp = await advisorFetch(`/clients/${client.id}/sessions`);
    if (!sessionsResp.ok) continue;
    const { sessions } = (await sessionsResp.json()) as {
      sessions: Array<{ id: string; turn_count: number }>;
    };
    const withTurns = sessions.find((s) => s.turn_count > 0);
    if (withTurns) return { clientId: client.id, sessionId: withTurns.id };
  }
  return undefined;
}

export interface ItineraryTiming {
  brief?: string | null;
  timing_kind?: "exact" | "window" | "flexible" | null;
  date_start?: string | null;
  date_end?: string | null;
  duration_nights?: number | null;
  timing_note?: string | null;
  // Ownership/linkage (GraphResponse.itinerary carries the full ItineraryResponse),
  // so a spec can assert the itinerary is bound to the intended client.
  client_id?: string | null;
  created_by?: string | null;
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

// ── Advisor seeds (client + itinerary) ───────────────────────────────────────
// Some advisor scenarios begin PAST the itinerary shell — they need a
// client-bound itinerary already standing (e.g. to reach the concierge or a
// trip's party) without re-driving creation + intake in the browser every time.
// So those specs seed that precondition at the API seam — the advisor is
// entitled to POST /clients and POST /itinerary — and then drive the *action*
// under test in the browser. (ADV-2 itself no longer seeds the itinerary: the
// command-center "New itinerary" affordance now creates the client binding in
// the browser — see itinerary-intake.spec.ts.) This mirrors the Collection seed
// helpers below and the harness's "seed state, drive the action" rule of thumb.

/**
 * Create a client owned by the advisor (POST /clients) and return its id. Like
 * the browser New Client form, this mints the invited auth user + welcome mail
 * — harmless against an example.com address, which never delivers. Pass a UNIQUE
 * email per test so the client is unambiguous and runs never collide.
 */
export async function createClientAsAdvisor(
  fullName: string,
  email: string,
): Promise<string> {
  const resp = await advisorFetch("/clients", {
    method: "POST",
    body: JSON.stringify({
      full_name: fullName,
      email,
      dossier: { typed: { contact_preference: "email", travel_party_notes: "" } },
    }),
  });
  if (!resp.ok) {
    throw new Error(`POST /clients failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as { client_id: string }).client_id;
}

/**
 * Create an itinerary linked to a client (POST /itinerary), authored by the
 * advisor, and return its id. Timing/brief are intentionally left empty so the
 * first-run intake still gates — a spec seeds the brief here only when it needs
 * to start *past* the intake (e.g. to reach the concierge). Returns the id.
 */
export async function createItineraryForClientAsAdvisor(
  clientId: string,
  opts: {
    title?: string;
    brief?: string;
    /**
     * Optional timing seed (Wave E): a spec that schedules cards on specific
     * dates should declare the window up front — `days_anchor` stamps from the
     * window's `date_start`, so Day 1 lands where the cards do rather than on
     * whatever day the test happened to run.
     */
    timing?: {
      kind: "exact" | "window" | "flexible";
      dateStart?: string;
      dateEnd?: string;
    };
  } = {},
): Promise<string> {
  const resp = await advisorFetch("/itinerary", {
    method: "POST",
    body: JSON.stringify({
      title: opts.title ?? "",
      client_id: clientId,
      ...(opts.brief ? { brief: opts.brief } : {}),
      ...(opts.timing
        ? {
            timing_kind: opts.timing.kind,
            ...(opts.timing.dateStart ? { date_start: opts.timing.dateStart } : {}),
            ...(opts.timing.dateEnd ? { date_end: opts.timing.dateEnd } : {}),
          }
        : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`POST /itinerary failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as { id: string }).id;
}

/** A client's durable party roster as the advisor sees it (for cross-actor backstops). */
export async function getClientPartyAsAdvisor(
  clientId: string,
): Promise<
  Array<{
    id: string;
    full_name: string;
    dietary?: string | null;
    created_by_actor?: string | null;
  }>
> {
  const resp = await advisorFetch(`/clients/${clientId}/party-members`);
  if (!resp.ok) {
    throw new Error(`GET party-members failed (${resp.status})`);
  }
  return ((await resp.json()) as { members: Array<{ id: string; full_name: string; dietary?: string | null; created_by_actor?: string | null }> }).members;
}

/**
 * Seed a durable ("remembered") household party member for a client (advisor
 * write) and return its id — the record a trip can later attach from. Members
 * created this way are stamped `created_by_actor = advisor`.
 */
export async function createPartyMemberAsAdvisor(
  clientId: string,
  body: { fullName: string; dietary?: string },
): Promise<string> {
  const resp = await advisorFetch(`/clients/${clientId}/party-members`, {
    method: "POST",
    body: JSON.stringify({
      full_name: body.fullName,
      ...(body.dietary ? { dietary: body.dietary } : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`POST party-member failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as { id: string }).id;
}

/** The itinerary's own party roster ("On this trip") as the advisor sees it. */
export async function getItineraryPartyAsAdvisor(
  itineraryId: string,
): Promise<
  Array<{ traveler_id: string; party_member_id: string | null; member?: { full_name?: string } | null }>
> {
  const resp = await advisorFetch(`/itineraries/${itineraryId}/party`);
  if (!resp.ok) {
    throw new Error(`GET itinerary party failed (${resp.status})`);
  }
  return ((await resp.json()) as { members: Array<{ traveler_id: string; party_member_id: string | null; member?: { full_name?: string } | null }> }).members;
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
  cost_amount?: string | null;
  cost_currency?: string | null;
  cost_kind?: "per_person" | "total" | null;
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
      status: "pending",
      title: body.title,
      ...(body.source ? { source: body.source, source_id: body.source_id } : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`seed node failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as GraphNode).id;
}

/** Seed a raw pending item (advisor still building) as a bare experience card. */
export async function seedIdeaItemAsAdvisor(
  itineraryId: string,
  body: { type?: string; title: string },
): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/nodes`, {
    method: "POST",
    body: JSON.stringify({
      type: body.type ?? "experience",
      status: "pending",
      title: body.title,
    }),
  });
  if (!resp.ok) {
    throw new Error(`seed idea node failed (${resp.status}): ${await resp.text()}`);
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
      status: "pending",
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

/** Seed a PRICED node (advisor), so the itinerary carries per-currency totals
 *  (ADV-10). Both-or-neither cost fields; `startsAt` schedules it (else Collection). */
export async function seedPricedItemAsAdvisor(
  itineraryId: string,
  body: {
    type?: string;
    title: string;
    amount: string;
    currency: string;
    kind?: "per_person" | "total";
    startsAt?: string;
  },
): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/nodes`, {
    method: "POST",
    body: JSON.stringify({
      type: body.type ?? "experience",
      status: "pending",
      title: body.title,
      cost_amount: body.amount,
      cost_currency: body.currency,
      cost_kind: body.kind ?? "total",
      ...(body.startsAt
        ? { starts_at: body.startsAt, duration_minutes: 60 }
        : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`seed priced node failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as GraphNode).id;
}

/** The itinerary's derived display status (advisor read) —
 *  in_studio | with_traveler | approved. */
export async function getItineraryStatusAsAdvisor(itineraryId: string): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}`);
  if (!resp.ok) {
    throw new Error(`GET /itinerary/${itineraryId} failed (${resp.status})`);
  }
  return (
    ((await resp.json()) as { itinerary: { display_status?: string | null } })
      .itinerary.display_status ?? "in_studio"
  );
}

/** The itinerary's per-currency totals (advisor read, ADV-10). */
export async function getItineraryTotalsAsAdvisor(
  itineraryId: string,
): Promise<Record<string, string>> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}`);
  if (!resp.ok) {
    throw new Error(`GET /itinerary/${itineraryId} failed (${resp.status})`);
  }
  return ((await resp.json()) as { totals?: Record<string, string> }).totals ?? {};
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

/** Approve a single node (advisor) — a node can be `approved` while the itinerary
 *  itself stays `draft`, which is what invoicing needs (chargeable = approved node
 *  cost) without freezing the advisor's edit lock (ADV-11). */
export async function approveNodeAsAdvisor(
  itineraryId: string,
  nodeId: string,
): Promise<void> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/nodes/${nodeId}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "approved" }),
  });
  if (!resp.ok) {
    throw new Error(`approve node failed (${resp.status}): ${await resp.text()}`);
  }
}

/** Set a client's billing identity (advisor, PATCH /clients/{id}) — the pay page
 *  pre-fills its form from this, so the payment e2e seeds it up front (0051). */
export async function setClientBillingAsAdvisor(
  clientId: string,
  body: {
    address?: string;
    city?: string;
    region?: string;
    postal_code?: string;
    country_code?: string;
  },
): Promise<void> {
  const resp = await advisorFetch(`/clients/${clientId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`set client billing failed (${resp.status}): ${await resp.text()}`);
  }
}

/** Draft a "Balance" invoice covering every remaining node balance (advisor,
 *  POST /itinerary/{id}/invoices/final) — returns the new invoice id. */
export async function createFinalInvoiceAsAdvisor(itineraryId: string): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/invoices/final`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!resp.ok) {
    throw new Error(`create final invoice failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as { id: string }).id;
}

/** Issue a draft invoice (advisor, POST /invoices/{id}/issue) — flips it to
 *  `issued` so the owning traveler can pay it. */
export async function issueInvoiceAsAdvisor(invoiceId: string): Promise<void> {
  const resp = await advisorFetch(`/invoices/${invoiceId}/issue`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!resp.ok) {
    throw new Error(`issue invoice failed (${resp.status}): ${await resp.text()}`);
  }
}

/** One invoice with its payments (advisor) — the backstop for "the charge really
 *  settled": status flips to `paid` and a succeeded payment (last-4) is recorded. */
export async function getInvoiceAsAdvisor(invoiceId: string): Promise<{
  id: string;
  status: string;
  payments: Array<{ status: string; amount: string; last_four: string | null }>;
}> {
  const resp = await advisorFetch(`/invoices/${invoiceId}`);
  if (!resp.ok) {
    throw new Error(`GET /invoices/${invoiceId} failed (${resp.status}): ${await resp.text()}`);
  }
  return (await resp.json()) as {
    id: string;
    status: string;
    payments: Array<{ status: string; amount: string; last_four: string | null }>;
  };
}

/** Every invoice on the itinerary (advisor) — the API-seam backstop for the
 *  billing cockpit: assert what the browser actions actually persisted. */
export async function listInvoicesAsAdvisor(
  itineraryId: string,
): Promise<Array<{ id: string; status: string; currency: string; total: string }>> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/invoices`);
  if (!resp.ok) {
    throw new Error(`list invoices failed (${resp.status}): ${await resp.text()}`);
  }
  return (await resp.json()) as Array<{
    id: string;
    status: string;
    currency: string;
    total: string;
  }>;
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

/** Fork an itinerary (advisor) — returns the new fork's id. The advisor's
 *  working copy: content built here reaches the trunk only via publish. */
export async function forkItineraryAsAdvisor(itineraryId: string): Promise<string> {
  const resp = await advisorFetch(`/itinerary/${itineraryId}/fork`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!resp.ok) {
    throw new Error(`fork failed (${resp.status}): ${await resp.text()}`);
  }
  return ((await resp.json()) as { itinerary: { id: string } }).itinerary.id;
}
