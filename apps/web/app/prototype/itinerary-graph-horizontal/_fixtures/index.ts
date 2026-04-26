// The horizontal prototype reuses the Japan fixture verbatim — same node
// shape, same start_times, same mood — and lays it out across day columns
// rather than a single tall column.

import { buildJapan } from "../../itinerary-graph-vertical/_fixtures/japan";
import type { HorizontalTimeline } from "../_lib/types";

export function getHorizontalTimeline(): HorizontalTimeline {
  return buildJapan();
}
