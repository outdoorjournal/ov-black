// Unit tests for journalEditing — the Journal's phase-3 editing arithmetic:
// drop-slot time assignment (the "sensible slot time" contract — no time-pixel
// math anywhere) and the drop policy (what a spine drop DOES per role/surface,
// driven by the existing store selectors).

import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import {
  cardBoundsOf,
  dropSlotMinutes,
  endOfDayMinute,
  journalDragId,
  journalDropMode,
  journalSlotId,
  minuteLabel,
  nodeIdFromJournalDragId,
  SLOT_EMPTY_DAY_MIN,
  slotMinute,
} from "@/app/_components/itinerary-graph/views/journal/journalEditing";
import type { JournalEntry } from "@/app/_components/itinerary-graph/views/journal/toJournal";
import type { ItineraryGraphState } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

// ── slotMinute: the sensible slot time between neighbours ─────────────────────
describe("slotMinute", () => {
  test("an empty day drops at noon", () => {
    expect(slotMinute(null, null)).toBe(SLOT_EMPTY_DAY_MIN);
  });
  test("before the first card: leads it by an hour", () => {
    expect(slotMinute(null, 9 * 60)).toBe(8 * 60);
  });
  test("after the last card: trails it by half an hour", () => {
    expect(slotMinute(10 * 60, null)).toBe(10 * 60 + 30);
  });
  test("between two cards: the midpoint, snapped to a quarter-hour", () => {
    expect(slotMinute(9 * 60, 11 * 60)).toBe(10 * 60);
    // 540 → 655: midpoint 597.5 snaps to 600.
    expect(slotMinute(540, 655)).toBe(600);
  });
  test("overlapping neighbours land at the first card's end", () => {
    expect(slotMinute(600, 580)).toBe(600);
  });
  test("never escapes the day", () => {
    expect(slotMinute(null, 20)).toBe(0);
    expect(slotMinute(1430, null)).toBe(1439); // clamped to the day's end
  });
});

// ── cardBoundsOf + dropSlotMinutes over a day's entries ───────────────────────
function mkNode(id: string, startIso: string, durationMin = 60): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: { start_time: startIso, duration_minutes: durationMin },
  } as NodeResponse;
}

function nodeEntry(id: string, startIso: string): JournalEntry {
  return { kind: "node", node: mkNode(id, startIso) };
}

describe("drop slots along a day", () => {
  test("N cards → N+1 slots: lead, midpoints, trail", () => {
    const entries: JournalEntry[] = [
      nodeEntry("a", "2024-06-20T09:00:00+09:00"), // 540–600
      { kind: "gap", minutes: 120 },
      nodeEntry("b", "2024-06-20T12:00:00+09:00"), // 720–780
    ];
    const bounds = cardBoundsOf(entries, 9);
    expect(bounds).toEqual([
      { startMinute: 540, endMinute: 600 },
      { startMinute: 720, endMinute: 780 },
    ]);
    expect(dropSlotMinutes(bounds)).toEqual([480, 660, 810]);
    expect(endOfDayMinute(bounds)).toBe(810);
  });

  test("an alt group is ONE row spanning its members", () => {
    const entries: JournalEntry[] = [
      {
        kind: "alt",
        groupKey: "g",
        nodes: [
          mkNode("a", "2024-06-20T13:00:00+09:00"),
          mkNode("b", "2024-06-20T13:30:00+09:00"),
        ],
      },
    ];
    expect(cardBoundsOf(entries, 9)).toEqual([
      { startMinute: 13 * 60, endMinute: 14 * 60 + 30 },
    ]);
  });

  test("an empty day has exactly one slot, at noon", () => {
    expect(dropSlotMinutes([])).toEqual([SLOT_EMPTY_DAY_MIN]);
    expect(endOfDayMinute([])).toBe(SLOT_EMPTY_DAY_MIN);
  });
});

// ── journalDropMode: role decides, via the existing selectors ─────────────────
function state(partial: Record<string, unknown>): ItineraryGraphState {
  return {
    canEdit: false,
    status: "in_studio",
    draftMine: false,
    lockStatus: "unlocked",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    sample: { itinerary: { forked_from_id: null } },
    ...partial,
  } as unknown as ItineraryGraphState;
}

describe("journalDropMode", () => {
  test("a traveler on their own fork moves directly", () => {
    expect(
      journalDropMode(
        state({ sample: { itinerary: { forked_from_id: "trunk-1" } } }),
      ),
    ).toBe("move");
  });
  test("an advisor on their working copy moves directly", () => {
    expect(
      journalDropMode(
        state({
          canEdit: true,
          sample: { itinerary: { forked_from_id: "trunk-1" } },
        }),
      ),
    ).toBe("move");
  });
  test("the draft-mine preview lazily forks on the first move", () => {
    expect(journalDropMode(state({ draftMine: true }))).toBe("fork-and-move");
  });
  test("the official trunk OFFERS the fork instead of silently failing", () => {
    expect(journalDropMode(state({}))).toBe("offer-fork");
  });
  test("approved plans and credential-less viewers get no drag at all", () => {
    expect(journalDropMode(state({ status: "approved" }))).toBe("none");
    expect(
      journalDropMode(state({ apiBaseUrl: null, accessToken: null })),
    ).toBe("none");
  });
});

// ── ids + labels ──────────────────────────────────────────────────────────────
describe("drag ids and labels", () => {
  test("drag ids are namespaced and round-trip", () => {
    expect(nodeIdFromJournalDragId(journalDragId("n1"))).toBe("n1");
    expect(journalSlotId("2024-06-20", 2)).toBe("journal-slot:2024-06-20:2");
  });
  test("minuteLabel prints a clean clock", () => {
    expect(minuteLabel(630)).toBe("10:30");
    expect(minuteLabel(0)).toBe("00:00");
  });
});
