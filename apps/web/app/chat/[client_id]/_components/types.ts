// View-model types for the client chat shell.
//
// AgentTurnView is a superset of the API's AgentTurnSummary: we widen `role`
// to include any TurnRole (assistant/user/system/tool/error) and keep id
// locally stable so the in-flight streaming row can be promoted to a real row
// on `done` without remounting.

import type {
  AgentTurnSummary,
  NodeResponse,
  NodeStatus,
  TurnRole,
} from "@ov-black/api-client";

import type { ExperienceSnapshot } from "@/lib/agentStream.types";

export type AgentTurnView = {
  id: string;
  turn_index: number;
  role: TurnRole;
  content: string;
};

export function fromSummary(summary: AgentTurnSummary): AgentTurnView {
  return {
    id: summary.id,
    turn_index: summary.turn_index,
    role: summary.role,
    content: summary.content,
  };
}

// In-flight streaming state. `turnIndex` is the optimistic next index we
// assigned when POSTing the user turn; `buffer` is the accumulated delta
// text for the in-progress assistant reply. Both are cleared on done/error.
export type StreamState = {
  turnIndex: number;
  buffer: string;
};

// ── MoodBoard card view model (S07 T05) ───────────────────────────────────

// The client-side view model for a single MoodBoard card. Keyed on `node_id`
// (unique per proposal) so optimistic status flips and PATCH reverts have a
// stable handle. Re-proposals of the same `source_id` in a session are
// avoided by agent-side discipline (T02 prompt); the reducer does not
// dedupe.
export type CardView = {
  node_id: string;
  source: string;
  source_id: string;
  status: NodeStatus;
  snapshot: ExperienceSnapshot;
};

// RSC-side initial shape derived from GET /itinerary/{id} nodes where
// type='experience' AND source='ov'. Built server-side in page.tsx and
// passed into ChatShell's reducer initializer so a hard reload restores
// the MoodBoard state without a client round-trip.
export type InitialCardPayload = {
  node_id: string;
  source: string;
  source_id: string;
  status: NodeStatus;
  snapshot: ExperienceSnapshot;
};

// Derive an InitialCardPayload from a NodeResponse row (the shape the
// itinerary GET returns). Snapshots live under metadata.snapshot; if the
// shape drifts (e.g. an older row without an inline snapshot), we fall back
// to a minimal snapshot containing the node title so the card still renders
// something the user can interact with.
export function cardFromNode(node: NodeResponse): InitialCardPayload | null {
  if (node.type !== "experience") return null;
  if (node.source !== "ov") return null;
  if (!node.source_id) return null;
  const rawSnapshot =
    node.metadata && typeof node.metadata === "object"
      ? (node.metadata as { snapshot?: unknown }).snapshot
      : undefined;
  const snapshot: ExperienceSnapshot =
    rawSnapshot && typeof rawSnapshot === "object"
      ? (rawSnapshot as ExperienceSnapshot)
      : { title: node.title };
  return {
    node_id: node.id,
    source: node.source,
    source_id: node.source_id,
    status: node.status,
    snapshot,
  };
}
