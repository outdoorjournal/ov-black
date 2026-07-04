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
  approveItinerary,
  cancelReconcile,
  createApiClient,
  createNode,
  createNodeFromInventory,
  createNodeFromLink,
  deleteNode,
  fillGap,
  forkItinerary,
  getAnalysis,
  releaseItineraryLock,
  requestReconcile,
  searchInventory,
  startAnalysis,
  updateNode,
  type AnalysisStatus,
  type FillProposalResponse,
  type FindingResponse,
  type ItineraryStatus,
  type SearchInventoryQuery,
  type SearchInventoryResponse,
} from "@ov-black/api-client";

import { createStoreContext } from "@/lib/store/createStoreContext";
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
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
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

/**
 * The card the persistent concierge is currently scoped to (M006/PS4). Set by a
 * card's "Ask Artemis about this" — the ConciergeColumn renders it as a "Re: …"
 * chip, and the next agent turn is prefixed with it, then it clears. A shared UI
 * slice (not a URL) because the concierge lives beside every routed destination.
 */
export type AskContext = { nodeId: string; title: string };

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
  flashNodeId: string | null;
  assemblePulse: number;

  // ── staff editing lifecycle ──
  status: ItineraryStatus;
  lockStatus: LockStatus;
  lockPending: boolean;
  releasePending: boolean;
  approvePending: boolean;

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

  // ── horizontal-view UI state ──
  pxPerMinute: number;

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
  /** The card the concierge is scoped to (PS4 "ask about this"); null = general. */
  askContext: AskContext | null;
  setAskContext: (ctx: AskContext | null) => void;
  focusNode: (id: string | null) => void;
  appendUserMessage: (id: string, text: string) => void;
  appendAssistantMessage: (id: string, text?: string) => void;
  appendDelta: (id: string, text: string) => void;
  finishAssistant: (id: string) => void;

  // ── proposals (agent stream) ──
  proposeNode: (node: AgentNode) => void;
  acceptProposal: (id: string) => void;
  dismissProposal: (id: string) => void;
  applyNodeUpdate: (node: AgentNode) => void;
  flashNode: (id: string | null) => void;
  pulseAssemble: () => void;

  // ── staff editing actions (no-op unless editable) ──
  acquireLock: () => void;
  releaseLock: () => void;
  approve: () => void;
  setNodes: (nodes: NodeResponse[]) => void;
  editNodeField: (
    id: string,
    field: "title" | "source_id",
    value: string,
  ) => void;
  // Re-target a node onto a different day (and optionally minute-of-day),
  // updating its start_time and persisting the new metadata when editable.
  moveNode: (id: string, dayKey: string, minuteOfDay: number | null) => void;
  addNode: (input: {
    type: NodeType;
    title: string;
    metadata?: Record<string, unknown>;
  }) => void;
  removeNode: (id: string) => void;
  // ── traveler notes (feedback for staff; gated by `selectCanLeaveNote`) ──
  // Attach a note to a host node ("why are we doing this at 1:30?").
  addAttachedNote: (hostId: string, text: string) => void;
  // Drop a free-standing note on a day at noon ("a dinner between these").
  addFreeStandingNote: (dayKey: string, text: string) => void;
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
};

export type ItineraryGraphInit = {
  timeline: ItineraryTimeline;
  itineraryId: string;
  status: ItineraryStatus;
  /** The viewer's resolved role; `canEdit` is derived from it in the store. */
  role: UserRole;
  apiBaseUrl: string | null;
  accessToken: string | null;
  /** The viewer's own OPEN fork of this baseline (from `GraphResponse`), so the
   *  two-version toggle resolves to it instead of spawning a duplicate. */
  viewerOpenForkId?: string | null;
  // Demo/sandbox escape hatch: start already locked-by-me so the prototype
  // (which has no API to acquire a real lock against) can exercise the editing
  // affordances. Production leaves this false — staff must click Edit to lock.
  startLocked?: boolean;
};

/**
 * A node is editable only when the viewer is staff (`canEdit`), holds the
 * lock, and the itinerary is still a draft. Centralised so views and actions
 * agree on the gate.
 */
export function selectEditable(s: ItineraryGraphState): boolean {
  return (
    s.canEdit && s.lockStatus === "locked-by-me" && s.status !== "approved"
  );
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
 * The traveler is on the OFFICIAL baseline but has toggled into the editable
 * "My version" preview, with no fork created yet. Edits here don't persist to
 * the baseline — the FIRST edit lazily forks (see `forkAndMove`) and carries
 * the change onto the new fork. Distinct from `selectTravelerEditable` (a real
 * fork) so the drop handler knows which path to take.
 */
export function selectIsDraftMine(s: ItineraryGraphState): boolean {
  return (
    !s.canEdit &&
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
 */
function isScheduled(node: NodeResponse): boolean {
  const meta = node.metadata as { start_time?: string; start_synthesized?: boolean };
  if (meta.start_synthesized === true) return false;
  return typeof meta.start_time === "string" && meta.start_time.length > 0;
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
  for (const node of nodes) if (node.status !== "discarded" && isScheduled(node)) n += 1;
  for (const node of pending) if (isScheduled(node)) n += 1;
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
  // someone chose, so it belongs on the timeline, not the Collection.
  const next: Record<string, unknown> = { ...meta, start_time: newStart };
  delete next["start_synthesized"];
  return next;
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
    startLocked = false,
  }) =>
    (set, get) => {
      // `canEdit` is derived from the viewer's role — role is the threaded
      // fact, this is just the capability it implies.
      const canEdit = role === "advisor";

      // Lazily build an authenticated client for a mutation. Returns null when
      // no credentials were provided (e.g. the API-less sandbox) so callers
      // degrade to a no-op.
      const client = () => {
        if (!apiBaseUrl || !accessToken) return null;
        return createApiClient({ baseUrl: apiBaseUrl, accessToken });
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
        flashNodeId: null,
        assemblePulse: 0,
        askContext: null,
        heldItem: null,
        lastPlacement: null,

        status,
        lockStatus: startLocked ? "locked-by-me" : "unlocked",
        lockPending: false,
        releasePending: false,
        approvePending: false,

        viewerOpenForkId,
        draftMine: false,
        forking: false,
        requestingMerge: false,
        mergeRequested: Boolean(timeline.itinerary?.reconcile_requested_at),
        cancelingMerge: false,
        discarding: false,

        pxPerMinute: ZOOM_PRESETS.day,

        setAskContext: (ctx) => set({ askContext: ctx }),

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

        focusNode: (id) => set({ focusedNodeId: id }),
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
              status: "proposed",
              title: node.title,
              source: node.source,
              source_id: node.source_id,
              metadata: node.metadata,
            };
            return { pendingProposals: [...s.pendingProposals, asNode] };
          }),
        acceptProposal: (id) =>
          set((s) => {
            const proposal = s.pendingProposals.find((p) => p.id === id);
            if (!proposal) return s;
            const approved: NodeResponse = { ...proposal, status: "approved" };
            return {
              pendingProposals: s.pendingProposals.filter((p) => p.id !== id),
              nodes: [...s.nodes, approved],
              flashNodeId: approved.id,
            };
          }),
        dismissProposal: (id) =>
          set((s) => ({
            pendingProposals: s.pendingProposals.filter((p) => p.id !== id),
          })),
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
        approve: () => {
          const s = get();
          if (!s.canEdit || s.approvePending || s.status === "approved") return;
          const c = client();
          if (!c) return;
          const previousStatus = s.status;
          set({ approvePending: true, status: "approved" });
          void approveItinerary(c, s.itineraryId)
            .then((result) => {
              if (!result.ok) set({ status: previousStatus });
            })
            .finally(() => set({ approvePending: false }));
        },
        setNodes: (nodes) => set({ nodes }),
        editNodeField: (id, field, value) => {
          const s = get();
          if (!selectEditable(s)) return;
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
        moveNode: (id, dayKey, minuteOfDay) => {
          const s = get();
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
          void updateNode(c, {
            itineraryId: s.itineraryId,
            nodeId: id,
            patch: { metadata: moved.metadata },
          }).then((result) => {
            if (!result.ok) set({ nodes: previousNodes });
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
            status: "idea",
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
              status: "idea",
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
        removeNode: (id) => {
          const s = get();
          if (!selectEditable(s)) return;
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
            status: "proposed",
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
              status: "proposed",
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
                void updateNode(c, {
                  itineraryId: forkId,
                  nodeId: forkNode.id,
                  patch: { metadata: newMeta },
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
            status: "proposed",
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
              status: "proposed",
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
            status: "proposed",
            title: body,
            source: null,
            source_id: null,
            metadata: {},
          };
          set({ nodes: [...s.nodes, optimistic], flashNodeId: tempId });
          void createNode(c, {
            itineraryId: s.itineraryId,
            body: { type: "note", title: body, status: "proposed" },
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
          // Collection. Persist only for actors who may write; the backend then
          // clears the starts_at column to match (0035 update_node fix).
          const meta = { ...(target.metadata as Record<string, unknown>) };
          delete meta["start_time"];
          delete meta["tz_offset_minutes"];
          delete meta["start_synthesized"];
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
            patch: { metadata: meta },
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
                set((cur) => ({
                  nodes: [...cur.nodes, result.node],
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
                set((cur) => ({
                  nodes: [...cur.nodes, result.node],
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
      };
    },
  "ItineraryGraph",
);
