"use client";

import { useCallback, useReducer } from "react";

import type {
  EdgeResponse,
  NodeResponse,
  SampleTimeline,
} from "../_lib/types";
import type { AgentNode } from "./mockStream";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  streaming?: boolean;
  pendingNodeId?: string;
}

export interface TimelineState {
  sample: SampleTimeline;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pendingProposals: NodeResponse[];
  messages: ChatMessage[];
  assemblePulse: number;
  flashNodeId: string | null;
}

export type TimelineAction =
  | { type: "LOAD_SAMPLE"; sample: SampleTimeline }
  | {
      type: "MOVE_NODE";
      id: string;
      dayIndex: number;
      rank: number;
    }
  | { type: "REORDER_WITHIN_DAY"; dayIndex: number; nodeIdsInOrder: string[] }
  | { type: "REMOVE_NODE"; id: string }
  | { type: "APPEND_USER_MESSAGE"; id: string; text: string }
  | { type: "APPEND_ASSISTANT_MESSAGE"; id: string; text?: string }
  | { type: "APPEND_DELTA"; id: string; text: string }
  | { type: "FINISH_ASSISTANT"; id: string }
  | { type: "PROPOSE_NODE"; node: AgentNode }
  | { type: "ACCEPT_PROPOSAL"; id: string }
  | { type: "DISMISS_PROPOSAL"; id: string }
  | {
      type: "ASSEMBLE_DRAFT";
      newEdges: Array<{ fromId: string; toId: string }>;
    }
  | { type: "UPDATE_NODE"; node: AgentNode }
  | { type: "FLASH_NODE"; id: string | null };

function meta(node: NodeResponse) {
  return node.metadata as Record<string, unknown>;
}

function reducer(state: TimelineState, action: TimelineAction): TimelineState {
  switch (action.type) {
    case "LOAD_SAMPLE":
      return {
        sample: action.sample,
        nodes: [...action.sample.nodes],
        edges: [...action.sample.edges],
        pendingProposals: [],
        messages: [
          {
            id: `sys-${action.sample.id}`,
            role: "system",
            text: `${action.sample.label} — ${action.sample.subtitle}. Try the AI demo below or drag cards to reorder.`,
          },
        ],
        assemblePulse: 0,
        flashNodeId: null,
      };

    case "MOVE_NODE": {
      const nodes = state.nodes.map((n) => {
        if (n.id !== action.id) return n;
        return {
          ...n,
          metadata: {
            ...meta(n),
            day_index: action.dayIndex,
            rank: action.rank,
          },
        };
      });
      return { ...state, nodes };
    }

    case "REORDER_WITHIN_DAY": {
      const nodes = state.nodes.map((n) => {
        const idx = action.nodeIdsInOrder.indexOf(n.id);
        if (idx < 0) return n;
        return {
          ...n,
          metadata: {
            ...meta(n),
            day_index: action.dayIndex,
            rank: idx,
          },
        };
      });
      return { ...state, nodes };
    }

    case "REMOVE_NODE":
      return {
        ...state,
        nodes: state.nodes.filter((n) => n.id !== action.id),
        edges: state.edges.filter(
          (e) => e.from_node_id !== action.id && e.to_node_id !== action.id,
        ),
      };

    case "APPEND_USER_MESSAGE":
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: action.id, role: "user", text: action.text },
        ],
      };

    case "APPEND_ASSISTANT_MESSAGE":
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: action.id,
            role: "assistant",
            text: action.text ?? "",
            streaming: true,
          },
        ],
      };

    case "APPEND_DELTA":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, text: m.text + action.text } : m,
        ),
      };

    case "FINISH_ASSISTANT":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, streaming: false } : m,
        ),
      };

    case "PROPOSE_NODE": {
      const asNode: NodeResponse = {
        id: action.node.id,
        itinerary_id: action.node.itinerary_id,
        parent_subgraph_id: null,
        type: action.node.type as NodeResponse["type"],
        status: "proposed",
        title: action.node.title,
        source: action.node.source,
        source_id: action.node.source_id,
        metadata: action.node.metadata,
      };
      return { ...state, pendingProposals: [...state.pendingProposals, asNode] };
    }

    case "ACCEPT_PROPOSAL": {
      const proposal = state.pendingProposals.find((p) => p.id === action.id);
      if (!proposal) return state;
      const approved: NodeResponse = { ...proposal, status: "approved" };
      return {
        ...state,
        pendingProposals: state.pendingProposals.filter(
          (p) => p.id !== action.id,
        ),
        nodes: [...state.nodes, approved],
        flashNodeId: approved.id,
      };
    }

    case "DISMISS_PROPOSAL":
      return {
        ...state,
        pendingProposals: state.pendingProposals.filter(
          (p) => p.id !== action.id,
        ),
      };

    case "ASSEMBLE_DRAFT": {
      const newEdges: EdgeResponse[] = action.newEdges.map((e, i) => ({
        id: `e-assembled-${Date.now()}-${i}`,
        itinerary_id: state.sample.itinerary.id,
        from_node_id: e.fromId,
        to_node_id: e.toId,
        type: "follows",
        metadata: {},
      }));
      return {
        ...state,
        edges: [...state.edges, ...newEdges],
        assemblePulse: state.assemblePulse + 1,
      };
    }

    case "UPDATE_NODE": {
      const nodes = state.nodes.map((n) =>
        n.id === action.node.id
          ? {
              ...n,
              title: action.node.title,
              metadata: { ...n.metadata, ...action.node.metadata },
            }
          : n,
      );
      return { ...state, nodes, flashNodeId: action.node.id };
    }

    case "FLASH_NODE":
      return { ...state, flashNodeId: action.id };
  }
}

export function useTimelineState(initial: SampleTimeline) {
  const init: TimelineState = {
    sample: initial,
    nodes: [...initial.nodes],
    edges: [...initial.edges],
    pendingProposals: [],
    messages: [
      {
        id: `sys-${initial.id}`,
        role: "system",
        text: `${initial.label} — ${initial.subtitle}. Try the AI demo below or drag cards to reorder.`,
      },
    ],
    assemblePulse: 0,
    flashNodeId: null,
  };
  const [state, dispatch] = useReducer(reducer, init);

  const loadSample = useCallback(
    (sample: SampleTimeline) => dispatch({ type: "LOAD_SAMPLE", sample }),
    [],
  );

  return { state, dispatch, loadSample };
}
