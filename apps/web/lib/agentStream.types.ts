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

// Legacy frame, emitted by the pre-agent-workspace runtime + FastAPI's
// stream_turn dispatch. Will be removed once the new runtime is the only
// path in staging/prod.
export type CardFrame = {
  type: "card";
  source: string;
  source_id: string;
  node_id: string;
  snapshot: ExperienceSnapshot;
};

// A node pushed into the itinerary by the agent runtime (new shape).
// Shape matches the API's NodeResponse — id + itinerary_id + type + status
// + title + source + source_id + metadata.
export type AgentNode = {
  id: string;
  itinerary_id: string;
  type: string;
  status: string;
  title: string;
  source: string | null;
  source_id: string | null;
  metadata: Record<string, unknown> & { snapshot?: ExperienceSnapshot };
};

export type CardProposedFrame = {
  type: "card_proposed";
  node: AgentNode;
};

export type DraftAssembledFrame = {
  type: "draft_assembled";
  edges_created: number;
};

export type NodeUpdatedFrame = {
  type: "node_updated";
  node: AgentNode;
};

// Emitted when the agent calls `set_mood` to shift basecamp ambience.
// `mood_id` is one of the curated MoodIds in apps/web/lib/atmos/moods.ts.
// The wire payload is `{type:"mood", mood_id:string}` — we keep mood_id
// as a plain string here and let the consumer narrow against MoodId so
// this types module stays free of UI-layer imports.
export type MoodFrame = {
  type: "mood";
  mood_id: string;
};

export type SseFrame =
  | FirstTokenFrame
  | DeltaFrame
  | DoneFrame
  | ErrorFrame
  | CardFrame
  | CardProposedFrame
  | DraftAssembledFrame
  | NodeUpdatedFrame
  | MoodFrame;
