import type { SampleTimeline } from "../_lib/types";
import { buildAmalfi } from "./amalfi-nested";
import { buildPatagonia } from "./patagonia";
import { buildTokyoKyoto } from "./tokyo-kyoto";
import { buildTuscany } from "./tuscany";

export function getSampleTimelines(): SampleTimeline[] {
  return [buildTuscany(), buildAmalfi(), buildTokyoKyoto(), buildPatagonia()];
}
