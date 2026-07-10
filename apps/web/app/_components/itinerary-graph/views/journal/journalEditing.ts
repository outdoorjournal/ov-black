// journalEditing — the Journal's phase-3 editing arithmetic and drop-policy
// (traveler-journal design, "Editing in the Journal"). Pure and view-free so
// vitest can pin the two decisions that matter:
//
//   · WHERE a drop lands in time. The Journal is narrative, not metric — there
//     is no time-pixel math. A drop between A and B assigns a sensible slot
//     time derived from the neighbours (midpoint, snapped), a drop before the
//     first card leads it by an hour, a drop after the last trails it by half
//     an hour, and an empty day defaults to noon.
//
//   · WHAT a drop does. Role (via the existing store selectors) decides:
//     a real editable fork moves the node; the draft-mine preview lazily forks
//     (the store's existing forkAndMove); the official trunk OFFERS the fork
//     ("make this yours?") instead of silently failing; everything else is a
//     no-op with no drag affordance at all.

import { offsetHoursOr, parseIso } from "../../model/time";
import type { NodeResponse } from "../../model/types";
import { getVerticalMeta } from "../../model/types";
import {
  selectEditable,
  selectIsDraftMine,
  selectTravelerEditable,
  type ItineraryGraphState,
} from "../../store/itineraryGraphStore";

import type { JournalEntry } from "./toJournal";

// ── Slot arithmetic ───────────────────────────────────────────────────────────
/** Drops snap to a clean quarter-hour (mirrors the horizontal canvas). */
export const SLOT_SNAP_MIN = 15;
/** A drop before the day's first card leads it by this much. */
export const SLOT_LEAD_MIN = 60;
/** A drop after the day's last card trails it by this much. */
export const SLOT_TRAIL_MIN = 30;
/** An empty day takes its drop at noon. */
export const SLOT_EMPTY_DAY_MIN = 12 * 60;

export function snapMinute(minute: number): number {
  const snapped = Math.round(minute / SLOT_SNAP_MIN) * SLOT_SNAP_MIN;
  return Math.max(0, Math.min(1439, snapped));
}

/**
 * The sensible slot time (minute-of-day) for a drop into the gap between two
 * neighbours. `null` means "no neighbour on that side".
 */
export function slotMinute(
  prevEndMinute: number | null,
  nextStartMinute: number | null,
): number {
  if (prevEndMinute === null && nextStartMinute === null) {
    return SLOT_EMPTY_DAY_MIN;
  }
  if (prevEndMinute === null && nextStartMinute !== null) {
    return snapMinute(nextStartMinute - SLOT_LEAD_MIN);
  }
  if (nextStartMinute === null && prevEndMinute !== null) {
    return snapMinute(prevEndMinute + SLOT_TRAIL_MIN);
  }
  const prev = prevEndMinute as number;
  const next = nextStartMinute as number;
  // Overlapping neighbours: land right at the first card's end.
  if (next <= prev) return snapMinute(prev);
  return snapMinute(prev + (next - prev) / 2);
}

// ── Card bounds along a day ───────────────────────────────────────────────────
export type CardBounds = { startMinute: number; endMinute: number };

function boundsOfNode(node: NodeResponse, tzDefault: number): CardBounds | null {
  const meta = getVerticalMeta(node);
  const start = meta.start_time;
  if (!start) return null;
  // The node's OWN offset (the trip can span timezones), falling back to the
  // trip default — the same rule every other Journal derivation uses.
  const off = offsetHoursOr(start, tzDefault);
  const d = new Date(parseIso(start) + off * 3_600_000);
  const startMinute = d.getUTCHours() * 60 + d.getUTCMinutes();
  const dur =
    typeof meta.duration_minutes === "number" && meta.duration_minutes > 0
      ? meta.duration_minutes
      : 60;
  return { startMinute, endMinute: Math.min(1439, startMinute + dur) };
}

/**
 * The day's card bounds in spine order — one entry per card ROW (an alt group
 * is one row spanning its members). Gaps/quiet moments carry no bounds.
 */
export function cardBoundsOf(
  entries: JournalEntry[],
  tzDefault: number,
): CardBounds[] {
  const out: CardBounds[] = [];
  for (const entry of entries) {
    if (entry.kind === "node") {
      const b = boundsOfNode(entry.node, tzDefault);
      if (b) out.push(b);
    } else if (entry.kind === "alt") {
      const bs = entry.nodes
        .map((n) => boundsOfNode(n, tzDefault))
        .filter((b): b is CardBounds => b !== null);
      if (bs.length > 0) {
        out.push({
          startMinute: Math.min(...bs.map((b) => b.startMinute)),
          endMinute: Math.max(...bs.map((b) => b.endMinute)),
        });
      }
    }
  }
  return out;
}

/**
 * The minute each drop slot assigns, in slot order: before the first card,
 * between each pair, after the last (N cards → N+1 slots; an empty day has
 * exactly one, at noon).
 */
export function dropSlotMinutes(bounds: CardBounds[]): number[] {
  const out: number[] = [];
  for (let i = 0; i <= bounds.length; i += 1) {
    const prev = i > 0 ? (bounds[i - 1]?.endMinute ?? null) : null;
    const next = i < bounds.length ? (bounds[i]?.startMinute ?? null) : null;
    out.push(slotMinute(prev, next));
  }
  return out;
}

/** Where the `+`-on-the-line (a day's end) inserts: after the last card. */
export function endOfDayMinute(bounds: CardBounds[]): number {
  const slots = dropSlotMinutes(bounds);
  return slots[slots.length - 1] ?? SLOT_EMPTY_DAY_MIN;
}

// ── Drop policy — role decides, via the existing selectors ────────────────────
export type JournalDropMode =
  /** A real editable fork (advisor working copy / traveler's version): move. */
  | "move"
  /** Draft-mine preview on the trunk: the FIRST edit lazily forks (existing
   *  `forkAndMove`). */
  | "fork-and-move"
  /** The official trunk: a content drag OFFERS the fork ("make this yours?")
   *  instead of silently 409ing — the working-copy path made legible. */
  | "offer-fork"
  /** No drag affordance at all (no credentials, or the plan is approved). */
  | "none";

export function journalDropMode(s: ItineraryGraphState): JournalDropMode {
  if (selectEditable(s) || selectTravelerEditable(s)) return "move";
  if (selectIsDraftMine(s)) return "fork-and-move";
  const hasCreds = Boolean(s.apiBaseUrl && s.accessToken);
  if (
    hasCreds &&
    !s.sample.itinerary?.forked_from_id &&
    s.status !== "approved"
  ) {
    return "offer-fork";
  }
  return "none";
}

// ── Drag/drop ids — namespaced so they can never collide with another
// DndContext's ids (the known dup-id gotcha across surfaces). ─────────────────
const JOURNAL_DRAG_PREFIX = "journal-node:";
export const journalDragId = (nodeId: string): string =>
  `${JOURNAL_DRAG_PREFIX}${nodeId}`;
export const nodeIdFromJournalDragId = (dragId: string): string =>
  dragId.startsWith(JOURNAL_DRAG_PREFIX)
    ? dragId.slice(JOURNAL_DRAG_PREFIX.length)
    : dragId;
export const journalSlotId = (dayKey: string, index: number): string =>
  `journal-slot:${dayKey}:${index}`;

/** "13:05" — the quiet time label a highlighted drop slot wears. */
export function minuteLabel(minute: number): string {
  const clamped = Math.max(0, Math.min(1439, Math.round(minute)));
  const hh = String(Math.floor(clamped / 60)).padStart(2, "0");
  const mm = String(clamped % 60).padStart(2, "0");
  return `${hh}:${mm}`;
}
