import {
  type EdgeResponse,
  type NodeResponse,
  NODE_TYPE_ORDER,
  getMeta,
} from "../_lib/types";

export const COL_WIDTH = 248;
export const COL_GAP = 40;
export const PAD_X = 32;
export const PAD_Y = 32;
export const CARD_HEIGHT = 140;
export const CARD_GAP = 16;
export const ALT_OFFSET_X = -10;
export const ALT_OFFSET_Y = 44;
export const DAY_HEADER_HEIGHT = 36;

export interface PositionedNode {
  node: NodeResponse;
  x: number;
  y: number;
  w: number;
  h: number;
  dayIndex: number;
  slot: number;
  altIndex: number;
  hidden: boolean;
}

export interface LayoutResult {
  positions: Map<string, PositionedNode>;
  dayIndices: number[];
  width: number;
  height: number;
}

// Build a map from alt-sibling -> canonical primary node id. We treat an
// `alternative_to` edge "A -> B" as "A is an alternative to B". Multiple
// siblings can point at the same canonical.
function buildAltMap(edges: EdgeResponse[]): Map<string, string> {
  const altMap = new Map<string, string>();
  for (const edge of edges) {
    if (edge.type === "alternative_to") {
      altMap.set(edge.from_node_id, edge.to_node_id);
    }
  }
  return altMap;
}

// Layout:
// - Each day_index becomes a column.
// - Within a column, nodes stack vertically ordered by (type priority, rank).
// - Alt siblings render offset from their canonical (right-down fan).
// - parent_subgraph_id nodes are hidden from the top-level layout (rendered
//   via NodeDetailSheet when opening their parent).
export function computeLayout(
  nodes: NodeResponse[],
  edges: EdgeResponse[],
): LayoutResult {
  const topLevel = nodes.filter((n) => n.parent_subgraph_id === null);
  const altMap = buildAltMap(edges);

  const byDay = new Map<number, NodeResponse[]>();
  for (const n of topLevel) {
    const meta = getMeta(n);
    const day = typeof meta.day_index === "number" ? meta.day_index : 0;
    const arr = byDay.get(day) ?? [];
    arr.push(n);
    byDay.set(day, arr);
  }

  const dayIndices = Array.from(byDay.keys()).sort((a, b) => a - b);
  const positions = new Map<string, PositionedNode>();
  let maxHeight = 0;

  for (const day of dayIndices) {
    const dayCol = dayIndices.indexOf(day);
    const baseX = PAD_X + dayCol * (COL_WIDTH + COL_GAP);
    const baseY = PAD_Y + DAY_HEADER_HEIGHT;

    const inDay = byDay.get(day) ?? [];

    // Split primaries (not alts) vs alt siblings.
    const primaries = inDay.filter((n) => !altMap.has(n.id));
    const alts = inDay.filter((n) => altMap.has(n.id));

    primaries.sort((a, b) => {
      const pa = NODE_TYPE_ORDER[a.type];
      const pb = NODE_TYPE_ORDER[b.type];
      if (pa !== pb) return pa - pb;
      const ra = getMeta(a).rank ?? 0;
      const rb = getMeta(b).rank ?? 0;
      return ra - rb;
    });

    let slotIdx = 0;
    for (const primary of primaries) {
      const x = baseX;
      const y = baseY + slotIdx * (CARD_HEIGHT + CARD_GAP);
      positions.set(primary.id, {
        node: primary,
        x,
        y,
        w: COL_WIDTH,
        h: CARD_HEIGHT,
        dayIndex: day,
        slot: slotIdx,
        altIndex: 0,
        hidden: false,
      });
      slotIdx++;
      maxHeight = Math.max(maxHeight, y + CARD_HEIGHT);
    }

    // Group alt siblings by their canonical target.
    const altsByTarget = new Map<string, NodeResponse[]>();
    for (const alt of alts) {
      const target = altMap.get(alt.id);
      if (!target) continue;
      const arr = altsByTarget.get(target) ?? [];
      arr.push(alt);
      altsByTarget.set(target, arr);
    }

    for (const [target, siblings] of altsByTarget.entries()) {
      const primaryPos = positions.get(target);
      if (!primaryPos) continue;
      siblings.sort((a, b) => (getMeta(a).rank ?? 0) - (getMeta(b).rank ?? 0));
      siblings.forEach((alt, i) => {
        const altIndex = i + 1;
        const x = primaryPos.x + altIndex * ALT_OFFSET_X;
        const y = primaryPos.y + altIndex * ALT_OFFSET_Y;
        positions.set(alt.id, {
          node: alt,
          x,
          y,
          w: COL_WIDTH,
          h: CARD_HEIGHT,
          dayIndex: day,
          slot: primaryPos.slot,
          altIndex,
          hidden: false,
        });
        maxHeight = Math.max(maxHeight, y + CARD_HEIGHT);
      });
    }
  }

  const width = PAD_X * 2 + dayIndices.length * (COL_WIDTH + COL_GAP) - COL_GAP;
  const height = maxHeight + PAD_Y;

  return { positions, dayIndices, width, height };
}

// Given a PositionedNode, return the anchor point on its edge closest to
// `target` (another PositionedNode). Used to draw SVG paths that connect
// the nearest sides rather than the centers.
export function edgeAnchor(
  from: PositionedNode,
  to: PositionedNode,
): { fromPoint: [number, number]; toPoint: [number, number] } {
  const fromCX = from.x + from.w / 2;
  const fromCY = from.y + from.h / 2;
  const toCX = to.x + to.w / 2;
  const toCY = to.y + to.h / 2;
  const dx = toCX - fromCX;
  const dy = toCY - fromCY;

  if (Math.abs(dx) >= Math.abs(dy)) {
    const fromPoint: [number, number] = dx >= 0
      ? [from.x + from.w, fromCY]
      : [from.x, fromCY];
    const toPoint: [number, number] = dx >= 0
      ? [to.x, toCY]
      : [to.x + to.w, toCY];
    return { fromPoint, toPoint };
  }
  const fromPoint: [number, number] = dy >= 0
    ? [fromCX, from.y + from.h]
    : [fromCX, from.y];
  const toPoint: [number, number] = dy >= 0
    ? [toCX, to.y]
    : [toCX, to.y + to.h];
  return { fromPoint, toPoint };
}

export function bezierPath(
  from: [number, number],
  to: [number, number],
): string {
  const [fx, fy] = from;
  const [tx, ty] = to;
  const dx = tx - fx;
  const horizontal = Math.abs(dx) > Math.abs(ty - fy);
  if (horizontal) {
    const cpx = Math.max(48, Math.abs(dx) * 0.45);
    return `M ${fx} ${fy} C ${fx + cpx} ${fy}, ${tx - cpx} ${ty}, ${tx} ${ty}`;
  }
  const cpy = Math.max(40, Math.abs(ty - fy) * 0.5);
  return `M ${fx} ${fy} C ${fx} ${fy + cpy}, ${tx} ${ty - cpy}, ${tx} ${ty}`;
}
