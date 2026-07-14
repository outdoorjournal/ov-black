import type { NodeResponse } from "../model/horizontalTypes";

/**
 * Embedded subgraphs (PRD "subgraphs for self-contained experiences"): a
 * multi-day inventory item (an OV adventure) lands as ONE experience card
 * whose internal day-by-day journey is materialized as child nodes carrying
 * `parent_subgraph_id`. In the Journal those children DO surface on the
 * timeline — `deriveJourneyBeats` (toJournal.ts) lays each one onto the day it
 * covers as a derived "journey beat" (day k of N), spread forward from the
 * parent card's day, so a multi-day package reads across the days it spans. The
 * children are still derived content (never in the Collection, never
 * independently draggable — the parent owns the slot and its provenance).
 * Subgraphs are inventory-born or campaign-template-authored (the Olympus
 * cornerstone); both feed these same read helpers.
 */

/** Structured per-day fields the from-inventory materialization stores. */
export type SubgraphDayMeta = {
  index?: number;
  hours?: number;
  lat?: number;
  lng?: number;
  description_html?: string;
};

export function isSubgraphChild(node: NodeResponse): boolean {
  return node.parent_subgraph_id !== null && node.parent_subgraph_id !== undefined;
}

export function subgraphDayMeta(node: NodeResponse): SubgraphDayMeta {
  const raw = (node.metadata as { subgraph_day?: unknown }).subgraph_day;
  return raw && typeof raw === "object" ? (raw as SubgraphDayMeta) : {};
}

/**
 * Group subgraph children by their parent node id, ordered by the day index
 * (falling back to creation order — the materializer writes days in order).
 */
export function subgraphChildrenByParent(
  nodes: NodeResponse[],
): Map<string, NodeResponse[]> {
  const map = new Map<string, NodeResponse[]>();
  for (const n of nodes) {
    const parent = n.parent_subgraph_id;
    if (!parent) continue;
    if (n.status === "discarded") continue;
    const existing = map.get(parent);
    if (existing) existing.push(n);
    else map.set(parent, [n]);
  }
  for (const children of map.values()) {
    children.sort(
      (a, b) =>
        (subgraphDayMeta(a).index ?? Number.MAX_SAFE_INTEGER) -
        (subgraphDayMeta(b).index ?? Number.MAX_SAFE_INTEGER),
    );
  }
  return map;
}

/** Vendor descriptions arrive as HTML; the Journal renders text only. */
export function stripHtml(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}
