// Collection (wish list) grouping — pure, view-agnostic.
//
// A Collection item is an itinerary node with no scheduled time. The rail can
// slice the same pile along different axes — by type, by cost, by proximity —
// and re-lay-out with animation when the axis changes. Each axis is a pure
// function from `NodeResponse[]` to ordered lanes, so it's unit-testable and
// the component stays a thin renderer.

import type { NodeResponse } from "../model/horizontalTypes";
import { getHMeta } from "../model/horizontalTypes";

export type GroupAxis = "type" | "cost" | "proximity";

export interface CollectionLane {
  /** Stable key for React + animation identity. */
  key: string;
  /** Human label shown as the lane heading. */
  label: string;
  items: NodeResponse[];
}

export const GROUP_AXES: ReadonlyArray<{ id: GroupAxis; label: string }> = [
  { id: "type", label: "Type" },
  { id: "cost", label: "Cost" },
  { id: "proximity", label: "Proximity" },
];

// ── Axis: type ────────────────────────────────────────────────────────────
// Fold the graph's granular node types into the traveler-facing lanes they
// listed: things to do, places to eat, places to stay, ways to travel, notes.
const TYPE_LANE: Record<string, { key: string; label: string }> = {
  experience: { key: "do", label: "Things to do" },
  free_time: { key: "do", label: "Things to do" },
  waiting: { key: "do", label: "Things to do" },
  meal: { key: "eat", label: "Places to eat" },
  hotel: { key: "stay", label: "Places to stay" },
  flight: { key: "travel", label: "Getting there" },
  transit: { key: "travel", label: "Getting there" },
  subway: { key: "travel", label: "Getting there" },
  train: { key: "travel", label: "Getting there" },
  drive: { key: "travel", label: "Getting there" },
  walk: { key: "travel", label: "Getting there" },
  boat: { key: "travel", label: "Getting there" },
  destination: { key: "places", label: "Places" },
  article: { key: "reading", label: "Reading list" },
  note: { key: "notes", label: "Notes" },
};
const TYPE_LANE_ORDER = ["do", "eat", "stay", "travel", "places", "reading", "notes", "other"];
const TYPE_LANE_FALLBACK = { key: "other", label: "Other" };

// ── Axis: cost ────────────────────────────────────────────────────────────
// Currency-agnostic tiers (amounts across providers are close enough in scale
// for a wish-list glance; the exact number lives on the card). "No price"
// (notes, links, price-less places) sorts last.
interface CostTier {
  key: string;
  label: string;
  max: number;
}
const COST_TIERS: readonly CostTier[] = [
  { key: "c0", label: "Under 1k", max: 1_000 },
  { key: "c1", label: "1k – 5k", max: 5_000 },
  { key: "c2", label: "5k – 20k", max: 20_000 },
  { key: "c3", label: "20k+", max: Infinity },
];
const COST_NONE = { key: "cnone", label: "No price" };

function costAmount(node: NodeResponse): number | null {
  const raw = node.cost_amount;
  if (raw === null || raw === undefined) return null;
  const n = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(n) ? n : null;
}

function costTierFor(amount: number): CostTier {
  // Non-null asserted via the guaranteed Infinity-max final tier.
  return COST_TIERS.find((t) => amount < t.max) ?? COST_TIERS[COST_TIERS.length - 1]!;
}

// ── Axis: proximity ───────────────────────────────────────────────────────
// Cluster by a coarse ~0.5° lat/lng cell so nearby saves (a Kyoto dinner and a
// Kyoto ryokan) land together. Labelled by the first item's place name in the
// cell; items with no coordinates sort last under "No location".
const PROX_CELL = 0.5;
const PROX_NONE = { key: "pnone", label: "No location" };

function proximityCell(node: NodeResponse): { key: string; label: string } | null {
  const loc = getHMeta(node).location;
  if (!loc || typeof loc.lat !== "number" || typeof loc.lng !== "number") return null;
  const latCell = Math.round(loc.lat / PROX_CELL) * PROX_CELL;
  const lngCell = Math.round(loc.lng / PROX_CELL) * PROX_CELL;
  const key = `p:${latCell.toFixed(1)},${lngCell.toFixed(1)}`;
  const label = loc.label ?? `Near ${latCell.toFixed(1)}, ${lngCell.toFixed(1)}`;
  return { key, label };
}

// ── Grouping ──────────────────────────────────────────────────────────────

/**
 * Slice Collection `items` into ordered lanes along `axis`. Empty lanes are
 * omitted; item order within a lane is preserved from the input.
 */
export function groupCollection(items: NodeResponse[], axis: GroupAxis): CollectionLane[] {
  const buckets = new Map<string, CollectionLane>();
  // Preserve first-seen lane order as a tiebreak, then apply axis-specific sort.
  const order: string[] = [];

  const put = (key: string, label: string, node: NodeResponse) => {
    let lane = buckets.get(key);
    if (!lane) {
      lane = { key, label, items: [] };
      buckets.set(key, lane);
      order.push(key);
    }
    lane.items.push(node);
  };

  for (const node of items) {
    if (axis === "type") {
      const lane = TYPE_LANE[node.type] ?? TYPE_LANE_FALLBACK;
      put(lane.key, lane.label, node);
    } else if (axis === "cost") {
      const amount = costAmount(node);
      const lane = amount === null ? COST_NONE : costTierFor(amount);
      put(lane.key, lane.label, node);
    } else {
      const cell = proximityCell(node) ?? PROX_NONE;
      put(cell.key, cell.label, node);
    }
  }

  const lanes = [...buckets.values()];
  lanes.sort((a, b) => laneRank(axis, a.key) - laneRank(axis, b.key) || order.indexOf(a.key) - order.indexOf(b.key));
  return lanes;
}

function laneRank(axis: GroupAxis, key: string): number {
  if (axis === "type") {
    const i = TYPE_LANE_ORDER.indexOf(key);
    return i === -1 ? TYPE_LANE_ORDER.length : i;
  }
  if (axis === "cost") {
    if (key === COST_NONE.key) return COST_TIERS.length; // "No price" last
    return COST_TIERS.findIndex((t) => t.key === key);
  }
  // proximity: keep first-seen order, but "No location" always last.
  return key === PROX_NONE.key ? Number.MAX_SAFE_INTEGER : 0;
}
