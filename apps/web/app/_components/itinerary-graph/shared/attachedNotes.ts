import type { NodeResponse } from "../model/horizontalTypes";

/**
 * Group `note` nodes that annotate a host node, keyed by the host node id.
 *
 * An *attached* note (0014 dual-mode) carries `attached_to_node_id` and no
 * `start_time`, so it never lands on the timeline as its own card — it rides
 * its host. Views use this map to badge a host card with its note count and to
 * list the notes in the host's expanded detail sheet. Free-standing notes
 * (which have their own time) are excluded; they render as ordinary cards.
 */
export function attachedNotesByHost(
  nodes: NodeResponse[],
): Map<string, NodeResponse[]> {
  const map = new Map<string, NodeResponse[]>();
  for (const n of nodes) {
    const host = n.attached_to_node_id;
    if (n.type !== "note" || !host) continue;
    const existing = map.get(host);
    if (existing) existing.push(n);
    else map.set(host, [n]);
  }
  return map;
}
