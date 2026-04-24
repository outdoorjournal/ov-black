import type {
  EdgeResponse,
  EdgeType,
  ItineraryResponse,
  NodeResponse,
  NodeStatus,
  NodeType,
} from "@ov-black/api-client";

export type { EdgeResponse, EdgeType, ItineraryResponse, NodeResponse, NodeStatus, NodeType };

// Mood ids mirror the atmos system; kept as a string union so the prototype
// doesn't need to import the runtime lib.
export type MoodId =
  | "glacial"
  | "ember"
  | "amber"
  | "verdant"
  | "tidal"
  | "onyx"
  | "alpine";

// A bag of typed fields we tuck into NodeResponse.metadata. The API keeps
// metadata open (`{ [key: string]: unknown }`) so our fixtures satisfy the
// real shape while callers can pull typed fields via `getMeta(node)`.
export interface NodeMeta {
  day_index?: number;
  rank?: number;
  snapshot?: CardSnapshot;
  iata_from?: string;
  iata_to?: string;
  flight_code?: string;
  nights?: number;
  mode?: string;
  time_of_day?: "morning" | "lunch" | "afternoon" | "evening" | "night";
  body?: string;
  emoji?: string;
  description?: string;
}

export interface CardSnapshot {
  title: string;
  cover_image?: string;
  price?: string;
  duration_days?: number;
  difficulty?: string;
  location?: string;
  activities?: string[];
}

export function getMeta(node: NodeResponse): NodeMeta {
  return node.metadata as NodeMeta;
}

export interface SampleTimeline {
  id: string;
  label: string;
  subtitle: string;
  mood: MoodId;
  dayLabels?: string[];
  itinerary: ItineraryResponse;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
}

export const NODE_TYPE_ORDER: Record<NodeType, number> = {
  flight: 0,
  transit: 1,
  destination: 2,
  hotel: 3,
  experience: 4,
  meal: 5,
  free_time: 6,
  note: 7,
};

export const STATUS_LABELS: Record<NodeStatus, string> = {
  idea: "Idea",
  proposed: "Proposed",
  approved: "Approved",
  booked: "Booked",
  confirmed: "Confirmed",
  discarded: "Dismissed",
};

export const EDGE_TYPE_COLORS: Record<EdgeType, string> = {
  follows: "rgba(10, 10, 10, 0.38)",
  alternative_to: "rgba(10, 10, 10, 0.28)",
  connected_by: "rgba(10, 10, 10, 0.30)",
  requires: "#8b2a1d",
  grouped_with: "rgba(10, 10, 10, 0.18)",
};

export const MOOD_ACCENTS: Record<MoodId, { accent: string; tint: string }> = {
  glacial: { accent: "#7a9aa8", tint: "#dfe8ee" },
  ember: { accent: "#b85a3e", tint: "#ebd2c6" },
  amber: { accent: "#b58a3a", tint: "#ecddbb" },
  verdant: { accent: "#5f7a4a", tint: "#d8e1cd" },
  tidal: { accent: "#4d7490", tint: "#d0dde4" },
  onyx: { accent: "#3a3a3a", tint: "#d4d2ce" },
  alpine: { accent: "#6d7c8f", tint: "#d9dde2" },
};
