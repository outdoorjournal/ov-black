// Wave E (ADV-16) — the strictly-Day-N-until-pinned helpers. One rule for
// every date-bearing surface: pinned trips render real dates, unpinned trips
// render honest "Day N" ordinals from the Day-1 anchor, and when nothing
// anchors Day 1 the stamp hides rather than lies.

import { describe, expect, test } from "vitest";

import {
  datesPinned,
  dayAnchorKey,
  dayOrdinal,
  formatNodeWhen,
} from "@/app/_components/itinerary-graph/model/time";

const PINNED = {
  timing_kind: "exact",
  date_start: "2027-03-18",
  days_anchor: "2027-03-18",
};
const WINDOWED = {
  timing_kind: "window",
  date_start: "2027-06-01",
  days_anchor: "2027-06-01",
};

describe("datesPinned / dayAnchorKey", () => {
  test("only exact counts as pinned", () => {
    expect(datesPinned(PINNED)).toBe(true);
    expect(datesPinned(WINDOWED)).toBe(false);
    expect(datesPinned(null)).toBe(false);
    expect(datesPinned({ timing_kind: "flexible" })).toBe(false);
  });

  test("anchor: exact → date_start; else the stamped days_anchor; else null", () => {
    expect(dayAnchorKey(PINNED)).toBe("2027-03-18");
    expect(dayAnchorKey(WINDOWED)).toBe("2027-06-01");
    expect(dayAnchorKey({ timing_kind: "window", days_anchor: null })).toBeNull();
    expect(dayAnchorKey(null)).toBeNull();
  });
});

describe("dayOrdinal", () => {
  test("counts 1-based from the anchor", () => {
    expect(dayOrdinal(WINDOWED, "2027-06-01")).toBe(1);
    expect(dayOrdinal(WINDOWED, "2027-06-03")).toBe(3);
  });

  test("a date before the anchor can't be an honest ordinal", () => {
    expect(dayOrdinal(WINDOWED, "2027-05-30")).toBeNull();
  });

  test("no anchor → null", () => {
    expect(dayOrdinal({ timing_kind: "flexible" }, "2027-06-01")).toBeNull();
  });
});

describe("formatNodeWhen", () => {
  test("pinned → a real date", () => {
    // Exact wording is locale-dependent; assert the shape (month present).
    expect(formatNodeWhen(PINNED, "2027-03-20T15:00:00+09:00")).toMatch(/Mar/);
  });

  test("unpinned → the Day-N ordinal in the node's OWN timezone", () => {
    // 19:00 on Jun 3 in +02:00 — day-bucketing must use the node's offset.
    expect(formatNodeWhen(WINDOWED, "2027-06-03T19:00:00+02:00")).toBe("Day 3");
  });

  test("unpinned with no anchor → hides rather than fabricates", () => {
    expect(formatNodeWhen({ timing_kind: "flexible" }, "2027-06-03T19:00:00Z")).toBeNull();
  });

  test("unparseable ISO → null", () => {
    expect(formatNodeWhen(PINNED, "not-a-date")).toBeNull();
  });
});
