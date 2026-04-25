"use client";

import { useReducer } from "react";

import type {
  EdgeResponse,
  NodeResponse,
  VerticalTimeline,
} from "../_lib/types";
import type { AgentNode } from "./mockStream";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  streaming?: boolean;
}

export interface VerticalTimelineState {
  sample: VerticalTimeline;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pendingProposals: NodeResponse[];
  messages: ChatMessage[];
  focusedNodeId: string | null;
  flashNodeId: string | null;
  assemblePulse: number;
}

export type VerticalTimelineAction =
  | { type: "FOCUS_NODE"; id: string | null }
  | { type: "APPEND_USER_MESSAGE"; id: string; text: string }
  | { type: "APPEND_ASSISTANT_MESSAGE"; id: string; text?: string }
  | { type: "APPEND_DELTA"; id: string; text: string }
  | { type: "FINISH_ASSISTANT"; id: string }
  | { type: "PROPOSE_NODE"; node: AgentNode }
  | { type: "ACCEPT_PROPOSAL"; id: string }
  | { type: "DISMISS_PROPOSAL"; id: string }
  | { type: "UPDATE_NODE"; node: AgentNode }
  | { type: "FLASH_NODE"; id: string | null }
  | { type: "ASSEMBLE_PULSE" };

function reducer(
  state: VerticalTimelineState,
  action: VerticalTimelineAction,
): VerticalTimelineState {
  switch (action.type) {
    case "FOCUS_NODE":
      return { ...state, focusedNodeId: action.id };
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
    case "ASSEMBLE_PULSE":
      return { ...state, assemblePulse: state.assemblePulse + 1 };
  }
}

export function useVerticalTimelineState(initial: VerticalTimeline) {
  // Pick a visually rich node for the opening frame so the ambient layer
  // never starts blank (image + map coords both present).
  const defaultFocus = initial.nodes.find((n) => {
    const m = n.metadata as { ambient_image?: string; location?: unknown };
    return typeof m.ambient_image === "string" && Boolean(m.location);
  });

  const init: VerticalTimelineState = {
    sample: initial,
    nodes: [...initial.nodes],
    edges: [...initial.edges],
    pendingProposals: [],
    messages: [
      {
        id: `sys-${initial.id}`,
        role: "system",
        text: `${initial.label} — ${initial.subtitle}. Hover cards to fly the map; try the AI demo below.`,
      },
    ],
    focusedNodeId: defaultFocus?.id ?? null,
    flashNodeId: null,
    assemblePulse: 0,
  };
  const [state, dispatch] = useReducer(reducer, init);
  return { state, dispatch };
}
