"use client";

// The inventory workbench (advisor + developer tool): search every registered
// provider — or scope to one — with full control of the query params, and see
// exactly what came back. Three things make it a provider debugging harness
// rather than a roster: the source pills come from the live registry
// (GET /inventory/sources), every search renders a per-provider diagnostics
// strip (count · latency · captured upstream error), and each result card
// carries a raw-JSON inspector. Searches run on demand (compose, then run) and
// the query round-trips through the URL so a repro is shareable. Browser auth
// follows the CommandPalette precedent: browser Supabase session, fresh token
// per request.

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  type SearchInventoryResponse,
  type SearchSourceDiagnostics,
  createApiClient,
  listInventorySources,
  searchInventory,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createBrowserSupabase } from "@/lib/supabase/client";

import {
  CABIN_CLASSES,
  INVENTORY_KINDS,
  OV_ACTIVITY_KINDS,
  OV_REGIONS,
  type InventoryQueryState,
  hasInventoryQuery,
  toSearchQuery,
  toUrlQuery,
} from "../_lib/inventoryQuery";
import { EmptyNote, ErrorBanner, Panel, SectionHeader } from "./panels";

type InventoryItem = SearchInventoryResponse["items"][number];

type SearchState = {
  items: InventoryItem[];
  diagnostics: SearchSourceDiagnostics[];
};

// Width is set per-use — a `w-full` here would fight the row layout's
// explicit widths (last-in-stylesheet wins, not last-in-class-list).
const inputClass =
  "h-9 rounded-sm border border-paper/15 bg-transparent px-3 font-sans text-sm text-paper placeholder:text-paper/35 focus:border-paper/40 focus:outline-none";

const fieldInputClass = `${inputClass} w-full`;

const pillClass = (on: boolean) =>
  `rounded-full border px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.14em] transition-colors ${
    on
      ? "border-brand/60 bg-brand/10 text-brand"
      : "border-paper/15 text-paper/55 hover:border-paper/35 hover:text-paper"
  }`;

export function InventoryWorkbench({
  initial,
}: {
  initial: InventoryQueryState;
}) {
  const router = useRouter();
  const { apiBaseUrl } = publicEnv();

  const [form, setForm] = useState<InventoryQueryState>(initial);
  const [availableSources, setAvailableSources] = useState<string[] | null>(
    null,
  );
  const [result, setResult] = useState<SearchState | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Monotonic ticket per run — a late response from a superseded search is
  // dropped instead of cancelled (the wrappers don't take an AbortSignal).
  const searchSeq = useRef(0);

  const getAccessToken = useMemo<() => Promise<string | null>>(() => {
    let supabase: ReturnType<typeof createBrowserSupabase> | null = null;
    try {
      supabase = createBrowserSupabase();
    } catch {
      supabase = null;
    }
    return async () => {
      if (!supabase) return null;
      const {
        data: { session },
      } = await supabase.auth.getSession();
      return session?.access_token ?? null;
    };
  }, []);

  const apiClient = useMemo(
    () => async () => {
      const token = await getAccessToken();
      return createApiClient(
        token
          ? { baseUrl: apiBaseUrl, accessToken: token }
          : { baseUrl: apiBaseUrl },
      );
    },
    [getAccessToken, apiBaseUrl],
  );

  const runSearch = useMemo(
    () => async (state: InventoryQueryState) => {
      const seq = ++searchSeq.current;
      setPending(true);
      setError(null);
      const api = await apiClient();
      const searched = await searchInventory(api, toSearchQuery(state));
      if (searchSeq.current !== seq) return;
      setPending(false);
      if (searched.ok) {
        setResult({ items: searched.items, diagnostics: searched.sources });
      } else {
        setResult(null);
        setError(
          searched.detail === "unknown_source"
            ? "One of the selected sources isn't registered on the API."
            : "Search failed — the API is unreachable or this account lacks access.",
        );
      }
    },
    [apiClient],
  );

  const submit = () => {
    const query = toUrlQuery(form);
    router.replace(
      `/command-center/inventory${query ? `?${query}` : ""}` as Route,
      { scroll: false },
    );
    void runSearch(form);
  };

  // Mount: load the provider list off the live registry, and re-run a shared
  // URL's search so the page opens showing what the link described.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const api = await apiClient();
      const sources = await listInventorySources(api);
      if (!cancelled) {
        setAvailableSources(sources.ok ? sources.sources : []);
      }
    })();
    if (hasInventoryQuery(initial)) void runSearch(initial);
    return () => {
      cancelled = true;
    };
    // Mount-only by design: `initial` is the URL snapshot this page opened with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = <K extends keyof InventoryQueryState>(
    field: K,
    value: InventoryQueryState[K],
  ) => setForm((cur) => ({ ...cur, [field]: value }));

  const toggle = (
    field: "sources" | "kinds" | "regions" | "activityKinds",
    value: string,
  ) =>
    setForm((cur) => ({
      ...cur,
      [field]: cur[field].includes(value)
        ? cur[field].filter((v) => v !== value)
        : [...cur[field], value],
    }));

  const onEnter = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") submit();
  };

  return (
    <div className="flex flex-col gap-6">
      <Panel aria-label="Inventory query">
        <SectionHeader
          title="Query"
          eyebrow={
            availableSources === null
              ? "loading sources…"
              : `${availableSources.length} sources registered`
          }
        />

        <div className="flex gap-2">
          <input
            type="text"
            value={form.keyword}
            onChange={(e) => set("keyword", e.target.value)}
            onKeyDown={onEnter}
            placeholder="Keyword — ramen in Kyoto, a private guide…"
            data-testid="inventory-keyword"
            className={`${inputClass} min-w-0 flex-1`}
          />
          <input
            type="number"
            min={1}
            max={50}
            value={form.limit}
            onChange={(e) => set("limit", e.target.value)}
            onKeyDown={onEnter}
            placeholder="Limit"
            aria-label="Result limit per provider"
            className={`${inputClass} w-24 shrink-0`}
          />
          <button
            type="button"
            onClick={submit}
            disabled={pending}
            data-testid="inventory-run"
            className="h-9 shrink-0 rounded-sm border border-brand/60 bg-brand/10 px-5 font-sans text-[11px] uppercase tracking-[0.2em] text-brand transition-colors hover:bg-brand/20 disabled:cursor-default disabled:opacity-40"
          >
            {pending ? "Searching…" : "Search"}
          </button>
        </div>

        <FilterRow label="Sources">
          {availableSources === null ? (
            <span className="font-sans text-xs italic text-paper/40">
              Loading registry…
            </span>
          ) : availableSources.length === 0 ? (
            <span className="font-sans text-xs italic text-paper/40">
              Could not load the provider registry.
            </span>
          ) : (
            <>
              {availableSources.map((source) => (
                <button
                  key={source}
                  type="button"
                  onClick={() => toggle("sources", source)}
                  data-testid={`inventory-source-${source}`}
                  className={pillClass(form.sources.includes(source))}
                >
                  {source}
                </button>
              ))}
              <span className="pl-1 font-sans text-[10px] uppercase tracking-[0.14em] text-paper/35">
                {form.sources.length === 0 ? "all sources" : "scoped"}
              </span>
            </>
          )}
        </FilterRow>

        <FilterRow label="Kinds">
          {INVENTORY_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => toggle("kinds", kind)}
              className={pillClass(form.kinds.includes(kind))}
            >
              {kind}
            </button>
          ))}
        </FilterRow>

        <ParamGroup
          summary="Flight params — Duffel needs origin + destination + departure date"
          defaultOpen={Boolean(form.origin || form.destination || form.departureDate)}
        >
          <Field label="Origin (IATA)">
            <input
              type="text"
              value={form.origin}
              onChange={(e) => set("origin", e.target.value.toUpperCase())}
              onKeyDown={onEnter}
              placeholder="LHR"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Destination (IATA)">
            <input
              type="text"
              value={form.destination}
              onChange={(e) => set("destination", e.target.value.toUpperCase())}
              onKeyDown={onEnter}
              placeholder="JFK"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Departure">
            <input
              type="date"
              value={form.departureDate}
              onChange={(e) => set("departureDate", e.target.value)}
              className={fieldInputClass}
            />
          </Field>
          <Field label="Return (round trip)">
            <input
              type="date"
              value={form.returnDate}
              onChange={(e) => set("returnDate", e.target.value)}
              className={fieldInputClass}
            />
          </Field>
          <Field label="Cabin">
            <select
              value={form.cabinClass}
              onChange={(e) => set("cabinClass", e.target.value)}
              className={`${fieldInputClass} appearance-none`}
            >
              <option value="">any</option>
              {CABIN_CLASSES.map((cabin) => (
                <option key={cabin} value={cabin}>
                  {cabin.replace("_", " ")}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Adults">
            <input
              type="number"
              min={1}
              max={9}
              value={form.adults}
              onChange={(e) => set("adults", e.target.value)}
              onKeyDown={onEnter}
              placeholder="2"
              className={fieldInputClass}
            />
          </Field>
        </ParamGroup>

        <ParamGroup
          summary="Hotel params — Ratehawk wants check-in/out plus a region or lat/lng"
          defaultOpen={Boolean(form.checkin || form.checkout || form.regionId)}
        >
          <Field label="Check-in">
            <input
              type="date"
              value={form.checkin}
              onChange={(e) => set("checkin", e.target.value)}
              className={fieldInputClass}
            />
          </Field>
          <Field label="Check-out">
            <input
              type="date"
              value={form.checkout}
              onChange={(e) => set("checkout", e.target.value)}
              className={fieldInputClass}
            />
          </Field>
          <Field label="Region id">
            <input
              type="number"
              value={form.regionId}
              onChange={(e) => set("regionId", e.target.value)}
              onKeyDown={onEnter}
              placeholder="2381"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Latitude">
            <input
              type="number"
              step="any"
              value={form.latitude}
              onChange={(e) => set("latitude", e.target.value)}
              onKeyDown={onEnter}
              placeholder="45.98"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Longitude">
            <input
              type="number"
              step="any"
              value={form.longitude}
              onChange={(e) => set("longitude", e.target.value)}
              onKeyDown={onEnter}
              placeholder="9.25"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Residency (ISO-2)">
            <input
              type="text"
              value={form.residency}
              onChange={(e) => set("residency", e.target.value.toLowerCase())}
              onKeyDown={onEnter}
              placeholder="us"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Currency">
            <input
              type="text"
              value={form.currency}
              onChange={(e) => set("currency", e.target.value.toUpperCase())}
              onKeyDown={onEnter}
              placeholder="USD"
              className={fieldInputClass}
            />
          </Field>
        </ParamGroup>

        <ParamGroup
          summary="Location bias — nudges Google Places toward a point"
          defaultOpen={Boolean(form.nearLat || form.nearLng)}
        >
          <Field label="Near lat">
            <input
              type="number"
              step="any"
              value={form.nearLat}
              onChange={(e) => set("nearLat", e.target.value)}
              onKeyDown={onEnter}
              placeholder="35.66"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Near lng">
            <input
              type="number"
              step="any"
              value={form.nearLng}
              onChange={(e) => set("nearLng", e.target.value)}
              onKeyDown={onEnter}
              placeholder="139.73"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Radius (m)">
            <input
              type="number"
              min={1}
              max={50000}
              value={form.radiusM}
              onChange={(e) => set("radiusM", e.target.value)}
              onKeyDown={onEnter}
              placeholder="5000"
              className={fieldInputClass}
            />
          </Field>
        </ParamGroup>

        <ParamGroup
          summary="Adventure params — Outdoor Voyage regions, activities, price, difficulty"
          defaultOpen={Boolean(
            form.regions.length > 0 ||
              form.activityKinds.length > 0 ||
              form.activities ||
              form.minPrice ||
              form.maxPrice,
          )}
        >
          <div className="col-span-2 sm:col-span-3 lg:col-span-4">
            <FilterRow label="Regions">
              {OV_REGIONS.map((region) => (
                <button
                  key={region}
                  type="button"
                  onClick={() => toggle("regions", region)}
                  data-testid={`inventory-region-${region.replaceAll(" ", "-")}`}
                  className={pillClass(form.regions.includes(region))}
                >
                  {region}
                </button>
              ))}
            </FilterRow>
          </div>
          <div className="col-span-2 sm:col-span-3 lg:col-span-4">
            <FilterRow label="Activity">
              {OV_ACTIVITY_KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => toggle("activityKinds", kind)}
                  data-testid={`inventory-activity-kind-${kind}`}
                  className={pillClass(form.activityKinds.includes(kind))}
                >
                  {kind}
                </button>
              ))}
            </FilterRow>
          </div>
          <Field label="Activities (comma-separated)">
            <input
              type="text"
              value={form.activities}
              onChange={(e) => set("activities", e.target.value)}
              onKeyDown={onEnter}
              placeholder="Hiking, Rafting"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Min price (USD)">
            <input
              type="number"
              min={0}
              value={form.minPrice}
              onChange={(e) => set("minPrice", e.target.value)}
              onKeyDown={onEnter}
              placeholder="0"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Max price (USD)">
            <input
              type="number"
              min={0}
              max={5000}
              value={form.maxPrice}
              onChange={(e) => set("maxPrice", e.target.value)}
              onKeyDown={onEnter}
              placeholder="5000"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Min difficulty (1–10)">
            <input
              type="number"
              min={1}
              max={10}
              value={form.minDifficulty}
              onChange={(e) => set("minDifficulty", e.target.value)}
              onKeyDown={onEnter}
              placeholder="1"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Max difficulty (1–10)">
            <input
              type="number"
              min={1}
              max={10}
              value={form.maxDifficulty}
              onChange={(e) => set("maxDifficulty", e.target.value)}
              onKeyDown={onEnter}
              placeholder="10"
              className={fieldInputClass}
            />
          </Field>
          <Field label="Page (9 per page)">
            <input
              type="number"
              min={1}
              value={form.page}
              onChange={(e) => set("page", e.target.value)}
              onKeyDown={onEnter}
              placeholder="auto"
              className={fieldInputClass}
            />
          </Field>
        </ParamGroup>
      </Panel>

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      {result ? (
        <DiagnosticsStrip diagnostics={result.diagnostics} />
      ) : null}

      {result === null && !pending && !error ? (
        <EmptyNote>
          Compose a query and run it — no sources selected means the aggregate
          fan-out across every registered provider.
        </EmptyNote>
      ) : null}

      {result !== null && result.items.length === 0 && !pending ? (
        <EmptyNote>
          No items came back — the diagnostics above say which providers
          answered empty (or errored).
        </EmptyNote>
      ) : null}

      {result !== null && result.items.length > 0 ? (
        <ul
          data-testid="inventory-results"
          className="grid list-none grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
        >
          {result.items.map((item) => (
            <ResultCard key={`${item.source}:${item.source_id}`} item={item} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FilterRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-16 shrink-0 font-sans text-[10px] uppercase tracking-label text-paper/45">
        {label}
      </span>
      {children}
    </div>
  );
}

function ParamGroup({
  summary,
  defaultOpen,
  children,
}: {
  summary: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  return (
    <details open={defaultOpen} className="group border-t border-paper/10 pt-3">
      <summary className="cursor-pointer list-none font-sans text-xs text-paper/55 transition-colors hover:text-paper">
        <span aria-hidden className="mr-2 inline-block group-open:rotate-90">
          ›
        </span>
        {summary}
      </summary>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {children}
      </div>
    </details>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-sans text-[10px] uppercase tracking-label text-paper/45">
        {label}
      </span>
      {children}
    </label>
  );
}

/** One chip per provider the fan-out hit: `source · count · latency`, red on
 *  a captured upstream error (full message rendered beneath the strip). */
function DiagnosticsStrip({
  diagnostics,
}: {
  diagnostics: SearchSourceDiagnostics[];
}) {
  if (diagnostics.length === 0) return null;
  const failures = diagnostics.filter((d) => d.error);
  return (
    <div data-testid="inventory-diagnostics" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {diagnostics.map((d) => (
          <span
            key={d.source}
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[11px] ${
              d.error
                ? "border-destructive/50 bg-destructive/10 text-destructive-foreground"
                : d.count === 0
                  ? "border-paper/15 text-paper/45"
                  : "border-paper/25 text-paper/80"
            }`}
          >
            <span className="uppercase tracking-[0.1em]">{d.source}</span>
            <span>{d.error ? "error" : d.count}</span>
            <span className="text-paper/40">{d.elapsed_ms}ms</span>
          </span>
        ))}
      </div>
      {failures.map((d) => (
        <p
          key={d.source}
          className="font-mono text-[11px] text-destructive-foreground/90"
        >
          {d.source}: {d.error}
        </p>
      ))}
    </div>
  );
}

function formatPrice(price: InventoryItem["price"]): string | null {
  if (!price) return null;
  const { amount_min: min, amount_max: max, currency } = price;
  const fmt = (value: number) =>
    new Intl.NumberFormat("en-US", {
      style: currency ? "currency" : "decimal",
      ...(currency ? { currency } : {}),
      maximumFractionDigits: value % 1 === 0 ? 0 : 2,
    }).format(value);
  if (min != null && max != null && min !== max) return `${fmt(min)}–${fmt(max)}`;
  const single = min ?? max;
  return single != null ? fmt(single) : null;
}

function ResultCard({ item }: { item: InventoryItem }) {
  const photo = item.photos?.[0];
  const price = formatPrice(item.price);
  return (
    <li
      data-testid="inventory-result"
      className="flex flex-col overflow-hidden rounded-md border border-paper/10 bg-paper/5"
    >
      {photo ? (
        // Provider photos come from arbitrary hosts — next/image would need a
        // remotePatterns entry per provider, so a plain <img> like the card kit.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={photo}
          alt=""
          loading="lazy"
          className="h-36 w-full object-cover"
        />
      ) : null}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-brand/40 px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.2em] text-brand">
            {item.source}
          </span>
          <span className="rounded-full border border-paper/15 px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55">
            {item.kind}
          </span>
          {price ? (
            <span className="ml-auto font-mono text-xs text-paper/80">
              {price}
            </span>
          ) : null}
        </div>
        <h3 className="font-serif text-lg leading-snug tracking-tight text-paper">
          {item.title}
        </h3>
        {item.description ? (
          <p className="line-clamp-2 font-sans text-xs leading-relaxed text-paper/60">
            {item.description}
          </p>
        ) : null}
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 font-sans text-[11px] text-paper/50">
          {item.location?.label ? <span>{item.location.label}</span> : null}
          {item.rating != null ? (
            <span>
              ★ {item.rating}
              {item.rating_count != null ? ` (${item.rating_count})` : ""}
            </span>
          ) : null}
          {(item.tags ?? []).slice(0, 4).map((tag) => (
            <span key={tag} className="text-paper/40">
              #{tag}
            </span>
          ))}
        </div>
        <details className="border-t border-paper/10 pt-2">
          <summary className="cursor-pointer list-none font-mono text-[10px] uppercase tracking-[0.2em] text-paper/40 transition-colors hover:text-paper/80">
            raw · {item.source_id}
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-sm bg-black/40 p-3 font-mono text-[10px] leading-relaxed text-paper/70">
            {JSON.stringify(item, null, 2)}
          </pre>
        </details>
      </div>
    </li>
  );
}
