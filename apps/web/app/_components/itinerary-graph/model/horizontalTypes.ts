// Re-export the vertical prototype's types so the horizontal layout consumes
// the same fixtures and node metadata shape. The horizontal view differs in
// how it lays time out (per-day columns sharing one minute-of-day y axis), not
// in what a node looks like.

export type {
  EdgeResponse,
  EdgeType,
  ItineraryResponse,
  NodeResponse,
  NodeStatus,
  NodeType,
  VerticalNodeMeta as HorizontalNodeMeta,
  ItineraryTimeline,
} from "./types";

export {
  getVerticalMeta as getHMeta,
  getMeta,
  MOOD_ACCENTS,
  NODE_TYPE_ORDER,
  STATUS_LABELS,
} from "./types";

export type { CardSnapshot, MoodId } from "./types";
