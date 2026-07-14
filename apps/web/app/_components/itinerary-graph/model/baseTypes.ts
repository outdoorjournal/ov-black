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
  cabin?: string;
  seat?: string;
  // Flight wall-clock endpoints (offset-bearing or Duffel-local ISO). The
  // flight card reads these for the depart → arrive line + jet-bridge timing.
  depart_at?: string;
  arrive_at?: string;
  nights?: number;
  // Hotel class, 1–5 stars (scraped SerpApi/Google Hotels hotels).
  stars?: number;
  mode?: string;
  time_of_day?: "morning" | "lunch" | "afternoon" | "evening" | "night";
  body?: string;
  emoji?: string;
  description?: string;
  place?: PlaceFacts;
  // Reading-list article fields (save_link_to_collection with kind="article").
  // `note` is a human-friendly label ("Backpacker — Olympus thru-hike");
  // `publication` is the derived source ("Backpacker"); `url` is the link. The
  // card prefers these over node.title, which for an article is the raw URL.
  url?: string;
  publication?: string;
  note?: string;
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

// Point-of-interest enrichment (Google Places et al.) surfaced on experience
// and meal cards: crowd rating, opening hours, contact, an external map deep
// link, and a signed handle for the keyed photo proxy. `photo_token` is NOT a
// URL — the card builds `{apiBase}/integrations/google-places/photo?token=…`
// from it (see `placePhotoUrl`). `maps_url` is a keyless Google Maps deep link.
export interface PlaceFacts {
  rating?: number;
  rating_count?: number;
  hours?: string[];
  website?: string;
  phone?: string;
  maps_url?: string;
  photo_token?: string;
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
  subway: 2,
  train: 3,
  drive: 4,
  walk: 5,
  boat: 6,
  destination: 7,
  hotel: 8,
  experience: 9,
  meal: 10,
  free_time: 11,
  waiting: 12,
  note: 13,
  article: 14,
};

export const STATUS_LABELS: Record<NodeStatus, string> = {
  pending: "Pending",
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
