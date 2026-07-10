"use client";

// The trip-timing controls (0033), extracted from ItineraryIntake so the
// Journal hero's timing POPOVER (phase 2 edit-in-place) and the first-run
// intake share one set of controls + one save payload. Timing spans exact
// dates → a fuzzy-but-bounded window (~a week in summer) → fully flexible.
// Pure-controlled: the caller owns the TimingValue state.

import type {
  ItineraryTimingKind,
  UpdateItineraryRequest,
} from "@ov-black/api-client";

/** The controls' draft state — strings, exactly as the inputs hold them. */
export type TimingValue = {
  kind: ItineraryTimingKind;
  /** ISO date (YYYY-MM-DD) or "" when unset. */
  dateStart: string;
  dateEnd: string;
  /** Nights as typed ("" when unset) — parsed only at save. */
  durationNights: string;
};

export function timingValueFrom(initial?: {
  timingKind?: ItineraryTimingKind | null | undefined;
  dateStart?: string | null | undefined;
  dateEnd?: string | null | undefined;
  durationNights?: number | null | undefined;
}): TimingValue {
  return {
    kind: initial?.timingKind ?? "window",
    dateStart: initial?.dateStart ?? "",
    dateEnd: initial?.dateEnd ?? "",
    durationNights:
      initial?.durationNights != null ? String(initial.durationNights) : "",
  };
}

export function timingDatesReversed(v: TimingValue): boolean {
  return (
    v.kind !== "flexible" &&
    v.dateStart !== "" &&
    v.dateEnd !== "" &&
    v.dateEnd < v.dateStart
  );
}

/**
 * The timing part of a PATCH /itinerary/{id} body. Send only the fields this
 * mode owns, and explicit nulls to clear the others — so saving in a different
 * mode doesn't leave stale dates behind (the intake's original semantics).
 */
export function timingPatch(
  v: TimingValue,
  note: string,
): Pick<
  UpdateItineraryRequest,
  "timing_kind" | "timing_note" | "date_start" | "date_end" | "duration_nights"
> {
  return {
    timing_kind: v.kind,
    timing_note: note.trim() === "" ? null : note.trim(),
    date_start: v.kind === "flexible" ? null : v.dateStart === "" ? null : v.dateStart,
    date_end: v.kind === "flexible" ? null : v.dateEnd === "" ? null : v.dateEnd,
    duration_nights:
      v.kind === "window" && v.durationNights.trim() !== ""
        ? Number(v.durationNights)
        : null,
  };
}

const TIMING_MODES: ReadonlyArray<{
  id: ItineraryTimingKind;
  label: string;
  hint: string;
}> = [
  { id: "exact", label: "Exact dates", hint: "You know the days." },
  { id: "window", label: "A rough window", hint: "Roughly when, for about so long." },
  { id: "flexible", label: "Flexible", hint: "No dates yet — just constraints." },
];

export function TimingFields({
  value,
  onChange,
}: {
  value: TimingValue;
  onChange: (next: TimingValue) => void;
}) {
  const reversed = timingDatesReversed(value);
  return (
    <div className="space-y-3" data-testid="timing-fields">
      <div className="flex flex-wrap gap-2">
        {TIMING_MODES.map((m) => {
          const active = value.kind === m.id;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => onChange({ ...value, kind: m.id })}
              aria-pressed={active}
              data-testid={`timing-mode-${m.id}`}
              className={
                "rounded-full border px-4 py-1.5 font-sans text-sm transition " +
                (active
                  ? "border-brand bg-brand/10 text-ink"
                  : "border-ink/15 text-ink/60 hover:border-ink/40 hover:text-ink")
              }
            >
              {m.label}
            </button>
          );
        })}
      </div>
      <p className="font-sans text-xs text-ink/45">
        {TIMING_MODES.find((m) => m.id === value.kind)?.hint}
      </p>

      {value.kind !== "flexible" ? (
        <div className="flex flex-wrap items-end gap-4 pt-1">
          <label className="flex flex-col gap-1">
            <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
              {value.kind === "window" ? "No earlier than" : "Start"}
            </span>
            <input
              type="date"
              value={value.dateStart}
              onChange={(e) => onChange({ ...value, dateStart: e.target.value })}
              data-testid="timing-date-start"
              className="rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
              {value.kind === "window" ? "No later than" : "End"}
            </span>
            <input
              type="date"
              value={value.dateEnd}
              onChange={(e) => onChange({ ...value, dateEnd: e.target.value })}
              data-testid="timing-date-end"
              className="rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
            />
          </label>
          {value.kind === "window" ? (
            <label className="flex flex-col gap-1">
              <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
                About how many nights
              </span>
              <input
                type="number"
                min={1}
                max={365}
                value={value.durationNights}
                onChange={(e) =>
                  onChange({ ...value, durationNights: e.target.value })
                }
                placeholder="7"
                data-testid="timing-nights"
                className="w-28 rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink placeholder:text-ink/30 focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
              />
            </label>
          ) : null}
        </div>
      ) : null}
      {reversed ? (
        <p className="font-sans text-xs text-brand">
          The end can’t be before the start.
        </p>
      ) : null}
    </div>
  );
}
