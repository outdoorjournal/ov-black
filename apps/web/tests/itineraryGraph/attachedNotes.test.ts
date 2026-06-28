// The attached-notes grouping helper: notes carrying `attached_to_node_id`
// (0014) ride their host and are surfaced as a per-host badge + detail list,
// never as their own timeline card.

import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import { attachedNotesByHost } from "@/app/_components/itinerary-graph/shared/attachedNotes";

function node(p: Partial<NodeResponse> & { id: string }): NodeResponse {
  return {
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "proposed",
    title: "",
    source: null,
    source_id: null,
    metadata: {},
    ...p,
  };
}

describe("attachedNotesByHost", () => {
  test("groups attached notes by host, in order", () => {
    const map = attachedNotesByHost([
      node({ id: "host" }),
      node({ id: "n1", type: "note", title: "why 1:30?", attached_to_node_id: "host" }),
      node({ id: "n2", type: "note", title: "and dinner?", attached_to_node_id: "host" }),
    ]);
    expect(map.get("host")?.map((n) => n.title)).toEqual(["why 1:30?", "and dinner?"]);
    expect(map.size).toBe(1);
  });

  test("ignores free-standing notes and non-note nodes", () => {
    const map = attachedNotesByHost([
      node({ id: "free", type: "note", title: "dinner?", metadata: { start_time: "x" } }),
      node({ id: "exp", type: "experience" }),
    ]);
    expect(map.size).toBe(0);
  });
});
