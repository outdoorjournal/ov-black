// The Journal's time-shape treatment (traveler-journal). Pins the pieces that
// let the spine read time without becoming a ruler:
//   · every activity card hangs a type-colored duration bar off its circle;
//   · the bar's length tracks the journal zoom (clamped) — the pure helper;
//   · gaps grow with zoom and wear occasional hour ticks;
//   · a gap that spills into evening wears the dusk wash;
//   · the night treatment is now that same dusk wash + ☾ tick, not a bar;
//   · the zoom control is present and drives `journalPxPerMinute`.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));

vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return { ...actual, createApiClient: vi.fn(() => ({})) };
});

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  JOURNAL_ZOOM_MAX,
  JOURNAL_ZOOM_MIN,
  JOURNAL_ZOOM_PRESETS,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { JournalView } from "@/app/_components/itinerary-graph/views/journal/JournalView";
import {
  journalBarHeight,
  JOURNAL_BAR_MAX_PX,
  JOURNAL_BAR_MIN_PX,
} from "@/app/_components/itinerary-graph/views/journal/Spine";

const TZ = 9;

const TRUNK: ItineraryResponse = {
  id: "it-1",
  title: "Kyoto in June",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "with_traveler",
};

function mkNode(
  id: string,
  start: string | null,
  overrides: Partial<NodeResponse> & { duration_minutes?: number } = {},
): NodeResponse {
  const { metadata, duration_minutes = 60, ...rest } = overrides;
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: {
      ...(start ? { start_time: start, duration_minutes } : {}),
      ...(metadata ?? {}),
    },
    ...rest,
  } as NodeResponse;
}

function days(count: number): Array<{ date: string; label: string }> {
  return Array.from({ length: count }, (_, i) => ({
    date: `2024-06-${String(20 + i).padStart(2, "0")}`,
    label: `Day ${i + 1}`,
  }));
}

function timeline(nodes: NodeResponse[], dayCount: number): ItineraryTimeline {
  return {
    id: TRUNK.id,
    label: TRUNK.title,
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: TZ,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-30T23:59:00+09:00",
    days: days(dayCount),
    itinerary: TRUNK,
    nodes,
    edges: [],
  };
}

type StoreApi = ReturnType<typeof itineraryGraphStore.useStoreApi>;
let storeApi: StoreApi | null = null;
function StoreProbe() {
  storeApi = itineraryGraphStore.useStoreApi();
  return null;
}
function api(): ReturnType<StoreApi["getState"]> {
  if (!storeApi) throw new Error("store not mounted");
  return storeApi.getState();
}

function renderJournal(nodes: NodeResponse[], dayCount = 2) {
  const t = timeline(nodes, dayCount);
  const full: ItineraryGraphInit = {
    timeline: t,
    itineraryId: TRUNK.id,
    status: "with_traveler",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
  };
  return render(
    <itineraryGraphStore.Provider initial={full}>
      <TimelineDataProvider value={{ timeline: t, baselineTitle: null }}>
        <StoreProbe />
        <JournalView railIdle={<div data-testid="stub-idle" />} />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

beforeEach(() => {
  storeApi = null;
  vi.clearAllMocks();
  Element.prototype.scrollIntoView =
    vi.fn() as unknown as typeof Element.prototype.scrollIntoView;
});

// ── The pure bar-height helper ────────────────────────────────────────────────
describe("journalBarHeight", () => {
  test("scales linearly with zoom between the clamps", () => {
    expect(journalBarHeight(120, 0.45)).toBeCloseTo(54, 5);
    expect(journalBarHeight(60, 0.9)).toBeCloseTo(54, 5);
  });

  test("never collapses below the floor, never runs past the ceiling", () => {
    expect(journalBarHeight(5, 0.12)).toBe(JOURNAL_BAR_MIN_PX);
    expect(journalBarHeight(24 * 60, 1.2)).toBe(JOURNAL_BAR_MAX_PX);
  });
});

// ── Duration bars on the cards ────────────────────────────────────────────────
describe("duration bars", () => {
  test("every activity card hangs a duration bar keyed to its type", () => {
    renderJournal([
      mkNode("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 90 }),
      mkNode("b", "2024-06-20T14:00:00+09:00", { type: "meal" }),
    ]);
    const bars = screen.getAllByTestId("journal-duration-bar");
    expect(bars).toHaveLength(2);
    // The bar records the minutes it draws (data-minutes) and its kind.
    const a = bars.find((el) => el.dataset["minutes"] === "90");
    expect(a).toBeTruthy();
  });

  test("a note carries no duration bar (it isn't an itinerary card)", () => {
    renderJournal([
      mkNode("a", "2024-06-20T09:00:00+09:00"),
      mkNode("n", "2024-06-20T10:00:00+09:00", { type: "note" }),
    ]);
    // One activity → one bar (the note contributes none).
    expect(screen.getAllByTestId("journal-duration-bar")).toHaveLength(1);
  });

  test("a long (multi-day) bar carries a scroll-back button", () => {
    // A 10-hour span at the default Hour zoom draws well past the card.
    renderJournal(
      [mkNode("long", "2024-06-20T08:00:00+09:00", { duration_minutes: 600 })],
      1,
    );
    expect(screen.getByTestId("journal-bar-scrollback")).toBeTruthy();
  });

  test("a short beat's bar stays near its card — no scroll-back", () => {
    renderJournal([mkNode("short", "2024-06-20T09:00:00+09:00")], 1);
    expect(screen.queryByTestId("journal-bar-scrollback")).toBeNull();
  });

  test("clicking the scroll-back button returns to the card", () => {
    renderJournal(
      [mkNode("long", "2024-06-20T08:00:00+09:00", { duration_minutes: 600 })],
      1,
    );
    fireEvent.click(screen.getByTestId("journal-bar-scrollback"));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  test("zooming changes the bar's drawn height", () => {
    renderJournal([
      mkNode("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 120 }),
    ]);
    const bar = () => screen.getByTestId("journal-duration-bar");
    act(() => api().setJournalZoomPreset("cozy"));
    const cozy = bar().style.height;
    act(() => api().setJournalZoomPreset("detail"));
    const detail = bar().style.height;
    expect(cozy).not.toBe(detail);
    expect(parseFloat(detail)).toBeGreaterThan(parseFloat(cozy));
  });
});

// ── Hour ticks + dusk wash in the gaps ────────────────────────────────────────
describe("gap time cues", () => {
  test("a multi-hour gap wears occasional hour ticks", () => {
    // 09:00–10:00 then 14:00 → a 4-hour quiet afternoon with hour ticks.
    // One day only, so no trailing open-day quiet muddies the count.
    renderJournal(
      [
        mkNode("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 60 }),
        mkNode("b", "2024-06-20T14:00:00+09:00"),
      ],
      1,
    );
    const ticks = screen.getAllByTestId("journal-hour-tick");
    expect(ticks.length).toBeGreaterThan(0);
    // The tick labels read as clock hours (11a, 12p, 1p …).
    expect(ticks.map((t) => t.textContent).join(" ")).toMatch(/\d+[ap]/);
  });

  test("a gap spilling into evening wears the dusk wash", () => {
    // 16:00–17:00 then 20:00 → a gap that crosses into the evening.
    renderJournal(
      [
        mkNode("a", "2024-06-20T16:00:00+09:00", { duration_minutes: 60 }),
        mkNode("b", "2024-06-20T20:00:00+09:00"),
      ],
      1,
    );
    expect(screen.getAllByTestId("journal-dusk-wash").length).toBeGreaterThan(0);
  });

  test("a purely daytime gap has no dusk wash", () => {
    // 09:00–10:00 then 13:00 → a midday gap, no evening. One day only, so no
    // trailing open-day (which would legitimately span into night).
    renderJournal(
      [
        mkNode("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 60 }),
        mkNode("b", "2024-06-20T13:00:00+09:00"),
      ],
      1,
    );
    expect(screen.queryByTestId("journal-dusk-wash")).toBeNull();
  });
});

// ── Night = dusk wash + moon (no bar) ─────────────────────────────────────────
describe("night treatment", () => {
  test("a day followed by another renders the night as a dusk wash + moon", () => {
    renderJournal(
      [
        mkNode("a", "2024-06-20T09:00:00+09:00"),
        mkNode("b", "2024-06-21T09:00:00+09:00"),
      ],
      2,
    );
    // Day 1's night renders; it is the wash, not a crisp colored bar.
    const nights = screen.getAllByTestId("journal-night");
    expect(nights.length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("journal-night-wash").length).toBeGreaterThan(0);
  });
});

// ── The zoom control ──────────────────────────────────────────────────────────
describe("journal zoom control", () => {
  test("presets + slider drive journalPxPerMinute within the clamps", () => {
    renderJournal([mkNode("a", "2024-06-20T09:00:00+09:00")]);
    // The trigger is present once there's a story to scale.
    expect(screen.getByTestId("journal-zoom-trigger")).toBeTruthy();
    act(() => api().setJournalZoomPreset("detail"));
    expect(api().journalPxPerMinute).toBe(JOURNAL_ZOOM_PRESETS.detail);
    act(() => api().setJournalPxPerMinute(999));
    expect(api().journalPxPerMinute).toBe(JOURNAL_ZOOM_MAX);
    act(() => api().setJournalPxPerMinute(0));
    expect(api().journalPxPerMinute).toBe(JOURNAL_ZOOM_MIN);
  });

  test("opening the popover reveals the preset buttons", () => {
    renderJournal([mkNode("a", "2024-06-20T09:00:00+09:00")]);
    fireEvent.click(screen.getByTestId("journal-zoom-trigger"));
    expect(screen.getByTestId("journal-zoom-panel")).toBeTruthy();
  });
});
