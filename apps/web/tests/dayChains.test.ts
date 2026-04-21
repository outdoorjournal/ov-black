import { expect, test } from "vitest";

import type { EdgeResponse, NodeResponse } from "@ov-black/api-client";

import { buildDayChains } from "@/app/itinerary/[id]/_components/dayChains";

function node(id: string): NodeResponse {
  return {
    id,
    itinerary_id: "itin-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "approved",
    title: `Node ${id}`,
    source: null,
    source_id: null,
    metadata: {},
  };
}

function edge(
  id: string,
  from: string,
  to: string,
  type: EdgeResponse["type"] = "follows",
): EdgeResponse {
  return {
    id,
    itinerary_id: "itin-1",
    from_node_id: from,
    to_node_id: to,
    type,
    metadata: {},
  };
}

test("(a) two days of 3+1 nodes connected by follows edges returns two groups in emission order", () => {
  const nodes = [node("a1"), node("a2"), node("a3"), node("b1")];
  const edges = [edge("e1", "a1", "a2"), edge("e2", "a2", "a3")];

  const result = buildDayChains(nodes, edges);

  expect(result).toHaveLength(2);
  expect(result[0]!.dayIndex).toBe(0);
  expect(result[0]!.nodes.map((n) => n.id)).toEqual(["a1", "a2", "a3"]);
  expect(result[1]!.dayIndex).toBe(1);
  expect(result[1]!.nodes.map((n) => n.id)).toEqual(["b1"]);
});

test("(b) grouped_with edge between nodes in different chains does NOT merge the chains", () => {
  const nodes = [node("a1"), node("a2"), node("b1"), node("b2")];
  const edges = [
    edge("e1", "a1", "a2"),
    edge("e2", "b1", "b2"),
    edge("e3", "a2", "b1", "grouped_with"),
  ];

  const result = buildDayChains(nodes, edges);

  expect(result).toHaveLength(2);
  expect(result[0]!.nodes.map((n) => n.id)).toEqual(["a1", "a2"]);
  expect(result[1]!.nodes.map((n) => n.id)).toEqual(["b1", "b2"]);
});

test("(c) orphan node with no edges appears as a single-node day", () => {
  const nodes = [node("a1"), node("a2"), node("z9")];
  const edges = [edge("e1", "a1", "a2")];

  const result = buildDayChains(nodes, edges);

  expect(result).toHaveLength(2);
  expect(result[0]!.nodes.map((n) => n.id)).toEqual(["a1", "a2"]);
  expect(result[1]!.nodes.map((n) => n.id)).toEqual(["z9"]);
});

test("(d) empty input returns []", () => {
  expect(buildDayChains([], [])).toEqual([]);
});
