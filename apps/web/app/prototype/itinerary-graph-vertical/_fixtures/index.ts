import { buildJapan } from "./japan";
import type { VerticalTimeline } from "../_lib/types";

export function getVerticalTimeline(): VerticalTimeline {
  return buildJapan();
}

export { buildJapan };
