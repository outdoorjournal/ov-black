import type { SampleTimeline } from "@/app/_components/itinerary-graph/model/baseTypes";
import { buildAmalfi } from "./amalfi-nested";
import { buildPatagonia } from "./patagonia";
import { buildTokyoKyoto } from "./tokyo-kyoto";
import { buildTuscany } from "./tuscany";

export function getSampleTimelines(): SampleTimeline[] {
  return [buildTuscany(), buildAmalfi(), buildTokyoKyoto(), buildPatagonia()];
}
