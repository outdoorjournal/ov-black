"use client";

// View-agnostic domain store for an itinerary graph.
//
// This is the single source of truth that every *view* of the graph (the
// horizontal timeline, a future calendar view, etc.) reads and mutates. It
// owns the domain — nodes, edges, proposals, focus, and the staff editing
// lifecycle (lock / release / approve, field edits, drag-reorder persistence,
// add / remove) — and is deliberately ignorant of how any view draws it.
//
// The viewer's `role` is resolved on the server and threaded in at
// construction; `canEdit` is DERIVED from it (`role === "advisor"`) rather
// than passed as its own boolean — role is the single source of truth both
// the server and client already hold. Each viewer is handed their OWN Supabase
// token (already present in their browser session), so the credentials are
// non-null for travelers too — that is what lets the traveler-facing concierge
// run. Editing actions still gate on `canEdit`/`selectEditable`, and the
// backend's advisor guards remain the real authority; `canEdit` only governs
// whether we render and attempt the mutations at all.
//
// NOTE: the zoom fields (`pxPerMinute` + zoom actions) are horizontal-view UI
// state that currently lives here for convenience. When a second view lands,
// extract per-view UI state into a view-local store and keep this store purely
// domain.

import {
  abandonFork,
  acquireItineraryLock,
  approveAllNodes,
  cancelReconcile,
  createApiClient,
  createNode,
  createNodeFromInventory,
  createNodeFromLink,
  deleteNode,
  fillGap,
  forkItinerary,
  getAnalysis,
  getForkDiff,
  getItinerary,
  listInvoices,
  reconcileFork,
  releaseItineraryLock,
  requestReconcile,
  searchInventory,
  startAnalysis,
  updateNode,
  updateNodeStatus,
  type AnalysisStatus,
  type CostKind,
  type DisplayStatus,
  type FillProposalResponse,
  type FindingResponse,
  type ForkDiffResponse,
  type SearchInventoryQuery,
  type SearchInventoryResponse,
} from "@ov-black/api-client";

import { createStoreContext } from "@/lib/store/createStoreContext";
import { createBrowserSupabase } from "@/lib/supabase/client";
import {
  billingChipsByNode,
  type BillingChip,
} from "@/app/itinerary/[id]/_shell/dashboardModel";
import type { UserRole } from "@/lib/role";

import { offsetHoursOr } from "../model/horizontalTime";
import type {
  EdgeResponse,
  ItineraryTimeline,
  NodeResponse,
  NodeType,
} from "../model/horizontalTypes";

/** A single inventory search result (the element of the search response). */
type InventoryItem = SearchInventoryResponse["items"][number];

/** A scheduled gap to fill — ISO start/end, the GapModel shape the API wants. */
export type FillGapWindow = { start: string; end: string };

// Shape of a node as emitted by the agent stream before it's persisted as a
// graph node. Mirrors the open-metadata NodeResponse but keeps type/status as
// plain strings so streamed proposals don't need the literal unions yet.
export interface AgentNode {
  id: string;
  itinerary_id: string;
  type: string;
  status: string;
  title: string;
  source: string | null;
  source_id: string | null;
  metadata: Record<string, unknown>;
  // A server-persisted node can be a subgraph CHILD (a day of a multi-day
  // package / campaign cornerstone). Carrying its parent id lets the Journal
  // derive it as a journey beat live, before a reload rehydrates the graph —
  // without it the child renders as a parentless top-level card (or not at all).
  parent_subgraph_id?: string | null;
}

export interface ChatMessage {
  id: string;
  // `error` renders the crafted D015 fallback copy (content ignored). It's a
  // persisted turn role, so replayed history must be able to carry it — see
  // ConciergeChat history hydration.
  role: "user" | "assistant" | "system" | "error";
  text: string;
  streaming?: boolean;
}

// Lock is tracked locally — the API's ItineraryResponse does not expose
// locked_by, so we treat "unlocked" as the default and flip on the lock/
// release calls (already_locked → locked-by-other). Mirrors the S08 advisor
// editor contract.
export type LockStatus = "unlocked" | "locked-by-me" | "locked-by-other";

// ── Horizontal-view zoom (see NOTE above) ─────────────────────────────
export const ZOOM_MIN = 0.6;
export const ZOOM_MAX = 6.0;
export const ZOOM_PRESETS = {
  day: 1.2,
  hour: 2.5,
  quarter: 6.0,
} as const;
export type ZoomPreset = keyof typeof ZOOM_PRESETS;

export function clampZoom(value: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
}

// ── Journal zoom (traveler-journal) ───────────────────────────────────
// The Journal is event-proportional, not a clock: this scale only sizes the
// duration bars hanging off each card and the height of the gaps between them
// (plus the hour ticks that fall inside those gaps), so "time passing" reads
// without turning the story into a ruler. Much coarser than the horizontal
// planner's px-per-minute — a two-hour dinner is a bar of tens of pixels, not
// hundreds. See Spine.DurationBar / VirtualNode.
export const JOURNAL_ZOOM_MIN = 0.12;
export const JOURNAL_ZOOM_MAX = 1.2;
export const JOURNAL_ZOOM_PRESETS = {
  cozy: 0.22,
  hour: 0.45,
  detail: 0.9,
} as const;
export type JournalZoomPreset = keyof typeof JOURNAL_ZOOM_PRESETS;

export function clampJournalZoom(value: number): number {
  return Math.min(JOURNAL_ZOOM_MAX, Math.max(JOURNAL_ZOOM_MIN, value));
}

/**
 * How the focused node became focused (the Journal's scroll-active system).
 * `click` is a deliberate pin — scroll observation must not steal it until the
 * pinned card leaves the viewport band; `scroll` is ambient and freely
 * superseded. `null` means no Journal interaction has happened yet (the rail
 * shows its idle state even though a default focus may be set).
 */
export type FocusSource = "scroll" | "click";

// Place mode (PS5): pick-then-place scheduling. `HeldItem` is the card lifted
// off the Collection and floating, waiting for a slot; `PlacedItem` is the
// just-dropped card the undo toast can return to the Collection.
export type HeldItem = { nodeId: string; title: string };
export type PlacedItem = {
  nodeId: string;
  title: string;
  dayKey: string;
  minute: number;
};

export type ItineraryGraphState = {
  // ── identity / config ──
  itineraryId: string;
  /** The viewer's resolved role — the source of truth for capability. */
  role: UserRole;
  /** Derived from `role` (advisor) at construction; not threaded as a prop. */
  canEdit: boolean;
  apiBaseUrl: string | null;
  accessToken: string | null;

  // ── domain ──
  sample: ItineraryTimeline;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pendingProposals: NodeResponse[];
  messages: ChatMessage[];
  focusedNodeId: string | null;
  /** Provenance of `focusedNodeId` — see `FocusSource`. */
  focusSource: FocusSource | null;
  /** A HARD focus lock: while true nothing but a deliberate focus of ANOTHER
   *  node moves focus — the Journal's scroll observer stands down entirely.
   *  Set when the 2xl inline detail is expanded ("Open full"), so scrolling the
   *  timeline can't swap the card out from under it; cleared on dismiss or when
   *  a different node is focused. */
  focusLocked: boolean;
  flashNodeId: string | null;
  assemblePulse: number;
  /** A monotonic nonce bumped whenever the agent changes the trip's travel
   *  party (a `party_updated`/`party_changed` frame). The travel party is a
   *  client-side fetch (not a server prop), so `router.refresh()` can't re-run
   *  it — surfaces that display the roster (the dashboard hero chip) key their
   *  fetch effect off this so a mid-chat seat/unseat re-reads the roster. */
  partyRevision: number;

  // ── staff editing lifecycle ──
  /** Derived trunk lifecycle from the API (in_studio / with_traveler / approved). */
  status: DisplayStatus;
  lockStatus: LockStatus;
  lockPending: boolean;
  releasePending: boolean;
  approvePending: boolean;
  /** id of the node whose per-node approve is in flight (disables its button). */
  approvingNodeId: string | null;
  /** Per-currency price of the plan (ADV-10), `{ currency: amount }` from the
   *  GraphResponse — amounts are strings; empty when nothing is priced. */
  totals: Record<string, string>;
  /** 0048: the traveler's preferred display currency + the whole plan's total
   *  converted into it (across mixed native currencies). Both null when the
   *  client has no preferred currency or FX can't resolve — the UI then falls
   *  back to the native `totals` map above. */
  displayCurrency: string | null;
  totalDisplay: string | null;
  /** ADV-15: node id → its billing chip (unbilled / partial / billed / paid),
   *  the board-side read of "how do the invoices relate to the inventory".
   *  Populated by `refreshBilling` (advisor only); empty otherwise. */
  billingChips: Record<string, BillingChip>;

  // ── two-version (Official ↔ My version) lifecycle, traveler-facing ──
  /** The viewer's own OPEN fork of this baseline, if any (from the API). Null
   *  on a fork itself or when the viewer has no open alternative. */
  viewerOpenForkId: string | null;
  /** On a baseline with no fork yet, the traveler toggled into editable "My
   *  version" preview — still a read-through of Official until the first edit
   *  materializes the fork. */
  draftMine: boolean;
  forking: boolean;
  requestingMerge: boolean;
  mergeRequested: boolean;
  cancelingMerge: boolean;
  discarding: boolean;
  /** Publish (advisor): reconcile this working copy into the trunk, accept-all. */
  publishing: boolean;
  /** The publish was refused by a blocking feasibility finding — the advisor
   *  reviews/overrides in the diff panel instead of the fast path. */
  publishBlocked: boolean;
  /** Traveler on an advisor-crafted trunk with nothing published yet — the
   *  timeline shows the "being crafted" teaser instead of the builder empty
   *  state (which is the solo/self-serve prompt). */
  awaitingProposal: boolean;

  // ── diff mode (phase 4): unified fork-vs-trunk compare over the Journal ──
  /** Reading this fork AGAINST its baseline — a toggle over the same Journal
   *  DOM (never a route). Only meaningful on a fork; content editing gestures
   *  are disabled while on (a reading/deciding mode — notes stay open). */
  diffMode: boolean;
  /** The G3 `diff_fork` response the Journal renders from; null until the
   *  first fetch lands. */
  diff: ForkDiffResponse | null;
  diffLoading: boolean;
  diffError: boolean;
  /** change_id → accept (true) | keep the original (false). Defaults to
   *  accept — the same convention as the DiffPanel. Advisor-facing: the rail's
   *  per-change accept/keep toggles write here; `applyDiffDecisions` sends the
   *  whole map in one reconcile pass (full coverage flips the fork's status
   *  server-side; per-change calls never would). */
  diffDecisions: Record<string, boolean>;
  /** change_id → outcome result from the last reconcile pass (applied /
   *  discarded / refused_booked / …) — `refused_booked` renders as a lock
   *  explanation, not an error. */
  diffOutcomes: Record<string, string>;
  /** The reconcile pass in flight. */
  diffApplying: boolean;
  /** The reconcile was refused by a blocking feasibility finding — review /
   *  override lives in the Timeline's Diff tab (the full panel). */
  diffBlocked: boolean;

  // ── cinema mode (phase 5): the Journal's autoscroll reading ──
  /** Cinema — a mode FLAG over the same Journal DOM (never a view): chrome
   *  fades out, the ambient layer goes full-bleed, and a rAF scroll driver
   *  eases from node to node. Mutually exclusive with `diffMode` — both are
   *  reading modes over the same DOM and their vocabularies would collide. */
  cinemaMode: boolean;

  // ── horizontal-view UI state ──
  pxPerMinute: number;

  // ── journal-view UI state ──
  /** Scale for the Journal's duration bars + gap heights (see JOURNAL_ZOOM_*). */
  journalPxPerMinute: number;

  // ── place mode (PS5): pick-then-place ──
  /** The card lifted off the Collection, floating until it lands on a slot. */
  heldItem: HeldItem | null;
  /** The most recent placement — drives the undo toast; cleared on undo/dismiss. */
  lastPlacement: PlacedItem | null;
  /** Lift a Collection card into the holding chip (start place mode). */
  holdItem: (nodeId: string) => void;
  /** Cancel place mode without placing (Esc / the chip's cancel). */
  clearHeldItem: () => void;
  /** Drop the held card onto (dayKey, minuteOfDay) — reuses moveNode; a no-op
   *  for a viewer who can't schedule. Records the placement for undo. */
  placeHeldItem: (dayKey: string, minuteOfDay: number) => void;
  /** Undo the last placement — returns the card to the Collection. */
  undoPlacement: () => void;
  /** Dismiss the undo toast without undoing. */
  clearLastPlacement: () => void;

  // ── focus / chat ──
  /** Focus a node. `source` defaults to `click` (a deliberate pin); the
   *  Journal's scroll observer passes `scroll` so a click-pin can outrank it. */
  focusNode: (id: string | null, source?: FocusSource) => void;
  /** Set/clear the hard focus lock (see `focusLocked`). */
  setFocusLocked: (locked: boolean) => void;
  appendUserMessage: (id: string, text: string) => void;
  appendAssistantMessage: (id: string, text?: string) => void;
  appendDelta: (id: string, text: string) => void;
  finishAssistant: (id: string) => void;

  // ── proposals (agent stream) ──
  proposeNode: (node: AgentNode) => void;
  acceptProposal: (id: string) => void;
  dismissProposal: (id: string) => void;
  /** Drop a node the agent PERSISTED server-side (campaign spine) straight onto
   *  the canvas — no accept step. Idempotent by id (a reload may race). */
  insertCreatedNode: (node: AgentNode) => void;
  applyNodeUpdate: (node: AgentNode) => void;
  flashNode: (id: string | null) => void;
  pulseAssemble: () => void;
  /** Bump `partyRevision` — the agent changed the travel party, so the roster
   *  fetch keyed off it re-reads. */
  bumpPartyRevision: () => void;

  // ── staff editing actions (no-op unless editable) ──
  acquireLock: () => void;
  releaseLock: () => void;
  // `approve` (traveler, or advisor on a client's behalf): the all-at-once
  // "Approve all" on the official trunk — cascades remaining `pending` nodes to
  // `approved` via the approve-all endpoint. `approveNode` (traveler): approve a
  // single pending card; clearing the last one derives the itinerary to approved.
  approve: () => void;
  approveNode: (id: string) => void;
  // Soft-remove a node (→ `discarded`, the reversible side-state). A pure
  // status flip, so the backend admits it on a trunk without a fork — the
  // reading rack's quiet per-tile remove. Optimistic; reverts on refusal.
  discardNode: (id: string) => void;
  /** ADV-15: (re)load the per-card billing chips from the live ledger. Advisor
   *  only — a no-op for travelers or without credentials. */
  refreshBilling: () => void;
  setNodes: (nodes: NodeResponse[]) => void;
  editNodeField: (
    id: string,
    field: "title" | "source_id",
    value: string,
  ) => void;
  // ADV-13 editable cards: patch a card's details after creation — description
  // (renders in every zoom body), the operator's confirmation number (renders
  // as the booked/confirmed footer serial), and first-class cost (feeds totals
  // + billing; also how a pasted-link card finally gets priced). Fields are
  // patch-style: `undefined` leaves a field alone; an empty string clears the
  // metadata key; `cost: null` clears the cost trio. Gated like every other
  // field edit (`selectEditable` + the server's G1 firmed-node gate).
  updateCardDetails: (
    id: string,
    input: {
      description?: string;
      confirmationNumber?: string;
      cost?: { amount: string; currency: string; kind: CostKind } | null;
    },
  ) => void;
  // Re-target a node onto a different day (and optionally minute-of-day),
  // updating its start_time and persisting the new metadata when editable.
  moveNode: (id: string, dayKey: string, minuteOfDay: number | null) => void;
  addNode: (input: {
    type: NodeType;
    title: string;
    metadata?: Record<string, unknown>;
  }) => void;
  // Hand-authoring (ADV-4): create a bespoke card the inventory
  // providers don't carry. Two shapes: a typed + optionally priced card
  // (→ POST /nodes, status `proposed`), or a pasted link whose OpenGraph
  // preview the server fetches (→ POST /nodes/from-link). Gated by
  // `selectEditable || selectTravelerEditable` (an editable fork surface —
  // the Journal's blank-card insert works on the traveler's own version
  // too). `cost` is a both-or-neither
  // amount+currency with a per_person|total kind; it applies to the typed
  // shape only (from-link carries no cost). `schedule` (a day + minute-of-day)
  // places the typed card ON the timeline at that time (Outlook-style
  // create-at-slot); omit it and the card lands in the (unscheduled) Collection.
  authorNode: (input: {
    type: NodeType;
    title?: string;
    url?: string;
    note?: string;
    cost?: { amount: string; currency: string; kind: CostKind } | null;
    schedule?: { dayKey: string; minute: number } | null;
  }) => void;
  removeNode: (id: string) => void;
  // ── traveler notes (feedback for staff; gated by `selectCanLeaveNote`) ──
  // Attach a note to a host node ("why are we doing this at 1:30?").
  addAttachedNote: (hostId: string, text: string) => void;
  // Drop a free-standing note on a day at noon ("a dinner between these").
  addFreeStandingNote: (dayKey: string, text: string) => void;
  // Rewrite a note's text in place (the Journal's tap-to-edit margin notes).
  // Notes bypass the fork/approve gates like the other note writes — the
  // backend's write authorization is the real authority; reverts on failure.
  editNoteText: (id: string, text: string) => void;
  // ── Collection (wish list) writes (credentialed; backend authorizes) ──
  // A pasted web link → server fetches its OpenGraph preview into a card.
  savingLink: boolean;
  saveLinkToCollection: (url: string, kind?: NodeType, note?: string) => void;
  // A timeless note into the wish list (no anchor, no time).
  addCollectionNote: (text: string) => void;
  // Return a scheduled card to the Collection by clearing its start_time.
  unscheduleNode: (id: string) => void;
  // ── two-version (Official ↔ My version) actions ──
  // Switch between the official baseline and the traveler's version. On a fork,
  // "official" navigates to the baseline; on a baseline, "mine" navigates to an
  // existing fork or, with none yet, enters the draft-mine editable preview.
  // `navigate` is the router push the caller supplies.
  selectVersion: (
    target: "official" | "mine",
    navigate: (id: string) => void,
  ) => void;
  // Lazy fork: the traveler's FIRST edit in draft-mine mode. Forks the baseline,
  // carries this move onto the matching fork node (by lineage), then navigates
  // to the new fork via `navigate`.
  forkAndMove: (
    id: string,
    dayKey: string,
    minuteOfDay: number | null,
    navigate: (id: string) => void,
  ) => void;
  // Ask staff to merge this alternative back into the agreed plan.
  requestMerge: () => void;
  // Withdraw a pending merge request; the fork stays open (keep editing).
  cancelMerge: () => void;
  // Discard this whole alternative (abandon the fork) and go back to Official.
  discardMine: (navigate: (id: string) => void) => void;
  /** Publish (advisor, on their working copy): reconcile every change into the
   *  official trunk (`accept_all`) and navigate back to it. A blocking
   *  feasibility finding refuses the fast path and sets `publishBlocked` —
   *  the diff panel's review/override flow is the escape hatch. */
  publishMine: (navigate: (id: string) => void) => void;
  // ── diff mode actions (phase 4) ──
  /** Enter/leave compare. Entering needs a fork + credentials (a no-op
   *  otherwise) and fetches the diff. */
  setDiffMode: (on: boolean) => void;
  /** (Re)fetch `diff_fork` for this fork; seeds `diffDecisions` (accept by
   *  default) preserving any choices already made. */
  refreshDiff: () => void;
  /** The rail's per-change accept / keep-the-original toggle (advisor). */
  setDiffDecision: (changeId: string, accept: boolean) => void;
  /** Reconcile the decided changes into the trunk in ONE pass (advisor).
   *  All-accept takes the server-side `accept_all` fast path (no staleness
   *  window). Fully resolved → navigate to the trunk; refusals
   *  (`refused_booked` — G1 immutable) stay honest: outcomes recorded, the
   *  diff refreshed, the fork stays open. */
  applyDiffDecisions: (navigate: (id: string) => void) => void;

  // ── cinema mode actions (phase 5) ──
  /** Enter/leave cinema. Entering exits compare (`setDiffMode(true)` exits
   *  cinema symmetrically) — the two modes are mutually exclusive. */
  setCinemaMode: (on: boolean) => void;

  // ── authoring (B7): inventory search · analyze · fill ──
  // Reads (search/analyze/fill) gate on `canEdit`; the two writes
  // (addNodeFromInventory / acceptFillProposal) gate on `selectEditable`
  // because they mutate the graph and so need the lock.
  inventoryResults: InventoryItem[];
  inventoryPending: boolean;
  inventoryError: boolean;
  /** source_id of the item currently being added — disables its Add button. */
  addingInventoryId: string | null;
  analysisId: string | null;
  analyzeStatus: AnalysisStatus | "idle";
  analyzePending: boolean;
  findings: FindingResponse[];
  analyzeSummary: string | null;
  fillProposals: FillProposalResponse[];
  fillPending: boolean;
  fillGapWindow: FillGapWindow | null;

  runInventorySearch: (query: SearchInventoryQuery) => void;
  clearInventoryResults: () => void;
  addNodeFromInventory: (source: string, sourceId: string) => void;
  startAnalyze: () => void;
  refreshAnalysis: () => void;
  runFill: (gap: FillGapWindow, desiredKinds?: NodeType[]) => void;
  acceptFillProposal: (proposal: FillProposalResponse) => void;
  dismissFillProposal: (inventoryId: string) => void;
  clearFill: () => void;

  // ── zoom (horizontal view) ──
  setPxPerMinute: (value: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
  setZoomPreset: (preset: ZoomPreset) => void;

  // ── zoom (journal view) ──
  setJournalPxPerMinute: (value: number) => void;
  journalZoomIn: () => void;
  journalZoomOut: () => void;
  resetJournalZoom: () => void;
  setJournalZoomPreset: (preset: JournalZoomPreset) => void;
};

export type ItineraryGraphInit = {
  timeline: ItineraryTimeline;
  itineraryId: string;
  status: DisplayStatus;
  /** The viewer's resolved role; `canEdit` is derived from it in the store. */
  role: UserRole;
  apiBaseUrl: string | null;
  accessToken: string | null;
  /** The viewer's own OPEN fork of this baseline (from `GraphResponse`), so the
   *  two-version toggle resolves to it instead of spawning a duplicate. */
  viewerOpenForkId?: string | null;
  /** Traveler viewing an advisor-crafted trunk with nothing published yet —
   *  drives the "being crafted" teaser over the empty timeline. */
  awaitingProposal?: boolean;
  /** Per-currency plan price from the `GraphResponse` (ADV-10). Empty by default. */
  totals?: Record<string, string>;
  /** 0048: preferred display currency + converted grand total (both nullable). */
  displayCurrency?: string | null;
  totalDisplay?: string | null;
  // Demo/sandbox escape hatch: start already locked-by-me so the prototype
  // (which has no API to acquire a real lock against) can exercise the editing
  // affordances. Production leaves this false — staff must click Edit to lock.
  startLocked?: boolean;
};

/**
 * The advisor's authoring surface is their WORKING COPY — a fork. The official
 * trunk only ever takes content via publish (reconcile), so staff build in a
 * private fork exactly like travelers do; the server's trunk guard is the
 * authority (409 `fork_required` for non-advisors, and the UI keeps advisors
 * honest by only offering authoring on a fork). The editor lock still exists
 * (legacy escape-hatch surfaces) but no longer grants trunk editability here.
 *
 * Credential-less sandbox exception: the design prototype has no API to fork
 * against, so it keeps the old lock-gated rule — nothing can persist anyway.
 */
export function selectEditable(s: ItineraryGraphState): boolean {
  if (!s.canEdit) return false;
  if (hasCredentials(s)) {
    return Boolean(s.sample.itinerary?.forked_from_id);
  }
  return s.lockStatus === "locked-by-me" && s.status === "in_studio";
}

function hasCredentials(s: ItineraryGraphState): boolean {
  return Boolean(s.apiBaseUrl && s.accessToken);
}

/**
 * Whether the viewer may approve — the all-at-once "Approve all" and the
 * per-node approve. The traveler approves cards the advisor has published to
 * them (`with_traveler`). Never on a fork (approval is on the official trunk),
 * an already-approved plan, or as an advisor — approval is a traveler action.
 */
export function selectCanApprove(s: ItineraryGraphState): boolean {
  if (!hasCredentials(s) || s.status === "approved") return false;
  if (s.sample.itinerary?.forked_from_id) return false;
  if (s.canEdit) return false; // advisors don't approve; that's the traveler's job
  return s.status === "with_traveler";
}

/**
 * Anyone viewing with credentials may leave a note — it's feedback for staff,
 * not a graph edit, so it bypasses the advisor lock/approve gate. The backend's
 * write gate (owner / advisor) is the real authority; a non-owner viewing an
 * approved itinerary will simply get a 403 and we revert the optimistic add.
 */
export function selectCanLeaveNote(s: ItineraryGraphState): boolean {
  return Boolean(s.apiBaseUrl && s.accessToken);
}

/**
 * Travelers may reshape (drag-move) their OWN alternative version — a fork
 * (`forked_from_id` set) that's still a draft. Persisted directly onto that
 * fork. Advisors keep their lock-based `selectEditable` path.
 */
export function selectTravelerEditable(s: ItineraryGraphState): boolean {
  return (
    !s.canEdit &&
    s.status !== "approved" &&
    Boolean(s.sample.itinerary?.forked_from_id) &&
    Boolean(s.apiBaseUrl && s.accessToken)
  );
}

/**
 * The viewer is on the OFFICIAL trunk but has toggled into the editable
 * working-copy preview, with no fork created yet. Edits here don't persist to
 * the trunk — the FIRST edit lazily forks (see `forkAndMove`) and carries
 * the change onto the new fork. Role-agnostic: advisors enter their private
 * workspace and travelers their "My version" through the same gesture.
 * Distinct from `selectTravelerEditable`/`selectEditable` (a real fork) so
 * the drop handler knows which path to take.
 */
export function selectIsDraftMine(s: ItineraryGraphState): boolean {
  return (
    s.status !== "approved" &&
    !s.sample.itinerary?.forked_from_id &&
    s.draftMine &&
    Boolean(s.apiBaseUrl && s.accessToken)
  );
}

/**
 * Whether the viewer can schedule via place mode (PS5) — a real editable
 * surface: an advisor holding the lock, or a traveler on their own fork. A
 * draft-mine traveler is excluded on purpose (their first change must lazily
 * fork, which the drag path handles); place mode stays a same-surface action.
 */
export function selectCanSchedule(s: ItineraryGraphState): boolean {
  return selectEditable(s) || selectTravelerEditable(s);
}

/**
 * A node is scheduled once it carries a REAL `metadata.start_time` — one an
 * advisor/agent actually placed. A *synthesized* start (the adapter auto-lays
 * out undated nodes so the timeline can draw them, stamping
 * `start_synthesized`) does NOT count: those nodes still belong to the
 * Collection until someone gives them a time.
 *
 * Exported so the Collection rail can split its pile into the unscheduled
 * "maybes" (shown by default) and the already-placed cards (hidden behind a
 * deliberate "show scheduled" toggle so the timeline's items don't clutter the
 * wish list).
 */
export function isNodeScheduled(node: NodeResponse): boolean {
  const meta = node.metadata as { start_time?: string; start_synthesized?: boolean };
  if (meta.start_synthesized === true) return false;
  return typeof meta.start_time === "string" && meta.start_time.length > 0;
}

/**
 * A node whose schedule is PINNED to an external booking/offer. A flight's
 * `depart_at` / `arrive_at` come from the Duffel offer, so its time is a FACT,
 * not a placement: the adapter derives its timeline slot from `depart_at`, and
 * "re-timing" it isn't a drag — it's a rebooking (a different offer). Such a
 * node is not drag-re-timable by anyone (traveler or advisor), so the move
 * entry points no-op on it and the Journal offers a nudge instead of a handle.
 */
export function isSchedulePinned(node: NodeResponse): boolean {
  if (node.type !== "flight") return false;
  const depart = (node.metadata as { depart_at?: unknown }).depart_at;
  return typeof depart === "string" && depart.length > 0;
}

/**
 * The Collection (wish list): every non-discarded node the viewer is
 * accumulating — persisted nodes AND fresh agent proposals, deduped by id.
 * This is the pile the rail renders. It's the whole mood board, so a node that
 * gets *placed* on the timeline (given a real start_time) STAYS here too — the
 * timeline is an additional surface for it, not a move out of the Collection.
 * Only discarding a node removes it.
 *
 * Pure over the two raw arrays so React components can `useMemo` it off the
 * stable `s.nodes` / `s.pendingProposals` references rather than passing a
 * new-array-every-render selector straight to `useStore` (which would defeat
 * the store's `Object.is` change check).
 */
export function collectionItemsOf(
  nodes: NodeResponse[],
  pending: NodeResponse[],
): NodeResponse[] {
  const seen = new Set<string>();
  const out: NodeResponse[] = [];
  for (const n of [...nodes, ...pending]) {
    if (seen.has(n.id)) continue;
    if (n.status === "discarded") continue;
    // Subgraph children live inside their parent card (the embedded
    // day-by-day journey) — never as free-standing wish-list items.
    if (n.parent_subgraph_id) continue;
    seen.add(n.id);
    out.push(n);
  }
  return out;
}

export function selectCollectionItems(s: ItineraryGraphState): NodeResponse[] {
  return collectionItemsOf(s.nodes, s.pendingProposals);
}

// A placed node now shows in BOTH the timeline and the Collection rail (see
// `collectionItemsOf`). Both make it draggable inside the same DndContext, so
// the rail namespaces its draggable id to avoid a duplicate-id collision with
// the timeline card. Handlers strip the prefix back to the real node id.
const COLLECTION_DRAG_PREFIX = "collection:";
export const collectionDragId = (nodeId: string): string =>
  `${COLLECTION_DRAG_PREFIX}${nodeId}`;
export const nodeIdFromDragId = (dragId: string): string =>
  dragId.startsWith(COLLECTION_DRAG_PREFIX)
    ? dragId.slice(COLLECTION_DRAG_PREFIX.length)
    : dragId;

/**
 * How many items are actually placed on the timeline. When this is zero the
 * Collection is the dominant surface (there's no meaningful timeline to show
 * yet), so the view hands it the main canvas.
 */
export function scheduledCountOf(
  nodes: NodeResponse[],
  pending: NodeResponse[],
): number {
  let n = 0;
  for (const node of nodes) if (node.status !== "discarded" && isNodeScheduled(node)) n += 1;
  for (const node of pending) if (isNodeScheduled(node)) n += 1;
  return n;
}

export function selectScheduledCount(s: ItineraryGraphState): number {
  return scheduledCountOf(s.nodes, s.pendingProposals);
}

// Move the start_time of a node onto a different day, keeping HH:MM and tz
// offset intact. This is what powers the drag-and-drop "move to day N" gesture.
function rebaseStartToDay(
  startIso: string,
  dayKey: string,
  tzOffsetHours: number,
): string {
  const ms = new Date(startIso).getTime() + tzOffsetHours * 3600 * 1000;
  const d = new Date(ms);
  return buildIsoOnDay(
    dayKey,
    d.getUTCHours(),
    d.getUTCMinutes(),
    d.getUTCSeconds(),
    tzOffsetHours,
  );
}

function buildIsoOnDay(
  dayKey: string,
  hh: number,
  mm: number,
  ss: number,
  tzOffsetHours: number,
): string {
  const offsetSign = tzOffsetHours >= 0 ? "+" : "-";
  const absOff = Math.abs(tzOffsetHours);
  const offH = String(Math.floor(absOff)).padStart(2, "0");
  const offM = String(Math.round((absOff % 1) * 60)).padStart(2, "0");
  const hhStr = String(hh).padStart(2, "0");
  const mmStr = String(mm).padStart(2, "0");
  const ssStr = String(ss).padStart(2, "0");
  return `${dayKey}T${hhStr}:${mmStr}:${ssStr}${offsetSign}${offH}:${offM}`;
}

// Build a new ISO start_time on `dayKey` at the given minute-of-day, snapped
// to a clean minute so drag drops don't introduce fractional-seconds noise.
function rebaseStartToDayAndMinute(
  dayKey: string,
  minuteOfDay: number,
  tzOffsetHours: number,
): string {
  const clamped = Math.max(0, Math.min(1439, Math.round(minuteOfDay)));
  return buildIsoOnDay(
    dayKey,
    Math.floor(clamped / 60),
    clamped % 60,
    0,
    tzOffsetHours,
  );
}

// A moved node's new metadata (rebased `start_time`) for a day/minute drop, or
// null when there's nothing to rebase. Shared by `moveNode` (persists onto the
// current graph) and `forkAndMove` (carries the move onto a fresh fork).
function rebasedMetadata(
  node: NodeResponse,
  dayKey: string,
  minuteOfDay: number | null,
  tzDefault: number,
): Record<string, unknown> | null {
  const meta = node.metadata as { start_time?: string; [k: string]: unknown };
  // Preserve the node's OWN offset (the trip spans tzs) so a Tokyo node stays
  // +09:00 after a drag; fall back to the trip default.
  const tz = offsetHoursOr(meta.start_time ?? "", tzDefault);
  const newStart =
    minuteOfDay !== null
      ? rebaseStartToDayAndMinute(dayKey, minuteOfDay, tz)
      : meta.start_time
        ? rebaseStartToDay(meta.start_time, dayKey, tz)
        : null;
  if (newStart === null) return null;
  // A real drop sheds the synthesized marker: the node now has a placement
  // someone chose, so it belongs on the timeline, not the Collection. The
  // target day is stamped as `day_key` so day bucketing follows the drop
  // without re-deriving it from the ISO (Phase 4, doc/itin-time.md).
  const next: Record<string, unknown> = { ...meta, start_time: newStart, day_key: dayKey };
  delete next["start_synthesized"];
  return next;
}

// The kernel day_index (human Day N; Day 1 = the trip's anchor) for a visual
// day column. `dayOneKey` comes from the adapter (the server's anchor_date
// when set); a fixture without one anchors at its first day column.
function kernelDayIndex(
  sample: { dayOneKey?: string; days: Array<{ date: string }> },
  dayKey: string,
): number {
  const anchor = sample.dayOneKey ?? sample.days[0]?.date ?? dayKey;
  const [ay, am, ad] = anchor.split("-").map(Number);
  const [by, bm, bd] = dayKey.split("-").map(Number);
  const a = Date.UTC(ay ?? 1970, (am ?? 1) - 1, ad ?? 1);
  const b = Date.UTC(by ?? 1970, (bm ?? 1) - 1, bd ?? 1);
  return Math.round((b - a) / 86_400_000) + 1;
}

// The wall-clock minute-of-day encoded in a local ISO ("…T16:10:00+09:00").
function minuteOfDayFromIso(iso: string): number {
  const hh = Number(iso.slice(11, 13));
  const mm = Number(iso.slice(14, 16));
  return (Number.isFinite(hh) ? hh : 9) * 60 + (Number.isFinite(mm) ? mm : 0);
}

// The Phase 4 placement payload for a (dayKey, minuteOfDay) drop: trip terms
// only — the kernel builds the schedule server-side (doc/itin-time.md). A
// null minute (move-to-day, keep the time) reads the wall clock off the
// optimistically-rebased start.
function placementFor(
  sample: { dayOneKey?: string; days: Array<{ date: string }> },
  dayKey: string,
  minuteOfDay: number | null,
  startIso: string | undefined,
): { day_index: number; minute_of_day: number } {
  const minute = minuteOfDay ?? (startIso ? minuteOfDayFromIso(startIso) : 9 * 60);
  return {
    day_index: kernelDayIndex(sample, dayKey),
    minute_of_day: Math.max(0, Math.min(1439, Math.round(minute))),
  };
}

export const itineraryGraphStore = createStoreContext<
  ItineraryGraphState,
  ItineraryGraphInit
>(
  ({
    timeline,
    itineraryId,
    status,
    role,
    apiBaseUrl,
    accessToken,
    viewerOpenForkId = null,
    awaitingProposal = false,
    totals = {},
    displayCurrency = null,
    totalDisplay = null,
    startLocked = false,
  }) =>
    (set, get) => {
      // `canEdit` is derived from the viewer's role — role is the threaded
      // fact, this is just the capability it implies.
      const canEdit = role === "advisor";

      // The SSR `accessToken` seeds the store, but a page held open past the
      // token's ~1h TTL would 401 on every browser write (the note POST, card
      // edits, approvals — all of them). So resolve the token per-request from
      // the browser Supabase client, which auto-refreshes in the background.
      // The client is built lazily on first mutation (never at construction —
      // that would touch browser-only APIs during SSR and in jsdom tests) and
      // memoized; any failure falls back to the SSR token.
      let browserSupabase: ReturnType<typeof createBrowserSupabase> | null = null;
      let browserSupabaseTried = false;
      const resolveAccessToken = async (): Promise<string | null> => {
        if (typeof window !== "undefined") {
          if (!browserSupabaseTried) {
            browserSupabaseTried = true;
            try {
              browserSupabase = createBrowserSupabase();
            } catch {
              browserSupabase = null;
            }
          }
          try {
            const session = (await browserSupabase?.auth.getSession())?.data.session;
            if (session?.access_token) return session.access_token;
          } catch {
            // Fall through to the SSR-seeded token below.
          }
        }
        return accessToken;
      };

      // Lazily build an authenticated client for a mutation. Returns null when
      // no credentials were provided (e.g. the API-less sandbox) so callers
      // degrade to a no-op. `accessToken` (the SSR seed) is the "credentialed
      // viewer" signal; `resolveAccessToken` supplies the live value per call.
      const client = () => {
        if (!apiBaseUrl || !accessToken) return null;
        return createApiClient({
          baseUrl: apiBaseUrl,
          accessToken: resolveAccessToken,
        });
      };

      // Pick a visually rich first focus so the map / image starts populated.
      const defaultFocus = timeline.nodes.find((n) => {
        const m = n.metadata as { ambient_image?: string; location?: unknown };
        return typeof m.ambient_image === "string" && Boolean(m.location);
      });

      return {
        itineraryId,
        role,
        canEdit,
        apiBaseUrl,
        accessToken,

        sample: timeline,
        nodes: [...timeline.nodes],
        edges: [...timeline.edges],
        pendingProposals: [],
        messages: [
          {
            id: `sys-${timeline.id}`,
            role: "system",
            text: `${timeline.label} — ${timeline.subtitle}.`,
          },
        ],
        focusedNodeId: defaultFocus?.id ?? null,
        focusLocked: false,
        // The default focus is a seed, not an interaction: `focusSource` stays
        // null so idle surfaces (the Journal rail) don't jump straight to it.
        focusSource: null,
        flashNodeId: null,
        assemblePulse: 0,
        partyRevision: 0,
        heldItem: null,
        lastPlacement: null,

        status,
        lockStatus: startLocked ? "locked-by-me" : "unlocked",
        lockPending: false,
        releasePending: false,
        approvePending: false,
        approvingNodeId: null,
        totals,
        displayCurrency,
        totalDisplay,
        billingChips: {},

        viewerOpenForkId,
        draftMine: false,
        forking: false,
        requestingMerge: false,
        mergeRequested: Boolean(timeline.itinerary?.reconcile_requested_at),
        cancelingMerge: false,
        discarding: false,
        publishing: false,
        publishBlocked: false,
        awaitingProposal,

        pxPerMinute: ZOOM_PRESETS.day,
        journalPxPerMinute: JOURNAL_ZOOM_PRESETS.hour,

        // ── place mode (PS5) ──
        holdItem: (nodeId) => {
          const s = get();
          const node =
            s.nodes.find((n) => n.id === nodeId) ??
            s.pendingProposals.find((n) => n.id === nodeId);
          if (!node) return;
          set({
            heldItem: { nodeId, title: node.title },
            // A new pickup supersedes any lingering undo toast.
            lastPlacement: null,
          });
        },
        clearHeldItem: () => set({ heldItem: null }),
        placeHeldItem: (dayKey, minuteOfDay) => {
          const s = get();
          const held = s.heldItem;
          if (!held) return;
          // Only a real editable surface places here; a draft-mine traveler keeps
          // the drag→lazy-fork path (parity with the PS4 card facet), so drop the
          // hold rather than mutate a read-through preview.
          if (!selectEditable(s) && !selectTravelerEditable(s)) {
            set({ heldItem: null });
            return;
          }
          s.moveNode(held.nodeId, dayKey, minuteOfDay);
          set({
            heldItem: null,
            lastPlacement: {
              nodeId: held.nodeId,
              title: held.title,
              dayKey,
              minute: minuteOfDay,
            },
          });
        },
        undoPlacement: () => {
          const s = get();
          const last = s.lastPlacement;
          if (!last) return;
          s.unscheduleNode(last.nodeId);
          set({ lastPlacement: null });
        },
        clearLastPlacement: () => set({ lastPlacement: null }),

        focusNode: (id, source) =>
          set((s) => ({
            focusedNodeId: id,
            focusSource: id === null ? null : (source ?? "click"),
            // Focusing a DIFFERENT node cancels any hard lock — a deliberate
            // move to another card always wins (re-focusing the same node
            // leaves the lock intact).
            focusLocked: id === s.focusedNodeId ? s.focusLocked : false,
          })),
        setFocusLocked: (locked) => set({ focusLocked: locked }),
        appendUserMessage: (id, text) =>
          set((s) => ({
            messages: [...s.messages, { id, role: "user", text }],
          })),
        appendAssistantMessage: (id, text) =>
          set((s) => ({
            messages: [
              ...s.messages,
              { id, role: "assistant", text: text ?? "", streaming: true },
            ],
          })),
        appendDelta: (id, text) =>
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === id ? { ...m, text: m.text + text } : m,
            ),
          })),
        finishAssistant: (id) =>
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === id ? { ...m, streaming: false } : m,
            ),
          })),
        proposeNode: (node) =>
          set((s) => {
            const asNode: NodeResponse = {
              id: node.id,
              itinerary_id: node.itinerary_id,
              parent_subgraph_id: null,
              type: node.type as NodeResponse["type"],
              status: "pending",
              title: node.title,
              source: node.source,
              source_id: node.source_id,
              metadata: node.metadata,
            };
            return { pendingProposals: [...s.pendingProposals, asNode] };
          }),
        // Accept a proposed card. The proposal already IS a real `pending`
        // node server-side (propose_card/propose_flight persisted it before
        // the `card_proposed` frame), so "accept" is purely a client move:
        // take the card out of the proposal tray and onto the plan, KEEPING
        // its `pending` status. It is NOT an approval — approving is the
        // traveler's separate, deliberate lock (`approveNode`); merely adding
        // a suggestion must not lock the card. No server write is needed (the
        // node is already pending in the DB), so a `router.refresh()` re-reads
        // it in the same state.
        acceptProposal: (id) => {
          const s = get();
          const proposal = s.pendingProposals.find((p) => p.id === id);
          if (!proposal) return;
          // Idempotent: a mid-turn reload may have already seeded this node
          // from the DB into `nodes`; never double-insert.
          const alreadyOnPlan = s.nodes.some((n) => n.id === id);
          set({
            pendingProposals: s.pendingProposals.filter((p) => p.id !== id),
            nodes: alreadyOnPlan ? s.nodes : [...s.nodes, proposal],
            flashNodeId: proposal.id,
          });
        },
        // Decline a proposed card: soft-remove it (`discarded`) server-side so
        // the pending node the agent persisted doesn't linger on the plan. Also
        // a direct graph op — the agent is not told.
        dismissProposal: (id) => {
          const s = get();
          const proposal = s.pendingProposals.find((p) => p.id === id);
          if (!proposal) return;
          const c = client();
          if (!c) return;
          set({
            pendingProposals: s.pendingProposals.filter((p) => p.id !== id),
          });
          void updateNodeStatus(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            status: "discarded",
          }).then((result) => {
            if (!result.ok)
              set((cur) => ({
                pendingProposals: [...cur.pendingProposals, proposal],
              }));
          });
        },
        insertCreatedNode: (node) =>
          set((s) => {
            // Idempotent: a mid-turn reveal can race a page reload that already
            // seeded this node from the DB. Never double-insert.
            if (s.nodes.some((n) => n.id === node.id)) return s;
            const asNode: NodeResponse = {
              id: node.id,
              itinerary_id: node.itinerary_id,
              // Preserve subgraph parentage so a materialized child (a campaign
              // cornerstone's day) derives as a journey beat immediately, rather
              // than rendering as a parentless top-level card until a reload.
              parent_subgraph_id: node.parent_subgraph_id ?? null,
              type: node.type as NodeResponse["type"],
              // The real status the agent persisted (pending/approved/…), NOT a
              // forced "pending" — this node is the trip, not a proposal.
              status: node.status as NodeResponse["status"],
              title: node.title,
              source: node.source,
              source_id: node.source_id,
              metadata: node.metadata,
            };
            return { nodes: [...s.nodes, asNode], flashNodeId: node.id };
          }),
        applyNodeUpdate: (node) =>
          set((s) => ({
            nodes: s.nodes.map((n) =>
              n.id === node.id
                ? {
                    ...n,
                    title: node.title,
                    metadata: { ...n.metadata, ...node.metadata },
                  }
                : n,
            ),
            flashNodeId: node.id,
          })),
        flashNode: (id) => set({ flashNodeId: id }),
        pulseAssemble: () =>
          set((s) => ({ assemblePulse: s.assemblePulse + 1 })),
        bumpPartyRevision: () =>
          set((s) => ({ partyRevision: s.partyRevision + 1 })),

        // ── staff editing ───────────────────────────────────────────────
        acquireLock: () => {
          const s = get();
          if (!s.canEdit || s.lockPending || s.lockStatus === "locked-by-me")
            return;
          if (s.status === "approved") return;
          const c = client();
          if (!c) return;
          const previousLock = s.lockStatus;
          set({ lockPending: true, lockStatus: "locked-by-me" });
          void acquireItineraryLock(c, s.itineraryId)
            .then((result) => {
              if (!result.ok) {
                set({
                  lockStatus:
                    result.detail === "already_locked"
                      ? "locked-by-other"
                      : previousLock,
                });
              }
            })
            .finally(() => set({ lockPending: false }));
        },
        releaseLock: () => {
          const s = get();
          if (s.releasePending || s.lockStatus !== "locked-by-me") return;
          const c = client();
          if (!c) return;
          set({ releasePending: true, lockStatus: "unlocked" });
          void releaseItineraryLock(c, s.itineraryId)
            .then((result) => {
              if (!result.ok) set({ lockStatus: "locked-by-me" });
            })
            .finally(() => set({ releasePending: false }));
        },
        // "Approve all": approve the whole plan in one action via the trunk's
        // approve-all endpoint. Optimistic — the itinerary flips to approved and
        // every remaining `pending` node cascades to `approved` (mirroring the
        // backend); on success the server's canonical graph is adopted; reverts
        // on failure.
        approve: () => {
          const s = get();
          if (!selectCanApprove(s) || s.approvePending) return;
          const c = client();
          if (!c) return;
          const previousStatus = s.status;
          const previousNodes = s.nodes;
          set({
            approvePending: true,
            status: "approved",
            nodes: s.nodes.map((n) =>
              n.status === "pending" ? { ...n, status: "approved" } : n,
            ),
          });
          void approveAllNodes(c, s.itineraryId)
            .then((result) => {
              if (result.ok) {
                set({
                  nodes: [...result.graph.nodes],
                  status: result.graph.itinerary.display_status ?? "approved",
                });
              } else {
                set({ status: previousStatus, nodes: previousNodes });
              }
            })
            .finally(() => set({ approvePending: false }));
        },
        // Node-by-node approve: the traveler approves a single pending card.
        // Optimistic; when this clears the LAST remaining pending node, the
        // itinerary derives to `approved` (the same rollup the backend does).
        approveNode: (id) => {
          const s = get();
          if (!selectCanApprove(s) || s.approvingNodeId) return;
          const target = s.nodes.find((n) => n.id === id);
          if (!target || target.status !== "pending") return;
          const c = client();
          if (!c) return;
          const previousStatus = s.status;
          const previousNodes = s.nodes;
          const nextNodes = s.nodes.map((n) =>
            n.id === id ? { ...n, status: "approved" as const } : n,
          );
          const anyPendingLeft = nextNodes.some((n) => n.status === "pending");
          set({
            approvingNodeId: id,
            nodes: nextNodes,
            status:
              !anyPendingLeft && s.status === "with_traveler"
                ? "approved"
                : s.status,
          });
          void updateNodeStatus(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            status: "approved",
          })
            .then((result) => {
              if (!result.ok) set({ status: previousStatus, nodes: previousNodes });
            })
            .finally(() => set({ approvingNodeId: null }));
        },
        // Soft-remove: flip the node to `discarded` (reversible; every derived
        // view — Collection, reading rack, journal — already filters it out).
        // Role-agnostic here: a pure status flip clears the trunk write gate
        // for travelers too, and the backend stays the authority (a firmed
        // node refuses and we revert).
        discardNode: (id) => {
          const s = get();
          const target = s.nodes.find((n) => n.id === id);
          if (!target || target.status === "discarded") return;
          const c = client();
          if (!c) return;
          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map((n) =>
              n.id === id ? { ...n, status: "discarded" as const } : n,
            ),
          });
          void updateNodeStatus(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            status: "discarded",
          }).then((result) => {
            if (!result.ok) set({ nodes: previousNodes });
          });
        },
        // ADV-15: the board's per-card money chips. Advisor-only (billing is
        // advisor workflow) and self-contained like InvoicePanel's fetch — it
        // reads the ledger + the FRESH graph (party size expands per_person
        // costs) rather than trusting the store's node snapshot, so a chip
        // never drifts from what the cockpit would show.
        refreshBilling: () => {
          const s = get();
          if (s.role !== "advisor") return;
          const c = client();
          if (!c) return;
          void Promise.all([
            listInvoices(c, s.itineraryId),
            getItinerary(c, s.itineraryId),
          ]).then(([inv, graph]) => {
            if (!inv.ok || !graph.ok) return;
            set({
              billingChips: billingChipsByNode({
                invoices: inv.invoices,
                nodes: graph.nodes,
                partySize: graph.party_size ?? 1,
              }),
            });
          });
        },
        setNodes: (nodes) => set({ nodes }),
        // Field edits work on any EDITABLE FORK surface: the advisor's working
        // copy (`selectEditable`) or the traveler's own version
        // (`selectTravelerEditable`) — the Journal's rail lets a traveler own
        // title/description on their fork (phase 3). The backend's fork/trunk
        // write gates stay the real authority.
        editNodeField: (id, field, value) => {
          const s = get();
          if (!selectEditable(s) && !selectTravelerEditable(s)) return;
          const target = s.nodes.find((n) => n.id === id);
          if (!target) return;
          const current = field === "title" ? target.title : target.source_id;
          if ((current ?? "") === value) return;
          const c = client();
          if (!c) return;
          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map((n) =>
              n.id === id ? { ...n, [field]: value } : n,
            ),
          });
          const patch =
            field === "title" ? { title: value } : { source_id: value };
          void updateNode(c, { itineraryId: s.itineraryId, nodeId: id, patch }).then(
            (result) => {
              if (!result.ok) set({ nodes: previousNodes });
            },
          );
        },
        updateCardDetails: (id, input) => {
          const s = get();
          // Editable-fork gate (advisor working copy OR traveler's version) —
          // same rule as editNodeField; see the note there.
          if (!selectEditable(s) && !selectTravelerEditable(s)) return;
          const target = s.nodes.find((n) => n.id === id);
          if (!target) return;
          const c = client();
          if (!c) return;

          const patch: Parameters<typeof updateNode>[1]["patch"] = {};

          // Metadata keys patch in place over the node's existing metadata —
          // the server replaces the whole object, so we must merge client-side.
          // An empty string clears the key (undefined leaves it alone).
          let mergedMetadata: { [key: string]: unknown } | undefined;
          if (
            input.description !== undefined ||
            input.confirmationNumber !== undefined
          ) {
            mergedMetadata = { ...(target.metadata ?? {}) };
            if (input.description !== undefined) {
              if (input.description.trim()) {
                mergedMetadata["description"] = input.description.trim();
              } else {
                delete mergedMetadata["description"];
              }
            }
            if (input.confirmationNumber !== undefined) {
              if (input.confirmationNumber.trim()) {
                mergedMetadata["confirmation_number"] =
                  input.confirmationNumber.trim();
              } else {
                delete mergedMetadata["confirmation_number"];
              }
            }
            patch.metadata = mergedMetadata;
          }

          // Cost: set the trio together, or clear it together (the DB CHECK
          // refuses a dangling amount/currency).
          if (input.cost !== undefined) {
            if (input.cost === null) {
              patch.cost_amount = null;
              patch.cost_currency = null;
              patch.cost_kind = null;
            } else {
              patch.cost_amount = input.cost.amount;
              patch.cost_currency = input.cost.currency.toUpperCase();
              patch.cost_kind = input.cost.kind;
            }
          }

          if (Object.keys(patch).length === 0) return;

          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map((n) =>
              n.id === id
                ? {
                    ...n,
                    ...(mergedMetadata !== undefined
                      ? { metadata: mergedMetadata }
                      : {}),
                    ...(input.cost !== undefined
                      ? {
                          cost_amount: input.cost?.amount ?? null,
                          cost_currency:
                            input.cost?.currency.toUpperCase() ?? null,
                          cost_kind: input.cost?.kind ?? null,
                        }
                      : {}),
                  }
                : n,
            ),
          });
          void updateNode(c, { itineraryId: s.itineraryId, nodeId: id, patch }).then(
            (result) => {
              if (result.ok) {
                // Adopt the server's canonical node (it normalizes the cost
                // decimal string), then refresh the billing chips — a price
                // change moves the card's unbilled remainder.
                set({
                  nodes: get().nodes.map((n) => (n.id === id ? result.node : n)),
                });
                if (input.cost !== undefined) get().refreshBilling();
              } else {
                set({ nodes: previousNodes });
              }
            },
          );
        },
        moveNode: (id, dayKey, minuteOfDay) => {
          const s = get();
          // A schedule-pinned node (a flight) can't be re-timed — its slot is
          // derived from the offer's depart_at. Silently ignore the move so no
          // junk placement is written (and the adapter would override it anyway).
          const moving = s.nodes.find((n) => n.id === id);
          if (moving && isSchedulePinned(moving)) return;
          const apply = (n: NodeResponse): NodeResponse => {
            if (n.id !== id) return n;
            const meta = rebasedMetadata(
              n,
              dayKey,
              minuteOfDay,
              s.sample.timezoneOffsetHours,
            );
            return meta ? { ...n, metadata: meta } : n;
          };
          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map(apply),
            pendingProposals: s.pendingProposals.map(apply),
            flashNodeId: id,
          });
          // Persist committed nodes only (proposals aren't persisted yet).
          // Advisors (lock) or a traveler on their own alternative may persist.
          if (!selectEditable(get()) && !selectTravelerEditable(get())) return;
          const c = client();
          if (!c) return;
          const moved = get().nodes.find((n) => n.id === id);
          if (!moved) return;
          // Phase 4 (doc/itin-time.md): the drop persists as trip terms —
          // (day_index, minute_of_day) — and the kernel builds the schedule
          // server-side. The rebased metadata above is the optimistic render;
          // the server's resolved node replaces it on success.
          void updateNode(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            patch: {
              schedule: placementFor(
                s.sample,
                dayKey,
                minuteOfDay,
                (moved.metadata as { start_time?: string }).start_time,
              ),
            },
          }).then((result) => {
            if (!result.ok) {
              set({ nodes: previousNodes });
              return;
            }
            // Reconcile with the server-resolved node (fresh schedule view,
            // mirrors, needs_revalidation); keep the stamped day_key so
            // bucketing stays put. Guarded — loose test doubles may resolve
            // ok without a node.
            const serverNode = result.node as NodeResponse | undefined;
            if (!serverNode) return;
            set((cur) => ({
              nodes: cur.nodes.map((n) =>
                n.id === id
                  ? {
                      ...serverNode,
                      metadata: { ...serverNode.metadata, day_key: dayKey },
                    }
                  : n,
              ),
            }));
          });
        },
        addNode: ({ type, title, metadata }) => {
          const s = get();
          if (!selectEditable(s)) return;
          const c = client();
          if (!c) return;
          const tempId = `tmp-${Date.now()}-${Math.round(
            Math.random() * 1e6,
          )}`;
          const optimistic: NodeResponse = {
            id: tempId,
            itinerary_id: s.itineraryId,
            parent_subgraph_id: null,
            type,
            status: "pending",
            title,
            source: null,
            source_id: null,
            metadata: metadata ?? {},
          };
          set({ nodes: [...s.nodes, optimistic], flashNodeId: tempId });
          void createNode(c, {
            itineraryId: s.itineraryId,
            body: {
              type,
              title,
              status: "pending",
              metadata: metadata ?? {},
            },
          }).then((result) => {
            if (result.ok) {
              set((cur) => ({
                nodes: cur.nodes.map((n) =>
                  n.id === tempId ? result.node : n,
                ),
                flashNodeId: result.node.id,
              }));
            } else {
              set((cur) => ({
                nodes: cur.nodes.filter((n) => n.id !== tempId),
              }));
            }
          });
        },
        authorNode: ({ type, title, url, note, cost, schedule }) => {
          const s = get();
          // Editable-fork gate: the advisor's working copy, or the traveler on
          // their own version (the Journal's "blank card" insert, phase 3).
          if (!selectEditable(s) && !selectTravelerEditable(s)) return;
          const c = client();
          if (!c) return;

          const link = (url ?? "").trim();
          // Paste-link path: the server fetches the OpenGraph preview into a
          // proposed card (title/image/description), degrading to the bare URL
          // when the fetch fails. from-link carries no cost — price is offered
          // on the typed path only.
          if (link) {
            if (s.savingLink) return;
            set({ savingLink: true });
            void createNodeFromLink(c, {
              itineraryId: s.itineraryId,
              url: link,
              kind: type,
              ...(note && note.trim() ? { note: note.trim() } : {}),
            })
              .then((result) => {
                if (result.ok) {
                  set((cur) => ({
                    nodes: [...cur.nodes, result.node],
                    flashNodeId: result.node.id,
                  }));
                }
              })
              .finally(() => set({ savingLink: false }));
            return;
          }

          // Typed path: a bespoke, optionally priced card, proposed on the board.
          const cleanTitle = (title ?? "").trim();
          if (!cleanTitle) return;
          const priced =
            cost && cost.amount.trim() !== ""
              ? {
                  cost_amount: cost.amount.trim(),
                  cost_currency: cost.currency,
                  cost_kind: cost.kind,
                }
              : null;
          // Schedule (Outlook-style create-at-slot): a day + minute places the
          // card on the timeline at that time; otherwise it stays an unscheduled
          // Collection item. Default a 1h duration, mirroring the seed helpers.
          const startIso = schedule
            ? rebaseStartToDayAndMinute(
                schedule.dayKey,
                schedule.minute,
                s.sample.timezoneOffsetHours,
              )
            : null;
          const scheduled = startIso
            ? { starts_at: startIso, duration_minutes: 60 }
            : null;
          const tempId = `tmp-${Date.now()}-${Math.round(
            Math.random() * 1e6,
          )}`;
          const optimistic: NodeResponse = {
            id: tempId,
            itinerary_id: s.itineraryId,
            parent_subgraph_id: null,
            type,
            status: "pending",
            title: cleanTitle,
            source: null,
            source_id: null,
            metadata: startIso
              ? { start_time: startIso, duration_minutes: 60 }
              : {},
            ...(priced ?? {}),
          };
          set({ nodes: [...s.nodes, optimistic], flashNodeId: tempId });
          void createNode(c, {
            itineraryId: s.itineraryId,
            body: {
              type,
              title: cleanTitle,
              status: "pending",
              ...(priced ?? {}),
              ...(scheduled ?? {}),
            },
          }).then((result) => {
            set((cur) => ({
              nodes: result.ok
                ? cur.nodes.map((n) => (n.id === tempId ? result.node : n))
                : cur.nodes.filter((n) => n.id !== tempId),
            }));
          });
        },
        removeNode: (id) => {
          const s = get();
          // Anyone writing with credentials may delete — advisors AND a traveler
          // on their own itinerary. The backend's writability check is the real
          // authority; a non-owner's optimistic remove reverts on the 403.
          if (!selectCanLeaveNote(s)) return;
          const target = s.nodes.find((n) => n.id === id);
          // A firmed (approved/booked/confirmed) node must be demoted before
          // removal — except a note, which is feedback and always removable.
          // Mirrors the backend G1 gate so the optimistic remove never flickers
          // on a delete that is guaranteed to be refused.
          if (target && target.type !== "note" && target.lock_reason) return;
          const c = client();
          if (!c) return;
          const previousNodes = s.nodes;
          set({ nodes: s.nodes.filter((n) => n.id !== id) });
          void deleteNode(c, { itineraryId: s.itineraryId, nodeId: id }).then(
            (result) => {
              if (!result.ok) set({ nodes: previousNodes });
            },
          );
        },

        addAttachedNote: (hostId, text) => {
          const s = get();
          const body = text.trim();
          if (!body || !selectCanLeaveNote(s)) return;
          const c = client();
          if (!c) return;
          const tempId = `tmp-note-${Date.now()}-${Math.round(Math.random() * 1e6)}`;
          const optimistic: NodeResponse = {
            id: tempId,
            itinerary_id: s.itineraryId,
            parent_subgraph_id: null,
            type: "note",
            status: "pending",
            title: body,
            source: null,
            source_id: null,
            metadata: {},
            attached_to_node_id: hostId,
          };
          set({ nodes: [...s.nodes, optimistic], flashNodeId: hostId });
          void createNode(c, {
            itineraryId: s.itineraryId,
            body: {
              type: "note",
              title: body,
              status: "pending",
              attached_to_node_id: hostId,
            },
          }).then((result) => {
            set((cur) => ({
              nodes: result.ok
                ? cur.nodes.map((n) => (n.id === tempId ? result.node : n))
                : cur.nodes.filter((n) => n.id !== tempId),
            }));
          });
        },

        selectVersion: (target, navigate) => {
          const s = get();
          const forkedFrom = s.sample.itinerary?.forked_from_id ?? null;
          if (target === "official") {
            // On a fork → back to the baseline; on a baseline → leave draft mode.
            if (forkedFrom) navigate(forkedFrom);
            else set({ draftMine: false });
            return;
          }
          // target === "mine"
          if (forkedFrom) return; // already on my version
          if (s.viewerOpenForkId) {
            navigate(s.viewerOpenForkId); // an alternative already exists
            return;
          }
          // No fork yet — enter the editable preview; the first edit forks it.
          set({ draftMine: true });
        },
        forkAndMove: (id, dayKey, minuteOfDay, navigate) => {
          const s = get();
          if (s.forking || !selectIsDraftMine(s)) return;
          const c = client();
          if (!c) return;
          // Optimistic local move so the card visibly shifts before we navigate.
          const target = s.nodes.find((n) => n.id === id);
          // Pinned (a flight): its time is the offer's, not a placement — never
          // fork just to re-time it (see isSchedulePinned / moveNode).
          if (target && isSchedulePinned(target)) return;
          const newMeta = target
            ? rebasedMetadata(target, dayKey, minuteOfDay, s.sample.timezoneOffsetHours)
            : null;
          const previousNodes = s.nodes;
          if (newMeta) {
            set((cur) => ({
              nodes: cur.nodes.map((n) =>
                n.id === id ? { ...n, metadata: newMeta } : n,
              ),
              flashNodeId: id,
            }));
          }
          set({ forking: true });
          void forkItinerary(c, s.itineraryId)
            .then((result) => {
              if (!result.ok) {
                set({ nodes: previousNodes }); // revert the optimistic move
                return;
              }
              const forkId = result.graph.itinerary.id;
              // Carry the move onto the matching fork node (paired by lineage).
              const forkNode = result.graph.nodes.find(
                (n) => n.forked_from_node_id === id,
              );
              if (forkNode && newMeta) {
                // Trip terms survive the fork unchanged: the fork inherits the
                // trunk's anchor, so the same (day_index, minute_of_day) means
                // the same slot there.
                void updateNode(c, {
                  itineraryId: forkId,
                  nodeId: forkNode.id,
                  patch: {
                    schedule: placementFor(
                      s.sample,
                      dayKey,
                      minuteOfDay,
                      (newMeta as { start_time?: string }).start_time,
                    ),
                  },
                }).finally(() => navigate(forkId));
              } else {
                navigate(forkId);
              }
            })
            .finally(() => set({ forking: false }));
        },
        requestMerge: () => {
          const s = get();
          if (s.requestingMerge || s.mergeRequested) return;
          const c = client();
          if (!c) return;
          set({ requestingMerge: true });
          void requestReconcile(c, s.itineraryId)
            .then((result) => {
              if (result.ok) set({ mergeRequested: true });
            })
            .finally(() => set({ requestingMerge: false }));
        },
        cancelMerge: () => {
          const s = get();
          if (s.cancelingMerge || !s.mergeRequested) return;
          const c = client();
          if (!c) return;
          set({ cancelingMerge: true });
          void cancelReconcile(c, s.itineraryId)
            .then((result) => {
              if (result.ok) set({ mergeRequested: false });
            })
            .finally(() => set({ cancelingMerge: false }));
        },
        discardMine: (navigate) => {
          const s = get();
          const forkedFrom = s.sample.itinerary?.forked_from_id ?? null;
          if (s.discarding || !forkedFrom) return;
          const c = client();
          if (!c) return;
          set({ discarding: true });
          void abandonFork(c, s.itineraryId)
            .then((result) => {
              if (result.ok) navigate(forkedFrom);
            })
            .finally(() => set({ discarding: false }));
        },
        publishMine: (navigate) => {
          const s = get();
          const forkedFrom = s.sample.itinerary?.forked_from_id ?? null;
          if (s.publishing || !s.canEdit || !forkedFrom) return;
          const c = client();
          if (!c) return;
          set({ publishing: true, publishBlocked: false });
          void reconcileFork(c, s.itineraryId, { accept_all: true })
            .then((result) => {
              if (result.ok) {
                navigate(forkedFrom);
                return;
              }
              if (result.detail === "fork_infeasible") {
                set({ publishBlocked: true });
              }
            })
            .finally(() => set({ publishing: false }));
        },

        // ── diff mode (phase 4) ─────────────────────────────────────────────
        diffMode: false,
        diff: null,
        diffLoading: false,
        diffError: false,
        diffDecisions: {},
        diffOutcomes: {},
        diffApplying: false,
        diffBlocked: false,
        setDiffMode: (on) => {
          const s = get();
          if (!on) {
            set({ diffMode: false });
            return;
          }
          // Compare is inherently pairwise: this fork against its baseline —
          // there is nothing to diff on the trunk or without credentials.
          if (!s.sample.itinerary?.forked_from_id || !client()) return;
          // Compare and cinema are mutually exclusive reading modes.
          set({ diffMode: true, diffBlocked: false, cinemaMode: false });
          s.refreshDiff();
        },
        refreshDiff: () => {
          const s = get();
          if (!s.sample.itinerary?.forked_from_id) return;
          const c = client();
          if (!c) return;
          set({ diffLoading: true, diffError: false });
          void getForkDiff(c, s.itineraryId)
            .then((result) => {
              if (!result.ok) {
                set({ diffError: true });
                return;
              }
              // Seed accept-by-default decisions, preserving choices already
              // made (the DiffPanel convention).
              const prev = get().diffDecisions;
              const decisions: Record<string, boolean> = {};
              const d = result.diff;
              for (const change of [
                ...d.added,
                ...d.removed,
                ...d.changed,
                ...d.moved,
              ]) {
                decisions[change.change_id] = prev[change.change_id] ?? true;
              }
              set({ diff: d, diffDecisions: decisions });
            })
            .finally(() => set({ diffLoading: false }));
        },
        setDiffDecision: (changeId, accept) =>
          set((s) => ({
            diffDecisions: { ...s.diffDecisions, [changeId]: accept },
          })),
        applyDiffDecisions: (navigate) => {
          const s = get();
          const forkedFrom = s.sample.itinerary?.forked_from_id ?? null;
          if (!s.canEdit || s.diffApplying || !s.diff || !forkedFrom) return;
          const c = client();
          if (!c) return;
          const changes = [
            ...s.diff.added,
            ...s.diff.removed,
            ...s.diff.changed,
            ...s.diff.moved,
          ];
          const decisions = changes.map((change) => ({
            change_id: change.change_id,
            accept: s.diffDecisions[change.change_id] ?? true,
          }));
          // Everything accepted → the server-side accept_all fast path (the
          // diff is recomputed in the same transaction, no staleness window).
          const allAccept = decisions.every((d) => d.accept);
          set({ diffApplying: true, diffBlocked: false, diffOutcomes: {} });
          void reconcileFork(
            c,
            s.itineraryId,
            allAccept ? { accept_all: true } : { decisions },
          )
            .then((result) => {
              if (!result.ok) {
                if (result.detail === "fork_infeasible") {
                  set({ diffBlocked: true });
                } else {
                  set({ diffError: true });
                }
                return;
              }
              const outcomes: Record<string, string> = {};
              for (const o of result.result.outcomes) {
                outcomes[o.change_id] = o.result;
              }
              set({ diffOutcomes: outcomes });
              const unresolved = result.result.outcomes.some(
                (o) => o.result === "refused_booked" || o.result === "failed",
              );
              if (!unresolved) {
                // Fully folded in — the review is done; read the trunk.
                navigate(forkedFrom);
                return;
              }
              // Honest partial: booked cards stayed (G1). Re-diff so the
              // remaining divergence (with its locks) is what's on screen.
              get().refreshDiff();
            })
            .finally(() => set({ diffApplying: false }));
        },

        // ── cinema mode (phase 5) ───────────────────────────────────────────
        cinemaMode: false,
        setCinemaMode: (on) => {
          if (!on) {
            set({ cinemaMode: false });
            return;
          }
          // Cinema and compare are both mode flags over the SAME Journal DOM —
          // never both: entering one exits the other (setDiffMode mirrors this).
          set({ cinemaMode: true, diffMode: false });
        },

        editNoteText: (id, text) => {
          const s = get();
          const body = text.trim();
          if (!body || !selectCanLeaveNote(s)) return;
          const target = s.nodes.find((n) => n.id === id);
          // Only note text is rewritable through this path — a content field
          // edit on a real card keeps its own gates (`editNodeField`).
          if (!target || target.type !== "note") return;
          if (target.title === body) return;
          const c = client();
          if (!c) return;
          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map((n) => (n.id === id ? { ...n, title: body } : n)),
          });
          void updateNode(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            patch: { title: body },
          }).then((result) => {
            if (result.ok) {
              set({
                nodes: get().nodes.map((n) => (n.id === id ? result.node : n)),
              });
            } else {
              set({ nodes: previousNodes });
            }
          });
        },

        addFreeStandingNote: (dayKey, text) => {
          const s = get();
          const body = text.trim();
          if (!body || !selectCanLeaveNote(s)) return;
          const c = client();
          if (!c) return;
          // Drop it at noon on the chosen day, in the trip's own offset.
          const startIso = rebaseStartToDayAndMinute(
            dayKey,
            12 * 60,
            s.sample.timezoneOffsetHours,
          );
          const tempId = `tmp-note-${Date.now()}-${Math.round(Math.random() * 1e6)}`;
          const optimistic: NodeResponse = {
            id: tempId,
            itinerary_id: s.itineraryId,
            parent_subgraph_id: null,
            type: "note",
            status: "pending",
            title: body,
            source: null,
            source_id: null,
            metadata: { start_time: startIso },
          };
          set({ nodes: [...s.nodes, optimistic], flashNodeId: tempId });
          void createNode(c, {
            itineraryId: s.itineraryId,
            body: {
              type: "note",
              title: body,
              status: "pending",
              starts_at: startIso,
            },
          }).then((result) => {
            set((cur) => ({
              nodes: result.ok
                ? cur.nodes.map((n) => (n.id === tempId ? result.node : n))
                : cur.nodes.filter((n) => n.id !== tempId),
            }));
          });
        },

        // ── Collection (wish list) writes ───────────────────────────────────
        savingLink: false,
        saveLinkToCollection: (url, kind, note) => {
          const s = get();
          const trimmed = url.trim();
          if (!trimmed || s.savingLink || !selectCanLeaveNote(s)) return;
          const c = client();
          if (!c) return;
          set({ savingLink: true });
          void createNodeFromLink(c, {
            itineraryId: s.itineraryId,
            url: trimmed,
            ...(kind ? { kind } : {}),
            ...(note ? { note } : {}),
          })
            .then((result) => {
              if (result.ok) {
                set((cur) => ({
                  nodes: [...cur.nodes, result.node],
                  flashNodeId: result.node.id,
                }));
              }
            })
            .finally(() => set({ savingLink: false }));
        },
        addCollectionNote: (text) => {
          const s = get();
          const body = text.trim();
          if (!body || !selectCanLeaveNote(s)) return;
          const c = client();
          if (!c) return;
          const tempId = `tmp-note-${Date.now()}-${Math.round(Math.random() * 1e6)}`;
          const optimistic: NodeResponse = {
            id: tempId,
            itinerary_id: s.itineraryId,
            parent_subgraph_id: null,
            type: "note",
            status: "pending",
            title: body,
            source: null,
            source_id: null,
            metadata: {},
          };
          set({ nodes: [...s.nodes, optimistic], flashNodeId: tempId });
          void createNode(c, {
            itineraryId: s.itineraryId,
            body: { type: "note", title: body, status: "pending" },
          }).then((result) => {
            set((cur) => ({
              nodes: result.ok
                ? cur.nodes.map((n) => (n.id === tempId ? result.node : n))
                : cur.nodes.filter((n) => n.id !== tempId),
            }));
          });
        },
        unscheduleNode: (id) => {
          const s = get();
          const target =
            s.nodes.find((n) => n.id === id) ??
            s.pendingProposals.find((n) => n.id === id);
          if (!target) return;
          // Strip start_time (+ mirrored offset) so the node returns to the
          // Collection. Persist only for actors who may write; the backend
          // clears all three schedule representations via the Phase 4
          // `schedule.clear` placement (doc/itin-time.md).
          const meta = { ...(target.metadata as Record<string, unknown>) };
          delete meta["start_time"];
          delete meta["tz_offset_minutes"];
          delete meta["start_synthesized"];
          delete meta["day_key"];
          const apply = (n: NodeResponse): NodeResponse =>
            n.id === id ? { ...n, metadata: meta } : n;
          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map(apply),
            pendingProposals: s.pendingProposals.map(apply),
            flashNodeId: id,
          });
          if (!selectEditable(get()) && !selectTravelerEditable(get())) return;
          const c = client();
          if (!c) return;
          void updateNode(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            patch: { schedule: { clear: true } },
          }).then((result) => {
            if (!result.ok) set({ nodes: previousNodes });
          });
        },

        // ── authoring (B7): inventory search · analyze · fill ───────────────
        inventoryResults: [],
        inventoryPending: false,
        inventoryError: false,
        addingInventoryId: null,
        analysisId: null,
        analyzeStatus: "idle",
        analyzePending: false,
        findings: [],
        analyzeSummary: null,
        fillProposals: [],
        fillPending: false,
        fillGapWindow: null,

        runInventorySearch: (query) => {
          const s = get();
          if (!s.canEdit) return;
          const c = client();
          if (!c) return;
          set({ inventoryPending: true, inventoryError: false });
          void searchInventory(c, query)
            .then((result) => {
              if (result.ok) {
                set({ inventoryResults: result.items });
              } else {
                set({ inventoryResults: [], inventoryError: true });
              }
            })
            .finally(() => set({ inventoryPending: false }));
        },
        clearInventoryResults: () =>
          set({ inventoryResults: [], inventoryError: false }),
        addNodeFromInventory: (source, sourceId) => {
          const s = get();
          if (!selectEditable(s)) return;
          const c = client();
          if (!c) return;
          set({ addingInventoryId: sourceId });
          void createNodeFromInventory(c, {
            itineraryId: s.itineraryId,
            source,
            sourceId,
          })
            .then((result) => {
              if (result.ok) {
                // A round-trip flight lands as the outbound node plus one
                // `additional_nodes` leg per return — surface every leg.
                const added = [result.node, ...(result.node.additional_nodes ?? [])];
                set((cur) => ({
                  nodes: [...cur.nodes, ...added],
                  flashNodeId: result.node.id,
                }));
              }
            })
            .finally(() => set({ addingInventoryId: null }));
        },
        startAnalyze: () => {
          const s = get();
          if (!s.canEdit || s.analyzePending) return;
          const c = client();
          if (!c) return;
          set({
            analyzePending: true,
            analyzeStatus: "queued",
            findings: [],
            analyzeSummary: null,
          });
          void startAnalysis(c, { itineraryId: s.itineraryId })
            .then((result) => {
              if (result.ok) {
                set({
                  analysisId: result.created.analysis_id,
                  analyzeStatus: result.created.status,
                });
              } else {
                set({ analyzeStatus: "failed" });
              }
            })
            .finally(() => set({ analyzePending: false }));
        },
        refreshAnalysis: () => {
          const s = get();
          if (!s.analysisId) return;
          const c = client();
          if (!c) return;
          void getAnalysis(c, {
            itineraryId: s.itineraryId,
            analysisId: s.analysisId,
          }).then((result) => {
            if (result.ok) {
              set({
                analyzeStatus: result.analysis.status,
                findings: result.analysis.findings,
                analyzeSummary: result.analysis.summary,
              });
            }
          });
        },
        runFill: (gap, desiredKinds) => {
          const s = get();
          if (!s.canEdit || s.fillPending) return;
          const c = client();
          if (!c) return;
          set({ fillPending: true, fillGapWindow: gap, fillProposals: [] });
          void fillGap(c, {
            itineraryId: s.itineraryId,
            body: {
              gap,
              ...(desiredKinds && desiredKinds.length > 0
                ? { desired_kinds: desiredKinds }
                : {}),
              ...(s.analysisId ? { analysis_id: s.analysisId } : {}),
            },
          })
            .then((result) => {
              set({ fillProposals: result.ok ? result.result.proposals : [] });
            })
            .finally(() => set({ fillPending: false }));
        },
        acceptFillProposal: (proposal) => {
          const s = get();
          if (!selectEditable(s)) return;
          const c = client();
          if (!c) return;
          set({ addingInventoryId: proposal.inventory_id });
          void createNodeFromInventory(c, {
            itineraryId: s.itineraryId,
            source: proposal.inventory_source,
            sourceId: proposal.inventory_id,
          })
            .then((result) => {
              if (result.ok) {
                // A round-trip flight lands as the outbound node plus one
                // `additional_nodes` leg per return — surface every leg.
                const added = [result.node, ...(result.node.additional_nodes ?? [])];
                set((cur) => ({
                  nodes: [...cur.nodes, ...added],
                  flashNodeId: result.node.id,
                  fillProposals: cur.fillProposals.filter(
                    (p) => p.inventory_id !== proposal.inventory_id,
                  ),
                }));
              }
            })
            .finally(() => set({ addingInventoryId: null }));
        },
        dismissFillProposal: (inventoryId) =>
          set((s) => ({
            fillProposals: s.fillProposals.filter(
              (p) => p.inventory_id !== inventoryId,
            ),
          })),
        clearFill: () => set({ fillProposals: [], fillGapWindow: null }),

        setPxPerMinute: (v) => set({ pxPerMinute: clampZoom(v) }),
        zoomIn: () =>
          set((s) => ({ pxPerMinute: clampZoom(s.pxPerMinute * 1.35) })),
        zoomOut: () =>
          set((s) => ({ pxPerMinute: clampZoom(s.pxPerMinute / 1.35) })),
        resetZoom: () => set({ pxPerMinute: ZOOM_PRESETS.day }),
        setZoomPreset: (preset) => set({ pxPerMinute: ZOOM_PRESETS[preset] }),

        setJournalPxPerMinute: (v) =>
          set({ journalPxPerMinute: clampJournalZoom(v) }),
        journalZoomIn: () =>
          set((s) => ({
            journalPxPerMinute: clampJournalZoom(s.journalPxPerMinute * 1.35),
          })),
        journalZoomOut: () =>
          set((s) => ({
            journalPxPerMinute: clampJournalZoom(s.journalPxPerMinute / 1.35),
          })),
        resetJournalZoom: () =>
          set({ journalPxPerMinute: JOURNAL_ZOOM_PRESETS.hour }),
        setJournalZoomPreset: (preset) =>
          set({ journalPxPerMinute: JOURNAL_ZOOM_PRESETS[preset] }),
      };
    },
  "ItineraryGraph",
);
