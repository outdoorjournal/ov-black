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

/** OV adventure continents (matches `countries.region` upstream). */
export const OV_REGIONS = [
  "Europe",
  "Asia",
  "Africa",
  "North America",
  "South America",
  "Oceania",
] as const;

/** OV activity-kind taxonomy (live `/api/activities/kinds`). */
export const OV_ACTIVITY_KINDS = [
  "Air",
  "Land",
  "Water",
  "Motor",
  "Snow",
  "Lodging",
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
  // OV adventures
  regions: string[];
  activityKinds: string[];
  activities: string;
  minPrice: string;
  maxPrice: string;
  minDifficulty: string;
  maxDifficulty: string;
  page: string;
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
    regions: [],
    activityKinds: [],
    activities: "",
    minPrice: "",
    maxPrice: "",
    minDifficulty: "",
    maxDifficulty: "",
    page: "",
  };
}

type StringField = Exclude<
  keyof InventoryQueryState,
  "sources" | "kinds" | "regions" | "activityKinds"
>;

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
  ["minPrice", "min_price"],
  ["maxPrice", "max_price"],
  ["minDifficulty", "min_difficulty"],
  ["maxDifficulty", "max_difficulty"],
  ["page", "page"],
];

/** Split a comma-separated activities input into clean names. */
export function splitActivities(raw: string): string[] {
  return raw
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

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
  state.regions = asList(searchParams["regions"]).filter((r) =>
    (OV_REGIONS as readonly string[]).includes(r),
  );
  state.activityKinds = asList(searchParams["activity_kinds"]).filter((k) =>
    (OV_ACTIVITY_KINDS as readonly string[]).includes(k),
  );
  // Repeated in the URL (mirrors the API); a single comma-separated text
  // input in the form.
  state.activities = asList(searchParams["activities"]).join(", ");
  for (const [field, key] of URL_KEYS) {
    state[field] = asString(searchParams[key]);
  }
  return state;
}

/** True when the state carries anything worth auto-running on mount. */
export function hasInventoryQuery(state: InventoryQueryState): boolean {
  if (state.sources.length > 0 || state.kinds.length > 0) return true;
  if (state.regions.length > 0 || state.activityKinds.length > 0) return true;
  return URL_KEYS.some(([field]) => state[field] !== "");
}

/** Canonical query string for router.replace — omits empty fields. */
export function toUrlQuery(state: InventoryQueryState): string {
  const params = new URLSearchParams();
  for (const source of state.sources) params.append("source", source);
  for (const kind of state.kinds) params.append("kinds", kind);
  for (const region of state.regions) params.append("regions", region);
  for (const kind of state.activityKinds)
    params.append("activity_kinds", kind);
  for (const activity of splitActivities(state.activities))
    params.append("activities", activity);
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
  const minPrice = asNumber(state.minPrice);
  const maxPrice = asNumber(state.maxPrice);
  const minDifficulty = asNumber(state.minDifficulty);
  const maxDifficulty = asNumber(state.maxDifficulty);
  const page = asNumber(state.page);
  const activities = splitActivities(state.activities);
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
    ...(state.regions.length > 0 ? { regions: state.regions } : {}),
    ...(state.activityKinds.length > 0
      ? { activity_kinds: state.activityKinds }
      : {}),
    ...(activities.length > 0 ? { activities } : {}),
    ...(minPrice !== undefined ? { min_price: minPrice } : {}),
    ...(maxPrice !== undefined ? { max_price: maxPrice } : {}),
    ...(minDifficulty !== undefined ? { min_difficulty: minDifficulty } : {}),
    ...(maxDifficulty !== undefined ? { max_difficulty: maxDifficulty } : {}),
    ...(page !== undefined ? { page } : {}),
  };
}
