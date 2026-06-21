import type {
  EdgeResponse,
  EdgeType,
  ItineraryResponse,
  NodeResponse,
  NodeStatus,
  NodeType,
} from "@ov-black/api-client";

import type { NodeMeta } from "./baseTypes";

export type { EdgeResponse, EdgeType, ItineraryResponse, NodeResponse, NodeStatus, NodeType };
export { getMeta, MOOD_ACCENTS, NODE_TYPE_ORDER, STATUS_LABELS } from "./baseTypes";
export type { CardSnapshot, MoodId } from "./baseTypes";

export interface VerticalNodeMeta extends NodeMeta {
  start_time?: string;
  duration_minutes?: number;
  location?: { lat: number; lng: number; label?: string };
  // Optional explicit endpoints for travel cards (flights). When set, the map
  // draws a great-circle arc between them. Trains/transit can omit these and
  // the previous node's location is used as the implicit "from".
  from_location?: { lat: number; lng: number; label?: string };
  to_location?: { lat: number; lng: number; label?: string };
  ambient_image?: string;
  lane?: number;
  weather_emoji?: string;
  night_bar?: boolean;
  alt_group?: string;
}

export function getVerticalMeta(node: NodeResponse): VerticalNodeMeta {
  return node.metadata as VerticalNodeMeta;
}

export type VerticalTimeline = ItineraryTimeline;

export interface ItineraryTimeline {
  id: string;
  label: string;
  subtitle: string;
  mood: import("./baseTypes").MoodId;
  timezoneOffsetHours: number;
  windowStart: string;
  windowEnd: string;
  days: Array<{ date: string; label: string; weather_emoji?: string }>;
  itinerary: ItineraryResponse;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
}
