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

  it("reads OV adventure filters, dropping unknown taxonomy values", () => {
    const state = parseInventoryQuery({
      regions: ["Asia", "Atlantis"],
      activity_kinds: ["Water", "Sky"],
      activities: ["Hiking", "Rafting"],
      min_price: "100",
      max_difficulty: "8",
      page: "2",
    });
    expect(state.regions).toEqual(["Asia"]);
    expect(state.activityKinds).toEqual(["Water"]);
    expect(state.activities).toBe("Hiking, Rafting");
    expect(state.minPrice).toBe("100");
    expect(state.maxDifficulty).toBe("8");
    expect(state.page).toBe("2");
    expect(hasInventoryQuery(state)).toBe(true);
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

  it("round-trips OV filters through repeated URL params", () => {
    const state = emptyInventoryQuery();
    state.regions = ["Asia", "Europe"];
    state.activityKinds = ["Water"];
    state.activities = "Hiking, Rafting";
    state.maxPrice = "2000";

    const query = toUrlQuery(state);
    const params = new URLSearchParams(query);
    expect(params.getAll("regions")).toEqual(["Asia", "Europe"]);
    expect(params.getAll("activity_kinds")).toEqual(["Water"]);
    expect(params.getAll("activities")).toEqual(["Hiking", "Rafting"]);

    // Object.fromEntries collapses repeats — rebuild lists the way Next's
    // searchParams does (string | string[]).
    const shape: Record<string, string | string[]> = {};
    for (const key of new Set(params.keys())) {
      const all = params.getAll(key);
      shape[key] = all.length > 1 ? all : (all[0] as string);
    }
    expect(parseInventoryQuery(shape)).toEqual(state);
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

  it("maps OV filters to API param names, splitting activities", () => {
    const state = emptyInventoryQuery();
    state.regions = ["Asia"];
    state.activityKinds = ["Water", "Land"];
    state.activities = " Hiking , Rafting ,";
    state.minPrice = "100";
    state.maxPrice = "2000";
    state.minDifficulty = "2";
    state.maxDifficulty = "8";
    state.page = "2";

    expect(toSearchQuery(state)).toEqual({
      regions: ["Asia"],
      activity_kinds: ["Water", "Land"],
      activities: ["Hiking", "Rafting"],
      min_price: 100,
      max_price: 2000,
      min_difficulty: 2,
      max_difficulty: 8,
      page: 2,
    });
  });
});
