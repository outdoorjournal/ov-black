// Public surface of @ov-black/api-client.
//
// The generator (@hey-api/openapi-ts) emits a fetch-based SDK under
// ./generated with a per-call `{ data, error, response }` return shape.
// We re-export the typed models and provide small, stable wrappers for
// the endpoints apps/web cares about. The wrappers collapse the SDK's
// error fields into a discriminated result so callers can render the
// D015 error copy without branching on response objects.

import { createClient } from "./generated/client/client.gen.js";
import type { Client } from "./generated/client/types.gen.js";
import {
  createClientEndpointClientsPost,
  createSessionEndpointSessionsPost,
  getClientEndpointClientsClientIdGet,
  getItineraryEndpointItineraryItineraryIdGet,
  listClientsEndpointClientsGet,
  listTurnsEndpointSessionsSessionIdTurnsGet,
  redeemInviteEndpointAuthRedeemInvitePost,
  updateNodeEndpointItineraryItineraryIdNodesNodeIdPatch,
} from "./generated/sdk.gen.js";
import type {
  AgentTurnSummary,
  ClientCreatePayload,
  ClientDetail,
  ClientSummary,
  EdgeResponse,
  ItineraryResponse,
  NodeResponse,
  NodeStatus,
  OpenSessionRequest,
  OpenSessionResponse,
  RedeemInviteRequest,
} from "./generated/types.gen.js";

export type { RedeemInviteRequest } from "./generated/types.gen.js";
export type { Client } from "./generated/client/types.gen.js";

// Itinerary graph (S02): create + read + node/edge mutation contracts and
// the assembled GraphResponse view consumed by apps/web.
export type {
  CreateItineraryRequest,
  ItineraryResponse,
  CreateNodeRequest,
  UpdateNodeRequest,
  NodeResponse,
  CreateEdgeRequest,
  EdgeResponse,
  GraphResponse,
  NodeStatus,
  NodeType,
  EdgeType,
} from "./generated/types.gen.js";

// Inventory (S02): the discriminated InventoryItem union and its nested
// value types. Consumers can switch on `kind` for variant-specific UI.
export type {
  ExperienceItem,
  DestinationItem,
  HotelItem,
  FlightItem,
  MealItem,
  TransitItem,
  NoteItem,
  Location,
  Price,
  Range,
  EditorialLink,
  SearchInventoryResponse,
} from "./generated/types.gen.js";

// Clients (S03): advisor-facing /clients surface — the three request/
// response shapes plus the nested Voodoo Doll payload types. Re-exported
// so apps/web can type forms + list/detail views from a single module.
export type {
  ClientCreatePayload,
  ClientCreateResponse,
  ClientSummary,
  ClientDetail,
  VoodooDollPayload,
  VoodooDollDetail,
  VoodooDollTyped,
  VoodooDollJsonb,
  ContactChannel,
  GroupType,
} from "./generated/types.gen.js";

// Agent sessions (S04): POST /sessions request/response + the replay shape
// for GET /sessions/{id}/turns. The SSE stream for /turn is consumed by a
// DIY reader in apps/web (S05) — only the non-streaming surfaces are typed
// here.
export type {
  OpenSessionRequest,
  OpenSessionResponse,
  TurnRequest,
  AgentTurnSummary,
  TurnRole,
} from "./generated/types.gen.js";

export interface ApiClientConfig {
  /** Base URL of the API — e.g. https://<alb-dns> or http://localhost:8000 */
  baseUrl: string;
  /**
   * Supabase access token forwarded as `Authorization: Bearer <token>` on
   * every request via a @hey-api client request interceptor. Omit for
   * unauthenticated flows (the invite-redeem call still runs without one).
   */
  accessToken?: string;
}

/**
 * Build an API client bound to a specific base URL. Each call returns a
 * fresh instance so callers can scope clients per-request (server
 * components) without stepping on each other's auth headers later.
 *
 * When `accessToken` is provided, a @hey-api request interceptor is
 * registered that stamps `Authorization: Bearer ${accessToken}` on every
 * outgoing Request. The interceptor is a no-op when the token is absent,
 * which is intentional: POST /auth/redeem-invite runs unauthenticated.
 */
export function createApiClient(config: ApiClientConfig): Client {
  const client = createClient({ baseUrl: config.baseUrl });
  const token = config.accessToken;
  if (token) {
    client.interceptors.request.use((request) => {
      request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    });
  }
  return client;
}

export type RedeemInviteDetail =
  | "invite_not_redeemable"
  | "invite_already_consumed"
  | "auth_upstream_unavailable"
  | "internal_error"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for POST /auth/redeem-invite. Keeps the D015
 * error-collapse guarantee visible in the type: "invite_not_redeemable"
 * covers both unknown-code and wrong-email.
 */
export type RedeemInviteResult =
  | { ok: true }
  | { ok: false; status: number; detail: RedeemInviteDetail };

/**
 * Typed wrapper for POST /auth/redeem-invite.
 *
 * Returns a result rather than throwing so UI components can branch on
 * `result.ok` without wrapping every call in try/catch. Network failures
 * surface as { ok: false, status: 0, detail: "network_error" }.
 */
export async function redeemInvite(
  client: Client,
  body: RedeemInviteRequest,
): Promise<RedeemInviteResult> {
  try {
    const { error, response } = await redeemInviteEndpointAuthRedeemInvitePost({
      client,
      body,
    });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseRedeemDetail(error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseRedeemDetail(error: unknown): RedeemInviteDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "invite_not_redeemable") return "invite_not_redeemable";
  if (raw === "invite_already_consumed") return "invite_already_consumed";
  if (raw === "auth_upstream_unavailable") return "auth_upstream_unavailable";
  if (raw === "internal_error") return "internal_error";
  return "unknown";
}

export type CreateClientDetail =
  | "advisor_only"
  | "client_email_already_invited"
  | "auth_upstream_unavailable"
  | "validation_error"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for POST /clients. Collapses the router's 201 /
 * 403 / 409 / 422 / 502 matrix into a single `ok` shape — advisor-only
 * (403) and upstream-unavailable (502) are distinct reason strings so the
 * UI can render the right D015 message.
 */
export type CreateClientResult =
  | { ok: true; client_id: string; email: string }
  | { ok: false; status: number; detail: CreateClientDetail };

/**
 * Typed wrapper for POST /clients (create client + Voodoo Doll + invite).
 *
 * The 201 body carries `client_id` + `invite_email`; we re-shape to
 * `{ client_id, email }` so the result is keyed the same way apps/web
 * already reads S01 redemption data.
 */
export async function createClientEndpoint(
  client: Client,
  body: ClientCreatePayload,
): Promise<CreateClientResult> {
  try {
    const { data, error, response } = await createClientEndpointClientsPost({
      client,
      body,
    });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        client_id: data.client_id,
        email: data.invite_email,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCreateClientDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCreateClientDetail(
  status: number,
  error: unknown,
): CreateClientDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "advisor_only") return "advisor_only";
  if (raw === "client_email_already_invited") return "client_email_already_invited";
  if (raw === "auth_upstream_unavailable") return "auth_upstream_unavailable";
  // FastAPI emits a structured 422 body; collapse any 422 to validation_error
  // regardless of the nested `detail` array shape.
  if (status === 422) return "validation_error";
  if (status === 403) return "advisor_only";
  if (status === 409) return "client_email_already_invited";
  if (status === 502) return "auth_upstream_unavailable";
  return "unknown";
}

export type ListClientsDetail =
  | "advisor_only"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for GET /clients. 403 collapses to `advisor_only`
 * — there is no 409/502 path on the read side.
 */
export type ListClientsResult =
  | { ok: true; clients: ClientSummary[] }
  | { ok: false; status: number; detail: ListClientsDetail };

/**
 * Typed wrapper for GET /clients — returns the calling advisor's clients
 * newest-first. The generated response is already typed as
 * `ClientSummary[]`; this wrapper only collapses the `{data, error}`
 * shape and the network-failure path.
 */
export async function listClients(client: Client): Promise<ListClientsResult> {
  try {
    const { data, error, response } = await listClientsEndpointClientsGet({
      client,
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, clients: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseListClientsDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseListClientsDetail(status: number): ListClientsDetail {
  if (status === 403) return "advisor_only";
  return "unknown";
}

export type GetClientDetail =
  | "client_not_found"
  | "advisor_only"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for GET /clients/{client_id}. 404 is the only
 * not-found shape (the router deliberately 404s on cross-advisor reads
 * to avoid leaking existence — S01 D015 precedent).
 */
export type GetClientResult =
  | { ok: true; client: ClientDetail }
  | { ok: false; status: number; detail: GetClientDetail };

/**
 * Typed wrapper for GET /clients/{client_id}.
 */
export async function getClient(
  client: Client,
  clientId: string,
): Promise<GetClientResult> {
  try {
    const { data, error, response } = await getClientEndpointClientsClientIdGet({
      client,
      path: { client_id: clientId },
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, client: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseGetClientDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseGetClientDetail(status: number): GetClientDetail {
  if (status === 404) return "client_not_found";
  if (status === 403) return "advisor_only";
  return "unknown";
}

export type CreateSessionDetail =
  | "client_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for POST /sessions. 404 collapses both
 * CLIENT_NOT_FOUND and FORBIDDEN (D015 shape) so the UI cannot probe.
 */
export type CreateSessionResult =
  | {
      ok: true;
      session_id: string;
      agentcore_session_id: string;
      // S07 T05: exposed so the RSC chat page can feed GET /itinerary/{id}
      // to rehydrate proposed cards on reload without a separate lookup.
      itinerary_id: string;
    }
  | { ok: false; status: number; detail: CreateSessionDetail };

/**
 * Typed wrapper for POST /sessions (open or reuse an agent session).
 *
 * Idempotent on the backend — two consecutive calls with the same
 * `client_id` return the same session_id. Callers can treat the 201 as
 * "you now have a session" without tracking create-vs-reuse state.
 */
export async function createSessionEndpoint(
  client: Client,
  body: OpenSessionRequest,
): Promise<CreateSessionResult> {
  try {
    const { data, error, response } = await createSessionEndpointSessionsPost({
      client,
      body,
    });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        session_id: data.session_id,
        agentcore_session_id: data.agentcore_session_id,
        itinerary_id: data.itinerary_id,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCreateSessionDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCreateSessionDetail(status: number): CreateSessionDetail {
  if (status === 404) return "client_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type ListTurnsDetail =
  | "session_not_found"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for GET /sessions/{id}/turns.
 */
export type ListTurnsResult =
  | { ok: true; turns: AgentTurnSummary[] }
  | { ok: false; status: number; detail: ListTurnsDetail };

/**
 * Typed wrapper for GET /sessions/{id}/turns — returns every turn on a
 * session in turn_index order. This is the Command Center replay path;
 * the live SSE stream is consumed with a DIY reader in apps/web.
 */
export async function listTurns(
  client: Client,
  sessionId: string,
): Promise<ListTurnsResult> {
  try {
    const { data, error, response } =
      await listTurnsEndpointSessionsSessionIdTurnsGet({
        client,
        path: { session_id: sessionId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, turns: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseListTurnsDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseListTurnsDetail(status: number): ListTurnsDetail {
  if (status === 404) return "session_not_found";
  return "unknown";
}

export type GetItineraryDetail =
  | "itinerary_not_found"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for GET /itinerary/{itinerary_id}. Collapses the
 * generated `{ itinerary, nodes, edges }` envelope onto the flat success
 * shape S05's wrappers use, so apps/web can hydrate the MoodBoard on the
 * RSC path without branching on the SDK response object.
 */
export type GetItineraryResult =
  | {
      ok: true;
      itinerary: ItineraryResponse;
      nodes: NodeResponse[];
      edges: EdgeResponse[];
    }
  | { ok: false; status: number; detail: GetItineraryDetail };

/**
 * Typed wrapper for GET /itinerary/{itinerary_id} — returns the whole
 * assembled graph view (itinerary + nodes + edges). Used by the chat page
 * RSC to hydrate the MoodBoard aside on a hard reload.
 */
export async function getItinerary(
  client: Client,
  itineraryId: string,
): Promise<GetItineraryResult> {
  try {
    const { data, error, response } =
      await getItineraryEndpointItineraryItineraryIdGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        itinerary: data.itinerary,
        nodes: data.nodes,
        edges: data.edges,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseGetItineraryDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseGetItineraryDetail(status: number): GetItineraryDetail {
  if (status === 404) return "itinerary_not_found";
  return "unknown";
}

export type UpdateNodeStatusDetail =
  | "node_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for PATCH /itinerary/{itinerary_id}/nodes/{node_id}.
 * Status transitions (pin → approved, keep → proposed, discard → discarded)
 * all flow through this one wrapper; the UI discriminates on the NodeStatus
 * it passed in, not on anything the wrapper surfaces.
 */
export type UpdateNodeResult =
  | { ok: true; node: NodeResponse }
  | { ok: false; status: number; detail: UpdateNodeStatusDetail };

export type UpdateNodeStatusArgs = {
  itineraryId: string;
  nodeId: string;
  status: NodeStatus;
};

/**
 * Typed wrapper for PATCH /itinerary/{itinerary_id}/nodes/{node_id}.
 *
 * Only the `status` field is sent; other UpdateNodeRequest fields remain
 * untouched on the server. Returns a discriminated result so the MoodBoard
 * can optimistically update and then revert on `ok: false` without
 * wrapping every call in try/catch.
 */
export async function updateNodeStatus(
  client: Client,
  args: UpdateNodeStatusArgs,
): Promise<UpdateNodeResult> {
  try {
    const { data, error, response } =
      await updateNodeEndpointItineraryItineraryIdNodesNodeIdPatch({
        client,
        path: {
          itinerary_id: args.itineraryId,
          node_id: args.nodeId,
        },
        body: { status: args.status },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, node: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseUpdateNodeStatusDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseUpdateNodeStatusDetail(status: number): UpdateNodeStatusDetail {
  if (status === 404) return "node_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}
