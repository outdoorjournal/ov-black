import type { EdgeResponse, NodeResponse } from "@ov-black/api-client";

export type DayChain = { dayIndex: number; nodes: NodeResponse[] };

export function buildDayChains(
  nodes: NodeResponse[],
  edges: EdgeResponse[],
): DayChain[] {
  if (nodes.length === 0) return [];

  const byId = new Map<string, NodeResponse>(nodes.map((n) => [n.id, n]));
  const follows = edges.filter((e) => e.type === "follows");
  const next = new Map<string, string>();
  const hasIncoming = new Set<string>();
  for (const e of follows) {
    if (!byId.has(e.from_node_id) || !byId.has(e.to_node_id)) continue;
    if (!next.has(e.from_node_id)) next.set(e.from_node_id, e.to_node_id);
    hasIncoming.add(e.to_node_id);
  }

  const heads = nodes
    .filter((n) => !hasIncoming.has(n.id))
    .map((n) => n.id)
    .sort();

  const chains: NodeResponse[][] = [];
  const visited = new Set<string>();
  for (const headId of heads) {
    const chain: NodeResponse[] = [];
    let cur: string | undefined = headId;
    while (cur && !visited.has(cur) && byId.has(cur)) {
      visited.add(cur);
      chain.push(byId.get(cur)!);
      cur = next.get(cur);
    }
    if (chain.length > 0) chains.push(chain);
  }

  const orphans = nodes
    .filter((n) => !visited.has(n.id))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  for (const o of orphans) chains.push([o]);

  return chains.map((c, i) => ({ dayIndex: i, nodes: c }));
}
