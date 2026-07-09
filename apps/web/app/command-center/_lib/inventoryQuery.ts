// Pure vocabulary for the inventory workbench (Wave F follow-on). The form
// state ↔ URL ↔ SDK-query mapping lives here — outside the client component —
// so round-tripping is unit-testable and the workbench stays a thin shell.
// URL param names mirror the API's query params exactly (`source` repeated,
// `departure_date`, …) so a shared workbench URL reads like the request it
// makes.

import type { SearchInventoryQuery } from "@ov-black/api-client";

import type { SearchParamsShape } from "./tableParams";

/** Every `InventoryItem.kind` the API's discriminated union carries. */
export const INVENTORY_KINDS = [
  "experience",
  "destination",
  "hotel",
  "flight",
  "meal",
  "transit",
  "note",
] as const;

export const CABIN_CLASSES = [
  "economy",
  "premium_economy",
  "business",
  "first",
] as const;

/**
 * The workbench form. Free-text fields stay strings (they back inputs
 * directly); numeric coercion happens once, in `toSearchQuery`.
 */
export type InventoryQueryState = {
  sources: string[];
  kinds: string[];
  keyword: string;
  limit: string;
  // Flight (Duffel)
  origin: string;
  destination: string;
  departureDate: string;
  returnDate: string;
  cabinClass: string;
  adults: string;
  // Hotel (Ratehawk / Duffel Stays)
  regionId: string;
  latitude: string;
  longitude: string;
  checkin: string;
  checkout: string;
  residency: string;
  currency: string;
  // Google Places location bias
  nearLat: string;
  nearLng: string;
  radiusM: string;
};

export function emptyInventoryQuery(): InventoryQueryState {
  return {
    sources: [],
    kinds: [],
    keyword: "",
    limit: "",
    origin: "",
    destination: "",
    departureDate: "",
    returnDate: "",
    cabinClass: "",
    adults: "",
    regionId: "",
    latitude: "",
    longitude: "",
    checkin: "",
    checkout: "",
    residency: "",
    currency: "",
    nearLat: "",
    nearLng: "",
    radiusM: "",
  };
}

type StringField = Exclude<keyof InventoryQueryState, "sources" | "kinds">;

/** URL param name per string field (list fields handled separately). */
const URL_KEYS: ReadonlyArray<[StringField, string]> = [
  ["keyword", "keyword"],
  ["limit", "limit"],
  ["origin", "origin"],
  ["destination", "destination"],
  ["departureDate", "departure_date"],
  ["returnDate", "return_date"],
  ["cabinClass", "cabin_class"],
  ["adults", "adults"],
  ["regionId", "region_id"],
  ["latitude", "latitude"],
  ["longitude", "longitude"],
  ["checkin", "checkin"],
  ["checkout", "checkout"],
  ["residency", "residency"],
  ["currency", "currency"],
  ["nearLat", "near_lat"],
  ["nearLng", "near_lng"],
  ["radiusM", "radius_m"],
];

function asList(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  const items = Array.isArray(value) ? value : [value];
  return items.map((v) => v.trim()).filter(Boolean);
}

function asString(value: string | string[] | undefined): string {
  if (value === undefined) return "";
  return (Array.isArray(value) ? (value[0] ?? "") : value).trim();
}

/** Rebuild the form state from a page's `searchParams` (a shared URL). */
export function parseInventoryQuery(
  searchParams: SearchParamsShape,
): InventoryQueryState {
  const state = emptyInventoryQuery();
  state.sources = asList(searchParams["source"]);
  state.kinds = asList(searchParams["kinds"]).filter((k) =>
    (INVENTORY_KINDS as readonly string[]).includes(k),
  );
  for (const [field, key] of URL_KEYS) {
    state[field] = asString(searchParams[key]);
  }
  return state;
}

/** True when the state carries anything worth auto-running on mount. */
export function hasInventoryQuery(state: InventoryQueryState): boolean {
  if (state.sources.length > 0 || state.kinds.length > 0) return true;
  return URL_KEYS.some(([field]) => state[field] !== "");
}

/** Canonical query string for router.replace — omits empty fields. */
export function toUrlQuery(state: InventoryQueryState): string {
  const params = new URLSearchParams();
  for (const source of state.sources) params.append("source", source);
  for (const kind of state.kinds) params.append("kinds", kind);
  for (const [field, key] of URL_KEYS) {
    if (state[field] !== "") params.set(key, state[field]);
  }
  return params.toString();
}

function asNumber(raw: string): number | undefined {
  if (raw === "") return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

/**
 * Build the SDK query. Only non-empty fields are included (the API treats a
 * missing param as "unconstrained"), and numeric fields drop silently when
 * unparseable rather than sending NaN.
 */
export function toSearchQuery(state: InventoryQueryState): SearchInventoryQuery {
  const limit = asNumber(state.limit);
  const adults = asNumber(state.adults);
  const regionId = asNumber(state.regionId);
  const latitude = asNumber(state.latitude);
  const longitude = asNumber(state.longitude);
  const nearLat = asNumber(state.nearLat);
  const nearLng = asNumber(state.nearLng);
  const radiusM = asNumber(state.radiusM);
  return {
    ...(state.sources.length > 0 ? { source: state.sources } : {}),
    ...(state.kinds.length > 0 ? { kinds: state.kinds } : {}),
    ...(state.keyword.trim() ? { keyword: state.keyword.trim() } : {}),
    ...(limit !== undefined ? { limit } : {}),
    ...(state.origin ? { origin: state.origin } : {}),
    ...(state.destination ? { destination: state.destination } : {}),
    ...(state.departureDate ? { departure_date: state.departureDate } : {}),
    ...(state.returnDate ? { return_date: state.returnDate } : {}),
    ...(state.cabinClass ? { cabin_class: state.cabinClass } : {}),
    ...(adults !== undefined ? { adults } : {}),
    ...(regionId !== undefined ? { region_id: regionId } : {}),
    ...(latitude !== undefined ? { latitude } : {}),
    ...(longitude !== undefined ? { longitude } : {}),
    ...(state.checkin ? { checkin: state.checkin } : {}),
    ...(state.checkout ? { checkout: state.checkout } : {}),
    ...(state.residency ? { residency: state.residency } : {}),
    ...(state.currency ? { currency: state.currency } : {}),
    ...(nearLat !== undefined ? { near_lat: nearLat } : {}),
    ...(nearLng !== undefined ? { near_lng: nearLng } : {}),
    ...(radiusM !== undefined ? { radius_m: radiusM } : {}),
  };
}
