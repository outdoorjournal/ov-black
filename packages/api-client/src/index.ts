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
  abandonForkEndpointItineraryForkIdAbandonPost,
  cancelReconcileEndpointItineraryForkIdCancelReconcilePost,
  approveAllNodesEndpointItineraryItineraryIdNodesApproveAllPost,
  retimeItineraryEndpointItineraryItineraryIdRetimePost,
  archiveClientPartyMemberEndpointClientsClientIdPartyMembersMemberIdDelete,
  archiveMyPartyMemberEndpointMePartyMembersMemberIdDelete,
  archiveClientDocumentEndpointClientsClientIdDocumentsDocumentIdDelete,
  archiveMyDocumentEndpointMeDocumentsDocumentIdDelete,
  assembleItineraryEndpointItineraryItineraryIdAssemblePost,
  attachItineraryPartyMemberEndpointItinerariesItineraryIdPartyMembersPost,
  cancelAnalysisEndpointItineraryItineraryIdAnalysesAnalysisIdCancelPost,
  completeClientDocumentEndpointClientsClientIdDocumentsDocumentIdCompletePost,
  completeMyDocumentEndpointMeDocumentsDocumentIdCompletePost,
  createClientContactEndpointClientsClientIdContactsPost,
  createClientEndpointClientsPost,
  createClientPartyMemberEndpointClientsClientIdPartyMembersPost,
  createDossierFactEndpointClientsClientIdDossierFactsPost,
  createEdgeEndpointItineraryItineraryIdEdgesPost,
  createItineraryEndpointItineraryPost,
  campaignKickoffEndpointItineraryItineraryIdCampaignKickoffPost,
  seedCampaignItineraryDemosCampaignCampaignIdPost,
  createMyPartyMemberEndpointMePartyMembersPost,
  createNodeEndpointItineraryItineraryIdNodesPost,
  createNodeFromInventoryEndpointItineraryItineraryIdNodesFromInventoryPost,
  createNodeFromLinkEndpointItineraryItineraryIdNodesFromLinkPost,
  getCollectionEndpointItineraryItineraryIdCollectionGet,
  exportItineraryEndpointItineraryItineraryIdExportGet,
  listDayNotesEndpointItineraryItineraryIdDayNotesGet,
  putDayNoteEndpointItineraryItineraryIdDayNotesDayDatePut,
  deleteDayNoteEndpointItineraryItineraryIdDayNotesDayDateDelete,
  generateDayNotesEndpointItineraryItineraryIdDayNotesGeneratePost,
  createOsintFactEndpointClientsClientIdOsintFactsPost,
  createProfileFactEndpointClientsClientIdProfileFactsPost,
  createSessionEndpointSessionsPost,
  openThreadEndpointThreadsPost,
  listMessagesEndpointThreadsThreadIdMessagesGet,
  sendMessageEndpointThreadsThreadIdMessagesPost,
  deleteClientContactEndpointClientsClientIdContactsContactIdDelete,
  deleteEdgeEndpointItineraryItineraryIdEdgesEdgeIdDelete,
  deleteNodeEndpointItineraryItineraryIdNodesNodeIdDelete,
  detachItineraryPartyMemberEndpointItinerariesItineraryIdPartyMembersMemberIdDelete,
  diffForkEndpointItineraryForkIdDiffGet,
  forkItineraryEndpointItineraryItineraryIdForkPost,
  createInvoiceEndpointItineraryItineraryIdInvoicesPost,
  createDepositInvoiceEndpointItineraryItineraryIdInvoicesDepositPost,
  createFinalInvoiceEndpointItineraryItineraryIdInvoicesFinalPost,
  listInvoicesEndpointItineraryItineraryIdInvoicesGet,
  getInvoiceEndpointInvoicesInvoiceIdGet,
  addLineItemEndpointInvoicesInvoiceIdLineItemsPost,
  voidLineItemEndpointInvoicesInvoiceIdLineItemsLineIdVoidPost,
  deleteLineItemEndpointInvoicesInvoiceIdLineItemsLineIdDelete,
  issueInvoiceEndpointInvoicesInvoiceIdIssuePost,
  voidInvoiceEndpointInvoicesInvoiceIdVoidPost,
  paymentTokenEndpointInvoicesInvoiceIdPaymentTokenPost,
  invoicePayContextEndpointInvoicesInvoiceIdPayContextGet,
  paymentQuoteEndpointInvoicesInvoiceIdPaymentQuotePost,
  payInvoiceEndpointInvoicesInvoiceIdPayPost,
  refreshOfferEndpointItineraryItineraryIdNodesNodeIdOffersRefreshPost,
  listOffersEndpointItineraryItineraryIdNodesNodeIdOffersGet,
  nodeChargesEndpointItineraryItineraryIdNodesNodeIdChargesGet,
  bookNodeEndpointItineraryItineraryIdNodesNodeIdBookPost,
  cancelNodeEndpointItineraryItineraryIdNodesNodeIdCancelPost,
  confirmNodeEndpointItineraryItineraryIdNodesNodeIdConfirmPost,
  supplierAvailabilityEndpointItineraryItineraryIdNodesNodeIdSupplierAvailabilityGet,
  reconciliationEndpointItineraryItineraryIdReconciliationGet,
  dismissOnboardingEndpointOnboardingDismissPost,
  downloadClientDocumentEndpointClientsClientIdDocumentsDocumentIdDownloadGet,
  downloadMyDocumentEndpointMeDocumentsDocumentIdDownloadGet,
  fillGapEndpointItineraryItineraryIdFillPost,
  getAnalysisEndpointItineraryItineraryIdAnalysesAnalysisIdGet,
  getClientEndpointClientsClientIdGet,
  updateClientEndpointClientsClientIdPatch,
  getItineraryEndpointItineraryItineraryIdGet,
  updateItineraryEndpointItineraryItineraryIdPatch,
  getMyOnboardingSessionEndpointMeOnboardingSessionGet,
  addToReadingListEndpointMeReadingListPost,
  getAwarenessEndpointAwarenessGet,
  getAdvisorOverviewEndpointAdvisorOverviewGet,
  getAdvisorActivityEndpointAdvisorActivityGet,
  getAdvisorMoneyEndpointAdvisorMoneyGet,
  getItineraryChangesEndpointItineraryItineraryIdChangesGet,
  getClientAwarenessEndpointAwarenessClientsClientIdGet,
  initClientDocumentEndpointClientsClientIdDocumentsPost,
  initMyDocumentEndpointMeDocumentsPost,
  listAdvisorItinerariesEndpointItinerariesGet,
  listAnalysesEndpointItineraryItineraryIdAnalysesGet,
  listClientDocumentsEndpointClientsClientIdDocumentsGet,
  listClientPartyMembersEndpointClientsClientIdPartyMembersGet,
  listClientSessionsEndpointClientsClientIdSessionsGet,
  listClientsEndpointClientsGet,
  listItineraryDocumentsEndpointItinerariesItineraryIdDocumentsGet,
  listItineraryPartyEndpointItinerariesItineraryIdPartyGet,
  listMyDocumentsEndpointMeDocumentsGet,
  listMyInvoicesEndpointMeInvoicesGet,
  listMyItinerariesEndpointMeItinerariesGet,
  listMyPartyMembersEndpointMePartyMembersGet,
  listSessionsEndpointSessionsGet,
  listTurnsEndpointSessionsSessionIdTurnsGet,
  patchSessionEndpointSessionsSessionIdPatch,
  lockItineraryEndpointItineraryItineraryIdLockPost,
  loginEndpointAuthLoginPost,
  randomOpenerEndpointOnboardingOpenersRandomGet,
  redactDossierFactEndpointClientsClientIdDossierFactsFactIdDelete,
  redactOsintFactEndpointClientsClientIdOsintFactsFactIdDelete,
  redactProfileFactEndpointClientsClientIdProfileFactsFactIdDelete,
  reconcileForkEndpointItineraryForkIdReconcilePost,
  releaseItineraryEndpointItineraryItineraryIdReleasePost,
  requestReconcileEndpointItineraryForkIdRequestReconcilePost,
  listInventorySourcesEndpointInventorySourcesGet,
  resendWelcomeEndpointClientsClientIdResendWelcomePost,
  searchInventoryEndpointSearchInventoryGet,
  placeBriefPlacesBriefPost,
  startAnalysisEndpointItineraryItineraryIdAnalysesPost,
  updateClientContactEndpointClientsClientIdContactsContactIdPatch,
  updateClientDocumentEndpointClientsClientIdDocumentsDocumentIdPatch,
  updateClientPartyMemberEndpointClientsClientIdPartyMembersMemberIdPatch,
  updateDossierFactEndpointClientsClientIdDossierFactsFactIdPatch,
  updateMyDocumentEndpointMeDocumentsDocumentIdPatch,
  updateMyPartyMemberEndpointMePartyMembersMemberIdPatch,
  updateNodeEndpointItineraryItineraryIdNodesNodeIdPatch,
  updateOsintFactEndpointClientsClientIdOsintFactsFactIdPatch,
  updateProfileFactEndpointClientsClientIdProfileFactsFactIdPatch,
} from "./generated/sdk.gen.js";
import type {
  AdvisorItinerarySummary,
  AgentTurnSummary,
  AnalysisCreatedResponse,
  AnalysisDetailResponse,
  AnalysisSummaryResponse,
  AttentionItemOut,
  AwarenessResponse,
  ClientAttentionOut,
  ActivityEventOut,
  AdvisorMoneyResponse,
  AdvisorOverviewResponse,
  ChangeOut,
  MoneyRowOut,
  MoneySummaryRowOut,
  ClientContactCreate,
  ClientContactDetail,
  ClientContactUpdate,
  ClientCreatePayload,
  ClientDetail,
  CampaignKickoffResponse,
  CampaignSeedResponse,
  ClientSessionSummary,
  ClientSummary,
  ClientUpdatePayload,
  CreateEdgeRequest,
  CreateItineraryRequest,
  CreateNodeRequest,
  DisplayStatus,
  DossierFactCreate,
  DossierFactDetail,
  DossierFactUpdate,
  EdgeResponse,
  FillRequest,
  FillResponse,
  ForkDiffResponse,
  GraphResponse,
  ItineraryResponse,
  UpdateItineraryRequest,
  RetimeItineraryRequest,
  AddLineItemRequest,
  CreateInvoiceRequest,
  InvoiceResponse,
  InvoiceLineItemResponse,
  PayInvoiceRequest,
  InvoicePayContextResponse,
  PaymentResponse,
  PaymentTokenResponse,
  BookNodeRequest,
  BookingResponse,
  CancelBookingRequest,
  NodeChargesResponse,
  OfferResponse,
  RecordConfirmationRequest,
  ReconciliationResponse,
  SupplierAvailabilityResponse,
  MyInvoiceSummary,
  MyInvoicesResponse,
  NodeChangeResponse,
  ReconcileOutcomeResponse,
  ReconcileRequest,
  ReconcileResponse,
  RequestReconcileRequest,
  LoginRequest,
  MyItinerarySummary,
  MyOnboardingSessionResponse,
  NodeResponse,
  NodeStatus,
  NodeType,
  CostKind,
  OnboardingOpenerResponse,
  OpenSessionRequest,
  OpenSessionResponse,
  PatchSessionRequest,
  ReadingListAddRequest,
  SessionSummary,
  OpenThreadRequest,
  ThreadSummary,
  SendMessageRequest,
  MessageSummary,
  AttachPartyMemberRequest,
  DocumentCompleteRequest,
  DocumentDetail,
  DocumentDownloadResponse,
  DocumentInitRequest,
  DocumentInitResponse,
  DocumentUpdate,
  ItineraryPartyResponse,
  OsintFactCreate,
  OsintFactDetail,
  OsintFactUpdate,
  PartyMemberCreate,
  PartyMemberDetail,
  PartyMemberUpdate,
  ProfileFactCreate,
  ProfileFactDetail,
  ProfileFactUpdate,
  RedactRequest,
  SearchInventoryEndpointSearchInventoryGetData,
  SearchInventoryResponse,
  SearchSourceDiagnostics,
  StartAnalysisRequest,
} from "./generated/types.gen.js";

export type { LoginRequest } from "./generated/types.gen.js";
export type { Client } from "./generated/client/types.gen.js";

// Itinerary graph (S02): create + read + node/edge mutation contracts and
// the assembled GraphResponse view consumed by apps/web.
export type {
  CreateItineraryRequest,
  UpdateItineraryRequest,
  RetimeItineraryRequest,
  RetimeItineraryResponse,
  ItineraryResponse,
  DisplayStatus,
  ItineraryTimingKind,
  CreateNodeRequest,
  UpdateNodeRequest,
  NodeResponse,
  CreateEdgeRequest,
  EdgeResponse,
  GraphResponse,
  NodeStatus,
  NodeType,
  CostKind,
  EdgeType,
  // Phase 4 (doc/itin-time.md): server-resolved schedule views + the
  // (day_index, minute_of_day) placement write shape.
  ResolvedScheduleResponse,
  ResolvedStampResponse,
  SchedulePlacementPayload,
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
  SearchSourceDiagnostics,
  InventorySourcesResponse,
} from "./generated/types.gen.js";

// Analyze (B5) + Fill (B6) + from-inventory authoring (B7). The advisor
// authoring surface renders findings (severity / category / evidence) and
// ranked Fill proposals, and adds inventory results as nodes — so apps/web
// types these from one module. SearchInventoryResponse is re-exported above.
export type {
  StartAnalysisRequest,
  AnalysisCreatedResponse,
  AnalysisSummaryResponse,
  AnalysisDetailResponse,
  AnalysisStatus,
  AnalysisDepth,
  FindingResponse,
  FindingSeverity,
  FillRequest,
  FillResponse,
  FillProposalResponse,
  GapModel,
  GeoPointResponse,
  CreateNodeFromInventoryRequest,
} from "./generated/types.gen.js";

// Fork diff / reconcile (M004/G3). The advisor diff view renders the four
// buckets (NodeChangeResponse) side by side, runs the feasibility gate, and
// reconciles a per-change selection; the per-change ReconcileOutcomeResponse
// reports applied / refused_booked honestly. Re-exported so apps/web types the
// DiffPanel from one module.
export type {
  ForkDiffResponse,
  NodeChangeResponse,
  ReconcileRequest,
  ReconcileResponse,
  ReconcileOutcomeResponse,
  RequestReconcileRequest,
} from "./generated/types.gen.js";

// Invoices (M005/I1). One itinerary -> N invoices; the InvoiceResponse carries
// the signed ledger (InvoiceLineItemResponse[]) and the computed total. The
// advisor InvoicePanel types its assemble/issue/void surface from one module.
export type {
  CreateInvoiceRequest,
  AddLineItemRequest,
  InvoiceResponse,
  InvoiceLineItemResponse,
  InvoiceStatus,
  InvoiceLineKind,
  PayInvoiceRequest,
  InvoicePayContextResponse,
  PaymentResponse,
  PaymentTokenResponse,
  PaymentStatus,
} from "./generated/types.gen.js";

// Bookings + money gate (M005/I3). The committed BookingResponse, a repriceable
// OfferResponse, the BookNode/RecordConfirmation requests, and the
// ReconciliationResponse (Σ paid ⇔ Σ booked) the advisor BookingPanel reads.
export type {
  BookNodeRequest,
  BookingResponse,
  CancelBookingRequest,
  NodeChargesResponse,
  OfferResponse,
  RecordConfirmationRequest,
  ReconciliationResponse,
  ReconciliationRowResponse,
  ReconciliationViolationResponse,
  // Real supplier booking (Bokun): the availability slots + the selection the
  // advisor picks to reserve+confirm upstream through the money gate.
  SupplierAvailabilityResponse,
  SupplierCategoryPriceResponse,
  SupplierSelectionRequest,
  PricingCategoryRequest,
} from "./generated/types.gen.js";

// Clients (S03): advisor-facing /clients surface — the request/response
// shapes plus the nested Dossier and per-fact tier types. Re-exported so
// apps/web can type forms + list/detail views from a single module.
export type {
  ClientCreatePayload,
  ClientCreateResponse,
  ClientSummary,
  ClientDetail,
  ClientUpdatePayload,
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
  ContactKind,
  ClientContactCreate,
  ClientContactDetail,
  ClientContactUpdate,
} from "./generated/types.gen.js";

// Party members (M003/V1): the durable, household-scoped traveler roster,
// authored collaboratively by advisor (/clients/{id}/party-members), traveler
// (/me/party-members), and agent. Plus the per-trip participation shapes for
// the "who's traveling" attach on an itinerary. Re-exported so apps/web can
// type the traveler form, the advisor completeness panel, and the attach UI.
export type {
  PartyMemberCreate,
  PartyMemberUpdate,
  PartyMemberDetail,
  PartyMemberListResponse,
  PartyMemberActor,
  LoyaltyProgram,
  EmergencyContact,
  AttachPartyMemberRequest,
  ItineraryPartyEntry,
  ItineraryPartyResponse,
} from "./generated/types.gen.js";

// Document vault (M003/V3): the secure, household-scoped document store. Upload
// is a two-step presigned flow (init → browser PUT to S3 → complete); reads mint
// a presigned GET. Re-exported so apps/web can type the upload form + the
// traveler/advisor vault surfaces. Detail shapes never carry the S3 key.
export type {
  DocumentType,
  DocumentActor,
  DocumentInitRequest,
  DocumentInitResponse,
  DocumentUpdate,
  DocumentDetail,
  DocumentListResponse,
  DocumentCompleteRequest,
  DocumentDownloadResponse,
} from "./generated/types.gen.js";

// Advisor /itineraries (plural) — rich roster row with embedded client.
// Distinct namespace from the singular /itinerary CRUD and the lean
// /me/itineraries shape.
export type {
  AdvisorItineraryClient,
  AdvisorItinerarySummary,
  AdvisorItinerariesResponse,
  ClientSessionSummary,
  ClientSessionsResponse,
} from "./generated/types.gen.js";

// Pydantic inlines this Literal union into ClientSummary / ClientDetail
// rather than emitting it as a named type; expose it so apps/web can match
// on string values without re-typing. "uninvited" while created silently
// (no welcome link issued), "pending" once invited and awaiting first login
// (which stamps accepted_at), "active" after.
export type AccessStatus = "uninvited" | "pending" | "active";

// Agent sessions (S04): POST /sessions request/response + the replay shape
// for GET /sessions/{id}/turns. The SSE stream for /turn is consumed by a
// DIY reader in apps/web (S05) — only the non-streaming surfaces are typed
// here.
export type {
  OpenSessionRequest,
  OpenSessionResponse,
  PatchSessionRequest,
  SessionSummary,
  TurnRequest,
  AgentTurnSummary,
  TurnRole,
} from "./generated/types.gen.js";

// Human messaging channel (M006/PS7): the /threads surface — get-or-create a
// scoped human thread, list its messages, and post one human message (no agent
// turn). Artemis-in-thread is the later PS8 bridge.
export type {
  OpenThreadRequest,
  ThreadSummary,
  SendMessageRequest,
  MessageSummary,
  ThreadActorKind,
} from "./generated/types.gen.js";

// /me/* — self-scoped client surfaces. Powers the basecamp page's empty/
// hydrated decision and the itinerary grid; no advisor gate.
export type {
  MyClientResponse,
  MyInvoiceSummary,
  MyInvoicesResponse,
  MyItinerariesResponse,
  MyItinerarySummary,
  MyOnboardingSessionResponse,
  OnboardingOpenerResponse,
} from "./generated/types.gen.js";

/**
 * A Supabase access token, or a getter that resolves the *current* one.
 *
 * A bare string is captured once — correct for server components / server
 * actions, which build a fresh client per request from a just-read session.
 * A getter is for long-lived browser clients: it's called on every request,
 * so a page held open past the token's ~1h TTL sends the refreshed token
 * (from `supabase.auth.getSession()`) instead of the stale one it rendered
 * with. Returning null/undefined sends no `Authorization` header.
 */
export type AccessTokenInput =
  | string
  | (() => string | null | undefined | Promise<string | null | undefined>);

export interface ApiClientConfig {
  /** Base URL of the API — e.g. https://<alb-dns> or http://localhost:8000 */
  baseUrl: string;
  /**
   * Supabase access token forwarded as `Authorization: Bearer <token>` on
   * every request via a @hey-api client request interceptor. Omit for
   * unauthenticated flows (the invite-redeem call still runs without one).
   * Pass a getter (see {@link AccessTokenInput}) to track a live session.
   */
  accessToken?: AccessTokenInput;
}

/**
 * Build an API client bound to a specific base URL. Each call returns a
 * fresh instance so callers can scope clients per-request (server
 * components) without stepping on each other's auth headers later.
 *
 * When `accessToken` is provided, a @hey-api request interceptor is
 * registered that stamps `Authorization: Bearer <token>` on every outgoing
 * Request, resolving a getter per-request so browser clients always send the
 * current session token. No header is set when the token resolves empty,
 * which is intentional: POST /auth/redeem-invite runs unauthenticated.
 */
export function createApiClient(config: ApiClientConfig): Client {
  const client = createClient({ baseUrl: config.baseUrl });
  const token = config.accessToken;
  if (token !== undefined) {
    client.interceptors.request.use(async (request) => {
      const resolved = typeof token === "function" ? await token() : token;
      if (resolved) {
        request.headers.set("Authorization", `Bearer ${resolved}`);
      }
      return request;
    });
  }
  return client;
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
 * Typed wrapper for POST /clients (create client + Dossier; emails a
 * code-free welcome sign-in link). The 201 body carries `client_id` +
 * `email`.
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
        email: data.email,
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

/** Optional roster query params for GET /clients (Wave F). */
export type ListClientsParams = {
  limit?: number;
  cursor?: string;
  q?: string;
  status?: AccessStatus;
  sort?: "created_at" | "full_name";
  order?: "asc" | "desc";
};

/**
 * Discriminated result for GET /clients. 403 collapses to `advisor_only`
 * — there is no 409/502 path on the read side.
 *
 * Wave F (BREAKING): the roster is an envelope — `clients` plus a keyset
 * `next_cursor` (null on the last page) and the filter-scoped `total`.
 */
export type ListClientsResult =
  | { ok: true; clients: ClientSummary[]; nextCursor: string | null; total: number }
  | { ok: false; status: number; detail: ListClientsDetail };

/**
 * Typed wrapper for GET /clients — searchable, keyset-paged roster.
 * No params → first page of 50, newest first.
 */
export async function listClients(
  client: Client,
  params?: ListClientsParams,
): Promise<ListClientsResult> {
  try {
    const { data, error, response } = await listClientsEndpointClientsGet({
      client,
      query: {
        ...(params?.limit !== undefined ? { limit: params.limit } : {}),
        ...(params?.cursor !== undefined ? { cursor: params.cursor } : {}),
        ...(params?.q !== undefined ? { q: params.q } : {}),
        ...(params?.status !== undefined ? { status: params.status } : {}),
        ...(params?.sort !== undefined ? { sort: params.sort } : {}),
        ...(params?.order !== undefined ? { order: params.order } : {}),
      },
    });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        clients: data.clients,
        nextCursor: data.next_cursor ?? null,
        total: data.total,
      };
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

/**
 * Typed wrapper for PATCH /clients/{client_id} — the traveler-logistics
 * fields (address, favorite_airport, preferred_currency). Only the keys
 * present in `payload` are applied server-side. Returns the refreshed
 * ClientDetail on success (same not-found shape as GET).
 */
export async function updateClient(
  client: Client,
  clientId: string,
  payload: ClientUpdatePayload,
): Promise<GetClientResult> {
  try {
    const { data, error, response } =
      await updateClientEndpointClientsClientIdPatch({
        client,
        path: { client_id: clientId },
        body: payload,
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

export type { AttentionItemOut, AwarenessResponse, ClientAttentionOut };

export type AwarenessDetail = "advisor_only" | "network_error" | "unknown";

/**
 * Discriminated result for GET /awareness — the advisor's per-client
 * attention rollup (ADV-14). 403 collapses to `advisor_only`.
 */
export type AwarenessResult =
  | { ok: true; clients: ClientAttentionOut[] }
  | { ok: false; status: number; detail: AwarenessDetail };

/**
 * Typed wrapper for GET /awareness — every client of the calling advisor with
 * a live attention signal, newest-first. Powers the Command Center roster
 * badges; the caller merges by `client_id` onto its roster rows.
 */
export async function getAwareness(client: Client): Promise<AwarenessResult> {
  try {
    const { data, error, response } = await getAwarenessEndpointAwarenessGet({
      client,
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, clients: data.clients };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 403 ? "advisor_only" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

/**
 * Discriminated result for GET /awareness/clients/{client_id} — one client's
 * attention feed (empty when nothing is pending). Powers the client-detail
 * strip.
 */
export type ClientAwarenessResult =
  | { ok: true; attention: ClientAttentionOut }
  | { ok: false; status: number; detail: AwarenessDetail };

/**
 * Typed wrapper for GET /awareness/clients/{client_id}.
 */
export async function getClientAwareness(
  client: Client,
  clientId: string,
): Promise<ClientAwarenessResult> {
  try {
    const { data, error, response } =
      await getClientAwarenessEndpointAwarenessClientsClientIdGet({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, attention: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 403 ? "advisor_only" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}


// ── Advisor ops surface (Wave F): overview / activity / money / changes ─────

export type {
  ActivityEventOut,
  AdvisorMoneyResponse,
  AdvisorOverviewResponse,
  ChangeOut,
  MoneyRowOut,
  MoneySummaryRowOut,
};

export type AdvisorOpsDetail =
  | "advisor_only"
  | "invalid_cursor"
  | "network_error"
  | "unknown";

function _parseAdvisorOpsDetail(status: number, error: unknown): AdvisorOpsDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "invalid_cursor") return "invalid_cursor";
  if (status === 403) return "advisor_only";
  return "unknown";
}

/** Discriminated result for GET /advisor/overview — the Ops glance band. */
export type AdvisorOverviewResult =
  | { ok: true; overview: AdvisorOverviewResponse }
  | { ok: false; status: number; detail: AdvisorOpsDetail };

/** Typed wrapper for GET /advisor/overview. */
export async function getAdvisorOverview(
  client: Client,
): Promise<AdvisorOverviewResult> {
  try {
    const { data, error, response } =
      await getAdvisorOverviewEndpointAdvisorOverviewGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, overview: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseAdvisorOpsDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

/** Optional query params for GET /advisor/activity. */
export type AdvisorActivityParams = {
  limit?: number;
  cursor?: string;
  clientId?: string;
  itineraryId?: string;
  /** Comma-joined server-side; unknown names are a 400. */
  kinds?: string[];
};

/** Discriminated result for GET /advisor/activity — the merged event feed. */
export type AdvisorActivityResult =
  | { ok: true; events: ActivityEventOut[]; nextCursor: string | null }
  | { ok: false; status: number; detail: AdvisorOpsDetail };

/**
 * Typed wrapper for GET /advisor/activity — newest-first merged roster
 * activity, keyset-paged. The live tail of the same projection streams over
 * GET /advisor/feed (SSE, consumed by a DIY reader in apps/web).
 */
export async function getAdvisorActivity(
  client: Client,
  params?: AdvisorActivityParams,
): Promise<AdvisorActivityResult> {
  try {
    const { data, error, response } =
      await getAdvisorActivityEndpointAdvisorActivityGet({
        client,
        query: {
          ...(params?.limit !== undefined ? { limit: params.limit } : {}),
          ...(params?.cursor !== undefined ? { cursor: params.cursor } : {}),
          ...(params?.clientId !== undefined
            ? { client_id: params.clientId }
            : {}),
          ...(params?.itineraryId !== undefined
            ? { itinerary_id: params.itineraryId }
            : {}),
          ...(params?.kinds !== undefined && params.kinds.length > 0
            ? { kinds: params.kinds.join(",") }
            : {}),
        },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        events: data.events,
        nextCursor: data.next_cursor ?? null,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseAdvisorOpsDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

/** Optional query params for GET /advisor/money. */
export type AdvisorMoneyParams = {
  limit?: number;
  cursor?: string;
  status?: "draft" | "issued" | "paid" | "void";
  clientId?: string;
};

/** Discriminated result for GET /advisor/money — the cross-client roster. */
export type AdvisorMoneyResult =
  | {
      ok: true;
      invoices: MoneyRowOut[];
      summary: MoneySummaryRowOut[];
      nextCursor: string | null;
    }
  | { ok: false; status: number; detail: AdvisorOpsDetail };

/**
 * Typed wrapper for GET /advisor/money — every invoice across the roster
 * with client/trip identity, plus the whole-roster per-currency band.
 */
export async function getAdvisorMoney(
  client: Client,
  params?: AdvisorMoneyParams,
): Promise<AdvisorMoneyResult> {
  try {
    const { data, error, response } =
      await getAdvisorMoneyEndpointAdvisorMoneyGet({
        client,
        query: {
          ...(params?.limit !== undefined ? { limit: params.limit } : {}),
          ...(params?.cursor !== undefined ? { cursor: params.cursor } : {}),
          ...(params?.status !== undefined ? { status: params.status } : {}),
          ...(params?.clientId !== undefined
            ? { client_id: params.clientId }
            : {}),
        },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        invoices: data.invoices,
        summary: data.summary,
        nextCursor: data.next_cursor ?? null,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseAdvisorOpsDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ItineraryChangesDetail =
  | "not_found"
  | "forbidden"
  | "invalid_cursor"
  | "network_error"
  | "unknown";

/** Discriminated result for GET /itinerary/{id}/changes — history replay. */
export type ItineraryChangesResult =
  | { ok: true; changes: ChangeOut[]; nextCursor: string | null }
  | { ok: false; status: number; detail: ItineraryChangesDetail };

/**
 * Typed wrapper for GET /itinerary/{id}/changes — the graph's audit trail,
 * newest-first, projected (never raw before/after payloads). Gated exactly
 * like the graph read.
 */
export async function getItineraryChanges(
  client: Client,
  itineraryId: string,
  params?: { limit?: number; cursor?: string; entity?: "node" | "edge" },
): Promise<ItineraryChangesResult> {
  try {
    const { data, error, response } =
      await getItineraryChangesEndpointItineraryItineraryIdChangesGet({
        client,
        path: { itinerary_id: itineraryId },
        query: {
          ...(params?.limit !== undefined ? { limit: params.limit } : {}),
          ...(params?.cursor !== undefined ? { cursor: params.cursor } : {}),
          ...(params?.entity !== undefined ? { entity: params.entity } : {}),
        },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        changes: data.changes,
        nextCursor: data.next_cursor ?? null,
      };
    }
    const body = error as { detail?: unknown } | undefined;
    const raw = body && typeof body.detail === "string" ? body.detail : "";
    const detail: ItineraryChangesDetail =
      raw === "invalid_cursor"
        ? "invalid_cursor"
        : response.status === 404
          ? "not_found"
          : response.status === 403
            ? "forbidden"
            : "unknown";
    return { ok: false, status: response.status, detail };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
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
 * Typed wrapper for GET /sessions/{id}/turns — a session's turns in
 * turn_index order. No params → every turn (the chat replay path). Wave F:
 * `limit` returns the most recent N (still ascending); `beforeIndex` pages
 * older — the next page's cursor is the first returned row's `turn_index`.
 */
export async function listTurns(
  client: Client,
  sessionId: string,
  params?: { limit?: number; beforeIndex?: number },
): Promise<ListTurnsResult> {
  try {
    const { data, error, response } =
      await listTurnsEndpointSessionsSessionIdTurnsGet({
        client,
        path: { session_id: sessionId },
        query: {
          ...(params?.limit !== undefined ? { limit: params.limit } : {}),
          ...(params?.beforeIndex !== undefined
            ? { before_index: params.beforeIndex }
            : {}),
        },
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

// ── Human messaging channel (M006/PS7) ──────────────────────────────────────

export type OpenThreadDetail = "thread_not_found" | "network_error" | "unknown";

/** Discriminated result for POST /threads — get-or-create the human thread. */
export type OpenThreadResult =
  | { ok: true; thread: ThreadSummary }
  | { ok: false; status: number; detail: OpenThreadDetail };

/**
 * Typed wrapper for POST /threads. Get-or-creates the single human thread for a
 * scope: omit `itineraryId` for the basecamp channel (you ↔ advisor), pass it
 * for that trip's thread (you ↔ advisor ↔ party). Idempotent — create vs reuse
 * is indistinguishable. A cross-tenant / foreign scope collapses to 404.
 */
export async function openThread(
  client: Client,
  body: { clientId: string; itineraryId?: string | null },
): Promise<OpenThreadResult> {
  try {
    const { data, error, response } = await openThreadEndpointThreadsPost({
      client,
      body: {
        client_id: body.clientId,
        ...(body.itineraryId != null ? { itinerary_id: body.itineraryId } : {}),
      },
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, thread: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 404 ? "thread_not_found" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListMessagesDetail =
  | "thread_not_found"
  | "network_error"
  | "unknown";

/** Discriminated result for GET /threads/{id}/messages. */
export type ListMessagesResult =
  | { ok: true; messages: MessageSummary[] }
  | { ok: false; status: number; detail: ListMessagesDetail };

/**
 * Typed wrapper for GET /threads/{id}/messages — the thread's human messages,
 * oldest first. A thread not accessible to the caller collapses to 404.
 */
export async function listMessages(
  client: Client,
  threadId: string,
): Promise<ListMessagesResult> {
  try {
    const { data, error, response } =
      await listMessagesEndpointThreadsThreadIdMessagesGet({
        client,
        path: { thread_id: threadId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, messages: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 404 ? "thread_not_found" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type SendMessageDetail =
  | "thread_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

/** Discriminated result for POST /threads/{id}/messages. */
export type SendMessageResult =
  | { ok: true; message: MessageSummary }
  | { ok: false; status: number; detail: SendMessageDetail };

/**
 * Typed wrapper for POST /threads/{id}/messages — post one HUMAN message. No
 * agent turn: this is the human channel (Artemis is summoned only in PS8).
 */
export async function sendMessage(
  client: Client,
  threadId: string,
  body: SendMessageRequest,
): Promise<SendMessageResult> {
  try {
    const { data, error, response } =
      await sendMessageEndpointThreadsThreadIdMessagesPost({
        client,
        path: { thread_id: threadId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, message: data };
    }
    return {
      ok: false,
      status: response.status,
      detail:
        response.status === 404
          ? "thread_not_found"
          : response.status === 422
            ? "validation_error"
            : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListSessionsDetail =
  | "client_not_found"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for GET /sessions — the scoped, resumable Artemis
 * session list (M006/PS2).
 */
export type ListSessionsResult =
  | { ok: true; sessions: SessionSummary[] }
  | { ok: false; status: number; detail: ListSessionsDetail };

/**
 * Typed wrapper for GET /sessions. Scope = (client + audience + itinerary);
 * archived sessions are excluded and the list is newest-first. A traveler
 * probing the advisor audience collapses to 404 (existence-hiding).
 */
export async function listSessions(
  client: Client,
  query: {
    clientId: string;
    audience?: OpenSessionRequest["audience"];
    itineraryId?: string | null;
  },
): Promise<ListSessionsResult> {
  try {
    const { data, error, response } = await listSessionsEndpointSessionsGet({
      client,
      query: {
        client_id: query.clientId,
        ...(query.audience ? { audience: query.audience } : {}),
        ...(query.itineraryId != null ? { itinerary_id: query.itineraryId } : {}),
      },
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, sessions: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 404 ? "client_not_found" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type PatchSessionDetail =
  | "session_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for PATCH /sessions/{id}.
 */
export type PatchSessionResult =
  | { ok: true; session: SessionSummary }
  | { ok: false; status: number; detail: PatchSessionDetail };

/**
 * Typed wrapper for PATCH /sessions/{id} — rename and/or (un)archive a
 * session (M006/PS2). Both fields optional; omitted means "leave as is".
 */
export async function patchSession(
  client: Client,
  sessionId: string,
  body: PatchSessionRequest,
): Promise<PatchSessionResult> {
  try {
    const { data, error, response } =
      await patchSessionEndpointSessionsSessionIdPatch({
        client,
        path: { session_id: sessionId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, session: data };
    }
    return {
      ok: false,
      status: response.status,
      detail:
        response.status === 404
          ? "session_not_found"
          : response.status === 422
            ? "validation_error"
            : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
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
      // Per-currency price of the plan (ADV-10): `{ currency: amount }` summed
      // over priced, non-discarded, selected nodes (per-person expanded by party
      // size). Amounts are strings like `cost_amount`; `{}` when nothing priced.
      totals: Record<string, string>;
      // 0048: the traveler's preferred display currency and the plan's total
      // converted into it. Both null when the client has no preferred currency
      // or FX can't resolve — the UI then falls back to the native `totals`.
      display_currency: string | null;
      total_display: string | null;
      // The itinerary's effective traveler count (floored at 1), matching the
      // party expansion applied to `per_person` costs. Lets the billing UI derive
      // a node's effective cost (and thus its remaining balance) client-side.
      party_size: number;
      // The caller's own open fork of this baseline ("My version"), when present
      // — drives the traveler's two-version toggle. Null on a fork or when none.
      viewer_open_fork_id: string | null;
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
        totals: data.totals ?? {},
        display_currency: data.display_currency ?? null,
        total_display: data.total_display ?? null,
        party_size: data.party_size ?? 1,
        viewer_open_fork_id: data.viewer_open_fork_id ?? null,
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

export type CreateItineraryResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: "validation_error" | "network_error" | "unknown" };

/**
 * Typed wrapper for POST /itinerary. Creates an empty itinerary container —
 * the entry point for a traveler (or advisor) starting a new trip. The brief +
 * timing are captured afterwards by the builder's first-run intake via
 * {@link updateItinerary}. Pass `client_id` to link it to the owning traveler.
 */
export async function createItinerary(
  client: Client,
  body: CreateItineraryRequest,
): Promise<CreateItineraryResult> {
  try {
    const { data, error, response } = await createItineraryEndpointItineraryPost({
      client,
      body,
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 422 ? "validation_error" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type SeedCampaignResult =
  | { ok: true; seed: CampaignSeedResponse }
  | { ok: false; status: number; detail: "unknown_campaign" | "forbidden" | "unknown" | "network_error" };

/**
 * Seed the behind-the-scenes shell itinerary for an inbound campaign landing
 * (advisor-only). Returns the new itinerary id + campaign title/mood so the
 * landing can redirect the traveler straight into the pre-warmed intake.
 */
export async function seedCampaign(
  client: Client,
  campaignId: string,
  clientRowId: string,
): Promise<SeedCampaignResult> {
  try {
    const { data, error, response } =
      await seedCampaignItineraryDemosCampaignCampaignIdPost({
        client,
        path: { campaign_id: campaignId },
        body: { client_id: clientRowId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, seed: data };
    }
    const detail =
      response.status === 404
        ? "unknown_campaign"
        : response.status === 403
          ? "forbidden"
          : "unknown";
    return { ok: false, status: response.status, detail };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type CampaignKickoffResult =
  | { ok: true; kickoff: CampaignKickoffResponse }
  | {
      ok: false;
      status: number;
      detail:
        | "itinerary_not_found"
        | "forbidden"
        // The itinerary carries no campaign (or an unknown one), so there's no
        // shipped spine to lay — the 409 the endpoint raises for both cases.
        | "not_a_campaign_itinerary"
        | "unknown"
        | "network_error";
    };

/**
 * Typed wrapper for POST /itinerary/{id}/campaign/kickoff. Instantiates the
 * length-snapped campaign spine (the curated skeleton + its outdoorvoyage.com
 * cornerstone) onto the traveler's own itinerary, and returns the freshly
 * created nodes so the dashboard can stream them in with the staggered reveal.
 *
 * Deterministic and idempotent: called once when a traveler lands on an empty
 * campaign trip. A re-fire on an itinerary that already has nodes is a no-op
 * (`node_count: 0`, empty `created_nodes`) rather than a second skeleton.
 */
export async function campaignKickoff(
  client: Client,
  itineraryId: string,
): Promise<CampaignKickoffResult> {
  try {
    const { data, error, response } =
      await campaignKickoffEndpointItineraryItineraryIdCampaignKickoffPost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, kickoff: data };
    }
    const detail =
      response.status === 404
        ? "itinerary_not_found"
        : response.status === 403
          ? "forbidden"
          : response.status === 409
            ? "not_a_campaign_itinerary"
            : "unknown";
    return { ok: false, status: response.status, detail };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type UpdateItineraryDetail =
  | "itinerary_not_found"
  | "forbidden"
  // A bad timing payload — reversed date range, non-positive duration, or an
  // unknown field. The intake validates before sending, so this is a backstop.
  | "validation_error"
  // Wave E (ADV-17): loosening exact → window/flexible is refused while
  // booked/confirmed cards exist — their dates are supplier commitments.
  | "booked_dates_locked"
  | "network_error"
  | "unknown";

export type UpdateItineraryResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: UpdateItineraryDetail };

/**
 * Typed wrapper for PATCH /itinerary/{itinerary_id} (0033). Sets the
 * first-class trip brief + timing captured by the builder's first-run intake.
 * Partial: only the fields present in `body` are applied, and an explicit
 * `null` clears a value (e.g. dropping dates when switching to a flexible
 * window). Owner/creator/advisor only — a stranger collapses to `forbidden`.
 */
export async function updateItinerary(
  client: Client,
  itineraryId: string,
  body: UpdateItineraryRequest,
): Promise<UpdateItineraryResult> {
  try {
    const { data, error, response } =
      await updateItineraryEndpointItineraryItineraryIdPatch({
        client,
        path: { itinerary_id: itineraryId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseUpdateItineraryDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseUpdateItineraryDetail(status: number, error?: unknown): UpdateItineraryDetail {
  if (status === 404) return "itinerary_not_found";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 422) return "validation_error";
  if (status === 409 && _detailToken(error) === "booked_dates_locked")
    return "booked_dates_locked";
  return "unknown";
}


export type RetimeItineraryDetail =
  | "itinerary_not_found"
  | "forbidden"
  | "validation_error"
  // The trip already has booked/confirmed cards — a non-zero shift would move
  // supplier-committed dates. Cancel the bookings first.
  | "booked_dates_locked"
  // Another advisor holds the editor lock; retime shifts the whole board.
  | "locked_by_advisor"
  | "network_error"
  | "unknown";

export type RetimeItineraryResult =
  | {
      ok: true;
      itinerary: ItineraryResponse;
      /** Whole days the plan moved (may be negative). */
      delta_days: number;
      /** Scheduled cards shifted with it. */
      shifted_nodes: number;
    }
  | { ok: false; status: number; detail: RetimeItineraryDetail };

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/retime (Wave E / ADV-17) —
 * the pinning gesture: "Day 1 is `date_start`". The server shifts every
 * scheduled card by `date_start − days_anchor` days (wall-clock preserved),
 * flips the trip to `timing_kind=exact`, and re-stamps the anchor. Symmetric
 * with loosening via {@link updateItinerary} (which moves nothing); 409
 * `booked_dates_locked` when booked/confirmed cards pin the calendar.
 */
export async function retimeItinerary(
  client: Client,
  itineraryId: string,
  body: RetimeItineraryRequest,
): Promise<RetimeItineraryResult> {
  try {
    const { data, error, response } =
      await retimeItineraryEndpointItineraryItineraryIdRetimePost({
        client,
        path: { itinerary_id: itineraryId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        itinerary: data.itinerary,
        delta_days: data.delta_days,
        shifted_nodes: data.shifted_nodes,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseRetimeDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseRetimeDetail(status: number, error?: unknown): RetimeItineraryDetail {
  const token = _detailToken(error);
  if (status === 409) {
    if (token === "booked_dates_locked") return "booked_dates_locked";
    if (token === "locked_by_advisor" || token === "already_locked")
      return "locked_by_advisor";
    return "unknown";
  }
  if (status === 404) return "itinerary_not_found";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 422) return "validation_error";
  return "unknown";
}

export type UpdateNodeStatusDetail =
  | "node_not_found"
  | "validation_error"
  | "network_error"
  // The node's lifecycle status forbids the edit (G1): it's approved/booked/
  // confirmed. Surfaced from the 409 body so the UI can craft the reason
  // instead of retrying. ``locked`` is the sibling editor-session lock.
  | "status_locked"
  | "locked"
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
      detail: parseUpdateNodeStatusDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseUpdateNodeStatusDetail(
  status: number,
  error?: unknown,
): UpdateNodeStatusDetail {
  if (status === 404) return "node_not_found";
  if (status === 422) return "validation_error";
  if (status === 409) {
    // Both the editor-session lock and the G1 status gate return 409; the body
    // token disambiguates. status_locked / demote_before_edit / demote_before_
    // delete are status-gate refusals; already_locked / locked_by_advisor are
    // the editor lock.
    const token =
      typeof error === "object" && error !== null && "detail" in error
        ? String((error as { detail?: unknown }).detail ?? "")
        : "";
    if (token.startsWith("demote_") || token === "status_locked") {
      return "status_locked";
    }
    return "locked";
  }
  return "unknown";
}

export type UpdateNodePatch = {
  title?: string | null;
  source?: string | null;
  source_id?: string | null;
  status?: NodeStatus | null;
  // Free-form node metadata patch — e.g. persisting a node's start_time
  // after a drag-to-reorder. Forwarded as-is to UpdateNodeRequest.metadata.
  metadata?: { [key: string]: unknown } | null;
  // First-class cost (ADV-13 editable cards). Amount + currency must be
  // set/cleared together — the service layer + DB CHECK enforce it; the
  // amount is a decimal string to avoid float precision loss.
  cost_amount?: string | null;
  cost_currency?: string | null;
  cost_kind?: CostKind | null;
  // Phase 4 schedule placement (doc/itin-time.md): drag-and-drop sends
  // {day_index, minute_of_day} (or {clear: true} to unschedule) and the
  // kernel builds the schedule server-side. Wins over metadata.start_time.
  schedule?: import("./generated/types.gen.js").SchedulePlacementPayload | null;
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
      detail: parseUpdateNodeStatusDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Node / edge mutations (itinerary graph) ────────────────────────────────
//
// Direct create/delete of graph nodes and edges, consumed by the advisor
// draft editor (drag-to-reorder, add/remove cards, wire/unwire sequence
// edges). All four collapse the SDK's `{data, error, response}` onto the
// shared discriminated result so the editor can mutate optimistically and
// revert on `ok: false` without try/catch.

export type CreateNodeDetail =
  | "itinerary_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

export type CreateNodeResult =
  | { ok: true; node: NodeResponse }
  | { ok: false; status: number; detail: CreateNodeDetail };

export type CreateNodeArgs = {
  itineraryId: string;
  body: CreateNodeRequest;
};

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/nodes. Creates a single
 * graph node (destination, hotel, experience, …) and returns it. 404 →
 * `itinerary_not_found`, 422 → `validation_error`.
 */
export async function createNode(
  client: Client,
  args: CreateNodeArgs,
): Promise<CreateNodeResult> {
  try {
    const { data, error, response } =
      await createNodeEndpointItineraryItineraryIdNodesPost({
        client,
        path: { itinerary_id: args.itineraryId },
        body: args.body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, node: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCreateNodeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCreateNodeDetail(status: number): CreateNodeDetail {
  if (status === 404) return "itinerary_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type DeleteNodeDetail =
  | "node_not_found"
  | "network_error"
  | "unknown";

export type DeleteNodeResult =
  | { ok: true }
  | { ok: false; status: number; detail: DeleteNodeDetail };

export type DeleteNodeArgs = {
  itineraryId: string;
  nodeId: string;
};

/**
 * Typed wrapper for DELETE /itinerary/{itinerary_id}/nodes/{node_id}. The
 * endpoint returns 204 with no body, so success is detected via
 * `error === undefined`. 404 → `node_not_found`.
 */
export async function deleteNode(
  client: Client,
  args: DeleteNodeArgs,
): Promise<DeleteNodeResult> {
  try {
    const { error, response } =
      await deleteNodeEndpointItineraryItineraryIdNodesNodeIdDelete({
        client,
        path: {
          itinerary_id: args.itineraryId,
          node_id: args.nodeId,
        },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseDeleteNodeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseDeleteNodeDetail(status: number): DeleteNodeDetail {
  if (status === 404) return "node_not_found";
  return "unknown";
}

export type CreateEdgeDetail =
  | "itinerary_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

export type CreateEdgeResult =
  | { ok: true; edge: EdgeResponse }
  | { ok: false; status: number; detail: CreateEdgeDetail };

export type CreateEdgeArgs = {
  itineraryId: string;
  body: CreateEdgeRequest;
};

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/edges. Wires two nodes
 * with a typed edge (e.g. a sequence edge between consecutive days) and
 * returns it. 404 → `itinerary_not_found`, 422 → `validation_error`.
 */
export async function createEdge(
  client: Client,
  args: CreateEdgeArgs,
): Promise<CreateEdgeResult> {
  try {
    const { data, error, response } =
      await createEdgeEndpointItineraryItineraryIdEdgesPost({
        client,
        path: { itinerary_id: args.itineraryId },
        body: args.body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, edge: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCreateEdgeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCreateEdgeDetail(status: number): CreateEdgeDetail {
  if (status === 404) return "itinerary_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type DeleteEdgeDetail =
  | "edge_not_found"
  | "network_error"
  | "unknown";

export type DeleteEdgeResult =
  | { ok: true }
  | { ok: false; status: number; detail: DeleteEdgeDetail };

export type DeleteEdgeArgs = {
  itineraryId: string;
  edgeId: string;
};

/**
 * Typed wrapper for DELETE /itinerary/{itinerary_id}/edges/{edge_id}. The
 * endpoint returns 204 with no body, so success is detected via
 * `error === undefined`. 404 → `edge_not_found`.
 */
export async function deleteEdge(
  client: Client,
  args: DeleteEdgeArgs,
): Promise<DeleteEdgeResult> {
  try {
    const { error, response } =
      await deleteEdgeEndpointItineraryItineraryIdEdgesEdgeIdDelete({
        client,
        path: {
          itinerary_id: args.itineraryId,
          edge_id: args.edgeId,
        },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseDeleteEdgeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseDeleteEdgeDetail(status: number): DeleteEdgeDetail {
  if (status === 404) return "edge_not_found";
  return "unknown";
}

// ── Analyze (B5) · Fill (B6) · inventory authoring (B7) ─────────────────────
//
// The advisor authoring surface (the unified itinerary graph view, unlocked
// for staff) drives three backend capabilities through these wrappers: search
// inventory across providers and add a result as a graph node; queue + poll an
// Analyze run and read its findings; and rank feasible Fill candidates for a
// gap. All collapse the SDK's `{data, error, response}` onto the shared
// discriminated result so the store can mutate / poll without try/catch.

export type SearchInventoryDetail =
  | "unknown_source"
  | "network_error"
  | "unknown";

/** Query params for GET /search-inventory — the generated shape, sans null. */
export type SearchInventoryQuery = NonNullable<
  SearchInventoryEndpointSearchInventoryGetData["query"]
>;

export type SearchInventoryResult =
  | {
      ok: true;
      items: SearchInventoryResponse["items"];
      count: number;
      sources: SearchSourceDiagnostics[];
    }
  | { ok: false; status: number; detail: SearchInventoryDetail };

/**
 * Typed wrapper for GET /search-inventory. Aggregate fan-out by default; pass
 * `source` / `kinds` / `keyword` (+ flight / hotel / geo-bias params) to
 * scope. `sources` carries per-provider diagnostics (count, latency, captured
 * upstream error) for the workbench status strip. 400 → `unknown_source`.
 */
export async function searchInventory(
  client: Client,
  query: SearchInventoryQuery = {},
): Promise<SearchInventoryResult> {
  try {
    const { data, error, response } =
      await searchInventoryEndpointSearchInventoryGet({ client, query });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        items: data.items,
        count: data.count,
        sources: data.sources ?? [],
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 400 ? "unknown_source" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListInventorySourcesResult =
  | { ok: true; sources: string[] }
  | { ok: false; status: number; detail: "network_error" | "unknown" };

/**
 * Typed wrapper for GET /inventory/sources — the registered provider names,
 * in registration order. Lets the workbench render provider filter pills off
 * the live registry instead of a hardcoded list.
 */
export async function listInventorySources(
  client: Client,
): Promise<ListInventorySourcesResult> {
  try {
    const { data, error, response } =
      await listInventorySourcesEndpointInventorySourcesGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, sources: data.sources };
    }
    return { ok: false, status: response.status, detail: "unknown" };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type CreateNodeFromInventoryDetail =
  | "itinerary_not_found"
  | "inventory_not_found"
  | "unknown_source"
  | "validation_error"
  | "network_error"
  | "unknown";

export type CreateNodeFromInventoryResult =
  | { ok: true; node: NodeResponse }
  | { ok: false; status: number; detail: CreateNodeFromInventoryDetail };

export type CreateNodeFromInventoryArgs = {
  itineraryId: string;
  source: string;
  sourceId: string;
  status?: NodeStatus;
  parentSubgraphId?: string | null;
};

/**
 * Typed wrapper for POST /itinerary/{id}/nodes/from-inventory. The server
 * re-fetches the item, derives typed card metadata + first-class cost (B4),
 * and adds it as a node (default status `proposed`). This is also how an
 * accepted Fill proposal lands on the graph. 400 → `unknown_source`, 404 →
 * `inventory_not_found`, 422 → `validation_error`.
 */
export async function createNodeFromInventory(
  client: Client,
  args: CreateNodeFromInventoryArgs,
): Promise<CreateNodeFromInventoryResult> {
  try {
    const { data, error, response } =
      await createNodeFromInventoryEndpointItineraryItineraryIdNodesFromInventoryPost(
        {
          client,
          path: { itinerary_id: args.itineraryId },
          body: {
            source: args.source,
            source_id: args.sourceId,
            ...(args.status ? { status: args.status } : {}),
            ...(args.parentSubgraphId !== undefined
              ? { parent_subgraph_id: args.parentSubgraphId }
              : {}),
          },
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, node: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCreateNodeFromInventoryDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCreateNodeFromInventoryDetail(
  status: number,
): CreateNodeFromInventoryDetail {
  if (status === 400) return "unknown_source";
  if (status === 404) return "inventory_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type CreateNodeFromLinkDetail =
  | "itinerary_not_found"
  | "forbidden"
  | "validation_error"
  | "network_error"
  | "unknown";

export type CreateNodeFromLinkResult =
  | { ok: true; node: NodeResponse }
  | { ok: false; status: number; detail: CreateNodeFromLinkDetail };

export type CreateNodeFromLinkArgs = {
  itineraryId: string;
  url: string;
  // Files the link under a Collection category (a restaurant → `meal`); the
  // server defaults to `note` (unfiled) when omitted.
  kind?: NodeType;
  status?: NodeStatus;
  note?: string;
  parentSubgraphId?: string | null;
};

/**
 * Typed wrapper for POST /itinerary/{id}/nodes/from-link. Saves a pasted web
 * link into the Collection: the server fetches its OpenGraph preview and adds
 * an unscheduled card (default status `proposed`, default kind `note`). 403 →
 * `forbidden`, 404 → `itinerary_not_found`, 422 → `validation_error`.
 */
export async function createNodeFromLink(
  client: Client,
  args: CreateNodeFromLinkArgs,
): Promise<CreateNodeFromLinkResult> {
  try {
    const { data, error, response } =
      await createNodeFromLinkEndpointItineraryItineraryIdNodesFromLinkPost({
        client,
        path: { itinerary_id: args.itineraryId },
        body: {
          url: args.url,
          ...(args.kind ? { kind: args.kind } : {}),
          ...(args.status ? { status: args.status } : {}),
          ...(args.note !== undefined ? { note: args.note } : {}),
          ...(args.parentSubgraphId !== undefined
            ? { parent_subgraph_id: args.parentSubgraphId }
            : {}),
        },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, node: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseCreateNodeFromLinkDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseCreateNodeFromLinkDetail(status: number): CreateNodeFromLinkDetail {
  if (status === 403) return "forbidden";
  if (status === 404) return "itinerary_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type GetCollectionDetail =
  | "itinerary_not_found"
  | "forbidden"
  | "network_error"
  | "unknown";

export type GetCollectionResult =
  | { ok: true; itineraryId: string; items: NodeResponse[] }
  | { ok: false; status: number; detail: GetCollectionDetail };

/**
 * Typed wrapper for GET /itinerary/{id}/collection — the wish list:
 * unscheduled, non-discarded nodes. The web usually derives the Collection
 * from the graph it already loads; this is the cheap read for surfaces that
 * only need the wish list. 403 → `forbidden`, 404 → `itinerary_not_found`.
 */
export async function getCollection(
  client: Client,
  itineraryId: string,
): Promise<GetCollectionResult> {
  try {
    const { data, error, response } =
      await getCollectionEndpointItineraryItineraryIdCollectionGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itineraryId: data.itinerary_id, items: data.items };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseGetCollectionDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseGetCollectionDetail(status: number): GetCollectionDetail {
  if (status === 403) return "forbidden";
  if (status === 404) return "itinerary_not_found";
  return "unknown";
}

export type AnalyzeDetail =
  | "itinerary_not_found"
  | "forbidden"
  | "analysis_not_found"
  | "validation_error"
  | "network_error"
  | "unknown";

export type StartAnalysisResult =
  | { ok: true; created: AnalysisCreatedResponse }
  | { ok: false; status: number; detail: AnalyzeDetail };

export type StartAnalysisArgs = {
  itineraryId: string;
  body?: StartAnalysisRequest;
};

/**
 * Typed wrapper for POST /itinerary/{id}/analyses (202). Queues an Analyze run
 * (standard depth by default) and returns its id + status; the caller polls
 * `getAnalysis` for findings. 404 → `itinerary_not_found`, 403 → `forbidden`.
 */
export async function startAnalysis(
  client: Client,
  args: StartAnalysisArgs,
): Promise<StartAnalysisResult> {
  try {
    const { data, error, response } =
      await startAnalysisEndpointItineraryItineraryIdAnalysesPost({
        client,
        path: { itinerary_id: args.itineraryId },
        body: args.body ?? {},
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, created: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseAnalyzeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListAnalysesResult =
  | { ok: true; analyses: AnalysisSummaryResponse[] }
  | { ok: false; status: number; detail: AnalyzeDetail };

/** Typed wrapper for GET /itinerary/{id}/analyses — recent runs, newest first. */
export async function listAnalyses(
  client: Client,
  itineraryId: string,
  limit?: number,
): Promise<ListAnalysesResult> {
  try {
    const { data, error, response } =
      await listAnalysesEndpointItineraryItineraryIdAnalysesGet({
        client,
        path: { itinerary_id: itineraryId },
        ...(limit !== undefined ? { query: { limit } } : {}),
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, analyses: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseAnalyzeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type GetAnalysisResult =
  | { ok: true; analysis: AnalysisDetailResponse }
  | { ok: false; status: number; detail: AnalyzeDetail };

/**
 * Typed wrapper for GET /itinerary/{id}/analyses/{analysis_id} — one run plus
 * its findings. The store polls this until `analysis.status` is terminal.
 */
export async function getAnalysis(
  client: Client,
  args: { itineraryId: string; analysisId: string },
): Promise<GetAnalysisResult> {
  try {
    const { data, error, response } =
      await getAnalysisEndpointItineraryItineraryIdAnalysesAnalysisIdGet({
        client,
        path: { itinerary_id: args.itineraryId, analysis_id: args.analysisId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, analysis: data };
    }
    return {
      ok: false,
      status: response.status,
      detail:
        response.status === 404
          ? "analysis_not_found"
          : parseAnalyzeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

/**
 * Typed wrapper for POST /itinerary/{id}/analyses/{analysis_id}/cancel
 * (idempotent). Returns the run's current detail.
 */
export async function cancelAnalysis(
  client: Client,
  args: { itineraryId: string; analysisId: string },
): Promise<GetAnalysisResult> {
  try {
    const { data, error, response } =
      await cancelAnalysisEndpointItineraryItineraryIdAnalysesAnalysisIdCancelPost(
        {
          client,
          path: {
            itinerary_id: args.itineraryId,
            analysis_id: args.analysisId,
          },
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, analysis: data };
    }
    return {
      ok: false,
      status: response.status,
      detail:
        response.status === 404
          ? "analysis_not_found"
          : parseAnalyzeDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseAnalyzeDetail(status: number): AnalyzeDetail {
  if (status === 404) return "itinerary_not_found";
  if (status === 403) return "forbidden";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type FillGapDetail =
  | "itinerary_not_found"
  | "forbidden"
  | "validation_error"
  | "network_error"
  | "unknown";

export type FillGapResult =
  | { ok: true; result: FillResponse }
  | { ok: false; status: number; detail: FillGapDetail };

export type FillGapArgs = {
  itineraryId: string;
  body: FillRequest;
};

/**
 * Typed wrapper for POST /itinerary/{id}/fill (read-only). Ranks feasible
 * inventory candidates for a gap; accepting one is `createNodeFromInventory`.
 * 404 → `itinerary_not_found`, 403 → `forbidden`, 422 → `validation_error`.
 */
export async function fillGap(
  client: Client,
  args: FillGapArgs,
): Promise<FillGapResult> {
  try {
    const { data, error, response } =
      await fillGapEndpointItineraryItineraryIdFillPost({
        client,
        path: { itinerary_id: args.itineraryId },
        body: args.body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, result: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseFillGapDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseFillGapDetail(status: number): FillGapDetail {
  if (status === 404) return "itinerary_not_found";
  if (status === 403) return "forbidden";
  if (status === 422) return "validation_error";
  return "unknown";
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

export type ApproveAllNodesDetail =
  | "not_a_trunk"
  | "forbidden"
  | "itinerary_not_found"
  | "network_error"
  | "unknown";

export type ApproveAllNodesResult =
  | { ok: true; approvedCount: number; graph: GraphResponse }
  | { ok: false; status: number; detail: ApproveAllNodesDetail };

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/nodes/approve-all — the
 * traveler's "Approve all" on the official trunk. Writability-gated (owner /
 * creator / advisor); a non-writer 403s (`forbidden`). 409 collapses to
 * `not_a_trunk` (a fork has nothing to approve). Idempotent: zero pending
 * approvable nodes returns `approvedCount: 0`.
 */
export async function approveAllNodes(
  client: Client,
  itineraryId: string,
): Promise<ApproveAllNodesResult> {
  try {
    const { data, error, response } =
      await approveAllNodesEndpointItineraryItineraryIdNodesApproveAllPost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, approvedCount: data.approved_count, graph: data.graph };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseApproveAllNodesDetail(response.status),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseApproveAllNodesDetail(status: number): ApproveAllNodesDetail {
  if (status === 409) return "not_a_trunk";
  if (status === 403) return "forbidden";
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

export type ResendWelcomeDetail =
  | "client_not_found"
  | "advisor_only"
  | "client_already_accepted"
  | "auth_upstream_unavailable"
  | "network_error"
  | "unknown";

/**
 * Discriminated result for POST /clients/{client_id}/resend-welcome. The
 * server returns 204 on success; this wrapper turns that into `ok: true`
 * with no payload.
 */
export type ResendWelcomeResult =
  | { ok: true }
  | { ok: false; status: number; detail: ResendWelcomeDetail };

/**
 * Typed wrapper for POST /clients/{client_id}/resend-welcome.
 *
 * Re-sends the welcome sign-in link to a client who hasn't signed in yet
 * (the advisor "nudge"). The server refuses with 409
 * (`client_already_accepted`) once the client has logged in — at that
 * point they use the normal /auth/login magic-link flow.
 */
export async function resendWelcomeEmail(
  client: Client,
  clientId: string,
): Promise<ResendWelcomeResult> {
  try {
    const { error, response } =
      await resendWelcomeEndpointClientsClientIdResendWelcomePost({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: parseResendWelcomeDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

function parseResendWelcomeDetail(
  status: number,
  error: unknown,
): ResendWelcomeDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "client_already_accepted") return "client_already_accepted";
  if (raw === "auth_upstream_unavailable") return "auth_upstream_unavailable";
  if (raw === "advisor_only") return "advisor_only";
  if (status === 403) return "advisor_only";
  if (status === 404) return "client_not_found";
  if (status === 409) return "client_already_accepted";
  if (status === 502) return "auth_upstream_unavailable";
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

export type AddToReadingListResult =
  | { ok: true; nodeId: string; itineraryId: string }
  | { ok: false; status: number; detail: "client_not_found" | "network_error" | "unknown" };

/**
 * Typed wrapper for POST /me/reading-list.
 *
 * Saves a concierge-suggested article into the caller's reading list — an
 * unscheduled `article` node in their Collection. The metadata is passed
 * verbatim from the flyout (the agent already surfaced it), so the source
 * page is never re-fetched.
 */
export async function addToReadingList(
  client: Client,
  body: ReadingListAddRequest,
): Promise<AddToReadingListResult> {
  try {
    const { data, error, response } = await addToReadingListEndpointMeReadingListPost({
      client,
      body,
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, nodeId: data.node_id, itineraryId: data.itinerary_id };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 404 ? "client_not_found" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type DismissOnboardingResult =
  | { ok: true }
  | { ok: false; status: number; detail: "client_not_found" | "network_error" | "unknown" };

/**
 * Typed wrapper for POST /onboarding/dismiss.
 *
 * Closes any active agent session for the calling client and ensures
 * `has_prior_session` is true on the next page load so basecamp's
 * single-prompt opener UI is not re-shown. Idempotent.
 */
export async function dismissOnboarding(
  client: Client,
): Promise<DismissOnboardingResult> {
  try {
    const { error, response } =
      await dismissOnboardingEndpointOnboardingDismissPost({ client });
    if (error === undefined && response.status === 204) {
      return { ok: true };
    }
    if (response.status === 404) {
      return { ok: false, status: 404, detail: "client_not_found" };
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

export type ListMyInvoicesResult =
  | { ok: true; invoices: MyInvoiceSummary[] }
  | { ok: false; status: number; detail: "network_error" | "unknown" };

/**
 * Typed wrapper for GET /me/invoices.
 *
 * The calling client's invoices across every itinerary, newest first. Powers
 * the traveler /basecamp/invoices listing; each row links to /invoices/{id}.
 * Empty list is a valid 200.
 */
export async function listMyInvoices(
  client: Client,
): Promise<ListMyInvoicesResult> {
  try {
    const { data, error, response } =
      await listMyInvoicesEndpointMeInvoicesGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoices: data.invoices };
    }
    return { ok: false, status: response.status, detail: "unknown" };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListAdvisorItinerariesDetail =
  | "advisor_only"
  | "network_error"
  | "unknown";

export type ListAdvisorItinerariesResult =
  | {
      ok: true;
      itineraries: AdvisorItinerarySummary[];
      nextCursor: string | null;
      total: number;
    }
  | { ok: false; status: number; detail: ListAdvisorItinerariesDetail };

/** Optional roster query params for GET /itineraries (Wave F). */
export type ListAdvisorItinerariesParams = {
  limit?: number;
  cursor?: string;
  q?: string;
  status?: DisplayStatus;
  clientId?: string;
  sort?: "updated_at" | "created_at" | "title";
  order?: "asc" | "desc";
};

/**
 * Typed wrapper for GET /itineraries (advisor). Returns one row per
 * itinerary across the calling advisor's clients, embedding the client
 * block so the Command Center can render a dense roster without N+1.
 * Wave F: searchable + keyset-paged (`nextCursor`/`total` additive), and
 * `needs_attention` is real (an open-state awareness signal on the trip).
 */
export async function listAdvisorItineraries(
  client: Client,
  params?: ListAdvisorItinerariesParams,
): Promise<ListAdvisorItinerariesResult> {
  try {
    const { data, error, response } =
      await listAdvisorItinerariesEndpointItinerariesGet({
        client,
        query: {
          ...(params?.limit !== undefined ? { limit: params.limit } : {}),
          ...(params?.cursor !== undefined ? { cursor: params.cursor } : {}),
          ...(params?.q !== undefined ? { q: params.q } : {}),
          ...(params?.status !== undefined ? { status: params.status } : {}),
          ...(params?.clientId !== undefined
            ? { client_id: params.clientId }
            : {}),
          ...(params?.sort !== undefined ? { sort: params.sort } : {}),
          ...(params?.order !== undefined ? { order: params.order } : {}),
        },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        itineraries: data.itineraries,
        nextCursor: data.next_cursor ?? null,
        total: data.total ?? data.itineraries.length,
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 403 ? "advisor_only" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListClientSessionsDetail =
  | "client_not_found"
  | "advisor_only"
  | "network_error"
  | "unknown";

export type ListClientSessionsResult =
  | { ok: true; sessions: ClientSessionSummary[] }
  | { ok: false; status: number; detail: ListClientSessionsDetail };

/**
 * Typed wrapper for GET /clients/{id}/sessions. Lists every agent
 * session for one client (advisor-scoped); each row carries turn_count
 * and last_turn_at so the Command Center can render the chat history
 * without an N+1 over /sessions/{id}/turns.
 */
export type ContactMutationDetail =
  | "client_not_found"
  | "contact_not_found"
  | "advisor_only"
  | "validation_error"
  | "network_error"
  | "unknown";

function _parseContactDetail(
  status: number,
  error: unknown,
): ContactMutationDetail {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "contact_not_found") return "contact_not_found";
  if (raw === "advisor_only") return "advisor_only";
  if (status === 403) return "advisor_only";
  if (status === 404) return "contact_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type CreateClientContactResult =
  | { ok: true; contact: ClientContactDetail }
  | { ok: false; status: number; detail: ContactMutationDetail };

export async function createClientContact(
  client: Client,
  clientId: string,
  body: ClientContactCreate,
): Promise<CreateClientContactResult> {
  try {
    const { data, error, response } =
      await createClientContactEndpointClientsClientIdContactsPost({
        client,
        path: { client_id: clientId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, contact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseContactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type UpdateClientContactResult =
  | { ok: true; contact: ClientContactDetail }
  | { ok: false; status: number; detail: ContactMutationDetail };

export async function updateClientContact(
  client: Client,
  clientId: string,
  contactId: string,
  body: ClientContactUpdate,
): Promise<UpdateClientContactResult> {
  try {
    const { data, error, response } =
      await updateClientContactEndpointClientsClientIdContactsContactIdPatch({
        client,
        path: { client_id: clientId, contact_id: contactId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, contact: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseContactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type DeleteClientContactResult =
  | { ok: true }
  | { ok: false; status: number; detail: ContactMutationDetail };

export async function deleteClientContact(
  client: Client,
  clientId: string,
  contactId: string,
): Promise<DeleteClientContactResult> {
  try {
    const { error, response } =
      await deleteClientContactEndpointClientsClientIdContactsContactIdDelete({
        client,
        path: { client_id: clientId, contact_id: contactId },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseContactDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function listClientSessions(
  client: Client,
  clientId: string,
): Promise<ListClientSessionsResult> {
  try {
    const { data, error, response } =
      await listClientSessionsEndpointClientsClientIdSessionsGet({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, sessions: data.sessions };
    }
    return {
      ok: false,
      status: response.status,
      detail:
        response.status === 404
          ? "client_not_found"
          : response.status === 403
            ? "advisor_only"
            : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Party members (M003/V1) ───────────────────────────────────────────────
//
// The durable, household-scoped traveler roster, authored by three actors.
// Two parallel surfaces share the same shapes: the traveler's own household
// (/me/party-members) and an advisor's view of a client's household
// (/clients/{id}/party-members). A third pair of routes attaches/detaches a
// saved member onto a specific itinerary's party ("who's traveling"). All
// collapse to `{ ok, member|members|party }` so apps/web branches on
// `result.ok`; cross-tenant reads return 404 (D015 existence-hiding).

export type PartyMemberDetailCode =
  | "client_not_found"
  | "itinerary_not_found"
  | "party_member_not_found"
  | "advisor_only"
  | "validation_error"
  | "network_error"
  | "unknown";

function _parsePartyMemberDetail(
  status: number,
  error: unknown,
): PartyMemberDetailCode {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "itinerary_not_found") return "itinerary_not_found";
  if (raw === "party_member_not_found") return "party_member_not_found";
  if (raw === "advisor_only") return "advisor_only";
  if (status === 403) return "advisor_only";
  if (status === 404) return "party_member_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type ListPartyMembersResult =
  | { ok: true; members: PartyMemberDetail[] }
  | { ok: false; status: number; detail: PartyMemberDetailCode };

export type PartyMemberResult =
  | { ok: true; member: PartyMemberDetail }
  | { ok: false; status: number; detail: PartyMemberDetailCode };

export type ItineraryPartyResult =
  | { ok: true; party: ItineraryPartyResponse }
  | { ok: false; status: number; detail: PartyMemberDetailCode };

// Traveler self-service — the caller's own household (/me/party-members).

export async function listMyPartyMembers(
  client: Client,
): Promise<ListPartyMembersResult> {
  try {
    const { data, error, response } =
      await listMyPartyMembersEndpointMePartyMembersGet({ client });
    if (error === undefined && data !== undefined) {
      return { ok: true, members: data.members };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function createMyPartyMember(
  client: Client,
  body: PartyMemberCreate,
): Promise<PartyMemberResult> {
  try {
    const { data, error, response } =
      await createMyPartyMemberEndpointMePartyMembersPost({ client, body });
    if (error === undefined && data !== undefined) {
      return { ok: true, member: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function updateMyPartyMember(
  client: Client,
  memberId: string,
  body: PartyMemberUpdate,
): Promise<PartyMemberResult> {
  try {
    const { data, error, response } =
      await updateMyPartyMemberEndpointMePartyMembersMemberIdPatch({
        client,
        path: { member_id: memberId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, member: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function archiveMyPartyMember(
  client: Client,
  memberId: string,
): Promise<PartyMemberResult> {
  try {
    const { data, error, response } =
      await archiveMyPartyMemberEndpointMePartyMembersMemberIdDelete({
        client,
        path: { member_id: memberId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, member: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// Advisor — a client's household (/clients/{id}/party-members).

export async function listClientPartyMembers(
  client: Client,
  clientId: string,
): Promise<ListPartyMembersResult> {
  try {
    const { data, error, response } =
      await listClientPartyMembersEndpointClientsClientIdPartyMembersGet({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, members: data.members };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function createClientPartyMember(
  client: Client,
  clientId: string,
  body: PartyMemberCreate,
): Promise<PartyMemberResult> {
  try {
    const { data, error, response } =
      await createClientPartyMemberEndpointClientsClientIdPartyMembersPost({
        client,
        path: { client_id: clientId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, member: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function updateClientPartyMember(
  client: Client,
  clientId: string,
  memberId: string,
  body: PartyMemberUpdate,
): Promise<PartyMemberResult> {
  try {
    const { data, error, response } =
      await updateClientPartyMemberEndpointClientsClientIdPartyMembersMemberIdPatch(
        {
          client,
          path: { client_id: clientId, member_id: memberId },
          body,
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, member: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function archiveClientPartyMember(
  client: Client,
  clientId: string,
  memberId: string,
): Promise<PartyMemberResult> {
  try {
    const { data, error, response } =
      await archiveClientPartyMemberEndpointClientsClientIdPartyMembersMemberIdDelete(
        {
          client,
          path: { client_id: clientId, member_id: memberId },
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, member: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// Per-trip participation — who's traveling on an itinerary.

export async function listItineraryParty(
  client: Client,
  itineraryId: string,
): Promise<ItineraryPartyResult> {
  try {
    const { data, error, response } =
      await listItineraryPartyEndpointItinerariesItineraryIdPartyGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, party: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function attachItineraryPartyMember(
  client: Client,
  itineraryId: string,
  body: AttachPartyMemberRequest,
): Promise<ItineraryPartyResult> {
  try {
    const { data, error, response } =
      await attachItineraryPartyMemberEndpointItinerariesItineraryIdPartyMembersPost(
        {
          client,
          path: { itinerary_id: itineraryId },
          body,
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, party: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function detachItineraryPartyMember(
  client: Client,
  itineraryId: string,
  memberId: string,
): Promise<ItineraryPartyResult> {
  try {
    const { data, error, response } =
      await detachItineraryPartyMemberEndpointItinerariesItineraryIdPartyMembersMemberIdDelete(
        {
          client,
          path: { itinerary_id: itineraryId, member_id: memberId },
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, party: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePartyMemberDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Document vault (M003/V3) ──────────────────────────────────────────────
//
// The secure, household-scoped document store. Upload is a two-step presigned
// flow: ``init`` persists metadata + returns a presigned PUT (the browser PUTs
// straight to S3 — NOT through this client), then ``complete`` confirms.
// Downloads mint a presigned GET. Two parallel surfaces (traveler ``/me/*`` and
// advisor ``/clients/{id}/*``) share the shapes; a third lists an itinerary's
// client's documents read-only. Detail shapes never carry the S3 key.

export type DocumentDetailCode =
  | "client_not_found"
  | "itinerary_not_found"
  | "document_not_found"
  | "party_member_not_found"
  | "advisor_only"
  | "validation_error"
  | "network_error"
  | "unknown";

function _parseDocumentDetail(
  status: number,
  error: unknown,
): DocumentDetailCode {
  const body = error as { detail?: unknown } | undefined;
  const raw = body && typeof body.detail === "string" ? body.detail : "";
  if (raw === "client_not_found") return "client_not_found";
  if (raw === "itinerary_not_found") return "itinerary_not_found";
  if (raw === "document_not_found") return "document_not_found";
  if (raw === "party_member_not_found") return "party_member_not_found";
  if (raw === "advisor_only") return "advisor_only";
  if (status === 403) return "advisor_only";
  if (status === 404) return "document_not_found";
  if (status === 422) return "validation_error";
  return "unknown";
}

export type ListDocumentsResult =
  | { ok: true; documents: DocumentDetail[] }
  | { ok: false; status: number; detail: DocumentDetailCode };

export type DocumentResult =
  | { ok: true; document: DocumentDetail }
  | { ok: false; status: number; detail: DocumentDetailCode };

export type DocumentInitResult =
  | { ok: true; document: DocumentDetail; uploadUrl: string }
  | { ok: false; status: number; detail: DocumentDetailCode };

export type DocumentDownloadResult =
  | { ok: true; url: string }
  | { ok: false; status: number; detail: DocumentDetailCode };

// Traveler self-service — the caller's own household (/me/documents).

export async function listMyDocuments(
  client: Client,
): Promise<ListDocumentsResult> {
  try {
    const { data, error, response } = await listMyDocumentsEndpointMeDocumentsGet(
      { client },
    );
    if (error === undefined && data !== undefined) {
      return { ok: true, documents: data.documents };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function initMyDocumentUpload(
  client: Client,
  body: DocumentInitRequest,
): Promise<DocumentInitResult> {
  try {
    const { data, error, response } = await initMyDocumentEndpointMeDocumentsPost(
      { client, body },
    );
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data.document, uploadUrl: data.upload_url };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function completeMyDocument(
  client: Client,
  documentId: string,
  body: DocumentCompleteRequest = {},
): Promise<DocumentResult> {
  try {
    const { data, error, response } =
      await completeMyDocumentEndpointMeDocumentsDocumentIdCompletePost({
        client,
        path: { document_id: documentId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function getMyDocumentDownload(
  client: Client,
  documentId: string,
): Promise<DocumentDownloadResult> {
  try {
    const { data, error, response } =
      await downloadMyDocumentEndpointMeDocumentsDocumentIdDownloadGet({
        client,
        path: { document_id: documentId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, url: data.url };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function updateMyDocument(
  client: Client,
  documentId: string,
  body: DocumentUpdate,
): Promise<DocumentResult> {
  try {
    const { data, error, response } =
      await updateMyDocumentEndpointMeDocumentsDocumentIdPatch({
        client,
        path: { document_id: documentId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function archiveMyDocument(
  client: Client,
  documentId: string,
): Promise<DocumentResult> {
  try {
    const { data, error, response } =
      await archiveMyDocumentEndpointMeDocumentsDocumentIdDelete({
        client,
        path: { document_id: documentId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// Advisor — a client's household (/clients/{id}/documents).

export async function listClientDocuments(
  client: Client,
  clientId: string,
): Promise<ListDocumentsResult> {
  try {
    const { data, error, response } =
      await listClientDocumentsEndpointClientsClientIdDocumentsGet({
        client,
        path: { client_id: clientId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, documents: data.documents };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function initClientDocumentUpload(
  client: Client,
  clientId: string,
  body: DocumentInitRequest,
): Promise<DocumentInitResult> {
  try {
    const { data, error, response } =
      await initClientDocumentEndpointClientsClientIdDocumentsPost({
        client,
        path: { client_id: clientId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data.document, uploadUrl: data.upload_url };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function completeClientDocument(
  client: Client,
  clientId: string,
  documentId: string,
  body: DocumentCompleteRequest = {},
): Promise<DocumentResult> {
  try {
    const { data, error, response } =
      await completeClientDocumentEndpointClientsClientIdDocumentsDocumentIdCompletePost(
        {
          client,
          path: { client_id: clientId, document_id: documentId },
          body,
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function getClientDocumentDownload(
  client: Client,
  clientId: string,
  documentId: string,
): Promise<DocumentDownloadResult> {
  try {
    const { data, error, response } =
      await downloadClientDocumentEndpointClientsClientIdDocumentsDocumentIdDownloadGet(
        {
          client,
          path: { client_id: clientId, document_id: documentId },
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, url: data.url };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function updateClientDocument(
  client: Client,
  clientId: string,
  documentId: string,
  body: DocumentUpdate,
): Promise<DocumentResult> {
  try {
    const { data, error, response } =
      await updateClientDocumentEndpointClientsClientIdDocumentsDocumentIdPatch({
        client,
        path: { client_id: clientId, document_id: documentId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export async function archiveClientDocument(
  client: Client,
  clientId: string,
  documentId: string,
): Promise<DocumentResult> {
  try {
    const { data, error, response } =
      await archiveClientDocumentEndpointClientsClientIdDocumentsDocumentIdDelete(
        {
          client,
          path: { client_id: clientId, document_id: documentId },
        },
      );
    if (error === undefined && data !== undefined) {
      return { ok: true, document: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// Per-trip read-only — the itinerary's client's documents.

export async function listItineraryDocuments(
  client: Client,
  itineraryId: string,
): Promise<ListDocumentsResult> {
  try {
    const { data, error, response } =
      await listItineraryDocumentsEndpointItinerariesItineraryIdDocumentsGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, documents: data.documents };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseDocumentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Fork diff / reconcile (M004/G3) ─────────────────────────────────────────

export type ForkReconcileDetail =
  | "not_found"
  | "not_a_fork"
  | "fork_infeasible"
  | "advisor_only"
  | "forbidden"
  | "network_error"
  | "unknown";

function _detailToken(error: unknown): string {
  return typeof error === "object" && error !== null && "detail" in error
    ? String((error as { detail?: unknown }).detail ?? "")
    : "";
}

function _parseForkReconcileDetail(
  status: number,
  error?: unknown,
): ForkReconcileDetail {
  const token = _detailToken(error);
  if (token === "not_a_fork" || token === "fork_infeasible") return token;
  if (status === 404) return "not_found";
  if (status === 403) return token === "advisor_only" ? "advisor_only" : "forbidden";
  return "unknown";
}

export type ForkItineraryDetail =
  | "not_found"
  | "forbidden"
  | "network_error"
  | "unknown";

export type ForkItineraryResult =
  | { ok: true; graph: GraphResponse }
  | { ok: false; status: number; detail: ForkItineraryDetail };

/**
 * Typed wrapper for POST /itinerary/{itinerary_id}/fork (G2). Deep-copies the
 * itinerary into an independently-editable alternative version and returns the
 * fork's graph — `graph.itinerary.id` is the new fork. Owner/creator/advisor
 * only (403 → `forbidden`); 404 → `not_found`.
 */
export async function forkItinerary(
  client: Client,
  itineraryId: string,
  title?: string,
): Promise<ForkItineraryResult> {
  try {
    const { data, error, response } =
      await forkItineraryEndpointItineraryItineraryIdForkPost({
        client,
        path: { itinerary_id: itineraryId },
        body: title ? { title } : {},
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, graph: data };
    }
    return {
      ok: false,
      status: response.status,
      detail:
        response.status === 404
          ? "not_found"
          : response.status === 403
            ? "forbidden"
            : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type GetForkDiffResult =
  | { ok: true; diff: ForkDiffResponse }
  | { ok: false; status: number; detail: ForkReconcileDetail };

/**
 * Typed wrapper for GET /itinerary/{fork_id}/diff — the fork's divergence from
 * its baseline (added/removed/changed/moved), paired by lineage. Owner/creator/
 * advisor only.
 */
export async function getForkDiff(
  client: Client,
  forkItineraryId: string,
): Promise<GetForkDiffResult> {
  try {
    const { data, error, response } =
      await diffForkEndpointItineraryForkIdDiffGet({
        client,
        path: { fork_id: forkItineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, diff: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseForkReconcileDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ReconcileForkResult =
  | { ok: true; result: ReconcileResponse }
  | { ok: false; status: number; detail: ForkReconcileDetail };

/**
 * Typed wrapper for POST /itinerary/{fork_id}/reconcile (advisor only). Folds
 * the accepted changes into the live baseline; per-change outcomes (applied /
 * refused_booked / discarded) come back in the body, not as a 409 — a booked
 * refusal is the expected "kept (booked)" row, not an error.
 */
export async function reconcileFork(
  client: Client,
  forkItineraryId: string,
  body: ReconcileRequest,
): Promise<ReconcileForkResult> {
  try {
    const { data, error, response } =
      await reconcileForkEndpointItineraryForkIdReconcilePost({
        client,
        path: { fork_id: forkItineraryId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, result: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseForkReconcileDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type RequestReconcileResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: ForkReconcileDetail };

/**
 * Typed wrapper for POST /itinerary/{fork_id}/request-reconcile. The traveler
 * (or agent) asks staff to merge the alternative; an advisor executes it.
 */
export async function requestReconcile(
  client: Client,
  forkItineraryId: string,
  body: RequestReconcileRequest = {},
): Promise<RequestReconcileResult> {
  try {
    const { data, error, response } =
      await requestReconcileEndpointItineraryForkIdRequestReconcilePost({
        client,
        path: { fork_id: forkItineraryId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseForkReconcileDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type AbandonForkResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: ForkReconcileDetail };

/** Typed wrapper for POST /itinerary/{fork_id}/abandon (advisor or owner). */
export async function abandonFork(
  client: Client,
  forkItineraryId: string,
): Promise<AbandonForkResult> {
  try {
    const { data, error, response } =
      await abandonForkEndpointItineraryForkIdAbandonPost({
        client,
        path: { fork_id: forkItineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseForkReconcileDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type CancelReconcileResult =
  | { ok: true; itinerary: ItineraryResponse }
  | { ok: false; status: number; detail: ForkReconcileDetail };

/**
 * Typed wrapper for POST /itinerary/{fork_id}/cancel-reconcile. The inverse of
 * `requestReconcile`: the traveler withdraws a pending merge request and the
 * fork stays open so they keep editing their alternative.
 */
export async function cancelReconcile(
  client: Client,
  forkItineraryId: string,
): Promise<CancelReconcileResult> {
  try {
    const { data, error, response } =
      await cancelReconcileEndpointItineraryForkIdCancelReconcilePost({
        client,
        path: { fork_id: forkItineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, itinerary: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseForkReconcileDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Invoices (M005/I1) ──────────────────────────────────────────────────────

export type InvoiceDetail =
  | "not_found"
  | "advisor_only"
  | "forbidden"
  | "invoice_not_draft"
  | "invoice_closed"
  | "currency_mismatch"
  | "node_has_no_cost"
  | "already_reversed"
  | "no_line_items"
  | "line_not_found"
  | "currency_invalid"
  | "nothing_to_deposit"
  | "nothing_to_bill"
  | "validation_error"
  | "network_error"
  | "unknown";

const _INVOICE_TOKENS = new Set<InvoiceDetail>([
  "invoice_not_draft",
  "invoice_closed",
  "currency_mismatch",
  "node_has_no_cost",
  "already_reversed",
  "no_line_items",
  "line_not_found",
  "currency_invalid",
  "nothing_to_deposit",
  "nothing_to_bill",
]);

function _parseInvoiceDetail(status: number, error?: unknown): InvoiceDetail {
  const token = _detailToken(error);
  if (_INVOICE_TOKENS.has(token as InvoiceDetail)) return token as InvoiceDetail;
  if (status === 404) return "not_found";
  if (status === 403) return token === "advisor_only" ? "advisor_only" : "forbidden";
  if (status === 400 || status === 422) return "validation_error";
  return "unknown";
}

export type CreateInvoiceResult =
  | { ok: true; invoice: InvoiceResponse }
  | { ok: false; status: number; detail: InvoiceDetail };

/** POST /itinerary/{itinerary_id}/invoices — create a draft invoice (advisor). */
export async function createInvoice(
  client: Client,
  itineraryId: string,
  body: CreateInvoiceRequest,
): Promise<CreateInvoiceResult> {
  try {
    const { data, error, response } =
      await createInvoiceEndpointItineraryItineraryIdInvoicesPost({
        client,
        path: { itinerary_id: itineraryId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

/** POST /itinerary/{itinerary_id}/invoices/deposit — draft a deposit invoice
 *  (100% of flights, 20% of everything else) over the chargeable nodes (advisor). */
export async function createDepositInvoice(
  client: Client,
  itineraryId: string,
): Promise<CreateInvoiceResult> {
  try {
    const { data, error, response } =
      await createDepositInvoiceEndpointItineraryItineraryIdInvoicesDepositPost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

/** POST /itinerary/{itinerary_id}/invoices/final — draft a balance invoice for
 *  every chargeable node's remaining balance (advisor). */
export async function createFinalInvoice(
  client: Client,
  itineraryId: string,
): Promise<CreateInvoiceResult> {
  try {
    const { data, error, response } =
      await createFinalInvoiceEndpointItineraryItineraryIdInvoicesFinalPost({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListInvoicesResult =
  | { ok: true; invoices: InvoiceResponse[] }
  | { ok: false; status: number; detail: InvoiceDetail };

/** GET /itinerary/{itinerary_id}/invoices — list (advisor or owning client). */
export async function listInvoices(
  client: Client,
  itineraryId: string,
): Promise<ListInvoicesResult> {
  try {
    const { data, error, response } =
      await listInvoicesEndpointItineraryItineraryIdInvoicesGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoices: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type GetInvoiceResult =
  | { ok: true; invoice: InvoiceResponse }
  | { ok: false; status: number; detail: InvoiceDetail };

/** GET /invoices/{invoice_id} — invoice with its ledger + total. */
export async function getInvoice(
  client: Client,
  invoiceId: string,
): Promise<GetInvoiceResult> {
  try {
    const { data, error, response } = await getInvoiceEndpointInvoicesInvoiceIdGet({
      client,
      path: { invoice_id: invoiceId },
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type AddLineItemResult =
  | { ok: true; line: InvoiceLineItemResponse }
  | { ok: false; status: number; detail: InvoiceDetail };

/**
 * POST /invoices/{invoice_id}/line-items (advisor). A manual signed line (a
 * discount/adjustment is negative), or a charge derived from a node's cost when
 * `amount` is omitted and `node_id` is set.
 */
export async function addInvoiceLineItem(
  client: Client,
  invoiceId: string,
  body: AddLineItemRequest,
): Promise<AddLineItemResult> {
  try {
    const { data, error, response } =
      await addLineItemEndpointInvoicesInvoiceIdLineItemsPost({
        client,
        path: { invoice_id: invoiceId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, line: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type VoidLineItemResult =
  | { ok: true; line: InvoiceLineItemResponse }
  | { ok: false; status: number; detail: InvoiceDetail };

/** POST /invoices/{invoice_id}/line-items/{line_id}/void — append a reversal (advisor). */
export async function voidInvoiceLineItem(
  client: Client,
  invoiceId: string,
  lineId: string,
): Promise<VoidLineItemResult> {
  try {
    const { data, error, response } =
      await voidLineItemEndpointInvoicesInvoiceIdLineItemsLineIdVoidPost({
        client,
        path: { invoice_id: invoiceId, line_id: lineId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, line: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type RemoveLineItemResult =
  | { ok: true }
  | { ok: false; status: number; detail: InvoiceDetail };

/** DELETE /invoices/{invoice_id}/line-items/{line_id} — draft-only hard delete (advisor). */
export async function removeInvoiceLineItem(
  client: Client,
  invoiceId: string,
  lineId: string,
): Promise<RemoveLineItemResult> {
  try {
    const { error, response } =
      await deleteLineItemEndpointInvoicesInvoiceIdLineItemsLineIdDelete({
        client,
        path: { invoice_id: invoiceId, line_id: lineId },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type IssueInvoiceResult =
  | { ok: true; invoice: InvoiceResponse }
  | { ok: false; status: number; detail: InvoiceDetail };

/** POST /invoices/{invoice_id}/issue — draft → issued (advisor). */
export async function issueInvoice(
  client: Client,
  invoiceId: string,
): Promise<IssueInvoiceResult> {
  try {
    const { data, error, response } =
      await issueInvoiceEndpointInvoicesInvoiceIdIssuePost({
        client,
        path: { invoice_id: invoiceId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type VoidInvoiceResult =
  | { ok: true; invoice: InvoiceResponse }
  | { ok: false; status: number; detail: InvoiceDetail };

/** POST /invoices/{invoice_id}/void — cancel an invoice (advisor). */
export async function voidInvoice(
  client: Client,
  invoiceId: string,
): Promise<VoidInvoiceResult> {
  try {
    const { data, error, response } =
      await voidInvoiceEndpointInvoicesInvoiceIdVoidPost({
        client,
        path: { invoice_id: invoiceId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parseInvoiceDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Payments (M005/I2) ──────────────────────────────────────────────────────

export type PaymentDetail =
  | "not_found"
  | "forbidden"
  | "invoice_not_issued"
  | "payment_declined"
  | "payments_unconfigured"
  | "nothing_to_pay"
  | "quote_required"
  | "quote_expired"
  | "no_settlement_currency"
  | "fx_unavailable"
  | "rate_unavailable"
  | "validation_error"
  | "network_error"
  | "unknown";

const _PAYMENT_TOKENS = new Set<PaymentDetail>([
  "invoice_not_issued",
  "payment_declined",
  "payments_unconfigured",
  "nothing_to_pay",
  "quote_required",
  "quote_expired",
  "no_settlement_currency",
  "fx_unavailable",
  "rate_unavailable",
]);

function _parsePaymentDetail(status: number, error?: unknown): PaymentDetail {
  const token = _detailToken(error);
  if (_PAYMENT_TOKENS.has(token as PaymentDetail)) return token as PaymentDetail;
  if (status === 404) return "not_found";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 422) return "validation_error";
  return "unknown";
}

export type GetPaymentTokenResult =
  | { ok: true; clientToken: string }
  | { ok: false; status: number; detail: PaymentDetail };

/** POST /invoices/{invoice_id}/payment-token — a gateway client token for the drop-in. */
export async function getPaymentToken(
  client: Client,
  invoiceId: string,
): Promise<GetPaymentTokenResult> {
  try {
    const { data, error, response } =
      await paymentTokenEndpointInvoicesInvoiceIdPaymentTokenPost({
        client,
        path: { invoice_id: invoiceId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, clientToken: data.client_token };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePaymentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type GetPayContextResult =
  | { ok: true; context: InvoicePayContextResponse }
  | { ok: false; status: number; detail: PaymentDetail };

/**
 * GET /invoices/{invoice_id}/pay-context — trip title + the owning traveler's
 * billing identity, used to narrate *why* the invoice is owed and to pre-fill the
 * pay form. Gated like the invoice read (advisor / owning client / creator).
 */
export async function getPayContext(
  client: Client,
  invoiceId: string,
): Promise<GetPayContextResult> {
  try {
    const { data, error, response } =
      await invoicePayContextEndpointInvoicesInvoiceIdPayContextGet({
        client,
        path: { invoice_id: invoiceId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, context: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePaymentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type PaymentQuote = {
  id: string;
  invoiceId: string;
  settlementCurrency: string;
  settlementAmount: string;
  rates: Record<string, string>;
  expiresAt: string;
};

export type CreatePaymentQuoteResult =
  | { ok: true; quote: PaymentQuote }
  | { ok: false; status: number; detail: PaymentDetail };

/**
 * POST /invoices/{invoice_id}/payment-quote — freeze a short-lived FX lock for a
 * settlement (pay-currency) invoice (0050). The returned quote's `id` is passed to
 * `payInvoice`; an expired quote (`quote_expired`) forces a re-quote.
 */
export async function createPaymentQuote(
  client: Client,
  invoiceId: string,
): Promise<CreatePaymentQuoteResult> {
  try {
    const { data, error, response } =
      await paymentQuoteEndpointInvoicesInvoiceIdPaymentQuotePost({
        client,
        path: { invoice_id: invoiceId },
      });
    if (error === undefined && data !== undefined) {
      return {
        ok: true,
        quote: {
          id: data.id,
          invoiceId: data.invoice_id,
          settlementCurrency: data.settlement_currency,
          settlementAmount: data.settlement_amount,
          rates: data.rates,
          expiresAt: data.expires_at,
        },
      };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePaymentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type PayInvoiceResult =
  | { ok: true; invoice: InvoiceResponse }
  | { ok: false; status: number; detail: PaymentDetail };

/**
 * POST /invoices/{invoice_id}/pay — charge an issued invoice with a tokenized
 * card nonce (owning client or advisor). Returns the updated invoice (now
 * `paid`, with the payment in its history). `payment_declined` on a soft refusal.
 */
export async function payInvoice(
  client: Client,
  invoiceId: string,
  body: PayInvoiceRequest,
): Promise<PayInvoiceResult> {
  try {
    const { data, error, response } =
      await payInvoiceEndpointInvoicesInvoiceIdPayPost({
        client,
        path: { invoice_id: invoiceId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, invoice: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: _parsePaymentDetail(response.status, error),
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Bookings + money gate (M005/I3) ─────────────────────────────────────────

export type BookingDetail =
  // 409 — money gate / lifecycle preconditions
  | "node_not_paid"
  | "dates_not_pinned"
  | "already_booked"
  | "node_not_approved"
  | "node_not_booked"
  | "no_booking"
  | "offer_required"
  | "offer_expired"
  | "offer_unavailable"
  | "reprice_failed"
  // 409 — cancel + refund
  | "already_cancelled"
  | "refund_declined"
  | "refund_gateway_unavailable"
  | "payments_unconfigured"
  // 409 — real supplier booking (Bokun): reserve/confirm/cancel failed upstream
  | "supplier_selection_required"
  | "supplier_reserve_failed"
  | "supplier_confirm_failed"
  | "supplier_cancel_failed"
  | "supplier_provider_unavailable"
  | "supplier_availability_failed"
  | "node_not_supplier_bookable"
  // 400 — validation
  | "node_has_no_cost"
  | "offer_unpriced"
  | "supplier_ref_required"
  | "not_found"
  | "advisor_only"
  | "forbidden"
  | "validation_error"
  | "network_error"
  | "unknown";

const _BOOKING_TOKENS = new Set<BookingDetail>([
  "node_not_paid",
  "dates_not_pinned",
  "already_booked",
  "node_not_approved",
  "node_not_booked",
  "no_booking",
  "offer_required",
  "offer_expired",
  "offer_unavailable",
  "reprice_failed",
  "already_cancelled",
  "refund_declined",
  "refund_gateway_unavailable",
  "payments_unconfigured",
  "supplier_selection_required",
  "supplier_reserve_failed",
  "supplier_confirm_failed",
  "supplier_cancel_failed",
  "supplier_provider_unavailable",
  "supplier_availability_failed",
  "node_not_supplier_bookable",
  "node_has_no_cost",
  "offer_unpriced",
  "supplier_ref_required",
]);

function _parseBookingDetail(status: number, error?: unknown): BookingDetail {
  const token = _detailToken(error);
  if (_BOOKING_TOKENS.has(token as BookingDetail)) return token as BookingDetail;
  if (status === 404) return "not_found";
  if (status === 403) return token === "advisor_only" ? "advisor_only" : "forbidden";
  if (status === 400 || status === 422) return "validation_error";
  return "unknown";
}

export type RefreshOfferResult =
  | { ok: true; offer: OfferResponse }
  | { ok: false; status: number; detail: BookingDetail };

/** POST /itinerary/{id}/nodes/{nodeId}/offers/refresh — re-price a held offer (advisor). */
export async function refreshOffer(
  client: Client,
  itineraryId: string,
  nodeId: string,
): Promise<RefreshOfferResult> {
  try {
    const { data, error, response } =
      await refreshOfferEndpointItineraryItineraryIdNodesNodeIdOffersRefreshPost({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, offer: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ListOffersResult =
  | { ok: true; offers: OfferResponse[] }
  | { ok: false; status: number; detail: BookingDetail };

/** GET /itinerary/{id}/nodes/{nodeId}/offers — a node's offer history (newest first). */
export async function listOffers(
  client: Client,
  itineraryId: string,
  nodeId: string,
): Promise<ListOffersResult> {
  try {
    const { data, error, response } =
      await listOffersEndpointItineraryItineraryIdNodesNodeIdOffersGet({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, offers: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type NodeChargesResult =
  | { ok: true; charges: NodeChargesResponse }
  | { ok: false; status: number; detail: BookingDetail };

/** GET /itinerary/{id}/nodes/{nodeId}/charges — the card's money facet (M006/PS4):
 *  this item's charge line, invoice status, paid/owed split, and live booking. */
export async function getNodeCharges(
  client: Client,
  itineraryId: string,
  nodeId: string,
): Promise<NodeChargesResult> {
  try {
    const { data, error, response } =
      await nodeChargesEndpointItineraryItineraryIdNodesNodeIdChargesGet({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, charges: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type BookNodeResult =
  | { ok: true; booking: BookingResponse }
  | { ok: false; status: number; detail: BookingDetail };

/** POST /itinerary/{id}/nodes/{nodeId}/book — money gate: book an approved, paid node (advisor). */
export async function bookNode(
  client: Client,
  itineraryId: string,
  nodeId: string,
  body: BookNodeRequest = { override_unpaid: false },
): Promise<BookNodeResult> {
  try {
    const { data, error, response } =
      await bookNodeEndpointItineraryItineraryIdNodesNodeIdBookPost({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, booking: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ConfirmNodeResult =
  | { ok: true; booking: BookingResponse }
  | { ok: false; status: number; detail: BookingDetail };

/** POST /itinerary/{id}/nodes/{nodeId}/confirm — record a supplier confirmation # (advisor). */
export async function confirmNode(
  client: Client,
  itineraryId: string,
  nodeId: string,
  body: RecordConfirmationRequest,
): Promise<ConfirmNodeResult> {
  try {
    const { data, error, response } =
      await confirmNodeEndpointItineraryItineraryIdNodesNodeIdConfirmPost({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, booking: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type CancelBookingResult =
  | { ok: true; booking: BookingResponse }
  | { ok: false; status: number; detail: BookingDetail };

/** POST /itinerary/{id}/nodes/{nodeId}/cancel — cancel + refund a booked node (advisor). */
export async function cancelBooking(
  client: Client,
  itineraryId: string,
  nodeId: string,
  body: CancelBookingRequest = {},
): Promise<CancelBookingResult> {
  try {
    const { data, error, response } =
      await cancelNodeEndpointItineraryItineraryIdNodesNodeIdCancelPost({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
        body,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, booking: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type ReconciliationResult =
  | { ok: true; reconciliation: ReconciliationResponse }
  | { ok: false; status: number; detail: BookingDetail };

/** GET /itinerary/{id}/reconciliation — Σ(paid lines) ⇔ Σ(booked node costs). */
export async function getReconciliation(
  client: Client,
  itineraryId: string,
): Promise<ReconciliationResult> {
  try {
    const { data, error, response } =
      await reconciliationEndpointItineraryItineraryIdReconciliationGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, reconciliation: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

export type SupplierAvailabilityResult =
  | { ok: true; slots: SupplierAvailabilityResponse[] }
  | { ok: false; status: number; detail: BookingDetail };

/**
 * GET /itinerary/{id}/nodes/{nodeId}/supplier-availability — real bookable slots
 * for a supplier-sourced node (Bokun). Feeds the {@link bookNode}
 * `supplier_selection`. `node_not_supplier_bookable` when the node isn't a
 * supplier source or supplier booking is disabled.
 */
export async function supplierAvailability(
  client: Client,
  itineraryId: string,
  nodeId: string,
  params: { start: string; end: string; currency?: string },
): Promise<SupplierAvailabilityResult> {
  try {
    const { data, error, response } =
      await supplierAvailabilityEndpointItineraryItineraryIdNodesNodeIdSupplierAvailabilityGet({
        client,
        path: { itinerary_id: itineraryId, node_id: nodeId },
        query: { start: params.start, end: params.end, currency: params.currency },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, slots: data };
    }
    return { ok: false, status: response.status, detail: _parseBookingDetail(response.status, error) };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Place brief (chat place drawer) ──────────────────────────────────────

export type {
  FactbookTexture,
  PlaceBrief,
  ResolvedPlace,
  WikipediaTexture,
} from "./generated/types.gen.js";

export type PlaceBriefDetail = "place_not_found" | "network_error" | "unknown";

/**
 * Discriminated result for POST /places/brief — server-side place resolution
 * (Google Places Text Search) plus texture (CIA World Factbook + Wikipedia)
 * for the drawer beside the chat. 404 means the query resolved to nothing
 * usable; texture fields inside a 200 brief may independently be null.
 */
export type PlaceBriefResult =
  | { ok: true; brief: import("./generated/types.gen.js").PlaceBrief }
  | { ok: false; status: number; detail: PlaceBriefDetail };

/**
 * Typed wrapper for POST /places/brief.
 */
export async function getPlaceBrief(
  client: Client,
  query: string,
): Promise<PlaceBriefResult> {
  try {
    const { data, error, response } = await placeBriefPlacesBriefPost({
      client,
      body: { query },
    });
    if (error === undefined && data !== undefined) {
      return { ok: true, brief: data };
    }
    return {
      ok: false,
      status: response.status,
      detail: response.status === 404 ? "place_not_found" : "unknown",
    };
  } catch {
    return { ok: false, status: 0, detail: "network_error" };
  }
}

// ── Itinerary export (PDF / XLSX) + day notes ────────────────────────────────

export type DayNoteResponse =
  import("./generated/types.gen.js").DayNoteResponse;
export type DayNoteContent =
  import("./generated/types.gen.js").DayNoteContent;
export type DayNotesListResponse =
  import("./generated/types.gen.js").DayNotesListResponse;

export type ItineraryExportResult =
  | { ok: true; blob: Blob; filename: string }
  | { ok: false; status: number };

export type DayNotesListResult =
  | { ok: true; notes: DayNoteResponse[] }
  | { ok: false; status: number };

export type DayNoteResult =
  | { ok: true; note: DayNoteResponse }
  | { ok: false; status: number };

function _filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      // fall through to the ASCII form
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1] ?? fallback;
}

/**
 * Download an itinerary (trunk or any fork the caller can read) as a PDF or
 * XLSX. Returns the raw bytes as a Blob plus the server-suggested filename —
 * the caller creates an object URL and clicks a download link. Uses
 * `parseAs: "blob"` so the binary body isn't JSON-parsed.
 */
export async function downloadItineraryExport(
  client: Client,
  itineraryId: string,
  format: "pdf" | "xlsx",
): Promise<ItineraryExportResult> {
  try {
    const { data, error, response } =
      await exportItineraryEndpointItineraryItineraryIdExportGet({
        client,
        path: { itinerary_id: itineraryId },
        query: { format },
        parseAs: "blob",
      });
    if (error === undefined && data !== undefined) {
      const filename = _filenameFromDisposition(
        response.headers.get("content-disposition"),
        `itinerary.${format}`,
      );
      return { ok: true, blob: data as Blob, filename };
    }
    return { ok: false, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** List an itinerary's per-day notes (readable by anyone who can read it). */
export async function listDayNotes(
  client: Client,
  itineraryId: string,
): Promise<DayNotesListResult> {
  try {
    const { data, error, response } =
      await listDayNotesEndpointItineraryItineraryIdDayNotesGet({
        client,
        path: { itinerary_id: itineraryId },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, notes: data.notes };
    }
    return { ok: false, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** Advisor: upsert hand-written notes for one day (source=advisor). */
export async function putDayNote(
  client: Client,
  itineraryId: string,
  dayDate: string,
  content: DayNoteContent,
): Promise<DayNoteResult> {
  try {
    const { data, error, response } =
      await putDayNoteEndpointItineraryItineraryIdDayNotesDayDatePut({
        client,
        path: { itinerary_id: itineraryId, day_date: dayDate },
        body: content,
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, note: data };
    }
    return { ok: false, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** Advisor: delete a day's notes (reverts to auto-fill on next export). */
export async function deleteDayNote(
  client: Client,
  itineraryId: string,
  dayDate: string,
): Promise<{ ok: true } | { ok: false; status: number }> {
  try {
    const { error, response } =
      await deleteDayNoteEndpointItineraryItineraryIdDayNotesDayDateDelete({
        client,
        path: { itinerary_id: itineraryId, day_date: dayDate },
      });
    if (error === undefined) {
      return { ok: true };
    }
    return { ok: false, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** Advisor: (re)generate day notes with AI (409 when the LLM lane is off). */
export async function generateDayNotes(
  client: Client,
  itineraryId: string,
  days?: string[],
): Promise<DayNotesListResult> {
  try {
    const { data, error, response } =
      await generateDayNotesEndpointItineraryItineraryIdDayNotesGeneratePost({
        client,
        path: { itinerary_id: itineraryId },
        body: { days: days ?? null },
      });
    if (error === undefined && data !== undefined) {
      return { ok: true, notes: data.notes };
    }
    return { ok: false, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}
