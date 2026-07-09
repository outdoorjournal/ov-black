import { describe, expect, it } from "vitest";

import {
  emptyInventoryQuery,
  hasInventoryQuery,
  parseInventoryQuery,
  toSearchQuery,
  toUrlQuery,
} from "../app/command-center/_lib/inventoryQuery";

describe("parseInventoryQuery", () => {
  it("returns the empty state for no params", () => {
    const state = parseInventoryQuery({});
    expect(state).toEqual(emptyInventoryQuery());
    expect(hasInventoryQuery(state)).toBe(false);
  });

  it("reads repeated source/kinds and scalar fields", () => {
    const state = parseInventoryQuery({
      source: ["duffel", "ratehawk"],
      kinds: "hotel",
      keyword: "como",
      limit: "10",
      departure_date: "2026-07-12",
      near_lat: "35.66",
    });
    expect(state.sources).toEqual(["duffel", "ratehawk"]);
    expect(state.kinds).toEqual(["hotel"]);
    expect(state.keyword).toBe("como");
    expect(state.limit).toBe("10");
    expect(state.departureDate).toBe("2026-07-12");
    expect(state.nearLat).toBe("35.66");
    expect(hasInventoryQuery(state)).toBe(true);
  });

  it("drops unknown kinds instead of forwarding them", () => {
    const state = parseInventoryQuery({ kinds: ["hotel", "banana"] });
    expect(state.kinds).toEqual(["hotel"]);
  });
});

describe("toUrlQuery round trip", () => {
  it("serializes only non-empty fields and parses back to the same state", () => {
    const state = emptyInventoryQuery();
    state.sources = ["duffel"];
    state.kinds = ["flight"];
    state.origin = "LHR";
    state.destination = "JFK";
    state.departureDate = "2026-07-12";
    state.adults = "2";

    const query = toUrlQuery(state);
    expect(query).not.toContain("keyword");
    expect(query).not.toContain("checkin");

    const reparsed = parseInventoryQuery(
      Object.fromEntries(new URLSearchParams(query)),
    );
    expect(reparsed).toEqual(state);
  });

  it("serializes nothing for the empty state", () => {
    expect(toUrlQuery(emptyInventoryQuery())).toBe("");
  });
});

describe("toSearchQuery", () => {
  it("omits empty fields entirely", () => {
    expect(toSearchQuery(emptyInventoryQuery())).toEqual({});
  });

  it("coerces numeric fields and keeps API param names", () => {
    const state = emptyInventoryQuery();
    state.sources = ["ratehawk"];
    state.keyword = "  lake como  ";
    state.limit = "10";
    state.regionId = "2381";
    state.checkin = "2026-09-12";
    state.nearLat = "35.66";

    expect(toSearchQuery(state)).toEqual({
      source: ["ratehawk"],
      keyword: "lake como",
      limit: 10,
      region_id: 2381,
      checkin: "2026-09-12",
      near_lat: 35.66,
    });
  });

  it("drops unparseable numerics instead of sending NaN", () => {
    const state = emptyInventoryQuery();
    state.limit = "lots";
    expect(toSearchQuery(state)).toEqual({});
  });
});
