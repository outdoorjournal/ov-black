// Unit tests for toJournalDiff — the Journal's unified fork-vs-trunk diff
// derivation (traveler-journal design, phase 4). Pins the union sequencing:
// fork nodes ordered by the fork's timing, GHOST rows for trunk-only
// ("removed") nodes interleaved at their trunk time, per-node annotations
// keyed by the rendered node id, and the divergence counts/summary the rail's
// idle state reads. Plus the pure field-level before/after helpers.

import { describe, expect, test } from "vitest";

import type {
  ForkDiffResponse,
  NodeChangeResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { JournalDaySection } from "@/app/_components/itinerary-graph/views/journal/toJournal";
import {
  GHOST_ID_PREFIX,
  changedFieldRows,
  diffSummaryOf,
  ghostIdOf,
  isGhostId,
  movedTimeLabels,
  toJournalDiff,
} from "@/app/_components/itinerary-graph/views/journal/toJournalDiff";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const TZ = 9;

function node(
  id: string,
  startTime: string | null,
  overrides: Partial<NodeResponse> & { duration_minutes?: number } = {},
): NodeResponse {
  const { duration_minutes = 60, metadata, ...rest } = overrides;
  return {
    id,
    itinerary_id: "it-fork",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: {
      ...(startTime ? { start_time: startTime, duration_minutes } : {}),
      ...(metadata ?? {}),
    },
    ...rest,
  } as NodeResponse;
}

function change(
  changeId: string,
  overrides: Partial<NodeChangeResponse> = {},
): NodeChangeResponse {
  return { change_id: changeId, kind: "changed", ...overrides };
}

function diffOf(parts: Partial<ForkDiffResponse> = {}): ForkDiffResponse {
  return {
    fork_id: "it-fork",
    baseline_id: "it-1",
    added: [],
    removed: [],
    changed: [],
    moved: [],
    ...parts,
  } as ForkDiffResponse;
}

const DAYS = [{ date: "2024-06-20", label: "Day 1" }];

function derive(nodes: NodeResponse[], diff: ForkDiffResponse, days = DAYS) {
  return toJournalDiff({
    nodes,
    edges: [],
    days,
    timezoneOffsetHours: TZ,
    diff,
  });
}

function firstDay(view: ReturnType<typeof derive>): JournalDaySection {
  const section = view.journal.sections.find(
    (s): s is JournalDaySection => s.kind === "day",
  );
  if (!section) throw new Error("no day section");
  return section;
}

/** The day's card rows in spine order: `node:<id>` / `ghost:<id>`. */
function rowIds(section: JournalDaySection): string[] {
  return section.entries
    .filter((e) => e.kind === "node" || e.kind === "ghost")
    .map((e) => (e.kind === "node" ? `node:${e.node.id}` : `row-${e.node.id}`));
}

// ── Annotations ───────────────────────────────────────────────────────────────
describe("annotations", () => {
  test("added / changed / moved key off the FORK node id", () => {
    const nodes = [
      node("n-add", "2024-06-20T09:00:00+09:00"),
      node("n-chg", "2024-06-20T13:00:00+09:00"),
      node("n-mov", "2024-06-20T16:00:00+09:00"),
    ];
    const view = derive(
      nodes,
      diffOf({
        added: [change("c-add", { kind: "added", fork_node_id: "n-add" })],
        changed: [
          change("c-chg", {
            fork_node_id: "n-chg",
            baseline_node_id: "b-chg",
            fields: ["title"],
          }),
        ],
        moved: [
          change("c-mov", {
            kind: "moved",
            fork_node_id: "n-mov",
            baseline_node_id: "b-mov",
            fields: ["position"],
          }),
        ],
      }),
    );
    expect(view.annotations.get("n-add")?.kind).toBe("added");
    expect(view.annotations.get("n-chg")?.kind).toBe("changed");
    expect(view.annotations.get("n-mov")?.kind).toBe("moved");
    expect(view.annotations.get("n-chg")?.change.change_id).toBe("c-chg");
  });

  test("where the versions agree, nothing is annotated", () => {
    const nodes = [
      node("n-same", "2024-06-20T09:00:00+09:00"),
      node("n-chg", "2024-06-20T13:00:00+09:00"),
    ];
    const view = derive(
      nodes,
      diffOf({
        changed: [change("c-chg", { fork_node_id: "n-chg" })],
      }),
    );
    expect(view.annotations.has("n-same")).toBe(false);
    expect(view.annotations.size).toBe(1);
  });
});

// ── Ghosts (removed → trunk-only rows) ────────────────────────────────────────
describe("ghost rows", () => {
  const removedChange = change("c-rem", {
    kind: "removed",
    baseline_node_id: "b-rem",
    before: {
      id: "b-rem",
      type: "meal",
      status: "pending",
      title: "Tea house",
      metadata: {
        start_time: "2024-06-20T10:30:00+09:00",
        duration_minutes: 60,
      },
    },
  });

  test("a removed node becomes a ghost entry at its TRUNK time, between the fork's cards", () => {
    const nodes = [
      node("n-a", "2024-06-20T09:00:00+09:00"),
      node("n-b", "2024-06-20T13:00:00+09:00"),
    ];
    const view = derive(nodes, diffOf({ removed: [removedChange] }));

    const ghostId = ghostIdOf("c-rem");
    expect(ghostId).toBe(`${GHOST_ID_PREFIX}c-rem`);
    expect(isGhostId(ghostId)).toBe(true);

    // Union order: fork 09:00 · ghost 10:30 · fork 13:00.
    expect(rowIds(firstDay(view))).toEqual([
      "node:n-a",
      `row-${ghostId}`,
      "node:n-b",
    ]);

    const ghost = view.ghosts.get(ghostId);
    expect(ghost?.title).toBe("Tea house");
    expect(ghost?.type).toBe("meal");
    expect(view.annotations.get(ghostId)?.kind).toBe("removed");
    expect(view.annotations.get(ghostId)?.change.change_id).toBe("c-rem");
  });

  test("the ghost falls back to the snapshot's starts_at when the metadata has no start_time", () => {
    const c = change("c-rem2", {
      kind: "removed",
      baseline_node_id: "b-rem2",
      before: {
        title: "Late walk",
        type: "experience",
        status: "pending",
        starts_at: "2024-06-20T18:00:00+09:00",
        duration_minutes: 30,
        metadata: {},
      },
    });
    const view = derive(
      [node("n-a", "2024-06-20T09:00:00+09:00")],
      diffOf({ removed: [c] }),
    );
    expect(rowIds(firstDay(view))).toEqual([
      "node:n-a",
      `row-${ghostIdOf("c-rem2")}`,
    ]);
  });

  test("an unscheduled removed node (incl. a synthesized start) never reaches the spine but still counts", () => {
    const synth = change("c-rem3", {
      kind: "removed",
      before: {
        title: "Wish",
        type: "experience",
        status: "pending",
        metadata: {
          start_time: "2024-06-20T08:00:00+09:00",
          start_synthesized: true,
        },
      },
    });
    const timeless = change("c-rem4", {
      kind: "removed",
      before: { title: "Idea", type: "experience", status: "pending", metadata: {} },
    });
    const view = derive(
      [node("n-a", "2024-06-20T09:00:00+09:00")],
      diffOf({ removed: [synth, timeless] }),
    );
    expect(rowIds(firstDay(view))).toEqual(["node:n-a"]);
    expect(view.counts.removed).toBe(2);
    expect(view.summary).toBe("2 removals");
  });
});

// ── Counts + summary ──────────────────────────────────────────────────────────
describe("divergence summary", () => {
  test("counts every change in the response and reads like a sentence", () => {
    const view = derive(
      [node("n-a", "2024-06-20T09:00:00+09:00")],
      diffOf({
        added: [
          change("c1", { kind: "added", fork_node_id: "x1" }),
          change("c2", { kind: "added", fork_node_id: "x2" }),
        ],
        removed: [change("c3", { kind: "removed" })],
        changed: [change("c4", { fork_node_id: "x3" })],
        moved: [change("c5", { kind: "moved", fork_node_id: "x4" })],
      }),
    );
    expect(view.counts).toEqual({ added: 2, removed: 1, changed: 1, moved: 1 });
    expect(view.total).toBe(5);
    expect(view.summary).toBe("2 additions, 1 removal, 1 change, 1 move");
  });

  test("an empty diff summarizes to nothing", () => {
    expect(diffSummaryOf({ added: 0, removed: 0, changed: 0, moved: 0 })).toBe(
      "",
    );
    const view = derive(
      [node("n-a", "2024-06-20T09:00:00+09:00")],
      diffOf(),
    );
    expect(view.total).toBe(0);
    expect(view.summary).toBe("");
  });
});

// ── Field-level before/after ──────────────────────────────────────────────────
describe("changedFieldRows", () => {
  test("maps the changed-field names to labelled before/after rows, skipping position + metadata", () => {
    const c = change("c-chg", {
      fields: ["title", "cost_amount", "position", "metadata"],
      before: { title: "Old tea", cost_amount: "120.00", metadata: {} },
      after: { title: "New tea", cost_amount: "180.00", metadata: { x: 1 } },
    });
    const rows = changedFieldRows(c, TZ);
    expect(rows.map((r) => r.field)).toEqual(["title", "cost_amount"]);
    expect(rows[0]).toMatchObject({
      label: "Title",
      before: "Old tea",
      after: "New tea",
    });
    expect(rows[1]).toMatchObject({
      label: "Price",
      before: "120.00",
      after: "180.00",
    });
  });

  test("starts_at renders as a readable local time (snapshot starts_at or metadata.start_time)", () => {
    const c = change("c-chg", {
      fields: ["starts_at"],
      before: { starts_at: "2024-06-20T10:00:00+09:00", metadata: {} },
      after: {
        metadata: { start_time: "2024-06-21T15:30:00+09:00" },
      },
    });
    const rows = changedFieldRows(c, TZ);
    expect(rows[0]?.before).toBe("Jun 20 · 10:00");
    expect(rows[0]?.after).toBe("Jun 21 · 15:30");
  });

  test("a missing side reads as an em dash / unscheduled", () => {
    const c = change("c-chg", {
      fields: ["title", "starts_at"],
      after: { title: "Only after", metadata: {} },
    });
    const rows = changedFieldRows(c, TZ);
    expect(rows[0]).toMatchObject({ before: "—", after: "Only after" });
    expect(rows[1]).toMatchObject({ before: "—", after: "unscheduled" });
  });
});

describe("movedTimeLabels", () => {
  test("reads the trunk slot vs the fork slot", () => {
    const c = change("c-mov", {
      kind: "moved",
      before: { starts_at: "2024-06-20T10:00:00+09:00", metadata: {} },
      after: { starts_at: "2024-06-20T16:15:00+09:00", metadata: {} },
    });
    expect(movedTimeLabels(c, TZ)).toEqual({
      before: "Jun 20 · 10:00",
      after: "Jun 20 · 16:15",
    });
  });
});
