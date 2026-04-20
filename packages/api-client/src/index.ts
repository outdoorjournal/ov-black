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
import { redeemInviteEndpointAuthRedeemInvitePost } from "./generated/sdk.gen.js";
import type { RedeemInviteRequest } from "./generated/types.gen.js";

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

export interface ApiClientConfig {
  /** Base URL of the API — e.g. https://<alb-dns> or http://localhost:8000 */
  baseUrl: string;
}

/**
 * Build an API client bound to a specific base URL. Each call returns a
 * fresh instance so callers can scope clients per-request (server
 * components) without stepping on each other's auth headers later.
 */
export function createApiClient(config: ApiClientConfig): Client {
  return createClient({ baseUrl: config.baseUrl });
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
      detail: parseDetail(error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseDetail(error: unknown): RedeemInviteDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "invite_not_redeemable") return "invite_not_redeemable";
  if (raw === "invite_already_consumed") return "invite_already_consumed";
  if (raw === "auth_upstream_unavailable") return "auth_upstream_unavailable";
  if (raw === "internal_error") return "internal_error";
  return "unknown";
}
