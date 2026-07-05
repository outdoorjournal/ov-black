"use client";

// B7 — advisor authoring panel.
//
// The "Build" half of the staff aside (the "Concierge" half is ChatPanel). It
// surfaces the three AI-assisted authoring capabilities the backend already
// exposes, all through itineraryGraphStore actions:
//   1. Inventory search (B1–B3) → Add a result as a `proposed` node.
//   2. Analyze (B5) → run + poll + render findings (severity / message / fix).
//   3. Fill (B6) → rank feasible candidates for a gap → Accept one as a node.
//
// Reads (search / analyze / fill) only need `canEdit`; the two writes
// (Add / Accept) need the lock, so their buttons gate on `editable`
// (selectEditable). Craft-feel (R014): no spinners / icons / emoji — plain
// text + `disabled` is the only in-flight affordance; serif for titles,
// uppercase sans for labels; the warm red `#8b2a1d` only for destructive.

import { useEffect, useMemo, useState } from "react";

import type {
  CostKind,
  FillProposalResponse,
  FindingResponse,
  FindingSeverity,
  NodeType,
  Price,
} from "@ov-black/api-client";

import {
  itineraryGraphStore,
  selectEditable,
} from "../../store/itineraryGraphStore";

const btn =
  "h-8 rounded-md border border-ink/20 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-40";

const sectionTitle =
  "font-sans text-[10px] uppercase tracking-[0.22em] text-ink/55";

// Quick kind filters for the keyword search. Flights/hotels need structured
// params (origin/dates, check-in/out) the agent chat is better at — the
// keyword box mostly drives meals/experiences (Places + OV).
const KIND_CHIPS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "meal", label: "Meals" },
  { value: "experience", label: "Experiences" },
  { value: "hotel", label: "Hotels" },
];

const SEVERITY_LABEL: Record<FindingSeverity, string> = {
  info: "Info",
  suggest: "Suggest",
  warn: "Warning",
  block: "Blocker",
};

const SEVERITY_WEIGHT: Record<FindingSeverity, number> = {
  block: 0,
  warn: 1,
  suggest: 2,
  info: 3,
};

function severityClass(sev: FindingSeverity): string {
  if (sev === "block" || sev === "warn") return "text-[#8b2a1d]";
  return "text-ink/55";
}

function formatPrice(price?: Price | null): string | null {
  if (!price) return null;
  const cur = price.currency ?? "";
  const lo = price.amount_min ?? null;
  const hi = price.amount_max ?? null;
  if (lo !== null && hi !== null && hi !== lo)
    return `${cur} ${lo}–${hi}`.trim();
  const amt = lo ?? hi;
  return amt !== null ? `${cur} ${amt}`.trim() : null;
}

// datetime-local ("YYYY-MM-DDTHH:MM") → tz-aware ISO so the gap aligns with the
// trip's local schedule rather than the browser's tz.
function localToIso(local: string, tzOffsetHours: number): string {
  if (!local) return local;
  const sign = tzOffsetHours >= 0 ? "+" : "-";
  const abs = Math.abs(tzOffsetHours);
  const offH = String(Math.floor(abs)).padStart(2, "0");
  const offM = String(Math.round((abs % 1) * 60)).padStart(2, "0");
  const withSecs = local.length === 16 ? `${local}:00` : local;
  return `${withSecs}${sign}${offH}:${offM}`;
}

type AuthoringPanelProps = {
  tzOffsetHours: number;
  /** Trip day keys (YYYY-MM-DD), used to default the Fill gap inputs. */
  days: ReadonlyArray<{ date: string }>;
};

export function AuthoringPanel({ tzOffsetHours, days }: AuthoringPanelProps) {
  const editable = itineraryGraphStore.useStore(selectEditable);
  const storeApi = itineraryGraphStore.useStoreApi();

  // ── inventory search ──
  const inventoryResults = itineraryGraphStore.useStore(
    (s) => s.inventoryResults,
  );
  const inventoryPending = itineraryGraphStore.useStore(
    (s) => s.inventoryPending,
  );
  const inventoryError = itineraryGraphStore.useStore((s) => s.inventoryError);
  const addingInventoryId = itineraryGraphStore.useStore(
    (s) => s.addingInventoryId,
  );

  // ── analyze ──
  const analyzeStatus = itineraryGraphStore.useStore((s) => s.analyzeStatus);
  const analyzePending = itineraryGraphStore.useStore((s) => s.analyzePending);
  const findings = itineraryGraphStore.useStore((s) => s.findings);
  const analyzeSummary = itineraryGraphStore.useStore((s) => s.analyzeSummary);

  // ── fill ──
  const fillProposals = itineraryGraphStore.useStore((s) => s.fillProposals);
  const fillPending = itineraryGraphStore.useStore((s) => s.fillPending);

  const [keyword, setKeyword] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const firstDay = days[0]?.date ?? "";
  const [gapStart, setGapStart] = useState(
    firstDay ? `${firstDay}T09:00` : "",
  );
  const [gapEnd, setGapEnd] = useState(firstDay ? `${firstDay}T13:00` : "");

  // Poll the analysis while it's in flight; stop as soon as it's terminal.
  useEffect(() => {
    if (analyzeStatus !== "queued" && analyzeStatus !== "running") return;
    const id = setInterval(
      () => storeApi.getState().refreshAnalysis(),
      1500,
    );
    return () => clearInterval(id);
  }, [analyzeStatus, storeApi]);

  const sortedFindings = useMemo(
    () =>
      [...findings].sort(
        (a, b) => SEVERITY_WEIGHT[a.severity] - SEVERITY_WEIGHT[b.severity],
      ),
    [findings],
  );

  const analyzing = analyzeStatus === "queued" || analyzeStatus === "running";

  const toggleKind = (value: string) =>
    setKinds((cur) =>
      cur.includes(value)
        ? cur.filter((k) => k !== value)
        : [...cur, value],
    );

  const onSearch = () => {
    storeApi.getState().runInventorySearch({
      ...(keyword.trim() ? { keyword: keyword.trim() } : {}),
      ...(kinds.length > 0 ? { kinds } : {}),
      limit: 20,
    });
  };

  const onFill = () => {
    if (!gapStart || !gapEnd) return;
    storeApi.getState().runFill({
      start: localToIso(gapStart, tzOffsetHours),
      end: localToIso(gapEnd, tzOffsetHours),
    });
  };

  return (
    <div
      data-testid="itinerary-graph-authoring"
      className="flex h-full flex-col gap-6 overflow-y-auto bg-paper/70 px-4 py-4"
    >
      {!editable ? (
        <p
          data-testid="itinerary-graph-authoring-locked"
          className="font-sans text-[11px] leading-relaxed text-ink/55"
        >
          Adding to the itinerary needs the edit lock — press{" "}
          <span className="uppercase tracking-[0.16em]">Edit</span> above. You
          can still search, analyze, and find options.
        </p>
      ) : null}

      {/* ── 0. Add a card (hand-author) ─────────────────────────────────── */}
      <AddCardEditor editable={editable} />

      {/* ── 1. Inventory search ─────────────────────────────────────────── */}
      <section data-testid="itinerary-graph-search">
        <div className={sectionTitle}>Search inventory</div>
        <div className="mt-2 flex gap-2">
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearch();
            }}
            placeholder="ramen in Kyoto, a private guide…"
            data-testid="itinerary-graph-search-input"
            className="h-8 min-w-0 flex-1 rounded-md border border-ink/15 bg-paper px-3 font-sans text-sm text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-hidden"
          />
          <button
            type="button"
            onClick={onSearch}
            disabled={inventoryPending}
            data-testid="itinerary-graph-search-run"
            className={btn}
          >
            {inventoryPending ? "Searching" : "Search"}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {KIND_CHIPS.map((chip) => {
            const on = kinds.includes(chip.value);
            return (
              <button
                key={chip.value}
                type="button"
                onClick={() => toggleKind(chip.value)}
                className={`rounded-full border px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.14em] transition-colors ${
                  on
                    ? "border-ink/40 bg-ink/10 text-ink"
                    : "border-ink/15 text-ink/55 hover:bg-ink/5"
                }`}
              >
                {chip.label}
              </button>
            );
          })}
        </div>

        {inventoryError ? (
          <p className="mt-3 font-sans text-[11px] text-[#8b2a1d]">
            That search didn’t come back. Try again in a moment.
          </p>
        ) : null}

        <ul
          className="mt-3 flex flex-col gap-2"
          data-testid="itinerary-graph-search-results"
        >
          {inventoryResults.map((item) => {
            const price = formatPrice(item.price);
            return (
              <li
                key={`${item.source}:${item.source_id}`}
                data-testid="itinerary-graph-search-result"
                className="rounded-lg border border-ink/10 bg-paper px-3 py-2"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-serif text-[15px] leading-tight text-ink">
                    {item.title}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      storeApi
                        .getState()
                        .addNodeFromInventory(item.source, item.source_id)
                    }
                    disabled={!editable || addingInventoryId === item.source_id}
                    data-testid="itinerary-graph-search-add"
                    className="h-7 shrink-0 rounded-md border border-ink/20 bg-paper px-2.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-40"
                  >
                    {addingInventoryId === item.source_id ? "Adding" : "Add"}
                  </button>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
                  <span>{item.kind ?? "item"}</span>
                  <span>·</span>
                  <span>{item.source}</span>
                  {price ? (
                    <>
                      <span>·</span>
                      <span className="text-ink/70">{price}</span>
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {/* ── 2. Analyze ──────────────────────────────────────────────────── */}
      <section data-testid="itinerary-graph-analyze">
        <div className="flex items-center justify-between gap-2">
          <span className={sectionTitle}>Analyze feasibility</span>
          <button
            type="button"
            onClick={() => storeApi.getState().startAnalyze()}
            disabled={analyzePending || analyzing}
            data-testid="itinerary-graph-analyze-run"
            className={btn}
          >
            {analyzing ? "Analyzing" : "Analyze"}
          </button>
        </div>

        {analyzeStatus === "failed" ? (
          <p className="mt-2 font-sans text-[11px] text-[#8b2a1d]">
            The analysis didn’t complete. Try running it again.
          </p>
        ) : null}

        {analyzeStatus === "completed" ? (
          <p
            data-testid="itinerary-graph-analyze-summary"
            className="mt-2 font-sans text-[11px] leading-relaxed text-ink/60"
          >
            {analyzeSummary ?? "No issues found."}
          </p>
        ) : null}

        <ul
          className="mt-2 flex flex-col gap-2"
          data-testid="itinerary-graph-findings"
        >
          {sortedFindings.map((f: FindingResponse) => (
            <li
              key={f.id}
              data-testid="itinerary-graph-finding"
              data-severity={f.severity}
              className="rounded-lg border border-ink/10 bg-paper px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`font-sans text-[10px] uppercase tracking-[0.18em] ${severityClass(
                    f.severity,
                  )}`}
                >
                  {SEVERITY_LABEL[f.severity]}
                </span>
                <span className="font-sans text-[10px] uppercase tracking-[0.14em] text-ink/40">
                  {f.category}
                </span>
              </div>
              <p className="mt-1 font-serif text-[14px] leading-snug text-ink">
                {f.message}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* ── 3. Fill a gap ───────────────────────────────────────────────── */}
      <section data-testid="itinerary-graph-fill">
        <div className={sectionTitle}>Fill a gap</div>
        <div className="mt-2 flex flex-col gap-2">
          <label className="flex items-center justify-between gap-2">
            <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50">
              From
            </span>
            <input
              type="datetime-local"
              value={gapStart}
              onChange={(e) => setGapStart(e.target.value)}
              data-testid="itinerary-graph-fill-start"
              className="h-8 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50">
              Until
            </span>
            <input
              type="datetime-local"
              value={gapEnd}
              onChange={(e) => setGapEnd(e.target.value)}
              data-testid="itinerary-graph-fill-end"
              className="h-8 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
            />
          </label>
          <button
            type="button"
            onClick={onFill}
            disabled={fillPending || !gapStart || !gapEnd}
            data-testid="itinerary-graph-fill-run"
            className={`${btn} self-start`}
          >
            {fillPending ? "Finding options" : "Find options"}
          </button>
        </div>

        <ul
          className="mt-3 flex flex-col gap-2"
          data-testid="itinerary-graph-fill-proposals"
        >
          {fillProposals.map((p: FillProposalResponse) => (
            <li
              key={`${p.inventory_source}:${p.inventory_id}`}
              data-testid="itinerary-graph-fill-proposal"
              className="rounded-lg border border-ink/10 bg-paper px-3 py-2"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-serif text-[15px] leading-tight text-ink">
                  {p.title}
                </span>
                <span className="shrink-0 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
                  {p.type}
                </span>
              </div>
              <p className="mt-1 font-sans text-[11px] leading-relaxed text-ink/60">
                {p.rationale}
              </p>
              <div className="mt-1 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/40">
                {p.feasibility_unknown
                  ? "Feasibility unconfirmed"
                  : p.fits_in_gap
                    ? "Fits the window"
                    : "Tight fit"}
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => storeApi.getState().acceptFillProposal(p)}
                  disabled={!editable || addingInventoryId === p.inventory_id}
                  data-testid="itinerary-graph-fill-accept"
                  className="h-7 rounded-md border border-ink/20 bg-paper px-2.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-40"
                >
                  {addingInventoryId === p.inventory_id ? "Adding" : "Accept"}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    storeApi.getState().dismissFillProposal(p.inventory_id)
                  }
                  data-testid="itinerary-graph-fill-dismiss"
                  className="h-7 rounded-md border border-ink/15 bg-paper px-2.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5"
                >
                  Dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

// ── Add a card: hand-author a node (ADV-4 / G-NODE-EDITOR) ───────────────────
// The advisor's editor for a bespoke card the inventory providers don't carry.
// Two shapes, mapped 1:1 to the two create endpoints the store already wraps:
//   • Details — choose a type, name it, optionally price it → POST /nodes
//     (status `proposed`, cost amount + currency + per-person|total kind).
//   • Link    — paste a URL; the server fetches its OpenGraph preview into a
//     proposed card → POST /nodes/from-link.
// Writes need the edit lock, so submit gates on `editable` exactly like the
// inventory "Add" button. Craft-feel: plain text + `disabled`, no spinners.

const NODE_TYPE_OPTIONS: ReadonlyArray<{ value: NodeType; label: string }> = [
  { value: "experience", label: "Experience" },
  { value: "meal", label: "Meal" },
  { value: "hotel", label: "Hotel" },
  { value: "destination", label: "Destination" },
  { value: "transit", label: "Transit" },
  { value: "note", label: "Note" },
];

const CURRENCY_OPTIONS = ["USD", "EUR", "GBP", "JPY", "CHF"] as const;

const COST_KIND_OPTIONS: ReadonlyArray<{ value: CostKind; label: string }> = [
  { value: "total", label: "Total" },
  { value: "per_person", label: "Per person" },
];

const addField =
  "h-8 w-full min-w-0 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-hidden";

const addLabel =
  "w-12 shrink-0 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45";

function AddCardEditor({ editable }: { editable: boolean }) {
  const storeApi = itineraryGraphStore.useStoreApi();
  const savingLink = itineraryGraphStore.useStore((s) => s.savingLink);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"details" | "link">("details");
  const [type, setType] = useState<NodeType>("experience");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<string>("USD");
  const [costKind, setCostKind] = useState<CostKind>("total");

  const ready = mode === "details" ? title.trim() !== "" : url.trim() !== "";
  const canSubmit = editable && ready && !savingLink;

  const submit = () => {
    if (!canSubmit) return;
    if (mode === "link") {
      const trimmedNote = note.trim();
      storeApi.getState().authorNode({
        type,
        url: url.trim(),
        ...(trimmedNote ? { note: trimmedNote } : {}),
      });
    } else {
      storeApi.getState().authorNode({
        type,
        title: title.trim(),
        cost:
          amount.trim() !== ""
            ? { amount: amount.trim(), currency, kind: costKind }
            : null,
      });
    }
    setTitle("");
    setUrl("");
    setNote("");
    setAmount("");
    setOpen(false);
  };

  return (
    <section data-testid="itinerary-graph-add-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid="add-card-toggle"
        className={`${btn} w-full justify-center`}
      >
        {open ? "Close" : "Add a card"}
      </button>

      {open ? (
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-ink/15 bg-paper/80 p-3">
          <div className="flex gap-1 rounded-md border border-ink/15 bg-paper p-0.5">
            {(["details", "link"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                data-testid={`add-card-mode-${m}`}
                className={`h-6 flex-1 rounded px-2 font-sans text-[10px] uppercase tracking-[0.16em] transition-colors ${
                  mode === m
                    ? "bg-ink/10 text-ink"
                    : "text-ink/50 hover:bg-ink/5"
                }`}
              >
                {m === "details" ? "Details" : "Link"}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-2">
            <span className={addLabel}>Type</span>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as NodeType)}
              data-testid="add-card-type"
              className={addField}
            >
              {NODE_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          {mode === "details" ? (
            <>
              <label className="flex items-center gap-2">
                <span className={addLabel}>Name</span>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submit();
                  }}
                  placeholder="Private sushi omakase…"
                  data-testid="add-card-title"
                  className={addField}
                />
              </label>
              <label className="flex items-center gap-2">
                <span className={addLabel}>Price</span>
                <div className="flex min-w-0 flex-1 gap-2">
                  <input
                    type="text"
                    inputMode="decimal"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="Amount"
                    data-testid="add-card-amount"
                    className={addField}
                  />
                  <select
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                    data-testid="add-card-currency"
                    className={`${addField} w-20`}
                  >
                    {CURRENCY_OPTIONS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <select
                    value={costKind}
                    onChange={(e) => setCostKind(e.target.value as CostKind)}
                    data-testid="add-card-kind"
                    className={`${addField} w-28`}
                  >
                    {COST_KIND_OPTIONS.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </div>
              </label>
            </>
          ) : (
            <>
              <label className="flex items-center gap-2">
                <span className={addLabel}>Link</span>
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submit();
                  }}
                  placeholder="Paste a restaurant, hotel, or article…"
                  data-testid="add-card-link"
                  className={addField}
                />
              </label>
              <label className="flex items-center gap-2">
                <span className={addLabel}>Note</span>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Why it's a fit (optional)"
                  data-testid="add-card-note"
                  className={addField}
                />
              </label>
            </>
          )}

          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            data-testid="add-card-submit"
            className={btn}
          >
            {savingLink ? "Adding…" : "Add to board"}
          </button>
          {!editable ? (
            <p className="font-sans text-[10px] leading-relaxed text-ink/50">
              Press <span className="uppercase tracking-[0.16em]">Edit</span>{" "}
              above to add cards.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
