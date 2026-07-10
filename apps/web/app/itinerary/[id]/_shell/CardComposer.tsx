"use client";

// The advisor card composer (ADV-4) — a summonable overlay for hand-authoring a
// bespoke node the inventory providers don't carry. Two shapes: **Details**
// (type + name + price → POST /nodes) and **Link** (paste a URL → OpenGraph
// preview via POST /nodes/from-link). A live card preview renders the real
// board card (CardShell + CardBody) from the in-progress form, so the advisor
// sees the result as they type.
//
// Placement is set by where it was summoned (ComposerControl.openComposer):
// with a `prefill` (day + minute) the typed card lands scheduled on the timeline
// at that slot; without one it lands in the (unscheduled) Collection. Advisor-
// only placement is a later slice (needs a node audience column + read filter).

import { useEffect, useMemo, useState } from "react";

import type { CostKind, NodeType } from "@ov-black/api-client";

import { CardBody, inferCardKind, statusToKind } from "@/app/_components/itinerary-graph/shared/cards/CardBody";
import { CardShell } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import type { NodeResponse } from "@/app/_components/itinerary-graph/model/horizontalTypes";
import {
  itineraryGraphStore,
  selectEditable,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { FillSection } from "@/app/_components/itinerary-graph/views/horizontal/authoring/FillSection";
import { SearchSection } from "@/app/_components/itinerary-graph/views/horizontal/authoring/SearchSection";

import type { ComposerPrefill } from "./ComposerControl";

// The four ways to get a card onto the board (M006 harmonization). Details/Link
// hand-author; Find searches live inventory; Fill ranks candidates for a gap.
type ComposerMode = "details" | "link" | "find" | "fill";
const MODE_LABEL: Record<ComposerMode, string> = {
  details: "Details",
  link: "Link",
  find: "Find",
  fill: "Fill",
};

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

const field =
  "h-9 w-full min-w-0 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[13px] text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-hidden";
const label = "font-sans text-[10px] uppercase tracking-[0.18em] text-ink/50";

// A prefill slot (day + minute-of-day) ⇄ an <input type="datetime-local"> value
// ("YYYY-MM-DDTHH:MM"), so the advisor can nudge the scheduled time in the modal.
function slotToLocal(dayKey: string, minute: number): string {
  const hh = String(Math.floor(minute / 60)).padStart(2, "0");
  const mm = String(minute % 60).padStart(2, "0");
  return `${dayKey}T${hh}:${mm}`;
}

function localToSlot(local: string): { dayKey: string; minute: number } | null {
  const [dayKey, time] = local.split("T");
  if (!dayKey || !time) return null;
  const [h, m] = time.split(":");
  const minute = Number(h) * 60 + Number(m);
  if (!Number.isFinite(minute)) return null;
  return { dayKey, minute };
}

export function CardComposer({
  prefill,
  onClose,
}: {
  prefill: ComposerPrefill;
  onClose: () => void;
}) {
  const editable = itineraryGraphStore.useStore(selectEditable);
  const savingLink = itineraryGraphStore.useStore((s) => s.savingLink);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const storeApi = itineraryGraphStore.useStoreApi();
  // Find/Fill source the trip's timezone + day scaffold from the server-fresh
  // timeline (the composer is inside TimelineDataProvider).
  const { timeline } = useTimelineData();

  const scheduled = prefill != null;
  const [mode, setMode] = useState<ComposerMode>("details");
  const [type, setType] = useState<NodeType>("experience");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<string>("USD");
  const [costKind, setCostKind] = useState<CostKind>("total");
  // The clicked slot is a starting point, not a lock — seed an editable
  // datetime-local so the advisor can adjust the day/time before adding.
  const [scheduleLocal, setScheduleLocal] = useState(
    prefill ? slotToLocal(prefill.dayKey, prefill.minute) : "",
  );

  // Esc closes the overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pricedAmount = amount.trim();
  const priceCells = useMemo(
    () =>
      mode === "details" && pricedAmount !== ""
        ? {
            cost_amount: pricedAmount,
            cost_currency: currency,
            cost_kind: costKind,
          }
        : null,
    [mode, pricedAmount, currency, costKind],
  );

  // Live preview: a synthetic node mirroring the in-progress form, rendered
  // through the same CardShell + CardBody the board uses.
  const draft = useMemo<NodeResponse>(() => {
    const trimmedTitle = title.trim();
    const trimmedUrl = url.trim();
    return {
      id: "draft-preview",
      itinerary_id: itineraryId,
      parent_subgraph_id: null,
      type,
      status: "pending",
      title:
        mode === "link"
          ? trimmedUrl || "Pasted link"
          : trimmedTitle || "New card",
      source: mode === "link" ? "web" : null,
      source_id: mode === "link" ? trimmedUrl || null : null,
      metadata: {},
      ...(priceCells ?? {}),
    };
  }, [itineraryId, mode, type, title, url, priceCells]);

  // Only the typed Details path honors the slot; Link/Find/Fill each add per
  // their own semantics (into the Collection). The editable field shows for
  // Details when summoned from a slot; clearing it drops the card to the
  // Collection, so `willSchedule` gates the chrome (chip → "Add to timeline").
  const editedSchedule = useMemo(
    () => (scheduleLocal ? localToSlot(scheduleLocal) : null),
    [scheduleLocal],
  );
  const showScheduleField = scheduled && mode === "details";
  const willSchedule = mode === "details" && editedSchedule != null;
  // Keep the picker within the trip's span so a nudge can't strand the card on a
  // day with no column.
  const dayDates = timeline.days.map((d) => d.date);
  const minDay = dayDates[0];
  const maxDay = dayDates[dayDates.length - 1];

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
          pricedAmount !== ""
            ? { amount: pricedAmount, currency, kind: costKind }
            : null,
        ...(editedSchedule ? { schedule: editedSchedule } : {}),
      });
    }
    onClose();
  };

  const kind = inferCardKind(draft);

  return (
    <div
      data-testid="card-composer"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close composer"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
      />

      <div
        role="dialog"
        aria-label="Add a card"
        className={`relative z-10 flex max-h-[90vh] w-full flex-col overflow-hidden rounded-xl border border-ink/10 bg-paper shadow-2xl ${
          mode === "find" || mode === "fill" ? "max-w-3xl" : "max-w-2xl"
        }`}
      >
        <header className="flex items-center justify-between border-b border-ink/10 px-5 py-4">
          <div className="flex flex-col gap-1">
            <h2 className="font-serif text-xl text-ink">Add a card</h2>
            {showScheduleField ? (
              <label
                data-testid="composer-schedule"
                className="flex items-center gap-2"
              >
                <span className="font-sans text-[11px] text-ink/55">
                  Scheduling for
                </span>
                <input
                  type="datetime-local"
                  value={scheduleLocal}
                  onChange={(e) => setScheduleLocal(e.target.value)}
                  data-testid="composer-schedule-input"
                  className="h-7 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
                  {...(minDay ? { min: `${minDay}T00:00` } : {})}
                  {...(maxDay ? { max: `${maxDay}T23:59` } : {})}
                />
              </label>
            ) : (
              <p className="font-sans text-[11px] text-ink/50">
                {mode === "find"
                  ? "Search live inventory — add a result to the Collection."
                  : mode === "fill"
                    ? "Find candidates for a gap — accept one onto the timeline."
                    : "Lands in the Collection — schedule it later."}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="composer-close"
            className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/50 transition-colors hover:text-ink"
          >
            Close
          </button>
        </header>

        {/* Mode switch — the four ways to get a card on the board. Shown in every
            entry path (including a timeline-slot tap); only Details honors the
            slot, so the header/label adapt via `willSchedule`. */}
        <div className="flex gap-1 border-b border-ink/10 px-5 pt-3">
          {(["details", "link", "find", "fill"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              data-testid={`composer-mode-${m}`}
              className={`h-8 rounded-t-md px-3 font-sans text-[11px] uppercase tracking-[0.16em] transition-colors ${
                mode === m ? "bg-ink/10 text-ink" : "text-ink/50 hover:bg-ink/5"
              }`}
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>

        {mode === "find" || mode === "fill" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {mode === "find" ? (
              <SearchSection heading={false} />
            ) : (
              <FillSection
                heading={false}
                tzOffsetHours={timeline.timezoneOffsetHours}
                days={timeline.days}
              />
            )}
          </div>
        ) : (
        <div className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-5 sm:grid-cols-[1fr_16rem]">
          {/* ── Form ── */}
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className={label}>Type</span>
              <select
                value={type}
                onChange={(e) => setType(e.target.value as NodeType)}
                data-testid="composer-type"
                className={field}
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
                <label className="flex flex-col gap-1">
                  <span className={label}>Name</span>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") submit();
                    }}
                    placeholder="Private sushi omakase…"
                    data-testid="composer-title"
                    className={field}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className={label}>Price (optional)</span>
                  <div className="flex min-w-0 gap-2">
                    <input
                      type="text"
                      inputMode="decimal"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder="Amount"
                      data-testid="composer-amount"
                      className={field}
                    />
                    <select
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                      data-testid="composer-currency"
                      className={`${field} w-20`}
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
                      data-testid="composer-kind"
                      className={`${field} w-28`}
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
                <label className="flex flex-col gap-1">
                  <span className={label}>Link</span>
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") submit();
                    }}
                    placeholder="Paste a restaurant, hotel, or article…"
                    data-testid="composer-link"
                    className={field}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className={label}>Note (optional)</span>
                  <input
                    type="text"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Why it's a fit"
                    data-testid="composer-note"
                    className={field}
                  />
                </label>
              </>
            )}
          </div>

          {/* ── Live preview ── */}
          <div className="flex flex-col gap-2">
            <span className={label}>Preview</span>
            <div
              data-testid="composer-preview"
              className="rounded-lg bg-ink/[0.03] p-3"
            >
              <CardShell kind={kind} status="pending" width="glance" lockLabel={type}>
                <CardBody node={draft} kind={kind} tzOffsetHours={0} />
              </CardShell>
              {priceCells ? (
                <p
                  data-testid="composer-preview-price"
                  className="mt-2 text-center font-sans text-[11px] text-ink/70"
                >
                  {currency} {pricedAmount} ·{" "}
                  {costKind === "per_person" ? "per person" : "total"}
                </p>
              ) : null}
            </div>
          </div>
        </div>
        )}

        {/* Footer carries the single-submit for the authoring modes; Find/Fill
            self-add via each candidate's own Add/Accept, so it only shows there
            to explain a disabled action when the lock isn't held. */}
        {mode === "details" || mode === "link" || !editable ? (
        <footer className="flex items-center justify-end gap-3 border-t border-ink/10 px-5 py-4">
          {!editable ? (
            <p className="mr-auto font-sans text-[11px] text-ink/50">
              Press <span className="uppercase tracking-[0.16em]">Edit</span> on
              the Timeline to add cards.
            </p>
          ) : null}
          {mode === "details" || mode === "link" ? (
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            data-testid="composer-submit"
            className="h-9 rounded-md border border-ink/20 bg-ink px-4 font-sans text-[12px] uppercase tracking-[0.16em] text-paper transition-colors hover:bg-ink/90 disabled:cursor-default disabled:opacity-40"
          >
            {savingLink
              ? "Adding…"
              : willSchedule
                ? "Add to timeline"
                : "Add to Collection"}
          </button>
          ) : null}
        </footer>
        ) : null}
      </div>
    </div>
  );
}
