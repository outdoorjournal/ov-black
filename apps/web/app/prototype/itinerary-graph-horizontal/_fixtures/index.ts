// The horizontal prototype reuses the Japan fixture verbatim — same node
// shape, same start_times, same mood — and lays it out across day columns
// rather than a single tall column.

import { buildJapan } from "../../itinerary-graph-vertical/_fixtures/japan";
import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/horizontalTypes";

export function getHorizontalTimeline(): ItineraryTimeline {
  return buildJapan();
}
