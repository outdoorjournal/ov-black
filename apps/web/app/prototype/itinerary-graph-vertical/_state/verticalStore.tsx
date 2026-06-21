"use client";

// Per-prototype zustand store for the vertical itinerary timeline. Combines
// the timeline slice (nodes, edges, proposals, chat messages, focus, flash)
// and the zoom slice (pxPerMinute + presets) into one store, scoped per
// VerticalShell instance via the Provider. Selectors keep components from
// re-rendering on slices they don't read.

import { createStoreContext } from "@/lib/store/createStoreContext";

import type {
  EdgeResponse,
  NodeResponse,
  VerticalTimeline,
} from "@/app/_components/itinerary-graph/model/types";
import type { AgentNode } from "./mockStream";

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

export type VerticalState = {
  // Timeline slice
  sample: VerticalTimeline;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pendingProposals: NodeResponse[];
  messages: ChatMessage[];
  focusedNodeId: string | null;
  flashNodeId: string | null;
  assemblePulse: number;

  // Zoom slice
  pxPerMinute: number;

  // Timeline actions
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

  // Zoom actions
  setPxPerMinute: (value: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
  setZoomPreset: (preset: ZoomPreset) => void;
};

export type VerticalStoreInit = {
  timeline: VerticalTimeline;
};

export const verticalStore = createStoreContext<
  VerticalState,
  VerticalStoreInit
>(
  ({ timeline }) =>
    (set) => {
      // Pick a visually rich node for the opening frame so the ambient layer
      // never starts blank (image + map coords both present).
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
            text: `${timeline.label} — ${timeline.subtitle}. Hover cards to fly the map; try the AI demo below.`,
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

        setPxPerMinute: (v) => set({ pxPerMinute: clampZoom(v) }),
        zoomIn: () =>
          set((s) => ({ pxPerMinute: clampZoom(s.pxPerMinute * 1.35) })),
        zoomOut: () =>
          set((s) => ({ pxPerMinute: clampZoom(s.pxPerMinute / 1.35) })),
        resetZoom: () => set({ pxPerMinute: ZOOM_PRESETS.day }),
        setZoomPreset: (preset) => set({ pxPerMinute: ZOOM_PRESETS[preset] }),
      };
    },
  "Vertical",
);
