"use client";

// Per-prototype zustand store for the horizontal itinerary-graph timeline.
// Replaces the previous useReducer-based useTimelineState. Scoped per
// PrototypeShell instance via the Provider so each mounted prototype gets a
// fresh store seeded from its initial sample.

import { createStoreContext } from "@/lib/store/createStoreContext";

import type {
  EdgeResponse,
  NodeResponse,
  SampleTimeline,
} from "@/app/_components/itinerary-graph/model/baseTypes";
import type { AgentNode } from "./mockStream";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  streaming?: boolean;
  pendingNodeId?: string;
}

export type TimelineState = {
  sample: SampleTimeline;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pendingProposals: NodeResponse[];
  messages: ChatMessage[];
  assemblePulse: number;
  flashNodeId: string | null;

  loadSample: (sample: SampleTimeline) => void;
  moveNode: (id: string, dayIndex: number, rank: number) => void;
  reorderWithinDay: (dayIndex: number, nodeIdsInOrder: string[]) => void;
  removeNode: (id: string) => void;
  appendUserMessage: (id: string, text: string) => void;
  appendAssistantMessage: (id: string, text?: string) => void;
  appendDelta: (id: string, text: string) => void;
  finishAssistant: (id: string) => void;
  proposeNode: (node: AgentNode) => void;
  acceptProposal: (id: string) => void;
  dismissProposal: (id: string) => void;
  assembleDraft: (newEdges: Array<{ fromId: string; toId: string }>) => void;
  applyNodeUpdate: (node: AgentNode) => void;
  flashNode: (id: string | null) => void;
};

export type TimelineStoreInit = {
  sample: SampleTimeline;
};

function meta(node: NodeResponse) {
  return node.metadata as Record<string, unknown>;
}

function buildInitialState(sample: SampleTimeline): Pick<
  TimelineState,
  | "sample"
  | "nodes"
  | "edges"
  | "pendingProposals"
  | "messages"
  | "assemblePulse"
  | "flashNodeId"
> {
  return {
    sample,
    nodes: [...sample.nodes],
    edges: [...sample.edges],
    pendingProposals: [],
    messages: [
      {
        id: `sys-${sample.id}`,
        role: "system",
        text: `${sample.label} — ${sample.subtitle}. Try the AI demo below or drag cards to reorder.`,
      },
    ],
    assemblePulse: 0,
    flashNodeId: null,
  };
}

export const timelineStore = createStoreContext<
  TimelineState,
  TimelineStoreInit
>(
  ({ sample }) =>
    (set) => ({
      ...buildInitialState(sample),

      loadSample: (next) => set(() => buildInitialState(next)),
      moveNode: (id, dayIndex, rank) =>
        set((s) => ({
          nodes: s.nodes.map((n) =>
            n.id === id
              ? { ...n, metadata: { ...meta(n), day_index: dayIndex, rank } }
              : n,
          ),
        })),
      reorderWithinDay: (dayIndex, nodeIdsInOrder) =>
        set((s) => ({
          nodes: s.nodes.map((n) => {
            const idx = nodeIdsInOrder.indexOf(n.id);
            if (idx < 0) return n;
            return {
              ...n,
              metadata: { ...meta(n), day_index: dayIndex, rank: idx },
            };
          }),
        })),
      removeNode: (id) =>
        set((s) => ({
          nodes: s.nodes.filter((n) => n.id !== id),
          edges: s.edges.filter(
            (e) => e.from_node_id !== id && e.to_node_id !== id,
          ),
        })),
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
      assembleDraft: (newEdges) =>
        set((s) => {
          const built: EdgeResponse[] = newEdges.map((e, i) => ({
            id: `e-assembled-${Date.now()}-${i}`,
            itinerary_id: s.sample.itinerary.id,
            from_node_id: e.fromId,
            to_node_id: e.toId,
            type: "follows",
            metadata: {},
          }));
          return {
            edges: [...s.edges, ...built],
            assemblePulse: s.assemblePulse + 1,
          };
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
    }),
  "Timeline",
);
