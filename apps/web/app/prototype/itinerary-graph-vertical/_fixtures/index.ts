import { buildJapan } from "./japan";
import type { VerticalTimeline } from "@/app/_components/itinerary-graph/model/types";

export function getVerticalTimeline(): VerticalTimeline {
  return buildJapan();
}

export { buildJapan };
