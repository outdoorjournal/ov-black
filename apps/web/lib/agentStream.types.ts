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

// Emitted after the agent calls `update_trip_timing` to set the trip's dates
// (or loosen them back to flexible). The itinerary's brief + timing live as a
// server-rendered prop on the timeline, so consumers refresh the route rather
// than patch a store; the payload mirrors the API's ItineraryResponse timing
// fields for consumers that want to read the new values directly.
export type ItineraryUpdatedFrame = {
  type: "itinerary_updated";
  itinerary: {
    id: string;
    title?: string;
    brief?: string | null;
    timing_kind?: "exact" | "window" | "flexible" | null;
    date_start?: string | null;
    date_end?: string | null;
    duration_nights?: number | null;
    timing_note?: string | null;
  };
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

// Emitted when the agent records or updates a party member during the
// immersive intake conversation. Whitelisted subset only — the runtime never
// puts dietary/medical/notes on this frame; the intake details card just
// needs a name and a relationship for "who's coming".
export type PartyUpdatedFrame = {
  type: "party_updated";
  member: {
    id: string;
    full_name?: string;
    relationship_to_primary?: string;
    is_primary?: boolean;
  };
};

// Emitted when the agent calls `complete_intake` — the immersive first
// conversation is done. The intake surface docks the chat into its normal
// column and lands the traveler on the trip dashboard; every other surface
// can ignore it.
export type IntakeCompleteFrame = {
  type: "intake_complete";
};

// Anonymous tool-activity pulse, emitted by the agent runtime for every tool
// call and result. Deliberately carries NOTHING but the phase — no tool name,
// id, status or payload — because even a tool's name can disclose private
// machinery to a traveler (record_dossier_inference). Chat surfaces use it to
// show "the concierge is working" during a tool-first preamble; the named,
// dev-only tool_trace frame is a separate harness channel and never part of
// this union.
export type ActivityFrame = {
  type: "activity";
  phase: "call" | "result";
};

// A presentation surface for the drawer beside the chat — emitted when the
// agent calls `present_route` / `present_options` (more kinds to come). The
// payload is deliberately kept as an unknown-record at the wire layer; the
// chat surface module parses it tolerantly per `kind` (like parseTimeline)
// so a malformed payload drops the panel rather than crashing the stream.
export type SurfaceFrame = {
  type: "surface";
  surface_id: string;
  kind: string;
  payload: Record<string, unknown>;
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
  | ItineraryUpdatedFrame
  | PartyUpdatedFrame
  | IntakeCompleteFrame
  | MoodFrame
  | ActivityFrame
  | SurfaceFrame;
