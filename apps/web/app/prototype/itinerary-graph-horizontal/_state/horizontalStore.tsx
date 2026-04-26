"use client";

// Per-prototype zustand store for the horizontal itinerary timeline. Same
// surface area as the vertical store (the AI mockStream and demo controller
// import VerticalState shape from there), so we keep the field set 1:1 and
// just call the type HorizontalState here for clarity.

import { createStoreContext } from "@/lib/store/createStoreContext";

import type {
  EdgeResponse,
  HorizontalTimeline,
  NodeResponse,
} from "../_lib/types";
import type { AgentNode } from "../../itinerary-graph-vertical/_state/mockStream";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  streaming?: boolean;
}

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

export type HorizontalState = {
  sample: HorizontalTimeline;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pendingProposals: NodeResponse[];
  messages: ChatMessage[];
  focusedNodeId: string | null;
  flashNodeId: string | null;
  assemblePulse: number;

  pxPerMinute: number;

  focusNode: (id: string | null) => void;
  appendUserMessage: (id: string, text: string) => void;
  appendAssistantMessage: (id: string, text?: string) => void;
  appendDelta: (id: string, text: string) => void;
  finishAssistant: (id: string) => void;
  proposeNode: (node: AgentNode) => void;
  acceptProposal: (id: string) => void;
  dismissProposal: (id: string) => void;
  applyNodeUpdate: (node: AgentNode) => void;
  flashNode: (id: string | null) => void;
  pulseAssemble: () => void;

  // Day move: re-target a node to a different day key. Updates the start_time
  // to the same minute-of-day on the new date, preserving timezone.
  moveNodeToDay: (id: string, dayKey: string) => void;

  setPxPerMinute: (value: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
  setZoomPreset: (preset: ZoomPreset) => void;
};

export type HorizontalStoreInit = {
  timeline: HorizontalTimeline;
};

// Move the start_time of a node onto a different day, keeping HH:MM and tz
// offset intact. This is what powers the drag-and-drop "move to day N" gesture.
function rebaseStartToDay(
  startIso: string,
  dayKey: string,
  tzOffsetHours: number,
): string {
  const ms = new Date(startIso).getTime() + tzOffsetHours * 3600 * 1000;
  const d = new Date(ms);
  const hh = d.getUTCHours();
  const mm = d.getUTCMinutes();
  const ss = d.getUTCSeconds();
  // Build the same HH:MM:SS on the new date in the same tz offset.
  const offsetSign = tzOffsetHours >= 0 ? "+" : "-";
  const absOff = Math.abs(tzOffsetHours);
  const offH = String(Math.floor(absOff)).padStart(2, "0");
  const offM = String(Math.round((absOff % 1) * 60)).padStart(2, "0");
  const hhStr = String(hh).padStart(2, "0");
  const mmStr = String(mm).padStart(2, "0");
  const ssStr = String(ss).padStart(2, "0");
  return `${dayKey}T${hhStr}:${mmStr}:${ssStr}${offsetSign}${offH}:${offM}`;
}

export const horizontalStore = createStoreContext<
  HorizontalState,
  HorizontalStoreInit
>(
  ({ timeline }) =>
    (set) => {
      // Pick a visually rich first focus so the map / image starts populated.
      const defaultFocus = timeline.nodes.find((n) => {
        const m = n.metadata as { ambient_image?: string; location?: unknown };
        return typeof m.ambient_image === "string" && Boolean(m.location);
      });

      return {
        sample: timeline,
        nodes: [...timeline.nodes],
        edges: [...timeline.edges],
        pendingProposals: [],
        messages: [
          {
            id: `sys-${timeline.id}`,
            role: "system",
            text: `${timeline.label} — ${timeline.subtitle}. Drag a card to a different day; hover to fly the map.`,
          },
        ],
        focusedNodeId: defaultFocus?.id ?? null,
        flashNodeId: null,
        assemblePulse: 0,
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
        moveNodeToDay: (id, dayKey) =>
          set((s) => {
            const tz = s.sample.timezoneOffsetHours;
            const update = (n: NodeResponse): NodeResponse => {
              if (n.id !== id) return n;
              const meta = n.metadata as {
                start_time?: string;
                [k: string]: unknown;
              };
              if (!meta.start_time) return n;
              const newStart = rebaseStartToDay(
                meta.start_time,
                dayKey,
                tz,
              );
              return {
                ...n,
                metadata: { ...meta, start_time: newStart },
              };
            };
            return {
              nodes: s.nodes.map(update),
              pendingProposals: s.pendingProposals.map(update),
              flashNodeId: id,
            };
          }),

        setPxPerMinute: (v) => set({ pxPerMinute: clampZoom(v) }),
        zoomIn: () =>
          set((s) => ({ pxPerMinute: clampZoom(s.pxPerMinute * 1.35) })),
        zoomOut: () =>
          set((s) => ({ pxPerMinute: clampZoom(s.pxPerMinute / 1.35) })),
        resetZoom: () => set({ pxPerMinute: ZOOM_PRESETS.day }),
        setZoomPreset: (preset) => set({ pxPerMinute: ZOOM_PRESETS[preset] }),
      };
    },
  "Horizontal",
);
