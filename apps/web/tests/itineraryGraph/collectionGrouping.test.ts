// Pure grouping of the Collection (wish list) along the switchable axes.
// Type folds granular node types into traveler-facing lanes; cost buckets by
// amount with "No price" last; proximity clusters coordinates with "No
// location" last.

import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import { groupCollection } from "@/app/_components/itinerary-graph/collection/grouping";

function node(id: string, over: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: {},
    ...over,
  };
}

describe("groupCollection · type", () => {
  test("folds node types into ordered traveler lanes", () => {
    const items = [
      node("m", { type: "meal" }),
      node("h", { type: "hotel" }),
      node("e", { type: "experience" }),
      node("f", { type: "flight" }),
      node("n", { type: "note" }),
    ];
    const lanes = groupCollection(items, "type");
    expect(lanes.map((l) => l.key)).toEqual(["do", "eat", "stay", "travel", "notes"]);
    expect(lanes.find((l) => l.key === "eat")?.items.map((i) => i.id)).toEqual(["m"]);
  });

  test("collapses several types into one lane", () => {
    const items = [
      node("e1", { type: "experience" }),
      node("ft", { type: "free_time" }),
      node("tr", { type: "train" }),
      node("fl", { type: "flight" }),
    ];
    const lanes = groupCollection(items, "type");
    expect(lanes.find((l) => l.key === "do")?.items).toHaveLength(2);
    expect(lanes.find((l) => l.key === "travel")?.items).toHaveLength(2);
  });
});

describe("groupCollection · cost", () => {
  test("buckets by amount, ascending, with No price last", () => {
    const items = [
      node("cheap", { cost_amount: "400", cost_currency: "USD" }),
      node("mid", { cost_amount: "3000", cost_currency: "USD" }),
      node("dear", { cost_amount: "50000", cost_currency: "USD" }),
      node("free", {}),
    ];
    const lanes = groupCollection(items, "cost");
    expect(lanes.map((l) => l.label)).toEqual([
      "Under 1k",
      "1k – 5k",
      "20k+",
      "No price",
    ]);
  });
});

describe("groupCollection · proximity", () => {
  test("clusters nearby coordinates and sinks the un-located last", () => {
    const kyotoA = { location: { lat: 35.01, lng: 135.76, label: "Kyoto" } };
    const kyotoB = { location: { lat: 35.02, lng: 135.77 } };
    const tokyo = { location: { lat: 35.68, lng: 139.69, label: "Tokyo" } };
    const items = [
      node("ka", { metadata: kyotoA }),
      node("kb", { metadata: kyotoB }),
      node("t", { metadata: tokyo }),
      node("none", {}),
    ];
    const lanes = groupCollection(items, "proximity");
    // Kyoto A + B share a ~0.5° cell; Tokyo is its own; un-located is last.
    const kyotoLane = lanes.find((l) => l.items.some((i) => i.id === "ka"));
    expect(kyotoLane?.items.map((i) => i.id).sort()).toEqual(["ka", "kb"]);
    expect(lanes[lanes.length - 1]?.label).toBe("No location");
  });
});

test("empty input yields no lanes", () => {
  expect(groupCollection([], "type")).toEqual([]);
});
