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
  approveItineraryEndpointItineraryItineraryIdApprovePost,
  assembleItineraryEndpointItineraryItineraryIdAssemblePost,
  cancelClientInviteEndpointClientsClientIdInviteCancelPost,
  createClientEndpointClientsPost,
  createDossierFactEndpointClientsClientIdDossierFactsPost,
  createOsintFactEndpointClientsClientIdOsintFactsPost,
  createProfileFactEndpointClientsClientIdProfileFactsPost,
  createSessionEndpointSessionsPost,
  getClientEndpointClientsClientIdGet,
  getItineraryEndpointItineraryItineraryIdGet,
  getMyOnboardingSessionEndpointMeOnboardingSessionGet,
  listClientsEndpointClientsGet,
  listMyItinerariesEndpointMeItinerariesGet,
  listTurnsEndpointSessionsSessionIdTurnsGet,
  lockItineraryEndpointItineraryItineraryIdLockPost,
  loginEndpointAuthLoginPost,
  randomOpenerEndpointOnboardingOpenersRandomGet,
  redactDossierFactEndpointClientsClientIdDossierFactsFactIdDelete,
  redactOsintFactEndpointClientsClientIdOsintFactsFactIdDelete,
  redactProfileFactEndpointClientsClientIdProfileFactsFactIdDelete,
  redeemInviteEndpointAuthRedeemInvitePost,
  reissueClientInviteEndpointClientsClientIdInviteReissuePost,
  releaseItineraryEndpointItineraryItineraryIdReleasePost,
  updateDossierFactEndpointClientsClientIdDossierFactsFactIdPatch,
  updateNodeEndpointItineraryItineraryIdNodesNodeIdPatch,
  updateOsintFactEndpointClientsClientIdOsintFactsFactIdPatch,
  updateProfileFactEndpointClientsClientIdProfileFactsFactIdPatch,
} from "./generated/sdk.gen.js";
import type {
  AgentTurnSummary,
  ClientCreatePayload,
  ClientDetail,
  ClientSummary,
  DossierFactCreate,
  DossierFactDetail,
  DossierFactUpdate,
  EdgeResponse,
  GraphResponse,
  ItineraryResponse,
  LoginRequest,
  MyItinerarySummary,
  MyOnboardingSessionResponse,
  NodeResponse,
  NodeStatus,
  OnboardingOpenerResponse,
  OpenSessionRequest,
  OpenSessionResponse,
  OsintFactCreate,
  OsintFactDetail,
  OsintFactUpdate,
  ProfileFactCreate,
  ProfileFactDetail,
  ProfileFactUpdate,
  RedactRequest,
  RedeemInviteRequest,
} from "./generated/types.gen.js";

export type { LoginRequest, RedeemInviteRequest } from "./generated/types.gen.js";
export type { Client } from "./generated/client/types.gen.js";

// Itinerary graph (S02): create + read + node/edge mutation contracts and
// the assembled GraphResponse view consumed by apps/web.
export type {
  CreateItineraryRequest,
  ItineraryResponse,
  ItineraryStatus,
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

// Clients (S03): advisor-facing /clients surface — the request/response
// shapes plus the nested Dossier and per-fact tier types. Re-exported so
// apps/web can type forms + list/detail views from a single module.
export type {
  ClientCreatePayload,
  ClientCreateResponse,
  ClientSummary,
  ClientDetail,
  InviteEvent,
  DossierPayload,
  DossierDetail,
  DossierTyped,
  DossierFactCreate,
  DossierFactDetail,
  DossierFactUpdate,
  ProfileFactCreate,
  ProfileFactDetail,
  ProfileFactUpdate,
  OsintFactCreate,
  OsintFactDetail,
  OsintFactUpdate,
  RedactRequest,
  ContactChannel,
  GroupType,
} from "./generated/types.gen.js";

// Pydantic inlines these Literal unions into ClientSummary / InviteEvent
// rather than emitting them as named types; expose them so apps/web can
// match on string values without re-typing.
export type InviteStatus = "pending" | "consumed" | "cancelled" | "none";
export type InviteEventStatus =
  | "active"
  | "consumed"
  | "cancelled"
  | "superseded";

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

// /me/* — self-scoped client surfaces. Powers the basecamp page's empty/
// hydrated decision and the itinerary grid; no advisor gate.
export type {
  MyClientResponse,
  MyItinerariesResponse,
  MyItinerarySummary,
  MyOnboardingSessionResponse,
  OnboardingOpenerResponse,
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

export type RequestLoginDetail =
  | "auth_upstream_unavailable"
  | "validation_error"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for POST /auth/login. By design the server
 * collapses both "magic link sent" and "no account for this email"
 * into 204 (D015 enumeration guarantee), so `ok: true` here does not
 * prove an account exists — only that the UI should tell the user to
 * check their inbox.
 */
export type RequestLoginResult =
  | { ok: true }
  | { ok: false; status: number; detail: RequestLoginDetail };

/**
 * Typed wrapper for POST /auth/login. Asks the backend to email a
 * sign-in magic link for an existing account. Returns a result so
 * components can branch on `result.ok` without a try/catch.
 */
export async function requestLogin(
  client: Client,
  body: LoginRequest,
): Promise<RequestLoginResult> {
  try {
    const { error, response } = await loginEndpointAuthLoginPost({
      client,
      body,
    });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseRequestLoginDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseRequestLoginDetail(
  status: number,
  error: unknown,
): RequestLoginDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "auth_upstream_unavailable") return "auth_upstream_unavailable";
  if (status === 422) return "validation_error";
  if (status === 502) return "auth_upstream_unavailable";
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
 * Typed wrapper for POST /clients (create client + Dossier + invite).
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
      // Null on basecamp/onboarding-only sessions where no itinerary has
      // been minted yet — chat/[client_id] callers get one because
      // open_or_reuse_session eagerly creates one for that path.
      itinerary_id: string | null;
      // Echoed back from the row so basecamp can verify the persisted
      // opener matches what it asked for. Null on non-basecamp sessions.
      seeded_opener: string | null;
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
        seeded_opener: data.seeded_opener ?? null,
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
  | "forbidden"
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
  if (status === 403) return "forbidden";
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

export type UpdateNodePatch = {
  title?: string | null;
  source?: string | null;
  source_id?: string | null;
  status?: NodeStatus | null;
};

export type UpdateNodeArgs = {
  itineraryId: string;
  nodeId: string;
  patch: UpdateNodePatch;
};

/**
 * Typed wrapper for PATCH /itinerary/{itinerary_id}/nodes/{node_id} that
 * accepts an arbitrary partial update (title / source / source_id / status).
 * S08 consumes this from the advisor draft-editor surface to persist inline
 * node edits (e.g. hotel swaps). Status-only transitions should continue to
 * use ``updateNodeStatus`` — both wrappers share the same error-detail map.
 */
export async function updateNode(
  client: Client,
  args: UpdateNodeArgs,
): Promise<UpdateNodeResult> {
  try {
    const { data, error, response } =
      await updateNodeEndpointItineraryItineraryIdNodesNodeIdPatch({
        client,
        path: {
          itinerary_id: args.itineraryId,
          node_id: args.nodeId,
        },
        body: args.patch,
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

export type AcquireLockDetail =
  | "already_locked"
  | "advisor_only"
  | "itinerary_not_found"
  | "network_error"
  | "unknown";

export type AcquireLockResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: AcquireLockDetail };

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/lock (S08). Advisor-only;
 * 200 returns the updated itinerary carrying the new locked_by/locked_at,
 * 409 collapses to `already_locked`.
 */
export async function acquireItineraryLock(
  client: Client,
  itineraryId: string,
): Promise<AcquireLockResult> {
  try {
    const { data, error, response } =
      await lockItineraryEndpointItineraryItineraryIdLockPost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseAcquireLockDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseAcquireLockDetail(status: number): AcquireLockDetail {
  if (status === 409) return "already_locked";
  if (status === 403) return "advisor_only";
  if (status === 404) return "itinerary_not_found";
  return "unknown";
}

export type ReleaseLockDetail =
  | "advisor_only"
  | "itinerary_not_found"
  | "network_error"
  | "unknown";

export type ReleaseLockResult =
  | {
      ok: true;
      itinerary: ItineraryResponse;
      replayed_count: number;
    }
  | { ok: false; status: number; detail: ReleaseLockDetail };

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/release (S08). Clears
 * the advisor lock and drains any queued agent mutations; `replayed_count`
 * tells the UI how many queued writes were applied before returning.
 */
export async function releaseItineraryLock(
  client: Client,
  itineraryId: string,
): Promise<ReleaseLockResult> {
  try {
    const { data, error, response } =
      await releaseItineraryEndpointItineraryItineraryIdReleasePost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        itinerary: data.itinerary,
        replayed_count: data.replayed_count,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseReleaseLockDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseReleaseLockDetail(status: number): ReleaseLockDetail {
  if (status === 403) return "advisor_only";
  if (status === 404) return "itinerary_not_found";
  return "unknown";
}

export type ApproveItineraryDetail =
  | "already_approved"
  | "advisor_only"
  | "itinerary_not_found"
  | "network_error"
  | "unknown";

export type ApproveItineraryResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: ApproveItineraryDetail };

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/approve (S08). Advisor-
 * only; 409 collapses to `already_approved` when status is already
 * 'approved'.
 */
export async function approveItinerary(
  client: Client,
  itineraryId: string,
): Promise<ApproveItineraryResult> {
  try {
    const { data, error, response } =
      await approveItineraryEndpointItineraryItineraryIdApprovePost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseApproveItineraryDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseApproveItineraryDetail(status: number): ApproveItineraryDetail {
  if (status === 409) return "already_approved";
  if (status === 403) return "advisor_only";
  if (status === 404) return "itinerary_not_found";
  return "unknown";
}

export type AssembleDraftDetail =
  | "itinerary_not_found"
  | "already_locked"
  | "node_not_in_itinerary"
  | "node_not_proposed"
  | "validation_error"
  | "network_error"
  | "unknown";

export type AssembleDraftResult =
  | { ok: true; graph: GraphResponse }
  | { ok: false; status: number; detail: AssembleDraftDetail };

export type AssembleDraftDaySlot = {
  day_index: number;
  node_ids_in_order: string[];
};

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/assemble (S08). Accepts
 * an ordered per-day plan; the service layer promotes the caller to an
 * advisor actor when appropriate. 409 → `already_locked`, 400 →
 * `node_not_in_itinerary` / `node_not_proposed`, 422 → `validation_error`.
 */
export async function assembleInitialDraft(
  client: Client,
  itineraryId: string,
  day_plan: AssembleDraftDaySlot[],
): Promise<AssembleDraftResult> {
  try {
    const { data, error, response } =
      await assembleItineraryEndpointItineraryItineraryIdAssemblePost({
        client,
        path: { itinerary_id: itineraryId },
        body: { day_plan },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, graph: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseAssembleDraftDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseAssembleDraftDetail(
  status: number,
  error: unknown,
): AssembleDraftDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "already_locked") return "already_locked";
  if (raw === "node_not_in_itinerary") return "node_not_in_itinerary";
  if (raw === "node_not_proposed") return "node_not_proposed";
  if (status === 409) return "already_locked";
  if (status === 404) return "itinerary_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type ReissueInviteDetail =
  | "client_not_found"
  | "advisor_only"
  | "invite_already_redeemed"
  | "auth_upstream_unavailable"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for POST /clients/{client_id}/invite/reissue. The
 * server returns 204 on success; this wrapper turns that into `ok: true`
 * with no payload, mirroring the redeem-invite shape.
 */
export type ReissueInviteResult =
  | { ok: true }
  | { ok: false; status: number; detail: ReissueInviteDetail };

/**
 * Typed wrapper for POST /clients/{client_id}/invite/reissue.
 *
 * Supersedes any active invite for the client and emails a fresh link.
 * The server refuses with 409 (`invite_already_redeemed`) if the client
 * has already accepted a prior invite — at that point the magic-link flow
 * is the right path, not another invite.
 */
export async function reissueClientInvite(
  client: Client,
  clientId: string,
): Promise<ReissueInviteResult> {
  try {
    const { error, response } =
      await reissueClientInviteEndpointClientsClientIdInviteReissuePost({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseReissueInviteDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseReissueInviteDetail(
  status: number,
  error: unknown,
): ReissueInviteDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "invite_already_redeemed") return "invite_already_redeemed";
  if (raw === "auth_upstream_unavailable") return "auth_upstream_unavailable";
  if (raw === "advisor_only") return "advisor_only";
  if (status === 403) return "advisor_only";
  if (status === 404) return "client_not_found";
  if (status === 502) return "auth_upstream_unavailable";
  return "unknown";
}

export type CancelInviteDetail =
  | "client_not_found"
  | "advisor_only"
  | "no_active_invite"
  | "network_error"
  | "unknown";

export type CancelInviteResult =
  | { ok: true }
  | { ok: false; status: number; detail: CancelInviteDetail };

/**
 * Typed wrapper for POST /clients/{client_id}/invite/cancel.
 *
 * Marks the active invite cancelled with no email sent. Returns 409
 * (`no_active_invite`) when there's nothing to cancel — either the
 * client has already redeemed or the outstanding invite was already
 * cancelled / superseded.
 */
export async function cancelClientInvite(
  client: Client,
  clientId: string,
): Promise<CancelInviteResult> {
  try {
    const { error, response } =
      await cancelClientInviteEndpointClientsClientIdInviteCancelPost({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCancelInviteDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCancelInviteDetail(
  status: number,
  error: unknown,
): CancelInviteDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "no_active_invite") return "no_active_invite";
  if (raw === "advisor_only") return "advisor_only";
  if (status === 403) return "advisor_only";
  if (status === 404) return "client_not_found";
  if (status === 409) return "no_active_invite";
  return "unknown";
}

// ── Basecamp / onboarding ──────────────────────────────────────────────────

export type PickRandomOpenerResult =
  | { ok: true; opener: OnboardingOpenerResponse }
  | { ok: false; status: number; detail: "no_openers_configured" | "network_error" | "unknown" };

/**
 * Typed wrapper for GET /onboarding/openers/random.
 *
 * Server-side fetch from /basecamp's RSC: returns one curated open-ended
 * question to render as the single elegant prompt for a brand-new client.
 * 404 (`no_openers_configured`) is a deploy-time misconfiguration.
 */
export async function pickRandomOpener(
  client: Client,
): Promise<PickRandomOpenerResult> {
  try {
    const { data, error, response } =
      await randomOpenerEndpointOnboardingOpenersRandomGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, opener: data };
    }
    if (response.status === 404) {
      return { ok: false, status: 404, detail: "no_openers_configured" };
    }
    return { ok: false, status: response.status, detail: "unknown" };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type GetMyOnboardingSessionResult =
  | { ok: true; session: MyOnboardingSessionResponse }
  | { ok: false; status: number; detail: "network_error" | "unknown" };

/**
 * Typed wrapper for GET /me/onboarding_session.
 *
 * Returns the calling client's most-recent agent-session metadata —
 * `{ session_id, turn_count, last_turn_at, seeded_opener }`. All fields
 * are null/0 when no session has ever been opened. Basecamp uses
 * `turn_count > 0` as the "have we conversed?" signal.
 */
export async function getMyOnboardingSession(
  client: Client,
): Promise<GetMyOnboardingSessionResult> {
  try {
    const { data, error, response } =
      await getMyOnboardingSessionEndpointMeOnboardingSessionGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, session: data };
    }
    return { ok: false, status: response.status, detail: "unknown" };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Per-fact tier mutations (Dossier / Profile / OSINT) ───────────────────
//
// Three triplets, all advisor-only. The 201 / 200 / 204 status matrix
// collapses to `{ ok, fact? }` so apps/web can branch on `result.ok`
// without try/catch. Cross-advisor reads return 404 (D015 collapse).

export type FactMutationDetail =
  | "client_not_found"
  | "fact_not_found"
  | "advisor_only"
  | "validation_error"
  | "invalid_source_kind"
  | "network_error"
  | "unknown";

function _parseFactDetail(status: number, error: unknown): FactMutationDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "fact_not_found") return "fact_not_found";
  if (raw === "advisor_only") return "advisor_only";
  if (raw === "invalid_source_kind") return "invalid_source_kind";
  if (status === 400) return "invalid_source_kind";
  if (status === 403) return "advisor_only";
  if (status === 404) return "fact_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type CreateDossierFactResult =
  | { ok: true; fact: DossierFactDetail }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function createDossierFact(
  client: Client,
  clientId: string,
  body: DossierFactCreate,
): Promise<CreateDossierFactResult> {
  try {
    const { data, error, response } =
      await createDossierFactEndpointClientsClientIdDossierFactsPost({
        client,
        path: { client_id: clientId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, fact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type UpdateDossierFactResult =
  | { ok: true; fact: DossierFactDetail }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function updateDossierFact(
  client: Client,
  clientId: string,
  factId: string,
  body: DossierFactUpdate,
): Promise<UpdateDossierFactResult> {
  try {
    const { data, error, response } =
      await updateDossierFactEndpointClientsClientIdDossierFactsFactIdPatch({
        client,
        path: { client_id: clientId, fact_id: factId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, fact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type RedactFactResult =
  | { ok: true }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function redactDossierFact(
  client: Client,
  clientId: string,
  factId: string,
  body: RedactRequest,
): Promise<RedactFactResult> {
  try {
    const { error, response } =
      await redactDossierFactEndpointClientsClientIdDossierFactsFactIdDelete({
        client,
        path: { client_id: clientId, fact_id: factId },
        body,
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type CreateProfileFactResult =
  | { ok: true; fact: ProfileFactDetail }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function createProfileFact(
  client: Client,
  clientId: string,
  body: ProfileFactCreate,
): Promise<CreateProfileFactResult> {
  try {
    const { data, error, response } =
      await createProfileFactEndpointClientsClientIdProfileFactsPost({
        client,
        path: { client_id: clientId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, fact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type UpdateProfileFactResult =
  | { ok: true; fact: ProfileFactDetail }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function updateProfileFact(
  client: Client,
  clientId: string,
  factId: string,
  body: ProfileFactUpdate,
): Promise<UpdateProfileFactResult> {
  try {
    const { data, error, response } =
      await updateProfileFactEndpointClientsClientIdProfileFactsFactIdPatch({
        client,
        path: { client_id: clientId, fact_id: factId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, fact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function redactProfileFact(
  client: Client,
  clientId: string,
  factId: string,
  body: RedactRequest,
): Promise<RedactFactResult> {
  try {
    const { error, response } =
      await redactProfileFactEndpointClientsClientIdProfileFactsFactIdDelete({
        client,
        path: { client_id: clientId, fact_id: factId },
        body,
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type CreateOsintFactResult =
  | { ok: true; fact: OsintFactDetail }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function createOsintFact(
  client: Client,
  clientId: string,
  body: OsintFactCreate,
): Promise<CreateOsintFactResult> {
  try {
    const { data, error, response } =
      await createOsintFactEndpointClientsClientIdOsintFactsPost({
        client,
        path: { client_id: clientId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, fact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type UpdateOsintFactResult =
  | { ok: true; fact: OsintFactDetail }
  | { ok: false; status: number; detail: FactMutationDetail };

export async function updateOsintFact(
  client: Client,
  clientId: string,
  factId: string,
  body: OsintFactUpdate,
): Promise<UpdateOsintFactResult> {
  try {
    const { data, error, response } =
      await updateOsintFactEndpointClientsClientIdOsintFactsFactIdPatch({
        client,
        path: { client_id: clientId, fact_id: factId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, fact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function redactOsintFact(
  client: Client,
  clientId: string,
  factId: string,
  body: RedactRequest,
): Promise<RedactFactResult> {
  try {
    const { error, response } =
      await redactOsintFactEndpointClientsClientIdOsintFactsFactIdDelete({
        client,
        path: { client_id: clientId, fact_id: factId },
        body,
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseFactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListMyItinerariesResult =
  | { ok: true; itineraries: MyItinerarySummary[] }
  | { ok: false; status: number; detail: "network_error" | "unknown" };

/**
 * Typed wrapper for GET /me/itineraries.
 *
 * Returns the calling client's itineraries (draft + approved) ordered
 * newest-updated first. Powers basecamp's itinerary grid. Empty list is
 * a valid 200 — a client mid-onboarding has none yet.
 */
export async function listMyItineraries(
  client: Client,
): Promise<ListMyItinerariesResult> {
  try {
    const { data, error, response } =
      await listMyItinerariesEndpointMeItinerariesGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, itineraries: data.itineraries };
    }
    return { ok: false, status: response.status, detail: "unknown" };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}
