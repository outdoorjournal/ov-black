// toJournalDiff — the Journal's unified version diff (traveler-journal design,
// phase 4). Pure and view-free: it takes the same inputs as `toJournal` (the
// FORK's graph + day scaffold) plus the G3 `diff_fork` response and derives the
// "tracked changes in a manuscript" sequence:
//
//   · the union of both graphs on ONE spine — fork nodes at the fork's timing,
//     plus GHOST entries for trunk-only ("removed") nodes at their trunk time,
//     synthesized from the diff's `before` snapshots (never persisted, never
//     in the store — the same never-a-parallel-store rule as every other
//     Journal derivation);
//   · per-node annotations (added / changed / moved / removed) keyed by the
//     node id the Journal renders (the fork node id, or the ghost id);
//   · the divergence counts + summary line the rail's idle state reads
//     ("4 additions, 1 change").
//
// Vocabulary guard: version divergence is stitches/ghosts/dots ONLY — the
// spine never splits for a diff (splits mean "choose one", the alternatives
// vocabulary). Two pairings, both this same shape: traveler fork vs trunk,
// advisor reviewing a fork vs trunk. Never three-way — `diff_fork` itself is
// pairwise.

import type { ForkDiffResponse, NodeChangeResponse } from "@ov-black/api-client";

import { formatClock, offsetHoursOr, parseIso } from "../../model/time";
import type { NodeResponse } from "../../model/types";

import { toJournal, type Journal, type ToJournalInput } from "./toJournal";

export type JournalDiffKind = "added" | "removed" | "changed" | "moved";

export type JournalNodeDiff = {
  kind: JournalDiffKind;
  change: NodeChangeResponse;
};

/** Ghost node ids are namespaced so they can never collide with a real node. */
export const GHOST_ID_PREFIX = "ghost:";
export const ghostIdOf = (changeId: string): string =>
  `${GHOST_ID_PREFIX}${changeId}`;
export const isGhostId = (id: string): boolean =>
  id.startsWith(GHOST_ID_PREFIX);

export type JournalDiffCounts = {
  added: number;
  removed: number;
  changed: number;
  moved: number;
};

export interface JournalDiffView {
  /** The unified sequence — render exactly like a Journal; `ghost` entries
   *  are the trunk-only rows. */
  journal: Journal;
  /** node id (fork node id, or ghost id for removed) → its annotation. */
  annotations: Map<string, JournalNodeDiff>;
  /** ghost id → the synthesized trunk-only node (the rail's active lookup —
   *  ghosts never live in the store's `nodes`). */
  ghosts: Map<string, NodeResponse>;
  /** Scaffold dates whose day carries ANY divergence (an annotated card, an
   *  alt member, or a ghost) — the dashed second-thread region cue and the
   *  day rail's divergence dots both read from this one derivation, so the
   *  two surfaces can never disagree. */
  divergedDays: Set<string>;
  counts: JournalDiffCounts;
  /** Total changes in the diff (spine-visible or not). */
  total: number;
  /** "2 additions, 1 change" — empty string when the versions agree. */
  summary: string;
}

export type ToJournalDiffInput = ToJournalInput & { diff: ForkDiffResponse };

// ── Snapshot helpers ──────────────────────────────────────────────────────────
type Snapshot = { [key: string]: unknown } | null | undefined;

function isRecord(v: unknown): v is { [key: string]: unknown } {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function snapStr(snapshot: Snapshot, key: string): string | null {
  const v = snapshot?.[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}

const NODE_STATUSES = new Set([
  "pending",
  "approved",
  "booked",
  "confirmed",
  "discarded",
]);

/**
 * Synthesize the ghost node for a `removed` change from its baseline (`before`)
 * snapshot. Returns null when the snapshot is missing or the trunk node was
 * itself discarded (history, not narrative). The ghost keeps the TRUNK's
 * timing — that is where the union sequence places it; a trunk node that was
 * never scheduled yields a time-less ghost, which the Journal (a view over the
 * SCHEDULED story) simply doesn't put on the spine — it still counts in the
 * divergence summary.
 */
function ghostNodeOf(
  change: NodeChangeResponse,
  itineraryId: string,
): NodeResponse | null {
  const before = change.before ?? null;
  if (!before) return null;
  const status = snapStr(before, "status") ?? "pending";
  if (status === "discarded") return null;

  const rawMeta = before["metadata"];
  const metadata: { [key: string]: unknown } = isRecord(rawMeta)
    ? { ...rawMeta }
    : {};
  // A synthesized start is a layout artifact, not a placement — the trunk node
  // was really unscheduled, so the ghost is too.
  if (metadata["start_synthesized"] === true) {
    delete metadata["start_time"];
    delete metadata["start_synthesized"];
  }
  if (typeof metadata["start_time"] !== "string") {
    const startsAt = snapStr(before, "starts_at");
    if (startsAt) metadata["start_time"] = startsAt;
  }
  if (typeof metadata["duration_minutes"] !== "number") {
    const dur = before["duration_minutes"];
    if (typeof dur === "number") metadata["duration_minutes"] = dur;
  }

  return {
    id: ghostIdOf(change.change_id),
    itinerary_id: itineraryId,
    parent_subgraph_id: null,
    type: (snapStr(before, "type") ?? "experience") as NodeResponse["type"],
    status: (NODE_STATUSES.has(status)
      ? status
      : "pending") as NodeResponse["status"],
    title: snapStr(before, "title") ?? "Untitled",
    source: snapStr(before, "source"),
    source_id: snapStr(before, "source_id"),
    metadata,
  };
}

// ── Summary ───────────────────────────────────────────────────────────────────
function part(n: number, singular: string, plural: string): string | null {
  if (n === 0) return null;
  return `${n} ${n === 1 ? singular : plural}`;
}

export function diffSummaryOf(counts: JournalDiffCounts): string {
  return [
    part(counts.added, "addition", "additions"),
    part(counts.removed, "removal", "removals"),
    part(counts.changed, "change", "changes"),
    part(counts.moved, "move", "moves"),
  ]
    .filter((p): p is string => p !== null)
    .join(", ");
}

// ── The derivation ────────────────────────────────────────────────────────────
export function toJournalDiff(input: ToJournalDiffInput): JournalDiffView {
  const { diff, nodes, ...rest } = input;
  const itineraryId = nodes[0]?.itinerary_id ?? "";

  // Annotations for the fork's own nodes (added / changed / moved).
  const annotations = new Map<string, JournalNodeDiff>();
  const annotate = (kind: JournalDiffKind, changes: NodeChangeResponse[]) => {
    for (const change of changes) {
      if (!change.fork_node_id) continue;
      annotations.set(change.fork_node_id, { kind, change });
    }
  };
  annotate("added", diff.added);
  annotate("changed", diff.changed);
  annotate("moved", diff.moved);

  // Ghosts for the trunk-only nodes (removed), placed by the TRUNK's timing.
  const ghosts = new Map<string, NodeResponse>();
  for (const change of diff.removed) {
    const ghost = ghostNodeOf(change, itineraryId);
    if (!ghost) continue;
    ghosts.set(ghost.id, ghost);
    annotations.set(ghost.id, { kind: "removed", change });
  }

  // One pass through the SAME layout engine over the union — fork nodes at
  // fork timing, ghosts interleaved at trunk timing — then rewrite the ghost
  // rows into their own entry kind (a ghost can never fold into an alt group:
  // no edge references a ghost id).
  const journal = toJournal({ ...rest, nodes: [...nodes, ...ghosts.values()] });
  const sections = journal.sections.map((section) => {
    if (section.kind !== "day") return section;
    return {
      ...section,
      entries: section.entries.map((entry) =>
        entry.kind === "node" && isGhostId(entry.node.id)
          ? ({ kind: "ghost", node: entry.node } as const)
          : entry,
      ),
    };
  });

  // The diverged-day set — one derivation for the second-thread region cue
  // AND the day rail's dots (phase 5), so they always agree.
  const divergedDays = new Set<string>();
  for (const section of sections) {
    if (section.kind !== "day") continue;
    const diverged = section.entries.some(
      (entry) =>
        entry.kind === "ghost" ||
        (entry.kind === "node" && annotations.has(entry.node.id)) ||
        (entry.kind === "alt" &&
          entry.nodes.some((n) => annotations.has(n.id))),
    );
    if (diverged) divergedDays.add(section.date);
  }

  const counts: JournalDiffCounts = {
    added: diff.added.length,
    removed: diff.removed.length,
    changed: diff.changed.length,
    moved: diff.moved.length,
  };
  const total = counts.added + counts.removed + counts.changed + counts.moved;

  return {
    journal: { ...journal, sections },
    annotations,
    ghosts,
    divergedDays,
    counts,
    total,
    summary: diffSummaryOf(counts),
  };
}

// ── Field-level before/after (the rail's "changed" view) ─────────────────────
const FIELD_LABELS: Record<string, string> = {
  title: "Title",
  type: "Type",
  status: "Status",
  cost_amount: "Price",
  cost_currency: "Currency",
  cost_kind: "Price basis",
  starts_at: "Time",
  source: "Source",
  source_id: "Reference",
};

export type DiffFieldRow = {
  field: string;
  label: string;
  before: string;
  after: string;
};

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** "Jun 21 · 09:00" — a snapshot instant in the node's own local clock. */
export function diffTimeLabel(iso: string, tzDefault: number): string {
  const off = offsetHoursOr(iso, tzDefault);
  const d = new Date(parseIso(iso) + off * 3_600_000);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()} · ${formatClock(iso, off)}`;
}

function snapshotTime(snapshot: Snapshot, tzDefault: number): string {
  const meta = snapshot?.["metadata"];
  const iso =
    snapStr(snapshot, "starts_at") ??
    (isRecord(meta) && typeof meta["start_time"] === "string"
      ? meta["start_time"]
      : null);
  return iso ? diffTimeLabel(iso, tzDefault) : "unscheduled";
}

function fieldValue(
  snapshot: Snapshot,
  field: string,
  tzDefault: number,
): string {
  if (!snapshot) return "—";
  if (field === "starts_at") return snapshotTime(snapshot, tzDefault);
  const v = snapshot[field];
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

/**
 * The rail's field-level before/after rows for a `changed` node, from the
 * diff's changed-field names + snapshots. `position` (a pure reorder marker)
 * and `metadata` (an opaque bag — the rail renders a quiet "details updated"
 * line instead) are excluded.
 */
export function changedFieldRows(
  change: NodeChangeResponse,
  tzDefault: number,
): DiffFieldRow[] {
  const fields = (change.fields ?? []).filter(
    (f) => f !== "position" && f !== "metadata",
  );
  return fields.map((field) => ({
    field,
    label: FIELD_LABELS[field] ?? field,
    before: fieldValue(change.before ?? null, field, tzDefault),
    after: fieldValue(change.after ?? null, field, tzDefault),
  }));
}

/** Old vs new time for a `moved` node — trunk's slot vs the fork's. */
export function movedTimeLabels(
  change: NodeChangeResponse,
  tzDefault: number,
): { before: string; after: string } {
  return {
    before: snapshotTime(change.before ?? null, tzDefault),
    after: snapshotTime(change.after ?? null, tzDefault),
  };
}
