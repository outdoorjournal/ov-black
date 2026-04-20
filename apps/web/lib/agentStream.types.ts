// SSE frame shapes emitted by POST /sessions/{id}/turn.
//
// The wire contract is defined by apps/api/app/services/agent.py (_sse_encode
// + _FALLBACK_FRAME). This module mirrors those shapes on the browser side so
// the DIY SSE consumer in agentStream.ts can discriminate without any runtime
// dependency.

export type FirstTokenFrame = {
  type: "first_token";
  ms: number;
};

export type DeltaFrame = {
  type: "delta";
  text: string;
};

export type DoneFrame = {
  type: "done";
  turn_id: string;
  model: string;
  latency_ms: number;
  first_token_ms: number | null;
  retried: number;
};

export type ErrorFrame = {
  type: "error";
  reason: string;
};

export type SseFrame = FirstTokenFrame | DeltaFrame | DoneFrame | ErrorFrame;
