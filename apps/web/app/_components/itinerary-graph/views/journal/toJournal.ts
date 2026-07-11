// toJournal — the Journal's narrative layout derivation (traveler-journal
// design, phase 1). Pure and view-free: it turns `ItineraryTimeline` output
// (the adapter's day scaffold + resolved nodes) into the event-proportional
// sequence the Journal renders — day groups, bucketed gaps (short gap = plain
// spine segment; long gap = a virtual "quiet moment" node), night treatment
// (driven by `night_bar` metadata), multi-day empty spans collapsed into
// elision markers, and alternative-group awareness (grouping data only; the
// fork-in-the-spine rendering is a later phase).
//
// Everything virtual here (quiet moments, nights, elisions) is DERIVED — the
// Journal is a view over the graph, never a parallel store, and nothing
// virtual is ever persisted (mirrors the collection/wishlist precedent).

import { offsetHoursOr, parseIso } from "../../model/time";
import type { EdgeResponse, NodeResponse } from "../../model/types";
import { getVerticalMeta } from "../../model/types";
import { dayKeyForNode } from "../../shared/groupNodesByDay";
import { subgraphChildrenByParent, subgraphDayMeta } from "../../shared/subgraph";

// ── Bucketing thresholds ──────────────────────────────────────────────────────
/** Below this a gap is invisible — the spine simply continues. */
export const SHORT_GAP_MIN = 25;
/** At or above this a gap becomes a virtual "quiet moment" node (~2h). */
export const LONG_GAP_MIN = 120;
/** Consecutive empty days collapse into one elision marker at this run length. */
export const ELISION_MIN_DAYS = 2;

export type QuietPeriod = "morning" | "afternoon" | "evening" | "day";

/** This card's position inside a `grouped_with` run — drives the bracket
 *  spanning the group (phase 3). Only runs of ≥2 consecutive cards mark. */
export type GroupedRole = "start" | "mid" | "end";

/** A derived per-day placement of a multi-day card's subgraph child — "day k
 *  of N" of the journey the parent packages. */
export type JourneyBeat = {
  parentId: string;
  parentTitle: string;
  index: number;
  total: number;
};

export type JournalEntry =
  /** A real graph node, rendered as a card on the spine. `groupedWith` marks
   *  membership in a consecutive `grouped_with` run (the bracket). `journey`
   *  marks a derived journey beat (a subgraph child laid onto its day). */
  | {
      kind: "node";
      node: NodeResponse;
      groupedWith?: GroupedRole;
      journey?: JourneyBeat;
    }
  /** DIFF MODE ONLY (toJournalDiff): a trunk-only node — "removed" in this
   *  version — rendered as a ghost card at its trunk time. `toJournal` itself
   *  never emits one; the node is SYNTHESIZED from the diff's `before`
   *  snapshot and never exists in the store. */
  | { kind: "ghost"; node: NodeResponse }
  /** An alternative group ("choose one of these") — members ordered by start
   *  time; rendered as the spine splitting (fork-in-the-spine, phase 3). */
  | { kind: "alt"; groupKey: string; nodes: NodeResponse[] }
  /** A short-but-visible gap: rendered as a plain, slightly longer spine
   *  segment (no marker, no card). */
  | { kind: "gap"; minutes: number }
  /** A long gap: a virtual quiet-moment node (small circle, caption, no card). */
  | {
      kind: "quiet";
      id: string;
      minutes: number;
      period: QuietPeriod;
      caption: string;
    };

export type JournalNight = {
  /** The `night_bar` node bracketing this night (e.g. the hotel stay), when
   *  the graph models one; null renders the generic night treatment. */
  node: NodeResponse | null;
};

export type JournalDaySection = {
  kind: "day";
  /** Local calendar day, YYYY-MM-DD (from the adapter's day scaffold). */
  date: string;
  /** The scaffold's ordinal label ("Day 4"). */
  label: string;
  /** 0-based index into the trip's day scaffold. */
  index: number;
  entries: JournalEntry[];
  /** Night treatment closing this day — present when another day follows. */
  night: JournalNight | null;
};

export type JournalElision = {
  kind: "elision";
  startDate: string;
  endDate: string;
  startLabel: string;
  endLabel: string;
  dayCount: number;
  /** The collapsed days, for the marker's expand affordance. */
  days: Array<{ date: string; label: string; index: number }>;
};

export type JournalSection = JournalDaySection | JournalElision;

export interface Journal {
  sections: JournalSection[];
  /** Real graph nodes on the spine (cards + alternative members). */
  nodeCount: number;
}

export interface ToJournalInput {
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  /** The adapter's contiguous day scaffold (`ItineraryTimeline.days`). */
  days: ReadonlyArray<{ date: string; label: string }>;
  timezoneOffsetHours: number;
}

// ── Node visibility ───────────────────────────────────────────────────────────
// The Journal shows the SCHEDULED story. Excluded:
//   - discarded nodes (history, not narrative),
//   - unscheduled nodes (no real start, or a synthesized layout-only start —
//     those belong to the Collection/wish list),
//   - attached notes (they ride their host in the margin — phase 2 renders
//     them there; putting them on the spine would double-count feedback),
//   - subgraph children (the journey INSIDE a card — they render as the
//     parent's expandable sub-journey, never as spine cards of their own).
function isJournalVisible(node: NodeResponse): boolean {
  if (node.status === "discarded") return false;
  if (node.attached_to_node_id) return false;
  if (node.parent_subgraph_id) return false;
  const meta = getVerticalMeta(node);
  if (meta.start_synthesized === true) return false;
  return typeof meta.start_time === "string" && meta.start_time.length > 0;
}

// ── Alternative groups ────────────────────────────────────────────────────────
// Same derivation the vertical layout uses: explicit `metadata.alt_group` plus
// `alternative_to` edges unioned into one key per group.
function altGroupsOf(
  nodes: NodeResponse[],
  edges: EdgeResponse[],
): Map<string, string> {
  const byId = new Set(nodes.map((n) => n.id));
  const groupByNode = new Map<string, string>();
  for (const n of nodes) {
    const meta = getVerticalMeta(n);
    if (meta.alt_group) groupByNode.set(n.id, meta.alt_group);
  }
  for (const e of edges) {
    if (e.type !== "alternative_to") continue;
    if (!byId.has(e.from_node_id) || !byId.has(e.to_node_id)) continue;
    const groupKey =
      groupByNode.get(e.to_node_id) ??
      groupByNode.get(e.from_node_id) ??
      `alt-${e.to_node_id}`;
    groupByNode.set(e.to_node_id, groupKey);
    groupByNode.set(e.from_node_id, groupKey);
  }
  return groupByNode;
}

// ── grouped_with groups ───────────────────────────────────────────────────────
// Union `grouped_with` edges into one key per group — the "these belong
// together" bracket (never a choice; alternatives are the split).
function groupedWithOf(
  nodes: NodeResponse[],
  edges: EdgeResponse[],
): Map<string, string> {
  const byId = new Set(nodes.map((n) => n.id));
  const groupByNode = new Map<string, string>();
  for (const e of edges) {
    if (e.type !== "grouped_with") continue;
    if (!byId.has(e.from_node_id) || !byId.has(e.to_node_id)) continue;
    const groupKey =
      groupByNode.get(e.to_node_id) ??
      groupByNode.get(e.from_node_id) ??
      `grp-${e.to_node_id}`;
    groupByNode.set(e.to_node_id, groupKey);
    groupByNode.set(e.from_node_id, groupKey);
  }
  return groupByNode;
}

// ── Timing helpers ────────────────────────────────────────────────────────────
/** Absolute start instant (epoch ms) — offsets are baked into the ISO string. */
function startMsOf(node: NodeResponse): number {
  return parseIso(getVerticalMeta(node).start_time ?? "");
}

function endMsOf(node: NodeResponse): number {
  const meta = getVerticalMeta(node);
  const dur =
    typeof meta.duration_minutes === "number" && meta.duration_minutes > 0
      ? meta.duration_minutes
      : 60;
  return parseIso(meta.start_time ?? "") + dur * 60_000;
}

/** Local hour-of-day for an epoch ms, using the reference node's own offset. */
function localHour(ms: number, referenceIso: string, tzDefault: number): number {
  const off = offsetHoursOr(referenceIso, tzDefault);
  const d = new Date(ms + off * 3_600_000);
  return d.getUTCHours() + d.getUTCMinutes() / 60;
}

function quietPeriodForHour(hour: number): Exclude<QuietPeriod, "day"> {
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}

export function quietCaption(period: QuietPeriod): string {
  switch (period) {
    case "morning":
      return "A quiet morning";
    case "afternoon":
      return "A free afternoon";
    case "evening":
      return "An open evening";
    case "day":
      return "An open day";
  }
}

// ── Journey beats (embedded subgraphs laid onto their days) ──────────────────
// A multi-day card (an OV adventure) carries its internal journey as subgraph
// children. The RAW children are never spine-visible; instead, when the parent
// is scheduled, each child is DERIVED onto its calendar day — day k of the
// journey lands on parentDay + (k-1), wearing a membership chip — so the span
// reads across the days it covers. Derived, never persisted (the same rule as
// quiet moments and nights).

const BEAT_DEFAULT_MIN = 6 * 60; // a day-long leg when the vendor gives no hours
const BEAT_START_TIME = "09:00"; // days 2..N start the morning

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function addDaysToKey(dayKey: string, days: number): string {
  const [y, m, d] = dayKey.split("-").map(Number);
  const dt = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1));
  dt.setUTCDate(dt.getUTCDate() + days);
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
}

/** The ISO offset suffix of `iso`, or one built from the trip default. */
function offsetSuffixOf(iso: string, tzDefault: number): string {
  const m = iso.match(/(Z|[+-]\d{2}:\d{2})$/);
  if (m?.[1]) return m[1];
  const sign = tzDefault < 0 ? "-" : "+";
  const abs = Math.abs(tzDefault);
  return `${sign}${pad(Math.floor(abs))}:${pad(Math.round((abs % 1) * 60))}`;
}

function deriveJourneyBeats(
  visibleCards: NodeResponse[],
  allNodes: NodeResponse[],
  tz: number,
): { beats: NodeResponse[]; info: Map<string, JourneyBeat> } {
  const childrenByParent = subgraphChildrenByParent(allNodes);
  const beats: NodeResponse[] = [];
  const info = new Map<string, JourneyBeat>();
  for (const parent of visibleCards) {
    const children = childrenByParent.get(parent.id) ?? [];
    if (children.length === 0) continue;
    const parentStart = getVerticalMeta(parent).start_time;
    if (!parentStart) continue;
    const parentDay = dayKeyForNode(parent, tz);
    if (!parentDay) continue;
    const suffix = offsetSuffixOf(parentStart, tz);
    children.forEach((child, i) => {
      const dayIndex = subgraphDayMeta(child).index ?? i + 1;
      const hours = subgraphDayMeta(child).hours;
      // Day 1 rides the parent's own start instant (the card sorts first on a
      // tie — input order is stable); later days start the morning.
      const start =
        dayIndex <= 1
          ? parentStart
          : `${addDaysToKey(parentDay, dayIndex - 1)}T${BEAT_START_TIME}:00${suffix}`;
      beats.push({
        ...child,
        metadata: {
          ...child.metadata,
          start_time: start,
          duration_minutes:
            typeof hours === "number" && hours > 0
              ? Math.round(hours * 60)
              : BEAT_DEFAULT_MIN,
        },
      } as NodeResponse);
      info.set(child.id, {
        parentId: parent.id,
        parentTitle: parent.title,
        index: dayIndex,
        total: children.length,
      });
    });
  }
  return { beats, info };
}

// ── The derivation ────────────────────────────────────────────────────────────
export function toJournal(input: ToJournalInput): Journal {
  const { nodes, edges, days, timezoneOffsetHours: tz } = input;

  const visible = nodes.filter(isJournalVisible);
  const nightBars = visible.filter((n) => getVerticalMeta(n).night_bar === true);
  const scheduledCards = visible.filter(
    (n) => getVerticalMeta(n).night_bar !== true,
  );
  // Embedded subgraphs: lay each scheduled parent's day children onto their
  // calendar days as derived journey beats (see deriveJourneyBeats above).
  const { beats, info: journeyInfo } = deriveJourneyBeats(scheduledCards, nodes, tz);
  const cards = [...scheduledCards, ...beats];
  const groupByNode = altGroupsOf(cards, edges);
  const groupedByNode = groupedWithOf(cards, edges);

  // Bucket by local calendar day (each node placed by its OWN offset — the
  // trip can span timezones), keeping only days on the scaffold.
  const cardsByDay = new Map<string, NodeResponse[]>();
  for (const n of cards) {
    const key = dayKeyForNode(n, tz);
    if (!key) continue;
    const arr = cardsByDay.get(key) ?? [];
    arr.push(n);
    cardsByDay.set(key, arr);
  }
  const nightByDay = new Map<string, NodeResponse>();
  for (const n of nightBars) {
    const key = dayKeyForNode(n, tz);
    if (key && !nightByDay.has(key)) nightByDay.set(key, n);
  }

  let nodeCount = 0;
  const daySections: JournalDaySection[] = days.map((d, index) => {
    const items = (cardsByDay.get(d.date) ?? [])
      .slice()
      .sort((a, b) => startMsOf(a) - startMsOf(b));

    // Fold alternative-group members into one `alt` entry at the position of
    // the group's earliest member.
    const folded: Array<
      | { kind: "node"; node: NodeResponse; startMs: number; endMs: number }
      | {
          kind: "alt";
          groupKey: string;
          nodes: NodeResponse[];
          startMs: number;
          endMs: number;
        }
    > = [];
    const consumedGroups = new Set<string>();
    for (const node of items) {
      const group = groupByNode.get(node.id);
      if (!group) {
        folded.push({
          kind: "node",
          node,
          startMs: startMsOf(node),
          endMs: endMsOf(node),
        });
        continue;
      }
      if (consumedGroups.has(group)) continue;
      consumedGroups.add(group);
      const members = items.filter((n) => groupByNode.get(n.id) === group);
      folded.push({
        kind: "alt",
        groupKey: group,
        nodes: members,
        startMs: Math.min(...members.map((n) => startMsOf(n))),
        endMs: Math.max(...members.map((n) => endMsOf(n))),
      });
    }

    // Bracket roles: runs of ≥2 CONSECUTIVE folded node entries sharing a
    // `grouped_with` group get start/mid/end marks (the spanning bracket).
    const bracketRoles = new Map<number, GroupedRole>();
    {
      let runKey: string | null = null;
      let runStart = -1;
      const flush = (endExclusive: number) => {
        if (runKey !== null && endExclusive - runStart >= 2) {
          for (let k = runStart; k < endExclusive; k += 1) {
            bracketRoles.set(
              k,
              k === runStart ? "start" : k === endExclusive - 1 ? "end" : "mid",
            );
          }
        }
        runKey = null;
        runStart = -1;
      };
      folded.forEach((f, idx) => {
        const key =
          f.kind === "node" ? (groupedByNode.get(f.node.id) ?? null) : null;
        if (key !== runKey) {
          flush(idx);
          if (key !== null) {
            runKey = key;
            runStart = idx;
          }
        }
      });
      flush(folded.length);
    }

    // Interleave gap buckets between consecutive entries.
    const entries: JournalEntry[] = [];
    let prev: (typeof folded)[number] | null = null;
    for (const [foldIdx, entry] of folded.entries()) {
      if (prev) {
        const gapMin = Math.round((entry.startMs - prev.endMs) / 60_000);
        if (gapMin >= LONG_GAP_MIN) {
          const midMs = prev.endMs + (entry.startMs - prev.endMs) / 2;
          const prevNode = prev.kind === "node" ? prev.node : prev.nodes[0];
          const refIso = prevNode
            ? (getVerticalMeta(prevNode).start_time ?? "")
            : "";
          const period = quietPeriodForHour(localHour(midMs, refIso, tz));
          entries.push({
            kind: "quiet",
            id: `quiet-${d.date}-${entries.length}`,
            minutes: gapMin,
            period,
            caption: quietCaption(period),
          });
        } else if (gapMin >= SHORT_GAP_MIN) {
          entries.push({ kind: "gap", minutes: gapMin });
        }
      }
      if (entry.kind === "node") {
        const role = bracketRoles.get(foldIdx);
        const journey = journeyInfo.get(entry.node.id);
        entries.push({
          kind: "node",
          node: entry.node,
          ...(role ? { groupedWith: role } : {}),
          ...(journey ? { journey } : {}),
        });
        nodeCount += 1;
      } else {
        entries.push({
          kind: "alt",
          groupKey: entry.groupKey,
          nodes: entry.nodes,
        });
        nodeCount += entry.nodes.length;
      }
      prev = entry;
    }

    // A single empty day (not part of an elided run — see below) reads as a
    // virtual open day rather than a hole in the story.
    if (entries.length === 0) {
      entries.push({
        kind: "quiet",
        id: `quiet-${d.date}-open`,
        minutes: 24 * 60,
        period: "day",
        caption: quietCaption("day"),
      });
    }

    const isEmpty = (cardsByDay.get(d.date) ?? []).length === 0;
    const hasNight = nightByDay.has(d.date);
    const night: JournalNight | null =
      index < days.length - 1 && (!isEmpty || hasNight)
        ? { node: nightByDay.get(d.date) ?? null }
        : null;

    return { kind: "day", date: d.date, label: d.label, index, entries, night };
  });

  // A journal with no cards at all is a fresh canvas, not a story with holes:
  // every scaffold day renders as an open day (with its insert affordance)
  // rather than collapsing into one big elision the traveler can't act on.
  if (nodeCount === 0) {
    return { sections: daySections, nodeCount };
  }

  // Collapse runs of ≥ ELISION_MIN_DAYS truly-empty days (no cards, no night
  // node) into elision markers so a 2-month trip doesn't scroll through a wall
  // of open days.
  const isElidable = (s: JournalDaySection): boolean =>
    (cardsByDay.get(s.date) ?? []).length === 0 && !nightByDay.has(s.date);

  const sections: JournalSection[] = [];
  let i = 0;
  while (i < daySections.length) {
    const section = daySections[i];
    if (!section) break;
    if (!isElidable(section)) {
      sections.push(section);
      i += 1;
      continue;
    }
    let j = i;
    while (j < daySections.length) {
      const candidate = daySections[j];
      if (!candidate || !isElidable(candidate)) break;
      j += 1;
    }
    const run = daySections.slice(i, j);
    const first = run[0];
    const last = run[run.length - 1];
    if (run.length >= ELISION_MIN_DAYS && first && last) {
      sections.push({
        kind: "elision",
        startDate: first.date,
        endDate: last.date,
        startLabel: first.label,
        endLabel: last.label,
        dayCount: run.length,
        days: run.map((s) => ({ date: s.date, label: s.label, index: s.index })),
      });
    } else {
      sections.push(...run);
    }
    i = j;
  }

  return { sections, nodeCount };
}
