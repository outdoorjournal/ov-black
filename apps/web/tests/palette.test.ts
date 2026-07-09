import { expect, test } from "vitest";

import {
  PALETTE_NAV_ACTIONS,
  filterNavActions,
} from "@/app/command-center/_lib/palette";

test("empty query shows every nav action (resting state is a nav menu)", () => {
  expect(filterNavActions("")).toEqual([...PALETTE_NAV_ACTIONS]);
  expect(filterNavActions("   ")).toEqual([...PALETTE_NAV_ACTIONS]);
});

test("matches on label, case-insensitively", () => {
  const hits = filterNavActions("TRIPS");
  expect(hits.map((a) => a.id)).toEqual(["nav-trips"]);
});

test("matches on keywords — billing finds Money, invite finds New client", () => {
  expect(filterNavActions("billing").map((a) => a.id)).toEqual(["nav-money"]);
  expect(filterNavActions("invite").map((a) => a.id)).toEqual([
    "nav-new-client",
  ]);
});

test("substring queries hit multiple actions", () => {
  // "client" matches the Clients label and New client.
  const ids = filterNavActions("client").map((a) => a.id);
  expect(ids).toContain("nav-clients");
  expect(ids).toContain("nav-new-client");
});

test("no nav match returns empty (roster results own the answer)", () => {
  expect(filterNavActions("zanzibar")).toEqual([]);
});

test("every nav action points under /command-center", () => {
  for (const action of PALETTE_NAV_ACTIONS) {
    expect(action.href.startsWith("/command-center")).toBe(true);
  }
});
