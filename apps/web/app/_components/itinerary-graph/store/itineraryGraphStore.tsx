"use client";

// View-agnostic domain store for an itinerary graph.
//
// This is the single source of truth that every *view* of the graph (the
// horizontal timeline, a future calendar view, etc.) reads and mutates. It
// owns the domain — nodes, edges, proposals, focus, and the staff editing
// lifecycle (lock / release / approve, field edits, drag-reorder persistence,
// add / remove) — and is deliberately ignorant of how any view draws it.
//
// `canEdit` is resolved on the server (advisor vs. traveler) and threaded in
// at construction; for travelers it is false and `accessToken`/`apiBaseUrl`
// are null, so the editing actions are inert and no client-side credential is
// ever handed to a traveler. The backend's advisor guards remain the real
// authority — `canEdit` only governs whether we render and attempt the
// mutations at all.
//
// NOTE: the zoom fields (`pxPerMinute` + zoom actions) are horizontal-view UI
// state that currently lives here for convenience. When a second view lands,
// extract per-view UI state into a view-local store and keep this store purely
// domain.

import {
  acquireItineraryLock,
  approveItinerary,
  createApiClient,
  createNode,
  createNodeFromInventory,
  deleteNode,
  fillGap,
  getAnalysis,
  releaseItineraryLock,
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

export type ItineraryGraphState = {
  // ── identity / config ──
  itineraryId: string;
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

  // ── horizontal-view UI state ──
  pxPerMinute: number;

  // ── focus / chat ──
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
  canEdit: boolean;
  apiBaseUrl: string | null;
  accessToken: string | null;
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

export const itineraryGraphStore = createStoreContext<
  ItineraryGraphState,
  ItineraryGraphInit
>(
  ({
    timeline,
    itineraryId,
    status,
    canEdit,
    apiBaseUrl,
    accessToken,
    startLocked = false,
  }) =>
    (set, get) => {
      // Lazily build an authenticated client for a mutation. Returns null for
      // travelers (no credentials) so callers degrade to a no-op.
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

        status,
        lockStatus: startLocked ? "locked-by-me" : "unlocked",
        lockPending: false,
        releasePending: false,
        approvePending: false,

        pxPerMinute: ZOOM_PRESETS.day,

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
            const meta = n.metadata as {
              start_time?: string;
              [k: string]: unknown;
            };
            // Preserve the node's OWN offset (the trip spans tzs) so a Tokyo
            // node stays +09:00 after a drag; fall back to the trip default.
            const tz = offsetHoursOr(
              meta.start_time ?? "",
              s.sample.timezoneOffsetHours,
            );
            const newStart =
              minuteOfDay !== null
                ? rebaseStartToDayAndMinute(dayKey, minuteOfDay, tz)
                : meta.start_time
                  ? rebaseStartToDay(meta.start_time, dayKey, tz)
                  : null;
            if (newStart === null) return n;
            return { ...n, metadata: { ...meta, start_time: newStart } };
          };
          const previousNodes = s.nodes;
          set({
            nodes: s.nodes.map(apply),
            pendingProposals: s.pendingProposals.map(apply),
            flashNodeId: id,
          });
          // Persist committed nodes only (proposals aren't persisted yet).
          if (!selectEditable(get())) return;
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
