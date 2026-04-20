// View-model types for the client chat shell.
//
// AgentTurnView is a superset of the API's AgentTurnSummary: we widen `role`
// to include any TurnRole (assistant/user/system/tool/error) and keep id
// locally stable so the in-flight streaming row can be promoted to a real row
// on `done` without remounting.

import type { AgentTurnSummary, TurnRole } from "@ov-black/api-client";

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
