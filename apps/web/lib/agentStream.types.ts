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

// Narrow, browser-side mirror of the T02 inline snapshot shape. We intentionally
// do NOT re-import ExperienceItem from the generated SDK — that type carries
// backend-only fields like `raw` we don't want to leak into the render path.
export type ExperienceSnapshot = {
  title: string;
  cover_image?: string | null;
  price?: string | null;
  duration_days?: number | null;
  difficulty?: string | null;
  location?: string | null;
  activities?: string[];
};

export type CardFrame = {
  type: "card";
  source: string;
  source_id: string;
  node_id: string;
  snapshot: ExperienceSnapshot;
};

export type SseFrame =
  | FirstTokenFrame
  | DeltaFrame
  | DoneFrame
  | ErrorFrame
  | CardFrame;
