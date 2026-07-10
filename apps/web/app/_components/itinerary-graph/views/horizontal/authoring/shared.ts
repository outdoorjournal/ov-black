// Shared vocabulary for the advisor authoring surfaces (Search / Analyze / Fill).
//
// These sections render in three hosts — the unified Add composer (Find/Fill
// modes), the Analyze modal, and the standalone-prototype "Build" aside — so the
// class strings, formatters, and (crucially) the inventory→card mappers live
// here as the single source of truth. The mappers turn a live inventory item or
// a fill candidate into a synthetic `NodeResponse` so both surfaces render
// through the SAME common Card model (`CardShell` + `CardBody`) the board and the
// composer preview already use — no bespoke card markup anywhere.

import type {
  FillProposalResponse,
  FindingSeverity,
  NodeType,
  Price,
  SearchInventoryResponse,
} from "@ov-black/api-client";

import type { NodeResponse } from "../../../model/horizontalTypes";

export type InventoryItem = SearchInventoryResponse["items"][number];

// Craft-feel button + section-label recipes, lifted verbatim from the old
// AuthoringPanel so every authoring control keeps the identical look.
export const btn =
  "h-8 rounded-md border border-ink/20 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-40";

export const sectionTitle =
  "font-sans text-[10px] uppercase tracking-[0.22em] text-ink/55";

// Quick kind filters for the keyword search. Flights/hotels need structured
// params (origin/dates, check-in/out) the agent chat is better at — the keyword
// box mostly drives meals/experiences (Places + OV).
export const KIND_CHIPS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "meal", label: "Meals" },
  { value: "experience", label: "Experiences" },
  { value: "hotel", label: "Hotels" },
];

export const SEVERITY_LABEL: Record<FindingSeverity, string> = {
  info: "Info",
  suggest: "Suggest",
  warn: "Warning",
  block: "Blocker",
};

export const SEVERITY_WEIGHT: Record<FindingSeverity, number> = {
  block: 0,
  warn: 1,
  suggest: 2,
  info: 3,
};

export function severityClass(sev: FindingSeverity): string {
  if (sev === "block" || sev === "warn") return "text-[#8b2a1d]";
  return "text-ink/55";
}

export function formatPrice(price?: Price | null): string | null {
  if (!price) return null;
  const cur = price.currency ?? "";
  const lo = price.amount_min ?? null;
  const hi = price.amount_max ?? null;
  if (lo !== null && hi !== null && hi !== lo) return `${cur} ${lo}–${hi}`.trim();
  const amt = lo ?? hi;
  return amt !== null ? `${cur} ${amt}`.trim() : null;
}

// datetime-local ("YYYY-MM-DDTHH:MM") → tz-aware ISO so the gap aligns with the
// trip's local schedule rather than the browser's tz.
export function localToIso(local: string, tzOffsetHours: number): string {
  if (!local) return local;
  const sign = tzOffsetHours >= 0 ? "+" : "-";
  const abs = Math.abs(tzOffsetHours);
  const offH = String(Math.floor(abs)).padStart(2, "0");
  const offM = String(Math.round((abs % 1) * 60)).padStart(2, "0");
  const withSecs = local.length === 16 ? `${local}:00` : local;
  return `${withSecs}${sign}${offH}:${offM}`;
}

// A geo point that might come from inventory (`Location`) or a fill proposal
// (`GeoPointResponse`) — both are `{ lat?, lng?, label? }` with nullable cells.
type MaybeGeo = { lat?: number | null; lng?: number | null; label?: string | null } | null | undefined;

function geoToMeta(loc: MaybeGeo): { location?: { lat: number; lng: number; label?: string } } {
  if (!loc || loc.lat == null || loc.lng == null) return {};
  return {
    location: {
      lat: loc.lat,
      lng: loc.lng,
      ...(loc.label ? { label: loc.label } : {}),
    },
  };
}

// A live inventory result → a synthetic proposed node, so it renders through the
// common Card model exactly like a board card. Price folds into the cost cells
// (surfaced as a caption beside the card, mirroring the composer preview).
export function inventoryItemToNode(item: InventoryItem): NodeResponse {
  const price = item.price ?? null;
  const amount = price?.amount_min ?? price?.amount_max ?? null;
  return {
    id: `inv:${item.source}:${item.source_id}`,
    itinerary_id: "",
    parent_subgraph_id: null,
    type: (item.kind ?? "experience") as NodeType,
    status: "pending",
    title: item.title,
    source: item.source,
    source_id: item.source_id,
    metadata: { ...geoToMeta(item.location) },
    ...(amount != null && price?.currency
      ? {
          cost_amount: String(amount),
          cost_currency: price.currency,
          cost_kind: "total" as const,
        }
      : {}),
  };
}

// A fill candidate → a synthetic proposed node. Carries the proposed slot
// (start_time + duration) so the card reads with a real time, like it will once
// accepted onto the timeline.
export function fillProposalToNode(p: FillProposalResponse): NodeResponse {
  const durationMinutes = (() => {
    const start = new Date(p.starts_at).getTime();
    const end = new Date(p.ends_at).getTime();
    if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return undefined;
    return Math.round((end - start) / 60000);
  })();
  return {
    id: `fill:${p.inventory_source}:${p.inventory_id}`,
    itinerary_id: "",
    parent_subgraph_id: null,
    type: p.type,
    status: "pending",
    title: p.title,
    source: p.inventory_source,
    source_id: p.inventory_id,
    metadata: {
      start_time: p.starts_at,
      ...(durationMinutes != null ? { duration_minutes: durationMinutes } : {}),
      ...geoToMeta(p.location),
    },
  };
}
