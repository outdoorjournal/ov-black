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

/** Structured per-day fields the from-inventory materialization stores. A
 *  campaign-authored BEAT child (an inferred sub-moment — several share one
 *  day) additionally carries `hhmm` (its local clock time within the day) and
 *  `duration_minutes`. */
export type SubgraphDayMeta = {
  index?: number;
  hours?: number;
  lat?: number;
  lng?: number;
  location_label?: string;
  description_html?: string;
  hhmm?: string;
  duration_minutes?: number;
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
    children.sort((a, b) => {
      const ma = subgraphDayMeta(a);
      const mb = subgraphDayMeta(b);
      const byDay =
        (ma.index ?? Number.MAX_SAFE_INTEGER) -
        (mb.index ?? Number.MAX_SAFE_INTEGER);
      if (byDay !== 0) return byDay;
      // Beats within one day order by their clock time ("HH:MM" sorts
      // lexically); the stable sort keeps creation order on a tie.
      return (ma.hhmm ?? "").localeCompare(mb.hhmm ?? "");
    });
  }
  return map;
}

/**
 * How many calendar days a subgraph spans — distinct day indexes, since a day
 * may hold several beat children. Drives "a N-day journey" / "day k of N".
 */
export function subgraphDaySpan(children: NodeResponse[]): number {
  const indexes = new Set<number>();
  for (const child of children) {
    const index = subgraphDayMeta(child).index;
    if (typeof index === "number") indexes.add(index);
  }
  return indexes.size > 0 ? indexes.size : children.length;
}

/**
 * Beat imagery: the materializer gives day children no image of their own, so
 * each beat wears its PARENT's — a rotating pull from the parent's editorial
 * gallery when one exists (a different shot per day, never the cover itself),
 * else the parent's cover. Keeps a multi-day run visibly sharing the parent
 * card's identity. Shared by the Journal (`deriveJourneyBeats`) and the
 * horizontal timeline so a beat looks the same on both surfaces. `dayIndex` is
 * the child's 1-based day-of-journey.
 */
export function beatImageForChild(
  parent: NodeResponse,
  child: NodeResponse,
  dayIndex: number,
): string | undefined {
  const pMeta = parent.metadata as {
    snapshot?: { cover_image?: string };
    ambient_image?: string;
    gallery?: Array<{ url?: string }>;
  };
  const cMeta = child.metadata as {
    snapshot?: { cover_image?: string };
    ambient_image?: string;
  };
  const parentCover = pMeta.snapshot?.cover_image ?? pMeta.ambient_image;
  const galleryPool = (pMeta.gallery ?? [])
    .map((g) => g.url)
    .filter(
      (u): u is string =>
        typeof u === "string" && u.length > 0 && u !== parentCover,
    );
  return (
    cMeta.snapshot?.cover_image ??
    cMeta.ambient_image ??
    galleryPool[Math.max(0, dayIndex - 1) % Math.max(1, galleryPool.length)] ??
    parentCover
  );
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
